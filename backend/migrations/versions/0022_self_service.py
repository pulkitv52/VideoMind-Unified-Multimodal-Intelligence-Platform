"""Bounded member onboarding, upload provenance and administrative activity."""

from alembic import op

revision = "0022_self_service"
down_revision = "0021_workspace_people"


def upgrade():
    op.get_bind().connection.driver_connection.execute(SQL, prepare=False)


def downgrade():
    raise RuntimeError("Preserve account and upload provenance")


SQL = r"""
DO $$ BEGIN
 IF EXISTS(SELECT lower(username) FROM auth.principals GROUP BY lower(username) HAVING count(*)>1) THEN
  RAISE EXCEPTION 'Case-insensitive account names need operator reconciliation';
 END IF;
END $$;
CREATE UNIQUE INDEX principals_username_fold ON auth.principals(lower(username));
ALTER TABLE app.memberships ADD COLUMN joined_at timestamptz;
ALTER TABLE app.memberships ALTER COLUMN joined_at SET DEFAULT now();
CREATE SEQUENCE auth.membership_versions;
ALTER TABLE app.memberships ADD COLUMN version bigint NOT NULL DEFAULT nextval('auth.membership_versions');
CREATE FUNCTION app.membership_version_changed() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN NEW.version:=nextval('auth.membership_versions'); RETURN NEW; END $$;
REVOKE ALL ON FUNCTION app.membership_version_changed() FROM PUBLIC,videomind_app;
CREATE TRIGGER membership_version_changed BEFORE UPDATE ON app.memberships FOR EACH ROW EXECUTE FUNCTION app.membership_version_changed();
ALTER TABLE app.sources ADD COLUMN created_by uuid REFERENCES auth.principals ON DELETE SET NULL;
CREATE INDEX source_creator ON app.sources(workspace_id,created_by) WHERE NOT deleted;

CREATE TABLE auth.signup_policies(
 workspace_id uuid PRIMARY KEY REFERENCES app.workspaces ON DELETE CASCADE,
 enabled boolean NOT NULL DEFAULT false,
 member_limit integer NOT NULL DEFAULT 100 CHECK(member_limit BETWEEN 1 AND 1000),
 initial_generation_id uuid,
 FOREIGN KEY(workspace_id,initial_generation_id) REFERENCES app.index_generations(workspace_id,id) DEFERRABLE INITIALLY DEFERRED
);
REVOKE ALL ON auth.signup_policies FROM PUBLIC,videomind_app;
REVOKE ALL ON SEQUENCE auth.membership_versions FROM PUBLIC,videomind_app;

CREATE FUNCTION app.create_upload_collection(w uuid, label text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE s uuid:=gen_random_uuid(); p uuid:=app.actor_id();
BEGIN
 PERFORM 1 FROM app.workspaces WHERE id=w FOR UPDATE;
 IF NOT app.member_of(w) OR NOT EXISTS(SELECT FROM auth.principals WHERE id=p AND NOT disabled) THEN
  RAISE EXCEPTION 'Workspace unavailable' USING ERRCODE='42501'; END IF;
 IF length(btrim(label)) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'Invalid collection name' USING ERRCODE='22023'; END IF;
 IF (SELECT count(*) FROM app.sources WHERE workspace_id=w AND created_by=p AND NOT deleted)>=20 THEN
  RAISE EXCEPTION 'Collection limit reached' USING ERRCODE='54000'; END IF;
 INSERT INTO app.sources(workspace_id,id,name,connector_kind,status,created_by) VALUES(w,s,btrim(label),'upload','connected',p);
 INSERT INTO app.source_grants(workspace_id,source_id,principal_id,permission) VALUES(w,s,p,'admin');
 RETURN s;
END $$;
REVOKE ALL ON FUNCTION app.create_upload_collection(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.create_upload_collection(uuid,text) TO videomind_app;

CREATE FUNCTION auth.signup_policy(w uuid) RETURNS TABLE(enabled boolean,member_limit integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT s.enabled,s.member_limit FROM auth.signup_policies s JOIN app.workspaces ws ON ws.id=s.workspace_id
 WHERE s.workspace_id=w AND EXISTS(SELECT FROM app.memberships m JOIN auth.principals p ON p.id=m.principal_id
 WHERE m.workspace_id=w AND m.role='owner' AND NOT p.disabled)
$$;
CREATE FUNCTION app.set_signup_policy(w uuid,allow_signup boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT app.owner_of(w) THEN RAISE EXCEPTION 'Workspace owner required' USING ERRCODE='42501'; END IF;
 INSERT INTO auth.signup_policies(workspace_id,enabled) VALUES(w,allow_signup)
 ON CONFLICT(workspace_id) DO UPDATE SET enabled=EXCLUDED.enabled;
END $$;
CREATE FUNCTION auth.register_member(w uuid,label text,hashed text) RETURNS TABLE(principal_id uuid,source_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE p uuid:=gen_random_uuid(); s uuid:=gen_random_uuid(); cap integer;
BEGIN
 SELECT member_limit INTO cap FROM auth.signup_policies WHERE workspace_id=w AND enabled FOR UPDATE;
 IF cap IS NULL THEN RAISE EXCEPTION 'Registration unavailable' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM app.workspaces WHERE id=w FOR UPDATE;
 IF NOT EXISTS(SELECT FROM app.memberships m JOIN auth.principals actor ON actor.id=m.principal_id
 WHERE m.workspace_id=w AND m.role='owner' AND NOT actor.disabled) THEN
  RAISE EXCEPTION 'Registration unavailable' USING ERRCODE='42501'; END IF;
 IF (SELECT count(*) FROM app.memberships WHERE workspace_id=w)>=cap THEN RAISE EXCEPTION 'Registration capacity reached' USING ERRCODE='54000'; END IF;
 IF label !~ '^[a-z0-9_.-]{3,64}$' OR hashed NOT LIKE 'scrypt-v1$%' OR length(hashed) NOT BETWEEN 100 AND 256 THEN
  RAISE EXCEPTION 'Invalid account' USING ERRCODE='22023'; END IF;
 INSERT INTO auth.principals(id,username,password_hash) VALUES(p,label,hashed);
 INSERT INTO app.memberships(workspace_id,principal_id,role) VALUES(w,p,'member');
 INSERT INTO app.sources(workspace_id,id,name,connector_kind,status,created_by) VALUES(w,s,label||' files','upload','connected',p);
 INSERT INTO app.source_grants(workspace_id,source_id,principal_id,permission) VALUES(w,s,p,'admin');
 RETURN QUERY SELECT p,s;
END $$;
REVOKE ALL ON FUNCTION auth.signup_policy(uuid),app.set_signup_policy(uuid,boolean),auth.register_member(uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth.signup_policy(uuid),app.set_signup_policy(uuid,boolean),auth.register_member(uuid,text,text) TO videomind_app;

CREATE TABLE app.upload_attribution(
 workspace_id uuid NOT NULL, source_id uuid NOT NULL, revision_id uuid NOT NULL,
 uploaded_by uuid REFERENCES auth.principals ON DELETE SET NULL,
 received_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,source_id,revision_id),
 FOREIGN KEY(workspace_id,source_id,revision_id) REFERENCES app.asset_revisions(workspace_id,source_id,id) ON DELETE CASCADE
);
INSERT INTO app.upload_attribution(workspace_id,source_id,revision_id,uploaded_by,received_at)
 SELECT DISTINCT ON (j.workspace_id,j.source_id,j.revision_id) j.workspace_id,j.source_id,j.revision_id,j.requested_by,j.created_at
 FROM app.ingestion_jobs j WHERE j.kind='validate' AND j.revision_id IS NOT NULL ORDER BY j.workspace_id,j.source_id,j.revision_id,j.created_at,j.id;
ALTER TABLE app.upload_attribution ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.upload_attribution FORCE ROW LEVEL SECURITY;
CREATE POLICY upload_read ON app.upload_attribution FOR SELECT TO videomind_app USING(app.source_access(workspace_id,source_id));
CREATE POLICY upload_insert ON app.upload_attribution FOR INSERT TO videomind_app WITH CHECK(app.source_access(workspace_id,source_id,true) AND uploaded_by=app.actor_id());
GRANT SELECT,INSERT ON app.upload_attribution TO videomind_app;
CREATE INDEX upload_activity_date ON app.upload_attribution(workspace_id,received_at DESC,revision_id);

CREATE TABLE app.membership_audit(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 workspace_id uuid NOT NULL REFERENCES app.workspaces ON DELETE CASCADE,
 actor_id uuid REFERENCES auth.principals ON DELETE SET NULL,
 target_id uuid REFERENCES auth.principals ON DELETE SET NULL,
 action text NOT NULL, old_role text, new_role text, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE app.membership_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.membership_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY membership_audit_read ON app.membership_audit FOR SELECT TO videomind_app USING(app.admin_of(workspace_id));
GRANT SELECT ON app.membership_audit TO videomind_app;
CREATE FUNCTION app.change_member(w uuid,target uuid,expected bigint,new_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE old_role text; current_version bigint;
BEGIN
 PERFORM 1 FROM app.workspaces WHERE id=w FOR UPDATE;
 IF NOT app.admin_of(w) OR NOT EXISTS(SELECT FROM auth.principals WHERE id=app.actor_id() AND NOT disabled) THEN
  RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
 SELECT role,version INTO old_role,current_version FROM app.memberships WHERE workspace_id=w AND principal_id=target;
 IF old_role IS NULL THEN RAISE EXCEPTION 'Member unavailable' USING ERRCODE='P0002'; END IF;
 IF old_role='owner' OR target=app.actor_id() OR (NOT app.owner_of(w) AND (old_role<>'member' OR coalesce(new_role,'member')<>'member')) THEN
  RAISE EXCEPTION 'Role change not allowed' USING ERRCODE='42501'; END IF;
 IF current_version<>expected THEN RAISE EXCEPTION 'Membership changed; refresh and retry' USING ERRCODE='40001'; END IF;
 IF new_role IS NOT NULL AND new_role NOT IN ('admin','member') THEN RAISE EXCEPTION 'Invalid role' USING ERRCODE='22023'; END IF;
 IF new_role IS NULL THEN
  DELETE FROM app.source_grants WHERE workspace_id=w AND principal_id=target;
  DELETE FROM app.memberships WHERE workspace_id=w AND principal_id=target;
 ELSE UPDATE app.memberships SET role=new_role WHERE workspace_id=w AND principal_id=target; END IF;
 INSERT INTO app.membership_audit(workspace_id,actor_id,target_id,action,old_role,new_role)
 VALUES(w,app.actor_id(),target,CASE WHEN new_role IS NULL THEN 'remove' ELSE 'role_change' END,old_role,new_role);
END $$;
REVOKE ALL ON FUNCTION app.change_member(uuid,uuid,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.change_member(uuid,uuid,bigint,text) TO videomind_app;
DROP FUNCTION app.workspace_people(uuid,uuid,integer);
CREATE FUNCTION app.workspace_people(w uuid,after_id uuid,page_size integer)
RETURNS TABLE(principal_id uuid,username text,role text,disabled boolean,joined_at timestamptz,version bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT p.id,p.username,m.role,p.disabled,m.joined_at,m.version FROM app.memberships m JOIN auth.principals p ON p.id=m.principal_id
 WHERE m.workspace_id=w AND app.admin_of(w) AND EXISTS(SELECT FROM auth.principals actor WHERE actor.id=app.actor_id() AND NOT actor.disabled)
 AND (after_id IS NULL OR p.id>after_id) ORDER BY p.id LIMIT greatest(0,least(coalesce(page_size,0),101))
$$;
REVOKE ALL ON FUNCTION app.workspace_people(uuid,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.workspace_people(uuid,uuid,integer) TO videomind_app;

CREATE FUNCTION app.member_metrics(w uuid,since_date timestamptz) RETURNS TABLE(members bigint,recent_members bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT count(*) FILTER(WHERE NOT p.disabled),count(*) FILTER(WHERE NOT p.disabled AND m.joined_at>=since_date)
 FROM app.memberships m JOIN auth.principals p ON p.id=m.principal_id
 WHERE m.workspace_id=w AND app.admin_of(w)
 AND EXISTS(SELECT FROM auth.principals actor WHERE actor.id=app.actor_id() AND NOT actor.disabled)
$$;
REVOKE ALL ON FUNCTION app.member_metrics(uuid,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.member_metrics(uuid,timestamptz) TO videomind_app;

CREATE FUNCTION app.initial_index_work() RETURNS TABLE(workspace_id uuid,owner_id uuid,generation_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT s.workspace_id,m.principal_id,s.initial_generation_id FROM auth.signup_policies s
 JOIN app.memberships m ON m.workspace_id=s.workspace_id AND m.role='owner'
 JOIN auth.principals p ON p.id=m.principal_id AND NOT p.disabled
 LEFT JOIN app.workspace_search_state ws ON ws.workspace_id=s.workspace_id
 WHERE ws.active_generation_id IS NULL
 AND (s.initial_generation_id IS NOT NULL OR NOT EXISTS(SELECT FROM app.index_generations g WHERE g.workspace_id=s.workspace_id))
 AND EXISTS(SELECT FROM app.assets a JOIN app.sources src ON (src.workspace_id,src.id)=(a.workspace_id,a.source_id)
 JOIN app.segment_sets ss ON (ss.workspace_id,ss.source_id,ss.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id)
 WHERE a.workspace_id=s.workspace_id AND NOT a.deleted AND NOT src.deleted AND ss.status='ready')
 ORDER BY s.workspace_id LIMIT 16
$$;
CREATE FUNCTION app.remember_initial_index(w uuid,g uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT app.owner_of(w) OR NOT EXISTS(SELECT FROM app.index_generations WHERE workspace_id=w AND id=g AND requested_by=app.actor_id() AND status='building') THEN
  RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
 UPDATE auth.signup_policies SET initial_generation_id=g WHERE workspace_id=w AND initial_generation_id IS NULL;
END $$;
REVOKE ALL ON FUNCTION app.initial_index_work(),app.remember_initial_index(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.initial_index_work(),app.remember_initial_index(uuid,uuid) TO videomind_app;
"""
