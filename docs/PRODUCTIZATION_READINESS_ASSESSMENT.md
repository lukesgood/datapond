# DataPond 상품화 준비도 평가

> 평가일: 2026-08-24  
> 평가 대상: 현재 저장소의 Portable Core, AWS Single-Node Reference, optional OSS add-on, Enterprise 경계  
> 평가 방식: README 제품 계약과 코드·테스트·Helm·Terraform·CI/CD·운영 문서의 정적 대조 및 로컬 검증

## 1. 결론

**현재 DataPond는 내부 데모, 기술 프리뷰, 통제된 디자인 파트너 평가에는 사용할 수 있지만 공개 Production 또는 유료 Enterprise GA로 출시하기에는 `NO-GO`다.**

Portable RAG 핵심은 단순 목업이 아니라 실제 구현돼 있다. 텍스트/S3/Iceberg 수집, chunk 교체, PII 처리, pgvector 검색, optional rerank, cited RAG, capability gating, OIDC 등은 코드와 테스트 근거가 있다. 반면 상품화에 필요한 권한 강제, 감사 불변성, data-plane 정책, 안전한 DB migration, 검증된 artifact promotion, 자동 acceptance, 공급망 보안, 상용 라이선스 및 지원 계약이 미완성이다.

현재 권장 단계는 다음과 같다.

| 출시 형태 | 판단 | 조건 |
|---|---|---|
| 내부 개발·데모 | 가능 | 비운영 데이터, 수동 검증 |
| 통제된 디자인 파트너 | 조건부 가능 | 고정 SHA, 제한된 사용자, 수동 backup/acceptance, 명확한 preview 고지 |
| Community 공개 beta | 보류 | 핵심 P0 보안·릴리스·acceptance 해소 후 |
| Enterprise paid beta | 보류 | Community 조건 + 법률 검토된 라이선스·지원 계약 |
| 유료 GA/SLA | 불가 | 모든 P0 및 주요 P1, 반복 가능한 운영 증적 필요 |

## 2. 준비도 요약

아래 점수는 정적 평가를 위한 정성 지표이며 출시 게이트를 대체하지 않는다. P0가 남아 있으면 점수와 관계없이 Production 출시는 차단된다.

| 영역 | 준비도 | 판단 |
|---|---:|---|
| Portable RAG 핵심 기능 | 75% | 베타 수준 |
| UI 및 배포 프로필 | 65% | 제한적 지원 가능 |
| 보안·권한·거버넌스 | 35% | Production 차단 |
| 운영·DR·관측성 | 45% | 수동 운영 수준 |
| CI/CD·공급망·업그레이드 | 40% | GA 차단 |
| 상용 라이선스·지원체계 | 20% | Enterprise 판매 불가 |
| **종합** | **약 45~50%** | **디자인 파트너 단계** |

## 3. 확인된 강점

### 3.1 실제 구현된 Portable RAG

- `backend/app/api/ai_vectors.py`에 text, S3, Iceberg source ingestion과 chunk replacement가 구현돼 있다.
- PostgreSQL `vector` 컬럼과 HNSW cosine index 생성 로직이 있다.
- embedding, vector retrieval, optional rerank fallback, cited RAG 응답이 연결돼 있다.
- `backend/app/rag_scheduler.py`는 advisory lock을 사용해 중복 실행을 방지한다.
- `frontend/app/knowledge/page.tsx`에서 collection 생성, 수집, 검색, 질문, citation 표시가 연결돼 있다.

### 3.2 방어적인 일부 보안 구현

- 수집 전 PII masking과 검색 후 재마스킹이 구현돼 있다.
- 외부 모델 egress 정책이 실패 시 허용보다 차단에 가깝게 동작한다.
- critical component secret은 Production에서 누락 시 fail-closed하도록 설계돼 있다.
- Enterprise OIDC는 Authorization Code + PKCE, state, nonce, JWKS, issuer, audience, algorithm 검증을 포함한다.
- WebAuthn에는 challenge single-use, origin/RP 검증, sign counter 방어가 있다.

### 3.3 비교적 명확한 제품 경계

- README는 AWS가 reference deployment이지 제품 경계가 아님을 명시한다.
- EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace를 Roadmap으로 구분한다.
- AWS Single-Node Reference가 application-node HA가 아니라는 점을 문서에 명시한다.
- capability metadata와 UI route gating으로 비활성 optional module을 숨긴다.

### 3.4 배포 기반

