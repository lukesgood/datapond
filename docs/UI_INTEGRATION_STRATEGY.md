# DataPond UI 통합 및 유지보수 전략

**작성일**: 2026-04-28  
**버전**: 1.0.0  
**목적**: UI 통합 문제 해결 및 장기 유지보수 전략

---

## 📋 문제 정의

### 현재 상황

```yaml
DataPond 컴포넌트별 UI:
  1. Frontend (Next.js): 자체 개발 ✅
  2. Backend (FastAPI): API only ✅
  3. JupyterLab: 독립 UI (포트 8888) ⚠️
  4. Airflow: 독립 UI (포트 8080) ⚠️
  5. MLflow: 독립 UI (포트 5000) ⚠️
  6. Trino: CLI only (UI 없음) ⚠️
  7. Airbyte: 독립 UI (포트 8000) ⚠️
  8. LiteLLM: API only ✅

문제점:
  - 🔴 7개의 별도 로그인
  - 🔴 일관성 없는 UI/UX
  - 🔴 네비게이션 복잡 (URL 여러 개)
  - 🔴 SSO 불가능
  - 🔴 유지보수 복잡 (각 UI 버전 관리)
```

### 사용자 경험 문제

```yaml
Bad UX:
  사용자: "파이프라인 만들고 싶어요"
  
  현재:
    1. Frontend 로그인
    2. Airflow URL 클릭 → 새 탭
    3. Airflow 재로그인
    4. DAG 작성
    5. Frontend 돌아와서 상태 확인?
  
  문제: 컨텍스트 전환 과다, 혼란스러움

Good UX:
  사용자: "파이프라인 만들고 싶어요"
  
  목표:
    1. Frontend 로그인 (한 번만)
    2. "Pipelines" 메뉴 클릭
    3. DAG 작성 (통합 UI)
    4. 실행 & 모니터링 (같은 화면)
  
  목표: 단일 인터페이스, 일관된 경험
```

---

## 🎯 해결책: 3단계 UI 통합 전략

### Strategy 1: Single Pane of Glass (권장)

**개념**: 모든 기능을 하나의 Frontend에서 접근

```
┌──────────────────────────────────────────────────────┐
│           DataPond Frontend (Next.js)                │
│                                                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ Home    │ │Pipelines│ │ SQL Lab │ │ ML Exp  │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │          Unified Content Area                │  │
│  │                                              │  │
│  │  [iframe 또는 API 기반 UI 렌더링]             │  │
│  │                                              │  │
│  └──────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
          │           │           │           │
          ▼           ▼           ▼           ▼
    ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
    │Airflow │  │ Trino  │  │ MLflow │  │Airbyte │
    │  API   │  │  API   │  │  API   │  │  API   │
    └────────┘  └────────┘  └────────┘  └────────┘
```

#### Approach A: iframe Embedding (단기 - 2주)

**장점**:
- ✅ 빠른 구현 (기존 UI 재사용)
- ✅ 각 서비스 독립 업데이트
- ✅ Single Sign-On (SSO) 가능

**단점**:
- ⚠️ 일관된 UX 어려움
- ⚠️ 성능 (iframe 로딩)
- ⚠️ Cross-origin 이슈

**구현**:
```typescript
// frontend/src/pages/Pipelines/AirflowView.tsx
import React, { useEffect, useState } from 'react';

export const AirflowView: React.FC = () => {
  const [airflowUrl, setAirflowUrl] = useState('');
  const user = useUser();
  
  useEffect(() => {
    // 1. Backend에서 임시 Airflow 토큰 생성
    const token = await generateAirflowToken(user.id);
    
    // 2. iframe URL에 토큰 포함
    setAirflowUrl(`http://datapond.local/airflow?token=${token}`);
  }, [user]);
  
  return (
    <div className="airflow-view">
      <Breadcrumb>
        <Link to="/">Home</Link> / <span>Pipelines</span>
      </Breadcrumb>
      
      <iframe
        src={airflowUrl}
        style={{ width: '100%', height: 'calc(100vh - 64px)', border: 'none' }}
        title="Airflow"
      />
    </div>
  );
};
```

**SSO 구현**:
```python
# backend/app/api/sso.py
from fastapi import APIRouter, Depends
from app.auth import get_current_user
import jwt
import requests

router = APIRouter(prefix="/api/sso", tags=["SSO"])

