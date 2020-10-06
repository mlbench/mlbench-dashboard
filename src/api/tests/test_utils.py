import os
import tempfile
from time import sleep
from unittest.mock import MagicMock, patch

import docker
from django.test import TestCase
from kubernetes import client, config
from pytest_kind import KindCluster

from api.models import KubePod, ModelRun
from api.utils.pod_monitor import (
    _check_and_create_new_pods,
    _check_and_update_pod_phase,
)
from api.utils.run_utils import (
    check_nodes_available_for_execution,
    create_statefulset,
    delete_service,
    delete_statefulset,
)

# Kubernetes 1.15
KIND_NODE_IMAGE = os.getenv(
    "KIND_NODE_IMAGE",
    "kindest/node:v1.15.12@sha256:d9b939055c1e852fe3d86955ee24976cab46cba518abcb8b13ba70917e6547a6",
)
WORKER_TEMPLATE = """
- role: worker
  image: {kind_node_image}
"""
KIND_CONFIG = """
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:{reg_port}"]
    endpoint = ["http://{reg_name}:{reg_port}"]
nodes:
- role: control-plane
  image: {kind_node_image}
{workers}
"""

REG_NAME = os.getenv("REG_NAME", "kind-registry")
REG_PORT = os.getenv("REG_PORT", "5000")
TEST_IMAGE = os.getenv("TEST_IMAGE", "localhost:5000/mlbench_worker:latest")

RUN_NAME = "Run{}"


class PodMonitorTests(TestCase):
    """Tests the functions in `api/utils/pod_monitor.py`"""

    @staticmethod
    def _create_mock_pods():
        """Creates 2 Mock pods and returns them

        Returns:
            MagickMock: Containing the pods in attribute `items`
        """
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

        return ret

    @staticmethod
    def _read_namespaced_pod(mock_pods):
        """Function to patch `read_namespaced_pod`

        Args:
            mock_pods (MagicMock): Current Mock pods

        Returns:
            func: Patching function for `read_namespaced_pods`
        """

        def _tmp(self, name, namespace):
            matching = [m for m in mock_pods.items if m.metadata.name == name]
            if len(matching) == 1:
                return matching[0]
            elif len(matching) > 1:
                raise ValueError("Multiple pods matching name={}".format(name))
            else:
                return None

        return _tmp

    @staticmethod
    def _check_pods_equal(original, ret_data):
        """Checks if the return data of `KubePod.objects.all()` is the same as the given Mock

        Args:
            original (MagicMock): Representing the pods
            ret_data (list[KubePod]): The pods in the DB

        Returns:
            bool: True if both are equal
        """
        original = sorted(original, key=lambda x: x.metadata.name)
        ret_data = sorted(ret_data, key=lambda x: x.name)

        equal = True
        for o, r in zip(original, ret_data):
            equal &= o.metadata.name == r.name
            equal &= o.metadata.labels == r.labels
            equal &= o.status.phase == r.phase
            equal &= o.status.pod_ip == r.ip
        return equal

    def test_kubepod_creation(self):
        """Tests the creation of KubePod in the DB when Pods are running"""

        # Patch used functions
        with patch("kubernetes.config.load_incluster_config"), patch(
            "kubernetes.client.CoreV1Api.list_namespaced_pod"
        ) as namespaced_pod:
            # Create mock pods
            ret = self._create_mock_pods()
            namespaced_pod.return_value = ret

            # Call function to add them to DB
            _check_and_create_new_pods()

            # Checks
            pods = KubePod.objects.all()
            self.assertTrue(self._check_pods_equal(ret, pods))

    def test_pod_status(self):
        with patch("kubernetes.config.load_incluster_config"), patch(
            "kubernetes.client.CoreV1Api.list_namespaced_pod"
        ) as namespaced_pod:
            # Create mock pods
            ret = self._create_mock_pods()
            namespaced_pod.return_value = ret

            # Call function to add them to DB
            _check_and_create_new_pods()

            # Change pod status to stopped
            ret.items[0].status.configure_mock(phase="Stopped")
            ret.items[1].status.configure_mock(phase="Stopped")

            # Change pod node name
            ret.items[0].spec.configure_mock(node_name="Node3")
            ret.items[1].spec.configure_mock(node_name="Node3")

            # Run checker to change in DB
            with patch(
                "kubernetes.client.CoreV1Api.read_namespaced_pod",
                new=self._read_namespaced_pod(ret),
            ):
                _check_and_update_pod_phase()

            # Test If updated
            pods = KubePod.objects.all()
            for pod in pods:
                self.assertEqual(pod.phase, "Stopped")
                self.assertEqual(pod.node_name, "Node3")

    def test_pod_metrics(self):
        # TODO: Can be cumbersome to write, but still important
        pass


