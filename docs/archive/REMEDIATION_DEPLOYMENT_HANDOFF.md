# DataPond Remediation and Deployment Handoff

> 작성 시각: 2026-07-20 07:43 KST
> 상태: 로컬 remediation과 검증은 완료, 커밋 범위 확정·push·신규 배포는 중단 상태
> 주의: 이 문서는 비밀번호, JWT, internal key, AWS access key 등 비밀 값을 포함하지 않는다.

## 1. 작업 목표

보안 blocker, API 계약 단절, 운영 상태 오표현, 접근성 문제를 수정하고 다음 단계까지 진행하는 작업이었다.

- Python 3.11 기준 Community/Enterprise backend 검증
- admin/viewer/internal-key 권한 경계 자동화
- frontend 핵심 오류·반응형·접근성 browser smoke
- Helm/AWS single-node 배포 준비
- 필요한 리소스 변경 후 scoped commit/push
- 확인된 환경에 이미지 배포 및 live acceptance
- 기존 dirty work와 보호 파일 보존

## 2. 완료된 작업

### 2.1 보안 및 권한 경계

- 전역 `X-Internal-Key` 우회를 제거했다.
- internal key는 다음 exact `POST` callback에서만 허용한다.
  - `/api/ai/collections/{name}/ingest-source`
  - `/api/connectors/{id}/sync`
- middleware와 route dependency가 method/path/key를 각각 재검증한다.
- metadata가 없는 request는 fail-closed 한다.
- shared Knowledge collection은 일반 사용자에게 read-only로 유지한다.
- AI backend/model/key/spend, Storage mutation, System settings, service restart/scale/pod delete를 admin-only로 제한했다.
- service log WebSocket은 same-origin cookie JWT를 검증하고 admin만 허용한다.
- pod describe/log/delete는 요청한 service label 소속을 검증한다.

### 2.2 API 및 운영 흐름

- Airflow callback이 runtime `DATAPOND_INTERNAL_KEY`를 사용하도록 정렬했다.
- Kubernetes Role에 필요한 최소 pod delete와 deployment patch/update 권한만 추가했다.
- streaming preview 계약과 multi-step rollback을 정리했다.
- Notebook UI를 backend `/api/notebooks` wrapper로 전환하고 direct Jupyter token/API 접근을 제거했다.
- Notebook CRUD/upload/download/duplicate/kernel/session route 및 입력 검증을 구현했다.
- MLflow Next proxy가 auth와 upstream status/body/header를 보존하도록 수정했다.
- transform create/update/delete를 remote-first ordering과 rollback으로 변경했다.
- `scripts/validate-deployment.sh`를 token-aware, external-DB-aware, read-only-by-default 검증기로 갱신했다.

### 2.3 UI 및 접근성

- Dashboard/Catalog/Storage/System에서 loading/error/empty 상태를 분리했다.
- backend 실패가 정상적인 zero/empty 상태로 보이지 않도록 수정했다.
- viewer에게 scale/restart/pod delete/WebSocket control을 숨겼다.
- nested sidebar active state와 `aria-current`를 보완했다.
- 로그인 non-JSON 오류를 안전하게 처리하고 `role=alert`, password toggle keyboard/ARIA를 보완했다.
- Next.js production cache policy가 development HMR chunk에 적용되지 않도록 조건화했다.

### 2.4 Python 3.11 test harness

다음 테스트의 `get_event_loop().run_until_complete`를 `asyncio.run`으로 정상화했다.

- `backend/tests/test_connector_rag_sink.py`
- `backend/tests/test_query_engine.py`
- `backend/tests/test_rag_ingest.py`
- `backend/tests/test_catalog_backend.py`
- `backend/tests/test_rag_scheduler.py`
- `backend/tests/test_webauthn.py`
- `ee/backend/tests/test_router.py`
- `ee/backend/tests/test_oidc.py`

추가된 request/regression tests:

- `backend/tests/test_auth_acceptance.py`
- `backend/tests/test_security_boundaries.py`
- `backend/tests/test_operational_flows.py`
- `backend/tests/test_ml_integrations.py`

## 3. 마지막 검증 결과

- Community Python 3.11 release-candidate suite: **234 passed, 2 skipped**
- Enterprise Python 3.11 suite: **21 passed**
- auth/security/operations focused acceptance: **29 passed**
- Frontend ESLint: 통과
- TypeScript: 통과
- Next.js production build: **35/35 pages**
- Browser smoke:
  - desktop/mobile horizontal overflow 없음
  - 390×844 login/dashboard 정상
  - accessible login error와 raw parser/HTML 비노출 확인
  - Dashboard/Storage/System unavailable 상태 확인
  - nested Documentation `aria-current="page"` 확인
  - mobile viewer sidebar role 표시 확인
- Helm: **8 profiles lint/render 통과**
- deployment validator mock acceptance: **19 checks passed**
- Python compile, forbidden direct Jupyter pattern, `bash -n`, `git diff --check`: 통과

