"""the roles the API authorises from exist in the database

`roles` is created empty by 0001_baseline and was only ever filled by
`schema/auth.sql` / `schema/rls_migration.sql`, which the startup bootstrap used to
apply and no longer does. On any database built from migrations the table is empty, so
`GET /governance/rls/roles` returns nothing and an RLS policy created for a named role
binds to zero rows — inserted silently, enforcing nothing. Found by the branch review.

The list mirrors `app/permissions.py`'s KNOWN_ROLES, and
`tests/test_role_seed_migration.py` checks this file against that one rather than
against a copy, so adding a role there without a row here fails a test instead of
producing policies that bind to nobody.

Additive: seven rows, no shape change, `ON CONFLICT (name) DO NOTHING` so it is a
no-op on an installation that already carries them from the old bootstrap. No
`Contract-of` needed — `app/migration_rules.py`'s violations are DROP TABLE /
DROP COLUMN / RENAME / SET NOT NULL, and none appear here.

Revision ID: 0007_seed_roles
Revises: 0006_resource_ownership
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0007_seed_roles"
down_revision: Union[str, None] = "0006_resource_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    # Only the system rows this revision inserts, and only while nothing references
    # them: a role bound to a policy or held by a user is deleted by neither this nor
    # any other downgrade — losing those bindings silently is exactly the failure this
    # migration exists to fix, in reverse.
    op.get_bind().exec_driver_sql(
        """
        DELETE FROM public.roles r
         WHERE r.is_system
           AND r.name IN ('admin', 'data_engineer', 'ai_engineer', 'data_scientist',
                          'business_analyst', 'auditor', 'viewer')
           AND NOT EXISTS (SELECT 1 FROM public.rls_policy_roles p WHERE p.role_id = r.id)
           AND NOT EXISTS (SELECT 1 FROM public.masking_policy_roles m WHERE m.role_id = r.id)
           AND NOT EXISTS (SELECT 1 FROM public.user_roles u WHERE u.role_id = r.id)
           AND NOT EXISTS (SELECT 1 FROM public.role_permissions rp WHERE rp.role_id = r.id);
        """
    )
