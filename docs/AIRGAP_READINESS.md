# 에어갭(Air-Gap) 준비도 감사

**작성일**: 2026-06-01
**대상**: 인터넷이 차단된 망분리/에어갭 환경에서의 DataPond 설치·운영 가능 여부
**방법**: helm 차트·values·스크립트·백엔드/프론트 코드 정적 감사

> 제품 포지셔닝은 "온프렘·에어갭·프라이빗 환경을 위한 AI-Native Lakehouse"이나,
> 현 상태는 **부트스트랩(이미지·모델 다운로드)부터 인터넷이 필요**해 에어갭 설치가 사실상 불가능하다.
> 에어갭은 AI만의 문제가 아니라 **플랫폼 전반의 교차 관심사**다.

## 종합 판정: 🔴 **에어갭 미준비 (Not air-gap ready)**

가장 치명적인 것은 **오프라인 번들(`bundle-airgap.sh`)의 이미지 목록이 실제 차트와 심각하게 불일치**한다는 점이다 — 이 번들로 설치하면 핵심 컴포넌트 대부분이 뜨지 않는다.

---

## 1. 이미지 공급 (가장 큰 표면)

### 1-1. 차트가 실제 사용하는 이미지 (values.yaml 기준)

| 컴포넌트 | 이미지 | 레지스트리 | 태그 문제 |
|---|---|---|---|
| frontend/backend/jupyter | `datapond/*` | (사내 빌드) | `latest` |
| postgres | `postgres:16-alpine` | Docker Hub | |
| valkey | `valkey/valkey:7.2.5` | Docker Hub | |
| mlflow | `ghcr.io/mlflow/mlflow:v2.10.0` | GHCR | |
| airflow | `apache/airflow:2.8.1` | Docker Hub | |
| spark | `apache/spark:3.5.8-python3` | Docker Hub | |
| seaweedfs | `chrislusf/seaweedfs:latest` | Docker Hub | ⚠️ `latest` |
| trino | `trinodb/trino:latest` | Docker Hub | ⚠️ `latest` |
| polaris | `apache/polaris:1.4.0` + `apache/polaris-admin-tool:1.4.0` | Docker Hub | |
| risingwave | `risingwavelabs/risingwave:v1.7.0` | Docker Hub | |
| openmetadata | `openmetadata/server:1.3.1` | Docker Hub | |
| elasticsearch | `docker.elastic.co/elasticsearch/elasticsearch:8.10.2` | Elastic registry | |
| litellm | `ghcr.io/berriai/litellm:main-latest` | GHCR | ⚠️ moving tag |
| ollama | `ollama/ollama:latest` | Docker Hub | ⚠️ `latest` |
| init containers | `busybox`, `busybox:1.36`, `postgres:16-alpine` | Docker Hub | ⚠️ `busybox`(태그 없음) |

**갭**
- **3개 레지스트리**(Docker Hub, GHCR, docker.elastic.co)에 분산 → 에어갭은 단일 사내 레지스트리로 미러 필요.
- **moving/latest 태그 다수**(seaweedfs, trino, ollama, litellm, busybox) → 재현성 없음. 에어갭은 번들 시점과 설치 시점이 달라 **반드시 고정 다이제스트/버전**이어야 함.
- **`imagePullSecrets` 미지원**(템플릿 전체에 없음) → 사설 레지스트리(Harbor) 인증 pull 불가.

### 1-2. 🔴 오프라인 번들(`bundle-airgap.sh`) — 차트와 불일치 (치명)

`THIRD_PARTY_IMAGES` 목록이 현재 차트와 어긋난다:

| 번들이 받는 것 | 차트가 쓰는 것 | 판정 |
|---|---|---|
| `redis:7-alpine` | `valkey/valkey:7.2.5` | ❌ Redis→Valkey 마이그레이션 반영 안 됨 |
| `ghcr.io/projectpolaris/polaris:0.5.0` | `apache/polaris:1.4.0` | ❌ 레지스트리·버전 모두 다름 |
| `trinodb/trino:435` | `trinodb/trino:latest` | ❌ 버전 불일치 |
| `mlflow/mlflow:2.10.2` | `ghcr.io/mlflow/mlflow:v2.10.0` | ❌ 레지스트리·버전 다름 |
| `ghcr.io/risingwavelabs/risingwave:v1.6.0` | `risingwavelabs/risingwave:v1.7.0` | ❌ 버전 불일치 |
| `opensearchproject/opensearch:2.11.0` | `docker.elastic.co/.../elasticsearch:8.10.2` | ❌ **OpenSearch≠Elasticsearch** |
| `open-metadata/server:1.2.0` | `openmetadata/server:1.3.1` | ❌ org명·버전 다름 |
| (없음) | `chrislusf/seaweedfs` | ❌ **스토리지 계층 누락** |
| (없음) | `ollama/ollama`, `ghcr.io/berriai/litellm` | ❌ AI 계층 누락 |
| (없음) | `apache/polaris-admin-tool`, `apache/spark`, `busybox` | ❌ 누락 |

