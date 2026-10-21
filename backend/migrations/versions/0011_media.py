"""Durable media receipts, native artifacts and original-time playback mappings."""

from alembic import op

revision = "0011_media"
down_revision = "0010_document_heartbeat"
branch_labels = None
depends_on = None
PROFILE = "5f918a0027223d7aa51aea72620cc0d5c5c15898275f5d09b17f8d09af877317"


def upgrade():
    op.execute("""
    ALTER TABLE app.ingestion_jobs DROP CONSTRAINT ingestion_jobs_kind_check;
    ALTER TABLE app.ingestion_jobs ADD CONSTRAINT ingestion_jobs_kind_check CHECK(kind IN ('validate','folder_sync','document','media'));
    DROP INDEX app.document_segment_set;
    CREATE UNIQUE INDEX document_segment_set ON app.segment_sets(workspace_id,source_id,processing_run_id,segmenter_profile) WHERE manifest->>'kind' IS DISTINCT FROM 'media';
    CREATE TABLE app.media_presentations (
      workspace_id uuid NOT NULL,source_id uuid NOT NULL,segment_set_id uuid NOT NULL,revision_id uuid NOT NULL,
      playback_object_id uuid NOT NULL,mapping_object_id uuid NOT NULL,manifest jsonb NOT NULL,
      PRIMARY KEY(workspace_id,source_id,segment_set_id),
      FOREIGN KEY(workspace_id,source_id,segment_set_id,revision_id) REFERENCES app.segment_sets(workspace_id,source_id,id,revision_id) ON DELETE CASCADE,
      FOREIGN KEY(workspace_id,source_id,playback_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED,
      FOREIGN KEY(workspace_id,source_id,mapping_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED);
    CREATE TABLE app.media_artifacts (
      workspace_id uuid NOT NULL,source_id uuid NOT NULL,segment_set_id uuid NOT NULL,object_id uuid NOT NULL,
      PRIMARY KEY(workspace_id,source_id,segment_set_id,object_id),
      FOREIGN KEY(workspace_id,source_id,segment_set_id) REFERENCES app.media_presentations ON DELETE CASCADE,
      FOREIGN KEY(workspace_id,source_id,object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED);
    CREATE INDEX media_object_reference ON app.media_artifacts(workspace_id,source_id,object_id);
    DO $$ DECLARE t text; BEGIN
      FOREACH t IN ARRAY ARRAY['media_presentations','media_artifacts'] LOOP
        EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE app.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('GRANT SELECT,INSERT,DELETE ON app.%I TO videomind_app',t);
        EXECUTE format('CREATE POLICY media_read ON app.%I FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id))',t);
        EXECUTE format('CREATE POLICY media_insert ON app.%I FOR INSERT TO videomind_app WITH CHECK(app.source_access(workspace_id,source_id,true))',t);
        EXECUTE format('CREATE POLICY media_delete ON app.%I FOR DELETE TO videomind_app USING(app.source_access(workspace_id,source_id,true))',t);
      END LOOP;
    END$$;
    CREATE OR REPLACE FUNCTION app.document_worker_active() RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT EXISTS(SELECT FROM app.ingestion_jobs WHERE kind IN ('document','media') AND status='running' AND lease_expires_at>now() AND updated_at>now()-interval '10 seconds') $$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.intake_pending() RETURNS TABLE(workspace_id uuid,source_id uuid,id uuid)
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT j.workspace_id,j.source_id,j.id FROM app.ingestion_jobs j
      WHERE (j.status='queued' AND j.available_at<=now()) OR (j.status='running' AND j.lease_expires_at<now())
      ORDER BY CASE j.kind WHEN 'validate' THEN 0 WHEN 'folder_sync' THEN 0 WHEN 'document' THEN 3 ELSE 6 END,j.created_at LIMIT 32 $$;
    CREATE FUNCTION app.intake_priority(w uuid,s uuid,j uuid) RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT CASE kind WHEN 'validate' THEN 0 WHEN 'folder_sync' THEN 0 WHEN 'document' THEN 3 ELSE 6 END FROM app.ingestion_jobs WHERE workspace_id=w AND source_id=s AND id=j $$;
    REVOKE ALL ON FUNCTION app.intake_priority(uuid,uuid,uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.intake_priority(uuid,uuid,uuid) TO videomind_app;
    """)
    op.execute(f"""
    CREATE FUNCTION app.queue_media() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE run_id uuid; job_id uuid; mime text;
    BEGIN
      IF NEW.kind<>'validate' OR NEW.status<>'stored' OR NEW.processing_run_id IS NULL THEN RETURN NEW; END IF;
      SELECT o.mime_type INTO mime FROM app.asset_revisions r JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id)
        WHERE r.workspace_id=NEW.workspace_id AND r.source_id=NEW.source_id AND r.id=NEW.revision_id;
      IF mime NOT LIKE 'video/%' AND mime NOT LIKE 'audio/%' THEN RETURN NEW; END IF;
      run_id:=gen_random_uuid();job_id:=gen_random_uuid();
      INSERT INTO app.processing_runs(workspace_id,source_id,id,revision_id,profile_hash) VALUES(NEW.workspace_id,NEW.source_id,run_id,NEW.revision_id,'{PROFILE}') ON CONFLICT DO NOTHING;
      IF NOT FOUND THEN RETURN NEW; END IF;
      INSERT INTO app.stage_runs(workspace_id,source_id,processing_run_id,stage,configuration_hash,trace_id) VALUES(NEW.workspace_id,NEW.source_id,run_id,'process_media','{PROFILE}',NEW.trace_id);
      INSERT INTO app.outbox(workspace_id,source_id,processing_run_id,event_type,payload) VALUES(NEW.workspace_id,NEW.source_id,run_id,'process_media',jsonb_build_object('job_id',job_id));
      INSERT INTO app.ingestion_jobs(workspace_id,source_id,id,kind,revision_id,processing_run_id,requested_by,dedupe_key,trace_id)
        VALUES(NEW.workspace_id,NEW.source_id,job_id,'media',NEW.revision_id,run_id,NEW.requested_by,'media/{PROFILE}/'||NEW.revision_id::text,NEW.trace_id);
      RETURN NEW;
    END$$;
    REVOKE ALL ON FUNCTION app.queue_media() FROM PUBLIC;
    CREATE TRIGGER queue_media AFTER INSERT OR UPDATE OF status ON app.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION app.queue_media();
    UPDATE app.ingestion_jobs SET status=status WHERE kind='validate' AND status='stored' AND processing_run_id IS NOT NULL;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.retire_intake() RETURNS jsonb
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
        (SELECT o.workspace_id,o.source_id,o.id FROM app.objects o WHERE o.role='derivative' AND o.created_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.document_pages p WHERE p.workspace_id=o.workspace_id AND p.source_id=o.source_id AND o.id IN (p.text_object_id,p.image_object_id,p.rendering_object_id))
         AND NOT EXISTS(SELECT FROM app.media_artifacts ma WHERE (ma.workspace_id,ma.source_id,ma.object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.segments g WHERE (g.workspace_id,g.source_id,g.derived_object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.evidence_anchors e WHERE e.workspace_id=o.workspace_id AND e.source_id=o.source_id AND o.id IN (e.original_object_id,e.text_artifact_id))
         AND NOT EXISTS(SELECT FROM app.segment_sets ss WHERE ss.workspace_id=o.workspace_id AND ss.source_id=o.source_id AND ss.manifest->>'structure_object_id'=o.id::text)
         AND NOT EXISTS(SELECT FROM app.objects d WHERE (d.workspace_id,d.source_id,d.derived_from_id)=(o.workspace_id,o.source_id,o.id)) LIMIT 128);
      DELETE FROM app.objects o WHERE (workspace_id,source_id,id) IN
        (SELECT o.workspace_id,o.source_id,o.id FROM app.objects o
         WHERE o.role='original' AND o.created_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.asset_revisions r WHERE (r.workspace_id,r.source_id,r.original_object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.evidence_anchors e WHERE e.workspace_id=o.workspace_id AND e.source_id=o.source_id AND (e.original_object_id=o.id OR e.text_artifact_id=o.id))
         AND NOT EXISTS(SELECT FROM app.objects d WHERE (d.workspace_id,d.source_id,d.derived_from_id)=(o.workspace_id,o.source_id,o.id)) LIMIT 128);
      GET DIAGNOSTICS objects_removed=ROW_COUNT;
      RETURN jsonb_build_object('sources',sources_removed,'assets',assets_removed,'object_rows',objects_removed);
    END$$;
    """)


def downgrade():
    raise RuntimeError("Media evidence requires a forward migration or backup restore")
