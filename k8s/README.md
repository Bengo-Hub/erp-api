# ERP API - Kubernetes Manifests

This directory contains ERP-specific Kubernetes resources that are not part of the shared infrastructure.

## Files

### Monitoring
- **`monitoring/servicemonitor.yaml`** - Prometheus ServiceMonitor
  - Scrapes metrics from `/api/v1/metrics` endpoint
  - Interval: 30s
  - Namespace: monitoring (or infra if monitoring namespace doesn't exist)

- **`monitoring/alerts.yaml`** - Prometheus alerts
  - ERPAPIDown: API unavailable for 2+ minutes
  - ERPUIDown: UI unavailable for 2+ minutes
  - HighCPUUsage: CPU > 80% for 5 minutes
  - HighMemoryUsage: Memory > 90% for 5 minutes
  - PodRestartingTooOften: Frequent pod restarts
  - HPAMaxedOut: HPA at maximum replicas

## Usage

### Apply Monitoring Resources
```bash
# ServiceMonitor (requires Prometheus Operator)
kubectl apply -f k8s/monitoring/servicemonitor.yaml

# Alerts (requires Prometheus Operator)
kubectl apply -f k8s/monitoring/alerts.yaml
```

### Database initialisation
The container entrypoint runs `erp-migrate` and the idempotent seeders on every start
(`scripts/entrypoint.sh`), so no separate init job is needed.

## Integration with ArgoCD

These files are **NOT** managed by ArgoCD. They are:
- Applied manually when needed
- Used for debugging and troubleshooting
- Reference implementations

The main deployment uses:
- Helm charts: `devops-k8s/charts/app/`
- Values: `devops-k8s/apps/erp-api/values.yaml`
- ArgoCD Application: `devops-k8s/apps/erp-api/app.yaml`

## Notes

- Migrations and seeding run in the container entrypoint (`scripts/entrypoint.sh`)
- These manifests are for manual operations and reference only