→ **이 번들로 에어갭 설치 시 storage·catalog·streaming·metadata·AI 대부분이 기동 실패.** CLAUDE.md의 "bundle-airgap.sh 검증 미완료"는 단순 미검증이 아니라 **실제 깨진 상태**.

### 1-3. 🔴 Ollama 모델 런타임 다운로드

`ollama-deployment.yaml:40` — startup에 `ollama pull <model>`로 **Docker Hub(registry.ollama.ai)에서 모델을 받음**. 번들도 이 모델을 포함하지 않음.
→ *"내부망 LLM"이라면서 부트스트랩에 인터넷이 필요한 모순.* 모델 blob을 사전 적재(PVC 시드 또는 번들)해야 함.

---

## 2. 보안 / 인증서 / 인증

| 항목 | 현재 상태 | 갭 |
|---|---|---|
| TLS 발급 | `values.yaml`/`values-prod.yaml`이 `cluster-issuer: letsencrypt-prod` | 🔴 ACME=인터넷 필요. 에어갭은 내부 CA/사설 인증서. (onprem은 `tls.enabled:false`라 회피하나 HTTPS 미적용) |
| egress 제어 | **NetworkPolicy 없음** | 🟠 외부 유출을 인프라로 막지 못함 — 에어갭 "하드 보장" 부재(앱이 외부를 시도하면 나갈 수 있음) |
| 인증/인가 | `auth.py` 단순 Bearer 토큰 (LDAP/SAML/OIDC **미구현**) | 🟠 내부 LDAP/AD 연동 필요(금융·공공 필수). 외부 IdP(Okta/Azure AD) 연동은 인터넷 의존이라 에어갭 부적합 |

---

## 3. AI / 외부 추론

| 항목 | 현재 상태 | 갭 |
|---|---|---|
| AI provider 폴백 | `ai_sql.py`: LiteLLM → **Bedrock → Anthropic**(외부) → 템플릿. 모드 가드 없음(자격 유무로 암묵 결정, fail-open) | 🔴 에어갭에서 LiteLLM 불가 시 외부 호출 시도(유출 위험). **strict 모드(LiteLLM만, fail-closed) 가드 필요** |
| 설정 | Settings UI + DB로 provider 설정 가능 | 🟡 모드 토글을 UI에만 두면 보장이 약함 → 배포 floor + UI tightening(계층형) 권장 |

---

## 4. 데이터 연동 / 사용자 작업

| 항목 | 현재 상태 | 갭 |
|---|---|---|
| 커넥터 소스 | 외부 SaaS/클라우드(AWS S3, Airbyte, 외부 REST) 지원 | 🟡 에어갭은 내부 소스만 도달 가능 — 정책상 외부 커넥터 차단 옵션 필요 |
| JupyterLab 패키지 | 사용자 노트북 `pip install` | 🟠 인터넷 없으면 실패 → 내부 PyPI 미러(Nexus/devpi) + `pip.conf` 주입 필요 |
| 프론트 폰트 | `layout.tsx`의 `next/font/google`(Inter) | 🟢 Next.js가 **빌드 시 self-host** → 런타임 에어갭 안전. 단 **빌드 머신엔 인터넷 필요** |

---

## 5. 텔레메트리 / phone-home

| 항목 | 현재 상태 | 갭 |
|---|---|---|
| DataPond 앱 자체 | analytics/phone-home **미발견** | 🟢 양호 |
| 서드파티 | Airflow(scarf), OpenMetadata, Elasticsearch 등 자체 텔레메트리 가능 | 🟡 컴포넌트별 텔레메트리 비활성 env 확인·설정 필요 |

---

## 권장 로드맵 (우선순위)

