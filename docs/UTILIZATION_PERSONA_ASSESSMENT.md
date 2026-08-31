# DataPond 페르소나 기반 활용 가능성 평가

> 평가 시각: 2026-08-31 KST  
> 평가 대상: 현재 작업 트리의 Portable Core, AWS Single-Node Reference, optional OSS add-on 및 Enterprise 경계  
> 평가 방식: README·활성 문서와 실제 코드·테스트·Helm·CI/CD·공개 live reference의 교차 검증
>
> **개정 2026-08-31 (2차):** fresh-install 게이트가 같은 날 처음 통과하여 §1의 서술을 갱신했다.
>
> **개정 2026-08-31 (1차):** 주장을 코드와 재대조하여 다섯 곳을 정정했다. §4.6의 pod security 서술은
> 사실이 뒤집혀 있었고(핵심 워크로드에는 적용, 누락된 13개 중 하나가 OpenMetadata이며 그중
> postgres가 가장 무겁다), §1·§2의 fresh-install 평가는 아직 한 번도 통과하지 않은 CI 잡을
> 검증된 것으로 취급하고 있었다. §6의 우선순위에서 SQL 권한 분리를 1번으로 올렸다 — 이 목록에서
> 유일하게 데이터 파괴가 가능한 항목이다. §4.6에는 acceptance 게이트가 업무시간 밖에서 무력해지는
> 함의를 추가했고, §2의 테스트 수치에는 재현 명령을 붙였다.

## 1. 결론

**DataPond는 현재 “동작하는 governed RAG 제품의 Private Beta”에는 도달했지만, “범용 AI Data Foundation”이나 “규제 데이터용 Enterprise 플랫폼”으로 판매할 단계는 아니다.**

가장 현실적인 활용 범위는 다음과 같다.

- **GO:** 내부 데모, PoC, 비민감 데이터 기반 부서용 RAG, 통제된 디자인 파트너 파일럿
- **조건부 GO:** AWS에서 운영 담당자가 붙는 저위험 내부 서비스
- **NO-GO:** 24×7 외부 고객 서비스, 강한 멀티테넌시, 규제·민감 데이터, 유료 Enterprise GA, Databricks/Snowflake 대체

기술적 Private Beta 준비도는 **약 65%**, 공개 상용화 준비도는 **약 40~45%**로 판단한다. 과거 `PRODUCTIZATION_READINESS_ASSESSMENT.md`의 평가 이후 RBAC, migration, CI가 크게 개선됐지만 데이터 보안·감사·가용성·상용 계약은 여전히 출시를 막는다.

**fresh-install 게이트는 2026-08-31에 처음으로 통과했다** (`install → schema 확인 → acceptance → upgrade → rollback`, 5분 50초). 다만 이 문장이 뜻하는 바를 정확히 해둘 필요가 있다.

이 잡은 만들어진 이래 **한 번도 통과한 적이 없었고**, 통과에 이르기까지 결함 7건을 드러냈다. 전부 *가동 중인 배포를 upgrade하는 것만으로는 원리상 드러날 수 없는* 신규 설치 경로의 결함이다.

1. 첫 설치 시 마이그레이션이 실행될 Namespace가 아직 없음
2. 그 수정(Namespace를 훅으로 전환)이 **다음 upgrade에서 라이브 네임스페이스를 삭제** — 파드·시크릿·TLS 인증서·Helm 릴리스 이력까지 함께 소실, 33분 장애. 되돌리고 테스트 4개로 고정
3. pre-install 훅에는 Secret이 없고, in-cluster DB에서는 DB 자체가 없음 → 마이그레이션을 훅 단계 밖으로
4. `python -m app.migrations`가 `__main__` 가드를 모듈 절반이 정의되기 전에 실행 → init 컨테이너가 이미 존재하는 스키마를 10분간 대기
5. kind에 없는 `local-path` StorageClass로 postgres Pending — 그리고 그 수정이 **YAML 중복 키에 삼켜짐**. 다른 두 프로파일도 같은 문제로 `enabled`·`resources`·`persistence`가 소실 중이었음
6. 빈 `storageClassName`이 null로 렌더링 → API 서버가 채운 값을 Helm이 되돌리려다 **PVC immutable로 upgrade 실패**
7. 마이그레이션 Job이 연결 재시도를 연결 *뒤에* 두어 콜드 클러스터에서 `backoffLimit: 0`으로 영구 실패

