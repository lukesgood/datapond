# Lakehouse P0 구현 계획 — 적재 경로 · 파티셔닝 · 테이블 유지보수

**작성일**: 2026-05-29
**대상**: DataPond Lakehouse 코어 최소 기능요건 충족
**범위**: P0 3개 항목 (AI 기능 제외)
**근거 점검**: `backend/app/connectors/iceberg_writer.py`, `backend/app/api/connectors.py`, `helm/datapond/templates/trino-deployment.yaml`, `helm/datapond/templates/polaris-*.yaml`
**스파이크 검증**: 2026-05-29, 운영 클러스터(z13/k3s) backend pod에서 PyIceberg 0.11.1 + pyarrow 실측

---

## ✅ 스파이크 검증 결과 (2026-05-29)

**PyIceberg ↔ Polaris REST + SeaweedFS S3 호환성 = 검증 완료.** 실 클러스터에서 라운드트립 수행.

| 검증 항목 | 결과 | 비고 |
|-----------|------|------|
| Polaris REST 접속 (OAUTH2 `polaris-client:***`, scope `PRINCIPAL_ROLE:ALL`) | ✅ | warehouse=`iceberg` |
| 네임스페이스 생성 | ✅ | |
| 테이블 생성 | ✅ | |
| **SeaweedFS S3에 Parquet 직접 쓰기 (`append`)** | ✅ | **핵심 호환 지점 — 통과** |
| 읽기 라운드트립 (`scan().to_pandas()`) | ✅ | |
| **인젝션 문자열을 데이터로 안전 저장** (`row-0'; DROP TABLE x--`) | ✅ | P0-1 보안 목표 입증 |
| **append 2회 → 스냅샷 2개** | ✅ | **행 단위 폭발 없음 — P0-1 핵심 입증** |
| **파티션 진화 + 파티션 경로 쓰기** | ✅ | `data/ts_day=2026-01-01/…parquet` 디렉터리 분기 확인 |
| 파티션 컬럼 필터 스캔 | ✅ | |

### 스파이크로 확정된 구현 사항 (계획 반영됨)

1. **파티션 생성 방식 = `update_spec` (컬럼명 기반)**. 직접 `PartitionSpec(PartitionField(source_id=…))`를 조립하면 `assign_fresh_partition_spec_ids`가 스키마 field-id 매칭에 실패한다(스파이크 1차 FAIL). **검증된 패턴**: 테이블을 스키마로 생성 → `with tbl.update_spec() as us: us.add_field("ts", DayTransform(), "ts_day")` → reload. P0-2 코드를 이 방식으로 확정.
2. **의존성 충돌 → mlflow-skinny로 해소 (구현·검증 완료)**: `pyiceberg[pyarrow] 0.11.1`은 `pyarrow 24`를 끌어오나 `mlflow==2.10.2`는 `pyarrow<16`을 강제 → 충돌. mlflow 2.x는 **어떤 버전도 pyarrow≥16을 허용하지 않음**(resolver 확인, 3.x에서야 해제). 백엔드는 `MlflowClient`/`entities`/`exceptions`만 쓰므로 **`mlflow-skinny==2.10.2`로 교체**(skinny는 pyarrow 비의존) → 동일 버전 유지하며 충돌 0. 또한 `s3fs`는 aiobotocore를 끌어와 `boto3==1.34`와 충돌하므로 제외(PyIceberg는 PyArrowFileIO 사용, pod에서 확인). 전체 `requirements.txt` 클린룸 dry-run 충돌 0 확인.
3. **환경**: 노드 메모리 포화로 별도 검증 pod 스케줄 불가 → backend pod 내 실행. 운영 반영 시 백엔드 메모리 여유 확인 필요(현재 limit 512Mi).

---

## 0. 배경 — 왜 P0인가

현재 Lakehouse 골격(Iceberg + Polaris + Trino + RisingWave)은 갖춰졌으나, **실 데이터 규모에서 성능·안정성·스토리지가 반드시 무너지는** 3중 결함이 있다. 데모/소량에선 동작하지만 엔터프라이즈 온프렘 타겟에는 부적합하다.

