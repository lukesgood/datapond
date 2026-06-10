"""
DataPond Backend API
FastAPI backend for DataPond unified management interface
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import asyncio
import time
import logging
from k8s_client import k8s_client

_log = logging.getLogger(__name__)
from app.api.queries import router as queries_router
from app.api.catalog import router as catalog_router
from app.api.connectors import router as connectors_router
from app.api.services import router as services_router
from app.api.notebooks import router as notebooks_router
from app.api.mlflow_integration import router as mlflow_router
from app.api.airflow import router as airflow_router
from app.api.dashboards import router as dashboards_router
from app.api.pipelines import router as pipelines_router
from app.api.storage import router as storage_router
from app.api.streaming import router as streaming_router
from app.api.auth import router as auth_router
from app.api.transforms import router as transforms_router
from app.api.ai_sql import router as ai_sql_router
from app.api.ai_backends import router as ai_backends_router
from app.api.ai_vectors import router as ai_vectors_router
from app.api.system_settings import router as system_settings_router, load_settings_on_startup
from app.api.governance import router as governance_router
from app.api.maintenance import router as maintenance_router, deploy_maintenance_dag

app = FastAPI(
    title="DataPond API",
    description="Unified management API for DataPond platform",
    version="0.1.0"
)

# ── API-level auth middleware ──────────────────────────────────────────────────
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Public paths that don't require authentication
AUTH_EXEMPT = {
    "/api/auth/login",
    "/api/auth/logout",
    "/health",
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Only protect /api/ routes
        if not path.startswith("/api/"):
            return await call_next(request)
        # Exempt public endpoints
        if path in AUTH_EXEMPT:
            return await call_next(request)
        # Trusted in-cluster automation (scheduled DAGs) authenticates with a shared
        # X-Internal-Key instead of a user JWT. Let it through here; the route's
        # require_user_or_internal dependency re-validates and assigns a service identity.
        import os as _os
        _ikey = (_os.getenv("INTERNAL_API_KEY") or "").strip()
        if _ikey and request.headers.get("X-Internal-Key", "") == _ikey:
            return await call_next(request)
        # Check for Bearer token. Only the auth check is guarded by try/except —
        # call_next() MUST stay outside it, otherwise a route handler's exception
        # gets swallowed here and returned as a misleading 401 "Not authenticated"
        # instead of a real 500 (this masked a missing-table error as an auth failure).
        auth = request.headers.get("Authorization", "")
        user = None
        if auth.startswith("Bearer "):
            from app.api.auth import get_current_user
            from fastapi.security import HTTPAuthorizationCredentials
            try:
                creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:])
                user = await get_current_user(creds)
            except Exception:
                user = None
        if user:
            request.state.user = user
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )

app.add_middleware(AuthMiddleware)


@app.on_event("startup")
async def startup():
    """Initialize Iceberg Medallion namespaces on startup."""
    import asyncio, logging, os
    logger = logging.getLogger(__name__)
    try:
        import trino
        conn = trino.dbapi.connect(
            host=os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local"),
            port=int(os.getenv("TRINO_SERVICE_PORT", "8080")),
            user="datapond", catalog="iceberg", http_scheme="http", request_timeout=10,
        )
        cur = conn.cursor()
        for ns in ("raw", "refined", "serving"):
            try:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS iceberg.{ns}")
                logger.info(f"[startup] Iceberg namespace '{ns}' ready")
            except Exception as e:
                logger.warning(f"[startup] Schema '{ns}' skip: {e}")
    except Exception as e:
        logger.warning(f"[startup] Medallion init skipped: {e}")

    # Restore persisted system settings into env (retry — DB may not be ready immediately)
    import asyncio as _asyncio
    for attempt in range(5):
        try:
            from app.api.connectors import get_db_pool
            pool = await get_db_pool()
            await load_settings_on_startup(pool)
            logger.info("[startup] System settings loaded from DB")
            break
        except Exception as e:
            if attempt < 4:
                logger.warning(f"[startup] Settings load attempt {attempt+1} failed: {e} — retrying in 3s")
                await _asyncio.sleep(3)
            else:
                logger.warning(f"[startup] Settings load skipped after retries: {e}")

    # 기반 스키마 부트스트랩 (auth.sql/queries.sql — users/roles/sessions/dashboards 등).
    # 빈 DB 1회 적용(센티넬 가드), 기존 DB는 skip. rls_migration이 users에 의존하므로 먼저 실행.
    try:
        from app.api.connectors import get_db_pool
        from app.schema_bootstrap import ensure_base_schema
        await ensure_base_schema(await get_db_pool())
    except Exception as e:
        logger.warning(f"[startup] Base schema bootstrap skipped: {e}")

    # RLS 스키마 마이그레이션 (멱등 — rls_policies/masking/user_roles/attributes). best-effort.
    try:
        from app.api.connectors import get_db_pool
        from app.rls.migrate import ensure_rls_schema
        await ensure_rls_schema(await get_db_pool())
    except Exception as e:
        logger.warning(f"[startup] RLS schema migration skipped: {e}")

    # Iceberg 유지보수 DAG 배포 (best-effort — Airflow/PVC 미준비 시 건너뜀)
    try:
        await deploy_maintenance_dag()
        logger.info("[startup] Iceberg maintenance DAG deployed")
    except Exception as e:
        logger.warning(f"[startup] Maintenance DAG deploy skipped: {e}")

    # AI SQL 스키마 컨텍스트 프리웜 — 첫 요청 cold(~40s, Polaris information_schema) 제거.
    # 데몬 스레드라 startup을 블로킹하지 않음. best-effort.
    try:
        from app.api.ai_sql import prewarm_schema_cache
        prewarm_schema_cache()
        logger.info("[startup] AI SQL schema context prewarm started")
    except Exception as e:
        logger.warning(f"[startup] AI SQL schema prewarm skipped: {e}")

    # pgvector schema (ai_collections / ai_chunks) — best-effort (needs pgvector image)
    try:
        from app.api.connectors import get_db_pool
        from app.api.ai_vectors import ensure_vector_schema
        await ensure_vector_schema(await get_db_pool())
        logger.info("[startup] pgvector schema ready")
    except Exception as e:
        logger.warning(f"[startup] pgvector schema skipped: {e}")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(queries_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")
app.include_router(connectors_router, prefix="/api")
app.include_router(services_router, prefix="/api")
app.include_router(notebooks_router, prefix="/api")
app.include_router(mlflow_router, prefix="/api")
app.include_router(airflow_router, prefix="/api")
app.include_router(dashboards_router, prefix="/api")
app.include_router(pipelines_router, prefix="/api")
app.include_router(storage_router, prefix="/api")
app.include_router(streaming_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(transforms_router, prefix="/api")
app.include_router(ai_sql_router, prefix="/api")
app.include_router(ai_vectors_router, prefix="/api")
app.include_router(ai_backends_router, prefix="/api")
app.include_router(system_settings_router, prefix="/api")
app.include_router(governance_router, prefix="/api")
app.include_router(maintenance_router, prefix="/api")

# Service endpoints (internal Kubernetes DNS)
SERVICES = {
    "postgres": "http://postgres:5432",
    "mlflow": "http://mlflow:5000",
    "jupyterlab": "http://jupyterlab:8888",
    "trino": "http://trino:8080",
    "risingwave": "http://risingwave-frontend:4566",
    "openmetadata": "http://openmetadata-server:8585",
    "seaweedfs": "http://seaweedfs-filer:8888",
    "polaris": "http://polaris:8181",
}


class ServiceStatus(BaseModel):
    name: str
    status: str  # "healthy", "unhealthy", "unknown"
    url: Optional[str] = None
    version: Optional[str] = None


class DashboardStats(BaseModel):
    total_services: int
    healthy_services: int
    unhealthy_services: int
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "DataPond API",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for K8s probes"""
    return {"status": "healthy"}

