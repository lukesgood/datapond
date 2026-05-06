# DataPond Data Connectors Architecture

**Version:** 1.0.0  
**Date:** 2026-04-29  
**Purpose:** Design comprehensive data ingestion system matching Databricks Partner Connect

---

## 📋 Overview

DataPond Connector System enables easy data ingestion from 50+ sources through:
- Visual connector UI (no code required)
- Pre-built connectors with templates
- Automatic schema detection
- Incremental loading strategies
- Connection credential management
- Real-time and batch ingestion

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend UI Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Connector    │  │ Connection   │  │ Data Preview │      │
│  │ Marketplace  │  │ Wizard       │  │ & Validation │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                 Backend API Layer (FastAPI)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Connection   │  │ Schema       │  │ Job          │      │
│  │ Manager      │  │ Inspector    │  │ Scheduler    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│               Connector Engine Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Airbyte OSS  │  │ RisingWave   │  │ Spark        │      │
│  │ (SaaS, APIs) │  │ (Streaming)  │  │ (Batch)      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Data Sources                              │
│  Databases · Cloud Storage · Streaming · SaaS · Files       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  Target: Iceberg Tables                      │
│              (via Apache Polaris Catalog)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔌 Connector Types

### 1. Database Connectors (JDBC/ODBC)

**Supported Databases:**
- PostgreSQL
- MySQL/MariaDB
- Oracle Database
- Microsoft SQL Server
- MongoDB
- Cassandra
- Redis
- Snowflake
- BigQuery

**Features:**
- Full table sync
- Incremental sync (CDC)
- Custom SQL queries
- Schema auto-detection
- Type mapping

**Implementation:**
```python
# backend/app/connectors/database.py
from typing import Dict, List, Optional
from enum import Enum
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table

class DatabaseType(Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ORACLE = "oracle"
    SQLSERVER = "sqlserver"
    MONGODB = "mongodb"

class DatabaseConnector:
    """Generic database connector using SQLAlchemy"""
    
    def __init__(
        self,
        db_type: DatabaseType,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = False
    ):
        self.db_type = db_type
        self.connection_string = self._build_connection_string(
            db_type, host, port, database, username, password, ssl
        )
        self.engine = None
    
    def _build_connection_string(
        self, 
        db_type: DatabaseType, 
        host: str, 
        port: int, 
        database: str, 
        username: str, 
        password: str,
        ssl: bool
    ) -> str:
        """Build SQLAlchemy connection string"""
        ssl_params = "?sslmode=require" if ssl else ""
        
        if db_type == DatabaseType.POSTGRESQL:
            return f"postgresql://{username}:{password}@{host}:{port}/{database}{ssl_params}"
        elif db_type == DatabaseType.MYSQL:
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}{ssl_params}"
        elif db_type == DatabaseType.ORACLE:
            return f"oracle+cx_oracle://{username}:{password}@{host}:{port}/{database}"
        elif db_type == DatabaseType.SQLSERVER:
            return f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
        elif db_type == DatabaseType.MONGODB:
            return f"mongodb://{username}:{password}@{host}:{port}/{database}"
    
    def connect(self):
        """Establish database connection"""
        self.engine = create_engine(self.connection_string)
        # Test connection
        with self.engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
    
    def test_connection(self) -> bool:
        """Test if connection is valid"""
        try:
            self.connect()
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def get_tables(self) -> List[str]:
        """List all tables in database"""
        metadata = MetaData()
        metadata.reflect(bind=self.engine)
        return list(metadata.tables.keys())
    
    def get_table_schema(self, table_name: str) -> Dict:
        """Get table schema (columns, types)"""
        metadata = MetaData()
        table = Table(table_name, metadata, autoload_with=self.engine)
        
        schema = {
            "table_name": table_name,
            "columns": []
        }
        
        for column in table.columns:
            schema["columns"].append({
                "name": column.name,
                "type": str(column.type),
                "nullable": column.nullable,
                "primary_key": column.primary_key
            })
        
        return schema
    
    def read_table(
        self, 
        table_name: str, 
        limit: Optional[int] = None,
        incremental_column: Optional[str] = None,
        last_value: Optional[any] = None
    ) -> pd.DataFrame:
        """Read table data as DataFrame"""
        query = f"SELECT * FROM {table_name}"
        
        # Incremental loading
        if incremental_column and last_value:
            query += f" WHERE {incremental_column} > '{last_value}'"
        
        if limit:
            query += f" LIMIT {limit}"
        
        return pd.read_sql(query, self.engine)
    
    def sync_to_iceberg(
        self,
        source_table: str,
        target_table: str,
        mode: str = "overwrite",  # "overwrite", "append", "incremental"
        incremental_column: Optional[str] = None
    ):
        """Sync database table to Iceberg table"""
        from pyspark.sql import SparkSession
        
        spark = SparkSession.builder.getOrCreate()
        
        # Read from source
        if mode == "incremental":
            # Get last synced value
            last_value = self._get_last_synced_value(target_table, incremental_column)
            df = self.read_table(source_table, incremental_column=incremental_column, last_value=last_value)
        else:
            df = self.read_table(source_table)
        
        # Convert pandas to Spark DataFrame
        spark_df = spark.createDataFrame(df)
        
        # Write to Iceberg
        if mode == "overwrite":
            spark_df.writeTo(target_table).using("iceberg").createOrReplace()
        else:
            spark_df.writeTo(target_table).using("iceberg").append()
```

