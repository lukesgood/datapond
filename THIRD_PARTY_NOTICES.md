# Third-Party Notices

DataPond's own code is licensed under Apache-2.0 (see [LICENSE](LICENSE)), except
`/ee` (see [ee/LICENSE](ee/LICENSE)). This file inventories the third-party software
DataPond depends on or deploys, grouped by how it is bundled. Inventory audited
2026-07-07 against `helm/datapond/values.yaml`, `backend/requirements.txt`, and
`frontend/package.json`.

## ⚠️ Copyleft & source-available components

The following deployed components carry non-permissive licenses. DataPond does NOT
link against, modify, or redistribute them — they are unmodified upstream container
images pulled at deploy time and operated by the deploying customer (aggregation,
not derivation). Their licenses govern those components, not DataPond's code.

| Component | License | Where it applies |
|---|---|---|
| MinIO (`minio/minio`, `minio/mc`) | **AGPL-3.0** | Any profile with minio.enabled (onprem / dev / quicktest / prod) — base, foundation, and aws profiles use native Amazon S3 and pull no MinIO image |
| Elasticsearch 8.x (via OpenMetadata) | **Elastic License 2.0 / SSPL** (source-available, not OSI open source) | Profiles with OpenMetadata enabled — the base chart default is ENABLED, and values-aws inherits it; disabled in the foundation profile. Set openmetadata.enabled: false if ELv2 is a procurement blocker |
| BusyBox (init containers) | GPL-2.0 | Unmodified standalone utility image (mere aggregation) |

**Procurement note for regulated environments:** the foundation profile
(`values-foundation.yaml`) deploys neither MinIO nor Elasticsearch. `values-aws.yaml`
deploys no MinIO but inherits OpenMetadata (and its Elasticsearch) from base defaults —
set `openmetadata.enabled: false` there if ELv2 is a blocker.

## 1. Deployed container images

| Image | Project | License |
|---|---|---|
| `pgvector/pgvector:0.8.4-pg16`, `postgres:16.14-alpine` | PostgreSQL + pgvector | PostgreSQL License |
| `valkey/valkey:7.2.5` | Valkey | BSD-3-Clause |
| `trinodb/trino:482` | Trino | Apache-2.0 |
| `apache/spark:3.5.8-python3` | Apache Spark | Apache-2.0 |
| `apache/airflow:2.8.1` | Apache Airflow | Apache-2.0 |
| `ghcr.io/mlflow/mlflow:v2.10.0` | MLflow | Apache-2.0 |
| `apache/polaris:1.4.0`, `apache/polaris-admin-tool` | Apache Polaris | Apache-2.0 |
| `risingwavelabs/risingwave:v1.7.0` | RisingWave (core) | Apache-2.0 |
| `openmetadata/server:1.3.1` | OpenMetadata | Apache-2.0 |
| `ghcr.io/berriai/litellm:v1.91.0` | LiteLLM | MIT |
| `ollama/ollama:0.31.1` | Ollama | MIT |
| `vllm/vllm-openai:v0.24.0` | vLLM | Apache-2.0 |
| `quay.io/jupyter/scipy-notebook:2026-07-06` (base of `datapond/jupyter`) | Jupyter Docker Stacks | BSD-3-Clause (bundles a broad BSD/PSF/Apache scientific-Python stack) |
| `curlimages/curl:8.10.1` | curl | curl license (MIT/X-style) |
| `minio/minio:RELEASE.2025-09-07T16-13-09Z`, `minio/mc:RELEASE.2025-08-13T08-35-41Z` | MinIO | AGPL-3.0 (see callout above) |
| `docker.elastic.co/elasticsearch/elasticsearch:8.10.2` | Elasticsearch | ELv2 / SSPL (see callout above) |
| `busybox:1.36.1` | BusyBox | GPL-2.0 (see callout above) |

The `datapond/jupyter` image additionally installs: duckdb (MIT), pyiceberg (Apache-2.0),
boto3 (Apache-2.0), pandas (BSD-3-Clause), matplotlib (Matplotlib License, BSD-style),
seaborn (BSD-3-Clause), plotly (MIT), scikit-learn (BSD-3-Clause), xgboost (Apache-2.0),
lightgbm (MIT).

## 2. Backend Python dependencies (`backend/requirements.txt`)

| Package | License |
|---|---|
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| httpx | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| **psycopg2-binary** | **LGPL-3.0 (with exceptions)** — weak copyleft; used as an unmodified dynamically-imported library; attribution here satisfies its terms for this usage |
| sqlalchemy | MIT |
| redis (redis-py) | MIT |
| kubernetes | Apache-2.0 |
| trino (client) | Apache-2.0 |
| sqlglot | MIT |
| mlflow-skinny | Apache-2.0 |
| asyncpg | Apache-2.0 |
| pymysql | MIT |
| boto3 | Apache-2.0 |
| pandas | BSD-3-Clause |
| pyiceberg[pyarrow] | Apache-2.0 |
| pyarrow | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause (dual) |
| jinja2 | BSD-3-Clause |
| python-jose | MIT |
| bcrypt | Apache-2.0 |
| anthropic | MIT |
| **ldap3** | **LGPL-3.0** — weak copyleft; unmodified library usage; attribution here satisfies its terms for this usage |

## 3. Frontend npm dependencies (`frontend/package.json`, production)

All MIT unless noted: @base-ui/react, @monaco-editor/react, @types/dagre, clsx, dagre,
date-fns, next, react, react-dom, reactflow, recharts, shadcn, tailwind-merge,
tw-animate-css. Exceptions:

| Package | License |
|---|---|
| class-variance-authority | Apache-2.0 |
| lucide-react | ISC (Lucide License) |
| **elkjs** | **EPL-2.0** — weak copyleft; consumed as an unmodified npm package; source available upstream at https://github.com/kieler/elkjs |

The CI license gate also scans production-TRANSITIVE npm packages; two carry reviewed
weak-copyleft licenses and are allowlisted:

| Package (transitive) | License | Review |
|---|---|---|
| `@img/sharp-libvips-*` | LGPL-3.0-or-later | Prebuilt libvips binaries pulled in by Next.js/sharp image optimization; dynamically linked, unmodified |
| `dompurify` | MPL-2.0 OR Apache-2.0 (dual) | Apache-2.0 elected |

## 4. Vendored source

`frontend/components/ui/*.tsx` are shadcn/ui components, copied into the repo by design
(shadcn's distribution model is copy-not-install). shadcn/ui is MIT-licensed:

```
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

No other third-party source is vendored in this repository.

---
Image tags are pinned to specific versions (P0-4); they are bumped deliberately, never
floating. See helm/datapond/values.yaml and the Dockerfiles for the authoritative tags.
