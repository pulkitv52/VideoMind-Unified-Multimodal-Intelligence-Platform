# Action and temporal pilot validation

Date: 20 October 2026. The user authorized starting the documented plan. AT0 review preparation and AT1 exploratory experiments are implemented. The live model, producer recipe, 0.70 search cutoff, original media and active generation remain unchanged. This report does not declare AT0 human adjudication, temporal localization or the Phase 7 release gate complete.

## What is implemented

`evaluation/action_temporal` owns the frozen protocol, review preparation/validation, authorized current-index replay, private resumable native-window experiments and fail-closed assessment. `scripts/evaluate_action_temporal.py` exposes `prepare`, `baseline`, `windows` and `assess`. The only shared change adds a response-start deadline and pre-cache validation to the existing operator encoder bridge. There is no new application endpoint, worker producer, database migration, model dependency or browser inference path.

Preparation re-downloaded and hash-verified the 46 authorized originals through the existing API, then pinned 19 clips: ten UR Fall sequences, four CAVIAR event/context sequences and five Roadscapes location checks. The [frozen protocol](../evaluation/manifests/action-temporal-v1.json) records immutable asset/revision/hash identities, mapping hashes, publisher context intervals, query families, recipes, candidate/result limits and batch budgets. Existing labels are not overwritten by a repeat prepare.

The [review worksheet](../evaluation/annotations/action-temporal-v1-review.md) links all originals. [Editable review records](../evaluation/annotations/action-temporal-v1-review.json) keep event and absence labels empty until human review. Publisher CAVIAR `drop down` is retained as that publisher context, not converted into a precise fall onset/offset. The demonstrated CAVIAR 30–40.56-second window is not declared gold. UR Fall sequence names provide provisional fall/ADL classes; synchronization CSVs do not supply fall intervals.

## Experiment rules and limits

The ten UR Fall clips are the native-window pilot. Development metrics use three fall and three ADL sequences. Four other sequences are reserved diagnostic groups; actor/session identities are unknown, and prior work has already exposed these data. No claim of an unseen or actor-independent test set is made.

The existing whole-index baseline naturally includes raw candidate scores for the reserved assets. Reserved labels are excluded from development quality metrics and threshold selection. New window query scores are computed only for development sequences; reserved features remain private and their quality is not evaluated. The protocol's instruction not to score reserved groups refers to quality evaluation, not a claim that existing global search never computes their similarities.

Each complete clip is uniformly covered, including non-action portions. The controlled recipes are 12-second/10-second-stride, four-second/two-second-stride and two-second/one-second-stride at 1 fps. They use the same rounded source-PTS sampling rule, 640-pixel maximum edge and JPEG quality 85. Current production can additionally split at shot proposals, so its registered vectors are a separate baseline from the uniform 12-second control. This is not the earlier oracle-selected four-second experiment.

The native candidate budget stays 150. The sequence proxy metrics credit one best window per asset in the first ten, consistently across recipes; this differs from the live first-ten asset cap of three. Raw window candidates remain inspectable. These numbers measure a small fall/ADL acceptance diagnostic, not whole-platform nDCG or fine-grained temporal accuracy.

Frames never include title, attribution or publisher-label text. Core model/processor/profile identity stays pinned. Each recipe records its input recipe hash, selected source PTS/time bases, intervals, processor token counts and valid normalized vectors. Vectors and caches stay under private `.local`; public reports omit vectors and frame payloads. No result is published to the runtime generation.

A batch admits at most 32 uncached native windows. It checks a 20-minute wall budget between bounded inference calls, plus a one-GiB available-host-memory guard at coarse sample points. The operator waits at most 180 seconds for a response to start; the existing HTTP inference timeout still applies. This is an operator batch budget, not a hard preemptive worker timeout. Resume the same recipe if the batch is partial; partial quality summaries are withheld. Queries and cached results are counted separately from fresh video encoding, so cache replays must not be called new throughput.