@router.post("/airflow/token")
async def generate_airflow_token(user = Depends(get_current_user)):
    """Airflow 임시 토큰 생성 (SSO)"""
    
    # 1. Airflow API에 사용자 생성/동기화
    airflow_api = "http://airflow-webserver:8080/api/v1"
    
    # Airflow에 사용자 없으면 생성
    response = requests.get(
        f"{airflow_api}/users/{user.username}",
        auth=("admin", get_airflow_admin_password())
    )
    
    if response.status_code == 404:
        # 사용자 생성
        requests.post(
            f"{airflow_api}/users",
            json={
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "roles": [{"name": map_role(user.role)}]
            },
            auth=("admin", get_airflow_admin_password())
        )
    
    # 2. 임시 토큰 생성 (10분 유효)
    token = jwt.encode(
        {
            "username": user.username,
            "exp": datetime.utcnow() + timedelta(minutes=10)
        },
        secret=AIRFLOW_SECRET_KEY,
        algorithm="HS256"
    )
    
    return {"token": token}
```

#### Approach B: API-Driven UI (중기 - 2개월)

**개념**: 각 서비스의 API를 직접 호출하여 자체 UI 구축

**장점**:
- ✅ 완전히 일관된 UX
- ✅ 성능 우수
- ✅ 커스터마이징 자유

**단점**:
- ⚠️ 개발 시간 많이 소요
- ⚠️ 각 서비스 API 변경 시 대응 필요

**구현 예시 - Airflow**:
```typescript
// frontend/src/pages/Pipelines/PipelineList.tsx
import React, { useEffect, useState } from 'react';
import { AirflowAPI } from '../../services/airflowApi';

