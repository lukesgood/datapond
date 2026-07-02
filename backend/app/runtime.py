"""Runtime environment helpers."""
import os


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"
