# Manual Deployment Guide - BengoERP API

This guide provides **complete step-by-step procedures** for manually deploying the BengoERP API when automated workflows are unavailable or require manual intervention. This guide assumes **no prior deployment exists** and walks you through the entire process from start to finish.

## 🚀 Complete Deployment Workflow

### Phase 0: Build & Push Docker Image (Beginner Friendly)
### Phase 1: Prerequisites Verification
## Phase 0: Build & Push Docker Image (Beginner Friendly)

This phase builds the API container locally and pushes it to your registry, then updates the devops-k8s Helm values to use the new image tag.

### 0.1 Set environment
```bash
# Application configuration
export APP_NAME=erp-api
export REGISTRY_SERVER=docker.io
export REGISTRY_NAMESPACE=codevertex
export IMAGE_REPO="$REGISTRY_SERVER/$REGISTRY_NAMESPACE/$APP_NAME"
export IMAGE_TAG=$(git rev-parse --short=8 HEAD)
export NAMESPACE=erp

# DevOps repository
export DEVOPS_REPO=https://github.com/Bengo-Hub/devops-k8s.git
export DEVOPS_DIR=~/devops-k8s
export VALUES_FILE_PATH="apps/${APP_NAME}/values.yaml"

# Kubernetes secret for application environment (used by migrations and runtime)
export ENV_SECRET_NAME=erp-api-env

# REQUIRED for cross-repo push (deploy keys DON'T work)
export GH_PAT="ghp_..."      # GitHub PAT with repo:write to Bengo-Hub/devops-k8s

# REQUIRED for private registry
export REGISTRY_USERNAME="codevertex"
export REGISTRY_PASSWORD="your-registry-token"

# REQUIRED for kubectl operations
export KUBE_CONFIG="$(cat ~/.kube/config | base64 -w0)"
```

### 0.2 Log in to registry
```bash
docker login $REGISTRY_SERVER
```

### 0.3 Build and push image
```bash
# From the API project root
cd /bengobox-erp-api/
docker build -t "$IMAGE_REPO:$IMAGE_TAG" .
docker push "$IMAGE_REPO:$IMAGE_TAG"
```

### 0.3.1 Security scans (optional but recommended)
```bash
# Filesystem scan (Trivy)
trivy fs . --exit-code 0 --format table --skip-files "localhost*.pem,*.key,*.crt"

# Image scan (respects .trivyignore when present)
trivy image "$IMAGE_REPO:$IMAGE_TAG" --exit-code 0 --format table --ignorefile .trivyignore
```

### 0.4 Create registry pull secret in cluster
```bash
# Decode kubeconfig
# Update server address
sed -i 's|server: https://.\*:6443|server: https://77.237.232.66:6443 |' ~/.kube/contabo-kubeadm-config
# Test
export KUBECONFIG=~/.kube/contabo-kubeadm-config

mkdir -p ~/.kube
echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config

# Create namespace if needed
kubectl get ns $NAMESPACE >/dev/null 2>&1 || kubectl create ns $NAMESPACE

# Create imagePullSecret for private registry
kubectl -n $NAMESPACE create secret docker-registry registry-credentials \
  --docker-server=$REGISTRY_SERVER \
  --docker-username=$REGISTRY_USERNAME \
  --docker-password=$REGISTRY_PASSWORD \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 0.5 Update devops-k8s values with new tag
```bash
# Clone devops repo if needed
[ -d "$DEVOPS_DIR" ] || git clone "$DEVOPS_REPO" "$DEVOPS_DIR"
cd "$DEVOPS_DIR"

# Ensure yq is installed
yq --version || (echo "Install yq: https://github.com/mikefarah/yq" && exit 1)

# Update image repo, tag, and imagePullSecrets (env-injection)
IMAGE_REPO="$IMAGE_REPO" IMAGE_TAG="$IMAGE_TAG" \
yq e -i '.image.repository = env(IMAGE_REPO) | .image.tag = env(IMAGE_TAG)' apps/erp-api/values.yaml

yq e -i '.image.pullSecrets = [{"name":"registry-credentials"}]' apps/erp-api/values.yaml

# Commit and push (MUST use GH_PAT - deploy keys don't work for cross-repo)
git fetch origin main
git checkout main || git checkout -b main
git add apps/erp-api/values.yaml
git commit -m "erp-api:$IMAGE_TAG released" || echo "No changes to commit"
git pull --rebase origin main || true

