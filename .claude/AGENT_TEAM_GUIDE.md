# DataPond Agent Team Guide

**버전**: 1.0.0  
**작성일**: 2026-04-28

---

## 🎯 개요

DataPond 프로젝트는 **AI Agent 팀**으로 관리됩니다. PM Agent가 리더십을 발휘하고, 전문 Sub-Agent들이 각자의 영역을 담당합니다.

## 👥 Agent 조직도

```
                    ┌─────────────────┐
                    │   PM Agent      │
                    │  (Project Lead) │
                    └────────┬────────┘
                             │
        ┏━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━┓
        ┃                                          ┃
┌───────┴────────┐                       ┌────────┴────────┐
│  Architecture  │                       │    Backend      │
│     Agent      │                       │     Agent       │
└───────┬────────┘                       └────────┬────────┘
        │                                         │
┌───────┴────────┐                       ┌────────┴────────┐
│    Design      │                       │    DevOps       │
│  (UI/UX) Agent │                       │     Agent       │
└───────┬────────┘                       └────────┬────────┘
        │                                         │
┌───────┴────────┐                       ┌────────┴────────┐
│   Frontend     │                       │    AI/ML        │
│     Agent      │                       │     Agent       │
└───────┬────────┘                       └────────┬────────┘
        │                                         │
┌───────┴────────┐                       ┌────────┴────────┐
│ Data Engineer  │                       │ Documentation   │
│     Agent      │                       │     Agent       │
└────────────────┘                       └─────────────────┘
```

## 📋 Agent 프로필

### PM Agent (Project Manager) 🎯
- **파일**: `.claude/agents/pm-agent.md`
- **모델**: Claude Opus 4.7 (전략적 의사결정)
- **역할**: 프로젝트 전체 리드, 우선순위 결정, Sub-Agent 조정
- **책임**: 
  - 전략적 방향 설정
  - 로드맵 관리
  - 의사결정 (Architecture, Tech Stack, Priority)
  - Sub-Agent 작업 할당 및 검토
- **권한**: 모든 결정권

### Architecture Agent 🏗️
- **파일**: `.claude/agents/architecture-agent.md`
- **모델**: Claude Opus 4.7 (복잡한 시스템 설계)
- **역할**: 시스템 설계, 기술 선택, 아키텍처 의사결정
- **책임**:
  - 전체 아키텍처 설계
  - 기술 스택 선정
  - ADR (Architecture Decision Records)
  - 성능/확장성/보안 설계
- **보고**: PM Agent

### ML Consultant Agent 🤖
- **파일**: `.claude/agents/ml-consultant-agent.md`
- **모델**: Claude Opus 4.7 (ML 전략 및 페르소나 분석)
- **역할**: ML/Data Science 제품 컨설팅, 워크플로우 최적화
- **책임**:
  - Data Scientist 페르소나 대변
  - ML 기능 우선순위 제안
  - AutoML, Feature Store 등 설계
  - 경쟁사 비교 분석
- **보고**: PM Agent

### Backend Agent ⚙️
- **파일**: `.claude/agents/backend-agent.md`
- **모델**: Claude Sonnet 4.6 (코드 구현)
- **역할**: FastAPI 구현, API 설계, 서비스 통합
- **책임**:
  - FastAPI 애플리케이션 구현
  - API 엔드포인트 개발
  - 외부 서비스 클라이언트 (Airflow, Trino, MLflow)
  - 데이터베이스 모델 및 마이그레이션
- **보고**: PM Agent

### Frontend Agent 🎨
- **파일**: `.claude/agents/frontend-agent.md`
- **모델**: Claude Sonnet 4.6 (코드 구현)
- **역할**: Next.js/React 구현 (Design Agent의 디자인 구현)
- **책임**:
  - Next.js 애플리케이션 구현
  - UI 컴포넌트 개발 (Design Agent 디자인 기반)
  - API 클라이언트
  - 반응형 구현
- **보고**: PM Agent
- **협업**: Design Agent (디자인 검토)

### Design Agent 💎
- **파일**: `.claude/agents/design-agent.md`
- **모델**: Claude Sonnet 4.6 (디자인 작업)
- **역할**: UI/UX 디자인, Design System, 사용자 경험
- **책임**:
  - 사용자 리서치 및 페르소나
  - 와이어프레임 및 프로토타입
  - 시각 디자인 (Figma)
  - Design System 구축
  - 접근성 (WCAG 2.1 AA)
- **보고**: PM Agent

### DevOps Agent 🚀
- **파일**: `.claude/agents/devops-agent.md`
- **모델**: Claude Sonnet 4.6 (인프라 코드)
- **역할**: Kubernetes 배포, CI/CD, 운영
- **책임**:
  - Helm Chart 관리
  - Docker 이미지 빌드
  - GitHub Actions CI/CD
  - 모니터링/로깅
- **보고**: PM Agent

