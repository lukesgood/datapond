# DataPond Phase 1 - Quick Start Guide

This guide will help you deploy and validate DataPond Phase 1 (Frontend + Backend + Database) on a Kubernetes cluster.

## Prerequisites

- Kubernetes 1.25+ (K3s recommended)
- Helm 3.12+
- kubectl configured
- Docker or nerdctl (for building images)
- 8GB+ RAM available

## Quick Deployment (5 minutes)

### Option 1: One-Command Deployment

```bash
cd /home/luke/datapond
bash scripts/quick-deploy.sh
```

This will:
1. Build Docker images for backend and frontend
2. Import them into K3s
3. Deploy Helm chart
4. Initialize database schemas
5. Wait for all pods to be ready

### Option 2: Step-by-Step Deployment

#### Step 1: Build Images

```bash
bash scripts/build-images.sh
```

This builds and imports:
- `datapond/backend:latest`
- `datapond/frontend:latest`

#### Step 2: Deploy to Kubernetes

```bash
# First install (creates namespace)
helm install datapond helm/datapond \
  --namespace datapond \
  --create-namespace \
  --values helm/datapond/values-quicktest.yaml \
  --wait \
  --timeout 10m

# Or upgrade existing
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-quicktest.yaml \
  --wait \
  --timeout 10m
```

#### Step 3: Initialize Database

```bash
# Get postgres pod name
POSTGRES_POD=$(kubectl get pod -n datapond -l app=postgres -o jsonpath="{.items[0].metadata.name}")

# Run init scripts
kubectl exec -n datapond $POSTGRES_POD -- psql -U datapond -d datapond -f /docker-entrypoint-initdb.d/init.sql

# Or use the backend init script
cd backend
bash init_database.sh
```

#### Step 4: Validate Deployment

```bash
bash scripts/validate-deployment.sh
```

This tests:
- All pods are running
- Backend API is accessible
- Frontend is accessible
- Database connectivity and schema
- Service-to-service networking

## Accessing Services

### Method 1: Port Forwarding (Development)

```bash
# Frontend (UI)
kubectl port-forward -n datapond svc/frontend 3000:3000
# Open: http://localhost:3000

# Backend (API)
kubectl port-forward -n datapond svc/backend 8000:8000
# Open: http://localhost:8000/docs (API documentation)

# Postgres (Database)
kubectl port-forward -n datapond svc/postgres 5432:5432
# Connect: psql -h localhost -U datapond -d datapond
```

### Method 2: Ingress (Production)

Add to `/etc/hosts`:
```
127.0.0.1 datapond.local
```

Access via:
- Frontend: http://datapond.local
- Backend: http://datapond.local/api

## Monitoring Services

### Real-time Monitoring

```bash
# One-time snapshot
bash scripts/monitor-services.sh

# Continuous monitoring (refresh every 5s)
bash scripts/monitor-services.sh --watch

# Show logs for failing pods
bash scripts/monitor-services.sh --logs
```

### Manual Checks

```bash
# Pod status
kubectl get pods -n datapond

# Pod logs
kubectl logs -n datapond -l app=backend
kubectl logs -n datapond -l app=frontend
kubectl logs -n datapond -l app=postgres

# Pod resources
kubectl top pods -n datapond

# Service status
kubectl get svc -n datapond

# Recent events
kubectl get events -n datapond --sort-by='.lastTimestamp'
```

## Testing the Application

### 1. Health Check

```bash
curl http://localhost:8000/api/health
# Expected: {"status":"healthy"}
```

### 2. List Services

```bash
curl http://localhost:8000/api/services | jq
```

### 3. Dashboard Stats

```bash
curl http://localhost:8000/api/dashboard/stats | jq
```

### 4. Create a Connector

```bash
curl -X POST http://localhost:8000/api/connectors \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-postgres",
    "type": "postgresql",
    "connection_string": "postgresql://user:pass@host:5432/db"
  }'
```

### 5. Execute Query

```bash
curl -X POST http://localhost:8000/api/queries/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT 1 as test",
    "connector_name": "test-postgres"
  }'
```

### 6. Browse Catalog

