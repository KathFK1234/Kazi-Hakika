"""Dira: check-ins, entries, application tags, users' check-in settings (Phase 3b)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-27 12:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "kazi_app"
CURRENT_USER_ID = "NULLIF(current_setting('app.user_id', true), '')::uuid"
NEW_USER_COLUMNS = (
    "checkin_interval_weeks",
    "next_checkin_on",
    "last_checkin_email_on",
    "weekly_target",
)
TAG = "[a-z0-9][a-z0-9-]{0,29}"


def _forced_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_owner ON {table}
            USING (user_id = {CURRENT_USER_ID})
            WITH CHECK (user_id = {CURRENT_USER_ID})
        """
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("checkin_interval_weeks", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("next_checkin_on", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("last_checkin_email_on", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("weekly_target", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_checkin_interval_valid"),
        "users",
        "checkin_interval_weeks IS NULL OR checkin_interval_weeks IN (4, 6, 8)",
    )
    op.create_check_constraint(
        op.f("ck_users_weekly_target_range"),
        "users",
        "weekly_target IS NULL OR weekly_target BETWEEN 1 AND 20",
    )
    # Column grants (0005): the app may write these new columns too.
    cols = ", ".join(NEW_USER_COLUMNS)
    op.execute(f"GRANT INSERT ({cols}), UPDATE ({cols}) ON users TO {APP_ROLE}")

    op.add_column(
        "applications",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=30)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_applications_tags_valid"),
        "applications",
        f"cardinality(tags) <= 5 AND array_to_string(tags, ',') ~ '^({TAG}(,{TAG})*)?$'",
    )

    op.create_table(
        "checkins",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("ideal_role", sa.String(length=300), nullable=False),
        sa.Column("excited", sa.Text(), nullable=True),
        sa.Column("energised", sa.Text(), nullable=True),
        sa.Column("drained", sa.Text(), nullable=True),
        sa.Column("changed", sa.Text(), nullable=True),
        sa.Column("confidence_planning", sa.SmallInteger(), nullable=True),
        sa.Column("confidence_control", sa.SmallInteger(), nullable=True),
        sa.Column("confidence_curiosity", sa.SmallInteger(), nullable=True),
        sa.Column("confidence_action", sa.SmallInteger(), nullable=True),
        sa.Column(
            "roles_shown",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(ideal_role) BETWEEN 1 AND 300", name=op.f("ck_checkins_ideal_role_length")
        ),
        sa.CheckConstraint(
            "char_length(excited) <= 2000 AND char_length(changed) <= 2000 "
            "AND char_length(energised) <= 1000 AND char_length(drained) <= 1000",
            name=op.f("ck_checkins_text_lengths"),
        ),
        sa.CheckConstraint(
            "coalesce(confidence_planning, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_control, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_curiosity, 1) BETWEEN 1 AND 5 "
            "AND coalesce(confidence_action, 1) BETWEEN 1 AND 5",
            name=op.f("ck_checkins_confidence_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(roles_shown) = 'array'", name=op.f("ck_checkins_roles_shown_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_checkins_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkins")),
        sa.UniqueConstraint("user_id", "on_date", name="uq_checkins_user_id_on_date"),
    )

    op.create_table(
        "entries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("text", sa.String(length=1000), nullable=False),
        sa.Column("happened_on", sa.Date(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("kind IN ('win', 'learning', 'goal')", name=op.f("ck_entries_kind_valid")),
        sa.CheckConstraint("char_length(text) >= 1", name=op.f("ck_entries_text_not_empty")),
        sa.CheckConstraint(
            "done_at IS NULL OR kind = 'goal'", name=op.f("ck_entries_done_only_for_goals")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_entries_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entries")),
    )
    # The entry keeps its owner when its application is deleted: only
    # application_id is cleared (Postgres 15+ column list).
    op.execute(
        "ALTER TABLE entries ADD CONSTRAINT fk_entries_application_owner "
        "FOREIGN KEY (application_id, user_id) REFERENCES applications (id, user_id) "
        "ON DELETE SET NULL (application_id)"
    )
    op.create_index("ix_entries_user_id_happened_on", "entries", ["user_id", "happened_on"])
    op.create_index(op.f("ix_entries_application_id"), "entries", ["application_id"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON checkins, entries TO {APP_ROLE}")
    _forced_rls("checkins")
    _forced_rls("entries")


def downgrade() -> None:
    for table in ("entries", "checkins"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
    op.drop_index(op.f("ix_entries_application_id"), table_name="entries")
    op.drop_index("ix_entries_user_id_happened_on", table_name="entries")
    op.drop_table("entries")
    op.drop_table("checkins")
    op.drop_constraint(op.f("ck_applications_tags_valid"), "applications", type_="check")
    op.drop_column("applications", "tags")
    cols = ", ".join(NEW_USER_COLUMNS)
    op.execute(f"REVOKE INSERT ({cols}), UPDATE ({cols}) ON users FROM {APP_ROLE}")
    op.drop_constraint(op.f("ck_users_weekly_target_range"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_checkin_interval_valid"), "users", type_="check")
    for col in reversed(NEW_USER_COLUMNS):
        op.drop_column("users", col)
