# DataPond PoC — AWS 인프라 구성

**작성일:** 2026-05-26  
**목적:** DataPond PoC 환경을 AWS에 최소 비용으로 구성  
**도메인:** datapond.csg.fitcloud.co.kr

---

## 설계 원칙

- PoC 전용 VPC로 격리 → 실험 종료 후 VPC 삭제로 일괄 정리
- Spot Instance + 업무시간 스케줄링으로 비용 최소화
- 단일 노드 K3s (values-quicktest.yaml)

---

## 인프라 구성도

```
┌─────────────────────────────────────────────────────┐
│  Route 53: datapond.csg.fitcloud.co.kr → EIP        │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  datapond-vpc (172.16.0.0/16)                       │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  datapond-public (172.16.1.0/24, 2a)        │    │
│  │                                              │    │
│  │  ┌────────────────────────────────────┐     │    │
│  │  │  EC2 Spot (t3.2xlarge)             │     │    │
│  │  │  Ubuntu 22.04, 150GB gp3           │     │    │
│  │  │  K3s + DataPond 전체 서비스         │     │    │
│  │  │  EIP 연결                           │     │    │
│  │  └────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  Internet Gateway: datapond-igw                      │
│  Security Group: datapond-sg (22, 80, 443)          │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  Lambda + EventBridge (스케줄링)                      │
│  - 평일 09:00 KST: 인스턴스 시작                     │
│  - 평일 19:00 KST: 인스턴스 중지                     │
└──────────────────────────────────────────────────────┘
```

---

## 리소스 상세

### VPC

| 항목 | 값 |
|------|-----|
| VPC Name | datapond-vpc |
| CIDR | 172.16.0.0/16 |
| DNS Hostnames | 활성화 |
| DNS Resolution | 활성화 |

### Subnet

| 항목 | 값 |
|------|-----|
| Name | datapond-public |
| CIDR | 172.16.1.0/24 |
| AZ | ap-northeast-2a |
| Auto-assign Public IP | No (EIP 사용) |

### Security Group (datapond-sg)

| 방향 | 프로토콜 | 포트 | 소스 | 용도 |
|------|----------|------|------|------|
| Inbound | TCP | 22 | 0.0.0.0/0 | SSH |
| Inbound | TCP | 80 | 0.0.0.0/0 | HTTP |
| Inbound | TCP | 443 | 0.0.0.0/0 | HTTPS |
| Outbound | All | All | 0.0.0.0/0 | 인터넷 접근 |

> 프로덕션 시 SSH 소스를 사무실 IP로 제한 권장

### EC2 Instance

| 항목 | 값 |
|------|-----|
| Type | t3.2xlarge (8 vCPU, 32GB RAM) |
| 구매 옵션 | Spot Instance |
| AMI | Ubuntu 22.04 LTS (최신) |
| Root Volume | 150GB gp3 (3000 IOPS, 125 MB/s) |
| Key Pair | cloudops-key |
| 중단 동작 | stop (데이터 보존) |

### Elastic IP

| 항목 | 값 |
|------|-----|
| 용도 | 인스턴스 고정 IP |
| 연결 대상 | DataPond Spot Instance |

### Route 53

| 항목 | 값 |
|------|-----|
| Hosted Zone | csg.fitcloud.co.kr (Z0240462V0L728N4P9PZ) |
| Record | datapond.csg.fitcloud.co.kr |
| Type | A |
| Value | Elastic IP |
| TTL | 300 |

---

## 스케줄링 (비용 최적화)

### 운영 시간

| 요일 | 시작 | 중지 |
|------|------|------|
| 월~금 | 09:00 KST | 19:00 KST |
| 토~일 | 중지 상태 유지 | — |

### 구현

- **Lambda 함수**: `datapond-scheduler`
  - Runtime: Python 3.12
  - 역할: EC2 start/stop
- **EventBridge Rules**:
  - `datapond-start`: cron(0 0 ? * MON-FRI *) — UTC 00:00 = KST 09:00
  - `datapond-stop`: cron(0 10 ? * MON-FRI *) — UTC 10:00 = KST 19:00

---

## 예상 비용 (월)

