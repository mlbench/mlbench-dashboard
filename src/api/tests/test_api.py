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


class OdelRunTests(APITestCase):
    def test_post_job(self):
        """
        Ensure we can return a pod list
        """
        with patch('kubernetes.config.load_incluster_config'),\
                patch('kubernetes.client.CoreV1Api.list_namespaced_pod') as\
                namespaced_pod,\
                patch('api.views.stream') as stream,\
                patch('kubernetes.client.CoreV1Api'
                      '.connect_get_namespaced_pod_exec'):
            ret = MagicMock(items=[
                MagicMock(
                    metadata=MagicMock(labels=['l1', 'l2'], namespace="ns1"),
                    status=MagicMock(phase='Running', pod_ip='192.168.1.2')),
                MagicMock(
                    metadata=MagicMock(labels=['l1', 'l2'], namespace="ns1"),
                    status=MagicMock(phase='Running', pod_ip='192.168.1.2'))])

            ret.items[0].metadata.configure_mock(name='Pod1')
            ret.items[1].metadata.configure_mock(name='Pod1')

            namespaced_pod.return_value = ret

            stream.stream.return_value = "Run Successful"

            response = self.client.post('/api/runs/', format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
