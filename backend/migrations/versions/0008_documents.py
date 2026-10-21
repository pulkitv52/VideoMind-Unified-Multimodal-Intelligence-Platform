"""Separate document jobs and immutable page/artifact provenance."""

from alembic import op

revision = "0008_documents"
down_revision = "0007_intake_indexes"
branch_labels = None
depends_on = None

# Migration is immutable: do not import the evolving application profile.
PROFILE = "a284c8f919c8f99352e1c2bf2b28646ef7a514430089f41e4eb7b351fff885b6"


def upgrade():
    op.execute("""
    ALTER TABLE app.ingestion_jobs DROP CONSTRAINT ingestion_jobs_kind_check;
    ALTER TABLE app.ingestion_jobs ADD CONSTRAINT ingestion_jobs_kind_check CHECK(kind IN ('validate','folder_sync','document'));
    DROP INDEX app.revision_validation_job;
    CREATE UNIQUE INDEX revision_validation_job ON app.ingestion_jobs(workspace_id,source_id,revision_id) WHERE kind='validate';
    ALTER TABLE app.segment_sets ADD COLUMN manifest jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE app.segments ADD COLUMN derived_object_id uuid;
    ALTER TABLE app.segments ADD CONSTRAINT segment_input_object
      FOREIGN KEY(workspace_id,source_id,derived_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED;
    CREATE UNIQUE INDEX document_segment_set ON app.segment_sets(workspace_id,source_id,processing_run_id,segmenter_profile);
    CREATE TABLE app.document_pages (
      workspace_id uuid NOT NULL,source_id uuid NOT NULL,segment_set_id uuid NOT NULL,revision_id uuid NOT NULL,
      page integer NOT NULL CHECK(page>=1),
      text_object_id uuid NOT NULL,image_object_id uuid,rendering_object_id uuid,
      width double precision,height double precision,
      manifest jsonb NOT NULL,
      PRIMARY KEY(workspace_id,source_id,segment_set_id,page),
      FOREIGN KEY(workspace_id,source_id,segment_set_id,revision_id) REFERENCES app.segment_sets(workspace_id,source_id,id,revision_id) ON DELETE CASCADE,
      FOREIGN KEY(workspace_id,source_id,text_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED,
      FOREIGN KEY(workspace_id,source_id,image_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED,
      FOREIGN KEY(workspace_id,source_id,rendering_object_id) REFERENCES app.objects DEFERRABLE INITIALLY DEFERRED
    );
    ALTER TABLE app.document_pages ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.document_pages FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT,DELETE ON app.document_pages TO videomind_app;
    CREATE POLICY page_read ON app.document_pages FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id));
    CREATE POLICY page_insert ON app.document_pages FOR INSERT TO videomind_app WITH CHECK(app.source_access(workspace_id,source_id,true));
    CREATE POLICY page_delete ON app.document_pages FOR DELETE TO videomind_app USING(app.source_access(workspace_id,source_id,true));
    CREATE TRIGGER scope_unchanged BEFORE UPDATE ON app.document_pages FOR EACH ROW EXECUTE FUNCTION app.scope_unchanged();
    """)
    op.execute(f"""
    CREATE FUNCTION app.queue_document() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE run_id uuid; job_id uuid; mime text;
    BEGIN
      IF NEW.kind<>'validate' OR NEW.status<>'stored' OR NEW.processing_run_id IS NULL THEN RETURN NEW; END IF;
      SELECT o.mime_type INTO mime FROM app.asset_revisions r JOIN app.objects o
        ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id)
        WHERE r.workspace_id=NEW.workspace_id AND r.source_id=NEW.source_id AND r.id=NEW.revision_id;
      IF mime NOT IN ('application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain','text/markdown') THEN RETURN NEW; END IF;
      run_id:=gen_random_uuid(); job_id:=gen_random_uuid();
      INSERT INTO app.processing_runs(workspace_id,source_id,id,revision_id,profile_hash)
        VALUES(NEW.workspace_id,NEW.source_id,run_id,NEW.revision_id,'{PROFILE}') ON CONFLICT DO NOTHING;
      IF NOT FOUND THEN RETURN NEW; END IF;
      INSERT INTO app.stage_runs(workspace_id,source_id,processing_run_id,stage,configuration_hash,trace_id)
        VALUES(NEW.workspace_id,NEW.source_id,run_id,'extract_document','{PROFILE}',NEW.trace_id);
      INSERT INTO app.outbox(workspace_id,source_id,processing_run_id,event_type,payload)
        VALUES(NEW.workspace_id,NEW.source_id,run_id,'extract_document',jsonb_build_object('job_id',job_id));
      INSERT INTO app.ingestion_jobs(workspace_id,source_id,id,kind,revision_id,processing_run_id,requested_by,dedupe_key,trace_id)
        VALUES(NEW.workspace_id,NEW.source_id,job_id,'document',NEW.revision_id,run_id,NEW.requested_by,'document/{PROFILE}/'||NEW.revision_id::text,NEW.trace_id);
      RETURN NEW;
    END$$;
    REVOKE ALL ON FUNCTION app.queue_document() FROM PUBLIC;
    CREATE TRIGGER queue_document AFTER INSERT OR UPDATE OF status ON app.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION app.queue_document();
    -- Queue only real, format-validated originals; preserve intake and user data.
    UPDATE app.ingestion_jobs SET status=status WHERE kind='validate' AND status='stored' AND processing_run_id IS NOT NULL;
    """)


def downgrade():
    raise RuntimeError(
        "Document evidence is durable; restore a backup to reverse this migration"
    )
