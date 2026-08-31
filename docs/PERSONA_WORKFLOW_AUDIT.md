# 역할별 페르소나 및 실제 업무 기능 점검

> 점검일: 2026-08-25  
> 기준: 현재 working tree의 `README.md`, `docs/PRODUCT_CONCEPT.md`, `backend/app/permissions.py`, Backend API, Frontend UI, 기존 테스트  
> 범위: 정적 코드 대조와 로컬 테스트. 라이브 Kubernetes, AWS, Bedrock, Athena, Trino, Jupyter, MLflow에 대한 실제 통합 호출은 포함하지 않는다.

## 1. 결론

DataPond에는 7개 역할과 역할별 permission matrix가 존재하며, Knowledge ACL, 주요 connector write, capability-gated navigation 같은 일부 경계는 구현·테스트되어 있다. 그러나 **역할별 실제 업무가 end-to-end로 정상 동작한다고 승인할 수는 없다.**

주요 이유는 다음과 같다.

1. Pipeline validate/compile이 제출된 Python의 top-level code를 backend 프로세스에서 실행하며, 해당 router는 permission과 capability gate가 없다. 모든 인증 역할이 backend 권한으로 코드를 실행할 수 있다.
2. `viewer`가 임의 SQL과 optional workload mutation을 수행할 수 있어 read-only 계약이 성립하지 않는다.
3. Knowledge inline ingest, Search, RAG가 `ai:generate` 없이 embedding/rerank/chat 비용을 발생시킨다.
4. `auditor`의 필수 policy/audit/spend read와 `ai_engineer`의 spend read는 permission matrix에는 있으나 실제 endpoint는 admin-only다.
5. `ai_engineer`가 collection은 만들 수 있지만 S3/Iceberg source ingest와 freshness schedule은 admin-only라 대표 업무 흐름이 끊긴다.
6. 서비스 계정 API가 `admin` role 입력을 허용하고, `require_admin`은 API key의 effective scopes를 보지 않아 사람 전용 관리 경계를 우회할 수 있다.
7. 프론트엔드는 사이드바만 permission-aware이며 페이지 액션과 direct route는 대부분 역할을 반영하지 않는다. 사용자 관리 UI도 7개 역할 중 `admin/viewer`만 지원한다.

따라서 현재 판정은 **기능 존재: 부분 충족 / 역할별 정상 동작과 격리: 실패**다. 특히 P0 항목을 해소하기 전에는 `viewer read-only`, `scoped service account`, `per-role AI spend governance`를 제품 보장으로 주장하면 안 된다.

## 2. 판정 기준

- **가능**: 대표 업무를 완료할 수 있고, 허용/거부 경계가 API에서 강제되며 관련 테스트가 있다.
- **부분**: 업무 자체는 일부 가능하지만 단계가 끊기거나 다른 역할에도 동일 작업이 열려 있어 역할 경계를 신뢰할 수 없다.
- **불가**: 핵심 JTBD를 완료하지 못하거나 역할의 안전 조건을 위반한다.
- Optional workflow는 runtime capability가 활성화된 프로필에서만 평가한다. 비활성 기능이 보이지 않는 것은 결함이 아니다.
- 메뉴 숨김은 UX일 뿐 권한 통제가 아니다. 최종 판정은 API dependency와 side effect 선차단 여부를 기준으로 한다.

## 3. 역할별 페르소나와 acceptance 시나리오

### 3.1 플랫폼 관리자 — `admin` / 민지

- **상황:** 소규모 플랫폼 팀에서 DataPond 배포, 사용자, 모델 provider, 거버넌스, 인프라를 운영한다.
- **JTBD:** 사용자를 올바른 역할로 배정하고, 모델·비용·정책·서비스 상태를 안전하게 관리한다.
- **필수 기능:** 사용자/역할 관리, service account, AI backend/key/budget, governance policy, storage/service 운영, audit 확인.
- **최소 acceptance:** 7개 역할을 생성·변경 → 역할별 메뉴/API 경계 확인 → 모델과 budget 구성 → audit에서 변경 주체 확인 → non-admin 및 scoped key의 관리 API 거부 확인.
- **판정: 부분.** 관리 API 대부분은 존재하지만 UI는 `admin/viewer`만 배정할 수 있고, admin-role service account가 `require_admin` 경계를 통과할 수 있다.

### 3.2 데이터 파이프라인 엔지니어 — `data_engineer` / 현우

