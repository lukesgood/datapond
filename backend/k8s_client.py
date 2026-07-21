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

            # No node allocatable ⇒ a percentage is genuinely unknown. Return None so the
            # UI shows "unavailable" — NEVER return absolute millicores/MiB here, which the
            # frontend would render as a bogus percent (e.g. 1747 MiB → "1747%").
            return None, None

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

    @staticmethod
    def _res_cpu_milli(q) -> int:
        """리소스 수량(cpu) → 밀리코어. '500m','2','2000m','100n' 처리."""
        if not q:
            return 0
        q = str(q)
        try:
            if q.endswith("m"): return int(float(q[:-1]))
            if q.endswith("n"): return int(float(q[:-1]) / 1_000_000)
            return int(float(q) * 1000)
        except Exception:
            return 0

    @staticmethod
    def _res_mem_bytes(q) -> int:
        """리소스 수량(memory/storage) → bytes. Ki/Mi/Gi/Ti, K/M/G/T(십진) 처리."""
        if not q:
            return 0
        q = str(q)
        units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
                 "K": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4}
        for u, m in units.items():
            if q.endswith(u):
                try: return int(float(q[:-len(u)]) * m)
                except Exception: return 0
        try: return int(float(q))
        except Exception: return 0

    def get_system_info(self) -> Dict[str, any]:
        """
        노드 사양/OS/런타임 + 컴포넌트(리소스 포함) + 스토리지(PVC) + 사용량
        + 필요/권장 사양 비교. 데이터는 모두 k8s API에서 얻으므로 환경(로컬/클라우드/온프렘) 무관.
        권장치는 env로 설정 가능(DATAPOND_REC_CPU_CORES / MEMORY_GB / DISK_GB).
        블로킹 호출 — 엔드포인트에서 스레드로 오프로드해 호출한다.
        """
        info: Dict[str, any] = {"node": {}, "cluster": {}, "components": [], "storage": [],
                                "usage": {}, "requirements": {}, "recommended": {}, "comparison": []}

        # ── 노드 사양/OS/상태 ─────────────────────────────────────────────────
        try:
            own_pod = self.core_v1.read_namespaced_pod(os.getenv("HOSTNAME", ""), self.namespace)
            node = self.core_v1.read_node(own_pod.spec.node_name)
            ni = node.status.node_info
            cap = node.status.capacity or {}
            alloc = node.status.allocatable or {}
            conds = {c.type: c.status for c in (node.status.conditions or [])}
            info["node"] = {
                "name": node.metadata.name,
                "os": ni.os_image, "kernel": ni.kernel_version, "arch": ni.architecture,
                "container_runtime": ni.container_runtime_version, "kubelet": ni.kubelet_version,
                "cpu_cores": round(self._res_cpu_milli(cap.get("cpu", "0")) / 1000, 1),
                "memory_gb": round(self._res_mem_bytes(cap.get("memory", "0")) / (1024 ** 3), 1),
                "ephemeral_storage_gb": round(self._res_mem_bytes(cap.get("ephemeral-storage", "0")) / (1024 ** 3), 1),
                "allocatable_cpu_cores": round(self._res_cpu_milli(alloc.get("cpu", "0")) / 1000, 1),
                "allocatable_memory_gb": round(self._res_mem_bytes(alloc.get("memory", "0")) / (1024 ** 3), 1),
                "max_pods": int(cap.get("pods", "0")),
                "ready": conds.get("Ready") == "True",
                "memory_pressure": conds.get("MemoryPressure") == "True",
                "disk_pressure": conds.get("DiskPressure") == "True",
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

        # ── 컴포넌트(이미지+리소스) + 총 요청량 합산 ──────────────────────────
        total_cpu_milli = 0
        total_mem_bytes = 0
        try:
            comps = []

            def _add(obj, kind):
                nonlocal total_cpu_milli, total_mem_bytes
                reps = obj.spec.replicas if obj.spec.replicas is not None else 1
                cr = mr = cl = ml = 0
                for c in obj.spec.template.spec.containers:
                    res = c.resources
                    req = (getattr(res, "requests", None) or {}) if res else {}
                    lim = (getattr(res, "limits", None) or {}) if res else {}
                    cr += self._res_cpu_milli(req.get("cpu")); mr += self._res_mem_bytes(req.get("memory"))
                    cl += self._res_cpu_milli(lim.get("cpu")); ml += self._res_mem_bytes(lim.get("memory"))
                total_cpu_milli += cr * reps
                total_mem_bytes += mr * reps
                comps.append({
                    "name": obj.metadata.name, "kind": kind,
                    "image": obj.spec.template.spec.containers[0].image,
                    "replicas": f"{obj.status.ready_replicas or 0}/{obj.spec.replicas or 0}",
                    "cpu_request": f"{cr}m" if cr else "-",
                    "mem_request": f"{round(mr / (1024 ** 2))}Mi" if mr else "-",
                    "cpu_limit": f"{cl}m" if cl else "-",
                    "mem_limit": f"{round(ml / (1024 ** 2))}Mi" if ml else "-",
                })

            for d in self.apps_v1.list_namespaced_deployment(self.namespace).items: _add(d, "Deployment")
            for s in self.apps_v1.list_namespaced_stateful_set(self.namespace).items: _add(s, "StatefulSet")
            info["components"] = sorted(comps, key=lambda c: c["name"])
        except Exception as e:
            logger.warning(f"components unavailable: {e}")

        # ── 영속 스토리지(PVC) + 총 요청 용량 ─────────────────────────────────
        total_disk_bytes = 0
        try:
            pvcs = self.core_v1.list_namespaced_persistent_volume_claim(self.namespace)
            for p in pvcs.items:
                total_disk_bytes += self._res_mem_bytes((p.status.capacity or {}).get("storage", "0"))
            info["storage"] = sorted([
                {"name": p.metadata.name,
                 "capacity": (p.status.capacity or {}).get("storage", "-"),
                 "status": p.status.phase, "storage_class": p.spec.storage_class_name}
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

        # ── 필요(요청 합) / 권장(env) / 실제 비교 ──────────────────────────────
        info["requirements"] = {
            "cpu_cores": round(total_cpu_milli / 1000, 1),
            "memory_gb": round(total_mem_bytes / (1024 ** 3), 1),
            "disk_gb": round(total_disk_bytes / (1024 ** 3), 1),
        }
        rec = {
            "cpu_cores": float(os.getenv("DATAPOND_REC_CPU_CORES", "8")),
            "memory_gb": float(os.getenv("DATAPOND_REC_MEMORY_GB", "32")),
            "disk_gb": float(os.getenv("DATAPOND_REC_DISK_GB", "100")),
        }
        info["recommended"] = rec

        def _status(actual, required, recommended):
            if actual is None: return "unknown"
            if actual >= recommended: return "ok"        # 권장 충족
            if actual >= required: return "warning"      # 최소 충족·권장 미달
            return "insufficient"                         # 최소 미달

        n = info["node"]; rq = info["requirements"]
        info["comparison"] = [
            {"resource": "CPU", "unit": "vCPU", "required": rq["cpu_cores"], "recommended": rec["cpu_cores"],
             "actual": n.get("cpu_cores"), "status": _status(n.get("cpu_cores"), rq["cpu_cores"], rec["cpu_cores"])},
            {"resource": "Memory", "unit": "GB", "required": rq["memory_gb"], "recommended": rec["memory_gb"],
             "actual": n.get("memory_gb"), "status": _status(n.get("memory_gb"), rq["memory_gb"], rec["memory_gb"])},
            {"resource": "Disk", "unit": "GB", "required": rq["disk_gb"], "recommended": rec["disk_gb"],
             "actual": n.get("ephemeral_storage_gb"), "status": _status(n.get("ephemeral_storage_gb"), rq["disk_gb"], rec["disk_gb"])},
        ]
        return info


# Global instance
k8s_client = K8sClient()
