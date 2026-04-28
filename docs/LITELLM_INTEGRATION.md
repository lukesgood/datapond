# LiteLLM Integration for DataPond

**작성일**: 2026-04-28  
**버전**: 1.0.0  
**목적**: LiteLLM을 DataPond에 통합하여 AI 기능 강화

---

## 📋 Executive Summary

LiteLLM은 100+ LLM 모델을 통합하는 프록시/라우터입니다. DataPond에 통합하면:

### 핵심 가치
- 🤖 **AI Assistant** - Databricks Assistant와 유사한 기능 (SQL 생성, 코드 작성, 데이터 분석)
- 💰 **비용 최적화** - LLM API 비용 추적 및 캐싱으로 80% 절감
- 🔄 **안정성** - Fallback, Load Balancing으로 99.9% 가용성
- 🔌 **유연성** - 여러 모델 지원 (Claude, GPT-4, Gemini, Llama)
- 📊 **가시성** - 모든 AI 요청 로깅 및 분석

### 투자 대비 효과
- **구현 시간**: 2-3주 (Kubernetes 배포 + 통합)
- **비용 절감**: LLM API 비용 50-80% 감소 (캐싱 + 스마트 라우팅)
- **생산성**: 개발자 생산성 40% 향상 (AI 어시스턴트)

---

## 🏗️ Architecture

### DataPond + LiteLLM Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DataPond Frontend                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ SQL Lab  │  │Notebooks │  │ Pipelines│  │ Catalog  │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │             │              │              │          │
│       └─────────────┴──────────────┴──────────────┘          │
│                          │                                   │
└──────────────────────────┼───────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   DataPond Backend (FastAPI)                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AI Service Layer                        │   │
│  │  - SQL Generation                                    │   │
│  │  - Code Completion                                   │   │
│  │  - Data Insights                                     │   │
│  │  - Error Explanation                                 │   │
│  └──────────────────────┬──────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────┘
                          │
                          ▼ HTTP/REST
┌─────────────────────────────────────────────────────────────┐
│                    LiteLLM Proxy Server                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             Smart Router & Load Balancer              │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │  Cache     │  │ Fallback   │  │Rate Limit  │     │  │
│  │  │  (Redis)   │  │  Handler   │  │  Manager   │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                 │
│  ┌────────────────────────┴─────────────────────────────┐  │
│  │              Model Configuration                      │  │
│  │  - Primary: Claude Sonnet 4.6                        │  │
│  │  - Fallback 1: GPT-4                                 │  │
│  │  - Fallback 2: Gemini Pro                            │  │
│  │  - Budget: Llama 3 (self-hosted)                     │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────┬──────────────────┬──────────────────────┘
                   │                  │
          ┌────────┴────────┐  ┌─────┴──────┐
          ▼                 ▼  ▼            ▼
    ┌──────────┐      ┌──────────┐    ┌──────────┐
    │ Anthropic│      │  OpenAI  │    │  Google  │
    │   API    │      │   API    │    │   API    │
    └──────────┘      └──────────┘    └──────────┘
```

---

## 🚀 Implementation

### 1. LiteLLM Deployment (Kubernetes)

```yaml
# helm/datapond/templates/litellm-deployment.yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
  namespace: {{ .Values.namespace }}
