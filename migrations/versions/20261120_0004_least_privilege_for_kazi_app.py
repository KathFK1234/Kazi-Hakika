"""least privilege for kazi_app

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20 11:46:54.244195

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Stage history is append-only for the app; the budget is never deleted from.

    FK cascades (deleting an application or account) run with the table
    owner's rights, so they keep working without DELETE here.
    """
    op.execute("REVOKE UPDATE, DELETE ON stage_events FROM kazi_app")
    op.execute("REVOKE DELETE ON email_budget FROM kazi_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("GRANT UPDATE, DELETE ON stage_events TO kazi_app")
    op.execute("GRANT DELETE ON email_budget TO kazi_app")
