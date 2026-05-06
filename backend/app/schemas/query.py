"""
Pydantic schemas for query history
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class QueryExecuteRequest(BaseModel):
    """Request schema for query execution"""
    query: str = Field(..., description="SQL query to execute")
    save_history: bool = Field(default=True, description="Save query to history")


class QueryHistoryResponse(BaseModel):
    """Response schema for query history item"""
    id: UUID
    user_id: UUID
    query_text: str
    execution_time_ms: int
    rows_returned: int
    status: str
    error_message: Optional[str] = None
    catalog: Optional[str] = None
    schema: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class QueryHistoryListResponse(BaseModel):
    """Response schema for query history list"""
    items: List[QueryHistoryResponse]
    total: int
    limit: int
    offset: int
