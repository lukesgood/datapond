"""
Dashboard Management API
CRUD operations for user dashboards with saved queries and visualizations
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.database.connection import get_db
from app.models.dashboard import Dashboard
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardUpdate,
    DashboardResponse,
    DashboardListResponse
)

router = APIRouter()

# Mock user ID for now (replace with actual auth when implemented)
MOCK_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/dashboards", response_model=DashboardResponse, status_code=201)
async def create_dashboard(
    dashboard: DashboardCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new dashboard with saved query and chart configuration

    - Requires authentication (user_id from JWT token)
    - Chart config stored as JSONB
    - Returns created dashboard with ID
    """
    try:
        # Create new dashboard
        new_dashboard = Dashboard(
            user_id=MOCK_USER_ID,
            name=dashboard.name.strip(),
            description=dashboard.description.strip() if dashboard.description else None,
            query_text=dashboard.query_text,
            chart_config=dashboard.chart_config.model_dump(),
            is_public=dashboard.is_public
        )

        db.add(new_dashboard)
        db.commit()
        db.refresh(new_dashboard)

        return DashboardResponse.model_validate(new_dashboard)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create dashboard: {str(e)}"
        )


@router.get("/dashboards", response_model=DashboardListResponse)
async def list_dashboards(
    include_public: bool = False,
    db: Session = Depends(get_db)
):
    """
    List dashboards for current user

    - Returns user's own dashboards
    - Optionally include public dashboards (include_public=true)
    - Ordered by most recent first
    """
    try:
        query = db.query(Dashboard)

        if include_public:
            # User's dashboards + public dashboards from others
            query = query.filter(
                (Dashboard.user_id == MOCK_USER_ID) | (Dashboard.is_public == True)
            )
        else:
            # Only user's dashboards
            query = query.filter(Dashboard.user_id == MOCK_USER_ID)

        dashboards = query.order_by(Dashboard.updated_at.desc()).all()

        return DashboardListResponse(
            items=[DashboardResponse.model_validate(d) for d in dashboards],
            total=len(dashboards)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch dashboards: {str(e)}"
        )


@router.get("/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get a specific dashboard by ID

    - Returns 404 if not found
    - Returns 403 if user doesn't have access
    """
    try:
        dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()

        if not dashboard:
            raise HTTPException(status_code=404, detail="Dashboard not found")

        # Check access: owner or public dashboard
        if dashboard.user_id != MOCK_USER_ID and not dashboard.is_public:
            raise HTTPException(
                status_code=403,
                detail="Access denied: Dashboard is private"
            )

        return DashboardResponse.model_validate(dashboard)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch dashboard: {str(e)}"
        )


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    updates: DashboardUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing dashboard

    - Only owner can update
    - Partial updates supported
    - Returns updated dashboard
    """
    try:
        dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()

        if not dashboard:
            raise HTTPException(status_code=404, detail="Dashboard not found")

        # Check ownership
        if dashboard.user_id != MOCK_USER_ID:
            raise HTTPException(
                status_code=403,
                detail="Access denied: Only owner can update dashboard"
            )

        # Apply updates
        update_data = updates.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field == "chart_config" and value is not None:
                # Convert Pydantic model to dict for JSONB storage
                setattr(dashboard, field, value.model_dump() if hasattr(value, 'model_dump') else value)
            elif field in ["name", "description"] and value is not None:
                # Strip whitespace from text fields
                setattr(dashboard, field, value.strip() if isinstance(value, str) else value)
            else:
                setattr(dashboard, field, value)

        db.commit()
        db.refresh(dashboard)

        return DashboardResponse.model_validate(dashboard)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update dashboard: {str(e)}"
        )


@router.delete("/dashboards/{dashboard_id}", status_code=204)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Delete a dashboard

    - Only owner can delete
    - Returns 204 No Content on success
    """
    try:
        dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()

        if not dashboard:
            raise HTTPException(status_code=404, detail="Dashboard not found")

        # Check ownership
        if dashboard.user_id != MOCK_USER_ID:
            raise HTTPException(
                status_code=403,
                detail="Access denied: Only owner can delete dashboard"
            )

        db.delete(dashboard)
        db.commit()

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete dashboard: {str(e)}"
        )