- Helm 프로필이 Portable Core, AWS single-node, AWS hybrid, on-prem, development로 분리돼 있다.
- AWS S3 versioning, Aurora encryption/PITR, ECR immutable tag/scan-on-push, SSM 운영 경로가 존재한다.
- `docs/AWS_MVP_RUNBOOK.md`와 `scripts/validate-deployment.sh`에 수동 acceptance 절차가 있다.

## 4. P0: 출시 차단 항목

### P0-1. 선언형 Pipeline의 silent no-op — **부분 해소 (2026-08-25)**

> **평가 이후 조치.** 두 층에서 막았다.
>
> 1. 생성되는 DAG가 더 이상 `EmptyOperator`를 쓰지 않는다. placeholder task는
>    `NotImplementedError`를 던진다 — `EmptyOperator`는 성공하므로, 매 실행이
>    초록불이 되어 Airflow의 상태 페이지 자체가 "동작했다"고 알려주는 상태였다.
> 2. `POST /api/pipelines/deploy`가 placeholder를 포함한 DAG를 **501로 거부**한다.
>    생성기가 module 레벨에 `DATAPOND_UNIMPLEMENTED_TASKS`를 선언하고 배포가 그것을
>    읽는다(연산자 이름 추측이 아님). 스케줄링 형태만 확인하려는 경우를 위해
>    `PIPELINES_ALLOW_PLACEHOLDER_DEPLOY=true`로 명시적 우회가 가능하다.
>
> 부수 발견: 저장소에 예제 파이프라인이 없어 `tests/test_pipelines/test_compiler.py`가
> 계속 skip되고 있었다 — 컴파일러 경로에 사실상 커버리지가 없었다. 새 테스트는
> 파이프라인 소스를 테스트 안에서 만들어 실제 컴파일러를 태운다.
>
> 잔여 항목: 실제 operator 구현, README의 Airflow/Spark transform 범위 축소, Spark
> 지원 제외 명시는 미완이다.

`backend/app/pipelines/dag_generator.py`의 source, quality, transform, checkpoint task가 `EmptyOperator`와 `TODO`로 생성된다. 그러나 `backend/app/api/pipelines.py`는 생성된 DAG를 배포하고 성공 상태를 반환할 수 있다.

**위험:** 사용자가 ingestion, transform, quality check가 수행됐다고 오인한다.

**개선:**

1. Pipeline UI/API를 experimental capability 뒤로 숨기거나 비활성화한다.
2. 실제 operator 구현 전에는 `deployed` 성공을 반환하지 않는다.
3. README의 “Airflow/Spark transforms”를 현재 실제 범위인 Airflow 기반 Trino SQL transform으로 축소한다.
4. Spark는 `spark-submit` 또는 `SparkSubmitOperator` 실행 경로와 acceptance가 생기기 전까지 지원 대상에서 제외한다.

### P0-2. 중앙 권한 강제 부재 — **해소 (2026-08-25)**

> **평가 이후 조치.** `app/permissions.py`의 permission matrix를 전체 route에 적용했다.
> 실행 중인 애플리케이션의 route graph를 직접 순회하는 인벤토리 테스트(`tests/
> test_route_authorization_inventory.py`)가 권한 의존성 없는 mutating route를 발견하면
> 빌드를 실패시킨다. 예외는 13개이며 각각 이유와 함께 코드에 명시돼 있다.
>
> 인벤토리가 처음 밝혀낸 미적용 route는 80개(정당한 예외 13개 제외 시 **67개**)였고,
> 그중에는 **거버넌스 정책 CRUD 8개**가 포함돼 있었다 — 로그인한 누구나 RLS·masking
> 정책을 삭제할 수 있었으므로 P0-3의 우회 경로이기도 했다. Airflow DAG 실행/삭제,
> streaming source/sink DROP, pipeline·transform 삭제, notebook 실행도 같은 상태였다.
>
> 잔여 항목: Query Lab permission의 SELECT/DML/DDL 분리는 미구현이다. 현재
> `/queries/execute`는 `query:run` 단일 권한이며 RLS rewrite가 별도 경계로 동작한다.

인증과 일부 admin dependency는 있으나 전체 route에 적용되는 permission matrix가 없었다. `/queries/execute`와 여러 connector, pipeline, streaming, transform, notebook mutation이 인증 사용자에게 열려 있었다.

**위험:** viewer가 DDL/DML이나 운영 변경을 수행할 수 있다.