**이 이력이 준비도 평가에 갖는 함의는 두 방향이다.** 신규 설치 경로가 실제로는 전혀 검증돼 있지 않았고 결함 밀도가 높았다는 점은 부정적이다. 반면 이제는 그 경로를 실행하고 실패시키는 게이트가 존재하며 통과한다는 점은, 다음 회귀가 라이브가 아니라 CI에서 잡힌다는 뜻이다. 2번은 후자가 왜 중요한지를 대가를 치르고 보여준 사례다.

한 번의 통과는 "신규 설치가 검증됐다"가 아니라 "신규 설치를 검증할 수단이 생겼다"이다. 준비도를 올리려면 이 게이트가 여러 커밋에 걸쳐 안정적으로 유지되는지를 보아야 한다.

## 2. 확인된 실제 상태

README의 주장만 따르지 않고 현재 코드와 실행 환경을 확인했다.

- Python 3.11 Community 추적 테스트: **846 passed, 18 skipped**
  (수치는 실행 시점과 deselect 범위에 따라 달라진다. 재현하려면 명령을 함께 기록할 것 —
  예: `pytest tests -q --ignore=tests/acceptance`는 2026-08-31 기준 847 passed / 7 skipped)
- Enterprise OIDC 테스트: **21 passed**
- 프런트엔드: **20/20 테스트**, TypeScript 통과, ESLint 오류 0·경고 1
- Helm: **8개 프로필 lint/render 통과**
- 현재 공개 AWS reference:
  - `/api/health/ready`: **HTTP 200, `ready=true`**
  - migration: `0002_system_events`
  - database: `ok`
  - 활성: S3, Aurora pgvector, Glue, Athena, LiteLLM/Bedrock, RLS, Ontology
  - 비활성: Pipeline, Streaming, Notebook, MLflow

현재 작업 트리는 clean checkout이 아니며, 미추적 stale 인증 테스트 2건이 현재 fail-closed 정책과 충돌한다. 이는 현재 제품 경계의 실패라기보다 로컬 테스트 자산 정리가 필요한 상태다. 테스트 중 background quality task가 실제 Trino 주소로 접속을 시도하고 pending task 경고를 남기는 테스트 격리 문제도 확인됐다.

따라서 DataPond는 실제로 배포·동작하지 않는 데모 코드가 아니다. 그러나 검증된 중심은 **Knowledge/RAG Core**이고, 넓은 데이터 플랫폼 기능 대부분은 optional·experimental 또는 live 비활성이다.

## 3. 영역별 평가

| 영역 | 평가 | 판단 |
|---|---:|---|
| Governed RAG 핵심 | **8/10** | 가장 강한 자산. 실제 활용 가능 |
| AWS Single-Node Reference | **6.5/10** | 파일럿·레퍼런스에 적합 |
| 인증·애플리케이션 RBAC | **7/10** | 상당히 개선됐지만 세션·역할 불일치 잔존 |
| 데이터 거버넌스·감사 | **4.5/10** | 기능은 있으나 규제 대응 수준 아님 |
| Connector·Catalog·SQL | **6/10** | 보조 데이터 워크플로로 가능 |
| Pipeline·Streaming·ML Workbench | **3/10** | 제품 기능으로 약속하면 안 됨 |
| 운영·HA·DR | **4.5/10** | 수동 운영 및 빠른 재구축 모델 |
| 포터빌리티 | **6/10** | 계약은 좋지만 자동 이관은 미구현 |
| Enterprise 상품화 | **2/10** | 라이선스 placeholder, SLA·지원 계약 없음 |
| 시장·수요 검증 | **3/10** | 기술보다 더 큰 불확실성 |

## 4. 페르소나별 활용 가능성