| # | 결함 | 현재 코드 | 영향 |
|---|------|----------|------|
| P0-1 | 행 단위 `INSERT VALUES` 쓰기 | `iceberg_writer.py:248-250` | 확장 불가, 스몰파일/스냅샷 폭발, SQL 인젝션 |
| P0-2 | 파티셔닝 전무 | `iceberg_writer.py:227-232` (`CREATE TABLE`에 `partitioning` 없음) | 전 쿼리 풀스캔, 프루닝 불가 |
| P0-3 | 테이블 유지보수 전무 | 코드/DAG 어디에도 없음 | 스몰파일 무한 누적, 스토리지 미회수 |

3개는 상호 결합되어 있다 (P0-1의 스몰파일을 P0-3가 청소하고, P0-2가 그 청소·쿼리 효율을 결정). **묶어서 구현해야 한다.**

### 현재 데이터 경로 (실측)

```
소스 → connector.sync_to_iceberg() [backend pod, pandas in-memory]
     → write_dataframe_to_iceberg(df, ...)   # iceberg_writer.py
        ├ CREATE TABLE IF NOT EXISTS ... WITH (format='PARQUET', location=...)   # 파티션 없음
        └ for batch(500): INSERT INTO ... VALUES (리터럴 문자열 조립)            # 인젝션 + 스몰파일
```

> ⚠️ CLAUDE.md의 `Airflow → Spark → Polaris → Iceberg` 배치 경로는 **문서상일 뿐**이다. Spark는 `values-quicktest.yaml`에서 `enabled: false`이며, 실제 커넥터 적재는 전부 위 Trino INSERT 경로를 탄다. 본 계획은 이 실제 경로를 교체한다.

### 인프라 사실 (PyIceberg 접속 근거)

- Polaris REST 카탈로그: `http://polaris:8181/api/catalog`, 보안 `OAUTH2`, credential `clientId:clientSecret`, scope `PRINCIPAL_ROLE:ALL`, warehouse = 카탈로그명 `iceberg`
- S3(SeaweedFS): `http://seaweedfs-s3:8333`, path-style, region `us-east-1`
- Trino Iceberg 커넥터 = `type=rest` → `ALTER TABLE … EXECUTE optimize / expire_snapshots / remove_orphan_files` 모두 지원
- 백엔드 deps(`requirements.txt`): `trino==0.328.0`, `boto3==1.34.0`, `sqlalchemy==2.0.25` — **`pyiceberg`/`pyarrow` 없음 (추가 필요)**

---

## P0-1. 쓰기 경로 교체 (INSERT VALUES → PyIceberg 벌크 쓰기)

### 목표
행 단위 INSERT를 제거하고, **pandas DataFrame → PyArrow Table → PyIceberg `append`/`overwrite`** 로 Parquet을 한 번에 쓰고 단일 스냅샷으로 커밋한다. 인젝션·스몰파일·스냅샷 폭발을 동시에 해소한다.

### 설계 결정 — PyIceberg (권장) vs 대안

| 방안 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **A. PyIceberg → Polaris REST 직접 쓰기** | Trino 우회, 단일 커밋, 적정 파일 크기, 인젝션 원천 차단, 파티션 spec 네이티브, 추후 upsert(`MERGE`) 확장 용이 | 신규 의존성, Polaris OAUTH2/SeaweedFS S3 호환 검증 필요 | ✅ **채택** |
| B. Parquet stage → Trino `INSERT … SELECT` | Trino 단일 writer 유지 | 외부 stage 등록 복잡, 여전히 Trino 경유 | 보류 |
| C. parameterized INSERT + 배치 확대 | 인젝션만 즉시 차단 | 스몰파일/스케일 미해결 | **핫픽스용** (아래) |

> **즉시 핫픽스(선택)**: A 구현 전 인젝션만 급히 막아야 하면, `_values_row`의 리터럴 조립을 trino-python `cursor.execute(sql, params)` 파라미터 바인딩으로 전환. 스몰파일은 그대로이므로 임시방편.

### 구현

