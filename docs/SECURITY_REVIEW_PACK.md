# 보안 심사 자료 (Security Review Pack)

**대상:** 도입을 검토하는 고객사의 정보보호 담당·IT팀이 보안성 검토 문서에 그대로 옮겨 쓸 수 있게 정리한 자료.
**기준:** chart 2.7.0, AWS Single-Node Reference, 2026-11-16. 각 항목에 **근거 위치**(코드·설정·문서)를 적었다.
**표기:** ✅ 구현·검증됨 · 🟡 구현됐으나 설정이 필요하거나 제한 있음 · ⬜ 아직 없음(계획). 없는 것을 있다고 쓰지 않는다.

## 1. 배포 모델과 데이터 위치

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 고객 계정 안 배포 | ✅ | 전 구성요소가 고객 AWS 계정·VPC 안에서 돈다. 벤더가 운영하는 SaaS 경로는 없다. | `terraform/`, `docs/DEPLOY_SINGLE_NODE.md` |
| 데이터 위치 | ✅ | 테이블 데이터: 고객 S3(Iceberg). 앱 상태·벡터·감사: 고객 Aurora PostgreSQL. 리전은 고객이 선택. | `docs/ARCHITECTURE.md` |
| 외부 전송 | 🟡 | 기본 외부 호출은 고객이 지정한 모델 제공자(Bedrock, 같은 계정·리전)뿐. 로컬 모델만 쓰는 프로필(Sovereign Core)은 외부 송신 정책 `local-only`로 강제. | `AI_EGRESS_POLICY`, `docs/SOVEREIGN_CORE_PROFILE.md` |
| 고가용성 | 🟡 | 레퍼런스는 **단일 노드**(EC2 + K3s). 복구 목표: Aurora 복원 약 30–60분, 노드 재구축 약 1.5–4시간. 운영용 HA 토폴로지는 로드맵. | `docs/DISASTER_RECOVERY.md` |