# Set remote with PAT token for push
git remote set-url origin "https://x-access-token:${GH_PAT}@github.com/Bengo-Hub/devops-k8s.git"
git push origin HEAD:main
```

**Important**: Deploy keys on devops-k8s won't work when pushing from another repo. You MUST use a PAT token with repo:write scope.

After pushing, ArgoCD will detect the change and sync automatically with zero-downtime rolling update.

### 0.6 Optional: Database setup (PostgreSQL and Redis)
```bash
# Ensure namespace exists
kubectl get ns $NAMESPACE >/dev/null 2>&1 || kubectl create ns $NAMESPACE

# Add/update Helm repos
helm repo add bitnami https://charts.bitnami.com/bitnami || true
helm repo update

# Set required passwords (if not already exported)
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"change-me-strong"}
export REDIS_PASSWORD=${REDIS_PASSWORD:-"change-me-strong"}
export PG_DATABASE=${PG_DATABASE:-bengo_erp}

# PRODUCTION NOTE:
#   Shared PostgreSQL and Redis are provisioned centrally via devops-k8s infrastructure scripts.
#   Do NOT install infra databases from this app. Instead, from the devops-k8s repo:
#
#   DB_NAMESPACE=$NAMESPACE PG_DATABASE=$PG_DATABASE ./scripts/infrastructure/install-postgres.sh
#   DB_NAMESPACE=$NAMESPACE ./scripts/infrastructure/install-redis.sh
#
# After infra is ready, create/update app env secret with DB/Redis URLs and production config:

# Generate a secure Django secret key if not already set
export DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-$(openssl rand -hex 50)}

kubectl -n $NAMESPACE create secret generic $ENV_SECRET_NAME \
  --from-literal=DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgresql.${NAMESPACE}.svc.cluster.local:5432/${PG_DATABASE}" \
  --from-literal=DB_HOST="postgresql.${NAMESPACE}.svc.cluster.local" \
  --from-literal=DB_PORT="5432" \
  --from-literal=DB_NAME="${PG_DATABASE}" \
  --from-literal=DB_USER="postgres" \
  --from-literal=DB_PASSWORD="${POSTGRES_PASSWORD}" \
  --from-literal=REDIS_URL="redis://:${REDIS_PASSWORD}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0" \
  --from-literal=REDIS_HOST="redis-master.${NAMESPACE}.svc.cluster.local" \
  --from-literal=REDIS_PORT="6379" \
  --from-literal=REDIS_PASSWORD="${REDIS_PASSWORD}" \
  --from-literal=CELERY_BROKER_URL="redis://:${REDIS_PASSWORD}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0" \
  --from-literal=CELERY_RESULT_BACKEND="redis://:${REDIS_PASSWORD}@redis-master.${NAMESPACE}.svc.cluster.local:6379/1" \
  --from-literal=DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=DJANGO_SETTINGS_MODULE="ProcureProKEAPI.settings" \
  --from-literal=DEBUG="False" \
  --from-literal=DJANGO_ENV="production" \
  --from-literal=ALLOWED_HOSTS="erpapi.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke" \
  --from-literal=CORS_ALLOWED_ORIGINS="https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke" \
  --from-literal=FRONTEND_URL="https://erp.masterspace.co.ke" \
  --from-literal=CSRF_TRUSTED_ORIGINS="https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke" \
  --from-literal=MEDIA_ROOT="/app/media" \
  --from-literal=MEDIA_URL="/media/" \
  --from-literal=STATIC_ROOT="/app/staticfiles" \
  --from-literal=STATIC_URL="/static/" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ Environment secret created/updated with production configuration"
```

### 0.7 Run database migrations (manual job)
```bash
SHORT_TAG=${IMAGE_TAG}
cat > /tmp/migrate-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: erp-migrate-${SHORT_TAG}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: ${IMAGE_REPO}:${SHORT_TAG}
        command: ["python", "manage.py", "migrate"]
        envFrom:
        - secretRef:
            name: ${ENV_SECRET_NAME}
EOF

kubectl apply -f /tmp/migrate-job.yaml

