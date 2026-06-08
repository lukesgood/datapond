# LiteLLM Integration for DataPond

**최종 수정**: 2026-05-11  
**버전**: 2.0.0 (구현 완료)  
**목적**: 실제 구현된 AI SQL Assistant 아키텍처 및 설정 가이드

---

## 개요

DataPond의 AI SQL Assistant는 LiteLLM(OpenAI 호환) 추상화를 통해 LLM을 사용합니다.
Query Lab에서 자연어로 입력하면 Trino SQL로 변환합니다.

**API 엔드포인트**: `POST /api/ai/sql`

### ⭐ BYO-LLM 기본 (Bring Your Own LLM)

**DataPond는 LLM을 기본적으로 co-locate하지 않습니다.** 7B 모델은 4~8GB RAM + CPU 추론이
무거워 lakehouse와 같은 노드(특히 단일/소형 노드)에 띄우면 자원·성능에 부담이 큽니다.

- **기본**: `ai.llmEndpoint`(OpenAI 호환 base URL)를 **고객 사내 LLM**(vLLM/Ollama/LiteLLM 등)으로 설정.
  - helm: `--set ai.llmEndpoint=http://my-llm.internal:8000`
  - 또는 Settings UI → System → AI에서 엔드포인트 설정(런타임 즉시 반영).
  - 비우면 AI(자연어 SQL)만 비활성(템플릿 폴백)되고 나머지 기능엔 영향 없음.
- **옵션(co-located)**: `litellm.enabled`(인클러스터 게이트웨이) / `ollama.enabled`(모델 서버) — 기본 OFF.
  GPU/여유 자원 보유 대규모 배포에서만, 가능하면 전용 노드에 스케줄.
- **주권**: "내부망 LLM" = 내부 엔드포인트를 가리키는 것이지 lakehouse 노드에 co-locate하는 것이 아님.
  BYO 엔드포인트를 사내 LLM으로 두면 데이터 주권을 지키면서 단일 노드 부담을 없앤다.

---

## Provider Fallback Chain

외부 연결이 없는 에어갭 환경부터 클라우드 환경까지 자동으로 적합한 provider를 선택합니다.

```
[자연어 입력]
      │
      ▼
1. LiteLLM Proxy (litellm:4000)
   └─ Ollama backend (qwen2.5-coder:7b)
   → on-prem 환경, values-onprem.yaml에서 활성화
      │ 실패 또는 미설정 시
      ▼
2. AWS Bedrock
   └─ us.anthropic.claude-haiku-4-5-20251001-v1:0
   → AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 환경변수 필요
      │ 실패 또는 미설정 시
      ▼
3. Anthropic API (직접)
   └─ claude-haiku-4-5
   → ANTHROPIC_API_KEY 환경변수 필요
      │ 실패 또는 미설정 시
      ▼
4. 스키마 템플릿 (항상 성공)
   └─ 카탈로그 스키마 기반 기본 SELECT 쿼리 반환
```

---

## Helm 환경별 설정

### values-quicktest.yaml (단일 노드, 15 GB RAM)

```yaml
litellm:
  enabled: false    # RAM 부족으로 비활성화

ollama:
  enabled: false    # RAM 부족으로 비활성화
```

AI SQL은 Bedrock 또는 Anthropic API fallback으로 동작합니다.
Settings UI에서 API key를 설정하면 됩니다.

### values-onprem.yaml (온프레미스 프로덕션, 32 GB+)

```yaml
litellm:
  enabled: true
  replicas: 1
  image: ghcr.io/berriai/litellm:main-latest
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "1Gi"
      cpu: "500m"

ollama:
  enabled: true
  model: "qwen2.5-coder:7b"    # initContainer에서 auto-pull
  resources:
    requests:
      memory: "8Gi"
      cpu: "2"
    limits:
      memory: "12Gi"
      cpu: "4"
  persistence:
    size: "30Gi"                # 모델 파일 저장
```

### values-aws.yaml (EKS + Bedrock)

```yaml
litellm:
  enabled: false    # Bedrock 직접 사용

ollama:
  enabled: false    # 불필요

# Bedrock 설정은 IAM Role 또는 환경변수로 주입
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
```

---

## Settings UI에서 설정

Settings → System 탭 → AI SQL Assistant 섹션:

