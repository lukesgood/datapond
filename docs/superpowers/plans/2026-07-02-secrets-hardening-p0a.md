# Secrets Hardening P0-a: Critical Secrets Fail-Closed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Eliminate the three prod-critical weak-secret fallbacks (ENCRYPTION_KEY, JWT_SECRET, ADMIN_PASSWORD): generate them strongly in Helm, inject them, and make the backend fail-closed in production (dev keeps working with a loud warning). No existing encrypted data is broken.

**Decisions (confirmed):** Fail-closed **in production only** (`ENVIRONMENT=production`); dev/CI keep working with insecure local defaults + warnings. Scope = the 3 critical secrets only (component passwords / prod-placeholder cleanup = P0-b, separate).

**Architecture:** A tiny `runtime.is_production()` helper. `CredentialVault` derives a valid Fernet key from ANY `ENCRYPTION_KEY` string (but passes an already-valid Fernet key through unchanged → backward compat with existing ciphertext), and fails closed in prod / warns in dev. `auth.py` does the same for JWT_SECRET and ADMIN_PASSWORD. Helm's existing lookup+randAlphaNum generator is extended to ENCRYPTION_KEY + ADMIN_PASSWORD, and both are injected into the backend.

**Tech Stack:** Python/FastAPI, cryptography.Fernet, Helm (lookup/randAlphaNum), pytest.

## Global Constraints

- **Backward compatibility of ciphertext**: if `ENCRYPTION_KEY` is already a valid Fernet key (existing deployments), use it AS-IS. Only derive when it is not a valid Fernet key. Never silently change the effective key for an already-valid key.
- **Prod-only fail-closed**: raise ONLY when `ENVIRONMENT=production` AND the secret is unset. Dev/CI (`ENVIRONMENT` unset) → insecure local default + `logger.warning`. Keeps CI pytest (which imports these modules without ENVIRONMENT) working.
- Helm deploys always set `ENVIRONMENT=production` (backend-deployment.yaml:32) AND now generate all three secrets → fail-closed never fires in a Helm deploy (secure + no lockout).
- helm NOT installed locally → Helm verified by CI render + a value assertion. Backend pure helpers are locally runnable with pytest.
- Remove the public dev key `"dev-key-32-bytes-padding-here!!"` and the weak `"datapond-dev-secret-change-in-production"` / `"datapond123"` from production code paths.

---

## File Structure
- Create: `backend/app/runtime.py`; Tests `backend/tests/test_runtime.py`, `backend/tests/test_vault_key.py`.
- Modify: `backend/app/connectors/vault.py`, `backend/app/api/system_settings.py`, `backend/app/api/auth.py`.
- Modify: `helm/datapond/templates/secrets.yaml`, `helm/datapond/templates/backend-deployment.yaml`, `helm/datapond/values.yaml`, `.github/workflows/ci.yml`, `docs/`.

---

## Task 1: runtime helper + vault Fernet coercion & fail-closed

**Files:** Create `backend/app/runtime.py`, `backend/tests/test_runtime.py`, `backend/tests/test_vault_key.py`; Modify `backend/app/connectors/vault.py`, `backend/app/api/system_settings.py`.

- [ ] **Step 1: failing tests**

`backend/tests/test_runtime.py`:
```python
import importlib
def _fresh():
    import app.runtime as r; return importlib.reload(r)
def test_production_true(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production"); assert _fresh().is_production() is True
def test_dev_false(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False); assert _fresh().is_production() is False
def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "Production"); assert _fresh().is_production() is True
```

`backend/tests/test_vault_key.py`:
```python
from cryptography.fernet import Fernet
from app.connectors.vault import _coerce_fernet_key, CredentialVault

def test_valid_fernet_key_passthrough():
    k = Fernet.generate_key()
    assert _coerce_fernet_key(k.decode()) == k

def test_arbitrary_string_derives_valid_key():
    kb = _coerce_fernet_key("any-random-helm-string-123")
    Fernet(kb)
    assert kb == _coerce_fernet_key("any-random-helm-string-123")

def test_roundtrip_with_derived_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "some-random-string")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    v = CredentialVault()
    assert v.decrypt_credentials(v.encrypt_credentials({"a": "b"})) == {"a": "b"}

def test_prod_failclosed(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    import pytest
    with pytest.raises(Exception):
        CredentialVault()

def test_dev_fallback_ok(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    CredentialVault()
```