# Stream logs in real-time while waiting for job
echo "Streaming migration logs (waiting for pod to start)..."
for i in {1..30}; do
  MIGRATE_POD=$(kubectl get pods -n ${NAMESPACE} -l job-name=erp-migrate-${SHORT_TAG} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [[ -n "$MIGRATE_POD" ]]; then
    echo "Migration pod started: $MIGRATE_POD"
    break
  fi
  sleep 2
done

if [[ -n "$MIGRATE_POD" ]]; then
  # Follow logs in real-time
  kubectl logs -n ${NAMESPACE} -f "$MIGRATE_POD" &
  LOGS_PID=$!
  
  kubectl wait --for=condition=complete job/erp-migrate-${SHORT_TAG} -n ${NAMESPACE} --timeout=300s
  JOB_STATUS=$?
  
  # Stop log streaming
  kill $LOGS_PID 2>/dev/null || true
  wait $LOGS_PID 2>/dev/null || true
  
  if [[ $JOB_STATUS -ne 0 ]]; then
    echo "Migration job failed or timed out"
    kubectl logs -n ${NAMESPACE} "$MIGRATE_POD" --tail=100 || true
    exit 1
  fi
else
  echo "Migration pod never started"
  exit 1
fi

# Optional: Seed minimal initial data after migrations
cat > /tmp/seed-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: erp-seed-${SHORT_TAG}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: seed
        image: ${IMAGE_REPO}:${SHORT_TAG}
        command: ["python", "manage.py", "seed_all", "--minimal"]
        envFrom:
        - secretRef:
            name: ${ENV_SECRET_NAME}
EOF

kubectl apply -f /tmp/seed-job.yaml

# Stream seed logs in real-time
echo "Streaming seed logs (waiting for pod to start)..."
for i in {1..30}; do
  SEED_POD=$(kubectl get pods -n ${NAMESPACE} -l job-name=erp-seed-${SHORT_TAG} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [[ -n "$SEED_POD" ]]; then
    echo "Seed pod started: $SEED_POD"
    break
  fi
  sleep 2
done

if [[ -n "$SEED_POD" ]]; then
  # Follow logs in real-time
  kubectl logs -n ${NAMESPACE} -f "$SEED_POD" &
  SEED_LOGS_PID=$!
  
  kubectl wait --for=condition=complete job/erp-seed-${SHORT_TAG} -n ${NAMESPACE} --timeout=300s
  SEED_STATUS=$?
  
  # Stop log streaming
  kill $SEED_LOGS_PID 2>/dev/null || true
  wait $SEED_LOGS_PID 2>/dev/null || true
  
  if [[ $SEED_STATUS -ne 0 ]]; then
    echo "Seed job failed or timed out"
    kubectl logs -n ${NAMESPACE} "$SEED_POD" --tail=100 || true
    exit 1
  fi
else
  echo "Seed pod never started"
  exit 1
fi

# Update ALLOWED_HOSTS with cluster IPs
echo "Updating ALLOWED_HOSTS with cluster internal IPs..."
kubectl rollout restart deployment/erp-api-app -n ${NAMESPACE} || true
kubectl rollout status deployment/erp-api-app -n ${NAMESPACE} --timeout=300s || true
sleep 5

# Retrieve dynamic pod and service IPs
POD_IPS=$(kubectl get pods -n ${NAMESPACE} -l app=erp-api-app -o jsonpath='{.items[*].status.podIP}' 2>/dev/null | tr ' ' ',' || true)
SVC_IP=$(kubectl get svc erp-api -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)

# Build comprehensive ALLOWED_HOSTS
UPDATED_ALLOWED_HOSTS="erpapi.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke"
[[ -n "$SVC_IP" ]] && UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},${SVC_IP}"
[[ -n "$POD_IPS" ]] && UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},${POD_IPS}"
UPDATED_ALLOWED_HOSTS="${UPDATED_ALLOWED_HOSTS},10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

echo "Updated ALLOWED_HOSTS: ${UPDATED_ALLOWED_HOSTS}"

# Patch env secret with updated ALLOWED_HOSTS
kubectl -n ${NAMESPACE} patch secret ${ENV_SECRET_NAME} --type merge -p "{\"stringData\":{\"ALLOWED_HOSTS\":\"${UPDATED_ALLOWED_HOSTS}\"}}"

