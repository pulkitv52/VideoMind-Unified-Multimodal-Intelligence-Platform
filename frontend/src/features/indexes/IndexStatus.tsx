import {useCallback,useEffect,useState,useRef} from "react";
import {api,ApiError} from "../../lib/api";
type Generation={id:string;status:string;fingerprint:string;coverage:{eligible_assets:number;published_assets:number;assets_without_ready_inputs:number;partial_extraction_assets:number;jobs:Record<string,number>}};
export function IndexStatus({workspace,onExpired}:{workspace:string;onExpired:()=>void}){
 const [rows,setRows]=useState<Generation[]>([]),[manage,setManage]=useState(false),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const refreshing=useRef(false);
 const base=`/api/workspaces/${workspace}/indexes`;
 const refresh=useCallback(async()=>{if(refreshing.current)return;refreshing.current=true;try{const data=await api<{can_manage:boolean;generations:Generation[]}>(base);setRows(data.generations);setManage(data.can_manage);setError("");}catch(e){if(e instanceof ApiError&&e.status===401)onExpired();else setError(e instanceof Error?e.message:"Unable to load indexing status");}finally{refreshing.current=false;}},[base,onExpired]);
 useEffect(()=>{void refresh();const timer=setInterval(()=>{void refresh();},5000);return()=>clearInterval(timer);},[refresh]);
 async function action(path:string){setBusy(true);setError("");try{await api(base+path,{method:"POST"});await refresh();}catch(e){setError(e instanceof Error?e.message:"Indexing request failed");}finally{setBusy(false);}}
 if(!manage)return null;
 return <section className="source-card" aria-label="Embedding index"><div className="source-heading"><div><h2>Embedding index</h2><p className="muted">EmbeddingGemma 2 · CPU · shared multimodal index</p></div>{!rows.some(g=>g.status==="building")&&<button disabled={busy} onClick={()=>{void action("");}}>{rows.length?"Build new generation":"Start indexing"}</button>}</div>
 {error&&<p role="alert" className="error">{error}</p>}
 {!rows.length&&<p>Prepared documents, frames and audio are ready to embed.</p>}
 {rows.map(g=><div key={g.id} className="index-generation"><p><strong>{g.status==="active"?"Active index":g.status==="standby"?"Previous generation":g.status==="building"?"Building index":g.status}</strong> · {g.coverage.published_assets} / {g.coverage.eligible_assets} assets indexed <small className="muted">· profile {g.fingerprint.slice(0,10)}</small></p>
 {g.coverage.assets_without_ready_inputs>0&&<p className="muted">{g.coverage.assets_without_ready_inputs} files have no ready extraction inputs.</p>}
 {g.coverage.partial_extraction_assets>0&&<p className="muted">{g.coverage.partial_extraction_assets} files have partial extraction; available representations are indexed.</p>}
 {(g.coverage.jobs.failed??0)>0&&<p className="error">{g.coverage.jobs.failed} embedding jobs failed. <button disabled={busy} onClick={()=>{void action(`/${g.id}/retry`);}}>Retry failed jobs</button></p>}
 {g.status!=="active"&&g.coverage.eligible_assets>0&&g.coverage.published_assets===g.coverage.eligible_assets&&<button disabled={busy} onClick={()=>{void action(`/${g.id}/activate`);}}>{g.status==="standby"?"Restore this generation":"Activate index"}</button>}
 </div>)}
 </section>;
}
