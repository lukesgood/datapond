#!/bin/bash
# DataPond Installation Script
# Supports: fresh install, upgrade, air-gapped environments
#
# Usage:
#   sudo bash scripts/install.sh                          # interactive
#   sudo bash scripts/install.sh --values customer.yaml  # non-interactive
#   sudo bash scripts/install.sh --airgap bundle.tar.gz  # air-gapped

set -euo pipefail

# ─── Constants ────────────────────────────────────────────────────────────────
DATAPOND_VERSION="2.3.0"
NAMESPACE="datapond"
RELEASE="datapond"
MIN_RAM_GB=8
REC_RAM_GB=16
MIN_DISK_GB=50
REC_DISK_GB=100
MIN_CPU=4

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/tmp/datapond-install-$(date +%Y%m%d-%H%M%S).log"

# ─── Logging ──────────────────────────────────────────────────────────────────
log()      { echo -e "${BLUE}[•]${NC} $*" | tee -a "$LOG_FILE"; }
ok()       { echo -e "${GREEN}[✓]${NC} $*" | tee -a "$LOG_FILE"; }
warn()     { echo -e "${YELLOW}[!]${NC} $*" | tee -a "$LOG_FILE"; }
err()      { echo -e "${RED}[✗]${NC} $*" | tee -a "$LOG_FILE" >&2; }
die()      { err "$*"; exit 1; }
section()  { echo -e "\n${BOLD}━━━ $* ━━━${NC}" | tee -a "$LOG_FILE"; }

# ─── Argument parsing ─────────────────────────────────────────────────────────
VALUES_FILE="values-quicktest.yaml"
AIRGAP_BUNDLE=""
SKIP_PREFLIGHT=false
SKIP_BUILD=false
DOMAIN="datapond.local"
NON_INTERACTIVE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --values)       VALUES_FILE="$2";     shift 2 ;;
    --airgap)       AIRGAP_BUNDLE="$2";   shift 2 ;;
    --domain)       DOMAIN="$2";          shift 2 ;;
    --skip-preflight) SKIP_PREFLIGHT=true; shift ;;
    --skip-build)   SKIP_BUILD=true;      shift ;;
    --yes|-y)       NON_INTERACTIVE=true; shift ;;
    --help|-h)
      echo "Usage: sudo bash $0 [options]"
      echo "  --values FILE        Helm values file (default: values-quicktest.yaml)"
      echo "  --domain DOMAIN      Ingress domain (default: datapond.local)"
      echo "  --airgap PATH        Air-gapped install — fully offline (no internet)."
      echo "                       PATH is the bundle .tar.gz OR an extracted bundle dir."
      echo "                       Installs K3s + Helm + images from the bundle, not the net."
      echo "  --skip-preflight     Skip system requirements check"
      echo "  --skip-build         Skip Docker image build"
      echo "  --yes                Non-interactive (auto-confirm)"
      exit 0 ;;
    *) die "Unknown option: $1. Run with --help for usage." ;;
  esac
done

confirm() {
  if $NON_INTERACTIVE; then return 0; fi
  read -rp "$1 [y/N] " ans
  [[ "${ans,,}" == "y" ]]
}

# ─── Root check ───────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash $0"
ACTUAL_USER="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)

