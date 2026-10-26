import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { Source } from "../../lib/api";

type Access = { role: "owner" | "admin" | "member"; can_manage_members: boolean };
type Person = { principal_id: string; username: string; role: string; disabled: boolean };
type Directory = { items: Person[]; next_cursor: string | null };
const roleNames: Record<string, string> = { owner: "Owner", admin: "Admin", member: "Member" };

export function WorkspaceAccess({ workspace, onExpired }: { workspace: string; onExpired: () => void }) {
  const [access, setAccess] = useState<Access | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setAccess(null); setDirectory(null); setSources([]); setError("");
    void (async () => {
      try {
        const permissions = await api<Access>(`/api/workspaces/${workspace}/capabilities`);
        const collections = await api<Source[]>(`/api/workspaces/${workspace}/sources`);
        const people = permissions.can_manage_members ? await api<Directory>(`/api/workspaces/${workspace}/people`) : null;
        if (current) { setAccess(permissions); setSources(collections); setDirectory(people); }
      } catch (cause) {
        if (!current) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        else setError("Unable to check workspace access. Try again.");
      }
    })();
    return () => { current = false; };
  }, [workspace, onExpired, retry]);
  async function morePeople() {
    if (!directory?.next_cursor) return;
    setBusy(true); setError("");
    try {
      const next = await api<Directory>(`/api/workspaces/${workspace}/people?after=${encodeURIComponent(directory.next_cursor)}`);
      setDirectory(previous => previous ? { items: [...previous.items, ...next.items], next_cursor: next.next_cursor } : next);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired();
      else { setDirectory(null); setAccess(null); setSources([]); setError("Unable to load people. Check your access and try again."); }
    } finally { setBusy(false); }
  }
  return <>
    <section className="source-card" aria-label="Your workspace access">
      <h2>Your workspace access</h2>
      {error && <p role="alert" className="error">{error} <button className="secondary" onClick={() => setRetry(value => value + 1)}>Retry access check</button></p>}
      {!access && !error && <p role="status">Checking your access…</p>}
      {access && <><p><strong>Workspace role: {roleNames[access.role]}</strong></p>
        {access.role === "owner" ? <p>You can access every collection, manage files and prepare the search index. People below shows the workspace accounts. Use Dashboard to review activity, change admin/member roles and control signup.</p>
          : access.role === "admin" ? <p>You can access every collection, manage files and prepare the search index. Use Dashboard to review activity and manage ordinary members. Owner-only role changes and registration controls are unavailable to admins.</p>
          : <p>Create your own upload collections, add files and search them as preparation completes. You can also open the collections listed below. A Viewer can inspect and download files. A Contributor can also upload files and retry supported processing tasks. Your workspace administrator manages collection access and the search index.</p>}
        <p className="muted">Files in this workspace are accessible to its owner and admins. Copying a citation does not grant someone access.</p>
        <h3>{access.role === "member" ? "Your accessible collections" : "Workspace collections"}</h3>
        {!sources.length ? <p>{access.role === "member" ? "No collections have been shared with you yet. Ask your workspace administrator for access." : "No collections have been added yet."}</p>
          : <ul className="access-collections">{sources.map(source => <li key={source.id}><strong>{source.name}</strong><span>{access.role !== "member" ? "Workspace administrator access" : source.can_admin ? "Collection manager" : source.can_ingest ? "Contributor · can upload" : "Viewer · read only"}</span></li>)}</ul>}
      </>}
    </section>
    {access?.can_manage_members && directory && <section className="source-card" aria-label="People"><h2>People</h2><p className="muted">Accounts in this workspace. This directory is read only. Use Dashboard to manage member access and review uploads.</p>
      <div className="people-list" role="list">{directory.items.map(person => <div role="listitem" key={person.principal_id}><strong>{person.username}</strong><span>{roleNames[person.role] ?? person.role}{person.disabled ? " · Disabled" : ""}</span></div>)}</div>
      {directory.next_cursor && <button className="secondary" disabled={busy} onClick={() => { void morePeople(); }}>{busy ? "Loading people…" : "More people"}</button>}
    </section>}
  </>;
}
