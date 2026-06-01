"""
Kubernetes client for fetching cluster metrics
"""
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Dict, List, Optional
import os
import logging

logger = logging.getLogger(__name__)

class K8sClient:
    def __init__(self):
        """Initialize K8s client"""
        try:
            # Try in-cluster config first (when running in K8s)
            config.load_incluster_config()
            logger.info("Loaded in-cluster K8s config")
        except:
            try:
                # Fall back to kubeconfig (for local development)
                config.load_kube_config()
                logger.info("Loaded kubeconfig for local development")
            except Exception as e:
                logger.error(f"Failed to load K8s config: {e}")
                raise

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.namespace = os.getenv("DATAPOND_NAMESPACE", "datapond")
        logger.info(f"K8s client initialized for namespace: {self.namespace}")

    async def get_pod_metrics(self) -> Dict[str, any]:
        """
        Get aggregated pod metrics for the DataPond namespace

        Returns:
            {
                "total_pods": 12,
                "running_pods": 11,
                "pending_pods": 1,
                "failed_pods": 0,
                "cpu_usage_percent": 45.2,
                "memory_usage_percent": 62.3
            }
        """
        try:
            # Get all pods in namespace
            pods = self.core_v1.list_namespaced_pod(self.namespace)

            total_pods = len(pods.items)
            running = sum(1 for p in pods.items if p.status.phase == "Running")
            pending = sum(1 for p in pods.items if p.status.phase == "Pending")
            failed = sum(1 for p in pods.items if p.status.phase == "Failed")

            # Get real metrics from metrics-server via kubectl top nodes
            cpu_usage, memory_usage = self._get_node_metrics()

            return {
                "total_pods": total_pods,
                "running_pods": running,
                "pending_pods": pending,
                "failed_pods": failed,
                "cpu_usage_percent": cpu_usage,
                "memory_usage_percent": memory_usage
            }
        except ApiException as e:
            logger.error(f"K8s API error: {e}")
            return {
                "total_pods": 0,
                "running_pods": 0,
                "pending_pods": 0,
                "failed_pods": 0,
                "cpu_usage_percent": None,
                "memory_usage_percent": None
            }

    def _parse_cpu_nano(self, s: str) -> int:
        if s.endswith("n"): return int(s[:-1])
        if s.endswith("m"): return int(s[:-1]) * 1_000_000
        return int(s) * 1_000_000_000

    def _parse_mem_bytes(self, s: str) -> int:
        if s.endswith("Ki"): return int(s[:-2]) * 1024
        if s.endswith("Mi"): return int(s[:-2]) * 1024 ** 2
        if s.endswith("Gi"): return int(s[:-2]) * 1024 ** 3
        return int(s)

    def _get_node_metrics(self) -> tuple:
        """
        Get CPU/Memory % from pod metrics-server + node info via configmap fallback.
        - Pod metrics API: namespace-scoped (always accessible)
        - Node allocatable: tries ClusterRole, falls back to reading node via pod's
          own node name from downward API env, then hard-coded cluster node size.
        Returns (cpu_percent, memory_percent).
        """
        try:
            custom = client.CustomObjectsApi()
            pod_metrics = custom.list_namespaced_custom_object(
                "metrics.k8s.io", "v1beta1", self.namespace, "pods"
            )

            total_cpu_nano = 0
            total_mem_bytes = 0
            for pod in pod_metrics.get("items", []):
                for c in pod.get("containers", []):
                    u = c.get("usage", {})
                    total_cpu_nano  += self._parse_cpu_nano(u.get("cpu", "0n"))
                    total_mem_bytes += self._parse_mem_bytes(u.get("memory", "0Ki"))

            # Try to get node allocatable (needs ClusterRole)
            alloc_cpu_nano = None
            alloc_mem_bytes = None
            try:
                nodes = self.core_v1.list_node()
                alloc_cpu_nano  = sum(self._parse_cpu_nano(n.status.allocatable.get("cpu","0"))  for n in nodes.items)
                alloc_mem_bytes = sum(self._parse_mem_bytes(n.status.allocatable.get("memory","0Ki")) for n in nodes.items)
            except Exception:
                # Try reading own node via pod spec (needs get pod permission)
                try:
                    own_pod = self.core_v1.read_namespaced_pod(
                        os.getenv("HOSTNAME", ""), self.namespace
                    )
                    node_name = own_pod.spec.node_name
                    node = self.core_v1.read_node(node_name)
                    alloc_cpu_nano  = self._parse_cpu_nano(node.status.allocatable.get("cpu","0"))
                    alloc_mem_bytes = self._parse_mem_bytes(node.status.allocatable.get("memory","0Ki"))
                except Exception:
                    # Last resort: read from K8s node info configmap or use env hint
                    node_cpu_cores = int(os.getenv("NODE_CPU_CORES", "0"))
                    node_mem_gb    = int(os.getenv("NODE_MEMORY_GB", "0"))
                    if node_cpu_cores and node_mem_gb:
                        alloc_cpu_nano  = node_cpu_cores * 1_000_000_000
                        alloc_mem_bytes = node_mem_gb * 1024 ** 3

            if alloc_cpu_nano and alloc_mem_bytes:
                cpu_pct = round(total_cpu_nano  / alloc_cpu_nano  * 100, 1)
                mem_pct = round(total_mem_bytes / alloc_mem_bytes * 100, 1)
                return cpu_pct, mem_pct

            # Return absolute values in millicores/MiB when no node info
            return total_cpu_nano / 1_000_000, total_mem_bytes / (1024**2)

        except Exception as e:
            logger.warning(f"metrics-server unavailable: {e}")
            return None, None

    def _get_all_pods_cached(self) -> List:
        """
        Get all pods once and cache for performance
        Cache expires after 5 seconds
        """
        import time
        current_time = time.time()

        if not hasattr(self, '_pods_cache') or not hasattr(self, '_pods_cache_time'):
            self._pods_cache = None
            self._pods_cache_time = 0

        # Return cached if less than 5 seconds old
        if self._pods_cache and (current_time - self._pods_cache_time) < 5:
            return self._pods_cache

        # Fetch fresh data
        try:
            pods = self.core_v1.list_namespaced_pod(self.namespace)
            self._pods_cache = pods.items
            self._pods_cache_time = current_time
            return self._pods_cache
        except ApiException as e:
            logger.error(f"Error getting all pods: {e}")
            return self._pods_cache if self._pods_cache else []

    async def get_service_pods(self, service_name: str) -> List[Dict]:
        """
        Get pods for a specific service (using cache for performance)

        Args:
            service_name: Name like "mlflow", "trino", "postgres"

        Returns:
            List of pod info dicts
        """
        try:
            # Get all pods from cache
            all_pods = self._get_all_pods_cached()

            # Filter by label
            service_pods = []
            for pod in all_pods:
                labels = pod.metadata.labels or {}
                if (labels.get("app") == service_name or
                    labels.get("app.kubernetes.io/name") == service_name):
                    service_pods.append({
                        "name": pod.metadata.name,
                        "phase": pod.status.phase,
                        "ready": self._is_pod_ready(pod),
                        "restarts": self._get_restart_count(pod)
                    })

            return service_pods
        except ApiException as e:
            logger.error(f"Error getting pods for {service_name}: {e}")
            return []

    def _is_pod_ready(self, pod) -> bool:
        """Check if pod is ready"""
        if not pod.status.conditions:
            return False
        for condition in pod.status.conditions:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    def _get_restart_count(self, pod) -> int:
        """Get total restart count for pod"""
        if not pod.status.container_statuses:
            return 0
        return sum(c.restart_count for c in pod.status.container_statuses)

    async def get_service_health(self, service_name: str) -> str:
        """
        Get health status for a service based on its pods

        Returns:
            "healthy", "unhealthy", or "unknown"
        """
        pods = await self.get_service_pods(service_name)

        if not pods:
            return "unknown"

        # Service is healthy if all pods are running and ready
        all_running = all(p["phase"] == "Running" for p in pods)
        all_ready = all(p["ready"] for p in pods)

        if all_running and all_ready:
            return "healthy"
        else:
            return "unhealthy"

    def get_system_info(self) -> Dict[str, any]:
        """
        노드 사양/OS/런타임 + 컴포넌트 버전 + 스토리지(PVC) + 사용량.
        블로킹 호출 — 엔드포인트에서 스레드로 오프로드해 호출한다.
        """
        info: Dict[str, any] = {"node": {}, "cluster": {}, "components": [], "storage": [], "usage": {}}

        # ── 노드 사양/OS (backend pod가 떠 있는 노드) ──────────────────────────
        try:
            own_pod = self.core_v1.read_namespaced_pod(os.getenv("HOSTNAME", ""), self.namespace)
            node = self.core_v1.read_node(own_pod.spec.node_name)
            ni = node.status.node_info
            cap = node.status.capacity or {}
            info["node"] = {
                "name": node.metadata.name,
                "os": ni.os_image,
                "kernel": ni.kernel_version,
                "arch": ni.architecture,
                "container_runtime": ni.container_runtime_version,
                "kubelet": ni.kubelet_version,
                "cpu_cores": int(self._parse_cpu_nano(cap.get("cpu", "0")) / 1_000_000_000),
                "memory_gb": round(self._parse_mem_bytes(cap.get("memory", "0Ki")) / (1024 ** 3), 1),
                "ephemeral_storage_gb": round(self._parse_mem_bytes(cap.get("ephemeral-storage", "0Ki")) / (1024 ** 3), 1),
                "max_pods": int(cap.get("pods", "0")),
            }
            info["cluster"] = {"kubernetes": ni.kubelet_version}
        except Exception as e:
            logger.warning(f"node info unavailable: {e}")

        # ── Pod 요약 ──────────────────────────────────────────────────────────
        try:
            pods = self._get_all_pods_cached()
            info["cluster"]["pods_running"] = sum(1 for p in pods if p.status.phase == "Running")
            info["cluster"]["pods_total"] = len(pods)
        except Exception as e:
            logger.warning(f"pod summary unavailable: {e}")

        # ── 컴포넌트/이미지 버전 ──────────────────────────────────────────────
        try:
            comps = []
            for d in self.apps_v1.list_namespaced_deployment(self.namespace).items:
                comps.append({"name": d.metadata.name, "kind": "Deployment",
                              "image": d.spec.template.spec.containers[0].image,
                              "replicas": f"{d.status.ready_replicas or 0}/{d.spec.replicas or 0}"})
            for s in self.apps_v1.list_namespaced_stateful_set(self.namespace).items:
                comps.append({"name": s.metadata.name, "kind": "StatefulSet",
                              "image": s.spec.template.spec.containers[0].image,
                              "replicas": f"{s.status.ready_replicas or 0}/{s.spec.replicas or 0}"})
            info["components"] = sorted(comps, key=lambda c: c["name"])
        except Exception as e:
            logger.warning(f"components unavailable: {e}")

        # ── 영속 스토리지(PVC) ────────────────────────────────────────────────
        try:
            pvcs = self.core_v1.list_namespaced_persistent_volume_claim(self.namespace)
            info["storage"] = sorted([
                {"name": p.metadata.name,
                 "capacity": (p.status.capacity or {}).get("storage", "-"),
                 "status": p.status.phase,
                 "storage_class": p.spec.storage_class_name}
                for p in pvcs.items
            ], key=lambda x: x["name"])
        except Exception as e:
            logger.warning(f"PVC info unavailable: {e}")

        # ── 실시간 사용량 ─────────────────────────────────────────────────────
        try:
            cpu_pct, mem_pct = self._get_node_metrics()
            info["usage"] = {"cpu_percent": cpu_pct, "memory_percent": mem_pct}
        except Exception:
            pass

        return info


# Global instance
k8s_client = K8sClient()
