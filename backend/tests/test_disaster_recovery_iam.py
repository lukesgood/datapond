"""The recovery runbook and the node's IAM policy must not drift apart.

docs/DISASTER_RECOVERY.md is a set of commands someone runs during an outage. Some
run on the application node, using its instance profile — and the node's role was
missing `secretsmanager:GetSecretValue`, so procedure B, the one that restores
ENCRYPTION_KEY, could not execute. Losing that key makes every connector and
provider credential stored in Aurora permanently undecryptable, which is the worst
outcome the runbook exists to prevent.

A runbook that cannot run is worse than no runbook: it is a plan someone is counting
on. This test reads the commands out of the document and checks the policy grants
them, so adding a step without the permission fails the build.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "DISASTER_RECOVERY.md"
POLICY = REPO / "terraform" / "iam.tf"

# `aws <service> <verb>` → the IAM action it needs.
ACTION_FOR = {
    ("secretsmanager", "get-secret-value"): "secretsmanager:GetSecretValue",
    ("secretsmanager", "put-secret-value"): "secretsmanager:PutSecretValue",
    ("s3api", "list-object-versions"): "s3:ListBucketVersions",
    ("ec2", "describe-security-groups"): "ec2:DescribeSecurityGroups",
    ("rds", "describe-db-cluster-snapshots"): "rds:DescribeDBClusterSnapshots",
    ("rds", "restore-db-cluster-from-snapshot"): "rds:RestoreDBClusterFromSnapshot",
    ("rds", "restore-db-cluster-to-point-in-time"): "rds:RestoreDBClusterToPointInTime",
    ("rds", "create-db-instance"): "rds:CreateDBInstance",
}

# Commands a human runs with their own credentials, not the node's. Each is either a
# deliberate operator act that should never be delegated to a machine, or part of
# rebuilding the infrastructure the node would be running on.
OPERATOR_CREDENTIALS = {
    ("secretsmanager", "put-secret-value"): "seeding the vault is a deliberate operator act",
    ("ec2", "describe-security-groups"): "infrastructure inspection during rebuild",
    ("rds", "describe-db-cluster-snapshots"): "run while the cluster is being rebuilt",
    ("rds", "restore-db-cluster-from-snapshot"): "recreates the database the node uses",
    ("rds", "restore-db-cluster-to-point-in-time"): "recreates the database the node uses",
    ("rds", "create-db-instance"): "recreates the database the node uses",
    ("s3api", "list-object-versions"): "object recovery is an operator decision",
}

_CALL = re.compile(r"\baws ([a-z0-9-]+) ([a-z0-9-]+)")


def _runbook_calls():
    return sorted(set(_CALL.findall(RUNBOOK.read_text())))


@pytest.fixture(scope="module")
def policy_text():
    return POLICY.read_text()


def test_every_runbook_command_is_a_known_action():
    """A new command with no mapping would otherwise be silently unchecked."""
    unmapped = [f"aws {s} {v}" for s, v in _runbook_calls() if (s, v) not in ACTION_FOR]
    assert not unmapped, (
        "docs/DISASTER_RECOVERY.md uses commands this test does not know about. Add "
        f"them to ACTION_FOR (and to OPERATOR_CREDENTIALS if a human runs them): {unmapped}"
    )


def test_node_run_commands_are_granted_to_the_node_role(policy_text):
    missing = [
        f"aws {s} {v} needs {ACTION_FOR[(s, v)]}"
        for s, v in _runbook_calls()
        if (s, v) not in OPERATOR_CREDENTIALS
        and ACTION_FOR[(s, v)] not in policy_text
    ]
    assert not missing, (
        "The runbook tells the node to run these, but terraform/iam.tf does not grant "
        "them. The procedure would fail mid-outage:\n  " + "\n  ".join(missing)
    )


def test_the_node_cannot_write_to_the_secrets_vault(policy_text):
    """Read-only by design: the node recovers secrets, it never overwrites them."""
    assert "secretsmanager:PutSecretValue" not in policy_text


def test_a_customer_managed_key_also_grants_decrypt(policy_text):
    """GetSecretValue alone cannot read a CMK-encrypted secret, and the failure would
    surface during recovery rather than at apply time."""
    assert "kms:Decrypt" in policy_text
    assert "var.db_kms_key_id == null" in policy_text, \
        "the grant must be conditional — an empty resource list is an invalid policy"
