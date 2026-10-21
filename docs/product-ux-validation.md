# Product and UX validation checklist

Date: 21 October 2026. Status: **UX0–UX2 implemented; first-milestone checks passed within the scope recorded below. UX3–UX6 pending.**

This checklist accompanies the [product and UX plan](product-ux-plan.md). It separates executed first-milestone checks from the remaining full-interface matrix. Historical platform tests and README screenshot captures do not count as validation of the new interface.

## Execution record

Complete this table during each implementation step. Link to sanitised evidence; keep private logs and content under ignored `.local` paths. Distinguish deterministic fixtures, real-stack tests, real-model observations and human usability sessions.

| Step | Commit or working state | Commands and environment | Result | Evidence and limitations |
| --- | --- | --- | --- | --- |
| UX0 | Working tree, 21 October 2026 | Source/API review and typed route design | Decisions recorded | Preview descriptor selected for UX3; current contracts unchanged |
| UX1 | Working tree, 21 October 2026 | `pnpm --dir frontend build`; `pnpm --dir frontend test:ui` | Build and browser checks passed | Search/Library/Settings shell, workspace handling and shared styles |
| UX2 | Working tree, 21 October 2026 | Expanded browser suite, 24 checks in 17.4 s | Passed for synthetic journeys | Live evidence checks and broader acceptance recorded below |
| UX3 | Not started | Not run | Pending | Preview contract and access checks pending |
| UX4 | Not started | Not run | Pending | Library and onboarding pending |
| UX5 | Not started | Not run | Pending | Settings and operational states pending |
| UX6 | Not started | Not run | Pending | Complete regression and usability checks pending |

## Journey checks

The matrix below defines the full interface acceptance scope. First-milestone results are recorded separately below; unrecorded cases remain pending. A fixture check does not imply real-backend authorisation or full product acceptance.

| ID | Scenario | Required observation |
| --- | --- | --- |
| J01 | New administrator with no files | Add collection/upload is discoverable; no unexplained index jargon |
| J02 | New member without index permission | Clear explanation and contact-admin action; no enabled admin controls |
| J03 | Upload a document and short video | Received/preparing/failed/ready states reflect actual stages and publication |
| J04 | First index creation and activation | Explicit admin actions; incomplete/failed/zero-eligible conditions are explained; no partial activation |
| J05 | Add a file with an existing active index | Existing searchable files remain usable; latest pending revision is not labelled published |
| J06 | Text search with collection/type/advanced filters | Actual filter semantics, ordered results and labels preserved |
| J07 | Image search | File limits, ephemeral preview, replacement/error cleanup and actual endpoint preserved |
| J08 | Open document, image, video and audio matches | Exact citation revision/set/locator resolves with correct original context |
| J09 | Inspect and switch results | Desktop results remain available; selection and original-time/page mapping stay correct |
| J10 | Copy/reopen an existing citation URL | Existing URL format survives refresh/sign-in; only authorised workspace opens |
| J11 | Clipboard permission denied | Selectable citation fallback; no false copied confirmation |
| J12 | Small-screen evidence and browser Back | Return restores query, filters, image where still in memory, result order and scroll |
| J13 | New search outruns an older response | Older response cannot replace the newer query; previous results clearly labelled while pending |
| J14 | No useful evidence vs busy vs service error | Distinct truthful messages; no automatic relevance-policy changes |
| J15 | Partial extraction/transcription and failed stages | Available evidence has visible limitations; retries target the authorised failed stage |
| J16 | Multi-file upload with a failed middle item | Per-file outcomes are accurate; successful uploads preserved; only failed/unsent items retried |
| J17 | File chooser and drop area | Both accessible; documented size/format guards; no implied resumability or byte progress |
| J18 | Folder import and sync | Only allowlisted read-only area; existing bounds, unchanged/revision behavior and retries preserved |
| J19 | More than 50 files | Cursor pagination and authorised totals work; partial-list filtering is labelled |
| J20 | Collection disconnect | Existing confirmation/consequences; imported evidence unavailable after committed disconnection |
| J21 | Index rebuild, failed activation, retry and restore | Existing admin capability, complete publication and caught-up restore requirements preserved |
| J22 | Refresh, sign-out, session expiry and workspace switch | No cross-workspace query/results/preview bleed; image URLs and media resources cleaned up |
| J23 | Member versus administrator Settings | Member sees no storage/index aggregate disclosure or unsupported operation |

## Preview and backend checks