| 항목 | 산정 기준 | 비용 |
|------|----------|------|
| EC2 Spot t3.2xlarge | ~$0.08/h × 10h × 22일 | ~$18 |
| EBS 150GB gp3 | 24/7 과금 | $12 |
| Elastic IP | 중지 시간 과금 포함 | ~$3 |
| Route 53 | Hosted Zone + 쿼리 | ~$1 |
| Lambda + EventBridge | 프리티어 내 | $0 |
| **합계** | | **~$34/월** |

---

## 설치 절차 (인스턴스 생성 후)

```bash
# SSH 접속
ssh -i cloudops-key.pem ubuntu@datapond.csg.fitcloud.co.kr

# DataPond 설치
git clone https://github.com/datapond/datapond-k8s && cd datapond-k8s
sudo bash scripts/install.sh --domain datapond.csg.fitcloud.co.kr
```

---

## 배포 상태 (2026-05-26)

✅ **DataPond 운영 중**: http://datapond.csg.fitcloud.co.kr

| 서비스 | 상태 |
|--------|------|
| Frontend (Next.js) | ✅ Running |
| Backend (FastAPI) | ✅ Running |
| JupyterLab | ✅ Running |
| Airflow (Scheduler + Webserver) | ✅ Running |
| MLflow | ✅ Running |
| OpenMetadata (Server + ES) | ✅ Running |
| PostgreSQL | ✅ Running |
| Trino | ✅ Running |
| RisingWave (4 pods) | ✅ Running |
| SeaweedFS (4 pods) | ✅ Running |
| Valkey | ✅ Running |
| Polaris | ⚠️ Init (비필수, 추후 수정) |

---

## 생성된 리소스 ID

| 리소스 | ID |
|--------|-----|
| VPC | vpc-0db224c1b31000bc7 |
| Subnet | subnet-05a13738fd5574e70 |
| Internet Gateway | igw-0c3b90b9fd10880d7 |
| Route Table | rtb-0c0562e46b42d7667 |
| Security Group | sg-014a98dcbb43044ec |
| EC2 Instance (Spot) | i-0c2fcc7c014d28647 |
| Spot Request | sir-q31qecsq |
| Elastic IP | 43.200.145.21 (eipalloc-05157913a96799473) |
| Lambda | datapond-scheduler |
| IAM Role | datapond-scheduler-role |
| EventBridge Rule (start) | datapond-start |
| EventBridge Rule (stop) | datapond-stop |
| Route 53 Record | datapond.csg.fitcloud.co.kr → 43.200.145.21 |

---

## 정리 절차 (PoC 종료 시)

```bash
# 1. Spot Instance 종료
aws ec2 terminate-instances --instance-ids <instance-id>

# 2. Elastic IP 해제
aws ec2 release-address --allocation-id <eip-alloc-id>

# 3. Lambda/EventBridge 삭제
aws lambda delete-function --function-name datapond-scheduler
aws events remove-targets --rule datapond-start --ids "1"
aws events remove-targets --rule datapond-stop --ids "1"
aws events delete-rule --name datapond-start
aws events delete-rule --name datapond-stop

# 4. VPC 삭제 (SG, Subnet, IGW, Route Table 포함)
aws ec2 delete-security-group --group-id <sg-id>
aws ec2 delete-subnet --subnet-id <subnet-id>
aws ec2 detach-internet-gateway --internet-gateway-id <igw-id> --vpc-id <vpc-id>
aws ec2 delete-internet-gateway --internet-gateway-id <igw-id>
aws ec2 delete-vpc --vpc-id <vpc-id>

# 5. Route 53 레코드 삭제
aws route53 change-resource-record-sets --hosted-zone-id Z0240462V0L728N4P9PZ \
  --change-batch '{"Changes":[{"Action":"DELETE","ResourceRecordSet":{"Name":"datapond.csg.fitcloud.co.kr","Type":"A","TTL":300,"ResourceRecords":[{"Value":"<EIP>"}]}}]}'
```

---

## Polaris 스키마 초기화 분석 (2026-05-26)

### 문제

