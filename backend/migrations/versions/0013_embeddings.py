"""Durable profile-isolated embedding generations and change fencing."""

from alembic import op

revision = "0013_embeddings"
down_revision = "0012_media_partial"


def upgrade():
    op.get_bind().connection.driver_connection.execute(SQL, prepare=False)


def downgrade():
    raise RuntimeError("Preserve published generations; forward migrations only")


SQL = r"""
ALTER TABLE app.index_generations ADD COLUMN requested_by uuid REFERENCES auth.principals;
ALTER TABLE app.index_generations ADD COLUMN coverage jsonb NOT NULL DEFAULT '{}';
ALTER TABLE app.index_generations ADD CONSTRAINT generation_state CHECK(status IN ('building','active','standby','failed'));
CREATE UNIQUE INDEX one_building_generation ON app.index_generations(workspace_id) WHERE status='building';
CREATE UNIQUE INDEX one_active_generation ON app.index_generations(workspace_id) WHERE status='active';
ALTER TABLE app.workspace_search_state ADD COLUMN content_epoch bigint NOT NULL DEFAULT 0;
CREATE TABLE app.embedding_jobs (
 workspace_id uuid NOT NULL,source_id uuid NOT NULL,id uuid NOT NULL DEFAULT gen_random_uuid(),
 generation_id uuid NOT NULL,asset_id uuid NOT NULL,revision_id uuid NOT NULL,segment_set_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','ready','failed','cancelled')),
 attempt integer NOT NULL DEFAULT 0,lease_token uuid,lease_expires_at timestamptz,
 error_code text,manifest jsonb NOT NULL DEFAULT '{}',updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,source_id,id),
 UNIQUE(workspace_id,source_id,generation_id,asset_id,segment_set_id),
 FOREIGN KEY(workspace_id,generation_id) REFERENCES app.index_generations ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,source_id,asset_id,revision_id) REFERENCES app.asset_revisions(workspace_id,source_id,asset_id,id) ON DELETE CASCADE,
 FOREIGN KEY(workspace_id,source_id,segment_set_id,revision_id) REFERENCES app.segment_sets(workspace_id,source_id,id,revision_id) ON DELETE CASCADE
);
ALTER TABLE app.embedding_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.embedding_jobs FORCE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.embedding_jobs TO videomind_app;
CREATE POLICY jobs_read ON app.embedding_jobs FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id));
CREATE POLICY jobs_write ON app.embedding_jobs FOR ALL TO videomind_app USING(app.source_access(workspace_id,source_id,true)) WITH CHECK(app.source_access(workspace_id,source_id,true));
CREATE TRIGGER scope_unchanged BEFORE UPDATE ON app.embedding_jobs FOR EACH ROW EXECUTE FUNCTION app.scope_unchanged();
CREATE INDEX embedding_pending ON app.embedding_jobs(updated_at) WHERE status IN ('queued','running');
-- An input change and cutover/publication take the same workspace transaction lock.
CREATE FUNCTION app.index_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE w uuid;s uuid;a uuid;
BEGIN
 w:=NEW.workspace_id;
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(w::text,501));
 INSERT INTO app.workspace_search_state(workspace_id,content_epoch) VALUES(w,1)
 ON CONFLICT(workspace_id) DO UPDATE SET content_epoch=app.workspace_search_state.content_epoch+1;
 IF TG_TABLE_NAME='sources' AND NEW.deleted THEN
   DELETE FROM app.generation_assets WHERE workspace_id=w AND source_id=NEW.id;
   UPDATE app.embedding_jobs SET status='cancelled',lease_token=NULL WHERE workspace_id=w AND source_id=NEW.id;
 ELSIF TG_TABLE_NAME='assets' AND NEW.deleted THEN
   DELETE FROM app.generation_assets WHERE workspace_id=w AND source_id=NEW.source_id AND asset_id=NEW.id;
   UPDATE app.embedding_jobs SET status='cancelled',lease_token=NULL WHERE workspace_id=w AND source_id=NEW.source_id AND asset_id=NEW.id;
 END IF;
 RETURN NEW;
END$$;
CREATE TRIGGER index_asset_change AFTER INSERT OR UPDATE OF current_revision_id,deleted ON app.assets FOR EACH ROW EXECUTE FUNCTION app.index_change();
CREATE TRIGGER index_set_change AFTER INSERT OR UPDATE OF status ON app.segment_sets FOR EACH ROW EXECUTE FUNCTION app.index_change();
CREATE TRIGGER index_source_change AFTER UPDATE OF deleted ON app.sources FOR EACH ROW EXECUTE FUNCTION app.index_change();
-- Trusted inventory carries no content and does not grant caller content access.
CREATE FUNCTION app.index_pending() RETURNS TABLE(workspace_id uuid,generation_id uuid,requested_by uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
SELECT g.workspace_id,g.id,g.requested_by FROM app.index_generations g
JOIN app.memberships m ON m.workspace_id=g.workspace_id AND m.principal_id=g.requested_by
JOIN auth.principals p ON p.id=m.principal_id
WHERE g.status IN ('building','active','standby') AND m.role IN ('owner','admin') AND NOT p.disabled$$;
REVOKE ALL ON FUNCTION app.index_change(),app.index_pending() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.index_pending() TO videomind_app;
-- DDL is migration-owner-only except this constrained profile index constructor.
CREATE FUNCTION app.ensure_embedding_index(w uuid,p uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT app.admin_of(w) OR NOT EXISTS(SELECT FROM app.embedding_profiles WHERE workspace_id=w AND id=p) THEN RAISE EXCEPTION 'unavailable'; END IF;
 EXECUTE pg_catalog.format('CREATE INDEX IF NOT EXISTS %I ON app.embeddings USING hnsw (embedding public.vector_cosine_ops) WHERE profile_id=%L::uuid','embedding_hnsw_'||replace(p::text,'-',''),p);
END$$;
REVOKE ALL ON FUNCTION app.ensure_embedding_index(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.ensure_embedding_index(uuid,uuid) TO videomind_app;
CREATE INDEX embedding_profile_segment ON app.embeddings(workspace_id,profile_id,source_id,segment_id);
REVOKE UPDATE ON app.embedding_profiles FROM videomind_app;
"""
