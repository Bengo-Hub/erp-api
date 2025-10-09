# Bengo ERP System - Infrastructure as Code (IaC) & CI/CD Pipeline

Documentation
-------------

- Start here: [docs/INDEX.md](docs/INDEX.md)
- Quick links: [Docker](docs/DOCKERREADME.md)

┌────────────────────────────────────────────────────────────────────────────┐
│                            🧑‍💼 Users (Web & Mobile)                         │
│                                                                            │
│   - Admins, Managers, Staff                                                │
│   - Access via Browsers or Mobile Devices                                  │
└────────────────────────────────────────────────────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────────────────────────┐
│                            🌐 Frontend (Vue.js 3)                          │
│                                                                            │
│   - Vue Router for SPA navigation                                          │
│   - Pinia for state management                                             │
│   - Axios for API calls                                                    │
│   - TailwindCSS for UI styling                                             │
│   - Vite for build tooling                                                 │
│   - Role-based access control                                              │
└────────────────────────────────────────────────────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────────────────────────┐
│                            🔐 API Gateway Layer                            │
│                                                                            │
│   - Nginx or Traefik as reverse proxy                                      │
│   - Handles SSL termination (Let's Encrypt)                                │
│   - Routes requests to appropriate services                                │
│   - Implements rate limiting and caching                                   │
└────────────────────────────────────────────────────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          🐍 Backend (Django + DRF)                         │
│                                                                            │
│   - Django REST Framework for API endpoints                                │
│   - PostgreSQL as the primary database                                     │
│   - Celery with Redis for background tasks                                 │
│   - Django Channels for real-time features                                 │
│   - Modular apps: Accounts, Inventory, Sales, HR, Finance, etc.            │
│   - JWT authentication (SimpleJWT)                                         │
│   - drf-spectacular for API documentation                                  │
└────────────────────────────────────────────────────────────────────────────┘

This repository contains the Bengo ERP application with a complete Infrastructure as Code (IaC) configuration for automated deployment, testing, and operations using modern DevOps practices.

## Architecture Overview

The Bengo ERP system consists of:

- **Django REST API Backend**: Python-based API with PostgreSQL database
- **Vue.js Frontend**: Modern SPA with PWA capabilities
- **Containerized Deployment**: Docker containers for consistent environments
- **Kubernetes Orchestration**: Full K8s deployment with scalability and resilience
- **CI/CD Pipeline**: Automated testing, building, and deployment
- **Infrastructure as Code**: Terraform, Ansible, and Kubernetes manifests
- **Multi-environment Support**: Development, staging, and production environments

## Infrastructure and Deployment Stack

### Database
- **PostgreSQL**: Primary database for all application data
- **Redis**: For caching, session management, and message queue

### Container Orchestration
- **Kubernetes**: For orchestrating containers, scaling, and resilience
- **Docker**: Container runtime for packaging applications

### CI/CD Tools
- **GitHub Actions**: Primary CI/CD pipeline for automated builds and tests
- **Jenkins**: Optional alternative CI/CD solution

### Infrastructure Provisioning
- **Terraform**: For provisioning infrastructure on Contabo VPS

## Project Documentation

### Strategic Planning
- **[Project Plan](plan.md)**: Comprehensive project overview, current state analysis, and strategic development plan
- **[Task Breakdown](docs/task-breakdown.md)**: Detailed task breakdown with priorities and implementation phases
- **[Kenyan Market Research](docs/kenyan-erp-market-research.md)**: In-depth analysis of the Kenyan ERP market and competitive landscape
- **[Kenyan Market Features](docs/kenyan-market-features.md)**: Detailed feature breakdown for the Kenyan market with existing and missing features

### Architecture & Development
- **[Architecture Overview](docs/architecture-overview.md)**: High-level architecture analysis and refactoring approach
- **[Project Structure](docs/project-structure.md)**: Detailed project structure and modular organization
- **[Refactoring Guidelines](docs/refactoring-guidelines.md)**: Comprehensive refactoring strategy and implementation guidelines
- **[Implementation Roadmap](docs/implementation-roadmap.md)**: Detailed 20-week implementation plan with phases and deliverables
- **Ansible**: For configuration management

### Monitoring & Operations
- **Kubernetes Health Probes**: For monitoring application health
- **Automated Rollbacks**: Fail-safe deployment with version tracking

## Directory Structure

### Infrastructure & Deployment
- `/iac/Dockerfile` - Multi-stage Dockerfile for UI and API
- `/iac/docker-compose.yml` - Docker Compose for local development
- `/iac/nginx.conf` - Nginx configuration for routing traffic
- `/iac/k8s/` - Kubernetes manifests for orchestration
- `/iac/pwa/` - Progressive Web App configuration files
- `/iac/terraform/` - Terraform configurations for Contabo VPS
- `/iac/ansible/` - Ansible playbooks for server configuration
- `/iac/jenkins/` - Jenkins pipeline configurations
- `/iac/deploy-production.sh` - Production deployment script
- `/iac/rollback.sh` - Rollback mechanism for failed deployments

### CI/CD Pipeline
- `/.github/workflows/` - GitHub Actions workflow definitions

### Application Components
- `/ERPAPI/` - Django REST API backend
- `/ERPUI/` - Vue.js frontend application

## Prerequisites

### For Local Development
- Docker and Docker Compose
- kubectl for Kubernetes interaction
- Node.js and npm for UI development
- Python 3.12+ for API development

### For Production Deployment
- Contabo VPS or similar server
- SSH access to deployment server
- Docker registry access (e.g., Docker Hub)
- GitHub repository with Secrets configured

## Development Environment Setup

### Local Development with Docker Compose

For quick local development without Kubernetes:

```powershell
# Windows
cd d:\Projects\BengoBox\BengoERP\iac
docker-compose up -d

# Linux/macOS
cd /path/to/BengoERP/iac
docker-compose up -d
```

This starts:
- PostgreSQL database on port 5432
- Redis cache on port 6379
- Bengo ERP application on port 8080 (UI) and 8000 (API)

### Local Development with Kubernetes

For testing with full Kubernetes orchestration locally:

```powershell
# Windows
cd d:\Projects\BengoBox\BengoERP\iac
.\deploy-local.ps1

# Linux/macOS
cd /path/to/BengoERP/iac
chmod +x deploy-local.sh
./deploy-local.sh
```

## CI/CD Pipeline

The project uses GitHub Actions as the primary CI/CD pipeline, with an optional Jenkins integration.

### GitHub Actions Workflow

The CI/CD pipeline (`.github/workflows/ci-cd.yml`) includes:

1. **Testing Stage**:
   - Runs unit and integration tests for both API and UI components
   - Ensures code quality with linting and static analysis

2. **Build Stage**:
   - Builds Docker images for the application
   - Tags images with the Git commit SHA for version tracking
   - Pushes images to Docker Hub

3. **Deployment Stage**:
   - Connects to the Contabo VPS via SSH
   - Deploys the application using Kubernetes
   - Performs health checks to ensure successful deployment
   - Implements automatic rollback if deployment fails

### Required GitHub Secrets

For the CI/CD pipeline to function properly, add these secrets to your GitHub repository:

| Secret Name | Description |
|-------------|-------------|
| `DOCKER_HUB_USERNAME` | Docker Hub username for image registry |
| `DOCKER_HUB_TOKEN` | Docker Hub access token |
| `DEPLOY_HOST` | Hostname/IP of the Contabo VPS |
| `DEPLOY_USER` | SSH username for server access |
| `DEPLOY_SSH_KEY` | Private SSH key for authentication |
| `SSH_PORT` | SSH port (default: 22) |
| `DB_PASSWORD` | PostgreSQL database password |
| `REDIS_PASSWORD` | Redis password |
| `DJANGO_SECRET_KEY` | Django application secret key |

## Infrastructure Provisioning

### Terraform for Server Provisioning

The Terraform configuration in `/iac/terraform/` automates the provisioning of the Contabo VPS:

```bash
cd /path/to/BengoERP/iac/terraform
terraform init
terraform apply
```

This creates a server with:
- Ubuntu 22.04 LTS
- Docker and containerd
- Kubernetes utilities (kubectl, kubeadm, kubelet)
- Necessary networking configuration

### Ansible for Configuration Management

Ansible playbooks in `/iac/ansible/` automate server configuration:

```bash
cd /path/to/BengoERP/iac/ansible
ansible-playbook -i inventory.yml playbooks/main.yml
```

This configures:
- System packages and dependencies
- Security hardening
- Docker and Kubernetes setup
- Monitoring tools

## Production Deployment

### Manual Deployment

For manual deployment to the Contabo VPS:

```bash
cd /path/to/BengoERP/iac
chmod +x deploy-production.sh
./deploy-production.sh
```

The script:
1. Pulls the latest Docker images
2. Applies Kubernetes manifests
3. Waits for services to be ready
4. Verifies deployment health

### Automated Deployment via CI/CD

The recommended approach is using the GitHub Actions CI/CD pipeline:

1. Push changes to the `staging` branch for testing
2. Once verified, merge to `main` for production deployment
3. The CI/CD pipeline automatically deploys to production

### Rollback Mechanism

If a deployment fails, use the rollback script:

```bash
cd /path/to/BengoERP/iac
chmod +x rollback.sh
./rollback.sh <previous-version>
```

This reverts to the specified previous version of the application.

## Kubernetes Resources

The Kubernetes deployment in `/iac/k8s/` includes:

- **Namespace**: `bengo-erp` for isolation
- **Deployments**:
  - `erp-deployment.yaml`: Main application deployment
  - `postgres-deployment.yaml`: PostgreSQL database
  - `redis-deployment.yaml`: Redis cache
- **Services**: For internal and external access
- **ConfigMaps**: For environment-specific configuration
- **Secrets**: For sensitive information
- **PersistentVolumeClaims**: For database storage

## Scaling and Operations

### Horizontal Scaling

Scale the application horizontally:

```bash
kubectl scale deployment bengo-erp -n bengo-erp --replicas=3
```

### Common Maintenance Operations

```bash
# View application logs
kubectl logs -f deployment/bengo-erp -n bengo-erp

# Check pod status
kubectl get pods -n bengo-erp

# Restart a deployment
kubectl rollout restart deployment/bengo-erp -n bengo-erp

# Execute commands in a pod
kubectl exec -it <pod-name> -n bengo-erp -- /bin/bash

# View service details
kubectl get svc -n bengo-erp
```

### Monitoring and Health Checks

The application includes health check endpoints:
- API: `/api/health/`
- Database connectivity checks
- Redis connectivity checks

These are used by Kubernetes probes for automatic remediation.

## Security Best Practices

- **Secrets Management**: All sensitive information is stored in Kubernetes Secrets or GitHub Secrets
- **Network Policies**: Restrict pod-to-pod communication for security
- **RBAC**: Role-Based Access Control for Kubernetes resources
- **TLS**: All production traffic is encrypted with TLS
- **Regular Updates**: Dependencies are updated regularly via the CI/CD pipeline

## Progressive Web App (PWA)

The Bengo ERP UI is configured as a Progressive Web App:

1. Visit the application in a supported browser
2. Click the "Install" button in the address bar
3. The app will install on your device and be available offline

## Troubleshooting

### Common Issues and Solutions

- **Database Connection Issues**: Check PostgreSQL pod status and credentials
- **CI/CD Pipeline Failures**: Verify GitHub Secrets are properly configured
- **Kubernetes Pod Crashes**: Check pod logs for application errors
- **Deployment Failures**: Use the rollback script to return to a stable version

## Project Documentation

### Strategic Planning
- **[Development Plan](plan.md)** - Comprehensive analysis and strategic roadmap for completing the Bengo ERP system
- **[Task Breakdown](docs/task-breakdown.md)** - Detailed task breakdown with specific implementation tasks and timelines
- **[Market Research](docs/kenyan-erp-market-research.md)** - In-depth analysis of the Kenyan ERP market and competitive landscape

### Technical Documentation
- **[API Documentation](ERPAPI/README.md)** - Backend API documentation and setup guide
- **[Frontend Documentation](ERPUI/README.md)** - Frontend application documentation
- **[Docker Setup](ERPAPI/DOCKERREADME.md)** - Docker containerization guide

## Contributing

Contributions to the Bengo ERP project are welcome. Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
