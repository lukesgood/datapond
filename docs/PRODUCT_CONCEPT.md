# DataPond 제품 컨셉 정의

**작성일**: 2026-04-29
**버전**: 4.0.0-enterprise
**목적**: 제품 포지셔닝 재정의 — 온프렘 AI-Native Lakehouse

---

## 🎯 제품 포지셔닝

### 핵심 정의

**DataPond는 Databricks가 진입할 수 없는 온프렘·에어갭·프라이빗 환경을 위한 AI-Native Lakehouse 플랫폼입니다.**

Databricks는 클라우드 SaaS 전용 제품이다. 금융 규제, 국방·공공 보안, 의료 데이터 주권, 제조 인프라 분리 요건을 가진 조직은 Databricks를 쓸 수 없다. DataPond는 이 시장을 위해 설계된 유일한 엔터프라이즈급 AI-Native Lakehouse다.

### Tagline

**"AI-Native Lakehouse for Sovereign Infrastructure"**

*Databricks가 들어올 수 없는 곳, DataPond가 있다.*

### Elevator Pitch (30초)

```
DataPond는 온프레미스, 에어갭, 프라이빗 클라우드 환경에서
엔터프라이즈급 AI-Native Lakehouse를 구현하는 제품입니다.

Databricks는 클라우드 SaaS이므로 다음 환경에 진입 불가입니다:
  - 금융사 내부망 (금감원·FSS 규제)
  - 공공기관·국방 (망분리 의무)
  - 의료기관 (개인정보 외부 반출 금지)
  - 제조·에너지 (OT 네트워크 분리)

DataPond는 Kubernetes 위에서 동작하며,
이 모든 환경에 완전 자체 호스팅으로 배포됩니다.
Databricks와 동등한 AI 기능, 거버넌스, 실시간 스트리밍을
고객의 인프라 안에서 실행합니다.
```

---

## 🎯 타겟 고객

### 진입 시장: Databricks 진입 불가 환경

DataPond의 경쟁 환경은 "Databricks보다 저렴한 제품"이 아니다. DataPond는 **Databricks 자체가 선택지가 될 수 없는 시장**을 타겟으로 한다.

#### Tier 1: 금융 (최우선)

```yaml
대상:
  - 시중은행, 지방은행, 저축은행
  - 증권사, 자산운용사
  - 보험사, 캐피탈

규제 요건:
  - 금감원 IT내부통제 기준 → 고객 데이터 외부 반출 금지
  - 망분리 의무 → 외부 SaaS 연결 불가
  - ISMS-P 인증 → 데이터 저장 위치 감사 대상

DataPond 역할:
  - 내부망 전용 Lakehouse
  - 거래 데이터, 고객 행동 분석, 리스크 모델링
  - OpenMetadata를 통한 규정 준수 감사 로그

Pain Point:
  - Databricks: SaaS만 제공 → 내부망 사용 불가
  - 기존 방식: Hadoop + 자체 개발 → 유지보수 비용 과다
  - DataPond: 엔터프라이즈 기능 + 완전 내부 운영
```

#### Tier 2: 공공·국방

```yaml
대상:
  - 중앙부처, 지자체, 공공기관
  - 국방부, 방위사업청, 방산업체
  - 국가 연구기관 (KIST, ETRI 등)

규제 요건:
  - 국가정보원 CC 인증 대상
  - 클라우드 서비스 이용 제한 (비밀 분류 데이터)
  - 망분리 의무 (업무망 ↔ 인터넷망)

DataPond 역할:
  - 에어갭 환경 완전 지원
  - 이미지 레지스트리 내재화
  - 오프라인 설치 패키지
```

#### Tier 3: 의료·바이오

```yaml
대상:
  - 상급종합병원, 대학병원
  - 제약·바이오 연구소
  - 건강보험 관련 기관

규제 요건:
  - 개인정보보호법 → EMR 외부 전송 금지
  - 의료기기 소프트웨어 규정 (SaMD)
  - HIPAA 준수 (글로벌 진출 시)

DataPond 역할:
  - 임상 데이터 Lakehouse (내부망)
  - 신약 개발 ML 파이프라인
  - 유전체 데이터 분석
```

