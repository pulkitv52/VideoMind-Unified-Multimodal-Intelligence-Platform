# Model and retrieval verification

Verified against primary documentation on 2026-10-16. These are research findings and architecture recommendations, not an implementation.

## Exact model identity

`google/embeddinggemma-2` is available. Google documents a 740M-parameter multimodal model, with text, image, video, and audio sharing a 768-dimensional space. It has open weights under Apache 2.0. This validates native cross-modal retrieval as an architectural option. [Google documentation](https://ai.google.dev/gemma/docs/embeddinggemma)

Do not substitute `google/embeddinggemma-300m`: its documented input is text with a 2,048-token limit. Equal output dimensions do not establish compatibility between different checkpoints. [Earlier model card](https://huggingface.co/google/embeddinggemma-300m)

## Processing contract

- Shared context: 8,192 tokens across modalities; text backbone 270M, optional vision encoder 170M, audio encoder 300M.
- Use 768 dimensions initially. Supported truncations are 512/256/128; re-normalize after truncation. The card cautions that 128 dimensions substantially harms multimodal quality.
- Text query format: `task: search result | query: {query}`. Corpus text: `title: {title} | text: {content}`; use `none` without a title. `SearchQuery` and `Document` are documented prompt names. Titled text needs manual formatting.
- Media inputs use no prefix. A mixed input returns one embedding; preserve independent evidence anchors rather than treating that vector as temporal localization.
- Video defaults to 1 fps, 140 tokens/frame; images default to 280 tokens each; audio costs 25 tokens/second and should be mono, 16 kHz. Thus single-modality theoretical limits are about 58 video frames or 327 audio seconds; accompanying modalities reduce capacity.
- Use BF16 where supported, otherwise FP32. FP16 can produce NaNs or silently degraded vectors.

These contracts and warnings come from the [official model card](https://huggingface.co/google/embeddinggemma-2).

## Retrieval caveats

pgvector offers exact search and ANN. HNSW uses more memory and builds more slowly than IVFFlat, but generally offers a better speed/recall tradeoff. A 768-dimensional `vector` fits HNSW's documented 2,000-dimensional limit. ANN applies filtering after scanning; restrictive tenant/ACL filters can underfill results. Iterative scans, available from 0.8.0, continue until enough results or configured limits. Highly selective filters may favor filtered exact search. Shared tenant indexes can couple recall and performance; partitioning/separate tables offer isolation. Hybrid search can combine PostgreSQL FTS with vectors through reciprocal rank fusion or a cross-encoder. [pgvector documentation](https://github.com/pgvector/pgvector)

PostgreSQL's standard ranks are `ts_rank` and `ts_rank_cd` (the latter considers proximity). They do not use global corpus statistics; do not describe standard PostgreSQL FTS as BM25. Scores are not probabilities. Text configuration/language and positional information affect matching/ranking. [PostgreSQL text-search controls](https://www.postgresql.org/docs/current/textsearch-controls.html)

RLS is defense in depth only with appropriate roles: superusers, `BYPASSRLS` roles, and ordinarily table owners bypass it. Use a separate restricted application role and test actual policies under it. [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

## Architecture implications and unresolved experiments

Recommendations, inferred from the documented contracts:

1. Start with one logical shared embedding space and one active 768-dimensional model profile; retain modality/representation columns. Physical partitions/indexes can evolve independently.
2. Compare unified global candidate selection against modality-specific candidate budgets plus rank fusion. A shared space does not guarantee balanced modality scores, event localization, or immunity to corpus imbalance.
3. Benchmark filtered ANN recall against filtered exact search for each tenant/ACL selectivity, inspecting execution plans. Authorization must constrain every lexical/vector branch and media endpoint, including citations and previews.
4. Pin model revision, processor/tokenizer revision, dependencies, prompt template, normalization, dimensions, precision, frame sampling, audio configuration, and preprocessing fingerprint. Different profiles never share a search candidate pool until compatibility is explicitly validated.
5. Verify the runtime API on a local fixture for each modality; documentation alone does not establish compatible installed library versions, codec support, peak RAM/VRAM, or throughput. Do not promise local latency before hardware measurement.
6. Test whether video encoding includes audio automatically; the card describes sampled vision frames but does not establish demux behavior. Explicitly extract and index the audio track as its own anchored evidence stream regardless.
7. Embeddings supply relevance rather than transcripts, OCR, bounding boxes, or proof of a claim. Those require independent preprocessing and evidence metadata. Native acoustic retrieval should be tested with non-speech events, not evaluated only on ASR text.
8. Treat publisher benchmarks as model-level evidence, not application acceptance thresholds. Evaluate segmentation, authorized retrieval, and citation localization on the intended corpus.
