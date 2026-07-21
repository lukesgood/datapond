# DataPond Scripts

Automation scripts for local development and self-hosted deployment.

> `quick-deploy.sh` defaults to `values-quicktest.yaml`; it is not the AWS production
> reference installer. Use `docs/DEPLOY_SINGLE_NODE.md` with
> `values-prod-single.yaml` for the current Terraform-backed AWS reference, or
> `values-foundation.yaml` for the lean Portable Core AWS starter.

## Quick Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `install-docker.sh` | Install Docker or nerdctl | `bash scripts/install-docker.sh` |
| `build-images.sh` | Build and import images | `bash scripts/build-images.sh` |
| `quick-deploy.sh` | One-command deployment | `bash scripts/quick-deploy.sh [--skip-build] [--values FILE]` |
| `validate-deployment.sh` | Run validation tests | `bash scripts/validate-deployment.sh` |
| `monitor-services.sh` | Monitor service health | `bash scripts/monitor-services.sh [--watch] [--logs]` |
| `deploy.sh` | Advanced Helm deployment | `bash scripts/deploy.sh values-dev.yaml` |
| `install-k3s.sh` | Install K3s cluster | `sudo bash scripts/install-k3s.sh` |

## Deployment Workflow

### First Time Setup

```bash
# 1. Install K3s (if not already installed)
sudo bash scripts/install-k3s.sh

# 2. Install Docker or nerdctl
bash scripts/install-docker.sh

# 3. Deploy everything
bash scripts/quick-deploy.sh
```

### Subsequent Deployments

```bash
# If images already built
bash scripts/quick-deploy.sh --skip-build

# Or rebuild and deploy
bash scripts/quick-deploy.sh
```

### Validation

```bash
# Run all tests
bash scripts/validate-deployment.sh

# Monitor continuously
bash scripts/monitor-services.sh --watch
```

## Script Details

### install-docker.sh

Installs Docker or nerdctl for building container images.

**Interactive menu:**
1. Docker (recommended, most compatible)
2. nerdctl (lightweight, containerd-native)

**Post-install:**
- Adds user to docker group
- Starts Docker daemon
- Verifies installation

### build-images.sh

Builds and imports DataPond images.

**Process:**
1. Detects docker or nerdctl
2. Builds backend image (Python 3.11 + FastAPI)
3. Builds frontend image (Node 20 + Next.js 15)
4. Saves to tar files
5. Imports to K3s containerd
6. Verifies with crictl

**Images created:**
- `datapond/backend:<chart appVersion>` (currently `2.3.0`, read from `helm/datapond/Chart.yaml`)
- `datapond/frontend:<chart appVersion>` (currently `2.3.0`, read from `helm/datapond/Chart.yaml`)

### quick-deploy.sh

One-command deployment script.

**Options:**
- `--skip-build`: Skip image building (use existing images)
- `--values FILE`: Use custom values file (default: values-quicktest.yaml)

**Steps:**
1. Build images (unless --skip-build)
2. Check K8s cluster
3. Deploy or upgrade Helm chart
4. Wait for pods to be ready
5. Initialize database
6. Show deployment status
7. Print access instructions

**Example:**
```bash
# Full deployment
bash scripts/quick-deploy.sh

# Use dev values
bash scripts/quick-deploy.sh --values values-dev.yaml

# Skip build
bash scripts/quick-deploy.sh --skip-build
```

### validate-deployment.sh

Comprehensive validation tests.

**Test Coverage:**
- Pod status (Running, restarts)
- Backend API health check
- Frontend accessibility
- Database connectivity and schema
- API endpoints
- Service-to-service networking

**Output:**
```
✓ Backend pod is running
✓ Backend API health check passed
✓ Database connection successful
...
Passed: 15 tests
All critical tests passed!
```

**Exit codes:**
- 0: All tests passed
- 1: One or more tests failed

### monitor-services.sh

Real-time service monitoring.

**Options:**
- `--watch` or `-w`: Continuous monitoring (refresh every 5s)
- `--logs` or `-l`: Show logs for failing pods

