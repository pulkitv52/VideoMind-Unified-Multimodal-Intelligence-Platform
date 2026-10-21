import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { api, ApiError } from "../lib/api";
import type { Account, Workspace } from "../lib/api";
import { SignIn } from "../features/identity/SignIn";
import { IndexStatus } from "../features/indexes/IndexStatus";
import { Search } from "../features/search/Search";
import { SourceList } from "../features/sources/SourceList";
import { readLocation, viewUrl } from "./navigation";
import { useCompact } from "./useCompact";
import type { EvidenceLink, View } from "./navigation";

const views: { id: View; label: string; description: string }[] = [
  { id: "search", label: "Search", description: "Find and inspect evidence" },
  { id: "library", label: "Library", description: "Your files and collections" },
  { id: "settings", label: "Settings", description: "Local services and search setup" },
];

export function App() {
  const compact = useCompact();
  const [location, setLocation] = useState(() => readLocation(window.location.pathname, window.location.search));
  const [account, setAccount] = useState<Account | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const [libraryVisited, setLibraryVisited] = useState(location.view === "library");
  const scrollPositions = useRef<Partial<Record<View, number>>>({});
  const currentView = useRef(location.view);
  const expired = useCallback(() => {
    setAccount(null); setWorkspaces([]); setSelected(""); setReady(null); setLibraryVisited(false);
    scrollPositions.current = {};
  }, []);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const identity = await api<Account>("/api/auth/me");
      const spaces = await api<Workspace[]>("/api/workspaces");
      const requested = readLocation(window.location.pathname, window.location.search).workspace;
      setAccount(identity); setWorkspaces(spaces);
      setSelected(spaces.find(space => space.id === requested)?.id ?? spaces[0]?.id ?? "");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) expired();
      else setError("Unable to connect. Check that the local services are running.");
    } finally { setLoading(false); }
  }, [expired]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const pop = () => {
      scrollPositions.current[currentView.current] = window.scrollY;
      setLocation(readLocation(window.location.pathname, window.location.search));
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    currentView.current = location.view;
    if (location.view === "library") setLibraryVisited(true);
    if (location.workspace && workspaces.some(space => space.id === location.workspace)) setSelected(location.workspace);
    const frame = requestAnimationFrame(() => window.scrollTo(0, scrollPositions.current[location.view] ?? 0));
    return () => cancelAnimationFrame(frame);
  }, [location.view, location.workspace, workspaces]);
  useEffect(() => {
    if (!account) return;
    let current = true; let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try { const value = await api<{ ready: boolean }>("/health/ready"); if (current) setReady(value.ready); }
      catch { if (current) setReady(false); }
      finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => { void refresh(); }, 15000);
    return () => { current = false; clearInterval(timer); };
  }, [account]);
  function navigate(view: View, workspace = selected, evidence?: EvidenceLink) {
    scrollPositions.current[currentView.current] = window.scrollY;
    window.history.pushState(null, "", viewUrl(view, workspace, evidence));
    setLocation(readLocation(window.location.pathname, window.location.search));
    if (workspace !== selected) { setSelected(workspace); setLibraryVisited(view === "library"); scrollPositions.current = {}; }
  }
  function follow(event: MouseEvent<HTMLAnchorElement>, view: View) {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(view);
  }
  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); expired(); }
    catch { setError("Unable to sign out. Try again."); }
  }
  if (loading) return <main className="signin"><p role="status">Opening VideoMind…</p></main>;
  if (!account) return <>{error && <p className="connection-error" role="alert">{error}</p>}<SignIn onSignedIn={() => { void load(); }} /></>;
  const current = views.find(view => view.id === location.view)!;
  const canCreate = ["owner", "admin"].includes(workspaces.find(space => space.id === selected)?.role ?? "");
  const evidenceDenied = location.invalidEvidence || !!location.evidence && !workspaces.some(space => space.id === location.evidence!.workspace);
  const evidence = evidenceDenied ? null : location.evidence;
  const backgroundInert = compact && !!evidence && location.view === "search";
  return <div className="shell product-shell">
    <a inert={backgroundInert || undefined} className="skip-link" href="#main-content">Skip to content</a>
    <aside inert={backgroundInert || undefined} className="sidebar" aria-label="Workspace navigation">
      <a className="brand" href={viewUrl("search", selected)} onClick={event => follow(event, "search")}>VideoMind<span>Your files, connected.</span></a>
      <nav aria-label="Main navigation">{views.map(view => <a key={view.id} href={viewUrl(view.id, selected)} aria-current={location.view === view.id ? "page" : undefined} onClick={event => follow(event, view.id)}><span>{view.label}</span><small>{view.description}</small></a>)}</nav>
      <div className="sidebar-footer"><span className="local-dot" aria-hidden="true" /> Runs on your computer<p>Inspect the original behind every match.</p></div>
    </aside>
    <div className="app-body">
      <header inert={backgroundInert || undefined} className="app-header"><div>{workspaces.length > 1 ? <label className="workspace-select">Workspace<select value={selected} onChange={event => navigate(location.view, event.target.value)}>{workspaces.map(space => <option key={space.id} value={space.id}>{space.name}</option>)}</select></label> : <span className="workspace-name">{workspaces[0]?.name ?? "Your workspace"}</span>}</div><div className="account"><span>{account.username}</span><button className="secondary" onClick={() => { void logout(); }}>Sign out</button></div></header>
      <main id="main-content" className={`workspace product-workspace view-${location.view}`}>
        {error && <p role="alert" className="error">{error}</p>}
        {evidenceDenied && <div className="notice" role="alert">Evidence unavailable. Check the link and your workspace access. <button className="text-button" onClick={() => navigate(location.view)}>Dismiss</button></div>}
        {!selected ? <div className="empty"><h1>No workspace assigned</h1><p>Contact your local administrator to get access.</p></div> : <>
          <section hidden={location.view !== "search"} aria-label="Search workspace"><Search key={selected} workspace={selected} active={location.view === "search"} canManage={canCreate} onLibrary={() => navigate("library")} onSettings={() => navigate("settings")} opened={location.view === "search" && evidence?.workspace === selected ? evidence : null} onOpen={value => navigate("search", selected, { ...value, workspace: selected })} onClose={() => navigate("search")} onExpired={expired} /></section>
          {libraryVisited && <section hidden={location.view !== "library"} aria-label="Library"><div className="page-heading"><p className="eyebrow">YOUR LIBRARY</p><h1>Files worth finding again.</h1><p className="muted">Keep related files in collections. Add originals here, then find their pages and moments in Search.</p></div><SourceList key={selected} workspace={selected} active={location.view === "library"} onExpired={expired} canCreate={canCreate} /></section>}
          {location.view === "settings" && <section aria-label="Settings"><div className="page-heading"><p className="eyebrow">YOUR INSTALLATION</p><h1>Settings</h1><p className="muted">Local service health and controls for preparing searchable files.</p></div><section className="source-card"><h2>Local services</h2><p role="status" className={ready === false ? "error" : "muted"}>{ready === null ? "Checking services…" : ready ? "Local services are ready" : "Some local services are unavailable"}</p><p>VideoMind processes files on this computer. Initial software and model downloads require internet access.</p>{ready === false && <p>Check Docker and run <code>python3 scripts/dev.py status</code> in the project folder.</p>}</section><IndexStatus workspace={selected} onExpired={expired} /><section className="source-card"><h2>About your data</h2><p>Original files and citations stay tied to their revisions. Sharing a citation does not grant access to its content.</p><p>Backups contain private data. Follow the project's local recovery guide; copying this app does not enable scheduled backups.</p></section></section>}
        </>}
        <footer inert={backgroundInert || undefined} className="workspace-footer">{current.label} <span>·</span> Local multimodal search <span>·</span> Verify matches against the original</footer>
      </main>
    </div>
  </div>;
}
