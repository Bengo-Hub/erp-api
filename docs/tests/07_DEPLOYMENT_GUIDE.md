# Deployment & Operations Guide

**Document Date**: March 1, 2026  
**Version**: 1.0  
**Status**: Production Ready

---

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Deployment Procedures](#deployment-procedures)
3. [Post-Deployment Validation](#post-deployment-validation)
4. [Rollback Procedures](#rollback-procedures)
5. [Monitoring & Operations](#monitoring--operations)
6. [Disaster Recovery](#disaster-recovery)
7. [Scaling & Performance](#scaling--performance)
8. [Maintenance Windows](#maintenance-windows)

---

## Pre-Deployment Checklist

### Code Quality (2 days before)
- [ ] All tests passing (100% suite)
- [ ] Coverage >= 80%
- [ ] Code review completed and approved
- [ ] No security vulnerabilities (run bandit/semgrep)
- [ ] No linting errors

### Database (1 week before)
- [ ] Migrations tested locally
- [ ] Migrations tested in staging
- [ ] Rollback migrations tested
- [ ] Data backup verified
- [ ] Estimated migration time < 30 seconds

### Documentation (2 days before)
- [ ] Release notes prepared
- [ ] API changes documented
- [ ] User communications drafted
- [ ] Support guides updated
- [ ] Admin procedures documented

### Infrastructure (1 day before)
- [ ] Load test completed
- [ ] Capacity plan reviewed
- [ ] Scaling policies active
- [ ] Monitoring alerts configured
- [ ] Backup verified

### Communication (1 day before)
- [ ] Deployment window scheduled
- [ ] Stakeholders notified
- [ ] Support team briefed
- [ ] Rollback team on standby
- [ ] Emergency contacts listed

---

## Deployment Procedures

### Option 1: Standard Deployment (Zero-downtime)

#### Step 1: Pre-flight Checks (15 mins)
```bash
# Verify all systems operational
./scripts/pre_deployment_check.sh

# Run smoke tests
pytest tests/smoke_tests/

# Check database connectivity
python manage.py check --deploy

# Verify migrations are ready
python manage.py migrate --plan
```

#### Step 2: Deploy New Code (10 mins)
```bash
# Update code
git pull origin main

# In container environment:
docker build -t erp-api:v2.0.0 .
docker tag erp-api:v2.0.0 registry/erp-api:v2.0.0
docker push registry/erp-api

# For Kubernetes:
kubectl set image deployment/erp-api \
  erp-api=registry/erp-api:v2.0.0 \
  --record
```

#### Step 3: Run Migrations (5-30 mins depending on size)
```bash
# In zero-downtime deployment:
# - Old code handles old schema
# - Run backwards-compatible migrations
# - New code deployed
# - Run forward migration

python manage.py migrate --database=default

# Verify migrations applied
python manage.py showmigrations
```

#### Step 4: Collect Static Files
```bash
python manage.py collectstatic --no-input
```

#### Step 5: Clear Caches
```bash
# Redis cache
redis-cli FLUSHDB

# Django cache
python manage.py clear_cache

# Cloudfront CDN (if applicable)
aws cloudfront create-invalidation --distribution-id E... --paths "/*"
```

#### Step 6: Verify Deployment
```bash
# Check health endpoint
curl https://erp-api.example.com/health/

# Check API endpoints
curl -H "Authorization: Bearer TOKEN" \
  https://erp-api.example.com/api/invoices/

# Run API tests
pytest tests/api/
```

### Option 2: Blue-Green Deployment

```bash
# 1. Deploy to Green environment
kubectl create -f deployment-v2.0.0.yaml

# 2. Wait for Green to be ready
kubectl wait --for=condition=ready pod \
  -l version=v2.0.0 --timeout=300s

# 3. Run smoke tests on Green
pytest --env=green tests/smoke_tests/

# 4. Switch traffic to Green
kubectl patch service erp-api \
  -p '{"spec":{"selector":{"version":"v2.0.0"}}}'

# 5. Monitor for issues (30 mins)
# 6. Remove Blue environment
kubectl delete deployment erp-api-v1.9.0
```

### Option 3: Canary Deployment

```bash
# 1. Deploy v2.0.0 alongside v1.9.0
kubectl create -f deployment-v2.0.0.yaml

# 2. Route 10% of traffic to new version
kubectl patch virtualservice erp-api \
  --patch '{"spec":{"hosts":[{"name":"erp-api","http":[{"match":[{"sourceLabels":{"canary":"true"}}],"route":[{"destination":{"host":"erp-api-v2.0.0"}}]},{"route":[{"destination":{"host":"erp-api-v1.9.0","port":{"number":8000},"weight":90}},{"destination":{"host":"erp-api-v2.0.0","port":{"number":8000},"weight":10}}]}]}]}'

# 3. Monitor metrics
# 4. Gradually increase traffic: 10% -> 25% -> 50% -> 100%
# 5. Remove old version
```

---

## Post-Deployment Validation

### Immediate (0-5 mins)
```bash
# Check deployment status
kubectl get deployment erp-api
kubectl get pods

# Check logs for errors
kubectl logs -f deployment/erp-api -n production

# Health check
curl -v https://erp-api.example.com/health/
```

### Short Term (5-30 mins)
```bash
# Run API tests
pytest tests/api/ -v

# Check key endpoints
./scripts/validation_tests.sh

# Monitor error rates
# Watch: error logs, exception tracking (Sentry)
```

### Medium Term (30 mins - 4 hours)
```bash
# Monitor performance metrics
# - Response time (< 200ms p95)
# - Error rate (< 0.1%)
# - Throughput (requests/sec)
# - Database performance

# Check feature functionality
# - Create invoice
# - Approve document
# - Process payment
# - Test new features

# Performance baseline
./scripts/benchmark.sh
```

### Full Validation (4 hours - 24 hours)
```bash
# Comprehensive testing
# - All critical user paths
# - Data integrity checks
# - Report generation
# - Export/import operations
# - Integration tests

# Security validation
# - No auth bypass
# - Permission checks working
# - No XSS/CSRF vulnerabilities
# - Rate limiting active
```

---

## Rollback Procedures

### Quick Rollback (If issues found within 30 mins)

#### Option 1: Container Rollback
```bash
# Revert to previous image
kubectl set image deployment/erp-api \
  erp-api=registry/erp-api:v1.9.0 \
  --record

# Wait for rollback to complete
kubectl wait --for=condition=ready pod \
  -l version=v1.9.0 --timeout=300s

# Verify rollback
kubectl logs deployment/erp-api | tail -20
curl https://erp-api.example.com/health/
```

#### Option 2: Git Rollback
```bash
# If deployment from code
git revert HEAD
git push origin main

# Restart deployment
kubectl rollout restart deployment/erp-api
```

### Database Rollback (If migrations failed)

```bash
# IMPORTANT: Backup current state first
pg_dump -h $DB_HOST -U $DB_USER $DB_NAME > backup-post-failed-migration.sql

# Restore previous migration state
python manage.py migrate finance 0042_previous_migration

# Verify data integrity
python manage.py validate_migrations
python manage.py check --deploy

# Restart application
kubectl rollout restart deployment/erp-api
```

### Zero-Data-Loss Rollback Process

```bash
# 1. Stop processing new requests (maintain read access)
#    (in Kubernetes, scale down to single instance)
kubectl scale deployment erp-api --replicas=1

# 2. Backup current database
pg_dump ... > backup-$(date +%s).sql

# 3. Rollback code
git revert HEAD
docker build -t erp-api:rollback .

# 4. Verify migrations
python manage.py migrate --plan

# 5. If migrations need rolling back:
python manage.py migrate finance <previous_migration>

# 6. Restart with rolled-back code
kubectl set image deployment/erp-api \
  erp-api=erp-api:rollback

# 7. Resume normal operation
kubectl scale deployment erp-api --replicas=3

# 8. Post-mortem
#    - Document what failed
#    - Create issue for fix
#    - Plan redeployment
```

### Full Environment Rollback

```bash
# If everything is broken:
# 1. Switch to previous fully-tested environment (Blue-Green)
kubectl patch service erp-api \
  -p '{"spec":{"selector":{"version":"v1.9.0"}}}'

# 2. Investigate via parallel environment
# 3. Fix issues
# 4. Redeploy when ready

# This assumes you maintained previous environment!
```

---

## Monitoring & Operations

### Key Metrics to Monitor

#### Application Metrics
```
- Request response time (< 200ms p95)
- Error rate (< 0.1%)
- Request throughput
- Active connections
- Memory usage (< 80% of limit)
- CPU usage (< 80% of limit)
```

#### Business Metrics
```
- Invoices created/day
- Payments processed/day
- Approval queue size
- Document processing time
- Delivery note fulfillment rate
```

#### Database Metrics
```
- Query execution time
- Slow queries (> 1000ms)
- Connection pool (< 80% used)
- Cache hit rate (> 90%)
- Disk I/O
- Replication lag (< 1s)
```

### Monitoring Setup

#### Prometheus
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'erp-api'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics/'
```

#### Grafana Dashboards
- API Performance Dashboard
- Business Metrics Dashboard
- Infrastructure Dashboard
- Error Tracking Dashboard

#### Alerting Rules
```yaml
# Alert if error rate > 1%
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.01
  for: 5m

# Alert if response time p95 > 500ms
- alert: HighResponseTime
  expr: histogram_quantile(0.95, response_time_seconds) > 0.5

# Alert if deployment failed
- alert: DeploymentReplicasMismatch
  expr: kube_deployment_spec_replicas != kube_deployment_status_replicas_available
```

### Log Aggregation

Use ELK Stack or similar:
```bash
# Parse logs for errors
curl "http://elasticsearch:9200/logstash-*/_search" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match":{"level":"ERROR"}}}'
```

---

## Disaster Recovery

### Backup Strategy

#### Daily Backups
```bash
# Full database backup (daily at 2 AM UTC)
pg_dump -h $DB_HOST -U $DB_USER \
  --no-password $DB_NAME \
  | gzip > /backups/erp-$(date +%Y%m%d).sql.gz

# Upload to S3
aws s3 cp /backups/erp-*.sql.gz \
  s3://erp-backups/daily/
```

#### Incremental Backups
```bash
# Use WAL archiving for point-in-time recovery
# (PostgreSQL setup - maintained continuously)
```

#### Retention Policy
```
- Daily backups: Keep 30 days
- Weekly backups: Keep 12 weeks
- Monthly backups: Keep 12 months
```

### Recovery Procedures

#### Database Recovery
```bash
# 1. Stop application
kubectl scale deployment erp-api --replicas=0

# 2. Restore from backup
gunzip -c /backups/erp-20260301.sql.gz | psql -h $DB_HOST -U $DB_USER $DB_NAME

# 3. Verify integrity
psql -h $DB_HOST -U $DB_USER $DB_NAME -c "SELECT COUNT(*) FROM finance_invoicing_invoice;"

# 4. Restart application
kubectl scale deployment erp-api --replicas=3

# 5. Validate functionality
./scripts/smoke_tests.sh
```

#### Complete Environment Recovery
```bash
# 1. Identify recovery point
# 2. Provision new infrastructure
# 3. Restore database
# 4. Deploy application
# 5. Verify and switch traffic
# 6. Decommission old environment
```

### RTO/RPO Targets
```
RTO (Recovery Time Objective): < 1 hour
RPO (Recovery Point Objective): < 1 hour
```

---

## Scaling & Performance

### Horizontal Scaling

```yaml
# Kubernetes HorizontalPodAutoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: erp-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: erp-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Vertical Scaling
```yaml
# Adjust resource requests/limits
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### Database Optimization
```bash
# Analyze slow queries
EXPLAIN ANALYZE SELECT * FROM finance_invoicing_invoice WHERE status='draft';

# Add indexes for slow queries
CREATE INDEX idx_invoice_status ON finance_invoicing_invoice(status);

# Reindex regularly
REINDEX INDEX idx_invoice_status;
```

### Caching Strategy
```python
# Cache frequently accessed data
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Cache invoice list
@cache_page(60 * 5)  # 5 minutes
def invoice_list(request):
    ...
```

---

## Maintenance Windows

### Planned Maintenance Schedule
```
Weekly: Sunday 2:00-3:00 AM UTC (Low-risk updates)
Monthly: First Sunday of month 2:00-4:00 AM UTC (Database maintenance)
Quarterly: TBD (Major updates)
```

### Maintenance Communication
```
- Announce 2 weeks before
- Announce 24 hours before
- Announce 1 hour before
- Send completion notice
- Share incident details (if any)
```

### During Maintenance
```bash
# Display maintenance page
kubectl set env deployment/erp-api MAINTENANCE_MODE=true

# Direct traffic to static maintenance page
# Keep read-only API access if possible
# Queue up write requests for post-maintenance

# Perform tasks
# - Database optimization
# - Dependency updates
# - System patching
# - Configuration changes

# Bring system back online
kubectl set env deployment/erp-api MAINTENANCE_MODE=false

# Process queued requests
# Notify users
```

---

## Incident Response

### Incident Severity Levels

| Level | Response Time | Impact | Examples |
|-------|--------------|--------|----------|
| #1 Critical | < 15 mins | Complete outage, data loss, security breach | 0% uptime, all users affected |
| #2 High | < 1 hour | Major feature down, significant data corruption | Major feature unavailable |
| #3 Medium | < 4 hours | Feature partially working, some users affected | Some users experiencing issues |
| #4 Low | < 24 hours | Minor issue, workaround available | Cosmetic issues, non-critical |

### Response Procedures

#### For #1 Severity
1. Page on-call team immediately
2. Start incident bridge
3. Assign incident commander
4. Immediately attempt rollback if recently deployed
5. Engage architecture team
6. Update status every 15 mins
7. Post-incident review within 24 hours

#### For #2-3 Severity
1. Notify team leads
2. Start incident bridge
3. Investigate root cause
4. Prepare fix or rollback
5. Deploy fix
6. Verify resolution
7. Post-incident review

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-01  
**Maintained By**: DevOps Team
