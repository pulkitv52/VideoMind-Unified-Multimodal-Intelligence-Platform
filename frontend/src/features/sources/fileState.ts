export type Stage = { job_id: string; status: string; error_code: string | null; manifest: { stage?: string; partial?: boolean; asr_status?: string; pages_done?: number; pages_total?: number; page_count?: number; warnings?: string[] } };
export type Asset = { embedding_status?: string | null; id: string; title: string; modality: string; size_bytes: number; status: string; error_code: string | null; job_id: string; revision_id: string; media: Stage | null; document: Stage | null };
export function fileState(file: Asset): { label: string; tone: string; detail: string } {
  const failed = file.status === "failed" || file.document?.status === "failed" || file.media?.status === "failed" || file.embedding_status === "failed";
  if (failed) return { label: "Needs attention", tone: "danger", detail: "Open processing details for the cause and available retry." };
  if (file.embedding_status === "indexed") return { label: "Ready to search", tone: "success", detail: "This revision is available in the active search index." };
  if (file.embedding_status === "cancelled" || file.status === "cancelled" || file.document?.status === "cancelled" || file.media?.status === "cancelled") return { label: "Preparation stopped", tone: "warning", detail: "Check with your workspace administrator before trying again." };
  if (file.embedding_status === "ready") return { label: "Waiting for publication", tone: "pending", detail: "Embedding is complete. This revision is not yet available in search." };
  if (file.embedding_status === "running" || file.embedding_status === "queued") return { label: "Preparing search", tone: "pending", detail: "Content is being added to the search index." };
  if (file.status !== "stored") return { label: "Validating file", tone: "pending", detail: "Original received. Validation runs in the background." };
  if ((file.document && file.document.status !== "stored") || (file.media && file.media.status !== "stored")) return { label: "Processing content", tone: "pending", detail: "Preparing readable content and original evidence." };
  return { label: "Preparing search", tone: "pending", detail: "Original validated. Waiting for search preparation." };
}
export function hasLimitations(file: Asset) {
  return !!(file.media?.manifest.partial || file.media?.manifest.asr_status === "partial" || file.document?.manifest.warnings?.length);
}