검증용 `/tmp/datapond-py311`과 임시 Next.js 서버/파일은 정리했다. 재검증 시 disposable Python 3.11 환경을 다시 만들어야 한다.

## 4. 보호 대상 및 알려진 예외

### 4.1 수정하면 안 되는 파일

- `backend/tests/test_auth.py`
- `docs/superpowers/**`

`backend/tests/test_auth.py`는 untracked 상태의 로컬 보호 파일이다. method/path가 없는 request double에서 internal key 허용을 기대하는 stale assertion 한 건이 있다. 현재 보안 정책은 metadata missing 시 fail-closed이므로 해당 test는 `HTTP 401`로 실패하는 것이 의도된 동작이다. 이 test에 맞추기 위해 `backend/app/api/auth.py`의 보안 정책을 완화하면 안 된다.

### 4.2 호환성 불변 조건

- 기존 URL 유지
- 기존 Helm values 파일명 유지
- flat `/api/capabilities` boolean 호환성 유지
- direct `/jupyter/api`, `token=jupyter`, `?token=` 패턴 재도입 금지
- secret/token을 로그, 문서, commit에 저장하지 않기

## 5. Git 상태와 중단 지점

handoff 문서 작성 직전 상태:

- branch: `main`
- HEAD: `d5370c2`
- `HEAD == origin/main`, ahead/behind `0/0`
- tracked modified: **142 files**
- untracked: **11 files**
- 이 handoff 문서 생성으로 untracked 파일이 하나 추가된다.

중요: 작업 시작 전부터 대규모 dirty tree가 있었다. 현재 diff에는 기존 사용자 작업, 제품 문서/화면 개편, 이번 remediation이 혼재한다. 따라서 다음 명령은 사용하면 안 된다.

```bash
# 사용 금지
git add .
git add -A
git commit -am "..."
git push origin main
```

### 5.1 중단된 위치

이전 요청은 “필요한 리소스 변경 → commit → push → 배포”였다. 다음 read-only 확인까지 완료했다.

- current branch/remotes/dirty tree 확인
- Terraform state의 non-secret outputs 확인
- AWS caller/account/region 확인
- EC2, SSM, Aurora, DNS, ECR image tag 상태 확인
- CD/ECR GitHub Actions workflow 확인
- Terraform diff에 실제 resource 변경이 있는지 1차 확인

그 다음 backend/frontend/deployment diff를 독립 분류해 최소 commit 범위를 제안하는 작업을 시작했으나 **분류 도구 실행이 취소되어 결과가 생성되지 않았다.** 이 시점까지 다음 작업은 수행되지 않았다.

- 신규 branch 생성: 안 함
- staging: 안 함
- commit: 안 함
- push: 안 함
- image build/push: 안 함
- Terraform apply: 안 함
- Helm upgrade: 안 함
- live resource mutation: 안 함

### 5.2 중단 원인

1. **커밋 범위 불확실성**: 142개 tracked 수정 중 어느 변경이 기존 사용자 작업인지 자동으로 확정할 수 없었다.
2. **보호 파일 존재**: untracked `backend/tests/test_auth.py`를 commit에서 반드시 제외해야 한다.
3. **main 직접 push 위험**: 현재 branch가 `main`이므로 별도 branch가 필요하다.
4. **GitHub 인증 미설정**: `gh auth status`가 unauthenticated였다. Git HTTPS credential 사용 가능 여부도 확인되지 않았다.
5. **로컬 kubectl 부재**: local kubeconfig 기반 deploy/rollout 검증은 불가능하다.
6. **Terraform plan 입력 부재**: required sensitive variable `db_master_password`를 설정하지 않아 plan이 중단됐다. 값을 로그나 명령 history에 노출하면 안 된다.
7. **운영 변경 확인 필요**: SSM을 통한 remote Helm upgrade와 ECR push는 production mutation이므로 정확한 범위/rollback 확인 후 수행해야 한다.
8. **긴급성 없음**: 기존 public health가 정상이라 안전 검토를 생략할 이유가 없었다.

## 6. 배포 환경의 마지막 확인 상태

2026-07-20 07:31 KST 전후 read-only 확인:

- AWS region: `us-east-1`
- EC2 application node: running
- SSM agent: Online
- Aurora PostgreSQL: available, engine `15.10`
- Aurora deletion protection: enabled
- Aurora backup retention: 14 days
- public `/api/health`: HTTP 200, `{"status":"healthy"}`
- public `/login`: HTTP 200, TLS verification successful
- ECR backend/frontend repositories: immutable `2.3.0-<sha>` tag pattern 사용

구체적인 account ID, instance ID, endpoint는 이 문서에 고정하지 않는다. 로컬 Terraform state에서 다음과 같이 조회한다.

```bash
terraform -chdir=terraform output -raw node_instance_id
terraform -chdir=terraform output -raw node_public_ip
terraform -chdir=terraform output -raw aurora_endpoint
terraform -chdir=terraform output -raw ecr_backend_repo_url
terraform -chdir=terraform output -raw ecr_frontend_repo_url
aws sts get-caller-identity --region us-east-1
```