### 4.1 AI/RAG 엔지니어 — 사내 문서 기반 AI 기능 개발

**적합도: 8/10 · 가장 적합한 페르소나**

가능한 업무:

- 컬렉션 생성 및 텍스트/S3/Iceberg source 적재
- 문자 기반 chunking 및 pgvector HNSW 검색
- optional reranking
- LiteLLM/Bedrock 기반 cited answer
- PII 마스킹
- source replacement, 삭제, freshness schedule
- API/service account를 이용한 애플리케이션 연동
- 사용자별 모델 사용량·비용 확인

storage·vector DB·model provider를 S3/PostgreSQL/LiteLLM 계약으로 분리한 구조는 내부 AI팀에 유용하다.

한계:

- S3 문서는 `.txt`, `.md`, `.csv`, `.json`, `.log` 중심이며 PDF/DOCX/HTML/OCR 파이프라인이 없다.
- 파일당 5MB 제한, 기본 200개 파일 처리 등 대규모 corpus ingestion에는 부족하다.
- chunking은 token/semantic parser가 아니라 문자 길이 기반이다.
- 검색은 vector 중심이며 BM25/hybrid retrieval은 없다.
- citation 후보는 반환하지만 답변의 `[n]`이 실제 근거와 일치하는지 검증하지 않는다.
- embedding은 최대 64개 chunk씩 순차 처리되므로 대량 적재 성능 검증이 필요하다.
- 명시적인 사용자·그룹 공유가 아니라 owner 또는 `owner_id IS NULL` global read-only 방식이다.

**추천 활용:** 비민감 내부 정책·FAQ·기술문서 기반 RAG API와 디자인 파트너 데모.  
**부적합:** 대규모 엔터프라이즈 문서 검색, 복잡한 문서 파싱, 부서별 정교한 공유 정책.

### 4.2 데이터 엔지니어 — 소스 연결 및 AI 데이터 흐름 관리

**적합도: 6/10**

가능한 업무:

- PostgreSQL/MySQL/S3/REST/custom source 연결
- schema introspection 및 sync
- Glue Catalog 탐색
- Athena/Trino query
- connector sync 결과를 Knowledge collection과 연결
- source → table → collection lineage 일부 확인

그러나 데이터 파이프라인 플랫폼으로는 부족하다.

- 선언형 Pipeline의 source/quality/transform/checkpoint operator는 아직 placeholder다.
- silent success 대신 배포를 HTTP 501로 거부하도록 개선됐지만, 이는 안전한 미구현이지 기능 완성이 아니다.
- live AWS reference에서도 `pipelines=false`, `streaming=false`다.
- Airflow/Spark/Streaming을 활성화할 수는 있지만 upstream 조합에 대한 지원 범위와 acceptance가 제한적이다.

**추천 활용:** 기존 데이터 파이프라인 결과를 DataPond Knowledge로 가져오는 얇은 연결 계층.  
**부적합:** Airflow/dbt/Glue/Databricks를 대체하는 핵심 ETL 오케스트레이터.

### 4.3 비즈니스 분석가 — SQL과 대시보드 기반 분석

**적합도: 5.5/10**

장점:

- Glue/Athena 기반 SQL 실행
- bare table name resolution
- query history, plan review
- dashboard 저장
- `business_analyst` 역할과 `query:run`, `dashboard:write` 존재

가장 큰 문제는 `query:run`이 SELECT/DML/DDL로 분리되지 않는다는 점이다. `viewer`, `auditor`, `business_analyst`도 query 권한을 갖고 있으며 SQL 실행 경로는 CREATE/DROP/ALTER를 원천 차단하지 않는다. Athena 권한이 읽기 전용 IAM으로 제한되지 않았다면 역할 이름과 실제 권한이 어긋날 수 있다.

또한 `business_analyst`는 `ai:generate`가 없어 직접 semantic search/RAG를 실행할 수 없다. 비용 통제 면에서는 합리적이지만 일반 사용자가 기대하는 “문서에 질문하기” UX와는 어긋날 수 있다.

