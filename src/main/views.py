import math
import os

import django_rq
from django.conf import settings
from django.shortcuts import render
from rq.job import Job

from api.models import KubePod, ModelRun


# Create your views here.
def index(request):
    return render(request, "main/index.html")


def worker(request, pod_name):
    worker = KubePod.objects.get(name=pod_name)
    metrics = worker.metrics.order_by("name").values("name").distinct()
    return render(
        request, "main/worker_detail.html", {"worker": worker, "metrics": metrics}
    )


def runs(request):
    """List all runs page"""
    runs = ModelRun.objects.all()

    max_workers = os.environ.get("MLBENCH_MAX_WORKERS")
    max_cpu = os.environ.get("MLBENCH_WORKER_MAX_CPU")

    if "m" in max_cpu:
        max_cpu = int(max_cpu.replace("m", "")) / 1000
    else:
        max_cpu = int(max_cpu)

    max_workers = int(max_workers)
    worker_ticks = [
        str(2 ** i) for i in range(0, math.floor(math.log2(max_workers)) + 1)
    ]

    return render(
        request,
        "main/runs.html",
        {
            "runs": runs,
            "max_workers": max_workers,
            "worker_ticks": ", ".join(worker_ticks),
            "worker_tick_labels": ", ".join('"{}"'.format(i) for i in worker_ticks),
            "max_cpus": max_cpu,
            "max_memory": 30000,
            "images": settings.MLBENCH_IMAGES,
            "backends": settings.MLBENCH_BACKENDS,
        },
    )


def run(request, run_id):
    """Details of single run page"""
    run = ModelRun.objects.get(pk=run_id)

    redis_conn = django_rq.get_connection()
    job = Job.fetch(run.job_id, redis_conn)

    run.job_metadata = job.meta

    metrics = run.metrics.order_by("name").values("name").distinct()

    return render(request, "main/run_detail.html", {"run": run, "metrics": metrics})