---

### 2. Cloud Storage Connectors

**Supported:**
- AWS S3
- Azure Blob Storage
- Google Cloud Storage
- MinIO
- SeaweedFS (internal)
- HDFS

**Features:**
- Auto file discovery
- Pattern matching (*.csv, *.parquet)
- Schema inference
- Compression support (gzip, snappy, zstd)
- Partitioned reads

**Implementation:**
```python
# backend/app/connectors/storage.py
import boto3
from typing import List, Dict
from enum import Enum

class StorageType(Enum):
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    GCS = "gcs"
    HDFS = "hdfs"

class CloudStorageConnector:
    """Cloud storage connector for file-based data"""
    
    def __init__(
        self,
        storage_type: StorageType,
        bucket: str,
        access_key: str = None,
        secret_key: str = None,
        region: str = "us-east-1"
    ):
        self.storage_type = storage_type
        self.bucket = bucket
        
        if storage_type == StorageType.S3:
            self.client = boto3.client(
                's3',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
    
    def list_files(self, prefix: str = "", pattern: str = "*") -> List[str]:
        """List files in bucket matching pattern"""
        import fnmatch
        
        files = []
        
        if self.storage_type == StorageType.S3:
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        if fnmatch.fnmatch(key, pattern):
                            files.append(key)
        
        return files
    
    def infer_schema(self, file_path: str, file_format: str = "csv") -> Dict:
        """Infer schema from file"""
        from pyspark.sql import SparkSession
        
        spark = SparkSession.builder.getOrCreate()
        
        # Read sample of file
        s3_path = f"s3a://{self.bucket}/{file_path}"
        
        if file_format == "csv":
            df = spark.read.option("inferSchema", "true").option("header", "true").csv(s3_path)
        elif file_format == "json":
            df = spark.read.option("inferSchema", "true").json(s3_path)
        elif file_format == "parquet":
            df = spark.read.parquet(s3_path)
        
        schema = {
            "columns": []
        }
        
        for field in df.schema.fields:
            schema["columns"].append({
                "name": field.name,
                "type": str(field.dataType),
                "nullable": field.nullable
            })
        
        return schema
    
    def create_auto_loader(
        self,
        source_prefix: str,
        target_table: str,
        file_format: str = "json",
        checkpoint_location: str = None
    ):
        """Create auto-loading streaming job"""
        from pyspark.sql import SparkSession
        
        spark = SparkSession.builder.getOrCreate()
        
        s3_path = f"s3a://{self.bucket}/{source_prefix}"
        checkpoint_path = checkpoint_location or f"/tmp/checkpoints/{target_table}"
        
        # Streaming read from S3
        df = (spark.readStream
            .format(file_format)
            .option("path", s3_path)
            .option("maxFilesPerTrigger", 1000)
            .load())
        
        # Write to Iceberg with checkpointing
        query = (df.writeStream
            .format("iceberg")
            .outputMode("append")
            .option("checkpointLocation", checkpoint_path)
            .option("path", f"s3a://iceberg/warehouse/{target_table}")
            .trigger(processingTime="1 minute")
            .start())
        
        return query
```

