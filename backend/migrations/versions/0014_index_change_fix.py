"""Use a heterogeneous-row-safe tombstone check in change tracking."""

from alembic import op

revision = "0014_index_change_fix"
down_revision = "0013_embeddings"


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION app.index_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE w uuid;
    BEGIN
      w:=NEW.workspace_id;
      PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(w::text,501));
      INSERT INTO app.workspace_search_state(workspace_id,content_epoch) VALUES(w,1)
      ON CONFLICT(workspace_id) DO UPDATE SET content_epoch=app.workspace_search_state.content_epoch+1;
      IF TG_TABLE_NAME='sources' AND (to_jsonb(NEW)->>'deleted')::boolean THEN
        DELETE FROM app.generation_assets WHERE workspace_id=w AND source_id=NEW.id;
        UPDATE app.embedding_jobs SET status='cancelled',lease_token=NULL WHERE workspace_id=w AND source_id=NEW.id;
      ELSIF TG_TABLE_NAME='assets' AND (to_jsonb(NEW)->>'deleted')::boolean THEN
        DELETE FROM app.generation_assets WHERE workspace_id=w AND source_id=NEW.source_id AND asset_id=NEW.id;
        UPDATE app.embedding_jobs SET status='cancelled',lease_token=NULL WHERE workspace_id=w AND source_id=NEW.source_id AND asset_id=NEW.id;
      END IF;
      RETURN NEW;
    END$$;
    """)


def downgrade():
    raise RuntimeError("Keep the corrected change fence")
