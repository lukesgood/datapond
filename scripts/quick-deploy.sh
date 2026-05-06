#!/bin/bash
# Quick deployment script for DataPond Phase 1
# Builds images, deploys to K8s, and initializes database

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

# Parse arguments
SKIP_BUILD=false
VALUES_FILE="values-quicktest.yaml"

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --values)
            VALUES_FILE="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--skip-build] [--values values-file.yaml]"
            exit 1
            ;;
    esac
done

log_info "=========================================="
log_info "DataPond Phase 1 Quick Deployment"
log_info "=========================================="

# Step 1: Build images (unless skipped)
if [ "$SKIP_BUILD" = false ]; then
    log_info "Step 1: Building Docker images..."
    bash "$SCRIPT_DIR/build-images.sh"
else
    log_warning "Skipping image build (--skip-build flag set)"
fi

# Step 2: Check K8s cluster
log_info "Step 2: Checking K8s cluster..."
if ! kubectl cluster-info &> /dev/null; then
    log_error "Kubernetes cluster not accessible. Is K3s running?"
    exit 1
fi
log_success "K8s cluster is accessible"

# Step 3: Deploy Helm chart
log_info "Step 3: Deploying Helm chart..."
cd "$PROJECT_ROOT"

if helm list -n datapond | grep -q datapond; then
    log_info "Existing release found. Upgrading..."
    helm upgrade datapond helm/datapond \
        --namespace datapond \
        --values "helm/datapond/$VALUES_FILE" \
        --wait \
        --timeout 10m
else
    log_info "No existing release. Installing fresh..."
    helm install datapond helm/datapond \
        --namespace datapond \
        --create-namespace \
        --values "helm/datapond/$VALUES_FILE" \
        --wait \
        --timeout 10m
fi

log_success "Helm deployment complete"

# Step 4: Wait for pods to be ready
log_info "Step 4: Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=backend -n datapond --timeout=300s || log_warning "Backend pods not ready yet"
kubectl wait --for=condition=ready pod -l app=frontend -n datapond --timeout=300s || log_warning "Frontend pods not ready yet"
kubectl wait --for=condition=ready pod -l app=postgres -n datapond --timeout=300s || log_warning "Postgres pod not ready yet"

# Step 5: Initialize database
log_info "Step 5: Initializing database schemas..."
sleep 10  # Give postgres a moment to fully start

# Get postgres pod name
POSTGRES_POD=$(kubectl get pod -n datapond -l app=postgres -o jsonpath="{.items[0].metadata.name}")

if [ -z "$POSTGRES_POD" ]; then
    log_error "Postgres pod not found"
    exit 1
fi

# Check if database is initialized
log_info "Checking database initialization..."
DB_EXISTS=$(kubectl exec -n datapond "$POSTGRES_POD" -- psql -U datapond -d datapond -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='connectors' LIMIT 1" 2>/dev/null || echo "")

if [ -z "$DB_EXISTS" ]; then
    log_info "Database not initialized. Running init script..."

    # Copy init script to postgres pod
    kubectl cp "$PROJECT_ROOT/backend/app/db/init.sql" "datapond/$POSTGRES_POD:/tmp/init.sql" 2>/dev/null || log_warning "Init script not found, will use backend API"

    # Run init script
    kubectl exec -n datapond "$POSTGRES_POD" -- psql -U datapond -d datapond -f /tmp/init.sql 2>/dev/null || log_info "Using backend API to initialize"

    log_success "Database initialized"
else
    log_info "Database already initialized"
fi

# Step 6: Show deployment status
log_info "Step 6: Deployment status"
echo ""
kubectl get pods -n datapond
echo ""

# Step 7: Port forwarding instructions
log_info "=========================================="
log_success "Deployment complete!"
log_info "=========================================="
echo ""
log_info "Access services:"
echo "  Frontend:  kubectl port-forward -n datapond svc/frontend 3000:3000"
echo "             Then open: http://localhost:3000"
echo ""
echo "  Backend:   kubectl port-forward -n datapond svc/backend 8000:8000"
echo "             Then open: http://localhost:8000/docs"
echo ""
echo "  Postgres:  kubectl port-forward -n datapond svc/postgres 5432:5432"
echo ""
log_info "Run validation tests:"
echo "  bash scripts/validate-deployment.sh"
echo ""
log_info "Monitor services:"
echo "  bash scripts/monitor-services.sh"
echo ""
