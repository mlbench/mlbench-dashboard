#!/usr/bin/env bash

BASEDIR=$(dirname "$0")

# Install helm,  kubectl and kind
echo "Installing Kubectl"
w
curl -LO https://storage.googleapis.com/kubernetes-release/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl
chmod +x ./kubectl && sudo mv ./kubectl /usr/local/bin/kubectl
sleep 1

echo "Installing Helm"
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh

echo "Installing kind"
curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.9.0/kind-$(uname)-amd64"
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# Pull image and store to local reg
echo "Pulling image from ${DOCKER_REPOSITORY}"
docker pull ${DOCKER_REPOSITORY}/mlbench_master:travis-ci-test
docker tag ${DOCKER_REPOSITORY}/mlbench_master:travis-ci-test localhost:5000/mlbench_master:travis-ci-test
docker push localhost:5000/mlbench_master:travis-ci-test

sleep 2

# Export KIND config
echo "Exporting kind config based on env variables"
envsubst < ${BASEDIR}/KIND_CONFIG > KIND_CONFIG
sleep 2

# Create kind cluster
echo "Creating Kind cluster"
curl https://raw.githubusercontent.com/zlabjp/kubernetes-scripts/master/wait-until-pods-ready > wait_until_pods_ready.sh
chmod +x wait_until_pods_ready.sh
kind create cluster --name ${RELEASE_NAME}-2 --config KIND_CONFIG
docker network connect "kind" ${REG_NAME}

# Clone Helm repo and deploy
git clone https://github.com/mlbench/mlbench-helm.git
helm template ${RELEASE_NAME}-2 mlbench-helm/ \
  --set limits.cpu=1 --set limits.gpu=0 --set limits.workers=1 \
  --set master.image.tag=travis-ci-test --set master.image.repository=localhost:5000/mlbench_master | kubectl apply -f -

./wait_until_pods_ready.sh 30 2

kubectl get pods

export NODE_IP=$(kubectl get nodes --namespace default -o jsonpath="{.items[0].status.addresses[0].address}")
export NODE_PORT=$(kubectl get --namespace default -o jsonpath="{.spec.ports[0].nodePort}" services ${RELEASE_NAME}-2-mlbench-master)
export DASHBOARD_URL=http://$NODE_IP:$NODE_PORT

echo "$DASHBOARD_URL"