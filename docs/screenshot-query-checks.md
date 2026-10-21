# Screenshot query checks

Tested on 20 October 2026 against the running local CPU model and active 197-vector generation, using the six query descriptions visible in the screenshot. The four truncated demo descriptions were expanded to their existing demo queries. No search configuration, model or corpus content was changed.

| Query | Observed result | Assessment |
|---|---|---|
| Repeated electronic beeping tones | `beeps.wav`, native audio, cosine 0.7246 | Expected sound evidence retrieved. |
| A red square moving across a white background | `silent.mp4` and `spoken.mp4`, native video, cosine 0.8145 | Expected visual evidence retrieved. |
| two person fighting | `video30-caviar-ATTRIBUTION.md`, cosine 0.7242; no video result with video-only filters | Fails the intended visual-action search. The attribution file is not evidence that a fight occurs in the returned media interval. |
| How do I safely open the electrical panel? | Scanned-page OCR, spoken video, speech audio and procedure text | Expected document/speech evidence retrieved. |
| A close-up photograph of an orange cat | Both retained copies of `chelsea.png`, cosine 0.7363 | Expected image evidence retrieved. Copies belong to different source assets. |
| person walking on roof | No accepted result, including with video-only filters | Abstention observed. No rooftop example is identified in the curated corpus; this is not an independently annotated absence test. |

## Fighting diagnosis

The retained CAVIAR manifest labels `caviar-Fight_Chase__derived.mp4` as a staged fight/chase sequence. Its two native windows score 0.6268 and 0.6308 for the exact query, below the current 0.70 floor. Other native CAVIAR clips rank above it. The attribution document clears the floor and is returned by the default unified query.

Changing the wording to `two people fighting` still returns no video result. The fight windows score 0.6331 and 0.6371. Adding `in a lobby` raises the fight scores to about 0.721, but unrelated lobby clips rank higher, and the fight is absent from the first ten returned groups. This is both an action-relevance/ranking limitation and a cutoff problem. Correcting grammar or lowering a global threshold alone does not establish a reliable fix.

The retained video was decoded for visual inspection at 2, 8 and 14 seconds. It is a distant overhead indoor scene with small people; those stills do not independently annotate the fight interval. Native inputs currently use sparse sampled frames and broad windows. The earlier four positive smoke examples do not establish accuracy for CCTV actions. A follow-up needs labelled action intervals, action-specific positive/negative tests, candidate diversity checks and an evaluated representation/ranking change. Attribution documents must not be treated as visual confirmation of an action.

Raw default, video-filtered and administrator vector diagnostics are in [the JSON report](../evaluation/reports/screenshot-query-checks.json). Scores are cosine ranking signals, not probabilities. These findings supplement the Phase 6 functional validation and do not change the existing release reports.
