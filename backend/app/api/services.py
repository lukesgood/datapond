"""
Services API - Real-time monitoring and management
Provides comprehensive K8s service monitoring, logs, metrics, and control
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from datetime import datetime, timedelta
import logging
import os
import asyncio
import json

from app.api import auth
from app.service_registry import service_registry
from k8s_client import k8s_client as _k8s

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize K8s clients
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster K8s config")
except:
    try:
        config.load_kube_config()
        logger.info("Loaded kubeconfig for local development")
    except Exception as e:
        logger.error(f"Failed to load K8s config: {e}")

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
NAMESPACE = os.getenv("DATAPOND_NAMESPACE", "datapond")

# ==========================================
# Models
# ==========================================

class PodInfo(BaseModel):
    name: str
    phase: str
    ready: bool
    restarts: int
    age: str
    node: Optional[str] = None
    ip: Optional[str] = None

class ServiceLogsResponse(BaseModel):
    service: str
    pod: str
    lines: List[str]
    timestamp: str

class ServiceMetrics(BaseModel):
    service: str
    pods: List[Dict[str, Any]]
    total_cpu: Optional[str] = None
    total_memory: Optional[str] = None

class ServiceHealth(BaseModel):
    service: str
    status: str
    message: str
    pods_ready: int
    pods_total: int
    last_restart: Optional[str] = None

class K8sEvent(BaseModel):
    type: str
    reason: str
    message: str
    timestamp: str
    object: str

class RestartResponse(BaseModel):
    status: str
    deleted_pods: List[str]
    message: str

class ScaleRequest(BaseModel):
    replicas: int

class ScaleResponse(BaseModel):
    status: str
    old_replicas: int
    new_replicas: int
    service: str

class ServiceDetail(BaseModel):
    """Consolidated single-service detail — backs the Services detail page."""
    name: str
    status: str  # "healthy" | "unhealthy" | "unknown" | "managed"
    kind: Optional[str] = None  # "pod" | "managed"
    url: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    replicas: Optional[int] = None
    cpu_usage: Optional[float] = None       # % of node allocatable (best-effort)
    memory_usage: Optional[float] = None    # % of node allocatable (best-effort)
    namespace: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    ports: Optional[List[Dict[str, Any]]] = None
    env: Optional[Dict[str, str]] = None
    uptime: Optional[str] = None

# ==========================================
# Helper Functions
# ==========================================

def get_pod_age(creation_timestamp) -> str:
    """Calculate pod age in human-readable format"""
    if not creation_timestamp:
        return "unknown"

    age = datetime.now(creation_timestamp.tzinfo) - creation_timestamp

    if age.days > 0:
        return f"{age.days}d"
    elif age.seconds >= 3600:
        return f"{age.seconds // 3600}h"
    elif age.seconds >= 60:
        return f"{age.seconds // 60}m"
    else:
        return f"{age.seconds}s"

def is_pod_ready(pod) -> bool:
    """Check if pod is ready"""
    if not pod.status.conditions:
        return False
    for condition in pod.status.conditions:
        if condition.type == "Ready":
            return condition.status == "True"
    return False

def get_restart_count(pod) -> int:
    """Get total restart count for pod"""
    if not pod.status.container_statuses:
        return 0
    return sum(c.restart_count for c in pod.status.container_statuses)

def get_service_label_selector(service: str) -> str:
    """Get label selector for service"""
    # Try common label patterns
    # Most DataPond services use app=service-name
    return f"app={service}"


def _pod_belongs_to_service(pod_obj, service: str) -> bool:
    """Match a pod against the same equality selector used for service lookups."""
    labels = getattr(getattr(pod_obj, "metadata", None), "labels", None) or {}
    for requirement in get_service_label_selector(service).split(","):
        key, separator, expected = requirement.partition("=")
        if not separator or labels.get(key.strip()) != expected.strip():
            return False
    return True


async def _safe_websocket_close(websocket: WebSocket, code: int) -> None:
    """Close during handshake or streaming without masking disconnect races."""
    try:
        await websocket.close(code=code)
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _authorize_log_websocket(websocket: WebSocket) -> bool:
    """Authenticate an admin from the same-origin session cookie before accept."""
    token = websocket.cookies.get("datapond_token")
    if not token:
        await _safe_websocket_close(websocket, 4401)
        return False

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = await auth.get_current_user(credentials)
    if not user:
        await _safe_websocket_close(websocket, 4401)
        return False
    if user.get("role") != "admin":
        await _safe_websocket_close(websocket, 4403)
        return False
    return True

def _node_allocatable():
    """Best-effort cluster node allocatable (cpu_nanocores, memory_bytes).

    Reuses k8s_client's quantity parsers (same ones the dashboard-wide
    metrics use) so % figures are consistent across the app. Returns
    (None, None) if node info isn't accessible (RBAC, etc.) — callers
    must treat that as "percentage unavailable", never fabricate a number.
    """
    try:
        nodes = core_v1.list_node()
        cpu_nano = sum(_k8s._parse_cpu_nano((n.status.allocatable or {}).get("cpu", "0")) for n in nodes.items)
        mem_bytes = sum(_k8s._parse_mem_bytes((n.status.allocatable or {}).get("memory", "0Ki")) for n in nodes.items)
        if cpu_nano and mem_bytes:
            return cpu_nano, mem_bytes
        return None, None
    except Exception as e:
        logger.warning(f"Node allocatable lookup failed: {e}")
        return None, None

# ==========================================
# Single-Service Detail Endpoint
# ==========================================

@router.get(
    "/services/{service}",
    response_model=ServiceDetail,
    dependencies=[Depends(auth.require_user)],
)
async def get_service_detail(service: str):
    """
    Consolidated detail for a single service — backs the Services detail page.

    Base identity (name/status/description/kind/url/version) comes from the
    profile-aware service_registry — 404 only when the service isn't in the
    registry at all. For self-hosted ("pod") services this is enriched
    best-effort with live k8s data (replicas/cpu/memory/namespace/labels/
    ports/env/uptime), reusing the same pod + metrics-server lookups as
    /pods and /metrics. External or managed adapters have no in-cluster pods to
    inspect, so the compatibility status ``managed`` means configured only; it is
    not a health check.

    Never 500s — any k8s error degrades to partial data, not a failure.
    """
    entry = next((s for s in service_registry(os.environ) if s["name"] == service), None)
    if entry is None:
        raise HTTPException(404, f"Service not found: {service}")

    if entry.get("kind") == "managed":
        return ServiceDetail(
            name=entry["name"],
            status="managed",
            kind="managed",
            version="Configured adapter",
            description=entry.get("desc"),
        )

    app_label = entry.get("app", service)
    detail = ServiceDetail(
        name=entry["name"],
        status="unknown",
        kind="pod",
        url=entry.get("url"),
        description=entry.get("desc"),
        namespace=NAMESPACE,
    )

    # Pod-derived fields: status/replicas/labels/uptime/version/env (best-effort).
    try:
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(app_label),
        )
        pod_items = pods.items
        if pod_items:
            all_running = all(p.status.phase == "Running" for p in pod_items)
            all_ready = all(is_pod_ready(p) for p in pod_items)
            detail.status = "healthy" if (all_running and all_ready) else "unhealthy"
            detail.replicas = len(pod_items)

            first = pod_items[0]
            detail.labels = first.metadata.labels or {}
            detail.uptime = get_pod_age(first.metadata.creation_timestamp)

            containers = first.spec.containers if first.spec and first.spec.containers else []
            if containers:
                image = containers[0].image or ""
                detail.version = image.split(":")[-1] if ":" in image else image
                if containers[0].env:
                    detail.env = {
                        e.name: e.value for e in containers[0].env if e.value is not None
                    }
    except ApiException as e:
        logger.warning(f"[services/{service}] pod lookup failed: {e}")
    except Exception as e:
        logger.warning(f"[services/{service}] pod enrichment failed: {e}")

    # Service ports — from the k8s Service object (falls back silently if absent).
    try:
        svc_obj = core_v1.read_namespaced_service(name=app_label, namespace=NAMESPACE)
        if svc_obj.spec and svc_obj.spec.ports:
            detail.ports = [
                {"name": p.name or "", "port": p.port, "protocol": p.protocol or "TCP"}
                for p in svc_obj.spec.ports
            ]
    except ApiException:
        pass
    except Exception as e:
        logger.warning(f"[services/{service}] service ports lookup failed: {e}")

    # CPU/Memory usage — sum pod usage from metrics-server, express as % of
    # node allocatable (same semantics as the dashboard-wide metrics).
    try:
        custom_api = client.CustomObjectsApi()
        metrics = custom_api.list_namespaced_custom_object(
            group="metrics.k8s.io", version="v1beta1", namespace=NAMESPACE,
            plural="pods", label_selector=get_service_label_selector(app_label),
        )
        total_cpu_nano = 0
        total_mem_bytes = 0
        for pod in metrics.get("items", []):
            for c in pod.get("containers", []):
                usage = c.get("usage", {})
                total_cpu_nano += _k8s._parse_cpu_nano(usage.get("cpu", "0n"))
                total_mem_bytes += _k8s._parse_mem_bytes(usage.get("memory", "0Ki"))

        alloc_cpu, alloc_mem = _node_allocatable()
        if alloc_cpu and alloc_mem:
            detail.cpu_usage = round(total_cpu_nano / alloc_cpu * 100, 1)
            detail.memory_usage = round(total_mem_bytes / alloc_mem * 100, 1)
    except ApiException as e:
        logger.warning(f"[services/{service}] metrics-server unavailable: {e}")
    except Exception as e:
        logger.warning(f"[services/{service}] metrics lookup failed: {e}")

    return detail

# ==========================================
# Pod Management Endpoints
# ==========================================

@router.get(
    "/services/{service}/pods",
    response_model=List[PodInfo],
    dependencies=[Depends(auth.require_user)],
)
async def get_service_pods(service: str):
    """
    List all pods for a service

    Returns detailed information about each pod including status, restarts, age.
    """
    try:
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(service)
        )

        if not pods.items:
            raise HTTPException(404, f"No pods found for service: {service}")

        pod_list = []
        for pod in pods.items:
            pod_list.append(PodInfo(
                name=pod.metadata.name,
                phase=pod.status.phase,
                ready=is_pod_ready(pod),
                restarts=get_restart_count(pod),
                age=get_pod_age(pod.metadata.creation_timestamp),
                node=pod.spec.node_name,
                ip=pod.status.pod_ip
            ))

        return pod_list

    except ApiException as e:
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to get pods: {str(e)}")

@router.get(
    "/services/{service}/pods/{pod}/describe",
    dependencies=[Depends(auth.require_user)],
)
async def describe_pod(service: str, pod: str):
    """
    Get detailed information about a specific pod

    Returns full pod spec, status, conditions, events.
    """
    try:
        pod_obj = core_v1.read_namespaced_pod(name=pod, namespace=NAMESPACE)
        if not _pod_belongs_to_service(pod_obj, service):
            raise HTTPException(404, f"Pod not found: {pod}")

        # Get pod events only after service ownership has been verified.
        events = core_v1.list_namespaced_event(
            namespace=NAMESPACE,
            field_selector=f"involvedObject.name={pod}"
        )

        # Format response
        return {
            "metadata": {
                "name": pod_obj.metadata.name,
                "namespace": pod_obj.metadata.namespace,
                "labels": pod_obj.metadata.labels,
                "creation_timestamp": pod_obj.metadata.creation_timestamp.isoformat(),
                "uid": pod_obj.metadata.uid
            },
            "spec": {
                "node": pod_obj.spec.node_name,
                "containers": [
                    {
                        "name": c.name,
                        "image": c.image,
                        "ports": [{"containerPort": p.container_port, "protocol": p.protocol} for p in c.ports] if c.ports else [],
                        "resources": {
                            "requests": c.resources.requests if c.resources and c.resources.requests else {},
                            "limits": c.resources.limits if c.resources and c.resources.limits else {}
                        }
                    }
                    for c in pod_obj.spec.containers
                ]
            },
            "status": {
                "phase": pod_obj.status.phase,
                "pod_ip": pod_obj.status.pod_ip,
                "start_time": pod_obj.status.start_time.isoformat() if pod_obj.status.start_time else None,
                "conditions": [
                    {
                        "type": c.type,
                        "status": c.status,
                        "reason": c.reason,
                        "message": c.message
                    }
                    for c in pod_obj.status.conditions
                ] if pod_obj.status.conditions else [],
                "container_statuses": [
                    {
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": str(cs.state)
                    }
                    for cs in pod_obj.status.container_statuses
                ] if pod_obj.status.container_statuses else []
            },
            "events": [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "timestamp": e.last_timestamp.isoformat() if e.last_timestamp else None
                }
                for e in events.items[-10:]  # Last 10 events
            ]
        }

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"Pod not found: {pod}")
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to describe pod: {str(e)}")

@router.delete(
    "/services/{service}/pods/{pod}",
    dependencies=[Depends(auth.require_admin)],
)
async def delete_service_pod(service: str, pod: str):
    """Delete one pod only after its labels prove it belongs to the service."""
    try:
        pod_obj = core_v1.read_namespaced_pod(name=pod, namespace=NAMESPACE)
        if not _pod_belongs_to_service(pod_obj, service):
            raise HTTPException(404, f"Pod not found for service {service}: {pod}")
        core_v1.delete_namespaced_pod(name=pod, namespace=NAMESPACE)
        return {"status": "deleted", "service": service, "pod": pod}
    except HTTPException:
        raise
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"Pod not found: {pod}")
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to delete pod: {str(e)}")


# ==========================================
# Logs Endpoints
# ==========================================

@router.get(
    "/services/{service}/logs",
    response_model=ServiceLogsResponse,
    dependencies=[Depends(auth.require_user)],
)
async def get_service_logs(
    service: str,
    lines: int = Query(100, ge=1, le=1000, description="Number of log lines to retrieve"),
    pod: Optional[str] = Query(None, description="Specific pod name (uses first pod if not specified)")
):
    """
    Get recent logs from a service's pod

    Returns the last N lines of logs from the first pod (or specified pod).
    """
    try:
        # An explicit pod name is untrusted input: read it and verify the same
        # service selector before accessing its logs.
        if pod:
            pod_obj = core_v1.read_namespaced_pod(name=pod, namespace=NAMESPACE)
            if not _pod_belongs_to_service(pod_obj, service):
                raise HTTPException(404, f"Pod not found: {pod}")
        else:
            pods = core_v1.list_namespaced_pod(
                namespace=NAMESPACE,
                label_selector=get_service_label_selector(service)
            )

            if not pods.items:
                raise HTTPException(404, f"No pods found for service: {service}")

            pod = pods.items[0].metadata.name

        # Get pod logs only after an explicit pod's ownership is verified.
        logs = core_v1.read_namespaced_pod_log(
            name=pod,
            namespace=NAMESPACE,
            tail_lines=lines
        )

        return ServiceLogsResponse(
            service=service,
            pod=pod,
            lines=logs.split("\n") if logs else [],
            timestamp=datetime.utcnow().isoformat()
        )

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"Pod not found: {pod}")
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to get logs: {str(e)}")

@router.websocket("/services/{service}/logs/stream")
async def stream_logs(websocket: WebSocket, service: str):
    """Stream pod logs to an authenticated administrator."""
    if not await _authorize_log_websocket(websocket):
        return
    await websocket.accept()

    try:
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(service)
        )
        if not pods.items:
            await websocket.send_json({"error": f"No pods found for service: {service}"})
            await _safe_websocket_close(websocket, 1000)
            return

        pod_name = pods.items[0].metadata.name
        await websocket.send_json({
            "status": "connected",
            "service": service,
            "pod": pod_name,
        })

        w = watch.Watch()
        for line in w.stream(
            core_v1.read_namespaced_pod_log,
            name=pod_name,
            namespace=NAMESPACE,
            follow=True,
            _request_timeout=3600,
        ):
            await websocket.send_json({
                "type": "log",
                "line": line,
                "timestamp": datetime.utcnow().isoformat(),
            })
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {service}")
    except ApiException as e:
        try:
            await websocket.send_json({"error": f"K8s API error: {str(e)}"})
        except (RuntimeError, WebSocketDisconnect):
            pass
        await _safe_websocket_close(websocket, 1011)
    except Exception as e:
        logger.error(f"Error streaming logs: {e}")
        try:
            await websocket.send_json({"error": f"Failed to stream logs: {str(e)}"})
        except (RuntimeError, WebSocketDisconnect):
            pass
        await _safe_websocket_close(websocket, 1011)

# ==========================================
# Metrics Endpoints
# ==========================================

@router.get(
    "/services/{service}/metrics",
    response_model=ServiceMetrics,
    dependencies=[Depends(auth.require_user)],
)
async def get_service_metrics(service: str):
    """
    Get current resource usage metrics for a service

    Returns CPU and memory usage for all pods. Requires metrics-server.
    """
    try:
        # Try to get metrics from metrics-server
        custom_api = client.CustomObjectsApi()

        metrics = custom_api.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=NAMESPACE,
            plural="pods",
            label_selector=get_service_label_selector(service)
        )

        pod_metrics = []
        total_cpu = 0
        total_memory = 0

        for pod in metrics.get("items", []):
            pod_name = pod["metadata"]["name"]
            containers = pod.get("containers", [])

            pod_cpu = 0
            pod_memory = 0

            for container in containers:
                cpu = container["usage"].get("cpu", "0")
                memory = container["usage"].get("memory", "0")

                # Parse CPU (format: "123n" or "1m")
                if cpu.endswith("n"):
                    cpu_val = int(cpu[:-1]) / 1_000_000_000  # nanocores to cores
                elif cpu.endswith("m"):
                    cpu_val = int(cpu[:-1]) / 1000  # millicores to cores
                else:
                    cpu_val = float(cpu)

                # Parse memory (format: "123Ki" or "1Mi")
                if memory.endswith("Ki"):
                    mem_val = int(memory[:-2]) * 1024  # KiB to bytes
                elif memory.endswith("Mi"):
                    mem_val = int(memory[:-2]) * 1024 * 1024  # MiB to bytes
                else:
                    mem_val = int(memory)

                pod_cpu += cpu_val
                pod_memory += mem_val

            pod_metrics.append({
                "name": pod_name,
                "cpu": f"{pod_cpu:.3f}",
                "memory": f"{pod_memory / (1024 * 1024):.2f}Mi"
            })

            total_cpu += pod_cpu
            total_memory += pod_memory

        return ServiceMetrics(
            service=service,
            pods=pod_metrics,
            total_cpu=f"{total_cpu:.3f} cores",
            total_memory=f"{total_memory / (1024 * 1024):.2f} Mi"
        )

    except ApiException as e:
        if e.status == 404:
            # metrics-server not available, return placeholder
            logger.warning("metrics-server not available, returning placeholder metrics")
            return ServiceMetrics(
                service=service,
                pods=[],
                total_cpu="N/A (metrics-server not installed)",
                total_memory="N/A (metrics-server not installed)"
            )
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to get metrics: {str(e)}")

@router.get(
    "/services/{service}/metrics/history",
    dependencies=[Depends(auth.require_user)],
)
async def get_service_metrics_history(
    service: str,
    hours: int = Query(24, ge=1, le=168, description="Hours of history (max 7 days)")
):
    """
    Get historical metrics for a service

    Note: This is a placeholder. In production, integrate with Prometheus/Grafana.
    """
    return {
        "service": service,
        "message": "Historical metrics require Prometheus integration",
        "suggestion": "Install kube-prometheus-stack for time-series metrics",
        "current_metrics": await get_service_metrics(service)
    }

# ==========================================
# Health & Events Endpoints
# ==========================================

@router.get(
    "/services/{service}/health",
    response_model=ServiceHealth,
    dependencies=[Depends(auth.require_user)],
)
async def get_service_health(service: str):
    """
    Get detailed health status for a service

    Checks pod readiness, recent restarts, and overall health.
    """
    try:
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(service)
        )

        if not pods.items:
            return ServiceHealth(
                service=service,
                status="unknown",
                message=f"No pods found for service: {service}",
                pods_ready=0,
                pods_total=0
            )

        total_pods = len(pods.items)
        ready_pods = sum(1 for p in pods.items if is_pod_ready(p))

        # Check for recent restarts
        last_restart = None
        max_restarts = 0
        for pod in pods.items:
            restart_count = get_restart_count(pod)
            if restart_count > max_restarts:
                max_restarts = restart_count
                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.last_state and cs.last_state.terminated:
                            last_restart = cs.last_state.terminated.finished_at.isoformat()

        # Determine status
        if ready_pods == total_pods:
            status = "healthy"
            message = "All pods are ready"
        elif ready_pods > 0:
            status = "degraded"
            message = f"Only {ready_pods}/{total_pods} pods ready"
        else:
            status = "unhealthy"
            message = "No pods are ready"

        return ServiceHealth(
            service=service,
            status=status,
            message=message,
            pods_ready=ready_pods,
            pods_total=total_pods,
            last_restart=last_restart
        )

    except ApiException as e:
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to get health: {str(e)}")

@router.get(
    "/services/{service}/events",
    response_model=List[K8sEvent],
    dependencies=[Depends(auth.require_user)],
)
async def get_service_events(
    service: str,
    limit: int = Query(50, ge=1, le=200, description="Number of events to retrieve")
):
    """
    Get recent Kubernetes events for a service

    Shows pod lifecycle events, errors, warnings.
    """
    try:
        # Get pods for service
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(service)
        )

        if not pods.items:
            return []

        # Get events for all pods
        all_events = []
        for pod in pods.items:
            events = core_v1.list_namespaced_event(
                namespace=NAMESPACE,
                field_selector=f"involvedObject.name={pod.metadata.name}"
            )

            for event in events.items:
                all_events.append(K8sEvent(
                    type=event.type,
                    reason=event.reason,
                    message=event.message,
                    timestamp=event.last_timestamp.isoformat() if event.last_timestamp else "",
                    object=event.involved_object.name
                ))

        # Sort by timestamp (most recent first) and limit
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:limit]

    except ApiException as e:
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to get events: {str(e)}")

# ==========================================
# Control Endpoints
# ==========================================

@router.post(
    "/services/{service}/restart",
    response_model=RestartResponse,
    dependencies=[Depends(auth.require_admin)],
)
async def restart_service(service: str):
    """
    Restart a service by deleting its pods

    Kubernetes will automatically recreate the pods from the deployment.
    WARNING: This will cause temporary downtime.
    """
    try:
        # Get all pods for service
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=get_service_label_selector(service)
        )

        if not pods.items:
            raise HTTPException(404, f"No pods found for service: {service}")

        deleted_pods = []
        for pod in pods.items:
            core_v1.delete_namespaced_pod(
                name=pod.metadata.name,
                namespace=NAMESPACE
            )
            deleted_pods.append(pod.metadata.name)

        logger.info(f"Restarted service {service}, deleted pods: {deleted_pods}")

        return RestartResponse(
            status="restarting",
            deleted_pods=deleted_pods,
            message=f"Successfully triggered restart for {service}"
        )

    except ApiException as e:
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to restart service: {str(e)}")

@router.post(
    "/services/{service}/scale",
    response_model=ScaleResponse,
    dependencies=[Depends(auth.require_admin)],
)
async def scale_service(service: str, request: ScaleRequest):
    """
    Scale a service to specified number of replicas

    Adjusts the deployment replica count.
    """
    try:
        # Get deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=service,
            namespace=NAMESPACE
        )

        old_replicas = deployment.spec.replicas

        # Update replica count
        deployment.spec.replicas = request.replicas
        apps_v1.patch_namespaced_deployment(
            name=service,
            namespace=NAMESPACE,
            body=deployment
        )

        logger.info(f"Scaled service {service} from {old_replicas} to {request.replicas} replicas")

        return ScaleResponse(
            status="success",
            old_replicas=old_replicas,
            new_replicas=request.replicas,
            service=service
        )

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(404, f"Deployment not found: {service}")
        logger.error(f"K8s API error: {e}")
        raise HTTPException(500, f"Failed to scale service: {str(e)}")
