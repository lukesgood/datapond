#!/usr/bin/env bash
# Read-only deployment validation for DataPond.
#
# Authentication (values are never printed):
#   DATAPOND_TOKEN / DATAPOND_TOKEN_FILE
#     Pre-issued admin JWT. If omitted, the script logs in with
#     DATAPOND_ADMIN_USERNAME (default: admin) and DATAPOND_ADMIN_PASSWORD.
#     An interactive terminal prompts for the password when the variable is unset.
#   DATAPOND_VIEWER_TOKEN / DATAPOND_VIEWER_TOKEN_FILE
#     Optional viewer JWT used to assert a read-only admin endpoint returns 403.
#   DATAPOND_INTERNAL_KEY / DATAPOND_INTERNAL_KEY_FILE
#     Optional internal key used to assert it cannot access a non-callback route.
#
# Targeting:
#   DATAPOND_NAMESPACE       Kubernetes namespace (default: datapond)
#   DATAPOND_BASE_URL        Deployed HTTPS origin. When omitted, backend/frontend
#                            services are reached through temporary port-forwards.
#   DATAPOND_INSECURE=1      Allow an untrusted TLS certificate for acceptance only.
#   DATAPOND_BACKEND_PORT    Local backend port-forward port (default: 8000)
#   DATAPOND_FRONTEND_PORT   Local frontend port-forward port (default: 3000)

set -uo pipefail

NAMESPACE="${DATAPOND_NAMESPACE:-datapond}"
BASE_URL="${DATAPOND_BASE_URL:-}"
BASE_URL="${BASE_URL%/}"
BACKEND_PORT="${DATAPOND_BACKEND_PORT:-8000}"
FRONTEND_PORT="${DATAPOND_FRONTEND_PORT:-3000}"
ADMIN_USERNAME="${DATAPOND_ADMIN_USERNAME:-admin}"
ADMIN_TOKEN="${DATAPOND_TOKEN:-}"
VIEWER_TOKEN="${DATAPOND_VIEWER_TOKEN:-}"
INTERNAL_KEY="${DATAPOND_INTERNAL_KEY:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$1"; }
log_success() { printf "%b[✓]%b %s\n" "$GREEN" "$NC" "$1"; }
log_warning() { printf "%b[⚠]%b %s\n" "$YELLOW" "$NC" "$1"; }
log_error() { printf "%b[✗]%b %s\n" "$RED" "$NC" "$1"; }

FAILED_TESTS=0
PASSED_TESTS=0
WARNING_TESTS=0
PF_PIDS=""
TEMP_FILES=""
API_STATUS="000"
API_BODY_FILE=""

add_temp_file() {
    TEMP_FILES="$TEMP_FILES $1"
}

cleanup() {
    local pid file
    for pid in $PF_PIDS; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    for file in $TEMP_FILES; do
        rm -f "$file"
    done
    unset ADMIN_TOKEN VIEWER_TOKEN INTERNAL_KEY DATAPOND_ADMIN_PASSWORD
}
trap cleanup EXIT INT TERM

test_passed() {
    PASSED_TESTS=$((PASSED_TESTS + 1))
    log_success "$1"
}

test_failed() {
    FAILED_TESTS=$((FAILED_TESTS + 1))
    log_error "$1"
}

test_warning() {
    WARNING_TESTS=$((WARNING_TESTS + 1))
    log_warning "$1"
}

load_secret_file() {
    local current_value="$1"
    local file_path="$2"
    if [ -n "$current_value" ]; then
        printf '%s' "$current_value"
    elif [ -n "$file_path" ] && [ -r "$file_path" ]; then
        tr -d '\r\n' < "$file_path"
    else
        printf ''
    fi
}

curl_args=(-sS --connect-timeout 5 --max-time 20)
if [ "${DATAPOND_INSECURE:-0}" = "1" ]; then
    curl_args+=(-k)
fi

