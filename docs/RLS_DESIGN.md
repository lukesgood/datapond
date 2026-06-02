# DataPond Row-Level Security (RLS) 설계안

> 상태: 설계(Draft) · 작성일 2026-06-02 · 대상 미완성 항목: "Row-level security"
> 전제: DataPond는 **단일 조직 주권형 lakehouse**다. 멀티테넌트 SaaS가 아니라 **조직 내부의
> need-to-know(알 필요 원칙)** 충족이 목적이다 — 부서·지점·보안등급 단위 행 격리.

---

## 1. 현황 분석 — 이미 있는 것 vs 빠진 것

RLS는 **그린필드가 아니다.** 데이터 모델은 `backend/schema/auth.sql`에 이미 설계돼 있다.

### 이미 있는 것 (스키마)
- `users.attributes JSONB` — RLS용 사용자 속성 (예: `{"department":"eng","region":"us-east","clearance":"secret"}`)
- `rls_policies` — (catalog, schema, table, **filter_expression**, enabled, priority)
- `rls_policy_roles` — 정책↔역할 매핑 + `is_exempt`(면제)
- `column_masking_policies` + `masking_policy_roles` — 컬럼 마스킹 (full/partial_email/hash/null/custom)
- `roles`/`permissions`/`user_roles` — 5개 시스템 역할 + `security.manage_rls`/`manage_masking`/`view_policies` 권한
- `auth_audit_log` + `audit_event_type`에 `rls_policy_created/updated/deleted`, `masking_policy_*` 이벤트

### 빠진 것 (핵심 — 이 설계의 범위)
1. **강제 엔진(enforcement engine)** — `rls_policies`를 읽어 실제 쿼리에 행필터/컬럼마스킹을 적용하는 코드. **전무.**
2. **인증 배선** — `queries.py`가 `require_user`를 안 쓰고 `MOCK_USER_ID` + 공유 Trino 유저(`datapond`)로 접속. 사용자 신원이 쿼리 계층에 전달되지 않음.
3. **스키마 실제 적용 여부** — 런타임 `auth.py`는 축소된 users 테이블(role VARCHAR admin/viewer, attributes 없음)을 쓴다. `auth.sql` 전체 스키마가 배포돼 있는지 확인 필요.
4. **다중 쿼리 경로 거버넌스** — Trino 외에 **JupyterLab→DuckDB→SeaweedFS 직접 읽기** 경로는 Polaris/Trino를 우회한다(아래 §6 리스크).

---

## 2. 목표 & 비-SaaS 매핑

| SaaS 워크숍 | DataPond (단일 조직) | 필터 기준 예시 |
|---|---|---|
| `tenant_id` 행 격리 | 부서/지점/등급 행 격리 | `department`, `branch_id`, `classification` |
| TVM(STS 세션태그) | JWT → Trino 세션 유저 + 속성 | `users.attributes` |
| Lake Formation 행필터 | **RLS 엔진**(이 설계) | `rls_policies.filter_expression` |
| QuickSight RLS | DataPond Dashboards | 동일 엔진 경유 |

**규제 근거**: FSS 전자금융감독규정(부서 차단벽), 개인정보보호법(최소수집), 의료 EMR 거주성, 국방 clearance — 내부 사용자라도 업무 범위만 접근했음을 **기술적으로 강제+감사**해야 한다.

---

## 3. 아키텍처 — 다층 강제(defense in depth)

```
┌────────────────────────────────────────────────────────────────┐
│ 사용자 (JWT: sub, role, + 해석된 attributes)                    │
└───────────────┬────────────────────────────────────────────────┘
                │
   ┌────────────▼─────────────┐         ┌──────────────────────────┐
   │ Backend SQL Lab          │         │ 직접 Trino 접속           │
   │ (queries.py)             │         │ (BI 도구, JDBC)           │
   │  └ RLS 엔진(Layer 1)     │         │  └ Trino 네이티브(Layer 2)│
   └────────────┬─────────────┘         └────────────┬─────────────┘
                │  user=실유저, 필터/마스킹 주입       │ rules.json 행필터+마스크
                ▼                                      ▼
        ┌───────────────────────── Trino ─────────────────────────┐
        │  Polaris(iceberg) 카탈로그 → Iceberg(SeaweedFS)          │
        └──────────────────────────────────────────────────────────┘
                ▲
   ┌────────────┴─────────────┐
   │ JupyterLab → DuckDB →    │  ⚠ Layer 3 갭: S3 직접 읽기는
   │ SeaweedFS S3 직접        │     RLS 우회 (§6)
   └──────────────────────────┘
```

### Layer 1 — Backend RLS 엔진 (MVP, 1순위)
SQL Lab/Dashboards/AI SQL 등 **백엔드를 경유하는 모든 쿼리**의 단일 choke point(`queries.py`)에서 강제.

