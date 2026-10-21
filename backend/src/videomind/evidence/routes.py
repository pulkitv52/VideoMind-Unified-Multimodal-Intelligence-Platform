"""Authorized immutable document evidence. IDs never confer access."""

from uuid import UUID
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from videomind.identity.service import actor
from videomind.infrastructure.database import transaction
from videomind.ingestion.service import source_scope

router = APIRouter()


def document(conn, w, s, r, segment_set_id=None):
    source_scope(conn, w, s)
    v = {"w": w, "s": s, "r": r, "selected_set": segment_set_id}
    original = (
        conn.execute(
            text(
                "SELECT r.id,r.asset_id,r.original_object_id,a.title FROM app.asset_revisions r JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r AND NOT a.deleted"
            ),
            v,
        )
        .mappings()
        .first()
    )
    if not original:
        raise HTTPException(404, "Evidence unavailable")
    output = (
        conn.execute(
            text(
                "SELECT id,manifest FROM app.segment_sets WHERE workspace_id=:w AND source_id=:s AND revision_id=:r AND status='ready' AND manifest->>'kind' IS DISTINCT FROM 'media' AND (CAST(:selected_set AS uuid) IS NULL OR id=CAST(:selected_set AS uuid)) ORDER BY created_at DESC,id DESC LIMIT 1"
            ),
            v,
        )
        .mappings()
        .first()
    )
    if not output:
        raise HTTPException(404, "Document extraction is not ready")
    return dict(v, set=output["id"]), original, output


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/document")
def descriptor(
    w: UUID,
    s: UUID,
    r: UUID,
    request: Request,
    segment_set_id: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        v, original, output = document(conn, w, s, r, segment_set_id)
        pages = [
            dict(p)
            for p in conn.execute(
                text(
                    "SELECT page,width,height,image_object_id,rendering_object_id,manifest->'ocr' AS ocr FROM app.document_pages WHERE workspace_id=:w AND source_id=:s AND segment_set_id=:set ORDER BY page"
                ),
                v,
            ).mappings()
        ]
        return {
            "revision_id": r,
            "asset_id": original["asset_id"],
            "title": original["title"],
            "segment_set_id": output["id"],
            "manifest": output["manifest"],
            "pages": pages,
        }


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/document/pages/{page}")
def page(
    w: UUID,
    s: UUID,
    r: UUID,
    page: int,
    request: Request,
    segment_set_id: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        v, original, output = document(conn, w, s, r, segment_set_id)
        v["page"] = page
        item = (
            conn.execute(
                text(
                    "SELECT page,text_object_id,image_object_id,width,height,manifest FROM app.document_pages WHERE workspace_id=:w AND source_id=:s AND segment_set_id=:set AND page=:page"
                ),
                v,
            )
            .mappings()
            .first()
        )
        if not item:
            raise HTTPException(404, "Evidence unavailable")
        # Each branch uses source RLS; complete segment sets only.
        segments = [
            dict(row)
            for row in conn.execute(
                text(
                    """SELECT g.id,g.representation,g.ordinal,g.text_content,g.quality,c.id AS citation_id,e.locator_kind,e.page,e.start_char,e.end_char,e.transform
        FROM app.segments g JOIN app.segment_evidence se ON (se.workspace_id,se.source_id,se.segment_id)=(g.workspace_id,g.source_id,g.id)
        JOIN app.evidence_anchors e ON (e.workspace_id,e.source_id,e.id)=(se.workspace_id,se.source_id,se.anchor_id)
        JOIN app.citation_records c ON (c.workspace_id,c.source_id,c.segment_id,c.anchor_id)=(se.workspace_id,se.source_id,se.segment_id,se.anchor_id)
        WHERE g.workspace_id=:w AND g.source_id=:s AND g.segment_set_id=:set AND (e.page=:page OR (e.locator_kind='text' AND :page=1)) ORDER BY g.ordinal LIMIT 5000"""
                ),
                v,
            ).mappings()
        ]
        return dict(item, segments=segments, revision_id=r)


@router.get("/workspaces/{w}/sources/{s}/citations/{citation}")
def citation(
    w: UUID, s: UUID, citation: UUID, request: Request, principal: UUID = Depends(actor)
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s)
        row = (
            conn.execute(
                text(
                    "SELECT c.id,c.segment_id,e.id AS anchor_id,e.revision_id,e.original_object_id,e.locator_kind,e.page,e.start_char,e.end_char,e.start_ms,e.end_ms,e.track,e.transform,g.text_content,g.representation,g.segment_set_id FROM app.citation_records c JOIN app.evidence_anchors e ON (e.workspace_id,e.source_id,e.id)=(c.workspace_id,c.source_id,c.anchor_id) JOIN app.segments g ON (g.workspace_id,g.source_id,g.id)=(c.workspace_id,c.source_id,c.segment_id) WHERE c.workspace_id=:w AND c.source_id=:s AND c.id=:citation"
                ),
                {"w": w, "s": s, "citation": citation},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Evidence unavailable")
        v = {"w": w, "s": s, "r": row["revision_id"], "set": row["segment_set_id"]}
        original = (
            conn.execute(
                text(
                    "SELECT a.id AS asset_id,a.title FROM app.asset_revisions r JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id) JOIN app.segment_sets ss ON (ss.workspace_id,ss.source_id,ss.revision_id)=(r.workspace_id,r.source_id,r.id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r AND ss.id=:set AND ss.status='ready' AND NOT a.deleted"
                ),
                v,
            )
            .mappings()
            .first()
        )
        if not original:
            raise HTTPException(404, "Evidence unavailable")
        return dict(
            row,
            title=original["title"],
            asset_id=original["asset_id"],
            offset_unit="Unicode code point",
        )


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/document/objects/{oid}")
def artifact(
    w: UUID,
    s: UUID,
    r: UUID,
    oid: UUID,
    request: Request,
    segment_set_id: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        v, original, output = document(conn, w, s, r, segment_set_id)
        v["oid"] = oid
        row = (
            conn.execute(
                text(
                    """SELECT o.object_key,o.size_bytes,o.mime_type FROM app.objects o
        WHERE o.workspace_id=:w AND o.source_id=:s AND o.id=:oid AND (
          EXISTS(SELECT FROM app.document_pages p WHERE p.workspace_id=:w AND p.source_id=:s AND p.segment_set_id=:set AND :oid IN (p.text_object_id,p.image_object_id,p.rendering_object_id))
          OR EXISTS(SELECT FROM app.segments g WHERE g.workspace_id=:w AND g.source_id=:s AND g.segment_set_id=:set AND g.derived_object_id=:oid)
          OR CAST(:oid AS text)=(SELECT manifest->>'structure_object_id' FROM app.segment_sets WHERE workspace_id=:w AND source_id=:s AND id=:set))"""
                ),
                v,
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Evidence unavailable")
    return stream_object(
        request, row, "document-artifact", inline=row["mime_type"] == "image/png"
    )


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/original")
def original_revision(
    w: UUID, s: UUID, r: UUID, request: Request, principal: UUID = Depends(actor)
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s)
        row = (
            conn.execute(
                text(
                    "SELECT o.object_key,o.size_bytes,o.mime_type,a.title FROM app.asset_revisions r JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id) JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r AND NOT a.deleted"
                ),
                {"w": w, "s": s, "r": r},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Evidence unavailable")
    return stream_object(request, row, row["title"])


def stream_object(request, row, name, inline=False):
    response = request.app.state.objects.get_object(
        request.app.state.settings.minio_bucket, row["object_key"]
    )

    def stream():
        try:
            yield from response.stream(1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(
        stream(),
        media_type=row["mime_type"] if inline else "application/octet-stream",
        headers={
            "Content-Length": str(row["size_bytes"]),
            "Content-Disposition": ("inline" if inline else "attachment")
            + "; filename*=UTF-8''"
            + quote(name, safe=""),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