# Final restart to apply updated ALLOWED_HOSTS
echo "Restarting API deployment to apply updated ALLOWED_HOSTS..."
kubectl rollout restart deployment/erp-api-app -n ${NAMESPACE} || true
kubectl rollout status deployment/erp-api-app -n ${NAMESPACE} --timeout=300s || true

echo "✅ ALLOWED_HOSTS updated with cluster IPs"
```

### 0.8 Verify Celery Workers (for async payslip generation)
```bash
# Check if Celery workers are running
kubectl get pods -n ${NAMESPACE} -l component=celery-worker

# If no workers found, they will be deployed automatically via ArgoCD
# Workers use the same image as the API and connect to Redis for task queuing

# Check worker logs
kubectl logs -n ${NAMESPACE} -l component=celery-worker --tail=50

# Check Celery beat scheduler (for periodic tasks)
kubectl get pods -n ${NAMESPACE} -l component=celery-beat

# Verify Redis connection (used by both API and Celery)
kubectl run redis-check --rm -i --tty --image redis:alpine -n ${NAMESPACE} -- redis-cli -h redis-master.${NAMESPACE}.svc.cluster.local -a "${REDIS_PASSWORD}" ping
# Expected: PONG
```

**Note**: Payslip generation is asynchronous. If workers are not running, payslips will be queued but not processed.

### Phase 2: Initial ArgoCD Application Deployment
### Phase 3: Application Sync Monitoring
### Phase 4: Post-Deployment Verification
### Phase 5: Troubleshooting & Maintenance

---

## Phase 1: Prerequisites Verification

Before starting deployment, ensure you have:

### 1.1 Access Verification
```bash
# Verify kubectl access to cluster
kubectl cluster-info

# Check if you can access the argocd namespace
kubectl get pods -n argocd

# Verify ArgoCD CLI is available
argocd version
```

### 1.2 Required Tools Check
```bash
# Check if all required tools are installed
which kubectl git docker helm argocd

# Verify Docker registry access
docker login docker.io
```

### 1.3 Repository Access
```bash
# Clone or verify access to devops-k8s repository
git clone https://github.com/Bengo-Hub/devops-k8s.git
cd devops-k8s

# Verify you can access the API application
ls -la apps/erp-api/
```

**If any prerequisite fails, stop here and resolve the issue before proceeding.**

---

## Phase 2: Initial ArgoCD Application Deployment

Now we'll deploy the ArgoCD application that will manage the ERP API service.

### 2.1 Navigate to DevOps Repository
```bash
# Ensure you're in the devops-k8s directory
cd /path/to/devops-k8s

# Verify current directory
pwd  # Should show: /path/to/devops-k8s
```

### 2.2 Deploy ArgoCD Application
```bash
# Deploy the ERP API ArgoCD application
kubectl apply -f apps/erp-api/app.yaml -n argocd

# Verify application was created
kubectl get application erp-api -n argocd
```

Note: The ArgoCD application `apps/erp-api/app.yaml` uses `helm.valueFiles` to reference `apps/erp-api/values.yaml`. This enables automated updates of image tags by CI/CD.

**Expected Output:**
```bash
NAME     SYNC STATUS   HEALTH STATUS
erp-api  OutOfSync     Missing
```

### 2.3 Initial Application Sync
```bash
# Sync the API application (creates namespace and basic resources)
argocd app sync erp-api

# Check sync status
argocd app get erp-api
```

**Expected progression:**
1. `OutOfSync` → `Synced` (application created)
2. Resources appear in `erp` namespace
3. `Health Status` changes from `Missing` to `Healthy`

---

## Phase 3: Application Sync Monitoring

Monitor the API application until it's fully deployed and healthy.

### 3.1 Real-time Monitoring
```bash
# Watch application status in real-time
kubectl get application erp-api -n argocd -w

# Or monitor with ArgoCD CLI
argocd app get erp-api --watch
```

### 3.2 Resource Creation Verification
```bash
# Check if resources are being created in erp namespace
kubectl get all,ingress,secrets,pvc -n erp

# Monitor pod creation (this takes several minutes)
kubectl get pods -n erp -w