**추천 활용:** 읽기 전용 AWS IAM/workgroup이 별도로 보장된 내부 분석 환경.  
**부적합:** SQL만으로 데이터 파괴를 확실히 방지해야 하는 셀프서비스 분석 서비스.

### 4.4 데이터 사이언티스트 — Notebook·실험·RAG 품질 관리

**적합도: 5/10**

역할상 query, Knowledge, AI generation, dashboard, workbench 권한을 갖는다. 코드에는 Jupyter와 MLflow 연동 UI/API도 상당량 존재한다.

하지만 현재 live reference에서는 Notebook과 MLflow가 꺼져 있고, `SUPPORT.md`도 optional add-on은 upstream wiring만 지원한다고 명시한다. 즉 “소스 코드에 있다”와 “현재 제품으로 지원한다” 사이에 차이가 크다.

**추천 활용:** RAG retrieval parameter와 ontology concept expansion을 실험하는 제한된 팀.  
**부적합:** 재현 가능한 ML lifecycle, feature store, 학습 pipeline, model governance가 필요한 팀.

### 4.5 보안·컴플라이언스 감사자 — 접근·감사·비용 검증

**적합도: 3.5/10**

긍정적인 요소:

- mutating route 전체를 순회하는 authorization inventory test
- 역할별 permission matrix
- query·auth·connector audit 화면
- RLS coverage 및 column masking
- per-user model spend
- ingestion/retrieval 이중 PII 마스킹
- 외부 model egress를 local-only로 막는 fail-closed 로직

규제 대응을 막는 핵심 공백:

1. **감사로그가 append-only가 아니다.** 동일 애플리케이션 DB에 저장되고, 별도 INSERT-only writer나 WORM/SIEM export가 없다. query history는 호출자가 `save_history=false`로 끌 수 있다.
2. **RLS가 기본 허용이다.** live profile도 `defaultDeny=false`이며 SQL rewrite 경로 중심이다. direct S3, Notebook 및 다른 data path에는 동일 보장이 없다.
3. **auditor 역할 계약이 불완전하다.** permission matrix에는 `audit:read`, `governance:read`가 있지만 audit log/stream과 정책 목록 상당수는 여전히 `_require_admin`을 추가 호출한다.
4. **PII 범위가 제한적이다.** 주민번호, 휴대전화, 사업자번호, 신용카드, 이메일 등 구조화된 한국형 PII regex이며 이름·주소·계좌·면허·문맥형 민감정보 및 NER는 지원하지 않는다.

**결론:** “거버넌스 기능이 있는 RAG”는 맞지만 “감사 가능한 규제 데이터 플랫폼”은 아니다.

### 4.6 플랫폼/SRE 운영자 — AWS 운영

**적합도: 5/10**

강점:

- Terraform으로 EC2, Aurora, S3, ECR, IAM, Route53, Secrets Manager 구성
- EBS/Aurora 암호화, IMDSv2, NetworkPolicy
- Alembic migration job
- readiness와 system event history
- immutable image tag, Trivy blocking scan, SBOM/provenance
- fresh install → acceptance → upgrade → rollback CI
- DR·upgrade runbook

제약:

- application node는 단일 Spot EC2/K3s다.
- 현재 live 환경은 평일 07:30~18:00 KST에만 켜지고 주말에는 내려간다.
- 앱 노드 HA나 EKS topology가 없다.
- DR은 문서화됐지만 정기 scratch restore가 release gate로 자동화되지 않았다.
- final image signing/verification과 digest promotion이 없다.
- Pod security context는 핵심 워크로드(backend, frontend, litellm, valkey, migration job)에는
  적용됐지만 13개 워크로드에는 없다: airflow, minio, jupyter, mlflow, polaris, openmetadata,
  ollama, **postgres**, trino, spark, mock-model, vllm, risingwave.
- 그중 **postgres가 문제다.** optional add-on이 아니라 자체 호스팅 프로파일 전부의 핵심
  워크로드이고 데이터를 전부 들고 있는데, `podSecurity`/`containerSecurity` 어느 쪽도
  적용돼 있지 않다.