처리 순서:
1. `require_user`로 인증 강제 → `user_id`, `role(s)`, `attributes` 로드.
2. 쿼리에서 참조 테이블 식별 → 각 테이블에 적용되는 `rls_policies`(역할 매칭, `is_exempt` 제외, admin 면제) 조회.
3. `filter_expression` 템플릿의 `current_user_attribute('region')`을 **사용자 실제 값으로 바인딩**.
4. 행필터/컬럼마스킹을 쿼리에 주입(아래 §4).
5. `user=<실유저>`로 Trino 접속(공유 `datapond` 유저 대신) → Trino 측 식별/감사 일치.
6. 적용된 정책 + 최종 SQL을 `auth_audit_log`에 기록.

### Layer 2 — Trino 네이티브 강제 (방어심화, 2순위)
직접 Trino 접속(BI/JDBC)은 백엔드를 안 거치므로 Layer 1로 못 막는다.
→ `rls_policies`/`column_masking_policies`에서 **Trino file-based access control(`rules.json`)** 를 생성·마운트.
Trino는 `rowFilters`/`columnMasks`를 **엔진 내부에서** 적용하므로 SQL 파싱이 불필요(가장 견고).
백엔드가 정책 변경 시 ConfigMap을 재생성하고 Trino를 reload 한다.

> **권장**: Layer 2(Trino 네이티브)를 최종 강제 수단으로 삼고, Layer 1은 UX(미리보기·설명·차단 사유 표시)와 비-Trino 경로용으로 둔다. 네이티브 행필터는 임의 SQL 재작성보다 안전하다.

### Layer 3 — 직접 S3 경로 (갭 — §6에서 별도 처리)

---

## 4. 핵심 메커니즘

### 4.1 속성 바인딩
`filter_expression` 예: `region = current_user_attribute('region') AND classification <= current_user_clearance()`
- Layer 1: 백엔드가 `users.attributes->>'region'`을 읽어 **리터럴로 안전 치환**(SQL 인젝션 방지: 화이트리스트 + 파라미터화).
- Layer 2: Trino 세션 속성/`current_user` 기반 함수로 매핑.

### 4.2 정책 결합 규칙
- 한 테이블에 여러 정책 → `priority` 순으로 **AND 결합**(가장 제한적).
- 사용자 역할 중 하나라도 `is_exempt=true` → 해당 정책 면제(예: 감사역).
- `admin` 역할 → 전체 RLS 우회(설정 가능 토글, 규제 환경에선 끌 수 있어야 함).
- 정책 없는 테이블 → **기본 동작은 정책으로 결정**: `default_deny`(화이트리스트) vs `default_allow`(블랙리스트). 규제 환경 기본값 = `default_deny` 권장(설정화).

### 4.3 행필터 주입 (Layer 1 방식 선택지)
| 방식 | 설명 | 장단점 |
|---|---|---|
| **A. 보안 뷰(secure view)** | 테이블별 `v_<table>` 뷰 생성(필터 내장), 베이스 테이블 직접권한 회수, 쿼리의 테이블 참조를 뷰로 치환 | 견고·재사용↑ / 뷰 관리·치환 필요 |
| **B. 서브쿼리 치환** | `FROM t` → `FROM (SELECT * FROM t WHERE <filter>) t` 로 AST 재작성 | 유연 / SQL 파서 필요(sqlglot), 엣지케이스 위험 |
| **C. Trino 네이티브** | rules.json `rowFilters` | 가장 견고 / Trino 한정 |

→ **MVP: C(네이티브) 우선, 비-Trino/미리보기엔 A(보안 뷰).** B(임의 재작성)는 신뢰성 문제로 비권장.

### 4.4 컬럼 마스킹
`column_masking_policies` → Trino `columnMasks`(Layer 2) 또는 SELECT 리스트 치환(Layer 1):
`email` → `regexp_replace(email,'(^.).*(@.*$)','$1***$2')`, `ssn`→`'***-**-'||substr(ssn,8)`, `hash`→`to_hex(sha256(...))`, `null`→`NULL`.

---

## 5. 통합 지점 (코드)

