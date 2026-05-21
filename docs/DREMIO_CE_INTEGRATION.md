# Dremio Community Edition — 벤치마크 분석 및 자체 구현 전략

**작성일**: 2026-05-18
**버전**: 2.0.0
**목적**: Dremio CE 기능 분석 후 DataPond 자체 구현 방향 결정

---

## 📌 결정: 통합하지 않고 벤치마크한다

Dremio CE를 DataPond에 컴포넌트로 통합하는 방안을 검토했으나, **자체 구현(벤치마크)**이 올바른 방향이다.

---

## 🔑 Dremio CE 분석 결과

| 항목 | 내용 |
|------|------|
| **라이선스** | Apache License 2.0 |
| **CE에 포함된 것** | Reflections(수동), Virtual Datasets, Spaces, Arrow Flight, 직접 파일 쿼리, JDBC 커넥터 40+ |
| **CE에 없는 것** | **RLS, 컬럼 마스킹, LDAP/SSO** (모두 Enterprise only) |
| **카탈로그** | Nessie 전용 — Polaris(REST Catalog) 미지원 |

---

## ❌ 통합을 선택하지 않는 이유

### 이유 1: DataPond 타겟 고객에게 필요한 것이 CE에 없다

```
DataPond 타겟 = 금융·공공·의료·국방 (규제 환경)

규제 고객 필수 기능              Dremio CE 지원 여부
─────────────────────────────────────────────────
행 수준 보안 (RLS)            →  ❌ Enterprise only
컬럼 마스킹                   →  ❌ Enterprise only
LDAP / AD 통합                →  ❌ Enterprise only
쿼리 수준 감사 로그            →  ❌ Enterprise only

CE가 제공하는 것               DataPond 자체 구현 가능 여부
─────────────────────────────────────────────────
Virtual Datasets              →  ✅ Trino VIEW + UI
Spaces                        →  ✅ DB 모델 + UI
Reflections (수동)            →  ✅ Iceberg MV + UI
Arrow Flight                  →  ✅ Trino 설정 1줄
직접 파일 쿼리                →  ✅ Trino Hive connector
```

CE가 주는 기능은 DataPond가 자체 구현할 수 있고,  
DataPond 고객에게 결정적인 기능(RLS, 마스킹)은 CE에 없다.

### 이유 2: 통합 비용이 편익보다 크다

```
필수 선행 작업:
  Polaris → Nessie 카탈로그 마이그레이션 (2주)
  Trino, Spark, RisingWave 설정 전면 재작업

추가 리소스:
  Nessie:    +512MB RAM
  Dremio CE: +8~16GB RAM  ← 현재 전체 스택과 맞먹는 수준

아키텍처 문제:
  쿼리 엔진 2개 공존 (Trino + Dremio)
  "이 쿼리는 어디서?" → 사용자 혼란
  인증 시스템 이중화 (DataPond JWT + Dremio 별도 계정)

라이선스 리스크:
  HashiCorp(Terraform), Elastic: Apache 2.0 → BSL 전환 선례
  외부 제품 의존 → DataPond 로드맵 통제 불가
```

### 이유 3: 자체 구현이 결과물이 더 낫다

Trino 기반으로 구현하면 Dremio CE보다 DataPond 고객에게 더 적합한 제품이 나온다.

| 기능 | Dremio CE | DataPond 자체 구현 |
|------|-----------|-------------------|
| Virtual Datasets | ✅ | ✅ (Trino VIEW + UI) |
| Spaces | ✅ | ✅ (DB + UI) |
| Reflections | ✅ (수동) | ✅ (Iceberg MV + 추천) |
| Arrow Flight | ✅ | ✅ (Trino 설정) |
| 직접 파일 쿼리 | ✅ | ✅ (Trino Hive) |
| **행 수준 보안** | ❌ | **✅ (Trino ACL)** |
| **컬럼 마스킹** | ❌ | **✅ (Trino masking)** |
| **LDAP/SSO** | ❌ | **✅ (DataPond 자체)** |
| **스트리밍 쿼리 통합** | ❌ | **✅ (RisingWave)** |
| **ML 인라인** | ❌ | **✅ (MLflow 연동)** |
| **단일 인증** | ❌ (이중) | **✅** |
| **Polaris 유지** | ❌ (Nessie 필요) | **✅** |

---

## ✅ 자체 구현 전략: DataPond SQL Workbench

Dremio CE의 좋은 UX를 참조 기준(벤치마크)으로 삼아,  
DataPond의 기존 스택(Trino + Polaris + Iceberg) 위에서 동등 이상의 기능을 구현한다.

### 목표 아키텍처 (변경 없음)

```
분석가                    엔지니어                데이터 사이언티스트
    ↓                         ↓                          ↓
DataPond SQL Workbench    DataPond UI               JupyterLab
  Managed Views             Airflow                  DuckDB
  Spaces (협업)             Spark                    MLflow
  MV 관리 (가속)            RisingWave               LiteLLM
  직접 파일 쿼리
  RLS + 컬럼 마스킹  ← Dremio CE에 없는 것
  LDAP/SSO          ← Dremio CE에 없는 것
    ↓                         ↓
         Trino (단일 쿼리 엔진)
                  ↓
         Apache Polaris (현행 유지)
                  ↓
         SeaweedFS + Apache Iceberg
```

