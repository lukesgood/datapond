"""
Object Storage API - SeaweedFS S3 usage statistics
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from datetime import datetime, timezone

router = APIRouter()

S3_ENDPOINT   = f"http://{os.getenv('S3_ENDPOINT', 'seaweedfs-s3:8333')}"
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "datapond")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "datapond_dev")


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )


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


@router.get("/storage/overview", response_model=StorageOverview)
async def get_storage_overview():
    """Get SeaweedFS S3 storage overview — bucket list with sizes"""
    try:
        s3 = get_s3_client()
        response = s3.list_buckets()
        buckets_raw = response.get("Buckets", [])

        bucket_stats: List[BucketStat] = []
        total_objects = 0
        total_bytes = 0

        for b in buckets_raw:
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

            total_objects += obj_count
            total_bytes += size

            bucket_stats.append(BucketStat(
                name=name,
                created_at=created.isoformat() if created else None,
                object_count=obj_count,
                total_size_bytes=size,
                total_size_human=human_size(size),
            ))

        # Sort by size descending
        bucket_stats.sort(key=lambda x: x.total_size_bytes, reverse=True)

        return StorageOverview(
            endpoint=S3_ENDPOINT,
            bucket_count=len(bucket_stats),
            total_object_count=total_objects,
            total_size_bytes=total_bytes,
            total_size_human=human_size(total_bytes),
            buckets=bucket_stats,
        )

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