**1) 의존성 추가 + 정합** — `backend/requirements.txt`
```
pyiceberg[pyarrow]==0.11.1         # 스파이크 검증 버전 (s3fs 제외 — boto3 충돌 회피)
pyarrow>=16,<25
mlflow-skinny==2.10.2              # (기존 mlflow==2.10.2 교체) pyarrow 비의존 → 충돌 0
```
> ✅ **의존성 정합 (구현·검증 완료)**: full `mlflow`는 모든 2.x에서 `pyarrow<16`을 강제하나, 백엔드는 `MlflowClient`/`entities`/`exceptions`만 사용하므로 `mlflow-skinny`(pyarrow 비의존)로 교체해 동일 버전·동일 API를 유지하며 충돌을 제거했다. `s3fs`는 PyArrowFileIO 사용으로 불필요(제외). 머지 게이트(`requirements.txt` 클린룸 dry-run 충돌 0) 통과.

**2) 신규 모듈** — `backend/app/connectors/iceberg_catalog.py`
```python
"""PyIceberg ↔ Polaris REST 카탈로그 커넥션 (싱글톤)."""
import os
from functools import lru_cache
from pyiceberg.catalog.rest import RestCatalog

@lru_cache(maxsize=1)
def get_catalog() -> RestCatalog:
    return RestCatalog(
        name="datapond",
        **{
            "uri":        os.getenv("POLARIS_URI", "http://polaris:8181/api/catalog"),
            "warehouse":  os.getenv("POLARIS_WAREHOUSE", "iceberg"),
            "credential": f'{os.getenv("POLARIS_CLIENT_ID")}:{os.getenv("POLARIS_CLIENT_SECRET")}',
            "scope":      "PRINCIPAL_ROLE:ALL",
            # SeaweedFS S3 (Polaris가 vended-credentials 미지원 시 FileIO에 직접 전달)
            "s3.endpoint":          os.getenv("S3_ENDPOINT_URL", "http://seaweedfs-s3:8333"),
            "s3.access-key-id":     os.getenv("S3_ACCESS_KEY", "datapond"),
            "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "datapond_dev"),
            "s3.path-style-access": "true",
            "s3.region":            "us-east-1",
        },
    )
```

**3) `iceberg_writer.write_dataframe_to_iceberg` 재구현** — 시그니처/`on_step` 콜백/반환(rows) 유지 (호출부 `connectors.py:1209` 무변경 보장)
```python
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from app.connectors.iceberg_catalog import get_catalog
from app.connectors.partitioning import build_partition_spec, infer_default_partition  # P0-2

def write_dataframe_to_iceberg(df, table_name, schema="default", mode="overwrite",
                               on_step=None, partition_spec=None):
    def step(name, msg, **extra): ...   # 기존 유지

    if df.empty:
        step("skip", f"No rows for {schema}.{table_name}"); return 0

    cat   = get_catalog()
    ident = (schema, _safe_name(table_name))
    arrow = pa.Table.from_pandas(df, preserve_index=False)   # 타입은 arrow 스키마로 정확 매핑

    # 1. 테이블 확보 (없으면 생성 후 파티션 진화 — 스파이크 검증 패턴)
    try:
        tbl = cat.load_table(ident)
        step("schema_check", f"Table {table_name} exists")
    except NoSuchTableError:
        cat.create_namespace_if_not_exists((schema,))
        tbl = cat.create_table(ident, schema=arrow.schema)   # 무파티션으로 생성
        # 파티션은 update_spec(컬럼명 기반)으로 적용 — PartitionSpec 직접조립 금지(field-id 매칭 실패)
        spec_def = partition_spec or infer_default_partition(arrow.schema)
        if spec_def:
            apply_partition_spec(tbl, spec_def)              # P0-2: us.add_field(col, transform, name)
            tbl = cat.load_table(ident)
        step("create", f"Created {table_name} (partition={spec_def})", action="done")

    # 2. 스키마 진화 (append 모드: 신규 컬럼만 union-by-name)
    if mode == "append":
        with tbl.update_schema(allow_incompatible_changes=False) as us:
            us.union_by_name(arrow.schema)
        tbl = cat.load_table(ident)

    # 3. 단일 커밋 쓰기 — Parquet 파일은 PyIceberg가 직접 S3에 적정 크기로 작성
    if mode == "overwrite":
        tbl.overwrite(arrow)               # 1 스냅샷
    else:
        tbl.append(arrow)                  # 1 스냅샷
    step("insert", f"Wrote {len(df):,} rows (1 commit)",
         rows_done=len(df), rows_total=len(df), pct=100)
    return len(df)
```