---

### 3. Streaming Connectors

**Supported:**
- Apache Kafka
- AWS Kinesis
- Azure Event Hubs
- Google Pub/Sub
- RabbitMQ
- MQTT

**Features:**
- Real-time ingestion
- Schema registry integration
- Automatic checkpointing
- Backpressure handling
- Dead letter queue

**Implementation (via RisingWave):**
```sql
-- RisingWave streaming connector
CREATE SOURCE kafka_events WITH (
  connector = 'kafka',
  topic = 'user_events',
  properties.bootstrap.server = 'kafka:9092',
  properties.group.id = 'datapond-consumer',
  scan.startup.mode = 'earliest'
) FORMAT PLAIN ENCODE JSON;

-- Stream to Iceberg
CREATE SINK events_iceberg AS
SELECT 
  event_id,
  user_id,
  event_type,
  properties,
  timestamp
FROM kafka_events
WITH (
  connector = 'iceberg',
  type = 'append-only',
  database.name = 'default',
  table.name = 'user_events',
  catalog.uri = 'http://polaris:8181',
  warehouse.path = 's3a://datapond/warehouse'
);
```

---

### 4. SaaS Connectors (via Airbyte)

**Strategy:** Integrate Airbyte OSS for 300+ pre-built connectors

**Supported:**
- Salesforce
- Google Analytics
- Facebook Ads
- Stripe
- Shopify
- Zendesk
- Jira
- Slack
- GitHub

**Architecture:**
```yaml
# Airbyte integration
services:
  airbyte-server:
    image: airbyte/server:latest
    environment:
      - DATABASE_URL=postgresql://postgres:5432/airbyte
      - CONFIG_ROOT=/data
    volumes:
      - airbyte_data:/data

  airbyte-worker:
    image: airbyte/worker:latest
    environment:
      - AIRBYTE_VERSION=0.50.0
```

**Backend Integration:**
```python
# backend/app/connectors/airbyte_client.py
import httpx
from typing import Dict, List

class AirbyteClient:
    """Client for Airbyte API"""
    
    def __init__(self, base_url: str = "http://airbyte-server:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def list_source_definitions(self) -> List[Dict]:
        """List available source connectors"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/source_definitions/list"
        )
        return response.json()["sourceDefinitions"]
    
    async def create_source(
        self,
        workspace_id: str,
        source_definition_id: str,
        connection_config: Dict,
        name: str
    ) -> Dict:
        """Create a new source connection"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/sources/create",
            json={
                "workspaceId": workspace_id,
                "sourceDefinitionId": source_definition_id,
                "connectionConfiguration": connection_config,
                "name": name
            }
        )
        return response.json()
    
    async def create_destination(
        self,
        workspace_id: str,
        destination_definition_id: str,  # Iceberg destination
        connection_config: Dict,
        name: str
    ) -> Dict:
        """Create Iceberg destination"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/destinations/create",
            json={
                "workspaceId": workspace_id,
                "destinationDefinitionId": destination_definition_id,
                "connectionConfiguration": connection_config,
                "name": name
            }
        )
        return response.json()
    
    async def create_connection(
        self,
        source_id: str,
        destination_id: str,
        sync_mode: str = "incremental",
        schedule: Dict = None
    ) -> Dict:
        """Create sync connection"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/connections/create",
            json={
                "sourceId": source_id,
                "destinationId": destination_id,
                "syncMode": sync_mode,
                "schedule": schedule or {"units": 24, "timeUnit": "hours"}
            }
        )
        return response.json()
    
    async def trigger_sync(self, connection_id: str) -> Dict:
        """Manually trigger sync"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/connections/sync",
            json={"connectionId": connection_id}
        )
        return response.json()
```

---

## 🎨 Frontend UI

### 1. Connector Marketplace

