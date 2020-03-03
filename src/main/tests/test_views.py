from django.test import TestCase
from unittest.mock import patch


class TestViews(TestCase):
    def test_call_index_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "main/index.html")

    def test_call_test_loads(self):
        with patch.dict(
            "os.environ",
            {"MLBENCH_MAX_WORKERS": "1", "MLBENCH_WORKER_MAX_CPU": "10000m"},
        ):
            response = self.client.get("/runs")
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "main/runs.html")