**4) Helm — 백엔드에 Polaris 자격/엔드포인트 주입** — `backend-deployment.yaml` env 추가
```yaml
- { name: POLARIS_URI,           value: "http://polaris:8181/api/catalog" }
- { name: POLARIS_WAREHOUSE,     value: "{{ .Values.polaris.catalogName | default \"iceberg\" }}" }
- { name: POLARIS_CLIENT_ID,     value: "{{ .Values.polaris.auth.clientId }}" }
- { name: POLARIS_CLIENT_SECRET, value: "{{ .Values.polaris.auth.clientSecret }}" }
- { name: S3_ENDPOINT_URL,       value: "http://seaweedfs-s3:8333" }
# S3_ACCESS_KEY / S3_SECRET_KEY 는 기존 secrets.yaml 재사용
```

### 제거/대체되는 코드
`_values_row`, `_col_defs`, `_pandas_to_trino_type`, `_apply_schema_evolution`, 배치 INSERT 루프, DROP+S3 wipe 폴백 → PyIceberg 경로로 대체 (overwrite는 `tbl.overwrite`가 스냅샷 교체로 처리).

### 경계 (P0 범위 밖)
- 데이터는 여전히 **백엔드 pod 메모리(pandas)** 를 경유한다. 진정한 분산 수집(Spark/PyIceberg 워커)은 **P1-6**. P0-1은 "쓰기 효율·정합·보안"만 해결한다. 대용량은 청크 단위 `append` 반복으로 메모리 상한을 두되, 청크당 1 스냅샷이 되지 않도록 누적 후 커밋(`tbl.append` 배치)한다.

### 인수 조건
- [ ] 1만 행 동기화 시 스냅샷 1개, Parquet 파일 ≤ 수 개 (기존: 스냅샷 20개 / 파일 20개)
- [ ] `'; DROP TABLE` 등이 포함된 문자열 컬럼이 데이터로 안전 저장 (인젝션 차단)
- [ ] `_pandas_to_trino_type` 의존 제거, arrow 스키마로 타입 보존
- [ ] 기존 SSE 진행 이벤트(`table_step`) 표면 변화 없음

---

## P0-2. 파티셔닝 도입

### 목표
테이블 생성 시 파티션 spec을 지정해 쿼리 프루닝을 가능케 한다. 사용자 미지정 시 시간 컬럼 기반 기본 파티션을 자동 적용한다.

### 구현

**1) 신규 모듈** — `backend/app/connectors/partitioning.py` (스파이크 검증 패턴)
```python
"""파티션 적용(컬럼명 기반 update_spec) + 기본 추론."""
import pyarrow as pa
from pyiceberg.transforms import (DayTransform, MonthTransform, YearTransform,
                                  IdentityTransform, BucketTransform)

_TRANSFORMS = {"day": DayTransform, "month": MonthTransform, "year": YearTransform,
               "identity": IdentityTransform}

def infer_default_partition(schema: pa.Schema) -> list[dict]:
    """첫 timestamp/date 컬럼을 day() 파티션으로. 없으면 무파티션."""
    for f in schema:
        if pa.types.is_timestamp(f.type) or pa.types.is_date(f.type):
            return [{"column": f.name, "transform": "day"}]
    return []

def apply_partition_spec(tbl, spec_def: list[dict]) -> None:
    """update_spec으로 컬럼명 기반 파티션 추가 (field-id 직접 조립 금지 — 스파이크 FAIL 확인)."""
    with tbl.update_spec() as us:
        for s in spec_def:
            if s["transform"] == "bucket":
                t = BucketTransform(num_buckets=s.get("buckets", 16))
            else:
                t = _TRANSFORMS[s["transform"]]()
            us.add_field(s["column"], t, f'{s["column"]}_{s["transform"]}')
```
> 검증 근거: `update_spec().add_field("ts", DayTransform(), "ts_day")` 적용 후 append 시
> `data/ts_day=2026-01-01/…parquet`로 파티션 디렉터리 분기 쓰기를 실측 확인.

