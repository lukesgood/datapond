#!/bin/bash
# Install Docker for building DataPond images
# Alternative: Install nerdctl for native containerd builds

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "Select installation option:"
echo "  1) Install Docker (recommended, most compatible)"
echo "  2) Install nerdctl (lightweight, containerd-native)"
echo "  3) Exit"
read -p "Choice [1]: " choice
choice=${choice:-1}

case $choice in
    1)
        log_info "Installing Docker..."

        # Remove old versions
        sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

        # Install dependencies
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg lsb-release

        # Add Docker's official GPG key
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

        # Set up repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Install Docker
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # Add user to docker group
        sudo usermod -aG docker $USER

        log_success "Docker installed successfully!"
        log_warning "You need to log out and back in for group changes to take effect"
        log_info "Or run: newgrp docker"
        ;;

    2)
        log_info "Installing nerdctl..."

        # Download nerdctl
        NERDCTL_VERSION="1.7.3"
        cd /tmp
        wget https://github.com/containerd/nerdctl/releases/download/v${NERDCTL_VERSION}/nerdctl-${NERDCTL_VERSION}-linux-amd64.tar.gz

        # Extract and install
        sudo tar Cxzvvf /usr/local/bin nerdctl-${NERDCTL_VERSION}-linux-amd64.tar.gz

        # Install buildkit for nerdctl build support
        BUILDKIT_VERSION="0.12.5"
        wget https://github.com/moby/buildkit/releases/download/v${BUILDKIT_VERSION}/buildkit-v${BUILDKIT_VERSION}.linux-amd64.tar.gz
        sudo tar Cxzvvf /usr/local buildkit-v${BUILDKIT_VERSION}.linux-amd64.tar.gz

        # Create buildkit systemd service
        sudo tee /etc/systemd/system/buildkit.service > /dev/null <<EOF
[Unit]
Description=BuildKit
Documentation=https://github.com/moby/buildkit

[Service]
ExecStart=/usr/local/bin/buildkitd --oci-worker=false --containerd-worker=true

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable buildkit
        sudo systemctl start buildkit

        log_success "nerdctl and buildkit installed successfully!"
        log_info "Test with: nerdctl version"
        ;;

    3)
        log_info "Installation cancelled"
        exit 0
        ;;

    *)
        log_error "Invalid choice"
        exit 1
        ;;
esac

# Verify installation
echo ""
log_info "Verifying installation..."
if command -v docker &> /dev/null; then
    docker version
    log_success "Docker is ready!"
elif command -v nerdctl &> /dev/null; then
    nerdctl version
    log_success "nerdctl is ready!"
else
    log_error "Installation failed or requires restart"
    exit 1
fi
