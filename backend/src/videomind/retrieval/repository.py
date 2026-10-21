"""All candidate branches share publication, filters and runtime-role RLS."""

import json
from uuid import UUID
from sqlalchemy import text
from videomind.embeddings.contracts import validate_vector


def scope(w, pinned, filters):
    params = {"w": w, "g": pinned["id"]}
    clauses = ["s.workspace_id=:w", "ga.generation_id=:g", "NOT a.deleted"]
    for name, column, typ in (
        ("source_ids", "s.source_id", "uuid"),
        ("asset_ids", "a.id", "uuid"),
        ("modalities", "a.modality", "text"),
        ("representations", "s.representation", "text"),
        ("languages", "coalesce(s.language,'und')", "text"),
    ):
        values = getattr(filters, name)
        if values:
            params[name] = [str(v) for v in values]
            clauses.append(f"{column}=ANY(CAST(:{name} AS {typ}[]))")
    if filters.tags:
        params["tags"] = json.dumps(filters.tags)
        clauses.append("a.tags @> CAST(:tags AS jsonb)")
    if filters.date:
        column = {
            "source_created": "a.source_created_at",
            "source_modified": "a.source_modified_at",
            "ingested": "r.created_at",
        }[filters.date.field]
        for bound, op in (("after", ">="), ("before", "<")):
            value = getattr(filters.date, bound)
            if value:
                params[bound] = value
                clauses.append(f"{column}{op}:{bound}")
    if filters.media_interval:
        params.update(
            start=filters.media_interval.start_ms, end=filters.media_interval.end_ms
        )
        clauses.append(
            "EXISTS(SELECT FROM app.segment_evidence se JOIN app.evidence_anchors ea ON (ea.workspace_id,ea.source_id,ea.id)=(se.workspace_id,se.source_id,se.anchor_id) WHERE (se.workspace_id,se.source_id,se.segment_id)=(s.workspace_id,s.source_id,s.id) AND ea.locator_kind='temporal' AND ea.start_ms<:end AND ea.end_ms>:start)"
        )
    query = """SELECT s.*,a.id AS asset_id,a.title,a.modality,a.tags,src.name AS source_name,
      r.original_object_id,r.created_at AS ingested_at,ss.manifest AS extraction_manifest
      FROM app.segments s
      JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)=(s.workspace_id,s.source_id,s.revision_id)
      JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id)
      JOIN app.sources src ON (src.workspace_id,src.id)=(s.workspace_id,s.source_id)
      JOIN app.segment_sets ss ON (ss.workspace_id,ss.source_id,ss.id)=(s.workspace_id,s.source_id,s.segment_set_id)
      JOIN app.generation_assets ga ON (ga.workspace_id,ga.source_id,ga.asset_id,ga.revision_id,ga.segment_set_id)=(r.workspace_id,r.source_id,r.asset_id,r.id,s.segment_set_id)
      WHERE """ + " AND ".join(
        clauses
    )
    return query, params


