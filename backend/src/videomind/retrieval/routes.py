"""Authenticated text queries; no shared content/query cache."""

import time
import asyncio
from urllib.error import HTTPError
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import text
from videomind.contracts import AssetRef
from videomind.evidence.previews import resolve_batch
from videomind.identity.service import actor
from videomind.infrastructure.database import transaction
from videomind.infrastructure.telemetry import trace_id
from videomind.embeddings import generations
from videomind.embeddings.client import Client
from videomind.embeddings.indexer import heavy
from videomind.retrieval.contracts import (
    SearchRequest,
    ImageSearchRequest,
    SearchFilters,
    SearchResponse,
    EvidenceResult,
    ContextEvidence,
)
from videomind.retrieval.config import configuration
from videomind.retrieval import repository, ranking

from videomind.retrieval.image_query import normalize, MAX_BODY

image_gate = asyncio.Semaphore(2)

router = APIRouter(prefix="/workspaces/{w}/search")


def member(conn, w):
    if not conn.execute(text("SELECT app.member_of(:w)"), {"w": w}).scalar_one():
        raise HTTPException(404, "Workspace unavailable")


@router.get("/facets")
def facets(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        member(conn, w)
        try:
            pinned = generations.pin(conn, w)
        except HTTPException as exc:
            if exc.status_code == 409:
                return {"ready": False, "items": []}
            raise
        return {
            "ready": True,
            "items": repository.facets(conn, w, pinned, SearchFilters()),
        }


@router.post("", response_model=SearchResponse)
def search(
    w: UUID, body: SearchRequest, request: Request, principal: UUID = Depends(actor)
):
    return execute_search(w, body, request, principal)


@router.post("/image", response_model=SearchResponse)
async def image_search(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        member(conn, w)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Image search expects JSON")
    if image_gate.locked():
        raise HTTPException(
            429, "Two image queries are already in progress; try again shortly"
        )
    async with image_gate:
        raw = bytearray()
        try:
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > MAX_BODY:
                        raise HTTPException(413, "Image query request is too large")
                    raw.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Image upload timed out") from None
        try:
            body = ImageSearchRequest.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(
                422,
                "Invalid image query; use JPEG/PNG up to 4 MiB and valid search filters",
            ) from None
        if body.workspace_id != w:
            raise HTTPException(422, "Workspace selector mismatch")
        content = await run_in_threadpool(normalize, body.image_base64)
        return await run_in_threadpool(
            execute_search, w, body, request, principal, content
        )


def execute_search(w, body, request, principal, image_content=None):
    if body.workspace_id != w:
        raise HTTPException(422, "Workspace selector mismatch")
    started = time.perf_counter()
    policy, digest = configuration(body)
    with transaction(request.app.state.db, principal) as conn:
        member(conn, w)
        pinned = generations.pin(conn, w)
    vector = None
    if body.mode != "lexical":
        try:
            with heavy(request.app.state.db, blocking=False) as available:
                if not available:
                    raise HTTPException(
                        503, "CPU processing is busy; try search again shortly"
                    )
                encoded = Client().encode(
                    pinned["fingerprint"],
                    "image" if image_content is not None else "text",
                    image_content if image_content is not None else body.query.strip(),
                    query=True,
                    configuration=pinned["configuration"],
                )
            if len(encoded["parts"]) != 1:
                raise ValueError("query cannot split")
            vector = encoded["parts"][0]["vector"]
        except HTTPException:
            raise
        except HTTPError as exc:
            raise HTTPException(
                422 if exc.code == 422 else 503,
                (
                    "Query exceeds model budget"
                    if exc.code == 422
                    else "Search model busy or unavailable; try again"
                ),
            )
        except Exception:
            raise HTTPException(503, "Query embedding unavailable; try again")
    embedded = time.perf_counter()
    with transaction(request.app.state.db, principal) as conn:
        member(conn, w)
        conn.execute(text("SET LOCAL statement_timeout='8s'"))
        branches, details = repository.candidates(conn, w, pinned, body, vector, policy)
        groups = ranking.fuse(
            branches, details, policy, body.top_k, len(body.filters.asset_ids) == 1
        )
        eligible, params = repository.scope(w, pinned, body.filters)
        fresh = repository.hydrate(conn, eligible, params, [r["id"] for r in details])
        visible_ids = {r["id"] for r in fresh}
        if visible_ids != {r["id"] for r in details}:
            branches = {
                name: [r for r in rows if r["id"] in visible_ids]
                for name, rows in branches.items()
            }
            groups = ranking.fuse(
                branches, fresh, policy, body.top_k, len(body.filters.asset_ids) == 1
            )
        results = []
        contexts = repository.context_batch(
            conn, w, pinned, body.filters, groups, policy["neighbors"]
        )
        for group, context_rows in zip(groups, contexts):
            group["context_rows"] = context_rows
        # Re-read scope after materializing/ranking, including neighbors. This
        # observes revocations, tombstones and replaced membership before return.
        eligible, params = repository.scope(w, pinned, body.filters)
        ids = [r["id"] for g in groups for r in g["members"] + g["context_rows"]]
        visible = {r["id"] for r in repository.hydrate(conn, eligible, params, ids)}
        for group in groups:
            if any(r["id"] not in visible for r in group["members"]):
                continue
            cites = {
                c.id: c for row in group["members"] for c in ranking.citations(row)
            }
            warnings = []
            manifest = group["extraction_manifest"]
            if manifest.get("warnings"):
                warnings.append("Extraction has warnings; inspect original evidence.")
            if group["representation"] in {"ocr", "transcript"}:
                warnings.append(
                    "Machine-extracted text may contain recognition errors."
                )
            results.append(
                EvidenceResult(
                    asset=AssetRef(
                        workspace_id=w,
                        source_id=group["source_id"],
                        asset_id=group["asset_id"],
                        revision_id=group["revision_id"],
                    ),
                    title=group["title"],
                    source_name=group["source_name"],
                    modality=group["modality"],
                    segment_id=group["id"],
                    representation=group["representation"],
                    matched_representations=tuple(
                        sorted({r["representation"] for r in group["members"]})
                    ),
                    citations=tuple(
                        sorted(
                            cites.values(),
                            key=lambda c: (
                                str(c.anchor.id)
                                != str(group["citations"][0]["anchor_id"]),
                                str(c.id),
                            ),
                        )
                    )[:8],
                    snippet=ranking.snippet(group, body.query),
                    branches=group["branches"],
                    dense_score=(
                        max(-1, min(1, group["branches"]["dense"]["score"]))
                        if "dense" in group["branches"]
                        else None
                    ),
                    lexical_score=group["branches"].get("lexical", {}).get("score"),
                    fusion_score=group["fusion_score"],
                    warnings=tuple(warnings),
                    context=tuple(
                        ContextEvidence(
                            segment_id=r["id"],
                            representation=r["representation"],
                            snippet=ranking.snippet(r, body.query),
                            citations=tuple(ranking.citations(r)),
                        )
                        for r in group["context_rows"]
                        if r["id"] in visible
                    ),
                )
            )
        previews = resolve_batch(conn, w, results)
        results = [
            hit.model_copy(update={"preview": previews.get(hit.segment_id)})
            for hit in results
        ]
        counts = repository.facets(conn, w, pinned, body.filters)
        progress = repository.progress(conn, w, pinned, body.filters)
    ended = time.perf_counter()
    return SearchResponse(
        request_id=UUID(trace_id.get()) if trace_id.get() else uuid4(),
        workspace_id=w,
        generation_id=pinned["id"],
        profile=pinned["fingerprint"],
        retrieval_config_sha256=digest,
        configuration=policy,
        filters=body.filters,
        progress=progress,
        results=tuple(results),
        no_useful_evidence=not results,
        facets=tuple(counts),
        warnings=(
            f"{progress['unpublished_assets']} files are not indexed; {progress['pending_updates']} have pending revisions; {progress['assets_with_errors']} have processing errors. Counts use source/file-type/tag filters. Check file status below.",
            (
                "Image-query relevance uses the existing 0.70 similarity cutoff; it has not been independently calibrated for image queries. Scores are not probabilities."
                if image_content is not None
                else "Relevance policy is calibrated on a small local development set; inspect the cited evidence."
            ),
        ),
        timings_ms={
            "embedding": round((embedded - started) * 1000, 2),
            "retrieval": round((ended - embedded) * 1000, 2),
            "total": round((ended - started) * 1000, 2),
        },
    )