#### Tier 4: 제조·에너지·통신

```yaml
대상:
  - 반도체, 자동차, 중공업
  - 발전소, 석유화학, 에너지
  - 통신사 (SKT, KT, LGU+)

규제 요건:
  - OT(Operational Technology) 망 분리
  - 산업 기밀 데이터 외부 반출 금지
  - 공장 자동화 데이터 내재화

DataPond 역할:
  - 공장 IoT 데이터 실시간 분석 (RisingWave)
  - 설비 예지보전 ML
  - 생산 최적화 AI
```

---

## 🏆 핵심 가치 제안

### 1. Databricks가 없는 곳에서의 유일한 선택

```yaml
시장 공백:
  "온프렘에서 Databricks 수준의 플랫폼을 쓰고 싶은데 없다"

기존 선택지의 한계:
  Databricks/Snowflake: SaaS 전용, 내부망 불가
  Cloudera CDP: 레거시 Hadoop 기반, AI 기능 취약
  자체 개발 스택: 통합 부재, 유지보수 인력 과다

DataPond의 답:
  - Kubernetes 네이티브 → 어떤 인프라에서도 동작
  - 에어갭 설치 지원 → 외부 인터넷 없이 배포 가능
  - 엔터프라이즈 거버넌스 내장 (Apache Polaris)
  - AI-Native → LiteLLM으로 내부망 LLM 연동 가능
```

### 2. AI-Native 설계 (사후 추가가 아닌 핵심 아키텍처)

```yaml
Databricks AI는:
  - 클라우드 외부 API 의존 (GPT, Gemini)
  - 데이터가 외부로 나가는 구조
  - 내부망 LLM 연동 불가

DataPond AI는:
  - LiteLLM 내장 → 내부망 LLM (Ollama, vLLM) 연결 가능
  - 데이터가 내부망 밖으로 나가지 않음
  - Claude/GPT/로컬 모델 선택적 사용
  - AI가 데이터 레이크 내에서 동작

실제 사용 시나리오:
  - 금융사 내부 Llama3 모델 → 고객 데이터로 SQL 생성
  - 병원 내부망 → 환자 데이터 AI 분석 (외부 유출 없음)
  - 국방 에어갭 → 자체 LLM으로 정보 분석
```

### 3. 엔터프라이즈 거버넌스 내장

```yaml
Apache Polaris (Unity Catalog 수준):
  - RBAC: 테이블/스키마/컬럼 레벨 권한
  - 멀티테넌시: 부서별 데이터 격리
  - 감사 로그: 누가 언제 무엇을 조회했는지
  - 규정 준수: GDPR, 개인정보보호법 준수 증빙

OpenMetadata (자동 Lineage):
  - 데이터 출처 자동 추적
  - 규제 감사 대응 (데이터 흐름 증명)
  - PII 자동 분류

이것이 왜 중요한가:
  - 금감원 검사 시 "이 데이터 어디서 왔어?" → 즉시 답변 가능
  - 개인정보 유출 사고 시 영향 범위 즉시 파악
  - ISO 27001, ISMS-P 심사 대응
```

### 4. 실시간 + 배치 통합

```yaml
제조·금융의 요구:
  - 공장 센서 데이터: 밀리초 단위 이상 감지
  - 금융 거래: 실시간 사기 탐지
  - 의료: 실시간 환자 모니터링

DataPond 해법:
  - RisingWave: PostgreSQL SQL로 스트리밍 처리
  - 배치(Spark) + 실시간(RisingWave) 동일 Lakehouse에 저장
  - 운영 복잡도 최소화 (Kafka+Flink → RisingWave 단일화)
```

---

## 🆚 경쟁 포지셔닝

### 실제 경쟁자

DataPond의 경쟁 구도는 "Databricks 대비 가격"이 아니다. DataPond가 들어가는 환경에서의 실제 대안들:

