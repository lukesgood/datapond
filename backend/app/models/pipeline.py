"""
Pipeline SQLAlchemy model for storing pipeline definitions
"""
from sqlalchemy import Column, String, Text, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
import enum

from app.database.connection import Base


class PipelineStatus(str, enum.Enum):
    draft = "draft"
    deployed = "deployed"
    failed = "failed"


class SavedPipeline(Base):
    """Stored pipeline definitions with draft/deployed state"""
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    schedule = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    code = Column(Text, nullable=False)  # Generated Python DSL code
    nodes_json = Column(JSONB, nullable=False, default=[])  # ReactFlow nodes
    edges_json = Column(JSONB, nullable=False, default=[])  # ReactFlow edges
    config_json = Column(JSONB, nullable=False, default={})  # Pipeline config (advanced settings)
    dag_id = Column(String(255), nullable=True)  # Airflow DAG ID after deploy
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
