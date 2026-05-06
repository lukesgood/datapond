import { Node, Edge, MarkerType } from "reactflow"

export interface PipelineTemplate {
  id: string
  name: string
  description: string
  icon: string
  category: "ETL" | "ELT" | "CDC" | "Analytics"
  nodes: Node[]
  edges: Edge[]
  pipelineDefaults: { schedule: string; description: string }
}

const EDGE_OPTS = {
  type: "smoothstep",
  animated: false,
  markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
  style: { strokeWidth: 1.5, stroke: "#94a3b8" },
}

export const PIPELINE_TEMPLATES: PipelineTemplate[] = [
  {
    id: "cdc-postgres",
    name: "CDC Replication",
    description: "PostgreSQL 변경 데이터 캡처 → Iceberg 실시간 동기화",
    icon: "🔄",
    category: "CDC",
    pipelineDefaults: { schedule: "*/5 * * * *", description: "CDC replication pipeline" },
    nodes: [
      {
        id: "bronze-1", type: "bronzeNode", position: { x: 50, y: 100 },
        data: { layer: "bronze", name: "cdc_source", connectionName: "", connectionType: "postgresql", table: "", mode: "incremental", watermarkColumn: "updated_at", primaryKey: "id", filterSql: "", batchSize: "10000" },
      },
      {
        id: "silver-1", type: "silverNode", position: { x: 350, y: 100 },
        data: { layer: "silver", name: "deduplicated", sql: "SELECT *\nFROM {{ source('cdc_source') }}\nQUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY updated_at DESC) = 1\n{{ incremental_filter('updated_at') }}", mode: "incremental", qualityCheck: "id IS NOT NULL", partitionBy: "DATE(updated_at)", primaryKey: "id", description: "중복 제거된 CDC 데이터" },
      },
    ],
    edges: [{ id: "e1", source: "bronze-1", target: "silver-1", ...EDGE_OPTS }],
  },
  {
    id: "etl-batch",
    name: "Batch ETL",
    description: "일별 배치 추출 → 정제 → 집계 (Medallion 아키텍처)",
    icon: "📦",
    category: "ETL",
    pipelineDefaults: { schedule: "@daily", description: "Daily batch ETL pipeline" },
    nodes: [
      {
        id: "bronze-1", type: "bronzeNode", position: { x: 50, y: 100 },
        data: { layer: "bronze", name: "raw_transactions", connectionName: "", connectionType: "postgresql", table: "", mode: "incremental", watermarkColumn: "created_at", primaryKey: "id", filterSql: "", batchSize: "" },
      },
      {
        id: "bronze-2", type: "bronzeNode", position: { x: 50, y: 280 },
        data: { layer: "bronze", name: "raw_accounts", connectionName: "", connectionType: "postgresql", table: "", mode: "full_refresh", watermarkColumn: "", primaryKey: "id", filterSql: "", batchSize: "" },
      },
      {
        id: "silver-1", type: "silverNode", position: { x: 350, y: 100 },
        data: { layer: "silver", name: "clean_transactions", sql: "SELECT id, account_id, amount, type, created_at\nFROM {{ source('raw_transactions') }}\nWHERE amount IS NOT NULL\n{{ incremental_filter('created_at') }}", mode: "incremental", qualityCheck: "amount IS NOT NULL", partitionBy: "DATE(created_at)", primaryKey: "id", description: "정제된 거래 데이터" },
      },
      {
        id: "silver-2", type: "silverNode", position: { x: 350, y: 280 },
        data: { layer: "silver", name: "clean_accounts", sql: "SELECT id, name, status\nFROM {{ source('raw_accounts') }}\nWHERE status = 'active'", mode: "full_refresh", qualityCheck: "status IS NOT NULL", partitionBy: "", primaryKey: "id", description: "활성 계정 목록" },
      },
      {
        id: "gold-1", type: "goldNode", position: { x: 650, y: 190 },
        data: { layer: "gold", name: "daily_summary", aggregation: "daily", sql: "SELECT\n  DATE(t.created_at) as date,\n  a.name as account_name,\n  SUM(t.amount) as total_amount,\n  COUNT(*) as tx_count\nFROM {{ ref('clean_transactions') }} t\nJOIN {{ ref('clean_accounts') }} a ON t.account_id = a.id\nGROUP BY 1, 2", partitionBy: "date", description: "일별 계정별 거래 요약" },
      },
    ],
    edges: [
      { id: "e1", source: "bronze-1", target: "silver-1", ...EDGE_OPTS },
      { id: "e2", source: "bronze-2", target: "silver-2", ...EDGE_OPTS },
      { id: "e3", source: "silver-1", target: "gold-1", ...EDGE_OPTS },
      { id: "e4", source: "silver-2", target: "gold-1", ...EDGE_OPTS },
    ],
  },
  {
    id: "elt-transform",
    name: "ELT Transform",
    description: "원본 로드 후 SQL 변환 (Transform in Warehouse)",
    icon: "⚡",
    category: "ELT",
    pipelineDefaults: { schedule: "@hourly", description: "ELT transform pipeline" },
    nodes: [
      {
        id: "bronze-1", type: "bronzeNode", position: { x: 50, y: 100 },
        data: { layer: "bronze", name: "raw_events", connectionName: "", connectionType: "kafka", table: "", mode: "incremental", watermarkColumn: "event_time", primaryKey: "", filterSql: "", batchSize: "50000" },
      },
      {
        id: "silver-1", type: "silverNode", position: { x: 350, y: 60 },
        data: { layer: "silver", name: "parsed_events", sql: "SELECT\n  event_id,\n  event_type,\n  JSON_EXTRACT(payload, '$.user_id') as user_id,\n  event_time\nFROM {{ source('raw_events') }}\n{{ incremental_filter('event_time') }}", mode: "incremental", qualityCheck: "event_id IS NOT NULL", partitionBy: "DATE(event_time)", primaryKey: "event_id", description: "파싱된 이벤트" },
      },
      {
        id: "silver-2", type: "silverNode", position: { x: 350, y: 240 },
        data: { layer: "silver", name: "user_sessions", sql: "SELECT\n  user_id,\n  MIN(event_time) as session_start,\n  MAX(event_time) as session_end,\n  COUNT(*) as event_count\nFROM {{ ref('parsed_events') }}\nGROUP BY user_id, DATE(event_time)", mode: "incremental", qualityCheck: "user_id IS NOT NULL", partitionBy: "DATE(session_start)", primaryKey: "", description: "사용자 세션 집계" },
      },
      {
        id: "gold-1", type: "goldNode", position: { x: 650, y: 150 },
        data: { layer: "gold", name: "user_engagement", aggregation: "daily", sql: "SELECT\n  DATE(session_start) as date,\n  COUNT(DISTINCT user_id) as dau,\n  AVG(event_count) as avg_events_per_session\nFROM {{ ref('user_sessions') }}\nGROUP BY 1", partitionBy: "date", description: "일별 사용자 참여 지표" },
      },
    ],
    edges: [
      { id: "e1", source: "bronze-1", target: "silver-1", ...EDGE_OPTS },
      { id: "e2", source: "silver-1", target: "silver-2", ...EDGE_OPTS },
      { id: "e3", source: "silver-2", target: "gold-1", ...EDGE_OPTS },
    ],
  },
  {
    id: "analytics-kpi",
    name: "KPI Dashboard",
    description: "다중 소스 → 비즈니스 KPI 대시보드 데이터 생성",
    icon: "📊",
    category: "Analytics",
    pipelineDefaults: { schedule: "@daily", description: "KPI analytics pipeline" },
    nodes: [
      {
        id: "bronze-1", type: "bronzeNode", position: { x: 50, y: 80 },
        data: { layer: "bronze", name: "raw_sales", connectionName: "", connectionType: "postgresql", table: "", mode: "incremental", watermarkColumn: "sale_date", primaryKey: "id", filterSql: "", batchSize: "" },
      },
      {
        id: "bronze-2", type: "bronzeNode", position: { x: 50, y: 240 },
        data: { layer: "bronze", name: "raw_costs", connectionName: "", connectionType: "postgresql", table: "", mode: "full_refresh", watermarkColumn: "", primaryKey: "id", filterSql: "", batchSize: "" },
      },
      {
        id: "silver-1", type: "silverNode", position: { x: 350, y: 160 },
        data: { layer: "silver", name: "revenue_costs", sql: "SELECT\n  s.sale_date as date,\n  SUM(s.amount) as revenue,\n  SUM(c.amount) as cost\nFROM {{ source('raw_sales') }} s\nLEFT JOIN {{ source('raw_costs') }} c ON s.sale_date = c.cost_date\nGROUP BY 1\n{{ incremental_filter('s.sale_date') }}", mode: "incremental", qualityCheck: "revenue >= 0", partitionBy: "date", primaryKey: "", description: "매출/비용 통합" },
      },
      {
        id: "gold-1", type: "goldNode", position: { x: 650, y: 100 },
        data: { layer: "gold", name: "kpi_daily", aggregation: "daily", sql: "SELECT\n  date,\n  revenue,\n  cost,\n  revenue - cost as profit,\n  ROUND((revenue - cost) / NULLIF(revenue, 0) * 100, 1) as margin_pct\nFROM {{ ref('revenue_costs') }}", partitionBy: "date", description: "일별 KPI (매출, 비용, 이익률)" },
      },
      {
        id: "gold-2", type: "goldNode", position: { x: 650, y: 280 },
        data: { layer: "gold", name: "kpi_monthly", aggregation: "monthly", sql: "SELECT\n  DATE_TRUNC('month', date) as month,\n  SUM(revenue) as revenue,\n  SUM(cost) as cost,\n  SUM(revenue - cost) as profit\nFROM {{ ref('kpi_daily') }}\nGROUP BY 1", partitionBy: "month", description: "월별 KPI 집계" },
      },
    ],
    edges: [
      { id: "e1", source: "bronze-1", target: "silver-1", ...EDGE_OPTS },
      { id: "e2", source: "bronze-2", target: "silver-1", ...EDGE_OPTS },
      { id: "e3", source: "silver-1", target: "gold-1", ...EDGE_OPTS },
      { id: "e4", source: "gold-1", target: "gold-2", ...EDGE_OPTS },
    ],
  },
]
