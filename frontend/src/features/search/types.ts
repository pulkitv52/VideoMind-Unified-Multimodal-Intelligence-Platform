export type Locator = { kind: string; page?: number; start_char?: number; end_char?: number; start_ms?: number; end_ms?: number };
export type Citation = { id: string; anchor: { locator: Locator } };
export type Context = { segment_id: string; representation: string; snippet: string | null; citations: Citation[] };
export type Hit = { preview?: { kind: "page" | "image" | "frame"; route: "document" | "media"; object_id: string; segment_set_id: string } | null; segment_id: string; title: string; source_name: string; modality: string; asset: { source_id: string; asset_id: string; revision_id: string }; representation: string; matched_representations: string[]; snippet: string | null; citations: Citation[]; warnings: string[]; branches: Record<string, { rank: number; score: number }>; fusion_score: number; dense_score: number | null; context: Context[] };
export type Facet = { source_id: string; source_name: string; modality: string; assets: number };
export type SearchResponse = { results: Hit[]; no_useful_evidence: boolean; generation_id: string; request_id: string; retrieval_config_sha256: string; timings_ms: { total: number }; warnings: string[] };
