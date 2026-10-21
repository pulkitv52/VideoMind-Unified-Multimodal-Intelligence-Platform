# Phase 7 evaluation and release assessment

The user authorized evaluation on 20 October 2026 after real CCTV searches exposed failures that the four demo queries did not detect. Local evaluation tooling and bounded experiments are implemented. The original MVP release gate remains open; this document does not declare the platform ready for release.

## Adopted evaluation scope

The retained corpus has 46 assets and 197 published vectors. `evaluation/manifests/phase7-corpus.json` freezes authorized asset/revision IDs, original byte hashes, the active generation/profile and publisher annotation/mapping hashes. Originals were downloaded through the authenticated API and checked before freezing. `phase7-rights.json` records terms for each asset. The pack includes noncommercial datasets, and this evaluation does not authorize redistribution.

`evaluation/annotations/phase7-qrels.json` contains 30 provisional queries in 18 families. Families cover fighting, falling, walking, driving, document safety, spoken instructions, sound, images, exact identifiers and proposed negatives. Paraphrases stay in the same family. The UR Fall and Roadscapes families are diagnostic held-out families, not an independently adjudicated test set. The data and query wording were already available during development; no model-training contamination exclusion is claimed.

CAVIAR provides frame-level publisher hypotheses. The parser joins annotation frame numbers to retained integer PTS/time-base mappings, including the original duplicate-timestamp repairs. It never assumes nominal frame rate. The fight interval is extracted from the publisher's `fighting` hypotheses. These annotations support a temporal diagnostic but still lack the plan's two independent human reviews. The [review worksheet](../evaluation/annotations/phase7-review.md) identifies the evidence basis and unreviewed labels.

UR Fall's synchronization CSV contains frame numbers, milliseconds and interpolated accelerometer data; it is not a per-frame fall label file. The sequence names provide fall/ADL classes, not precise action intervals. [Publisher format description](https://fenix.ur.edu.pl/mkepski/ds/uf.html). Roadscapes sequence hints and proposed absence labels require independent review. Neither is silently promoted to gold ground truth.

The planned release corpus requires 200 assets, 400 queries and two human annotators with adjudication. Current metadata explicitly marks the corpus and queries unreviewed. The release assessor fails closed on those requirements, even if a small numerical metric happens to pass. No scope waiver is inferred from the CPU-only hardware decision.

## Metrics and comparison protocol

`evaluation/quality` separates corpus/label preparation, metrics, search runs, offline video experiments, recovery and release assessment. `scripts/evaluate.py` is the local command entry point. It reads existing credentials without printing them. Normal search and citation checks use server-validated sessions and current source RLS. The private encoder bridge is an operator CLI over Docker stdin, with no new application endpoint or exposed service port.

The search matrix compares hybrid, native-only dense, lexical/identifier and text-derived dense retrieval in both unified and per-modality candidate strategies. Requests pin the frozen generation/profile; a changed revision or profile invalidates the run. Raw responses, request/configuration IDs, filters and timings remain in the report. Native-only runs explicitly restrict representations; textual and visual evidence are not treated as interchangeable labels.

Recall counts distinct judged relevant assets. nDCG credits an asset once and preserves its displayed rank, so repeated windows do not inflate gain or erase the penalty of intervening results. Temporal matches require the same asset and interval IoU at least 0.5. Proposed negatives and answerable rejection have separate denominators. Required-evidence-set recall stays unmeasured unless required sets were explicitly annotated; all relevant alternatives are not assumed jointly necessary. Macro summaries and 95% bootstrap intervals resample query families with seed 701, using 1,000 replicates. Provisional labels limit what these numbers establish.

## Video sampling experiment

The broad uniform-window grid was stopped after the first baseline clip because native CPU encoding was expensive. Its cached vectors were retained privately. The executed diagnostic uses paired fight/walk and fall/ADL examples with four-second windows at 1, 2 and 4 fps. CAVIAR uses 12–16 seconds for both videos; the fight window is deliberately oracle-localized using publisher annotations. UR Fall uses the first four seconds and clip-level labels only. This is a small representation diagnostic, not an end-to-end localization or held-out accuracy benchmark.

For `two person fighting`, the same 12–16-second positive window scored 0.6265, 0.6262 and 0.6292 at 1, 2 and 4 fps. Its first relevant asset rank stayed second within the four-asset pool. The fall example rose from 0.6545 to 0.6781 to 0.6937 for one tested phrase; those values still do not pass the existing 0.70 floor. Walking was easier than fighting. These results do not support promoting denser sampling as a reliable action-search fix.

The three four-asset runs took about 105, 212 and 439 seconds, respectively. These are measured serial experiment times; cached repeat timings would not represent fresh encoding throughput. The active preprocessing profile and published vectors were left unchanged. No model substitution, generated action captions or GPU was used.

## Search quality and context batching