Docker memory/CPU and host available-memory/swap-level snapshots are taken at batch start/end and every four completed windows. These are coarse observations, not continuous peak RSS or swap-I/O measurements. Existing two-model-CPU/6.5-GiB service limits remain in force. The model is reused serially behind the shared PostgreSQL CPU gate; browser search may receive its existing explicit busy response during a window encode.

## Baseline finding

On the six development sequences, the exact query `person falling` has positive-asset recall 0/3 at 0.70, 2/3 at 0.675 and 3/3 at 0.65. All three ADL sequences are admitted at 0.65. Other fall paraphrases change this tradeoff: at 0.675 they admit all three ADL development clips. These are publisher-sequence proxy results, not confirmed human false-positive rates. They already show why moving the global cutoff to recover one example is not justified.

## Commands

Run all model commands serially. The window command is resumable and does not raise its batch cap when called again.

```bash
backend/.venv/bin/python scripts/evaluate_action_temporal.py prepare
backend/.venv/bin/python scripts/evaluate_action_temporal.py baseline
backend/.venv/bin/python scripts/evaluate_action_temporal.py windows --recipe uniform12
backend/.venv/bin/python scripts/evaluate_action_temporal.py windows --recipe short4
backend/.venv/bin/python scripts/evaluate_action_temporal.py windows --recipe fine2
backend/.venv/bin/python scripts/evaluate_action_temporal.py assess
backend/.venv/bin/python -m pytest evaluation/tests/test_action_temporal.py evaluation/tests/test_quality.py -q
```

Use a new protocol version for changed source membership, splits, queries or recipes. Do not silently edit the frozen v1 manifest or turn publisher/agent observations into independent human labels.

## Promotion status

The assessment reports complete versus incomplete recipes, each fall phrase's recall/ADL acceptance, demonstrated fall-04 windows, resource observations and source/input hashes. A favorable proxy setting is a candidate for further validation only. Human boundaries, reviewed hard negatives, cross-domain/held-out quality and the original latency/resource release criteria remain necessary before serving promotion. No auxiliary model is downloaded or adopted as part of AT0/AT1.

The next gate is the completed interval/absence review. If native windows still confuse actions after those labels are available, proceed to the conditional AT2 model-feasibility experiment in [the plan](action-temporal-retrieval-plan.md), using [the primary-source options](research/action-temporal-options.md). Do not describe lower thresholds or shorter windows as proven action understanding.

## Completed CPU results

All three recipes completed: ten uniform 12-second windows, 19 four-second windows and 44 two-second windows. The fine recipe stopped after 32 fresh encodes, retained its checkpoint with quality summaries withheld, and completed the remaining ten windows in a second batch. The recipes were subsequently replayed from exact profile/input caches: all 73 windows were revalidated, raw scores stayed identical and no new model encoding was needed. [Cache replay evidence](../evaluation/reports/action-temporal-v1-cache-replay.json).

At the unchanged trial floor of 0.70, the development proxy results are:

| Recipe | Mean positive-asset recall | Mean ADL-asset acceptance | Mean asset nDCG@10 |
|---|---:|---:|---:|
| Current published native windows | 0.5556 | 0.0000 | 0.5885 |
| Uniform 12-second control | 0.5556 | 0.0000 | 0.5885 |
| Four-second windows | 0.6667 | 0.1111 | 0.6353 |
| Two-second windows | 0.8889 | 0.3333 | 0.9218 |

Each row averages three phrasings of one fall-query family on only three fall and three ADL development assets. This is a publisher-sequence proxy, not an independent test-set estimate, a query-negative false-useful rate, or whole-platform nDCG. Ranking can be strong in this tiny cohort while acceptance still admits extra ADL clips. At 0.65, the current/control ranking puts the three labelled falls ahead of the ADL clips, but all six are admitted. The data therefore do not establish that a new action model is necessary; calibration and broader reviewed negatives remain important.

No tested recipe/floor meets the proposed positive-recall and ADL-acceptance limits for every fall phrasing. Two-second windows improve recall and ranking but increase ADL admission for some phrases. Do not promote them solely because the demonstrated clip crosses the cutoff. No threshold or physical vector index was changed.

