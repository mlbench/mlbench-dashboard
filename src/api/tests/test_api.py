import datetime as dt
from django.utils import timezone
import random
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from api.models import KubePod, KubeMetric, ModelRun


class KubePodTests(APITestCase):
    def test_get_list(self):
        """
        Ensure we can return a pod list
        """
        with patch("kubernetes.config.load_incluster_config"), patch(
            "kubernetes.client.CoreV1Api.list_namespaced_pod"
        ) as namespaced_pod:
            ret = MagicMock(
                items=[
                    MagicMock(
                        metadata=MagicMock(labels=["l1", "l2"]),
                        status=MagicMock(phase="Running", pod_ip="192.168.1.2"),
                    ),
                    MagicMock(
                        metadata=MagicMock(labels=["l1", "l2"]),
                        status=MagicMock(phase="Running", pod_ip="192.168.1.2"),
                    ),
                ]
            )

            ret.items[0].metadata.configure_mock(name="Pod1")
            ret.items[1].metadata.configure_mock(name="Pod1")

            namespaced_pod.return_value = ret

            response = self.client.get("/api/pods/", format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)


class ModelRunTests(APITestCase):
    def test_post_job(self):
        """
        Ensure we can create a `ModelRun`
        """
        with patch("api.utils.run_utils.run_model_job.delay") as delay:
            delay.return_value = None

            response = self.client.post(
                "/api/runs/",
                {
                    "num_cpus": "1.0",
                    "name": "Run1",
                    "num_workers": 1,
                    "image_name": "custom_image",
                    "custom_image_name": "mlbench/mlbench_worker",
                    "custom_image_command": "sleep",
                    "run_all_nodes": True,
                    "light_target": True,
                    "gpu_enabled": "false",
                    "backend": "MPI",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class KubeMetricTests(APITestCase):
    names = [
        "start",
        "batch_load",
        "init",
        "fwd_pass",
        "comp_loss",
        "backprop",
        "agg",
        "opt_step",
        "comp_metrics",
        "end",
    ]

    def setUp(self):
        self.run = ModelRun(
            name="TestRun",
            num_workers=3,
            cpu_limit="1000m",
            image="Testimage",
            command="Testcommand",
            backend="mpi",
            run_on_all_nodes=False,
            gpu_enabled=False,
            light_target=True,
        )
        self.run.save()

        for i in range(100):
            for j, name in enumerate(self.names):
                metric = KubeMetric(
                    name=name,
                    date=(
                        timezone.now() - dt.timedelta(seconds=(100 - i) * 10 + (10 - j))
                    ),
                    value=random.random(),
                    metadata={},
                    cumulative=False,
                    model_run=self.run,
                )
                metric.save()

    def test_get_metric(self):
        """
        Ensure we can get metrics
        """
        response = self.client.get(
            "/api/metrics/{}/?metric_type=run".format(self.run.id), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()

        for name in self.names:
            assert len(res[name]) == 100

        response = self.client.get(
            "/api/metrics/{}/?metric_type=run&summarize=10".format(self.run.id),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()

        for name in self.names:
            assert len(res[name]) == 10

        response = self.client.get(
            "/api/metrics/{}/?metric_type=run&last_n=5".format(self.run.id),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()

        for name in self.names:
            assert len(res[name]) == 5