### P0 — 에어갭 설치 자체를 가능하게
1. **`bundle-airgap.sh` 이미지 목록을 차트에서 자동 생성** — 하드코딩 배열 제거, `helm template … | grep image:`로 추출해 항상 일치 보장. 누락(seaweedfs/ollama/litellm/polaris-admin/spark/busybox) 포함.
2. **moving/`latest` 태그 고정** — 전 이미지를 버전/다이제스트 핀. (재현성 + 번들 정합)
3. **Ollama 모델 사전 적재** — 번들에 모델 blob 포함 + PVC 시드(런타임 `ollama pull` 제거 또는 오프라인 폴백).
4. **`imagePullSecrets` 지원** — 사설 레지스트리(Harbor) 인증 pull 가능하게 차트 파라미터화.

### P1 — 주권/보안 하드 보장
5. **AI strict 모드 가드** (계층형: 배포 floor + UI tightening) — 외부 폴백 차단.
6. **NetworkPolicy egress 차단** — 에어갭 강제(앱 가드와 방어 심층화).
7. **내부 CA/사설 TLS** 경로 — letsencrypt 의존 제거 옵션.

### P2 — 규제 충족
8. **LDAP/AD 통합** (외부 IdP 아님).
9. **내부 PyPI 미러** 연동(Jupyter `pip.conf`).
10. 서드파티 텔레메트리 비활성 env 일괄 설정.

## 권장 구조: 통합 `values-airgap.yaml` + 단일 정책

기능별로 흩어진 토글 대신 **하나의 air-gap 프로파일**이 아래를 일관되게 뒤집도록:

| 영역 | connected | **air-gapped** |
|---|---|---|
| 이미지 | public hub/GHCR | 사내 레지스트리(`registry` prefix + pullSecret) / 오프라인 번들 |
| Ollama 모델 | 런타임 pull | 사전 적재 |
| AI | 외부 폴백 허용 | strict(LiteLLM만, fail-closed) |
| egress | 허용 | NetworkPolicy 차단 |
| TLS | Let's Encrypt | 내부 CA/사설 |
| 인증 | 외부 IdP 가능 | 내부 LDAP/AD |
| PyPI(노트북) | 공개 | 내부 미러 |

---

## 다음 단계 제안
가장 ROI 큰 **P0-1(번들 자동 생성) + P0-2(태그 고정)**부터 착수하면, 일단 "에어갭에서 뜨긴 한다"를 확보할 수 있다. 그 위에 P1(주권 가드·egress)로 "데이터가 안 나간다"를 보장한다.

---

## 진행 상태 (2026-06 업데이트)

대부분의 P0/P1 항목이 해소됨:
- ✅ **번들 자동 생성**: `bundle-airgap.sh`가 `helm template`로 차트에서 이미지 목록을 동적 추출(redis≠valkey류 불일치 제거) + digest freeze + 누락 시 fatal.
- ✅ **오프라인 설치**: `install.sh --airgap`이 K3s(번들 바이너리+시스템 이미지 `k3s-airgap-images-*.tar.zst`)·Helm·앱 이미지를 모두 번들에서 적재.
- ✅ **jupyter 이미지 누락 수정(#59)**: `datapond/jupyter`는 `docker/jupyter/Dockerfile` 커스텀 이미지(공개 레지스트리에 없음)인데 번들·설치가 빌드하지 않아 air-gap/온프렘 jupyter가 기동 실패하던 갭 → 두 스크립트에 빌드 단계 추가.
- ✅ **이미지 태그 정합(#59)**: datapond 이미지를 차트 기본값과 동일한 `:latest`로 빌드(이전엔 `:VERSION` 빌드 + 일부 values만 패치해 onprem 프로파일 air-gap이 깨짐) → 전 프로파일이 번들 이미지를 직접 resolve.
- ✅ **AI fail-open 제거**: `AI_EGRESS_POLICY=local-only`로 외부 LLM 차단(fail-closed).
- ✅ **기반 스키마 부트스트랩(#60)**: `auth.sql`/`queries.sql` git 추적 + startup 멱등 적용 → 신규/에어갭 설치 시 핵심 테이블 자동 생성.

### 여전히 미해결
- ❌ **단절 호스트 클린룸 E2E**: 격리 VM에서 번들만으로 부팅→로그인→쿼리→RAG 전 과정 미수행(구성요소 단위 검증만: 차트 이미지 추출 21종, third-party manifest 실재 18종, jupyter 빌드 성공, bash -n).
- ❌ **Ollama 모델 blob 번들 자동 포함**: initContainer는 PVC에 모델이 있을 때만 skip하지, 번들에서 자동 seed하지 않음 → 첫 에어갭 설치는 모델을 PVC에 수동 적재 필요.
- ❌ imagePullSecrets(사설 Harbor), TLS 정적 cert, SSO.