---

## 🗺️ 구현 로드맵

### Phase 1 — SQL Workbench 핵심 (4주, 엔지니어 2명)

Dremio의 Sonar SQL Workbench를 벤치마크 삼아 DataPond 전용으로 구현.

**Arrow Flight 활성화 (1일)**
```properties
# Trino config.properties에 추가 — 설정만으로 완료
flight.enabled=true
flight.server.port=32010
```
→ Tableau, Power BI가 Arrow Flight로 Trino에 직접 연결 가능.  
→ Dremio CE의 BI 연결 속도와 동등.

**SQL 에디터**
```
Monaco Editor (VS Code 동일 엔진)
  + Polaris 카탈로그 자동완성 (테이블 / 컬럼)
  + LiteLLM 연동: "자연어 → SQL" 버튼
  + 실행 결과 테이블 + Chart.js 시각화
  + 쿼리 저장 / 히스토리
```

**직접 파일 쿼리 UI**
```sql
-- Trino Hive connector (이미 지원) 위에 UI만 추가
-- SeaweedFS 경로 입력 → 스키마 자동 추론 → 즉시 쿼리
SELECT * FROM hive."s3a://raw-uploads/orders_2026.csv" LIMIT 100;
```
→ 파일 브라우저 UI에서 파일 선택 → "Query" 버튼 한 번.

---

### Phase 2 — Managed Views + Spaces (3주, 엔지니어 2명)

**Managed Views (Virtual Datasets 벤치마크)**

Dremio CE의 Virtual Datasets와 동등한 기능을 Trino VIEW로 구현.  
차이점: Polaris 카탈로그에 버전 관리되므로 Dremio보다 추적성이 높다.

```sql
-- DataPond SQL Workbench에서 분석가가 생성
-- UI: "New Managed View" 버튼 → SQL 입력 → 저장
CREATE OR REPLACE VIEW "analytics"."customer_revenue" AS
SELECT
    c.customer_name,
    c.segment,
    SUM(s.revenue)  AS total_revenue,
    COUNT(s.id)     AS order_count
FROM iceberg.raw.sales_fact  s
JOIN iceberg.raw.customers   c ON s.customer_id = c.id
GROUP BY 1, 2;
```

Polaris에 뷰 메타데이터 저장 → OpenMetadata 자동 리니지 추적.

**Spaces (협업 워크스페이스)**

```
DB 테이블: workspaces, workspace_members, saved_queries

My Space (개인)
├── 내가 만든 Managed View
├── 저장된 쿼리
└── 실험 작업

Analytics Team (공유)
├── official_kpi_view   ← 공식 지표
├── monthly_reports     ← 팀 공유
└── bi_exports          ← Tableau 연결용
```

---

### Phase 3 — 규제 기능 (Dremio CE에 없는 것) (4주, 엔지니어 2명)

이 단계에서 DataPond는 Dremio Enterprise도 부분 초과한다.

**행 수준 보안 (RLS)**
```java
// Trino system access control plugin 구현
// DataPond 사용자 컨텍스트 → 쿼리에 자동 WHERE 절 주입

public class DataPondAccessControl implements SystemAccessControl {
    @Override
    public void checkCanSelectFromTable(
            SystemSecurityContext ctx, CatalogSchemaTableName table) {
        // 사용자의 부서/역할 조회
        String dept = userService.getDepartment(ctx.getIdentity().getUser());
        // Trino 쿼리 플랜에 row filter 자동 추가
        // → 서울 지점 직원은 서울 거래만, 전국 관리자는 전체 조회
    }
}
```

**동적 컬럼 마스킹**
```java
// 동일 Trino plugin에서 컬럼 마스킹 정책 적용
@Override
public Optional<ViewExpression> getColumnMask(
        SystemSecurityContext ctx, CatalogSchemaTableName table, String column, Type type) {

    MaskPolicy policy = policyRepo.findPolicy(table, column);
    if (policy == null) return Optional.empty();

    boolean canUnmask = roleService.hasPrivilege(ctx.getIdentity(), "UNMASK", table, column);
    if (canUnmask) return Optional.empty();

    return switch (policy.type()) {
        case FULL    -> Optional.of(new ViewExpression("'***'"));
        case PARTIAL -> Optional.of(new ViewExpression(
                           "CONCAT(SUBSTRING(" + column + ", 1, 3), '***')"));
        case HASH    -> Optional.of(new ViewExpression("TO_HEX(SHA256(TO_UTF8(" + column + ")))"));
    };
}
```

