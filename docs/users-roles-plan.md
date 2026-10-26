# Users, roles and workspace management

Date: 21 October 2026. Status: proposed implementation plan, requested by the
user. Implementation was authorized on 26 October 2026. A1 is implemented and validated;
see [access implementation validation](access-validation.md) for measured results
and pending work. This document describes the complete proposed target, not a
claim that all account, permission or signup features exist. It extends the product UX plan's scope to account and grant
management; those screens were excluded from its original UX0–UX6 milestone.
Existing processing, retrieval and Phase 7 release gates remain unchanged.

**Product-direction update, 26 October 2026:** the user requested self-signup,
member upload/index/search workflows and administrative analytics. The
[self-service product plan](self-service-product-plan.md) supersedes this
document's invitation-first/no-public-signup rule and the restriction on member
upload-collection creation. The older details below remain the original A1–A7
design history where they conflict; the self-service plan is authoritative for
new implementation. Signup and analytics have not yet been implemented.

The user subsequently requested persistent admin/two-member accounts and tested
role dashboards. See [role dashboards and validation](role-dashboards-validation.md)
for the implemented local accounts, access summaries and read-only People
directory. This does not complete invitation or permission-mutation features.

## 1. Current behavior and planned changes

| Area | Current implementation | Proposed behavior |
| --- | --- | --- |
| Sign-in | Username/password and server sessions | Retain; add account/password/session management |
| Account creation | Operator bootstrap, normally one owner | Owner invitations and controlled account activation |
| Workspace roles | Owner, admin, member; owner/admin share administrative checks | Distinguish ownership and membership powers from operational administration |
| Content access | Workspace membership plus collection grants; owners/admins access every collection | Preserve this boundary and explain it in the interface |
| Permission editing | No product screens | People and collection-sharing screens with server enforcement |
| Personal files | Separate workspace can be provisioned by an operator | Personal workspace available through controlled provisioning; no automatically private uploads in a shared workspace |
| Role management | No public management API | Narrow, audited APIs with concurrency-safe checks |

The database already forces row-level security for content. The runtime database
role cannot bypass it. This is a starting point, not evidence that the proposed
management APIs are implemented or validated. The relevant existing contracts
are in identity, connector, retrieval and evidence modules and the foundation
SQL. Read the Phase 2 and Phase 6 validation/acceptance reports before extending
these boundaries.

## 2. Access model and product rules

- An account identifies a person. A workspace owns its collections, files,
  immutable revisions, search index and storage allocation.
- A role belongs to a workspace membership, not to an account globally. The same
  person can own a personal workspace and be a member of a team workspace.
- A collection is the existing backend source. Grants apply to the collection
  and its files, including future uploads. The sharing dialog explains this.
- Owners and admins can read and manage every collection in their workspace.
  They do not receive access to another workspace merely because they are an
  administrator somewhere else.
- A member requires an explicit collection grant. No grant means no files,
  filenames, snippets, search results, counts, jobs or evidence from it.
- Files uploaded into a shared collection are shared with that collection's
  authorized users. They do not belong privately to their uploader.
- Local machine/database operators can access installation storage and backups.
  Workspace isolation is application authorization, not separate encrypted
  storage against the machine operator. Do not promise otherwise.
- Prefer one owner per workspace. Preserve existing data during migration;
  detect any existing zero/multiple-owner memberships and require operator
  reconciliation before enforcing this invariant. Never silently demote users.
- Self-registration is now required for the configured installation workspace,
  with a member's own initial collection and bounded resource admission. It must
  not grant access to other members' collections or other workspaces. See the
  superseding self-service plan for the updated onboarding contract.

## 3. Who sees and does what

All roles retain Search, Library, theme selection, account settings and sign-out.
Show only meaningful, allowed actions. The server remains authoritative when a
role changes after a screen was opened.

