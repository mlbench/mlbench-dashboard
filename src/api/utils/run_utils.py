import os
import traceback
from copy import deepcopy
from time import sleep

import django_rq
import kubernetes.stream as stream
import websocket
from django.utils import timezone
from kubernetes import client, config
from rq import get_current_job

from api.models import KubePod, ModelRun
from master.settings import MPI_COMMAND

MAX_POD_RETRIES = 20

service_template = client.V1Service(
    api_version="v1",
    kind="Service",
    metadata=client.V1ObjectMeta(
        name="",
        labels={
            "app": "mlbench",
            "chart": "mlbench-2.0.0",
            "component": "worker",
            "release": os.environ.get("MLBENCH_KUBE_RELEASENAME"),
            "heritage": "Helm",
            "set": "",
        },
    ),
    spec=client.V1ServiceSpec(
        selector={
            "app": "mlbench",
            "release": os.environ.get("MLBENCH_KUBE_RELEASENAME"),
            "set": "",
        },
        cluster_ip="None",
        ports=[client.V1ServicePort(name="dummy", port=22)],
    ),
)

statefulset_template = client.V1StatefulSet(
    api_version="apps/v1",
    kind="StatefulSet",
    metadata=client.V1ObjectMeta(
        name="",
        labels={
            "app": "mlbench",
            "chart": "mlbench-2.0.0",
            "component": "worker",
            "release": os.environ.get("MLBENCH_KUBE_RELEASENAME"),
            "heritage": "Helm",
            "set": "",
        },
    ),
    spec=client.V1StatefulSetSpec(
        replicas=0,
        selector=client.V1LabelSelector(
            match_labels={
                "app": "mlbench",
                "release": os.environ.get("MLBENCH_KUBE_RELEASENAME"),
                "set": "",
            }
        ),
        service_name="",
        pod_management_policy="Parallel",
        update_strategy=client.V1StatefulSetUpdateStrategy(type="RollingUpdate"),
        template=client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": "mlbench",
                    "chart": "mlbench-2.0.0",
                    "component": "worker",
                    "release": os.environ.get("MLBENCH_KUBE_RELEASENAME"),
                    "heritage": "Helm",
                    "set": "",
                }
            ),
            spec=client.V1PodSpec(
                service_account_name="mlbench-worker-sa",
                affinity=client.V1Affinity(
                    pod_anti_affinity=client.V1PodAntiAffinity(
                        required_during_scheduling_ignored_during_execution=[
                            client.V1PodAffinityTerm(
                                label_selector=client.V1LabelSelector(
                                    match_expressions=[
                                        client.V1LabelSelectorRequirement(
                                            key="component",
                                            operator="In",
                                            values=["worker"],
                                        )
                                    ]
                                ),
                                topology_key="kubernetes.io/hostname",
                            )
                        ]
                    )
                ),
                containers=[
                    client.V1Container(
                        name="",
                        image="",
                        image_pull_policy="Always",
                        stdin=True,
                        tty=True,
                        ports=[
                            client.V1ContainerPort(
                                name="ssh",
                                container_port=22,
                                host_port=16166,
                                protocol="TCP",
                            )
                        ],
                        resources=client.V1ResourceRequirements(
                            limits={"cpu": "1", "nvidia.com/gpu": "0"}
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="mlbench-ssh-key", mount_path="/ssh-key/root"
                            )
                        ],
                        security_context=client.V1SecurityContext(privileged=True),
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="mlbench-ssh-key",
                        secret=client.V1SecretVolumeSource(
                            secret_name="{}-ssh-key".format(
                                os.environ.get("MLBENCH_KUBE_RELEASENAME")
                            ),
                            default_mode=256,
                        ),
                    )
                ],
            ),
        ),
    ),
)