- [ ] **Step 2: run → fail** (`cd backend && python3 -m pytest tests/test_runtime.py tests/test_vault_key.py -v`).

- [ ] **Step 3: implement**

`backend/app/runtime.py`:
```python
"""Runtime environment helpers."""
import os

def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"
```

In `backend/app/connectors/vault.py` add `import base64, hashlib` and a helper, and rework `__init__`:
```python
def _coerce_fernet_key(key) -> bytes:
    """Valid Fernet key: an already-valid key passes through (preserves existing
    ciphertext); any other string is deterministically derived (SHA-256 → urlsafe b64)."""
    kb = key.encode() if isinstance(key, str) else key
    try:
        Fernet(kb)
        return kb
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(kb).digest())
```
`__init__`:
```python
    def __init__(self, encryption_key: Optional[str] = None):
        from app.runtime import is_production
        key = encryption_key or os.getenv("ENCRYPTION_KEY")
        if not key:
            if is_production():
                raise ValueError("ENCRYPTION_KEY is required in production (ENVIRONMENT=production).")
            logger.warning("ENCRYPTION_KEY unset — using an insecure local-dev key. NOT for production.")
            key = "datapond-local-dev-encryption-key"
        self.cipher = Fernet(_coerce_fernet_key(key))
```

In `backend/app/api/system_settings.py` line 18, change
`vault = CredentialVault(os.getenv("ENCRYPTION_KEY", "dev-key-32-bytes-padding-here!!"))`
to
`vault = CredentialVault()  # reads ENCRYPTION_KEY; prod-fail-closed, dev-warns (see vault)`.

- [ ] **Step 4: run → pass** (both test files).
- [ ] **Step 5: Commit**
```bash
git add backend/app/runtime.py backend/app/connectors/vault.py backend/app/api/system_settings.py backend/tests/test_runtime.py backend/tests/test_vault_key.py
git commit -m "feat(security): ENCRYPTION_KEY fail-closed in prod + Fernet derivation; drop public dev key"
```

---

## Task 2: auth.py JWT + ADMIN fail-closed

**Files:** Modify `backend/app/api/auth.py`.

- [ ] **Step 1: implement** — replace the `SECRET_KEY = (... or "datapond-dev-secret-change-in-production")` block (~36-44) and `DEFAULT_ADMIN_PASSWORD` (~46):
```python
from app.runtime import is_production   # add near the top imports (and ensure a module logger exists)

_jwt = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET")
if not _jwt:
    if is_production():
        raise RuntimeError("JWT_SECRET is required in production (ENVIRONMENT=production).")
    logger.warning("JWT_SECRET unset — using an insecure local-dev key. NOT for production.")
    _jwt = "datapond-local-dev-jwt-secret"
SECRET_KEY = _jwt
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

DEFAULT_ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
_admin_pw = os.getenv("ADMIN_PASSWORD")
if not _admin_pw:
    if is_production():
        raise RuntimeError("ADMIN_PASSWORD is required in production (ENVIRONMENT=production).")
    logger.warning("ADMIN_PASSWORD unset — using an insecure dev default. NOT for production.")
    _admin_pw = "datapond123"
DEFAULT_ADMIN_PASSWORD = _admin_pw
```
(If auth.py has no module `logger`, add `import logging` + `logger = logging.getLogger(__name__)`.)

- [ ] **Step 2: Verify** — `cd backend && python3 -m pytest tests/ -q` (existing tests pass; ENVIRONMENT unset → dev path, no raise) + `python3 -m py_compile app/api/auth.py`.
- [ ] **Step 3: Commit**
```bash
git add backend/app/api/auth.py
git commit -m "feat(security): JWT_SECRET + ADMIN_PASSWORD fail-closed in prod (dev warns)"
```

---

## Task 3: Helm generate + inject ENCRYPTION_KEY & ADMIN_PASSWORD

