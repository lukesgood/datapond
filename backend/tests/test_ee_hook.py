"""The /api/capabilities sso flag logic (pure — mirrors main.py's expression)."""
from app.capabilities import compute_capabilities


def _sso_flag(ee_loaded: bool, env: dict) -> bool:
    # Same expression main.py uses for the "sso" capability
    return ee_loaded and str(env.get("OIDC_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")


def test_sso_false_without_ee():
    assert _sso_flag(False, {"OIDC_ENABLED": "true"}) is False


def test_sso_false_without_oidc_enabled():
    assert _sso_flag(True, {}) is False


def test_sso_true_when_both():
    assert _sso_flag(True, {"OIDC_ENABLED": "true"}) is True


def test_base_capabilities_unaffected():
    caps = compute_capabilities({})
    assert "sso" not in caps  # sso is layered on in main.py, not in the pure fn
