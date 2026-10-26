"""Server-derived access policy; capabilities never replace mutation checks."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text


class WorkspaceCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    role: Literal["owner", "admin", "member"]
    can_create_collections: bool
    can_import_folders: bool
    can_manage_index: bool
    can_view_storage: bool
    can_view_analytics: bool
    # Authorization for future management routes, not feature availability.
    can_manage_members: bool
    can_manage_roles: bool
    can_transfer_ownership: bool


class CollectionCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    source_id: UUID
    permission: Literal["workspace_admin", "read", "ingest", "admin"]
    can_read: bool = True
    can_ingest: bool
    can_manage: bool


def workspace_capabilities(conn, workspace: UUID) -> WorkspaceCapabilities:
    row = (
        conn.execute(
            text("""
        SELECT m.role,app.admin_of(w.id) AS administrator,app.owner_of(w.id) AS owner
        FROM app.workspaces w JOIN app.memberships m ON m.workspace_id=w.id
        WHERE w.id=:w AND m.principal_id=app.actor_id()
        AND EXISTS(SELECT FROM auth.principals WHERE id=app.actor_id() AND NOT disabled)
        """),
            {"w": workspace},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Workspace unavailable")
    return WorkspaceCapabilities(
        workspace_id=workspace,
        role=row["role"],
        can_create_collections=True,
        can_import_folders=row["administrator"],
        can_manage_index=row["administrator"],
        can_view_storage=row["administrator"],
        can_view_analytics=row["administrator"],
        can_manage_members=row["administrator"],
        can_manage_roles=row["owner"],
        can_transfer_ownership=row["owner"],
    )


def require_workspace_owner(conn, workspace: UUID):
    capabilities = workspace_capabilities(conn, workspace)
    if not capabilities.can_manage_roles:
        raise HTTPException(403, "Workspace owner required")


def collection_capabilities(
    conn, workspace: UUID, source: UUID
) -> CollectionCapabilities:
    workspace_capabilities(conn, workspace)
    row = (
        conn.execute(
            text("""
        SELECT CASE WHEN app.admin_of(s.workspace_id) THEN 'workspace_admin'
          ELSE g.permission END AS permission,
          app.source_access(s.workspace_id,s.id,true) AS can_ingest,
          app.source_admin(s.workspace_id,s.id) AS can_manage
        FROM app.sources s LEFT JOIN app.source_grants g
          ON (g.workspace_id,g.source_id)=(s.workspace_id,s.id) AND g.principal_id=app.actor_id()
        WHERE s.workspace_id=:w AND s.id=:s AND NOT s.deleted
          AND app.source_access(s.workspace_id,s.id)
        """),
            {"w": workspace, "s": source},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Source unavailable")
    return CollectionCapabilities(workspace_id=workspace, source_id=source, **row)
