# 배포 파이프라인

DataPond의 빌드·테스트·배포 자동화. 기존의 수동 흐름
(`docker build → save → sudo k3s ctr import → kubectl rollout restart`,
`latest` 단일 태그)을 **CI 게이트 + git-SHA 버전 이미지**로 대체한다.

## 구성 요소

| 워크플로 | 트리거 | 역할 |
|---|---|---|
| `.github/workflows/ci.yml` | PR, main push | **머지 게이트** — backend `pytest`, frontend `tsc`, `helm lint` |
| `.github/workflows/cd.yml` | main push, `v*` 태그 | 이미지 빌드 → **git-SHA 태깅** → GHCR push → (옵션) `helm upgrade` |

## CI — 머지 게이트

PR마다 자동 실행. 하나라도 실패하면 머지 차단:
- **backend-tests**: `backend/tests`의 단위테스트(`pytest`). 서비스 비의존. 루트 `backend/test_*.py`(통합 스크립트)는 제외.
- **frontend-check**: `tsc --noEmit`(타입 게이트), `eslint`(경고는 비차단).
- **helm-lint**: `values-quicktest` lint(게이트) + 전 프로파일 `helm template` 구문 검증.

> 이 게이트는 이번 세션에서 수동 배포 5회가 놓쳤던 `DatabaseURLConnector` NameError 같은 회귀를 머지 전에 잡는다.

## CD — 버전 이미지 + 배포

main 머지 시:
1. `backend`/`frontend` 이미지 빌드
2. **git-SHA 태그**(`sha-<12자>`, 또는 `v*` 태그면 그 값)로 GHCR push
   - `ghcr.io/<owner>/datapond-backend:<tag>`, `…-frontend:<tag>` (+ `latest`)
3. **배포(helm upgrade)** — 기본 비활성. 아래 설정 시 활성화.

### 배포 활성화 (대상 클러스터별 1회 설정)

GitHub repo Settings → Secrets and variables → Actions:
- Variable `ENABLE_CD_DEPLOY` = `true`
- Variable `HELM_VALUES_FILE` = (선택) `helm/datapond/values-onprem.yaml` 등
- Secret `KUBE_CONFIG` = 대상 클러스터 kubeconfig 전체

활성화 시 CD가 자동으로:
```
helm upgrade --install datapond helm/datapond -n datapond \
  --set backend.image.repository=ghcr.io/<owner>/datapond-backend \
  --set backend.image.tag=<sha> --set backend.image.pullPolicy=Always \
  --set frontend.image.repository=ghcr.io/<owner>/datapond-frontend \
  --set frontend.image.tag=<sha> --set frontend.image.pullPolicy=Always
```

### GHCR 이미지 pull (사설 패키지인 경우)
대상 클러스터가 GHCR에서 pull하려면 imagePullSecret이 필요하다(또는 패키지를 public으로):
```bash
kubectl create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io --docker-username=<gh-user> \
  --docker-password=<PAT(read:packages)> -n datapond
# values에 imagePullSecrets 추가 또는 default SA에 연결
```

### 수동 배포 (CD 미활성/긴급 롤백)
이미지는 이미 GHCR에 git-SHA로 있으므로 어떤 커밋이든 결정적으로 배포·롤백:
```bash
helm upgrade datapond helm/datapond -n datapond \
  --values helm/datapond/values-onprem.yaml \
  --set backend.image.repository=ghcr.io/<owner>/datapond-backend \
  --set backend.image.tag=sha-<원하는-커밋> --set backend.image.pullPolicy=Always
```

## 단일 노드 k3s (로컬 dev)
레지스트리 없이 쓰는 기존 방식은 유지 가능:
```bash
bash scripts/build-images.sh   # docker build → k3s ctr images import
kubectl rollout restart deploy/backend deploy/frontend -n datapond
```
단, `latest` 태그라 버전 추적이 안 되므로 **운영 환경엔 CD(git-SHA)를 사용**할 것.

## 에어갭 고객 설치 (별도 모드)
GHCR/CD는 **DataPond 팀 내부** dev→운영 흐름용이다. 고객사 air-gap 설치는
인터넷이 없으므로 **오프라인 번들** 경로를 쓴다:
```bash
sudo bash scripts/bundle-airgap.sh         # 인터넷 머신에서 이미지·차트 번들 생성
sudo bash datapond-airgap-*/install.sh      # 타겟(에어갭) 머신에서 설치
```
> CLAUDE.md상 `bundle-airgap.sh`는 미검증 — 운영 전 검증 필요. 장기적으로는 사내
> 레지스트리(Harbor)로 내재화하면 CD와 에어갭 번들 양쪽에 동일 이미지를 공급할 수 있다.

## 향후 (이 PR 범위 밖)
- 사내 레지스트리(Harbor) 도입 → 에어갭 번들과 CD 통합
- `backend/tests`에 커넥터/Iceberg 통합테스트 추가(현재 단위테스트만)
- 프로덕션 배포에 승인 게이트(GitHub Environments) + 스모크 테스트
