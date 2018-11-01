import django_rq
from kubernetes import client, config
import kubernetes.stream as stream
from rq import get_current_job

import os
from time import sleep
import socket
import time


def limit_resources(model_run, name, namespace, job):
    kube_api = client.AppsV1beta1Api()
    v1Api = client.CoreV1Api()

    release_name = os.environ.get('MLBENCH_KUBE_RELEASENAME')

    name = "{}-mlbench-worker".format(name)

    body = [
        {
            'op': 'replace',
            'path': '/spec/replicas',
            'value': int(model_run.num_workers)
        },
        {
            'op': 'replace',
            'path': '/spec/template/spec/containers/0/resources/limits/cpu',
            'value': model_run.cpu_limit
        },
        {
            'op': 'replace',
            'path': '/spec/template/spec/containers/0/image',
            'value': model_run.image
        },
        {
            # force redeploy even if nothing changes
            'op': 'replace',
            'path': '/spec/template/metadata/labels/date',
            'value': str(time.time())
        }
    ]

    kube_api.patch_namespaced_stateful_set(name, namespace, body)

    # wait for StatefulSet to upgrade
    while True:
        response = kube_api.read_namespaced_stateful_set_status(name,
                                                                namespace)
        s = response.status
        if (s.current_replicas == response.spec.replicas and
                s.replicas == response.spec.replicas and
                s.observed_generation >= response.metadata.generation):
            break

        job.meta['stdout'].append(
            "Waiting for workers: Current: {}/{}, Replicas: {}/{}, "
            "Observed Gen: {}/{}".format(
                s.current_replicas,
                response.spec.replicas,
                s.replicas,
                response.spec.replicas,
                s.observed_generation,
                response.metadata.generation
            ))
        job.save()

        sleep(1)

    # set network limits on all pods
    master_ip = socket.gethostbyname(socket.gethostname())
    ret = v1Api.list_namespaced_pod(
        namespace,
        label_selector="component=worker,app=mlbench,release={}"
        .format(release_name))

    threads = []
    commands = [
        # remove existing entries, if they exist
        'tc qdisc show dev eth0 | grep -q htb && tc qdisc del dev eth0 root'
        ' handle 1: htb',
        # add root class
        'tc qdisc add dev eth0 root handle 1: htb default 11',
        'tc class add dev eth0 parent 1: classid 1:1 htb rate '
        '10000mbit ceil 10000mbit',
        # add limited defaulz class
        'tc class add dev eth0 parent 1:1 classid 1:11 htb rate '
        '{0}mbit ceil {0}mbit'.format(model_run.network_bandwidth_limit),
        # add unlimited class for communication with master
        'tc class add dev eth0 parent 1:1 classid 1:12 htb rate '
        '10000mbit ceil 10000mbit',
        'tc filter add dev eth0 protocol ip parent 1:0 prio 0 u32 match ip '
        'dst {}/32 flowid 1:12'.format(master_ip)
    ]

    for i in ret.items:
        name = i.metadata.name
        exec_command = [
            '/bin/bash',
            '-c',
            ' ; '.join(commands)
        ]

        job.meta['stdout'].append(
            "Running Bandwidth Limitation: {}".format(" ".join(exec_command)))

        resp = stream.stream(v1Api.connect_get_namespaced_pod_exec, name,
                             namespace,
                             command=exec_command,
                             stderr=True, stdin=False,
                             stdout=True, tty=False,
                             _preload_content=False)
        resp.update(timeout=1)
        if resp.peek_stdout():
            out = resp.read_stdout()
            job.meta['stdout'] += out.splitlines()
        if resp.peek_stderr():
            err = resp.read_stderr()
            job.meta['stderr'] += err.splitlines()

        job.save()
        threads.append(resp)

    # wait for commands to execute
    while any(t.is_open() for t in threads):
        for resp in threads:
            resp.update(timeout=1)
            if resp.peek_stdout():
                out = resp.read_stdout()
                job.meta['stdout'] += out.splitlines()
            if resp.peek_stderr():
                err = resp.read_stderr()
                job.meta['stderr'] += err.splitlines()

        job.save()
        sleep(1)


@django_rq.job('default', result_ttl=-1, timeout=-1, ttl=-1)
def run_model_job(model_run):
    """RQ Job to execute OpenMPI

    Arguments:
        model_run {models.ModelRun} -- the database entry this job is
                                       associated with
    """

    from api.models import ModelRun, KubePod

    try:
        job = get_current_job()

        job.meta['stdout'] = []
        job.meta['stderr'] = []

        model_run.job_id = job.id
        model_run.state = ModelRun.STARTED
        model_run.save()

        config.load_incluster_config()

        v1 = client.CoreV1Api()

        release_name = os.environ.get('MLBENCH_KUBE_RELEASENAME')
        ns = os.environ.get('MLBENCH_NAMESPACE')

        limit_resources(model_run, release_name, ns, job)

        # start run
        ret = v1.list_namespaced_pod(
            ns,
            label_selector="component=worker,app=mlbench,release={}"
            .format(release_name))

        pods = []
        db_pods = []
        hosts = []
        for i in ret.items:
            pods.append((i.status.pod_ip,
                         i.metadata.namespace,
                         i.metadata.name,
                         str(i.metadata.labels)))

            db_pod = KubePod.objects.get(name=i.metadata.name)
            db_pods.append(db_pod)
            hosts.append("{}.{}".format(i.metadata.name, release_name))

        model_run.pods.set(db_pods)
        model_run.save()

        job.meta['pods'] = pods
        job.save()

        # Write hostfile
        max_gpu_per_worker = int(os.environ.get(
            'MLBENCH_MAX_GPU_PER_WORKER',
            0))
        slots = max_gpu_per_worker or 1

        hosts_with_slots = []
        for host in hosts:
            for _ in range(slots):
                hosts_with_slots.append(host)

        # Use `question 22 <https://www.open-mpi.org/faq/?category=running#mpirun-hostfile`_ to add slots # noqa: E501
        exec_command = model_run.command.format(
            hosts=','.join(hosts_with_slots),
            run_id=model_run.id)
        job.meta['command'] = exec_command

        job.meta['master_name'] = ret.items[0].metadata.name
        job.save()

        streams = []

        for i, n in enumerate(ret.items):
            name = n.metadata.name
            cmd = exec_command.format(rank=i).split(' ')

            resp = stream.stream(v1.connect_get_namespaced_pod_exec, name,
                                 ns,
                                 command=cmd,
                                 stderr=True, stdin=False,
                                 stdout=True, tty=False,
                                 _preload_content=False,
                                 _request_timeout=None)
            streams.append(resp)

            if not model_run.run_on_all_nodes:
                break

        # keep writing openmpi output to job metadata
        while any(s.is_open() for s in streams):
            for s in streams:
                if not s.is_open():
                    continue
                s.update(timeout=None)
                if s.peek_stdout():
                    out = s.read_stdout()
                    job.meta['stdout'] += out.splitlines()
                if s.peek_stderr():
                    err = s.read_stderr()
                    job.meta['stderr'] += err.splitlines()

            job.save()

        model_run.state = ModelRun.FINISHED
        model_run.save()
    except Exception as e:
        model_run.state = ModelRun.FAILED

        job.meta['stderr'].append(str(e))
        job.save()
        model_run.save()