start_port_forward() {
    local service="$1"
    local local_port="$2"
    local remote_port="$3"
    local log_file pid i
    log_file=$(mktemp "${TMPDIR:-/tmp}/datapond-port-forward.XXXXXX")
    add_temp_file "$log_file"
    kubectl port-forward -n "$NAMESPACE" "svc/$service" "$local_port:$remote_port" >"$log_file" 2>&1 &
    pid=$!
    PF_PIDS="$PF_PIDS $pid"
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        if grep -q "Forwarding from" "$log_file"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

api_request() {
    local method="$1"
    local path="$2"
    shift 2
    API_BODY_FILE=$(mktemp "${TMPDIR:-/tmp}/datapond-api.XXXXXX")
    add_temp_file "$API_BODY_FILE"
    API_STATUS=$(curl "${curl_args[@]}" -X "$method" -o "$API_BODY_FILE" -w '%{http_code}' "$@" "$API_BASE$path" 2>/dev/null || printf '000')
}

admin_get() {
    local path="$1"
    api_request GET "$path" -H "Authorization: Bearer $ADMIN_TOKEN"
}

pod_name() {
    kubectl get pod -n "$NAMESPACE" -l "app=$1" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

pod_is_ready() {
    local pod="$1"
    [ -n "$pod" ] || return 1
    [ "$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || true)" = "Running" ] || return 1
    [ "$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)" = "True" ]
}

restart_count() {
    local pod="$1"
    if [ -z "$pod" ]; then
        printf 'unknown'
        return
    fi
    kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || printf 'unknown'
}

log_info "=========================================="
log_info "DataPond Deployment Validation"
log_info "=========================================="
log_info "Namespace: $NAMESPACE"
if [ -n "$BASE_URL" ]; then
    log_info "API/frontend target: $BASE_URL"
else
    log_info "API/frontend target: temporary local port-forwards"
fi
printf '\n'

# Prerequisites
for command_name in kubectl curl jq; do
    if command -v "$command_name" >/dev/null 2>&1; then
        test_passed "Required command is available: $command_name"
    else
        test_failed "Required command is missing: $command_name"
    fi
done

if ! command -v kubectl >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    log_error "Cannot continue without kubectl, curl, and jq."
    exit 1
fi

if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    test_passed "Kubernetes namespace is reachable: $NAMESPACE"
else
    test_failed "Kubernetes namespace is not reachable: $NAMESPACE"
    exit 1
fi

printf '\n'
log_info "Test 1: Checking core pod readiness..."
BACKEND_POD=$(pod_name backend)
FRONTEND_POD=$(pod_name frontend)
POSTGRES_POD=$(pod_name postgres)

if pod_is_ready "$BACKEND_POD"; then
    test_passed "Backend pod is Running and Ready: $BACKEND_POD"
else
    test_failed "Backend pod is not Running and Ready"
fi

if pod_is_ready "$FRONTEND_POD"; then
    test_passed "Frontend pod is Running and Ready: $FRONTEND_POD"
else
    test_failed "Frontend pod is not Running and Ready"
fi

if [ -n "$POSTGRES_POD" ]; then
    if pod_is_ready "$POSTGRES_POD"; then
        test_passed "Postgres pod is Running and Ready: $POSTGRES_POD"
    else
        test_failed "Postgres pod exists but is not Running and Ready"
    fi
else
    test_warning "No in-cluster Postgres pod found; treating the database as external"
fi

printf '\n'
log_info "Test 2: Checking core pod restart counts..."
for item in "backend:$BACKEND_POD" "frontend:$FRONTEND_POD"; do
    component=${item%%:*}
    pod=${item#*:}
    restarts=$(restart_count "$pod")
    if [ "$restarts" = "0" ]; then
        test_passed "$component has 0 restarts"
    elif [[ "$restarts" =~ ^[0-9]+$ ]] && [ "$restarts" -lt 3 ]; then
        test_warning "$component has $restarts restarts"
    else
        test_failed "$component restart count is $restarts"
    fi
done

printf '\n'
log_info "Test 3: Establishing API target..."
if [ -n "$BASE_URL" ]; then
    API_BASE="$BASE_URL"
    FRONTEND_BASE="$BASE_URL"
    test_passed "Using configured deployment origin"
else
    API_BASE="http://127.0.0.1:$BACKEND_PORT"
    FRONTEND_BASE="http://127.0.0.1:$FRONTEND_PORT"
    if start_port_forward backend "$BACKEND_PORT" 8000; then
        test_passed "Backend port-forward is active on $BACKEND_PORT"
    else
        test_failed "Backend port-forward could not be established"
    fi
    if start_port_forward frontend "$FRONTEND_PORT" 3000; then
        test_passed "Frontend port-forward is active on $FRONTEND_PORT"
    else
        test_failed "Frontend port-forward could not be established"
    fi
fi

api_request GET /api/health
if [ "$API_STATUS" = "200" ] && grep -qi 'healthy' "$API_BODY_FILE"; then
    test_passed "Backend health endpoint reports healthy"
else
    test_failed "Backend health check failed (HTTP $API_STATUS)"
fi

FRONTEND_STATUS=$(curl "${curl_args[@]}" -o /dev/null -w '%{http_code}' "$FRONTEND_BASE/" 2>/dev/null || printf '000')
if [ "$FRONTEND_STATUS" = "200" ]; then
    test_passed "Frontend is accessible (HTTP 200)"
else
    test_failed "Frontend returned HTTP $FRONTEND_STATUS"
fi

printf '\n'
log_info "Test 4: Acquiring and validating an admin token..."
ADMIN_TOKEN=$(load_secret_file "$ADMIN_TOKEN" "${DATAPOND_TOKEN_FILE:-}")
if [ -z "$ADMIN_TOKEN" ]; then
    ADMIN_PASSWORD="${DATAPOND_ADMIN_PASSWORD:-}"
    if [ -z "$ADMIN_PASSWORD" ] && [ -t 0 ]; then
        printf 'Admin password for %s: ' "$ADMIN_USERNAME" >&2
        IFS= read -r -s ADMIN_PASSWORD
        printf '\n' >&2
    fi

    if [ -n "$ADMIN_PASSWORD" ]; then
        LOGIN_PAYLOAD=$(jq -cn --arg username "$ADMIN_USERNAME" --arg password "$ADMIN_PASSWORD" '{username:$username,password:$password}')
        api_request POST /api/auth/login -H 'Content-Type: application/json' --data-binary "$LOGIN_PAYLOAD"
        if [[ "$API_STATUS" =~ ^2[0-9][0-9]$ ]]; then
            ADMIN_TOKEN=$(jq -er '.access_token | select(type == "string" and length > 0)' "$API_BODY_FILE" 2>/dev/null || true)
        fi
        unset ADMIN_PASSWORD DATAPOND_ADMIN_PASSWORD LOGIN_PAYLOAD
    fi
fi

if [ -z "$ADMIN_TOKEN" ]; then
    test_failed "No admin token available; set DATAPOND_TOKEN(_FILE) or DATAPOND_ADMIN_PASSWORD"
else
    admin_get /api/auth/me
    if [ "$API_STATUS" = "200" ] && jq -e '(.role // .user.role) == "admin"' "$API_BODY_FILE" >/dev/null 2>&1; then
        test_passed "Admin token is valid and resolves to the admin role"
    else
        test_failed "Provided credential is not a valid admin session (HTTP $API_STATUS)"
        ADMIN_TOKEN=""
    fi
fi

printf '\n'
log_info "Test 5: Checking protected read-only APIs..."
if [ -n "$ADMIN_TOKEN" ]; then
    admin_get /api/services
    if [ "$API_STATUS" = "200" ] && jq -e 'type == "array"' "$API_BODY_FILE" >/dev/null 2>&1; then
        test_passed "Services API returned an authenticated list"
    else
        test_failed "Services API failed or returned an invalid contract (HTTP $API_STATUS)"
    fi

    admin_get /api/dashboard/stats
    if [ "$API_STATUS" = "200" ] && jq -e 'type == "object" and has("total_services")' "$API_BODY_FILE" >/dev/null 2>&1; then
        test_passed "Dashboard stats API returned the expected contract"
    else
        test_failed "Dashboard stats API failed or returned an invalid contract (HTTP $API_STATUS)"
    fi

    admin_get /api/connectors/connections
    if [ "$API_STATUS" = "200" ] && jq -e 'type == "array"' "$API_BODY_FILE" >/dev/null 2>&1; then
        test_passed "Connector connections API returned an authenticated list"
    else
        test_failed "Connector connections API failed or returned an invalid contract (HTTP $API_STATUS)"
    fi
else
    test_failed "Protected API checks skipped because admin authentication failed"
fi

printf '\n'
log_info "Test 6: Checking database connectivity..."
if [ -n "$POSTGRES_POD" ]; then
    if kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dt"' >/dev/null 2>&1; then
        test_passed "In-cluster database connection succeeded"
    else
        test_failed "In-cluster database connection failed"
    fi

    TABLES=$(kubectl exec -n "$NAMESPACE" "$POSTGRES_POD" -- sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'\"" 2>/dev/null || printf '0')
    TABLES=$(printf '%s' "$TABLES" | tr -d '[:space:]')
    if [[ "$TABLES" =~ ^[0-9]+$ ]] && [ "$TABLES" -gt 0 ]; then
        test_passed "Database has $TABLES public tables"
    else
        test_failed "Database has no public tables or could not be queried"
    fi
else
    test_warning "Direct schema inspection skipped for the external database profile"
fi

if [ -n "$BACKEND_POD" ] && kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- python -c 'import os,socket; s=socket.create_connection((os.getenv("POSTGRES_HOST","postgres"),int(os.getenv("POSTGRES_PORT","5432"))),5); s.close()' >/dev/null 2>&1; then
    test_passed "Backend can open a TCP connection to its configured PostgreSQL host"
else
    test_failed "Backend cannot reach its configured PostgreSQL host"
fi

if [ -n "$BACKEND_POD" ] && kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- python -c 'import os,socket; from urllib.parse import urlparse; u=urlparse(os.getenv("REDIS_URL","redis://redis:6379")); s=socket.create_connection((u.hostname or "redis",u.port or 6379),5); s.close()' >/dev/null 2>&1; then
    test_passed "Backend can open a TCP connection to its configured Valkey/Redis host"
else
    test_failed "Backend cannot reach its configured Valkey/Redis host"
fi

printf '\n'
log_info "Test 7: Optional live authorization-boundary checks..."
VIEWER_TOKEN=$(load_secret_file "$VIEWER_TOKEN" "${DATAPOND_VIEWER_TOKEN_FILE:-}")
if [ -n "$VIEWER_TOKEN" ]; then
    api_request GET /api/settings/system -H "Authorization: Bearer $VIEWER_TOKEN"
    if [ "$API_STATUS" = "403" ]; then
        test_passed "Viewer is denied the read-only admin settings endpoint"
    else
        test_failed "Viewer boundary check expected HTTP 403, got $API_STATUS"
    fi
else
    test_warning "Viewer boundary not checked; DATAPOND_VIEWER_TOKEN(_FILE) was not provided"
fi

INTERNAL_KEY=$(load_secret_file "$INTERNAL_KEY" "${DATAPOND_INTERNAL_KEY_FILE:-}")
if [ -n "$INTERNAL_KEY" ]; then
    api_request GET /api/services -H "X-Internal-Key: $INTERNAL_KEY"
    if [ "$API_STATUS" = "401" ]; then
        test_passed "Internal key is denied outside the exact POST callback allowlist"
    else
        test_failed "Internal-key scope check expected HTTP 401, got $API_STATUS"
    fi
else
    test_warning "Internal-key scope not checked; DATAPOND_INTERNAL_KEY(_FILE) was not provided"
fi

printf '\n'
log_info "=========================================="
log_info "Validation Summary"
log_info "=========================================="
log_success "Passed: $PASSED_TESTS"
if [ "$WARNING_TESTS" -gt 0 ]; then
    log_warning "Warnings/skips: $WARNING_TESTS"
fi

if [ "$FAILED_TESTS" -gt 0 ]; then
    log_error "Failed: $FAILED_TESTS"
    log_warning "Review failures above. Suggested diagnostics:"
    [ -n "$BACKEND_POD" ] && printf '  kubectl logs -n %q %q\n' "$NAMESPACE" "$BACKEND_POD"
    [ -n "$FRONTEND_POD" ] && printf '  kubectl logs -n %q %q\n' "$NAMESPACE" "$FRONTEND_POD"
    exit 1
fi

log_success "All critical read-only deployment checks passed."
log_info "Mutating RAG/connector acceptance remains an explicit operator step; see docs/AWS_MVP_RUNBOOK.md."
exit 0
