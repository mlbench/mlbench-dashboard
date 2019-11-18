import django_rq
from kubernetes import client, config
import kubernetes.stream as stream
from rq import get_current_job

import os
from time import sleep


def create_statefulset(model_run, name, namespace, job):
    kube_api = client.AppsV1beta1Api()

    statefulset_name = "{0}-mlbench-worker-{1}".format(name, model_run.name)

    template_name = "{}-mlbench-worker".format(name)

    statefulset = kube_api.read_namespaced_stateful_set(
        template_name, namespace)

    statefulset.metadata.name = statefulset_name
    statefulset.spec.replicas = int(model_run.num_workers)
    statefulset.spec.template.spec.containers[0].resources.limits.cpu = \
        model_run.cpu_limit
    statefulset.spec.template.spec.containers[0].image = model_run.image

    kube_api.create_namespaced_stateful_set(namespace, statefulset)

    # wait for StatefulSet to be created
    while True:
        response = kube_api.read_namespaced_stateful_set_status(
            statefulset_name, namespace)
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


def delete_statefulset(model_run, name, namespace):
    kube_api = client.AppsV1beta1Api()

    statefulset_name = "{0}-mlbench-worker-{1}".format(name, model_run.name)

    kube_api.delete_namespaced_stateful_set(statefulset_name, namespace)


def check_nodes_available_for_execution(model_run):
    from api.models import ModelRun

    max_workers = os.environ.get('MLBENCH_MAX_WORKERS')
    active_runs = ModelRun.objects.filter(state=ModelRun.STARTED)

    utilized_workers = sum(r.num_workers for r in active_runs)

    if utilized_workers == max_workers:
        return False

    available_workers = max_workers - utilized_workers

    pending_runs = ModelRun.objects.filter(
        state=ModelRun.INITIALIZED).order_by('num_workers')

    for r in pending_runs:
        if r.num_workers > available_workers:
            return False

        if r.id == model_run.id:
            return True

        available_workers -= r.num_workers

    return False  # this should never be reached!


@django_rq.job('default', result_ttl=-1, timeout=-1, ttl=-1)
def run_model_job(model_run):
    """RQ Job to execute OpenMPI

    Arguments:
        model_run {models.ModelRun} -- the database entry this job is
                                       associated with
    """

    from api.models import ModelRun, KubePod

    try:
        while not check_nodes_available_for_execution(model_run):
            sleep(30)
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

        create_statefulset(model_run, release_name, ns, job)

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
            run_id=model_run.id,
            rank=0)

        cmd_append = ''

        if model_run.gpu_enabled:
            cmd_append += ' --gpu'

        if model_run.light_target:
            cmd_append += ' --light'

        job.meta['command'] = exec_command + cmd_append

        job.meta['master_name'] = ret.items[0].metadata.name
        job.save()

        streams = []

        for i, n in enumerate(ret.items):
            name = n.metadata.name
            cmd = (model_run.command.format(
                hosts=','.join(hosts_with_slots),
                run_id=model_run.id,
                rank=i) + cmd_append).split(' ')

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
    finally:
        delete_statefulset(model_run, release_name, ns)