| 경쟁자 | 실제 현황 | DataPond 차별화 |
|--------|-----------|----------------|
| **Cloudera CDP** | Hadoop 레거시, AI 기능 빈약 | 현대 Lakehouse 아키텍처 + AI Native |
| **자체 개발 스택** | 통합 없음, 유지보수 인력 과다 | 5분 배포, 엔터프라이즈 기능 내장 |
| **Oracle/Teradata** | 고비용, 클로즈드 생태계 | Kubernetes 표준, 오픈 포맷 |
| **HPE Ezmeral** | 복잡, 특정 하드웨어 종속 | 하드웨어 독립, K8s 기반 |
| **아무것도 안 함** | Excel + 수동 분석 | 데이터 팀 생산성 혁신 |

### Databricks와의 관계

Databricks는 **직접 경쟁자가 아니다**. 오히려 DataPond의 시장을 정의해주는 기준점이다.

```
"Databricks를 쓰고 싶지만 클라우드에 데이터를 올릴 수 없는 조직"
= DataPond의 핵심 고객
```

Databricks가 성장할수록 → "Databricks 같은 걸 내부망에서" 수요 증가 → DataPond 시장 확대

---

## 🗺️ 제품 로드맵

### Phase 1: 온프렘 배포 완성도 (현재 ~ 3개월)

```yaml
목표: 규제 환경에서 걱정 없이 배포할 수 있는 제품

핵심 과제:
  에어갭 지원:
    - 이미지 레지스트리 내재화 (harbor 통합)
    - 오프라인 Helm Chart 패키지
    - 인터넷 없이 완전 동작 검증

  보안 강화:
    - TLS 전 구간 암호화
    - Secret 관리 (HashiCorp Vault 통합)
    - Kubernetes RBAC 최소 권한 원칙

  운영 편의:
    - 단일 노드 → 멀티 노드 마이그레이션 가이드
    - 백업/복구 자동화
    - 모니터링 대시보드 (Prometheus + Grafana)

  인증 준비:
    - CC(Common Criteria) 요건 분석
    - ISMS-P 체크리스트 대응
```

### Phase 2: 엔터프라이즈 거버넌스 완성 (3~6개월)

```yaml
목표: 금융·공공 고객의 규제 요건 100% 충족

핵심 과제:
  인증·인가:
    - LDAP/Active Directory 통합
    - SAML 2.0 / OpenID Connect
    - MFA 지원

  고급 거버넌스:
    - 행/열 레벨 보안 (Polaris 확장)
    - 데이터 마스킹 정책
    - 감사 로그 무결성 보장 (tamper-proof)
    - 데이터 분류 레이블 (기밀/내부/일반)

  규정 준수:
    - 개인정보보호법 Right-to-Erasure 지원
    - 데이터 보존 정책 자동화
    - 규정 준수 리포팅 자동화
```

### Phase 3: AI-Native 기능 고도화 (6~12개월)

```yaml
목표: 내부망에서도 최고 수준의 AI 경험

핵심 과제:
  내부망 LLM 최적화:
    - vLLM / Ollama 자동 배포
    - GPU 노드 자동 스케줄링
    - 모델 레지스트리 (MLflow 연동)

  AI 기능 확장:
    - 자연어 SQL (스키마 인식 자동완성)
    - 이상 탐지 자동화 (데이터 품질)
    - AI 파이프라인 오케스트레이션
    - RAG (Retrieval-Augmented Generation) 내장

  Vector DB 통합:
    - pgvector (PostgreSQL 확장)
    - Milvus / Qdrant 옵션
    - 시맨틱 데이터 검색
```

### Phase 4: 산업별 솔루션 (12개월+)

```yaml
금융 패키지:
  - 거래 분석 사전 빌트인 DAG
  - 리스크 모델 템플릿
  - 금감원 보고서 자동화

공공 패키지:
  - 클라우드 보안인증(CSAP) 대응 설정
  - 공공데이터 수집 커넥터
  - 통계청 데이터 연동

의료 패키지:
  - FHIR 커넥터
  - 임상 데이터 Medallion 아키텍처
  - 의료 AI 모델 마켓플레이스

제조 패키지:
  - OPC-UA / MQTT 커넥터
  - 설비 예지보전 템플릿
  - 품질 관리 이상 탐지
```

