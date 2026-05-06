#!/bin/bash
# Build and import Docker images for DataPond into K3s (with sudo)
# Temporary script until docker group permissions are applied

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

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
log_info "Building backend image..."
cd "$PROJECT_ROOT/backend"
$BUILD_CMD build -t datapond/backend:latest .
if [ $? -eq 0 ]; then
    log_success "Backend image built successfully"
else
    log_error "Failed to build backend image"
    exit 1
fi

# Build frontend image
log_info "Building frontend image..."
cd "$PROJECT_ROOT/frontend"

# Check if .next exists, if not run npm install and build
if [ ! -d ".next" ]; then
    log_warning ".next directory not found. Running npm install and build..."
    npm install
    npm run build
fi

$BUILD_CMD build -t datapond/frontend:latest .
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
$SAVE_CMD datapond/backend:latest -o /tmp/backend.tar
$SAVE_CMD datapond/frontend:latest -o /tmp/frontend.tar

# Import into K3s containerd
sudo k3s ctr images import /tmp/backend.tar
sudo k3s ctr images import /tmp/frontend.tar

# Clean up tar files
rm -f /tmp/backend.tar /tmp/frontend.tar

log_success "Images imported into K3s successfully"

# Restart deployments to pick up new images
log_info "Restarting deployments..."
kubectl rollout restart deployment/backend deployment/frontend -n datapond
kubectl rollout status deployment/backend -n datapond --timeout=90s
kubectl rollout status deployment/frontend -n datapond --timeout=90s

log_success "Build and deploy complete! Both services are running with the latest images."
log_warning "Note: For permanent fix, logout and login again to apply docker group permissions"