**개선:**

1. ~~`permission -> route/action` 중앙 매트릭스를 정의한다.~~ 완료
2. ~~공통 FastAPI dependency로 모든 route에 적용한다.~~ 완료
3. Query Lab permission을 SELECT, DML, DDL, administration으로 분리한다. — 미완
4. ~~전체 route inventory 기반 negative authorization 테스트를 required merge gate로 만든다.~~ 완료

### P0-3. RLS가 기본 허용이고 적용 범위가 제한적임 — **부분 해소 (2026-08-25)**

> **평가 이후 조치 — 가시화 우선.** `defaultDeny`의 기본값은 바꾸지 않았다. 정책이 없는
> DB에서 true로 강제하면 모든 쿼리가 차단되므로, 기존 배포를 깨지 않고 위험 상태를
> **보이게** 만드는 쪽을 택했다.
>
> - `GET /api/governance/rls/coverage` — 카탈로그 테이블 중 정책이 있는 것/없는 것,
>   `default_deny`를 켰을 때 차단될 목록, 그리고 존재하지 않는 테이블을 가리키는
>   orphaned 정책(모두가 켜져 있다고 믿는 통제)을 보고한다. 카탈로그를 못 읽으면
>   `catalog_error`를 채운다 — 0건을 "이상 없음"으로 오독하는 것이 이 엔드포인트가
>   할 수 있는 가장 위험한 일이다.
> - 기동 시 경고: RLS가 켜져 있고 `defaultDeny`가 꺼져 있으며 미보호 테이블이 있을 때만
>   한 줄을 남긴다. 그 조합이 "보호되고 있다"고 읽히면서 실제로는 아닌 유일한 상태다.
>
> 또한 이번 라운드에서 거버넌스 정책 CRUD 8개가 무권한이었던 것(P0-2)을 닫았다 —
> 정책을 만드는 사람이 아무나였으면 RLS 자체가 무의미했다.
>
> 잔여 항목: Production defaultDeny 강제, 배포 preflight 차단, Athena/Jupyter/direct S3
> 등 data path별 강제 경계는 미구현이다.

`RLS_DEFAULT_DENY`의 기본값이 false이고 정책이 없으면 SQL이 그대로 통과한다. 현재 RLS는 주로 Query Lab SQL rewrite 경로에 적용되며 Athena, Jupyter, direct S3 같은 data path에 동일하게 강제되지 않는다.

**위험:** 정책 누락 또는 우회 경로를 통해 원본 데이터가 노출될 수 있다.

**개선:**

1. Production에서 `defaultDeny=true`를 강제한다.
2. 정책이 없는 테이블을 배포 preflight에서 차단한다.
3. Athena/Lake Formation, Trino access control, Jupyter 전용 IAM 등 data path별 강제 경계를 구현한다.
4. 현재 RLS가 PostgreSQL DB-native RLS가 아니라 SQL rewrite 기반임을 제품 문서에 명확히 유지한다.

### P0-4. 감사로그가 선택 가능하고 append-only가 아님

Query의 `save_history`가 호출자 제어이고, audit/query 데이터는 동일 애플리케이션 DB 경계에 있다. 모든 privilege/data mutation이 일관되게 기록되지 않으며 실제 append-only DB role도 생성되지 않는다.

**위험:** 악성 변경이나 SQL 실행이 기록되지 않거나 사후 변경될 수 있다.

**개선:**

1. 사용자 query history와 mandatory security audit를 분리한다.
2. 권한·데이터·설정 변경은 요청 옵션과 관계없이 기록한다.
3. 별도 audit writer credential에 INSERT만 허용하고 UPDATE/DELETE를 revoke한다.
4. 외부 SIEM/WORM export, retention, SQL literal/secret/PII redaction을 적용한다.

### P0-5. 검증된 artifact에 종속되지 않는 릴리스 — **부분 해소 (2026-08-25)**

