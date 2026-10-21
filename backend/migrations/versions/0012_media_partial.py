"""Expose optional ASR failure in processing state while retaining native evidence."""

from alembic import op

revision = "0012_media_partial"
down_revision = "0011_media"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION app.intake_stage_state() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    BEGIN
      IF NEW.processing_run_id IS NOT NULL THEN
        UPDATE app.processing_runs SET status=CASE WHEN NEW.status='stored' AND NEW.kind='media' AND NEW.manifest->>'partial'='true' THEN 'partial' WHEN NEW.status='stored' THEN 'ready' ELSE NEW.status END,manifest=NEW.manifest
          WHERE workspace_id=NEW.workspace_id AND source_id=NEW.source_id AND id=NEW.processing_run_id;
        UPDATE app.stage_runs SET status=CASE WHEN NEW.status='stored' AND NEW.kind='media' AND NEW.manifest->>'partial'='true' THEN 'partial' ELSE NEW.status END,attempt=NEW.attempt,lease_token=NEW.lease_token,lease_expires_at=NEW.lease_expires_at,error_code=NEW.error_code,manifest=NEW.manifest
          WHERE workspace_id=NEW.workspace_id AND source_id=NEW.source_id AND processing_run_id=NEW.processing_run_id;
      END IF;
      RETURN NEW;
    END$$;
    UPDATE app.ingestion_jobs SET status=status WHERE kind='media' AND status='stored' AND manifest->>'partial'='true';
    """)


def downgrade():
    raise RuntimeError("Processing state requires a forward migration")
