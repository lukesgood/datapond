#!/bin/bash
# Build and import Docker images for DataPond into K3s (with sudo)
# Temporary script until docker group permissions are applied

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APPVER="$(grep '^appVersion:' "$PROJECT_ROOT/helm/datapond/Chart.yaml" | tr -d ' "' | cut -d: -f2)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Use sudo for docker commands
BUILD_CMD="sudo docker"
SAVE_CMD="sudo docker save"

log_info "Using Docker with sudo (temporary workaround)"

# Build backend image
# Backend Dockerfile needs repo-root context + --target (COPY backend/... and ee/backend/...).
log_info "Building backend image..."
cd "$PROJECT_ROOT"
$BUILD_CMD build -t datapond/backend:$APPVER -f backend/Dockerfile --target enterprise .
if [ $? -eq 0 ]; then
    log_success "Backend image built successfully"
else
    log_error "Failed to build backend image"
    exit 1
fi

# Build frontend image
log_info "Building frontend image..."
cd "$PROJECT_ROOT/frontend"

log_info "Running npm install and build..."
REAL_USER="${SUDO_USER:-luke}"
# Find nvm node version dir
NVM_NODE_DIR=$(ls -d /home/$REAL_USER/.nvm/versions/node/*/bin 2>/dev/null | tail -1)
if [ -z "$NVM_NODE_DIR" ]; then
    log_error "nvm node not found for user $REAL_USER"
    exit 1
fi
NPM_BIN="$NVM_NODE_DIR/npm"
log_info "Using npm at: $NPM_BIN (node dir: $NVM_NODE_DIR)"
su -c "export PATH=$NVM_NODE_DIR:\$PATH; cd $PROJECT_ROOT/frontend && $NVM_NODE_DIR/npm install && $NVM_NODE_DIR/npm run build" "$REAL_USER"

$BUILD_CMD build --no-cache -t datapond/frontend:$APPVER .
if [ $? -eq 0 ]; then
    log_success "Frontend image built successfully"
else
    log_error "Failed to build frontend image"
    exit 1
fi

# Import images into K3s (containerd)
log_info "Importing images into K3s..."
cd "$PROJECT_ROOT"

# Save images to tar files
$SAVE_CMD datapond/backend:$APPVER -o /tmp/backend.tar
$SAVE_CMD datapond/frontend:$APPVER -o /tmp/frontend.tar

# Import into K3s containerd
sudo k3s ctr images import /tmp/backend.tar
sudo k3s ctr images import /tmp/frontend.tar

# Clean up tar files (use sudo since they were created by sudo docker save)
sudo rm -f /tmp/backend.tar /tmp/frontend.tar

log_success "Images imported into K3s successfully"

# Restart deployments to pick up new images
log_info "Restarting deployments..."
kubectl rollout restart deployment/backend deployment/frontend -n datapond
kubectl rollout status deployment/backend -n datapond --timeout=90s
kubectl rollout status deployment/frontend -n datapond --timeout=90s

log_success "Build and deploy complete! Both services are running with the latest images."
log_warning "Note: For permanent fix, logout and login again to apply docker group permissions"
