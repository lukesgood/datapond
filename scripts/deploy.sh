#!/bin/bash

# DataPond Deployment Script
# Deploys DataPond to Kubernetes using Helm

set -e

NAMESPACE="datapond"
RELEASE_NAME="datapond"
CHART_PATH="./helm/datapond"
VALUES_FILE="${1:-values.yaml}"

echo "==========================================="
echo "  DataPond Kubernetes Deployment"
echo "==========================================="
echo ""

# Check if running from correct directory
if [ ! -d "helm/datapond" ]; then
  echo "ERROR: Must run from /home/luke/datapond-k8s directory"
  echo "Current directory: $(pwd)"
  echo ""
  echo "Usage: cd /home/luke/datapond-k8s && bash scripts/deploy.sh [values-file]"
  exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
  echo "ERROR: kubectl is not installed"
  echo "Please install K3s first: sudo bash scripts/install-k3s.sh"
  exit 1
fi

# Check if helm is available
if ! command -v helm &> /dev/null; then
  echo "ERROR: helm is not installed"
  echo "Please install K3s first: sudo bash scripts/install-k3s.sh"
  exit 1
fi

# Check if values file exists
if [ ! -f "$CHART_PATH/$VALUES_FILE" ]; then
  echo "ERROR: Values file not found: $CHART_PATH/$VALUES_FILE"
  echo ""
  echo "Available values files:"
  ls -1 $CHART_PATH/values*.yaml
  echo ""
  echo "Usage: bash scripts/deploy.sh [values-file]"
  echo "Example: bash scripts/deploy.sh values-dev.yaml"
  exit 1
fi

echo "Configuration:"
echo "  - Chart path: $CHART_PATH"
echo "  - Values file: $VALUES_FILE"
echo "  - Namespace: $NAMESPACE"
echo "  - Release name: $RELEASE_NAME"
echo ""

# Check if cluster is accessible
echo "Checking Kubernetes cluster..."
if ! kubectl cluster-info &> /dev/null; then
  echo "ERROR: Cannot connect to Kubernetes cluster"
  echo ""
  echo "Troubleshooting:"
  echo "  1. Check if K3s is running: sudo systemctl status k3s"
  echo "  2. Check kubeconfig: echo \$KUBECONFIG"
  echo "  3. Try: export KUBECONFIG=~/.kube/config"
  exit 1
fi

# Show cluster info
kubectl get nodes
echo "✓ Kubernetes cluster is accessible"
echo ""

# Validate Helm chart
echo "Validating Helm chart..."
if ! helm lint $CHART_PATH --values $CHART_PATH/$VALUES_FILE; then
  echo "ERROR: Helm chart validation failed"
  exit 1
fi
echo "✓ Helm chart is valid"
echo ""

# Create namespace if it doesn't exist
echo "Creating namespace: $NAMESPACE"
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
echo ""

# Check if release already exists
if helm list -n $NAMESPACE 2>/dev/null | grep -q "^$RELEASE_NAME"; then
  echo "⚠️  Release '$RELEASE_NAME' already exists in namespace '$NAMESPACE'"
  echo ""
  helm list -n $NAMESPACE
  echo ""
  read -p "Do you want to upgrade it? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Upgrading DataPond..."
    echo "This may take 5-10 minutes..."

    helm upgrade $RELEASE_NAME $CHART_PATH \
      --namespace $NAMESPACE \
      --values $CHART_PATH/$VALUES_FILE \
      --timeout 10m \
      --wait \
      --debug 2>&1 | tee /tmp/datapond-upgrade.log

    echo ""
    echo "✓ Upgrade complete!"
    ACTION="upgraded"
  else
    echo ""
    echo "Deployment cancelled"
    echo ""
    echo "To uninstall existing release:"
    echo "  helm uninstall $RELEASE_NAME -n $NAMESPACE"
    exit 0
  fi
else
  echo "Installing DataPond (first time)..."
  echo "This may take 5-10 minutes..."
  echo ""

  # Show what will be deployed
  echo "Resources to be created:"
  helm template $RELEASE_NAME $CHART_PATH \
    --namespace $NAMESPACE \
    --values $CHART_PATH/$VALUES_FILE \
    | grep "^kind:" | sort | uniq -c
  echo ""

  read -p "Continue with installation? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled"
    exit 0
  fi

  echo ""
  echo "Installing..."

  helm install $RELEASE_NAME $CHART_PATH \
    --namespace $NAMESPACE \
    --create-namespace \
    --values $CHART_PATH/$VALUES_FILE \
    --timeout 10m \
    --wait \
    --debug 2>&1 | tee /tmp/datapond-install.log

  echo ""
  echo "✓ Installation complete!"
  ACTION="installed"
