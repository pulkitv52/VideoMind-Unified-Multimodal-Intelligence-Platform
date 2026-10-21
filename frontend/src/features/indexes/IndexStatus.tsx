import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
type Generation = { id: string; status: string; fingerprint: string; coverage: { eligible_assets: number; published_assets: number; assets_without_ready_inputs: number; partial_extraction_assets: number; jobs: Record<string, number> } };
export function IndexStatus({ workspace, onExpired }: { workspace: string; onExpired: () => void }) {
  const [rows, setRows] = useState<Generation[]>([]);
  const [manage, setManage] = useState<boolean | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<{ bytes: number; limit_bytes: number } | null>(null);
  const refreshing = useRef(false);
  const base = `/api/workspaces/${workspace}/indexes`;
  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const data = await api<{ can_manage: boolean; generations: Generation[] }>(base);
      setRows(data.generations); setManage(data.can_manage); setError("");
    } catch (cause) { if (cause instanceof ApiError && cause.status === 401) onExpired(); else setError(cause instanceof Error ? cause.message : "Unable to check search preparation"); }
    finally { refreshing.current = false; }
  }, [base, onExpired]);
  useEffect(() => { void refresh(); const timer = setInterval(() => { void refresh(); }, 5000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => {
    if (!manage) return;
    let current = true;
    void api<{ bytes: number; limit_bytes: number }>(`/api/workspaces/${workspace}/storage`).then(value => { if (current) setUsage(value); }).catch(cause => { if (current && cause instanceof ApiError && cause.status === 401) onExpired(); });
    return () => { current = false; };
  }, [workspace, manage, onExpired]);
  async function action(path: string) {
    setBusy(true); setError("");
    try { await api(base + path, { method: "POST" }); await refresh(); }
    catch (cause) { if (cause instanceof ApiError && cause.status === 401) onExpired(); else setError(cause instanceof Error ? cause.message : "Search preparation failed"); }
    finally { setBusy(false); }
  }
  return <section className="source-card" aria-label="Search preparation"><div className="source-heading"><div><h2>Search preparation</h2><p className="muted">Make your prepared files available for search.</p></div>{manage && !rows.some(row => row.status === "building") && <button disabled={busy} onClick={() => { void action(""); }}>{rows.length ? "Rebuild search index" : "Start indexing"}</button>}</div>
    {error && <p role="alert" className="error">{error}</p>}
    {manage === null && !error && <p role="status">Checking search preparation…</p>}
    {manage === false && <p>Your workspace administrator manages the search index. You can search files when an active index is available.</p>}
    {manage && !rows.length && <p>Add files in Library, then start indexing here. Once all eligible files are indexed, make the index available to enable search.</p>}
    {rows.map(row => <div key={row.id} className="index-generation"><div className="index-heading"><h3>{row.status === "active" ? "Ready for search" : row.status === "standby" ? "Previous index" : row.status === "building" ? "Preparing search index" : row.status}</h3><span className="muted">{row.coverage.published_assets} of {row.coverage.eligible_assets} eligible files</span></div>
      {row.coverage.eligible_assets > 0 && <progress value={row.coverage.published_assets} max={row.coverage.eligible_assets} aria-label="Eligible files indexed" />}
      {row.coverage.assets_without_ready_inputs > 0 && <p className="muted">{row.coverage.assets_without_ready_inputs} files have no ready extraction inputs.</p>}
      {row.coverage.partial_extraction_assets > 0 && <p className="notice">{row.coverage.partial_extraction_assets} files have partial extraction. Available content is indexed; some evidence may be missing.</p>}
      {(row.coverage.jobs.failed ?? 0) > 0 && <p className="error">{row.coverage.jobs.failed} indexing jobs need attention. <button disabled={busy} className="secondary" onClick={() => { void action(`/${row.id}/retry`); }}>Retry failed jobs</button></p>}
      {["building", "standby"].includes(row.status) && row.coverage.eligible_assets > 0 && row.coverage.published_assets === row.coverage.eligible_assets && <button disabled={busy} onClick={() => { void action(`/${row.id}/activate`); }}>{row.status === "standby" ? "Restore previous index" : "Make index available"}</button>}
      {row.status === "standby" && <p className="muted">Restoring an index changes search coverage. It does not restore deleted files.</p>}
      <details><summary>Technical details</summary><p className="muted">Generation {row.id}<br />Profile {row.fingerprint}<br />EmbeddingGemma 2 · local CPU processing</p></details>
    </div>)}
    {manage && usage && <p className="muted helper">Storage: {(usage.bytes / 1024 ** 2).toFixed(1)} MiB of {(usage.limit_bytes / 1024 ** 3).toFixed(1)} GiB, including original revisions, derivatives and pending uploads.</p>}
  </section>;
}