```typescript
// frontend/app/connectors/page.tsx
"use client"

import { useState, useEffect } from "react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Search, Database, Cloud, Activity, Zap } from "lucide-react"

interface Connector {
  id: string
  name: string
  category: "database" | "storage" | "streaming" | "saas"
  icon: string
  description: string
  supported: boolean
}

export default function ConnectorMarketplace() {
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/connectors/available")
      .then(res => res.json())
      .then(data => setConnectors(data.connectors))
  }, [])

  const categories = [
    { name: "Databases", value: "database", icon: Database },
    { name: "Cloud Storage", value: "storage", icon: Cloud },
    { name: "Streaming", value: "streaming", icon: Activity },
    { name: "SaaS Apps", value: "saas", icon: Zap }
  ]

  const filteredConnectors = connectors.filter(c => {
    const matchesSearch = c.name.toLowerCase().includes(search.toLowerCase())
    const matchesCategory = !category || c.category === category
    return matchesSearch && matchesCategory
  })

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Data Connectors</h2>
          <p className="text-muted-foreground">
            Connect to 50+ data sources
          </p>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center space-x-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search connectors..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      {/* Category Tabs */}
      <div className="flex space-x-2">
        <Badge
          variant={category === null ? "default" : "outline"}
          className="cursor-pointer px-4 py-2"
          onClick={() => setCategory(null)}
        >
          All
        </Badge>
        {categories.map(cat => {
          const Icon = cat.icon
          return (
            <Badge
              key={cat.value}
              variant={category === cat.value ? "default" : "outline"}
              className="cursor-pointer px-4 py-2 flex items-center gap-1"
              onClick={() => setCategory(cat.value)}
            >
              <Icon className="h-3 w-3" />
              {cat.name}
            </Badge>
          )
        })}
      </div>

      {/* Connector Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filteredConnectors.map(connector => (
          <Card key={connector.id} className="cursor-pointer hover:shadow-md transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">{connector.name}</CardTitle>
                <img src={connector.icon} alt={connector.name} className="h-8 w-8" />
              </div>
              <CardDescription className="text-xs">
                {connector.description}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {connector.supported ? (
                <Button 
                  onClick={() => window.location.href = `/connectors/${connector.id}/setup`}
                  className="w-full"
                >
                  Connect
                </Button>
              ) : (
                <Button variant="outline" disabled className="w-full">
                  Coming Soon
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
```

### 2. Connection Setup Wizard