| 파일 | 변경 |
|---|---|
| `backend/app/api/queries.py` | `require_user` 의존성 추가, `MOCK_USER_ID` 제거, Trino `connect(user=실유저)`, RLS 엔진 호출 |
| `backend/app/rls/engine.py` (신규) | 정책 조회·속성 바인딩·필터/마스킹 적용·감사 |
| `backend/app/rls/trino_acl.py` (신규) | `rls_policies`→`rules.json` 생성기(Layer 2) |
| `backend/app/api/governance.py` | RLS/마스킹 정책 **CRUD** 엔드포인트 + `auth_audit_log` 기록 (현재 audit/pii/stats만 있음) |
| `backend/app/api/auth.py` | JWT에 역할(복수)·`attributes` 포함, `attributes` 관리 엔드포인트 |
| `helm/.../trino-*.yaml` | file-based access control plugin + 생성된 rules ConfigMap 마운트 |
| `frontend/app/governance/` | 정책 관리 UI(테이블 선택·필터식·역할·마스킹·미리보기) |

---

## 6. 미해결 리스크 (반드시 명시)

1. **DuckDB 직접 S3 우회 (가장 큰 갭)**: JupyterLab→DuckDB→SeaweedFS는 Polaris/Trino를 안 거쳐 **RLS가 적용 불가**. 행수준 격리는 원본 parquet 직접 읽기에서 강제할 수 없다.
   - 완화책: (a) 탐색 쿼리도 Trino 경유 강제, (b) SeaweedFS 자격을 **prefix 스코프**로 발급해 *silo(테넌트/부서별 경로) 격리*만 보장(행수준은 불가), (c) 민감 테이블은 직접 읽기 차단·뷰만 노출. → 규제 데이터는 (a)/(c) 권장.
2. **SQL 재작성 신뢰성**: 임의 SQL에 필터를 안전히 주입하긴 어렵다 → Layer 2(네이티브)로 회피.
3. **성능**: 필터가 파티션 컬럼(예: `region`)과 정렬되면 영향 최소. 비파티션 컬럼 필터는 스캔 증가 → 정책 컬럼을 파티션 키로 권장.
4. **인젝션**: 속성 치환은 화이트리스트·타입검증·리터럴 이스케이프 필수.
5. **기본 거부 vs 허용**: 잘못 설정 시 과잉 차단/누출. 테이블별 명시적 등록 + 기본 `default_deny`.

---

## 7. 단계별 구현 계획

| 단계 | 산출물 | 규모 |
|---|---|---|
| **P0** | `auth.sql` 전체 스키마 실제 적용 확인/마이그레이션, `users.attributes` 관리 UI/API | S |
| **P1 (MVP)** | `queries.py` 인증 배선 + Trino 실유저 접속 + RLS 엔진(보안 뷰 또는 네이티브) + 감사 로깅 | M |
| **P2** | `governance.py` 정책 CRUD + 프론트 정책 관리 UI + 컬럼 마스킹 | M |
| **P3** | Layer 2 Trino `rules.json` 생성기 + Helm 배선(직접 Trino 강제) | M |
| **P4** | DuckDB 갭 완화(탐색 Trino 강제 또는 prefix 격리) + 민감테이블 정책 | L |

---

## 8. 확정된 결정 (2026-06-02 lock)

1. **1차 강제 계층 = Hybrid** — Trino 네이티브 `rules.json`(P3)을 최종 강제로, 백엔드 엔진(P1)은
   MVP 단계의 실제 행필터 + 미리보기/차단사유 표시 + 비-Trino 경로용. (P3 전까지는 백엔드 엔진이 실강제.)
2. **정책 없는 테이블 = `default_deny`** — RLS 정책이 명시적으로 등록된 테이블만 접근 허용(화이트리스트).
   미등록 테이블 참조 시 fail-closed. 파싱 불가 SQL도 deny.
3. **admin = 기본 RLS 적용**, 환경변수 `RLS_ADMIN_BYPASS`(기본 false)로만 우회 허용.
4. **DuckDB 갭 = 민감테이블 직접읽기 차단** — RLS 정책이 있는(=민감) 테이블은 DuckDB/S3 직접읽기
   차단, 뷰/Trino 경로만 노출. 정책 없는 테이블은 탐색 허용.

### MVP(P0+P1) 강제 알고리즘 (백엔드)
```
요청(user, sql)
 ├ require_user (인증 강제)
 ├ sqlglot 파싱 → 참조 테이블 추출
 │    └ 파싱 실패 → DENY (default_deny)
 ├ 각 테이블:
 │    ├ 정책 0건 → DENY (default_deny; admin이고 RLS_ADMIN_BYPASS=true면 허용)
 │    └ 정책 ≥1건 → 사용자 역할 매칭·is_exempt·priority AND결합 → bound filter
 │         └ FROM tbl  →  FROM (SELECT <마스킹된 컬럼> FROM tbl WHERE <bound filter>) tbl
 ├ Trino connect(user=실유저)로 실행
 └ auth_audit_log 기록 (적용 정책 id, 최종 SQL 해시, 결과)
```
데모 검증 정책: `iceberg.sales.orders`를 `region = current_user_attribute('region')` 으로 격리.
