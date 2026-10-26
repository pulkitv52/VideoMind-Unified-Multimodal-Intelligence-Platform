# Self-service signup and administrative Dashboard

26 October 2026. Implements the authorized [S1–S6 product plan](self-service-product-plan.md).
Final validation results are recorded below. Earlier access and role-demo results
remain in their original reports and do not substitute for these checks.

## Using the product

- **New member:** on the sign-in screen, choose **New here? Create an account**.
  Enter a username (3–64 letters, numbers, underscores, dots or hyphens), a password
  (12–256 characters) and confirmation. Accept the workspace access notice. The
  account opens in Library with an initial writable collection. Upload, wait for
  **Ready to search**, then use Search and Open evidence.
- **Member:** Library supports creating further upload collections and uploading
  or retrying writable files. Search/evidence remains restricted to granted
  collections. A read-only share remains read-only. Members see their own access
  summary in Settings and have no analytics, directory or global index controls.
- **Admin:** Dashboard shows members, recorded joins, attributed current files,
  preparation failures and storage. Filter uploads by account, type, state and
  period; page older entries or download their original. Open Library for detailed
  processing/retry. Admins can remove ordinary members, but cannot promote anyone
  or change/remove an owner or another admin.
- **Owner:** has the same Dashboard and content operations, plus member/admin role
  changes and registration open/close. The owner cannot be demoted or removed by
  this workflow. Ownership transfer remains a separate future workflow.

Owners/admins can access every collection in their workspace. A member's newly
created collection is hidden from other ordinary members, not from administrators.
Removal revokes workspace membership and explicit source grants immediately;
existing files remain in the workspace. Role changes retain explicit collection
grants. The UI explains these effects before confirmation. Membership updates use
an expected version, so stale updates fail instead of silently overwriting another
administrator's action. Audit rows retain actor, target, old/new role and time.

## Installation setup

Registration is closed until explicitly configured. Set the nonsecret
`VM_SIGNUP_WORKSPACE_ID` in the installation's ignored `.env` to an existing
workspace UUID, then recreate the API with Compose. Sign in as that workspace's
owner and use **Dashboard → Open registration**. Anonymous `signup-info` exposes
only an enabled flag, not workspace or account inventories. The API never accepts
an alternate signup workspace, role, source grant or uploader identity from clients.
The configured local workspace is the existing demo workspace; existing accounts,
source grants, originals and active generation are retained.

Migration `0022_self_service` follows `0021_workspace_people`. It adds a
case-insensitive username uniqueness index (fails on existing ambiguous names),
private signup policy, future join timestamps and membership version sequence,
source creator, source-scoped upload attribution and membership audit tables.
Existing unknown join dates remain null. Uploader history is backfilled only from
original validation job request records; unknown uploaders stay Unknown.

Bounds: 100 memberships per configured workspace by default, 20 active created
collections per account, 10 signup submissions per workspace per minute and one
password hashing operation at a time in the API process. Normal existing file,
media, quota and worker resource bounds still apply. Passwords use the existing
scrypt hashing and HttpOnly/SameSite session flow. Account, membership, default
collection, grant and session creation commit together. A failed registration
preserves an existing session.

The indexer provisions a first generation only when a policy exists, prepared
content is eligible, a valid current owner exists, and no generation/active index
already exists. It records the automatically created generation, uses the current
pinned service profile and existing publication locks, and activates only complete
coverage. It never replaces an active generation or takes over an administrator's
manual build. Closing registration does not stop indexing for existing accounts.
The current owner supplies the indexing authority; member requests cannot select
global profiles or activate/replace generations. Model failures remain retryable
file/index errors rather than successful-search claims.

## Analytics definitions

Overview cards count current, nondeleted assets/latest revisions in nondeleted
collections across the workspace. Filters affect the upload table and chart,
not workspace totals or per-member lifetime-current-file counts. Date ranges are
1–90 days, upload pages contain at most 20 rows and use a received-time/UUID cursor.
The chart groups current file receipts by UTC day; it is not a historical audit of
all uploads, revisions or deleted files. Activity refreshes every 15 seconds. Loading older upload pages pauses automatic
refresh so rows remain visible; **Return to latest activity** resets paging and
resumes updates.

