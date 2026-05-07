#!/bin/bash
# DataPond Air-Gap Bundle Creator
# Creates a self-contained installation package for air-gapped environments
#
# Usage: sudo bash scripts/bundle-airgap.sh [--output /path/to/output]

set -euo pipefail

DATAPOND_VERSION="2.3.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-/tmp}"
BUNDLE_NAME="datapond-airgap-${DATAPOND_VERSION}-$(date +%Y%m%d).tar.gz"
BUNDLE_PATH="${OUTPUT_DIR}/${BUNDLE_NAME}"
WORKDIR=$(mktemp -d)

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${BLUE}[•]${NC} $*"; }
ok()  { echo -e "${GREEN}[✓]${NC} $*"; }
die() { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

[[ $EUID -eq 0 ]] || die "Run with sudo"
command -v docker &>/dev/null || die "Docker required to build images"

log "DataPond Air-Gap Bundle v${DATAPOND_VERSION}"
log "Output: $BUNDLE_PATH"
log "Working directory: $WORKDIR"

mkdir -p "$WORKDIR/images"

# ─── Build DataPond images ────────────────────────────────────────────────────
log "Building backend image..."
docker build -t "datapond/backend:${DATAPOND_VERSION}" "$PROJECT_ROOT/backend/"
docker save "datapond/backend:${DATAPOND_VERSION}" -o "$WORKDIR/images/backend.tar"
ok "Backend image saved"

log "Building frontend image..."
docker build -t "datapond/frontend:${DATAPOND_VERSION}" "$PROJECT_ROOT/frontend/"
docker save "datapond/frontend:${DATAPOND_VERSION}" -o "$WORKDIR/images/frontend.tar"
ok "Frontend image saved"

# ─── Pull third-party images ─────────────────────────────────────────────────
log "Pulling third-party images (this may take a while)..."

# Read image list from values.yaml
THIRD_PARTY_IMAGES=(
  "postgres:16-alpine"
  "redis:7-alpine"
  "apache/airflow:2.8.1"
  "ghcr.io/projectpolaris/polaris:0.5.0"
  "trinodb/trino:435"
  "datapond/jupyter:latest"
  "mlflow/mlflow:2.10.2"
  "ghcr.io/risingwavelabs/risingwave:v1.6.0"
  "opensearchproject/opensearch:2.11.0"
  "open-metadata/server:1.2.0"
)

for image in "${THIRD_PARTY_IMAGES[@]}"; do
  safe_name=$(echo "$image" | tr '/: ' '___')
  log "Pulling $image..."
  docker pull "$image" 2>/dev/null || { echo "  [warn] Skipped: $image"; continue; }
  docker save "$image" -o "$WORKDIR/images/${safe_name}.tar"
  ok "Saved: $image"
done

# ─── Pull K3s installer ───────────────────────────────────────────────────────
log "Downloading K3s installer..."
K3S_VERSION="v1.29.3+k3s1"
curl -sfL "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION}/k3s" \
  -o "$WORKDIR/k3s-binary" 2>/dev/null || warn "K3s binary download failed (optional)"
curl -sfL "https://get.k3s.io" -o "$WORKDIR/k3s-install.sh" 2>/dev/null || warn "K3s install script download failed"
chmod +x "$WORKDIR/k3s-binary" "$WORKDIR/k3s-install.sh" 2>/dev/null || true

# ─── Pull Helm installer ──────────────────────────────────────────────────────
log "Downloading Helm..."
HELM_VERSION="v3.14.0"
curl -sfL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
  -o "$WORKDIR/helm.tar.gz" 2>/dev/null || warn "Helm download failed (optional)"

# ─── Copy Helm chart and scripts ─────────────────────────────────────────────
log "Copying Helm chart and install scripts..."
cp -r "$PROJECT_ROOT/helm" "$WORKDIR/"
cp -r "$PROJECT_ROOT/scripts" "$WORKDIR/"
cp "$PROJECT_ROOT/README.md" "$WORKDIR/" 2>/dev/null || true

# Patch image tags in values files to use versioned tags
sed -i "s|datapond/backend:latest|datapond/backend:${DATAPOND_VERSION}|g" \
  "$WORKDIR/helm/datapond/values.yaml" \
  "$WORKDIR/helm/datapond/values-quicktest.yaml" 2>/dev/null || true
sed -i "s|datapond/frontend:latest|datapond/frontend:${DATAPOND_VERSION}|g" \
  "$WORKDIR/helm/datapond/values.yaml" \
  "$WORKDIR/helm/datapond/values-quicktest.yaml" 2>/dev/null || true

# ─── Create install entrypoint ───────────────────────────────────────────────
cat > "$WORKDIR/install.sh" <<'INSTALLER'
#!/bin/bash
# DataPond Air-Gap Installer
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }

