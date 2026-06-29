# 📦 아카이브: 이전 컨셉 (OSS Open Lakehouse)

DataPond는 **AWS 특화 AI 데이터 기반**으로 피보팅했습니다 (2026-06-30).
피보팅 이전의 컨셉인 **"AI-Native Open Lakehouse Platform — 벤더 중립 OSS Databricks 대안"**의
모든 문서는 아래 위치에 보관되어 있습니다.

## 어디에 보관되어 있나

| 항목 | 위치 |
|---|---|
| **Git 태그** | `v3.0-oss-lakehouse` — 이전 컨셉의 마지막 상태 |
| **아카이브 브랜치** | `archive/oss-lakehouse` — 피보팅 시점의 전체 스냅샷(옛 문서 포함) |

## 이전 문서를 보려면

```bash
# 태그 또는 브랜치 체크아웃
git checkout v3.0-oss-lakehouse
# 또는
git checkout archive/oss-lakehouse

# 특정 문서만 꺼내 보기 (main 유지한 채)
git show archive/oss-lakehouse:docs/PRODUCT_CONCEPT.md
git show archive/oss-lakehouse:README.md
```

## 이전 컨셉 요약

- **포지셔닝**: 벤더 중립, 1/10 비용 OSS Databricks 대안
- **스택**: SeaweedFS · Iceberg · Trino · Spark · Airflow · MLflow · JupyterLab · LiteLLM · Valkey · Polaris · RisingWave · DuckDB · OpenMetadata (K8s/Helm)
- **아카이브된 주요 문서**: `PRODUCT_CONCEPT.md`, `ARCHITECTURE.md`, `GO_TO_MARKET_PLAN.md`, `LAB_GUIDE.md`, `DATABRICKS_FEATURE_COMPARISON.md` 등 (`docs/` 전체) + `START_HERE.md`, `QUICKSTART.md`, `PROJECT_SUMMARY.md`, `COMPLETION_REPORT.md`, `SCRIPT_FIXES.md`

## ⚠️ 코드는 아직 마이그레이션 전입니다

`helm/`, `docker/`, `scripts/`, `.claude/` 디렉토리의 코드/설정은 **이전 OSS 아키텍처를
구현한 것**으로, 아직 새 AWS 컨셉으로 옮겨지지 않았습니다. 새 아키텍처 코드는
피보팅 설계 스펙의 **Phase 2~3**에서 작성됩니다. 그 전까지 이 코드는 이전 컨셉의
참고용으로만 보십시오.

---

새 컨셉: [README.md](README.md) · [설계 스펙](docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md)
