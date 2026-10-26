export type View = "dashboard" | "search" | "library" | "settings";
export type EvidenceLink = { workspace: string; source: string; citation: string };
export type LocationState = { view: View; workspace: string; evidence: EvidenceLink | null; invalidEvidence: boolean };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function readLocation(pathname: string, search: string): LocationState {
  const candidate = pathname.replace(/^\//, "");
  const view: View = candidate === "dashboard" || candidate === "library" || candidate === "settings" ? candidate : "search";
  const params = new URLSearchParams(search);
  const workspace = params.get("workspace") ?? "";
  const source = params.get("source") ?? "";
  const citation = params.get("citation") ?? "";
  const valid = [workspace, source, citation].every(value => uuid.test(value));
  return { view, workspace: uuid.test(workspace) ? workspace : "", evidence: citation && valid ? { workspace, source, citation } : null, invalidEvidence: !!citation && !valid };
}

export function viewUrl(view: View, workspace: string, evidence?: EvidenceLink): string {
  const params = new URLSearchParams();
  if (workspace) params.set("workspace", workspace);
  if (evidence) { params.set("source", evidence.source); params.set("citation", evidence.citation); }
  return `/${view}${params.size ? `?${params}` : ""}`;
}