The provisional hybrid/unified family-macro Recall@10 is 0.7283, nDCG@10 is 0.6005 and temporal recall at IoU 0.5 is 0.6667. These miss the original 0.85, 0.70 and 0.80 targets. Eight proposed negatives produce no accepted result, but their absence labels are unreviewed; this cannot establish a calibrated false-positive rate. A nonempty response also does not establish correctness: fighting queries can return attribution text while missing the relevant video.

Native-only dense retrieval has provisional Recall@10 0.5917 and nDCG@10 0.5179; lexical retrieval has 0.1250 and 0.0947. Text-derived dense retrieval has 0.2500 and 0.2061. Raw query-family confidence intervals, modality slices and both candidate strategies remain in the search report. The strategy comparison uses exact cosine and a common physical table with fixed candidate budgets. It does not compare separate physical ANN indexes or establish sparse-filter ANN recall at scale.

The actual `procedure.txt` slow-path reproduction took about 17.0 seconds before the fix, including 16.7 seconds of retrieval. Profiling found ten context selections and twelve evidence hydrations for ten hits. An on/off/on JIT diagnostic produced identical result signatures but inconsistent timings, so no production JIT setting changed.

The retrieval repository now resolves all groups' neighbors with one scoped selection and one context hydration, retaining the per-group limit, source/set/representation identity and final authorization/publication rechecks. A runtime-database regression first failed with ten neighbor-selection queries, then passed with the bounded batch. Context is displayed in deterministic original ordinal order. The immediate post-deploy reproduction took 4.63 seconds, with 4.33 seconds of retrieval: an improvement in this observation, still a latency failure. Development warming and host contention prevent treating these two observations as a controlled speedup measurement.

The retained before/after sweeps each exercise all 30 queries in eight configurations. The comparison checks full ordered matches, scores, snippets, citations, filters, facets and generation/profile/configuration provenance. It canonicalizes neighbor display order and excludes request IDs and timings; it does not discard changed evidence. The separate warm performance run and final regression suite are recorded below.

All 240 paired responses passed this comparison. Hybrid/unified HTTP p50/p95/p99 changed from 3,418/9,137/10,091 ms to 1,610/3,995/4,836 ms in these development sweeps. The earlier sweep included other diagnostic activity; warming and laptop contention were not controlled. These observations support retaining the batching change and its bounded-query regression, but do not establish an isolated causal speedup or a passing p95.

Hybrid/unified and hybrid/per-modality had identical provisional Recall@10 and nDCG@10 on this corpus. Their after-change p95 values were about 3,995 and 4,621 ms, respectively. Four scoped dense branches add work here without a measured relevance gain. Keep the unified exact-cosine baseline for local use; no physical index split was adopted.

The dedicated run restarted only the embedding service and sent one first request followed by 60 serialized warm requests over six query types. The first search took 32.83 seconds, including 31.53 seconds of embedding/model loading; restart-to-first-response was about 41.06 seconds. Warm p50/p95/p99 were 1,501/4,428/5,191 ms, with zero failed warm requests. Both the two-second p95 and five-second p99 targets were missed. This is process-cold evidence with uncontrolled OS file caches, not a filesystem-cold run. No other benchmark or test suite ran concurrently with this performance run.

The first full regression attempt had 172 passes, 17 search failures and one fixture-teardown error. PostgreSQL reported a deadlock cascading disposable workspaces; search failures explicitly reported CPU admission busy while the live worker was processing jobs. No advisory lock remained after that run. The harness now retries only SQLSTATE `40P01` during disposable cleanup, with a fresh transaction and at most three attempts. Search semantic tests wait up to 60 seconds only for the exact CPU-busy response. The explicit busy-response test opts out. Other errors still fail immediately; real-model benchmarks never retry or exclude failed requests. The abandoned fixture cleanup was limited to the two IDs from that error, guarded by verification workspace names and test-only memberships. The first failed log is preserved privately alongside the subsequent verification result.

## Recovery and resource evidence

The recovery tool coordinates a custom-format database dump and referenced object copies under the exclusive storage lock. The dump retains original database ACLs; stripping ACLs caused the initial rehearsal to fail runtime-role checks and was corrected. Backups include authentication data and stay under private `.local/backups`, with database/object files mode 0600. The script admits at most 512 MiB and 2,000 objects per local rehearsal. It does not export user data or restore the primary database.

A disposable database and private MinIO bucket received the restored data. The successful drill restored and checksum-verified 924 objects (104,215,414 bytes), 46 assets/revisions, 197 vectors, 197 citations and 46 active memberships. All 197 citations resolved through a TestClient using the restored runtime role and existing authenticated identity. An unrelated identity saw no vectors. A clone-only post-backup deletion was recorded, the original dump restored again, and that fixture tombstone replayed; the affected asset had zero generation memberships and active coverage became 45. The disposable targets were removed; the primary remained untouched. The successful drill took about 52.6 seconds.