> **평가 이후 조치.**
>
> - CD에 `require-ci` job 추가: Checks API로 **해당 커밋의** CI 결과를 조회해 success가
>   아니면 빌드/배포를 중단한다. push 시 두 워크플로가 동시에 시작되므로 즉시 실패
>   대신 대기 후 판정한다.
> - `helm upgrade`에 `--atomic --wait --timeout 10m` — 실패 시 자동 롤백.
> - 이미지 빌드에 `provenance: true`, `sbom: true`.
> - CI 렌더 루프에 `values-prod-single`(AWS 레퍼런스 프로파일) 추가 — 빠져 있었다.
> - **Trivy를 report-only에서 실제 게이트로 전환(`exit-code: 1`).** 전환 전 baseline이
>   HIGH/CRITICAL **41건**이었고, 그 안에 이 제품이 인증에 쓰는 JWT 라이브러리의 알고리즘
>   혼동(`python-jose` CVE-2024-33663)과 DB 드라이버의 SQL 인젝션(`pymysql`
>   CVE-2024-36039)이 있었다. 직접 의존성을 올려 baseline을 0으로 만든 뒤 게이트를 켰다:
>   `cryptography` 41.0.7→50.0.0, `python-jose` 3.3.0→3.4.0, `pymysql` 1.1.0→1.1.1,
>   `python-multipart` 0.0.6→0.0.30, `next` 16.2.4→16.3.2, `npm audit fix`.
>
> 잔여 항목: 최종 이미지 signing/verification, digest 기반 배포, staging acceptance 후
> production 승격은 미구현이다.

`.github/workflows/ci.yml`과 `.github/workflows/cd.yml`이 독립 실행된다. CD는 CI 성공 artifact를 요구하지 않으며 `helm upgrade --wait=false`를 사용한다. 실패 후 자동 rollback과 post-deploy acceptance가 없다.

추가 공백:

- Trivy `exit-code: "0"`으로 HIGH/CRITICAL이 report-only다.
- image build provenance가 `false`다.
- 최종 이미지 SBOM, signing, verification이 없다.
- image tag를 사용하며 release manifest에 digest가 없다.
- AWS `values-prod-single.yaml`이 CI의 all-profile render loop에서 빠져 있다.

**개선:**

`test -> image build -> final image scan/SBOM/sign -> staging deploy -> acceptance -> production promotion`을 하나의 required release workflow로 구성한다. Production에는 검증된 digest만 승격하고 Helm `--atomic --wait` 또는 검증 실패 자동 rollback을 적용한다.

### P0-6. 버전형 DB migration 부재 — **대부분 해소 (2026-08-27)**

> **2026-08-27 갱신.** 0~2단계 완료. Alembic 도입, pre-upgrade Job, 실제 스키마
> baseline, 부트스트랩 제거까지 진행했다.
>
> - **0단계** — 마이그레이션을 기동 훅에서 **Helm pre-install/pre-upgrade Job**으로
>   이동. 기동 훅은 레플리카마다 돌고 Alembic은 잠그지 않으므로, 롤링 업그레이드 중
>   두 백엔드가 동시에 DDL을 낼 수 있었다. readiness가 마이그레이션 소요 시간에
>   묶여 있던 것도 함께 해소(느린 `CREATE INDEX`가 정상 릴리스를 롤백시켰을 것).
>   앱은 이제 **확인만** 하고, head보다 뒤처지면 트래픽을 거부한다.
> - **1단계** — `0001_baseline`을 실제 스키마(`pg_dump`: 테이블 41·인덱스 62·제약
>   105·enum 8·함수 3·트리거 10)로 채움. 빈 DB는 migrate, 기존 DB는 stamp.
>   scratch DB를 baseline으로 만들어 라이브와 diff → CHECK 제약 재렌더 외 차이 없음.
> - **2단계** — 부트스트랩 8개와 요청 경로의 지연 `ensure_*` 13곳 제거. **제거 전에
>   증명함**: baseline으로 만든 DB에 부트스트랩 8개를 전부 돌렸을 때 스키마 차이가
>   **0줄**이었다. 제거로 잃는 self-healing은 readiness의 **핵심 테이블 존재 확인**으로
>   대체 — `alembic_version`은 결정을 기록할 뿐 테이블이 있는지는 말하지 않는다.
>
> 라이브 검증: rev 102에서 부트스트랩 없이 기동, `{"ready": true, "migrations":
> "at 0001_baseline", "base_schema": "core tables present"}`, acceptance 통과.
>
> 잔여 항목: expand/contract 리뷰 규칙 문서화, N-1→N upgrade·rollback·실패 주입의
> 자동 검증(P0-10의 ephemeral acceptance와 묶임).
>
> **이하 원 평가 내용.** Alembic 도입은 하지 않았다. `CREATE TABLE IF NOT EXISTS`가 7개
> 모듈에 54곳 흩어져 있고 SQL 파일 4개와 부트스트랩 함수 여러 개가 얽혀 있어, 절반만
> 하면 안 하느니만 못하다. 정직하게 미완으로 남긴다.
>
> 다만 이 항목이 지목한 **실제 위험 — "부분 schema 상태에서 pod가 Ready가 된다"** 는
> 닫았다. 기존에는 liveness와 readiness가 **둘 다** `/health`를 봤고, 그 엔드포인트는
> 무조건 200을 반환했다. 모든 스키마 부트스트랩이 예외를 삼키므로, 스키마가 없는 채로
> Ready가 되어 엔드포인트별로 하나씩 실패하는 상태가 예외가 아니라 기본값이었다.
>
> - `app/readiness.py`: 각 부트스트랩의 성공/실패를 기록. 필수 항목(base_schema) 실패
>   또는 미보고 시 not-ready. optional add-on 스키마는 pod를 붙잡지 않는다.
> - `GET /health/ready`: 부트스트랩 상태 + 실시간 DB 확인, 실패 시 **503**.
> - readinessProbe를 `/health/ready`로 변경(liveness는 `/health` 유지).
>
> 이로써 P1 5.3의 "readiness가 핵심 dependency를 확인하지 않는다"도 함께 해소된다.
>
> 잔여 항목: 순번·checksum 기반 migration, deploy 전 migration Job, expand/contract
> 규칙, N-1→N·rollback 호환 테스트는 미구현이다.