export const PipelineList: React.FC = () => {
  const [dags, setDags] = useState([]);
  
  useEffect(() => {
    // Airflow REST API 호출 (Backend 프록시 통과)
    AirflowAPI.getDags().then(setDags);
  }, []);
  
  return (
    <div className="pipeline-list">
      <PageHeader title="Pipelines" />
      
      <Button onClick={() => navigate('/pipelines/new')}>
        + New Pipeline
      </Button>
      
      <Table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Schedule</th>
            <th>Last Run</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {dags.map(dag => (
            <tr key={dag.dag_id}>
              <td>
                <Link to={`/pipelines/${dag.dag_id}`}>
                  {dag.dag_id}
                </Link>
              </td>
              <td>{dag.schedule_interval}</td>
              <td>{formatDate(dag.last_run)}</td>
              <td>
                <StatusBadge status={dag.is_active ? 'active' : 'paused'} />
              </td>
              <td>
                <IconButton onClick={() => triggerDag(dag.dag_id)}>
                  ▶️ Run
                </IconButton>
                <IconButton onClick={() => toggleDag(dag.dag_id)}>
                  ⏸️ Pause
                </IconButton>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
};
```

```typescript
// frontend/src/services/airflowApi.ts
import axios from 'axios';

const airflowClient = axios.create({
  baseURL: '/api/airflow',  // Backend 프록시
  headers: {
    'Authorization': `Bearer ${getToken()}`
  }
});

export class AirflowAPI {
  static async getDags() {
    const response = await airflowClient.get('/dags');
    return response.data.dags;
  }
  
  static async triggerDag(dagId: string, conf?: any) {
    const response = await airflowClient.post(`/dags/${dagId}/dagRuns`, {
      conf: conf
    });
    return response.data;
  }
  
  static async pauseDag(dagId: string) {
    const response = await airflowClient.patch(`/dags/${dagId}`, {
      is_paused: true
    });
    return response.data;
  }
}
```

**Backend 프록시** (API 통합):
```python
# backend/app/api/airflow_proxy.py
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
import httpx

router = APIRouter(prefix="/api/airflow", tags=["Airflow"])

AIRFLOW_URL = "http://airflow-webserver:8080/api/v1"

@router.get("/dags")
async def list_dags(user = Depends(get_current_user)):
    """Airflow DAG 목록"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIRFLOW_URL}/dags",
            auth=(user.username, get_airflow_token(user))
        )
        return response.json()

@router.post("/dags/{dag_id}/dagRuns")
async def trigger_dag(
    dag_id: str,
    conf: dict = None,
    user = Depends(get_current_user)
):
    """DAG 실행"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIRFLOW_URL}/dags/{dag_id}/dagRuns",
            json={"conf": conf or {}},
            auth=(user.username, get_airflow_token(user))
        )
        return response.json()
```

#### Approach C: Micro-Frontend (장기 - 6개월)

**개념**: 각 서비스를 독립 Micro-Frontend로, 런타임에 통합

**장점**:
- ✅ 각 팀 독립 개발
- ✅ 독립 배포
- ✅ 기술 스택 자유

**단점**:
- ⚠️ 복잡한 아키�ecture
- ⚠️ 번들 크기

**구현 (Module Federation)**:
```javascript
// frontend/next.config.js (Host)
const { ModuleFederationPlugin } = require('webpack').container;

module.exports = {
  webpack: (config, { isServer }) => {
    config.plugins.push(
      new ModuleFederationPlugin({
        name: 'datapond',
        remotes: {
          airflow: 'airflow@http://datapond.local/airflow/remoteEntry.js',
          mlflow: 'mlflow@http://datapond.local/mlflow/remoteEntry.js'
        },
        shared: ['react', 'react-dom']
      })
    );
    return config;
  }
};
```

---

## 🔧 Strategy 2: Component 별 전략

### JupyterLab

```yaml
현재:
  - 독립 UI (포트 8888)
  - iframe 또는 별도 탭

권장:
  옵션 A: iframe Embedding (빠름)
    - Frontend에서 iframe으로 JupyterLab 표시
    - SSO 토큰으로 자동 로그인
  
  옵션 B: JupyterHub (중기)
    - JupyterHub로 멀티 사용자 관리
    - DataPond 사용자와 동기화
    - Spawner로 개인 노트북 환경

구현:
  # helm/datapond/values.yaml
  jupyter:
    enabled: true
    mode: "hub"  # lab 또는 hub
    
    # JupyterHub 설정
    hub:
      authenticator: "datapond"  # 커스텀 authenticator
      spawner: "kubernetes"
```

### Airflow

```yaml
현재:
  - 독립 UI (포트 8080)
  
권장:
  Phase 1 (단기): iframe Embedding + SSO
  Phase 2 (중기): API-Driven UI
    - DAG 목록/실행/모니터링 자체 구현
    - 복잡한 DAG 편집은 iframe 또는 코드 에디터

핵심 화면:
  1. DAG 목록 (API-Driven)
  2. DAG 실행 (API-Driven)
  3. DAG 편집 (Code Editor 또는 No-Code Builder)
  4. DAG 모니터링 (API-Driven - 실시간 그래프)
```

### MLflow

```yaml
현재:
  - 독립 UI (포트 5000)

권장:
  Phase 1: iframe Embedding
  Phase 2: API-Driven UI
    - Experiments 목록
    - Runs 비교
    - Model Registry
    
핵심 화면:
  1. Experiments List (API-Driven)
  2. Run Details (API-Driven)
  3. Model Registry (API-Driven)
  4. Model Deployment (새로 구현)
```

### Trino (SQL Lab)

```yaml
현재:
  - UI 없음 (CLI only)

권장:
  완전 자체 구현 (API-Driven)
  
핵심 기능:
  1. SQL Editor (Monaco Editor)
  2. Query History
  3. Results Table (pagination)
  4. Visualization (Chart.js)
  5. Export (CSV, JSON, Parquet)

참고 프로젝트:
  - Apache Superset SQL Lab
  - Redash Query Editor
  - Metabase Query Builder
```

### Airbyte

```yaml
현재:
  - 독립 UI (포트 8000)

권장:
  Phase 1: iframe Embedding
  Phase 2: Smart Ingestion UI (완전 자체 구현)
    - 이미 설계됨 (DATA_INGESTION_LAYER.md)
    - 6-step wizard
    - AI 추천 UI

핵심: Airbyte UI는 복잡하므로 자체 간소화 UI 권장
```

---

## 🎨 UI 일관성 전략

### Design System

```yaml
구축 필요:
  - Component Library (Button, Input, Table, etc.)
  - Color Palette
  - Typography
  - Icons
  - Spacing/Grid System

도구:
  - Tailwind CSS (이미 사용 중)
  - shadcn/ui (컴포넌트 라이브러리)
  - Radix UI (접근성)
  - Storybook (컴포넌트 문서화)
```

**구현**:
```typescript
// frontend/src/components/ui/DataTable.tsx
// 모든 화면에서 재사용 가능한 공통 테이블 컴포넌트

import React from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({ data, columns, onRowClick }: DataTableProps<T>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHead key={column.id}>{column.header}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((row, i) => (
          <TableRow
            key={i}
            onClick={() => onRowClick?.(row)}
            className="cursor-pointer hover:bg-gray-50"
          >
            {columns.map((column) => (
              <TableCell key={column.id}>
                {column.cell(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

### Navigation Structure

```yaml
통일된 네비게이션:
  - Top Navigation: Logo, Search, User Menu
  - Side Navigation: Main menu
  - Breadcrumb: 현재 위치

메뉴 구조:
  🏠 Home
  📊 Data
    - Sources (Airbyte)
    - Catalog (통합 카탈로그)
    - SQL Lab (Trino)
  🔄 Pipelines
    - DAGs (Airflow)
    - Runs
    - Schedule
  🧪 ML
    - Experiments (MLflow)
    - Models (Model Registry)
    - Notebooks (JupyterLab)
  📈 Monitoring
    - Jobs
    - Resources
    - Costs
  ⚙️ Admin
    - Users
    - Connections
    - Settings
```

---

## 🔄 유지보수 전략

### Version Management

```yaml
문제:
  - Airflow 2.x → 3.x 업그레이드
  - MLflow 1.x → 2.x
  - API 변경 시 Frontend 깨짐

해결책:
  1. Helm Chart Dependency Lock
     dependencies:
       - name: airflow
         version: "~1.10.0"  # Minor 버전만 자동 업데이트
  
  2. API Versioning
     /api/v1/airflow/dags  # 버전별 엔드포인트
  
  3. Feature Flags
     if (features.airflowV3) {
       // 새 API 사용
     } else {
       // 기존 API 사용
     }
  
  4. Integration Tests
     - Cypress E2E 테스트
     - API contract testing
```

### Backend API Abstraction Layer

```python
# backend/app/services/pipeline_service.py
# Airflow API를 추상화하여 버전 변경에 대응

from abc import ABC, abstractmethod

class PipelineService(ABC):
    """파이프라인 추상화 레이어"""
    
    @abstractmethod
    async def list_pipelines(self) -> List[Pipeline]:
        pass
    
    @abstractmethod
    async def trigger_pipeline(self, pipeline_id: str) -> RunInfo:
        pass

class AirflowPipelineService(PipelineService):
    """Airflow 구현"""
    
    def __init__(self, airflow_version: str):
        self.version = airflow_version
        if airflow_version.startswith("2"):
            self.client = AirflowV2Client()
        else:
            self.client = AirflowV3Client()
    
    async def list_pipelines(self):
        # Airflow API 호출하여 공통 Pipeline 모델로 변환
        dags = await self.client.get_dags()
        return [self._convert_to_pipeline(dag) for dag in dags]
    
    def _convert_to_pipeline(self, dag):
        """Airflow DAG → Pipeline 모델 변환"""
        return Pipeline(
            id=dag["dag_id"],
            name=dag["dag_id"],
            schedule=dag["schedule_interval"],
            last_run=dag.get("last_run"),
            status="active" if dag["is_active"] else "paused"
        )

# Frontend는 PipelineService만 알면 됨 (Airflow 버전 무관)
```

### Upgrade Strategy

```yaml
Helm Chart Upgrade:
  # 1. 테스트 환경에서 먼저 업그레이드
  helm upgrade datapond-test ./helm/datapond \
    --set airflow.version=2.9.0 \
    -n datapond-test
  
  # 2. Integration Tests 실행
  npm run test:e2e
  
  # 3. 문제 없으면 프로덕션 업그레이드
  helm upgrade datapond ./helm/datapond \
    --set airflow.version=2.9.0 \
    -n datapond \
    --wait --timeout 10m

Rolling Update:
  - 기본값: RollingUpdate (무중단)
  - maxSurge: 1
  - maxUnavailable: 0
```

### Monitoring & Alerting

```yaml
모니터링:
  - API 응답 시간
  - 에러율
  - 각 서비스 헬스 체크

알림:
  - Airflow API 에러 → Slack
  - MLflow 연결 실패 → Discord
  - Airbyte sync 실패 → Email

도구:
  - Prometheus (메트릭 수집)
  - Grafana (대시보드)
  - AlertManager (알림)
```

---

## 📊 Implementation Roadmap

### Phase 1: Quick Wins (2주)

```yaml
목표: 사용 가능한 통합 UI

작업:
  - [ ] Frontend에 통합 네비게이션 추가
  - [ ] iframe으로 Airflow, MLflow, JupyterLab 임베딩
  - [ ] SSO 토큰 기반 자동 로그인
  - [ ] Breadcrumb 네비게이션

결과:
  - 단일 로그인
  - 일관된 네비게이션
  - 여전히 각 UI는 원본 그대로
```

### Phase 2: Core Features (2개월)

```yaml
목표: 핵심 화면 자체 구현

작업:
  - [ ] SQL Lab (Trino) - 완전 자체 구현
  - [ ] Pipeline 목록/실행 (Airflow API)
  - [ ] Experiment 목록 (MLflow API)
  - [ ] Smart Ingestion UI (Airbyte 대체)
  - [ ] 통합 Design System

결과:
  - 80% 자체 UI
  - 20% iframe (복잡한 화면만)
```

### Phase 3: Advanced Integration (6개월)

```yaml
목표: 완전 통합 + Micro-Frontend

작업:
  - [ ] Micro-Frontend 아키텍처
  - [ ] 모든 화면 자체 구현
  - [ ] Advanced 워크플로우
  - [ ] Mobile 대응

결과:
  - 100% 일관된 UX
  - 독립 배포 가능
```

---

## 🎯 권장 전략

### 단기 (첫 출시)

```yaml
접근: Pragmatic Hybrid

구현:
  ✅ 자체 구현:
    - Home Dashboard
    - Data Catalog
    - SQL Lab (Trino)
    - Smart Ingestion (Airbyte 대체)
  
  ⚠️ iframe Embedding:
    - JupyterLab (복잡, 자주 사용)
    - Airflow DAG 편집기 (복잡)
    - MLflow Experiment 상세

이유:
  - 빠른 출시 (2주)
  - 핵심 가치 제공
  - 점진적 개선 가능
```

### 중기 (3-6개월)

```yaml
접근: API-Driven UI

목표:
  - iframe 제거 (JupyterLab 제외)
  - 모든 주요 화면 자체 구현
  - 일관된 UX

우선순위:
  1. Airflow (Pipeline 관리)
  2. MLflow (Experiment 추적)
  3. Airbyte (완전 대체)
```

### 장기 (12개월+)

```yaml
접근: Micro-Frontend

목표:
  - 완전한 통합 플랫폼
  - 각 모듈 독립 배포
  - Enterprise Edition 기능

참고: Databricks, Snowflake 수준
```

---

## 🚨 Risks & Mitigation

### Risk 1: iframe 성능 문제

```yaml
증상: 느린 로딩, 메모리 사용 증가
완화:
  - Lazy loading (필요할 때만 로드)
  - iframe unload (탭 전환 시)
  - 경량 화면 우선 자체 구현
```

### Risk 2: API 버전 호환성

```yaml
증상: Airflow 업그레이드 후 Frontend 깨짐
완화:
  - API Abstraction Layer
  - Integration Tests (CI/CD)
  - Version pinning (Helm)
  - Gradual rollout
```

### Risk 3: 개발 리소스 부족

```yaml
증상: 모든 UI 자체 구현 시간 없음
완화:
  - Phase별 점진적 구현
  - 우선순위 명확화 (핵심 먼저)
  - 커뮤니티 기여 활용
  - Open source UI 컴포넌트 재사용
```

---

## 📝 Conclusion

### 권장 전략 요약

```yaml
지금 (첫 출시):
  ✅ iframe Embedding + SSO
  ✅ 통합 네비게이션
  ✅ SQL Lab 자체 구현
  
  시간: 2주
  효과: 사용 가능한 제품

3개월 후:
  ✅ 80% API-Driven UI
  ✅ Airflow/MLflow 핵심 화면
  ✅ Design System
  
  시간: 2개월
  효과: 일관된 UX

12개월 후:
  ✅ Micro-Frontend
  ✅ 100% 자체 UI
  ✅ Enterprise 기능
  
  시간: 6개월
  효과: Databricks 수준
```

### 핵심 원칙

1. **Progressive Enhancement** - 점진적 개선
2. **Pragmatic Approach** - 실용적 접근 (완벽주의 금지)
3. **User First** - 사용자 경험 최우선
4. **Maintainability** - 유지보수 가능성 고려

이 전략으로 DataPond는 **실용적이면서도 확장 가능한 UI**를 구축할 수 있습니다! 🚀
