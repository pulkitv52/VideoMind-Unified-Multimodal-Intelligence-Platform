"""Distinguish a busy solo document worker from a missing worker."""

from alembic import op

revision = "0010_document_heartbeat"
down_revision = "0009_document_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION app.document_worker_active() RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT EXISTS(SELECT FROM app.ingestion_jobs WHERE kind='document' AND status='running'
        AND lease_expires_at>now() AND updated_at>now()-interval '10 seconds') $$;
    REVOKE ALL ON FUNCTION app.document_worker_active() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.document_worker_active() TO videomind_app;
    """)


def downgrade():
    op.execute("DROP FUNCTION app.document_worker_active()")