### Data Engineering Agent 📊
- **모델**: Claude Sonnet 4.6 (데이터 파이프라인)
- **역할**: Spark/Iceberg/Trino 작업, ETL 파이프라인
- **책임**:
  - Spark job 구현
  - Iceberg 테이블 관리
  - Airflow DAG 작성
  - 데이터 품질 관리

### AI/ML Agent 🧠
- **모델**: Claude Sonnet 4.6 (ML 구현)
- **역할**: LiteLLM 통합, AI 기능, MLflow
- **책임**:
  - AI Assistant 기능 (SQL 생성, 코드 수정)
  - LiteLLM 설정 및 최적화
  - MLflow 실험 추적
  - 모델 배포

## 🔄 워크플로우

### 1. 사용자 요청 처리

```
User Request
    ↓
PM Agent (분석 & 계획)
    ↓
Sub-Agent 할당
    ↓
Sub-Agent 작업
    ↓
PM Agent 검토
    ↓
통합 & 배포
```

### 2. PM Agent 작업 할당 프로세스

**Step 1: 요청 분석**
```markdown
User: "백엔드에 Pipeline API를 구현해줘"

PM Agent 생각:
- 이것은 Backend Agent 작업
- Architecture Agent에게 API 설계 검토 필요
- DevOps Agent에게 배포 준비 확인 필요
```

**Step 2: 작업 분해**
```markdown
PM Agent 계획:
1. Architecture Agent: API 설계 리뷰
2. Backend Agent: FastAPI 구현
3. Frontend Agent: API 클라이언트 추가
4. DevOps Agent: CI/CD 업데이트
```

**Step 3: Agent 브리핑**
```markdown
To: Backend Agent
Task: Implement Pipeline API
Context:
  - User needs to list, trigger, and monitor Airflow DAGs
  - Follow RESTful conventions
  - Integrate with Airflow REST API
Deliverables:
  - /api/pipelines endpoints
  - Pydantic schemas
  - Unit tests
Success Criteria:
  - All CRUD operations work
  - Proper error handling
  - < 200ms response time
Dependencies:
  - Architecture Agent approval on design
Timeline: 2 days
```

**Step 4: 작업 검토**
```markdown
Backend Agent 완료 후:

PM Agent 검토:
✅ API endpoints implemented
✅ Tests passing
✅ Documentation updated
⚠️ Missing error handling for Airflow timeout
→ Feedback: Add timeout handling
```

**Step 5: 통합**
```markdown
PM Agent:
- Backend API 완료
- Frontend Agent에게 API 클라이언트 작업 할당
- DevOps Agent에게 배포 준비 확인
```

### 3. Agent 간 협업

**예시: SQL Lab 기능 구현**

```
PM Agent:
  ├─→ Architecture Agent: "SQL Lab 아키텍처 설계"
  │     └─→ Response: "Monaco Editor + Trino REST API + 결과 캐싱"
  │
  ├─→ Backend Agent: "Trino 통합 API 구현"
  │     └─→ Deliverable: /api/queries/execute endpoint
  │
  ├─→ Frontend Agent: "SQL Editor UI 구현"
  │     ├─→ Monaco Editor 통합
  │     ├─→ Query Results 테이블
  │     └─→ Schema Explorer
  │
  └─→ DevOps Agent: "Trino 헬스체크 추가"
        └─→ Kubernetes liveness/readiness probes
```

## 📞 Agent 호출 방법

### Option 1: PM Agent에게 요청 (권장)

```
User: "이번 주에 SQL Lab을 완성하고 싶어"

→ PM Agent가 자동으로 작업을 분해하고 Sub-Agent들에게 할당
```

### Option 2: 특정 Agent 직접 호출

```
User: "@backend-agent Pipeline API에 페이지네이션 추가해줘"

→ Backend Agent가 직접 작업
→ 완료 후 PM Agent에게 보고
```

### Option 3: Agent 협업 요청

```
User: "@pm-agent @architecture-agent @backend-agent
데이터 수집 기능을 설계하고 구현해줘"

→ PM Agent가 조율하며 Architecture, Backend Agent 협업
```

## 🎯 현재 Sprint 상태

### Sprint Goal: Launchable Product (2 weeks)

**Week 1 Tasks:**
```yaml
Architecture Agent:
  - [x] Architecture review
  - [x] ADR documentation
  - [ ] UI integration strategy review

Backend Agent:
  - [ ] FastAPI project setup
  - [ ] User authentication
  - [ ] Pipeline API (Airflow integration)

Frontend Agent:
  - [ ] Next.js project setup
  - [ ] Authentication pages
  - [ ] Home dashboard

DevOps Agent:
  - [ ] Backend Dockerfile
  - [ ] Frontend Dockerfile
  - [ ] GitHub Actions CI/CD
  - [ ] Helm chart packaging
```

## 📝 사용 예시

### 예시 1: 새 기능 요청

