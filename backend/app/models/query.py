"""
Query history SQLAlchemy model
"""
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from app.database.connection import Base


class QueryHistory(Base):
    """Query execution history"""
    __tablename__ = "query_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)  # FK to users table
    query_text = Column(Text, nullable=False)
    execution_time_ms = Column(Integer, nullable=False)
    rows_returned = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="success")
    error_message = Column(Text, nullable=True)
    catalog = Column(String(128), nullable=True)
    schema = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "query_text": self.query_text,
            "execution_time_ms": self.execution_time_ms,
            "rows_returned": self.rows_returned,
            "status": self.status,
            "error_message": self.error_message,
            "catalog": self.catalog,
            "schema": self.schema,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
