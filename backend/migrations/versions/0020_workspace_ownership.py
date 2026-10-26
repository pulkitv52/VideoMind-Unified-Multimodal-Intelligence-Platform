"""Separate ownership authorization and preserve exactly one workspace owner."""

from alembic import op

revision = "0020_workspace_ownership"
down_revision = "0019_recovery_journal"


def upgrade():
    op.execute("""
    LOCK TABLE app.workspaces, app.memberships IN SHARE ROW EXCLUSIVE MODE;
    DO $$ BEGIN
      IF EXISTS (
        SELECT w.id FROM app.workspaces w LEFT JOIN app.memberships m
        ON m.workspace_id=w.id AND m.role='owner'
        GROUP BY w.id HAVING count(m.principal_id)<>1
      ) THEN
        RAISE EXCEPTION 'Workspace ownership needs operator reconciliation before migration';
      END IF;
    END $$;

    CREATE UNIQUE INDEX workspace_one_owner ON app.memberships(workspace_id) WHERE role='owner';

    CREATE FUNCTION app.owner_of(w uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
      SELECT EXISTS(SELECT FROM app.memberships m JOIN auth.principals p ON p.id=m.principal_id
        WHERE m.workspace_id=w AND m.principal_id=app.actor_id() AND m.role='owner' AND NOT p.disabled)
    $$;
    REVOKE ALL ON FUNCTION app.owner_of(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.owner_of(uuid) TO videomind_app;

    CREATE FUNCTION app.lock_membership_workspace() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE w uuid;
    BEGIN
      FOR w IN SELECT id FROM app.workspaces
        WHERE id IN (CASE WHEN TG_OP<>'INSERT' THEN OLD.workspace_id END,
                     CASE WHEN TG_OP<>'DELETE' THEN NEW.workspace_id END)
        ORDER BY id FOR UPDATE
      LOOP NULL; END LOOP;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;

    CREATE FUNCTION app.check_workspace_owner() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE targets uuid[]; w uuid;
    BEGIN
      IF TG_TABLE_NAME='workspaces' THEN targets:=ARRAY[NEW.id];
      ELSIF TG_OP='INSERT' THEN targets:=ARRAY[NEW.workspace_id];
      ELSIF TG_OP='DELETE' THEN targets:=ARRAY[OLD.workspace_id];
      ELSE targets:=ARRAY[OLD.workspace_id,NEW.workspace_id]; END IF;
      FOREACH w IN ARRAY targets LOOP
        IF EXISTS(SELECT FROM app.workspaces WHERE id=w) AND
           (SELECT count(*) FROM app.memberships WHERE workspace_id=w AND role='owner')<>1 THEN
          RAISE EXCEPTION 'A workspace must retain exactly one owner'
            USING ERRCODE='23514', CONSTRAINT='workspace_requires_owner';
        END IF;
      END LOOP;
      RETURN NULL;
    END $$;
    REVOKE ALL ON FUNCTION app.lock_membership_workspace(), app.check_workspace_owner()
      FROM PUBLIC, videomind_app;
    CREATE TRIGGER lock_membership_workspace BEFORE INSERT OR UPDATE OR DELETE
      ON app.memberships FOR EACH ROW EXECUTE FUNCTION app.lock_membership_workspace();
    CREATE CONSTRAINT TRIGGER membership_owner_required AFTER INSERT OR UPDATE OR DELETE
      ON app.memberships DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION app.check_workspace_owner();
    CREATE CONSTRAINT TRIGGER workspace_owner_required AFTER INSERT ON app.workspaces
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_workspace_owner();
    """)


def downgrade():
    raise RuntimeError("Preserve workspace ownership invariants")
