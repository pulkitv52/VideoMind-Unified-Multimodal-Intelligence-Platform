"""Bounded metadata-only previews; byte endpoints independently reauthorize."""

import json

from sqlalchemy import text

from videomind.evidence.contracts import Preview


def resolve_batch(conn, workspace, results):
    if not results:
        return {}
    if len(results) > 30:
        raise ValueError("preview result budget exceeded")
    requested = [
        {"segment_id": str(hit.segment_id), "citation_id": str(hit.citations[0].id)}
        for hit in results
    ]
    rows = conn.execute(
        text("""
        WITH requested AS (
          SELECT * FROM jsonb_to_recordset(CAST(:requested AS jsonb))
          AS req(segment_id uuid, citation_id uuid)
        ), preview_candidates AS (
          SELECT g.id AS segment_id, g.segment_set_id, a.modality,
            p.image_object_id,
            CASE WHEN e.locator_kind='temporal'
              THEN e.transform->'frames'->0->>'object_id' END AS frame_id
          FROM requested req
          JOIN app.segments g ON g.id=req.segment_id AND g.workspace_id=:w
          JOIN app.citation_records cr ON (cr.workspace_id,cr.source_id,cr.segment_id,cr.id)
            =(g.workspace_id,g.source_id,g.id,req.citation_id)
          JOIN app.evidence_anchors e ON (e.workspace_id,e.source_id,e.id,e.revision_id)
            =(cr.workspace_id,cr.source_id,cr.anchor_id,g.revision_id)
          JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)
            =(g.workspace_id,g.source_id,g.revision_id)
          JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)
            =(r.workspace_id,r.source_id,r.asset_id) AND NOT a.deleted
          JOIN app.segment_sets ss ON (ss.workspace_id,ss.source_id,ss.id,ss.revision_id)
            =(g.workspace_id,g.source_id,g.segment_set_id,g.revision_id) AND ss.status='ready'
          LEFT JOIN app.document_pages p ON (p.workspace_id,p.source_id,p.segment_set_id,p.page)
            =(g.workspace_id,g.source_id,g.segment_set_id,e.page)
          WHERE EXISTS(SELECT FROM app.objects o
            WHERE (o.workspace_id,o.source_id)=(g.workspace_id,g.source_id)
              AND o.mime_type IN ('image/png','image/jpeg') AND o.size_bytes<=4194304
              AND (o.id=p.image_object_id OR (
                o.id::text=e.transform->'frames'->0->>'object_id'
                AND EXISTS(SELECT FROM app.media_artifacts ma
                  WHERE (ma.workspace_id,ma.source_id,ma.segment_set_id,ma.object_id)
                    =(g.workspace_id,g.source_id,g.segment_set_id,o.id)))))
        ) SELECT * FROM preview_candidates
        """),
        {"w": workspace, "requested": json.dumps(requested)},
    ).mappings()
    return {
        row["segment_id"]: Preview(
            kind=(
                "frame"
                if row["frame_id"]
                else "image" if row["modality"] == "image" else "page"
            ),
            object_id=row["frame_id"] or row["image_object_id"],
            segment_set_id=row["segment_set_id"],
            route="media" if row["frame_id"] else "document",
        )
        for row in rows
    }