| ID | Check | Required observation |
| --- | --- | --- |
| S01 | Foreign workspace/source/citation/object IDs | Generic denial with no hidden filenames, snippets, counts or preview bytes; actual runtime DB role exercised |
| S02 | Preview object provenance | Same workspace/source/revision/set as the result; no arbitrary object selection or raw storage keys |
| S03 | Permission revoked after search | Next preview/evidence/playback request denied; clear affected UI when denial is observed; no claim that already delivered bytes can be revoked |
| S04 | File replaced after result/citation obtained | Historical citation and preview resolve the original revision while authorised; no accidental latest-revision substitution |
| S05 | Missing preview, audio-only result, failed preview load | Useful type fallback; result and evidence remain operable |
| S06 | Bounded preview work | Descriptor lookup is batched; only visible result images loaded with bounded concurrency; no full document/segment-list fetch per hit |
| S07 | Caches, logs and external requests | No content or query persistence, service worker content cache, external asset beacon, raw credentials or signed public links |
| S08 | Range and temporal mapping | Existing 206/416/HEAD behavior, nonzero-origin/variable-frame-rate alignment and original-time seeking preserved |
| S09 | Publication and retries | Preview additions cannot bypass active membership, stale-task fences or transactional publication |
| S10 | Retrieval regression | With fixed query/corpus/profile, ordered matches, scores, filters, warnings, snippets and citation/context identity remain unchanged, apart from separately documented optional preview metadata |
| S11 | No model or producer change | Model/profile/configuration and frozen labels unchanged; no derivative writes on preview requests |

## Accessibility and responsive checks

| ID | Check | Required observation |
| --- | --- | --- |
| A01 | Keyboard-only complete journey | Sign-in, navigation, upload, filters, result selection, playback, copy and return work without a pointer |
| A02 | Focus and semantics | Labelled controls, logical headings/landmarks, visible focus, deliberate panel focus and restoration; no keyboard traps |
| A03 | Dialogs | Creation/confirmation dialogs trap/restore focus; Escape dismisses appropriate overlays without losing completed uploads |
| A04 | Status and errors | Loading/completion/failure announced appropriately; polling and playback do not create repeated noisy announcements |
| A05 | Contrast and selection | Applicable WCAG 2.2 AA contrast checked; selected results/passages and errors distinguishable without colour alone |
| A06 | Reflow and sizes | 360/768/1024/1440 widths plus 320-pixel reflow and zoom checked; no clipped actions, hidden focus or horizontal page overflow |
| A07 | Pointer, reduced motion and text | Usable touch targets, no hover-only essential actions, reduced-motion support, long filenames and large text handled |
| A08 | Imported content limits | Available transcript/OCR alternatives labelled; missing/inaccurate content alternatives documented rather than claiming full conformance |

## Real-model and product checks

Run the requested video examples serially against the unchanged policy. Record the query, returned file and interval, whether evidence opens, and whether inspection supports the requested event. A working viewer is a functional pass; an incorrect action match remains a relevance limitation.

| Query | UI/evidence check | Relevance assessment |
| --- | --- | --- |
| person falling | Not run for new UI | Existing demonstrated interval starts after descent; verify and report honestly |
| person bending down | Not run for new UI | Inspect the clip; no assumed independent gold label |
| men entering an empty room | Not run for new UI | Existing example shows one person in a furnished room; no exact-match claim |

Use document, standalone-image, spoken-audio and non-speech-audio fixtures as well. Do not force every text query to produce a result, lower thresholds for screenshots, or treat attribution text as visual proof. Compare real-model runs only when profile/corpus/configuration are controlled; do not run heavy integration fixtures and model examples concurrently.

For task-based user sessions, record role, task completion with/without assistance, confusing terms, errors and understanding of imperfect matches. Participant recruitment and observations are pending. No usability success percentage or time saving has been measured.

## Commands and evidence to record

During implementation, use the locked project tools:

```bash
pnpm --dir frontend build
python3 scripts/dev.py verify
python3 scripts/check_repository.py worktree
```

UX0 selected pinned `@playwright/test` 1.62.1 with the installed Google Chrome channel. Run `pnpm --dir frontend test:ui`; the configuration starts a loopback fixture test server on port 4174. Install Chrome separately on a new host. No browser download is part of application startup. The new development dependency and lockfile are committed only when a commit is requested. Add scoped runtime-role preview/evidence regression commands when the contract is implemented. Use the existing phase acceptance scripts only for the features changed, and record service restarts or fixture mutations before running them.

Capture Search, Library, onboarding, Settings and evidence at representative desktop/small-screen sizes, including failures and no-results. Review images visually and inspect metadata before selecting public documentation assets. Keep rejected/raw private captures ignored. Preserve attribution for public research footage. Update README screenshots only after the implemented UI has passed its journey checks.

Before a requested commit, scan staged blobs and the staged diff. Before a requested push, scan committed history. Keep original Phase 7 assessment and reports intact; completing UX0–UX6 is not permission to mark that release gate passed.

## First-milestone test record

The frontend strict TypeScript check and Vite production build passed. The isolated browser suite passed **24 checks in 17.4 seconds**, using twelve scenarios at desktop 1440×1000 and mobile 360×800. The reflow scenario also explicitly checks 320 CSS pixels. Node 24.21.0, pnpm 12.10.1 and Playwright 1.62.1 were used on this host.

