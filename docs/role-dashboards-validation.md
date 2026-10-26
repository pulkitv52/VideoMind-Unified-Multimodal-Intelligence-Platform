# Persistent role accounts and dashboards

26 October 2026. The user requested one admin, two members, role-specific
dashboards and thorough testing. These accounts are persistent local test
accounts, not the disposable integration-suite identities. They remain available
for the user to sign in. Passwords are random and stored only in the private,
ignored `.local/role-test-accounts.json`, with file mode 0600. The existing owner
password and membership are unchanged.

## What each account can see and do

| Account | Workspace role | Visible collections | Available dashboard and actions |
| --- | --- | --- | --- |
| Existing owner | Owner | Every collection in this workspace | Search and inspect all files; create collections/upload/import folders; processing and index controls; storage; workspace access summary; read-only People directory |
| `demo_admin` | Admin | Every collection in this workspace | Same current file/index operations, storage and read-only People; no owner-only role/ownership policy privileges |
| `demo_member_viewer` | Member | Role test — Viewer only | Search, inspect, download originals and copy citations in that collection; read-only Library; access summary; safe search-preparation guidance |
| `demo_member_contributor` | Member | Role test — Contributor only | Viewer actions in its own collection plus upload and supported processing retries; no collection disconnect, People, workspace storage or index administration |

Viewer and Contributor are collection permissions, not additional workspace
roles. Owners/admins can access both members' collections. Members cannot access
one another's collections or the pre-existing research files. This is a shared
workspace with restricted collections; it does not provision separate personal
workspaces or claim privacy against the local machine operator.

## Where to find the dashboards

- Header: signed-in username and current workspace role, theme and sign-out.
- **Settings → Your workspace access:** current role, plain-language powers and
  only the collections that the actor can access, with Viewer/Contributor/
  Collection manager or workspace-administrator labels.
- **Settings → People:** bounded, paginated, read-only account directory for
  owner/admin only. It includes usernames, workspace roles and disabled status,
  never password hashes, tokens, cookies or unrelated-workspace identities.
- **Library:** role-appropriate Add collection, Upload files, retries and
  Disconnect actions. A member with no grants sees access-request guidance.
- **Search:** authorized facets, results, originals and citations. A citation
  link cannot bypass collection access.
- **Settings → Search preparation:** administrator operations and storage;
  members receive guidance without generation inventories or global counts.

The People directory intentionally has no inactive invite/promote/remove buttons.
Self-service signup, invitations, password/session management, role/grant mutation
screens and ownership transfer remain unimplemented parts of A2–A7. This work
implements the specifically requested account setup and a read-only portion of
A3, not the entire account-management roadmap.

## Implementation and operator provisioning

Migration `0021_workspace_people` adds a SECURITY DEFINER read function with a
fixed search path, current active-actor/admin checks and a 101-row hard bound.
`GET /api/workspaces/{w}/people` checks server capabilities, validates paging and
returns only directory fields. The runtime role gains no membership-write
privileges. Member direct calls receive 403; inaccessible workspaces receive 404.

`videomind.identity.role_demo` is operator-only and never mounted as an API.
It creates the three identities/memberships, two upload collections and their
individual grants in one transaction. Existing username collisions fail closed.
Credential-write failure rolls back database creation. Re-running with its
existing credential file validates identities, passwords and grants instead of
changing roles or rotating passwords. It does not silently repair permission
drift. Unexpected changes require operator review.

The explicit operator invocation uses the existing bootstrap service:

```bash
docker compose --env-file .env -f infra/compose/compose.yaml run --rm --no-deps \
  --user "$(id -u):$(id -g)" bootstrap \
  python -m videomind.identity.role_demo --workspace <workspace-uuid> \
  --credential-file /bootstrap/role-test-accounts.json
```

No generic create-account form or public registration endpoint is introduced.
Git guards block the credential filename and nested role-account passwords even
if copied into otherwise innocently named files. Ordinary server logs contain
no account passwords or source content.

## Synthetic content and preservation

Each member collection contains one small `role-example.txt` document. Their
distinct markers are `ROLE-VIEWER-ALPHA` and `ROLE-CONTRIBUTOR-BETA`. The viewer
fixture was uploaded by the admin; the contributor uploaded its own fixture.
They use the ordinary validation/extraction/indexing pipeline and existing active
generation. No new model, producer, threshold, ranking or generation was selected.

The live API checker first used the upload endpoint for GET file listing and
received 405. Its harness was corrected to the existing `/assets` listing route;
no application endpoint change was needed. The failure and corrected run are
retained privately under `.local`.

## Test record

| Verification | Result |
| --- | --- |
| Focused access/directory/provisioning tests | 14 passed; actual restricted PostgreSQL role; includes provisioning rollback/idempotency, directory paging/revocation and secret-free response fields |
| Live API checks | 68 passed: four real logins; admin/contributor uploads; viewer write denial; collection/facet/search isolation; original downloads; document/citation access; member storage/People/index/creation denial |
| Actual role account database scope | Passed across 23 source-scoped tables, including originals, jobs, media, vectors, text, evidence and grants |
| Live permission revocation | Existing viewer session lost access on grant removal; existing contributor session lost workspace access on membership removal; both exact permissions restored and access verified |
| Live desktop/mobile browser journeys | 8 passed in 55.5 seconds; all four accounts log in, see the correct dashboard/Library actions, run hybrid search and open real document evidence |
| Git guard regressions | 13 passed, including detection/redaction of a nested role-account password copied into another file |
| Full backend regression | 213 passed in 270.37 seconds; one existing Starlette/httpx deprecation warning |
| Final desktop/mobile UI regression | 36 passed in 35.7 seconds; includes clearing stale directory and collection details after an access error |
| Build/type checks | Production frontend build and strict TypeScript checks for both browser configurations/specs passed |
| Preservation | All 121 pre-existing original checksum/length and asset-revision records unchanged; two synthetic originals added; active generation unchanged |
| Persistent accounts | Exactly owner/admin/member/member in the target workspace; provisioning rerun preserved credentials and restored grants |

The ordinary UI suite uses synthetic intercepted APIs; the separate live suite
uses the deployed app, actual credentials and real search/indexed evidence.
Neither is a relevance benchmark or a claim of full accessibility compliance.
Private screenshots cover all four roles at desktop/mobile widths. Passwords are
not displayed in screenshots, test names or the committed validation record.
The live suites sign out their isolated test sessions; they do not sign out the
user's existing browser session.

Reproduce after provisioning/indexing:

```bash
python3 scripts/check_role_accounts.py --seed
pnpm --dir frontend exec playwright test --config playwright.live.config.ts
python3 scripts/dev.py verify
```

`--seed` adds the two synthetic documents only if their collections have no files.
It does not overwrite existing files. The measured 68 checks include the two
initial successful fixture uploads; reruns with existing fixtures skip those
uploads and run 66 checks. The database-scope/revocation drill is an
explicit operator check, not an application feature. It requires both the actual
runtime and migration connection environment and restores permissions in `finally`:

```bash
docker compose --env-file .env -f infra/compose/compose.yaml run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/scripts/check_role_isolation.py:/role-check.py:ro" \
  --volume "$PWD/.local/role-test-accounts.json:/role-accounts.json:ro" \
  verify python /role-check.py --credentials /role-accounts.json
```

Existing original-file metadata and active-index identities are compared to a
private pre-change snapshot after the full integration suite has cleaned up.
This checks stored checksums/lengths and identities, not a new byte-by-byte scan
of every original object. Unrelated database-viewer changes remain intact.