| Capability | Owner | Admin | Member |
| --- | --- | --- | --- |
| Search, inspect evidence, copy citations | All workspace collections | All workspace collections | Granted collections only |
| Download originals | All | All | Granted collections; read access includes download |
| See Library and processing status | All | All | Granted collections only |
| Upload files | Any collection | Any collection | Contributor/manager grant only |
| Create an upload collection | Yes | Yes | Own scoped collection, under the superseding self-service plan |
| Sync an allowlisted local folder | Yes | Yes | No; host-folder discovery stays administrative |
| Retry file processing | Yes | Yes | Contributor/manager on that collection, within supported retry APIs |
| Remove a file/disconnect a collection | Yes | Yes | Collection manager only |
| Manage collection grants | Yes | Yes | Collection manager, restricted as below |
| View workspace storage/quotas | Yes | Yes | Own upload limit and actionable limit errors only |
| Build/retry/activate/restore search index | Yes | Yes | No |
| View People directory | Full workspace directory | Full workspace directory | No full directory |
| Invite a new member | Yes | Yes, member role only | No |
| Promote/demote an admin | Yes | No | No |
| Remove a member from workspace | Yes | Yes, members only | Leave own membership only |
| Remove an admin | Yes | No | No |
| Transfer workspace ownership | Yes, to an active admin after reauthentication | No | No |
| Rename workspace/change approved quota allocation | Yes, within installation limits | No | No |
| Disable an account across the installation | Operator only | No | No |
| Delete workspace | Deferred; operator recovery procedure | No | No |

Owner/admin currently share `admin_of` checks. Keep that check for content and
operational capabilities; add a separate owner check for ownership and role
management. Do not broaden existing endpoints incidentally.

### Collection permissions for members

| UI name | Existing grant | Allowed actions |
| --- | --- | --- |
| Viewer | `read` | Search, view evidence, inspect and download originals |
| Contributor | `ingest` | Viewer actions plus upload and supported processing retry |
| Collection manager | `admin` | Contributor actions plus supported file removal/disconnect and sharing |

Collection management is not a workspace role. Managers can share only with
existing workspace members, can grant Viewer or Contributor, and cannot create
another manager, invite users, promote roles or manage the index. Owners/admins
assign and revoke managers. A manager can relinquish their own grant; workspace
administrators remain able to manage the collection. Verify every mutating
endpoint against this matrix; existing broad source-admin checks may need
narrower action checks.

Read access includes downloading and copying delivered content. Hiding a download
button cannot make viewed content non-copyable. Future requests can be denied
after revocation; bytes already delivered cannot be withdrawn.

## 4. Screen plan

### Shared header and account

Header: workspace selector when applicable, current workspace role, theme toggle
and account menu. Account menu: username, Account settings and Sign out. Never
show a global administrator badge for a workspace-scoped role.

Account settings: change own password, list/revoke own sessions, and sign out
everywhere. Require current password or a supported recovery flow; no shared
temporary password displayed in People. Account deletion and self-service
username changes are deferred. Theme remains a browser preference.

### Owner experience

Search and Library expose every collection. Settings has Workspace, People,
Search preparation, Storage and Account links. Workspace settings include name,
ownership, installation-assigned quota and the privacy explanation. People shows
active members, roles and pending invitations. Owner can invite members/admins,
promote/demote, remove, cancel invitations and transfer ownership.

Collection details have Files, Processing and Sharing. Sharing identifies that
owners/admins have inherent access; it cannot misleadingly revoke their access.
Dangerous operations show concrete scope and the existing retention behavior.
There is no workspace deletion button until deletion/recovery is implemented.

### Admin experience

Search, Library, Processing, Sharing, Search preparation and Storage are available
for the entire selected workspace. People supports inviting/removing members,
canceling invitations created for members and reviewing access. Owner/admin
roles are visible but immutable for admins. Ownership transfer, role promotion,
workspace policy and installation controls are absent.

An admin can solve failed processing, grant a member collection access and
activate a rebuilt index without needing the owner for everyday operations.
Show member invitation limits and workspace capacity without exposing unrelated
workspace information.

### Member experience

Search contains only authorized collection filters/results. Library lists only
granted collections with a plain permission label. Viewers see Open evidence and
Download original. Contributors also see Upload files and supported retries.
Collection managers additionally see the supported management/sharing actions.

Settings contains personal appearance/account options and a short service status
with actionable guidance. Hide generation inventories, global storage totals,
People and administrative health diagnostics. Readiness/error counts must be
scoped or reduced to a safe workspace capability signal.

