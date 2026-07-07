# Secrets Hardening P0-b: Component Credentials — Design

**Date**: 2026-07-07
**Status**: Design approved (pre-implementation)
**Predecessor**: P0-1a (PR #106) — ENCRYPTION_KEY / JWT_SECRET / ADMIN_PASSWORD fail-closed + Helm lookup-preserve generation
**Scope decision**: All three layers in ONE PR — (1) password generation + backend guards, (2) inline plaintext `value:` → `secretKeyRef`, (3) Jupyter hardcoded-token fix.

## 1. Problem

P0-1a hardened the three critical backend secrets. Component credentials remain weak in three distinct ways:

1. **Weak/placeholder defaults** — `datapond_password`, `changeme`, `airflow`, `changeme-polaris-secret`, `admin/admin`, and seven `CHANGE_THIS_*` placeholders in `values-prod.yaml`. Backend mirrors each with weak `os.getenv` defaults; `LITELLM_MASTER_KEY` falls back to `""`, which makes the backend call the LiteLLM gateway **unauthenticated**.
2. **Plaintext in pod manifests** — several templates render passwords inline as env `value:` (visible via `kubectl get pod -o yaml`), bypassing the Secret: postgres password inside connection strings (`airflow-deployment.yaml:42,56,143`, `backend-deployment.yaml:104`), `AIRFLOW_PASSWORD` (`backend-deployment.yaml:133`), Polaris clientSecret (backend env, catalog-init-job, bootstrap-job command arg, polaris server config), Langfuse secret key, vLLM HF token.
3. **Jupyter token hardcoded in the container command** — `jupyter-deployment.yaml:76` `--NotebookApp.token=jupyter`. The `JUPYTER_TOKEN` values entries are decorative; a generated secret takes no effect until the command reads it.

## 2. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Scope | All three layers in one PR |
| Backend guard | **Call-time** `component_secret()` helper (Approach B) — NOT import-time; optional components must not crash startup |
| Fail-closed policy | Production only (`ENVIRONMENT=production`, via existing `runtime.is_production()`); dev/CI warn + known dev default |
| Dev profiles | `values-quicktest.yaml` / `values-dev.yaml` KEEP known dev creds (explicit-wins); base / prod / onprem / foundation / aws → `""` ⇒ generated |
| Rotation | None in this PR — lookup-preserve keeps existing installs on current passwords |
| MinIO rootUser | Stays values-driven (identity, not secret; default `datapond`); only the root password / secret key is generated |
| OpenMetadata admin | NOT generated (OM manages its own internal admin password; generating ours would desync backend↔OM auth). Values-driven + backend guard only |
| Grafana admin | Blank in values + comment (no consuming template exists) |

## 3. Backend: `component_secret()` guard

Add to `backend/app/runtime.py` (beside `is_production()`):

```python
def component_secret(env_var: str, dev_default: str, component: str = "") -> str:
    """Read a component credential from the environment.
    Production: raise RuntimeError if unset (fail-closed).
    Dev/CI: logger.warning ONCE per env var, return dev_default."""
```

Semantics:
- Production + unset → `RuntimeError(f"{env_var} is required in production" ...)` at the **call site** — surfaces as a clear 500 on the affected endpoint, not a startup crash of unrelated features.
- Dev + unset → warn once (module-level seen-set), return `dev_default` — CI pytest and local dev keep working.
- Empty string counts as unset (kills the `LITELLM_MASTER_KEY=""` unauthenticated path).

### Call sites to convert (weak default → `component_secret`)

| Credential | Files (current weak default) |
|---|---|
| `POSTGRES_PASSWORD` | `app/database/connection.py:16` (`datapond`); `app/api/auth.py:82`, `app/rls/loader.py:34`, `app/api/connectors.py:287,658,673,768` (`dev_password`) |
| `S3_ACCESS_KEY`/`S3_SECRET_KEY` | `app/connectors/iceberg_catalog.py:35-36`, `app/api/streaming.py:256-257,372-373` (`datapond`/`datapond_dev`) |
| `AIRFLOW_PASSWORD` | `app/api/transforms.py:30`, `app/api/airflow.py:17`, `app/api/pipelines.py:266,338` (`airflow`) |
| `JUPYTER_TOKEN` | `app/api/notebooks.py:16` (`jupyter`) |
| `OPENMETADATA_PASSWORD` | `app/api/om_util.py:19` (`admin`) |
| `POLARIS_CLIENT_SECRET` | `app/connectors/iceberg_catalog.py:25`, `app/api/polaris_client.py:16` (`changeme-polaris-secret`) |
| `LITELLM_MASTER_KEY` | `app/api/ai_sql.py:47`, `app/api/ai_vectors.py:50`, `app/api/ai_backends.py:81` (`""` → unauthenticated) |

**Laziness rule**: credential reads for optional components (airflow, polaris, openmetadata, jupyter, litellm, s3-dependent paths) must execute inside the request/call path, not at module import. Any site currently evaluated at module level moves into the function. Postgres is core: its read may stay at startup — failing closed at boot in prod when unset is correct, and Helm always injects it.

Dev defaults passed to `component_secret` are the current documented dev values (`dev_password`, `datapond`/`datapond_dev`, `airflow`, `jupyter`, `admin`, `changeme-polaris-secret`) so quicktest/dev behavior is unchanged. For `LITELLM_MASTER_KEY` the dev fallback keeps today's no-auth-header behavior (dev gateway runs without auth) — but ONLY in dev.

## 4. Helm: extend lookup-preserve generation (`templates/secrets.yaml`)

Same chain as P0-1a per key: explicit values → existing secret (`lookup` + `b64dec`) → `randAlphaNum`.

| Secret key | Source values | Generated length | Notes |
|---|---|---|---|
| `POSTGRES_PASSWORD` | `postgres.auth.password` | 24 | replaces `\| default "changeme"` |
| `S3_SECRET_KEY` / `SEAWEEDFS_S3_PASSWORD` / MinIO root password | `minio.auth.rootPassword` | 32 | `S3_ACCESS_KEY`/rootUser stays values-driven (`datapond`) |
| `AIRFLOW_PASSWORD` | `airflow.auth.password` | 20 | replaces `\| default "airflow"` |
| `JUPYTER_TOKEN` | jupyter values entry (see §6) | 32 | new key in `datapond-secrets` |
| `POLARIS_CLIENT_SECRET` | `polaris.auth.clientSecret` | 32 | new key — currently not in the Secret at all |

Derived connection strings rendered into the Secret (password already resolved in scope): `DATABASE_URL` (backend), Airflow `SQL_ALCHEMY_CONN` (+ its result-backend variant if present). `OPENMETADATA_*` / `LDAP_BIND_PASSWORD` keep their existing `with`-guarded behavior. Add `with`-guarded entries for `LANGFUSE_SECRET_KEY` (+ public key for symmetry) and `HF_TOKEN`.

### Values changes
- `values.yaml` (base), `values-prod.yaml`, `values-onprem.yaml`, `values-foundation.yaml`, `values-aws.yaml`: the credentials above become `""` with a comment `# empty ⇒ Helm generates & preserves (kubectl -n datapond get secret datapond-secrets ...)`. All seven `CHANGE_THIS_*` in values-prod removed — password/token fields become `""` (⇒ generated); `rootUser: CHANGE_THIS_MINIO_USER` reverts to the identity default `datapond` (override freely; usernames are not generated). Grafana `adminPassword` blanked + comment.
- `values-quicktest.yaml`, `values-dev.yaml`: unchanged known dev creds (explicit-wins keeps local flows and the CLAUDE.md URL/credential table valid).
- Remove the duplicate second postgres password block (`values.yaml:247`, mlflow section) if it is dead config; otherwise point it at the same source.

## 5. Kill plaintext-in-manifest leaks (→ `secretKeyRef` / Secret mounts)

| Leak | Fix |
|---|---|
| `backend-deployment.yaml:104` `DATABASE_URL` inline | `secretKeyRef` → `datapond-secrets/DATABASE_URL` |
| `airflow-deployment.yaml:42,56,143` conn strings inline | `secretKeyRef` → rendered conn-string keys in `datapond-secrets` |
| `backend-deployment.yaml:133` `AIRFLOW_PASSWORD` inline | `secretKeyRef` |
| `backend-deployment.yaml:115-116`, `polaris-catalog-init-job.yaml:40-41` `POLARIS_CLIENT_SECRET` inline | `secretKeyRef` |
| `polaris-bootstrap-job.yaml:99` secret in command arg | env from `secretKeyRef` + `$(VAR)` expansion in args |
| `polaris-deployment.yaml:206` clientSecret in rendered config | move the config from ConfigMap to a **Secret** mount (checksum annotation preserved) |
| `litellm-deployment.yaml:157-159` Langfuse keys inline | `with`-guarded `secretKeyRef` |
| `vllm-deployment.yaml:49-50` HF token inline | `with`-guarded `secretKeyRef` |

`openmetadata-deployment.yaml:200-203` `ELASTICSEARCH_PASSWORD value: ""` is an empty literal, not a leak — leave as is.

## 6. Jupyter token fix

- `jupyter-deployment.yaml` command: `--NotebookApp.token=jupyter` → `--NotebookApp.token=$(JUPYTER_TOKEN)`; add `JUPYTER_TOKEN` env via `secretKeyRef` (K8s expands `$(VAR)` in command/args).
- The generic `jupyter.env` passthrough entry for `JUPYTER_TOKEN` becomes the explicit-wins source (quicktest/dev keep token `jupyter`); other profiles blank ⇒ generated.
- `scripts/install.sh:392` and docs: for generated profiles print/document `kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.JUPYTER_TOKEN}' | base64 -d` instead of the literal token.

## 7. Migration & rotation safety

- **No rotation**: upgrades of existing installs hit the `lookup` branch and keep the current (possibly weak) passwords — Postgres/Airflow/MinIO state was initialized with them and keeps working. Strong passwords apply to fresh installs (or explicit values).
- **Runbook caveat** (add to `docs/AWS_MVP_RUNBOOK.md` §7 area): deleting `datapond-secrets` while keeping PVCs desyncs generated passwords from Postgres/MinIO state → auth failures. Same preflight class as P0-1a: never delete the secret independent of the data volumes.
- Live EC2 tar-sync deployment: env comes from Helm, so lookup-preserve protects it; no manual seeding needed for these keys (unlike P0-1a ENCRYPTION_KEY).
- **POLARIS_CLIENT_SECRET upgrade preservation**: Polaris persists the client secret server-side in its DB at bootstrap (the bootstrap job skips re-provisioning on upgrade), and pre-branch installs never stored it in `datapond-secrets`. The `$psec` resolution therefore has a legacy tier: explicit value → `datapond-secrets` lookup → **legacy standalone `polaris-secret` lookup (key `clientSecret`, still in-cluster at first-upgrade render time)** → random. Without the legacy tier, first upgrade would mint a new random and desync all catalog OAuth (cluster-wide 401s). After the first upgrade the value lives in `datapond-secrets`, so the legacy tier never fires again.
- **JUPYTER_TOKEN intentionally rotates on first upgrade** for installs that used the old env-list token: Jupyter token auth is stateless (no data initialized with it), so rotation is safe — retrieve the new token via the kubectl command in the runbook. quicktest/dev profiles keep `jupyter` explicitly via values.

## 8. Testing & CI

- **pytest** (locally runnable): `backend/tests/test_component_secret.py` — prod-raise, dev-default, empty-string-counts-as-unset, warn-once; plus no regressions in the existing suite (CI py3.11 authoritative).
- **CI helm render assertions** (helm not installed locally):
  - all new secret keys present in rendered `datapond-secrets`;
  - `CHANGE_THIS`, `changeme`, `datapond_password` appear NOWHERE in rendered manifests (default render + prod/onprem/foundation values);
  - no password-bearing inline env `value:` remains (grep the known patterns);
  - jupyter command contains `$(JUPYTER_TOKEN)`.
- Error-handling behavior: prod missing credential for an enabled component → RuntimeError at call site → clear 500; disabled component → code path never runs; dev → warn once + dev default.

## 9. Out of scope

Password rotation tooling, Valkey/Redis auth (currently none), SSO (P0-3), OpenMetadata server-side admin password management, image-tag pinning (P0-4), external secret managers (ESO/Vault).
