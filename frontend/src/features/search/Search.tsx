import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../lib/api";
import { useCompact } from "../../app/useCompact";
import { CitationViewer } from "../evidence/CitationViewer";
import { CitationCopy } from "../../components/ui/CitationCopy";
import type { EvidenceLink } from "../../app/navigation";
import type { Citation, Facet, SearchResponse } from "./types";

const labels: Record<string, string> = { text: "Extracted text", ocr: "Scanned text", transcript: "Speech transcript", image: "Image match", video: "Visual match", audio: "Sound match" };
const time = (ms: number) => `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(1).padStart(4, "0")}`;
function location(citation: Citation) {
  const value = citation.anchor.locator;
  return value.kind === "page" ? `Page ${value.page}` : value.kind === "temporal" ? `${time(value.start_ms ?? 0)}–${time(value.end_ms ?? 0)}` : `Characters ${value.start_char}–${value.end_char}`;
}
type Props = {
  workspace: string; active: boolean; canManage: boolean; onExpired: () => void;
  onLibrary: () => void; onSettings: () => void; opened: EvidenceLink | null;
  onOpen: (value: { source: string; citation: string }) => void; onClose: () => void;
};

export function Search({ workspace, active, canManage, onExpired, onLibrary, onSettings, opened, onOpen, onClose }: Props) {
  const [kind, setKind] = useState<"text" | "image">("text");
  const [image, setImage] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [modality, setModality] = useState("");
  const [representation, setRepresentation] = useState("");
  const [language, setLanguage] = useState("");
  const [tags, setTags] = useState("");
  const [dateField, setDateField] = useState("ingested");
  const [after, setAfter] = useState(""); const [before, setBefore] = useState("");
  const [start, setStart] = useState(""); const [end, setEnd] = useState("");
  const [asset, setAsset] = useState("");
  const [facets, setFacets] = useState<Facet[]>([]);
  const [indexReady, setIndexReady] = useState<boolean | null>(null);
  const [result, setResult] = useState<{ data: SearchResponse; description: string; kind: string; scope: string } | null>(null);
  const [pendingDescription, setPendingDescription] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [facetError, setFacetError] = useState("");
  const compact = useCompact();
  const serial = useRef(0); const list = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const previouslyOpened = useRef(false);
  useEffect(() => {
    if (opened) {
      if (document.activeElement instanceof HTMLElement && !document.activeElement.closest(".evidence-pane")) returnFocus.current = document.activeElement;
    } else if (previouslyOpened.current) {
      returnFocus.current?.focus({ preventScroll: true });
    }
    previouslyOpened.current = !!opened;
  }, [opened]);
  useEffect(() => {
    if (!opened) return;
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); onClose(); } };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [opened, onClose]);
  useEffect(() => {
    if (opened && !compact) list.current?.scrollIntoView({ block: "start" });
  }, [opened?.citation, compact]);
  useEffect(() => {
    if (!opened || !compact || !active) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [opened, compact, active]);
  useEffect(() => () => { serial.current++; }, []);
  useEffect(() => {
    if (!active) return;
    let current = true; let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await api<{ ready: boolean; items: Facet[] }>(`/api/workspaces/${workspace}/search/facets`);
        if (current) { setFacets(value.items); setIndexReady(value.ready); setFacetError(""); }
      } catch (cause) {
        if (current) {
          if (cause instanceof ApiError && cause.status === 401) onExpired();
          else { setFacetError("Unable to check searchable files. Check local services in Settings."); if (cause instanceof ApiError && [403, 404].includes(cause.status)) { setFacets([]); setResult(null); setIndexReady(false); } }
        }
      } finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => { void refresh(); }, 15000);
    return () => { current = false; clearInterval(timer); };
  }, [workspace, onExpired, active]);
  useEffect(() => {
    if (!image) { setPreview(""); return; }
    const url = URL.createObjectURL(image); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);
  async function run(event?: FormEvent, onlyAsset?: string) {
    event?.preventDefault();
    if (kind === "image" && !image) { setError("Choose a JPEG or PNG image first."); return; }
    if (kind === "text" && !query.trim()) { setError("Describe what you are looking for."); return; }
    if (after && before && after >= before) { setError("The end date must be later than the start date."); return; }
    if ((start || end) && (Number(end) <= Number(start) || Number(start) < 0)) { setError("The media end time must be later than the start time."); return; }
    const request = ++serial.current;
    const description = kind === "image" ? `image ${image!.name}` : `“${query}”`;
    setBusy(true); setError(""); setPendingDescription(description);
    if (opened) onClose();
    const filters: Record<string, unknown> = {};
    if (source) filters.source_ids = [source];
    const targetAsset = onlyAsset ?? asset;
    if (targetAsset) filters.asset_ids = [targetAsset];
    if (modality) filters.modalities = [modality];
    if (representation) filters.representations = [representation];
    if (language.trim()) filters.languages = [language.trim()];
    if (tags.trim()) filters.tags = tags.split(",").map(value => value.trim()).filter(Boolean);
    if (after || before) filters.date = { field: dateField, ...(after ? { after: new Date(`${after}T00:00:00Z`).toISOString() } : {}), ...(before ? { before: new Date(`${before}T00:00:00Z`).toISOString() } : {}) };
    if (start || end) filters.media_interval = { start_ms: Math.round(Number(start) * 1000), end_ms: Math.round(Number(end) * 1000) };
    const scope = [source ? facets.find(value => value.source_id === source)?.source_name ?? "Selected collection" : "All accessible collections", modality || "All file types", representation ? labels[representation] : "", language.trim() ? `Language: ${language.trim()}` : "", tags.trim() ? `Tags: ${tags.trim()}` : "", after || before ? `${dateField.replaceAll("_", " ")}: ${after || "any start"} to ${before || "any end"}` : "", start || end ? `Media: ${start || "0"}–${end} seconds` : "", targetAsset ? "Within one file" : ""].filter(Boolean).join(" · ");
    try {
      let payload: Record<string, unknown> = { workspace_id: workspace, query, filters };
      if (kind === "image" && image) {
        const encoded = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(new Error("Could not read this image.")); reader.readAsDataURL(image); });
        payload = { workspace_id: workspace, image_base64: encoded, filters };
      }
      const value = await api<SearchResponse>(`/api/workspaces/${workspace}/search${kind === "image" ? "/image" : ""}`, { method: "POST", body: JSON.stringify(payload) });
      if (request === serial.current) setResult({ data: value, description, kind, scope });
    } catch (cause) {
      if (request === serial.current) {
        setError(cause instanceof TypeError ? "Unable to reach local services. Check the connection and try Search again." : cause instanceof Error ? cause.message : "Search unavailable. Try again.");
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        if (cause instanceof ApiError && [403, 404].includes(cause.status)) setResult(null);
      }
    } finally { if (request === serial.current) setBusy(false); }
  }
  const sources = [...new Map(facets.map(value => [value.source_id, value])).values()];
  const hasFilters = !!(source || modality || representation || language || tags || after || before || start || end || asset);
  function resetFilters() { setSource(""); setModality(""); setRepresentation(""); setLanguage(""); setTags(""); setAfter(""); setBefore(""); setStart(""); setEnd(""); setAsset(""); }
  function changeKind(value: "text" | "image") { serial.current++; setBusy(false); setKind(value); setImage(null); setError(""); setAsset(""); }
  const resultInert = !!opened && compact;
  return <section className="search-section" aria-labelledby="search-heading">
    <div inert={resultInert || undefined}>
      <div className="page-heading"><p className="eyebrow">FIND THE ORIGINAL</p><h1 id="search-heading">What are you looking for?</h1><p className="muted">Search across documents, images, videos and audio. Open a match to see it for yourself.</p></div>
      <form onSubmit={run} className="search-form">
        <div className="query-heading"><label htmlFor={kind === "text" ? "query" : "query-image"}>{kind === "text" ? "Describe a passage, scene or sound" : "Choose a similar image"}</label><div className="query-modes" role="group" aria-label="Search with"><button type="button" aria-pressed={kind === "text"} onClick={() => changeKind("text")}>Text</button><button type="button" aria-pressed={kind === "image"} onClick={() => changeKind("image")}>Image</button></div></div>
        {kind === "text" ? <div className="search-input"><input id="query" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="For example, a person bending down" maxLength={2000} required /><button disabled={busy || indexReady === false || !query.trim()}>{busy ? "Searching…" : "Search"}</button></div> : <><div className="search-input"><input key={workspace} aria-label="Query image" id="query-image" type="file" accept="image/jpeg,image/png" onChange={event => {
          serial.current++; setBusy(false); setError(""); setAsset("");
          const file = event.target.files?.[0] ?? null;
          if (file && (file.size > 4 * 1024 * 1024 || file.size === 0 || !["image/jpeg", "image/png"].includes(file.type))) { setImage(null); event.target.value = ""; setError("Choose a JPEG or PNG up to 4 MiB."); return; }
          setImage(file);
        }} /><button disabled={busy || indexReady === false || !image}>{busy ? "Searching…" : "Search"}</button></div>{preview && <img className="query-image-preview" src={preview} alt="Selected query image" />}<p className="muted helper">JPEG/PNG, up to 4 MiB and 8 million pixels. Used temporarily for search; never added to your collections. Similarity does not establish identity or an action.</p></>}
        <div className="search-filters"><label>Collection<select value={source} onChange={event => { setSource(event.target.value); setAsset(""); }}><option value="">All accessible collections</option>{sources.map(value => <option value={value.source_id} key={value.source_id}>{value.source_name}</option>)}</select></label><label>File type<select value={modality} onChange={event => setModality(event.target.value)}><option value="">All types</option>{["document", "image", "video", "audio"].map(type => <option key={type} value={type}>{type.charAt(0).toUpperCase() + type.slice(1)}</option>)}</select></label></div>
        <details className="advanced-filters"><summary>More filters</summary><div className="search-filters">
          <label>Matched content<select value={representation} onChange={event => setRepresentation(event.target.value)}><option value="">All representations</option>{Object.entries(labels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label>Language code<input value={language} onChange={event => setLanguage(event.target.value)} placeholder="en, or und for unknown" maxLength={30} /></label>
          <label>Tags (all must match)<input value={tags} onChange={event => setTags(event.target.value)} placeholder="Comma-separated tags" maxLength={300} /></label>
          <label>Date refers to<select value={dateField} onChange={event => setDateField(event.target.value)}><option value="ingested">Revision imported</option><option value="source_created">Source file created</option><option value="source_modified">Source file modified</option></select></label>
          <label>On or after (UTC)<input type="date" value={after} onChange={event => setAfter(event.target.value)} /></label><label>Before (UTC, exclusive)<input type="date" value={before} onChange={event => setBefore(event.target.value)} /></label>
          <label>Media from (seconds)<input type="number" min="0" step="0.001" value={start} onChange={event => setStart(event.target.value)} /></label><label>Media until (seconds)<input type="number" min="0.001" step="0.001" value={end} onChange={event => setEnd(event.target.value)} required={!!start} /></label>
        </div><p className="muted helper">Filters combine to narrow your results. Unknown dates do not match a date range. Language is recorded for recognised text/speech; other inputs usually have unknown language. Tags come from stored metadata.</p></details>
        {hasFilters && <div className="filter-summary"><span>Filters selected{asset ? " · searching within one file" : ""}</span><button type="button" className="text-button" onClick={resetFilters}>Clear filters</button></div>}
        {asset && <button type="button" className="text-button" disabled={busy} onClick={() => { setAsset(""); void run(undefined, ""); }}>Search all files again</button>}
      </form>
      {indexReady === false && !facetError && <div className="notice"><h2>Prepare your files for search</h2><p>{canManage ? "Add files in Library, then start and activate your first search index in Settings." : "Your workspace administrator needs to prepare and activate a search index before you can search."}</p><button className="secondary" onClick={onLibrary}>Open Library</button>{canManage && <button className="secondary" onClick={onSettings}>Set up search</button>}</div>}
      {facetError && <p role="alert" className="error">{facetError}</p>}
      {busy && <p role="status">Searching for {pendingDescription}. The first search may take longer while the CPU model loads.</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
    <div className={`search-workbench ${opened ? "has-evidence" : ""}`}>
      <div className="results-column" ref={list} inert={resultInert || undefined}>
        {!result && !busy && !error && indexReady !== false && <div className="search-welcome"><h2>A page, a moment, a sound.</h2><p>Describe what you need. Every match leads back to the original file.</p><p className="muted">Try “person falling”, “person bending down” or “men entering an empty room”. These are example descriptions; matches depend on your files.</p><button className="secondary" onClick={onLibrary}>Browse your Library</button></div>}
        {result && <div className="search-results" aria-busy={busy}><div className="results-heading"><h2>{busy ? "Previous results" : "Results"}</h2><p>For {result.description}</p><p className="muted helper">{result.scope}</p><span className="muted" role="status">{result.data.results.length} evidence {result.data.results.length === 1 ? "match" : "matches"}{busy ? " from the previous search" : ""}</span></div>
          {result.data.no_useful_evidence && <div className="empty"><h3>No useful matches found</h3><p>Try a different description or adjust the filters. This does not establish that the event is absent from your files.</p></div>}
          {result.data.results.map(hit => <article className={`search-hit ${opened?.citation === hit.citations[0].id ? "is-selected" : ""}`} key={hit.segment_id}>
            <div className="result-overline"><span className="file-type">{hit.modality}</span><span>{hit.source_name}</span></div><div className="search-hit-heading"><h3>{hit.title}</h3></div>
            <p className="match-kind">{hit.matched_representations.map(value => labels[value] ?? value).join(" · ")} · {location(hit.citations[0])}</p>
            {hit.snippet ? <p className="search-snippet">{hit.snippet}</p> : <p className="muted">{hit.representation === "audio" ? "Listen to this interval to verify the sound match." : "Inspect the original evidence to verify this visual match."}</p>}
            <div className="search-hit-actions"><button type="button" onClick={() => onOpen({ source: hit.asset.source_id, citation: hit.citations[0].id })}>Open evidence</button>{!asset && <button type="button" className="text-button" disabled={busy} onClick={() => { setAsset(hit.asset.asset_id); void run(undefined, hit.asset.asset_id); }}>Search within this file</button>}</div>
            {hit.warnings.map(warning => <p className="notice helper" key={warning}>{warning}</p>)}
            <details><summary>Match details and nearby evidence</summary><CitationCopy href={`${window.location.origin}/?workspace=${workspace}&source=${hit.asset.source_id}&citation=${hit.citations[0].id}`} /><p className="muted">{Object.entries(hit.branches).map(([branch, trace]) => `${branch}: rank ${trace.rank}, score ${trace.score.toFixed(4)}`).join(" · ")} · Fusion {hit.fusion_score.toFixed(5)}. Scores are ranking signals, not confidence.</p>
              {hit.citations.slice(1).map(citation => <button className="text-button" key={citation.id} onClick={() => onOpen({ source: hit.asset.source_id, citation: citation.id })}>Matched evidence · {location(citation)}</button>)}
              {hit.context.map(context => <div className="search-context" key={context.segment_id}><p>{labels[context.representation]} · {location(context.citations[0])} · nearby context</p>{context.snippet && <p className="search-snippet">{context.snippet}</p>}<button className="text-button" onClick={() => onOpen({ source: hit.asset.source_id, citation: context.citations[0].id })}>Open context</button></div>)}
            </details>
          </article>)}
          <details className="search-trace"><summary>Search details and limits</summary>{result.data.warnings.map(warning => <p key={warning}>{warning}</p>)}<p>Search time {(result.data.timings_ms.total / 1000).toFixed(2)} s<br />Request {result.data.request_id}<br />Index {result.data.generation_id}<br />Retrieval configuration {result.data.retrieval_config_sha256}</p></details>
        </div>}
      </div>
      {opened && <aside className="evidence-pane" aria-label="Selected evidence"><CitationViewer key={`${opened.source}:${opened.citation}`} workspace={workspace} source={opened.source} citation={opened.citation} mode="panel" onClose={onClose} onExpired={onExpired} /></aside>}
    </div>
  </section>;
}
