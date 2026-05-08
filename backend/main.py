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
from k8s_client import k8s_client
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
        # Check for Bearer token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from app.api.auth import get_current_user
            from fastapi.security import HTTPAuthorizationCredentials
            try:
                creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:])
                user = await get_current_user(creds)
                if user:
                    request.state.user = user
                    return await call_next(request)
            except Exception:
                pass
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


@app.get("/api/services", response_model=List[ServiceStatus])
async def get_services():
    """Get status of all DataPond services from K8s"""
    services_status = []

    # Service name mapping (API name -> K8s label)
    service_mappings = {
        "postgres": "postgres",
        "mlflow": "mlflow",
        "jupyterlab": "jupyterlab",
        "trino": "trino",
        "risingwave": "risingwave",
        "openmetadata": "openmetadata",
        "seaweedfs": "seaweedfs",
        "polaris": "polaris",
        "valkey": "valkey"
    }

    for name, k8s_name in service_mappings.items():
        status = await k8s_client.get_service_health(k8s_name)
        pods = await k8s_client.get_service_pods(k8s_name)

        # Get version from pod labels if available
        version = None
        if pods:
            # Mark as running if we have pods
            version = "Running"

        services_status.append(ServiceStatus(
            name=name,
            status=status,
            url=SERVICES.get(name),
            version=version
        ))

    return services_status


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics from real K8s metrics"""
    # Get K8s metrics
    k8s_metrics = await k8s_client.get_pod_metrics()

    # Get service health
    services = await get_services()
    healthy = sum(1 for s in services if s.status == "healthy")
    unhealthy = sum(1 for s in services if s.status == "unhealthy")

    return DashboardStats(
        total_services=len(services),
        healthy_services=healthy,
        unhealthy_services=unhealthy,
        cpu_usage=k8s_metrics["cpu_usage_percent"],
        memory_usage=k8s_metrics["memory_usage_percent"]
    )


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
