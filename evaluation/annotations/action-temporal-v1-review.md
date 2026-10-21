# Action and temporal evidence review (v1)

This worksheet and the adjacent `action-temporal-v1-review.json` prepare AT0. They are not adjudicated labels. All event lists begin empty; unknown does not mean absent. Publisher sequence classes support a provisional pilot only. Do not choose thresholds from the reserved diagnostic groups.

Two independent human reviewers should inspect each complete original, record observable actions and original-time intervals, and resolve disagreements. Use separate reviewer IDs. Keep uncertain/occluded boundaries explicit rather than guessing. A fall starts at the first visible transition from the stable posture toward the floor and ends at the first settled floor posture. Label lying afterward separately. Confirm the boundary convention before review. The CAVIAR 30–40.56-second retrieved window is not automatically a fall label.

For each reviewed event add `reviewer`, `action`, `start_ms`, `end_ms`, `provenance` (`human`), and `visibility` (`clear`, `occluded` or `uncertain`). Milliseconds = seconds × 1000. Record absence separately only after reviewing the complete clip. Set the asset status to reviewed after both reviews and resolution; preserve the two original reviewer records. Set adjudication metadata only when the human review actually occurred. No agent-only assessment qualifies.

The JSON pins asset/revision identity; the protocol pins original hashes, frame mappings, split groups and producer settings. Actor/session identities are unknown, so the reserved sequence groups do not establish actor-independent generalization. The demonstrated fall-04 clip is development data.

| Clip | Duration (s) | Group | Publisher hint (not human ground truth) | Media |
|---|---:|---|---|---|
| caviar-Fight_Chase | 17.480 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/caviar-Fight_Chase__derived.mp4) |
| caviar-Rest_FallOnFloor | 40.560 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/caviar-Rest_FallOnFloor__derived.mp4) |
| caviar-Rest_InChair | 40.560 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/caviar-Rest_InChair__derived.mp4) |
| caviar-Walk1 | 24.720 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/caviar-Walk1__derived.mp4) |
| roadscapes-day_11 | 5.000 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/roadscapes-day_11__derived.mp4) |
| roadscapes-day_12 | 5.000 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/roadscapes-day_12__derived.mp4) |
| roadscapes-day_13 | 5.000 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/roadscapes-day_13__derived.mp4) |
| roadscapes-night_12 | 5.000 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/roadscapes-night_12__derived.mp4) |
| roadscapes-night_13 | 5.000 | development | context/event labels need review | [Open local original](../../.local/datasets/video30/derived/roadscapes-night_13__derived.mp4) |
| urfall-adl-01 | 5.030 | development | adl | [Open local original](../../.local/datasets/video30/derived/urfall-adl-01__derived.mp4) |
| urfall-adl-02 | 6.050 | development | adl | [Open local original](../../.local/datasets/video30/derived/urfall-adl-02__derived.mp4) |
| urfall-adl-03 | 6.050 | reserved_diagnostic | adl | [Open local original](../../.local/datasets/video30/derived/urfall-adl-03__derived.mp4) |
| urfall-adl-24 | 2.335 | development | adl | [Open local original](../../.local/datasets/video30/derived/urfall-adl-24__derived.mp4) |
| urfall-adl-28 | 2.841 | reserved_diagnostic | adl | [Open local original](../../.local/datasets/video30/derived/urfall-adl-28__derived.mp4) |
| urfall-fall-01 | 5.338 | development | fall | [Open local original](../../.local/datasets/video30/derived/urfall-fall-01__derived.mp4) |
| urfall-fall-02 | 3.670 | development | fall | [Open local original](../../.local/datasets/video30/derived/urfall-fall-02__derived.mp4) |
| urfall-fall-03 | 7.240 | reserved_diagnostic | fall | [Open local original](../../.local/datasets/video30/derived/urfall-fall-03__derived.mp4) |
| urfall-fall-04 | 3.203 | development | fall | [Open local original](../../.local/datasets/video30/derived/urfall-fall-04__derived.mp4) |
| urfall-fall-05 | 5.064 | reserved_diagnostic | fall | [Open local original](../../.local/datasets/video30/derived/urfall-fall-05__derived.mp4) |

Related protocol: [action-temporal-v1.json](../manifests/action-temporal-v1.json). Editable reviews: [action-temporal-v1-review.json](action-temporal-v1-review.json). Implementation plan: [action and temporal plan](../../docs/action-temporal-retrieval-plan.md).
