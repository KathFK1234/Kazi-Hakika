"""board roles, reports, domain checks, NEA agencies, users.is_admin (Phase 2)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27 09:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "kazi_app"
CURRENT_USER_ID = "NULLIF(current_setting('app.user_id', true), '')::uuid"
STATUSES = ("verified", "unverified", "flagged", "hidden", "archived")
REASONS = ("fee", "fake", "expired", "duplicate", "other")
# Every users column kazi_app may write. is_admin is deliberately missing:
# only the owner (python -m app.admins, on web start) can grant admin.
USER_WRITABLE = (
    "id",
    "email",
    "password_hash",
    "handle",
    "email_verified_at",
    "reminder_opt_in",
    "last_digest_on",
    "deleted_at",
    "created_at",
    "updated_at",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    cols = ", ".join(USER_WRITABLE)
    op.execute(f"REVOKE INSERT, UPDATE ON users FROM {APP_ROLE}")
    op.execute(f"GRANT INSERT ({cols}), UPDATE ({cols}) ON users TO {APP_ROLE}")

    # Who is acting, as SQL: an admin (a verified account the owner marked),
    # or the daily job (which declares itself per transaction, like app.user_id).
    op.execute(
        f"""
        CREATE FUNCTION kh_is_admin() RETURNS boolean
        LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
            SELECT EXISTS (
                SELECT 1 FROM users
                WHERE id = {CURRENT_USER_ID} AND is_admin AND email_verified_at IS NOT NULL
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION kh_is_job() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(current_setting('app.job', true), '') = 'daily'
        $$
        """
    )

    op.create_table(
        "board_roles",
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("job_url", sa.String(length=2048), nullable=False),
        sa.Column("company_domain", sa.String(length=253), nullable=False),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("remote", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("report_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_board_roles_status_valid")),
        sa.CheckConstraint("report_count >= 0", name=op.f("ck_board_roles_report_count_nonnegative")),
        sa.CheckConstraint(
            "jsonb_typeof(checks) = 'array'", name=op.f("ck_board_roles_checks_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name=op.f("fk_board_roles_posted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_roles")),
    )
    op.create_index(op.f("ix_board_roles_posted_by"), "board_roles", ["posted_by"])
    op.create_index("ix_board_roles_status_deadline", "board_roles", ["status", "deadline"])
    op.create_index("ix_board_roles_status_checked_at", "board_roles", ["status", "checked_at"])
    op.create_index("ix_board_roles_archived_at", "board_roles", ["archived_at"])
    # One live post per link: a second poster is pointed at the first.
    op.create_index(
        "uq_board_roles_live_job_url",
        "board_roles",
        ["job_url"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "reports",
        sa.Column("board_role_id", sa.Uuid(), nullable=False),
        sa.Column("reported_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(_in("reason", REASONS), name=op.f("ck_reports_reason_valid")),
        sa.ForeignKeyConstraint(
            ["board_role_id"],
            ["board_roles.id"],
            name=op.f("fk_reports_board_role_id_board_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"],
            ["users.id"],
            name=op.f("fk_reports_reported_by_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("board_role_id", "reported_by", name="uq_reports_role_reporter"),
    )
    op.create_index(op.f("ix_reports_reported_by"), "reports", ["reported_by"])

    op.create_table(
        "domain_checks",
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("registered_on", sa.Date(), nullable=True),
        sa.Column("resolves", sa.Boolean(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_domain_checks")),
    )
    op.create_index(op.f("ix_domain_checks_checked_at"), "domain_checks", ["checked_at"])

    op.create_table(
        "nea_agencies",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("licence_status", sa.String(length=40), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nea_agencies")),
        sa.UniqueConstraint("name_key", name=op.f("uq_nea_agencies_name_key")),
    )

    op.create_foreign_key(
        op.f("fk_applications_board_role_id_board_roles"),
        "applications",
        "board_roles",
        ["board_role_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON board_roles TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON reports TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON domain_checks, nea_agencies TO {APP_ROLE}")

    # Board roles: anyone reads what's on the board; posters see their own
    # (pending, flagged, hidden); only admins and the daily job change status.
    # Not FORCEd: the report-count trigger below runs as the owner.
    op.execute("ALTER TABLE board_roles ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY board_roles_read ON board_roles FOR SELECT USING (
            (approved_at IS NOT NULL AND status IN ('verified', 'unverified'))
            OR posted_by = {CURRENT_USER_ID} OR kh_is_admin() OR kh_is_job()
        )
        """
    )
    op.execute(
        f"CREATE POLICY board_roles_post ON board_roles FOR INSERT "
        f"WITH CHECK (posted_by = {CURRENT_USER_ID})"
    )
    op.execute(
        "CREATE POLICY board_roles_moderate ON board_roles FOR UPDATE "
        "USING (kh_is_admin() OR kh_is_job()) WITH CHECK (kh_is_admin() OR kh_is_job())"
    )
    op.execute(
        f"CREATE POLICY board_roles_remove ON board_roles FOR DELETE "
        f"USING (posted_by = {CURRENT_USER_ID} OR kh_is_admin() OR kh_is_job())"
    )

    # Reports: the reporter and admins only.
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reports FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY reports_read ON reports FOR SELECT "
        f"USING (reported_by = {CURRENT_USER_ID} OR kh_is_admin())"
    )
    op.execute(
        f"CREATE POLICY reports_file ON reports FOR INSERT "
        f"WITH CHECK (reported_by = {CURRENT_USER_ID})"
    )
    op.execute("CREATE POLICY reports_clear ON reports FOR DELETE USING (kh_is_admin())")

    # NEA licence list: everyone reads, only admins replace it.
    op.execute("ALTER TABLE nea_agencies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE nea_agencies FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY nea_read ON nea_agencies FOR SELECT USING (true)")
    op.execute(
        "CREATE POLICY nea_admin ON nea_agencies FOR ALL "
        "USING (kh_is_admin()) WITH CHECK (kh_is_admin())"
    )

    # Report count follows the reports table, and three reports take a role
    # off the board until an admin looks. Runs as the owner (reporters can't
    # update other people's posts themselves).
    op.execute(
        """
        CREATE FUNCTION kh_board_report_count() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE board_roles
                   SET report_count = report_count + 1,
                       status = CASE WHEN report_count + 1 >= 3
                                      AND status IN ('verified', 'unverified')
                                     THEN 'hidden' ELSE status END,
                       updated_at = now()
                 WHERE id = NEW.board_role_id;
                RETURN NEW;
            END IF;
            UPDATE board_roles
               SET report_count = greatest(report_count - 1, 0), updated_at = now()
             WHERE id = OLD.board_role_id;
            RETURN OLD;
        END
        $$
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION kh_board_report_count() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER reports_count AFTER INSERT OR DELETE ON reports "
        "FOR EACH ROW EXECUTE FUNCTION kh_board_report_count()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS reports_count ON reports")
    op.execute("DROP FUNCTION IF EXISTS kh_board_report_count()")
    op.drop_constraint(
        op.f("fk_applications_board_role_id_board_roles"), "applications", type_="foreignkey"
    )
    op.drop_table("nea_agencies")
    op.drop_index(op.f("ix_domain_checks_checked_at"), table_name="domain_checks")
    op.drop_table("domain_checks")
    op.drop_index(op.f("ix_reports_reported_by"), table_name="reports")
    op.drop_table("reports")
    op.drop_index("uq_board_roles_live_job_url", table_name="board_roles")
    op.drop_index("ix_board_roles_archived_at", table_name="board_roles")
    op.drop_index("ix_board_roles_status_checked_at", table_name="board_roles")
    op.drop_index("ix_board_roles_status_deadline", table_name="board_roles")
    op.drop_index(op.f("ix_board_roles_posted_by"), table_name="board_roles")
    op.drop_table("board_roles")
    op.execute("DROP FUNCTION IF EXISTS kh_is_job()")
    op.execute("DROP FUNCTION IF EXISTS kh_is_admin()")
    op.execute(f"REVOKE INSERT, UPDATE ON users FROM {APP_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE ON users TO {APP_ROLE}")
    op.drop_column("users", "is_admin")
