#!/bin/bash
# DataPond Air-Gap Bundle Creator
# Creates a self-contained installation package for air-gapped environments
#
# Usage: sudo bash scripts/bundle-airgap.sh [--output /path/to/output]

set -euo pipefail

DATAPOND_VERSION="2.3.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APPVER="$(grep '^appVersion:' "$PROJECT_ROOT/helm/datapond/Chart.yaml" | tr -d ' "' | cut -d: -f2)"
OUTPUT_DIR="${1:-/tmp}"
BUNDLE_NAME="datapond-airgap-${DATAPOND_VERSION}-$(date +%Y%m%d).tar.gz"
BUNDLE_PATH="${OUTPUT_DIR}/${BUNDLE_NAME}"
WORKDIR=$(mktemp -d)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[•]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*" >&2; }
die()  { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

[[ $EUID -eq 0 ]] || die "Run with sudo"
command -v docker &>/dev/null || die "Docker required to build images"

log "DataPond Air-Gap Bundle v${DATAPOND_VERSION}"
log "Output: $BUNDLE_PATH"
log "Working directory: $WORKDIR"

mkdir -p "$WORKDIR/images"

# ─── Build DataPond images ────────────────────────────────────────────────────
# Tag with :$APPVER to match the chart's image defaults (repository: datapond/<x>,
# tag: "" ⇒ chart appVersion). This lets ANY values profile (quicktest/onprem) consume
# the bundle without rewriting image tags — the freeze record lives in images-digests.txt.
log "Building backend image (${EDITION:-enterprise})..."
docker build -t "datapond/backend:$APPVER" \
  -f "$PROJECT_ROOT/backend/Dockerfile" --target "${EDITION:-enterprise}" \
  "$PROJECT_ROOT"
docker save "datapond/backend:$APPVER" -o "$WORKDIR/images/backend.tar"
ok "Backend image saved"

log "Building frontend image..."
docker build -t "datapond/frontend:$APPVER" "$PROJECT_ROOT/frontend/"
docker save "datapond/frontend:$APPVER" -o "$WORKDIR/images/frontend.tar"
ok "Frontend image saved"

# JupyterLab is a CUSTOM image (docker/jupyter/Dockerfile: scipy-notebook + DuckDB/
# PyIceberg + helper). It is NOT on a public registry, so it must be built here or the
# air-gapped install has no jupyter image to import.
log "Building jupyter image..."
docker build -t "datapond/jupyter:$APPVER" "$PROJECT_ROOT/docker/jupyter/"
docker save "datapond/jupyter:$APPVER" -o "$WORKDIR/images/jupyter.tar"
ok "Jupyter image saved"

# ─── Derive image list from the actual chart (single source of truth) ─────────
# 하드코딩 배열 대신 helm template으로 실제 차트가 쓰는 이미지를 추출 → 항상 정합.
# (이전 하드코딩은 차트와 불일치해 redis≠valkey, opensearch≠elasticsearch 등으로 깨졌음)
command -v helm &>/dev/null || die "Helm required to derive image list from chart"

VALUES_FILE="${VALUES_FILE:-$PROJECT_ROOT/helm/datapond/values-onprem.yaml}"
log "Deriving image list from chart ($VALUES_FILE)..."

# coredns 템플릿이 요구하는 clusterIP는 렌더 통과용 placeholder로만 주입(번들엔 영향 없음)
mapfile -t ALL_IMAGES < <(
  helm template datapond "$PROJECT_ROOT/helm/datapond" \
    --values "$VALUES_FILE" \
    --set seaweedfs.s3.clusterIP=10.0.0.1 2>/dev/null \
  | grep -E '^[[:space:]]*image:' \
  | sed -E 's/^[[:space:]]*image:[[:space:]]*//; s/^"//; s/"$//' \
  | grep -v '{{' \
  | sort -u
)
[[ ${#ALL_IMAGES[@]} -gt 0 ]] || die "Failed to derive images from chart (helm template returned nothing)"

# datapond/* 는 위에서 직접 빌드하므로 제외
THIRD_PARTY_IMAGES=()
for img in "${ALL_IMAGES[@]}"; do
  [[ -z "$img" ]] && continue
  [[ "$img" == datapond/* ]] && continue
  THIRD_PARTY_IMAGES+=("$img")
done
log "Found ${#THIRD_PARTY_IMAGES[@]} third-party images in chart"

# ─── Pull & save third-party images, recording exact digests (bundle freeze) ──
log "Pulling third-party images (this may take a while)..."
IMAGES_MANIFEST="$WORKDIR/images-digests.txt"
: > "$IMAGES_MANIFEST"
MISSING=()
for image in "${THIRD_PARTY_IMAGES[@]}"; do
  safe_name=$(echo "$image" | tr '/:@ ' '____')
  log "Pulling $image..."
  if ! docker pull "$image" 2>/dev/null; then
    echo "  [warn] FAILED: $image" >&2
    MISSING+=("$image")
    continue
  fi
  docker save "$image" -o "$WORKDIR/images/${safe_name}.tar"
  # 빌드시점 digest 기록 → moving/latest 태그라도 번들은 정확히 freeze됨(재현성)
  digest=$(docker inspect --format '{{ index .RepoDigests 0 }}' "$image" 2>/dev/null || echo "$image")
  echo "$image -> $digest" >> "$IMAGES_MANIFEST"
  ok "Saved: $image"
done

# 누락 이미지가 있으면 에어갭 설치가 깨지므로 명확히 실패시킴(silent skip 금지)
if [[ ${#MISSING[@]} -gt 0 ]]; then
  die "Pull 실패로 번들 불완전 — 에어갭 설치 시 기동 실패함: ${MISSING[*]}"
fi
ok "All ${#THIRD_PARTY_IMAGES[@]} third-party images saved (digests → images-digests.txt)"

# ─── Pull K3s binary + installer + SYSTEM airgap images ───────────────────────
# These are REQUIRED for an offline install — a silent skip would produce a bundle
# that fails to bootstrap on the target. Fail loudly instead.
log "Downloading K3s (binary + installer + system images)..."
K3S_VERSION="v1.29.3+k3s1"
K3S_TAG="${K3S_VERSION/+/%2B}"   # URL-encode '+' for the release path
curl -sfL "https://github.com/k3s-io/k3s/releases/download/${K3S_TAG}/k3s" \
  -o "$WORKDIR/k3s-binary" || die "K3s binary download failed — bundle would be unusable offline"
curl -sfL "https://get.k3s.io" -o "$WORKDIR/k3s-install.sh" \
  || die "K3s install script download failed"
# K3s system images (pause/coredns/traefik/local-path/metrics-server). Without these
# K3s never reaches Ready in an air-gapped environment.
curl -sfL "https://github.com/k3s-io/k3s/releases/download/${K3S_TAG}/k3s-airgap-images-amd64.tar.zst" \
  -o "$WORKDIR/k3s-airgap-images-amd64.tar.zst" \
  || die "K3s system airgap images download failed — air-gap K3s would not start"
chmod +x "$WORKDIR/k3s-binary" "$WORKDIR/k3s-install.sh"
ok "K3s binary + installer + system images bundled (${K3S_VERSION})"

# ─── Pull Helm binary ─────────────────────────────────────────────────────────
log "Downloading Helm..."
HELM_VERSION="v3.14.0"
curl -sfL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
  -o "$WORKDIR/helm.tar.gz" || die "Helm download failed — air-gap install needs the Helm binary"
ok "Helm binary bundled (${HELM_VERSION})"

# ─── Copy Helm chart and scripts ─────────────────────────────────────────────
log "Copying Helm chart and install scripts..."
cp -r "$PROJECT_ROOT/helm" "$WORKDIR/"
cp -r "$PROJECT_ROOT/scripts" "$WORKDIR/"
cp "$PROJECT_ROOT/README.md" "$WORKDIR/" 2>/dev/null || true

# No image-tag patching needed: datapond images are built as :latest above, which
# matches the chart's image defaults, so every values profile resolves them directly
# from the imported tars. (The earlier per-file sed only touched values.yaml +
# values-quicktest.yaml and missed values-onprem.yaml — the very profile this bundle
# is derived from — which silently broke on-prem air-gap installs.)

# ─── Create install entrypoint ───────────────────────────────────────────────
cat > "$WORKDIR/install.sh" <<'INSTALLER'
#!/bin/bash
# DataPond Air-Gap Installer (thin entrypoint).
# All offline logic — K3s (binary + system images), Helm, app images — lives in
# scripts/install.sh's --airgap path, so there is a single source of truth.
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }
echo "DataPond Air-Gap Installation — bundle: $BUNDLE_DIR"
exec bash "$BUNDLE_DIR/scripts/install.sh" --airgap "$BUNDLE_DIR" "$@"
INSTALLER
chmod +x "$WORKDIR/install.sh"

# ─── Create manifest file ─────────────────────────────────────────────────────
cat > "$WORKDIR/MANIFEST.txt" <<EOF
DataPond Air-Gap Bundle
Version: ${DATAPOND_VERSION}
Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Host: $(hostname)

Contents:
  images/                          Container images (*.tar)
  images-digests.txt               빌드시점 이미지 digest(재현성 기록)
  helm/                            Helm chart
  scripts/                         Installation scripts
  install.sh                       Air-gap installer entrypoint (→ scripts/install.sh --airgap)
  k3s-binary                       K3s binary (offline install)
  k3s-install.sh                   K3s installer script
  k3s-airgap-images-amd64.tar.zst  K3s system images (pause/coredns/traefik/…)
  helm.tar.gz                      Helm binary

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