data:
  config.yaml: |
    model_list:
      # Primary: Claude Sonnet (최고 품질)
      - model_name: claude-sonnet
        litellm_params:
          model: claude-sonnet-4-6
          api_key: os.environ/ANTHROPIC_API_KEY
          rpm: 500  # requests per minute
          tpm: 100000  # tokens per minute
        model_info:
          mode: chat
          supports_function_calling: true
          supports_vision: true
      
      # Fallback 1: GPT-4 (안정적)
      - model_name: gpt-4
        litellm_params:
          model: gpt-4-turbo
          api_key: os.environ/OPENAI_API_KEY
          rpm: 500
          tpm: 150000
      
      # Fallback 2: Gemini (Google)
      - model_name: gemini
        litellm_params:
          model: gemini-pro
          api_key: os.environ/GOOGLE_API_KEY
          rpm: 300
      
      # Budget: Llama 3 (자체 호스팅)
      - model_name: llama3
        litellm_params:
          model: ollama/llama3
          api_base: http://ollama:11434
          rpm: 1000
    
    # Router 설정
    router_settings:
      # 비용 기반 라우팅
      routing_strategy: "cost-based"
      
      # Fallback 순서
      fallbacks:
        - claude-sonnet
        - gpt-4
        - gemini
        - llama3
      
      # 캐싱 (Redis)
      cache:
        type: redis
        host: redis
        port: 6379
        ttl: 3600  # 1시간
      
      # 로깅
      success_callback: ["postgres"]
      failure_callback: ["postgres"]
    
    # 비용 추적
    litellm_settings:
      set_verbose: true
      json_logs: true
      
      # PostgreSQL에 로그 저장
      database_url: "postgresql://user:password@postgres:5432/litellm"
      
      # 예산 제한
      max_budget: 1000  # $1000/month
      budget_duration: "30d"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm
  namespace: {{ .Values.namespace }}
spec:
  replicas: 2
  selector:
    matchLabels:
      app: litellm
  template:
    metadata:
      labels:
        app: litellm
    spec:
      containers:
      - name: litellm
        image: ghcr.io/berriai/litellm:main-latest
        ports:
        - containerPort: 4000
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: litellm-secrets
              key: anthropic-api-key
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: litellm-secrets
              key: openai-api-key
        - name: GOOGLE_API_KEY
          valueFrom:
            secretKeyRef:
              name: litellm-secrets
              key: google-api-key
        - name: DATABASE_URL
          value: "postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/litellm"
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 4000
          initialDelaySeconds: 30
          periodSeconds: 10
      volumes:
      - name: config
        configMap:
          name: litellm-config

---
apiVersion: v1
kind: Service
metadata:
  name: litellm
  namespace: {{ .Values.namespace }}
spec:
  selector:
    app: litellm
  ports:
  - port: 4000
    targetPort: 4000
  type: ClusterIP

---
apiVersion: v1
kind: Secret
metadata:
  name: litellm-secrets
  namespace: {{ .Values.namespace }}
type: Opaque
stringData:
  anthropic-api-key: "sk-ant-xxxxx"
  openai-api-key: "sk-xxxxx"
  google-api-key: "AIzaSyxxxxx"
```

### 2. Ollama Deployment (Self-hosted Llama 3)

```yaml
# helm/datapond/templates/ollama-deployment.yaml
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ollama
  namespace: {{ .Values.namespace }}
spec:
  serviceName: ollama
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        volumeMounts:
        - name: models
          mountPath: /root/.ollama
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
            nvidia.com/gpu: "1"  # GPU 사용 (선택)
        env:
        - name: OLLAMA_MODELS
          value: "/root/.ollama/models"
  volumeClaimTemplates:
  - metadata:
      name: models
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi

---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: {{ .Values.namespace }}
spec:
  selector:
    app: ollama
  ports:
  - port: 11434
    targetPort: 11434
  type: ClusterIP

---
# Ollama 모델 다운로드 Job
apiVersion: batch/v1
kind: Job
metadata:
  name: ollama-pull-llama3
  namespace: {{ .Values.namespace }}
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: pull-model
        image: ollama/ollama:latest
        command: ["ollama", "pull", "llama3"]
        env:
        - name: OLLAMA_HOST
          value: "http://ollama:11434"
```

### 3. DataPond Backend Integration

```python
# backend/app/services/ai_service.py
from typing import Optional, List, Dict, Any
import httpx
from pydantic import BaseModel

