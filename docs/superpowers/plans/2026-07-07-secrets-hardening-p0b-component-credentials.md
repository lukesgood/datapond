# Secrets Hardening P0-b: Component Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate weak component-credential defaults (postgres, MinIO/S3, Airflow, Jupyter, Polaris, OpenMetadata, LiteLLM key fallback): Helm generates strong values with lookup-preserve, templates stop leaking plaintext into pod manifests, and the backend fails closed in production via a call-time `component_secret()` guard.

**Spec:** `docs/superpowers/specs/2026-07-07-secrets-hardening-p0b-component-credentials-design.md`

**Architecture:** New `runtime.component_secret(env_var, dev_default, component)` — prod: raise, dev: warn-once + dev default — replaces every weak `os.getenv` credential default at **call time** (module-level reads for optional components become lazy functions). `secrets.yaml` extends the P0-1a explicit→lookup→random chain to POSTGRES_PASSWORD, S3_SECRET_KEY, AIRFLOW_PASSWORD, JUPYTER_TOKEN, POLARIS_CLIENT_SECRET. Templates that embed passwords switch to `secretKeyRef` / `$(VAR)`-expansion (pattern already used by backend `DATABASE_URL` and mlflow).

**Tech Stack:** Python/FastAPI, pytest, Helm (lookup/randAlphaNum), GitHub Actions CI.

## Global Constraints

- Fail-closed ONLY when `ENVIRONMENT=production` (`app.runtime.is_production()`); dev/CI warn once and use the current dev default. Empty string counts as unset.
- Credential reads for optional components (airflow, jupyter, openmetadata, polaris, litellm) must happen inside the request path — never at module import. Postgres is core; import-time is acceptable.
- Helm generation priority per key: explicit values → existing `datapond-secrets` (lookup, preserves upgrades) → `randAlphaNum`. NO rotation of existing installs.
- `values-quicktest.yaml` / `values-dev.yaml` KEEP known dev creds (explicit-wins). base / prod / onprem (foundation/aws inherit base) get `""` ⇒ generated.
- Dev defaults passed to `component_secret` = today's exact defaults (behavior-neutral in dev): `datapond`, `dev_password`, `datapond_dev`, `airflow`, `jupyter`, `admin`, `changeme-polaris-secret`, `""` (litellm).
- Usernames / access-key IDs are identities, not secrets: `POSTGRES_USER`, MinIO `rootUser`/`S3_ACCESS_KEY`, `AIRFLOW_USERNAME`, `POLARIS_CLIENT_ID`, `OPENMETADATA_EMAIL` stay plain values.
- helm is NOT installed locally — Helm work is verified by CI render assertions (Task 7). Backend changes are verified locally with pytest, but CI py3.11 is authoritative.
- `$(VAR)` env expansion in K8s resolves only env entries defined EARLIER in the same container's env list — always add the `secretKeyRef` env before the string that expands it.

---

### Task 1: `component_secret()` helper (TDD)

**Files:**
- Modify: `backend/app/runtime.py`
- Test: `backend/tests/test_component_secret.py`

**Interfaces:**
- Produces: `app.runtime.component_secret(env_var: str, dev_default: str, component: str = "") -> str` — used by every backend call site in Tasks 2–3. Raises `RuntimeError` in prod when env var unset/empty; returns stripped env value when set; warns once + returns `dev_default` in dev.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_component_secret.py`:

```python
import logging
import pytest
from app import runtime
from app.runtime import component_secret


@pytest.fixture(autouse=True)
def _reset_warned():
    runtime._warned_secrets.clear()
    yield
    runtime._warned_secrets.clear()


