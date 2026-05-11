"""
Database connection and session management for DataPond
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# DATABASE_URL takes precedence; fall back to individual vars.
# POSTGRES_PORT must not be read directly — K8s injects POSTGRES_PORT=tcp://...
# for the ClusterIP service, which breaks int parsing.
DATABASE_URL = os.getenv("DATABASE_URL") or (
    "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "datapond"),
        password=os.getenv("POSTGRES_PASSWORD", "datapond"),
        host=os.getenv("POSTGRES_HOST", "postgres.datapond.svc.cluster.local"),
        port="5432",
        db=os.getenv("POSTGRES_DB", "datapond"),
    )
)

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Test connection before using
    echo=False  # Set to True for SQL query logging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()


def get_db():
    """
    Dependency function for FastAPI to inject database session

    Usage in FastAPI endpoint:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager for database session

    Usage:
        with get_db_context() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
