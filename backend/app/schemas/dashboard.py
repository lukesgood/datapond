"""
Pydantic schemas for dashboards
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class ChartConfig(BaseModel):
    """Chart configuration for dashboard visualization.

    `yAxis` is the original single measure and stays valid: a dashboard saved before
    multi-series carries only that. `yAxes` wins when both are present.
    """
    chartType: str = Field(
        ...,
        description="Chart type: 'table', 'line', 'bar', 'area', 'pie', 'kpi', 'scatter', "
                    "'histogram' or 'heatmap'",
    )
    xAxis: Optional[str] = Field(None, description="X-axis column name")
    yAxis: Optional[str] = Field(None, description="Y-axis column name")
    yAxes: Optional[List[str]] = Field(
        None, max_length=5, description="Measures plotted together (up to 5)")
    colorBy: Optional[str] = Field(
        None, description="Category column: series per value, scatter colour, or heatmap rows")
    stacked: Optional[bool] = Field(None, description="Stack bar/area series into a whole")
    aggregate: Optional[str] = Field(
        None, pattern="^(sum|avg|count|min|max)$",
        description="How rows sharing an X value are combined")
    horizontal: Optional[bool] = Field(
        None, description="Bars only; unset lets long labels or many categories decide")
    showGrid: Optional[bool] = Field(None, description="Draw the grid")
    showLegend: Optional[bool] = Field(None, description="Draw the legend")
    colors: Optional[List[str]] = Field(None, description="Chart color palette")
    title: Optional[str] = Field(None, description="Chart title")
    options: Optional[Dict[str, Any]] = Field(None, description="Additional chart options")


class DashboardCreate(BaseModel):
    """Request schema for creating dashboard"""
    name: str = Field(..., min_length=1, max_length=255, description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    query_text: str = Field(..., min_length=1, description="SQL query for dashboard")
    chart_config: ChartConfig = Field(..., description="Chart configuration")
    is_public: bool = Field(default=False, description="Make dashboard publicly accessible")


class DashboardUpdate(BaseModel):
    """Request schema for updating dashboard"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    query_text: Optional[str] = Field(None, min_length=1, description="SQL query for dashboard")
    chart_config: Optional[ChartConfig] = Field(None, description="Chart configuration")
    is_public: Optional[bool] = Field(None, description="Make dashboard publicly accessible")


class DashboardResponse(BaseModel):
    """Response schema for dashboard"""
    id: UUID
    user_id: UUID
    name: str
    description: Optional[str]
    query_text: str
    chart_config: Dict[str, Any]
    is_public: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DashboardListResponse(BaseModel):
    """Response schema for dashboard list"""
    items: List[DashboardResponse]
    total: int
