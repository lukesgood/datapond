"""
Data Catalog API - Integration with Apache Polaris REST catalog
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import httpx
import os
from datetime import datetime

router = APIRouter()

# Configuration
# Note: Kubernetes injects POLARIS_PORT as "tcp://IP:PORT" so we use POLARIS_SERVICE_PORT_HTTP
POLARIS_HOST = os.getenv("POLARIS_HOST", "polaris.datapond.svc.cluster.local")
POLARIS_PORT = os.getenv("POLARIS_SERVICE_PORT_HTTP", "8181")
POLARIS_BASE_URL = f"http://{POLARIS_HOST}:{POLARIS_PORT}"
REQUEST_TIMEOUT = 10  # seconds


class TableInfo(BaseModel):
    name: str
    namespace: str
    table_type: str
    metadata_location: Optional[str] = None
    last_updated: Optional[str] = None


class TableColumn(BaseModel):
    name: str
    type: str
    nullable: bool = True
    comment: Optional[str] = None


class PartitionField(BaseModel):
    name: str
    transform: str
    source_id: int


class PartitionSpec(BaseModel):
    spec_id: int
    fields: List[PartitionField]


class TableStatistics(BaseModel):
    row_count: Optional[int] = None
    file_count: Optional[int] = None
    total_size: Optional[int] = None


class TableSchema(BaseModel):
    columns: List[TableColumn]


class TableDetails(BaseModel):
    name: str
    namespace: str
    table_type: str = "iceberg"
    location: str
    schema: TableSchema
    partition_specs: Optional[List[PartitionSpec]] = None
    statistics: Optional[TableStatistics] = None
    properties: Optional[Dict[str, Any]] = None
    last_updated: Optional[str] = None


class NamespaceInfo(BaseModel):
    name: str
    properties: Optional[Dict[str, str]] = None


class TablesResponse(BaseModel):
    tables: List[TableInfo]


class NamespacesResponse(BaseModel):
    namespaces: List[NamespaceInfo]


# Mock data for fallback when Polaris is unavailable
MOCK_NAMESPACES = [
    NamespaceInfo(
        name="default",
        properties={"description": "Default namespace", "owner": "datapond"}
    ),
    NamespaceInfo(
        name="analytics",
        properties={"description": "Analytics workspace", "owner": "data-team"}
    )
]

MOCK_TABLES = [
    TableInfo(
        name="sample_events",
        namespace="default",
        table_type="iceberg",
        metadata_location="s3://datapond/warehouse/default/sample_events/metadata/v1.metadata.json",
        last_updated="2026-04-29T10:30:00Z"
    ),
    TableInfo(
        name="user_profiles",
        namespace="default",
        table_type="iceberg",
        metadata_location="s3://datapond/warehouse/default/user_profiles/metadata/v2.metadata.json",
        last_updated="2026-04-29T09:15:00Z"
    ),
    TableInfo(
        name="sales_data",
        namespace="analytics",
        table_type="iceberg",
        metadata_location="s3://datapond/warehouse/analytics/sales_data/metadata/v3.metadata.json",
        last_updated="2026-04-28T14:20:00Z"
    )
]

MOCK_TABLE_DETAILS = {
    "sample_events": TableDetails(
        name="sample_events",
        namespace="default",
        table_type="iceberg",
        location="s3://datapond/warehouse/default/sample_events",
        schema=TableSchema(columns=[
            TableColumn(name="event_id", type="long", nullable=False, comment="Unique event identifier"),
            TableColumn(name="user_id", type="long", nullable=False, comment="User identifier"),
            TableColumn(name="event_type", type="string", nullable=False, comment="Type of event"),
            TableColumn(name="timestamp", type="timestamp", nullable=False, comment="Event timestamp"),
            TableColumn(name="properties", type="map<string,string>", nullable=True, comment="Event properties")
        ]),
        partition_specs=[
            PartitionSpec(
                spec_id=0,
                fields=[PartitionField(name="timestamp", transform="day", source_id=3)]
            )
        ],
        statistics=TableStatistics(
            row_count=1_250_000,
            file_count=156,
            total_size=2_500_000_000
        ),
        last_updated="2026-04-29T10:30:00Z"
    ),
    "user_profiles": TableDetails(
        name="user_profiles",
        namespace="default",
        table_type="iceberg",
        location="s3://datapond/warehouse/default/user_profiles",
        schema=TableSchema(columns=[
            TableColumn(name="user_id", type="long", nullable=False, comment="User identifier"),
            TableColumn(name="username", type="string", nullable=False, comment="Username"),
            TableColumn(name="email", type="string", nullable=True, comment="User email"),
            TableColumn(name="created_at", type="timestamp", nullable=False, comment="Account creation timestamp"),
            TableColumn(name="last_login", type="timestamp", nullable=True, comment="Last login timestamp")
        ]),
        partition_specs=[],
        statistics=TableStatistics(
            row_count=45_000,
            file_count=12,
            total_size=150_000_000
        ),
        last_updated="2026-04-29T09:15:00Z"
    ),
    "sales_data": TableDetails(
        name="sales_data",
        namespace="analytics",
        table_type="iceberg",
        location="s3://datapond/warehouse/analytics/sales_data",
        schema=TableSchema(columns=[
            TableColumn(name="sale_id", type="long", nullable=False, comment="Sale identifier"),
            TableColumn(name="product_id", type="long", nullable=False, comment="Product identifier"),
            TableColumn(name="amount", type="decimal(10,2)", nullable=False, comment="Sale amount"),
            TableColumn(name="sale_date", type="date", nullable=False, comment="Sale date"),
            TableColumn(name="region", type="string", nullable=False, comment="Sales region")
        ]),
        partition_specs=[
            PartitionSpec(
                spec_id=0,
                fields=[
                    PartitionField(name="sale_date", transform="month", source_id=3),
                    PartitionField(name="region", transform="identity", source_id=4)
                ]
            )
        ],
        statistics=TableStatistics(
            row_count=3_500_000,
            file_count=420,
            total_size=5_000_000_000
        ),
        last_updated="2026-04-28T14:20:00Z"
    )
}


async def check_polaris_health() -> bool:
    """Check if Polaris is available"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{POLARIS_BASE_URL}/v1/config")
            return response.status_code == 200
    except Exception:
        return False