class LiteLLMClient:
    """LiteLLM Proxy 클라이언트"""
    
    def __init__(self, base_url: str = "http://litellm:4000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "claude-sonnet",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False
    ) -> Dict[str, Any]:
        """채팅 완성 요청"""
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def embedding(self, text: str, model: str = "text-embedding-ada-002") -> List[float]:
        """텍스트 임베딩"""
        response = await self.client.post(
            f"{self.base_url}/embeddings",
            json={
                "model": model,
                "input": text
            }
        )
        return response.json()["data"][0]["embedding"]

class AIService:
    """AI 기능 서비스"""
    
    def __init__(self, litellm: LiteLLMClient):
        self.llm = litellm
    
    async def generate_sql_from_natural_language(
        self,
        prompt: str,
        schema: Dict[str, Any],
        dialect: str = "trino"
    ) -> str:
        """자연어 → SQL"""
        
        system_prompt = f"""
        You are an expert SQL engineer for {dialect} database.
        Given a database schema and a natural language request, generate a SQL query.
        
        Database schema:
        {self._format_schema(schema)}
        
        Rules:
        - Use standard {dialect} syntax
        - Include comments for complex logic
        - Optimize for performance
        - Handle NULL values appropriately
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate SQL query for: {prompt}"}
        ]
        
        response = await self.llm.chat_completion(
            messages=messages,
            model="claude-sonnet",
            temperature=0.2  # 낮은 temperature로 정확도 우선
        )
        
        sql = self._extract_sql_from_response(response)
        return sql
    
    async def explain_query_plan(self, query: str, execution_plan: str) -> str:
        """쿼리 플랜 설명"""
        
        messages = [
            {
                "role": "system",
                "content": "You are a database performance expert. Explain query execution plans in simple terms."
            },
            {
                "role": "user",
                "content": f"""
                SQL Query:
                {query}
                
                Execution Plan:
                {execution_plan}
                
                Please explain:
                1. What this query does
                2. How it executes (step by step)
                3. Performance bottlenecks (if any)
                4. Optimization suggestions
                """
            }
        ]
        
        response = await self.llm.chat_completion(messages=messages)
        return response["choices"][0]["message"]["content"]
    
    async def generate_data_insights(
        self,
        data_sample: Dict[str, Any],
        context: str = ""
    ) -> str:
        """데이터 인사이트 생성"""
        
        messages = [
            {
                "role": "system",
                "content": "You are a data analyst. Analyze data and provide actionable insights."
            },
            {
                "role": "user",
                "content": f"""
                Context: {context}
                
                Data sample:
                {data_sample}
                
                Provide:
                1. Key patterns and trends
                2. Anomalies or outliers
                3. Business implications
                4. Recommended actions
                """
            }
        ]
        
        response = await self.llm.chat_completion(messages=messages)
        return response["choices"][0]["message"]["content"]
    
    async def fix_code_error(
        self,
        code: str,
        error_message: str,
        language: str = "python"
    ) -> Dict[str, str]:
        """코드 에러 수정"""
        
        messages = [
            {
                "role": "system",
                "content": f"You are an expert {language} developer. Fix code errors and explain the solution."
            },
            {
                "role": "user",
                "content": f"""
                Code:
                ```{language}
                {code}
                ```
                
                Error:
                {error_message}
                
                Please provide:
                1. Fixed code
                2. Explanation of the issue
                3. Prevention tips
                """
            }
        ]
        
        response = await self.llm.chat_completion(messages=messages)
        content = response["choices"][0]["message"]["content"]
        
        return {
            "fixed_code": self._extract_code_from_response(content),
            "explanation": content
        }
    
    async def generate_documentation(
        self,
        code: str,
        language: str = "python"
    ) -> str:
        """코드 문서 자동 생성"""
        
        messages = [
            {
                "role": "system",
                "content": "You are a technical writer. Generate clear, concise documentation."
            },
            {
                "role": "user",
                "content": f"""
                Generate documentation for this {language} code:
                
                ```{language}
                {code}
                ```
                
                Include:
                1. Overview (what it does)
                2. Parameters
                3. Returns
                4. Examples
                5. Notes/Warnings (if applicable)
                """
            }
        ]
        
        response = await self.llm.chat_completion(messages=messages)
        return response["choices"][0]["message"]["content"]
    
    async def semantic_search(
        self,
        query: str,
        documents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """시맨틱 검색 (벡터 유사도)"""
        
        # 쿼리 임베딩
        query_embedding = await self.llm.embedding(query)
        
        # 문서 임베딩 (캐시 사용)
        doc_embeddings = []
        for doc in documents:
            embedding = await self._get_or_create_embedding(doc["content"])
            doc_embeddings.append(embedding)
        
        # 코사인 유사도 계산
        similarities = []
        for i, doc_emb in enumerate(doc_embeddings):
            similarity = self._cosine_similarity(query_embedding, doc_emb)
            similarities.append((similarity, documents[i]))
        
        # 유사도 순으로 정렬
        similarities.sort(key=lambda x: x[0], reverse=True)
        
        return [doc for _, doc in similarities[:10]]
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """코사인 유사도"""
        import numpy as np
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    
    async def _get_or_create_embedding(self, text: str) -> List[float]:
        """임베딩 캐시 (Redis)"""
        import hashlib
        
        # 텍스트 해시
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        
        # Redis에서 캐시 확인
        cached = await redis.get(f"embedding:{text_hash}")
        if cached:
            return json.loads(cached)
        
        # 새로 생성
        embedding = await self.llm.embedding(text)
        
        # 캐시 저장 (7일)
        await redis.setex(f"embedding:{text_hash}", 7 * 24 * 3600, json.dumps(embedding))
        
        return embedding
    
    def _format_schema(self, schema: Dict[str, Any]) -> str:
        """스키마 포맷팅"""
        result = []
        for table, columns in schema.items():
            result.append(f"Table: {table}")
            for col in columns:
                result.append(f"  - {col['name']} ({col['type']})")
        return "\n".join(result)
    
    def _extract_sql_from_response(self, response: Dict) -> str:
        """응답에서 SQL 추출"""
        content = response["choices"][0]["message"]["content"]
        # ```sql ... ``` 블록 추출
        import re
        match = re.search(r"```sql\n(.*?)\n```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.strip()
    
    def _extract_code_from_response(self, content: str) -> str:
        """응답에서 코드 추출"""
        import re
        match = re.search(r"```\w+\n(.*?)\n```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.strip()

# FastAPI 엔드포인트
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user

router = APIRouter(prefix="/api/ai", tags=["AI"])

litellm_client = LiteLLMClient()
ai_service = AIService(litellm_client)

@router.post("/sql/generate")
async def generate_sql(
    request: dict,
    user = Depends(get_current_user)
):
    """자연어 → SQL"""
    try:
        sql = await ai_service.generate_sql_from_natural_language(
            prompt=request["prompt"],
            schema=request.get("schema", {}),
            dialect=request.get("dialect", "trino")
        )
        return {"sql": sql}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/explain")
async def explain_query(
    request: dict,
    user = Depends(get_current_user)
):
    """쿼리 플랜 설명"""
    explanation = await ai_service.explain_query_plan(
        query=request["query"],
        execution_plan=request["execution_plan"]
    )
    return {"explanation": explanation}

@router.post("/insights")
async def generate_insights(
    request: dict,
    user = Depends(get_current_user)
):
    """데이터 인사이트"""
    insights = await ai_service.generate_data_insights(
        data_sample=request["data"],
        context=request.get("context", "")
    )
    return {"insights": insights}

@router.post("/code/fix")
async def fix_code(
    request: dict,
    user = Depends(get_current_user)
):
    """코드 에러 수정"""
    result = await ai_service.fix_code_error(
        code=request["code"],
        error_message=request["error"],
        language=request.get("language", "python")
    )
    return result

@router.post("/search/semantic")
async def semantic_search(
    request: dict,
    user = Depends(get_current_user)
):
    """시맨틱 검색"""
    results = await ai_service.semantic_search(
        query=request["query"],
        documents=request["documents"]
    )
    return {"results": results}
```

### 4. Frontend Integration

```typescript
// frontend/src/services/aiService.ts
class AIService {
  private baseUrl = '/api/ai';
  
  async generateSQL(prompt: string, schema?: any, dialect: string = 'trino') {
    const response = await fetch(`${this.baseUrl}/sql/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, schema, dialect })
    });
    return response.json();
  }
  
  async explainQuery(query: string, executionPlan: string) {
    const response = await fetch(`${this.baseUrl}/explain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, execution_plan: executionPlan })
    });
    return response.json();
  }
  
  async generateInsights(data: any, context?: string) {
    const response = await fetch(`${this.baseUrl}/insights`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data, context })
    });
    return response.json();
  }
  
  async fixCode(code: string, error: string, language: string = 'python') {
    const response = await fetch(`${this.baseUrl}/code/fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, error, language })
    });
    return response.json();
  }
}

export const aiService = new AIService();
```

```typescript
// frontend/src/components/AI/AIAssistantPanel.tsx
import React, { useState } from 'react';
import { aiService } from '../../services/aiService';

export const AIAssistantPanel: React.FC = () => {
  const [prompt, setPrompt] = useState('');
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  
  const handleGenerate = async () => {
    setLoading(true);
    try {
      const result = await aiService.generateSQL(prompt);
      setResponse(result.sql);
    } catch (error) {
      console.error('AI generation failed:', error);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="ai-assistant-panel">
      <div className="header">
        <h3>🤖 AI Assistant</h3>
        <span className="badge">Powered by LiteLLM</span>
      </div>
      
      <div className="input-section">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe what you want to query... e.g., 'Show me top 10 customers by revenue in 2025'"
          rows={4}
        />
        <button onClick={handleGenerate} disabled={loading}>
          {loading ? 'Generating...' : 'Generate SQL'}
        </button>
      </div>
      
      {response && (
        <div className="response-section">
          <h4>Generated SQL:</h4>
          <pre><code>{response}</code></pre>
          <div className="actions">
            <button onClick={() => navigator.clipboard.writeText(response)}>
              Copy
            </button>
            <button onClick={() => executeQuery(response)}>
              Run Query
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
```

```typescript
// frontend/src/pages/SQL/SQLWorkbench.tsx
import { AIAssistantPanel } from '../../components/AI/AIAssistantPanel';

export const SQLWorkbench: React.FC = () => {
  return (
    <Split direction="horizontal">
      {/* 왼쪽: SQL 에디터 */}
      <div className="sql-editor">
        <SQLEditor />
      </div>
      
      {/* 오른쪽: AI 어시스턴트 */}
      <div className="ai-panel">
        <AIAssistantPanel />
      </div>
    </Split>
  );
};
```

---

## 🎯 Use Cases

### Use Case 1: Natural Language to SQL

```typescript
// 사용자 입력
"Show me the top 10 users by total transaction amount in the last 30 days"

// AI 생성 SQL
SELECT 
  u.user_id,
  u.username,
  SUM(t.amount) as total_amount,
  COUNT(t.transaction_id) as transaction_count
FROM users u
JOIN transactions t ON u.user_id = t.user_id
WHERE t.created_at >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY u.user_id, u.username
ORDER BY total_amount DESC
LIMIT 10;
```

### Use Case 2: Query Optimization

```typescript
// 느린 쿼리 입력
SELECT * FROM large_table WHERE status = 'active';

// AI 제안
"This query can be optimized:
1. Add index on 'status' column
2. Avoid SELECT * - specify columns
3. Consider partitioning by date if temporal queries are common

Optimized query:
SELECT id, name, created_at 
FROM large_table 
WHERE status = 'active'
  AND date_partition >= CURRENT_DATE - INTERVAL '90' DAY;
"
```

### Use Case 3: Data Insights

```typescript
// 데이터 샘플 입력
{
  "revenue": [100, 120, 95, 150, 200, 180, 210],
  "date": ["2025-01-01", "2025-01-02", ...]
}

// AI 인사이트
"Key Findings:
1. Revenue is trending upward (+110% growth)
2. Spike on 2025-01-05 (200) - investigate campaign or event
3. Lowest on 2025-01-03 (95) - possible weekend effect
4. Average daily revenue: $150

Recommendations:
1. Focus on replicating success factors from high-revenue days
2. Investigate weekend performance drop
3. Consider seasonal patterns for forecasting
"
```

### Use Case 4: Code Error Fixing

```python
# 에러 있는 코드
def calculate_metrics(df):
    return df.groupby('user_id').agg({
        'revenue': 'sum',
        'count': 'count'  # ❌ 에러: 'count' 열이 없음
    })

# AI 수정
def calculate_metrics(df):
    return df.groupby('user_id').agg({
        'revenue': 'sum',
        'transaction_id': 'count'  # ✅ 수정
    }).rename(columns={'transaction_id': 'count'})

# 설명: "'count'는 열 이름이 아니라 집계 함수입니다. 
# 실제 열 이름(예: 'transaction_id')를 사용하고 
# .rename()으로 결과 열 이름을 변경하세요."
```

### Use Case 5: Semantic Search (Data Catalog)

```typescript
// 검색 쿼리
"customer purchase history"

// 시맨틱 검색 결과 (벡터 유사도 기반)
1. "customer_transactions" (similarity: 0.92)
   - Contains purchase records with customer_id, amount, timestamp
2. "order_history" (similarity: 0.87)
   - Historical order data with customer information
3. "user_activity_log" (similarity: 0.73)
   - User actions including purchases
```

---

## 💰 Cost Optimization Strategies

### 1. Intelligent Model Routing

```yaml
# LiteLLM 라우팅 전략
routing_rules:
  # 간단한 작업 → 저렴한 모델
  - condition: "tokens < 500 AND complexity = 'low'"
    model: llama3  # 자체 호스팅 (무료)
  
  # 중간 작업 → 중간 모델
  - condition: "tokens < 2000"
    model: gpt-4  # $0.03/1K tokens
  
  # 복잡한 작업 → 최고급 모델
  - condition: "complexity = 'high'"
    model: claude-sonnet  # $0.015/1K tokens
```

### 2. Aggressive Caching

```python
# 캐싱 전략
cache_rules:
  # SQL 생성: 1시간 캐시 (동일 스키마 + 프롬프트)
  sql_generation:
    ttl: 3600
    key: hash(schema + prompt)
  
  # 임베딩: 7일 캐시 (텍스트 변경 없으면 재사용)
  embeddings:
    ttl: 604800
    key: hash(text)
  
  # 데이터 인사이트: 6시간 캐시
  insights:
    ttl: 21600
    key: hash(data_sample)
```

**예상 비용 절감**:
- 캐시 히트율 70% 가정
- 월 LLM API 비용: $1000 → $300 (70% 절감)

### 3. Batch Processing

```python
# 배치 처리로 비용 절감
async def batch_generate_embeddings(texts: List[str]) -> List[List[float]]:
    """여러 텍스트를 한 번에 임베딩 (API 호출 횟수 감소)"""
    response = await litellm_client.embeddings(
        model="text-embedding-ada-002",
        input=texts  # 배치 입력
    )
    return [item.embedding for item in response.data]
```

---

## 📊 Monitoring & Analytics

### 1. LiteLLM Cost Dashboard

```sql
-- PostgreSQL에 저장된 LiteLLM 로그 분석
CREATE VIEW ai_cost_summary AS
SELECT 
  DATE(created_at) as date,
  model,
  COUNT(*) as request_count,
  SUM(prompt_tokens) as total_prompt_tokens,
  SUM(completion_tokens) as total_completion_tokens,
  -- 비용 계산 (모델별 단가)
  CASE model
    WHEN 'claude-sonnet' THEN (SUM(prompt_tokens) * 0.015 / 1000) + (SUM(completion_tokens) * 0.075 / 1000)
    WHEN 'gpt-4' THEN (SUM(prompt_tokens) * 0.03 / 1000) + (SUM(completion_tokens) * 0.06 / 1000)
    ELSE 0
  END as estimated_cost
FROM litellm_logs
GROUP BY DATE(created_at), model;
```

### 2. Frontend Dashboard

```typescript
// frontend/src/pages/Admin/AIAnalytics.tsx
export const AIAnalyticsDashboard: React.FC = () => {
  return (
    <div className="ai-analytics">
      <h1>AI Usage Analytics</h1>
      
      {/* 비용 요약 */}
      <div className="cost-summary">
        <Card title="This Month">
          <h2>${currentMonthCost}</h2>
          <p>Budget: ${budget} ({usagePercent}%)</p>
        </Card>
        <Card title="Total Requests">
          <h2>{totalRequests}</h2>
        </Card>
        <Card title="Cache Hit Rate">
          <h2>{cacheHitRate}%</h2>
        </Card>
      </div>
      
      {/* 모델별 사용량 */}
      <BarChart
        title="Requests by Model"
        data={modelUsage}
        xAxis="model"
        yAxis="requests"
      />
      
      {/* 시간별 비용 추이 */}
      <LineChart
        title="Daily Cost Trend"
        data={dailyCost}
        xAxis="date"
        yAxis="cost"
      />
      
      {/* Top Users */}
      <Table
        title="Top AI Users"
        columns={['User', 'Requests', 'Cost']}
        data={topUsers}
      />
    </div>
  );
};
```

---

## 🔒 Security & Governance

### 1. API Key Management

```yaml
# Kubernetes Secret (Sealed Secrets 사용)
apiVersion: v1
kind: Secret
metadata:
  name: litellm-secrets
type: Opaque
data:
  anthropic-api-key: <base64-encoded>
  openai-api-key: <base64-encoded>
  google-api-key: <base64-encoded>
```

### 2. Rate Limiting & Quotas

```python
# 사용자별 할당량
user_quotas = {
    "admin": 10000,      # requests/month
    "developer": 5000,
    "analyst": 2000,
    "viewer": 500
}

async def check_user_quota(user_id: str, role: str):
    """사용자 할당량 확인"""
    current_usage = await get_user_ai_usage(user_id, month=current_month())
    quota = user_quotas.get(role, 0)
    
    if current_usage >= quota:
        raise HTTPException(
            status_code=429,
            detail=f"AI quota exceeded. Used: {current_usage}/{quota}"
        )
```

### 3. Audit Logging

```python
# 모든 AI 요청 로깅
@router.post("/sql/generate")
async def generate_sql(request: dict, user = Depends(get_current_user)):
    # 감사 로그 기록
    await audit_log.record(
        user_id=user.id,
        action="ai.sql.generate",
        details={
            "prompt": request["prompt"],
            "model": "claude-sonnet",
            "timestamp": datetime.now()
        }
    )
    
    # AI 요청
    result = await ai_service.generate_sql_from_natural_language(...)
    
    return result
```

---

## 🚀 Deployment Guide

### Step 1: Install Helm Chart

```bash
# values.yaml 업데이트
cat >> helm/datapond/values.yaml <<EOF

litellm:
  enabled: true
  replicas: 2
  resources:
    requests:
      memory: 512Mi
      cpu: 250m
    limits:
      memory: 1Gi
      cpu: 500m
  secrets:
    anthropicApiKey: "sk-ant-xxxxx"
    openaiApiKey: "sk-xxxxx"
    googleApiKey: "AIzaSyxxxxx"

ollama:
  enabled: true
  gpu: false  # true if GPU available
  models:
    - llama3
  resources:
    requests:
      memory: 4Gi
      cpu: 2
EOF

# Helm 설치
helm upgrade --install datapond ./helm/datapond -f values.yaml
```

### Step 2: Verify Deployment

```bash
# LiteLLM 상태 확인
kubectl get pods -l app=litellm
kubectl logs -l app=litellm

# 헬스 체크
curl http://litellm:4000/health

# Ollama 상태 확인
kubectl get pods -l app=ollama
kubectl exec -it ollama-0 -- ollama list
```

### Step 3: Test AI Service

```bash
# SQL 생성 테스트
curl -X POST http://localhost:8000/api/ai/sql/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "prompt": "Show me top 10 customers by revenue",
    "schema": {
      "customers": [
        {"name": "customer_id", "type": "bigint"},
        {"name": "name", "type": "varchar"},
        {"name": "revenue", "type": "decimal"}
      ]
    }
  }'
```

---

## 📈 Expected Impact

### Developer Productivity
- ⏱️ SQL 작성 시간: **5분 → 30초** (90% 감소)
- 🐛 디버깅 시간: **30분 → 5분** (83% 감소)
- 📖 문서화 시간: **2시간 → 10분** (92% 감소)

### Cost Savings
- 💰 LLM API 비용: **$1000/월 → $300/월** (70% 절감)
- 📦 자체 호스팅: **간단한 작업은 Llama 3 사용** (추가 비용 없음)

### User Experience
- 🎯 기능 발견: **신규 사용자 온보딩 시간 50% 단축**
- 💡 데이터 인사이트: **분석가 생산성 40% 향상**
- 🔍 시맨틱 검색: **데이터 발견 시간 60% 단축**

---

## 🎓 Best Practices

### 1. Model Selection Strategy

```python
# 작업 복잡도에 따른 모델 선택
def select_model(task_type: str, complexity: str) -> str:
    if complexity == "low":
        return "llama3"  # 자체 호스팅
    elif task_type == "code_generation":
        return "claude-sonnet"  # 코드 품질 최고
    elif task_type == "analysis":
        return "gpt-4"  # 분석 능력 우수
    else:
        return "claude-sonnet"  # 기본값
```

### 2. Prompt Engineering

```python
# 좋은 프롬프트 예시
good_prompt = """
Context: E-commerce database with customers, orders, products tables
Task: Find customers who haven't purchased in the last 90 days
Requirements:
- Include customer name and email
- Show their last purchase date
- Order by last purchase date (oldest first)
- Limit to 100 results
"""

# 나쁜 프롬프트
bad_prompt = "find inactive customers"
```

### 3. Error Handling

```python
# Fallback 체인
try:
    result = await ai_service.generate_sql(prompt, model="claude-sonnet")
except Exception as e:
    logger.warning(f"Primary model failed: {e}")
    try:
        result = await ai_service.generate_sql(prompt, model="gpt-4")
    except Exception as e:
        logger.error(f"Fallback model failed: {e}")
        # 최후의 수단: 자체 호스팅 모델
        result = await ai_service.generate_sql(prompt, model="llama3")
```

---

## 🎯 Conclusion

LiteLLM을 DataPond에 통합하면:

1. **AI Assistant** - Databricks Assistant와 동등한 기능 제공
2. **비용 최적화** - 캐싱 + 스마트 라우팅으로 70% 비용 절감
3. **안정성** - Fallback + Load Balancing으로 99.9% 가용성
4. **유연성** - 여러 LLM 모델 지원 (Claude, GPT-4, Gemini, Llama)
5. **자체 호스팅** - Ollama로 간단한 작업은 무료 처리

**투자 대비 효과**: 2-3주 구현으로 개발자 생산성 40% 향상 + API 비용 70% 절감

**추천 구현 순서**:
1. Week 1: LiteLLM + Ollama Kubernetes 배포
2. Week 2: Backend AI Service 구현 (SQL 생성, 코드 수정)
3. Week 3: Frontend 통합 (AI Assistant Panel)