**2) 스키마 — 테이블별 파티션 설정 저장** — `connector_sync_jobs` 컬럼 추가
```sql
ALTER TABLE connector_sync_jobs
  ADD COLUMN IF NOT EXISTS partition_spec JSONB;   -- 예: [{"column":"created_at","transform":"day"}]
```
적재 흐름(`connectors.py`)에서 `job['partition_spec']`을 읽어 `write_dataframe_to_iceberg(..., partition_spec=...)`로 전달.

**3) UI** — 커넥터 테이블 설정에 파티션 키/변환 선택 (인라인 편집, 기존 sync_mode 편집 UI 옆). 미설정 시 "auto (day on <ts컬럼>)" 표시.

### 파티션 진화
- `overwrite` 모드: 신규 spec으로 재생성(스냅샷 교체)으로 자연 반영.
- `append`(기존 테이블 spec 변경): PyIceberg `tbl.update_spec()`으로 파티션 진화 — 신규 데이터부터 신규 spec 적용(과거 파일 재작성은 P0-3 compaction이 점진 정리).

### 인수 조건
- [ ] timestamp 컬럼 보유 테이블 신규 생성 시 `day()` 파티션 자동 적용
- [ ] `SELECT … WHERE ts BETWEEN …` 쿼리가 파티션 프루닝됨 (Trino `EXPLAIN`으로 확인)
- [ ] UI에서 파티션 키 지정/변경 가능

---

## P0-3. 테이블 유지보수 DAG

### 목표
주기적으로 모든 Iceberg 테이블에 대해 **compaction(스몰파일 병합) + 스냅샷 만료 + orphan 파일 제거**를 수행해 P0-1/P0-2가 만든 파일·스냅샷·고아 데이터를 정리하고 스토리지를 회수한다.

### 구현 — Trino `ALTER TABLE EXECUTE` (type=rest 지원 확인됨)

**1) 신규 모듈** — `backend/app/pipelines/maintenance_dag.py`
런타임에 `iceberg.information_schema.tables`를 조회해 raw/refined/serving 전 테이블을 순회하는 Airflow DAG 생성. 기존 transform CTAS DAG와 동일한 Airflow 배포 경로(dags 폴더 마운트) 사용.

DAG가 테이블별로 실행할 SQL:
```sql
-- 1. compaction: 128MB 미만 파일 병합
ALTER TABLE iceberg.{schema}.{table}
  EXECUTE optimize(file_size_threshold => '128MB');

-- 2. 스냅샷 만료 (기본 7일 — 시간여행 보존창과 직결, 설정화)
ALTER TABLE iceberg.{schema}.{table}
  EXECUTE expire_snapshots(retention_threshold => '7d');

-- 3. 고아 파일 제거
ALTER TABLE iceberg.{schema}.{table}
  EXECUTE remove_orphan_files(retention_threshold => '7d');
```

**2) 스케줄/설정** — `system_settings` 또는 values에 노출
```yaml
maintenance:
  schedule: "0 3 * * *"        # 매일 03:00
  target_file_size: "128MB"
  snapshot_retention: "7d"     # ↓ 시간여행 보존창 (P1-5 연동)
  orphan_retention: "7d"
```

**3) 안전장치**
- `expire_snapshots` 보존창 이전 스냅샷은 **시간여행 불가**가 된다 — 기본 7일, 설정 가능. UI/문서에 명시.
- `remove_orphan_files` 보존창은 진행 중 쓰기와의 경쟁을 피하기 위해 ≥ 1일 권장 (동시 적재 중 신규 파일 오삭제 방지).
- DAG는 테이블별 try/except로 격리 — 한 테이블 실패가 전체 중단으로 번지지 않게.

