import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
export const accepted = ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.mp4,.webm,.mp3,.wav,.m4a,.flac,.ogg";
type Receipt = { file: File; state: "waiting" | "uploading" | "received" | "failed"; error?: string };
export function UploadFiles({ resolveBase, onReceived, onExpired, onBusy }: { resolveBase: () => Promise<string>; onReceived: (base: string) => Promise<void>; onExpired: () => void; onBusy?: (busy: boolean) => void }) {
  const [items, setItems] = useState<Receipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const lock = useRef(false);
  const receiptBase = useRef("");
  const mounted = useRef(true);
  const request = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current?.abort(); }; }, []);
  const input = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  function validate(file: File) {
    if (!file.size) return "This file is empty.";
    if (file.size > 64 * 1024 * 1024) return "Exceeds the 64 MiB file limit.";
    if (!accepted.split(",").some(extension => file.name.toLowerCase().endsWith(extension))) return "Unsupported file type. Choose a supported format.";
    return "";
  }
  async function upload(batch: Receipt[], retry = false) {
    if (lock.current || !batch.length) return;
    lock.current = true; setBusy(true); onBusy?.(true);
    const next = batch.map(item => item.state === "received" ? item : { ...item, state: "waiting" as const, error: undefined });
    const update = () => setItems(next.map(item => ({ ...item })));
    update(); let base = retry ? receiptBase.current : "";
    if (!retry) receiptBase.current = "";
    try {
      for (const item of next) {
        if (!mounted.current) break;
        if (item.state === "received") continue;
        const invalid = validate(item.file);
        if (invalid) { item.state = "failed"; item.error = invalid; update(); continue; }
        item.state = "uploading"; update();
        try {
          base ||= await resolveBase();
          receiptBase.current = base;
          if (!mounted.current) break;
          request.current = new AbortController();
          const response = await fetch(`${base}/files?filename_value=${encodeURIComponent(item.file.name)}`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" }, body: item.file, signal: request.current.signal });
          const body = await response.json().catch(() => ({ detail: "Upload failed" }));
          if (!response.ok) throw new ApiError(response.status, body.detail ?? "Upload failed");
          item.state = "received"; update();
        } catch (cause) {
          item.state = "failed"; item.error = cause instanceof Error ? cause.message : "Upload failed. Try again."; update();
          if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { if (cause.status === 401) onExpired(); break; }
        }
      }
      if (mounted.current && next.some(item => item.state === "received")) await onReceived(base);
    } finally { lock.current = false; setBusy(false); onBusy?.(false); }
  }
  const received = items.filter(item => item.state === "received").length;
  const retryable = items.some(item => item.state === "failed" || item.state === "waiting");
  return <div className="upload-area">
    <div className={`upload-drop ${dragging ? "is-dragging" : ""}`} onDragEnter={event => { event.preventDefault(); depth.current++; setDragging(true); }} onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = busy ? "none" : "copy"; }} onDragLeave={event => { event.preventDefault(); if (--depth.current <= 0) setDragging(false); }} onDrop={event => { event.preventDefault(); depth.current = 0; setDragging(false); if (!lock.current) void upload(Array.from(event.dataTransfer.files).map(file => ({ file, state: "waiting" }))); }}>
      <strong>Drop files here</strong><span className="muted">or choose them from your computer</span>
      <button type="button" disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : "Choose files"}</button>
      <input ref={input} aria-label="Upload files" className="visually-hidden" tabIndex={-1} type="file" multiple accept={accepted} disabled={busy} onChange={event => { void upload(Array.from(event.target.files ?? []).map(file => ({ file, state: "waiting" }))); event.target.value = ""; }} />
      <span className="muted helper">PDF, DOCX, text, images, video and audio · 64 MiB per file · media up to 5 minutes</span>
    </div>
    {items.length > 0 && <div className="upload-receipts"><p role="status">{busy ? "Uploading files…" : `${received} of ${items.length} files received.`} {received > 0 && "Received files prepare in the background."}</p><ul>{items.map((item, index) => <li key={index}><span>{item.file.name}</span><span className={item.state === "failed" ? "error" : "muted"}>{item.state === "received" ? "Received" : item.state === "failed" ? item.error : item.state === "uploading" ? "Uploading…" : "Not sent yet"}</span></li>)}</ul>{!busy && retryable && <><p className="muted helper">Retries use the original destination collection.</p><button className="secondary" type="button" onClick={() => { void upload(items, true); }}>Retry failed or unsent files</button></>}</div>}
  </div>;
}
