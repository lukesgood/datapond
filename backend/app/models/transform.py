from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

Base = declarative_base()


class SavedTransform(Base):
    __tablename__ = "saved_transforms"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name             = Column(String(255), unique=True, nullable=False)
    description      = Column(Text, nullable=True)
    source_namespace = Column(String(50), nullable=False)
    target_namespace = Column(String(50), nullable=False)
    target_table     = Column(String(255), nullable=False)
    sql              = Column(Text, nullable=False)
    schedule         = Column(String(100), nullable=True)
    status           = Column(String(50), default="draft")
    dag_id           = Column(String(255), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
