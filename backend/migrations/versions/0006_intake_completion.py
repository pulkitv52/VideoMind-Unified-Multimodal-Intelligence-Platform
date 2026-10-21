"""Bound storage, preserve deletion ages and maintain durable storage sweeps."""

from alembic import op

revision = "0006_intake_completion"
down_revision = "0005_source_cancellation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION app.intake_stage_state() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    BEGIN
      IF NEW.processing_run_id IS NOT NULL THEN
        UPDATE app.processing_runs SET status=CASE WHEN NEW.status='stored' THEN 'ready' ELSE NEW.status END,manifest=NEW.manifest
          WHERE workspace_id=NEW.workspace_id AND source_id=NEW.source_id AND id=NEW.processing_run_id;
        UPDATE app.stage_runs SET status=NEW.status,attempt=NEW.attempt,lease_token=NEW.lease_token,lease_expires_at=NEW.lease_expires_at,
          error_code=NEW.error_code,manifest=NEW.manifest
          WHERE workspace_id=NEW.workspace_id AND source_id=NEW.source_id AND processing_run_id=NEW.processing_run_id;
      END IF;
      RETURN NEW;
    END$$;
    REVOKE ALL ON FUNCTION app.intake_stage_state() FROM PUBLIC;
    CREATE TRIGGER intake_stage_state AFTER INSERT OR UPDATE ON app.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION app.intake_stage_state();
    ALTER TABLE app.sources ADD COLUMN deleted_at timestamptz;
    ALTER TABLE app.assets ADD COLUMN deleted_at timestamptz;
    UPDATE app.sources SET deleted_at=now() WHERE deleted;
    UPDATE app.assets SET deleted_at=now() WHERE deleted;
    CREATE FUNCTION app.deletion_time() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
    BEGIN
      IF NEW.deleted THEN
        NEW.deleted_at:=CASE WHEN OLD.deleted THEN OLD.deleted_at ELSE now() END;
      ELSE NEW.deleted_at:=NULL; END IF;
      RETURN NEW;
    END$$;
    CREATE TRIGGER deletion_time BEFORE UPDATE ON app.sources FOR EACH ROW EXECUTE FUNCTION app.deletion_time();
    CREATE TRIGGER deletion_time BEFORE UPDATE ON app.assets FOR EACH ROW EXECUTE FUNCTION app.deletion_time();
    CREATE TABLE app.object_reservations (
      workspace_id uuid NOT NULL,source_id uuid NOT NULL,id uuid NOT NULL,
      bucket text NOT NULL,object_key text NOT NULL,size_bytes bigint NOT NULL CHECK(size_bytes>=0),
      created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(workspace_id,source_id,id));
    ALTER TABLE app.object_reservations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.object_reservations FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT,DELETE ON app.object_reservations TO videomind_app;
    CREATE POLICY reservation_read ON app.object_reservations FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id));
    CREATE POLICY reservation_insert ON app.object_reservations FOR INSERT TO videomind_app WITH CHECK(app.source_access(workspace_id,source_id,true));
    CREATE POLICY reservation_delete ON app.object_reservations FOR DELETE TO videomind_app USING(app.source_access(workspace_id,source_id,true));
    CREATE INDEX ON app.object_reservations(created_at);
    -- No source FK: a failed-write reservation survives source deletion until
    -- storage removal is confirmed. It cannot be exposed through content APIs.
    CREATE FUNCTION app.expired_reservations() RETURNS SETOF app.object_reservations
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT * FROM app.object_reservations WHERE created_at<now()-interval '1 hour' ORDER BY created_at LIMIT 32 $$;
    CREATE FUNCTION app.release_reservation(w uuid,s uuid,i uuid) RETURNS void
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      DELETE FROM app.object_reservations WHERE workspace_id=w AND source_id=s AND id=i AND created_at<now()-interval '1 hour' $$;
    CREATE TABLE app.storage_sweep (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
      cursor text NOT NULL DEFAULT '', updated_at timestamptz NOT NULL DEFAULT now());
    INSERT INTO app.storage_sweep DEFAULT VALUES;
    ALTER TABLE app.storage_sweep ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.storage_sweep FORCE ROW LEVEL SECURITY;
    -- No direct runtime grants. These functions are trusted server internals,
    -- like intake_claim, and have no HTTP exposure or user-supplied SQL surface.
    CREATE FUNCTION app.storage_cursor(next_value text DEFAULT NULL) RETURNS text
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE result text;
    BEGIN
      IF next_value IS NOT NULL THEN
        UPDATE app.storage_sweep SET cursor=next_value,updated_at=now();
      END IF;
      SELECT cursor INTO result FROM app.storage_sweep;
      RETURN result;
    END$$;
    CREATE FUNCTION app.storage_referenced(b text,k text) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT EXISTS(SELECT FROM app.objects WHERE bucket=b AND object_key=k) $$;
    CREATE FUNCTION app.storage_admit(w uuid,s uuid,extra bigint,budget bigint,object_budget bigint) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT extra>=0 AND app.source_access(w,s,true)
        AND (SELECT coalesce(sum(size_bytes),0)+extra<=budget AND count(*)<object_budget
             FROM (SELECT size_bytes FROM app.objects WHERE workspace_id=w UNION ALL SELECT size_bytes FROM app.object_reservations WHERE workspace_id=w) usage) $$;
    CREATE FUNCTION app.storage_usage(w uuid) RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    BEGIN
      IF NOT app.admin_of(w) THEN RAISE EXCEPTION 'workspace administrator required'; END IF;
      RETURN (SELECT jsonb_build_object('bytes',coalesce(sum(size_bytes),0),'objects',count(*))
              FROM (SELECT size_bytes FROM app.objects WHERE workspace_id=w UNION ALL SELECT size_bytes FROM app.object_reservations WHERE workspace_id=w) usage);
    END$$;
    CREATE FUNCTION app.retire_intake() RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE sources_removed integer; assets_removed integer; objects_removed integer;
    BEGIN
      -- Caller holds the exclusive storage lock. A fixed one-hour retention
      -- floor cannot be shortened through the runtime function arguments.
      DELETE FROM app.sources WHERE (workspace_id,id) IN
        (SELECT workspace_id,id FROM app.sources WHERE deleted AND deleted_at<now()-interval '1 hour' LIMIT 32);
      GET DIAGNOSTICS sources_removed=ROW_COUNT;
      DELETE FROM app.assets a WHERE (workspace_id,source_id,id) IN
        (SELECT a.workspace_id,a.source_id,a.id FROM app.assets a WHERE a.deleted AND a.deleted_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.generation_assets g WHERE (g.workspace_id,g.source_id,g.asset_id)=(a.workspace_id,a.source_id,a.id)) LIMIT 128);
      GET DIAGNOSTICS assets_removed=ROW_COUNT;
      DELETE FROM app.objects o WHERE (workspace_id,source_id,id) IN
        (SELECT o.workspace_id,o.source_id,o.id FROM app.objects o
         WHERE o.role='original' AND o.created_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.asset_revisions r WHERE (r.workspace_id,r.source_id,r.original_object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.evidence_anchors e WHERE e.workspace_id=o.workspace_id AND e.source_id=o.source_id AND (e.original_object_id=o.id OR e.text_artifact_id=o.id))
         AND NOT EXISTS(SELECT FROM app.objects d WHERE (d.workspace_id,d.source_id,d.derived_from_id)=(o.workspace_id,o.source_id,o.id)) LIMIT 128);
      GET DIAGNOSTICS objects_removed=ROW_COUNT;
      RETURN jsonb_build_object('sources',sources_removed,'assets',assets_removed,'object_rows',objects_removed);
    END$$;
    REVOKE ALL ON FUNCTION app.storage_cursor(text),app.storage_referenced(text,text),app.storage_admit(uuid,uuid,bigint,bigint,bigint),app.storage_usage(uuid),app.retire_intake(),app.expired_reservations(),app.release_reservation(uuid,uuid,uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.storage_cursor(text),app.storage_referenced(text,text),app.storage_admit(uuid,uuid,bigint,bigint,bigint),app.storage_usage(uuid),app.retire_intake(),app.expired_reservations(),app.release_reservation(uuid,uuid,uuid) TO videomind_app;
    CREATE INDEX ON app.sources(deleted_at) WHERE deleted;
    CREATE INDEX ON app.assets(deleted_at) WHERE deleted;
    CREATE INDEX ON app.objects(bucket,object_key);
    """)


def downgrade():
    op.execute("""
    DROP FUNCTION app.storage_cursor(text),app.storage_referenced(text,text),app.storage_admit(uuid,uuid,bigint,bigint,bigint),app.storage_usage(uuid),app.retire_intake();
    DROP FUNCTION app.expired_reservations(),app.release_reservation(uuid,uuid,uuid);
    DROP TABLE app.object_reservations;
    DROP TRIGGER intake_stage_state ON app.ingestion_jobs;
    DROP FUNCTION app.intake_stage_state();
    DROP TABLE app.storage_sweep;
    DROP TRIGGER deletion_time ON app.sources; DROP TRIGGER deletion_time ON app.assets;
    DROP FUNCTION app.deletion_time();
    ALTER TABLE app.sources DROP COLUMN deleted_at; ALTER TABLE app.assets DROP COLUMN deleted_at;
    DROP INDEX app.objects_bucket_object_key_idx;
    """)