- **상황:** 원천 DB/S3 데이터를 수집하고 품질·스케줄·파이프라인을 운영한다.
- **JTBD:** source를 연결하고 반복 sync와 transform/streaming workload를 안전하게 운영해 downstream 사용자가 신뢰할 데이터를 받게 한다.
- **필수 기능:** connector 조회/생성/수정/sync, catalog 확인, bounded query, pipeline/transform/streaming 배포·실행·모니터링, 실패 재시도.
- **최소 acceptance:** connector 생성 → 연결 테스트 → table 선택 → sync/schedule → catalog 확인 → pipeline 실행 → run/log/quality 확인. viewer와 analyst의 동일 mutation은 side effect 전에 403이어야 한다.
- **판정: 부분.** 주요 connector write에는 `connector:write`가 적용되지만 pipeline, transform, streaming, Airflow mutation은 역할 검사 없이 인증 사용자에게 열려 있다. 더 심각하게 Pipeline validate/compile은 제출된 Python top-level code를 backend에서 실행한다. 기능 수행은 가능해도 `data_engineer` 역할과 capability 경계가 강제되지 않는다.

### 3.3 RAG/에이전트 엔지니어 — `ai_engineer` / 서연

- **상황:** RAG/agent 애플리케이션을 PoC에서 운영으로 옮기며 ingestion, retrieval, citation, 비용을 함께 관리한다.
- **JTBD:** collection을 만들고 text/S3/table source를 적재·갱신한 뒤 Search/RAG 품질과 사용자별 spend를 검증한다.
- **필수 기능:** collection lifecycle, inline/source ingest, freshness schedule, PII masking, semantic search, cited RAG, AI SQL, spend read, scoped service account.
- **최소 acceptance:** collection 생성 → text 및 S3/table ingest → schedule 설정 → Search → cited RAG → PII 확인 → 자신의 앱 사용량/spend 확인 → collection 삭제.
- **판정: 부분.** collection create/delete와 AI SQL permission은 맞지만 source ingest와 schedule은 admin-only다. spend read permission은 선언되어도 endpoint와 UI는 admin-only다. Search/RAG의 비용 permission도 누락됐다.

### 3.4 데이터 사이언티스트 — `data_scientist` / 지훈

- **상황:** SQL과 notebook으로 데이터를 탐색하고 실험·모델 결과를 추적하며 재현 가능한 분석을 만든다.
- **JTBD:** governed data를 분석하고 실험·모델·dashboard 결과를 팀과 공유한다.
- **필수 기능:** query, Knowledge/RAG, notebook/kernel/session, MLflow experiment/run/model registry, dashboard.
- **최소 acceptance:** bounded query → notebook으로 열기 → experiment/run 기록 → 결과 비교 → model stage 요청 → dashboard 저장. viewer의 create/update/delete/kernel/model-stage는 403이어야 한다.
- **판정: 부분.** UI와 API 기능은 존재하지만 notebook/experiment permission vocabulary가 없고 대부분의 mutation이 인증만 요구한다. Pipeline Python 실행 경로도 모든 인증 역할에 열려 있다. `data_scientist`의 고유 업무 경계를 표현하거나 검증할 수 없다.

### 3.5 비즈니스 분석가 — `business_analyst` / 유나

- **상황:** 승인된 데이터로 반복 질의를 실행하고 dashboard를 작성한다.
- **JTBD:** 원본 플랫폼을 변경하지 않고 SELECT 결과를 시각화·공유한다.
- **필수 기능:** catalog read, SELECT-only query, 자신의 history, dashboard create/update/delete, RLS/masking 결과.
- **최소 acceptance:** catalog 탐색 → SELECT 실행 → mask/RLS 확인 → chart 구성 → dashboard 저장/수정. DDL/DML, connector/pipeline/Knowledge mutation, model spend는 거부되어야 한다.
- **판정: 부분.** query와 dashboard 업무는 가능하지만 `/queries/execute`가 SELECT-only가 아니며 dashboard PATCH도 `dashboard:write`를 확인하지 않는다. 업무 기능은 있으나 안전 조건이 실패한다.

### 3.6 보안·컴플라이언스 감사자 — `auditor` / 도윤

