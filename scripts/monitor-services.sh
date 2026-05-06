#!/bin/bash
# Monitor DataPond services in real-time
# Shows pod status, resource usage, and logs for any failing pods

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_header() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

# Parse arguments
WATCH_MODE=false
SHOW_LOGS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --watch|-w)
            WATCH_MODE=true
            shift
            ;;
        --logs|-l)
            SHOW_LOGS=true
            shift
            ;;
        *)
            echo "Usage: $0 [--watch|-w] [--logs|-l]"
            echo "  --watch: Continuously monitor (refresh every 5s)"
            echo "  --logs:  Show logs for failing pods"
            exit 1
            ;;
    esac
done

monitor_once() {
    clear
    log_header "DataPond Service Monitor - $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # Check if namespace exists
    if ! kubectl get namespace datapond &> /dev/null; then
        log_error "Namespace 'datapond' not found. Is DataPond deployed?"
        return 1
    fi

    # Pod status
    log_info "Pod Status:"
    echo ""
    kubectl get pods -n datapond -o wide
    echo ""

    # Count pods by status
    RUNNING=$(kubectl get pods -n datapond --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    PENDING=$(kubectl get pods -n datapond --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l)
    FAILED=$(kubectl get pods -n datapond --field-selector=status.phase=Failed --no-headers 2>/dev/null | wc -l)
    TOTAL=$(kubectl get pods -n datapond --no-headers 2>/dev/null | wc -l)

    echo -e "${GREEN}Running:${NC} $RUNNING | ${YELLOW}Pending:${NC} $PENDING | ${RED}Failed:${NC} $FAILED | ${BLUE}Total:${NC} $TOTAL"
    echo ""

    # Resource usage
    log_info "Resource Usage (CPU / Memory):"
    echo ""
    kubectl top pods -n datapond 2>/dev/null || log_warning "Metrics not available (metrics-server may not be running)"
    echo ""

    # Node resources
    log_info "Node Resources:"
    echo ""
    kubectl top nodes 2>/dev/null || log_warning "Node metrics not available"
    echo ""

    # Services
    log_info "Services:"
    echo ""
    kubectl get svc -n datapond
    echo ""

    # Check for pods with restarts
    log_info "Pods with Restarts:"
    echo ""
    RESTART_PODS=$(kubectl get pods -n datapond -o jsonpath='{range .items[?(@.status.containerStatuses[0].restartCount>0)]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}')
    if [ -n "$RESTART_PODS" ]; then
        echo "$RESTART_PODS" | awk '{printf "  %-40s %s restarts\n", $1, $2}'
    else
        log_success "No pods have restarted"
    fi
    echo ""

    # Check for non-running pods
    log_info "Non-Running Pods:"
    echo ""
    NON_RUNNING=$(kubectl get pods -n datapond --field-selector=status.phase!=Running --no-headers 2>/dev/null)
    if [ -n "$NON_RUNNING" ]; then
        echo "$NON_RUNNING"
        echo ""

        # Show logs for non-running pods if requested
        if [ "$SHOW_LOGS" = true ]; then
            echo "$NON_RUNNING" | awk '{print $1}' | while read pod; do
                log_warning "Logs for $pod:"
                echo "----------------------------------------"
                kubectl logs -n datapond "$pod" --tail=20 2>&1 || log_error "Could not get logs for $pod"
                echo ""
            done
        fi
    else
        log_success "All pods are running"
    fi
    echo ""

    # Check backend and frontend specifically
    log_info "Phase 1 Core Services:"
    echo ""

    # Backend
    BACKEND_STATUS=$(kubectl get pod -n datapond -l app=backend -o jsonpath="{.items[0].status.phase}" 2>/dev/null || echo "Not Found")
    BACKEND_POD=$(kubectl get pod -n datapond -l app=backend -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "")
    if [ "$BACKEND_STATUS" = "Running" ]; then
        log_success "Backend: Running ($BACKEND_POD)"
    elif [ "$BACKEND_STATUS" = "Not Found" ]; then
        log_error "Backend: Not deployed"
    else
        log_warning "Backend: $BACKEND_STATUS ($BACKEND_POD)"
    fi

    # Frontend
    FRONTEND_STATUS=$(kubectl get pod -n datapond -l app=frontend -o jsonpath="{.items[0].status.phase}" 2>/dev/null || echo "Not Found")
    FRONTEND_POD=$(kubectl get pod -n datapond -l app=frontend -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "")
    if [ "$FRONTEND_STATUS" = "Running" ]; then
        log_success "Frontend: Running ($FRONTEND_POD)"
    elif [ "$FRONTEND_STATUS" = "Not Found" ]; then
        log_error "Frontend: Not deployed"
    else
        log_warning "Frontend: $FRONTEND_STATUS ($FRONTEND_POD)"
    fi

    # Postgres
    POSTGRES_STATUS=$(kubectl get pod -n datapond -l app=postgres -o jsonpath="{.items[0].status.phase}" 2>/dev/null || echo "Not Found")
    POSTGRES_POD=$(kubectl get pod -n datapond -l app=postgres -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "")
    if [ "$POSTGRES_STATUS" = "Running" ]; then
        log_success "Postgres: Running ($POSTGRES_POD)"
    else
        log_warning "Postgres: $POSTGRES_STATUS ($POSTGRES_POD)"
    fi

    echo ""

    # Recent events
    log_info "Recent Events (last 10):"
    echo ""
    kubectl get events -n datapond --sort-by='.lastTimestamp' | tail -10
    echo ""

    if [ "$WATCH_MODE" = false ]; then
        log_info "Tip: Use --watch to continuously monitor"
        log_info "     Use --logs to see logs for failing pods"
    fi
}

# Main execution
if [ "$WATCH_MODE" = true ]; then
    log_info "Starting watch mode (Ctrl+C to exit)..."
    while true; do
        monitor_once
        sleep 5
    done
else
    monitor_once
fi