def create_statefulset(model_run, release_name, namespace, job=None):
    """Creates a stateful set from the given run.
    The stateful set will have the name [release-name]-mlbench-worker-[model_run.name]

    Args:
        model_run (:obj:`ModelRun`): The model run with appropriate values
        release_name (str): Release name
        namespace (str): Kubernetes namespace
        job: Job to write output to

    Returns:
        (str): Name of stateful set
    """
    core = client.CoreV1Api()
    kube_api = client.AppsV1Api()

    statefulset_name = "{1}-mlbench-worker-{0}".format(
        release_name, model_run.name
    ).lower()

    # create service
    service = deepcopy(service_template)

    service.metadata.name = statefulset_name
    service.metadata.labels["set"] = model_run.name
    service.spec.selector["set"] = model_run.name

    response = core.create_namespaced_service(namespace, service)

    # create stateful set
    statefulset = deepcopy(statefulset_template)

    statefulset.metadata.name = statefulset_name
    statefulset.metadata.labels["set"] = model_run.name

    statefulset.spec.selector.match_labels["set"] = model_run.name
    statefulset.spec.service_name = statefulset_name
    statefulset.spec.replicas = int(model_run.num_workers)
    container = statefulset.spec.template.spec.containers[0]
    container.resources.limits["cpu"] = model_run.cpu_limit

    if model_run.gpu_enabled:
        container.resources.limits["nvidia.com/gpu"] = "1"

    container.image = model_run.image
    container.name = "{}-worker".format(model_run.name).lower()
    statefulset.spec.template.spec.service_account_name = "{}-mlbench-worker-sa".format(
        os.environ.get("MLBENCH_KUBE_RELEASENAME")
    )
    statefulset.spec.template.metadata.labels["set"] = model_run.name

    response = kube_api.create_namespaced_stateful_set(namespace, statefulset)

    if job is not None:
        job.meta["stdout"].append("Waiting for pods to become available\n")
        job.save()

    # wait for StatefulSet to be created
    while True:
        response = kube_api.read_namespaced_stateful_set_status(
            statefulset_name, namespace
        )
        s = response.status

        if job is not None:
            job.meta["stdout"].append(
                "Waiting for workers: Current: {}/{}, Replicas: {}/{}, "
                "Ready: {}, "
                "Observed Gen: {}/{}".format(
                    s.current_replicas,
                    response.spec.replicas,
                    s.replicas,
                    response.spec.replicas,
                    s.ready_replicas,
                    s.observed_generation,
                    response.metadata.generation,
                )
            )
            job.save()

        if (
            s.current_replicas == response.spec.replicas
            and s.replicas == response.spec.replicas
            and s.ready_replicas == response.spec.replicas
            and s.observed_generation == response.metadata.generation
        ):
            break

        sleep(1)

    return statefulset_name


def delete_statefulset(
    statefulset_name, namespace, grace_period_seconds=5, in_cluster=True
):
    """Delete a stateful set in a given namespace

    Args:
        statefulset_name (str): Stateful set to delete
        namespace (str): Namespace on which stateful set was deployed
        grace_period_seconds (int): Grace period for deletion
        in_cluster (bool): Running inside cluster or not. Default `True`
    """
    if in_cluster:
        config.load_incluster_config()
    kube_api = client.AppsV1Api()

    kube_api.delete_namespaced_stateful_set(
        statefulset_name,
        namespace,
        pretty=True,
        grace_period_seconds=grace_period_seconds,
        propagation_policy="Foreground",
    )


def delete_service(statefulset_name, namespace, in_cluster=True):
    """Deletes a service in a given namespace and stateful set

    Args:
        statefulset_name (str): Name of stateful set for service
        namespace (str): Namespace on which it was deployed
        in_cluster (bool): Running inside cluster or not. Default `True`
    """
    if in_cluster:
        config.load_incluster_config()
    kube_api = client.CoreV1Api()

    kube_api.delete_namespaced_service(
        statefulset_name,
        namespace,
        body=client.V1DeleteOptions(
            propagation_policy="Foreground",
        ),
    )


def check_nodes_available_for_execution(model_run, job=None):
    if job is not None:
        job.meta["stdout"].append("Waiting for nodes to be available\n")
        job.save()

    max_workers = int(os.environ.get("MLBENCH_MAX_WORKERS"))
    active_runs = ModelRun.objects.filter(state=ModelRun.STARTED)

    utilized_workers = sum(r.num_workers for r in active_runs)

    if utilized_workers == max_workers:
        return False

    available_workers = max_workers - utilized_workers

    pending_runs = ModelRun.objects.filter(state=ModelRun.INITIALIZED).order_by(
        "num_workers"
    )
    for r in pending_runs:
        if r.num_workers > available_workers:
            return False

        if r.id == model_run.id:
            return True

        available_workers -= r.num_workers

    return False  # this should never be reached!