Apache Polaris 1.4.x 공식 Docker 이미지(`apache/polaris:1.4.1`)는 **NoSQL(MongoDB) persistence가 기본 활성**되어 있으며, `POLARIS_PERSISTENCE_TYPE=relational-jdbc` 환경변수를 설정해도 CDI bean 우선순위에 의해 NoSQL이 선택됩니다.

### 분석 결과

| 항목 | 상태 |
|------|------|
| JDBC jar (`polaris-relational-jdbc-1.4.1.jar`) | ✅ 이미지에 포함 |
| PostgreSQL 스키마 SQL (`postgres/schema-v4.sql`) | ✅ jar 내부에 존재 |
| `polaris_schema` 테이블 (9개) | ✅ 수동 적용 완료 |
| CDI persistence 전환 | ❌ 환경변수/system property로 불가 |
| 소스 빌드 (Gradle) | ✅ 성공 (4분 13초) |
| 커스텀 이미지 배포 | ❌ 빌드 결과에도 NoSQL 모듈 포함 |

### 근본 원인

Polaris 1.4.x의 Quarkus CDI 아키텍처에서 NoSQL persistence bean이 JDBC보다 높은 우선순위를 가짐. 단순 환경변수나 jar 제거로는 전환 불가. **소스코드 수정** (`build.gradle.kts`에서 NoSQL 의존성 제거) 필요.

### 현재 우회 방안

```sql
-- Trino postgres 카탈로그로 샘플 데이터 조회 (정상 동작)
SHOW SCHEMAS IN postgres;
SHOW TABLES IN postgres.sample;
SELECT * FROM postgres.sample.customers;
```

### 프로덕션 전환 시 해결 방안

1. `runtime/server/build.gradle.kts`에서 NoSQL 의존성 제거 후 재빌드
2. 또는 Polaris 커뮤니티의 JDBC-only 이미지 출시 대기 (GitHub Issue 추적)
3. 또는 Hive Metastore 기반 Iceberg catalog로 대체

---

## PoC 최종 현황 (2026-05-26 16:30 KST)

### 인프라

| 항목 | 값 |
|------|-----|
| URL | http://datapond.csg.fitcloud.co.kr |
| EC2 | i-0c2fcc7c014d28647 (t3.2xlarge Spot) |
| EIP | 43.200.145.21 |
| 스케줄링 | 평일 08:00~18:00 KST 자동 시작/중지 |
| 예상 비용 | ~$34/월 |

### 서비스 상태 (20/20 Running)

| 서비스 | 상태 | 비고 |
|--------|------|------|
| Frontend | ✅ | 세션 만료 수정 완료 |
| Backend | ✅ | DB 스키마 초기화 완료 |
| Airflow | ✅ | Scheduler + Webserver |
| MLflow | ✅ | |
| JupyterLab | ✅ | |
| OpenMetadata | ✅ | Server + Elasticsearch |
| Trino | ✅ | postgres 카탈로그 정상 |
| RisingWave | ✅ | 4 pods |
| SeaweedFS | ✅ | 4 pods |
| PostgreSQL | ✅ | |
| Valkey | ✅ | |
| Polaris | ✅ Running | OAuth 500 (NoSQL/JDBC 전환 미완) |

### 해결된 이슈

1. ✅ DB 스키마 미초기화 (`auth.sql`, `connectors.sql`, `queries.sql`)
2. ✅ Admin 비밀번호 placeholder → bcrypt hash 생성
3. ✅ `users` 테이블 컬럼 불일치 (`role`, `is_active`, `require_password_change`)
4. ✅ Backend RBAC 권한 부족 (pod 조회 403)
5. ✅ 프론트엔드 세션 만료 오탐 (JWT exp 기반으로 변경)
6. ✅ Polaris init container 대기 (수동 테이블 생성)
7. ✅ 샘플 데이터 생성 (`postgres.sample.*`)

### 미해결 (후속 과제)

1. ⚠️ Polaris JDBC persistence 전환 (소스 수정 필요)
2. ⚠️ Trino Iceberg 카탈로그 연동 (Polaris 해결 후)
3. ⚠️ HTTPS/TLS 설정 (cert-manager)