## 7. 관리자 비밀번호 안전 조회

비밀번호를 문서, shell history, chat, command output capture에 저장하지 않는다.

```bash
NODE_ID=$(terraform -chdir=terraform output -raw node_instance_id)
aws ssm start-session --region us-east-1 --target "$NODE_ID"
```

SSM session 내부에서 본인 터미널로만 확인한다.

```bash
sudo k3s kubectl -n datapond get secret datapond-secrets \
  -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d
printf '\n'
```

확인 후 password manager에 저장하고 terminal scrollback을 정리한다.

## 8. 커밋 후보 범위 — 아직 확정 아님

아래는 remediation과 직접 연결된 후보군이다. **whole-file staging 전에 각 diff를 다시 검토해야 하며, 이 목록은 commit 승인 목록이 아니다.**

### Backend/security/operations

- `backend/app/api/auth.py`
- `backend/app/api/ai_backends.py`
- `backend/app/api/ai_vectors.py`
- `backend/app/api/connectors.py`
- `backend/app/api/mlflow_integration.py`
- `backend/app/api/notebooks.py`
- `backend/app/api/services.py`
- `backend/app/api/storage.py`
- `backend/app/api/streaming.py`
- `backend/app/api/system_settings.py`
- `backend/app/api/transforms.py`
- `backend/main.py`
- 새 regression tests와 Python 3.11-normalized tests

### Frontend

- login/auth error handling
- sidebar active state와 role gating
- Dashboard/Catalog/Storage/System truthful states
- Notebook backend wrapper
- MLflow proxy routes
- service viewer controls
- `frontend/next.config.ts` development cache fix

Frontend에는 제품 UI 개편으로 보이는 큰 diff가 섞여 있으므로 파일/부분 staging 검토가 특히 필요하다.

### Helm/deployment

- `helm/datapond/templates/airflow-deployment.yaml`
- `helm/datapond/templates/backend-deployment.yaml`
- `helm/datapond/templates/rbac-backend.yaml`
- profile values files의 capability/environment 정렬
- `scripts/validate-deployment.sh`
- `docs/AWS_MVP_RUNBOOK.md`

현재 `terraform/variables.tf` diff는 comment-only로 확인됐다. 실제 AWS resource topology 변경이 필요하다는 증거는 아직 없으므로 Terraform apply를 기본 경로로 두지 않는다.

## 9. 안전한 재개 절차

1. 현재 상태를 다시 기록한다.
   ```bash
   git status --short --branch
   git diff --check
   ```
2. backend/frontend/Helm/docs diff를 파일별·필요하면 hunk별로 분류한다.
3. 보호 파일과 기존 사용자 작업을 제외한 확정 목록을 문서화한다.
4. `main`에서 새 branch를 만든다. 예:
   ```bash
   git switch -c remediation/security-ops-deploy
   ```
5. 확정된 파일만 명시적으로 stage한다. `git add .`는 사용하지 않는다.
6. staged diff와 secret pattern을 검토한다.
   ```bash
   git diff --cached --check
   git diff --cached --stat
   git diff --cached
   ```
7. Python 3.11 backend, Enterprise, frontend lint/tsc/build, Helm 8-profile 검증을 재실행한다.
8. 하나의 거대한 commit보다 다음처럼 논리적으로 나누는 방안을 우선 검토한다.
   - security/auth/backend contracts + tests
   - frontend contracts/accessibility
   - Helm/deployment validation/runbook
9. Git 인증을 확인한 뒤 feature branch만 push한다.
10. push된 commit SHA로 고유 ECR tag `2.3.0-<short-sha>`를 생성한다. immutable repository에서 기존 tag를 재사용하지 않는다.
11. 배포 전에 SSM에서 현재 Helm revision, image repository/tag, pod 상태를 기록한다.
12. Terraform apply 없이 기존 AWS single-node K3s에 Helm image tag/resource 변경만 적용하는 것을 우선한다.
13. rollout 실패 시 이전 Helm revision/image tag로 rollback한다.
14. live acceptance:
    - health/login/TLS
    - admin token과 viewer 403
    - internal key non-allowlisted 401
    - exact callback은 dedicated fixture에서만
    - Dashboard/Storage/System truthful error state
    - RAG/Bedrock/pgvector와 optional Glue/Athena

## 10. 재개 전 확인해야 할 결정

- 이번 commit에 기존 제품 문서/화면 개편을 포함할지 여부
- frontend mixed diff를 whole-file로 stage할 수 있는지 또는 hunk 분리가 필요한지
- push할 branch 이름
- 이미지 build/push를 GitHub Actions OIDC로 할지 local Docker/ECR로 할지
- SSM remote Helm upgrade를 실행할 운영 승인
- viewer credential과 dedicated internal-callback fixture 제공 여부
- Terraform 변경이 정말 필요한지; 필요하면 sensitive plan input 전달 방법

이 결정들이 확정되기 전에는 commit, push, Terraform apply, ECR push, Helm upgrade를 진행하지 않는다.