- **상황:** 운영 변경 권한 없이 정책, audit, PII, model spend와 enforcement 결과를 검토한다.
- **JTBD:** 누가 무엇을 실행·변경했는지 확인하고 RLS/masking과 비용 통제가 실제로 적용되는지 재현한다.
- **필수 기능:** governance/audit/spend read, policy preview, read-only verification query, report export. 모든 mutation은 금지.
- **최소 acceptance:** policy 목록 → audit stream → PII report → spend report → masked SELECT 검증. policy/settings/workload mutation은 모두 403이어야 한다.
- **판정: 불가.** permission matrix에는 `governance:read`, `audit:read`, `spend:read`가 있지만, 실제로 필요한 policy 목록·preview, audit log/stream, spend endpoint는 admin-only다. stats와 PII report만 인증 read로 열려 있어 감사 업무 전체를 완료할 수 없다.

### 3.7 읽기 전용 소비자 — `viewer` / 소라

- **상황:** 승인된 catalog, collection, query 결과를 조회하되 데이터·설정·비용을 변경하지 않는다.
- **JTBD:** 안전하게 정보를 소비하고 실수나 자격 증명 탈취가 write 또는 비용 폭증으로 이어지지 않게 한다.
- **필수 기능:** catalog/collection metadata read, 허용 범위의 SELECT, 자신의 history. 모든 mutation과 model-token action은 금지.
- **최소 acceptance:** catalog/collection 목록과 SELECT는 성공하고, DDL/DML, connector/pipeline/streaming/notebook/experiment/dashboard/Knowledge mutation, Search/RAG/AI SQL은 side effect 전에 403이어야 한다.
- **판정: 불가.** 읽기는 가능하지만 backend Python code 실행, 임의 SQL, optional workload mutation, Search/RAG 비용 발생 경로가 열려 있어 read-only 격리가 성립하지 않는다.

## 4. 기능·권한·UI·테스트 대조

| 도메인 | 구현 | API 권한 | UI 권한 | 기존 테스트 | 판정 |
|---|---|---|---|---|---|
| 역할 매트릭스 | 7 roles, 16 permissions | `require_permission` factory 존재 | `/api/me/permissions` 사용 | pure matrix/guard 테스트 있음 | 기반은 있음 |
| 사용자 역할 관리 | API는 7 roles 허용 | admin-only | `admin/viewer`만 생성·toggle | API validation 일부 | 불일치 |
| Knowledge collection | create/list/delete, owner/shared ACL | create/delete `knowledge:write`; ACL owner/admin/shared | role 대신 owner/admin 중심 | ACL negative tests 있음 | 부분 양호 |
| Knowledge ingest | inline, S3, Iceberg, schedule | inline/delete schedule은 permission 누락; source/schedule create는 admin-only | source/schedule admin UI | ingestion unit tests | 역할 흐름 불일치 |
| Search/RAG | embedding, optional rerank, citation, PII | `ai:generate` 누락 | 모든 역할에 화면/액션 노출 | 비용 권한 negative test 없음 | 실패 |
| AI SQL | model SQL generation | `ai:generate` 적용 | query 화면 버튼은 permission 미반영 | endpoint tests 있음 | API는 양호, UX 부분 |
| Connector | CRUD/sync/schedule | 주요 9개 write route에 `connector:write` | sidebar gate | integrity/security tests 일부 | 상대적으로 양호 |
| Query | Trino/Athena, RLS rewrite, history | `query:run` dependency 없음; statement type 제한 없음 | query capability + sidebar permission | engine/RLS tests, role route tests 없음 | 실패 |
| Dashboard | create/read/update/delete | create/delete만 `dashboard:write`; update는 owner/admin | save 액션 permission 미반영 | owner tests 제한적 | 부분 |
| Pipeline/Transform/Airflow | 배포·실행·삭제 API | `pipeline:write` 미적용 | sidebar만 gate | 기능/보안 단편 테스트 | 실패 |
| Streaming | source/view/sink/CDC/raw SQL | `pipeline:write` 미적용 | sidebar만 gate | S3 config 중심 | 실패 |
| Notebook | 파일/kernel/session CRUD | 관련 permission 없음 | capability만 gate | path/upload security 중심 | 실패 |
| MLflow | experiment/run/model API | delete/archive만 admin; 기타 mutation auth-only | capability 및 일부 admin UI | integration 단편 테스트 | 실패 |
| Governance/Audit | stats, PII, policy, mask, audit stream | stats/PII는 인증 read; 필수 policy/audit read는 admin-only | auditor는 메뉴는 보이나 핵심 API 실패 | 일부 non-admin 거부를 현재 계약으로 고정 | 역할 계약 실패 |
| Spend | summary/usage/report/alerts | 전부 admin-only | AI Gateway는 `settings:write` 필요 | non-admin read acceptance 없음 | 역할 계약 실패 |
| Storage/Services/Settings | 운영 API | 주요 mutation admin-only | 다수 페이지가 local token role 사용 | admin boundary tests 있음 | 부분 양호 |
| Capability gating | profile별 optional UI/API | 일부 router만 component/capability guard; Airflow/Pipelines/Transforms 누락 | direct route capability gate | capability 계산/UI tests 중심 | API 경계 실패 |

