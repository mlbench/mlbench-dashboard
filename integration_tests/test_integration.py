import requests
import os

from time import sleep
from kubernetes import config, client
from kubernetes.client.rest import ApiException
import json
import random
import string

DASHBOARD_URL = os.environ.get("DASHBOARD_URL")
KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT")
RELEASE_NAME = os.environ.get("RELEASE_NAME")


def get_random_name(length):
    return ''.join(random.choices(string.ascii_lowercase, k=length))


def check_pod_number(number):
    response = requests.get(os.path.join(DASHBOARD_URL, "api/pods/"))

    assert response.status_code == 200

    pods = json.loads(response.content.decode())
    assert len(pods) == number


def wait_for_pod(pod_name):
    config.load_kube_config(context=KUBE_CONTEXT)
    v1 = client.CoreV1Api()
    created = False
    while not created:
        try:
            pod = v1.read_namespaced_pod(name=pod_name, namespace="default")
            created = pod.status.phase == "Running"
        except ApiException as e:
            continue


def test_integration_1():
    # Create the run
    name = get_random_name(5)
    response = requests.post(os.path.join(DASHBOARD_URL, "api/runs/"),
                             {
                                 "num_cpus": "1.0",
                                 "name": name,
                                 "num_workers": 1,
                                 "image_name": "custom_image",
                                 "custom_image_name": "mlbench/mlbench_worker",
                                 "custom_image_command": "sleep 10",
                                 "run_all_nodes": True,
                                 "light_target": True,
                                 "gpu_enabled": "false",
                                 "backend": "gloo",
                             })
    pod_name = "{}-mlbench-worker-{}-2-0".format(name, RELEASE_NAME)

    assert response.status_code == 201  # Created
    print("created")
    # Wait for pods to come up
    wait_for_pod(pod_name)

    check_pod_number(1)

    # Check list runs
    model_run = get_modelrun(name)

    assert model_run is not None
    # Check run ID and state
    run_id = model_run['id']
    state = model_run['state']
    assert state == "started"
    assert model_run['name'] == name

    # Wait for it to finish
    while state not in ["finished", "failed"]:
        state = json.loads(requests.get(os.path.join(DASHBOARD_URL, "api/runs/{}/".format(run_id))).content.decode())[
            'state']

    assert state == "finished"
    sleep(30)
    check_pod_number(0)


def get_modelrun(name):
    model_runs = requests.get(os.path.join(DASHBOARD_URL, "api/runs/"))
    assert model_runs.status_code == 200
    model_runs = json.loads(model_runs.content.decode())
    model_run = [m for m in model_runs if m['name'] == name]

    if len(model_run) == 1:
        return model_run[0]
    return None
#
# def test_integration_2():
#     name = get_random_name(5)
#     response = requests.post(os.path.join(DASHBOARD_URL, "api/runs/"),
#                              {
#                                  "num_cpus": "1.0",
#                                  "name": name,
#                                  "num_workers": 1,
#                                  "image_name": "custom_image",
#                                  "custom_image_name": "mlbench/mlbench_worker",
#                                  "custom_image_command": "sleep 120",
#                                  "run_all_nodes": True,
#                                  "light_target": True,
#                                  "gpu_enabled": "false",
#                                  "backend": "gloo",
#                              })
#     assert response.status_code == 201  # Created
#
#     model_run = get_modelrun(name)
#     assert model_run is not None
#
#     response = requests.delete(os.path.join(DASHBOARD_URL, "api/runs/{}/".format(model_run['id'])))
#     assert response.status_code == 204
#
#     sleep(10)
#     model_run = get_modelrun(name)
#     assert model_run is None
#
#     check_pod_number(0)
#
if __name__ == "__main__":
    test_integration_1()