class RunUtilsTests(TestCase):
    """Tests the functions in `api/utils/run_utils.py`

    Those functions are related to creation/deletion of runs
    """

    @staticmethod
    def connect_kind_to_registry():
        """Connects kind to the local registry.
        Registry must be running at http://localhost:5000 and called `kind-registry`
        """
        docker_client = docker.from_env()

        kind_network = [x for x in docker_client.networks.list() if x.name == "kind"]
        if len(kind_network) == 0:
            raise ValueError("Kind network not found")
        kind_network = kind_network[0]
        kind_network.connect(REG_NAME)

    @staticmethod
    def disconnect_kind_from_registry():
        """ Disconnect kind from running registry"""
        docker_client = docker.from_env()

        kind_network = [x for x in docker_client.networks.list() if x.name == "kind"]
        if len(kind_network) == 0:
            raise ValueError("Kind network not found")
        kind_network = kind_network[0]

        kind_network.disconnect(REG_NAME)

    @classmethod
    def setUpClass(cls):
        """ Creates a kind cluster with correct configuration to run pods"""
        # Create cluster
        cls.cluster = KindCluster("test")

        with tempfile.TemporaryDirectory() as temp_directory:
            kind_config_file_location = os.path.join(temp_directory, "kind_config.yml")

            with open(kind_config_file_location, "w") as f:
                kind_config = KIND_CONFIG.format(
                    reg_port=REG_PORT,
                    reg_name=REG_NAME,
                    workers=WORKER_TEMPLATE.format(kind_node_image=KIND_NODE_IMAGE)
                    * int(os.environ.get("MLBENCH_MAX_WORKERS", "1")),
                    kind_node_image=KIND_NODE_IMAGE,
                )
                f.write(kind_config)

            cls.cluster.create(config_file=kind_config_file_location)

        kube_config = str(cls.cluster.kubeconfig_path.absolute())
        config.load_kube_config(kube_config)
        cls.connect_kind_to_registry()
        v1 = client.CoreV1Api()

        # create service account
        v1.create_namespaced_service_account(
            os.environ.get("MLBENCH_NAMESPACE"),
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {
                    "name": "{}-mlbench-worker-sa".format(
                        os.environ.get("MLBENCH_KUBE_RELEASENAME")
                    ),
                    "generateName": "{}-mlbench-worker-sa".format(
                        os.environ.get("MLBENCH_KUBE_RELEASENAME")
                    ),
                    "namespace": os.environ.get("MLBENCH_NAMESPACE"),
                },
            },
        )

        # Create secret for service account
        v1.create_namespaced_secret(
            os.environ.get("MLBENCH_NAMESPACE"),
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "{}-ssh-key".format(os.getenv("MLBENCH_KUBE_RELEASENAME")),
                    "component": "worker",
                    "release": os.getenv("MLBENCH_KUBE_RELEASENAME"),
                },
                "type": "Opaque",
            },
        )

    @classmethod
    def tearDownClass(cls):
        """Delete KIND cluster"""
        cls.disconnect_kind_from_registry()
        cls.cluster.delete()

    def _test_create_statefulset(self):
        """Tests the creation of a stateful set"""
        run = ModelRun(
            name=RUN_NAME.format(1),
            num_workers=1,
            cpu_limit=0.1,
            image=TEST_IMAGE,
            command="sleep",
            backend="gloo",
            run_on_all_nodes=True,
            gpu_enabled=False,
            light_target=False,
        )

        # Create stateful set
        create_statefulset(
            run,
            os.getenv("MLBENCH_KUBE_RELEASENAME"),
            os.environ.get("MLBENCH_NAMESPACE"),
        )

        # Wait for creation
        sleep(10)
        # Check creation
        stateful_set_name = "{1}-mlbench-worker-{0}".format(
            os.getenv("MLBENCH_KUBE_RELEASENAME"), run.name
        ).lower()
        kube_api = client.AppsV1Api()
        stateful_sets = kube_api.list_namespaced_stateful_set(
            os.environ.get("MLBENCH_NAMESPACE")
        )

        items = stateful_sets.items
        self.assertEqual(len(items), 1)

        stateful_set = items[0]
        self.assertEqual(stateful_set.metadata.name, stateful_set_name)
        self.assertEqual(stateful_set.status.current_replicas, 1)
        self.assertEqual(stateful_set.status.ready_replicas, 1)
        self.assertEqual(stateful_set.status.replicas, 1)

        containers = stateful_set.spec.template.spec.containers
        self.assertEqual(len(containers), 1)

        container = containers[0]
        self.assertEqual(container.image, TEST_IMAGE)

        core = client.CoreV1Api()
        pods = core.list_namespaced_pod(os.environ.get("MLBENCH_NAMESPACE"))
        self.assertEqual(len(pods.items), 1)

    def _test_delete_statefulset(self):
        """Tests deletion of stateful set"""
        run_name = RUN_NAME.format(1)
        stateful_set_name = "{1}-mlbench-worker-{0}".format(
            os.getenv("MLBENCH_KUBE_RELEASENAME"), run_name
        ).lower()
        delete_statefulset(
            stateful_set_name,
            os.environ.get("MLBENCH_NAMESPACE"),
            grace_period_seconds=0,
        )
        # Wait for stateful set to delete
        sleep(30)
        kube_api = client.AppsV1Api()
        core = client.CoreV1Api()
        stateful_sets = kube_api.list_namespaced_stateful_set(
            os.environ.get("MLBENCH_NAMESPACE")
        )

        pods = core.list_namespaced_pod(os.environ.get("MLBENCH_NAMESPACE"))
        self.assertEqual(len(stateful_sets.items), 0)
        self.assertEqual(len(pods.items), 0)

    def _test_delete_service(self):
        """Tests deletion of service"""
        run_name = RUN_NAME.format(1)
        stateful_set_name = "{1}-mlbench-worker-{0}".format(
            os.getenv("MLBENCH_KUBE_RELEASENAME"), run_name
        ).lower()
        delete_service(stateful_set_name, os.environ.get("MLBENCH_NAMESPACE"))

        sleep(1)
        v1 = client.CoreV1Api()
        services = v1.list_namespaced_service(os.environ.get("MLBENCH_NAMESPACE"))
        service_names = [s.metadata.name for s in services.items]

        self.assertFalse(stateful_set_name in service_names)

    def test_statefulset_and_service(self):
        self._test_create_statefulset()
        self._test_delete_statefulset()
        self._test_delete_service()

    @patch.dict("os.environ", {"MLBENCH_MAX_WORKERS": "8"})
    def test_check_available_nodes(self):
        """Tests check available nodes"""
        total_workers = int(os.environ.get("MLBENCH_MAX_WORKERS", "1"))

        run_1 = ModelRun(
            name=RUN_NAME.format(1),
            num_workers=4,
            cpu_limit=0.1,
            image=TEST_IMAGE,
            command="sleep",
            backend="gloo",
            run_on_all_nodes=True,
            gpu_enabled=False,
            light_target=False,
        )

        run_1.state = ModelRun.STARTED
        run_1.save()

        run_2 = ModelRun(
            name=RUN_NAME.format(2),
            num_workers=4,
            cpu_limit=0.1,
            image=TEST_IMAGE,
            command="sleep",
            backend="gloo",
            run_on_all_nodes=True,
            gpu_enabled=False,
            light_target=False,
        )

        run_2.save()
        available = check_nodes_available_for_execution(run_2)
        self.assertEqual(
            available, total_workers - run_1.num_workers >= run_2.num_workers
        )

        run_3 = ModelRun(
            name=RUN_NAME.format(3),
            num_workers=1,
            cpu_limit=0.1,
            image=TEST_IMAGE,
            command="sleep",
            backend="gloo",
            run_on_all_nodes=True,
            gpu_enabled=False,
            light_target=False,
        )

        available = check_nodes_available_for_execution(run_3)
        self.assertEqual(
            available,
            total_workers - run_1.num_workers - run_2.num_workers >= run_3.num_workers,
        )
