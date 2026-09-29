# Implementation log, 2026 H1 (historical)

> Moved out of `CLAUDE.md` on 2026-09-29. This is implementation evidence from the v3–v5 eras and uses superseded terminology (SeaweedFS, the Airflow re-embed DAG, "AI Data Foundation"). It is not a statement of current product scope; see `README.md` and `docs/PRODUCT_CONCEPT.md`.

### Sprint 1: Ingestion (완료)
- ✅ Incremental Sync: watermark 기반, max_value DB 저장, 빈 결과 시 덮어쓰기 방지
- ✅ Schema Evolution: append 모드에서 `ALTER TABLE ADD COLUMN` 자동 실행
- ✅ ELT Transform UI: Pipelines 페이지 SQL Editor + Source/Target namespace + Airflow CTAS DAG 생성
- ✅ CDC: RisingWave postgres-cdc (Streaming 탭 4단계 마법사)

### Sprint 2: 분석 & 품질 (완료)
- ✅ Catalog 데이터 미리보기: Preview 탭, 상위 100 rows, 컬럼 통계 (null rate, distinct count, min/max)
- ✅ Dashboard 인라인 미니 차트: 목록 카드에 실시간 쿼리 + Recharts 렌더링
- ✅ Data Quality: sync 후 row count 이상(±20% warn, ±50% alert) + null rate 체크, connector_quality_checks 테이블
- ✅ AI SQL Assistant: LiteLLM → Bedrock → Anthropic fallback chain, Query Lab 자연어 입력

### 완성도 개선 (완료)
- ✅ Notebook view 실제 JupyterLab API 연동 (mock 제거)
- ✅ Services 로그 뷰어: pod-specific 로그, 선택한 pod 배너 표시
- ✅ Experiment run 비교: MLflow compare API, metrics/params 비교 테이블 (best 값 ★ 표시)
- ✅ OpenMetadata lineage: sync 완료 후 best-effort 등록, pipelines lineage/quality 엔드포인트 실제 OM API 호출
- ✅ Per-table sync mode 편집: 테이블별 sync_mode/incremental_column 인라인 편집
- ✅ 실제 K8s metrics: kubectl top 기반 CPU/Memory 실시간 조회

### 인프라 & 안정성 (완료)
- ✅ PostgreSQL: Headless(postgres-headless) + ClusterIP(postgres) 분리로 Pod 재시작 시 안정성 확보
- ✅ SeaweedFS: initContainer로 master/filer 준비 대기, liveness probe 조정
- ✅ HPA maxReplicas: 5→2 (단일 노드 메모리 부족 방지)
- ✅ POSTGRES_PORT 버그: K8s 자동 주입 `tcp://...` 파싱 오류 수정
- ✅ DATABASE_URL env 순서 버그 수정
- ✅ Airflow trino_default connection 자동 업데이트 (Transform 배포 시)

### AI 아키텍처 (완료)
- ✅ LiteLLM Helm template: ConfigMap(model_list) + Deployment + Service
- ✅ Ollama Helm template: StatefulSet + initContainer(모델 auto-pull) + PVC
- ✅ AI Provider 우선순위 체인: LiteLLM(내부) → Bedrock(AWS) → Anthropic → 스키마 템플릿
- ✅ values-onprem.yaml: 완전한 온프레미스 프로파일 (SeaweedFS, Ollama, LiteLLM, 32GB+ 노드)
- ✅ values-aws.yaml: 기존 Kubernetes용 AWS Hybrid Extended compatibility overlay (EKS를 생성하지 않음)
- ✅ Settings UI → System → AI SQL Assistant: provider/URL/key 설정
- ✅ System Settings API: DB 저장 + 암호화(CredentialVault) + startup 복원

