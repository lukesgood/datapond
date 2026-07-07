"""Runtime environment helpers."""
import logging
import os

logger = logging.getLogger(__name__)

_warned_secrets: set = set()


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"


def component_secret(env_var: str, dev_default: str, component: str = "") -> str:
    """Read a component credential from the environment, fail-closed in production.

    Production (ENVIRONMENT=production): unset/empty raises RuntimeError — never
    fall back to a shipped default (Helm injects these from datapond-secrets).
    Dev/CI: warn once per variable, return dev_default so local flows keep working.
    """
    val = (os.getenv(env_var) or "").strip()
    if val:
        return val
    if is_production():
        label = f" for {component}" if component else ""
        raise RuntimeError(
            f"{env_var} is required in production{label} (ENVIRONMENT=production); "
            "it is injected from the datapond-secrets Secret in a Helm deploy."
        )
    if env_var not in _warned_secrets:
        _warned_secrets.add(env_var)
        logger.warning(
            "%s unset — using an insecure local-dev default. NOT for production.", env_var
        )
    return dev_default
