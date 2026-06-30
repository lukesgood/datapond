"""
Object Storage API - SeaweedFS S3 usage statistics
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import time
import asyncio
import boto3
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import ClientError, EndpointConnectionError
from datetime import datetime, timezone

router = APIRouter()

S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "").strip()
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "").strip()
S3_REGION     = os.getenv("S3_REGION", "us-east-1").strip() or "us-east-1"


def _s3_config() -> dict:
    """boto3 s3 client kwargs.

    Native AWS S3 when S3_ENDPOINT is empty (default credential chain / IAM
    role). SeaweedFS / S3-compatible when S3_ENDPOINT is set; bare host:port
    is assumed http unless a scheme is given.
    """
    cfg: dict = {"region_name": S3_REGION}
    if not S3_ENDPOINT:
        return cfg
    endpoint = S3_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = "http://" + endpoint
    cfg["endpoint_url"] = endpoint
    if S3_ACCESS_KEY and S3_SECRET_KEY:
        cfg["aws_access_key_id"] = S3_ACCESS_KEY
        cfg["aws_secret_access_key"] = S3_SECRET_KEY
    return cfg


def get_s3_client():
    return boto3.client("s3", **_s3_config())


class BucketStat(BaseModel):
    name: str
    created_at: Optional[str] = None
    object_count: int = 0
    total_size_bytes: int = 0
    total_size_human: str = "0 B"


class StorageOverview(BaseModel):
    endpoint: str
    bucket_count: int
    total_object_count: int
    total_size_bytes: int
    total_size_human: str
    buckets: List[BucketStat]


class RecentObject(BaseModel):
    bucket: str
    key: str
    size_bytes: int
    size_human: str
    last_modified: str
    content_type: Optional[str] = None


def human_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


_OVERVIEW_TTL_SEC = int(os.getenv("STORAGE_OVERVIEW_TTL_SEC", "30"))
_overview_cache: dict = {"data": None, "ts": 0.0}


def _scan_bucket(s3, b) -> BucketStat:
    """단일 버킷 객체 집계 — 병렬 워커에서 실행."""
    name = b["Name"]
    created = b.get("CreationDate")
    obj_count = 0
    size = 0
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=name):
            for obj in page.get("Contents", []):
                obj_count += 1
                size += obj.get("Size", 0)
    except Exception:
        pass
    return BucketStat(
        name=name,
        created_at=created.isoformat() if created else None,
        object_count=obj_count,
        total_size_bytes=size,
        total_size_human=human_size(size),
    )


def _collect_overview() -> "StorageOverview":
    """전체 수집(블로킹) — 버킷별 객체 나열을 스레드풀로 병렬화."""
    s3 = get_s3_client()
    buckets_raw = s3.list_buckets().get("Buckets", [])
    # boto3 클라이언트는 스레드세이프 — 버킷 단위 병렬 스캔
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(buckets_raw)))) as ex:
        bucket_stats = list(ex.map(lambda b: _scan_bucket(s3, b), buckets_raw))
    total_objects = sum(b.object_count for b in bucket_stats)
    total_bytes = sum(b.total_size_bytes for b in bucket_stats)
    bucket_stats.sort(key=lambda x: x.total_size_bytes, reverse=True)
    return StorageOverview(
        endpoint=S3_ENDPOINT,
        bucket_count=len(bucket_stats),
        total_object_count=total_objects,
        total_size_bytes=total_bytes,
        total_size_human=human_size(total_bytes),
        buckets=bucket_stats,
    )


@router.get("/storage/overview", response_model=StorageOverview)
async def get_storage_overview():
    """SeaweedFS S3 개요 — 30s TTL 캐시 + to_thread(이벤트루프 비블로킹) + 버킷 병렬 스캔."""
    now = time.monotonic()
    if _overview_cache["data"] is not None and now - _overview_cache["ts"] < _OVERVIEW_TTL_SEC:
        return _overview_cache["data"]
    try:
        data = await asyncio.to_thread(_collect_overview)
        _overview_cache["data"], _overview_cache["ts"] = data, now
        return data


    except EndpointConnectionError:
        raise HTTPException(status_code=503, detail="SeaweedFS S3 endpoint unreachable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/storage/buckets/{bucket_name}/objects", response_model=List[RecentObject])
async def list_bucket_objects(bucket_name: str, limit: int = 50, prefix: str = ""):
    """List objects in a bucket, sorted by last modified (newest first)"""
    try:
        s3 = get_s3_client()
        objects: List[RecentObject] = []

        kwargs: Dict[str, Any] = {"Bucket": bucket_name, "MaxKeys": min(limit, 1000)}
        if prefix:
            kwargs["Prefix"] = prefix

        response = s3.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            objects.append(RecentObject(
                bucket=bucket_name,
                key=obj["Key"],
                size_bytes=obj["Size"],
                size_human=human_size(obj["Size"]),
                last_modified=obj["LastModified"].isoformat(),
            ))

        objects.sort(key=lambda x: x.last_modified, reverse=True)
        return objects[:limit]

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchBucket":
            raise HTTPException(status_code=404, detail=f"Bucket '{bucket_name}' not found")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage/buckets/{bucket_name}")
async def create_bucket(bucket_name: str):
    """Create a new S3 bucket"""
    try:
        s3 = get_s3_client()
        s3.create_bucket(Bucket=bucket_name)
        return {"message": f"Bucket '{bucket_name}' created", "bucket": bucket_name}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "BucketAlreadyExists":
            raise HTTPException(status_code=409, detail=f"Bucket '{bucket_name}' already exists")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/storage/buckets/{bucket_name}")
async def delete_bucket(bucket_name: str):
    """Delete an empty bucket"""
    try:
        s3 = get_s3_client()
        s3.delete_bucket(Bucket=bucket_name)
        return {"message": f"Bucket '{bucket_name}' deleted"}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchBucket":
            raise HTTPException(status_code=404, detail=f"Bucket '{bucket_name}' not found")
        if code == "BucketNotEmpty":
            raise HTTPException(status_code=409, detail=f"Bucket '{bucket_name}' is not empty")
        raise HTTPException(status_code=500, detail=str(e))
