import { useEffect, useRef, useState } from "react";
import type { Hit } from "./types";
let running = 0;
const queue: (() => void)[] = [];
function drain() { while (running < 3 && queue.length) queue.shift()!(); }
export function ResultPreview({ hit, workspace, onExpired }: { hit: Hit; workspace: string; onExpired: () => void }) {
  const target = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState("");
  const preview = hit.preview;
  useEffect(() => {
    setSrc("");
    if (!preview) return;
    let current = true; let url = "";
    const controller = new AbortController();
    const load = () => {
      if (!current) return;
      running++;
      const base = `/api/workspaces/${workspace}/sources/${hit.asset.source_id}/revisions/${hit.asset.revision_id}`;
      void fetch(`${base}/${preview.route}/objects/${preview.object_id}?segment_set_id=${preview.segment_set_id}`, { credentials: "same-origin", signal: controller.signal }).then(async response => {
        if (response.status === 401) { if (current) onExpired(); return; }
        if (!response.ok || !["image/png", "image/jpeg"].includes(response.headers.get("Content-Type")?.split(";")[0] ?? "")) return;
        const blob = await response.blob();
        if (current && blob.size <= 4 * 1024 * 1024) { url = URL.createObjectURL(blob); setSrc(url); }
      }).catch(() => { /* A missing preview retains the usable result fallback. */ }).finally(() => { running--; drain(); });
    };
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); queue.push(load); drain(); }
    }, { rootMargin: "120px" });
    if (target.current) observer.observe(target.current);
    return () => { current = false; observer.disconnect(); controller.abort(); const index = queue.indexOf(load); if (index >= 0) queue.splice(index, 1); if (url) URL.revokeObjectURL(url); };
  }, [preview, workspace, hit.asset.source_id, hit.asset.revision_id, onExpired]);
  return <div ref={target} className={`result-preview preview-${hit.modality}`} aria-hidden="true">{src ? <img src={src} alt="" onError={() => setSrc("")} /> : <><span className="preview-symbol">{({ document: "▤", image: "▧", video: "▷", audio: "♫" } as Record<string, string>)[hit.modality] ?? "▤"}</span><span>{hit.modality === "audio" ? "Audio interval" : `${hit.modality} evidence`}</span></>}</div>;
}