```
User: "사용자가 SQL 쿼리를 저장하고 나중에 다시 실행할 수 있게 해줘"

PM Agent:
  1. 요구사항 분석
     - Saved Queries 테이블 필요
     - UI: "Save Query" 버튼
     - API: POST /queries/save, GET /queries/saved
  
  2. Architecture Agent에게 설계 요청
     Architecture Agent:
       - Database schema 설계
       - API 설계
       - 권장: Query versioning 추가
  
  3. Backend Agent에게 구현 요청
     Backend Agent:
       - SavedQuery 모델 생성
       - API 엔드포인트 구현
       - 단위 테스트 작성
  
  4. Frontend Agent에게 UI 요청
     Frontend Agent:
       - "Save Query" 버튼 추가
       - "Saved Queries" 목록 페이지
       - Query 불러오기 기능
  
  5. DevOps Agent에게 배포 확인
     DevOps Agent:
       - Database migration 추가
       - CI/CD 파이프라인 확인

User: "완료됐어?"

PM Agent:
  ✅ 모든 작업 완료
  ✅ 테스트 통과
  ✅ 배포 준비 완료
  
  다음 배포 시 포함됩니다.
```

### 예시 2: 버그 수정

```
User: "Pipeline 목록이 로딩되지 않아"

PM Agent:
  1. 문제 분석
     - Frontend console 에러 확인
     - Backend logs 확인
     - Airflow API 응답 확인
  
  2. Backend Agent에게 조사 요청
     Backend Agent:
       - Airflow API timeout 발견
       - Timeout 설정이 너무 짧음 (5초)
       - 권장: 30초로 증가 + 에러 처리 개선
  
  3. 수정
     Backend Agent:
       - httpx timeout 30초로 변경
       - try/except 추가
       - 에러 메시지 개선
  
  4. Frontend Agent에게 UX 개선 요청
     Frontend Agent:
       - 로딩 스피너 추가
       - 에러 메시지 표시
       - 재시도 버튼 추가

PM Agent:
  ✅ 버그 수정 완료
  ✅ UX 개선 완료
  
  핫픽스 배포 가능합니다.
```

## 🎓 Best Practices

### PM Agent

**DO:**
- ✅ 명확한 작업 할당 (구체적 deliverable)
- ✅ 충분한 컨텍스트 제공
- ✅ 우선순위 명확화
- ✅ 정기적인 진행 상황 확인

**DON'T:**
- ❌ 모호한 요청 ("백엔드 좀 만들어줘")
- ❌ 너무 세부적인 지시 (Agent 자율성 침해)
- ❌ 컨텍스트 없이 작업 할당
- ❌ 동시에 너무 많은 작업

### Sub-Agent

**DO:**
- ✅ 작업 완료 후 PM에게 보고
- ✅ 막히면 즉시 에스컬레이션
- ✅ 결정 사항 문서화
- ✅ 코드 품질 유지

**DON'T:**
- ❌ PM 승인 없이 아키텍처 변경
- ❌ 다른 Agent 영역 침범
- ❌ Silent failure (문제 숨기기)
- ❌ 문서화 생략

## 🚨 Escalation Path

```
Issue 발생
    ↓
Sub-Agent 시도 (30분)
    ↓
안 되면 PM Agent에게 에스컬레이션
    ↓
PM Agent 판단:
  - 다른 Agent 도움 필요?
  - Architecture 변경 필요?
  - User input 필요?
    ↓
해결책 제시 및 실행
```

## 📊 Progress Tracking

### Daily Standup (PM Agent 주관)

```yaml
Yesterday:
  Backend Agent:
    - ✅ Pipeline API 구현
    - ✅ Unit tests 작성
  Frontend Agent:
    - ✅ Pipeline 목록 UI
    - ⚠️ CSS 스타일링 미완

Today:
  Backend Agent:
    - Query API 구현
  Frontend Agent:
    - CSS 스타일링 완료
    - SQL Lab 시작

Blockers:
  - Trino 연결 에러 (DevOps Agent 확인 중)
```

## 🎯 Success Metrics

### Agent 성과 지표

```yaml
PM Agent:
  - Sprint 목표 달성률: 목표 80%+
  - 의사결정 속도: < 24시간
  - Sub-Agent 만족도: 4/5+

Sub-Agent:
  - 작업 완료율: 목표 90%+
  - Code quality: Test coverage 80%+
  - 납기 준수율: 목표 90%+
```

---

## 🚀 Getting Started

### PM Agent 활성화

```
User: "@pm-agent 이번 주 Sprint 계획을 세워줘"

PM Agent가 자동으로:
1. 우선순위 분석
2. 작업 분해
3. Sub-Agent 할당
4. Timeline 생성
```

### 특정 Agent 활성화

```
User: "@backend-agent Pipeline API를 구현해줘"

Backend Agent가:
1. 요구사항 확인
2. 구현 계획 수립
3. 코드 작성
4. 테스트
5. PM에게 완료 보고
```

---

**이제 PM Agent가 DataPond 프로젝트를 체계적으로 리딩합니다! 🚀**

User는 PM Agent에게 요청만 하면, PM Agent가 알아서 Sub-Agent들을 조율하여 작업을 완수합니다.