- live acceptance는 노드가 꺼져 있으면 실패하지 않고 skip된다. 위의 업무시간 제약과
  합치면 **야간·주말에 실행되는 모든 CI에서 이 게이트는 항상 무력**이라는 뜻이다.
  통과한 것이 아니라 실행되지 않은 것인데, 결과 화면에서는 구분되지 않는다.
- browser E2E와 실제 S3/Glue/Athena adapter acceptance는 required gate가 아니다.
- Python 의존성이 완전히 hash-lock되지 않았고 일부 범위 의존성이 남아 있다.

**추천 활용:** 담당 운영자가 있고 업무시간 제한을 받아들일 수 있는 파일럿.  
**부적합:** 무중단·다중 AZ·자동 failover·지원 SLA가 필요한 서비스.

### 4.7 Enterprise 구매·법무 담당자 — 계약 및 운영 책임

**적합도: 2/10**

현재는 구매할 수 있는 완성된 Enterprise 상품이 아니다.

- `ee/LICENSE`가 명시적으로 placeholder
- 법률 검토된 구독 계약 없음
- SLA 없음
- on-call 없음
- LTS/backport 정책 없음
- OIDC는 구현·테스트됐지만 Preview
- SAML 및 Marketplace packaging 없음
- 지원 문서가 best-effort라고 명시

기술 검증용 Enterprise Preview는 가능하지만 계약·조달·책임 분계가 필요한 고객에게 판매하면 안 된다.

### 4.8 창업자/제품 책임자 — 사업 지속 가능성

**기술 데모 적합도: 8.5/10 · 사업 검증도: 3/10**

데모 자산은 충분하다. 특히 다음 이야기는 설득력이 있다.

> S3/PostgreSQL/LiteLLM 위에서 RAG를 만들고, PII·역할·인용·비용 귀속까지 한 번에 보여준다.

그러나 시장 수요는 아직 검증되지 않았다. `CONCEPT_RECONFIRMATION.md`도 다음을 명시한다.

- 넓은 “AI Data Foundation” 포지셔닝은 기각
- governed·portable RAG/agent data access로 좁힐 것
- jargon-heavy 규제 버티컬의 디자인 파트너 확보가 다음 게이트
- 3개월 내 실제 데이터·예산·지불 경로를 가진 파트너가 없으면 재검토

현재 가장 큰 사업 위험은 기술 부족보다 너무 넓은 UI와 메시지가 핵심 구매 이유를 흐린다는 점이다. Pipeline, Streaming, Notebook, MLflow 화면의 존재는 플랫폼이 커 보이게 하지만 고객 기대와 지원 부담도 함께 키운다.

## 5. 현실적으로 가능한 활용 시나리오

### 5.1 적극 권장

1. **사내 정책·기술문서 RAG**
   - 비민감 또는 마스킹 가능한 텍스트
   - 10~50명 규모
   - API를 통해 기존 챗봇/에이전트에 연결
2. **AWS 디자인 파트너 데모**
   - S3 → Bedrock embeddings → Aurora pgvector → cited answer
   - Glue/Athena catalog와 structured data query를 보조 시나리오로 사용
3. **모델 비용·데이터 접근 통제가 필요한 AI팀 파일럿**
   - `ai_engineer` service account
   - 사용자별 spend attribution
   - local-only/cloud-allowed egress 정책 비교
4. **포터빌리티 검증 PoC**
   - Bedrock과 local/OpenAI-compatible provider rebinding
   - Aurora와 일반 PostgreSQL 비교
   - export/import 자동화는 직접 스크립트로 수행

### 5.2 현재 피해야 할 시나리오

- 의료·금융·법률 원본 PII를 그대로 저장하는 운영 환경
- 고객별 tenant 격리가 필요한 SaaS
- 24×7 외부 서비스
- 감사 불변성과 법적 증적이 필요한 환경
- 복잡한 PDF·이미지·스캔 문서 RAG
- 대규모 ETL/streaming/lakehouse 대체
- Enterprise 유료 판매 및 SLA 계약

## 6. 상품화 전 우선 해결 과제

