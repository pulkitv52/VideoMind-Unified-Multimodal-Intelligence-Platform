# VideoMind agent instructions

## Before implementation

Phase 2 is implemented and validated on the CPU-only laptop. For connector, ingestion, quota or retention changes, read `docs/phase2-validation.md` and its acceptance report. Phase 3 document extraction/evidence is implemented and validated; for extraction, OCR, rendering, citation or document-viewer changes, read `docs/phase3-validation.md` and its acceptance report. Phase 4 media processing/playback is implemented and validated; for media, ASR, temporal citations, Range playback or shared worker changes, read `docs/phase4-validation.md` and its acceptance report. Phase 5 embedding/index lifecycle is implemented and validated; for model inference, index jobs, source publication locks or generation changes, read `docs/phase5-validation.md` and its acceptance report. Phase 6 hybrid search is implemented and validated; for retrieval, ranking, filters, facets, abstention or search-UI changes, read `docs/phase6-validation.md` and its acceptance report. Phase 7 evaluation is authorized and has measured failures; read `docs/phase7-validation.md` and `evaluation/reports/phase7-assessment.json` before benchmark, recovery or relevance changes. Its MVP release gate remains open. GPU work and scaling retain their own implementation requests.

For platform design or implementation, read `docs/architecture-proposal.md`. For a phased task, read its entry and dependencies in `docs/codex-implementation-plan.md`. Treat requirements there as proposed until adopted; surface changes to scope or acceptance criteria explicitly.

For local setup or infrastructure changes, read `README.md` and `docs/phase1-validation.md`; run `python3 scripts/dev.py verify` against the running stack. Preserve `.env`, `.local` and named volumes.

## Tools and conventions

- Follow existing patterns. Prefer uv, Black, Python logging and Pydantic for Python/backend work.
- Prefer pnpm, TypeScript, Vite and shadcn patterns for frontend work. Add controls only when they serve a real user action.
- Use Python/FastAPI, PostgreSQL + pgvector, MinIO, Redis and Celery unless the user changes the stack.
- Keep connector fetching, preprocessing, embedding, retrieval and evidence resolution behind separate module contracts.

## Correctness invariants

- Preserve immutable originals, source revisions and evidence locators. Derived text and media identify their producer and original mapping.
- Apply workspace/source access checks to every content path, including vectors, snippets, thumbnails, jobs, citations and playback. Test using the runtime database role.
- Publish complete generation membership transactionally. Retries, duplicate task delivery and worker restarts must preserve idempotency.
- Pin model/processor revisions and persist embedding profiles. Compare vectors only within compatible profiles; validate dimension, finiteness and normalization.
- Keep quota reservations until reference commit or confirmed cleanup. Coordinate object writes/reference commits and maintenance with the shared/exclusive storage lock.
- Keep long processing in workers, with bounded resources. Keep PostgreSQL as durable job authority and Redis reconstructible.
- Keep source content, credentials and signed links out of ordinary logs. Treat imported media/documents as untrusted input.

## Completing a phase

Implement only the requested phase and its authorized dependencies. Verify every exit criterion with appropriate checks and record results, limitations and changed decisions. Do not report proposed benchmark targets as measured results. Update design documentation when an adopted decision changes.

## Commits

Use conventional commits with this format:

```text
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `chore`, `docs`, `feat`, `fix`, `refactor`, `style`, `test`.
Scopes: `backend`, `frontend`, `infra`, `general`.
Subject: at most 50 characters. Optional body: bullet list describing the change. Optional footer: issue references or breaking-change notes.