## 5. 우선순위별 발견 사항

### P0-1. viewer read-only를 깨는 임의 SQL 실행

- `backend/app/permissions.py:76-78`은 viewer에게 `query:run`을 주면서 write permission은 주지 않는다.
- `backend/tests/test_permissions.py:74-83`은 viewer가 아무 write도 못 한다는 계약을 테스트한다.
- 그러나 `backend/app/api/queries.py:192-257`의 `/queries/execute`는 `require_user`만 사용하고 statement가 SELECT인지 검사하지 않는다.
- `backend/app/api/query_engine.py:17-29,62-80`은 전달받은 SQL을 그대로 Trino/Athena에 실행한다.
- `add_limit_to_query`는 SELECT에 LIMIT만 붙이며 DDL/DML을 거부하지 않는다.

**영향:** engine/IAM이 허용하는 경우 viewer, auditor, analyst가 INSERT/UPDATE/DELETE/DDL을 실행할 수 있다. `query:run`을 최소 `query:select`와 별도 write/admin permission으로 분리하고 AST 기반 single-statement SELECT allowlist를 적용해야 한다.

### P0-2. Pipeline validate/compile을 통한 인증 사용자 임의 backend Python 실행

- `/pipelines/validate`와 `/pipelines/compile`은 요청의 Python code를 임시 파일로 저장해 `PipelineCompiler`에 넘긴다(`backend/app/api/pipelines.py:137-236`).
- compiler는 `spec.loader.exec_module(module)`로 모듈을 import하므로 제출된 top-level code가 backend 프로세스 권한으로 실행된다(`backend/app/pipelines/compiler.py:122-139`).
- `pipelines_router`에는 `pipeline:write`뿐 아니라 component/capability dependency도 없다(`backend/main.py:273-281`). 따라서 Airflow가 없는 Portable Core에서도 전역 인증만 통과하면 호출할 수 있다.
- 안전한 임시 marker smoke test에서 `top_level_code_executed=True`가 재현됐다. pipeline 정의가 유효하지 않아 `validation_success=False`여도 code는 이미 실행됐다.

**영향:** viewer, auditor, business analyst 등 모든 인증 역할이 backend pod의 파일·네트워크·credential 권한으로 Python을 실행할 수 있다. Pipeline API를 즉시 비활성화하거나 admin/data_engineer permission 및 capability 뒤로 이동하는 것만으로는 충분하지 않으며, 제출 코드를 backend에서 import하지 않는 안전한 parser/sandbox 구조로 교체해야 한다.

### P0-3. optional workload mutation이 인증만으로 실행됨

- `pipeline:write`는 역할 매트릭스에 존재하지만 `backend/app/api/pipelines.py`, `transforms.py`, `streaming.py`, `airflow.py`, `maintenance.py`에 일관되게 적용되지 않는다. maintenance의 component gate도 role permission을 대신하지 않는다.
- `/pipelines/deploy`는 전달된 DAG code를 파일로 배포한다(`backend/app/api/pipelines.py:267-337`).
- `/streaming/sql`은 raw SQL을 실행한다(`backend/app/api/streaming.py:718-748`).
- notebook 파일/kernel/session mutation은 component gate 외 역할 permission이 없다(`backend/app/api/notebooks.py:340-491`).
- MLflow experiment create와 model stage transition도 인증만 요구한다(`backend/app/api/mlflow_integration.py:244,758`).

**영향:** 해당 capability가 활성화된 프로필에서 viewer를 포함한 인증 사용자가 workload와 데이터를 변경할 수 있다. 모든 side-effect route를 중앙 action inventory에 등록하고 API dependency로 강제해야 한다.

