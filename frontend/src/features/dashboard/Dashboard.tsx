import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";

type Person = { principal_id: string; username: string; role: string; disabled: boolean; joined_at: string | null; version: number; files: number; ready: number };
type Upload = { id: string; title: string; modality: string; source_id: string; revision_id: string; collection: string; uploader: string | null; received_at: string; status: string; has_warnings: boolean };
type Data = { can_manage_roles: boolean; summary: Record<string, number>; recent_members: Person[]; people: Person[]; uploads: Upload[]; trend: { day: string; uploads: number }[]; next_cursor: string | null; directory_limited: boolean };
type Policy = { enabled: boolean; configured: boolean; can_change: boolean };
const date = (value: string | null) => value ? new Date(value).toLocaleString() : "Join date not recorded";
const roles: Record<string, string> = { owner: "Owner", admin: "Admin", member: "Member" };
const states: Record<string, string> = { ready: "Ready to search", preparing: "Preparing content", indexing: "Indexing", failed: "Needs attention" };

export function Dashboard({ workspace, account, onExpired, onLibrary }: { workspace: string; account: string; onExpired: () => void; onLibrary: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [storage, setStorage] = useState<{ bytes: number; limit_bytes: number } | null>(null);
  const [error, setError] = useState("");
  const [days, setDays] = useState("7"); const [member, setMember] = useState(""); const [status, setStatus] = useState(""); const [modality, setModality] = useState("");
  const [refresh, setRefresh] = useState(0); const [busy, setBusy] = useState(false); const [more, setMore] = useState(false);
  const expandedUploads = useRef(false);
  const [olderUploads, setOlderUploads] = useState(false);
  const [action, setAction] = useState<{ person: Person; role: string | null } | null>(null);
  const query = new URLSearchParams({ days, ...(member ? { member } : {}), ...(status ? { status } : {}), ...(modality ? { modality } : {}) }).toString();
  const currentQuery = useRef(query); currentQuery.current = query;
  const base = `/api/workspaces/${workspace}`;
  useEffect(() => {
    let current = true; let pending = false;
    expandedUploads.current = false; setOlderUploads(false);
    setData(null); setPolicy(null); setStorage(null); setError(""); setMore(false); setAction(null);
    const update = async () => {
      if (pending) return;
      pending = true;
      try {
        const [value, registration, usage] = await Promise.all([api<Data>(`${base}/analytics?${query}`), api<Policy>(`${base}/registration`), api<{ bytes: number; limit_bytes: number }>(`${base}/storage`)]);
        if (current && !expandedUploads.current) { setData(value); setPolicy(registration); setStorage(usage); setError(""); }
      } catch (cause) {
        if (!current) return;
        setData(null); setPolicy(null); setStorage(null);
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        else setError(cause instanceof ApiError && [403,404].includes(cause.status) ? "This dashboard is available to workspace owners and admins." : "Unable to load workspace activity. Try again.");
      } finally { pending = false; }
    };
    void update(); const timer = setInterval(() => { if (!expandedUploads.current) void update(); }, 15000);
    return () => { current = false; clearInterval(timer); };
  }, [base, query, refresh, onExpired]);
  async function moreUploads() {
    if (!data?.next_cursor) return;
    const requestQuery = query; setMore(true);
    try {
      const value = await api<Data>(`${base}/analytics?${query}&after=${encodeURIComponent(data.next_cursor)}`);
      if (currentQuery.current === requestQuery) {
        expandedUploads.current = true; setOlderUploads(true);
        setData(previous => previous ? { ...previous, uploads: [...previous.uploads, ...value.uploads], next_cursor: value.next_cursor } : value);
      }
    } catch (cause) {
      if (currentQuery.current !== requestQuery) return;
      if (cause instanceof ApiError && cause.status === 401) onExpired();
      setData(null); setError("Unable to load activity. Check your access and refresh.");
    } finally { if (currentQuery.current === requestQuery) setMore(false); }
  }
  async function changeMember() {
    if (!action) return;
    setBusy(true); setError("");
    try { await api(`${base}/people/${action.person.principal_id}`, { method: "POST", body: JSON.stringify({ version: action.person.version, role: action.role }) }); setAction(null); setRefresh(value => value + 1); }
    catch (cause) { if (cause instanceof ApiError && cause.status === 401) onExpired(); else setError(cause instanceof Error ? cause.message : "Unable to update membership"); }
    finally { setBusy(false); }
  }
  async function toggleSignup() {
    if (!policy) return;
    setBusy(true); setError("");
    try { await api(`${base}/registration`, { method: "PUT", body: JSON.stringify({ enabled: !policy.enabled }) }); setRefresh(value => value + 1); }
    catch (cause) { if (cause instanceof ApiError && cause.status === 401) onExpired(); else setError(cause instanceof Error ? cause.message : "Unable to update registration"); }
    finally { setBusy(false); }
  }
  const ownRole = data?.can_manage_roles ? "owner" : "admin";
  return <section aria-label="Workspace dashboard">
    <div className="page-heading"><p className="eyebrow">WORKSPACE OVERVIEW</p><h1>Dashboard</h1><p className="muted">Members, uploads and search preparation. {olderUploads ? "Updates paused while viewing older uploads." : "Updates every 15 seconds."}</p></div>
    {error && <p role="alert" className="error">{error} <button className="secondary" onClick={() => setRefresh(value => value + 1)}>Refresh dashboard</button></p>}
    {!data && !error && <p role="status">Loading workspace activity…</p>}
    {data && <>
      <section className="metric-grid" aria-label="Workspace totals">{[["Members", data.summary.members], ["Current files", data.summary.files], ["Ready to search", data.summary.ready], ["Preparing", data.summary.preparing], ["Needs attention", data.summary.failed]].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>
      <section className="source-card"><div className="source-heading"><div><h2>Activity period</h2><p className="muted">{data.summary.recent_members} new members and {data.summary.recent_uploads} current file uploads in the last {days} days.</p></div><label>Time range<select aria-label="Time range" value={days} onChange={event => setDays(event.target.value)}><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select></label></div>
        {storage && <p>Storage: {(storage.bytes / 1024 ** 2).toFixed(1)} MiB of {(storage.limit_bytes / 1024 ** 3).toFixed(1)} GiB, including original revisions, derivatives and pending uploads.</p>}
        {policy && <div className="registration-setting"><p>New account registration: <strong>{policy.configured ? policy.enabled ? "Open" : "Closed" : "Not configured for this workspace"}</strong></p>{policy.can_change && <button className="secondary" disabled={busy} onClick={() => { void toggleSignup(); }}>{policy.enabled ? "Close registration" : "Open registration"}</button>}</div>}
      </section>
      <section className="source-card" aria-label="Members and their files"><h2>Members and their files</h2><p className="muted">File counts refer to current files attributed to each uploader. Older join dates may not have been recorded.</p>
        {data.directory_limited && <p>Showing the first 101 accounts. The People directory in Settings supports further paging.</p>}
        <div className="dashboard-table-wrap"><table className="dashboard-table"><thead><tr><th>Account</th><th>Role</th><th>Joined</th><th>Files</th><th>Ready</th><th>Actions</th></tr></thead><tbody>{data.people.map(person => <tr key={person.principal_id}><td>{person.username}{person.disabled && " · Disabled"}</td><td>{roles[person.role]}</td><td>{date(person.joined_at)}</td><td>{person.files}</td><td>{person.ready}</td><td><button className="text-button" onClick={() => setMember(person.principal_id)}>View uploads</button>{person.principal_id !== account && person.role !== "owner" && <>{ownRole === "owner" && <button className="text-button" disabled={busy} onClick={() => setAction({ person, role: person.role === "admin" ? "member" : "admin" })}>Make {person.role === "admin" ? "member" : "admin"}</button>}{(ownRole === "owner" || person.role === "member") && <button className="text-button" disabled={busy} onClick={() => setAction({ person, role: null })}>Remove access</button>}</>}</td></tr>)}</tbody></table></div>
        {action && <div className="notice" role="alert"><p>{action.role === null ? `Remove ${action.person.username}'s workspace access? Their shared files remain in the workspace.` : `Make ${action.person.username} a workspace ${action.role}? ${action.role === "admin" ? "Admins can access every collection." : "Their explicit collection grants will remain."}`}</p><button disabled={busy} onClick={() => { void changeMember(); }}>Confirm change</button> <button className="secondary" disabled={busy} onClick={() => setAction(null)}>Cancel</button></div>}
      </section>
      <section className="source-card" aria-label="Upload activity"><h2>Uploads and indexing</h2><p className="muted">Current nondeleted files uploaded in the selected period. Inspect preparation warnings in Library.</p>
        {olderUploads && <p role="status">Automatic refresh is paused to keep older uploads visible. <button className="secondary" onClick={() => setRefresh(value => value + 1)}>Return to latest activity</button></p>}
        <div className="dashboard-filters"><label>Uploader<select aria-label="Uploader" value={member} onChange={event => setMember(event.target.value)}><option value="">All uploaders</option>{data.people.map(person => <option key={person.principal_id} value={person.principal_id}>{person.username}</option>)}</select></label><label>Status<select aria-label="Status" value={status} onChange={event => setStatus(event.target.value)}><option value="">All states</option>{Object.entries(states).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>File type<select aria-label="File type" value={modality} onChange={event => setModality(event.target.value)}><option value="">All types</option>{["document","image","video","audio"].map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
        {!data.uploads.length ? <p>No uploads match these filters.</p> : <div className="dashboard-table-wrap"><table className="dashboard-table"><thead><tr><th>File / collection</th><th>Uploaded by</th><th>Received</th><th>Search preparation</th><th>Original</th></tr></thead><tbody>{data.uploads.map(file => <tr key={file.id}><td><strong>{file.title}</strong><br/><span className="muted">{file.collection}</span></td><td>{file.uploader ?? "Unknown"}</td><td>{date(file.received_at)}</td><td>{states[file.status] ?? file.status}{file.has_warnings && " · preparation warnings"}</td><td><a href={`${base}/sources/${file.source_id}/revisions/${file.revision_id}/original`}>Download original</a></td></tr>)}</tbody></table></div>}
        {data.next_cursor && <button className="secondary" disabled={more} onClick={() => { void moreUploads(); }}>{more ? "Loading uploads…" : "More uploads"}</button>}
        <p><button className="secondary" onClick={onLibrary}>Open Library to inspect or retry files</button></p>
        <h3>Current file uploads by day (UTC)</h3>{!data.trend.length ? <p className="muted">No activity in this period.</p> : <ul className="activity-chart" aria-label="Uploads by day">{data.trend.map(day => <li key={day.day}><span>{day.day}</span><div><span className="activity-bar" style={{ width: `${Math.max(2, day.uploads / Math.max(...data.trend.map(point => point.uploads)) * 100)}%` }}/></div><strong>{day.uploads}</strong></li>)}</ul>}
      </section>
    </>}
  </section>;
}
