import json
import os
import random
import string
from time import sleep

import requests
from kubernetes import client, config
from kubernetes.client.rest import ApiException

DASHBOARD_URL = os.environ.get("DASHBOARD_URL")
KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT")
RELEASE_NAME = os.environ.get("RELEASE_NAME")


def get_modelrun(name):
    """Returns a model run by name

    Args:
        name (str): Model Run name

    Returns:
        (dict): The model run
    """
    model_runs = requests.get(os.path.join(DASHBOARD_URL, "api/runs/"))
    assert model_runs.status_code == 200
    model_runs = json.loads(model_runs.content.decode())
    model_run = [m for m in model_runs if m["name"] == name]

    if len(model_run) == 1:
        return model_run[0]
    return None


def get_random_name(length):
    """Returns a random string of given length

    Args:
        length (int): Name length

    Returns:
        (str): Random name
    """
    return "".join(random.choices(string.ascii_lowercase, k=length))


def check_pod_number(number):
    """Checks that the number of pods returned by the API is equal to `number`

    Args:
        number (int):
    """
    response = requests.get(os.path.join(DASHBOARD_URL, "api/pods/"))

    assert response.status_code == 200

    pods = json.loads(response.content.decode())
    assert len(pods) == number


def statefulset_exists(name):
    """Checks that the given stateful set exists by using kube client

    Args:
        name (str): Statefulset name

    Returns:
        (bool): Whether the stateful set exists
    """
    config.load_kube_config(context=KUBE_CONTEXT)
    v1 = client.AppsV1Api()

    stateful_set = None
    try:
        stateful_set = v1.read_namespaced_stateful_set(name, namespace="default")
    except ApiException as e:
        pass

    return stateful_set is not None


def service_exists(name):
    """Checks that the given service exists by using kube client

    Args:
        name (str): Service name

    Returns:
        (bool): Whether the stateful set exists
    """
    config.load_kube_config(context=KUBE_CONTEXT)
    v1 = client.CoreV1Api()

    service = None
    try:
        service = v1.read_namespaced_service(name, namespace="default")
    except ApiException as e:
        pass

    return service is not None


def wait_for_pod(pod_name):
    """Waits for the given pod to be in `Running` state

    Args:
        pod_name (str): Pod name
    """
    config.load_kube_config(context=KUBE_CONTEXT)
    v1 = client.CoreV1Api()
    created = False
    while not created:
        try:
            pod = v1.read_namespaced_pod(name=pod_name, namespace="default")
            created = pod.status.phase == "Running"
        except ApiException as e:
            pass


def test_integration_1():
    # Create the run
    name = get_random_name(5)
    response = requests.post(
        os.path.join(DASHBOARD_URL, "api/runs/"),
        {
            "num_cpus": "1.0",
            "name": name,
            "num_workers": 1,
            "image_name": "custom_image",
            "custom_image_name": "mlbench/mlbench_worker",
            "custom_image_command": "sleep 60",
            "run_all_nodes": True,
            "light_target": True,
            "gpu_enabled": "false",
            "backend": "gloo",
        },
    )
    pod_name = "{}-mlbench-worker-{}-2-0".format(name, RELEASE_NAME)

    assert response.status_code == 201  # Created
    # Wait for pods to come up
    wait_for_pod(pod_name)
    check_pod_number(1)

    # Check list runs
    model_run = get_modelrun(name)

    assert model_run is not None
    # Check run ID and state
    run_id = model_run["id"]
    state = model_run["state"]
    assert state == "started"
    assert model_run["name"] == name

    # Wait for it to finish
    while state not in ["finished", "failed"]:
        state = json.loads(
            requests.get(
                os.path.join(DASHBOARD_URL, "api/runs/{}/".format(run_id))
            ).content.decode()
        )["state"]

    assert state == "finished"
    sleep(20)
    check_pod_number(0)

    s_name = "{}-mlbench-worker-{}-2".format(name, RELEASE_NAME)
    assert not statefulset_exists(s_name)
    assert not service_exists(s_name)


def test_integration_2():
    name = get_random_name(5)
    response = requests.post(
        os.path.join(DASHBOARD_URL, "api/runs/"),
        {
            "num_cpus": "1.0",
            "name": name,
            "num_workers": 1,
            "image_name": "custom_image",
            "custom_image_name": "mlbench/mlbench_worker",
            "custom_image_command": "sleep 120",
            "run_all_nodes": True,
            "light_target": True,
            "gpu_enabled": "false",
            "backend": "gloo",
        },
    )
    pod_name = "{}-mlbench-worker-{}-2-0".format(name, RELEASE_NAME)
    assert response.status_code == 201  # Created
    wait_for_pod(pod_name)
    check_pod_number(1)

    model_run = get_modelrun(name)
    assert model_run is not None
    assert model_run["state"] == "started"
    response = requests.delete(
        os.path.join(DASHBOARD_URL, "api/runs/{}/".format(model_run["id"]))
    )
    assert response.status_code == 204

    sleep(20)
    model_run = get_modelrun(name)
    assert model_run is None

    check_pod_number(0)

    s_name = "{}-mlbench-worker-{}-2".format(name, RELEASE_NAME)
    assert not statefulset_exists(s_name)
    assert not service_exists(s_name)