### P0-4. `ai:generate` 비용 경계 우회

- `backend/app/permissions.py:33-35`는 model token을 쓰는 모든 action을 `ai:generate`로 정의한다.
- `/ai/embed`와 `/ai/sql`에는 dependency가 있지만, inline ingest는 embedding을 호출하면서 permission이 없다(`backend/app/api/ai_vectors.py:389-399`).
- Search는 query embedding과 optional rerank를 호출하지만 permission이 없다(`backend/app/api/ai_vectors.py:657-718`).
- RAG는 retrieval과 chat completion을 호출하지만 permission이 없다(`backend/app/api/ai_vectors.py:720-784`).

**영향:** viewer, data_engineer, business_analyst, auditor가 허용 collection에서 비용을 발생시킬 수 있다. 비용 호출 전에 403이 발생하고 `_embed`, rerank, chat HTTP가 한 번도 호출되지 않았음을 테스트해야 한다.

### P0-5. admin-role service account의 scope 우회

- `ASSIGNABLE_ROLES`에는 admin이 포함된다(`backend/app/permissions.py:81-86`).
- list response에서는 admin을 숨기지만 create API는 admin 입력을 거부하지 않는다(`backend/app/api/service_account_routes.py:66-80`).
- API key effective permission은 `user:manage`, `settings:write`를 제거한다(`backend/app/service_accounts.py:32-37,74-85`).
- 그러나 `require_admin`은 `permissions`와 `auth_method`를 무시하고 role string만 검사한다(`backend/app/api/auth.py:329-333`).

**영향:** 제한 scope 또는 empty scope의 admin-role key가 user/settings/storage/services/governance 등 `require_admin` route를 통과할 수 있다. service account 생성 시 admin을 서버에서 거부하고, 사람 전용 dependency 또는 effective-permission 기반 dependency로 통일해야 한다.

### P1-1. 선언된 read permission과 admin-only endpoint 충돌

- `auditor`: governance/audit/spend read, `ai_engineer`: spend read가 선언되어 있다.
- governance stats와 PII report는 인증 사용자에게 열려 있지만, auditor 업무에 필수인 policy 목록·preview와 audit log/stream은 `_require_admin`, spend/usage/report/alerts는 `require_admin`만 허용한다.
- 기존 governance 테스트는 auditor의 필수 read 계약을 검증하지 않고 일부 non-admin 거부를 고정한다.

**개선:** 민감 필드 redaction 범위를 정한 뒤 read endpoint에 `governance:read`, `audit:read`, `spend:read`를 각각 적용하고 write는 별도 permission으로 유지한다.

### P1-2. AI engineer의 Knowledge lifecycle 단절

- AI engineer는 `knowledge:write`와 `ai:generate`를 갖지만 S3/Iceberg source ingest와 schedule create는 admin-only다.
- 반대로 inline ingest와 schedule delete는 `knowledge:write`를 확인하지 않고 ownership만 본다.

**개선:** owner + `knowledge:write` + 필요한 `ai:generate`를 조합하고, automation principal은 별도의 exact-route scope로 유지한다.

### P1-3. permission vocabulary가 optional 업무를 표현하지 못함

Notebook, experiment/run, model registry, pipeline read/operate, query statement class가 분리되어 있지 않다. 현재 permission만으로 data scientist, operator, viewer의 차이를 API에서 표현할 수 없다.

**개선 예시:** `query:select`, `query:write`, `pipeline:read`, `pipeline:operate`, `notebook:read`, `notebook:write`, `experiment:read`, `experiment:write`, `model:promote`. 실제 제품 정책을 먼저 확정한 뒤 최소 vocabulary로 적용한다.

### P1-4. 프론트 역할 UX 불일치

- permission context는 sidebar에서만 사용된다(`frontend/components/app-sidebar.tsx:108-166`).
- `useHasPermission`은 정의되어 있지만 페이지에서 사용되지 않는다.
- direct route layout은 capability만 확인한다(`frontend/components/conditional-layout.tsx:12-43`).
- User Management type/select/toggle은 `admin | viewer`만 지원한다(`frontend/app/settings/page.tsx:475-493,594-610,805-810`).
- 여러 페이지는 서버 permission 응답 대신 local token의 `getUser()?.role`을 사용한다.