# Check service creation
kubectl get svc -n erp
```

### 3.3 Common Deployment Timeline
```bash
# Typical deployment sequence (5-10 minutes total):
# 1. Namespace created (immediate)
# 2. Secrets created (10-30 seconds)
# 3. ConfigMaps created (10-30 seconds)
# 4. Services created (10-30 seconds)
# 5. Deployments created (30-60 seconds)
# 6. Pods start (1-3 minutes)
# 7. Ingress created (30-60 seconds)
# 8. Certificates issued (2-5 minutes)
# 9. LoadBalancer assigned (2-5 minutes)
```

### 3.4 Wait for Full Deployment
```bash
# Wait for API deployment to be ready
kubectl wait --for=condition=available --timeout=600s deployment/erp-api-app -n erp

# Verify API pods are running
kubectl get pods -n erp -l app=erp-api-app
# Expected: Pods show "Running" with READY status
```

---

## Phase 4: Post-Deployment Verification

Once applications show `Synced` and `Healthy`, verify everything is working.

### 4.1 Application Status Check
```bash
# Get detailed application information
argocd app get erp-api --health

# Check application conditions
kubectl get application erp-api -n argocd -o jsonpath='{.status.conditions}'
```

### 4.2 Service Verification
```bash
# Check all deployed resources
kubectl get all,ingress,secrets,pvc -n erp

# Verify API deployment and service
kubectl get deployment erp-api-app -n erp
kubectl get service erp-api -n erp

# Check API ingress configuration
kubectl get ingress -n erp -o yaml
```

### 4.3 Certificate Verification
```bash
# Check certificate status
kubectl get certificates -n erp

# Verify certificate details
kubectl describe certificate erp-masterspace-tls -n erp

# Check certificate secret exists
kubectl get secret erp-masterspace-tls -n erp
```

### 4.4 DNS and SSL Testing
```bash
# Check DNS resolution for API
nslookup erpapi.masterspace.co.ke

# Get LoadBalancer IP
kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}'

# Test SSL certificate for API
echo | openssl s_client -servername erpapi.masterspace.co.ke -connect erpapi.masterspace.co.ke:443

# Test HTTPS connectivity
curl -k https://erpapi.masterspace.co.ke/api/v1/health/
```

### 4.5 API Health Checks
```bash
# Test API health endpoint
curl -k https://erpapi.masterspace.co.ke/api/v1/health/

# Or test via core health endpoint
curl -k https://erpapi.masterspace.co.ke/api/v1/core/health/

# Verify LoadBalancer IP assignment
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "LoadBalancer IP: $LB_IP"
```

---

## Phase 5: Troubleshooting & Maintenance

If any step fails, use these troubleshooting procedures.

### 5.1 Application Sync Issues
```bash
# Check ArgoCD application controller status
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Check application controller logs
kubectl logs -f deployment/argocd-application-controller -n argocd

# Check API application events
kubectl get events -n argocd --field-selector involvedObject.name=erp-api

# Check for stuck application
kubectl get application erp-api -n argocd -o jsonpath='{.status.sync.status}'
```

### 5.2 Resource Creation Issues
```bash
# Check if namespace exists
kubectl get namespace erp

# If missing, create it
kubectl create namespace erp

# Check ArgoCD server status
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server

# Check repo-server status (handles Git operations)
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server
```

### 5.3 Pod Startup Issues
```bash
# Check API pod logs for errors
kubectl logs -f deployment/erp-api-app -n erp

# Check API pod events
kubectl describe pod -n erp -l app=erp-api-app

# Check resource constraints
kubectl top pods -n erp -l app=erp-api-app
kubectl top nodes
```

### 5.4 Certificate Issues
```bash
# Check cert-manager status
kubectl get pods -n cert-manager

# Check certificate events
kubectl get events -n erp --field-selector involvedObject.kind=Certificate

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager -f

# Manual certificate renewal
kubectl annotate certificate erp-masterspace-tls -n erp cert-manager.io/issue-temporary-certificate="true"
```

### 5.5 Ingress and LoadBalancer Issues
```bash
# Check ingress controller status
kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller

# Check LoadBalancer service
kubectl describe svc ingress-nginx-controller -n ingress-nginx

# Check LoadBalancer events
kubectl get events -n ingress-nginx --field-selector involvedObject.name=ingress-nginx-controller

