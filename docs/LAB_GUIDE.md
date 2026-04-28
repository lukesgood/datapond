# DataPond 실습 가이드 (Hands-on Lab)

**버전**: 2.1.0  
**소요 시간**: 60-90분  
**난이도**: 초급~중급

---

## 📋 목차

1. [환경 준비](#1-환경-준비)
2. [Lab 1: JupyterLab 데이터 분석](#lab-1-jupyterlab-데이터-분석)
3. [Lab 2: Spark로 Iceberg 테이블 생성](#lab-2-spark로-iceberg-테이블-생성)
4. [Lab 3: Trino SQL 분석](#lab-3-trino-sql-분석)
5. [Lab 4: Time Travel 실습](#lab-4-time-travel-실습)
6. [Lab 5: MLflow 실험 추적](#lab-5-mlflow-실험-추적)
7. [Lab 6: Airflow 워크플로우](#lab-6-airflow-워크플로우)
8. [Lab 7: 종합 프로젝트](#lab-7-종합-프로젝트)
9. [Lab 8: RisingWave 실시간 스트리밍](#lab-8-risingwave-실시간-스트리밍)

---

## 1. 환경 준비

### 1.1 DataPond 배포 확인

```bash
# Pod 상태 확인
kubectl get pods -n datapond

# 모든 Pod가 Running 상태여야 함
# NAME                                 READY   STATUS    RESTARTS   AGE
# backend-xxxxx                        1/1     Running   0          5m
# frontend-xxxxx                       1/1     Running   0          5m
# postgres-0                           1/1     Running   0          5m
# jupyter-xxxxx                        1/1     Running   0          5m
# trino-xxxxx                          1/1     Running   0          5m
# spark-master-0                       1/1     Running   0          5m
# spark-worker-0                       1/1     Running   0          5m
# ...
```

### 1.2 서비스 접속 확인

```bash
# /etc/hosts 설정 확인
cat /etc/hosts | grep datapond
# 127.0.0.1  datapond.local

# 서비스 접속 테스트
curl http://datapond.local/api/health
# {"status": "healthy"}
```

### 1.3 브라우저 접속

| 서비스 | URL | 기본 계정 |
|--------|-----|-----------|
| Frontend | http://datapond.local | - |
| Backend API | http://datapond.local/api | - |
| JupyterLab | http://datapond.local/jupyter | token: `jupyter` |
| MLflow | http://datapond.local/mlflow | - |
| Airflow | http://datapond.local/airflow | admin / admin |
| Spark UI | http://datapond.local/spark | - |
| Trino | http://datapond.local/trino | - |

---

## Lab 1: JupyterLab 데이터 분석

### 목표
JupyterLab에서 PostgreSQL 데이터를 읽고 Pandas로 분석하기

### 단계

#### 1.1 JupyterLab 접속

```
브라우저에서 http://datapond.local/jupyter 접속
Token: jupyter
```

#### 1.2 새 노트북 생성

```
1. New → Python 3 (ipykernel)
2. 노트북 이름: "lab1-data-analysis.ipynb"
```

#### 1.3 PostgreSQL 연결

```python
import pandas as pd
from sqlalchemy import create_engine
import matplotlib.pyplot as plt

# PostgreSQL 연결
DATABASE_URL = "postgresql://datapond:datapond_password@postgres:5432/datapond"
engine = create_engine(DATABASE_URL)

# 테스트 데이터 생성
test_data = pd.DataFrame({
    'user_id': range(1, 101),
    'age': [20 + (i % 50) for i in range(100)],
    'score': [50 + (i % 50) for i in range(100)],
    'country': ['KR', 'US', 'JP', 'CN'][i % 4] for i in range(100)]
})

# 데이터 저장
test_data.to_sql('users', engine, if_exists='replace', index=False)
print("✅ 테스트 데이터 100건 생성 완료")
```

#### 1.4 데이터 분석

```python
# 데이터 읽기
df = pd.read_sql("SELECT * FROM users", engine)
print(f"📊 데이터 건수: {len(df)}")
print(df.head())

# 기본 통계
print("\n📈 기본 통계:")
print(df.describe())

# 국가별 평균 점수
country_avg = df.groupby('country')['score'].mean()
print("\n🌍 국가별 평균 점수:")
print(country_avg)

# 시각화
plt.figure(figsize=(10, 5))

plt.subplot(1, 2, 1)
country_avg.plot(kind='bar', color='skyblue')
plt.title('Average Score by Country')
plt.ylabel('Score')

plt.subplot(1, 2, 2)
df['age'].hist(bins=20, color='lightgreen')
plt.title('Age Distribution')
plt.xlabel('Age')

plt.tight_layout()
plt.savefig('/home/jovyan/work/analysis.png')
print("✅ 그래프 저장: analysis.png")
```

---

## Lab 2: Spark로 Iceberg 테이블 생성

### 목표
PySpark로 Iceberg 테이블을 생성하고 데이터 저장하기

### 단계

#### 2.1 새 노트북 생성

```
노트북 이름: "lab2-iceberg-spark.ipynb"
```

#### 2.2 Spark 세션 생성

```python
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType
from datetime import datetime, timedelta
import random

# Spark 세션 생성 (Iceberg 설정 포함)
spark = SparkSession.builder \
    .appName("DataPond-Iceberg-Lab") \
    .config("spark.jars.packages", 
            "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.4.3,"
            "org.apache.hadoop:hadoop-aws:3.3.4,"
            "software.amazon.awssdk:bundle:2.20.18") \
    .config("spark.sql.extensions", 
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions") \
    .config("spark.sql.catalog.iceberg", 
            "org.apache.iceberg.spark.SparkCatalog") \
    .config("spark.sql.catalog.iceberg.type", "hadoop") \
    .config("spark.sql.catalog.iceberg.warehouse", 
            "s3a://iceberg/warehouse") \
    .config("spark.hadoop.fs.s3a.endpoint", "http://seaweedfs-s3:8333") \
    .config("spark.hadoop.fs.s3a.access.key", "datapond") \
    .config("spark.hadoop.fs.s3a.secret.key", "datapond_s3_password") \
    .config("spark.hadoop.fs.s3a.path.style.access", "true") \
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
    .master("spark://spark-master:7077") \
    .getOrCreate()

print("✅ Spark 세션 생성 완료")
print(f"Spark 버전: {spark.version}")
```

#### 2.3 Iceberg 테이블 생성

```python
# 스키마 정의
schema = StructType([
    StructField("event_id", IntegerType(), False),
    StructField("user_id", IntegerType(), False),
    StructField("event_type", StringType(), False),
    StructField("event_time", TimestampType(), False),
    StructField("country", StringType(), True),
    StructField("device", StringType(), True)
])

# 샘플 데이터 생성
event_types = ['login', 'view', 'click', 'purchase', 'logout']
countries = ['KR', 'US', 'JP', 'CN', 'UK']
devices = ['mobile', 'desktop', 'tablet']

data = []
base_time = datetime.now() - timedelta(days=30)

for i in range(1000):
    data.append({
        'event_id': i + 1,
        'user_id': random.randint(1, 100),
        'event_type': random.choice(event_types),
        'event_time': base_time + timedelta(hours=i),
        'country': random.choice(countries),
        'device': random.choice(devices)
    })

# DataFrame 생성
df = spark.createDataFrame(data, schema)

# Iceberg 테이블로 저장
df.writeTo("iceberg.analytics.events") \
    .using("iceberg") \
    .partitionedBy("country") \
    .createOrReplace()

print("✅ Iceberg 테이블 생성 완료: iceberg.analytics.events")
print(f"📊 데이터 건수: {df.count()}")
```

#### 2.4 테이블 확인

```python
# 테이블 메타데이터 확인
spark.sql("DESCRIBE EXTENDED iceberg.analytics.events").show(50, False)

# 데이터 조회
result = spark.sql("""
    SELECT 
        country,
        event_type,
        COUNT(*) as event_count
    FROM iceberg.analytics.events
    GROUP BY country, event_type
    ORDER BY country, event_count DESC
""")

result.show(20)

# Pandas로 변환하여 시각화
import matplotlib.pyplot as plt

pdf = result.toPandas()
pivot_table = pdf.pivot(index='country', columns='event_type', values='event_count')

pivot_table.plot(kind='bar', figsize=(12, 6))
plt.title('Events by Country and Type')
plt.xlabel('Country')
plt.ylabel('Event Count')
plt.legend(title='Event Type')
plt.tight_layout()
plt.savefig('/home/jovyan/work/iceberg-events.png')
print("✅ 그래프 저장: iceberg-events.png")
```

---

## Lab 3: Trino SQL 분석

### 목표
Trino로 Iceberg 테이블 쿼리 및 페더레이션 분석

### 단계

#### 3.1 Trino CLI 접속

```bash
# Trino Pod 확인
kubectl get pods -n datapond | grep trino

# Trino CLI 실행
kubectl exec -it <trino-pod-name> -n datapond -- trino --server localhost:8080

# 또는 port-forward로 로컬에서 접속
kubectl port-forward -n datapond svc/trino 8080:8080
```

#### 3.2 Iceberg 테이블 조회

```sql
-- Catalog 확인
SHOW CATALOGS;

-- Iceberg 테이블 목록
SHOW TABLES FROM iceberg.analytics;

-- 테이블 스키마 확인
DESCRIBE iceberg.analytics.events;

-- 데이터 조회
SELECT * FROM iceberg.analytics.events LIMIT 10;
```

#### 3.3 집계 쿼리

```sql
-- 국가별 이벤트 통계
SELECT 
    country,
    COUNT(*) as total_events,
    COUNT(DISTINCT user_id) as unique_users,
    COUNT(*) * 1.0 / COUNT(DISTINCT user_id) as avg_events_per_user
FROM iceberg.analytics.events
GROUP BY country
ORDER BY total_events DESC;

-- 시간대별 이벤트 트렌드
SELECT 
    date_trunc('day', event_time) as event_date,
    event_type,
    COUNT(*) as event_count
FROM iceberg.analytics.events
GROUP BY 1, 2
ORDER BY event_date, event_count DESC;

-- 디바이스별 전환율
SELECT 
    device,
    SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as conversion_rate,
    COUNT(*) as total_events
FROM iceberg.analytics.events
GROUP BY device
ORDER BY conversion_rate DESC;
```

#### 3.4 페더레이션 쿼리 (PostgreSQL + Iceberg)

```sql
-- PostgreSQL 카탈로그 확인
SHOW SCHEMAS FROM postgres;

-- PostgreSQL 테이블 확인
SHOW TABLES FROM postgres.public;

-- 페더레이션 쿼리: Users(PostgreSQL) + Events(Iceberg)
SELECT 
    u.user_id,
    u.country as user_country,
    u.age,
    COUNT(e.event_id) as total_events,
    SUM(CASE WHEN e.event_type = 'purchase' THEN 1 ELSE 0 END) as purchases
FROM postgres.public.users u
LEFT JOIN iceberg.analytics.events e ON u.user_id = e.user_id
GROUP BY u.user_id, u.country, u.age
ORDER BY total_events DESC
LIMIT 20;
```

---

## Lab 4: Time Travel 실습

### 목표
Iceberg의 Time Travel 기능으로 과거 데이터 조회 및 복원

### 단계

#### 4.1 초기 스냅샷 생성

```python
# JupyterLab에서 실행
from pyspark.sql import SparkSession

spark = SparkSession.builder \
    .appName("Iceberg-TimeTravel") \
    .config("spark.sql.catalog.iceberg", "org.apache.iceberg.spark.SparkCatalog") \
    .config("spark.sql.catalog.iceberg.type", "hadoop") \
    .config("spark.sql.catalog.iceberg.warehouse", "s3a://iceberg/warehouse") \
    .master("spark://spark-master:7077") \
    .getOrCreate()

# 초기 데이터 확인
df = spark.sql("SELECT COUNT(*) as count FROM iceberg.analytics.events")
df.show()

# 스냅샷 ID 확인
snapshots = spark.sql("""
    SELECT snapshot_id, committed_at, operation, summary
    FROM iceberg.analytics.events.snapshots
    ORDER BY committed_at DESC
""")
snapshots.show(truncate=False)
print("📸 현재 스냅샷 저장")
```

#### 4.2 데이터 수정

```python
# 신규 이벤트 추가
new_events = spark.createDataFrame([
    (1001, 50, 'special_event', datetime.now(), 'KR', 'mobile'),
    (1002, 51, 'special_event', datetime.now(), 'US', 'desktop'),
], schema=schema)

new_events.writeTo("iceberg.analytics.events").append()
print("✅ 신규 이벤트 2건 추가")

# 데이터 삭제
spark.sql("""
    DELETE FROM iceberg.analytics.events 
    WHERE event_type = 'logout' AND country = 'KR'
""")
print("✅ KR 로그아웃 이벤트 삭제")

# 변경 후 데이터 확인
df_after = spark.sql("SELECT COUNT(*) as count FROM iceberg.analytics.events")
df_after.show()
```

#### 4.3 Time Travel 쿼리

```python
# 스냅샷 히스토리 조회
history = spark.sql("""
    SELECT snapshot_id, committed_at, operation
    FROM iceberg.analytics.events.snapshots
    ORDER BY committed_at DESC
""")
history.show(10)

# 이전 스냅샷 ID 가져오기 (첫 번째 스냅샷)
first_snapshot_id = history.collect()[2]['snapshot_id']  # 최초 생성 스냅샷
print(f"🕐 Time Travel 대상 스냅샷: {first_snapshot_id}")

# Time Travel 쿼리 - 과거 데이터 조회
df_past = spark.read \
    .option("snapshot-id", first_snapshot_id) \
    .format("iceberg") \
    .load("iceberg.analytics.events")

print(f"과거 데이터 건수: {df_past.count()}")
print(f"현재 데이터 건수: {spark.table('iceberg.analytics.events').count()}")

# 과거와 현재 비교
comparison = spark.sql(f"""
    SELECT 
        'Past' as time_period, 
        COUNT(*) as event_count,
        COUNT(DISTINCT user_id) as unique_users
    FROM iceberg.analytics.events VERSION AS OF {first_snapshot_id}
    
    UNION ALL
    
    SELECT 
        'Current' as time_period,
        COUNT(*) as event_count,
        COUNT(DISTINCT user_id) as unique_users
    FROM iceberg.analytics.events
""")
comparison.show()
```

#### 4.4 롤백 (선택사항)

```python
# 특정 스냅샷으로 롤백
spark.sql(f"""
    CALL iceberg.system.rollback_to_snapshot(
        'analytics.events', 
        {first_snapshot_id}
    )
""")
print(f"✅ 스냅샷 {first_snapshot_id}로 롤백 완료")

# 롤백 확인
df_rollback = spark.sql("SELECT COUNT(*) as count FROM iceberg.analytics.events")
df_rollback.show()
```

---

## Lab 5: MLflow 실험 추적

### 목표
머신러닝 실험을 MLflow로 추적하고 모델 저장

### 단계

#### 5.1 MLflow 설정

```python
# 새 노트북: lab5-mlflow-tracking.ipynb
import mlflow
import mlflow.sklearn
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
import pandas as pd
from sqlalchemy import create_engine

# MLflow 서버 설정
mlflow.set_tracking_uri("http://mlflow:5000")
mlflow.set_experiment("datapond-user-prediction")

print("✅ MLflow 연결 완료")
print(f"Tracking URI: {mlflow.get_tracking_uri()}")
print(f"Experiment: {mlflow.get_experiment_by_name('datapond-user-prediction')}")
```

#### 5.2 데이터 준비

```python
# PostgreSQL에서 데이터 로드
DATABASE_URL = "postgresql://datapond:datapond_password@postgres:5432/datapond"
engine = create_engine(DATABASE_URL)

df = pd.read_sql("SELECT * FROM users", engine)

# 피처 엔지니어링
df['age_group'] = pd.cut(df['age'], bins=[0, 30, 50, 100], labels=['young', 'middle', 'senior'])
df['high_score'] = (df['score'] > df['score'].median()).astype(int)

# 원-핫 인코딩
df_encoded = pd.get_dummies(df, columns=['country', 'age_group'], drop_first=True)

# 훈련/테스트 분할
X = df_encoded.drop(['user_id', 'high_score'], axis=1)
y = df_encoded['high_score']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(f"📊 훈련 데이터: {len(X_train)}, 테스트 데이터: {len(X_test)}")
```

#### 5.3 실험 1 - 기본 모델

```python
with mlflow.start_run(run_name="baseline-rf"):
    # 하이퍼파라미터
    n_estimators = 50
    max_depth = 5
    
    # 파라미터 로깅
    mlflow.log_param("n_estimators", n_estimators)
    mlflow.log_param("max_depth", max_depth)
    mlflow.log_param("model_type", "RandomForest")
    
    # 모델 훈련
    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # 예측 및 평가
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    # 메트릭 로깅
    mlflow.log_metric("accuracy", accuracy)
    mlflow.log_metric("f1_score", f1)
    
    # 모델 저장
    mlflow.sklearn.log_model(model, "model")
    
    print(f"✅ 실험 1 완료 - Accuracy: {accuracy:.4f}, F1: {f1:.4f}")
```

#### 5.4 실험 2 - 튜닝된 모델

```python
with mlflow.start_run(run_name="tuned-rf"):
    # 개선된 하이퍼파라미터
    n_estimators = 100
    max_depth = 10
    min_samples_split = 5
    
    mlflow.log_param("n_estimators", n_estimators)
    mlflow.log_param("max_depth", max_depth)
    mlflow.log_param("min_samples_split", min_samples_split)
    mlflow.log_param("model_type", "RandomForest-Tuned")
    
    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_split=min_samples_split,
        random_state=42
    )
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    mlflow.log_metric("accuracy", accuracy)
    mlflow.log_metric("f1_score", f1)
    
    # Feature importance 저장
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    feature_importance.to_csv('/tmp/feature_importance.csv', index=False)
    mlflow.log_artifact('/tmp/feature_importance.csv')
    
    mlflow.sklearn.log_model(model, "model")
    
    print(f"✅ 실험 2 완료 - Accuracy: {accuracy:.4f}, F1: {f1:.4f}")
    print("\n📊 Feature Importance:")
    print(feature_importance.head(10))
```

#### 5.5 MLflow UI에서 확인

```
브라우저에서 http://datapond.local/mlflow 접속

1. Experiments 탭에서 "datapond-user-prediction" 선택
2. 두 실험 비교 (Compare 버튼)
3. 메트릭 시각화 확인
4. 최고 성능 모델 선택 → Register Model
```

---

## Lab 6: Airflow 워크플로우

### 목표
데이터 파이프라인을 Airflow DAG로 자동화

### 단계

#### 6.1 DAG 파일 생성

```bash
# Airflow Pod에 접속
kubectl exec -it <airflow-webserver-pod> -n datapond -- bash

# DAG 디렉토리로 이동
cd /opt/airflow/dags

# DAG 파일 생성
cat > datapond_etl_dag.py << 'EOF'
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import create_engine

default_args = {
    'owner': 'datapond',
    'depends_on_past': False,
    'start_date': datetime(2026, 4, 28),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'datapond_daily_etl',
    default_args=default_args,
    description='Daily ETL pipeline for DataPond',
    schedule_interval='@daily',
    catchup=False,
)

def extract_data(**context):
    """PostgreSQL에서 데이터 추출"""
    DATABASE_URL = "postgresql://datapond:datapond_password@postgres:5432/datapond"
    engine = create_engine(DATABASE_URL)
    
    df = pd.read_sql("SELECT * FROM users", engine)
    
    # XCom에 데이터 건수 저장
    context['ti'].xcom_push(key='record_count', value=len(df))
    print(f"✅ Extracted {len(df)} records")
    return len(df)

def transform_data(**context):
    """데이터 변환"""
    record_count = context['ti'].xcom_pull(key='record_count', task_ids='extract')
    print(f"✅ Transforming {record_count} records")
    
    # 실제 변환 로직 (예시)
    DATABASE_URL = "postgresql://datapond:datapond_password@postgres:5432/datapond"
    engine = create_engine(DATABASE_URL)
    
    df = pd.read_sql("SELECT * FROM users", engine)
    
    # 집계 테이블 생성
    summary = df.groupby('country').agg({
        'score': ['mean', 'max', 'min', 'count']
    }).round(2)
    
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    summary = summary.reset_index()
    
    # 요약 테이블 저장
    summary.to_sql('user_summary', engine, if_exists='replace', index=False)
    
    print(f"✅ Created summary table with {len(summary)} rows")
    return len(summary)

def load_data(**context):
    """결과 로드 (예: Iceberg 테이블로)"""
    print("✅ Loading data to Iceberg (simulated)")
    # 실제로는 Spark job 트리거
    return True

# Task 정의
extract_task = PythonOperator(
    task_id='extract',
    python_callable=extract_data,
    provide_context=True,
    dag=dag,
)

transform_task = PythonOperator(
    task_id='transform',
    python_callable=transform_data,
    provide_context=True,
    dag=dag,
)

load_task = PythonOperator(
    task_id='load',
    python_callable=load_data,
    provide_context=True,
    dag=dag,
)

health_check = BashOperator(
    task_id='health_check',
    bash_command='curl -f http://backend:8000/health || exit 1',
    dag=dag,
)

# Task 의존성
health_check >> extract_task >> transform_task >> load_task
EOF

echo "✅ DAG 파일 생성 완료"
```

#### 6.2 DAG 활성화

```
1. 브라우저에서 http://datapond.local/airflow 접속
2. 로그인: admin / admin
3. DAGs 목록에서 "datapond_daily_etl" 찾기
4. 토글 스위치로 DAG 활성화
5. "Trigger DAG" 버튼 클릭하여 수동 실행
```

#### 6.3 실행 모니터링

```
1. DAG 이름 클릭 → Graph View
2. 각 Task 클릭하여 로그 확인
3. Task Duration, Gantt Chart 확인
4. XCom 데이터 확인 (Admin → XComs)
```

---

## Lab 7: 종합 프로젝트

### 목표
실시간 이벤트 분석 파이프라인 구축

### 시나리오
웹사이트 사용자 행동 데이터를 수집하고, Iceberg에 저장하며, Trino로 실시간 대시보드를 위한 집계 뷰를 생성합니다.

### 아키텍처

```
데이터 소스 (PostgreSQL)
    ↓
Spark ETL (JupyterLab)
    ↓
Iceberg 테이블 (S3/SeaweedFS)
    ↓
Trino 집계 뷰
    ↓
Airflow 스케줄링 (매시간)
    ↓
MLflow 모델 서빙
```

### 구현

#### 7.1 이벤트 시뮬레이터

```python
# 노트북: lab7-realtime-pipeline.ipynb
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime, timedelta
import random
import time

DATABASE_URL = "postgresql://datapond:datapond_password@postgres:5432/datapond"
engine = create_engine(DATABASE_URL)

def generate_events(count=100):
    """실시간 이벤트 시뮬레이션"""
    events = []
    event_types = ['page_view', 'click', 'add_cart', 'purchase', 'logout']
    pages = ['home', 'product', 'cart', 'checkout', 'profile']
    
    for i in range(count):
        events.append({
            'event_id': int(time.time() * 1000) + i,
            'user_id': random.randint(1, 100),
            'session_id': f"sess_{random.randint(1, 50)}",
            'event_type': random.choice(event_types),
            'page': random.choice(pages),
            'country': random.choice(['KR', 'US', 'JP', 'CN']),
            'device': random.choice(['mobile', 'desktop', 'tablet']),
            'event_time': datetime.now() - timedelta(seconds=random.randint(0, 3600)),
            'value': random.uniform(0, 1000) if random.random() > 0.7 else 0
        })
    
    df = pd.DataFrame(events)
    df.to_sql('raw_events', engine, if_exists='append', index=False)
    
    print(f"✅ Generated {count} events")
    return df

# 초기 데이터 생성
print("📊 이벤트 생성 중...")
for batch in range(5):
    generate_events(200)
    time.sleep(2)

print("✅ 총 1000개 이벤트 생성 완료")
```

#### 7.2 Spark ETL

```python
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, window, count, sum as _sum, avg

# Spark 세션
spark = SparkSession.builder \
    .appName("Realtime-Analytics-Pipeline") \
    .config("spark.sql.catalog.iceberg", "org.apache.iceberg.spark.SparkCatalog") \
    .config("spark.sql.catalog.iceberg.type", "hadoop") \
    .config("spark.sql.catalog.iceberg.warehouse", "s3a://iceberg/warehouse") \
    .master("spark://spark-master:7077") \
    .getOrCreate()

# PostgreSQL에서 읽기
jdbc_url = "jdbc:postgresql://postgres:5432/datapond"
properties = {
    "user": "datapond",
    "password": "datapond_password",
    "driver": "org.postgresql.Driver"
}

raw_events = spark.read.jdbc(jdbc_url, "raw_events", properties=properties)

print(f"📊 읽은 이벤트: {raw_events.count()}개")

# 데이터 정제 및 변환
cleaned_events = raw_events \
    .filter(col("event_time").isNotNull()) \
    .filter(col("user_id").isNotNull()) \
    .dropDuplicates(["event_id"])

# Iceberg 테이블로 저장 (append)
cleaned_events.writeTo("iceberg.analytics.web_events") \
    .using("iceberg") \
    .partitionedBy("country", "device") \
    .createOrReplace()

print("✅ Iceberg 테이블 생성: iceberg.analytics.web_events")

# 시간별 집계
hourly_stats = cleaned_events.groupBy(
    window(col("event_time"), "1 hour"),
    col("country"),
    col("event_type")
).agg(
    count("*").alias("event_count"),
    _sum("value").alias("total_value"),
    avg("value").alias("avg_value")
)

hourly_stats.writeTo("iceberg.analytics.hourly_stats") \
    .using("iceberg") \
    .createOrReplace()

print("✅ 집계 테이블 생성: iceberg.analytics.hourly_stats")
```

#### 7.3 Trino 분석 뷰

Trino CLI에서 실행:

```sql
-- 실시간 대시보드 뷰 생성
CREATE OR REPLACE VIEW iceberg.analytics.dashboard_metrics AS
SELECT 
    DATE_TRUNC('hour', event_time) as hour,
    country,
    COUNT(DISTINCT user_id) as active_users,
    COUNT(DISTINCT session_id) as sessions,
    COUNT(*) as total_events,
    SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) as purchases,
    SUM(CASE WHEN event_type = 'purchase' THEN value ELSE 0 END) as revenue,
    AVG(value) as avg_order_value
FROM iceberg.analytics.web_events
WHERE event_time >= CURRENT_TIMESTAMP - INTERVAL '24' HOUR
GROUP BY 1, 2
ORDER BY hour DESC, country;

-- 뷰 조회
SELECT * FROM iceberg.analytics.dashboard_metrics
LIMIT 20;

-- 전환 퍼널 분석
WITH funnel AS (
    SELECT 
        country,
        COUNT(DISTINCT CASE WHEN event_type = 'page_view' THEN user_id END) as views,
        COUNT(DISTINCT CASE WHEN event_type = 'click' THEN user_id END) as clicks,
        COUNT(DISTINCT CASE WHEN event_type = 'add_cart' THEN user_id END) as add_carts,
        COUNT(DISTINCT CASE WHEN event_type = 'purchase' THEN user_id END) as purchases
    FROM iceberg.analytics.web_events
    GROUP BY country
)
SELECT 
    country,
    views,
    clicks,
    add_carts,
    purchases,
    ROUND(clicks * 100.0 / NULLIF(views, 0), 2) as click_rate,
    ROUND(add_carts * 100.0 / NULLIF(clicks, 0), 2) as cart_rate,
    ROUND(purchases * 100.0 / NULLIF(add_carts, 0), 2) as purchase_rate
FROM funnel
ORDER BY purchases DESC;
```

#### 7.4 Airflow 자동화 DAG

```python
# /opt/airflow/dags/realtime_analytics_dag.py
from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'datapond',
    'start_date': datetime(2026, 4, 28),
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'realtime_analytics_hourly',
    default_args=default_args,
    description='Hourly analytics pipeline',
    schedule_interval='@hourly',
    catchup=False,
)

def check_data_quality(**context):
    """데이터 품질 검사"""
    from sqlalchemy import create_engine
    import pandas as pd
    
    engine = create_engine("postgresql://datapond:datapond_password@postgres:5432/datapond")
    
    # 최근 1시간 이벤트 확인
    query = """
        SELECT COUNT(*) as count 
        FROM raw_events 
        WHERE event_time >= NOW() - INTERVAL '1 hour'
    """
    result = pd.read_sql(query, engine)
    count = result.iloc[0]['count']
    
    if count < 10:
        raise ValueError(f"Data quality check failed: only {count} events in last hour")
    
    print(f"✅ Data quality OK: {count} events")
    return count

quality_check = PythonOperator(
    task_id='quality_check',
    python_callable=check_data_quality,
    dag=dag,
)

# Spark ETL job (실제로는 spark-submit 사용)
etl_task = BashOperator(
    task_id='spark_etl',
    bash_command='echo "Spark ETL completed"',  # 실제: spark-submit script
    dag=dag,
)

# 메트릭 계산
metrics_task = BashOperator(
    task_id='calculate_metrics',
    bash_command='echo "Metrics calculated"',
    dag=dag,
)

quality_check >> etl_task >> metrics_task
```

---

quality_check >> etl_task >> metrics_task
```

---

## Lab 8: RisingWave 실시간 스트리밍

### 목표
RisingWave로 실시간 스트리밍 SQL 처리 및 Materialized Views 생성

### 배경
RisingWave는 PostgreSQL 호환 스트리밍 데이터베이스로, Kafka + Flink를 대체하여 실시간 데이터 처리를 간소화합니다.

### 단계

#### 8.1 RisingWave 접속

```bash
# 포트 포워딩
kubectl port-forward -n datapond svc/risingwave-frontend 4566:4566

# 별도 터미널에서 psql로 연결
psql -h localhost -p 4566 -U root -d dev

# 또는 Python에서
import psycopg2
conn = psycopg2.connect(
    host="localhost",
    port=4566,
    user="root",
    database="dev"
)
```

#### 8.2 이벤트 스트림 시뮬레이션

JupyterLab에서 실행:

```python
# 노트북: lab8-risingwave-streaming.ipynb
import psycopg2
import json
import time
from datetime import datetime
import random

# PostgreSQL에 이벤트 테이블 생성 (Kafka 대신 사용)
pg_conn = psycopg2.connect(
    host="postgres",
    port=5432,
    user="datapond",
    password="datapond_password",
    database="datapond"
)
pg_cur = pg_conn.cursor()

pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS streaming_events (
        event_id SERIAL PRIMARY KEY,
        user_id INT,
        event_type VARCHAR(50),
        page VARCHAR(100),
        timestamp TIMESTAMP DEFAULT NOW(),
        value DECIMAL(10, 2)
    )
""")
pg_conn.commit()

# 이벤트 생성 함수
def generate_streaming_event():
    """실시간 이벤트 생성"""
    event_types = ['page_view', 'click', 'add_cart', 'purchase', 'search']
    pages = ['home', 'product', 'cart', 'checkout', 'category']
    
    pg_cur.execute("""
        INSERT INTO streaming_events (user_id, event_type, page, value)
        VALUES (%s, %s, %s, %s)
    """, (
        random.randint(1, 100),
        random.choice(event_types),
        random.choice(pages),
        random.uniform(0, 500) if random.random() > 0.7 else 0
    ))
    pg_conn.commit()

# 초기 이벤트 생성 (백그라운드로 계속 실행)
print("📊 이벤트 스트림 시작...")
for i in range(50):
    generate_streaming_event()
    if i % 10 == 0:
        print(f"  ✅ {i} events generated")
    time.sleep(0.1)

print("✅ 초기 50개 이벤트 생성 완료")
```

#### 8.3 RisingWave에서 Source 생성

```sql
-- RisingWave CLI (psql -h localhost -p 4566 -U root -d dev)

-- PostgreSQL CDC Source 생성
CREATE SOURCE pg_events (
    event_id INT,
    user_id INT,
    event_type VARCHAR,
    page VARCHAR,
    timestamp TIMESTAMP,
    value DECIMAL
)
WITH (
    connector = 'postgres-cdc',
    hostname = 'postgres',
    port = '5432',
    username = 'datapond',
    password = 'datapond_password',
    database.name = 'datapond',
    schema.name = 'public',
    table.name = 'streaming_events'
);

-- 데이터 확인
SELECT * FROM pg_events LIMIT 10;

-- 스트림 계속 모니터링
SELECT COUNT(*) as total_events FROM pg_events;
```

#### 8.4 Materialized Views 생성

```sql
-- 1. 실시간 이벤트 카운트 (최근 1분)
CREATE MATERIALIZED VIEW events_last_1min AS
SELECT
    event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT user_id) AS unique_users,
    AVG(value) AS avg_value,
    MAX(timestamp) AS last_event
FROM pg_events
WHERE timestamp > NOW() - INTERVAL '1 minute'
GROUP BY event_type
ORDER BY event_count DESC;

-- 조회 (자동으로 업데이트됨)
SELECT * FROM events_last_1min;

-- 2. Top 활성 사용자 (최근 5분)
CREATE MATERIALIZED VIEW top_active_users AS
SELECT
    user_id,
    COUNT(*) AS event_count,
    COUNT(DISTINCT event_type) AS event_types,
    SUM(value) AS total_value,
    MAX(timestamp) AS last_activity
FROM pg_events
WHERE timestamp > NOW() - INTERVAL '5 minutes'
GROUP BY user_id
HAVING COUNT(*) > 5
ORDER BY event_count DESC
LIMIT 20;

SELECT * FROM top_active_users;

-- 3. 페이지별 전환율 (실시간)
CREATE MATERIALIZED VIEW page_conversion_funnel AS
SELECT
    page,
    COUNT(*) AS total_views,
    SUM(CASE WHEN event_type = 'click' THEN 1 ELSE 0 END) AS clicks,
    SUM(CASE WHEN event_type = 'add_cart' THEN 1 ELSE 0 END) AS add_carts,
    SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases,
    ROUND(
        SUM(CASE WHEN event_type = 'click' THEN 1 ELSE 0 END)::DECIMAL / 
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS click_rate,
    ROUND(
        SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END)::DECIMAL / 
        NULLIF(SUM(CASE WHEN event_type = 'add_cart' THEN 1 ELSE 0 END), 0) * 100, 2
    ) AS purchase_rate
FROM pg_events
GROUP BY page;

SELECT * FROM page_conversion_funnel ORDER BY total_views DESC;

-- 4. 실시간 이상 탐지 (5분내 동일 사용자 50회 이상)
CREATE MATERIALIZED VIEW suspicious_users AS
SELECT
    user_id,
    COUNT(*) AS event_count,
    ARRAY_AGG(DISTINCT event_type) AS event_types,
    ARRAY_AGG(DISTINCT page) AS pages_accessed,
    MIN(timestamp) AS first_seen,
    MAX(timestamp) AS last_seen
FROM pg_events
WHERE timestamp > NOW() - INTERVAL '5 minutes'
GROUP BY user_id
HAVING COUNT(*) > 50;

-- 알림용 쿼리
SELECT * FROM suspicious_users;
```

#### 8.5 실시간 모니터링 (Python)

JupyterLab에서 실행:

```python
import psycopg2
import pandas as pd
import time
from IPython.display import clear_output
import matplotlib.pyplot as plt

# RisingWave 연결
rw_conn = psycopg2.connect(
    host="localhost",
    port=4566,
    user="root",
    database="dev"
)

# PostgreSQL 연결 (이벤트 생성용)
pg_conn = psycopg2.connect(
    host="postgres",
    port=5432,
    user="datapond",
    password="datapond_password",
    database="datapond"
)
pg_cur = pg_conn.cursor()

# 실시간 대시보드
def realtime_dashboard(duration=60):
    """실시간 이벤트 대시보드 (duration초 동안)"""
    print(f"🔴 실시간 대시보드 시작 ({duration}초)")
    
    for i in range(duration):
        # 백그라운드로 이벤트 계속 생성
        for _ in range(2):
            generate_streaming_event()
        
        # Materialized View 조회
        df_events = pd.read_sql_query(
            "SELECT * FROM events_last_1min",
            rw_conn
        )
        
        df_users = pd.read_sql_query(
            "SELECT * FROM top_active_users LIMIT 10",
            rw_conn
        )
        
        df_funnel = pd.read_sql_query(
            "SELECT * FROM page_conversion_funnel",
            rw_conn
        )
        
        # 화면 지우고 출력
        clear_output(wait=True)
        
        print(f"\n{'='*60}")
        print(f"⏰ 실시간 대시보드 - {time.strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
        
        print("📊 이벤트 타입별 (최근 1분)")
        print(df_events.to_string(index=False))
        
        print(f"\n👥 Top 활성 사용자 (최근 5분)")
        print(df_users[['user_id', 'event_count', 'total_value']].to_string(index=False))
        
        print(f"\n🔄 페이지 전환율")
        print(df_funnel[['page', 'total_views', 'click_rate', 'purchase_rate']].to_string(index=False))
        
        # 의심 활동 확인
        suspicious = pd.read_sql_query("SELECT * FROM suspicious_users", rw_conn)
        if not suspicious.empty:
            print(f"\n⚠️  의심 활동 감지!")
            print(suspicious.to_string(index=False))
        
        time.sleep(1)
    
    print("\n✅ 대시보드 종료")

# 실시간 대시보드 실행
realtime_dashboard(duration=30)

# 정리
rw_conn.close()
pg_conn.close()
```

#### 8.6 Sink로 Iceberg 연동

```sql
-- RisingWave 결과를 Iceberg 테이블로 내보내기
CREATE SINK iceberg_hourly_summary
FROM events_last_1min
WITH (
    connector = 'iceberg',
    type = 'append-only',
    s3.endpoint = 'http://seaweedfs-s3:8333',
    s3.region = 'us-east-1',
    s3.path.style.access = 'true',
    catalog.type = 'rest',
    catalog.uri = 'http://polaris:8181/api/catalog/v1',
    database.name = 'streaming',
    table.name = 'hourly_events'
);

-- 이제 Trino/Spark에서 쿼리 가능:
-- SELECT * FROM iceberg.streaming.hourly_events;
```

#### 8.7 시각화

```python
# JupyterLab에서 실행
import matplotlib.pyplot as plt
import pandas as pd
import psycopg2

rw_conn = psycopg2.connect(
    host="localhost",
    port=4566,
    user="root",
    database="dev"
)

# 이벤트 타입별 분포
df = pd.read_sql_query("SELECT * FROM events_last_1min", rw_conn)

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# 이벤트 카운트
axes[0].bar(df['event_type'], df['event_count'], color='steelblue')
axes[0].set_title('Event Count by Type (Last 1 min)')
axes[0].set_xlabel('Event Type')
axes[0].set_ylabel('Count')
axes[0].tick_params(axis='x', rotation=45)

# 사용자 수
axes[1].bar(df['event_type'], df['unique_users'], color='coral')
axes[1].set_title('Unique Users by Event Type')
axes[1].set_xlabel('Event Type')
axes[1].set_ylabel('Unique Users')
axes[1].tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.show()

rw_conn.close()
```

---

## 🎯 실습 완료 체크리스트

- [ ] Lab 1: JupyterLab에서 PostgreSQL 데이터 분석
- [ ] Lab 2: Spark로 Iceberg 테이블 생성
- [ ] Lab 3: Trino로 SQL 분석 수행
- [ ] Lab 4: Time Travel로 과거 데이터 조회
- [ ] Lab 5: MLflow로 ML 실험 추적
- [ ] Lab 6: Airflow DAG 생성 및 실행
- [ ] Lab 7: 종합 파이프라인 구축
- [ ] Lab 8: RisingWave 실시간 스트리밍

---

## 🔍 문제 해결

### JupyterLab 연결 안됨
```bash
kubectl logs -f <jupyter-pod> -n datapond
kubectl describe pod <jupyter-pod> -n datapond
```

### Spark 작업 실패
```bash
# Spark Master 로그 확인
kubectl logs -f spark-master-0 -n datapond

# Worker 로그 확인
kubectl logs -f spark-worker-0 -n datapond
```

### Trino 쿼리 오류
```sql
-- Trino에서 실행
SHOW FUNCTIONS;
SHOW TABLES FROM iceberg.analytics;
```

### Iceberg 테이블이 안보임
```bash
# SeaweedFS S3 확인
kubectl exec -it <seaweedfs-s3-pod> -n datapond -- sh
ls -la /data
```

---

## 📚 추가 학습 자료

### Iceberg
- [Apache Iceberg 공식 문서](https://iceberg.apache.org/docs/latest/)
- [Iceberg Format Specification](https://iceberg.apache.org/spec/)

### Trino
- [Trino 공식 문서](https://trino.io/docs/current/)
- [Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html)

### Spark
- [Spark Iceberg Integration](https://iceberg.apache.org/docs/latest/spark-getting-started/)

---

## 🎓 다음 단계

1. **성능 튜닝**: Iceberg 테이블 파티셔닝 최적화
2. **보안 강화**: RBAC, Network Policies 설정
3. **모니터링**: Prometheus + Grafana 대시보드 구축
4. **CI/CD**: GitOps (ArgoCD/Flux) 통합
5. **프로덕션**: 멀티 노드 클러스터로 확장

---

**랩 가이드 버전**: 1.0  
**최종 수정**: 2026-04-28  
**피드백**: [GitHub Issues](https://github.com/lukesgood/datapond/issues)
