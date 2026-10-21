"""Profile-pinned exact/ANN baseline, with current ACLs on every candidate."""

import json
from uuid import UUID
from sqlalchemy import text
from videomind.embeddings.contracts import validate_vector


def neighbors(conn, w, pinned, vector, limit=10, ann=False, source_id=None):
    validate_vector(vector)
    pid = str(UUID(str(pinned["profile_id"])))
    # A canonical UUID proves the partial-index predicate. OFFSET 0 keeps the
    # membership predicate correlated, so the ordered vector scan remains usable.
    sql = f"""WITH candidates AS MATERIALIZED (
      SELECT e.id,e.source_id,e.segment_id,e.embedding <=> CAST(:v AS vector) AS distance
      FROM app.embeddings e
      WHERE e.workspace_id=:w AND e.profile_id='{pid}'::uuid
      AND (CAST(:source AS uuid) IS NULL OR e.source_id=CAST(:source AS uuid))
      AND EXISTS(
        SELECT 1 FROM app.segments s
        JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)=(s.workspace_id,s.source_id,s.revision_id)
        JOIN app.generation_assets ga ON (ga.workspace_id,ga.source_id,ga.asset_id,ga.revision_id,ga.segment_set_id)=(r.workspace_id,r.source_id,r.asset_id,r.id,s.segment_set_id)
        JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id)
        WHERE (s.workspace_id,s.source_id,s.id)=(e.workspace_id,e.source_id,e.segment_id)
        AND ga.generation_id=:g AND NOT a.deleted OFFSET 0)
      ORDER BY e.embedding <=> CAST(:v AS vector) LIMIT :budget)
    SELECT c.id AS embedding_id,c.segment_id,c.source_id,s.representation,cite.id AS citation_id,1-c.distance AS score
    FROM candidates c JOIN app.segments s ON (s.workspace_id,s.source_id,s.id)=(:w,c.source_id,c.segment_id)
    JOIN LATERAL(SELECT id FROM app.citation_records cr WHERE (cr.workspace_id,cr.source_id,cr.segment_id)=(:w,c.source_id,c.segment_id) ORDER BY id LIMIT 1) cite ON true
    ORDER BY c.distance,c.id LIMIT :limit"""
    params = {
        "w": w,
        "g": pinned["id"],
        "v": json.dumps(vector),
        "limit": limit,
        "source": source_id,
        "budget": min(400, limit * 4),
    }
    if ann:
        conn.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
        conn.execute(text("SET LOCAL hnsw.ef_search=100"))
        conn.execute(text("SET LOCAL hnsw.max_scan_tuples=20000"))
        conn.execute(text("SET LOCAL enable_seqscan=off"))
        conn.execute(text("SET LOCAL enable_sort=off"))
        conn.execute(text("SET LOCAL jit=off"))
    else:
        conn.execute(text("SET LOCAL enable_indexscan=off"))
        conn.execute(text("SET LOCAL enable_bitmapscan=off"))
    rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    if ann and len(rows) < limit:
        conn.execute(text("SET LOCAL enable_seqscan=on"))
        return neighbors(conn, w, pinned, vector, limit, False, source_id)
    return rows
