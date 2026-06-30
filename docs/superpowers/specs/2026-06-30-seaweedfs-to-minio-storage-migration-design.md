# SeaweedFS → MinIO + Unified S3 Endpoint — Migration Design

**작성일**: 2026-06-30
**상태**: 설계 (구현 전, 승인 대기)
**상위**: AWS 피보팅 ([PRODUCT_CONCEPT](../../PRODUCT_CONCEPT.md)) — "AWS-Native" 정합성 강화
**선행**: PR #100 (AWS MVP) 머지 완료

---

## 1. 목표

1. **base 기본값을 AWS 네이티브 S3로** — 프로필 없는 `helm install`이 AWS S3를 향함 ("AWS-Native" 정체성).
2. **로컬/온프렘은 SeaweedFS → MinIO**로 교체 (표준 S3 호환, path-style 친화).
3. **모든 스토리지 소비처(8곳)가 단일 `.Values.storage.endpoint`/자격증명을 읽도록 통일** — 현재 `seaweedfs-s3:8333` 하드코딩 제거. 이로써 AWS 프로필에서도 lakehouse 서비스가 올바른 스토리지(S3)를 가리킴.
4. **coredns virtual-host 해킹은 단계적 제거** — 우선 MinIO ClusterIP로 재지정·유지, Polaris path-style 검증 후 별도 제거.

## 1b. 단계 분할 (확정)

사용자 결정: **단계적으로 쪼개서 진행.**

- **Stage 1 (이 계획) — SeaweedFS → MinIO 교체**: MinIO 템플릿 추가, SeaweedFS 템플릿 제거, 소비처 8곳을 `seaweedfs-s3:8333` → `minio:9000`으로 **재지정**(개별 endpoint 유지), coredns를 MinIO로 재지정, values 프로필 정리(중복 블록 제거). 각 단계가 렌더 가능 상태 유지.
- **Stage 2 (후속) — base AWS 기본 + endpoint 통일**: base 기본값을 AWS 네이티브 S3로, 8곳을 `.Values.storage.endpoint` 단일 소스로 통일(`_helpers.tpl`), 자격증명 endpoint-게이팅. AWS에서 lakehouse 서비스가 S3에 연결되도록.
- **Stage 3 (후속) — coredns 완전 제거** (Polaris path-style 검증 후), IRSA, MinIO 분산.

아래 §2~§7은 전체 그림이며, 본 계획서는 **Stage 1만** 구현한다.

## 2. 결정 (확정)

| 항목 | 결정 |
|---|---|
| base 기본 스토리지 | **AWS S3 네이티브** (`storage.provider: s3`, `endpoint: ""`, `seaweedfs/minio.enabled: false`) |
| 로컬/온프렘 스토리지 | **MinIO** (단독 단일노드, `minio.enabled: true`, `endpoint: "minio:9000"`) |
| coredns | **단계적 제거** — MinIO ClusterIP로 재지정·유지(`minio.enabled` 게이트), 검증 후 후속 제거 |
| 자격증명 | endpoint 설정 시(MinIO) 정적 키 주입, 비었을 때(AWS) 생략(IAM 역할/IRSA) — backend `storage.py` 패턴을 모든 소비처로 확장 |

## 3. 컴포넌트 변경

### 추가
- `helm/datapond/templates/minio-deployment.yaml` — MinIO Deployment + Service(`minio:9000`) + PVC. `{{- if .Values.minio.enabled }}` 게이트.
- `helm/datapond/templates/minio-bucket-init-job.yaml` — post-install/upgrade Job: `mc`/aws-cli로 `iceberg`(+필요 버킷) 생성. (기존 `seaweedfs-bucket-init-job.yaml` 로직 이식, endpoint/creds는 storage 값에서.)

### 제거
- `helm/datapond/templates/seaweedfs-deployment.yaml`
- `helm/datapond/templates/seaweedfs-bucket-init-job.yaml`

### 수정 — 엔드포인트/자격증명 통일 (소비처 8곳)
모든 곳에서 `http://seaweedfs-s3:8333` → `{{ .Values.storage.endpoint }}` 기반으로, **path-style=true 유지**, 자격증명은 endpoint 설정 시에만 주입:
- `polaris-deployment.yaml` (AWS_ENDPOINT_URL_S3 / AWS_S3_FORCE_PATH_STYLE / creds)
- `spark-config-configmap.yaml` (iceberg.s3.endpoint, hadoop.fs.s3a.endpoint, path-style)
- `trino-deployment.yaml` (s3.endpoint, s3.path-style-access)
- `risingwave-statefulset.yaml` (meta/compute/compactor RW_S3_ENDPOINT, RW_S3_PATH_STYLE_ACCESS, creds)
- `mlflow-deployment.yaml` (MLFLOW_S3_ENDPOINT_URL, creds)
- `jupyter-deployment.yaml` (S3 endpoint, creds)
- `backend-deployment.yaml` (이미 `.Values.storage.endpoint` 사용 — 자격증명 게이팅도 이미 적용됨)
- `secrets.yaml` — `S3_ACCESS_KEY/SECRET_KEY`(범용) 중심으로, `minio.enabled || seaweedfs.enabled` 대신 `storage.endpoint` 존재로 게이트. 레거시 `SEAWEEDFS_*` 키는 호환 별칭으로 한시 유지 가능.