## 2. 암호화

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 전송 구간 | ✅ | 외부 접속은 HTTPS(Let's Encrypt, DNS-01). Aurora 연결은 TLS(`sslmode=require`). | `helm/datapond/values-prod-single.yaml`, `externalDatabase.sslmode` |
| 저장 — DB | ✅ | Aurora 스토리지 암호화(KMS). | `terraform/aurora.tf` (`storage_encrypted = true`) |
| 저장 — S3 | ✅ | 기본 SSE(AES-256), 버전 관리, 퍼블릭 접근 차단. | `terraform/s3.tf` |
| 저장 — 노드 디스크 | ✅ | 루트 볼륨 암호화(K3s 데이터스토어와 클러스터 Secret 포함), 일일 스냅샷 7개 보관. | `terraform/ec2.tf`, `terraform/dlm.tf` |
| 저장된 자격 증명 | ✅ | 소스 DB 비밀번호 등은 앱이 Fernet으로 암호화해 DB에 저장. 키(`ENCRYPTION_KEY`)는 Kubernetes Secret과 AWS Secrets Manager 보관함에 이중 보관(2026-11-13 일치 확인). | `backend/app/connectors/vault.py`, `docs/DISASTER_RECOVERY.md` |

## 3. 인증과 접근 통제

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 사용자 인증 | ✅ | 로컬 계정, 패스키(WebAuthn), LDAP/AD(선택), OIDC SSO(상용 이미지). 콘솔 세션은 HttpOnly 쿠키, 상태 변경 요청은 동일 출처만. | `backend/app/api/auth.py` |
| 역할 기반 권한 | ✅ | 7개 역할(관리자·데이터 엔지니어·AI 엔지니어·데이터 사이언티스트·분석가·감사·열람자). API에서 강제하며 화면 숨김에 의존하지 않음. 비관리자 역할 라이브 검증(2026-11-13). | `backend/app/permissions.py`, `docs/PERSONA_REVIEW_2026-11.md` |
| 기계 계정 | ✅ | 서비스 계정 키: 범위 지정, 만료, 교체(유예 기간), 키별 요청 한도(429). 키나 IdP 토큰은 관리자 권한을 얻을 수 없음. | `backend/app/api/service_account_routes.py` |
| 데이터 접근 | ✅ | 카탈로그별 권한(거부 시 카탈로그 이름도 노출하지 않음), 행 필터·컬럼 마스킹(SQL 실행 경로), 쓰기 문장은 별도 권한. | `backend/app/catalog_access.py`, `backend/app/rls/` |
| 직접 엔진 접속 통제 | 🟡 | 쿼리 엔진(Trino)은 클러스터 내부 전용, 외부 노출 없음. 엔진 수준 접근 통제(Layer 2)는 선택 기능, 기본 꺼짐. | `docs/RLS_DESIGN.md` |
| 외부 IdP 토큰(리소스 서버) | 🟡 | 구현됐으나 기본 꺼짐, 실제 IdP와의 실연동 검증 전. | README "Roadmap or hardening" |

## 4. 네트워크와 인프라

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 인바운드 | ✅ | 443/80만 허용(허용 CIDR 지정 필수), SSH 없음(관리는 SSM). | `terraform/ec2.tf` 보안 그룹 |
| 클러스터 내부 | ✅ | NetworkPolicy 기본 거부, 필요한 연결만 허용. 인스턴스 메타데이터는 AWS를 호출하는 파드만. | `helm/datapond/templates/networkpolicy.yaml` |
| 인스턴스 메타데이터 | ✅ | IMDSv2 필수(토큰). | `terraform/ec2.tf` |
| IAM | ✅ | 노드 역할은 필요한 S3·Glue·Bedrock·ECR 권한만, 배포 역할(OIDC)은 `main` 브랜치에서만, SSM 명령은 태그로 제한. | `terraform/iam.tf`, `terraform/github-oidc.tf` |
| 이미지 | ✅ | ECR 태그 불변(IMMUTABLE): 배포된 이미지는 덮어쓸 수 없음. | `terraform/ecr.tf` |

## 5. 감사와 증적

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 감사 범위 | ✅ | 권한 결정(모든 거부 + 쓰기 허용), 로그인·계정·권한 변경, 카탈로그·정책 변경, 도구 호출(검색·답변·SQL·임베딩, 거부 포함), 동기화 대상 재생성·작업 정리. | `backend/app/api/` 각 감사 기록, `tool_call_log` |
| 변조 방지 | ✅ | 감사 테이블은 DB 트리거로 UPDATE/DELETE 차단, 앱은 테이블 소유자가 아닌 런타임 역할(SELECT·INSERT만)로 접속. 스토리지 수준 WORM은 아님. | `migrations/0005_audit_append_only.sql`, `0012_audit_worm_role.sql` |
| 보존 | ✅ | 기본 365일(설정 가능), 단일 리더가 공인된 함수로만 정리. | `AUDIT_RETENTION_DAYS`, `backend/app/audit_retention.py` |
| 내보내기 | ✅ | NDJSON 내보내기(감사 로그, 도구 호출), 컴플라이언스 리포트. | `GET /api/audit/export` |
| 누락 방지 검사 | ✅ | 코드가 쓰는 감사 이벤트 종류가 모두 DB 목록에 있는지 테스트로 강제(2026-11-13 결함 발견 후 추가). | `backend/tests/test_audit_event_types.py` |

## 6. 개인정보 보호

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 한국형 식별자 탐지·마스킹 | ✅ | 주민등록번호(체크섬)·휴대전화·사업자등록번호·이메일·카드(Luhn)·자격 증명. 문서 적재, 검색 결과·인용에서 재마스킹. | `backend/app/guardrails/pii_ko.py` |
| 동기화 시 마스킹 | ✅ | DB 소스 동기화는 Trino `SELECT` 안에서 마스킹 — 원본 값이 레이크에 들어가지 않음. **직접 지정한 개인정보 컬럼은 패턴이 안 맞아도 값 전체를 `[개인정보]`로 대체**(이름·주소). | `backend/app/connectors/trino_sync.py` |
| 증적 화면 | ✅ | 동기화된 모든 테이블을 샘플 검사해 원본 개인정보 잔존 여부를 표시·NDJSON 내보내기. 라이브 첫 검사에서 실제 누락 2건 발견·수정(2026-11-13), 과거 스냅샷까지 정리. | Governance → Data Protection, `backend/app/pii_evidence.py` |
| 한계 | 🟡 | 자동 검사는 패턴이 있는 값만 찾는다. 이름·주소는 컬럼을 직접 지정해야 한다. | 위 화면 안내 |

## 7. 취약점·공급망 관리

| 항목 | 상태 | 내용 | 근거 |
|---|---|---|---|
| 의존성 취약점 스캔 | ✅ | 모든 PR과 main에서 Trivy(HIGH·CRITICAL 발견 시 실패, 기준선 0). | `.github/workflows/ci.yml` |
| SBOM | 🟡 | 모든 CI 실행에서 CycloneDX 1.6 SBOM 생성·90일 보관(빌드 아티팩트 `sbom-cyclonedx`, 2026-11-16 실행 기준 구성요소 188개). 프런트엔드는 lockfile 기준 운영 의존성 전체, **백엔드는 `requirements.txt`에 선언된 패키지만**(간접 의존성 제외). 이미지 기준 SBOM은 계획. | 같은 파일 |
| 라이선스 | ✅ | 직접 의존성 라이선스 게이트, 선택 add-on 라이선스 고지. | CI `license-gate`, `THIRD_PARTY_NOTICES.md` |
| 배포 무결성 | ✅ | CI 통과 커밋만 main에 머지, 불변 이미지 태그, 배포 전 사전 점검(노드 자원). | `scripts/preflight.py` |
| 패치 정책 | ⬜ | **초안(확정 전):** CRITICAL 7일, HIGH 30일 안에 수정 이미지 배포. 장기 지원 브랜치 없음 — 최신 이미지로 업그레이드해 받는다. | `SUPPORT.md` (정책 확정 시 갱신) |
| 침투 테스트 | ⬜ | **수행하지 않았다.** 제3자 침투 테스트는 첫 유료 고객 전 수행 예정(범위: 콘솔·API·MCP·서비스 계정 키·소스 연합 조회). | — |
| 인증(ISMS-P 등) | ⬜ | 제품 인증 없음. 고객사의 인증 범위 안에서 운영되는 구성요소로 심사받는 형태. | — |

## 8. 알려진 한계 (심사에서 먼저 말할 것)

- 단일 노드 레퍼런스: 노드 장애 시 재시작·재구축 동안 서비스 중단. Spot 인스턴스는 용량 부족으로 시작이 늦어질 수 있다(운영용은 온디맨드 권장).
- 감사 테이블은 DB 수준 append-only이지 스토리지 WORM이 아니다(필요 시 NDJSON을 고객의 WORM 저장소로 정기 반출).
- 엔진 수준 접근 통제(Layer 2) 기본 꺼짐: DataPond 콘솔·API 경로 밖에서 엔진에 직접 붙는 클라이언트(예: QuickSight 직접 연결)는 행 필터가 적용되지 않는다(`docs/QUICKSIGHT.md`).
- 레퍼런스 고객 없음, 제3자 침투 테스트 없음, 제품 인증 없음.

## 9. 고객이 요청할 수 있는 추가 자료

- 최신 SBOM(CycloneDX JSON), 최신 Trivy 결과 — CI 아티팩트.
- 아키텍처·데이터 흐름도 — `docs/ARCHITECTURE.md`.
- 개인정보 증적 NDJSON, 감사 로그 NDJSON 샘플 — 고객 PoC 환경에서 생성.
- 재해 복구 절차와 실측 기록 — `docs/DISASTER_RECOVERY.md`.
