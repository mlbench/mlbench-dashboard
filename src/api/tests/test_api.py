import json
from ast import literal_eval
from unittest.mock import MagicMock, create_autospec, patch

from rest_framework import status
from rest_framework.test import APITestCase

from api.models import ModelRun
from api.utils.pod_monitor import _check_and_create_new_pods


class KubePodTests(APITestCase):
    """Tests for class KubePodView"""

    @staticmethod
    def _decode_response(json_response):
        dict_res = json.loads(json_response.decode())
        dict_res = [
            {k: v if k != "labels" else literal_eval(v) for k, v in d.items()}
            for d in dict_res
        ]

        return dict_res

    @staticmethod
    def _check_pods_equal(original, ret_data):
        original = sorted(original.items, key=lambda x: x.metadata.name)
        ret_data = sorted(ret_data, key=lambda x: x["name"])

        equal = True
        for o, r in zip(original, ret_data):
            equal &= o.metadata.name == r["name"]
            equal &= o.metadata.labels == r["labels"]
            equal &= o.status.phase == r["phase"]
            equal &= o.status.pod_ip == r["ip"]
        return equal

    def test_list_pods(self):
        """ Tests whether the API correctly lists the current pods (KubePodeView.list)"""
        with patch("kubernetes.config.load_incluster_config"), patch(
            "kubernetes.client.CoreV1Api.list_namespaced_pod"
        ) as namespaced_pod:
            # Create mock pods
            ret = MagicMock(
                items=[
                    MagicMock(
                        metadata=MagicMock(labels=["l1", "l2"]),
                        status=MagicMock(phase="Running", pod_ip="192.168.1.2"),
                    ),
                    MagicMock(
                        metadata=MagicMock(labels=["l3", "l4"]),
                        status=MagicMock(phase="Running", pod_ip="192.168.1.3"),
                    ),
                ]
            )

            ret.items[0].spec.configure_mock(node_name="Node1")
            ret.items[1].spec.configure_mock(node_name="Node2")
            ret.items[0].metadata.configure_mock(name="Pod1")
            ret.items[1].metadata.configure_mock(name="Pod2")

            namespaced_pod.return_value = ret

            # Call function to add them to DB
            _check_and_create_new_pods()

            # Make API call & decode response
            response = self.client.get("/api/pods/", format="json")
            ret_data = self._decode_response(response.content)

            # Checks
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(ret_data), 2)
            self.assertTrue(self._check_pods_equal(ret, ret_data))


class ModelRunTests(APITestCase):
    """Tests ModelRunView class"""

    def test_create_modelrun(self):
        """Tests Job creation via API (ModelRunView.create())"""

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

            # Check if object was created in DB
            runs = ModelRun.objects.all()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].name, "Run1")
            self.assertEqual(runs[0].backend, "mpi")
            delay.assert_called_once()

            # Check response
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["name"], "Run1")
            self.assertEqual(response.data["state"], "initialized")

    def test_destroy_modelrun(self):
        with patch("api.views.delete_service", autospec=True), patch(
            "api.views.delete_statefulset", autospec=True
        ), patch("api.models.modelrun._remove_run_job", autospec=True):
            run = ModelRun(name="Run1")
            run.start()

            response = self.client.delete("/api/runs/{}/".format(run.pk))

            # Check if object was created in DB
            runs = ModelRun.objects.all()
            self.assertEqual(len(runs), 0)
