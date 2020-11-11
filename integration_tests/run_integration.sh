#!/usr/bin/env bash

BASEDIR=$(dirname "$0")
TMPDIR=$(dirname $(mktemp -u))

# Install helm,  kubectl and kind
if ! command -v kubectl &> /dev/null
then
  echo "Installing Kubectl"
  curl -LO https://storage.googleapis.com/kubernetes-release/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl
  chmod +x ./kubectl && sudo mv ./kubectl /usr/local/bin/kubectl
  sleep 1
else
  echo "kubectl found, skipping install"
fi

if ! command -v helm &> /dev/null
then
  echo "Installing Helm"
  curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
  chmod 700 get_helm.sh
  ./get_helm.sh
else
  echo "helm found, skipping install"
fi

if ! command -v kind &> /dev/null
then
  echo "Installing kind"
  curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.9.0/kind-$(uname)-amd64"
  chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
else
  echo "kind found, skipping install"
fi




# Pull image and store to local reg
echo "Pulling image from ${DOCKER_REPOSITORY}"
docker pull ${DOCKER_REPOSITORY}/mlbench_master:${DOCKER_IMAGE_TAG}
docker tag ${DOCKER_REPOSITORY}/mlbench_master:${DOCKER_IMAGE_TAG} localhost:5000/mlbench_master:${DOCKER_IMAGE_TAG}
docker push localhost:5000/mlbench_master:${DOCKER_IMAGE_TAG}

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
docker network disconnect "kind" ${REG_NAME} &> /dev/null
docker network connect "kind" ${REG_NAME}

# Clone Helm repo and deploy
git clone https://github.com/mlbench/mlbench-helm.git ${TMPDIR}/mlbench-helm
helm template ${RELEASE_NAME}-2 ${TMPDIR}/mlbench-helm/ \
  --set limits.cpu=1 --set limits.gpu=0 --set limits.workers=1 \
  --set master.image.tag=${DOCKER_IMAGE_TAG} --set master.image.repository=localhost:5000/mlbench_master | kubectl apply -f -

sleep 2

./wait_until_pods_ready.sh 120 10
sleep 60

export NODE_IP=$(kubectl get nodes --namespace default -o jsonpath="{.items[0].status.addresses[0].address}")
export NODE_PORT=$(kubectl get --namespace default -o jsonpath="{.spec.ports[0].nodePort}" services ${RELEASE_NAME}-2-mlbench-master)
export DASHBOARD_URL=http://$NODE_IP:$NODE_PORT
export KUBE_CONTEXT=kind-${RELEASE_NAME}-2

echo "$DASHBOARD_URL"

rm wait_until_pods_ready.sh
rm KIND_CONFIG

pytest -v

passed = $?
sleep 5

kind delete cluster --name ${RELEASE_NAME}-2
docker network disconnect "kind" ${REG_NAME}

exit $(passed)