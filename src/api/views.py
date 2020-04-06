import io
import json
import os
import zipfile
from datetime import datetime
from itertools import groupby
from math import ceil

import django_rq
import pytz
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from rq.job import Job

from api.models import KubePod, KubeMetric, ModelRun
from api.serializers import KubePodSerializer, ModelRunSerializer, KubeMetricsSerializer
from api.utils.run_utils import delete_statefulset, delete_service
from api.utils.utils import secure_filename


class KubePodView(ViewSet):
    """Handles the /api/pods endpoint
    """

    serializer_class = KubePodSerializer

    def list(self, request, format=None):
        pod = KubePod.objects.all()

        serializer = KubePodSerializer(pod, many=True)
        return Response(serializer.data)


class KubeMetricsView(ViewSet):
    """Handles the /api/metrics endpoint
    """

    def __format_result(self, metrics, q, summarize, last_n):
        # get available kind of metrics
        names = metrics.values("name").distinct()

        result = {}

        for name in names:
            name = name["name"]
            temp_filter = q & Q(name=name)
            filtered_metrics = (
                metrics.filter(temp_filter)
                .order_by("date")
                .values("date", "value", "cumulative")
            )

            metric_count = filtered_metrics.count()

            if summarize and metric_count > summarize:
                factor = ceil(metric_count / summarize)

                new_metrics = []
                temp_metric = None

                count = 0

                for metric in filtered_metrics:
                    if not temp_metric:
                        temp_metric = {
                            "date": metric["date"],
                            "value": 0.0,
                            "cumulative": metric["cumulative"],
                        }
                    temp_metric["value"] += float(metric["value"])
                    count += 1

                    if count % factor == 0:
                        temp_metric["value"] = str(temp_metric["value"] / factor)
                        new_metrics.append(temp_metric)
                        temp_metric = None

                filtered_metrics = new_metrics
            result_metrics = list(filtered_metrics)

            if last_n:
                result_metrics = result_metrics[-last_n:]

            if len(result_metrics) > 0:
                result[name] = result_metrics

        return result

    def __format_zip_result(self, metrics, q, summarize, last_n, prefix, zf):
        names = metrics.values("name").distinct()

        for name in names:
            name = name["name"]
            if "TaskResult" in name:
                continue

            temp_filter = q & Q(name=name)
            filtered_metrics = (
                metrics.filter(temp_filter)
                .order_by("date")
                .values("date", "value", "cumulative")
            )

            metric_count = filtered_metrics.count()

            if summarize and metric_count > summarize:
                factor = ceil(metric_count / summarize)

                new_metrics = []
                temp_metric = None

                count = 0

                for metric in filtered_metrics:
                    if not temp_metric:
                        temp_metric = {
                            "date": metric["date"],
                            "value": 0.0,
                            "cumulative": metric["cumulative"],
                        }
                    temp_metric["value"] += float(metric["value"])
                    count += 1

                    if count % factor == 0:
                        temp_metric["value"] = str(temp_metric["value"] / factor)
                        new_metrics.append(temp_metric)
                        temp_metric = None

                filtered_metrics = new_metrics
            result_metrics = list(filtered_metrics)

            if last_n:
                result_metrics = result_metrics[-last_n:]

            if len(result_metrics) == 0:
                continue

            data = json.dumps(list(filtered_metrics), indent=4, cls=DjangoJSONEncoder)

            with io.StringIO() as metrics_file:
                metrics_file.write(data)

                zf.writestr("{}_{}.json".format(prefix, name), metrics_file.getvalue())

        return zf

    def list(self, request, format=None):
        """Get all metrics

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all metrics
        """

        pod_metrics = {
            pod.name: {
                g[0]: [
                    KubeMetricsSerializer(e).data
                    for e in sorted(g[1], key=lambda x: x.date)
                ]
                for g in groupby(
                    sorted(pod.metrics.all(), key=lambda m: m.name),
                    key=lambda m: m.name,
                )
            }
            for pod in KubePod.objects.all()
        }

        run_metrics = {
            run.name: {
                g[0]: [
                    KubeMetricsSerializer(e).data
                    for e in sorted(g[1], key=lambda x: x.date)
                ]
                for g in groupby(
                    sorted(run.metrics.all(), key=lambda m: m.name),
                    key=lambda m: m.name,
                )
            }
            for run in ModelRun.objects.all()
        }

        return Response(
            {"pod_metrics": pod_metrics, "run_metrics": run_metrics},
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, pk=None, format=None):
        """Get all metrics for a pod

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            pk {string} -- Name of the pod
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all metrics for the pod
        """
        q = Q()
        since = self.request.query_params.get("since", None)

        if since is not None:
            since = datetime.strptime(since, "%Y-%m-%dT%H:%M:%S.%fZ")
            since = pytz.utc.localize(since)
            q &= Q(date__gte=since)

        summarize = self.request.query_params.get("summarize", None)

        if summarize is not None:
            summarize = int(summarize)

        metric_filter = self.request.query_params.get("metric_filter", None)

        if metric_filter:
            q &= Q(name=metric_filter)

        last_n = self.request.query_params.get("last_n", None)

        if last_n:
            last_n = int(last_n)

        metric_type = self.request.query_params.get("metric_type", "pod")

        if metric_type == "pod":
            pod = KubePod.objects.filter(name=pk).first()
            metrics = pod.metrics
        else:
            run = ModelRun.objects.get(pk=pk)
            metrics = run.metrics

        if request.accepted_renderer.format != "zip":
            # generate json
            result = self.__format_result(metrics, q, summarize, last_n)

            return Response(result, status=status.HTTP_200_OK)

        result_file = io.BytesIO()

        with zipfile.ZipFile(
            result_file, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:

            if metric_type == "run":
                run = ModelRun.objects.get(pk=pk)
                pods = run.pods.all()

                filename = secure_filename(run.name)

                since = run.created_at
                until = run.finished_at

                q &= Q(date__gte=since)

                if until:
                    q &= Q(date__lte=until)

                zf = self.__format_zip_result(
                    metrics, q, summarize, last_n, "result", zf
                )
                try:
                    task_result = metrics.get(name="TaskResult @ 0")

                    with io.StringIO() as task_result_file:
                        task_result_file.write(task_result.value)

                        zf.writestr("official_result.txt", task_result_file.getvalue())
                except ObjectDoesNotExist:
                    pass

                for pod in pods:
                    pod_metrics = pod.metrics
                    zf = self.__format_zip_result(
                        pod_metrics, q, summarize, last_n, pod.name, zf
                    )

            else:
                zf = self.__format_zip_result(
                    metrics, q, summarize, last_n, "result", zf
                )
                pod = KubePod.objects.filter(name=pk).first()
                filename = secure_filename(pod.name)

            zf.close()

            response = Response(result_file.getvalue(), status=status.HTTP_200_OK)

            response[
                "content-disposition"
            ] = "attachment; " "filename=metrics_{}.zip".format(filename)
            return response

    def create(self, request):
        """Create a new metric

        Arguments:
            request {[Django request]} -- The request object

        Returns:
            Json -- Returns posted values
        """

        d = request.data

        metric = None

        if "pod_name" in d:
            pod = KubePod.objects.filter(name=d["pod_name"]).first()

            if pod is None:
                return Response(
                    {"status": "Not Found", "message": "Pod not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            metric = KubeMetric(
                name=d["name"],
                date=parse_datetime(d["date"]),
                value=d["value"],
                metadata=d["metadata"],
                cumulative=d["cumulative"],
                pod=pod,
            )
            metric.save()

            return Response(metric, status=status.HTTP_201_CREATED)

        elif "run_id" in d:
            run = ModelRun.objects.get(pk=d["run_id"])

            if run is None:
                return Response(
                    {"status": "Not Found", "message": "Run not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            metric = KubeMetric(
                name=d["name"],
                date=parse_datetime(d["date"]),
                value=d["value"],
                metadata=d["metadata"],
                cumulative=d["cumulative"],
                model_run=run,
            )
            metric.save()

            serializer = KubeMetricsSerializer(metric, many=False)

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        else:
            return Response(
                {
                    "status": "Bad Request",
                    "message": "Pod Name or run id have to be supplied",
                    "data": d,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class ModelRunView(ViewSet):
    """Handles Model Runs
    """

    serializer_class = ModelRunSerializer

    def list(self, request, format=None):
        """Get all runs

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all runs
        """

        runs = ModelRun.objects.all()

        serializer = ModelRunSerializer(runs, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None, format=None):
        """Get all details for a run

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            pk {string} -- Id of the run
            format {string} -- Output format to use (default: {None})

        Returns:
            Json -- Object containing all metrics for the pod
        """
        run = ModelRun.objects.get(pk=pk)

        redis_conn = django_rq.get_connection()
        job = Job.fetch(run.job_id, redis_conn)
        run.job_metadata = job.meta

        serializer = ModelRunSerializer(run, many=False)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        """ Create and start a new Model run

        Arguments:
            request {[Django request]} -- The request object

        Returns:
            Json -- Returns posted values
        """
        # TODO: lock table, otherwise there might be concurrency conflicts
        d = request.data

        image = d["image_name"]
        backend = d["backend"]
        run_all = d["run_all_nodes"] == "true"
        gpu = False

        if image == "custom_image":
            image = d["custom_image_name"]
            command = d["custom_image_command"]
            gpu = d["gpu_enabled"] == "true"
        else:
            entry = settings.MLBENCH_IMAGES[image]
            command = entry[1]
            if entry[3]:
                gpu = d["gpu_enabled"] == "true"

        cpu = "{}m".format(float(d["num_cpus"]) * 1000)

        run = ModelRun(
            name=d["name"],
            num_workers=d["num_workers"],
            cpu_limit=cpu,
            image=image,
            command=command,
            backend=backend,
            run_on_all_nodes=run_all,
            gpu_enabled=gpu,
            light_target=d["light_target"] == "true",
        )

        run.start()

        serializer = ModelRunSerializer(run, many=False)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        """Delete a run from the db

        Arguments:
            request {[Django request]} -- The request object

        Keyword Arguments:
            pk {int} -- [the id of the run] (default: {None})
        """
        run = ModelRun.objects.get(pk=pk)

        release_name = os.environ.get("MLBENCH_KUBE_RELEASENAME")
        ns = os.environ.get("MLBENCH_NAMESPACE")
        statefulset_name = "{1}-mlbench-worker-{0}".format(
            release_name, run.name
        ).lower()

        if run is not None:
            run.delete()

            try:
                delete_statefulset(statefulset_name, ns)
                delete_service(statefulset_name, ns)
            except (BaseException, Exception):
                pass

        return Response(
            {"status": "Deleted", "message": "The run was deleted"},
            status=status.HTTP_204_NO_CONTENT,
        )
