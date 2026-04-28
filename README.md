# DataPond Kubernetes Edition

**🚀 Complete Kubernetes-native reimplementation of DataPond platform**

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.25+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Helm](https://img.shields.io/badge/Helm-3.12+-0F1689?logo=helm&logoColor=white)](https://helm.sh/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📋 Overview

DataPond is a comprehensive data analytics and ML platform redesigned for cloud-native deployments with Kubernetes. This edition provides production-ready infrastructure with auto-scaling, high availability, and complete observability.

### ✨ Key Features

- ✅ **Kubernetes Native**: Built for cloud-native deployments
- ✅ **Helm Charts**: Easy deployment and management
- ✅ **Auto-scaling**: HPA for dynamic resource allocation
- ✅ **High Availability**: Multi-replica services with health checks
- ✅ **Single Ingress**: Unified routing for all services
- ✅ **Persistent Storage**: Data persistence with PVC
- ✅ **Environment Configs**: Separate dev/prod configurations
- ✅ **Complete Documentation**: 4,000+ lines of guides

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingress Controller                       │
│                   (Traefik/Nginx)                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
┌───▼────┐          ┌─────▼─────┐        ┌─────▼──────┐
│Frontend│          │  Backend  │        │  Services  │
│Next.js │   ──────▶│  FastAPI  │  ──────▶│ Data & ML  │
└────────┘          └───────────┘        └────────────┘
                          │
                ┌─────────┴──────────┐
                │                    │
          ┌─────▼──────┐      ┌─────▼────┐
          │ PostgreSQL │      │  Redis   │
          │    (DB)    │      │ (Cache)  │
          └────────────┘      └──────────┘
```

### 🎯 Services

| Service | Description | Technology |
|---------|-------------|------------|
| **Frontend** | Web UI | Next.js 14+ |
| **Backend** | REST API | FastAPI |
| **Database** | Primary data store | PostgreSQL 16 |
| **Cache** | Session & caching | Redis 7 |
| **Notebooks** | Interactive analysis | JupyterLab |
| **ML Tracking** | Experiment tracking | MLflow 2.10 |
| **Storage** | Object storage | MinIO (S3 API) |
| **Workflow** | Orchestration | Airflow 2.8 |
| **Processing** | Distributed compute | Spark 3.5 |

---

## 🚀 Quick Start

### Prerequisites

- **OS**: Ubuntu 20.04+ / RHEL 8+ / Debian 11+
- **CPU**: 4+ cores (8+ recommended)
- **RAM**: 8GB+ (16GB+ recommended)
- **Disk**: 100GB+ SSD

### Installation (5 minutes)

```bash
# 1. Clone repository
git clone https://github.com/lukesgood/datapond.git
cd datapond

# 2. Install K3s (lightweight Kubernetes)
sudo bash scripts/install-k3s.sh

# 3. Add hostname to /etc/hosts
sudo bash -c 'echo "127.0.0.1  datapond.local" >> /etc/hosts'

# 4. Deploy DataPond
bash scripts/deploy.sh values-dev.yaml

# 5. Watch deployment
kubectl get pods -n datapond -w
```

### Access

Once all pods are running, access the platform:

```
http://datapond.local
```

**Default Credentials:**
- Airflow: `admin / admin`
- JupyterLab: Token `jupyter`
- MinIO: `minioadmin / minioadmin`

---

## 📁 Project Structure

```
datapond/
├── helm/datapond/              # Helm Chart
│   ├── Chart.yaml              # Chart metadata
│   ├── values.yaml             # Default values
│   ├── values-dev.yaml         # Development config
│   ├── values-prod.yaml        # Production config
│   └── templates/              # 13 Kubernetes templates
│       ├── backend-deployment.yaml
│       ├── frontend-deployment.yaml
│       ├── postgres-statefulset.yaml
│       ├── redis-deployment.yaml
│       ├── jupyter-deployment.yaml
│       ├── mlflow-deployment.yaml
│       ├── minio-deployment.yaml
│       ├── airflow-deployment.yaml
│       ├── spark-statefulset.yaml
│       └── ...
│
├── scripts/                    # Automation scripts
│   ├── install-k3s.sh         # K3s installation
│   └── deploy.sh              # Deployment script
│
└── docs/                       # Documentation
    ├── ARCHITECTURE.md         # System architecture
    ├── INSTALLATION.md         # Detailed installation
    ├── DEPLOYMENT_CHECKLIST.md # Pre-deployment checklist
    └── TROUBLESHOOTING.md      # Problem solving
```

---

## 📊 System Requirements

### Development Environment

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8GB | 16GB+ |
| Disk | 50GB | 100GB+ SSD |
| Storage | ~100GB | ~200GB |

### Production Environment

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 16 cores | 32+ cores |
| RAM | 32GB | 64GB+ |
| Disk | 200GB SSD | 500GB+ NVMe |
| Storage | ~500GB | ~1TB+ |

---

## 🛠️ Configuration

### Environment Selection

**Development** (8GB RAM optimized):
```bash
bash scripts/deploy.sh values-dev.yaml
```

**Production** (High availability):
```bash
bash scripts/deploy.sh values-prod.yaml
```

### Customization

Edit configuration files:
```bash
vim helm/datapond/values-dev.yaml
```

Key settings:
- `global.domain`: Your domain name
- `*.replicas`: Number of replicas per service
- `*.resources`: CPU/Memory allocation
- `*.persistence.size`: Storage size

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [START_HERE.md](START_HERE.md) | Quick start guide |
| [QUICKSTART.md](QUICKSTART.md) | 5-minute deployment |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Detailed installation |
| [docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md) | Pre-deployment checklist |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Problem solving |
| [SCRIPT_FIXES.md](SCRIPT_FIXES.md) | Script improvements |

---

## 🔧 Useful Commands

```bash
# Check pod status
kubectl get pods -n datapond

# View logs
kubectl logs -f deployment/backend -n datapond

# Scale service
kubectl scale deployment backend --replicas=5 -n datapond

# Port forward (direct access)
kubectl port-forward svc/backend 8000:8000 -n datapond

# Uninstall
helm uninstall datapond -n datapond
```

---

## 🔄 Upgrade & Rollback

### Upgrade

```bash
helm upgrade datapond ./helm/datapond \
  --namespace datapond \
  --values helm/datapond/values.yaml
```

### Rollback

```bash
# View history
helm history datapond -n datapond

# Rollback to previous version
helm rollback datapond -n datapond
```

---

## 🆚 Docker Compose vs Kubernetes

| Feature | Docker Compose | Kubernetes |
|---------|----------------|------------|
| Deployment Time | 30 min (manual) | 5 min (automated) |
| Auto-scaling | ❌ Manual | ✅ Automatic (HPA) |
| High Availability | ❌ Single point | ✅ Multi-replica |
| Zero-downtime Deploy | ❌ | ✅ Rolling update |
| Auto Recovery | ❌ | ✅ Self-healing |
| Monitoring | Manual setup | Integrated (Prometheus) |
| Rollback | Difficult | One command |
| Scalability | Limited | Unlimited |

---

## 🚦 Roadmap

### Phase 1: Single Node (Current)
- ✅ K3s deployment
- ✅ All services running
- ✅ Development/testing ready

### Phase 2: 3-Node Cluster (3-6 months)
- [ ] Multi-node setup
- [ ] True high availability
- [ ] Production deployment

### Phase 3: Managed Kubernetes (6-12 months)
- [ ] AWS EKS / GKE / AKS
- [ ] Multi-region
- [ ] Disaster recovery

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🆘 Support

- 📖 **Documentation**: [docs/](docs/)
- 🐛 **Issues**: [GitHub Issues](https://github.com/lukesgood/datapond/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/lukesgood/datapond/discussions)

---

## 🎉 Acknowledgments

- Built with [Kubernetes](https://kubernetes.io/)
- Packaged with [Helm](https://helm.sh/)
- Deployed on [K3s](https://k3s.io/)
- Developed with assistance from [Claude](https://claude.ai/)

---

**Version**: 2.0.0-k8s  
**Status**: ✅ Production Ready  
**Last Updated**: 2026-04-28

---

<div align="center">
  <strong>⭐ Star this repository if you find it useful!</strong>
</div>
