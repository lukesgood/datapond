#!/bin/bash
# DataPond 빌드 스크립트 - sudo 불필요 (fix-permissions.sh 1회 실행 후)
set -e

cd "$(dirname "$0")/.."

TARGET="${1:-all}"   # all | backend | frontend
TAG="${2:-$(grep '^appVersion:' helm/datapond/Chart.yaml | tr -d ' "' | cut -d: -f2)}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[•]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# 권한 체크
if ! docker info &>/dev/null; then
  err "Docker 접근 불가. 다음 명령으로 권한 설정 후 터미널 재시작:\n  sudo bash /tmp/fix-permissions.sh"
fi

build_and_import() {
  local name=$1
  local ctx=$2
  log "Building datapond/${name}:${TAG}..."
  docker build -t "datapond/${name}:${TAG}" "$ctx"

  log "Importing into k3s containerd..."
  docker save "datapond/${name}:${TAG}" | \
    k3s ctr --address /run/k3s/containerd/containerd.sock images import -
  ok "${name} image ready"
}

restart_deployment() {
  local name=$1
  log "Restarting ${name}..."
  kubectl rollout restart "deployment/${name}" -n datapond
  sleep 5
  kubectl delete pods -n datapond --field-selector=status.phase=Pending 2>/dev/null || true
  ok "${name} restarted"
}

build_backend() {
  # EDITION: enterprise (default, includes /ee) | community (Apache-2.0 only)
  log "Building datapond/backend:${TAG} (${EDITION:-enterprise})..."
  docker build -t "datapond/backend:${TAG}" -f backend/Dockerfile --target "${EDITION:-enterprise}" .
  log "Importing into k3s containerd..."
  docker save "datapond/backend:${TAG}" | \
    k3s ctr --address /run/k3s/containerd/containerd.sock images import -
  ok "backend image ready"
}

case "$TARGET" in
  backend)
    build_backend
    restart_deployment backend
    ;;
  frontend)
    build_and_import frontend frontend/
    restart_deployment frontend
    ;;
  all)
    build_backend
    build_and_import frontend frontend/
    kubectl rollout restart deployment/backend deployment/frontend -n datapond
    sleep 10
    kubectl delete pods -n datapond --field-selector=status.phase=Pending 2>/dev/null || true
    ;;
  *)
    echo "Usage: $0 [all|backend|frontend] [tag]"
    exit 1
    ;;
esac

echo ""
kubectl get pods -n datapond | grep -E "backend|frontend"
