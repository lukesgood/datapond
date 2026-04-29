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

app = FastAPI(
    title="DataPond API",
    description="Unified management API for DataPond platform",
    version="0.1.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/services", response_model=List[ServiceStatus])
async def get_services():
    """Get status of all DataPond services"""
    services_status = []

    for name, url in SERVICES.items():
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                if name == "trino":
                    response = await client.get(f"{url}/v1/info")
                elif name == "openmetadata":
                    response = await client.get(f"{url}/api/v1/system/version")
                elif name == "mlflow":
                    response = await client.get(f"{url}/health")
                else:
                    response = await client.get(url)

                status = "healthy" if response.status_code == 200 else "unhealthy"
                services_status.append(ServiceStatus(
                    name=name,
                    status=status,
                    url=url
                ))
        except Exception as e:
            services_status.append(ServiceStatus(
                name=name,
                status="unhealthy",
                url=url
            ))

    return services_status


@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    services = await get_services()

    healthy = sum(1 for s in services if s.status == "healthy")
    unhealthy = sum(1 for s in services if s.status == "unhealthy")

    return DashboardStats(
        total_services=len(services),
        healthy_services=healthy,
        unhealthy_services=unhealthy
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


@app.get("/api/mlflow/experiments")
async def get_mlflow_experiments():
    """Get MLflow experiments"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVICES['mlflow']}/api/2.0/mlflow/experiments/search")
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