For `person falling`, fall-04's best score rises from 0.691237 for the entire 0–3.203-second clip to **0.714901 for 1–3 seconds**. Other fine windows score 0.676742 for 0–2 seconds and 0.681309 for 2–3.203 seconds. This supports testing finer windows, not a claim of correct onset/offset prediction. The two sampled source frames for the winning window are at 1.001 and 2.002 seconds, showing a transitional posture and a floor posture; exact event boundaries still need review. The JPEG below is a resized preview of those selected source frames, not a model explanation or heatmap.

![Sampled source frames for the experimental 1–3-second fall-04 window](../evaluation/reports/action-temporal-v1-fall04-inputs.jpg)

[Play the experimental 1–3-second window](../evaluation/reports/action-temporal-v1-fall04-1s-3s.mp4). This is a local preview derived from a checksum-verified original. It has not been published as a new application citation.

The initial uniform batch took 262.26 seconds with ten fresh video encodes. The short batch took 273.57 seconds with 15 fresh encodes and four cache hits. Fine windows took 391.71 seconds across two batches, with 42 fresh encodes and two cache hits. These serial pilot wall times include operator overhead and resource sampling. They are not representative ingestion-throughput measurements; zero-encode cache replay times are recorded separately. The largest coarse observed service-memory sum was 3,522.11 MiB (about 3.44 GiB), not a true peak or a new resource guarantee.

## Final verification and remaining work

All **21 evaluation tests passed**. Checks cover sequence de-duplication, acceptance/ranking tradeoffs, reserved-group exclusion, invalid review intervals/revisions, immutable protocol writes, PTS-based sampling, batch bounds and an unresponsive operator-bridge deadline. No serving code, migrations or UI behavior changed, so the earlier 189-test backend result remains historical rather than being claimed as a new full-suite run.

The final preservation check re-downloaded and verified all **46 originals**, revalidated all **19 local video/mapping inputs**, preserved the review file and confirmed the same active generation/profile and live 0.70 policy. The normal API still returns the original accepted CAVIAR result and still excludes fall-04 under that policy. [Verification report](../evaluation/reports/action-temporal-v1-verification.json).

[The assessment](../evaluation/reports/action-temporal-v1-assessment.json) records all recipe/floor results by phrase, demonstrated-case windows, source/input hashes and resource samples. Its status is `not_ready_for_promotion`. AT0 preparation is available, but all 19 clips still require the specified human event/absence review. AT1's bounded exploratory comparisons are complete. AT2 remains conditional; AT3 calibration and temporal evaluation need the reviewed labels, and AT4 serving integration has not started. The broader Phase 7 release gate remains open.

## Development frame inspection and boundary diagnostics

A subsequent offline inspection covers all 15 development clips using timestamped source frames. The four reserved sequences remain excluded. The [review pack](../evaluation/reports/action-temporal-review/index.md) includes retained-original links, complete sampled timelines, a denser CAVIAR transition sheet and uncertain fall-boundary proposals. Its [machine-readable report](../evaluation/reports/action-temporal-v1-inspection.json) records source/mapping identities, preview hashes, source PTS, raw score comparisons and the unchanged human-worksheet checksum. Reproduce it without login, network access or model inference:

```bash
backend/.venv/bin/python scripts/evaluate_action_temporal.py inspect
```

These observations are stored separately in [agent observations](../evaluation/annotations/action-temporal-v1-agent-observations.json). They were made after seeing the scores and cannot supply independent gold, held-out validation or release acceptance. All 19 human-review records remain pending. Sampling can miss motion between frames, so even apparent negative examples need review in motion. Roadscapes frames show traffic and riders; small subjects, darkness and glare leave pedestrian walking unresolved. Riding or merely seeing a person does not establish walking on a street. CAVIAR contact/proximity is likewise insufficient to establish fighting intent.