```typescript
// frontend/app/connectors/[id]/setup/page.tsx
"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default function ConnectorSetup({ params }: { params: { id: string } }) {
  const [step, setStep] = useState(1)
  const [config, setConfig] = useState<any>({})
  const [testResult, setTestResult] = useState<"success" | "error" | null>(null)

  const testConnection = async () => {
    const response = await fetch("/api/connectors/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ connector_id: params.id, config })
    })
    
    const result = await response.json()
    setTestResult(result.success ? "success" : "error")
  }

  const createConnection = async () => {
    await fetch("/api/connectors/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ connector_id: params.id, config })
    })
    
    window.location.href = "/connectors/connections"
  }

  return (
    <div className="flex-1 p-8 pt-6">
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <CardTitle>Configure {params.id} Connection</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs value={`step${step}`} onValueChange={(v) => setStep(Number(v.replace("step", "")))}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="step1">Connection</TabsTrigger>
              <TabsTrigger value="step2">Schema</TabsTrigger>
              <TabsTrigger value="step3">Schedule</TabsTrigger>
            </TabsList>

            {/* Step 1: Connection Details */}
            <TabsContent value="step1" className="space-y-4">
              <div>
                <Label htmlFor="name">Connection Name</Label>
                <Input
                  id="name"
                  placeholder="My PostgreSQL Database"
                  value={config.name || ""}
                  onChange={(e) => setConfig({ ...config, name: e.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="host">Host</Label>
                <Input
                  id="host"
                  placeholder="localhost"
                  value={config.host || ""}
                  onChange={(e) => setConfig({ ...config, host: e.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="port">Port</Label>
                <Input
                  id="port"
                  type="number"
                  placeholder="5432"
                  value={config.port || ""}
                  onChange={(e) => setConfig({ ...config, port: e.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="database">Database</Label>
                <Input
                  id="database"
                  placeholder="mydb"
                  value={config.database || ""}
                  onChange={(e) => setConfig({ ...config, database: e.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={config.username || ""}
                  onChange={(e) => setConfig({ ...config, username: e.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={config.password || ""}
                  onChange={(e) => setConfig({ ...config, password: e.target.value })}
                />
              </div>

              <div className="flex space-x-2">
                <Button onClick={testConnection}>
                  Test Connection
                </Button>
                {testResult === "success" && (
                  <span className="text-green-600">✓ Connected</span>
                )}
                {testResult === "error" && (
                  <span className="text-red-600">✗ Failed</span>
                )}
              </div>

              <Button onClick={() => setStep(2)} disabled={testResult !== "success"}>
                Next: Select Tables
              </Button>
            </TabsContent>

            {/* Step 2: Schema Selection */}
            <TabsContent value="step2" className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Select tables to sync
              </p>
              {/* Table selection UI */}
              <Button onClick={() => setStep(3)}>
                Next: Configure Schedule
              </Button>
            </TabsContent>

            {/* Step 3: Schedule */}
            <TabsContent value="step3" className="space-y-4">
              <div>
                <Label htmlFor="sync-mode">Sync Mode</Label>
                <Select
                  value={config.syncMode || "incremental"}
                  onValueChange={(v) => setConfig({ ...config, syncMode: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="full">Full Refresh</SelectItem>
                    <SelectItem value="incremental">Incremental</SelectItem>
                    <SelectItem value="cdc">Change Data Capture (CDC)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="schedule">Schedule</Label>
                <Select
                  value={config.schedule || "daily"}
                  onValueChange={(v) => setConfig({ ...config, schedule: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Manual</SelectItem>
                    <SelectItem value="hourly">Every Hour</SelectItem>
                    <SelectItem value="daily">Every Day</SelectItem>
                    <SelectItem value="weekly">Every Week</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button onClick={createConnection} className="w-full">
                Create Connection
              </Button>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
```

---

## 📊 Implementation Priority

### Phase 1 (2 weeks): Foundation
- ✅ Database connectors (PostgreSQL, MySQL, SQL Server)
- ✅ Cloud storage connectors (S3, Azure Blob, GCS)
- ✅ Connector marketplace UI
- ✅ Connection wizard UI

### Phase 2 (2 weeks): Streaming & Automation
- ✅ Streaming connectors (Kafka via RisingWave)
- ✅ Auto Loader for cloud storage
- ✅ Incremental loading with CDC
- ✅ Connection monitoring dashboard

### Phase 3 (3 weeks): SaaS & Advanced
- ✅ Airbyte integration (300+ connectors)
- ✅ Schema registry integration
- ✅ Data quality checks on ingestion
- ✅ Connection templates library

---

## 🎯 Success Metrics

- **50+ connectors** supported (database + storage + streaming + SaaS)
- **Zero-code setup** for 80% of use cases
- **<5 minutes** from connection to first data
- **Automatic schema detection** (90% accuracy)
- **Incremental loading** for all supported databases

---

## 🔐 Security & Credentials

**Credential Storage:**
```python
# backend/app/connectors/vault.py
from cryptography.fernet import Fernet
import os

class CredentialVault:
    """Secure credential storage"""
    
    def __init__(self):
        self.key = os.getenv("ENCRYPTION_KEY")
        self.cipher = Fernet(self.key.encode())
    
    def encrypt_credentials(self, credentials: dict) -> str:
        """Encrypt connection credentials"""
        import json
        plaintext = json.dumps(credentials)
        encrypted = self.cipher.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt_credentials(self, encrypted: str) -> dict:
        """Decrypt connection credentials"""
        import json
        decrypted = self.cipher.decrypt(encrypted.encode())
        return json.loads(decrypted.decode())
    
    def store_connection(self, connection_id: str, credentials: dict):
        """Store encrypted credentials in database"""
        encrypted = self.encrypt_credentials(credentials)
        
        # Store in PostgreSQL
        db.execute("""
            INSERT INTO connector_credentials (connection_id, credentials)
            VALUES (?, ?)
        """, (connection_id, encrypted))
```

---

This connector system will match Databricks Partner Connect and enable easy data ingestion from any source!
