from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock


class KubePodTests(APITestCase):
    def test_get_list(self):
        """
        Ensure we can return a pod list
        """
        with patch('kubernetes.config.load_incluster_config'),\
                patch('kubernetes.client.CoreV1Api.list_namespaced_pod') as\
                namespaced_pod:
            ret = MagicMock(items=[
                MagicMock(
                    metadata=MagicMock(labels=['l1', 'l2']),
                    status=MagicMock(phase='Running', pod_ip='192.168.1.2')),
                MagicMock(
                    metadata=MagicMock(labels=['l1', 'l2']),
                    status=MagicMock(phase='Running', pod_ip='192.168.1.2'))])

            ret.items[0].metadata.configure_mock(name='Pod1')
            ret.items[1].metadata.configure_mock(name='Pod1')

            namespaced_pod.return_value = ret

            response = self.client.get('/api/pods/', format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)


class ModelRunTests(APITestCase):
    def test_post_job(self):
        """
        Ensure we can return a pod list
        """
        with patch('api.utils.run_utils.run_model_job.delay') as delay:
            delay.return_value = None

            response = self.client.post(
                '/api/runs/',
                {
                    'num_cpus': '1.0',
                    'name': 'Run1',
                    'num_workers': 1,
                    'image_name': 'custom_image',
                    'custom_image_name': 'mlbench/mlbench_worker',
                    'custom_image_command': 'sleep',
                    'custom_image_all_nodes': True},
                format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