fi

# Show deployment status
echo ""
echo "==========================================="
echo "  Deployment Status"
echo "==========================================="
echo ""

echo "Helm release:"
helm list -n $NAMESPACE

echo ""
echo "Pods:"
kubectl get pods -n $NAMESPACE -o wide

echo ""
echo "Services:"
kubectl get svc -n $NAMESPACE

echo ""
echo "Ingress:"
kubectl get ingress -n $NAMESPACE 2>/dev/null || echo "No ingress found"

echo ""
echo "PersistentVolumeClaims:"
kubectl get pvc -n $NAMESPACE

echo ""
echo "==========================================="
echo "  Resource Usage"
echo "==========================================="
echo ""

# Wait a bit for metrics to be available
sleep 5
kubectl top nodes 2>/dev/null || echo "Metrics not available yet (metrics-server may still be starting)"

echo ""
echo "==========================================="
echo "  Access Information"
echo "==========================================="
echo ""

# Check if hostname is in /etc/hosts
if ! grep -q "datapond.local" /etc/hosts 2>/dev/null; then
  echo "⚠️  WARNING: datapond.local not found in /etc/hosts"
  echo ""
  echo "Add this line to /etc/hosts:"
  echo "  sudo bash -c 'echo \"127.0.0.1  datapond.local\" >> /etc/hosts'"
  echo ""
else
  echo "✓ datapond.local is configured in /etc/hosts"
  echo ""
fi

echo "Access URLs:"
echo "  Frontend:     http://datapond.local"
echo "  Backend API:  http://datapond.local/api/health"
echo "  JupyterLab:   http://datapond.local/jupyter"
echo "  MLflow:       http://datapond.local/mlflow"
echo "  Airflow:      http://datapond.local/airflow"
echo "  Spark UI:     http://datapond.local/spark"
echo "  MinIO:        http://datapond.local/minio-console"
echo ""

echo "Default credentials:"
echo "  Airflow:   admin / admin"
echo "  Jupyter:   Token: jupyter"
echo "  MinIO:     minioadmin / minioadmin"
echo ""

echo "==========================================="
echo "  Useful Commands"
echo "==========================================="
echo ""
echo "Watch pod status:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo ""
echo "View logs:"
echo "  kubectl logs -f deployment/backend -n $NAMESPACE"
echo "  kubectl logs -f deployment/frontend -n $NAMESPACE"
echo ""
echo "Describe pod (troubleshooting):"
echo "  kubectl describe pod <pod-name> -n $NAMESPACE"
echo ""
echo "Port forward (direct access):"
echo "  kubectl port-forward svc/backend 8000:8000 -n $NAMESPACE"
echo ""
echo "Uninstall:"
echo "  helm uninstall $RELEASE_NAME -n $NAMESPACE"
echo ""

# Check if pods are running
echo "==========================================="
echo "  Pod Health Check"
echo "==========================================="
echo ""

TOTAL_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | wc -l)
RUNNING_PODS=$(kubectl get pods -n $NAMESPACE --no-headers | grep Running | wc -l)

echo "Pods: $RUNNING_PODS/$TOTAL_PODS running"
echo ""

if [ "$RUNNING_PODS" -eq "$TOTAL_PODS" ]; then
  echo "✓ All pods are running!"
  echo ""
  echo "🎉 DataPond has been successfully $ACTION!"
  echo ""
  echo "You can now access the application at:"
  echo "  http://datapond.local"
else
  echo "⚠️  Some pods are not running yet"
  echo ""
  echo "This is normal during initial deployment."
  echo "Pods may take 5-10 minutes to start."
  echo ""
  echo "Monitor progress with:"
  echo "  kubectl get pods -n $NAMESPACE -w"
  echo ""
  echo "Check pod details:"
  kubectl get pods -n $NAMESPACE | grep -v Running || true
  echo ""
  echo "If pods stay in Pending/Error state, check:"
  echo "  kubectl describe pod <pod-name> -n $NAMESPACE"
  echo ""
  echo "Common issues:"
  echo "  - ImagePullBackOff: Images need to be built locally"
  echo "  - Pending: Insufficient resources (CPU/Memory)"
  echo "  - CrashLoopBackOff: Check logs with 'kubectl logs <pod-name>'"
  echo ""
  echo "For detailed troubleshooting:"
  echo "  cat docs/TROUBLESHOOTING.md"
fi

echo ""
echo "Deployment log saved to: /tmp/datapond-${ACTION}.log"
echo ""
