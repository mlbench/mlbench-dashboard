mlbench: Distributed Machine Learning Benchmark Helm Chart
==========================================================

[![Build Status](https://travis-ci.com/mlbench/mlbench-dashboard.svg?branch=develop)](https://travis-ci.com/mlbench/mlbench-dashboard)
[![DocumentationStatus](https://readthedocs.org/projects/mlbench-docs/badge/?version=latest)](https://mlbench.readthedocs.io/projects/mlbench_dashboard/en/latest/readme.html?badge=latest)

MLBench is a Benchmarking Framework for Distributed Machine Learning algorithms.

This repository contains the Dashboard for MLBench which is used manage Benchmark runs and worker status.

For more information refer to the [Dashboard Documentation](https://mlbench.readthedocs.io/projects/mlbench_dashboard/en/stable/readme.html)
or the [Main Documentation](https://mlbench.readthedocs.io/)

Development Guide
-----------------

#### Django tests
To run django tests, you can either use `make test` or `python src/manage.py test`


#### Integration tests
For integration tests to run, one needs to have a running local registry, and the image pushed onto it.
Those tests will deploy the dashboard on a local KIND cluster, and send requests as if it was the client.
It tests basic functionality of the dashboard and helps with version upgrades.

- Deploy local registry: `docker run -d -p 5000:5000 --restart=always --name kind-registry registry:2`
- Build image `docker build -t localhost:5000/mlbench_master:test -f Docker/Dockerfile .`
- Push image to local registry `docker push localhost:5000/mlbench_master:test`
- Run tests `make integration-test`

By default, the tests (integration and django) will be run using Kubernetes v1.15. To change that, you can prepend the test command with 
`env KIND_NODE_IMAGE=<image>` and the list of images is:

```
- Kubernetes 1.15: kindest/node:v1.15.12@sha256:d9b939055c1e852fe3d86955ee24976cab46cba518abcb8b13ba70917e6547a6
- Kubernetes 1.16: kindest/node:v1.16.15@sha256:a89c771f7de234e6547d43695c7ab047809ffc71a0c3b65aa54eda051c45ed20
- Kubernetes 1.17: kindest/node:v1.17.11@sha256:5240a7a2c34bf241afb54ac05669f8a46661912eab05705d660971eeb12f6555
- Kubernetes 1.18: kindest/node:v1.18.8@sha256:f4bcc97a0ad6e7abaf3f643d890add7efe6ee4ab90baeb374b4f41a4c95567eb
- Kubernetes 1.19: kindest/node:v1.19.1@sha256:98cf5288864662e37115e362b23e4369c8c4a408f99cbc06e58ac30ddc721600
```  

#### Debugging
Debugging integration tests can be tricky as we don't have access to logs. To access logs, use `kubectl cp` to copy files from `/var/log`
from the master node.