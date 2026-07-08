#!/bin/bash
# Build and import Docker images for DataPond into K3s
# This script builds backend and frontend images and imports them into containerd

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

# Check if docker or nerdctl is available
if command -v docker &> /dev/null; then
    BUILD_CMD="docker"
    SAVE_CMD="docker save"
    log_info "Using Docker for building images"
elif command -v nerdctl &> /dev/null; then
    BUILD_CMD="nerdctl"
    SAVE_CMD="nerdctl save"
    log_info "Using nerdctl for building images"
else
    log_error "Neither docker nor nerdctl found. Please install Docker or nerdctl."
    exit 1
fi

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

# Check if .next exists, if not run npm install and build
if [ ! -d ".next" ]; then
    log_warning ".next directory not found. Running npm install and build..."
    npm install
    npm run build
fi

$BUILD_CMD build -t datapond/frontend:$APPVER .
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

# Clean up tar files
rm -f /tmp/backend.tar /tmp/frontend.tar

log_success "Images imported into K3s successfully"

# List imported images
log_info "Verifying imported images:"
sudo crictl images | grep datapond || log_warning "Images not found in crictl, but may still be available"

log_success "Build complete! Images are ready for deployment."
