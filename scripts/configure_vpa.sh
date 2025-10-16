#!/usr/bin/env bash
# VPA configuration script for database StatefulSets
# Configures Vertical Pod Autoscaler for PostgreSQL and Redis

set -euo pipefail

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[1;33m[WARNING]\033[0m $1"; }
log_step() { echo -e "\033[0;35m[STEP]\033[0m $1"; }

NAMESPACE=${NAMESPACE:-erp}

# Optional: Configure VPA for databases if CRDs exist
if kubectl get crd verticalpodautoscalers.autoscaling.k8s.io >/dev/null 2>&1; then
    log_step "Configuring VPA for PostgreSQL and Redis"
    cat > /tmp/vpa-postgresql.yaml <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: postgresql-vpa
  namespace: ${NAMESPACE}
spec:
  targetRef:
    apiVersion: "apps/v1"
    kind:       StatefulSet
    name:       postgresql
  updatePolicy:
    updateMode: "Auto"
EOF
    kubectl apply -f /tmp/vpa-postgresql.yaml || log_warning "Failed to apply VPA for PostgreSQL"

    cat > /tmp/vpa-redis-master.yaml <<EOF
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: redis-master-vpa
  namespace: ${NAMESPACE}
spec:
  targetRef:
    apiVersion: "apps/v1"
    kind:       StatefulSet
    name:       redis-master
  updatePolicy:
    updateMode: "Auto"
EOF
    kubectl apply -f /tmp/vpa-redis-master.yaml || log_warning "Failed to apply VPA for Redis"
    log_success "VPA configured for PostgreSQL and Redis"
else
    log_info "VPA CRDs not found; skipping DB VPA configuration"
fi