Fixture scenarios cover legacy/malformed citation routing; lazy Library mounting; retained text/results across navigation and browser Back; member versus administrator settings and storage-request separation; document citation/page/span selection; evidence open/back/forward; mobile background inertness; clipboard denial; stale response ordering; ephemeral image-query payload and state; no-index/no-result/busy distinctions; 320-pixel overflow checks; truthful collection loading; and browser Back dismissing Library dialogs. These checks support portions of J02/J06/J07/J08/J09/J10/J11/J12/J13/J14/J23 and A06. They do not prove complete accessibility, all imported media, real grants/RLS or backend publication correctness.

The first run had 17 passes and three failures. Two no-result assertions targeted the wrong workspace fixture, and one assertion incorrectly treated Playwright's role locator as proof of native inertness. The mobile check prompted a real improvement: the header, navigation and footer also become inert while full-screen evidence is open. The fixture and assertion were corrected. A subsequent run had 19 passes and one blank-page timeout while frontend edits/hot reload were still occurring. A clean 20-check run passed in 21.6 seconds with stable source. Two new scenarios then covered loading versus empty collections and closing Library dialogs on navigation; the expanded 24-check run passed in 27.9 seconds. The final mobile background-scroll fix was then checked in the same 24 scenarios, all passing in 17.4 seconds. No test retries or disabled cases were used to obtain it.

Pending UX3–UX6 work includes real preview contracts and isolation checks, selected-collection Library, upload/drop-area outcomes, unified file readiness states, complete onboarding, comprehensive accessibility and task-based user sessions. Existing index operations have been moved and relabelled, but this is not completion of all UX5 checks. The full platform Phase 7 release gate remains open.

### Real local-stack observations

The frontend container was rebuilt with its frozen pnpm lockfile and restarted by itself using `docker compose --env-file .env -f infra/compose/compose.yaml up -d --build --no-deps frontend`. Backend services and named volumes were preserved. The real browser checks below used that rebuilt interface on localhost:8080, not fixture interception.

| Check | Observation |
| --- | --- |
| Text → video evidence | `person bending down` with video filter returned UR Fall ADL 28; the panel opened its 0–2.841-second citation. Browser video reported ready state 4, original time 0, duration 2.839333 s. |
| Text → standalone audio | Electronic-beeping query returned `beeps.wav`; audio opened at time 0, ready state 4, duration 3 s. |
| Text → document/OCR | Electrical-panel question returned four document groups. The scanned-page OCR result opened the cited page and highlighted the passage `opening the safety panel.` |
| Text → standalone image | Orange-cat query returned both accessible copies of `chelsea.png`; one opened its original-image evidence and citation controls. |
| Citation action | Copy citation succeeded in the real video viewer. Denied clipboard access is covered separately by the deterministic browser suite. |
| Navigation/Settings | Real Library and Settings opened. Settings showed the existing active coverage of 46/46; no index build, activation or restore was invoked. |

The document question initially failed twice in the browser with `Failed to fetch`. A direct authenticated local HTTP check returned 200 with four groups in 2.89 s, and an explicit browser retry then succeeded. The failed observations are retained here; this is not a zero-error latency benchmark. Network failures now receive a plain-language connection/retry message and previous successful results retain their original query/scope labels.

Only synthetic or licensed public content was inspected. No user originals were uploaded, removed or replaced for these checks. API search configuration, model, producer profiles and stored index membership were not changed. All-media seek accuracy, exhaustive Range behavior and source-grant revocation remain part of the existing backend regression suite and the later complete UX6 matrix, rather than being inferred from these four UI smoke observations.

### Final running-stack and publication checks

`python3 scripts/dev.py verify` passed **199 tests in 164.18 seconds**, with the existing Starlette/httpx deprecation warning. Its private output is retained in `.local/ux-foundation-verify.log`. The earlier verification session ended before a final result could be collected after the interrupted turn, so this recorded run was made with a retained private log. It is the result used here.

The final frontend production build passed. The Playwright configuration and test source also passed a separate strict TypeScript check:

```bash
pnpm --dir frontend exec tsc --ignoreConfig --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --types node tests/product.spec.ts playwright.config.ts
```

All 12 repository-guard regression tests passed. Browser report/capture directories are now ignored and rejected by the guard even if force-added. Worktree leakage scanning and `git diff --check` passed. No commit or push was made.

Final local desktop/mobile visual checks used the rebuilt production frontend. The original citation opened the mobile evidence view; its page background is inert and scroll-locked, and closing evidence restores normal scrolling. Desktop and mobile captures are private under `.local`, outside Git. These screenshots are review aids for this milestone; published README captures remain labelled as the earlier validated interface until the complete UX6 refresh.

The original Phase 7 assessment is unchanged. This milestone neither adds result thumbnails nor completes selected-collection browsing, drag-and-drop uploads, the unified file-state mapper, full onboarding, exhaustive accessibility or independent usability sessions. Those remain UX3–UX6 work.
