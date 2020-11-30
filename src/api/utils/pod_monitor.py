import json
import logging
import os
import urllib
from datetime import datetime

import pytz
from django.db import transaction
from django.db.models import Max
from django_rq import job
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pid import PidFile, PidFileError

from api.models.kubemetric import KubeMetric
from api.models.kubepod import KubePod


def _check_and_create_new_pods():
    """Checks the cluster for pods and updates DB accordingly"""
    # Get cluster config and client API
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    release_name = os.environ.get("MLBENCH_KUBE_RELEASENAME")
    ns = os.environ.get("MLBENCH_NAMESPACE")

    ret = v1.list_namespaced_pod(
        ns,
        label_selector="component=worker,app=mlbench,release={}".format(release_name),
    )
    all_pods = list(KubePod.objects.all().values_list("name"))

    if len(ret.items) == 0:
        return

    with transaction.atomic():
        for i in ret.items:
            if KubePod.objects.filter(name=i.metadata.name).count() == 0:
                ip = i.status.pod_ip
                if ip is None:
                    ip = ""

                pod = KubePod(
                    name=i.metadata.name,
                    labels=i.metadata.labels,
                    phase=i.status.phase,
                    ip=ip,
                    node_name=i.spec.node_name,
                )
                pod.save()
            if i.metadata.name in all_pods:
                all_pods.remove(i.metadata.name)

    KubePod.objects.filter(name__in=all_pods).delete()


def _check_and_update_pod_phase():
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    ns = os.environ.get("MLBENCH_NAMESPACE")
    # Read all pods
    pods = KubePod.objects.all()

    for pod in pods:
        try:
            ret = v1.read_namespaced_pod(name=pod.name, namespace=ns)
        except ApiException as e:
            if e.status == 404:  # pod not found
                pod.delete()
                continue
            else:
                raise e

        phase = ret.status.phase
        node_name = ret.spec.node_name

        if phase != pod.phase:
            pod.phase = phase
            pod.save()
        if pod.node_name != node_name:
            pod.node_name = node_name
            pod.save()


@job
def check_new_pods():
    """Background task to look for new pods available in cluster.
    Creates corresponding `KubePod` objects in db.
    """
    try:
        with PidFile("new_pods") as p:
            _check_and_create_new_pods()

    except PidFileError:
        return


@job
def check_pod_status():
    """Background Task to update status/phase of known pods"""
    try:
        with PidFile("pod_status") as p:
            _check_and_update_pod_phase()

    except PidFileError:
        return


def _update_pod_metric(pod, cont_data, metric_name, value_name, value_denom):
    newest_time = pod.metrics.filter(name=metric_name).aggregate(Max("date"))[
        "date__max"
    ]

    new_time = datetime.strptime(cont_data[metric_name]["time"], "%Y-%m-%dT%H:%M:%SZ")
    new_time = pytz.utc.localize(new_time)

    if (
        (not newest_time or new_time > newest_time)
        and metric_name in cont_data
        and value_name in cont_data[metric_name]
    ):
        metric = KubeMetric(
            name=metric_name,
            date=cont_data[metric_name]["time"],
            value=cont_data[metric_name][value_name] / value_denom,
            metadata="",
            cumulative=False,
            pod=pod,
        )
        metric.save()


@job
def check_pod_metrics():
    """Background task to get metrics (cpu/memory etc.) of known pods"""
    logger = logging.getLogger("rq.worker")
    try:
        with PidFile("pod_metrics") as p:
            # Fetch all pods/nodes from database
            all_pods = KubePod.objects.all()
            nodes = {p.node_name for p in all_pods}
            all_pods = {p.name: p for p in all_pods}

            if len(nodes) == 0:
                return

            pods = []

            # Request stats for eac hnode
            for node in nodes:
                url = "http://{}:10255/stats/summary/".format(node)
                try:
                    with urllib.request.urlopen(url) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        pods += data["pods"]
                except Exception as e:
                    logger.error(
                        "Couldn't get performance data: {}, {}".format(url, repr(e))
                    )

            # Now iterate on all found pods
            for pod in pods:
                if pod["podRef"]["name"] not in all_pods:
                    continue

                current_pod = all_pods[pod["podRef"]["name"]]

                if not pod["containers"] or len(pod["containers"]) == 0:
                    continue

                cont_data = pod["containers"][0]

                _update_pod_metric(
                    current_pod,
                    cont_data,
                    metric_name="cpu",
                    value_name="usageNanoCores",
                    value_denom=10 ** 9,
                )

                _update_pod_metric(
                    pod,
                    cont_data,
                    metric_name="memory",
                    value_name="usageBytes",
                    value_denom=1024 * 1024,
                )

                newest_network_time = current_pod.metrics.filter(
                    name="network_in"
                ).aggregate(Max("date"))["date__max"]

                new_time = datetime.strptime(
                    pod["network"]["time"], "%Y-%m-%dT%H:%M:%SZ"
                )
                new_time = pytz.utc.localize(new_time)

                if (
                    (not newest_network_time or new_time > newest_network_time)
                    and "network" in pod
                    and "rxBytes" in pod["network"]
                ):
                    metric = KubeMetric(
                        name="network_in",
                        date=pod["network"]["time"],
                        value=pod["network"]["rxBytes"] / (1024 * 1024),
                        metadata="",
                        cumulative=True,
                        pod=current_pod,
                    )
                    metric.save()

                    metric = KubeMetric(
                        name="network_out",
                        date=pod["network"]["time"],
                        value=pod["network"]["txBytes"] / (1024 * 1024),
                        metadata="",
                        cumulative=True,
                        pod=current_pod,
                    )
                    metric.save()
    except PidFileError:
        return
