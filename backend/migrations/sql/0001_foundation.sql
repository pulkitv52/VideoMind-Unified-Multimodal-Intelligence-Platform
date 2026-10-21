CREATE EXTENSION IF NOT EXISTS vector;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA auth;
CREATE SCHEMA app;
REVOKE ALL ON SCHEMA auth, app FROM PUBLIC;

CREATE TABLE auth.principals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE CHECK (length(username) BETWEEN 1 AND 64),
  password_hash text NOT NULL,
  disabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE auth.sessions (
  token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  principal_id uuid NOT NULL REFERENCES auth.principals ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON auth.sessions (expires_at);

CREATE TABLE app.workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.memberships (
  workspace_id uuid NOT NULL REFERENCES app.workspaces ON DELETE CASCADE,
  principal_id uuid NOT NULL REFERENCES auth.principals ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner','admin','member')),
  PRIMARY KEY (workspace_id, principal_id)
);
CREATE TABLE app.sources (
  workspace_id uuid NOT NULL REFERENCES app.workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  name text NOT NULL,
  connector_kind text NOT NULL CHECK (connector_kind IN ('upload','local_folder')),
  connector_version text NOT NULL DEFAULT 'v1',
  config jsonb NOT NULL DEFAULT '{}',
  secret_ref text,
  sync_cursor text,
  acl_revision bigint NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'disconnected',
  deleted boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,id)
);
CREATE TABLE app.source_grants (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  principal_id uuid NOT NULL REFERENCES auth.principals ON DELETE CASCADE,
  permission text NOT NULL CHECK (permission IN ('read','ingest','admin')),
  PRIMARY KEY (workspace_id,source_id,principal_id),
  FOREIGN KEY (workspace_id,source_id) REFERENCES app.sources ON DELETE CASCADE
);
CREATE TABLE app.objects (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  bucket text NOT NULL,
  object_key text NOT NULL,
  version_id text,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes>=0),
  mime_type text NOT NULL,
  role text NOT NULL CHECK (role IN ('original','derivative')),
  derived_from_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,object_key),
  FOREIGN KEY (workspace_id,source_id) REFERENCES app.sources ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,derived_from_id) REFERENCES app.objects,
  CHECK (derived_from_id IS NULL OR derived_from_id<>id)
);
CREATE TABLE app.assets (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  external_id text NOT NULL,
  title text NOT NULL,
  modality text NOT NULL CHECK (modality IN ('document','video','audio')),
  mime_type text NOT NULL,
  tags jsonb NOT NULL DEFAULT '[]',
  current_revision_id uuid,
  -- Provider item ACLs are deferred. Other modes cannot silently inherit access.
  acl_mode text NOT NULL DEFAULT 'inherit_source' CHECK (acl_mode='inherit_source'),
  deleted boolean NOT NULL DEFAULT false,
  source_created_at timestamptz,
  source_modified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,external_id),
  FOREIGN KEY (workspace_id,source_id) REFERENCES app.sources ON DELETE CASCADE
);
CREATE TABLE app.asset_revisions (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  external_revision text NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  original_object_id uuid NOT NULL,
  duration_ms bigint CHECK (duration_ms>=0),
  page_count integer CHECK (page_count>0),
  probe_manifest jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,asset_id,id),
  UNIQUE (workspace_id,source_id,asset_id,external_revision,sha256),
  FOREIGN KEY (workspace_id,source_id,asset_id) REFERENCES app.assets ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,original_object_id) REFERENCES app.objects
);
ALTER TABLE app.assets ADD CONSTRAINT current_revision_same_asset
  FOREIGN KEY (workspace_id,source_id,id,current_revision_id)
  REFERENCES app.asset_revisions(workspace_id,source_id,asset_id,id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE app.processing_runs (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL,
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','ready','partial','failed','cancelled')),
  manifest jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,revision_id,profile_hash),
  UNIQUE (workspace_id,source_id,id,revision_id),
  FOREIGN KEY (workspace_id,source_id,revision_id) REFERENCES app.asset_revisions ON DELETE CASCADE
);
CREATE TABLE app.stage_runs (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  processing_run_id uuid NOT NULL,
  stage text NOT NULL,
  configuration_hash text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt>=0),
  lease_token uuid,
  lease_expires_at timestamptz,
  error_code text,
  trace_id uuid NOT NULL DEFAULT gen_random_uuid(),
  manifest jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,processing_run_id,stage,configuration_hash),
  FOREIGN KEY (workspace_id,source_id,processing_run_id) REFERENCES app.processing_runs ON DELETE CASCADE
);
CREATE TABLE app.outbox (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  processing_run_id uuid NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  FOREIGN KEY (workspace_id,source_id,processing_run_id) REFERENCES app.processing_runs ON DELETE CASCADE
);
CREATE INDEX ON app.outbox (created_at) WHERE published_at IS NULL;
CREATE TABLE app.segment_sets (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL,
  processing_run_id uuid NOT NULL,
  segmenter_profile text NOT NULL,
  status text NOT NULL DEFAULT 'building',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,id,revision_id),
  FOREIGN KEY (workspace_id,source_id,revision_id) REFERENCES app.asset_revisions ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,processing_run_id,revision_id) REFERENCES app.processing_runs(workspace_id,source_id,id,revision_id)
);
CREATE TABLE app.segments (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  segment_set_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  representation text NOT NULL CHECK (representation IN ('text','ocr','transcript','image','video','audio')),
  ordinal integer NOT NULL CHECK (ordinal>=0),
  text_content text,
  language text,
  producer text NOT NULL,
  quality jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,id,revision_id),
  UNIQUE (workspace_id,source_id,segment_set_id,representation,ordinal),
  FOREIGN KEY (workspace_id,source_id,segment_set_id,revision_id) REFERENCES app.segment_sets(workspace_id,source_id,id,revision_id) ON DELETE CASCADE
);
CREATE TABLE app.evidence_anchors (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL,
  original_object_id uuid NOT NULL,
  locator_kind text NOT NULL CHECK (locator_kind IN ('page','temporal','text')),
  page integer,
  start_ms bigint,
  end_ms bigint,
  track text,
  text_artifact_id uuid,
  start_char integer,
  end_char integer,
  transform jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,id,revision_id),
  FOREIGN KEY (workspace_id,source_id,revision_id) REFERENCES app.asset_revisions ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,original_object_id) REFERENCES app.objects,
  FOREIGN KEY (workspace_id,source_id,text_artifact_id) REFERENCES app.objects,
  CHECK (
    (locator_kind='page' AND page IS NOT NULL AND page>=1 AND start_ms IS NULL AND end_ms IS NULL AND track IS NULL AND text_artifact_id IS NULL AND start_char IS NULL AND end_char IS NULL) OR
    (locator_kind='temporal' AND page IS NULL AND start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms>=0 AND end_ms>start_ms AND track IS NOT NULL AND length(track)>0 AND text_artifact_id IS NULL AND start_char IS NULL AND end_char IS NULL) OR
    (locator_kind='text' AND page IS NULL AND start_ms IS NULL AND end_ms IS NULL AND track IS NULL AND text_artifact_id IS NOT NULL AND start_char IS NOT NULL AND end_char IS NOT NULL AND start_char>=0 AND end_char>start_char)
  )
);
CREATE TABLE app.segment_evidence (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  segment_id uuid NOT NULL,
  anchor_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  relation text NOT NULL CHECK (relation IN ('extracted_from','transcribed_from','depicts','ocr_from')),
  producer text NOT NULL,
  PRIMARY KEY (workspace_id,source_id,segment_id,anchor_id),
  FOREIGN KEY (workspace_id,source_id,segment_id,revision_id) REFERENCES app.segments(workspace_id,source_id,id,revision_id) ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,anchor_id,revision_id) REFERENCES app.evidence_anchors(workspace_id,source_id,id,revision_id) ON DELETE CASCADE
);
CREATE TABLE app.segment_relations (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  from_id uuid NOT NULL,
  to_id uuid NOT NULL,
  relation text NOT NULL CHECK (relation IN ('part_of','aligned_with','overlaps','derived_from')),
  producer text NOT NULL,
  PRIMARY KEY (workspace_id,source_id,from_id,to_id,relation),
  CHECK (from_id<>to_id),
  FOREIGN KEY (workspace_id,source_id,from_id) REFERENCES app.segments ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,to_id) REFERENCES app.segments ON DELETE CASCADE
);
CREATE TABLE app.embedding_profiles (
  workspace_id uuid NOT NULL REFERENCES app.workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
  model_id text NOT NULL,
  model_revision text NOT NULL CHECK (model_revision ~ '^[0-9a-f]{40}$'),
  configuration jsonb NOT NULL,
  dimension integer NOT NULL CHECK (dimension=768),
  PRIMARY KEY (workspace_id,id),
  UNIQUE (workspace_id,fingerprint)
);
CREATE TABLE app.index_generations (
  workspace_id uuid NOT NULL REFERENCES app.workspaces ON DELETE CASCADE,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'building',
  watermark text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,id),
  FOREIGN KEY (workspace_id,profile_id) REFERENCES app.embedding_profiles
);
CREATE TABLE app.generation_assets (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  generation_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  segment_set_id uuid NOT NULL,
  PRIMARY KEY (workspace_id,source_id,generation_id,asset_id),
  FOREIGN KEY (workspace_id,generation_id) REFERENCES app.index_generations ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,source_id,asset_id,revision_id) REFERENCES app.asset_revisions(workspace_id,source_id,asset_id,id),
  FOREIGN KEY (workspace_id,source_id,segment_set_id,revision_id) REFERENCES app.segment_sets(workspace_id,source_id,id,revision_id)
);
CREATE TABLE app.workspace_search_state (
  workspace_id uuid PRIMARY KEY REFERENCES app.workspaces ON DELETE CASCADE,
  active_generation_id uuid,
  policy_epoch bigint NOT NULL DEFAULT 0,
  FOREIGN KEY (workspace_id,active_generation_id) REFERENCES app.index_generations
);
CREATE TABLE app.embeddings (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  segment_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
  input_manifest jsonb NOT NULL DEFAULT '{}',
  embedding vector(768) NOT NULL,
  PRIMARY KEY (workspace_id,source_id,id),
  UNIQUE (workspace_id,source_id,segment_id,profile_id,input_hash),
  FOREIGN KEY (workspace_id,source_id,segment_id) REFERENCES app.segments ON DELETE CASCADE,
  FOREIGN KEY (workspace_id,profile_id) REFERENCES app.embedding_profiles,
  CHECK (vector_norm(embedding)>0.999 AND vector_norm(embedding)<1.001)
);
CREATE TABLE app.searchable_text (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  segment_id uuid NOT NULL,
  configuration regconfig NOT NULL DEFAULT 'simple',
  text_content text NOT NULL,
  lexemes tsvector NOT NULL,
  PRIMARY KEY (workspace_id,source_id,segment_id),
  FOREIGN KEY (workspace_id,source_id,segment_id) REFERENCES app.segments ON DELETE CASCADE
);
CREATE INDEX ON app.searchable_text USING gin(lexemes);
CREATE TABLE app.citation_records (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  segment_id uuid NOT NULL,
  anchor_id uuid NOT NULL,
  PRIMARY KEY (workspace_id,source_id,id),
  FOREIGN KEY (workspace_id,source_id,segment_id,anchor_id) REFERENCES app.segment_evidence
);
CREATE TABLE app.audit_events (
  workspace_id uuid NOT NULL,
  source_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL REFERENCES auth.principals,
  action text NOT NULL,
  outcome text NOT NULL,
  trace_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id,source_id,id),
  FOREIGN KEY (workspace_id,source_id) REFERENCES app.sources ON DELETE CASCADE
);