def rows(conn, sql, params):
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def candidates(conn, w, pinned, body, vector, policy):
    eligible, params = scope(w, pinned, body.filters)
    params.update(
        query=body.query.strip(),
        lexical_limit=policy["lexical_candidates"],
        identifier_limit=policy["identifier_candidates"],
    )
    base = "WITH eligible AS MATERIALIZED (" + eligible + ") "
    branches = {}
    if body.mode in {"hybrid", "lexical"}:
        branches["lexical"] = rows(
            conn,
            base
            + """SELECT t.segment_id AS id,max(ts_rank_cd(t.lexemes,websearch_to_tsquery(t.configuration,:query))) AS score
          FROM app.searchable_text t JOIN eligible s ON (s.workspace_id,s.source_id,s.id)=(t.workspace_id,t.source_id,t.segment_id)
          WHERE t.lexemes @@ websearch_to_tsquery(t.configuration,:query)
          GROUP BY t.segment_id ORDER BY score DESC,t.segment_id LIMIT :lexical_limit""",
            params,
        )
        # Literal substring semantics: %, _, quotes and punctuation have no SQL pattern meaning.
        branches["identifier"] = rows(
            conn,
            base + """SELECT s.id,1.0 AS score FROM eligible s
          WHERE strpos(lower(s.title),lower(:query))>0 OR strpos(lower(coalesce(s.text_content,'')),lower(:query))>0
          ORDER BY s.id LIMIT :identifier_limit""",
            params,
        )
    if body.mode != "lexical":
        validate_vector(vector)
        params.update(
            v=json.dumps(vector),
            pid=pinned["profile_id"],
            dense_limit=policy["dense_candidates"],
        )
        dense_sql = (
            base
            + """SELECT s.id,max(1-(e.embedding <=> CAST(:v AS vector))) AS score
          FROM eligible s JOIN app.embeddings e ON (e.workspace_id,e.source_id,e.segment_id)=(s.workspace_id,s.source_id,s.id)
          WHERE e.profile_id=:pid {extra} GROUP BY s.id ORDER BY score DESC,s.id LIMIT :dense_limit"""
        )
        extra = (
            "AND s.representation IN ('text','ocr','transcript')"
            if body.mode == "derived_dense"
            else ""
        )
        if body.strategy == "per_modality":
            # Same total dense budget; empty slices do not donate their reservation.
            dense = []
            for modality, budget in zip(
                ("document", "image", "video", "audio"), (38, 38, 37, 37)
            ):
                dense.extend(
                    rows(
                        conn,
                        dense_sql.format(extra=extra + " AND s.modality=:slice"),
                        dict(params, slice=modality, dense_limit=budget),
                    )
                )
            branches["dense"] = sorted(dense, key=lambda r: (-r["score"], str(r["id"])))
        else:
            # Exact segment-max cosine is the laptop baseline; split vectors vote once.
            branches["dense"] = rows(conn, dense_sql.format(extra=extra), params)
    ids = list({r["id"] for branch in branches.values() for r in branch})
    details = hydrate(conn, eligible, params, ids)
    return branches, details


def hydrate(conn, eligible, params, ids):
    if not ids:
        return []
    return rows(
        conn,
        "WITH eligible AS MATERIALIZED (" + eligible + """ )
      SELECT s.*,cite.citations FROM eligible s
      JOIN LATERAL(SELECT jsonb_agg(x ORDER BY x.id) AS citations FROM (
        SELECT cr.id,ea.id AS anchor_id,ea.locator_kind,ea.page,ea.start_char,ea.end_char,
        ea.text_artifact_id,ea.start_ms,ea.end_ms,ea.track,ea.transform
        FROM app.citation_records cr JOIN app.evidence_anchors ea
        ON (ea.workspace_id,ea.source_id,ea.id)=(cr.workspace_id,cr.source_id,cr.anchor_id)
        WHERE (cr.workspace_id,cr.source_id,cr.segment_id)=(s.workspace_id,s.source_id,s.id)
        ORDER BY cr.id LIMIT 8) x) cite ON cite.citations IS NOT NULL
      WHERE s.id=ANY(CAST(:ids AS uuid[]))""",
        dict(params, ids=[str(i) for i in ids]),
    )


