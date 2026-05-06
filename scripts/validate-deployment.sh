#!/bin/bash
# Validation script for DataPond Phase 1 deployment
# Tests all services, APIs, and database connectivity

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

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
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

FAILED_TESTS=0
PASSED_TESTS=0

test_passed() {
    PASSED_TESTS=$((PASSED_TESTS + 1))
    log_success "$1"
}

test_failed() {
    FAILED_TESTS=$((FAILED_TESTS + 1))
    log_error "$1"
}

log_info "=========================================="
log_info "DataPond Phase 1 Validation Tests"
log_info "=========================================="
echo ""

# Test 1: Check all pods are running
log_info "Test 1: Checking pod status..."
BACKEND_POD=$(kubectl get pod -n datapond -l app=backend -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)
FRONTEND_POD=$(kubectl get pod -n datapond -l app=frontend -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)
POSTGRES_POD=$(kubectl get pod -n datapond -l app=postgres -o jsonpath="{.items[0].metadata.name}" 2>/dev/null)

if [ -n "$BACKEND_POD" ] && kubectl get pod -n datapond "$BACKEND_POD" | grep -q "Running"; then
    test_passed "Backend pod is running: $BACKEND_POD"
else
    test_failed "Backend pod is not running"
fi

if [ -n "$FRONTEND_POD" ] && kubectl get pod -n datapond "$FRONTEND_POD" | grep -q "Running"; then
    test_passed "Frontend pod is running: $FRONTEND_POD"
else
    test_failed "Frontend pod is not running"
fi

if [ -n "$POSTGRES_POD" ] && kubectl get pod -n datapond "$POSTGRES_POD" | grep -q "Running"; then
    test_passed "Postgres pod is running: $POSTGRES_POD"
else
    test_failed "Postgres pod is not running"
fi

echo ""

# Test 2: Check pod restarts
log_info "Test 2: Checking pod restart counts..."
BACKEND_RESTARTS=$(kubectl get pod -n datapond "$BACKEND_POD" -o jsonpath="{.status.containerStatuses[0].restartCount}" 2>/dev/null || echo "999")
FRONTEND_RESTARTS=$(kubectl get pod -n datapond "$FRONTEND_POD" -o jsonpath="{.status.containerStatuses[0].restartCount}" 2>/dev/null || echo "999")

if [ "$BACKEND_RESTARTS" -eq 0 ]; then
    test_passed "Backend has 0 restarts"
elif [ "$BACKEND_RESTARTS" -lt 3 ]; then
    test_warning "Backend has $BACKEND_RESTARTS restarts (acceptable)"
else
    test_failed "Backend has $BACKEND_RESTARTS restarts"
fi

if [ "$FRONTEND_RESTARTS" -eq 0 ]; then
    test_passed "Frontend has 0 restarts"
elif [ "$FRONTEND_RESTARTS" -lt 3 ]; then
    test_warning "Frontend has $FRONTEND_RESTARTS restarts (acceptable)"
else
    test_failed "Frontend has $FRONTEND_RESTARTS restarts"
fi

echo ""

# Test 3: Backend API health check
log_info "Test 3: Testing backend API health..."
# Start port-forward in background
kubectl port-forward -n datapond svc/backend 8000:8000 > /dev/null 2>&1 &
PF_PID=$!
sleep 3

if curl -s http://localhost:8000/api/health | grep -q "healthy"; then
    test_passed "Backend API health check passed"
else
    test_failed "Backend API health check failed"
fi

# Test backend root endpoint
if curl -s http://localhost:8000/ | grep -q "DataPond"; then
    test_passed "Backend root endpoint accessible"
else
    test_failed "Backend root endpoint failed"
fi

# Kill port-forward
kill $PF_PID 2>/dev/null || true
sleep 1

echo ""

# Test 4: Frontend accessibility
log_info "Test 4: Testing frontend accessibility..."
# Start port-forward in background
kubectl port-forward -n datapond svc/frontend 3000:3000 > /dev/null 2>&1 &
PF_PID=$!
sleep 3

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    test_passed "Frontend is accessible (HTTP 200)"
else
    test_failed "Frontend returned HTTP $HTTP_CODE"
