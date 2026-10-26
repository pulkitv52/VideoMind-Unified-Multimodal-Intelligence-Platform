"""Workspace administrative analytics; current files are counted once."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from videomind.identity.access import workspace_capabilities
from videomind.identity.service import actor
from videomind.infrastructure.database import transaction

router = APIRouter()

FILES = """
WITH files AS (
 SELECT a.id,a.title,a.modality,a.source_id,a.latest_revision_id AS revision_id,s.name AS collection,
 u.uploaded_by,p.username AS uploader,coalesce(u.received_at,r.created_at) AS received_at,
 EXISTS(SELECT FROM app.segment_sets ss WHERE (ss.workspace_id,ss.source_id,ss.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id)
 AND ss.status='ready' AND (ss.manifest->>'partial'='true' OR (ss.manifest->'warnings' IS NOT NULL AND ss.manifest->'warnings'<>'[]'::jsonb))) AS has_warnings,
 CASE WHEN EXISTS(SELECT FROM app.generation_assets ga JOIN app.workspace_search_state ws
 ON (ws.workspace_id,ws.active_generation_id)=(ga.workspace_id,ga.generation_id)
 WHERE (ga.workspace_id,ga.source_id,ga.asset_id,ga.revision_id)=(a.workspace_id,a.source_id,a.id,a.latest_revision_id)) THEN 'ready'
 WHEN EXISTS(SELECT FROM app.ingestion_jobs j WHERE (j.workspace_id,j.source_id,j.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id) AND j.status='failed')
 OR EXISTS(SELECT FROM app.embedding_jobs j JOIN app.index_generations g ON (g.workspace_id,g.id)=(j.workspace_id,j.generation_id)
 WHERE (j.workspace_id,j.source_id,j.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id) AND j.status='failed' AND g.status IN ('active','building')) THEN 'failed'
 WHEN EXISTS(SELECT FROM app.segment_sets ss WHERE (ss.workspace_id,ss.source_id,ss.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id) AND ss.status='ready') THEN 'indexing'
 ELSE 'preparing' END AS status
 FROM app.assets a JOIN app.sources s ON (s.workspace_id,s.id)=(a.workspace_id,a.source_id)
 JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)=(a.workspace_id,a.source_id,a.latest_revision_id)
 LEFT JOIN app.upload_attribution u ON (u.workspace_id,u.source_id,u.revision_id)=(r.workspace_id,r.source_id,r.id)
 LEFT JOIN auth.principals p ON p.id=u.uploaded_by
 WHERE a.workspace_id=:w AND NOT a.deleted AND NOT s.deleted
)
"""


@router.get("/workspaces/{w}/analytics")
def analytics(
    w: UUID,
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    member: UUID | None = None,
    status: str | None = Query(
        default=None, pattern="^(ready|indexing|preparing|failed)$"
    ),
    modality: str | None = Query(
        default=None, pattern="^(document|image|video|audio)$"
    ),
    after: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        capabilities = workspace_capabilities(conn, w)
        if not capabilities.can_view_analytics:
            raise HTTPException(403, "Workspace administrator required")
        conn.execute(text("SET LOCAL statement_timeout='8s'"))
        since = datetime.now(timezone.utc) - timedelta(days=days)
        params = {
            "w": w,
            "since": since,
            "member": member,
            "status": status,
            "modality": modality,
            "after": after,
        }
        summary = dict(
            conn.execute(
                text(FILES + """SELECT count(*) AS files,
          count(*) FILTER(WHERE status='ready') AS ready,
          count(*) FILTER(WHERE status IN ('preparing','indexing')) AS preparing,
          count(*) FILTER(WHERE status='failed') AS failed,
          count(*) FILTER(WHERE received_at>=:since) AS recent_uploads FROM files"""),
                params,
            )
            .mappings()
            .one()
        )
        # Membership RLS exposes only the caller. The bounded privileged directory
        # supplies administrative identity rows; it never exposes credentials.
        directory = [
            dict(row)
            for row in conn.execute(
                text("SELECT * FROM app.workspace_people(:w,NULL,101)"), params
            ).mappings()
        ]
        # Total membership metrics come from the dedicated admin-checked helper.
        members = dict(
            conn.execute(text("SELECT * FROM app.member_metrics(:w,:since)"), params)
            .mappings()
            .one()
        )
        summary.update(members)
        filters = """ WHERE received_at>=:since
          AND (CAST(:member AS uuid) IS NULL OR uploaded_by=CAST(:member AS uuid))
          AND (CAST(:status AS text) IS NULL OR status=:status)
          AND (CAST(:modality AS text) IS NULL OR modality=:modality)"""
        page = [
            dict(row)
            for row in conn.execute(
                text(
                    FILES
                    + "SELECT * FROM files"
                    + filters
                    + " AND (CAST(:after AS uuid) IS NULL OR (received_at,id)<(SELECT received_at,id FROM files WHERE id=CAST(:after AS uuid))) ORDER BY received_at DESC,id DESC LIMIT 21"
                ),
                params,
            ).mappings()
        ]
        trend = [
            dict(row)
            for row in conn.execute(
                text(
                    FILES
                    + "SELECT (received_at AT TIME ZONE 'UTC')::date AS day,count(*) AS uploads FROM files"
                    + filters
                    + " GROUP BY 1 ORDER BY 1"
                ),
                params,
            ).mappings()
        ]
        per_member = [
            dict(row)
            for row in conn.execute(
                text(
                    FILES
                    + "SELECT uploaded_by,count(*) AS files,count(*) FILTER(WHERE status='ready') AS ready FROM files GROUP BY uploaded_by"
                ),
                params,
            ).mappings()
        ]
        counts = {str(row["uploaded_by"]): row for row in per_member}
        for person in directory:
            counted = counts.get(str(person["principal_id"]), {})
            person.update(files=counted.get("files", 0), ready=counted.get("ready", 0))
        directory.sort(
            key=lambda item: (
                item["joined_at"] is not None,
                item["joined_at"] or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        current = workspace_capabilities(conn, w)
        if not current.can_view_analytics:
            raise HTTPException(403, "Workspace administrator required")
        return {
            "can_manage_roles": current.can_manage_roles,
            "summary": summary,
            "recent_members": directory[:10],
            "people": directory,
            "uploads": page[:20],
            "next_cursor": str(page[19]["id"]) if len(page) > 20 else None,
            "trend": trend,
            "days": days,
            "directory_limited": len(directory) > 100,
        }