With no grants, show “You don't have access to any collections yet. Ask your
workspace administrator.” Do not imply the whole workspace is empty. For a
first index that is not ready, show “An administrator needs to prepare search.”
Do not reveal titles or counts belonging to inaccessible collections.

## 5. Joining and personal versus shared workspaces

### Original invitation-first account creation (superseded)

The sequence below records the earlier design. Normal onboarding is now
self-service signup under the [revised product plan](self-service-product-plan.md);
invitations are optional future sharing functionality.

1. Owner/admin enters a username for the invite and permitted workspace role.
   First release uses a manually shared activation link; it sends no email.
2. Backend issues a cryptographically random, single-use activation token, stores
   only its hash, and applies a proposed 48-hour expiry plus invitation limits.
3. Inviter receives the link once and shares it through their chosen channel.
   Do not log tokens or persist them in analytics/browser storage. Serve token
   pages without third-party assets or referrers; remove the token from browser
   history after exchange. Do not consume invitations on a GET/page preview.
4. A new user chooses a password and explicitly accepts membership. Existing
   accounts must authenticate as the intended account; invite tokens cannot
   silently attach a different person or replace an existing password.
5. In one transaction, validate inviter authority, token/expiry, account binding,
   workspace capacity and role limits, then activate membership and consume it.
6. A member receives explicitly selected collection grants, otherwise starts
   with none. Invitations do not grant all collections by default.

Revoked/demoted inviters cannot leave invitations that grant powers they no
longer hold. Revalidate authority at redemption or cancel affected invitations.
Expired/invalid links receive a generic recovery path. Apply bounded attempts
and avoid username enumeration. Access/password recovery is operator-assisted
initially; no fake “Forgot password” flow.

### Personal files

Offer personal workspaces through an explicit, installation-approved provisioning
flow with a storage allocation and workspace limit. The person is owner there;
team owners/admins get no automatic membership. Do not create a personal workspace
silently on every invitation, which would multiply CPU/storage commitments.

Suggested first-time text: “Files added to this team workspace can be accessed
by its owner and admins. Use a separate personal workspace for private files.”
Sharing between workspaces is deferred: no move/copy shortcut that loses original
revision provenance or silently changes access. Shared workspaces can be created
by the installation operator initially; self-service creation is a later phase.

## 6. Management journeys and edge cases

- **Share a collection:** choose existing member, inspect scope including future
  uploads, choose Viewer/Contributor, apply, and show the resulting permission.
  Only owners/admins can grant Collection manager. No “Anyone with the link.”
- **Change role:** owner confirms the named person and new workspace role. Show
  that admin grants access to all workspace collections. Demotion does not invent
  member grants; show the grants that will remain before applying.
- **Remove member:** remove workspace membership and collection grants atomically,
  invalidate effective access immediately on subsequent requests, and cancel
  pending invitations/grant actions as appropriate. Keep the person's other
  workspaces/account intact. Shared uploaded files stay in the workspace.
- **Transfer ownership:** require recent authentication; target must already be
  an active admin and explicitly accept transfer. Atomically change roles, with
  the old owner becoming admin. Lock membership changes to preserve one owner
  under concurrent requests. Do not implement by deleting the old owner first.
- **Leave workspace:** member/admin can leave; the owner must transfer first.
  Explain that uploaded shared files remain. Leaving is not account deletion.
- **Disable compromised account:** installation operator revokes all sessions
  and disables authentication. Existing worker leases and on-behalf-of jobs must
  honor the established actor/grant fencing rules before further publication.
- **Lost owner access:** operator-assisted recovery with a private audit record;
  no public owner-reset endpoint or default bypass password.
- **Access changes while open:** clear results, previews, document passages and
  playback on authoritative access denial. Stop hidden polling, cancel requests,
  reject stale responses and reset state on account/workspace changes. Refresh
  capabilities on route entry and after permission mutations.
- **Concurrent edits:** return a version conflict rather than overwriting a
  newer role/grant change. UI refreshes permissions and asks for the intended
  change again. Retrying invite acceptance/removal must not duplicate membership.