@django_rq.job("default", result_ttl=-1, timeout=-1, ttl=None)
def run_model_job(model_run):
    """RQ Job to execute OpenMPI

    Arguments:
        model_run {models.ModelRun} -- the database entry this job is
                                       associated with
    """
    release_name = os.environ.get("MLBENCH_KUBE_RELEASENAME")
    ns = os.environ.get("MLBENCH_NAMESPACE")

    job = get_current_job()

    job.meta["stdout"] = []
    job.meta["stderr"] = []
    job.meta["stdout"].append("Initializing run")
    job.meta["workhorse_pid"] = os.getpid()
    job.save()

    model_run.job_id = job.id
    model_run.save()

    set_name = ""

    try:
        while not check_nodes_available_for_execution(model_run, job):
            sleep(30)

        model_run.state = ModelRun.STARTED
        model_run.save()

        config.load_incluster_config()

        v1 = client.CoreV1Api()

        set_name = create_statefulset(model_run, release_name, ns, job)

        job.meta["stdout"].append("Created stateful set, starting run.")
        job.save()

        # start run
        ret = v1.list_namespaced_pod(
            ns,
            label_selector="component=worker,app=mlbench,release={0},set={1}".format(
                release_name, model_run.name
            ),
        )

        retries = 0
        while retries < MAX_POD_RETRIES:
            if len(ret.items) == 0:
                sleep(10)
                ret = v1.list_namespaced_pod(
                    ns,
                    label_selector="component=worker,app=mlbench,release={0},set={1}".format(
                        release_name, model_run.name
                    ),
                )
                continue
            pods = []
            db_pods = []
            hosts = []
            for i in ret.items:
                pods.append(
                    (
                        i.status.pod_ip,
                        i.metadata.namespace,
                        i.metadata.name,
                        str(i.metadata.labels),
                    )
                )
                try:
                    db_pod = KubePod.objects.get(name=i.metadata.name)
                    db_pods.append(db_pod)
                    hosts.append("{}.{}".format(i.metadata.name, set_name))
                except KubePod.DoesNotExist:
                    sleep(10)
                    retries += 1
                    break  # wait for pods to be in DB

            if len(hosts) > 0:
                break

        if retries == MAX_POD_RETRIES:
            raise Exception("Couldn't find pods in db")

        model_run.pods.set(db_pods)
        model_run.save()

        job.meta["pods"] = pods
        job.meta["stdout"].append(str(hosts))
        job.save()

        # Write hostfile
        max_gpu_per_worker = int(os.environ.get("MLBENCH_MAX_GPU_PER_WORKER", 0))
        slots = max_gpu_per_worker or 1

        hosts_with_slots = []
        for host in hosts:
            for _ in range(slots):
                hosts_with_slots.append(host)

        # Use `question 22 <https://www.open-mpi.org/faq/?category=running#mpirun-hostfile`_ to add slots # noqa: E501
        exec_command = model_run.command.format(
            hosts=",".join(hosts_with_slots),
            run_id=model_run.id,
            rank=0,
            backend=model_run.backend,
        )

        # Add mpirun to run on mpi
        cmd_prepend = ""
        cmd_append = ""

        if model_run.backend == "mpi":
            cmd_prepend = MPI_COMMAND.format(hosts=",".join(hosts_with_slots))

        if model_run.gpu_enabled:
            cmd_append += " --gpu"

        if model_run.light_target:
            cmd_append += " --light"

        if model_run.use_horovod:
            cmd_append += "--horovod"

        job.meta["command"] = cmd_prepend + exec_command + cmd_append

        job.meta["master_name"] = ret.items[0].metadata.name
        job.save()

        streams = []

        for i, n in enumerate(ret.items):
            name = n.metadata.name
            cmd = (
                cmd_prepend
                + model_run.command.format(
                    hosts=",".join(hosts_with_slots),
                    run_id=model_run.id,
                    rank=i,
                    backend=model_run.backend,
                )
                + cmd_append
            ).split(" ")

            resp = stream.stream(
                v1.connect_get_namespaced_pod_exec,
                name,
                ns,
                command=cmd,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
                _request_timeout=None,
            )
            streams.append(resp)

            if not model_run.run_on_all_nodes:
                break

        job.meta["stdout"].append("Started run.")
        job.save()

        # keep writing openmpi output to job metadata
        cont = True
        while any(s.is_open() for s in streams) and cont:
            for s in streams:
                try:
                    if not s.is_open():
                        # cont = False
                        continue
                    s.update(timeout=5)
                    if s.peek_stdout(timeout=5):
                        out = s.read_stdout()
                        if "Goal Reached!" in out:
                            cont = False

                        job.meta["stdout"] += out.splitlines()
                    if s.peek_stderr(timeout=5):
                        err = s.read_stderr()
                        job.meta["stderr"] += err.splitlines()

                    job.save()
                except websocket.WebSocketConnectionClosedException:
                    # cont = False
                    job.meta["stderr"] += [
                        "Websocket exception",
                        traceback.format_exc(),
                    ]
                    continue
                except BrokenPipeError:
                    # Client closed connection prematurely
                    cont = False
                    job.meta["stderr"] += [
                        "Container closed connection " "prematurely",
                        "This could be "
                        "caused by an exception or by"
                        "training being finished",
                    ]
                    continue

        for s in streams:
            s.close()

        model_run.state = ModelRun.FINISHED
        model_run.finished_at = timezone.now()
        model_run.save()
    except (Exception, BaseException):
        model_run.state = ModelRun.FAILED
        job.meta["stderr"].append("Run failed")
        job.meta["stderr"].append(traceback.format_exc())
        job.save()
        model_run.save()
    finally:
        if set_name:
            delete_statefulset(set_name, ns)
            delete_service(set_name, ns)
