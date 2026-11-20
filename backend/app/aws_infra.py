"""Read (and, for two settings, change) the AWS resources this deployment runs on.

The Infrastructure AWS and Cost tabs. Every resource is found from what the backend
already knows — the node from instance metadata, Aurora from the database host, the
bucket from the Glue warehouse, the schedules and alarms by the Terraform name
prefix — so there is nothing to configure beyond turning the tabs on.

Each AWS call is made on its own: one the node role may not make (the IAM in
terraform/iam.tf arrived later than the code) is reported by name in `missing`,
and the rest of the page still fills. Nothing here stops, resizes or deletes; the
only writes are Aurora's capacity range and the node's start/stop schedule.

boto3 is synchronous: the routes call these through asyncio.to_thread.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app import aws_cost
from app.cloud_info import cloud_info

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
CE_CACHE_SECONDS = 6 * 3600   # Cost Explorer charges $0.01 a request

_cache: Dict[str, Any] = {}
_lock = threading.Lock()


def enabled() -> bool:
    return str(os.getenv("AWS_INFRA_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")


def name_prefix() -> str:
    return (os.getenv("AWS_INFRA_NAME_PREFIX") or "datapond").strip()


def db_cluster_id() -> str:
    """`datapond-pg` from `datapond-pg.cluster-abc.us-east-1.rds.amazonaws.com`."""
    explicit = (os.getenv("AWS_INFRA_DB_CLUSTER") or "").strip()
    if explicit:
        return explicit
    host = (os.getenv("POSTGRES_HOST") or "").strip()
    if host.endswith(".rds.amazonaws.com"):
        return host.split(".", 1)[0]
    return f"{name_prefix()}-pg"


def bucket_name() -> Optional[str]:
    wh = (os.getenv("GLUE_WAREHOUSE") or os.getenv("ICEBERG_WAREHOUSE") or "").strip()
    if wh.startswith("s3://"):
        return wh[5:].split("/", 1)[0] or None
    return None


def schedule_names() -> Dict[str, str]:
    p = name_prefix()
    return {"start": f"{p}-node-start", "stop": f"{p}-node-stop"}


class _Calls:
    """Runs AWS calls one by one, remembering the ones IAM refused."""

    def __init__(self) -> None:
        self.missing: List[str] = []
        self.errors: List[str] = []
        self.payer_blocked = False  # a linked account whose payer has not shared Cost Explorer

    def __call__(self, action: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except Exception as e:  # botocore ClientError, NoCredentialsError, endpoint errors
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
            message = str(e)
            if "Payer account" in message and "linked account" in message:
                # Not IAM: the organization's management account keeps Cost Explorer to itself.
                self.payer_blocked = True
            elif code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
                          "UnauthorizedException", "AuthorizationError"):
                if action not in self.missing:
                    self.missing.append(action)
            else:
                logger.warning("aws_infra %s failed: %s", action, e)
                self.errors.append(f"{action}: {e}")
            return default


def _client(name: str, region: str):
    import boto3  # lazy: off-AWS deployments never import it
    return boto3.client(name, region_name=region)


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else None


def _metric(q_id: str, ns: str, name: str, dims: Dict[str, str], period: int, stat: str) -> dict:
    return {"Id": q_id, "ReturnData": True, "MetricStat": {
        "Metric": {"Namespace": ns, "MetricName": name,
                   "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
        "Period": period, "Stat": stat}}


def _series(results: List[dict], q_id: str) -> List[tuple]:
    for r in results:
        if r.get("Id") == q_id:
            pts = list(zip(r.get("Timestamps") or [], r.get("Values") or []))
            return sorted(((ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)), float(v)) for ts, v in pts)
    return []


def gather(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything the AWS and Cost tabs show, read from AWS now."""
    now = now or datetime.now(timezone.utc)
    meta = cloud_info() or {}
    region = meta.get("region") or os.getenv("S3_REGION") or "us-east-1"
    call = _Calls()
    month_start, _ = aws_cost.month_bounds(now)
    out: Dict[str, Any] = {"region": region, "read_at": now.isoformat()}

    sts = _client("sts", region)
    ident = call("sts:GetCallerIdentity", sts.get_caller_identity, {}) or {}
    acct = str(ident.get("Account") or "")
    out["account"] = f"••••{acct[-4:]}" if acct else None

    # The node
    ec2 = _client("ec2", region)
    iid = meta.get("instance_id")
    node: Dict[str, Any] = {"instance_id": iid}
    if iid:
        desc = call("ec2:DescribeInstances", lambda: ec2.describe_instances(InstanceIds=[iid]), {}) or {}
        inst = next((i for r in desc.get("Reservations", []) for i in r.get("Instances", [])), None)
        if inst:
            node.update(instance_type=inst.get("InstanceType"), state=inst.get("State", {}).get("Name"),
                        zone=inst.get("Placement", {}).get("AvailabilityZone"),
                        lifecycle="spot" if inst.get("InstanceLifecycle") == "spot" else "on-demand",
                        launched_at=_iso(inst.get("LaunchTime")), public_ip=inst.get("PublicIpAddress"))
            vols = [m["Ebs"]["VolumeId"] for m in inst.get("BlockDeviceMappings", []) if m.get("Ebs")]
            if vols:
                vd = call("ec2:DescribeVolumes", lambda: ec2.describe_volumes(VolumeIds=vols), {}) or {}
                v = (vd.get("Volumes") or [{}])[0]
                node.update(volume_gb=v.get("Size"), volume_type=v.get("VolumeType"))
        else:
            node.update(instance_type=meta.get("instance_type"), zone=meta.get("availability_zone"),
                        lifecycle="spot" if meta.get("lifecycle") == "spot" else "on-demand")
        if node.get("lifecycle") == "spot" and node.get("instance_type") and node.get("zone"):
            hist = call("ec2:DescribeSpotPriceHistory", lambda: ec2.describe_spot_price_history(
                InstanceTypes=[node["instance_type"]], ProductDescriptions=["Linux/UNIX"],
                AvailabilityZone=node["zone"], StartTime=max(month_start, now - timedelta(days=30)),
                MaxResults=200), {}) or {}
            prices = [float(p["SpotPrice"]) for p in hist.get("SpotPriceHistory", [])]
            if prices:
                node["hourly_price"] = round(sum(prices) / len(prices), 4)
                node["spot_price_now"] = prices[0]
        else:
            node["hourly_price"] = aws_cost.ON_DEMAND_HOURLY.get(node.get("instance_type") or "")
        node["on_demand_hourly"] = aws_cost.ON_DEMAND_HOURLY.get(node.get("instance_type") or "")
    out["node"] = node

    # Aurora
    rds = _client("rds", region)
    cid = db_cluster_id()
    cl = call("rds:DescribeDBClusters", lambda: rds.describe_db_clusters(DBClusterIdentifier=cid), {}) or {}
    c = (cl.get("DBClusters") or [None])[0]
    aurora: Dict[str, Any] = {"cluster": cid}
    if c:
        sc = c.get("ServerlessV2ScalingConfiguration") or {}
        aurora.update(status=c.get("Status"), engine_version=c.get("EngineVersion"),
                      min_acu=sc.get("MinCapacity"), max_acu=sc.get("MaxCapacity"),
                      auto_pause_seconds=sc.get("SecondsUntilAutoPause"))
    out["aurora"] = aurora

    # Metrics, one GetMetricData call
    cw = _client("cloudwatch", region)
    bucket = bucket_name()
    queries = [_metric("acu", "AWS/RDS", "ServerlessDatabaseCapacity", {"DBClusterIdentifier": cid}, 3600, "Average"),
               _metric("acupeak", "AWS/RDS", "ServerlessDatabaseCapacity", {"DBClusterIdentifier": cid}, 3600, "Maximum"),
               _metric("dbconn", "AWS/RDS", "DatabaseConnections", {"DBClusterIdentifier": cid}, 3600, "Maximum"),
               _metric("dbvol", "AWS/RDS", "VolumeBytesUsed", {"DBClusterIdentifier": cid}, 86400, "Average")]
    if iid:
        queries += [_metric("cpu", "AWS/EC2", "CPUUtilization", {"InstanceId": iid}, 3600, "Average"),
                    _metric("cpupeak", "AWS/EC2", "CPUUtilization", {"InstanceId": iid}, 3600, "Maximum")]
    if bucket:
        queries += [_metric("s3size", "AWS/S3", "BucketSizeBytes", {"BucketName": bucket, "StorageType": "StandardStorage"}, 86400, "Average"),
                    _metric("s3objs", "AWS/S3", "NumberOfObjects", {"BucketName": bucket, "StorageType": "AllStorageTypes"}, 86400, "Average")]
    md = call("cloudwatch:GetMetricData", lambda: cw.get_metric_data(
        MetricDataQueries=queries, StartTime=min(month_start, now - timedelta(days=7)), EndTime=now), {}) or {}
    res = md.get("MetricDataResults") or []
    day_ago = now - timedelta(hours=24)
    acu, acupeak = _series(res, "acu"), _series(res, "acupeak")
    cpu, cpupeak = _series(res, "cpu"), _series(res, "cpupeak")
    last = lambda s: s[-1][1] if s else None
    aurora.update(acu_now=last(acu), acu_peak_24h=max((v for ts, v in acupeak if ts >= day_ago), default=None),
                  connections_peak_24h=max((v for ts, v in _series(res, "dbconn") if ts >= day_ago), default=None),
                  storage_gb=round(last(_series(res, "dbvol")) / 1e9, 2) if _series(res, "dbvol") else None)
    cpu24 = [(ts, v) for ts, v in cpu if ts >= day_ago]
    node.update(cpu_24h=[{"at": ts.isoformat(), "pct": round(v, 1)} for ts, v in cpu24],
                cpu_avg_24h=round(sum(v for _, v in cpu24) / len(cpu24), 1) if cpu24 else None,
                cpu_peak_24h=round(max((v for ts, v in cpupeak if ts >= day_ago), default=0), 1) if cpupeak else None)
    s3size = last(_series(res, "s3size"))
    out["s3"] = {"bucket": bucket, "size_gb": round(s3size / 1e9, 3) if s3size is not None else None,
                 "objects": int(last(_series(res, "s3objs")) or 0) if _series(res, "s3objs") else None}

    # Alarms and dashboards
    p = name_prefix()
    al = call("cloudwatch:DescribeAlarms", lambda: cw.describe_alarms(AlarmNamePrefix=f"{p}-"), {}) or {}
    out["alarms"] = [{"name": a.get("AlarmName"), "state": a.get("StateValue"),
                      "watches": _watches(a), "changed_at": _iso(a.get("StateUpdatedTimestamp"))}
                     for a in al.get("MetricAlarms", [])]
    dash = call("cloudwatch:ListDashboards", lambda: cw.list_dashboards(DashboardNamePrefix=p), {}) or {}
    out["dashboards"] = [d.get("DashboardName") for d in dash.get("DashboardEntries", [])]
    mets = call("cloudwatch:ListMetrics", lambda: cw.list_metrics(Namespace=os.getenv("CLOUDWATCH_METRICS_NAMESPACE", "DataPond")), {}) or {}
    custom_metrics = len(mets.get("Metrics", []))

    # Schedule
    sch = _client("scheduler", region)
    sched: Dict[str, Any] = {"names": schedule_names()}
    for k, name in schedule_names().items():
        s = call("scheduler:GetSchedule", lambda name=name: sch.get_schedule(Name=name), None)
        if s:
            sched[k] = {"expression": s.get("ScheduleExpression"), "state": s.get("State"),
                        "tz": s.get("ScheduleExpressionTimezone"), "parsed": aws_cost.parse_cron(s.get("ScheduleExpression", ""))}
    out["schedule"] = _schedule_view(sched)

    # Counts that only feed the estimate
    sm = _client("secretsmanager", region)
    secrets = call("secretsmanager:ListSecrets", lambda: sm.list_secrets(
        Filters=[{"Key": "name", "Values": [p]}], MaxResults=100), {}) or {}
    n_secrets = len(secrets.get("SecretList", []))

    out["usage"] = {
        "aurora": {"acu_hourly": acu, "storage_gb": aurora.get("storage_gb"), "min_acu": aurora.get("min_acu")},
        "node": {"running_hours": [ts for ts, _ in cpu], "hourly_price": node.get("hourly_price"),
                 "lifecycle": node.get("lifecycle"), "instance_type": node.get("instance_type"),
                 "volume_gb": node.get("volume_gb")},
        "schedule": out["schedule"] if out["schedule"].get("editable") else None,
        "public_ips": 1 if node.get("public_ip") else 0,
        "hosted_zones": 1 if (os.getenv("APP_BASE_URL") or "").startswith("https://") else 0,
        "alarms": len(out["alarms"]), "dashboards": len(out["dashboards"]),
        "custom_metrics": custom_metrics, "secrets": n_secrets, "s3_gb": out["s3"].get("size_gb"),
    }
    out["missing"] = call.missing
    out["errors"] = call.errors[:5]
    return out