Ready means the latest revision has membership in the active generation. Failed
means a current-revision ingestion/indexing job failed; prepared content awaiting
active publication is Indexing, and other content is Preparing. Partial extraction
warnings are shown separately. Counts do not count vectors, retries or old
revisions as new files. Directory rows are bounded to 101 accounts; Settings
People supports further paging. Original validated and ready-to-search are
separate states.

## Verification record

- Fresh isolated database upgrade through revision 0022: **passed**.
- Focused signup/access/role API suite before expanded edge-case checks: **26 passed**.
- Desktop/mobile UI suite: **42 passed**, including signup disclosure, member route
  denial, dashboard filters, theme persistence, legacy citations and 320 CSS-pixel
  reflow. Corrected four-item mobile navigation overflow found on the first run.
- Production TypeScript/Vite build: **passed**.
- Repository leak-guard regression suite: **14 passed** after the precommit review
  added pgAdmin/database-viewer password inventory and private-filename checks;
  worktree, staged and history scans passed. Optional database-viewer tests: **2 passed**.
- Full running-stack backend suite: **227 passed**. Expanded self-service edge-case
  suite: **16 passed**, including two further retry/pagination cases (229 unique
  backend tests covered across the runs). It exercises actual concurrent DB
  connections, capacity/closed registration, throttling, rollback, version conflicts,
  source grants, initial generation creation/incomplete-publication blocking,
  completed activation/idempotency, upload attribution and administrative filters.
- Live desktop/mobile browsers: **9 passed** initially; the single mobile admin
  search received the expected CPU-busy response during a simultaneous role API
  search. Its isolated rerun **passed**. All 10 journeys are covered, including
  real signup → upload → automatic indexing → search → original evidence,
  owner/admin attribution, peer isolation and immediate membership revocation.
- Persistent owner/admin/two-member direct API regression: **66 passed**.
- Original preservation: **123 originals verified byte for byte**, 123 original
  latest-revision pointers unchanged, and the existing active generation unchanged.
  All four original active accounts remain. The two successful synthetic signup
  accounts had membership/grants revoked, sessions removed and accounts disabled;
  their disconnected test collections follow existing retention. Identity records
  remain for ingestion-job provenance. Two temporary fixture workspaces left by a
  test starting during API restart were removed; the readiness-safe rerun passed.
- Restricted runtime-role scope checks: **24 content tables passed**, plus immediate
  live source-grant/workspace revocation and restoration. The drill preserves
  original join dates instead of presenting the test restoration as a new signup.
- Recent application/worker logs: **no existing deployment credentials found**.
  Worktree guard and whitespace checks passed after documentation updates.

The local stack runs the new API, worker, dispatcher, indexer and frontend.
Registration is configured and open for the existing workspace. Dashboard currently
reports 123 current files, 118 ready and 5 needing attention; these existing file
failures were not repaired or hidden by this account/UI change. The validation run did not commit or push changes.

Private execution logs and synthetic live-test captures remain under ignored
`.local/`. No passwords, session tokens or private source contents are part of
this report. Tests use the restricted runtime database role for authorization
assertions; privileged fixture setup/cleanup is explicitly separate.

## Limits

This is username/password registration for the existing loopback-only deployment.
Email verification, password recovery, invitation links, billing, Internet hosting,
workspace creation and ownership transfer are not implemented. No external signup
provider, tracking service or persistent member search history was added. Unknown
historical join/uploader values are not reconstructed from filenames. The Phase 7
relevance and performance release gate remains open; these account/UI checks do
not establish better search quality or an Internet production deployment.


## Precommit review follow-up

Standards/security and product-spec source reviews found two issues: the exact
credential inventory omitted pgAdmin/database-viewer passwords, and periodic
Dashboard refresh reset expanded upload pages. Both were fixed with regression
coverage. The guard now also blocks exported viewer credential filenames and
`.pgpass`; scanner diagnostics do not print matched values. Final TypeScript/Vite build passed and **44 desktop/mobile UI checks passed**,
including pagination across the refresh interval and resuming current activity.
The 14 leak-guard regressions and all three repository scans (worktree, staged
index and history) passed. The precommit review did not create a commit.
