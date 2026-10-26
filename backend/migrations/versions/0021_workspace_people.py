"""Expose a bounded administrative directory without authentication secrets."""

from alembic import op

revision = "0021_workspace_people"
down_revision = "0020_workspace_ownership"


def upgrade():
    op.execute("""
    CREATE FUNCTION app.workspace_people(w uuid, after_id uuid, page_size integer)
    RETURNS TABLE(principal_id uuid,username text,role text,disabled boolean)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
      SELECT p.id,p.username,m.role,p.disabled FROM app.memberships m
      JOIN auth.principals p ON p.id=m.principal_id
      WHERE m.workspace_id=w AND app.admin_of(w)
      AND EXISTS(SELECT FROM auth.principals actor WHERE actor.id=app.actor_id() AND NOT actor.disabled)
      AND (after_id IS NULL OR p.id>after_id)
      ORDER BY p.id LIMIT greatest(0,least(coalesce(page_size,0),101))
    $$;
    REVOKE ALL ON FUNCTION app.workspace_people(uuid,uuid,integer) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.workspace_people(uuid,uuid,integer) TO videomind_app;
    """)


def downgrade():
    raise RuntimeError("Preserve access-management migration history")
