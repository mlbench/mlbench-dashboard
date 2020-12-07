import os
import signal
from time import sleep

import django_rq
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from rq.job import Job, JobStatus


class ModelRun(models.Model):
    INITIALIZED = "initialized"
    STARTED = "started"
    FAILED = "failed"
    FINISHED = "finished"
    MPI = "mpi"
    NCCL = "nccl"
    GLOO = "gloo"
    STATE_CHOICES = [(STARTED, STARTED), (FAILED, FAILED), (FINISHED, FINISHED)]
    BACKENDS = [(MPI, MPI), (NCCL, NCCL), (GLOO, GLOO)]

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(default=None, blank=True, null=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=INITIALIZED)
    job_id = models.CharField(max_length=38, default="")

    cpu_limit = models.CharField(max_length=20, default="12000m")
    num_workers = models.IntegerField(default=2)

    image = models.CharField(max_length=100, default="mlbench/mlbench_worker")
    command = models.CharField(max_length=1000, default="")
    backend = models.CharField(max_length=20, choices=BACKENDS, default=MPI)
    run_on_all_nodes = models.BooleanField(default=False)
    gpu_enabled = models.BooleanField(default=False)
    light_target = models.BooleanField(default=False)
    use_horovod = models.BooleanField(default=False)

    job_metadata = {}

    def start(self, run_model_job=None):
        """Saves the model run and starts the RQ job

        Args:
            run_model_job (:obj:`django_rq.job` | None): Django RQ job to start the run
        Raises:
            ValueError -- Raised if state is not initialized
        """

        if self.job_id != "" or self.state != self.INITIALIZED:
            raise ValueError("Wrong State")
        self.save()

        if run_model_job is not None:
            run_model_job.delay(self)


def _remove_run_job(sender, instance, using, **kwargs):
    """Signal to delete job when ModelRun is deleted"""
    redis_conn = django_rq.get_connection()
    job = Job.fetch(instance.job_id, redis_conn)

    if job.is_started:
        # Kill job pid
        os.kill(job.meta["workhorse_pid"], signal.SIGTERM)
        while job.get_status() not in [JobStatus.FAILED, JobStatus.FINISHED]:
            sleep(1)
    else:
        # Delete job from queue
        job.delete()


@receiver(pre_delete, sender=ModelRun, dispatch_uid="run_delete_job")
def remove_run_job(sender, instance, using, **kwargs):
    _remove_run_job(sender, instance, using, **kwargs)
