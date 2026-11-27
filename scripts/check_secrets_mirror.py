#!/usr/bin/env python3
"""Does the Secrets Manager vault still hold the cluster's critical secrets?

The vault (`<prefix>/critical-secrets`) is what a rebuilt node re-seeds `datapond-secrets`
from (docs/DISASTER_RECOVERY.md). On 2026-11-10 it was found four months stale: the
cluster's ENCRYPTION_KEY had been regenerated after the one-time mirror, the 11-06
rebuild restored the old key, and every stored source credential became unreadable
(memory: stale-secrets-mirror incident). Nothing compared the two.

This runs on the node after each deploy (.github/workflows/deploy-aws.yml) and compares
every key the vault holds with the same key in the cluster secret, by SHA-256: values
never leave the node and are never printed. Exit 1 when a key differs or is missing
from the cluster (the deploy goes red with what to do); exit 0 with a warning when the
vault cannot be read or a cluster key that should be mirrored is missing from it.
Refreshing the vault stays a deliberate operator step (put-secret-value with operator
credentials); the node's role can only read it.

Standard library only; needs kubectl and the aws CLI on PATH.
usage: check_secrets_mirror.py [--namespace datapond] [--secret datapond-secrets]
                               [--vault datapond/critical-secrets] [--region us-east-1]
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys

# Keys a rebuild cannot do without: losing ENCRYPTION_KEY makes every stored credential
# unreadable; the rest sign sessions, internal calls and Polaris tokens.
MUST_MIRROR = ("ENCRYPTION_KEY", "JWT_SECRET", "INTERNAL_API_KEY")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def compare(cluster: dict, vault: dict):
    """(differs, missing_in_cluster, not_mirrored, matching) key lists. Values are plain
    strings (the cluster's already base64-decoded)."""
    differs, missing, matching = [], [], []
    for k, v in sorted(vault.items()):
        if k not in cluster:
            missing.append(k)
        elif _digest(str(v)) != _digest(cluster[k]):
            differs.append(k)
        else:
            matching.append(k)
    not_mirrored = [k for k in MUST_MIRROR if k in cluster and k not in vault]
    return differs, missing, not_mirrored, matching


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--namespace", default="datapond")
    p.add_argument("--secret", default="datapond-secrets")
    p.add_argument("--vault", default="datapond/critical-secrets")
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    a = p.parse_args(argv)

    k = _run(["kubectl", "-n", a.namespace, "get", "secret", a.secret, "-o", "json"])
    if k.returncode != 0:
        print(f"::warning::cannot read secret {a.namespace}/{a.secret}: {k.stderr.strip()[:200]}")
        return 0
    cluster = {key: base64.b64decode(val).decode()
               for key, val in (json.loads(k.stdout).get("data") or {}).items()}

    s = _run(["aws", "secretsmanager", "get-secret-value", "--region", a.region,
              "--secret-id", a.vault, "--query", "SecretString", "--output", "text"])
    if s.returncode != 0:
        print(f"::warning::cannot read the vault {a.vault}; the mirror was not checked: "
              f"{s.stderr.strip().splitlines()[-1][:200] if s.stderr.strip() else 'no output'}")
        return 0
    try:
        vault = json.loads(s.stdout)
        assert isinstance(vault, dict)
    except Exception:
        print(f"::error::the vault {a.vault} does not hold a JSON object of keys")
        return 1

    differs, missing, not_mirrored, matching = compare(cluster, vault)
    print(f"vault {a.vault}: {len(matching)} key(s) match the cluster ({', '.join(matching) or 'none'})")
    fix = ("Refresh the vault from the cluster with operator credentials "
           "(docs/DISASTER_RECOVERY.md, 'seed the Secrets Manager vault'): a node rebuilt now "
           "would restore the vault's values")
    if not_mirrored:
        print(f"::warning::not in the vault: {', '.join(not_mirrored)}. {fix}.")
    if missing:
        print(f"::error::in the vault but not in the cluster secret: {', '.join(missing)}.")
    if differs:
        print(f"::error::the vault's value differs from the cluster for: {', '.join(differs)}. "
              f"{fix}, and with a different ENCRYPTION_KEY every stored source credential "
              "would be unreadable.")
    return 1 if differs or missing else 0


if __name__ == "__main__":
    sys.exit(main())
