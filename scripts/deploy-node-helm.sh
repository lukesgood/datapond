#!/usr/bin/env bash
#
# Deploy a specific image tag to the single-node K3s cluster by pulling from ECR.
# Runs ON the node (invoked by SSM from CI, or manually inside `aws ssm start-session`).
# Images for <tag> MUST already exist in ECR (the CI build-push job puts them there);
# this script does NOT build or push — it only rolls the cluster to that tag.
#
# Usage: sudo bash deploy-node-helm.sh <image-tag> [s3://bucket/chart.tgz]
#   <image-tag>          e.g. 2.3.0-9215a2a  (immutable ECR tag)
#   [chart tarball]      optional s3 URI of a `tar czf helm/datapond` bundle; when given,
#                        the chart is fetched from S3 so the node needs no repo checkout.
#
set -euo pipefail

TAG="${1:?usage: deploy-node-helm.sh <image-tag> [s3://bucket/chart.tgz]}"
CHART_S3="${2:-}"
NS="datapond"
RELEASE="datapond"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -n "$CHART_S3" ]; then
  aws s3 cp "$CHART_S3" "$WORK/chart.tgz"
  tar xzf "$WORK/chart.tgz" -C "$WORK"
  CHART="$WORK/helm/datapond"
else
  # Fall back to a repo checkout synced to the node.
  CHART="${DATAPOND_CHART_DIR:-/home/ubuntu/datapond/helm/datapond}"
fi
[ -d "$CHART" ] || { echo "chart not found at $CHART"; exit 1; }

echo "== deploying $TAG from ECR =="
# --reset-then-reuse-values: keep the live release's custom values (Aurora host, ECR
#   repos, ingress domain, catalog, RLS, …) while picking up new chart defaults; only
#   override the image tags. pullPolicy IfNotPresent + an immutable SHA tag ⇒ the node
#   pulls this exact tag from ECR the first time and caches it.
helm -n "$NS" upgrade "$RELEASE" "$CHART" \
  --reset-then-reuse-values \
  --set-string backend.image.tag="$TAG" \
  --set-string frontend.image.tag="$TAG" \
  --set backend.image.pullPolicy=IfNotPresent \
  --set frontend.image.pullPolicy=IfNotPresent \
  --wait --timeout 300s

kubectl -n "$NS" rollout status deploy/backend  --timeout=200s
kubectl -n "$NS" rollout status deploy/frontend --timeout=200s
kubectl -n "$NS" get deploy backend frontend \
  -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image --no-headers
echo "== deployed $TAG =="