- **Session expiry:** return to sign-in, clear sensitive in-memory state and
  restore navigation only after authorization. Do not store queries/results in
  persistent browser storage as part of account work.

## 7. Backend boundaries and audit

Add membership/invitation/grant service contracts to the identity/access boundary;
keep ingestion, embedding and evidence resolution in their existing modules.
The frontend consumes action capabilities from the server rather than relying
only on role-name comparisons. Reject unauthorized direct API calls even when
the matching button is hidden.

Proposed APIs, paths subject to implementation review:

| Area | Operations |
| --- | --- |
| Account | Own password change, session list, revoke session/all sessions |
| Workspace People | Authorized paged members, invite, cancel invite, accept invite, owner-only role change, allowed member removal/leave |
| Collection Sharing | Scoped grants, add/change/revoke grant, restricted member picker |
| Ownership | Create/cancel/accept expiring transfer request with recent authentication |
| Capabilities | Current workspace and per-collection allowed actions, bounded and revalidated |

Use existing schema where possible. Add invitation/transfer token hashes,
expiry/consumption state, mutation versions and access audit records through
migrations. Privileged database functions must have a fixed search path and
narrow grants, validate the server-derived actor and own their transaction
invariants; never grant the runtime role arbitrary membership-table writes.

Audit actor, action, workspace, target identifiers, role/grant before/after,
timestamp and outcome for access mutations. Never record passwords, raw tokens,
session cookies, query content, file text or signed content links. Workspace
owners can read their workspace access audit; broader account/operator events
remain operator-only. Bound retention, paging and storage before exposing audit.

Preserve runtime-role RLS for every content path, including originals, vectors,
counts/facets, thumbnails, jobs, citations, playback and generated artifacts.
Any cache must be authorization-scoped and invalidated on changes. Membership,
role changes and ownership transfer must not republish content, rebuild vectors,
change evidence locators or erase original revisions.

## 8. Implementation order and acceptance gates

| Step | Deliverable | Required verification |
| --- | --- | --- |
| A1 | Final permission contract, owner-specific authorization, safe migrations and capabilities | Existing identities/grants preserved; multiple/zero-owner migration cases; direct API role matrix; concurrency and runtime-role tests |
| A2 | Account/session controls and expiring invitations | Single-use/expired/revoked/wrong-account tokens, replay/concurrency, role escalation, rate limits, no token leakage; password/session revocation checks |
| A3 | Owner/admin People UI and owner role changes | Both roles exercised; admin cannot promote/remove admin/owner; member cannot list directory; navigation/state clear on role change |
| A4 | Collection Sharing and permission-aware member Library | Viewer/contributor/manager actions; cross-workspace target denial; manager cannot escalate; counts/snippets/jobs reflect actual grants |
| A5 | Ownership transfer, leave/removal, access audit | Recent-auth/acceptance, one-owner races, pending-invite authority changes, session/worker access recheck, uploaded content retention |
| A6 | Controlled personal-workspace provisioning and onboarding | Quota/workspace limits, separate workspaces isolated, no inherited team-admin access, no unexpected automatic index jobs |
| A7 | Whole-product validation and documentation | Three-role desktop/mobile journeys, access changes during search/playback, keyboard/focus/error checks, running-stack verification and publication leak checks |

A1 is complete; A2–A7 remain pending. Its capability flags describe authorization
policy, not availability of the later account/People/sharing features. Validation
results and the migration's ownership preflight are recorded in
[access validation](access-validation.md).

The persisted grant values stay `read`, `ingest` and `admin`; “Contributor” is
the user-facing name for `ingest`. No grant-data conversion is necessary.

Do not ship a signup button before its backend activation/access behavior is
complete. Prefer invitation-first onboarding, then expand provisioning once
account recovery and resource policies are established. No new dependencies or
production permission changes are authorized merely by this planning document.

Release examples must include Alice as team owner, Bob as team admin, and Carol
as member with different grants on at least two collections, plus an unrelated
workspace. Test all content paths both before and after grant/membership removal.
Run against the actual restricted runtime database role. Preserve existing local
owner credentials, originals, named volumes, citations and active index. Record
measured results and any remaining limits in a dedicated access validation report.
