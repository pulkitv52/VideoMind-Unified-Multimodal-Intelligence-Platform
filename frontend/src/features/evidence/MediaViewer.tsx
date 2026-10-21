import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { EvidenceFrame } from "./EvidenceFrame";
import type { EvidenceMode } from "./EvidenceFrame";
import { CitationCopy } from "../../components/ui/CitationCopy";

type Transform={playback_object_id:string;playback_origin_ms:number;playback_kind:"video"|"audio";words:{word:string;start_ms:number;end_ms:number}[];frames:{object_id:string;original_ms:number}[]};
type Segment={id:string;representation:string;text_content:string|null;start_ms:number;end_ms:number;track:string;citation_id:string;transform:Transform};
type Descriptor={revision_id:string;segment_set_id:string;title:string;playback_object_id:string;manifest:{origin_ms:number;end_ms:number;playback_kind:"video"|"audio";asr_status:string;warnings:string[]}};
const stamp=(ms:number)=>`${Math.floor(ms/60000)}:${(ms%60000/1000).toFixed(3).padStart(6,"0")}`;

export function MediaViewer({workspace,source,revision,citation,mode,onClose,onExpired}:{workspace:string;source:string;revision?:string;citation?:string;mode?:EvidenceMode;onClose:()=>void;onExpired:()=>void}){
  const player=useRef<HTMLMediaElement|null>(null);const seek=useRef(0);
  const [doc,setDoc]=useState<Descriptor|null>(null);const [items,setItems]=useState<Segment[]>([]);const [next,setNext]=useState<number|null>(null);
  const [active,setActive]=useState<Segment|null>(null);const [time,setTime]=useState(0);const [error,setError]=useState("");const [filter,setFilter]=useState("");
  const base=`/api/workspaces/${workspace}/sources/${source}`;
  useEffect(()=>{let current=true;void(async()=>{try{
    let target=revision;let set="";let initial:Segment|null=null;
    if(citation){const c=await api<Segment&{revision_id:string;segment_id:string;segment_set_id:string}>(`${base}/citations/${citation}`);target=c.revision_id;set=c.segment_set_id;initial={...c,id:c.segment_id,citation_id:citation};}
    const d=await api<Descriptor>(`${base}/revisions/${target}/media${set?`?segment_set_id=${set}`:""}`);
    const result=await api<{items:Segment[];next:number|null}>(`${base}/revisions/${target}/media/segments?segment_set_id=${d.segment_set_id}`);
    if(current){setDoc(d);setItems(result.items);setNext(result.next);setActive(initial);seek.current=initial?(initial.start_ms-d.manifest.origin_ms)/1000:0;setTime(initial?.start_ms??d.manifest.origin_ms);}
  }catch(cause){if(current){setError(cause instanceof ApiError&&[403,404].includes(cause.status)?"Evidence unavailable. Check your collection access.":cause instanceof Error?cause.message:"Media unavailable");if(cause instanceof ApiError&&cause.status===401)onExpired();}}})();return()=>{current=false;};},[base,revision,citation,onExpired]);
  const object=active?.transform.playback_object_id??doc?.playback_object_id;
  const kind=active?.transform.playback_kind??doc?.manifest.playback_kind;
  const location=doc?`${base}/revisions/${doc.revision_id}`:"";
  const stream=doc&&object?`${location}/media/objects/${object}?segment_set_id=${doc.segment_set_id}`:"";
  function select(segment:Segment,at=segment.start_ms){seek.current=(at-(doc?.manifest.origin_ms??0))/1000;setActive(segment);setTime(at);if(player.current&&object===segment.transform.playback_object_id)player.current.currentTime=seek.current;}
  async function more(){try{const response=await api<{items:Segment[];next:number|null}>(`${location}/media/segments?segment_set_id=${doc!.segment_set_id}&after=${next}`);setItems(old=>[...old,...response.items]);setNext(response.next);}catch(cause){setError(cause instanceof Error?cause.message:"Unable to load evidence");}}
  const citationLink=active?`${window.location.origin}/?workspace=${encodeURIComponent(workspace)}&source=${encodeURIComponent(source)}&citation=${encodeURIComponent(active.citation_id)}`:"";
  const props={controls:true,preload:"metadata",src:stream,onLoadedMetadata:()=>{if(player.current)player.current.currentTime=seek.current;},onTimeUpdate:()=>{if(player.current&&doc)setTime(Math.round(player.current.currentTime*1000)+doc.manifest.origin_ms);},onError:()=>setError("Playback unavailable. Reopen this media to recheck access and service availability.")};
  return <EvidenceFrame mode={mode} title={doc?.title??"Media evidence"} subtitle="Playback mapped to original timestamps" onClose={onClose}>

    {error&&<p className="error" role="alert">{error}</p>}{!doc&&!error&&<p role="status">Loading media…</p>}
    {doc&&<><div className="media-columns"><div className="media-player-panel">
      {kind==="video"?<video key={object} ref={node=>{player.current=node;}} {...props}/>:<audio key={object} ref={node=>{player.current=node;}} {...props}/>}
      {active&&<div className="matched-interval"><span>Matched interval</span><strong>{stamp(active.start_ms)}–{stamp(active.end_ms)}</strong></div>}
      <p className="muted">Original time {stamp(time)} · {stamp(doc.manifest.origin_ms)}–{stamp(doc.manifest.end_ms)}</p>
      <a href={`${location}/original`}>Download this original revision</a>
      {doc.manifest.asr_status==="partial"&&<p className="error">Transcription could not finish. Native audio and playback are available. Retry media processing from the file list.</p>}
      {doc.manifest.asr_status==="ready"&&!items.some(s=>s.representation==="transcript")&&next===null&&<p className="muted">No speech was transcribed. Native audio windows include non-speech sounds.</p>}
      {doc.manifest.warnings?.length>0&&<p className="notice">{doc.manifest.warnings.join(" · ").replaceAll("_"," ").toLowerCase()}</p>}
      {active&&<div className="citation-detail"><p>{active.representation==="transcript"?"ASR transcript":active.representation==="video"?"Visual evidence":"Native audio evidence"} · {stamp(active.start_ms)}–{stamp(active.end_ms)} · {active.track}</p>
      {active.transform.words.length>0&&<p className="transcript-words">{active.transform.words.map((word,i)=><button key={i} className={time>=word.start_ms&&time<word.end_ms?"word current":"word"} onClick={()=>select(active,word.start_ms)}>{word.word}</button>)}</p>}
      {active.representation==="transcript"&&<p className="muted">Speech recognition may contain errors.</p>}<CitationCopy href={citationLink}/><details><summary>Evidence details</summary><p className="muted">Citation revision: {doc.revision_id}. Visual windows are sampled evidence, not detected event boundaries.</p></details></div>}
    </div><div className="media-evidence"><h3>Timeline evidence</h3>{new Set(items.map(s=>s.representation)).size>1&&<label>Show<select aria-label="Evidence type" value={filter} onChange={e=>setFilter(e.target.value)}><option value="">All evidence</option>{Array.from(new Set(items.map(s=>s.representation))).map(type=><option key={type} value={type}>{type==="video"?"Visual windows":type==="audio"?"Native audio windows":"ASR transcript"}</option>)}</select></label>}
      {items.filter(s=>!filter||s.representation===filter).map(segment=><button key={segment.id} className={`passage ${active?.id===segment.id?"selected":""}`} onClick={()=>select(segment)}>
        <span className="passage-label">{segment.representation==="transcript"?"ASR transcript":segment.representation==="video"?"Visual window":"Native audio window"} · {stamp(segment.start_ms)}–{stamp(segment.end_ms)} · {segment.track}</span>
        {segment.transform.frames[0]&&<img className="media-thumbnail" alt={`Visual sample at ${stamp(segment.transform.frames[0].original_ms)}`} loading="lazy" src={`${location}/media/objects/${segment.transform.frames[0].object_id}?segment_set_id=${doc.segment_set_id}`}/>}
        {segment.text_content&&<span>{segment.text_content}</span>}
      </button>)}{next!==null&&<button className="secondary" onClick={()=>{void more();}}>Load more evidence</button>}
    </div></div></>}
  </EvidenceFrame>;
}
