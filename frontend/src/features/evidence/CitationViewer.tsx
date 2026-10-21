import { useEffect,useState } from "react";
import { api,ApiError } from "../../lib/api";
import { DocumentViewer } from "./DocumentViewer";
import { MediaViewer } from "./MediaViewer";

export function CitationViewer(props:{workspace:string;source:string;citation:string;onClose:()=>void;onExpired:()=>void}){
  const [kind,setKind]=useState("");const [error,setError]=useState("");
  useEffect(()=>{let current=true;void api<{locator_kind:string}>(`/api/workspaces/${props.workspace}/sources/${props.source}/citations/${props.citation}`).then(value=>{if(current)setKind(value.locator_kind);}).catch(cause=>{if(current){setError(cause instanceof Error?cause.message:"Evidence unavailable");if(cause instanceof ApiError&&cause.status===401)props.onExpired();}});return()=>{current=false;};},[props.workspace,props.source,props.citation,props.onExpired]);
  if(kind==="temporal")return <MediaViewer {...props}/>;
  if(kind)return <DocumentViewer {...props}/>;
  return <div className="citation-loading"><p role={error?"alert":"status"}>{error||"Opening evidence…"}</p><button className="secondary" onClick={props.onClose}>Close citation</button></div>;
}
