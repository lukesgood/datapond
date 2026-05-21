// API Client for DataPond Backend

export interface QueryResult {
  columns: string[]
  rows: any[][]
  execution_time_ms: number
}

export interface QueryHistoryItem {
  id: string
  user_id: string
  query_text: string
  execution_time_ms: number
  rows_returned: number
  status: 'success' | 'error' | 'timeout'
  error_message?: string
  catalog?: string
  schema?: string
  created_at: string
}

export interface QueryHistoryListResponse {
  items: QueryHistoryItem[]
  total: number
  limit: number
  offset: number
}

export interface ChartConfig {
  chartType: 'table' | 'line' | 'bar' | 'area' | 'pie'
  xAxis?: string
  yAxis?: string
  colors?: string[]
  showGrid?: boolean
  showLegend?: boolean
}

export interface Dashboard {
  id: string
  user_id: string
  name: string
  description?: string
  query_text: string
  chart_config: ChartConfig
  is_public: boolean
  created_at: string
  updated_at: string
}

export interface CreateDashboardInput {
  name: string
  description?: string
  query_text: string
  chart_config: ChartConfig
  is_public?: boolean
}

export interface UpdateDashboardInput {
  name?: string
  description?: string
  is_public?: boolean
}

// Query API
export const queryApi = {
  execute: async (query: string, saveHistory: boolean = true): Promise<QueryResult> => {
    const response = await fetch('/api/queries/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, save_history: saveHistory }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.error || 'Query execution failed')
    }
    return response.json()
  },

  history: async (limit: number = 50, offset: number = 0): Promise<QueryHistoryListResponse> => {
    const response = await fetch(`/api/queries/history?limit=${limit}&offset=${offset}`)
    if (!response.ok) {
      throw new Error('Failed to fetch query history')
    }
    return response.json()
  },
}

// Dashboard API
export const dashboardApi = {
  list: async (): Promise<Dashboard[]> => {
    const response = await fetch('/api/dashboards')
    if (!response.ok) throw new Error('Failed to fetch dashboards')
    const data = await response.json()
    // API returns {items: [...], total: N} — extract the array
    return Array.isArray(data) ? data : (data.items ?? [])
  },

  get: async (id: string): Promise<Dashboard> => {
    const response = await fetch(`/api/dashboards/${id}`)
    if (!response.ok) throw new Error('Failed to fetch dashboard')
    return response.json()
  },

  create: async (data: CreateDashboardInput): Promise<Dashboard> => {
    const response = await fetch('/api/dashboards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'Failed to create dashboard')
    }
    return response.json()
  },

  update: async (id: string, data: UpdateDashboardInput): Promise<Dashboard> => {
    const response = await fetch(`/api/dashboards/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'Failed to update dashboard')
    }
    return response.json()
  },

  delete: async (id: string): Promise<void> => {
    const response = await fetch(`/api/dashboards/${id}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'Failed to delete dashboard')
    }
  },
}

export interface GovernanceStats {
  queries_today: number
  ai_sql_count: number
  pii_detections: number
  blocked_count: number
}

export interface AuditLogItem {
  id: string
  event_type: string
  user_email: string
  resource: string
  action: string
  result: string
  details: Record<string, any>
  created_at: string
}

export interface PiiTable {
  table: string
  pii_columns: { column: string; type: string }[]
}

export interface AiSafetyFlag {
  sql_preview: string
  risk: string
  user: string
  ts: string
}

export const governanceApi = {
  stats: async (): Promise<GovernanceStats> => {
    const r = await fetch('/api/governance/stats')
    if (!r.ok) throw new Error('Failed to fetch governance stats')
    return r.json()
  },
  auditLog: async (params?: { limit?: number; offset?: number; event_type?: string }): Promise<{ items: AuditLogItem[]; total: number }> => {
    const qs = new URLSearchParams()
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.offset) qs.set('offset', String(params.offset))
    if (params?.event_type) qs.set('event_type', params.event_type)
    const r = await fetch(`/api/governance/audit-log?${qs}`)
    if (!r.ok) throw new Error('Failed to fetch audit log')
    return r.json()
  },
  piiReport: async (): Promise<{ tables: PiiTable[] }> => {
    const r = await fetch('/api/governance/pii-report')
    if (!r.ok) throw new Error('Failed to fetch PII report')
    return r.json()
  },
  aiSafety: async (): Promise<{ risk_distribution: { low: number; medium: number; high: number }; recent_flags: AiSafetyFlag[] }> => {
    const r = await fetch('/api/governance/ai-safety')
    if (!r.ok) throw new Error('Failed to fetch AI safety data')
    return r.json()
  },
}