def context_batch(conn, w, pinned, filters, groups, limit=2):
    """Resolve nearest bounded neighbors with one scoped selection and hydration.

    Every request carries source and segment-set identity. The materialized
    authorized scope is shared across result groups, rather than rebuilt for
    every result. Returned context is ordered by original segment ordinal.
    """
    if not groups:
        return []
    eligible, params = scope(w, pinned, filters)
    requests = [
        {
            "position": position,
            "source_id": str(group["source_id"]),
            "segment_set_id": str(group["segment_set_id"]),
            "representation": group["representation"],
            "ordinal": group["ordinal"],
            "member_ids": [str(i) for i in group["member_ids"]],
        }
        for position, group in enumerate(groups)
    ]
    params.update(requests=json.dumps(requests), n=limit)
    selected = rows(
        conn,
        "WITH eligible AS MATERIALIZED (" + eligible + """ ),
      requested AS (
        SELECT * FROM jsonb_to_recordset(CAST(:requests AS jsonb)) AS req(
          position integer, source_id uuid, segment_set_id uuid,
          representation text, ordinal integer, member_ids uuid[])),
      ranked AS (
        SELECT req.position,s.source_id,s.id,
          row_number() OVER(PARTITION BY req.position
            ORDER BY abs(s.ordinal-req.ordinal),s.ordinal,s.id) AS neighbor_rank
        FROM requested req JOIN eligible s
          ON (s.source_id,s.segment_set_id,s.representation)=
             (req.source_id,req.segment_set_id,req.representation)
        WHERE s.id<>ALL(req.member_ids))
      SELECT position,source_id,id FROM ranked WHERE neighbor_rank<=:n
      ORDER BY position,neighbor_rank""",
        params,
    )
    hydrated = hydrate(conn, eligible, params, [r["id"] for r in selected])
    by_id = {(r["source_id"], r["id"]): r for r in hydrated}
    output = [[] for _ in groups]
    for item in selected:
        row = by_id.get((item["source_id"], item["id"]))
        if row is not None:
            output[item["position"]].append(row)
    for context_rows in output:
        context_rows.sort(key=lambda r: (r["ordinal"], str(r["id"])))
    return output


def context(conn, w, pinned, filters, result, limit=2):
    return context_batch(conn, w, pinned, filters, [result], limit)[0]


def facets(conn, w, pinned, filters):
    eligible, params = scope(w, pinned, filters)
    return rows(
        conn,
        "WITH eligible AS MATERIALIZED ("
        + eligible
        + """ )
      SELECT source_id,source_name,modality,count(DISTINCT asset_id) AS assets
      FROM eligible GROUP BY source_id,source_name,modality ORDER BY source_name,modality""",
        params,
    )


def progress(conn, w, pinned, filters):
    # Intake status is asset metadata. Segment-only filters cannot describe
    # unfinished inputs; these counts deliberately use metadata filters only.
    params = {"w": w, "g": pinned["id"]}
    clauses = ["a.workspace_id=:w", "NOT a.deleted"]
    for name, column, typ in (
        ("source_ids", "a.source_id", "uuid"),
        ("asset_ids", "a.id", "uuid"),
        ("modalities", "a.modality", "text"),
    ):
        values = getattr(filters, name)
        if values:
            params[name] = [str(v) for v in values]
            clauses.append(f"{column}=ANY(CAST(:{name} AS {typ}[]))")
    if filters.tags:
        params["tags"] = json.dumps(filters.tags)
        clauses.append("a.tags @> CAST(:tags AS jsonb)")
    query = """SELECT count(*) FILTER(WHERE ga.asset_id IS NULL) AS unpublished_assets,
      count(*) FILTER(WHERE ga.asset_id IS NOT NULL AND ga.revision_id IS DISTINCT FROM a.latest_revision_id) AS pending_updates,
      count(*) FILTER(WHERE EXISTS(SELECT FROM app.ingestion_jobs j WHERE (j.workspace_id,j.source_id,j.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id) AND j.status IN ('failed','partial')) OR EXISTS(SELECT FROM app.embedding_jobs ej WHERE (ej.workspace_id,ej.source_id,ej.asset_id)=(a.workspace_id,a.source_id,a.id) AND ej.generation_id=:g AND ej.status='failed')) AS assets_with_errors
      FROM app.assets a LEFT JOIN app.generation_assets ga ON (ga.workspace_id,ga.source_id,ga.asset_id)=(a.workspace_id,a.source_id,a.id) AND ga.generation_id=:g WHERE """ + " AND ".join(
        clauses
    )
    return dict(conn.execute(text(query), params).mappings().one())