**Display:**
- Pod status (all pods)
- Resource usage (CPU/Memory)
- Node resources
- Services and ingress
- Pods with restarts
- Non-running pods
- Phase 1 core services status
- Recent events

**Example:**
```bash
# One-time check
bash scripts/monitor-services.sh

# Continuous monitoring
bash scripts/monitor-services.sh --watch

# With logs for failures
bash scripts/monitor-services.sh --logs --watch
```

### deploy.sh

Advanced Helm deployment script (legacy).

**Usage:**
```bash
bash scripts/deploy.sh values-dev.yaml
```

**Features:**
- Detects existing release
- Prompts for upgrade confirmation
- Shows differences
- Validates before deploy

**Note:** For most use cases, use `quick-deploy.sh` instead.

### install-k3s.sh

Installs K3s Kubernetes cluster.

**Usage:**
```bash
sudo bash scripts/install-k3s.sh
```

**What it does:**
- Installs K3s (lightweight Kubernetes)
- Configures kubectl
- Adds datapond.local to /etc/hosts
- Verifies installation

**Requirements:**
- Ubuntu/Debian Linux
- 4GB+ RAM
- 20GB+ disk space

## Common Scenarios

### Scenario 1: Fresh Installation

```bash
# Install K3s
sudo bash scripts/install-k3s.sh

# Install Docker
bash scripts/install-docker.sh
# Choose option 1

# Logout and login (for docker group)
# Or run: newgrp docker

# Deploy
bash scripts/quick-deploy.sh

# Validate
bash scripts/validate-deployment.sh
```

### Scenario 2: Code Changes (Rebuild)

```bash
# Rebuild images
bash scripts/build-images.sh

# Redeploy
bash scripts/quick-deploy.sh --skip-build

# Or combine
bash scripts/quick-deploy.sh
```

### Scenario 3: Configuration Changes

```bash
# Edit values file
nano helm/datapond/values-quicktest.yaml

# Deploy with changes
bash scripts/quick-deploy.sh --skip-build --values values-quicktest.yaml
```

### Scenario 4: Troubleshooting

```bash
# Check current status
bash scripts/monitor-services.sh

# Run validation
bash scripts/validate-deployment.sh

# Watch logs
bash scripts/monitor-services.sh --watch --logs

# Manual checks
kubectl get pods -n datapond
kubectl logs -n datapond -l app=backend
kubectl describe pod -n datapond <pod-name>
```

### Scenario 5: Full Reset

```bash
# Uninstall
helm uninstall datapond -n datapond
kubectl delete namespace datapond

# Reinstall
bash scripts/quick-deploy.sh
```

## Environment Variables

These scripts respect the following environment variables:

- `KUBECONFIG`: Path to kubectl config (default: ~/.kube/config)
- `HELM_HOME`: Helm home directory (default: ~/.helm)

## Exit Codes

All scripts follow standard exit code conventions:

- `0`: Success
- `1`: General error
- `2`: Missing dependency
- `3`: Validation failure

## Prerequisites

- **Kubernetes:** K3s 1.25+ or equivalent
- **Helm:** 3.12+
- **kubectl:** Configured and accessible
- **Docker or nerdctl:** For building images
- **bash:** 4.0+

## Support

- **Documentation:** `/home/luke/datapond/docs/`
- **Quick Start:** `/home/luke/datapond/docs/QUICK_START.md`
- **Troubleshooting:** `/home/luke/datapond/docs/TROUBLESHOOTING.md`
- **Architecture:** `/home/luke/datapond/docs/ARCHITECTURE.md`

## Notes

- All scripts are idempotent (safe to run multiple times)
- Scripts use color output for better readability
- Most scripts require no sudo (except install-k3s.sh and K3s image import)
- Scripts validate prerequisites before running
- Detailed error messages guide troubleshooting

## Development

To add a new script:

1. Create script in `/home/luke/datapond/scripts/`
2. Make executable: `chmod +x script.sh`
3. Add header with description
4. Use color output functions (RED, GREEN, YELLOW, BLUE)
5. Add to this README
6. Test thoroughly
