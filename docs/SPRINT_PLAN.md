# DataPond Sprint Plan

**최종 수정**: 2026-05-11  
**PM**: PM Agent  
**목표**: 엔터프라이즈 고객 데모 가능한 완전한 AI-Native Lakehouse

---

## 현재 완성도 체크리스트

### ✅ 완료 (2026-05-11 기준)

**인프라 & 인증**
- [x] Auth (JWT, BCrypt, First-login 강제변경)
- [x] Session Expired 오버레이
- [x] 사용자 관리 (CRUD, Role, 활성화/비활성화)
- [x] Settings 4탭 (Overview/Users/Security/System)
- [x] Login 화면 (좌우 분할, 포지셔닝 메시지)
- [x] API 인증 보호 (모든 /api/ 엔드포인트)
- [x] Sample DB 자동 생성 (온보딩)
- [x] middleware.ts → proxy.ts 파일명 변경

**Ingestion**
- [x] Connector CRUD + Edit + Test
- [x] 테이블 enable/disable, sync_mode, incremental_column 설정
- [x] Per-table sync mode 인라인 편집
- [x] Watermark 컬럼 드롭다운 선택
- [x] Schedule 자동화 (Airflow DAG 생성) — "How often / Start time" UI
- [x] Ingestion 목록 Schedule 컬럼 (사람이 읽는 텍스트)
- [x] Sync Now (fetch+ReadableStream SSE)
- [x] Sync History (세션별 이력, 오류 표시)
- [x] Iceberg 실제 적재 (Full Refresh, pandas→Trino)
- [x] **Incremental Sync**: watermark 기반, max_value DB 저장, 빈 결과 시 덮어쓰기 방지
- [x] **Schema Evolution**: append 모드에서 `ALTER TABLE ADD COLUMN` 자동 실행
- [x] **ELT Transform UI**: Pipelines 페이지 SQL Editor + Source/Target namespace + Airflow CTAS DAG
- [x] **CDC**: RisingWave postgres-cdc (Streaming 탭 4단계 마법사)
- [x] Streaming UI (RisingWave — Pipelines 중심, src+mv+sink 그룹핑)
- [x] Medallion 네임스페이스 (raw/refined/serving)

**분석 & 품질**
- [x] Catalog (Trino 실데이터, 필터링)
- [x] **Catalog 데이터 미리보기**: Preview 탭, 상위 100 rows, 컬럼 통계 (null rate, distinct count, min/max)
- [x] Query Lab (Trino SQL 실행)
- [x] **AI SQL Assistant**: LiteLLM → Bedrock → Anthropic fallback chain, Query Lab 자연어 입력
- [x] **Data Quality**: sync 후 row count 이상(±20% warn, ±50% alert) + null rate 체크
- [x] **Dashboard 인라인 미니 차트**: 목록 카드에 실시간 쿼리 + Recharts 렌더링

**서비스 & 운영**
- [x] Notebook view 실제 JupyterLab API 연동 (mock 제거)
- [x] Services 로그 뷰어: pod-specific 로그, 선택한 pod 배너
- [x] Services 실제 K8s metrics (kubectl top 기반)
- [x] Experiment run 비교: MLflow compare API, best 값 ★ 표시
- [x] OpenMetadata lineage: sync 완료 후 best-effort 등록
- [x] Airflow trino_default connection 자동 업데이트

**AI 아키텍처**
- [x] LiteLLM Helm template (ConfigMap + Deployment + Service)
- [x] Ollama Helm template (StatefulSet + initContainer + PVC)
- [x] values-onprem.yaml (완전한 온프레미스 프로파일)
- [x] values-aws.yaml (EKS + S3 + Bedrock)
- [x] Settings UI → AI SQL Assistant 설정
- [x] System Settings API (DB 저장 + 암호화 + startup 복원)

**인프라 안정성**
- [x] PostgreSQL Headless + ClusterIP 분리
- [x] SeaweedFS initContainer (master/filer 준비 대기)
- [x] HPA maxReplicas: 5→2
- [x] POSTGRES_PORT tcp:// 파싱 오류 수정
- [x] DATABASE_URL env 순서 버그 수정

### ❌ 미구현
- [ ] 에어갭 설치 패키지 (bundle-airgap.sh 검증)
- [ ] LDAP/SSO 연동
- [ ] Iceberg VACUUM DAG
- [ ] Row-level security
- [ ] 자동 데이터 프로파일링 (PII 감지)
- [ ] 자연어 파이프라인 생성

---

## Sprint 1: Ingestion 완성 ✅ 완료 (2026-05-08 ~ 2026-05-11)
**목표**: Incremental/CDC/ELT 실제 작동

| 항목 | 상태 | 완료일 |
|------|------|--------|
| S1-1: Incremental Sync | ✅ | 2026-05-11 |
| S1-2: Schema Evolution | ✅ | 2026-05-11 |
| S1-3: ELT Transform UI | ✅ | 2026-05-11 |
| S1-4: CDC (RisingWave postgres-cdc) | ✅ | 2026-05-08 |

