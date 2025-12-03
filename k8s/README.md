# ERP API - Kubernetes Manifests

This directory contains ERP-specific Kubernetes resources that are not part of the shared infrastructure.

## Files

### Database Initialization
- **`db-init-job.yaml`** - Database initialization job
  - Creates Django superuser
  - Runs migrations
  - Collects static files
  - Uses: `erp-api-env` secret for credentials
  - **Note**: Migrations are now handled by Helm migration hook (charts/app/templates/migrate-hook.yaml)
  - This file is kept for reference or manual initialization

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

### Manual Database Initialization (if needed)
```bash
# Only use if Helm migration hook fails
kubectl apply -f k8s/db-init-job.yaml

# Check job status
kubectl get jobs -n erp
kubectl logs -n erp job/erp-db-init
```

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

- Migrations are handled by Helm migration hook (pre-install, pre-upgrade)
- Seeding is handled by `scripts/run_seeding.sh` during deployment
- These manifests are for manual operations and reference only