**DataPond UI에서 정책 관리**
```
[카탈로그] → [테이블: customers] → [보안] 탭
  컬럼별 마스킹 정책:
    email    → 부분 마스킹 (j***@example.com)
    ssn      → 전체 마스킹 (***)
    phone    → 해시 (SHA256)
  
  행 필터:
    분석가 그룹 → branch = current_user_branch()
    DBA 그룹   → (필터 없음)
```

---

### Phase 4 — Materialized View 관리 (3주, 엔지니어 1명)

Dremio CE Reflections의 기능적 동등물을 Trino + Iceberg MV로 구현.

**MV 관리 UI**
```
[SQL Workbench] → 쿼리 실행 후 → "이 쿼리 가속하기" 버튼

팝업:
  집계 키: [segment ▾] [order_date ▾]
  측정값:  [SUM(revenue) ✓] [COUNT(*) ✓]
  갱신 주기: [매시간 ▾]
  
  → "MV 생성" 클릭
  → CREATE MATERIALIZED VIEW 자동 실행
  → 다음 실행부터 MV에서 읽음 (0.1초 vs 원본 30초)
```

**MV 추천 시스템 (Dremio Autonomous Reflections 벤치마크)**
```python
# 쿼리 로그 분석 → 반복 패턴 탐지 → MV 추천
# (Dremio CE는 수동, DataPond는 반자동으로 동등 수준 달성)

def analyze_query_log(window_hours=24):
    frequent_patterns = db.query("""
        SELECT normalized_query, COUNT(*) as freq,
               AVG(duration_ms) as avg_duration
        FROM query_log
        WHERE created_at > NOW() - INTERVAL '{h} hours'
          AND duration_ms > 5000   -- 5초 초과 쿼리만
        GROUP BY normalized_query
        HAVING COUNT(*) >= 3       -- 3회 이상 반복
        ORDER BY freq * avg_duration DESC
    """, h=window_hours)

    for pattern in frequent_patterns:
        notify_user(
            f"이 쿼리가 지난 {window_hours}시간 동안 {pattern.freq}회 실행됐습니다. "
            f"평균 {pattern.avg_duration/1000:.1f}초 소요. "
            f"Materialized View를 만들면 0.1초로 단축됩니다.",
            action="MV 생성하기"
        )
```

---

## 📊 최종 기능 매트릭스

DataPond SQL Workbench 완성 후 Dremio CE와 비교:

| 기능 | Dremio CE | DataPond (완성 후) |
|------|-----------|-------------------|
| SQL 에디터 + 자동완성 | ✅ | ✅ |
| Virtual Datasets / Managed Views | ✅ | ✅ |
| Spaces (개인/팀 협업) | ✅ | ✅ |
| Reflections / MV 관리 | ✅ (수동) | ✅ (반자동 추천) |
| Arrow Flight BI 연결 | ✅ | ✅ |
| 직접 파일 쿼리 | ✅ | ✅ |
| 40+ 외부 소스 커넥터 | ✅ | ✅ (Trino) |
| **행 수준 보안 (RLS)** | ❌ Enterprise | **✅** |
| **동적 컬럼 마스킹** | ❌ Enterprise | **✅** |
| **LDAP / SSO** | ❌ Enterprise | **✅** |
| **쿼리 수준 감사 로그** | ❌ Enterprise | **✅** |
| **실시간 스트리밍 쿼리** | ❌ | **✅ (RisingWave)** |
| **ML 실험 인라인** | ❌ | **✅ (MLflow)** |
| **자연어 → SQL (AI)** | 제한적 | **✅ (LiteLLM)** |
| **단일 인증** | ❌ (이중) | **✅** |
| **에어갭 완전 지원** | △ | **✅** |
| **추가 RAM 필요** | +8~16GB | **0 (기존 Trino 활용)** |

---

## 🎯 포지셔닝

```
Dremio CE가 할 수 있는 것 → DataPond도 다 한다.
Dremio CE가 못 하는 것   → DataPond는 한다.
DataPond가 Dremio CE에 의존하지 않는다.
```

규제 환경 고객에게:
> "Dremio Enterprise에서 돈 내야 쓸 수 있는 RLS·컬럼마스킹·SSO가  
> DataPond에서는 기본으로 포함됩니다.  
> 분석가 셀프서비스 UI도 동등 수준입니다.  
> 그리고 실시간 스트리밍, ML, AI까지 하나의 플랫폼에서."

---

## 📋 구현 우선순위 요약

| 단계 | 내용 | 기간 | 비고 |
|------|------|------|------|
| **P0** | Arrow Flight 활성화 (Trino 설정) | 1일 | 즉시 가능 |
| **P0** | SQL Workbench MVP (에디터 + 실행 + 결과) | 4주 | 2명 |
| **P0** | 직접 파일 쿼리 UI | 1주 | 1명 |
| **P1** | Managed Views + Spaces | 3주 | 2명 |
| **P1** | RLS + 컬럼 마스킹 (Trino plugin) | 4주 | 2명 |
| **P2** | MV 관리 UI + 추천 시스템 | 3주 | 1명 |
| **총** | **~3.5개월** | | **엔지니어 2명 기준** |
