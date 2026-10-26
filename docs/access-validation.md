# Access-management implementation and validation

26 October 2026. Scope: A1 of the [users and roles plan](users-roles-plan.md).
Implementation authorized by the user's “go ahead”. A2–A7 remain pending; this
milestone adds no public signup, invitation, People or sharing-management UI.

Follow-up: the user subsequently requested persistent admin/two-member accounts
and role dashboards. [Role dashboard validation](role-dashboards-validation.md)
records the added read-only People UI, explicit operator provisioning and live
multi-account checks. The A1 results below remain the historical foundation.

## Adopted A1 decisions

- Keep existing owner/admin content and index powers unchanged. Add
  `app.owner_of(workspace)` and a reusable owner guard for later owner-only
  membership and ownership operations. It does not create those operations.
- Expose authenticated, no-store workspace and per-collection capabilities at
  `/api/workspaces/{w}/capabilities` and
  `/api/workspaces/{w}/sources/{s}/capabilities`. They use the actual actor and
  restricted database role, rechecking membership/grants on every call.
- The existing workspace-list response now includes `can_create_collections`.
  The frontend uses that server value for collection creation instead of
  interpreting the role label. Other account and role-management UI is pending.
- Workspace capabilities distinguish collection creation, folder import, index,
  storage, member management, role management and ownership transfer. The last
  three describe authorization policy for later routes, not implemented feature
  availability. Do not display placeholder management controls from these flags.
- Collection capabilities return the existing `read`, `ingest`, `admin` grant
  or `workspace_admin`, plus read/ingest/manage booleans. UI Contributor maps to
  `ingest`; the plan's earlier `write` value was corrected to match the schema.
- Migration `0020_workspace_ownership` rejects existing ownerless/multiple-owner
  workspaces without changing memberships. A partial unique index prevents two
  owners, deferred checks require an owner at commit, and membership changes
  serialize on the workspace row. Provisioning must create workspace and owner
  together. Future transfers must demote then promote in one transaction.
- The runtime role receives only the new owner predicate's EXECUTE privilege,
  not direct membership-write privileges or permission to invoke internal
  trigger functions. Operator workspace deletion and fixture cleanup still work.

These are workspace-scoped roles. An owner of one workspace cannot manage
another. Ownership is a membership invariant; disabling its account remains an
operator recovery action, not an automatic transfer.

## Validation record

Completed A1 checks on 26 October 2026:

| Check | Result |
| --- | --- |
| Disposable-database migration checks | 3 passed: fresh head, zero owners rejected, duplicate owners rejected |
| Focused runtime-role access suite | 11 passed |
| `python3 scripts/dev.py verify` | 210 passed in 262.91 seconds; one existing Starlette/httpx deprecation warning |
| `make build-frontend` | Strict TypeScript and production bundle passed |
| `make test-frontend` | 30 desktop/mobile checks passed in 28.3 seconds; synthetic API fixtures |
| Repository guard tests | 12 passed |
| Existing owner, deployed API | Login, workspace list, owner capabilities and collection capabilities passed; temporary session signed out |
| Preservation snapshot | One workspace/membership, 121 assets/revisions, 579 citations/embeddings and active generation unchanged; no ownership anomalies |

Test coverage added for:
owner/admin/member capabilities; owner-only guard; read/ingest/admin grants;
hidden versus missing IDs; anonymous access and spoofed actor headers; grant,
membership and role revocation; deleted collections; runtime write denial;
zero/duplicate-owner rejection; atomic owner handoff; serialized concurrent
membership edits; safe rejection of ambiguous pre-migration ownership; fresh
database migration.

Pre-change inspection found one workspace, one membership and no ownership
anomalies. Content counts were 121 assets/revisions and 579 citations/embeddings.
Private preservation snapshots stay under `.local`. The comparison covers row
counts and active index identities, not a fresh byte-by-byte object-store scan.
These are counts, not a
new relevance benchmark. No corpus, model or retrieval setting changes are part
of this work.

Baseline service inspection found API, frontend, worker, embedding, PostgreSQL
and Redis healthy, but the pre-existing recovery-journal container unhealthy.
This milestone does not claim recovery readiness or repair that separate issue.
Unrelated database-viewer edits in Compose, developer docs and scripts are
preserved. API and frontend were rebuilt and restarted; the deployed owner
capability flow was verified. No new signup/management controls are exposed.

Black's formatting API verified all four changed/new Python implementation and
test files. Its CLI printed completion but did not exit cleanly in this tool
environment, so the API check was used instead. Whitespace and publication
leakage checks are required again before any commit. No commit or push is part
of this milestone.
