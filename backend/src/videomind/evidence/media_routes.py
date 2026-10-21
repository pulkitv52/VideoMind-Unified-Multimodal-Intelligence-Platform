"""Original-time media evidence and per-request authorized HTTP byte ranges."""

import re
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from videomind.identity.service import actor
from videomind.infrastructure.database import transaction
from videomind.ingestion.service import source_scope

router = APIRouter()


def presentation(conn, w, s, r, segment_set_id=None):
    source_scope(conn, w, s)
    v = {"w": w, "s": s, "r": r, "selected": segment_set_id}
    original = (
        conn.execute(
            text(
                "SELECT r.asset_id,a.title FROM app.asset_revisions r JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r AND NOT a.deleted"
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
                "SELECT p.* FROM app.media_presentations p JOIN app.segment_sets ss ON (ss.workspace_id,ss.source_id,ss.id)=(p.workspace_id,p.source_id,p.segment_set_id) WHERE p.workspace_id=:w AND p.source_id=:s AND p.revision_id=:r AND ss.status='ready' AND (CAST(:selected AS uuid) IS NULL OR p.segment_set_id=CAST(:selected AS uuid)) ORDER BY ss.created_at DESC,ss.id DESC LIMIT 1"
            ),
            v,
        )
        .mappings()
        .first()
    )
    if not output:
        raise HTTPException(404, "Media processing is not ready")
    return dict(v, set=output["segment_set_id"]), original, output


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/media")
def descriptor(
    w: UUID,
    s: UUID,
    r: UUID,
    request: Request,
    segment_set_id: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        v, original, output = presentation(conn, w, s, r, segment_set_id)
        return dict(output, asset_id=original["asset_id"], title=original["title"])


@router.get("/workspaces/{w}/sources/{s}/revisions/{r}/media/segments")
def segments(
    w: UUID,
    s: UUID,
    r: UUID,
    request: Request,
    segment_set_id: UUID | None = None,
    after: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        v, _, output = presentation(conn, w, s, r, segment_set_id)
        rows = [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT g.id,g.ordinal,g.representation,g.text_content,e.start_ms,e.end_ms,e.track,e.transform,c.id AS citation_id FROM app.segments g JOIN app.segment_evidence se ON (se.workspace_id,se.source_id,se.segment_id)=(g.workspace_id,g.source_id,g.id) JOIN app.evidence_anchors e ON (e.workspace_id,e.source_id,e.id)=(se.workspace_id,se.source_id,se.anchor_id) JOIN app.citation_records c ON (c.workspace_id,c.source_id,c.segment_id,c.anchor_id)=(se.workspace_id,se.source_id,se.segment_id,se.anchor_id) WHERE g.workspace_id=:w AND g.source_id=:s AND g.segment_set_id=:set AND g.ordinal>:after ORDER BY g.ordinal LIMIT :limit"
                ),
                dict(v, after=after, limit=limit + 1),
            ).mappings()
        ]
        return {
            "items": rows[:limit],
            "next": rows[limit - 1]["ordinal"] if len(rows) > limit else None,
        }


def byte_range(value, size):
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()):
        raise ValueError("range")
    a, b = match.groups()
    if not a:
        length = int(b)
        if length <= 0:
            raise ValueError("range")
        first = max(0, size - length)
        last = size - 1
    else:
        first = int(a)
        last = min(size - 1, int(b)) if b else size - 1
    if first >= size or first > last:
        raise ValueError("range")
    return first, last, True


@router.api_route(
    "/workspaces/{w}/sources/{s}/revisions/{r}/media/objects/{oid}",
    methods=["GET", "HEAD"],
)
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
        v, _, output = presentation(conn, w, s, r, segment_set_id)
        row = (
            conn.execute(
                text(
                    "SELECT o.object_key,o.size_bytes,o.mime_type,o.sha256 FROM app.media_artifacts a JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(a.workspace_id,a.source_id,a.object_id) WHERE a.workspace_id=:w AND a.source_id=:s AND a.segment_set_id=:set AND a.object_id=:oid"
                ),
                dict(v, oid=oid),
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Evidence unavailable")
    size = row["size_bytes"]
    etag = '"' + row["sha256"] + '"'
    wanted = (
        request.headers.get("range")
        if request.headers.get("if-range", etag) == etag
        else None
    )
    try:
        first, last, partial = byte_range(wanted, size)
    except (ValueError, OverflowError):
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(last - first + 1),
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    if partial:
        headers["Content-Range"] = f"bytes {first}-{last}/{size}"
    if row["mime_type"] == "application/json":
        headers["Content-Disposition"] = 'attachment; filename="mapping.json"'
    if request.method == "HEAD":
        return Response(
            status_code=206 if partial else 200,
            media_type=row["mime_type"],
            headers=headers,
        )
    response = request.app.state.objects.get_object(
        request.app.state.settings.minio_bucket,
        row["object_key"],
        offset=first,
        length=last - first + 1,
    )

    def stream():
        try:
            yield from response.stream(1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(
        stream(),
        status_code=206 if partial else 200,
        media_type=row["mime_type"],
        headers=headers,
    )