The CAVIAR Rest_FallOnFloor sheet suggests descent around 26–28 seconds. The proposed onset range is 25.920–26.400 seconds and the first settled-floor range is 27.840–28.320 seconds. The currently accepted 30–40.560-second window begins afterward, showing floor posture and recovery. Its overlap with the proposed falling transition is zero. The asset may be relevant while this specific citation fails to locate the action.

For `person falling`, the diagnostic comparisons are:

| Clip / recipe | Best window | Similarity | IoU sensitivity to agent boundary proposal |
|---|---|---:|---|
| CAVIAR / current | 30–40.560 s | 0.700353 | 0.000–0.000 |
| UR Fall 01 / current | 0–5.338 s | 0.683024 | 0.150–0.250 |
| UR Fall 01 / fine | 3–5 s | 0.715216 | 0.401–0.635 |
| UR Fall 02 / current | 0–3.670 s | 0.673945 | 0.299–0.437 |
| UR Fall 02 / fine | 2–3.670 s | 0.695076 | 0.299–0.452 |
| UR Fall 04 / current | 0–3.203 s | 0.691237 | 0.417–0.584 |
| UR Fall 04 / fine | 1–3 s | 0.714901 | 0.317–0.460 |

The JSON report is authoritative for full-precision scores. IoU ranges describe possible overlap as the proposed onset/settlement move within their uncertainty ranges. They are not statistical confidence intervals. These are top-scored raw windows per asset before acceptance, not temporal Recall@10 over the complete platform. The fine-window experiment covers UR Fall only; CAVIAR has no corresponding fine-window comparison here.

Fall-04 illustrates why admission and localization need separate checks. Its 1–3-second window clears the experimental 0.70 floor, but starts after the proposed onset at 0.266–0.533 seconds. A better similarity score can accompany a worse event interval. For `A person falling to the floor`, fall-01's highest fine-window score is from 4–5.338 seconds, mostly the later floor posture. A retrieved window is therefore a proposal requiring temporal verification, not an estimated event boundary.

The report also compares each best fall window with the existing sitting, bending and lying query scores for the same input. For `person falling`, fall-02's best fine window scores about 0.6951, while lying scores about 0.7222. Crouching/kneeling daily-activity examples often favor bending or sitting. These differences help identify confusion but are not calibrated action probabilities. Applying a mandatory positive fall-versus-posture margin would reject this real fall example. No such rule is selected or deployed.

This completes an agent-assisted inspection pass and adds preliminary AT3 diagnostics. It does not complete AT0 human adjudication or AT3 policy calibration. The next dependent gate remains independent review of the proposed boundaries and hard negatives. Then freeze a development acceptance/localization policy before scoring reserved groups. Test a temporal/action branch only if the reviewed comparisons justify its CPU cost; a new action model is still conditional. Live profiles, vectors, thresholds and citations are unchanged.

The updated evaluation suite passes **25 tests**. New checks cover event overlap versus asset relevance, uncertain interval extrema, invalid boundaries, reserved-group exclusion, revision/gold-provenance validation and rejecting changed original bytes before writing review aids. Black passes for the changed Python files. All 16 generated preview checksums and the unchanged human worksheet checksum were verified; no new inference or serving rebuild was required.

## Offline calibration decision

Following the user's approval of the review pack, calibration used the same provisional event ranges as development feedback. That approval is recorded in the procedure; it does not fill the human worksheet, resolve all absence labels, or create independent gold. Luna independently reviewed the method and confirmed that failed development settings should not be rescued with reserved-sequence scores.

The [frozen procedure](../evaluation/manifests/action-temporal-calibration-v1.json) covers the current native windows and the three controlled recipes, each at 0.65/0.675/0.70. It requires every fall paraphrase to meet all three pilot limits: asset recall at least 0.85, publisher-ADL admission at most 0.10, and conservative temporal overlap recall at IoU 0.5 of at least 0.80. With three positive and three ADL development clips, the asset limits require 3/3 positives and 0/3 ADLs per phrase. The three paraphrases are one correlated query family, not three independent benchmark samples.

