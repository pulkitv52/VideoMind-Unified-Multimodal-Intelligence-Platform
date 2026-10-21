"""Durable intake jobs, received revision pointers, and standalone images."""

from alembic import op

revision = "0004_intake"
down_revision = "0003_citation_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.assets DROP CONSTRAINT assets_modality_check;
    ALTER TABLE app.assets ADD CONSTRAINT assets_modality_check CHECK(modality IN ('document','image','video','audio'));
    ALTER TABLE app.assets ADD COLUMN latest_revision_id uuid;
    ALTER TABLE app.assets ADD CONSTRAINT latest_revision_same_asset
      FOREIGN KEY(workspace_id,source_id,id,latest_revision_id)
      REFERENCES app.asset_revisions(workspace_id,source_id,asset_id,id) DEFERRABLE INITIALLY DEFERRED;
    CREATE TABLE app.ingestion_jobs (
      workspace_id uuid NOT NULL, source_id uuid NOT NULL, id uuid NOT NULL DEFAULT gen_random_uuid(),
      kind text NOT NULL CHECK(kind IN ('validate','folder_sync')),
      revision_id uuid, processing_run_id uuid,
      requested_by uuid NOT NULL REFERENCES auth.principals,
      dedupe_key text NOT NULL,
      status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','stored','failed','cancelled')),
      attempt integer NOT NULL DEFAULT 0, lease_token uuid, lease_expires_at timestamptz,
      available_at timestamptz NOT NULL DEFAULT now(), error_code text,
      manifest jsonb NOT NULL DEFAULT '{}', trace_id uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(workspace_id,source_id,id), UNIQUE(workspace_id,source_id,dedupe_key),
      FOREIGN KEY(workspace_id,source_id) REFERENCES app.sources ON DELETE CASCADE,
      FOREIGN KEY(workspace_id,source_id,revision_id) REFERENCES app.asset_revisions ON DELETE CASCADE,
      FOREIGN KEY(workspace_id,source_id,processing_run_id) REFERENCES app.processing_runs ON DELETE CASCADE
    );
    CREATE INDEX ON app.ingestion_jobs(available_at) WHERE status IN ('queued','running');
    ALTER TABLE app.ingestion_jobs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.ingestion_jobs FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT,UPDATE,DELETE ON app.ingestion_jobs TO videomind_app;
    CREATE POLICY read_job ON app.ingestion_jobs FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id));
    CREATE POLICY write_job ON app.ingestion_jobs FOR ALL TO videomind_app
      USING(app.source_access(workspace_id,source_id,true))
      WITH CHECK(app.source_access(workspace_id,source_id,true) AND requested_by=app.actor_id());
    CREATE TRIGGER scope_unchanged BEFORE UPDATE ON app.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION app.scope_unchanged();
    -- Internal scheduler inventory contains identifiers only; no content endpoint exposes it.
    CREATE FUNCTION app.intake_pending() RETURNS TABLE(workspace_id uuid,source_id uuid,id uuid)
      LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
      SELECT j.workspace_id,j.source_id,j.id FROM app.ingestion_jobs j
      WHERE (j.status='queued' AND j.available_at<=now()) OR (j.status='running' AND j.lease_expires_at<now())
      ORDER BY j.created_at LIMIT 32 $$;
    CREATE FUNCTION app.intake_claim(w uuid,s uuid,jid uuid) RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
      DECLARE j app.ingestion_jobs; old_actor text; permitted boolean;
      BEGIN
        SELECT * INTO j FROM app.ingestion_jobs WHERE workspace_id=w AND source_id=s AND id=jid FOR UPDATE;
        IF NOT FOUND OR NOT ((j.status='queued' AND j.available_at<=now()) OR (j.status='running' AND j.lease_expires_at<now())) THEN RETURN NULL; END IF;
        old_actor:=current_setting('videomind.actor_id',true);
        PERFORM set_config('videomind.actor_id',j.requested_by::text,true);
        permitted:=app.source_access(w,s,true) AND EXISTS(SELECT FROM auth.principals WHERE id=j.requested_by AND NOT disabled);
        PERFORM set_config('videomind.actor_id',coalesce(old_actor,''),true);
        IF NOT permitted OR j.attempt>=3 THEN
          UPDATE app.ingestion_jobs SET status=CASE WHEN permitted THEN 'failed' ELSE 'cancelled' END,
            error_code=CASE WHEN permitted THEN 'ATTEMPTS_EXHAUSTED' ELSE 'ACCESS_REVOKED' END,updated_at=now() WHERE workspace_id=w AND source_id=s AND id=jid;
          RETURN NULL;
        END IF;
        UPDATE app.ingestion_jobs SET status='running',attempt=attempt+1,lease_token=gen_random_uuid(),
          lease_expires_at=now()+interval '5 minutes',updated_at=now() WHERE workspace_id=w AND source_id=s AND id=jid RETURNING * INTO j;
        RETURN to_jsonb(j);
      END$$;
    REVOKE ALL ON FUNCTION app.intake_pending(),app.intake_claim(uuid,uuid,uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.intake_pending(),app.intake_claim(uuid,uuid,uuid) TO videomind_app;
    """)


def downgrade():
    op.execute(
        """DROP FUNCTION app.intake_claim(uuid,uuid,uuid); DROP FUNCTION app.intake_pending();
      DROP TABLE app.ingestion_jobs; ALTER TABLE app.assets DROP COLUMN latest_revision_id;
      ALTER TABLE app.assets DROP CONSTRAINT assets_modality_check;
      ALTER TABLE app.assets ADD CONSTRAINT assets_modality_check CHECK(modality IN ('document','video','audio'));"""
    )