---

## Sprint 2: 분석 & 품질 ✅ 완료 (2026-05-08 ~ 2026-05-11)

| 항목 | 상태 | 완료일 |
|------|------|--------|
| S2-1: Catalog 데이터 미리보기 | ✅ | 2026-05-11 |
| S2-2: Dashboard 인라인 미니 차트 | ✅ | 2026-05-11 |
| S2-3: Data Quality 기본 체크 | ✅ | 2026-05-11 |
| S2-4: AI SQL Assistant | ✅ | 2026-05-11 |

---

## Sprint 3: 거버넌스 & 엔터프라이즈 (2026-05-22 ~)

### S3-1: 에어갭 패키징 검증 ⬜
**우선순위**: P0  
**공수**: 1일  
- bundle-airgap.sh 전체 실행 테스트
- 오프라인 환경에서 설치 검증
- 내부 registry (Harbor) 연동

### S3-2: LDAP/SSO 기초 ⬜
**우선순위**: P1  
**공수**: 2일  
- Settings > Security > LDAP 설정 UI
- 테스트 연결
- JWT + LDAP 하이브리드 인증

### S3-3: Iceberg VACUUM ⬜
**우선순위**: P2  
**공수**: 0.5일  
- snapshot expire Airflow DAG 자동 등록
- Ingestion 상세 "Maintenance" 버튼

---

## Sprint 4: AI-Native 차별화 (2026-05-29 ~)

### S4-1: 자동 데이터 프로파일링 ⬜
- PII 감지 (이메일, 전화번호 패턴 매칭)
- Catalog 뷰에 PII 뱃지 표시
- OpenMetadata 태그 자동 등록

### S4-2: 자연어 파이프라인 생성 ⬜
- "매일 orders 테이블을 refined로 집계해줘" → ELT Transform 자동 생성
- LiteLLM 기반

### S4-3: Row-level Security ⬜
- Polaris RBAC + 사용자 역할 연동

---

## 진행 현황 업데이트

| 날짜 | 완료 항목 |
|------|-----------|
| 2026-05-08 | Sprint 1 계획 수립 |
| 2026-05-08 | Ingestion 논리적 일관성 수정, Watermark 드롭다운 구현 |
| 2026-05-08 | Schedule 카드 재설계, lib/schedule.ts 공유 유틸 |
| 2026-05-08 | Sync History 재배치, 높이 제한 + 더보기 토글 |
| 2026-05-08 | Sync Now 401 오류 수정 (EventSource → fetch+ReadableStream) |
| 2026-05-08 | S1-4: CDC 마법사 (4단계: Connection→Tables→Confirm→Result) |
| 2026-05-08 | Streaming 페이지 Pipelines 탭 (src+mv+sink 그룹핑) |
| 2026-05-08 | Auth, 사용자 관리, Login 화면 |
| 2026-05-09 | Catalog 실데이터, API 인증 보호, UTC 타임스탬프 |
| 2026-05-10 | S1-1: Incremental Sync 수정 (watermark 기반) |
| 2026-05-10 | S1-2: Schema Evolution (ALTER TABLE ADD COLUMN 자동) |
| 2026-05-10 | S1-3: ELT Transform UI (Pipelines, Airflow CTAS DAG) |
| 2026-05-11 | S2-1: Catalog 데이터 미리보기 (Preview 탭 + 컬럼 통계) |
| 2026-05-11 | S2-2: Dashboard 인라인 미니 차트 (Recharts) |
| 2026-05-11 | S2-3: Data Quality (row count 이상 감지 + null rate) |
| 2026-05-11 | S2-4: AI SQL Assistant (LiteLLM → Bedrock → Anthropic fallback) |
| 2026-05-11 | LiteLLM + Ollama Helm templates (values-onprem/aws) |
| 2026-05-11 | System Settings API (암호화 저장, startup 복원) |
| 2026-05-11 | Services 로그 뷰어, K8s metrics, per-table sync mode 편집 |
| 2026-05-11 | Experiment run 비교, Notebook JupyterLab API 연동 |
| 2026-05-11 | PostgreSQL Headless/ClusterIP 분리, SeaweedFS initContainer |

---

## 엔터프라이즈 데모 체크리스트

다음이 모두 완료되면 첫 엔터프라이즈 POC 가능:

- [x] Incremental Sync 작동
- [x] ELT Transform (Medallion 2레이어 이상)
- [x] CDC 1개 이상 작동
- [x] Catalog 미리보기
- [x] Auth (JWT) + 사용자 관리
- [x] AI SQL Assistant
- [ ] 에어갭 설치 패키지 (bundle-airgap.sh 검증)
- [ ] LDAP 연동 (또는 로컬 인증으로 대체 가능)
- [ ] 데모 스크립트 (재현 가능)
