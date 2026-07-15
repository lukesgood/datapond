"""AWS-native operational metrics — best-effort emission to Amazon CloudWatch.

Fits the AWS foundation profile: no extra pods (unlike an on-node Prometheus
stack), no memory pressure on the single node, and it feeds the cost-governance
story directly — Athena BytesScanned is dollars ($5/TB), embedding counts track
Bedrock spend, RagQuery tracks usage.

Design:
- Gated by CLOUDWATCH_METRICS_ENABLED (default OFF) so a fresh install never
  incurs CloudWatch cost or needs IAM until explicitly enabled.
- boto3 default credential chain (node instance profile / IRSA) — no static keys.
- Fire-and-forget on a tiny thread pool so PutMetricData never blocks the request
  path, and never raises to the caller (metrics must not break the product).
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

NAMESPACE = os.getenv("CLOUDWATCH_METRICS_NAMESPACE", "DataPond")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cw-metrics")
_client = None
_client_lock = threading.Lock()


def _enabled() -> bool:
    return os.getenv("CLOUDWATCH_METRICS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import boto3  # lazy — only when metrics are enabled
                _client = boto3.client("cloudwatch", region_name=os.getenv("S3_REGION", "us-east-1"))
    return _client


def _put(name: str, value: float, unit: str, dimensions) -> None:
    try:
        datum = {"MetricName": name, "Value": float(value), "Unit": unit}
        if dimensions:
            datum["Dimensions"] = [{"Name": k, "Value": str(v)} for k, v in dimensions.items()]
        _get_client().put_metric_data(Namespace=NAMESPACE, MetricData=[datum])
    except Exception as e:  # never propagate — metrics are best-effort
        logger.debug(f"[metrics] put_metric_data failed (non-fatal): {e}")


def emit(name: str, value: float = 1, unit: str = "Count", dimensions: dict = None) -> None:
    """Emit one CloudWatch metric. No-op unless CLOUDWATCH_METRICS_ENABLED.
    Non-blocking (submitted to a thread pool) and never raises."""
    if not _enabled():
        return
    try:
        _executor.submit(_put, name, value, unit, dimensions)
    except Exception:
        pass
