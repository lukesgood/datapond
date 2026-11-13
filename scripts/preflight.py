#!/usr/bin/env python3
"""DataPond pre-check: find the failures we hit live before an install or a deploy.

  python3 scripts/preflight.py aws --region us-east-1 --instance-type t3.xlarge --az-id use1-az1
      Spot placement score of the instance type in the node's zone, the Spot vCPU quota,
      and whether Bedrock model access is granted. Uses the AWS CLI and your credentials.
  python3 scripts/preflight.py node
      On the node (kubectl): CPU request headroom — a rolling update needs room for one
      more pod of the largest Deployment beside the old one. scripts/deploy-node-helm.sh
      runs this before `helm upgrade`.

Each check prints ok / warn / fail; any fail exits 1. Standard library only.
"""
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass

SYMBOL = {"ok": "✓", "warn": "⚠", "fail": "✗"}


@dataclass
class Check:
    name: str
    level: str
    detail: str


def cpu_m(q) -> int:
    if not q:
        return 0
    q = str(q)
    return int(q[:-1]) if q.endswith("m") else int(float(q) * 1000)


def check_spot(scores, az_id: str, instance_type: str) -> Check:
    by = {s["AvailabilityZoneId"]: s["Score"] for s in scores}
    if az_id not in by:
        return Check("Spot capacity", "warn", f"no placement score for {instance_type} in {az_id}")
    best = max(by.items(), key=lambda kv: kv[1])
    if by[az_id] >= 3:
        return Check("Spot capacity", "ok", f"{instance_type} scores {by[az_id]} (of 10) in {az_id}")
    return Check("Spot capacity", "warn",
                 f"{instance_type} scores {by[az_id]} in {az_id} (best: {best[0]} = {best[1]}); scheduled starts may "
                 "fail for lack of capacity — consider another zone or type (t3.xlarge scored high everywhere on 2026-11-11)")


def check_quota(quota_vcpu: float, need_vcpu: int) -> Check:
    if quota_vcpu >= need_vcpu:
        return Check("Spot vCPU quota", "ok", f"{quota_vcpu:g} vCPU available, {need_vcpu} needed")
    return Check("Spot vCPU quota", "fail", f"quota {quota_vcpu:g} vCPU < {need_vcpu} needed — request an increase "
                 "(Service Quotas: 'All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests')")


def check_headroom(allocatable_m: int, requested_m: int, largest_rolling_m: int) -> Check:
    free = allocatable_m - requested_m
    if free >= largest_rolling_m:
        return Check("CPU request headroom", "ok", f"{free}m free, a rolling update needs {largest_rolling_m}m")
    return Check("CPU request headroom", "fail",
                 f"{free}m of {allocatable_m}m free but a rolling update needs {largest_rolling_m}m for the new pod — "
                 "lower a request (e.g. polaris.resources.requests.cpu) or use a bigger node")


def exit_code(checks) -> int:
    return 1 if any(c.level == "fail" for c in checks) else 0


def _run(cmd):
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout or "{}")


def aws_checks(region, instance_type, az_id):
    out = []
    try:
        r = _run(["aws", "ec2", "get-spot-placement-scores", "--region", region, "--instance-types", instance_type,
                  "--target-capacity", "1", "--single-availability-zone", "--region-names", region, "--output", "json"])
        out.append(check_spot(r.get("SpotPlacementScores", []), az_id, instance_type))
    except Exception as e:
        out.append(Check("Spot capacity", "warn", f"could not read placement scores: {e}"))
    try:
        r = _run(["aws", "ec2", "describe-instance-types", "--region", region, "--instance-types", instance_type, "--output", "json"])
        need = r["InstanceTypes"][0]["VCpuInfo"]["DefaultVCpus"]
        q = _run(["aws", "service-quotas", "get-service-quota", "--region", region, "--service-code", "ec2",
                  "--quota-code", "L-34B43A08", "--output", "json"])
        out.append(check_quota(float(q["Quota"]["Value"]), int(need)))
    except Exception as e:
        out.append(Check("Spot vCPU quota", "warn", f"could not read the quota: {e}"))
    try:
        r = _run(["aws", "bedrock", "list-foundation-models", "--region", region, "--by-output-modality", "TEXT", "--output", "json"])
        n = len(r.get("modelSummaries", []))
        out.append(Check("Bedrock", "ok" if n else "warn",
                         f"{n} text models listed in {region}" + ("" if n else " — enable model access, or the AI layer stays off")))
    except Exception as e:
        out.append(Check("Bedrock", "warn", f"could not list models ({e}); the lakehouse works without it, the AI layer does not"))
    return out


def node_checks(namespace="datapond"):
    nodes = _run(["kubectl", "get", "nodes", "-o", "json"])["items"]
    pods = _run(["kubectl", "get", "pods", "-A", "-o", "json"])["items"]
    deps = _run(["kubectl", "-n", namespace, "get", "deploy", "-o", "json"])["items"]
    alloc = sum(cpu_m(n["status"]["allocatable"].get("cpu")) for n in nodes)
    req = sum(cpu_m((c.get("resources") or {}).get("requests", {}).get("cpu"))
              for p in pods if p["status"].get("phase") in ("Running", "Pending")
              for c in p["spec"]["containers"])
    rolling = [sum(cpu_m((c.get("resources") or {}).get("requests", {}).get("cpu")) for c in d["spec"]["template"]["spec"]["containers"])
               for d in deps if (d["spec"].get("strategy") or {}).get("type") != "Recreate"]
    return [check_headroom(alloc, req, max(rolling or [0]))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("aws")
    a.add_argument("--region", default="us-east-1")
    a.add_argument("--instance-type", default="t3.xlarge")
    a.add_argument("--az-id", required=True, help="zone id, e.g. use1-az1 (aws ec2 describe-availability-zones)")
    n = sub.add_parser("node")
    n.add_argument("--namespace", default="datapond")
    args = ap.parse_args(argv)
    checks = aws_checks(args.region, args.instance_type, args.az_id) if args.mode == "aws" else node_checks(args.namespace)
    for c in checks:
        print(f"{SYMBOL[c.level]} {c.name}: {c.detail}")
    return exit_code(checks)


if __name__ == "__main__":
    sys.exit(main())