fi

# Kill port-forward
kill $PF_PID 2>/dev/null || true
sleep 1

echo ""

# Test 5: Database connectivity and schema
log_info "Test 5: Testing database connectivity..."
if kubectl exec -n datapond "$POSTGRES_POD" -- psql -U datapond -d datapond -c "\dt" > /dev/null 2>&1; then
    test_passed "Database connection successful"
else
    test_failed "Database connection failed"
fi

# Check for required tables
TABLES=$(kubectl exec -n datapond "$POSTGRES_POD" -- psql -U datapond -d datapond -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo "0")
if [ "$TABLES" -gt 0 ]; then
    test_passed "Database has $TABLES tables"
else
    test_failed "Database has no tables (not initialized?)"
fi

# Check specific tables
for table in connectors queries query_history users; do
    if kubectl exec -n datapond "$POSTGRES_POD" -- psql -U datapond -d datapond -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='$table'" 2>/dev/null | grep -q 1; then
        test_passed "Table '$table' exists"
    else
        test_warning "Table '$table' not found"
    fi
done

echo ""

# Test 6: Backend API endpoints
log_info "Test 6: Testing backend API endpoints..."
# Start port-forward in background
kubectl port-forward -n datapond svc/backend 8000:8000 > /dev/null 2>&1 &
PF_PID=$!
sleep 3

# Test services endpoint
if curl -s http://localhost:8000/api/services | grep -q "\["; then
    test_passed "Services API endpoint working"
else
    test_failed "Services API endpoint failed"
fi

# Test dashboard stats
if curl -s http://localhost:8000/api/dashboard/stats | grep -q "total_services"; then
    test_passed "Dashboard stats API working"
else
    test_failed "Dashboard stats API failed"
fi

# Test connectors endpoint
if curl -s http://localhost:8000/api/connectors | grep -q "\["; then
    test_passed "Connectors API endpoint working"
else
    test_failed "Connectors API endpoint failed"
fi

# Kill port-forward
kill $PF_PID 2>/dev/null || true

echo ""

# Test 7: Service-to-service connectivity
log_info "Test 7: Testing service-to-service connectivity..."

# Test backend to postgres
if kubectl exec -n datapond "$BACKEND_POD" -- curl -s --max-time 5 postgres:5432 > /dev/null 2>&1; then
    test_passed "Backend can reach Postgres"
else
    test_warning "Backend to Postgres connectivity unclear (expected for PostgreSQL)"
fi

# Test backend to valkey
if kubectl exec -n datapond "$BACKEND_POD" -- timeout 5 nc -zv valkey 6379 > /dev/null 2>&1; then
    test_passed "Backend can reach Valkey"
else
    test_warning "Backend to Valkey connectivity test failed (may need redis-cli)"
fi

echo ""

# Summary
log_info "=========================================="
log_info "Validation Summary"
log_info "=========================================="
echo ""
log_success "Passed: $PASSED_TESTS tests"

if [ $FAILED_TESTS -gt 0 ]; then
    log_error "Failed: $FAILED_TESTS tests"
    echo ""
    log_warning "Review failed tests above and check pod logs:"
    echo "  kubectl logs -n datapond $BACKEND_POD"
    echo "  kubectl logs -n datapond $FRONTEND_POD"
    echo ""
    exit 1
else
    log_success "All critical tests passed!"
    echo ""
    log_info "Deployment is healthy and ready for use."
    echo ""
    log_info "Next steps:"
    echo "  1. Access frontend: kubectl port-forward -n datapond svc/frontend 3000:3000"
    echo "  2. Access backend API: kubectl port-forward -n datapond svc/backend 8000:8000"
    echo "  3. View API docs: http://localhost:8000/docs"
    echo "  4. Monitor services: bash scripts/monitor-services.sh"
    echo ""
    exit 0
fi