1. **SQL 권한 분리** — 이 목록에서 유일하게 데이터 파괴가 가능한 항목이므로 첫 번째다.
   - `POST /queries/execute`에는 문장 종류 게이트가 없다. `queries.py:144`의 주석이
     *"Don't add LIMIT to DDL or SHOW commands"*로, DDL이 흐른다는 전제 위에 쓰여 있다.
     `transforms.py:139`만 SELECT/WITH를 강제하고, 그 경로는 별개다.
   - `viewer`를 포함해 `query:run`을 가진 모든 역할이 `DROP TABLE`을 실행할 수 있다.
     Athena IAM이 읽기 전용으로 제한돼 있지 않다면 실제 데이터 파괴로 이어진다.
   - SELECT / DML / DDL / administration 분리
   - viewer·analyst·auditor는 SELECT-only를 엔진/IAM 양쪽에서 강제
2. **제품 범위를 Portable Core로 고정**
   - Pipeline/Streaming/MLflow/Jupyter는 Experimental로 분리하거나 기본 UI에서 제거
   - “AI Data Foundation”보다 “governed data access for AI/RAG”로 메시지 축소
3. **거버넌스 경계 완성**
   - Production `defaultDeny=true`
   - direct S3/Athena/Notebook 등 우회 경로 통제
   - 명시적 collection user/group membership 구현
4. **감사로그 강제·불변화**
   - mandatory security audit와 query history 분리
   - INSERT-only writer, WORM/SIEM export, retention 및 redaction
   - auditor 역할과 실제 endpoint 정렬
5. **RAG 제품 품질 강화**
   - PDF/DOCX/HTML loader
   - semantic/token-aware chunking
   - hybrid retrieval
   - citation integrity validator
   - 고정 평가셋과 품질 회귀 gate
6. **상용 운영 경계**
   - HttpOnly session/CSRF
   - 고위험 route DB recheck fail-closed
   - Pod Security
   - 24×7 topology 또는 “업무시간 파일럿”의 명시적 상품화
7. **수요 검증**
   - 개발 추가보다 먼저 실제 데이터·예산·지불 의사가 있는 디자인 파트너 1곳 확보
   - retrieval 품질뿐 아니라 구축 시간 절감, 정책 준수, 운영 비용을 수치화

## 7. 최종 판정

| 출시·활용 형태 | 판정 |
|---|---|
| 내부 기술 데모 | **GO** |
| 비민감 데이터 기반 사내 RAG PoC | **GO** |
| 통제된 디자인 파트너 파일럿 | **조건부 GO** |
| 담당 운영자가 있는 저위험 부서 서비스 | **조건부 GO** |
| Community 공개 Beta | **핵심 범위 축소 후 가능** |
| 규제·민감 데이터 Production | **NO-GO** |
| 24×7 외부 고객 SaaS | **NO-GO** |
| 유료 Enterprise/계약/SLA | **NO-GO** |
| 범용 데이터·AI 플랫폼으로 포지셔닝 | **NO-GO** |

가장 냉정하게 표현하면 **DataPond는 버려야 할 프로토타입이 아니라 좁혀야 할 제품**이다. RAG Core는 충분히 활용 가치가 있지만 넓은 플랫폼 외형과 규제·Enterprise 주장이 현재 실체보다 앞서 있다. 다음 투자는 기능 확장보다 **한 버티컬 디자인 파트너, 명확한 ACL·감사 경계, 반복 가능한 RAG 품질 증명**에 집중하는 것이 타당하다.

## 8. 평가 제한

- 공개 live readiness와 capability는 확인했지만 인증 자격증명이 필요한 live end-to-end acceptance는 이번 평가에서 재실행하지 않았다.
- 실제 S3/Glue/Athena 데이터 작업, DR restore 및 장애 주입은 수행하지 않았다.
- 현재 작업 트리는 clean checkout이 아니므로 테스트 결과는 현재 로컬 상태 기준이다.
- 점수는 의사결정을 위한 정성 지표이며 출시 acceptance gate를 대체하지 않는다.
