# Local development and tests

The backend test suite runs on Python 3.11+ with every package in `backend/requirements.txt`
installed. A system interpreter usually lacks some of them (Homebrew's Python refuses `pip install`
outside a virtual environment, PEP 668), and a missing package shows up as test failures that look
like product bugs — `tests/test_webauthn.py` fails with `ModuleNotFoundError: No module named
'webauthn'` when the `webauthn` package is absent, although the code and CI are fine.

## Backend

```bash
cd backend
python3.12 -m venv .venv                       # or python3.11
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests -q --ignore=tests/acceptance
```

`.venv/` is git-ignored. `tests/acceptance` needs a live deployment and is excluded from the unit run;
CI runs it in its own job. There is no database in the unit tests: every test uses fake pools, and
migrations are checked as SQL text.

Some backend tests parse frontend and Helm files (`tests/test_dashboard_workflow_matches_nav.py`,
`tests/test_helm_*.py`, `tests/test_service_registry.py`). Run the backend suite after a
frontend-only or chart-only change too; CI does, on every pull request.

## Frontend

```bash
cd frontend
npm install
npm test          # node --test lib/**/*.test.ts — pure logic under frontend/lib only
npm run lint
npm run build
```

## Helm

```bash
helm lint helm/datapond --values helm/datapond/values-quicktest.yaml
helm template datapond helm/datapond --values helm/datapond/values-foundation.yaml | grep '^kind:' | sort | uniq -c
```

`backend/tests/test_helm_*.py` render every profile offline and pin which workloads each one
produces; a new `values-*.yaml` must be added to `PROFILE_EXPECTATIONS` in
`tests/test_helm_addon_defaults.py` or that suite fails.