# Wait for LoadBalancer IP assignment
kubectl wait --for=condition=available --timeout=300s deployment/ingress-nginx-controller -n ingress-nginx
```

### 5.6 Network Connectivity Issues
```bash
# Test API service accessibility from within cluster
kubectl run test-pod --rm -i --tty --image curlimages/curl -- curl -k http://erp-api.erp.svc.cluster.local:80/api/v1/health/

# Port forward for local testing
kubectl port-forward svc/erp-api 8000:80 -n erp

# Test locally
curl http://localhost:8000/api/v1/health/
curl http://localhost:8000/api/v1/core/health/
```

### 5.7 Celery Worker Issues (Payslips Not Generated)
```bash
# Check if Celery workers are running
kubectl get pods -n erp -l component=celery-worker

# Check worker logs for errors
kubectl logs -n erp -l component=celery-worker --tail=100

# Check if workers can connect to Redis
kubectl exec -it -n erp deployment/erp-api-celery-worker -- celery -A ProcureProKEAPI inspect ping

# Check active tasks
kubectl exec -it -n erp deployment/erp-api-celery-worker -- celery -A ProcureProKEAPI inspect active

# Check registered tasks
kubectl exec -it -n erp deployment/erp-api-celery-worker -- celery -A ProcureProKEAPI inspect registered

# Restart workers if stuck
kubectl rollout restart deployment/erp-api-celery-worker -n erp

# Scale workers if needed
kubectl scale deployment/erp-api-celery-worker -n erp --replicas=4

# Check Redis queue length (should decrease as tasks are processed)
kubectl run redis-check --rm -i --tty --image redis:alpine -n erp -- redis-cli -h redis-master.erp.svc.cluster.local -a "$REDIS_PASSWORD" llen celery
```

### 5.8 WebSocket Connection Issues
```bash
# Check if Channels is configured to use Redis
kubectl get secret erp-api-env -n erp -o jsonpath='{.data.CHANNEL_BACKEND}' | base64 -d
# Expected: channels_redis.core.RedisChannelLayer

kubectl get secret erp-api-env -n erp -o jsonpath='{.data.CHANNEL_URL}' | base64 -d
# Expected: redis://:<password>@redis-master.erp.svc.cluster.local:6379/2

# Test WebSocket connection from browser console
# const ws = new WebSocket('wss://erp.masterspace.co.ke/ws/payroll/');
# ws.onopen = () => console.log('Connected');
# ws.onerror = (e) => console.error('Error:', e);

# Check Ingress for WebSocket support (upgrade headers)
kubectl describe ingress -n erp | grep -i upgrade
```

---

## Emergency Procedures

### Force Application Recreation
```bash
# Delete and recreate API application if it's stuck
kubectl delete application erp-api -n argocd

# Wait a moment, then recreate
kubectl apply -f apps/erp-api/app.yaml -n argocd

# Force sync
argocd app sync erp-api --force
```

### Application Rollback
```bash
# List available revisions
argocd app history erp-api

# Rollback to previous working version
argocd app rollback erp-api PREV
```

### Scale API Application
```bash
# Scale down for maintenance
kubectl scale deployment erp-api-app -n erp --replicas=0

# Scale back up
kubectl scale deployment erp-api-app -n erp --replicas=2
```

---

## Quick Reference Commands

### Status Check
```bash
# Quick status overview
kubectl get application erp-api -n argocd
kubectl get all,ingress -n erp
kubectl get certificates -n erp
```

### Health Check
```bash
# Test API endpoints
curl -k https://erpapi.masterspace.co.ke/api/v1/health/
curl -k https://erpapi.masterspace.co.ke/api/v1/core/health/
```

### Common Fixes
```bash
# Restart API application
kubectl rollout restart deployment/erp-api-app -n erp

# Force certificate renewal
kubectl annotate certificate erp-masterspace-tls -n erp cert-manager.io/issue-temporary-certificate="true"
```

---

## Support and Escalation

For issues not covered in this guide:

1. **Check ArgoCD Interface**: Access ArgoCD web UI for visual application status
2. **Review Application Logs**: Check both application and ArgoCD controller logs
3. **Consult System Documentation**: Refer to `devops-k8s/docs/pipelines.md` for additional procedures
4. **Contact Development Team**: Escalate complex issues requiring code or configuration changes

---

*This manual deployment guide provides a complete walkthrough from initial deployment to ongoing maintenance. Always attempt automated deployment first, and use this guide for troubleshooting or emergency manual operations.*