def _watches(a: dict) -> str:
    op = {"GreaterThanOrEqualToThreshold": "≥", "GreaterThanThreshold": ">",
          "LessThanThreshold": "<", "LessThanOrEqualToThreshold": "≤"}.get(a.get("ComparisonOperator", ""), "?")
    mins = int(a.get("Period") or 0) * int(a.get("EvaluationPeriods") or 1) // 60
    thr = a.get("Threshold")
    thr_s = f"{thr:g}" if isinstance(thr, (int, float)) else str(thr)
    return f"{a.get('MetricName')} {op} {thr_s} for {mins} min"


def _schedule_view(s: Dict[str, Any]) -> Dict[str, Any]:
    """One schedule the form can show: days, start, stop, timezone, on/off."""
    start, stop = s.get("start"), s.get("stop")
    if not (start and stop):
        return {"known": False, "names": s["names"]}
    ps, pe = start.get("parsed"), stop.get("parsed")
    view = {"known": True, "names": s["names"], "tz": start.get("tz") or "UTC",
            "enabled": start.get("state") == "ENABLED" and stop.get("state") == "ENABLED",
            "start_expression": start.get("expression"), "stop_expression": stop.get("expression")}
    if ps and pe and ps["days"] == pe["days"]:
        view.update(days=ps["days"], start=ps["time"], stop=pe["time"], editable=True)
    else:
        view.update(editable=False)  # a cron the form cannot build: shown as text
    return view