### 인수 조건
- [ ] DAG 1회 실행 후 스몰파일 수가 테이블당 한 자릿수로 수렴
- [ ] 만료창 초과 스냅샷 제거 + 스토리지 사용량 감소 확인 (SeaweedFS)
- [ ] 신규 테이블이 자동으로 순회 대상에 포함 (information_schema 동적 조회)
- [ ] 한 테이블 실패가 다른 테이블 유지보수를 막지 않음

---

## 통합 시퀀스 & 의존성

```
P0-1 (PyIceberg 쓰기 경로)  ──┐
                              ├─→ 함께 머지 (P0-1이 P0-2 spec을 소비)
P0-2 (파티셔닝)            ──┘
                                   ↓
P0-3 (유지보수 DAG)  ── P0-1/P0-2 배포 후 (정리 대상이 생긴 뒤) 활성화
```

권장 순서: **P0-1 + P0-2 동시 구현 → 통합 검증 → P0-3 활성화.**

## 단계별 작업 목록

1. **준비**: `requirements.txt`에 pyiceberg/pyarrow 추가, 백엔드 이미지 재빌드, Helm env 주입
2. **P0-1/P0-2**: `iceberg_catalog.py`, `partitioning.py` 신규 → `iceberg_writer.py` 재구현 → `connector_sync_jobs.partition_spec` 마이그레이션 → `connectors.py` 적재 흐름에 spec 전달 → UI 파티션 편집
3. **검증**: 소량/중량(≥100만 행) 동기화로 스냅샷·파일 수·인젝션·프루닝 인수 조건 확인
4. **P0-3**: `maintenance_dag.py` 생성 → Airflow 배포 → 수동 트리거 검증 → 스케줄 활성화
5. **회귀**: `backend/test_database_connector.py`, `test_storage_connector.py` 갱신 + PyIceberg 경로 신규 테스트 추가

## 리스크 & 완화

| 리스크 | 완화 |
|--------|------|
| ~~PyIceberg ↔ Polaris OAUTH2 / SeaweedFS S3 호환 미검증~~ | ✅ **해소 — 2026-05-29 스파이크로 라운드트립 검증 완료** (상단 결과 참조) |
| ~~mlflow(pyarrow<16) ↔ pyiceberg(pyarrow≥16) 의존성 충돌~~ | ✅ **해소 — `mlflow`→`mlflow-skinny==2.10.2`(pyarrow 비의존) + `s3fs` 제외. 클린룸 dry-run 충돌 0** |
| Polaris vended-credentials 미지원 시 FileIO 인증 | s3.* 자격을 카탈로그 프로퍼티로 직접 주입(스파이크에서 이 방식으로 동작 확인) |
| 대용량 시 백엔드 메모리(pandas) 한계 | 청크 append + 상한, 근본 해결은 P1-6(분산 수집) |
| `expire_snapshots`가 시간여행 보존창 축소 | 보존창 설정화·문서화, 기본 7일 |
| 기존 테이블(무파티션) 혼재 | overwrite 시 자연 재생성, append는 update_spec으로 점진 전환 |

## 인수 기준 (P0 전체 완료 정의)

- [ ] 모든 신규 적재가 PyIceberg 단일 커밋으로 수행 (Trino INSERT VALUES 경로 제거)
- [ ] 데이터 인젝션 불가 (리터럴 SQL 조립 제거)
- [ ] 시간 컬럼 테이블이 기본 파티셔닝되고 쿼리 프루닝 동작
- [ ] 유지보수 DAG가 스몰파일/스냅샷/고아파일을 주기적으로 정리
- [ ] CLAUDE.md "미완성 항목"의 *Iceberg VACUUM DAG* 해소, 데이터 경로 문서를 실제 구현과 일치하도록 갱신

---

## 후속 (P1 — 본 계획 범위 밖, 참조)

- **P1-4**: `MERGE INTO` 기반 배치 upsert (증분 동기화의 update/delete 반영)
- **P1-5**: 시간여행/스냅샷 조회·롤백 API + UI (`$snapshots`/`$history`/`FOR VERSION`)
- **P1-6**: 분산 수집 경로 복구 (Spark 활성화 또는 PyIceberg 워커) — 백엔드 pandas 의존 제거
