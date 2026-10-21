import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../lib/api";
import { CitationViewer } from "../evidence/CitationViewer";

type Locator = { kind:string; page?:number; start_char?:number; end_char?:number; start_ms?:number; end_ms?:number };
type Citation = { id:string; anchor:{ locator:Locator } };
type Context = { segment_id:string; representation:string; snippet:string|null; citations:Citation[] };
type Hit = { segment_id:string; title:string; source_name:string; modality:string; asset:{source_id:string;asset_id:string;revision_id:string}; representation:string; matched_representations:string[]; snippet:string|null; citations:Citation[]; warnings:string[]; branches:Record<string,{rank:number;score:number}>; fusion_score:number; dense_score:number|null; context:Context[] };
type Facet = {source_id:string;source_name:string;modality:string;assets:number};
type Response = {results:Hit[];no_useful_evidence:boolean;generation_id:string;request_id:string;retrieval_config_sha256:string;timings_ms:{total:number};warnings:string[]};
const labels:Record<string,string>={text:"Extracted text",ocr:"OCR text",transcript:"ASR transcript",image:"Native image",video:"Native visual match",audio:"Native sound match"};
const time = (ms:number) => `${Math.floor(ms/60000)}:${((ms%60000)/1000).toFixed(1).padStart(4,"0")}`;
function location(c:Citation){const l=c.anchor.locator;return l.kind==="page"?`Page ${l.page}`:l.kind==="temporal"?`${time(l.start_ms??0)}–${time(l.end_ms??0)}`:`Characters ${l.start_char}–${l.end_char}`;}

