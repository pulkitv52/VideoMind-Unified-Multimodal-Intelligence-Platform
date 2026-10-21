import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { EvidenceFrame } from "./EvidenceFrame";
import type { EvidenceMode } from "./EvidenceFrame";
import { CitationCopy } from "../../components/ui/CitationCopy";

type Segment = {id:string;representation:string;text_content:string|null;citation_id:string;start_char:number|null;end_char:number|null;transform:{box:number[]|null;text_start:number|null;text_end:number|null};quality:{method:string}};
type Document = {segment_set_id:string;revision_id:string;title:string;manifest:{kind?:string;warnings:string[];profile:string;rendering_object_id:string|null};pages:{page:number;image_object_id:string|null;ocr:boolean}[]};
type Page = {page:number;image_object_id:string|null;manifest:{lines:{text:string;start:number;end:number}[]};segments:Segment[]};

export function DocumentViewer({workspace,source,revision,citation,mode,onClose,onExpired}:{workspace:string;source:string;revision?:string;citation?:string;mode?:EvidenceMode;onClose:()=>void;onExpired:()=>void}) {
  const selectedPassage=useRef<HTMLButtonElement>(null);
  const [citedSegment,setCitedSegment]=useState("");
  const [doc,setDoc]=useState<Document|null>(null);
  const [page,setPage]=useState(1);
  const [content,setContent]=useState<Page|null>(null);
  const [selected,setSelected]=useState("");
  const [error,setError]=useState("");

  const base=`/api/workspaces/${workspace}/sources/${source}`;
  useEffect(()=>{
    let current=true;
    setDoc(null);setContent(null);setSelected("");setCitedSegment("");setError("");
    void (async()=>{
      try {
        let target=revision;let initialPage=1;let segment="";let targetSet="";
        if(citation){const resolved=await api<{revision_id:string;page:number|null;segment_id:string;segment_set_id:string}>(`${base}/citations/${citation}`);target=resolved.revision_id;initialPage=resolved.page??1;segment=resolved.segment_id;targetSet=resolved.segment_set_id;}
        if(!target)throw new Error("Evidence unavailable");
        const result=await api<Document>(`${base}/revisions/${target}/document${targetSet?`?segment_set_id=${encodeURIComponent(targetSet)}`:""}`);
        if(current){setDoc(result);setPage(initialPage);setSelected(segment);setCitedSegment(segment);}
      }catch(cause){if(current){setError(cause instanceof ApiError&&[403,404].includes(cause.status)?"Evidence unavailable. Check your collection access.":cause instanceof Error?cause.message:"Evidence unavailable");if(cause instanceof ApiError&&cause.status===401)onExpired();}}
    })();
    return()=>{current=false;};
  },[base,revision,citation,onExpired]);
  useEffect(()=>{
    if(!doc)return;
    let current=true;setContent(null);
    void api<Page>(`${base}/revisions/${doc.revision_id}/document/pages/${page}?segment_set_id=${doc.segment_set_id}`).then(result=>{if(current){setContent(result);setError("");}}).catch(cause=>{if(current){setError(cause instanceof ApiError&&[403,404].includes(cause.status)?"Evidence unavailable. Check your collection access.":cause instanceof Error?cause.message:"Evidence unavailable");if(cause instanceof ApiError&&cause.status===401)onExpired();}});
    return()=>{current=false;};
  },[base,doc,page,onExpired]);
  useEffect(()=>{
    if(content&&selected)selectedPassage.current?.scrollIntoView({block:"center",inline:"nearest",behavior:"auto"});
  },[content,selected]);
  const active=content?.segments.find(s=>s.id===selected);
  const box=active?.transform.box;
  const location=doc?`${base}/revisions/${doc.revision_id}`:"";
  const cite=active?`${window.location.origin}/?workspace=${encodeURIComponent(workspace)}&source=${encodeURIComponent(source)}&citation=${encodeURIComponent(active.citation_id)}`:"";
  return <EvidenceFrame mode={mode} title={doc?.title??"Document evidence"} subtitle={`${doc?.manifest.kind==="image"?"Image evidence":"Extracted content"} · ${doc?.manifest.rendering_object_id?"Word document rendered to PDF":"original revision"}`} onClose={onClose}>

    {error&&<p role="alert" className="error">{error}</p>}
    {!doc&&!error&&<p role="status">Loading document…</p>}
    {doc&&<>
      <div className="document-navigation"><label>Page <select aria-label="Document page" value={page} onChange={e=>{setPage(Number(e.target.value));setSelected("");}}>{doc.pages.map(p=><option key={p.page} value={p.page}>{p.page} of {doc.pages.length}{p.ocr?" · OCR processed":""}</option>)}</select></label><a href={`${location}/original`}>Download this original revision</a>{doc.manifest.rendering_object_id&&<a href={`${location}/document/objects/${doc.manifest.rendering_object_id}?segment_set_id=${doc.segment_set_id}`}>Download rendered PDF</a>}</div>
      {doc.manifest.warnings.length>0&&<p className="muted">{doc.manifest.warnings.join(" · ").replaceAll("_"," ").toLowerCase()}</p>}
      {!content&&!error&&<p role="status">Loading page…</p>}
      {content&&<div className={`document-columns ${content.image_object_id?"":"text-only"}`}>
        {content.image_object_id&&<div><p className="muted">{doc.manifest.kind==="image"?"Original image":doc.manifest.rendering_object_id?"Rendered DOCX page":"Original PDF page preview"}</p><div className="document-image"><img alt={`Page ${page} of ${doc.title}`} src={`${location}/document/objects/${content.image_object_id}?segment_set_id=${doc.segment_set_id}`}/>{box&&<span aria-label="Evidence region" className="evidence-region" style={{left:`${box[0]*100}%`,top:`${box[1]*100}%`,width:`${(box[2]-box[0])*100}%`,height:`${(box[3]-box[1])*100}%`}}/>}</div></div>}
        <div className="document-text"><h3>{doc.manifest.kind==="image"?"Image evidence":"Extracted passages"}</h3>{doc.manifest.kind!=="image"&&<p className="muted">The selected passage is highlighted in yellow. This marks the cited evidence, not individual query words. OCR may contain errors.</p>}
          {content.segments.filter(s=>s.text_content).map(segment=><button key={segment.id} ref={selected===segment.id?selectedPassage:undefined} aria-current={selected===segment.id?"location":undefined} className={`passage ${selected===segment.id?"selected":""}`} onClick={()=>{setSelected(segment.id);}}><span className="passage-label">{selected===segment.id&&<strong className="evidence-label">{segment.id===citedSegment?"Cited passage":"Selected passage"} · </strong>}{segment.representation==="ocr"?"OCR text":"Extracted text"}{segment.start_char!==null?` · characters ${segment.start_char}–${segment.end_char}`:""}</span>{selected===segment.id?<mark className="passage-highlight">{segment.text_content}</mark>:<span>{segment.text_content}</span>}</button>)}
          {!content.segments.some(s=>s.text_content)&&<p className="muted">{doc.manifest.kind==="image"?"Select the image below to copy its evidence citation.":"No readable text was found on this page. The page image remains available as evidence."}</p>}
          {content.image_object_id&&<button className="secondary" onClick={()=>{setSelected(content.segments.find(s=>s.representation==="image")?.id??"");}}>{doc.manifest.kind==="image"?"Cite original image":"Cite full page image"}</button>}
          {active&&<div className="citation-detail"><p>Evidence: {active.representation==="ocr"?"OCR passage":active.representation==="image"?"Page image":"Extracted passage"} · page {page}</p><CitationCopy href={cite}/><details><summary>Evidence details</summary><p className="muted">Revision {doc.revision_id}. This citation references this revision when the file changes.</p></details></div>}
        </div>
      </div>}
    </>}
  </EvidenceFrame>;
}
