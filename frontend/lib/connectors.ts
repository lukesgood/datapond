// Types and data for connector marketplace

export interface ConnectorField {
  name: string
  label: string
  type: "text" | "number" | "password" | "boolean" | "select" | "textarea"
  required?: boolean
  default?: string | number | boolean
  options?: string[]
  placeholder?: string
  help?: string
}

export interface Connector {
  id: string
  name: string
  category: "database" | "storage" | "streaming" | "saas"
  icon: string
  description: string
  supported: boolean
  fields: ConnectorField[]
  features?: string[]
}

export interface Connection {
  id: string
  name: string
  connector_id: string
  connector_name: string
  status: "active" | "paused" | "error"
  last_sync?: string
  next_sync?: string
  config: Record<string, string | number | boolean | null>
  created_at: string
}

export interface SyncJob {
  id: string
  connection_id: string
  status: "running" | "success" | "failed"
  started_at: string
  completed_at?: string
  rows_synced?: number
  error_message?: string
}

// Mock connector data
export const availableConnectors: Connector[] = [
  {
    id: "postgresql",
    name: "PostgreSQL",
    category: "database",
    icon: "/connectors/postgresql.svg",
    description: "Connect to PostgreSQL databases for full or incremental batch sync",
    supported: true,
    features: ["Incremental Sync", "Schema Discovery"],
    fields: [
      { name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { name: "port", label: "Port", type: "number", default: 5432, required: true },
      { name: "database", label: "Database", type: "text", required: true, placeholder: "mydb" },
      { name: "username", label: "Username", type: "text", required: true },
      { name: "password", label: "Password", type: "password", required: true },
      { name: "ssl", label: "Use SSL", type: "boolean", default: false, help: "Enable SSL/TLS connection" }
    ]
  },
  {
    id: "mysql",
    name: "MySQL",
    category: "database",
    icon: "/connectors/mysql.svg",
    description: "Connect to MySQL and MariaDB for full or incremental batch sync",
    supported: true,
    features: ["Incremental Sync", "Schema Discovery"],
    fields: [
      { name: "host", label: "Host", type: "text", required: true, placeholder: "localhost" },
      { name: "port", label: "Port", type: "number", default: 3306, required: true },
      { name: "database", label: "Database", type: "text", required: true, placeholder: "mydb" },
      { name: "username", label: "Username", type: "text", required: true },
      { name: "password", label: "Password", type: "password", required: true }
    ]
  },
  {
    id: "s3",
    name: "Amazon S3",
    category: "storage",
    icon: "/connectors/s3.svg",
    description: "Connect to Amazon S3 or an S3-compatible endpoint",
    supported: true,
    features: ["File Discovery", "Incremental Sync", "Structured Files"],
    fields: [
      { name: "bucket", label: "Bucket Name", type: "text", required: true, placeholder: "my-bucket" },
      { name: "endpoint_url", label: "S3 Endpoint URL", type: "text", required: false, placeholder: "https://s3.example.com", help: "Leave blank for Amazon S3" },
      { name: "access_key", label: "Access Key ID", type: "text", required: false, help: "Optional when the runtime credential chain provides access" },
      { name: "secret_key", label: "Secret Access Key", type: "password", required: false },
      {
        name: "region",
        label: "Region",
        type: "select",
        options: ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"],
        default: "us-east-1",
        required: true
      },
      { name: "prefix", label: "Folder Prefix", type: "text", required: false, placeholder: "data/" }
    ]
  },
  {
    id: "kafka",
    name: "Apache Kafka",
    category: "streaming",
    icon: "/connectors/kafka.svg",
    description: "Stream data from Kafka topics (batch connector 미구현)",
    supported: false,
    features: ["Real-time Streaming", "Schema Registry", "Exactly-once Processing"],
    fields: [
      { name: "bootstrap_servers", label: "Bootstrap Servers", type: "text", required: true, placeholder: "localhost:9092" },
      { name: "topic", label: "Topic", type: "text", required: true, placeholder: "my-topic" },
      { name: "consumer_group", label: "Consumer Group", type: "text", required: true, placeholder: "datapond-group" },
      { name: "sasl_username", label: "SASL Username", type: "text", required: false },
      { name: "sasl_password", label: "SASL Password", type: "password", required: false }
    ]
  },
  {
    id: "mongodb",
    name: "MongoDB",
    category: "database",
    icon: "/connectors/mongodb.svg",
    description: "Connect to MongoDB databases",
    supported: false,
    features: ["Change Streams", "Schema Inference", "Incremental Sync"],
    fields: [
      { name: "connection_string", label: "Connection String", type: "text", required: true, placeholder: "mongodb://localhost:27017" },
      { name: "database", label: "Database", type: "text", required: true },
      { name: "auth_database", label: "Auth Database", type: "text", default: "admin" }
    ]
  },
  {
    id: "snowflake",
    name: "Snowflake",
    category: "database",
    icon: "/connectors/snowflake.svg",
    description: "Connect to Snowflake data warehouse",
    supported: false,
    features: ["Batch Sync", "Schema Discovery"],
    fields: [
      { name: "account", label: "Account", type: "text", required: true, placeholder: "xy12345.us-east-1" },
      { name: "warehouse", label: "Warehouse", type: "text", required: true },
      { name: "database", label: "Database", type: "text", required: true },
      { name: "schema", label: "Schema", type: "text", required: true },
      { name: "username", label: "Username", type: "text", required: true },
      { name: "password", label: "Password", type: "password", required: true }
    ]
  },
  {
    id: "redshift",
    name: "Amazon Redshift",
    category: "database",
    icon: "/connectors/redshift.svg",
    description: "Connect to AWS Redshift data warehouse",
    supported: false,
    features: ["Batch Sync", "Schema Discovery"],
    fields: [
      { name: "host", label: "Host", type: "text", required: true },
      { name: "port", label: "Port", type: "number", default: 5439 },
      { name: "database", label: "Database", type: "text", required: true },
      { name: "username", label: "Username", type: "text", required: true },
      { name: "password", label: "Password", type: "password", required: true }
    ]
  },
  {
    id: "bigquery",
    name: "Google BigQuery",
    category: "database",
    icon: "/connectors/bigquery.svg",
    description: "Connect to Google BigQuery",
    supported: false,
    features: ["Batch Sync", "Schema Discovery"],
    fields: [
      { name: "project_id", label: "Project ID", type: "text", required: true },
      { name: "dataset", label: "Dataset", type: "text", required: true },
      { name: "credentials_json", label: "Service Account JSON", type: "password", required: true, help: "Paste your service account JSON key" }
    ]
  },
  {
    id: "database_url",
    name: "Universal Database",
    category: "database",
    icon: "/connectors/database.svg",
    description: "Connect through a SQLAlchemy URL when the required dialect and driver are installed",
    supported: true,
    features: ["SQLAlchemy URL", "Batch Sync", "Driver-dependent"],
    fields: [
      {
        name: "database_url",
        label: "Connection URL",
        type: "text",
        required: true,
        placeholder: "postgresql://user:pass@host:5432/db",
        help: "SQLAlchemy 연결 문자열. 예: postgresql://, mysql+pymysql://, mssql+pyodbc://, oracle+cx_oracle://"
      },
      {
        name: "query",
        label: "Test Query (optional)",
        type: "text",
        placeholder: "SELECT 1",
        help: "연결 테스트에 사용할 SQL 쿼리"
      }
    ]
  },
  {
    id: "rest_api",
    name: "REST API",
    category: "saas",
    icon: "/connectors/rest.svg",
    description: "HTTP/HTTPS REST API에서 데이터 수집. JSON 응답, 인증 헤더, 페이지네이션 지원",
    supported: true,
    features: ["Bearer Token", "Basic Auth", "API Key", "JSON Path"],
    fields: [
      {
        name: "base_url",
        label: "Base URL",
        type: "text",
        required: true,
        placeholder: "https://api.example.com/v1"
      },
      {
        name: "auth_type",
        label: "Auth Type",
        type: "select",
        options: ["none", "bearer", "basic", "api_key"],
        default: "none"
      },
      {
        name: "auth_value",
        label: "Auth Value",
        type: "password",
        placeholder: "token / user:password / api_key_value"
      },
      {
        name: "auth_header",
        label: "Auth Header Name",
        type: "text",
        default: "Authorization",
        help: "api_key 방식일 때 사용할 헤더 이름"
      },
      {
        name: "data_path",
        label: "Data Path (JSONPath)",
        type: "text",
        placeholder: "data.items",
        help: "응답 JSON에서 배열 데이터가 있는 경로"
      }
    ]
  },
  {
    id: "custom",
    name: "Custom Python",
    category: "saas",
    icon: "/connectors/python.svg",
    description: "Python 코드로 어떤 소스든 직접 연결. fetch_data() 함수가 dict 리스트를 반환하면 됩니다",
    supported: true,
    features: ["완전 커스텀", "모든 Python 라이브러리", "사내 API"],
    fields: [
      {
        name: "code",
        label: "Python Code",
        type: "textarea",
        required: true,
        placeholder: "def fetch_data():\n    # 데이터를 가져와서 반환\n    return [{\"id\": 1, \"name\": \"example\"}]",
        help: "fetch_data() 함수를 정의하세요. dict 리스트를 반환해야 합니다."
      }
    ]
  }
]

export function getConnector(id: string): Connector | undefined {
  return availableConnectors.find(c => c.id === id)
}

export function getConnectorsByCategory(category: string): Connector[] {
  if (category === "all") return availableConnectors
  return availableConnectors.filter(c => c.category === category)
}