schema 변경이 startup의 `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE`, best-effort bootstrap에 분산돼 있다. 일부 migration 실패 후에도 애플리케이션이 계속 기동할 수 있다.

**위험:** 부분 schema 상태에서 pod가 Ready가 되거나 이전 image rollback이 DB와 호환되지 않을 수 있다.

**개선:**

1. Alembic/Flyway 등 순번·checksum·transaction 기반 migration을 도입한다.
2. deploy 전 migration Job을 실행하고 실패 시 release를 중단한다.
3. expand/contract 호환 규칙을 적용한다.
4. fresh install, N-1→N, 재실행, 실패 주입, app rollback 호환 테스트를 추가한다.

### P0-7. DR 절차와 실제 IAM 불일치 — **부분 해소 (2026-08-25)**

> **평가 이후 조치.** node role에 vault ARN으로 한정된 `secretsmanager:GetSecretValue`
> + `DescribeSecret`을 부여했다. `PutSecretValue`는 부여하지 않았다 — seeding은 운영자
> 자격증명으로 수행하는 의도적 행위다. CMK(`db_kms_key_id`)를 지정한 경우에만 해당 키에
> 한정된 `kms:Decrypt`를 조건부로 부여한다. CMK만 지정하고 decrypt 권한이 없으면 복구
> 시점에야 실패하므로 apply 시점에 함께 결정되도록 했다.
>
> `backend/tests/test_disaster_recovery_iam.py`가 runbook의 `aws` 명령을 파싱해 node가
> 실행하는 명령마다 대응 IAM action이 `terraform/iam.tf`에 있는지 검사한다. 운영자
> 자격증명으로 실행하는 명령은 이유와 함께 명시적으로 제외된다. 문서와 권한의 drift가
> 다시 벌어지면 빌드가 실패한다.
>
> 잔여 항목: 최초 설치 후 secret mirror 자동화, restore preflight, scratch restore
> drill의 release gate화는 미구현이다.

`docs/DISASTER_RECOVERY.md`는 critical secret을 Secrets Manager에 저장하고 복구하도록 요구하지만 `terraform/iam.tf`의 application node role에는 필요한 Secrets Manager action이 없다.

**위험:** cluster loss 후 기존 `ENCRYPTION_KEY`를 복구하지 못하면 Aurora에 저장된 connector/provider credential을 복호화할 수 없다.

**개선:**

1. ~~critical secret vault ARN에 한정된 `GetSecretValue` 권한을 부여한다.~~ 완료
2. ~~write는 별도 운영 role로 분리한다.~~ 완료 (node는 read-only)
3. 최초 설치 후 secret mirror를 자동화한다. — 미완
4. backend 시작 전 restore preflight와 실제 scratch restore drill을 release gate로 만든다. — 미완

### P0-8. 로그인 및 Kubernetes/AWS runtime hardening 부족