This demonstrates recovery mechanics with a supplied fixture journal. It does not establish a durable primary deletion ledger, scheduled backups, 24-hour RPO, or post-retirement deletion replay after loss of the primary. Those remain release blockers. The tool does not configure a recurring automation.

Twelve coarse concurrent resource snapshots observed up to about 4.37 GiB across the running services. The embedding cgroup lifetime high-water value was about 5.31 GiB; it is not a run-specific peak or the simultaneous platform peak. Raw samples retain CPU/memory values and the two-CPU/6.5-GiB model admission envelope remains unchanged. During the bounded video producer, all 20 search probes received the explicit retryable CPU-busy response. Those failed requests are retained rather than excluded from a successful-latency percentile. This is not a corpus-ingestion throughput measurement.

## Commands and reports

Run the baseline search sweep and video experiment serially; both share the existing heavy CPU gate. The performance command restarts only the embedding service to measure actual cold loading, then runs serialized warm searches. The recovery command touches only its generated restore targets and private backup directory.

```bash
backend/.venv/bin/python scripts/evaluate.py freeze
backend/.venv/bin/python scripts/evaluate.py search
backend/.venv/bin/python scripts/evaluate.py ablate
backend/.venv/bin/python scripts/evaluate.py recovery
backend/.venv/bin/python scripts/evaluate.py resources
backend/.venv/bin/python scripts/evaluate.py performance
backend/.venv/bin/python -m pytest evaluation/tests/test_quality.py -q
python3 scripts/dev.py verify
backend/.venv/bin/python scripts/evaluate.py assess
```

Freeze establishes a new corpus/label version only when no version exists; otherwise it verifies the existing checksum and preserves labels. A changed corpus requires a new version. Routine benchmark runs use the existing freeze. Frozen labels remain provisional until independently reviewed.

Reports live in `evaluation/reports/phase7-*.json`. The final assessment records measured passes, numerical misses and unmeasured requirements separately. Phase 2–6 reports remain historical evidence and are not overwritten by Phase 7.

## Remaining release work

Final local verification: **189 integration tests passed in 148.92 seconds**, with one upstream Starlette/httpx deprecation warning. All **12 evaluation tests** passed. Strict TypeScript checking and the Vite production build passed. The final authenticated freeze check re-downloaded and verified all **46 originals**, confirmed the unchanged corpus/generation/profile snapshot and preserved labels. Source and report SHA-256 values are recorded in [the assessment](../evaluation/reports/phase7-assessment.json); [verification](../evaluation/reports/phase7-verification.json), [preservation](../evaluation/reports/phase7-preservation.json) and [response comparison](../evaluation/reports/phase7-comparison.json) retain the supporting results.

The assessment is **not ready**, with 21 open criteria. Some have measured numerical misses; others require missing gold labels, corpus coverage or operational guarantees. A numerical result on provisional labels cannot pass a gold-quality gate. This is the completed bounded local evaluation attempt, with the original Phase 7/MVP exit gate still open.

- Expand the licensed corpus to the original 200-asset/400-query coverage and obtain two independent human annotations with adjudication. Use the review worksheet; do not convert publisher hints or proposed negatives into human labels.
- Improve action retrieval against the frozen fighting/falling families, then validate on independently held-out families. Denser sampling is not supported as the current fix. Any new model, captions or reranker needs an explicit profile and separate evidence mapping.
- Meet the CPU latency target across the agreed warm and concurrent workloads. The producer-busy behavior is measured, not counted as successful concurrent search capacity. Full ingestion throughput and filesystem-cold behavior remain unmeasured.
- Establish an adopted backup schedule/RPO and durable post-backup deletion journal. The clone-only rehearsal proves mechanics without supplying either operational policy.
- Complete gold citation-support review, explicitly annotated evidence sets and filtered-ANN/selectivity measurements before claiming the original release gate passed. GPU and larger-corpus scaling remain deferred.

## Planned action and temporal follow-up

The 20 October 2026 user review identified UR Fall fall-04 as a relevant below-cutoff example. [The proposed follow-up plan](action-temporal-retrieval-plan.md) separates acceptance calibration from action understanding and event boundaries, preserves the measured baseline and defines CPU bounds, human review and promotion criteria. [The options note](research/action-temporal-options.md) records primary-source model research. These documents authorize no model download, threshold change or index publication.

## Subsequent local recovery work

After the user deferred further action/temporal experiments, backup/recovery reliability was authorized. The [local recovery runbook](local-recovery.md) records the additive journal migration, persistent exporter, coordinated operational backup, saved/latest journal replay, installed daily Codex backup check and measured acceptance. Historical Phase 7 measurements above are preserved. The operational changes do not resolve the original quality/performance gates, the asynchronous export gap, off-device protection or post-backup access-revocation replay.