```bash
curl http://localhost:8000/api/catalog/tables | jq
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod -n datapond <pod-name>

# Check logs
kubectl logs -n datapond <pod-name> --previous

# Check events
kubectl get events -n datapond --field-selector involvedObject.name=<pod-name>
```

### Image Pull Errors

```bash
# Rebuild and reimport images
bash scripts/build-images.sh

# Verify images are available
sudo crictl images | grep datapond
```

### Database Connection Errors

```bash
# Check postgres is running
kubectl get pod -n datapond -l app=postgres

# Test connection from backend pod
BACKEND_POD=$(kubectl get pod -n datapond -l app=backend -o jsonpath="{.items[0].metadata.name}")
kubectl exec -n datapond $BACKEND_POD -- env | grep DATABASE_URL

# Connect to postgres directly
kubectl exec -n datapond -it postgres-0 -- psql -U datapond -d datapond
```

### Backend API Not Responding

```bash
# Check backend logs
kubectl logs -n datapond -l app=backend -f

# Check backend pod status
kubectl describe pod -n datapond -l app=backend

# Restart backend
kubectl rollout restart deployment/backend -n datapond
```

### Frontend Not Loading

```bash
# Check frontend logs
kubectl logs -n datapond -l app=frontend -f

# Check environment variables
FRONTEND_POD=$(kubectl get pod -n datapond -l app=frontend -o jsonpath="{.items[0].metadata.name}")
kubectl exec -n datapond $FRONTEND_POD -- env | grep NEXT_PUBLIC
```

## Cleanup

### Remove Deployment (Keep Namespace)

```bash
helm uninstall datapond -n datapond
```

### Full Cleanup (Remove Everything)

```bash
helm uninstall datapond -n datapond
kubectl delete namespace datapond
```

### Rebuild from Scratch

```bash
# Full cleanup
helm uninstall datapond -n datapond
kubectl delete namespace datapond

# Rebuild and deploy
bash scripts/quick-deploy.sh
```

## Configuration Options

### Values Files

- `values.yaml` - Base configuration (all defaults)
- `values-dev.yaml` - Development (minimal resources)
- `values-quicktest.yaml` - Quick test (Phase 1 only)
- `values-prod.yaml` - Production (HA, full resources)

### Custom Deployment

```bash
# Deploy with custom values
bash scripts/quick-deploy.sh --values values-dev.yaml

# Skip image build (if already built)
bash scripts/quick-deploy.sh --skip-build
```

### Resource Limits

Edit `helm/datapond/values-quicktest.yaml`:

```yaml
backend:
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

frontend:
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

## Next Steps

After successful deployment:

1. **Explore the UI**: Open http://localhost:3000 and browse the dashboard
2. **Try the API**: Open http://localhost:8000/docs for interactive API docs
3. **Create Connectors**: Add data sources via the UI or API
4. **Run Queries**: Execute SQL queries against your data sources
5. **Browse Catalog**: Explore available tables and schemas

## Support

- Documentation: `/home/luke/datapond/docs/`
- Troubleshooting: `/home/luke/datapond/docs/TROUBLESHOOTING.md`
- Architecture: `/home/luke/datapond/docs/ARCHITECTURE.md`
- Scripts: `/home/luke/datapond/scripts/`

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `build-images.sh` | Build and import Docker images | `bash scripts/build-images.sh` |
| `quick-deploy.sh` | One-command deployment | `bash scripts/quick-deploy.sh [--skip-build] [--values FILE]` |
| `validate-deployment.sh` | Run validation tests | `bash scripts/validate-deployment.sh` |
| `monitor-services.sh` | Monitor service health | `bash scripts/monitor-services.sh [--watch] [--logs]` |
| `deploy.sh` | Advanced Helm deployment | `bash scripts/deploy.sh values-dev.yaml` |

## Phase 1 Architecture

```
┌─────────────────┐
│   Frontend      │  Next.js 15 + React 19
│   (Port 3000)   │  Unified Management UI
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Backend       │  FastAPI + Python 3.11
│   (Port 8000)   │  REST API
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   PostgreSQL    │  Database
│   (Port 5432)   │  Schemas: connectors, queries, auth
└─────────────────┘
```

All services run in the `datapond` namespace with full observability and monitoring.