def snapshot(force: bool = False) -> Dict[str, Any]:
    """gather(), cached for five minutes."""
    with _lock:
        hit = _cache.get("aws")
        if hit and not force and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    data = gather()
    with _lock:
        _cache["aws"] = (time.time(), data)
    return data


def cached_snapshot() -> Optional[Dict[str, Any]]:
    """The last snapshot without asking AWS — for Overview, which must stay fast."""
    hit = _cache.get("aws")
    return hit[1] if hit else None


def forget() -> None:
    with _lock:
        _cache.pop("aws", None)


def actual_costs(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Cost Explorer, month to date, for resources tagged Project=<prefix>.

    `{"active": False}` while the tag is not activated (Cost Explorer then returns
    nothing for it) — the page stays on the estimate. `blocked: "payer"` when this is a
    linked account of an organization whose payer has not shared Cost Explorer with it.
    Cached six hours.
    """
    now = now or datetime.now(timezone.utc)
    with _lock:
        hit = _cache.get("ce")
        if hit and time.time() - hit[0] < CE_CACHE_SECONDS:
            return hit[1]
    start, end = aws_cost.month_bounds(now)
    call = _Calls()
    ce = _client("ce", "us-east-1")  # Cost Explorer has one endpoint
    tomorrow = (now + timedelta(days=1)).date()
    r = call("ce:GetCostAndUsage", lambda: ce.get_cost_and_usage(
        TimePeriod={"Start": start.date().isoformat(), "End": min(tomorrow, end.date()).isoformat()},
        Granularity="MONTHLY", Metrics=["UnblendedCost"],
        Filter={"Tags": {"Key": "Project", "Values": [name_prefix()]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]), None)
    out: Dict[str, Any] = {"active": False, "missing": call.missing}
    if call.payer_blocked:
        out["blocked"] = "payer"
    if r:
        groups = [g for t in r.get("ResultsByTime", []) for g in t.get("Groups", [])]
        services = [{"label": g["Keys"][0], "mtd": round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 2)}
                    for g in groups]
        total = round(sum(s["mtd"] for s in services), 2)
        if total > 0:
            out = {"active": True, "services": sorted(services, key=lambda s: -s["mtd"]), "total": total,
                   "read_at": now.isoformat(), "missing": []}
    with _lock:
        _cache["ce"] = (time.time(), out)
    return out


# ── the two safe changes ───────────────────────────────────────────────────

AURORA_MIN_CHOICES = (0, 0.5, 1, 2)
AURORA_MAX_CHOICES = (2, 4, 8, 16)


def set_aurora_capacity(min_acu: float, max_acu: float) -> Dict[str, Any]:
    if min_acu not in AURORA_MIN_CHOICES or max_acu not in AURORA_MAX_CHOICES or min_acu >= max_acu:
        raise ValueError("Pick a minimum of 0, 0.5, 1 or 2 ACU and a larger maximum of 2, 4, 8 or 16.")
    region = (cloud_info() or {}).get("region") or os.getenv("S3_REGION") or "us-east-1"
    cfg: Dict[str, Any] = {"MinCapacity": float(min_acu), "MaxCapacity": float(max_acu)}
    if min_acu == 0:
        cfg["SecondsUntilAutoPause"] = 300
    _client("rds", region).modify_db_cluster(
        DBClusterIdentifier=db_cluster_id(), ServerlessV2ScalingConfiguration=cfg, ApplyImmediately=True)
    forget()
    return {"min_acu": min_acu, "max_acu": max_acu}


def set_schedule(days: List[str], start: str, stop: str, enabled: bool = True) -> Dict[str, Any]:
    """Rewrite both schedules' cron (and on/off), keeping everything else they hold —
    UpdateSchedule replaces the whole schedule, so the target is copied from GetSchedule."""
    start_cron, stop_cron = aws_cost.build_cron(days, start), aws_cost.build_cron(days, stop)
    sh, sm = aws_cost.parse_time(start)
    eh, em = aws_cost.parse_time(stop)
    if (eh, em) <= (sh, sm):
        raise ValueError("Stop must be later in the day than start.")
    region = (cloud_info() or {}).get("region") or os.getenv("S3_REGION") or "us-east-1"
    sch = _client("scheduler", region)
    for key, expr in (("start", start_cron), ("stop", stop_cron)):
        cur = sch.get_schedule(Name=schedule_names()[key])
        args = {k: cur[k] for k in ("Name", "GroupName", "FlexibleTimeWindow", "Target",
                                    "ScheduleExpressionTimezone", "Description") if cur.get(k) is not None}
        sch.update_schedule(**args, ScheduleExpression=expr, State="ENABLED" if enabled else "DISABLED")
    forget()
    return {"days": days, "start": start, "stop": stop, "enabled": enabled,
            "start_expression": start_cron, "stop_expression": stop_cron}