**Files:** Modify `helm/datapond/templates/secrets.yaml`, `helm/datapond/templates/backend-deployment.yaml`, `helm/datapond/values.yaml`, `.github/workflows/ci.yml`, docs.

- [ ] **Step 1: secrets.yaml** — after the JWT block (reuse `$existing` from line 35), add:
```yaml
  {{- $ekey := "" }}
  {{- if and $existing $existing.data (hasKey $existing.data "ENCRYPTION_KEY") }}
  {{- $ekey = index $existing.data "ENCRYPTION_KEY" | b64dec }}
  {{- else }}
  {{- $ekey = randAlphaNum 48 }}
  {{- end }}
  ENCRYPTION_KEY: {{ $ekey | quote }}
  {{- $apass := (((.Values.auth).adminPassword) | default "") }}
  {{- if not $apass }}
  {{- if and $existing $existing.data (hasKey $existing.data "ADMIN_PASSWORD") }}
  {{- $apass = index $existing.data "ADMIN_PASSWORD" | b64dec }}
  {{- else }}
  {{- $apass = randAlphaNum 24 }}
  {{- end }}
  {{- end }}
  ADMIN_PASSWORD: {{ $apass | quote }}
```

- [ ] **Step 2: backend-deployment.yaml** — inject both near JWT_SECRET (~77-89):
```yaml
        - name: ENCRYPTION_KEY
          valueFrom: { secretKeyRef: { name: datapond-secrets, key: ENCRYPTION_KEY } }
        - name: ADMIN_PASSWORD
          valueFrom: { secretKeyRef: { name: datapond-secrets, key: ADMIN_PASSWORD } }
```

- [ ] **Step 3: values.yaml** — add to the `auth:` block (create if absent; do NOT duplicate):
```yaml
auth:
  # Optional: pin the initial admin password. Empty ⇒ Helm generates a strong random one
  # (retrieve: kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d).
  adminPassword: ""
```

- [ ] **Step 4: ci.yml** — extend the helm value-assertion step:
```bash
          echo "== critical secrets generated + injected =="
          helm template datapond helm/datapond | grep -q 'ENCRYPTION_KEY:' || { echo FAIL ENCRYPTION_KEY; exit 1; }
          helm template datapond helm/datapond | grep -q 'ADMIN_PASSWORD:'  || { echo FAIL ADMIN_PASSWORD; exit 1; }
          helm template datapond helm/datapond | grep -q 'name: ENCRYPTION_KEY' || { echo FAIL ENCRYPTION_KEY inject; exit 1; }
          echo "OK: secrets wired"
```

- [ ] **Step 5: docs** — add to `docs/AWS_MVP_RUNBOOK.md`: retrieving the generated admin password + note ENCRYPTION_KEY/JWT/ADMIN are auto-generated, preserved across upgrades, and required in production (Helm provides them).

- [ ] **Step 6: Commit**
```bash
git add helm/datapond/templates/secrets.yaml helm/datapond/templates/backend-deployment.yaml helm/datapond/values.yaml .github/workflows/ci.yml docs/
git commit -m "feat(helm): generate+inject ENCRYPTION_KEY and ADMIN_PASSWORD (lookup-preserve) + CI assert + docs"
```

---

## Task 4: CI verify + PR
- [ ] **Step 1: push + PR.** CI runs backend pytest (runtime/vault tests + no regressions), helm render + the new secret assertions.
- [ ] **Step 2: fix any CI failure; complete only when all green.**

---

## Self-Review

**Coverage:** ENCRYPTION_KEY (T1), JWT_SECRET + ADMIN_PASSWORD (T2), Helm generation+injection+docs (T3), CI (T4). Component passwords + prod-placeholder cleanup = P0-b (out of scope, stated).

**Backward-compat / no-lockout:** existing valid Fernet ENCRYPTION_KEY passes through unchanged (ciphertext preserved); Helm deploys set ENVIRONMENT=production AND generate all three → fail-closed never locks out; dev/CI (ENVIRONMENT unset) keep working with warnings so pytest/import stays green. `is_production()` is the single gate used by both vault and auth.

**Placeholder scan:** none. Dev fallbacks are intentional (prod-only fail-closed) and clearly warned; never used in production.
