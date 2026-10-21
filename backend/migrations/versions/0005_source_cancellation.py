"""Narrow source-admin cancellation without broadening job row privileges."""

from alembic import op

revision = "0005_source_cancellation"
down_revision = "0004_intake"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE FUNCTION app.cancel_source_intake(w uuid,s uuid) RETURNS void
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
      BEGIN
        IF NOT app.source_admin(w,s) THEN RAISE EXCEPTION 'source administrator required'; END IF;
        PERFORM 1 FROM app.sources WHERE workspace_id=w AND id=s AND NOT deleted FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'source unavailable'; END IF;
        UPDATE app.ingestion_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,updated_at=now()
          WHERE workspace_id=w AND source_id=s AND status IN ('queued','running');
      END$$;
      REVOKE ALL ON FUNCTION app.cancel_source_intake(uuid,uuid) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION app.cancel_source_intake(uuid,uuid) TO videomind_app;"""
    )


def downgrade():
    op.execute("DROP FUNCTION app.cancel_source_intake(uuid,uuid)")
