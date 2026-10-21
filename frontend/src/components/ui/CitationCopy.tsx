import { useEffect, useState } from "react";

export function CitationCopy({ href }: { href: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  useEffect(() => setState("idle"), [href]);
  async function copy() {
    try { await navigator.clipboard.writeText(href); setState("copied"); }
    catch { setState("manual"); }
  }
  return <div className="citation-copy"><button className="secondary" type="button" onClick={() => { void copy(); }}>{state === "copied" ? "Citation copied" : "Copy citation"}</button><a href={href}>Open citation link</a>{state === "copied" && <span className="muted" role="status">Link copied to clipboard.</span>}{state === "manual" && <label>Copy this link<input readOnly value={href} onFocus={event => event.currentTarget.select()} /></label>}</div>;
}
