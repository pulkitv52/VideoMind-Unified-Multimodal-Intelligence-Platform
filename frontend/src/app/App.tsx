import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Account, Workspace } from "../lib/api";
import { SignIn } from "../features/identity/SignIn";
import { CitationViewer } from "../features/evidence/CitationViewer";
import { IndexStatus } from "../features/indexes/IndexStatus";
import { Search } from "../features/search/Search";
import { SourceList } from "../features/sources/SourceList";

export function App() {
  const [citationQuery,setCitationQuery]=useState(()=>new URLSearchParams(window.location.search));
  const [account, setAccount] = useState<Account | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const expired = useCallback(() => { setAccount(null); setWorkspaces([]); setSelected(""); }, []);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const identity = await api<Account>("/api/auth/me");
      const spaces = await api<Workspace[]>("/api/workspaces");
      setAccount(identity); setWorkspaces(spaces); setSelected(spaces[0]?.id ?? "");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) expired();
      else setError("Unable to connect. Check that the local services are running.");
    } finally { setLoading(false); }
  }, [expired]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!account) return;
    let current = true;
    const refresh = () => { api<{ready: boolean}>("/health/ready").then((v) => { if (current) setReady(v.ready); }).catch(() => { if (current) setReady(false); }); };
    refresh(); const timer = setInterval(refresh, 15000);
    return () => { current = false; clearInterval(timer); };
  }, [account]);
  async function logout() {
    try { await api("/api/auth/logout", {method: "POST"}); expired(); }
    catch { setError("Unable to sign out. Try again."); }
  }
  if (loading) return <main className="signin"><p aria-live="polite">Opening VideoMind…</p></main>;
  if (!account) return <>{error && <p className="connection-error" role="alert">{error}</p>}<SignIn onSignedIn={() => { void load(); }}/></>;
  return <div className="shell">
    {citationQuery.get("citation")&&citationQuery.get("workspace")&&citationQuery.get("source")&&<CitationViewer workspace={citationQuery.get("workspace")!} source={citationQuery.get("source")!} citation={citationQuery.get("citation")!} onExpired={expired} onClose={()=>{window.history.replaceState(null,"",window.location.pathname);setCitationQuery(new URLSearchParams());}}/>}
    <header><div className="brand">VideoMind<span>Unified knowledge</span></div><div className="account"><span>{account.username}</span><button className="secondary" onClick={logout}>Sign out</button></div></header>
    <main className="workspace">
      <p className="eyebrow">WORKSPACE</p>
      {workspaces.length > 1 ? <label className="workspace-select">Choose workspace<select value={selected} onChange={(event) => setSelected(event.target.value)}>{workspaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}</select></label> : <h1>{workspaces[0]?.name ?? "Your workspace"}</h1>}
      {selected&&<Search key={selected} workspace={selected} onExpired={expired}/>}
      <div className="section-heading"><h2>Connected sources</h2><p className={ready === false ? "error" : "muted"} aria-live="polite">{ready === null ? "Checking services…" : ready ? "Local services ready" : "Some local services are unavailable"}</p></div>
      {error && <p role="alert" className="error">{error}</p>}
      {selected&&<IndexStatus workspace={selected} onExpired={expired}/>}
      {selected ? <SourceList workspace={selected} onExpired={expired} canCreate={["owner","admin"].includes(workspaces.find(w=>w.id===selected)?.role??"")}/> : <p className="muted">No workspace is assigned to this account. Contact the local administrator.</p>}
    </main>
  </div>;
}