Temporal diagnostics use the same accepted top-ten, one-highest-scoring-window-per-asset results as asset evaluation. Rejected positives count as temporal misses. A conservative temporal hit requires IoU at least 0.5 for every feasible onset/settlement pair in the proposed uncertainty ranges; optimistic overlap is reported separately. Boundary error median/p90 ranges are conditional on accepted events, with explicit denominators. These are exploratory sensitivity calculations, not release temporal metrics against human gold. The cohort excludes CAVIAR and all other assets to match the controlled UR Fall experiment; this does not measure whole-platform top-ten retrieval.

The top-ten cap cannot bind within this six-asset cohort. The current-native replay also had the existing global candidate budget applied before cohort filtering, whereas experimental recipes score the private UR Fall pool. Use the uniform 12-second control for a controlled window comparison; do not interpret the native-versus-private comparison as an isolated full-index ranking experiment.

[The calibration report](../evaluation/reports/action-temporal-v1-calibration.json) contains every configuration, raw accepted counts, nDCG, per-event intervals, overlap ranges and conditional boundary errors. At floor 0.70:

| Recipe | Accepted falls / 3, by fall-1 / fall-2 / fall-3 | Admitted ADLs / 3, by phrase | Conservative temporal hits / 3, by phrase |
|---|---|---|---|
| Current native | 0 / 3 / 2 | 0 / 0 / 0 | 0 / 0 / 0 |
| Uniform 12 s | 0 / 3 / 2 | 0 / 0 / 0 | 0 / 0 / 0 |
| Four seconds | 0 / 3 / 3 | 0 / 1 / 0 | 0 / 0 / 0 |
| Two seconds | 2 / 3 / 3 | 0 / 2 / 1 | 0 / 0 / 0 |

All 12 recipe/floor combinations fail. The strict conservative overlap test can fail even when an optimistic interpretation crosses 0.5, so the JSON retains both rather than concealing boundary uncertainty. Zero conservative hits does not establish that the videos contain no falls or that the encoder has no action information.

An oracle diagnostic checks every encoded window before acceptance and selects by the annotation overlap. Fine windows provide conservative IoU-0.5 coverage for 2/3 proposed events; current, uniform and short windows provide 0/3. This is a coverage ceiling for these fixed recipes and proposed ranges, not achieved retrieval or an action detector. It suggests both a window-coverage limit and a window-selection problem. Choosing the best similarity window alone does not reliably select the best event interval. A broader citation may remain useful, but cannot be called precise event localization.

The [frozen decision](../evaluation/manifests/action-temporal-calibration-v1-decision.json) selects **no policy**. Reserved quality is deliberately withheld because no development setting qualifies. The full-index baseline already contains raw reserved similarities from the earlier replay, as previously disclosed; this calibration does not evaluate those groups or select using them. Actor/session independence is still unknown.

Reproduce locally, without login or inference:

```bash
backend/.venv/bin/python scripts/evaluate_action_temporal.py calibrate
backend/.venv/bin/python -m pytest evaluation/tests/test_action_calibration.py evaluation/tests/test_action_temporal.py evaluation/tests/test_quality.py -q
```

All **28 evaluation tests pass**. The new checks prevent rejected-event/oracle confusion, optimistic-overlap promotion, correct-asset/wrong-time acceptance, reserved-group inclusion and incomplete paraphrase evaluation. Black checks pass for the changed Python files. The original human worksheet checksum remains unchanged, as do the recorded raw input reports. No serving code, model, vectors, index, threshold or original media changed; no new inference or latency claim is made.

The next technical experiment is the conditional AT2 CPU feasibility work: test whether motion/action features improve event proposals and window selection on development clips, including crouch/kneel and lying-posture confusion. Select and pin an approach from the research note, measure CPU/memory and demonstrate improvement over these fixed native baselines before integration. Independent annotation and held-out evaluation remain separate promotion requirements. AT3 has exploratory diagnostics and a failure decision, not a validated acceptance policy; AT4 integration has not started.