@router.get("/catalog/namespaces", response_model=NamespacesResponse)
async def list_namespaces():
    """
    List all namespaces (schemas) from Polaris catalog

    Returns mock data if Polaris is unavailable
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{POLARIS_BASE_URL}/v1/namespaces")

            if response.status_code == 200:
                data = response.json()
                namespaces = []

                # Parse Polaris response format
                # Expected: {"namespaces": [["ns1"], ["ns2"], ...]}
                if "namespaces" in data:
                    for ns in data["namespaces"]:
                        # Handle both string and list format
                        ns_name = ns[0] if isinstance(ns, list) else ns
                        namespaces.append(NamespaceInfo(name=ns_name))

                return NamespacesResponse(namespaces=namespaces)
            else:
                # Return mock data on non-200 response
                return NamespacesResponse(namespaces=MOCK_NAMESPACES)

    except Exception as e:
        # Return mock data on any error
        return NamespacesResponse(namespaces=MOCK_NAMESPACES)


@router.get("/catalog/tables", response_model=TablesResponse)
async def list_tables():
    """
    List all tables across all namespaces from Polaris catalog

    Returns mock data if Polaris is unavailable
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # First get all namespaces
            ns_response = await client.get(f"{POLARIS_BASE_URL}/v1/namespaces")

            if ns_response.status_code != 200:
                return TablesResponse(tables=MOCK_TABLES)

            all_tables = []
            ns_data = ns_response.json()

            if "namespaces" in ns_data:
                for ns in ns_data["namespaces"]:
                    ns_name = ns[0] if isinstance(ns, list) else ns

                    # Get tables for this namespace
                    try:
                        tables_response = await client.get(
                            f"{POLARIS_BASE_URL}/v1/namespaces/{ns_name}/tables"
                        )

                        if tables_response.status_code == 200:
                            tables_data = tables_response.json()

                            # Parse table identifiers
                            # Expected: {"identifiers": [{"namespace": ["ns"], "name": "table"}, ...]}
                            if "identifiers" in tables_data:
                                for table_id in tables_data["identifiers"]:
                                    table_name = table_id.get("name", "")
                                    table_ns = ns_name

                                    all_tables.append(TableInfo(
                                        name=table_name,
                                        namespace=table_ns,
                                        table_type="iceberg"
                                    ))
                    except Exception:
                        # Skip this namespace on error
                        continue

            if all_tables:
                return TablesResponse(tables=all_tables)
            else:
                # Return mock data if no tables found
                return TablesResponse(tables=MOCK_TABLES)

    except Exception as e:
        # Return mock data on any error
        return TablesResponse(tables=MOCK_TABLES)


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str):
    """
    Get detailed metadata for a specific table from Polaris catalog

    Returns mock data if Polaris is unavailable or table not found
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(
                f"{POLARIS_BASE_URL}/v1/namespaces/{namespace}/tables/{table}"
            )

            if response.status_code == 200:
                data = response.json()

                # Parse Iceberg table metadata
                metadata = data.get("metadata", {})
                schema_data = metadata.get("schema", {})
                partition_specs_data = metadata.get("partition-specs", [])

                # Extract schema columns
                columns = []
                if "fields" in schema_data:
                    for field in schema_data["fields"]:
                        columns.append(TableColumn(
                            name=field.get("name", ""),
                            type=field.get("type", ""),
                            nullable=not field.get("required", True),
                            comment=field.get("doc")
                        ))

                # Extract partition specs
                partition_specs = []
                if partition_specs_data:
                    for spec in partition_specs_data:
                        fields = []
                        for field in spec.get("fields", []):
                            fields.append(PartitionField(
                                name=field.get("name", ""),
                                transform=field.get("transform", ""),
                                source_id=field.get("source-id", 0)
                            ))
                        partition_specs.append(PartitionSpec(
                            spec_id=spec.get("spec-id", 0),
                            fields=fields
                        ))

                # Extract statistics (may not be available in all cases)
                stats = None
                if "statistics" in metadata:
                    stats_data = metadata["statistics"]
                    stats = TableStatistics(
                        row_count=stats_data.get("row-count"),
                        file_count=stats_data.get("file-count"),
                        total_size=stats_data.get("total-size")
                    )

                return TableDetails(
                    name=table,
                    namespace=namespace,
                    table_type="iceberg",
                    location=data.get("metadata-location", ""),
                    schema=TableSchema(columns=columns),
                    partition_specs=partition_specs if partition_specs else None,
                    statistics=stats,
                    properties=metadata.get("properties"),
                    last_updated=metadata.get("last-updated-ms")
                )
            elif response.status_code == 404:
                # Try mock data
                mock_key = table
                if mock_key in MOCK_TABLE_DETAILS:
                    return MOCK_TABLE_DETAILS[mock_key]
                raise HTTPException(status_code=404, detail=f"Table {namespace}.{table} not found")
            else:
                # Try mock data
                mock_key = table
                if mock_key in MOCK_TABLE_DETAILS:
                    return MOCK_TABLE_DETAILS[mock_key]
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Polaris returned error: {response.text}"
                )

    except HTTPException:
        raise
    except Exception as e:
        # Try mock data on any error
        mock_key = table
        if mock_key in MOCK_TABLE_DETAILS:
            return MOCK_TABLE_DETAILS[mock_key]
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch table details: {str(e)}"
        )


@router.get("/catalog/health")
async def catalog_health():
    """Check Polaris catalog health status"""
    is_healthy = await check_polaris_health()

    return {
        "service": "polaris",
        "status": "healthy" if is_healthy else "unavailable",
        "url": POLARIS_BASE_URL,
        "message": "Connected to Polaris catalog" if is_healthy else "Using mock data (Polaris unavailable)"
    }