export function Search({workspace,onExpired}:{workspace:string;onExpired:()=>void}){
  const [kind,setKind]=useState<"text"|"image">("text");const [image,setImage]=useState<File|null>(null);const [preview,setPreview]=useState("");
  const [query,setQuery]=useState("");const [source,setSource]=useState("");const [modality,setModality]=useState("");
  const [representation,setRepresentation]=useState("");const [language,setLanguage]=useState("");const [tags,setTags]=useState("");
  const [dateField,setDateField]=useState("ingested");const [after,setAfter]=useState("");const [before,setBefore]=useState("");
  const [start,setStart]=useState("");const [end,setEnd]=useState("");const [asset,setAsset]=useState("");
  const [facets,setFacets]=useState<Facet[]>([]);const [indexReady,setIndexReady]=useState<boolean|null>(null);
  const [result,setResult]=useState<Response|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const [opened,setOpened]=useState<{source:string;citation:string}|null>(null);const serial=useRef(0);
  useEffect(()=>{let current=true;let pending=false;
    const refresh=async()=>{if(pending)return;pending=true;try{const v=await api<{ready:boolean;items:Facet[]}>(`/api/workspaces/${workspace}/search/facets`);if(current){setFacets(v.items);setIndexReady(v.ready);}}catch(c){if(current&&c instanceof ApiError&&c.status===401)onExpired();}finally{pending=false;}};
    void refresh();const timer=setInterval(()=>{void refresh();},15000);return()=>{current=false;serial.current++;clearInterval(timer);};
  },[workspace,onExpired]);
  useEffect(()=>{if(!image){setPreview("");return;}const url=URL.createObjectURL(image);setPreview(url);return()=>URL.revokeObjectURL(url);},[image]);
  useEffect(()=>{setImage(null);setResult(null);setOpened(null);},[workspace]);
  async function run(event?:FormEvent,onlyAsset?:string){
    event?.preventDefault();
    if(kind==="image"&&!image){setError("Choose a JPEG or PNG image first.");return;}
    if(after&&before&&after>=before){setError("The end date must be later than the start date.");return;}
    if((start||end)&&Number(end)<=Number(start)){setError("The media end time must be later than the start time.");return;}
    const request=++serial.current;setBusy(true);setError("");setResult(null);
    const filters:Record<string,unknown>={};
    if(source)filters.source_ids=[source];const targetAsset=onlyAsset??asset;if(targetAsset)filters.asset_ids=[targetAsset];
    if(modality)filters.modalities=[modality];if(representation)filters.representations=[representation];
    if(language.trim())filters.languages=[language.trim()];if(tags.trim())filters.tags=tags.split(",").map(t=>t.trim()).filter(Boolean);
    if(after||before)filters.date={field:dateField,...(after?{after:new Date(`${after}T00:00:00Z`).toISOString()}:{}),...(before?{before:new Date(`${before}T00:00:00Z`).toISOString()}: {})};
    if(start||end)filters.media_interval={start_ms:Math.round(Number(start)*1000),end_ms:Math.round(Number(end)*1000)};
    try{
      let payload:Record<string,unknown>={workspace_id:workspace,query,filters};
      if(kind==="image"&&image){
        const encoded=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("Could not read this image."));reader.readAsDataURL(image);});
        payload={workspace_id:workspace,image_base64:encoded,filters};
      }
      const v=await api<Response>(`/api/workspaces/${workspace}/search${kind==="image"?"/image":""}`,{method:"POST",body:JSON.stringify(payload)});if(request===serial.current)setResult(v);
    }
    catch(c){if(request===serial.current){setError(c instanceof Error?c.message:"Search unavailable");if(c instanceof ApiError&&c.status===401)onExpired();}}
    finally{if(request===serial.current)setBusy(false);}
  }
  const sources=[...new Map(facets.map(f=>[f.source_id,f])).values()];
  return <section className="search-section" aria-labelledby="search-heading">
    {opened&&<CitationViewer key={opened.citation} workspace={workspace} {...opened} onClose={()=>setOpened(null)} onExpired={onExpired}/>}
    <h2 id="search-heading">Search your sources</h2><p className="muted">Find passages, visual moments and sounds. Open a match to inspect the original evidence.</p>
    <form onSubmit={run} className="search-form">
      <label>Search with<select value={kind} disabled={busy} onChange={e=>{setKind(e.target.value as "text"|"image");setImage(null);setResult(null);setError("");setAsset("");}}><option value="text">Text</option><option value="image">Image</option></select></label>
      {kind==="text"?<><label htmlFor="query">What are you looking for?</label><div className="search-input"><input id="query" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="For example: a person falling, electronic beeps, electrical safety" maxLength={2000} required/><button disabled={busy||indexReady===false||!query.trim()}>{busy?"Searching…":"Search"}</button></div></>:<>
        <label htmlFor="query-image">Find evidence similar to this image</label><div className="search-input"><input key={workspace} id="query-image" type="file" accept="image/jpeg,image/png" disabled={busy} onChange={e=>{const file=e.target.files?.[0]??null;setResult(null);setError("");setAsset("");if(file&&(file.size>4*1024*1024||file.size===0||!["image/jpeg","image/png"].includes(file.type))){setImage(null);e.target.value="";setError("Choose a JPEG or PNG up to 4 MiB.");return;}setImage(file);}}/><button disabled={busy||indexReady===false||!image}>{busy?"Searching…":"Search"}</button></div>
        {preview&&<img className="query-image-preview" src={preview} alt="Selected query image"/>}<p className="muted">Still JPEG/PNG, up to 4 MiB and 8 million pixels. Used temporarily for search; not added to your sources. Similarity does not establish identity or an action.</p>
      </>}
      <div className="search-filters"><label>Source<select value={source} onChange={e=>{setSource(e.target.value);setAsset("");}}><option value="">All accessible sources</option>{sources.map(f=><option value={f.source_id} key={f.source_id}>{f.source_name}</option>)}</select></label>
      <label>File type<select value={modality} onChange={e=>setModality(e.target.value)}><option value="">All types</option>{["document","image","video","audio"].map(t=><option key={t}>{t}</option>)}</select></label></div>
      <details className="advanced-filters"><summary>More filters</summary><div className="search-filters">
        <label>Matched representation<select value={representation} onChange={e=>setRepresentation(e.target.value)}><option value="">All representations</option>{Object.entries(labels).map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></label>
        <label>Language code<input value={language} onChange={e=>setLanguage(e.target.value)} placeholder="en, or und for unknown" maxLength={30}/></label>
        <label>Tags (all must match)<input value={tags} onChange={e=>setTags(e.target.value)} placeholder="Comma-separated tags" maxLength={300}/></label>
        <label>Date refers to<select value={dateField} onChange={e=>setDateField(e.target.value)}><option value="ingested">Revision imported</option><option value="source_created">Source file created</option><option value="source_modified">Source file modified</option></select></label>
        <label>On or after (UTC)<input type="date" value={after} onChange={e=>setAfter(e.target.value)}/></label><label>Before (UTC, exclusive)<input type="date" value={before} onChange={e=>setBefore(e.target.value)}/></label>
        <label>Media overlap from (seconds)<input type="number" min="0" step="0.001" value={start} onChange={e=>setStart(e.target.value)}/></label><label>Media overlap until (seconds)<input type="number" min="0.001" step="0.001" value={end} onChange={e=>setEnd(e.target.value)} required={!!start}/></label>
      </div><p className="muted">Lists use OR within a filter and AND across filters. Unknown dates do not match a date range. Language is recorded for OCR/ASR; other inputs usually have unknown language. Tags are available through stored metadata.</p></details>
      {asset&&<p>Searching within one file. <button type="button" className="text-button" onClick={()=>{setAsset("");void run(undefined,"");}}>Search all files again</button></p>}
    </form>
    {indexReady===false&&<p role="status">Activate a complete embedding index below to enable search.</p>}
    {busy&&<p role="status">Searching on CPU. The first search may take longer while the model loads.</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    {result&&<div aria-live="polite" className="search-results">
      <p>{result.no_useful_evidence?"No useful evidence found. Try a more specific description or change the filters.":`${result.results.length} evidence matches · ${(result.timings_ms.total/1000).toFixed(2)} s`}</p>
      {result.results.map(hit=><article className="search-hit" key={hit.segment_id}>
        <div className="search-hit-heading"><h3>{hit.title}</h3><span className="muted">{hit.source_name} · {hit.modality}</span></div>
        <p className="match-kind">{hit.matched_representations.map(r=>labels[r]).join(" · ")} · {location(hit.citations[0])}</p>
        {kind==="image"&&hit.dense_score!==null&&<p className="muted">Similarity {hit.dense_score.toFixed(4)} · ranking signal, not confidence</p>}
        {hit.snippet?<p className="search-snippet">{hit.snippet}</p>:<p className="muted">{hit.representation==="audio"?"Listen to this interval to verify the sound match.":"Inspect this visual evidence to verify the match."}</p>}
        <div className="search-hit-actions"><button type="button" onClick={()=>setOpened({source:hit.asset.source_id,citation:hit.citations[0].id})}>Open evidence</button>{!asset&&<button type="button" className="secondary" disabled={busy} onClick={()=>{setAsset(hit.asset.asset_id);void run(undefined,hit.asset.asset_id);}}>More from this file</button>}<a href={`/?workspace=${workspace}&source=${hit.asset.source_id}&citation=${hit.citations[0].id}`} target="_blank" rel="noreferrer">Citation link</a></div>
        {hit.warnings.map(w=><p className="note" key={w}>{w}</p>)}
        <details><summary>Why this matched and nearby evidence</summary><p className="muted">{Object.entries(hit.branches).map(([b,t])=>`${b}: rank ${t.rank}, score ${t.score.toFixed(4)}`).join(" · ")} · Fusion {hit.fusion_score.toFixed(5)}. Scores are ranking signals.</p>
        {hit.citations.length>1&&<div>{hit.citations.slice(1).map(c=><button className="text-button" key={c.id} onClick={()=>setOpened({source:hit.asset.source_id,citation:c.id})}>Matched evidence · {location(c)}</button>)}</div>}
        {hit.context.map(c=><div className="search-context" key={c.segment_id}><p>{labels[c.representation]} · {location(c.citations[0])} · nearby context</p>{c.snippet&&<p className="search-snippet">{c.snippet}</p>}<button className="text-button" onClick={()=>setOpened({source:hit.asset.source_id,citation:c.citations[0].id})}>Open context</button></div>)}
        </details>
      </article>)}
      <details className="search-trace"><summary>Search details and limits</summary>{result.warnings.map(w=><p key={w}>{w}</p>)}<p>Request {result.request_id}<br/>Index {result.generation_id}<br/>Retrieval configuration {result.retrieval_config_sha256}</p></details>
    </div>}
  </section>;
}