**개선:** API가 최종 강제한 뒤, 동일 permission source로 버튼·탭·empty/403 state를 제어한다. 사용자 역할 select는 `/api/me/permissions.assignable_roles` 또는 admin 전용 roles endpoint를 사용한다.

### P2. 테스트와 진단 공백

- 세분화 `require_permission` 사용은 4개 API 파일의 15개 route에만 존재한다.
- 역할 관련 기존 테스트는 guard factory나 선택된 route만 확인하며 전체 route inventory를 검사하지 않는다.
- Frontend에는 test script와 `*.test.*`/`*.spec.*`가 없다.
- permission fetch 실패는 권한 없음과 구분되는 오류/retry 상태가 없다.
- 동일한 `POST /mlflow/experiments` route가 두 번 선언되어 있다.

## 6. 확인된 양호 항목

1. `backend/app/permissions.py`의 역할과 permission vocabulary는 pure module이며 unknown role은 viewer 수준으로 write를 차단한다.
2. Knowledge collection은 non-admin에 대해 owner 또는 legacy shared read를 구분하고, shared collection write를 거부한다.
3. collection create/delete와 주요 connector CRUD/sync에는 permission dependency가 적용되어 있다.
4. capability flag 계산과 frontend optional navigation/direct route gate는 구현·테스트되어 있다. Backend에서는 query/catalog/connectors/notebooks/MLflow/streaming/maintenance에 일부 gate가 있으나 Airflow/Pipelines/Transforms router에는 누락되어 있다.
5. AI actor metadata와 per-user spend attribution 경로, retrieval-side PII 방어는 코드에 존재한다. 단위 테스트로 확인된 범위는 ingest PII masking과 embedding egress fail-closed이며 Search/RAG actor payload와 retrieval-side masking acceptance는 추가가 필요하다.
6. Storage, system settings, AI provider/key, 주요 service mutation에는 admin dependency가 적용되어 있다.

## 7. 실행 검증 결과

### 7.1 역할·권한 관련 기존 테스트

```bash
cd backend
/opt/homebrew/bin/python3.12 -m pytest -q \
  tests/test_permissions.py \
  tests/test_permission_enforcement.py \
  tests/test_service_accounts.py \
  tests/test_security_boundaries.py \
  tests/test_auth_acceptance.py \
  tests/test_governance_audit_admin.py \
  tests/test_operational_flows.py \
  tests/test_ml_integrations.py \
  tests/test_transform_security.py
```

결과: **109 passed, 1 skipped, 7 warnings**.

이 결과는 현재 구현된 제한적 계약이 동작한다는 뜻이지, 전체 역할 경계가 안전하다는 뜻은 아니다. 위 P0 공백이 존재하는 상태에서도 모두 통과하므로 route-level negative acceptance가 부족하다는 직접 증거다.

### 7.2 백엔드 전체 테스트

```bash
cd backend
/opt/homebrew/bin/python3.12 -m pytest -q
```

결과: **481 passed, 6 failed, 7 skipped, 53 warnings**.

실패 분류:

- 계약/테스트 불일치 2건
  - `test_require_user_or_internal_accepts_only_exact_nonempty_key`: 테스트 request가 exact callback method/path를 제공하지 않아 현재 allowlist 계약과 불일치.
  - `test_setup_password_forces_change_on_next_login`: 구현에 추가된 인자와 테스트 기대가 불일치.
- 로컬 의존성 누락 4건
  - WebAuthn 테스트가 `ModuleNotFoundError: webauthn`으로 실패. `requirements.txt`에는 선언되어 있으나 실행한 Python 3.12 환경에는 설치되어 있지 않다.
- quality background task가 로컬 Trino에 접속하려다 timeout되고 pending task warning을 남겼다.

기본 macOS `python3`는 3.9여서 `X | None` 타입 구문과 미설치 `pyiceberg` 때문에 collection 단계에서 8 errors가 발생했다. 이 저장소의 로컬 검증은 지원 Python 버전과 lock된 test environment를 명시해야 한다.

### 7.3 Pipeline code 실행 smoke test

임시 Python 파일의 top-level code가 marker 파일을 만들도록 한 뒤 `PipelineCompiler.validate_only()`를 호출했다.

```text
{'top_level_code_executed': True, 'validation_success': False}
```

validation 실패 여부와 무관하게 import 시점에 code가 먼저 실행됨을 확인했다. 테스트는 임시 디렉터리만 사용하고 종료 시 정리했다.

