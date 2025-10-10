#!/usr/bin/env bash
set -euo pipefail

# SS-style build wrapper for ERP API

TRIVY_ECODE=${TRIVY_ECODE:-1}
DEPLOY=${DEPLOY:-false}

if [[ -z ${GITHUB_SHA:-} ]]; then
  GIT_COMMIT_ID=$(git rev-parse --short=8 HEAD)
else
  GIT_COMMIT_ID=${GITHUB_SHA::8}
fi

IMAGE_REPO=${IMAGE_REPO:-docker.io/Bengo-Hub/erp-api}

echo "[INFO] Trivy FS scan"
trivy fs . --exit-code $TRIVY_ECODE || true

echo "[INFO] Docker build $IMAGE_REPO:$GIT_COMMIT_ID"
DOCKER_BUILDKIT=1 docker build . -t "$IMAGE_REPO:$GIT_COMMIT_ID"

echo "[INFO] Trivy Image scan"
trivy image "$IMAGE_REPO:$GIT_COMMIT_ID" --exit-code $TRIVY_ECODE || true

if [[ "$DEPLOY" == "true" ]]; then
  echo "[INFO] Pushing image"
  docker push "$IMAGE_REPO:$GIT_COMMIT_ID"

  if [[ -n ${KUBE_CONFIG:-} ]]; then
    echo "[INFO] Applying kube secrets"
    mkdir -p ~/.kube
    echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config
    kubectl apply -f kubeSecrets/devENV.yaml || true
  fi
fi

echo "[SUCCESS] Completed. Tag: $GIT_COMMIT_ID"