### 2026-06 업데이트 — AI 플랫폼·RAG·거버넌스·안정성 (완료)
**Vector/RAG (AI 데이터 플랫폼)**
- ✅ pgvector 벡터스토어 + RAG: `ai_collections`/`ai_chunks(vector(1024), HNSW)`, Knowledge UI(사이드바 Analyze→Knowledge), 텍스트/lakehouse/S3 적재
- ✅ AI 데이터 파이프라인: `ingest-source`(iceberg 테이블 컬럼 / S3 객체) + Airflow `schedule`(주기 재임베딩 DAG)
- ✅ 컬렉션별 RLS: `ai_collections.owner_id`, 소유자/admin 게이트, 공용(owner NULL) 전사 노출, 삭제는 owner/admin (#52/#57)
- ✅ Ingestion→RAG 브릿지: Knowledge Ingest 카탈로그 드롭다운(schema/table/column) + Catalog 'Send to Knowledge'(✨) 다이얼로그 (#71)
- ✅ Bedrock E2E 검증: Titan 임베딩 → pgvector → 검색 → Claude RAG 인용답변 (라이브)

**외부 LLM 거버넌스 (LiteLLM 활용)**
- ✅ 토큰/비용 대시보드 + 날짜범위 Spend report + 예산 알림 배너 (Settings→AI) (#53~56)
- ✅ 모델 폴백(router fallbacks) — 단일모델 SPOF 제거, `litellm.fallbacks` (#62, 라이브 mock_testing_fallbacks 검증)
- ✅ 사용자별 비용 귀속(per-user spend) — chat/embed payload에 `user`/metadata, usage `users[]` 집계 (#63)
- ✅ 관측성 배선 — `/metrics` prometheus scrape 어노테이션 + Langfuse 트레이싱 opt-in (#64)
- ✅ 가드레일 전 경로 — 한국 PII(`pii_ko`)를 RAG/search/sql/ingest에 적용 + 게이트웨이 Presidio passthrough opt-in (#54)
- ✅ RAG rerank opt-in — `AI_RERANK_MODEL` 설정 시 `/v1/rerank` 재정렬 (#65)

**데이터계층 안정성**
- ✅ SeaweedFS durability: master/volume/filer를 `/data` PVC에 영속(`-mdir/-dir/-defaultStoreDir`) — /tmp 휘발 손상 근본수정 (#49)
- ✅ Iceberg DROP 복구: Polaris `DROP_WITH_PURGE_ENABLED` 활성 — CREATE/INSERT/SELECT/DROP 전 라이프사이클 라이브 동작 (#58)
- ✅ 무거운 sync를 `asyncio.to_thread` + 관대한 liveness probe로 이벤트루프 보호 (#49/#50)
- ✅ Catalog 트리 성능: `/catalog/schemas` 지연 컬럼 로딩(37s 504 → 0.3s) + `/catalog/columns` on-demand (#70)

**보안/인증/재현성**
- ✅ Row-Level Security 엔진: 정책관리·Trino 네이티브·DuckDB 가드 (P0~P4, #13)
- ✅ LDAP/AD 인증(환경설정, 기본 OFF, 로컬 admin 항상 동작) (#41)
- ✅ 예약 DAG 인증: 내부 서비스 키 `X-Internal-Key`(`require_user_or_internal`) — 무인증 콜백 401 해소 (#61)
- ✅ 기반 스키마 부트스트랩: `auth.sql`/`queries.sql` git 추적 + startup 멱등 적용(센티넬 가드) — 신규/에어갭 설치 재현성 (#60)
- ✅ AI SQL 응답 파서 견고화: 제어문자/프로즈/이중래핑 JSON/plain-SQL salvage (#66~69)
- ✅ 에어갭 번들 검증: jupyter 커스텀 이미지 빌드 추가 + datapond 이미지 `:latest` 통일(전 프로파일 동작) (#59)

### 새로 추가된 DB 테이블
- `connector_quality_checks`: Data Quality 결과 저장
- `saved_transforms`: ELT Transform 정의 저장
- `system_settings`: 시스템 설정 (암호화 저장)
- `ai_collections` / `ai_chunks`: pgvector 컬렉션·청크(embedding vector(1024), HNSW cosine). `ai_collections.owner_id`로 컬렉션 RLS
- `rls_policies` / `column_masking_policies` / `user_roles` 등: RLS 엔진 스키마 (rls_migration.sql)

### 새로 추가된 API 엔드포인트
- `POST /api/ai/sql`: 자연어 → Trino SQL (LiteLLM 게이트웨이 단일 경로 + egress 가드)
- `GET/PATCH /api/settings/system`: 시스템 설정 CRUD
- `GET /api/settings/system/ai`: AI 설정 조회
- `GET /api/connectors/{id}/quality`: Data Quality 결과
- `POST /api/transforms`: ELT Transform CRUD
- `GET /api/catalog/tables/{namespace}/{table}/preview`: 데이터 미리보기 + 컬럼 통계
- `GET /api/catalog/schemas?columns=false`: 카탈로그 트리(지연 컬럼) · `GET /api/catalog/columns`: 테이블 컬럼 on-demand
- **Vector/RAG**: `POST /api/ai/embed`, `GET/POST/DELETE /api/ai/collections`, `POST /api/ai/collections/{name}/{ingest,ingest-source,schedule}`, `POST /api/ai/search`, `POST /api/ai/rag`
- **AI 거버넌스**: `GET /api/settings/ai/{usage,spend/report,budget-alerts}`, `/api/settings/ai/{providers,status,backends,active,keys}`, `/backends/{name}/test`
- 내부 자동화 인증: 신뢰된 in-cluster 호출은 `X-Internal-Key`(=`INTERNAL_API_KEY`)로 `require_user_or_internal` 엔드포인트(`/ingest-source`) 접근

### 미완성 항목
- ✅ ~~Row-level security~~ — 완료 (엔진 #13 + 컬렉션 RLS #52/#57)
- ✅ ~~LDAP 연동~~ — 완료 (#41). ✅ ~~SSO OIDC~~ — 완료 (enterprise 이미지, /ee). ✅ ~~Passkey/WebAuthn~~ — 완료 (passwordless). SAML은 미구현
- ✅ ~~에어갭 설치 패키지~~ — 구성요소 검증 완료 (#59). *(OSS 온프렘 프로파일 한정; AWS 파운데이션은 ECR pull 기반)*
- ✅ ~~Iceberg VACUUM DAG~~ — startup `deploy_maintenance_dag()`로 유지보수 DAG 배포 *(full-profile Airflow 한정)*
- ✅ ~~**자동 신선도(AI Data Foundation 핵심)**~~ — 완료: 백엔드 인프로세스 재임베딩 스케줄러(`backend/app/rag_scheduler.py`, pg advisory-lock으로 replica 중복 방지, interval 기반). Airflow DAG 경로 제거, append→replace(`ai_chunks.source_group`) 버그 수정. `RAG_SCHEDULER_ENABLED`/`TICK_SECONDS` env
- ✅ ~~커넥터 RAG sink(소스 변경 시 자동 재임베딩)~~ — 완료·라이브: 커넥터 sync 완료 시 `_invalidate_sink_collections()`가 매칭되는 fresh 컬렉션(`refresh_enabled`, iceberg source, 동일 (namespace,table))의 `last_refreshed_at`을 NULL로 → in-process `rag_scheduler`가 다음 tick에 재임베딩(advisory-lock, source_group replace). `RAG_SINK_ENABLED`(기본 on) 게이트, `test_connector_rag_sink.py` 커버.
- ✅ ~~모니터링(AWS)~~ — AWS 단일노드는 **CloudWatch**로 관측(`cloudwatchMetrics.enabled`, 노드 profile의 PutMetricData, 추가 파드 없음). 앱 메트릭(`DataPond` 네임스페이스: RagQuery/EmbeddingCount/QueryCount/BytesScanned) + EC2 메트릭을 묶은 CloudWatch 대시보드 `DataPond` 배포. Prometheus/Grafana는 OSS 프로파일용 옵션으로 남음(차트 템플릿 미구현). Langfuse 트레이싱은 opt-in.
- [ ] Sovereign profile live acceptance와 Bedrock→local model/provider exit drill 자동화 *(별도 self-hosted OSS 환경 필요 — AWS 단일노드에선 라이브 acceptance 불가)*
