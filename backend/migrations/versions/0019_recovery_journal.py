"""Keep deletion and reinstatement events outside content retention cascades."""

from alembic import op

revision = "0019_recovery_journal"
down_revision = "0018_embedding_invariants"


def upgrade():
    op.execute("""
    CREATE SCHEMA recovery;
    REVOKE ALL ON SCHEMA recovery FROM PUBLIC, videomind_app;
    CREATE TABLE recovery.identity(id integer PRIMARY KEY CHECK(id=1), lineage uuid NOT NULL DEFAULT gen_random_uuid());
    INSERT INTO recovery.identity(id) VALUES(1);
    CREATE TABLE recovery.events(
      sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      event_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
      kind text NOT NULL CHECK(kind IN ('workspace','source','asset')),
      workspace_id uuid NOT NULL, source_id uuid, asset_id uuid,
      deleted boolean NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TABLE recovery.replayed_events(event_id uuid PRIMARY KEY);
    REVOKE ALL ON ALL TABLES IN SCHEMA recovery FROM PUBLIC, videomind_app;
    CREATE FUNCTION recovery.record_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE w uuid; s uuid; a uuid; k text; d boolean;
    BEGIN
      IF TG_OP='UPDATE' THEN
        IF NEW.deleted IS NOT DISTINCT FROM OLD.deleted THEN RETURN NEW; END IF;
        d:=NEW.deleted;
      ELSE d:=true; END IF;
      IF TG_TABLE_NAME='workspaces' THEN w:=OLD.id; k:='workspace';
      ELSIF TG_TABLE_NAME='sources' THEN w:=OLD.workspace_id; s:=OLD.id; k:='source';
      ELSIF TG_TABLE_NAME='assets' THEN w:=OLD.workspace_id; s:=OLD.source_id; a:=OLD.id; k:='asset';
      ELSE RAISE EXCEPTION 'Unsupported recovery entity'; END IF;
      INSERT INTO recovery.events(kind,workspace_id,source_id,asset_id,deleted) VALUES(k,w,s,a,d);
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END$$;
    REVOKE ALL ON FUNCTION recovery.record_change() FROM PUBLIC, videomind_app;
    CREATE TRIGGER recovery_workspace_delete BEFORE DELETE ON app.workspaces FOR EACH ROW EXECUTE FUNCTION recovery.record_change();
    CREATE TRIGGER recovery_source_change BEFORE UPDATE OF deleted OR DELETE ON app.sources FOR EACH ROW EXECUTE FUNCTION recovery.record_change();
    CREATE TRIGGER recovery_asset_change BEFORE UPDATE OF deleted OR DELETE ON app.assets FOR EACH ROW EXECUTE FUNCTION recovery.record_change();
    """)


def downgrade():
    raise RuntimeError("Preserve recovery history")