| 필드 | 설명 | 예시 |
|------|------|------|
| Provider URL | LiteLLM 엔드포인트 | `http://litellm:4000` |
| API Key | LiteLLM master key | `sk-...` |
| Bedrock Region | AWS Bedrock 리전 | `us-east-1` |
| Anthropic API Key | 직접 Anthropic 사용 시 | `sk-ant-...` |

설정은 `system_settings` 테이블에 암호화(CredentialVault)되어 저장됩니다.
Backend 재시작 시 자동으로 복원됩니다 (retry 5회).

**설정 API:**
```
GET  /api/settings/system/ai    — 현재 AI 설정 조회
PATCH /api/settings/system      — 설정 저장
```

---

## kubectl로 직접 설정

Settings UI 대신 환경변수로 주입하는 방법:

```bash
# Anthropic API Key 설정
kubectl set env deployment/backend \
  ANTHROPIC_API_KEY=sk-ant-xxxx \
  -n datapond

# AWS Bedrock 설정
kubectl set env deployment/backend \
  AWS_ACCESS_KEY_ID=AKIA... \
  AWS_SECRET_ACCESS_KEY=... \
  AWS_DEFAULT_REGION=us-east-1 \
  -n datapond

# LiteLLM endpoint (내부 서비스 자동 감지, 필요시 오버라이드)
kubectl set env deployment/backend \
  LITELLM_URL=http://litellm:4000 \
  -n datapond
```

---

## Ollama 모델 관리

Ollama는 StatefulSet으로 배포되며 initContainer가 모델을 자동으로 pull합니다.

```bash
# 현재 로드된 모델 확인
kubectl exec -it ollama-0 -n datapond -- ollama list

# 추가 모델 pull (선택)
kubectl exec -it ollama-0 -n datapond -- ollama pull codellama:13b

# 모델 테스트
kubectl exec -it ollama-0 -n datapond -- \
  ollama run qwen2.5-coder:7b "Write a SQL query to count rows in a table"
```

**권장 모델:**
- `qwen2.5-coder:7b` — 기본값, SQL 코드 생성에 최적화, 8 GB RAM
- `qwen2.5-coder:14b` — 더 높은 품질, 16 GB RAM 필요
- `codellama:7b` — 일반 코드 생성, SQL은 qwen이 더 우수

---

## LiteLLM ConfigMap

`helm/datapond/templates/litellm-deployment.yaml`의 ConfigMap은 다음과 같이 구성됩니다:

```yaml
model_list:
  - model_name: default
    litellm_params:
      model: ollama/qwen2.5-coder:7b
      api_base: http://ollama:11434

router_settings:
  fallbacks:
    - default
```

---

## 단일 노드 제약 사항

**values-quicktest.yaml** 환경 (15 GB RAM):
- LiteLLM pod: disabled (`litellm.enabled: false`)
- Ollama pod: disabled (`ollama.enabled: false`)
- AI SQL은 Bedrock 또는 Anthropic API fallback으로만 동작
- Settings UI에서 API key를 직접 입력하거나 `kubectl set env`로 주입

**메모리 사용 현황 (단일 노드 기준, 2026-05-11):**
- 총 20개 pod Running
- Helm revision 49
- RAM 97% request 사용 중
- LiteLLM/Ollama 활성화 시 추가 8~12 GB 필요

---

## 문제 해결

### AI SQL "timeout" 오류

Ingress 타임아웃 설정 확인:
```yaml
# Ingress annotation (traefik)
traefik.ingress.kubernetes.io/request-timeout: "120s"
```

### LiteLLM pod Pending

```bash
kubectl describe pod -l app=litellm -n datapond
# "Insufficient memory" → values-quicktest에서 disabled 확인
```

### Ollama 모델 로딩 느림

initContainer에서 모델을 pull합니다. 첫 배포 시 qwen2.5-coder:7b 기준 약 5-10분 소요.
```bash
# 진행 상황 확인
kubectl logs -f ollama-0 -n datapond -c init-pull-model
```

### Bedrock 인증 실패

```bash
# IAM 권한 확인 (bedrock:InvokeModel 필요)
kubectl exec -it deployment/backend -n datapond -- \
  aws bedrock list-foundation-models --region us-east-1
```

---

## 외부 LLM 거버넌스 & RAG (2026-06 업데이트)

LiteLLM을 단일 게이트웨이로 두고 신뢰성·관측성·비용·가드레일을 통합 관리한다. 모든 AI(자연어→SQL, RAG, 임베딩)는 게이트웨이의 OpenAI 호환 엔드포인트를 경유한다.