- 인터넷 로그인에 account/IP rate limit과 lockout 적용이 없다.
- Kubernetes workload에 restricted Pod Security를 강제하는 security context가 부족하다.
- default-deny NetworkPolicy가 없다.
- backend service account는 namespace의 pod 삭제, deployment/configmap 변경 권한이 넓다.
- AWS bootstrap이 외부 script를 checksum/signature 검증 없이 root로 실행한다.
- root EBS encryption과 IMDSv2 강제가 Terraform에 명시되지 않았다.

**개선:**

- Valkey 기반 account/IP rate limit, exponential backoff, alert를 구현한다.
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, capability drop, seccomp, read-only filesystem을 적용한다.
- NetworkPolicy default-deny와 명시적 service egress/ingress를 적용한다.
- backend RBAC를 resource name 또는 전용 controller 경계로 축소한다.
- K3s/Helm bootstrap artifact의 version/digest/signature를 검증한다.
- EBS CMK encryption과 IMDSv2 required를 Terraform에서 강제한다.

### P0-9. Enterprise 법률·지원 계약 미완성 — **부분 해소 (2026-08-27)**

> **평가 이후 조치.** 법률 검토가 필요한 부분(상용 라이선스, 구독 계약)은 손대지 않았다 —
> 변호사가 할 일이고, 초안을 쓰면 검토된 것처럼 보이게 된다.
>
> 운영 문서는 작성했다: `SECURITY.md`(취약점 신고 경로, 3영업일 확인 / 10영업일 초기
> 판단, severity 정의, 범위, **그리고 이 제품이 보호하지 *않는* 것**)와 `SUPPORT.md`
> (SLA 없음·best-effort임을 명시, 지원 범위, 버전 정책). 둘 다 없는 것을 있다고 쓰지
> 않는 데 중점을 뒀다 — 여기서 가장 쓰기 쉬운 문장이 누군가에게 가장 비싼 문장이다.
>
> 잔여 항목: 법무 검토된 EE 라이선스와 구독 계약, SLA 또는 명시적 best-effort 계약서.

`ee/LICENSE`는 `DataPond Commercial License (placeholder)`이며 법률 검토 전이라고 명시한다. 저장소에는 확정된 `SECURITY.md`, `SUPPORT.md`, SLA, 지원 severity/응답시간 정책이 없다.

**개선:**

1. 법무 검토된 상용 라이선스·구독 계약을 확정한다.
2. 평가, Production 사용, 백업, 재배포, 계약 종료 권리를 명확히 한다.
3. 지원 채널, severity, 응답 목표, 지원 시간대, 유지보수 및 보안 패치 정책을 정의한다.
4. SLA를 제공하지 않는 단계라면 best-effort support임을 명시한다.

### P0-10. 자동 release acceptance 부재 — **부분 해소 (2026-08-27)**

> **평가 이후 조치.** `backend/tests/acceptance/test_portable_core.py`가 평가가 요구한
> 항목을 실제 배포에 대해 검증한다: readiness, 컬렉션 생성, text 적재, **PII 마스킹
> 건수**, 구성 보고, 벡터 검색, **검색 결과에 PII가 되돌아오지 않는지**, 인용 답변,
> 소스 교체, 소스 단위 삭제, **per-user spend 귀속**, 그리고 viewer 토큰이 주어지면
> 읽기 전용 경계까지.
>
> 기존 `scripts/validate-deployment.sh`는 health와 authorization만 보고 RAG 경로는
> 한 줄도 검증하지 않았다.
>
> **라이브 검증 완료 (2026-08-27, rev 96): 10 passed, 1 skipped.** 생성한 컬렉션은
> 실패 시에도 정리된다.
>
> **CI job `acceptance`가 라이브 레퍼런스 배포를 대상으로 활성화됐다 (2026-08-27).**
> 모든 PR과 main push에서 실행된다. 자격증명은 세션 JWT가 아니라 `ai_engineer` 롤의
> **서비스 계정 키**다 — JWT는 만료돼 몇 주 뒤 원인 불명의 실패가 되고, 서비스 계정은
> 사람 계정을 건드리지 않고 단독으로 폐기할 수 있다.
>
> 노드는 평일 업무시간 외 정지되므로, job이 먼저 대상 도달 가능성을 확인한다. 대상이
> 응답하지 않으면 **실패가 아니라 `::notice`로 알리고 건너뛴다** — 도달 불가는 acceptance
> 실패가 아니고, 그것으로 머지를 막으면 변경과 무관한 이유로 밤에 막힌다. 조용히
> 넘어가지 않고 알리는 이유는 초록 체크가 "acceptance가 돌았다"로 읽히면 안 되기 때문이다.
>
> 잔여 항목: ephemeral Kubernetes 설치부터의 acceptance(모델 제공자가 필요하므로
> mock provider 또는 격리된 AWS staging 계정이 선행), browser E2E, upgrade/rollback
> 자동 검증, acceptance 결과의 SHA/digest 보존.

