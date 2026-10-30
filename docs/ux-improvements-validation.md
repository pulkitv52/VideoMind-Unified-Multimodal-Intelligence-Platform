# Library, search and evidence improvements

26 October 2026. Implements the user's request to improve the add-files → search →
verify journey. This extends the earlier UX0–UX2 milestone and delivers the core
preview and Library work from UX3–UX5. It does not declare all UX6 usability and
accessibility criteria complete or change the Phase 7 release gate.

## Adopted behavior

- Search is the default home for existing accounts, including administrators.
  Signup still opens Library. Dashboard retains its explicit route and access rules.
- Library offers Add files with an existing writable destination or creation of a
  new upload collection. Invalid files do not create an empty collection. Existing
  collection creation and read-only folder sync remain available.
- File chooser and drag-and-drop share sequential, bounded upload handling. Each
  file has an outcome; a failed middle submission does not hide earlier successes
  or stop later independent files. Retry resends only failed/unsent submissions to
  the original destination. Navigation keeps the upload owner mounted; sign-out
  or workspace unmount aborts outstanding client work. Aborting a request does not
  undo a receipt already committed by the server. Upload receipts do not claim
  that validation, extraction or publication has finished.
- Library loads and polls files only for the selected collection. Previously
  visited collection state and in-flight uploads stay mounted. Existing 50-file
  paging and server totals remain authoritative.
- A shared file-state mapper distinguishes validation, content processing, search
  preparation, unpublished embeddings, stopped work, failure and active membership.
  Mandatory failures take precedence. Only `embedding_status=indexed` qualifies
  as Ready to search. Partial-content warnings remain visible. Processing details
  expose stage errors, permitted retries and original download; failed rows open
  those details. The latest revision's pending state makes no claim about older
  searchable revisions.
- First-use copy respects the implemented self-service preparation policy.
  Configured workspaces prepare automatically. Global build/activate/restore
  controls remain administrative; manual setup is linked rather than automated
  by this UI change.
- Individual filter removal preserves other selected filters. A submitted result
  retains its original query/scope until a new search succeeds. Ranking, filters,
  abstention, text/image payloads and immutable citations are unchanged.
- Result titles open evidence. The desktop inspector has previous/next match
  navigation and a pointer/keyboard divider (arrow keys, Home, End). Document
  passage reveal scrolls the inspector, preserving the outer results position.
  Compact evidence retains its inert background and Back to results control.
- Smaller headings, quieter hover effects and clearer file rows reduce visual
  competition. Primary button foregrounds were adjusted for contrast in both
  themes. No new framework, font request, analytics or content persistence was added.

## Preview contract and bounds

An optional `preview` on each evidence result identifies an existing page image,
standalone image or sampled video frame: kind, protected route family, object ID
and exact segment-set ID. Source and revision come from the result's immutable
asset reference. Audio/text/missing/oversized previews have useful type fallbacks;
no waveform, thumbnail producer, generated caption or confidence percentage is
invented.

The evidence module resolves metadata with one runtime-role SQL batch for at most
30 returned results. Joins enforce workspace/source/revision/set/citation identity,
ready sets and nondeleted assets. Media frames must belong to the same set's media
artifacts. Only PNG/JPEG objects up to 4 MiB qualify. Existing byte endpoints
independently reauthorize every request, including historical revisions; the
metadata descriptor is not a capability or a storage key.

The frontend observes proximity to the viewport and fetches at most three preview
images concurrently. Object URLs are released on replacement/unmount. Missing
previews retain operable results; expired sessions trigger the existing identity
reset. No per-result document/segment-list hydration, producer write or shared
content cache is added.

## Verification

- `python3 scripts/dev.py verify`: **232 passed in 310.54 seconds**, with the existing Starlette/httpx deprecation warning. This includes runtime-role search and page/image/frame preview tests, unchanged retrieval facts when preview metadata is absent, one metadata batch for ten results, guessed object/set denial, grant revocation, tombstones and historical-revision bytes.
- `pnpm --dir frontend build`: strict TypeScript and Vite production build passed.
- Separate strict TypeScript check of `tests/product.spec.ts` and `playwright.config.ts`: passed.
- `pnpm --dir frontend test:ui`: **70 desktop/mobile checks passed in 1.1 minutes** on the final run. Tests cover uploads, partial failures, retry destinations, drag-and-drop across navigation, lazy collection loading, publication-aware status, text/image queries, filter removal, divider keyboard controls, citation history/clipboard, preview failure/success/concurrency and document scroll preservation.
- Light/dark Library and evidence captures inspected at 1440 and 360 CSS pixels. Inspection found and fixed whole-page passage scrolling and a squeezed mobile toolbar. Single-result evidence no longer shows disabled previous/next controls. Existing 320-pixel reflow checks remain included.
- `python3 scripts/check_repository.py worktree` and `git diff --check`: passed.

Earlier runs exposed invalid synthetic preview fixture values/JSON serialization,
which were corrected before the passing full backend run. Browser test selectors
were corrected for scoped status messages and off-screen lazy previews. One
concurrent-run mobile page-load timeout was followed by a separate browser run.
Private execution logs and synthetic screenshots remain under ignored `.local`.

Browser fixtures are synthetic; runtime-role API checks use isolated database
fixtures and actual protected image byte paths. Neither establishes improved
relevance or successful independent user testing.

## Remaining limits

Independent task-based usability sessions, exhaustive screen-reader/a11y audits,
all-media live visual validation and the original complete UX6 matrix remain
separate validation work. Small previews reuse existing derivatives; objects over
4 MiB fall back to type presentation. Upload transport has no resumability,
cancellation rollback or byte-progress contract. Network interruption can leave an
unconfirmed server receipt, so retry is not a claim of exactly-once delivery.

The user subsequently authorized deployment. The API and frontend were rebuilt
and recreated locally; details are recorded below. Existing private files,
credentials, volumes, model profiles and publication policies are preserved. No
commit or push was made.

## Local deployment

The user authorized deployment on 26 October 2026. Built the `api` and `frontend`
images and recreated only those services with `up -d --no-deps --wait`. Both
reported healthy. No database, storage, broker, worker or model-service container
was recreated by that deployment command; no migration or configuration change
was required.

An authenticated Chrome smoke against `http://127.0.0.1:8080` verified the new
Search home, live protected previews and evidence for image (2 returned matches),
scanned document (10 matches) and video (1 match). The video reached playable
ready state. Library exposed collection selection and Add files; its upload
chooser and 360-pixel mobile reflow passed without uploading or disconnecting
anything. The initially selected Library collection was a read-only folder, so
the upload check used the explicit Add files flow rather than assuming every
collection supports uploads. These observations establish functioning deployment,
not relevance quality. Private live captures and the smoke report remain in
`.local/ux-deployed-*`.

`python3 scripts/dev.py verify` against the deployed stack passed **232 tests in
200.85 seconds**, with the existing Starlette/httpx deprecation warning. The
repository worktree guard and whitespace check also passed.