### 7.4 프론트엔드

```bash
cd frontend
npm run build
```

결과: **성공**. Next.js compile, TypeScript, 38개 static page generation을 통과했다.

```bash
npm run lint
```

결과: **실패 — 2 errors, 1 warning**.

- error: `components/catalog/relationship-graph.tsx:86` `react-hooks/set-state-in-effect`
- error: `components/settings/service-accounts.tsx:45` `react-hooks/set-state-in-effect`
- warning: `app/query/page.tsx:267` missing `aiGeneratedSql` dependency

Frontend에는 자동 역할/E2E 테스트 script가 없다.

## 8. 필수 개선 및 acceptance 우선순위

### T0 — P0 해소 전 필수

1. **Route authorization inventory:** 모든 route를 `(method, path, capability, permission, allowed roles/service scopes, side effect)`로 등록하고 누락을 CI에서 실패시킨다.
2. **7-role negative API tests:** 각 mutation을 7개 역할과 empty/single-scope service key로 실제 ASGI 호출해 200/403을 검증한다.
3. **SQL statement boundary:** viewer/auditor/analyst의 SELECT 성공과 INSERT/UPDATE/DELETE/DDL/multi-statement 거부를 검증하고 engine `execute` 미호출을 assert한다.
4. **AI cost boundary:** 비허용 역할의 ingest/Search/RAG가 `_embed`, rerank, chat 호출 전에 403인지 검증한다.
5. **Untrusted Pipeline code boundary:** validate/compile/upload가 제출 Python을 backend에서 import/실행하지 않는지 marker, filesystem, network, credential 접근 payload로 격리 테스트한다. 안전한 parser/sandbox가 없으면 endpoint는 비활성화한다.
6. **Workload side-effect boundary:** viewer가 pipeline deploy, streaming SQL, notebook kernel, experiment/model transition 호출 시 파일 쓰기·upstream API·DB 호출이 0회인지 검증한다.
7. **Admin service key boundary:** admin-role key 생성을 서버가 거부하고 제한 key가 모든 human-admin route에서 403인지 검증한다.

### T1 — 역할 업무 완료성

1. AI engineer의 create → inline/source ingest → schedule → Search → RAG → spend → delete 전체 flow.
2. Auditor의 governance/audit/spend read 성공과 모든 mutation 거부.
3. Data engineer의 connector → schedule → sync → catalog → pipeline/run/log flow 및 타 역할 거부.
4. Data scientist의 query → notebook → experiment/run → model action → dashboard flow.
5. Business analyst의 SELECT/RLS/mask → chart → dashboard create/update/delete flow.
6. Admin UI의 7-role create/update/display/re-login round trip.
7. Frontend에서 7 roles × capability 조합의 sidebar, direct URL, action visibility, 403 UX E2E.

### T2 — 운영 품질

1. 역할 변경 시 current session permission refresh와 stale local token UI 처리.
2. 모든 mutation UI의 `response.ok` 및 401/403/5xx 오류 메시지 검증.
3. OpenAPI `(method, path)` 중복 route 검사.
4. Python/Node 버전과 test dependencies를 고정한 재현 가능한 로컬·CI 명령 제공.
5. 실제 profile별 live acceptance: Portable Core RAG, AWS Glue/Athena, optional OSS add-on을 분리해 증적 보관.

## 9. 출시 승인 기준

다음 조건을 모두 만족하기 전에는 역할 기반 업무 기능을 Production-ready로 승인하지 않는다.

- 어떠한 인증 역할도 제출한 Pipeline Python을 backend 프로세스에서 직접 실행할 수 없다.
- viewer가 모든 write, workload mutation, DDL/DML, model 비용 action에서 side effect 전에 거부된다.
- auditor가 redacted governance/audit/spend를 읽고 어떠한 mutation도 수행하지 못한다.
- ai_engineer가 admin 도움 없이 승인된 Knowledge lifecycle과 spend review를 완료한다.
- data_engineer/data_scientist/business_analyst의 optional 업무는 capability가 있을 때만 보이고, 해당 permission이 API에서 강제된다.
- service account scope가 `require_admin` 또는 다른 role-only dependency를 통해 우회되지 않는다.
- 7 roles × 핵심 route matrix negative/positive 테스트와 frontend E2E가 CI required gate로 통과한다.
- 전체 backend test, frontend lint/build가 동일한 고정 환경에서 green이다.