# ─── Banner ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
cat <<'EOF'
  ____        _        ____                    _
 |  _ \  __ _| |_ __ _|  _ \ ___  _ __   __| |
 | | | |/ _` | __/ _` | |_) / _ \| '_ \ / _` |
 | |_| | (_| | || (_| |  __/ (_) | | | | (_| |
 |____/ \__,_|\__\__,_|_|   \___/|_| |_|\__,_|

 AI-Native Lakehouse Platform  v${DATAPOND_VERSION}
EOF
echo -e "${NC}"
log "Log file: $LOG_FILE"

# ─── Step 1: Pre-flight checks ────────────────────────────────────────────────
section "Step 1/6: Pre-flight Checks"

if ! $SKIP_PREFLIGHT; then
  FAIL=0

  # CPU
  CPU_COUNT=$(nproc 2>/dev/null || echo 1)
  if [[ $CPU_COUNT -lt $MIN_CPU ]]; then
    warn "CPU: ${CPU_COUNT} cores (minimum ${MIN_CPU} recommended)"
    FAIL=1
  else
    ok "CPU: ${CPU_COUNT} cores"
  fi

  # RAM
  RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
  if [[ $RAM_GB -lt $MIN_RAM_GB ]]; then
    err "RAM: ${RAM_GB}GB — minimum ${MIN_RAM_GB}GB required"
    FAIL=1
  elif [[ $RAM_GB -lt $REC_RAM_GB ]]; then
    warn "RAM: ${RAM_GB}GB — ${REC_RAM_GB}GB recommended for full stack"
  else
    ok "RAM: ${RAM_GB}GB"
  fi

  # Disk
  DISK_GB=$(df -BG "$PROJECT_ROOT" | awk 'NR==2 {print $4}' | tr -d G)
  if [[ $DISK_GB -lt $MIN_DISK_GB ]]; then
    err "Disk: ${DISK_GB}GB free — minimum ${MIN_DISK_GB}GB required"
    FAIL=1
  elif [[ $DISK_GB -lt $REC_DISK_GB ]]; then
    warn "Disk: ${DISK_GB}GB free — ${REC_DISK_GB}GB recommended"
  else
    ok "Disk: ${DISK_GB}GB free"
  fi

  # OS
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    ok "OS: $PRETTY_NAME"
  fi

  # Required ports
  for port in 80 443 6443; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " ; then
      warn "Port ${port} is in use — may conflict with Traefik/K3s"
    fi
  done

  [[ $FAIL -eq 0 ]] || die "Pre-flight failed. Fix the above issues or re-run with --skip-preflight"
  ok "Pre-flight checks passed"
fi

# ─── Resolve air-gap bundle (fully offline when --airgap given) ───────────────
# AIRGAP_DIR holds the extracted bundle: k3s-binary, k3s-install.sh, helm.tar.gz,
# k3s-airgap-images-*.tar*, images/*.tar. PATH may be a .tar.gz or a directory
# (the bundle's own installer passes its extracted dir).
AIRGAP=false
AIRGAP_DIR=""
if [[ -n "$AIRGAP_BUNDLE" ]]; then
  AIRGAP=true
  SKIP_BUILD=true   # never build images in air-gap; they come from the bundle
  if [[ -d "$AIRGAP_BUNDLE" ]]; then
    AIRGAP_DIR="$AIRGAP_BUNDLE"
  elif [[ -f "$AIRGAP_BUNDLE" ]]; then
    AIRGAP_DIR="$(mktemp -d)"
    log "Extracting air-gap bundle: $AIRGAP_BUNDLE"
    tar -xzf "$AIRGAP_BUNDLE" -C "$AIRGAP_DIR" 2>&1 | tee -a "$LOG_FILE"
    # Bundle archives wrap everything in a single top dir — descend into it.
    if [[ ! -d "$AIRGAP_DIR/images" ]]; then
      inner=$(find "$AIRGAP_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)
      [[ -d "$inner/images" ]] && AIRGAP_DIR="$inner"
    fi
  else
    die "Air-gap bundle not found: $AIRGAP_BUNDLE"
  fi
  [[ -d "$AIRGAP_DIR/images" ]] || die "Invalid air-gap bundle (no images/ in $AIRGAP_DIR)"
  ok "Air-gap mode — bundle at $AIRGAP_DIR (offline install, no internet)"
fi

install_helm_offline() {
  local tgz="$AIRGAP_DIR/helm.tar.gz"
  [[ -f "$tgz" ]] || die "Air-gap: helm.tar.gz missing from bundle — re-run bundle-airgap.sh"
  local td; td=$(mktemp -d)
  tar -xzf "$tgz" -C "$td"
  install -m 755 "$(find "$td" -name helm -type f | head -1)" /usr/local/bin/helm
  rm -rf "$td"
}

# ─── Step 2: Install K3s + Helm ───────────────────────────────────────────────
section "Step 2/6: Kubernetes (K3s) + Helm"

if command -v k3s &>/dev/null && kubectl get nodes &>/dev/null 2>&1; then
  ok "K3s already running: $(k3s --version | head -1)"
elif $AIRGAP; then
  log "Installing K3s from bundle (offline)..."
  [[ -f "$AIRGAP_DIR/k3s-binary" && -f "$AIRGAP_DIR/k3s-install.sh" ]] \
    || die "Air-gap: k3s-binary / k3s-install.sh missing from bundle — re-run bundle-airgap.sh"
  # Pre-stage K3s system images (pause/coredns/traefik/local-path/metrics-server) so
  # K3s boots with no registry access; without this an air-gapped K3s never goes Ready.
  mkdir -p /var/lib/rancher/k3s/agent/images/
  if ls "$AIRGAP_DIR"/k3s-airgap-images-*.tar* &>/dev/null; then
    cp "$AIRGAP_DIR"/k3s-airgap-images-*.tar* /var/lib/rancher/k3s/agent/images/
    ok "K3s system images pre-staged"
  else
    warn "K3s system airgap images not in bundle — K3s may fail to start offline"
  fi
  install -m 755 "$AIRGAP_DIR/k3s-binary" /usr/local/bin/k3s
  INSTALL_K3S_SKIP_DOWNLOAD=true bash "$AIRGAP_DIR/k3s-install.sh" --write-kubeconfig-mode 644 \
    2>&1 | tee -a "$LOG_FILE"
  sleep 15
  for i in {1..30}; do
    kubectl get nodes 2>/dev/null | grep -q Ready && break
    log "Waiting for K3s node ($i/30)..."
    sleep 5
  done
  ok "K3s installed (offline)"
else
  log "Installing K3s..."
  curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644 2>&1 | tee -a "$LOG_FILE"
  sleep 15

  # Wait for node ready
  for i in {1..30}; do
    kubectl get nodes 2>/dev/null | grep -q Ready && break
    log "Waiting for K3s node ($i/30)..."
    sleep 5
  done
  ok "K3s installed"
fi

# kubectl config for non-root user
mkdir -p "$USER_HOME/.kube"
cp /etc/rancher/k3s/k3s.yaml "$USER_HOME/.kube/config"
chown "$ACTUAL_USER:$ACTUAL_USER" "$USER_HOME/.kube/config"
chmod 600 "$USER_HOME/.kube/config"
ok "kubectl configured for user: $ACTUAL_USER"

if ! command -v helm &>/dev/null; then
  if $AIRGAP; then
    log "Installing Helm from bundle (offline)..."
    install_helm_offline
    ok "Helm installed (offline)"
  else
    log "Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash 2>&1 | tee -a "$LOG_FILE"
    ok "Helm installed"
  fi
else
  ok "Helm already installed: $(helm version --short)"
fi

# ─── Step 3: Build or load images ─────────────────────────────────────────────
section "Step 3/6: Container Images"

if $AIRGAP; then
  # Air-gapped: import the application images already extracted to AIRGAP_DIR/images.
  log "Loading images from air-gap bundle: $AIRGAP_DIR/images"
  shopt -s nullglob
  imgs=("$AIRGAP_DIR"/images/*.tar)
  [[ ${#imgs[@]} -gt 0 ]] || die "Air-gap: no image tars in $AIRGAP_DIR/images"
  for tar_file in "${imgs[@]}"; do
    log "Importing: $(basename "$tar_file")"
    k3s ctr images import "$tar_file" 2>&1 | tee -a "$LOG_FILE"
  done
  shopt -u nullglob
  ok "Images loaded from air-gap bundle (${#imgs[@]} images)"

elif ! $SKIP_BUILD; then
  # Build locally
  if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    bash "$SCRIPT_DIR/install-docker.sh" 2>&1 | tee -a "$LOG_FILE"
  fi

  log "Building backend image..."
  docker build -t datapond/backend:latest "$PROJECT_ROOT/backend/" 2>&1 | tee -a "$LOG_FILE"
  docker save datapond/backend:latest | k3s ctr images import -
  ok "Backend image built and imported"

  log "Building frontend image..."
  docker build -t datapond/frontend:latest "$PROJECT_ROOT/frontend/" 2>&1 | tee -a "$LOG_FILE"
  docker save datapond/frontend:latest | k3s ctr images import -
  ok "Frontend image built and imported"
else
  warn "Skipping image build (--skip-build). Ensure images exist in containerd."
fi

# ─── Step 4: Configure ────────────────────────────────────────────────────────
section "Step 4/6: Configuration"

VALUES_PATH="$PROJECT_ROOT/helm/datapond/$VALUES_FILE"
[[ -f "$VALUES_PATH" ]] || die "Values file not found: $VALUES_PATH"
ok "Values file: $VALUES_FILE"

# /etc/hosts entry
if ! grep -q "$DOMAIN" /etc/hosts 2>/dev/null; then
  echo "127.0.0.1  $DOMAIN" >> /etc/hosts
  ok "Added $DOMAIN → 127.0.0.1 to /etc/hosts"
else
  ok "$DOMAIN already in /etc/hosts"
fi

# ─── Step 5: Deploy ───────────────────────────────────────────────────────────
section "Step 5/6: Deploying DataPond"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - 2>&1

if helm list -n "$NAMESPACE" 2>/dev/null | grep -q "^$RELEASE"; then
  warn "Existing release found."
  if confirm "Upgrade existing DataPond installation?"; then
    log "Upgrading DataPond..."
    helm upgrade "$RELEASE" "$PROJECT_ROOT/helm/datapond" \
      --namespace "$NAMESPACE" \
      --values "$VALUES_PATH" \
      --wait=false \
      --timeout 15m \
      2>&1 | tee -a "$LOG_FILE"
    ok "Helm upgrade submitted"
  else
    die "Installation cancelled."
  fi
else
  log "Installing DataPond for the first time..."
  # Dry-run first
  RESOURCE_COUNT=$(helm template "$RELEASE" "$PROJECT_ROOT/helm/datapond" \
    --namespace "$NAMESPACE" --values "$VALUES_PATH" \
    2>/dev/null | grep -c "^kind:" || true)
  log "Resources to create: $RESOURCE_COUNT"

  if ! $NON_INTERACTIVE; then
    confirm "Proceed with installation?" || die "Installation cancelled."
  fi

  helm install "$RELEASE" "$PROJECT_ROOT/helm/datapond" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    --values "$VALUES_PATH" \
    --wait=false \
    --timeout 15m \
    2>&1 | tee -a "$LOG_FILE"
  ok "Helm install submitted"
fi

# ─── Step 6: Wait & Verify ────────────────────────────────────────────────────
section "Step 6/6: Waiting for Services"

log "Waiting for core services (this takes 3-10 minutes on first install)..."

# Wait for PostgreSQL first (everything depends on it)
log "Waiting for PostgreSQL..."
kubectl wait pod -l app=postgres -n "$NAMESPACE" \
  --for=condition=ready --timeout=300s 2>&1 | tee -a "$LOG_FILE" || warn "PostgreSQL not ready yet"

# Wait for backend
log "Waiting for backend..."
kubectl wait pod -l app=backend -n "$NAMESPACE" \
  --for=condition=ready --timeout=300s 2>&1 | tee -a "$LOG_FILE" || warn "Backend not ready yet"

# Wait for frontend
log "Waiting for frontend..."
kubectl wait pod -l app=frontend -n "$NAMESPACE" \
  --for=condition=ready --timeout=300s 2>&1 | tee -a "$LOG_FILE" || warn "Frontend not ready yet"

# Clean up any Pending pods (memory pressure artifacts)
PENDING=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l)
if [[ $PENDING -gt 0 ]]; then
  warn "Deleting $PENDING Pending pods (memory pressure artifacts)..."
  kubectl delete pods -n "$NAMESPACE" --field-selector=status.phase=Pending 2>/dev/null || true
fi

# Final status
echo ""
TOTAL=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
RUNNING=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c Running || true)
echo -e "${BOLD}Pod status: ${GREEN}${RUNNING}${NC}${BOLD}/${TOTAL} Running${NC}"
kubectl get pods -n "$NAMESPACE" 2>/dev/null

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  DataPond v${DATAPOND_VERSION} Installation Complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Access URLs:${NC}"
echo -e "    Frontend    →  http://${DOMAIN}"
echo -e "    API Docs    →  http://${DOMAIN}/api/docs"
echo -e "    JupyterLab  →  http://${DOMAIN}/jupyter  (token: jupyter)"
echo -e "    Airflow     →  http://${DOMAIN}/airflow   (airflow/airflow)"
echo -e "    MLflow      →  http://${DOMAIN}/mlflow"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "    Watch pods:  kubectl get pods -n datapond -w"
echo -e "    Logs:        kubectl logs -f deployment/backend -n datapond"
echo -e "    Validate:    bash scripts/validate-deployment.sh"
echo -e "    Uninstall:   helm uninstall datapond -n datapond"
echo ""
echo -e "  ${BOLD}Install log:${NC} $LOG_FILE"
echo ""

if [[ $RUNNING -lt $TOTAL ]]; then
  warn "Some pods are still starting. Check with: kubectl get pods -n datapond -w"
  warn "First install typically takes 5-10 minutes for all images to pull."
fi
