from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from videomind.identity.service import actor
from videomind.infrastructure.database import transaction

router = APIRouter()


@router.get("/workspaces/{workspace_id}/sources")
def sources(workspace_id: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        if not conn.execute(
            text("SELECT id FROM app.workspaces WHERE id=:id"), {"id": workspace_id}
        ).first():
            raise HTTPException(404, "Workspace unavailable")
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT id,name,connector_kind,status,app.source_access(workspace_id,id,true) AS can_ingest,app.source_admin(workspace_id,id) AS can_admin FROM app.sources WHERE workspace_id=:id AND NOT deleted ORDER BY name,id"
                ),
                {"id": workspace_id},
            ).mappings()
        ]


@router.get("/workspaces/{workspace_id}/sources/{source_id}")
def source(
    workspace_id: UUID,
    source_id: UUID,
    request: Request,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id,name,connector_kind,status,app.source_access(workspace_id,id,true) AS can_ingest,app.source_admin(workspace_id,id) AS can_admin FROM app.sources WHERE workspace_id=:workspace AND id=:source AND NOT deleted"
                ),
                {"workspace": workspace_id, "source": source_id},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Source unavailable")
        return dict(row)
