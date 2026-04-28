#!/bin/bash

# DataPond K3s Installation Script
# This script installs K3s (lightweight Kubernetes) on your system

set -e

echo "==========================================="
echo "  DataPond K3s Installation"
echo "==========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: This script must be run as root (use sudo)"
  exit 1
fi

# Check system requirements
echo "Checking system requirements..."
TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
if [ "$TOTAL_RAM" -lt 8 ]; then
  echo "WARNING: Less than 8GB RAM detected ($TOTAL_RAM GB). K3s may run slowly."
  read -p "Continue anyway? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 1
  fi
fi

# Check if K3s is already installed
if command -v k3s &> /dev/null; then
  echo "WARNING: K3s is already installed"
  k3s --version
  read -p "Reinstall K3s? This will remove existing installation. (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstalling existing K3s..."
    /usr/local/bin/k3s-uninstall.sh 2>/dev/null || true
    sleep 5
  else
    echo "Skipping K3s installation..."
    SKIP_K3S=true
  fi
fi

# Install K3s
if [ "$SKIP_K3S" != "true" ]; then
  echo ""
  echo "Installing K3s..."
  curl -sfL https://get.k3s.io | sh -s - \
    --write-kubeconfig-mode 644

  # Wait for K3s to be ready
  echo ""
  echo "Waiting for K3s to be ready..."
  sleep 15

  # Check K3s status
  echo "K3s service status:"
  systemctl status k3s --no-pager | head -10 || true
fi

# Setup kubectl for current user
echo ""
echo "Setting up kubectl access..."
ACTUAL_USER=${SUDO_USER:-$USER}
if [ "$ACTUAL_USER" == "root" ]; then
  echo "WARNING: Running as root, setting up kubectl for root user"
  ACTUAL_USER="root"
  USER_HOME="/root"
else
  USER_HOME="/home/$ACTUAL_USER"
fi

mkdir -p $USER_HOME/.kube
if [ -f /etc/rancher/k3s/k3s.yaml ]; then
  cp /etc/rancher/k3s/k3s.yaml $USER_HOME/.kube/config
  if [ "$ACTUAL_USER" != "root" ]; then
    chown -R $ACTUAL_USER:$ACTUAL_USER $USER_HOME/.kube
  fi
  chmod 600 $USER_HOME/.kube/config
  echo "kubectl config copied to $USER_HOME/.kube/config"
else
  echo "ERROR: K3s config file not found at /etc/rancher/k3s/k3s.yaml"
  exit 1
fi

# Install Helm
echo ""
echo "Installing Helm..."
if ! command -v helm &> /dev/null; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
  echo "Helm installed successfully"
else
  HELM_VERSION=$(helm version --short)
  echo "Helm is already installed: $HELM_VERSION"
fi

# Wait for K3s to be fully ready
echo ""
echo "Waiting for Kubernetes to be fully ready..."
for i in {1..30}; do
  if kubectl get nodes &>/dev/null; then
    echo "Kubernetes is ready!"
    break
  fi
  echo "Waiting... ($i/30)"
  sleep 2
done

# Check Traefik (K3s default ingress)
echo ""
echo "Checking Traefik Ingress Controller..."
if kubectl get pods -n kube-system | grep -q traefik; then
  echo "Traefik is already installed (K3s default)"
  INSTALL_NGINX=false
else
  echo "Traefik not found"
  INSTALL_NGINX=true
fi

# Option to install Nginx Ingress Controller
if [ "$INSTALL_NGINX" == "true" ]; then
  read -p "Install Nginx Ingress Controller? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Installing Nginx Ingress Controller..."
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml

    # Wait for Ingress Controller
    echo "Waiting for Ingress Controller to be ready..."
    kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=120s 2>/dev/null || echo "Timeout waiting for Nginx Ingress Controller (it may still be starting)"
  fi
fi

# Install Metrics Server (for HPA)
echo ""
echo "Installing Metrics Server..."
if kubectl get deployment metrics-server -n kube-system &>/dev/null; then
  echo "Metrics Server is already installed"
else
  kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

  # Wait a bit for deployment to be created
  sleep 5

  # Patch Metrics Server for K3s (allow insecure TLS)
  echo "Patching Metrics Server for K3s..."
  kubectl patch deployment metrics-server -n kube-system --type='json' \
    -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]' 2>/dev/null || true

  echo "Metrics Server installed (may take a minute to be ready)"
fi

# Verify installation
echo ""
echo "==========================================="
echo "  Installation Complete!"
echo "==========================================="
echo ""

# Show cluster info
echo "Cluster information:"
kubectl cluster-info 2>/dev/null || echo "kubectl cluster-info failed"

echo ""
echo "Kubernetes nodes:"
kubectl get nodes

echo ""
echo "Kubernetes version:"
kubectl version --short 2>/dev/null || kubectl version

echo ""
echo "System pods:"
kubectl get pods -n kube-system

echo ""
echo "Storage class:"
kubectl get storageclass

echo ""
echo "==========================================="
echo "  Configuration"
echo "==========================================="
echo ""
echo "kubectl config: $USER_HOME/.kube/config"
echo ""
if [ "$ACTUAL_USER" != "root" ]; then
  echo "To use kubectl as $ACTUAL_USER:"
  echo "  export KUBECONFIG=$USER_HOME/.kube/config"
  echo "  # or (already configured):"
  echo "  kubectl get nodes"
fi
echo ""
echo "==========================================="
echo "  Next Steps"
echo "==========================================="
echo ""
echo "1. Add hostname to /etc/hosts:"
echo "   sudo bash -c 'echo \"127.0.0.1  datapond.local\" >> /etc/hosts'"
echo ""
echo "2. Deploy DataPond:"
echo "   cd /home/luke/datapond-k8s"
echo "   bash scripts/deploy.sh values-dev.yaml"
echo ""
echo "3. Check deployment:"
echo "   kubectl get pods -n datapond -w"
echo ""
echo "4. Access DataPond:"
echo "   http://datapond.local"
echo ""
