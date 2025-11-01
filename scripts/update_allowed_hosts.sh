#!/bin/bash
NAMESPACE=erp
ENV_SECRET_NAME=erp-api-env

# Retrieve dynamic pod and service IPs
POD_IPS=$(kubectl get pods -n ${NAMESPACE} -l app=erp-api-app -o jsonpath='{.items[*].status.podIP}' 2>/dev/null | tr ' ' ',' || true)
SVC_IP=$(kubectl get svc erp-api -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)

# Build comprehensive ALLOWED_HOSTS
# NOTE: Django doesn't support CIDR notation, use wildcards or explicit IPs
UPDATED_ALLOWED_HOSTS="erpapi.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke"
[[ -n "$SVC_IP" ]] && UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},${SVC_IP}"
[[ -n "$POD_IPS" ]] && UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},${POD_IPS}"
# Use wildcards for private IP ranges (Django doesn't support CIDR notation)
UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},10.*,172.*,192.168.*"

echo "Current pod IPs: ${POD_IPS}"
echo "Service ClusterIP: ${SVC_IP}"
echo "Updated ALLOWED_HOSTS: ${UPDATED_ALLOWED_HOSTS}"

# Patch env secret with updated ALLOWED_HOSTS
kubectl -n ${NAMESPACE} patch secret ${ENV_SECRET_NAME} --type merge -p "{\"stringData\":{\"ALLOWED_HOSTS\":\"${UPDATED_ALLOWED_HOSTS}\"}}"

# Restart deployment to apply updated ALLOWED_HOSTS
echo "Restarting API deployment to apply updated ALLOWED_HOSTS..."
kubectl rollout restart deployment/erp-api-app -n ${NAMESPACE}
kubectl rollout status deployment/erp-api-app -n ${NAMESPACE} --timeout=300s

echo "✅ ALLOWED_HOSTS updated with cluster IPs"