### 모델 폴백 (신뢰성)
`values.yaml` `litellm.fallbacks`가 `config.yaml`의 `router_settings.fallbacks`로 렌더된다. `num_retries`는 같은 모델 재시도뿐이라 모델 장애/스로틀 시 페일오버가 없었다. 폴백은 1차 model_name → 백업 model_name 목록.
```yaml
litellm:
  fallbacks:
    - default: ["default-fallback"]   # primary 실패 시 백업 모델로
```
검증: `mock_testing_fallbacks: true` 요청 파라미터로 1차 강제 실패 → 백업 응답 확인.

### 사용자별 비용 귀속 (멀티테넌시)
백엔드가 chat/embed 호출 payload에 OpenAI `user` 필드 + `metadata`(app/user_id/username)를 실어 LiteLLM이 `end_user`별 spend_logs를 집계한다. 요청 단위 `ContextVar`(`app/ai_context.py`)로 설정되어 모든 호출부에 전파(`asyncio.to_thread` 포함). `GET /api/settings/ai/usage`의 `users[]`로 노출, Settings→AI "By user" 표.

### 비용 대시보드
`GET /api/settings/ai/usage`(총/모델별/키별/사용자별 spend·토큰), `GET /api/settings/ai/spend/report?start_date&end_date`(날짜범위), `GET /api/settings/ai/budget-alerts`(키 예산 임박). 롤업 미집계 시 `/global/spend/models`(usage)가 더 신뢰.

### 관측성
`litellm.metrics: true` → `/metrics`(Prometheus) + Service에 `prometheus.io/{scrape,port,path}` 어노테이션(스크레이프 자동발견). `litellm.tracing`(opt-in, 기본 off) → `config.yaml callbacks`에 provider(langfuse) 추가 + `LANGFUSE_*` env. 백엔드(Prometheus/Langfuse) 실배포는 환경별 판단.

### 가드레일
한국 PII(`app/guardrails/pii_ko.py`)를 `/ai/sql`·`/ai/rag`·`/ai/search`·ingest 전 경로에서 LLM 호출 전 마스킹/차단(`PII_GUARDRAIL_MODE`). 게이트웨이 Presidio 등은 `litellm.guardrails` passthrough로 환경별 opt-in(서비스 별도 배포 필요).

### egress 정책 (주권/에어갭)
`AI_EGRESS_POLICY`(`ai.egressPolicy`): `local-only`(외부 Bedrock/Anthropic/OpenAI/Gemini 차단, 로컬 Ollama/vLLM만, fail-closed) vs `cloud-allowed`. onprem=local-only 기본, aws/quicktest=cloud-allowed.

## Vector 스토어 & RAG (AI 데이터 플랫폼)

pgvector 기반. `ai_collections`/`ai_chunks(embedding vector(N), HNSW cosine)`. 임베딩·chat 모두 게이트웨이 경유(egress 정책 적용 = 주권 모드면 무유출).

- **API**: `POST /ai/embed`, `GET/POST/DELETE /ai/collections`, `POST /ai/collections/{name}/ingest`(텍스트), `/ingest-source`(iceberg 테이블 컬럼 / S3 객체), `/schedule`(Airflow 주기 재임베딩 DAG), `POST /ai/search`, `POST /ai/rag`.
- **임베딩 모델**: `ai.embedModel`/`ai.embedDim`(=`AI_EMBED_MODEL`/`AI_EMBED_DIM`, 기본 embed/1024). LiteLLM에 등록 필요 — 주권=로컬 bge-m3/mxbai(1024), 클라우드=Bedrock Titan v2(1024). dim 변경 시 ai_chunks 재생성.
- **rerank(opt-in)**: `AI_RERANK_MODEL`(`ai.rerankModel`) 설정 시 후보 과적재→`/v1/rerank` 재정렬→top-k. 미설정 시 벡터 순서.
- **컬렉션 RLS**: `ai_collections.owner_id` — 소유자/admin + 공용(owner NULL) 접근, 삭제는 owner/admin.
- **예약 DAG 인증**: 무인증 콜백 방지 — DAG가 `DATAPOND_INTERNAL_KEY`(=secret `INTERNAL_API_KEY`)를 `X-Internal-Key`로 전송, `require_user_or_internal`이 수락.
- **Ingestion→RAG 브릿지**: Knowledge Ingest 카탈로그 드롭다운 + Catalog 'Send to Knowledge'(✨). 커넥터 sync로 Iceberg에 적재된 테이블의 텍스트 컬럼을 임베딩.