@app.get("/api/health")
async def api_health_check():
    """Health check endpoint (API path)"""
    return {"status": "healthy"}


# API name → K8s app label
SERVICE_MAPPINGS = {
    "postgres": "postgres", "mlflow": "mlflow", "jupyterlab": "jupyterlab",
    "trino": "trino", "risingwave": "risingwave", "openmetadata": "openmetadata",
    "seaweedfs": "seaweedfs", "polaris": "polaris", "valkey": "valkey",
}

# 대시보드가 자주 폴링하므로 짧은 TTL 캐시 + 스레드 오프로드로 견고화.
# 블로킹 k8s 호출(list_namespaced_pod / kubectl top)을 이벤트 루프에서 직접 실행하면
# k8s API가 느릴 때 백엔드 전체가 멈추고 liveness 실패→재시작→502 연쇄가 발생한다.
_K8S_TIMEOUT = 6.0
_SERVICES_TTL = 8.0
_services_cache: dict = {"data": None, "ts": 0.0}
_stats_cache: dict = {"data": None, "ts": 0.0}


def _compute_services_sync() -> List[ServiceStatus]:
    """단일 pod 목록 캐시에서 서비스별 상태 산출 (블로킹 — 스레드에서 실행)."""
    pods = k8s_client._get_all_pods_cached()
    by_app: dict = {}
    for pod in pods:
        labels = (pod.metadata.labels or {})
        app = labels.get("app") or labels.get("app.kubernetes.io/name")
        if app:
            by_app.setdefault(app, []).append(pod)

    out = []
    for name, k8s_name in SERVICE_MAPPINGS.items():
        sp = by_app.get(k8s_name, [])
        if not sp:
            status = "unknown"
        else:
            all_running = all((p.status.phase == "Running") for p in sp)
            all_ready = all(k8s_client._is_pod_ready(p) for p in sp)
            status = "healthy" if (all_running and all_ready) else "unhealthy"
        out.append(ServiceStatus(
            name=name, status=status, url=SERVICES.get(name),
            version="Running" if sp else None,
        ))
    return out


