# DataPond Sprint Plan

**작성일**: 2026-05-08  
**PM**: PM Agent  
**목표**: 엔터프라이즈 고객 데모 가능한 완전한 AI-Native Lakehouse

---

## 현재 완성도 체크리스트

### ✅ 완료
- [x] Iceberg 실제 적재 (Full Refresh, pandas→Trino)
- [x] Sync 실시간 시각화 (SSE, 단계별 진행)
- [x] Sync History (세션별 이력, 오류 표시)
- [x] Connector CRUD + Edit + Test
- [x] 테이블 enable/disable, sync_mode, incremental_column 설정
- [x] Schedule 자동화 (Airflow DAG 생성)
- [x] Sample DB 자동 생성 (온보딩)
- [x] Auth (JWT, BCrypt, First-login 강제변경)
- [x] Session Expired 오버레이
- [x] 사용자 관리 (CRUD, Role, 활성화/비활성화)
- [x] Settings 4탭 (Overview/Users/Security/System)
- [x] Login 화면 (좌우 분할, 포지셔닝 메시지)
- [x] Catalog (Trino 실데이터, 필터링)
- [x] Query Lab (Trino SQL 실행)
- [x] Streaming UI (RisingWave Sources/Sinks/MVs/SQL Console)
- [x] Medallion 네임스페이스 (raw/refined/serving)
- [x] API 인증 보호 (모든 /api/ 엔드포인트)
- [x] UTC 타임스탬프 통일
- [x] 색상 체계 통일 (primary/destructive/green-600)
- [x] 사이드바 구조 개편 (Data/Analyze/Platform)

### 🚧 부분 구현
- [ ] Incremental Sync (코드 있으나 watermark 미연결)
- [ ] Dashboard (서비스 상태만, 실제 차트 없음)
- [ ] Notebooks (JupyterLab 직접 연결, 노트북 목록만)
- [ ] Services (K8s 상태 조회, 실시간 metrics 추정값)

### ❌ 미구현
- [ ] ELT Transform (Medallion 변환 파이프라인)
- [ ] CDC (RisingWave PostgreSQL CDC Source)
- [ ] Schema Evolution (컬럼 추가 자동 ALTER TABLE)
- [ ] Catalog 데이터 미리보기
- [ ] Data Quality 기본 체크
- [ ] OpenMetadata 리니지 자동 등록
- [ ] AI SQL Assistant (LiteLLM)
- [ ] LDAP/SSO
- [ ] Iceberg VACUUM

---

## Sprint 1: Ingestion 완성 (현재 진행)
**기간**: 2026-05-08 ~ 2026-05-15  
**목표**: Incremental/CDC/ELT 실제 작동

### S1-1: Incremental Sync 수정 ⬜
**우선순위**: P0  
**공수**: 2시간  
**작업**:
- SSE stream에서 `connector_sync_jobs.last_value` 읽어 `sync_to_iceberg()` 전달
- sync 완료 후 `max(incremental_column)` → `last_value` UPDATE
- 상세 페이지 Tables 카드에 watermark 현황 표시

**완료 기준**: `updated_at` 컬럼으로 Incremental 설정 시 신규/변경 rows만 sync

### S1-2: Schema Evolution ⬜
**우선순위**: P1  
**공수**: 2시간  
**작업**:
- sync 실패 시 에러 타입 분석 (TYPE_MISMATCH, COLUMN_NOT_FOUND)
- Trino `ALTER TABLE ADD COLUMN` 자동 실행 후 재시도
- iceberg_writer에 `_apply_schema_evolution()` 추가

**완료 기준**: 소스 컬럼 추가 시 sync 자동 성공

### S1-3: ELT Transform UI ⬜
**우선순위**: P1  
**공수**: 1일  
**작업**:
- Pipelines 페이지 "New Transform" 버튼 추가
- SQL Editor + Source/Target namespace 선택
- Airflow DAG 자동 생성 (Trino CTAS)
- 변환 결과 iceberg.refined.* 또는 iceberg.serving.* 저장

**완료 기준**: UI에서 SQL 작성 → refined 레이어 테이블 생성 → 스케줄 실행

### S1-4: CDC Source (RisingWave) ⬜
**우선순위**: P1  
**공수**: 1일  
**작업**:
- Streaming 페이지 "New CDC Source" 템플릿 추가
- PostgreSQL WAL → RisingWave CREATE SOURCE (Debezium 포맷)
- Iceberg Sink 자동 연결 SQL 생성
- Ingestion 목록에 CDC 타입 소스 표시

**완료 기준**: PostgreSQL CDC → RisingWave → Iceberg 흐름 E2E 작동

---

## Sprint 2: 분석 & 품질 (2026-05-15 ~ 2026-05-22)

### S2-1: Catalog 데이터 미리보기 ⬜
**공수**: 1일  
**작업**:
- Catalog 테이블 클릭 → 우측 패널에 상위 100 rows
- 컬럼 통계 (null rate, distinct count, min/max)
- Query Lab에서 열기 버튼

### S2-2: Dashboard 실제 시각화 ⬜
**공수**: 1.5일  
**작업**:
- Query Lab 저장 쿼리 → Dashboard 차트
- Recharts bar/line/pie 렌더링
- 시계열 트렌드 지원

### S2-3: 기본 Data Quality ⬜
**공수**: 1일  
**작업**:
- sync 후 row count 이상 감지 (±20% 경고)
- null rate 임계값 초과 경고
- Ingestion 상세 "Data Quality" 탭

### S2-4: AI SQL Assistant ⬜
**공수**: 2일  
**작업**:
- LiteLLM 서비스 활성화
- Query Lab 자연어 → SQL 변환
- 쿼리 설명 / 최적화 제안
- 내부 LLM (Ollama) 지원

---

## Sprint 3: 거버넌스 & 엔터프라이즈 (2026-05-22 ~ 2026-05-29)

### S3-1: OpenMetadata 리니지 자동 등록 ⬜
**공수**: 1일  
- sync 완료 시 OpenMetadata API → 리니지 자동 생성
- ELT transform → raw→refined 리니지

### S3-2: Iceberg VACUUM ⬜
**공수**: 0.5일  
- snapshot expire Airflow DAG 자동 등록
- Ingestion 상세 "Maintenance" 버튼

### S3-3: LDAP/SSO 기초 ⬜
**공수**: 2일  
- Settings > Security > LDAP 설정 UI
- 테스트 연결
- JWT + LDAP 하이브리드 인증

### S3-4: 에어갭 패키징 검증 ⬜
**공수**: 1일  
- bundle-airgap.sh 전체 실행 테스트
- 오프라인 환경에서 설치 검증

---

## Sprint 4: AI-Native 차별화 (2026-05-29 ~)

### S4-1: LiteLLM 완전 활성화 ⬜
### S4-2: 자동 데이터 프로파일링 (PII 감지) ⬜
### S4-3: 자연어 파이프라인 생성 ⬜
### S4-4: Row-level Security ⬜

---

## 진행 현황 업데이트

| 날짜 | 완료 항목 |
|------|-----------|
| 2026-05-08 | Sprint 1 계획 수립 |

---

## 엔터프라이즈 데모 체크리스트

다음이 모두 완료되면 첫 엔터프라이즈 POC 가능:

- [ ] Incremental Sync 작동
- [ ] ELT Transform (Medallion 2레이어 이상)
- [ ] CDC 1개 이상 작동
- [ ] Catalog 미리보기
- [ ] Auth (JWT) + 사용자 관리
- [ ] 에어갭 설치 패키지
- [ ] LDAP 연동 (또는 로컬 인증)
- [ ] 데모 스크립트 (재현 가능)