`docs/AWS_MVP_RUNBOOK.md`의 핵심 검증은 수동 절차이고 CI에는 live infrastructure, browser E2E, Helm test가 없다. 현재 live AWS 환경도 `docs/OPERATIONS_PAUSE.md`에 따라 중지돼 있다.

**개선:**

- ephemeral Kubernetes에서 Portable Core 설치부터 RAG까지 자동화한다.
- 격리된 AWS staging 계정에서 S3, Bedrock, Aurora/pgvector, Glue/Athena를 nightly/release gate로 검증한다.
- 핵심 UI 여정을 browser E2E로 검증한다.
- acceptance 결과를 commit SHA, chart version, image digest와 함께 보존한다.

## 5. 주요 P1 개선 항목

### 5.1 인증·세션

- frontend가 bearer token을 localStorage 및 JavaScript-readable cookie에 저장한다.
- CORS가 wildcard와 credentials 조합이다.
- 비밀번호 최소 길이가 6자다.
- JWT user recheck가 DB 장애 시 기존 claim을 신뢰하는 fail-open 정책이다.

**권고:** HttpOnly/Secure/SameSite session, CSRF 방어, exact origin allowlist, 12자 이상 passphrase, admin MFA, 고위험 route fail-closed recheck를 적용한다.

### 5.2 제품 계약 정합성

- collection “shared ACL”은 명시적 사용자·그룹 공유가 아니라 `owner_id IS NULL`인 legacy global read-only collection이다.
- cited RAG는 citation 후보를 반환하지만 답변의 `[n]`과 실제 source 범위 일치 여부를 검증하지 않는다.
- budget alert는 주기적 notification이 아니라 조회 시 percentage/boolean을 계산한다.
- Catalog → Knowledge 성공 링크가 query parameter를 만들지만 Knowledge 화면이 해당 collection을 선택하지 않는다.

**권고:** 실제 sharing membership 모델, citation integrity validator, durable budget notification, 사용자 여정 E2E를 구현하거나 문구를 현재 범위로 축소한다.

### 5.3 운영·관측성

- `/health`와 readiness가 DB, Valkey, LiteLLM 등 핵심 dependency를 확인하지 않는다.
- `values-prod.yaml`의 HA, NetworkPolicy, monitoring 값 일부가 실제 리소스를 생성하지 않는다.
- application 5xx/latency, Aurora capacity, node disk, backup failure, synthetic RAG에 대한 통합 alarm이 부족하다.

**권고:** liveness/readiness/startup을 분리하고, `values-prod.yaml`을 compatibility/unsupported로 낮추며, RED/USE metric과 synthetic canary를 도입한다.

### 5.4 라이선스·의존성

- `THIRD_PARTY_NOTICES.md`에 현재 `pyathena`, `webauthn`, `@simplewebauthn/browser` 등이 누락돼 있다.
- Python transitive dependency는 lock/hash 기반으로 고정되지 않았다.
- final image 및 OS package의 완전한 license inventory가 없다.

**권고:** release SBOM에서 notice inventory를 자동 생성·검토하고 hash-locked Python dependency를 사용한다.

## 6. 개선 로드맵

### 단계 A. 제품 사실성 정리

1. silent no-op Pipeline 비활성화 또는 Experimental 표시
2. collection shared ACL 문구 수정
3. `values-prod.yaml`을 Production 지원 경로에서 제거
4. 지원 범위를 Portable Core RAG와 AWS Single-Node Reference로 제한
5. Enterprise 기능을 Preview로 명시

**완료 기준:** 성공 상태를 반환하는 모든 기능이 실제 side effect를 수행하고 자동 검증된다.

### 단계 B. 보안 경계 완성

1. 중앙 RBAC/permission enforcement
2. role별 SQL 권한
3. default-deny RLS 및 data path 전체 강제
4. mandatory append-only audit
5. HttpOnly session, CORS allowlist, login abuse protection
6. Kubernetes Pod Security, NetworkPolicy, 최소 RBAC
7. DR IAM 및 실제 복구 drill