def _degraded_services() -> List[ServiceStatus]:
    return [ServiceStatus(name=n, status="unknown", url=SERVICES.get(n)) for n in SERVICE_MAPPINGS]


@app.get("/api/services", response_model=List[ServiceStatus])
async def get_services():
    """Get status of all DataPond services from K8s (캐시 + 타임아웃 + 오류허용)."""
    now = time.monotonic()
    if _services_cache["data"] is not None and now - _services_cache["ts"] < _SERVICES_TTL:
        return _services_cache["data"]
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_compute_services_sync), timeout=_K8S_TIMEOUT)
        _services_cache.update(data=result, ts=now)
        return result
    except Exception as e:
        _log.warning(f"[/api/services] k8s 조회 실패/지연 — 캐시/degraded 반환: {e}")
        return _services_cache["data"] if _services_cache["data"] is not None else _degraded_services()


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics from real K8s metrics (캐시 + 타임아웃 + 오류허용)."""
    now = time.monotonic()
    if _stats_cache["data"] is not None and now - _stats_cache["ts"] < _SERVICES_TTL:
        return _stats_cache["data"]

    services = await get_services()  # 자체적으로 캐시/오류허용
    healthy = sum(1 for s in services if s.status == "healthy")
    unhealthy = sum(1 for s in services if s.status == "unhealthy")

    cpu = mem = None
    try:
        m = await asyncio.wait_for(asyncio.to_thread(_pod_metrics_blocking), timeout=_K8S_TIMEOUT)
        cpu, mem = m.get("cpu_usage_percent"), m.get("memory_usage_percent")
    except Exception as e:
        _log.warning(f"[/api/dashboard/stats] 메트릭 조회 실패/지연 — 메트릭 생략: {e}")

    stats = DashboardStats(
        total_services=len(services), healthy_services=healthy,
        unhealthy_services=unhealthy, cpu_usage=cpu, memory_usage=mem,
    )
    _stats_cache.update(data=stats, ts=now)
    return stats


def _pod_metrics_blocking() -> dict:
    """get_pod_metrics(async-but-blocking)를 워커 스레드의 별도 루프에서 실행."""
    return asyncio.run(k8s_client.get_pod_metrics())


_sysinfo_cache: dict = {"data": None, "ts": 0.0}
_SYSINFO_TTL = 15.0


@app.get("/api/system/info")
async def get_system_info():
    """서버 시스템 정보·사양 (노드 스펙/OS/컴포넌트 버전/스토리지/사용량).

    블로킹 k8s 호출을 스레드 오프로드 + 타임아웃 + 캐시 + 오류허용으로 안전하게 노출.
    """
    now = time.monotonic()
    if _sysinfo_cache["data"] is not None and now - _sysinfo_cache["ts"] < _SYSINFO_TTL:
        return _sysinfo_cache["data"]
    try:
        data = await asyncio.wait_for(asyncio.to_thread(k8s_client.get_system_info), timeout=_K8S_TIMEOUT)
        _sysinfo_cache.update(data=data, ts=now)
        return data
    except Exception as e:
        _log.warning(f"[/api/system/info] 조회 실패/지연: {e}")
        if _sysinfo_cache["data"] is not None:
            return _sysinfo_cache["data"]
        return {"node": {}, "cluster": {}, "components": [], "storage": [], "usage": {}}


@app.get("/api/trino/catalogs")
async def get_trino_catalogs():
    """Get Trino catalogs"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVICES['trino']}/v1/catalogs")
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Legacy MLflow endpoint removed - use /api/mlflow/experiments from mlflow_integration router


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