### 재지정
- `coredns-custom-configmap.yaml` — 게이트를 `seaweedfs.enabled` → `minio.enabled`로, A레코드 대상을 `minio` ClusterIP로, 매치 도메인을 `*.minio.<ns>.svc...`로. (단계적: 유지하되 MinIO 대응.)

### values 파일
- `values.yaml`(base): `seaweedfs:` 블록 제거(또는 enabled:false), `minio.enabled:false`, `storage: {provider: s3, endpoint: "", region: us-east-1}`.
- `values-aws.yaml`: 변경 없음(이미 S3 네이티브) — 단, lakehouse 서비스가 이제 storage.endpoint를 읽으므로 AWS에서 S3로 올바르게 연결됨.
- `values-dev / values-quicktest / values-onprem / values-prod`: `minio.enabled:true`, `seaweedfs` 블록 제거, `storage.endpoint:"minio:9000"`, `provider:minio`, MinIO clusterIP(coredns용). **중복 `seaweedfs:` 블록 정리.**

## 4. 단일 소스 헬퍼 (DRY)
`templates/_helpers.tpl`에 `datapond.s3.endpoint`/`datapond.s3.pathStyle` 헬퍼를 추가해 8곳이 동일 로직을 공유 — 하드코딩·중복 제거.

## 4b. Stage 2 carry-notes (Stage 1 최종 리뷰에서 발견)

- **AWS lakehouse 자격증명 갭**: `values-aws`(minio.enabled=false)에서 Polaris/RisingWave/MLflow가 여전히 `minio:9000` + `SEAWEEDFS_S3_*` 키를 무조건 참조 → 활성 시 `CreateContainerConfigError`. (기존과 동일, 악화 아님.) Stage 2의 endpoint 통일 + 자격증명 endpoint-게이팅(IAM/IRSA)으로 해소.
- **RisingWave S3 설정은 사실상 vestigial**: meta가 `--state-store hummock+memory`라 MinIO를 안 씀 → `RW_S3_*` env와 `storage.bucket: risingwave`는 불필요(init job도 이 버킷을 안 만듦). Stage 2에서 정리.
- **이미지 태그 `:latest`**(minio/minio, minio/mc): 재현성 위해 digest/버전 핀 (Stage 2).
- **base values.yaml**: `minio.enabled:true`인데 `minio.clusterIP` 없음 → 프로필 없는 bare 렌더는 coredns required 실패(기존 seaweedfs와 동일 패턴, CI는 프로필별 렌더라 무영향). base를 AWS 기본으로 바꿀 때(Stage 2) 자연 해소.
- `configmap.yaml`의 `MINIO_ENDPOINT/MINIO_CONSOLE_ENDPOINT`는 현재 소비처 없음(dead) — 필요 시 활용 또는 제거.

## 5. 범위 밖 (YAGNI / 후속)
- **AWS IRSA 완전 구성** (lakehouse Pod들이 S3에 IAM 역할로 접근) — 본 마이그레이션은 endpoint/creds 배선을 통일하고 "endpoint 비면 정적키 생략"까지만. 실제 AWS에서 Polaris/Spark 등이 IAM 역할로 S3 접근하려면 IRSA/ServiceAccount 주석이 별도 필요(EKS 작업과 함께).
- **coredns 완전 제거** — 본 작업은 MinIO로 재지정까지. Polaris path-style 검증 후 별도.
- **MinIO 분산 모드(prod HA)** — 우선 단독. prod 분산은 후속.
- 데이터 마이그레이션 — 불필요(dev/onprem 신규 생성; 기존 SeaweedFS 데이터 이전 없음).

## 6. 리스크
- **Polaris S3FileIO virtual-host** — coredns를 MinIO로 재지정해 완화. 제거는 검증 후.
- **검증 한계** — helm 미설치 로컬 → 렌더 검증은 CI(helm chart lint)가 모든 프로필 렌더로 수행. MinIO/Polaris 런타임 동작은 실제 배포 시 검증(런북 확장).
- **자격증명 게이팅 회귀** — endpoint 존재 여부로 키 주입을 가르므로, 각 프로필에서 키 누락/잔존 없는지 CI 렌더 + 점검.

## 7. 검증 전략
- CI `Helm chart lint`(모든 values-* 렌더)로 템플릿 정합성 — base/aws/dev/prod/onprem/quicktest 전부 렌더 성공.
- `helm template`으로 프로필별 S3 env가 기대 endpoint(빈값=AWS / minio:9000)로 나오는지 grep 검증.
- 배포 검증(런북): MinIO 프로필에서 Iceberg 쓰기·Trino 쿼리·RAG 동작; AWS 프로필은 PR #100 런북 + lakehouse 서비스 S3 연결.
