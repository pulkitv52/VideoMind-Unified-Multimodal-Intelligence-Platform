# Action retrieval and temporal localization plan

Date: 20 October 2026. Status: AT0 review preparation and AT1 exploratory implementation authorized by the user after planning. [Implementation evidence and limits](action-temporal-validation.md) record the CPU pilot. Human adjudication and serving promotion remain pending. No new serving model, threshold or schema is adopted by this plan alone.

## Current decision

The user stopped further action/temporal work after the offline calibration pilot because current search is adequate for their use. AT2 and the remaining action-specific follow-ups are deferred. Preserve the experiments and unchanged live policy; resume only on a new request. This decision does not mark the original Phase 7 quality or release criteria as passed.

## Objective and scope

Retrieve videos that show the requested action, and cite the interval where it occurs. Start with falling, distinguish it from sitting/bending/lying still, then test fighting versus close interaction and walking versus standing. Evaluate location constraints such as "on streets" separately. Work on the existing Ryzen 7 7730U laptop with about 15 GiB RAM and no GPU. Keep EmbeddingGemma 2 as the core cross-modal model. An auxiliary action model is an experiment requiring a measured benefit and a later implementation decision.

This is a Phase 7 improvement work package, not a new declaration of MVP completion. The original release gates in [architecture section 9](architecture-proposal.md#9-evaluation-and-benchmarks) remain in force. GPU deployment, scale, generated answers, new dataset downloads and automatic incident alerts are outside this plan.

## Evidence behind the plan

The active corpus has 46 assets and 197 vectors. Native visual preprocessing uses 12-second windows, two seconds of overlap and 1 fps. [Current recipe](../backend/src/videomind/preprocessing/media/profile.py). The pinned core model is `google/embeddinggemma-2`, revision `914f7f89142e33e77833254d9c9b90c3cef7303b`; the active profile is recorded in the [corpus manifest](../evaluation/manifests/phase7-corpus.json).

These are measured scores against that generation, not classification probabilities:

| Query | Native video window | Cosine | Current outcome |
|---|---|---:|---|
| person falling | CAVIAR Rest_FallOnFloor, 30.000–40.560 s | 0.700353 | Accepted |
| person falling | UR Fall fall-04, 0.000–3.203 s | 0.691237 | Rejected |
| person walking on streets | The same CAVIAR lobby window | 0.664069 | Rejected |
| person walking on streets | CAVIAR LeftBag, 20.000–32.000 s | 0.660231 | Rejected |

The user identified UR Fall fall-04 as the relevant example; its preview visibly contains a fall. The request also expects the CAVIAR asset to remain discoverable. That does not make the specific 30–40.56-second CAVIAR window a verified fall interval. Review its full original and locate the actual event before assigning temporal ground truth. Filenames and similarity scores cannot supply action labels.

The [score report](../evaluation/reports/query-scene-scores.json) retains profile/generation IDs, citation IDs, scores and original-time intervals. [Preview clips and frames](../evaluation/reports/query-scenes/) were extracted from checksum-verified retained media. They are diagnostic evidence, not a new index.

Importantly, UR Fall is already present among raw dense candidates. The current 0.70 filter is applied during ranking, after candidate retrieval. The immediate defect is acceptance/calibration; a failure to retrieve candidates has not been established for this example. Increasing the candidate budget alone cannot fix its rejection.

A previous paired four-second experiment at 1/2/4 fps left fighting scores near 0.626–0.629 and increased encoding time substantially. [Phase 7 measurements](phase7-validation.md). Shorter windows and more frames are hypotheses to evaluate, not established fixes. Current warm p95/p99 are 4.43/5.19 seconds, already above the 2/5-second targets. Add no synchronous heavy action inference by default.

## Proposed retrieval flow

1. Decode, sample and map media in workers; retain immutable originals and integer source PTS mappings.
2. Store coarse visual windows and, if experiments justify them, finer windows under a new producer recipe.
3. Generate authorized native-video candidates with a generous bounded budget. Keep raw candidates separate from final accepted results.
4. Optionally score candidates with a validated temporal/action branch using precomputed features. Its absence or unsupported action is explicit.
5. Rank and apply a calibrated acceptance policy. Preserve native evidence independently of attribution text, OCR and ASR.
6. Return a versioned citation for the supported original-time interval. Playback seeks to it and shows its boundaries.

Metadata documents may appear in an all-types search, but a document mentioning an action must not establish that the referenced video shows it. Video-only search stays restricted to video assets. A future attribution-to-media link would be a separate relationship labelled "related file", not a visual match or a transferred score. Do not silently infer "Video only" from query wording; mixed-source queries remain supported.

## Work packages and decision gates

The user has requested implementation. AT0 preparation and AT1 exploratory runs are underway; later packages remain conditional on their preceding evidence gates. Each package produces a report before the next dependent package starts.

| Package | Work | Deliverable and exit condition |
|---|---|---|
| AT0: establish labels | Review existing videos, define event boundaries, preserve a baseline and lock development/held-out groups | Versioned annotations, review worksheet and baseline replay; unresolved intervals remain unknown |
| AT1: test admission and windows | Sweep native-video acceptance policies offline; compare whole-clip multi-duration windows against the current recipe | Fixed-budget quality/resource report; no serving change; stop an approach if it adds false matches or has no useful gain |
| AT2: test action features, conditional | Only if AT1 leaves action confusion: benchmark one auxiliary temporal/action approach selected from the research note | Pinned model/runtime/license record, CPU benchmark, ablation with/without the branch; reject if memory, coverage or quality fails |
| AT3: calibrate ranking and boundaries | Choose thresholds on development data; evaluate temporal proposals, deduplication and any action reranker on locked held-out groups | Frozen policy and promotion report, including false-positive examples and unsupported queries |
| AT4: integrate the winning approach | Add bounded worker jobs, provenance, complete generation publication, authorized retrieval and playback interval UI | Integration/security/crash tests, before/after replay, feature flag and rollback exercise |
| AT5: assess release | Rerun the frozen evaluation and resource workloads | Updated Phase 7 assessment; failed original gates stay open |

AT1 is the recommended first technical experiment after AT0. A new action model is not a prerequisite. If no approach meets the acceptance criteria on this laptop, retain the baseline and document the measured blocker. Do not mark the experiment successful by lowering its criteria after seeing test results.

## AT0: annotation and evaluation protocol

Begin with the ten retained UR Fall clips (five fall, five ADL), plus CAVIAR Rest_FallOnFloor, Rest_InChair, Walk1 and Fight_Chase. Review the five Roadscapes clips for location-constrained queries; label visible people and actions only when the footage supports them. This provides 14 core clips and five context checks, not the 200-asset release corpus. Add other retained CAVIAR interactions as hard negatives only after review confirms their contents.

For each event record asset/revision/hash, original track, action, start/end in milliseconds, visibility/occlusion, scene context, reviewer identity, uncertainty and label provenance. Keep publisher frame labels separate from human observations. UR Fall synchronization CSVs contain timing/accelerometer data, not precise fall-action intervals.

Use this provisional boundary convention, to be agreed before annotation: fall start is the first visible transition from the preceding stable posture toward the floor; fall end is the first settled floor posture after contact. Label lying still afterward separately. Record ambiguous or occluded boundary ranges and adjudication rather than inventing exact timestamps. Fighting and walking need their own observable boundary definitions before joining temporal metrics. Do not infer violence, medical state or intent from proximity or a fall label.

The user's identification of fall-04 is useful development feedback, not two independent annotations. Release-quality labels still need two independent human reviewers and disagreement resolution. Agents may prepare worksheets and publisher mappings; they may not mark their own reviews as independent human gold.

Group all windows, crops, duplicate files and query paraphrases of a source sequence together. Where actor/session identity is known, group it too; record unknown identities as a leakage limitation. Select development and held-out groups before experiments, keep held-out groups untouched during calibration, and include a cross-dataset check when possible. The demonstrated clips and queries are development regressions, not an unseen test set. If data cannot support both calibration and a meaningful held-out set, report a pilot only.

Include hard negatives and paired wording: falling versus sitting/bending/lying, fighting versus standing close, walking versus standing, walking indoors versus walking on a street, a person on a street versus driving along a road. An unreviewed street clip is not a confirmed negative. Use the same query families across all ablations.

## AT1: bounded experiments with the existing model

First replay the frozen generation and save unfiltered candidate scores, accepted groups, citations and timings. Preserve native-video, derived-text and all-types results separately.

Test acceptance floors of 0.65, 0.675 and 0.70 for the native-video branch on development data. Also record top-k before acceptance as a diagnostic ceiling. These are trial values, not adopted defaults. Keep document/audio/image behavior fixed. Since 0.65 would also admit the indoor CAVIAR window for the street query, the fall regression alone cannot justify it. Evaluate a low candidate floor followed by final acceptance separately from simply showing every candidate.

Next test one segmentation variable at a time:

| Recipe | Duration / stride | Sampling | Purpose |
|---|---|---|---|
| Baseline | 12 s / 10 s | 1 fps | Reproduce current results |
| Short | 4 s / 2 s | 1 fps | Test dilution by unrelated movement |
| Fine | 2 s / 1 s | 1 fps | Test boundary resolution and missing short actions |
| Optional follow-up | Winning duration/stride | 2 fps | Test motion sampling only if duration improved results |

Use all windows of each selected clip, including non-action portions. Do not choose a ground-truth event window for the retrieval benchmark. The earlier oracle-window experiment remains a separate diagnostic. Apply the same total candidate and result budgets to each recipe; report vector-count and storage growth. Multiple overlapping windows from one asset must not multiply relevance votes or occupy the result list unchecked.

Start with the short UR Fall corpus. Preflight duration/window counts and processor token limits. Encode at most 32 new windows per resumable batch with a proposed 20-minute batch wall budget; record incomplete runs and resume from producer/input/profile-keyed private caches. Complete every declared batch before reporting a recipe's quality. Expand to longer CAVIAR clips only after a useful pilot result. These are experiment limits, not measured throughput promises.

Keep one heavy CPU job at a time, two model CPUs and the existing 6.5-GiB embedding container ceiling. Preserve service timeouts, media decode limits and no-silent-truncation behavior. Record total platform memory, per-process high water, available host memory and swap activity. Stop on resource exhaustion; do not hide it with smaller unreported input subsets.

## AT2: optional action and temporal features

Read [the primary-source options note](research/action-temporal-options.md) before selecting an approach. Motion proposals can suggest where to look; camera movement, shadows and scene changes can also trigger them. Pose landmarks can help describe body transitions but depend on a visible, sufficiently large person. Neither establishes an action by itself.

A fixed-class action classifier may help falling or fighting only if its label set and training domain support those concepts. It does not automatically support arbitrary semantic queries such as "walking on streets". A text-video model can support open-vocabulary scoring but may have larger CPU costs and still lack reliable event boundaries. No model name, weights or runtime is selected by this plan.

Benchmark preprocessing, native runtime/export compatibility, model load time, inference per clip, peak memory, frame-order sensitivity, action confusion and missing-person behavior. Compare against the existing model on exactly the same clips. Where person crops are tested, keep the full frame too so location/context is not lost; map crop coordinates and times back to the original.

Compute action features offline in workers. A query should reuse them rather than launch a large decoder/model cascade. Do not load a second heavy model alongside the resident embedder without a measured memory budget. If a controlled unload/reload or maintenance window is required for a prototype, document that dependency and the availability cost before execution. Quantization or a different encoder requires its own validity and quality checks.

## AT3: ranking, calibration and temporal proposals

Keep asset-level action presence, temporal overlap and scene context as separate evaluation signals. Cosine is not a probability. Action logits, pose features and a different model's cosine are not directly comparable to EmbeddingGemma cosine. Use separate branches and rank fusion as a baseline, or a calibrator trained only on development labels; persist its parameters and training-data version. Compare the result against every contributing branch to catch regressions.

Distinguish a broad retrieved window from a refined event proposal. Only return a refined interval when an implemented method supports it. Otherwise cite the broad window and label its granularity. Never tighten playback to the middle of a window and claim that this localizes the action.

Test temporal suppression of overlapping proposals with a fixed, versioned overlap rule. Merge adjacent intervals only with evidence of a continuous event; retain the contributing segments and score provenance. Do not merge all similar windows across an entire lobby video. Repeated actions should produce separate intervals. Playback boundaries remain half-open original-time intervals, and presentation keeps both the retrieved window and refined event available for inspection.

## Module and persistence boundaries for later implementation

| Owner | Proposed responsibility |
|---|---|
| `preprocessing/media` | Window proposals, bounded sampling/decoding, PTS and crop transforms; no retrieval policy |
| `embeddings` | Pinned native/optional auxiliary producer adapters, validity, durable jobs, compatible profiles and publication |
| `retrieval` | Authorized candidate scopes, action/temporal branch fusion, acceptance, diversity and final rechecks |
| `evidence` | Original-time anchors, transform resolution, retained producer relationships and authorized playback |
| `frontend/features/evidence` | Actual interval display/seek/highlight; no browser-side event detector or invented confidence |
| `evaluation/quality` | Annotation adapters, ablations, calibration, held-out metrics, resource and failure reports |

Reuse immutable asset revisions and segment/evidence relationships. A new window recipe creates a new segment set and producer fingerprint. Persist model/processor revisions, frame order and timestamps, preprocessing/sampling/crop hashes, action label vocabulary, feature schema and calibration policy version. Audit whether the embedding profile fingerprint covers every changed input recipe before reuse; never silently reuse stale vectors.

Optional action proposals should retain parent window IDs, producer ID, original start/end/track and supported action/score semantics. Add a feature/proposal relation only if an adopted prototype requires it; this document does not authorize a schema migration. Reuse existing evidence locators where they can express the result truthfully.

Never compare vectors across incompatible profiles. The current embedding storage is 768-dimensional: an auxiliary model with a different dimension needs a deliberate table/index migration or separate feature storage, not padding or insertion into the existing vector column. Physical index splitting remains unnecessary for this pilot; exact cosine remains the local baseline.

A new generation must publish complete membership transactionally, preserve the other modalities and remain rollback-capable. Make clear whether one video family is replaced or coarse and fine representations coexist; do not silently drop documents/audio/images while building a video experiment. Apply current RLS and tombstone/revocation checks to candidate features, proposals, snippets, thumbnails, citations and playback. Resumption, duplicate delivery and worker death must not publish partial or stale work.

## Proposed acceptance criteria

These are targets to approve before implementation and freeze before experiments, not measured achievements or replacements for the original Phase 7 gates.

| Area | Acceptance |
|---|---|
| Demonstrated fall regression | UR Fall fall-04 appears in top 10 for the agreed fall query family; retain CAVIAR asset relevance only where human review supports it, with a reviewed event interval rather than forcing 30–40.56 s as gold |
| Hard-negative protection | On reviewed negatives, false-useful rate at most 0.10; report all false positives and answerable rejection separately, with counts and family-level intervals |
| Video retrieval | Held-out action slice Recall@10 at least 0.85 and nDCG@10 at least 0.70; inspect by fall/fight/walk and context query, not only aggregate |
| Temporal localization | Correct-asset temporal Recall@10 at IoU at least 0.5 reaches 0.80; report IoU 0.3/0.5/0.7, median/p90 boundary errors, and events of at most two seconds separately |
| Boundary precision | Proposed pilot target: median absolute start error at most one second on reviewed visible-boundary events; list uncertain/excluded cases and denominators |
| Existing modalities | No more than 0.02 absolute nDCG regression on a primary modality slice against the stronger baseline; use gold labels for release eligibility |
| Source integrity and access | Every returned proposal/citation resolves to the correct immutable revision/time/track; runtime-role revocation, deletion and cross-source tests pass |
| CPU response | Original warm end-to-end p95 at most two seconds, p99 at most five seconds, with failed/busy requests retained; current measurements fail these targets, so no latency waiver is inferred |
| Resources and robustness | Stay inside adopted resource limits; report new vector/storage cost, encode throughput, restart/retry behavior, and concurrent-ingestion busy/success counts |
| Promotion | Freeze producer/profile/policy and report before/after held-out results, human-review status, model/license/runtime checks, original preservation, generation cutover and rollback |

A small pilot can demonstrate a regression fix or reject an approach. It cannot satisfy independent gold evaluation or erase the existing corpus-size, annotation, backup and release blockers. If a target is unmeasured or missed, keep that gate open.

## Deliverables and future handoff

The next implementation should begin with AT0, then AT1. Deliver versioned annotation files and review instructions, a frozen baseline/configuration manifest, a complete experiment report, and an explicit recommendation to retain or replace the baseline. Record negative results as well as improvements. Only proceed to AT2 if needed; only integrate a winner after AT3 evaluates it.

Expected future artifacts are an action/temporal annotation version, experiment manifest, native-window ablation report, optional auxiliary CPU feasibility report, calibration/held-out report and updated Phase 7 assessment. They do not exist merely because this plan names them. Keep exact query wording, grouping/splits, source/code hashes, candidate/result budgets, profile IDs and resource conditions in every report.

Open questions: Do the retained clips support independent actor/session splits? What are the reviewed CAVIAR fall/fight boundaries? Does the new representation improve unseen actions or only the demonstrated examples? Can any auxiliary model fit the laptop without degrading interactive availability? How much improvement comes from ranking/calibration versus action representation? Which boundary definition is reproducible between reviewers? Resolve these through the staged evidence above, not assumed answers.

## Implementation tracking

AT0 protocol/review preparation is implemented; independent human event and absence labels remain pending. AT1 completed all three bounded native-window recipes and documented their acceptance/ranking tradeoffs. See [the measured validation](action-temporal-validation.md). AT2 is conditional, AT3 needs reviewed temporal labels and calibration evidence, and AT4/AT5 have not promoted or released a new serving approach.
