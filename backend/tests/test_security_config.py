"""Settings → Security reads what sign-in actually does (app/api/auth.py
security_config), not a hard-coded list that still said "admin / viewer roles"."""
import inspect

from app.api import auth
from app.permissions import ASSIGNABLE_ROLES


def test_reports_every_assignable_role():
    cfg = auth.security_config()
    assert [r["name"] for r in cfg["roles"]] == list(ASSIGNABLE_ROLES)
    assert all(r["permissions"] > 0 for r in cfg["roles"])


def test_reports_the_enforced_values(monkeypatch):
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "7")
    cfg = auth.security_config()
    assert cfg["session_hours"] == auth.TOKEN_EXPIRE_HOURS
    assert cfg["login_lockout"]["max_failures"] == 7
    assert cfg["password_min_length"] == 6
    # The hashing claim names the cost the hasher really uses.
    assert "rounds=12" in inspect.getsource(auth._hash_password)
    assert "12" in cfg["password_hash"]


def test_route_needs_user_manage():
    src = inspect.getsource(auth.get_security_config)
    assert 'require_permission("user:manage")' in src