def test_set_value_wins_everywhere(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MY_SECRET", " s3cret ")
    assert component_secret("MY_SECRET", "dev") == "s3cret"


def test_prod_missing_raises(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MY_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="MY_SECRET is required in production"):
        component_secret("MY_SECRET", "dev")


def test_prod_empty_string_raises(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MY_SECRET", "   ")
    with pytest.raises(RuntimeError):
        component_secret("MY_SECRET", "dev", component="airflow")


def test_dev_returns_default_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MY_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        assert component_secret("MY_SECRET", "dev-default") == "dev-default"
    assert "MY_SECRET" in caplog.text


def test_dev_warns_only_once(monkeypatch, caplog):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MY_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        component_secret("MY_SECRET", "d")
        component_secret("MY_SECRET", "d")
    assert caplog.text.count("MY_SECRET") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_component_secret.py -v`
Expected: FAIL / ERROR with `ImportError: cannot import name 'component_secret'`

- [ ] **Step 3: Implement** — `backend/app/runtime.py` becomes:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_component_secret.py tests/test_runtime.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime.py backend/tests/test_component_secret.py
git commit -m "feat(security): component_secret() — call-time prod fail-closed credential reads"
```

---

### Task 2: Backend call sites — Postgres + S3

**Files:**
- Modify: `backend/app/database/connection.py:13-21`, `backend/app/api/auth.py:~82`, `backend/app/rls/loader.py:~34`, `backend/app/api/connectors.py:~287,~658,~673,~768`, `backend/app/connectors/iceberg_catalog.py:~36`, `backend/app/api/streaming.py:~257,~373`

**Interfaces:**
- Consumes: `component_secret` from Task 1 (`from app.runtime import component_secret`).
- Produces: no new interfaces — behavior-preserving in dev (same defaults), fail-closed in prod.

All these reads are already lazy (inside functions) except `connection.py`, which is core (import-time acceptable; the fallback only evaluates when `DATABASE_URL` is unset, because `or` short-circuits).

- [ ] **Step 1: connection.py** — add `from app.runtime import component_secret` after the os import; replace `password=os.getenv("POSTGRES_PASSWORD", "datapond"),` with:

```python
        password=component_secret("POSTGRES_PASSWORD", "datapond", component="postgres"),
```

- [ ] **Step 2: the five `dev_password` sites** — in `app/api/auth.py` (`_db_pool` creation), `app/rls/loader.py` (`_pool` creation), `app/api/connectors.py` (`_pool_kwargs()` and the two sampledb `_asyncpg.connect(...)` calls and the `sample_config` dict): add `from app.runtime import component_secret` to each file's imports (auth.py already imports `is_production` — extend that import line), and replace every

```python
password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
```

with

```python
password=component_secret("POSTGRES_PASSWORD", "dev_password", component="postgres"),
```

(connectors.py `sample_config` uses `"password": ...` dict syntax — same replacement.) Verify all converted: `grep -rn '"dev_password"' app/` → no `os.getenv` hits remain.

- [ ] **Step 3: S3 secret keys** — in `app/connectors/iceberg_catalog.py` (inside the catalog factory) and `app/api/streaming.py` (both `create_sink` and the CDC wizard function), add the import and replace only the SECRET key (access-key ID stays a plain getenv):

```python
# iceberg_catalog.py
"s3.secret-access-key": component_secret("S3_SECRET_KEY", "datapond_dev", component="s3"),
# streaming.py (both sites)
s3_secret    = component_secret("S3_SECRET_KEY", "datapond_dev", component="s3")
```

- [ ] **Step 4: Verify** — `cd backend && python3 -m pytest tests/ -q` (no regressions; ENVIRONMENT unset in CI/local ⇒ dev path) and `python3 -m py_compile app/database/connection.py app/api/auth.py app/rls/loader.py app/api/connectors.py app/connectors/iceberg_catalog.py app/api/streaming.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/app
git commit -m "feat(security): postgres/S3 credential reads via component_secret (prod fail-closed)"
```

---

### Task 3: Backend call sites — Airflow / Jupyter / OpenMetadata / Polaris / LiteLLM (lazy refactor)

**Files:**
- Modify: `backend/app/api/transforms.py:~30`, `backend/app/api/airflow.py:~17`, `backend/app/api/pipelines.py:~266,~338`, `backend/app/api/notebooks.py:~16`, `backend/app/api/om_util.py:~19,~35`, `backend/app/api/polaris_client.py:~16`, `backend/app/connectors/iceberg_catalog.py:~25`, `backend/app/api/ai_sql.py:~47`, `backend/app/api/ai_vectors.py:~50`, `backend/app/api/ai_backends.py:~81`

**Interfaces:**
- Consumes: `component_secret` from Task 1.
- Produces (module-internal helpers later steps of THIS task wire up): `_airflow_auth() -> tuple` in transforms.py / airflow.py / pipelines.py; `_jupyter_token() -> str` in notebooks.py. These replace the module-level constants `AIRFLOW_AUTH`, `AIRFLOW_PASSWORD`, `JUPYTER_TOKEN`.

These components are optional ⇒ reads move from module level into functions so a disabled component's missing env never crashes startup.

- [ ] **Step 1: Airflow modules** — in `transforms.py` and `pipelines.py`, replace the module-level

```python
AIRFLOW_AUTH = (os.getenv("AIRFLOW_USERNAME", "airflow"), os.getenv("AIRFLOW_PASSWORD", "airflow"))
```

with

```python
def _airflow_auth() -> tuple:
    """Resolved per-request: fail-closed in prod when Airflow creds are missing."""
    return (
        os.getenv("AIRFLOW_USERNAME", "airflow"),
        component_secret("AIRFLOW_PASSWORD", "airflow", component="airflow"),
    )
```

then replace every use of `AIRFLOW_AUTH` in those files with `_airflow_auth()` (find them: `grep -n "AIRFLOW_AUTH" app/api/transforms.py app/api/pipelines.py` — includes the function-local `AIRFLOW_AUTH = (...)` in pipelines.py's deploy function; replace that assignment with `AIRFLOW_AUTH = _airflow_auth()` since it's already lazy). In `airflow.py`, replace the module-level `AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD", "airflow")` with the same `_airflow_auth()` helper and update every `(AIRFLOW_USERNAME, AIRFLOW_PASSWORD)` / `AIRFLOW_PASSWORD` use (`grep -n "AIRFLOW_PASSWORD\|AIRFLOW_USERNAME" app/api/airflow.py`). Add the `component_secret` import to all three files.

- [ ] **Step 2: notebooks.py** — replace module-level `JUPYTER_TOKEN = os.getenv("JUPYTER_TOKEN", "jupyter")` with:

```python
def _jupyter_token() -> str:
    return component_secret("JUPYTER_TOKEN", "jupyter", component="jupyter")
```

and update every `JUPYTER_TOKEN` use to `_jupyter_token()` (`grep -n "JUPYTER_TOKEN" app/api/notebooks.py`).

- [ ] **Step 3: om_util.py** — delete the module-level `OPENMETADATA_PASSWORD = os.getenv("OPENMETADATA_PASSWORD", "admin")`; inside `om_token()`, immediately before `pw_b64 = base64.b64encode(...)`, add:

```python
    password = component_secret("OPENMETADATA_PASSWORD", "admin", component="openmetadata")
```

and change the encode line to use `password.encode()`. Check for other `OPENMETADATA_PASSWORD` uses: `grep -rn "OPENMETADATA_PASSWORD" app/` — convert any other module-level read the same way (call-time).

- [ ] **Step 4: Polaris** — `polaris_client.py`: delete module-level `POLARIS_CLIENT_SECRET = os.getenv(...)`; inside `_get_token()` (start of the token-fetch branch) add `client_secret = component_secret("POLARIS_CLIENT_SECRET", "changeme-polaris-secret", component="polaris")` and use it where `POLARIS_CLIENT_SECRET` was used (`grep -n "POLARIS_CLIENT_SECRET" app/api/polaris_client.py`). `iceberg_catalog.py` (already lazy): replace `client_secret = os.getenv("POLARIS_CLIENT_SECRET", "changeme-polaris-secret")` with `client_secret = component_secret("POLARIS_CLIENT_SECRET", "changeme-polaris-secret", component="polaris")`.

- [ ] **Step 5: LiteLLM master key** — dev default is `""` (preserves today's no-auth-header dev behavior); prod raises instead of calling the gateway unauthenticated. Resolve the key ONLY after the URL check so a disabled gateway keeps returning 503, never a RuntimeError:

`ai_vectors.py` and `ai_backends.py` `_gateway()`:

```python
def _gateway() -> tuple[str, str]:
    url = os.getenv("LITELLM_URL", "").strip().rstrip("/")
    if not url:
        raise HTTPException(503, "LiteLLM gateway not configured (LITELLM_URL empty).")
    key = component_secret("LITELLM_MASTER_KEY", "", component="litellm")
    return url, key
```

`ai_sql.py` gateway-conf function — replace the `"master_key"` line so it resolves only when the gateway is configured:

```python
        url = os.getenv("LITELLM_URL", "").strip()
        return {
            "litellm_url":   url,
            "litellm_model": os.getenv("LITELLM_MODEL", "default"),
            "master_key":    component_secret("LITELLM_MASTER_KEY", "", component="litellm") if url else "",
        }
```

(keep the existing comments; add the import.)

- [ ] **Step 6: Verify no stragglers + tests**

```bash
cd backend
grep -rn 'os.getenv("AIRFLOW_PASSWORD"\|os.getenv("JUPYTER_TOKEN"\|os.getenv("OPENMETADATA_PASSWORD"\|os.getenv("POLARIS_CLIENT_SECRET"\|os.getenv("LITELLM_MASTER_KEY"' app/
# Expected: no output
python3 -m pytest tests/ -q   # no regressions
```

- [ ] **Step 7: Commit**

```bash
git add backend/app
git commit -m "feat(security): lazy component_secret reads for airflow/jupyter/OM/polaris/litellm"
```

---

### Task 4: Helm — generate component secrets + blank weak values

**Files:**
- Modify: `helm/datapond/templates/secrets.yaml`, `helm/datapond/values.yaml`, `helm/datapond/values-prod.yaml`, `helm/datapond/values-onprem.yaml`, `helm/datapond/values-quicktest.yaml`, `helm/datapond/values-dev.yaml`

**Interfaces:**
- Produces: `datapond-secrets` keys consumed by Task 5/6 `secretKeyRef`s: `POSTGRES_PASSWORD`, `S3_SECRET_KEY`, `SEAWEEDFS_S3_PASSWORD`, `AIRFLOW_PASSWORD` (all pre-existing keys, now generated), `JUPYTER_TOKEN`, `POLARIS_CLIENT_SECRET`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `HF_TOKEN` (new keys). New values fields: `jupyter.auth.token`.

- [ ] **Step 1: secrets.yaml — move `$existing` to the top.** The lookup currently sits mid-file (line ~35, JWT block). Move `{{- $existing := (lookup "v1" "Secret" (.Values.namespace | default "datapond") "datapond-secrets") }}` to directly under `stringData:` (before the postgres block) and delete it from the JWT block. Also widen the file's top-level guard (line 1) to include the backend:

```yaml
{{- if or .Values.postgres.enabled .Values.minio.enabled .Values.litellm.enabled .Values.backend.enabled }}
```

- [ ] **Step 2: secrets.yaml — postgres block.** Replace the current `POSTGRES_PASSWORD: {{ .Values.postgres.auth.password | default "changeme" | quote }}` so the postgres block reads:

```yaml
  {{- if .Values.postgres.enabled }}
  # PostgreSQL credentials — password lookup-preserve (explicit → existing → random).
  # NEVER delete this Secret while keeping the postgres PVC: the DB was initialized
  # with this password and a regenerated one will not match.
  POSTGRES_DB: {{ .Values.postgres.auth.database | default "datapond" | quote }}
  POSTGRES_USER: {{ .Values.postgres.auth.username | default "datapond" | quote }}
  {{- $pgpass := (((.Values.postgres).auth).password) | default "" }}
  {{- if not $pgpass }}
  {{- if and $existing $existing.data (hasKey $existing.data "POSTGRES_PASSWORD") }}
  {{- $pgpass = index $existing.data "POSTGRES_PASSWORD" | b64dec }}
  {{- else }}
  {{- $pgpass = randAlphaNum 24 }}
  {{- end }}
  {{- end }}
  POSTGRES_PASSWORD: {{ $pgpass | quote }}
  {{- end }}
```

- [ ] **Step 3: secrets.yaml — MinIO block.** Same pattern; ONE resolved password feeds both key aliases; rootUser stays values-driven:

```yaml
  {{- if .Values.minio.enabled }}
  # MinIO S3 credentials (multiple key names for compatibility). Secret key is
  # lookup-preserve generated; the access-key ID (rootUser) is an identity, not a secret.
  {{- $s3pass := (((.Values.minio).auth).rootPassword) | default "" }}
  {{- if not $s3pass }}
  {{- if and $existing $existing.data (hasKey $existing.data "S3_SECRET_KEY") }}
  {{- $s3pass = index $existing.data "S3_SECRET_KEY" | b64dec }}
  {{- else }}
  {{- $s3pass = randAlphaNum 32 }}
  {{- end }}
  {{- end }}
  S3_ACCESS_KEY: {{ .Values.minio.auth.rootUser | default "datapond" | quote }}
  S3_SECRET_KEY: {{ $s3pass | quote }}
  SEAWEEDFS_S3_USER: {{ .Values.minio.auth.rootUser | default "datapond" | quote }}
  SEAWEEDFS_S3_PASSWORD: {{ $s3pass | quote }}
  {{- end }}
```

- [ ] **Step 4: secrets.yaml — Airflow block.** Replace `AIRFLOW_PASSWORD: {{ .Values.airflow.auth.password | default "airflow" | quote }}`:

```yaml
  {{- if .Values.airflow.enabled }}
  # Airflow admin password — lookup-preserve (explicit → existing → random).
  {{- $afpass := (((.Values.airflow).auth).password) | default "" }}
  {{- if not $afpass }}
  {{- if and $existing $existing.data (hasKey $existing.data "AIRFLOW_PASSWORD") }}
  {{- $afpass = index $existing.data "AIRFLOW_PASSWORD" | b64dec }}
  {{- else }}
  {{- $afpass = randAlphaNum 20 }}
  {{- end }}
  {{- end }}
  AIRFLOW_PASSWORD: {{ $afpass | quote }}
  {{- end }}
```

- [ ] **Step 5: secrets.yaml — new JUPYTER_TOKEN + POLARIS_CLIENT_SECRET blocks** (add after the Airflow block):

```yaml
  {{- if .Values.jupyter.enabled }}
  # JupyterLab token — lookup-preserve. Retrieve:
  # kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.JUPYTER_TOKEN}' | base64 -d
  {{- $jtok := (((.Values.jupyter).auth).token) | default "" }}
  {{- if not $jtok }}
  {{- if and $existing $existing.data (hasKey $existing.data "JUPYTER_TOKEN") }}
  {{- $jtok = index $existing.data "JUPYTER_TOKEN" | b64dec }}
  {{- else }}
  {{- $jtok = randAlphaNum 32 }}
  {{- end }}
  {{- end }}
  JUPYTER_TOKEN: {{ $jtok | quote }}
  {{- end }}

  {{- if .Values.polaris.enabled }}
  # Polaris OAuth2 client secret — single source of truth (backend + init/bootstrap
  # jobs all read THIS key; the old standalone polaris-secret was removed to avoid
  # two independent randoms desyncing on fresh install). Lookup-preserve.
  {{- $psec := (((.Values.polaris).auth).clientSecret) | default "" }}
  {{- if not $psec }}
  {{- if and $existing $existing.data (hasKey $existing.data "POLARIS_CLIENT_SECRET") }}
  {{- $psec = index $existing.data "POLARIS_CLIENT_SECRET" | b64dec }}
  {{- else }}
  {{- $psec = randAlphaNum 32 }}
  {{- end }}
  {{- end }}
  POLARIS_CLIENT_SECRET: {{ $psec | quote }}
  {{- end }}
```

- [ ] **Step 6: secrets.yaml — with-guarded Langfuse/HF entries** (add near the LDAP block):

```yaml
  {{- if .Values.litellm.enabled }}
  {{- with ((.Values.litellm.tracing | default dict).publicKey) }}
  LANGFUSE_PUBLIC_KEY: {{ . | quote }}
  {{- end }}
  {{- with ((.Values.litellm.tracing | default dict).secretKey) }}
  # Langfuse tracing keys — kept out of pod manifests (consumed via secretKeyRef)
  LANGFUSE_SECRET_KEY: {{ . | quote }}
  {{- end }}
  {{- end }}
  {{- with ((.Values.vllm | default dict).hfToken) }}
  # HuggingFace hub token for vLLM model pulls
  HF_TOKEN: {{ . | quote }}
  {{- end }}
```

- [ ] **Step 7: values.yaml (base)** — blank the weak credentials, each with the comment `# empty ⇒ Helm generates & preserves (see templates/secrets.yaml)`:
  - `postgres.auth.password: datapond_password` → `password: ""`
  - the mlflow-section `postgres` block (`values.yaml:~247`): DELETE its `password: datapond_password` line — dead config (mlflow-deployment reads `datapond-secrets/POSTGRES_PASSWORD`).
  - `airflow.auth.password: airflow` → `password: ""`
  - `minio.auth.rootPassword: datapond_s3_password` → `rootPassword: ""` (`rootUser: datapond` stays)
  - `monitoring.grafana.adminPassword: admin` → `adminPassword: ""` with comment `# set explicitly if you enable grafana (no template consumes this yet)`
  - `polaris.auth.clientSecret: changeme-polaris-secret` → `clientSecret: ""`; `adminPassword: changeme-admin-password` → DELETE the line (nothing consumes it — verify: `grep -rn "polaris.auth.adminPassword\|auth.adminPassword" helm/datapond/templates/` → only hits must be `.Values.auth.adminPassword` (the app admin), not polaris)
  - `jupyter.env`: remove the `JUPYTER_TOKEN` entry; add under `jupyter:` a new block:

```yaml
  auth:
    # JupyterLab token. Empty ⇒ Helm generates & preserves (retrieve:
    # kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.JUPYTER_TOKEN}' | base64 -d)
    token: ""
```

- [ ] **Step 8: values-prod.yaml** — remove all seven `CHANGE_THIS_*`: postgres password → `""`, airflow password → `""`, `rootUser: CHANGE_THIS_MINIO_USER` → `rootUser: datapond`, `rootPassword` → `""`, grafana `adminPassword` → `""`, openmetadata `auth.adminPassword` → `""` with comment `# set to your OM instance's admin password (OM manages this itself)`, and remove the `JUPYTER_TOKEN` entry from `jupyter.env` (generated via base). Each generated field gets the same `# empty ⇒ generated` comment.

- [ ] **Step 9: values-onprem.yaml** — `postgres.auth.password: datapond_password` → `""`, `airflow.auth.password: airflow` → `""`, `minio.auth.rootPassword: datapond_s3_password` → `""`, remove `JUPYTER_TOKEN` from `jupyter.env`.

- [ ] **Step 10: values-quicktest.yaml + values-dev.yaml (KEEP dev creds, migrate jupyter format)** — postgres/airflow/minio passwords stay exactly as-is. Replace the `JUPYTER_TOKEN` entry in `jupyter.env` with the new explicit field under `jupyter:`:

```yaml
  auth:
    token: "jupyter"   # known dev token (explicit-wins; docs reference it)
```

- [ ] **Step 11: Commit**

```bash
git add helm/datapond/templates/secrets.yaml helm/datapond/values*.yaml
git commit -m "feat(helm): lookup-preserve generation for component passwords; blank weak values defaults"
```

---

### Task 5: Helm — kill plaintext-in-manifest leaks

**Files:**
- Modify: `helm/datapond/templates/airflow-deployment.yaml`, `helm/datapond/templates/backend-deployment.yaml:130-135`, `helm/datapond/templates/polaris-catalog-init-job.yaml:~40`, `helm/datapond/templates/polaris-bootstrap-job.yaml:~99`, `helm/datapond/templates/polaris-deployment.yaml:~197-208`, `helm/datapond/templates/litellm-deployment.yaml:~155-160`, `helm/datapond/templates/vllm-deployment.yaml:~48-50`

**Interfaces:**
- Consumes: `datapond-secrets` keys from Task 4 (`POSTGRES_PASSWORD`, `AIRFLOW_PASSWORD`, `POLARIS_CLIENT_SECRET`, `LANGFUSE_*`, `HF_TOKEN`).

- [ ] **Step 1: airflow-deployment.yaml — DB conn strings (3 sites: init/webserver/scheduler).** For EACH container whose env contains `AIRFLOW__CORE__SQL_ALCHEMY_CONN`, insert FIRST in that env list:

```yaml
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: POSTGRES_PASSWORD
```

then change each conn value to `$(VAR)` expansion (K8s expands refs to earlier env entries):

```yaml
        - name: AIRFLOW__CORE__SQL_ALCHEMY_CONN
          value: "postgresql+psycopg2://{{ .Values.postgres.auth.username | default "datapond" }}:$(POSTGRES_PASSWORD)@postgres:5432/airflow"
```

- [ ] **Step 2: airflow-deployment.yaml — admin user creation.** The init block runs `airflow users create ... --password {{ .Values.airflow.auth.password }}` inside a shell script. Add to that container's env:

```yaml
        - name: AIRFLOW_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: AIRFLOW_PASSWORD
```

and change the script line to `--password "$AIRFLOW_ADMIN_PASSWORD" \` (shell expansion, quoted).

- [ ] **Step 3: backend-deployment.yaml — AIRFLOW_PASSWORD.** Replace

```yaml
        - name: AIRFLOW_PASSWORD
          value: "{{ .Values.airflow.auth.password }}"
```

with (optional: backend renders this env even when airflow is disabled ⇒ key may be absent):

```yaml
        - name: AIRFLOW_PASSWORD
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: AIRFLOW_PASSWORD
              optional: true
```

- [ ] **Step 4: backend-deployment.yaml — POLARIS_CLIENT_SECRET.** Inside the existing `{{- if .Values.polaris.enabled }}` block, replace the inline `value: "{{ .Values.polaris.auth.clientSecret }}"` with:

```yaml
        - name: POLARIS_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: POLARIS_CLIENT_SECRET
```

- [ ] **Step 5: polaris-catalog-init-job.yaml** — replace `CSECRET`'s inline `value: "{{ .Values.polaris.auth.clientSecret }}"` with the same `secretKeyRef` (key `POLARIS_CLIENT_SECRET`, no `optional` — the job only renders when polaris is enabled).

- [ ] **Step 6: polaris-bootstrap-job.yaml** — the `sh -c` script embeds the credential. Add to the container env:

```yaml
        - name: POLARIS_CLIENT_ID
          value: {{ .Values.polaris.auth.clientId | quote }}
        - name: POLARIS_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: POLARIS_CLIENT_SECRET
```

and change the script's credential line to shell expansion:

```
              --credential={{ .Values.polaris.auth.realm | default "default-realm" }},${POLARIS_CLIENT_ID},${POLARIS_CLIENT_SECRET}
```

- [ ] **Step 7: polaris-deployment.yaml — delete the dead `polaris-secret` Secret** (the whole `---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: polaris-secret\n...` block, ~lines 197-208). Nothing consumes it (`grep -rn "polaris-secret" helm/datapond/templates/` must return zero hits after deletion), and leaving it would render a value desynced from the generated `POLARIS_CLIENT_SECRET`.

- [ ] **Step 8: litellm-deployment.yaml — Langfuse keys.** Inside the existing tracing `{{- if ... }}` block, keep `LANGFUSE_HOST` as-is and replace the two inline key envs with:

```yaml
        - name: LANGFUSE_PUBLIC_KEY
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: LANGFUSE_PUBLIC_KEY
        - name: LANGFUSE_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: LANGFUSE_SECRET_KEY
```

Also update the stale comment above (`keys can be moved to a Secret for production` → `keys come from datapond-secrets`).

- [ ] **Step 9: vllm-deployment.yaml — HF token.** Inside the existing `{{- if .Values.vllm.hfToken }}` guard, replace the inline value with:

```yaml
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: HF_TOKEN
```

- [ ] **Step 10: Sanity grep + commit**

```bash
grep -rn '{{ .Values.polaris.auth.clientSecret }}\|{{ .Values.airflow.auth.password }}\|{{ .Values.postgres.auth.password }}\|.Values.litellm.tracing.secretKey \|.Values.vllm.hfToken | quote' helm/datapond/templates/
# Expected: only secrets.yaml hits (the generation source), no deployment/job hits
git add helm/datapond/templates
git commit -m "feat(helm): component passwords via secretKeyRef/\$(VAR) — no plaintext in pod manifests"
```

---

### Task 6: Jupyter token takes effect + docs

**Files:**
- Modify: `helm/datapond/templates/jupyter-deployment.yaml:~76-102`, `helm/datapond/templates/backend-deployment.yaml` (env block near AIRFLOW_PASSWORD), `scripts/install.sh:~392`, `docs/AWS_MVP_RUNBOOK.md`

**Interfaces:**
- Consumes: `datapond-secrets/JUPYTER_TOKEN` from Task 4; `_jupyter_token()` backend read from Task 3.

- [ ] **Step 1: jupyter-deployment.yaml command.** The startup is a shell script block; change the hardcoded token to shell env expansion (quoted):

```
          exec start-notebook.sh --NotebookApp.token="${JUPYTER_TOKEN}" --NotebookApp.base_url=/jupyter --NotebookApp.allow_origin='*'
```

and add to the container env (before the `{{- range .Values.jupyter.env }}` block):

```yaml
        - name: JUPYTER_TOKEN
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: JUPYTER_TOKEN
```

- [ ] **Step 2: backend-deployment.yaml** — backend's notebooks proxy needs the token; add next to the AIRFLOW_PASSWORD env:

```yaml
        - name: JUPYTER_TOKEN
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: JUPYTER_TOKEN
              optional: true
```

- [ ] **Step 3: install.sh** — replace the literal `token: jupyter` output line with:

```bash
echo "  JupyterLab token: kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.JUPYTER_TOKEN}' | base64 -d   (quicktest profile: 'jupyter')"
```

- [ ] **Step 4: Runbook** — add to `docs/AWS_MVP_RUNBOOK.md` (near the §7 P0-1a preflight):

```markdown
### Component passwords (P0-1b)
POSTGRES_PASSWORD, MinIO S3_SECRET_KEY, AIRFLOW_PASSWORD, JUPYTER_TOKEN, POLARIS_CLIENT_SECRET
are auto-generated on first install and preserved across upgrades (lookup-preserve).
Retrieve any of them:
    kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.<KEY>}' | base64 -d
⚠️ NEVER delete datapond-secrets while keeping data PVCs: Postgres/MinIO were initialized
with the generated passwords — a regenerated Secret will not match the data volumes and
every component login will fail. Delete the Secret only together with the PVCs (full reset).
Existing installs keep their current passwords (no rotation is performed by upgrades).
```

- [ ] **Step 5: Commit**

```bash
git add helm/datapond/templates/jupyter-deployment.yaml helm/datapond/templates/backend-deployment.yaml scripts/install.sh docs/AWS_MVP_RUNBOOK.md
git commit -m "feat(helm): jupyter token from Secret (was hardcoded 'jupyter') + retrieval docs"
```

---

### Task 7: CI render assertions + PR

**Files:**
- Modify: `.github/workflows/ci.yml` (extend the existing "secrets wired" assertion step, lines ~84-94)

- [ ] **Step 1: extend the helm assertion step** — after the P0-1a assertions (`OK: secrets wired`), add:

```bash
          echo "== component credentials generated (P0-1b) =="
          out=$(helm template datapond helm/datapond)
          for k in POSTGRES_PASSWORD S3_SECRET_KEY AIRFLOW_PASSWORD JUPYTER_TOKEN POLARIS_CLIENT_SECRET; do
            echo "$out" | grep -q "$k:" || { echo "FAIL $k not generated"; exit 1; }
          done
          echo "$out" | grep -q 'token="${JUPYTER_TOKEN}"' || { echo "FAIL jupyter token still hardcoded"; exit 1; }
          echo "== no weak literals in rendered manifests (base/prod/onprem/foundation) =="
          for v in "" "--values helm/datapond/values-prod.yaml" "--values helm/datapond/values-onprem.yaml" "--values helm/datapond/values-foundation.yaml"; do
            r=$(helm template datapond helm/datapond $v)
            if echo "$r" | grep -E 'CHANGE_THIS|changeme|datapond_password|datapond_s3_password'; then
              echo "FAIL: weak credential literal rendered (profile: ${v:-base})"; exit 1
            fi
            if echo "$r" | grep -q 'AIRFLOW_PASSWORD: "airflow"'; then
              echo "FAIL: weak airflow password rendered (profile: ${v:-base})"; exit 1
            fi
          done
          echo "OK: component credentials wired"
```

(quicktest/dev are intentionally excluded — they keep known dev creds by design.)

- [ ] **Step 2: full local test pass** — `cd backend && python3 -m pytest tests/ -q` → all green (CI py3.11 remains authoritative for the connectors chain).

- [ ] **Step 3: branch, push, PR**

```bash
git checkout -b feat/secrets-hardening-p0b   # if not already on it
git push -u origin feat/secrets-hardening-p0b
gh pr create --title "feat(security): component-credential hardening — generate, fail-closed, no plaintext manifests (P0-1b)" --body "..."
```

PR body summarizes: component_secret() call-time guard, lookup-preserve generation for 5 credential families, secretKeyRef/\$(VAR) conversion (no plaintext in pod manifests), jupyter token fix, values blanking (quicktest/dev keep dev creds), no rotation of existing installs. CI must be fully green (helm render assertions + backend pytest) before merge.

- [ ] **Step 4: fix any CI failures; done only when green.**

---

## Self-Review

**Spec coverage:** §3 backend guard → Tasks 1-3 (all call sites from the spec table, incl. laziness rule). §4 generation + values → Task 4 (incl. `$existing` hoist, MinIO single-resolution, values-prod placeholder removal, dead mlflow password removal). §5 leaks → Task 5 (spec said "render conn strings into the Secret"; plan uses the `$(VAR)`/shell-expansion pattern already established by backend `DATABASE_URL` + mlflow — same guarantee (no plaintext in manifests), less machinery; polaris config leak resolved by deleting the dead unreferenced `polaris-secret`). §6 jupyter → Task 6. §7 migration/runbook → Task 6 Step 4. §8 tests/CI → Tasks 1, 7.

**Type consistency:** `component_secret(env_var, dev_default, component="")` uniform across Tasks 1-3; `_airflow_auth()` / `_jupyter_token()` defined and consumed within Task 3; Secret key names identical between Task 4 (producers) and Tasks 5-6 (consumers).

**Placeholder scan:** grep-then-replace steps (Task 3) name the exact search commands and exact replacement code — usage sites vary but the transformation is fully specified. No TBDs.