---

## 💰 비즈니스 모델

### 제품 판매 모델 (엔터프라이즈 소프트웨어)

```yaml
기본 원칙:
  - 오픈소스 공개: 당장 고려 안 함
  - 가격 경쟁: 포지셔닝 전략 아님
  - 포지셔닝: 엔터프라이즈 소프트웨어 (Databricks 진입 불가 시장)

라이선스 모델:
  제품 라이선스:
    - 노드 기반 (Core-based / Node-based)
    - 연간 계약 (SLA 포함)
    - 사이트 라이선스 (대규모 배포)

  에디션:
    Standard:
      - 단일 클러스터
      - 기본 거버넌스
      - 커뮤니티 지원

    Enterprise:
      - 멀티 클러스터
      - 고급 거버넌스 (행/열 보안, LDAP, SSO)
      - 에어갭 지원
      - 전담 기술 지원 (24/7)
      - SLA 보장

    Government:
      - Enterprise 기능 전체
      - CC 인증 대응 문서
      - 망분리 설치 가이드
      - 전담 SA(Solution Architect)

Professional Services:
  - 구축 컨설팅: 설치 + 아키텍처 설계
  - 데이터 마이그레이션
  - 교육 프로그램 (관리자, 개발자, 데이터 분석가)
  - 유지보수 계약
```

### 영업 전략

```yaml
채널:
  직접 영업:
    - 타겟: CIO, CDO, 데이터 아키텍트
    - 접근: POC(개념 검증) 우선
    - 기간: 3-6개월 세일즈 사이클

  SI 파트너:
    - 삼성SDS, LG CNS, SK C&C 등 대형 SI
    - 금융·공공 프로젝트 참여
    - SI가 DataPond를 솔루션으로 제안

  RFP 대응:
    - 금융사 차세대 시스템 구축 RFP
    - 공공기관 데이터 플랫폼 구축 사업
    - 국방부 데이터 분석 인프라

레퍼런스 전략:
  - 1호 고객: 파일럿 프로젝트 (무상 또는 저가)
  - 성공 사례 작성 (허락 하에)
  - 동종 업계 확산 (금융 1곳 → 다른 금융사)
```

---

## 📊 성공 지표

### 제품 성숙도 (1년 내)

```yaml
기술:
  - 에어갭 환경 배포 성공률: 95%+
  - 업타임 SLA: 99.9%
  - 보안 취약점 CVE: Critical 0건

고객:
  - 파일럿 고객 (Tier 1): 3개사
  - 정식 계약 고객: 2개사
  - 고객 NPS: 40+

파트너:
  - SI 파트너 계약: 2개사
  - 클라우드 파트너 (on-prem 전용 클라우드): 1개사
```

---

## 🎯 핵심 메시지

### 한 줄 포지셔닝

```
"DataPond는 Databricks가 들어올 수 없는 곳에서
엔터프라이즈 AI 데이터 플랫폼을 운영하는 유일한 방법입니다."
```

### 산업별 메시지

**금융사 CIO/CDO에게:**
> "금감원 규제와 망분리 의무를 지키면서 데이터 팀의 생산성을
> Databricks 수준으로 끌어올릴 수 있습니다."

**공공기관 IT 담당자에게:**
> "에어갭 환경에서도 완전히 동작하는 AI-Native 데이터 플랫폼입니다.
> 인터넷 연결 없이 설치부터 운영까지 가능합니다."

**의료기관 정보화 담당자에게:**
> "환자 데이터가 병원 밖으로 나가지 않으면서
> AI 기반 임상 데이터 분석을 시작할 수 있습니다."

**제조사 데이터 엔지니어에게:**
> "OT 망에서 직접 IoT 데이터를 실시간 분석하고
> 예지보전 AI를 구동하는 가장 빠른 방법입니다."