-- Trusted server identity is transaction-local. DB credentials are server-only.
CREATE FUNCTION app.actor_id() RETURNS uuid LANGUAGE sql STABLE
  SET search_path='' AS $$SELECT nullif(current_setting('videomind.actor_id',true),'')::uuid$$;
CREATE FUNCTION app.member_of(w uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path='' AS $$SELECT EXISTS(SELECT FROM app.memberships WHERE workspace_id=w AND principal_id=app.actor_id())$$;
CREATE FUNCTION app.admin_of(w uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path='' AS $$SELECT EXISTS(SELECT FROM app.memberships WHERE workspace_id=w AND principal_id=app.actor_id() AND role IN ('owner','admin'))$$;
CREATE FUNCTION app.source_access(w uuid,s uuid,write_access boolean DEFAULT false) RETURNS boolean
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
  SELECT app.member_of(w) AND EXISTS(SELECT FROM app.sources WHERE workspace_id=w AND id=s AND NOT deleted)
  AND (app.admin_of(w) OR EXISTS(SELECT FROM app.source_grants WHERE workspace_id=w AND source_id=s AND principal_id=app.actor_id()
       AND (NOT write_access OR permission IN ('ingest','admin'))))$$;
CREATE FUNCTION app.source_admin(w uuid,s uuid) RETURNS boolean
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
  SELECT app.member_of(w) AND (app.admin_of(w) OR EXISTS(SELECT FROM app.source_grants WHERE workspace_id=w AND source_id=s AND principal_id=app.actor_id() AND permission='admin'))$$;

GRANT USAGE ON SCHEMA app, auth TO videomind_app;
GRANT SELECT ON auth.principals TO videomind_app;
GRANT SELECT,INSERT,DELETE ON auth.sessions TO videomind_app;
GRANT SELECT ON app.workspaces,app.memberships,app.source_grants TO videomind_app;
GRANT SELECT ON public.alembic_version TO videomind_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO videomind_app;

ALTER TABLE app.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY member_read ON app.workspaces FOR SELECT TO videomind_app USING(app.member_of(id));
ALTER TABLE app.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY own_membership ON app.memberships FOR SELECT TO videomind_app USING(principal_id=app.actor_id());
ALTER TABLE app.source_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.source_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY own_grants ON app.source_grants FOR SELECT TO videomind_app USING(app.member_of(workspace_id) AND (principal_id=app.actor_id() OR app.admin_of(workspace_id)));
ALTER TABLE app.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.sources FORCE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.sources TO videomind_app;
CREATE POLICY source_read ON app.sources FOR SELECT TO videomind_app USING(app.source_access(workspace_id,id));
CREATE POLICY source_insert ON app.sources FOR INSERT TO videomind_app WITH CHECK(app.admin_of(workspace_id));
CREATE POLICY source_update ON app.sources FOR UPDATE TO videomind_app USING(app.source_admin(workspace_id,id)) WITH CHECK(app.source_admin(workspace_id,id));
CREATE POLICY source_delete ON app.sources FOR DELETE TO videomind_app USING(app.source_admin(workspace_id,id));

DO $$DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['objects','assets','asset_revisions','processing_runs','stage_runs','outbox','segment_sets','segments','evidence_anchors','segment_evidence','segment_relations','generation_assets','embeddings','searchable_text','citation_records','audit_events'] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE app.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON app.%I TO videomind_app',t);
    EXECUTE format('CREATE POLICY content_read ON app.%I FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id))',t);
    EXECUTE format('CREATE POLICY content_insert ON app.%I FOR INSERT TO videomind_app WITH CHECK(app.source_access(workspace_id,source_id,true))',t);
    EXECUTE format('CREATE POLICY content_update ON app.%I FOR UPDATE TO videomind_app USING(app.source_access(workspace_id,source_id,true)) WITH CHECK(app.source_access(workspace_id,source_id,true))',t);
    EXECUTE format('CREATE POLICY content_delete ON app.%I FOR DELETE TO videomind_app USING(app.source_access(workspace_id,source_id,true))',t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['embedding_profiles','index_generations','workspace_search_state'] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE app.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON app.%I TO videomind_app',t);
    EXECUTE format('CREATE POLICY workspace_read ON app.%I FOR SELECT TO videomind_app USING(app.member_of(workspace_id))',t);
    EXECUTE format('CREATE POLICY workspace_write ON app.%I FOR ALL TO videomind_app USING(app.admin_of(workspace_id)) WITH CHECK(app.admin_of(workspace_id))',t);
  END LOOP;
END$$;
CREATE FUNCTION app.scope_unchanged() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
  IF (to_jsonb(NEW)->'workspace_id') IS DISTINCT FROM (to_jsonb(OLD)->'workspace_id')
     OR (to_jsonb(NEW)->'source_id') IS DISTINCT FROM (to_jsonb(OLD)->'source_id')
     OR (to_jsonb(NEW)->'id') IS DISTINCT FROM (to_jsonb(OLD)->'id') THEN
    RAISE EXCEPTION 'resource scope is immutable';
  END IF;
  RETURN NEW;
END$$;
REVOKE ALL ON FUNCTION app.scope_unchanged() FROM PUBLIC;
DO $$DECLARE t text; BEGIN
  FOR t IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='app' LOOP
    EXECUTE format('CREATE TRIGGER scope_unchanged BEFORE UPDATE ON app.%I FOR EACH ROW EXECUTE FUNCTION app.scope_unchanged()',t);
  END LOOP;
END$$;
-- Append-only facts: versions and evidence identities cannot be rewritten.
REVOKE UPDATE ON app.objects,app.asset_revisions,app.embedding_profiles,app.evidence_anchors,app.segments,app.segment_evidence,app.segment_relations,app.embeddings,app.citation_records,app.audit_events FROM videomind_app;
REVOKE DELETE ON app.audit_events FROM videomind_app;