**완료 기준:** viewer, disabled user, policy 없는 table, direct data path에 대한 negative acceptance가 모두 통과한다.

### 단계 C. 안전한 릴리스 체계

1. 순번 DB migration
2. CI 검증 artifact promotion
3. final image SBOM, blocking CVE scan, signing, provenance
4. digest 기반 배포
5. staging acceptance 후 Production 승인
6. atomic upgrade와 자동 rollback
7. SemVer, CHANGELOG, upgrade/rollback 정책

**완료 기준:** N-1→N upgrade, migration 실패, application rollback, vulnerable image 차단이 자동 검증된다.

### 단계 D. 자동 acceptance와 운영 증적

Portable Core 자동 acceptance는 최소 다음을 포함한다.

1. 설치 및 admin 초기화
2. collection 생성
3. text/S3 ingest
4. pgvector search
5. cited RAG
6. PII masking
7. owner/viewer ACL
8. source replacement/freshness
9. per-user spend attribution
10. upgrade/rollback

AWS adapter는 별도 staging 계정에서 S3, Bedrock, Aurora/pgvector, Glue/Athena를 검증한다. DR, upgrade, provider exit drill 결과를 정기적으로 보존한다.

### 단계 E. 상용 운영체계

1. 법률 검토된 EE 라이선스
2. SECURITY 및 vulnerability disclosure 정책
3. 지원 채널, severity, 응답 목표
4. compatibility 및 EOL matrix
5. SLA 또는 명시적 best-effort 계약
6. 정기 DR·upgrade·exit drill 증적

## 7. 권장 출시 패키지

현재 상태에서 가장 정직한 패키지는 다음과 같다.

- **Community:** `Portable Core RAG Beta`
- **AWS:** 수동 승인·runbook 기반 `Single-Node Design Partner Reference`
- **Enterprise OIDC:** Preview; 상용 라이선스 확정 전 판매 금지
- **Optional OSS stack:** capability별 Experimental/Community/Reference maturity 표시
- **Pipeline/Spark:** 실제 execution operator와 acceptance 전까지 Experimental 또는 비활성
- **규제·민감 데이터:** 중앙 권한·감사·data-plane 강제가 완료될 때까지 지원 대상에서 제외

## 8. 실행 검증 결과

| 검증 | 결과 |
|---|---|
| Frontend ESLint | PASS |
| TypeScript type check | PASS |
| Next.js production build | PASS |
| Helm lint | PASS |
| Helm 7개 프로필 render | PASS |
| Terraform fmt/main/bootstrap validate | PASS |
| Enterprise OIDC/router tests | 21 passed |
| 추적 Community tests(WebAuthn 제외) | 287 passed, 7 skipped |
| 현재 작업 트리 전체 Community tests | 320 passed, 7 skipped, 6 failed |

전체 Community 실행의 6개 실패는 다음과 같이 구분된다.

- 2개: 미추적 `backend/tests/test_auth.py`와 현재 코드 기대값 차이
- 4개: 로컬 환경에 `webauthn` package가 설치되지 않아 발생

따라서 이번 평가에서는 Python 3.11 clean checkout CI green을 완전히 인증하지 못했다. 테스트 종료 후 실제 Trino 주소를 호출하는 background quality task와 pending task 경고도 확인돼 테스트 격리 개선이 필요하다.

## 9. 평가 제한과 재평가 조건

- live AWS 환경은 중지 상태여서 실제 S3→Bedrock→pgvector→citation 경로를 재검증하지 않았다.
- 실제 복구, upgrade, rollback, failover를 수행하지 않았다.
- GitHub branch protection, Production Environment 승인 등 저장소 외 설정은 확인하지 않았다.
- 취약점 및 라이선스 평가는 저장소의 현재 CI/notice 구성을 기준으로 했으며 final image SBOM 분석은 수행하지 않았다.
- 작업 트리에 평가 시작 전부터 수정·미추적 테스트가 존재해 clean checkout과 완전히 동일한 검증은 아니었다.

다음 재평가는 P0 수정 후 clean checkout에서 다음 증거를 확보한 뒤 수행한다.

1. Python 3.11 전체 Community/Enterprise test green
2. frontend production build 및 browser E2E green
3. Helm all-profile assertion과 final image security gate green
4. staging core/AWS acceptance green
5. N-1 upgrade/rollback과 scratch DR drill green
6. EE 라이선스·지원 문서 법률/운영 승인
