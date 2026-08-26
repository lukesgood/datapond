"""baseline — the schema as it already exists

Deliberately empty. This application builds its schema at startup: 44 tables across
four SQL files and thirty-odd CREATE/ALTER/INDEX statements in Python, each catching
its own exception. Recreating any of that here would fail against every database that
already has it, and on this product the deploy is --atomic, so it would roll back a
release for a reason nobody could see in the output.

What this revision does is mark where every existing database already is, so the next
schema change has somewhere to go. Converting the existing bootstraps happens one at a
time after this, each with its own revision and its own review.

Revision ID: 0001_baseline
Revises:
"""
from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op by design — see the module docstring."""


def downgrade() -> None:
    """There is nothing below a baseline."""