echo "DataPond Air-Gap Installation"
echo "Bundle directory: $BUNDLE_DIR"

# Install K3s offline if binary present
if [[ -f "$BUNDLE_DIR/k3s-binary" ]] && ! command -v k3s &>/dev/null; then
  echo "Installing K3s from bundle..."
  install -m 755 "$BUNDLE_DIR/k3s-binary" /usr/local/bin/k3s
  INSTALL_K3S_SKIP_DOWNLOAD=true bash "$BUNDLE_DIR/k3s-install.sh"
fi

# Import all images
echo "Importing container images..."
for img in "$BUNDLE_DIR"/images/*.tar; do
  echo "  Importing: $(basename "$img")"
  k3s ctr images import "$img"
done

# Run main install script
bash "$BUNDLE_DIR/scripts/install.sh" --skip-build "$@"
INSTALLER
chmod +x "$WORKDIR/install.sh"

# ─── Create manifest file ─────────────────────────────────────────────────────
cat > "$WORKDIR/MANIFEST.txt" <<EOF
DataPond Air-Gap Bundle
Version: ${DATAPOND_VERSION}
Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Host: $(hostname)

Contents:
  images/         Container images (*.tar)
  helm/           Helm chart
  scripts/        Installation scripts
  install.sh      Main installer entrypoint
  k3s-binary      K3s binary (offline install)
  k3s-install.sh  K3s installer script
  helm.tar.gz     Helm binary

Usage:
  tar -xzf $(basename "$BUNDLE_PATH")
  cd $(basename "$BUNDLE_PATH" .tar.gz)
  sudo bash install.sh [--values your-values.yaml] [--domain your.domain.com]

Requirements:
  - Ubuntu 20.04+ / RHEL 8+ / Rocky Linux 8+
  - CPU: 4+ cores (8+ recommended)
  - RAM: 8GB minimum (16GB recommended)
  - Disk: 50GB minimum (100GB recommended)
EOF

# ─── Package everything ───────────────────────────────────────────────────────
log "Creating bundle archive..."
BUNDLE_DIR_NAME="datapond-airgap-${DATAPOND_VERSION}"
mv "$WORKDIR" "/tmp/${BUNDLE_DIR_NAME}"

tar -czf "$BUNDLE_PATH" -C /tmp "$BUNDLE_DIR_NAME"
mv "/tmp/${BUNDLE_DIR_NAME}" "$WORKDIR"  # restore for cleanup trap

BUNDLE_SIZE=$(du -sh "$BUNDLE_PATH" | cut -f1)
ok "Bundle created: $BUNDLE_PATH ($BUNDLE_SIZE)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Air-Gap Bundle Ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Bundle: $BUNDLE_PATH"
echo "  Size:   $BUNDLE_SIZE"
echo ""
echo "  Transfer to target server:"
echo "    scp $BUNDLE_PATH user@customer-server:/tmp/"
echo ""
echo "  Install on target server:"
echo "    tar -xzf $(basename "$BUNDLE_PATH")"
echo "    cd $(basename "$BUNDLE_PATH" .tar.gz)"
echo "    sudo bash install.sh --values your-values.yaml"
echo ""
