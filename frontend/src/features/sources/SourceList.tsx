import { useCallback, useEffect, useState, useRef } from "react";
import type { FormEvent } from "react";
import { api, apiPage, ApiError } from "../../lib/api";
import { MediaViewer } from "../evidence/MediaViewer";
import { DocumentViewer } from "../evidence/DocumentViewer";
import type { Source } from "../../lib/api";
import { UploadFiles } from "./UploadFiles";
import { fileState, hasLimitations } from "./fileState";
import type { Asset } from "./fileState";

type Job = {id:string;kind:string;status:string;error_code:string|null;manifest:{files_seen?:number;files_expected?:number;unchanged?:number;deleted?:number}};
const terminal = (status:string) => ["stored","failed","cancelled"].includes(status);
const statusText = (status:string) => status === "stored" ? "Original validated" : status === "running" ? "Validating…" : status === "queued" ? "Waiting for validation" : status;

function documentError(code:string) {
  const messages:Record<string,string>={DOCUMENT_STORAGE_LIMIT:"Workspace storage limit reached. Free stored content before retrying extraction.",DOCUMENT_PAGE_LIMIT:"Document exceeds 50 pages. Split it into smaller files.",DOCUMENT_TEXT_LIMIT:"Document exceeds the text limit. Split it into smaller files.",DOCUMENT_TIMEOUT:"Extraction exceeded three minutes. Split the document and retry.",DOCUMENT_ENCRYPTED:"Password-protected PDF. Upload an unlocked copy.",DOCUMENT_RENDER_FAILED:"Document rendering failed. Try exporting it to PDF and uploading that copy.",EXTERNAL_DOCUMENT_RESOURCE:"DOCX links to external content. Embed that content or export to PDF.",SANDBOX_UNAVAILABLE:"Document sandbox is unavailable on this host. Check the documented Linux requirements.",DOCUMENT_RESOURCE_LIMIT:"Document exceeded a parser resource limit. Split it or export a simpler PDF.",DOCUMENT_CORRUPT:"Document could not be parsed. Export a new PDF and try again.",STRUCTURAL_VALIDATION_FAILED:"File validation failed. Export a fresh copy and try again."};
  return messages[code]??`${code.replaceAll("_"," ").toLowerCase()}. Try a simpler PDF or smaller document.`;
}

function mediaError(code:string){const messages:Record<string,string>={MEDIA_DURATION_LIMIT:"Media exceeds five minutes. Split it into shorter clips.",MEDIA_TIMEOUT:"Processing exceeded ten minutes. Split the media and retry.",MEDIA_TRACK_LIMIT:"Use at most one video track and two audio tracks.",MEDIA_ALIGNMENT_FAILED:"Playback timestamps could not be verified. Export a fresh copy and retry.",MEDIA_STORAGE_LIMIT:"Workspace storage limit reached. Free stored content before retrying.",MEDIA_TIMELINE_UNSUPPORTED:"Unsupported or non-monotonic timestamps. Export a fresh copy.",MEDIA_DECODE_FAILED:"Media decoding failed. Export a fresh MP4 or WAV and retry."};return messages[code]??`${code.replaceAll("_"," ").toLowerCase()}. Try a shorter or simpler media file.`;}

function SourceFiles({source,workspace,onExpired,onRemoved,active,onSearch,onSettings,canManage}: {source:Source;workspace:string;onExpired:()=>void;onRemoved:()=>void;active:boolean;onSearch:()=>void;onSettings:()=>void;canManage:boolean}) {
  const base=`/api/workspaces/${workspace}/sources/${source.id}`;
  const [mediaView,setMediaView]=useState<Asset|null>(null);
  const [viewing,setViewing]=useState<Asset|null>(null);
  useEffect(()=>{if(!active){setMediaView(null);setViewing(null);}},[active]);
  const [assets,setAssets]=useState<Asset[]>([]);
  const [loaded,setLoaded]=useState(false);
  const refreshing=useRef(false);
  const [pages,setPages]=useState(1);
  const [next,setNext]=useState("");
  const [total,setTotal]=useState(0);
  const [jobs,setJobs]=useState<Job[]>([]);
  const [error,setError]=useState("");
  const [loadError,setLoadError]=useState("");
  const [busy,setBusy]=useState(false);
  const [confirmRemove,setConfirmRemove]=useState(false);
  const fail=useCallback((cause:unknown)=>{if(cause instanceof ApiError && cause.status===401) onExpired(); else setError(cause instanceof Error?cause.message:"Request failed");},[onExpired]);
  const refresh=useCallback(async()=>{
    if(refreshing.current)return;
    refreshing.current=true;
    try {
      const files:Asset[]=[];let cursor="";let count=0;
      for(let page=0;page<pages;page++) {
        const result=await apiPage<Asset>(`${base}/assets?limit=50${cursor?`&after=${cursor}`:""}`);
        files.push(...result.items);cursor=result.next;count=result.total;
        if(!cursor)break;
      }
      const status=await api<Job[]>(`${base}/jobs?kind=folder_sync&limit=1`);
      setAssets(files);setNext(cursor);setTotal(count);setJobs(status);setLoaded(true);setLoadError("");
    }
    catch(cause){if(cause instanceof ApiError&&cause.status===401)fail(cause);else setLoadError(cause instanceof Error?cause.message:"Unable to refresh files");}
    finally{refreshing.current=false;}
  },[base,fail,pages]);
  useEffect(()=>{if(!active)return;void refresh();const timer=setInterval(()=>{void refresh();},4000);return()=>clearInterval(timer);},[refresh,active]);
  async function action(path:string,method="POST") {setError("");try{await api(`${base}${path}`,{method});await refresh();}catch(cause){fail(cause);}}
  async function remove(){setBusy(true);try{await api(base,{method:"DELETE"});onRemoved();}catch(cause){fail(cause);}finally{setBusy(false);}}
  const folderJobs=jobs.filter(j=>j.kind==="folder_sync");
  const pending=jobs.some(j=>!terminal(j.status));
  return <section className="source-card">
    {mediaView&&<MediaViewer workspace={workspace} source={source.id} revision={mediaView.revision_id} onClose={()=>setMediaView(null)} onExpired={onExpired}/>}
    {viewing&&<DocumentViewer workspace={workspace} source={source.id} revision={viewing.revision_id} onClose={()=>setViewing(null)} onExpired={onExpired}/>}
    <div className="source-heading"><div><h2>{source.name}</h2><p className="muted">{source.connector_kind==="upload"?"Upload collection":"Read-only local folder"} · {loaded?`${total} ${total === 1 ? "file" : "files"}`:"Loading files…"}</p></div>
      {source.can_admin && <button className="text-button" onClick={()=>setConfirmRemove(!confirmRemove)}>Disconnect</button>}
    </div>
    {source.can_ingest && (source.connector_kind === "upload" ? <UploadFiles resolveBase={async () => base} onReceived={refresh} onExpired={onExpired} onBusy={setBusy} /> : <div className="source-actions"><button disabled={busy || pending} onClick={() => { void action("/sync"); }}>Sync folder</button><span className="muted">Read-only import · up to 200 files and 256 MiB per sync</span></div>)}
    {confirmRemove && <div className="confirm"><p>Disconnect this collection? Its imported files will become unavailable. Original files on your laptop are untouched. Stored copies are eligible for cleanup after one hour.</p><button disabled={busy} onClick={()=>{void remove();}}>Disconnect collection</button> <button className="secondary" onClick={()=>setConfirmRemove(false)}>Keep collection</button></div>}
    {(error||loadError)&&<p className="error" role="alert">{error||loadError}</p>}
    {folderJobs.slice(0,1).map(job=><div key={job.id} className="folder-status" role="status">Folder sync: {job.status==="stored"?`${job.manifest.files_seen??0} files checked, ${job.manifest.unchanged??0} unchanged, ${job.manifest.deleted??0} removed`:job.status==="running"?`${job.manifest.files_seen??0} of ${job.manifest.files_expected??"?"} files checked`:job.status}
      {job.error_code&&<span className="error"> · {job.error_code.replaceAll("_"," ").toLowerCase()}</span>}
      {job.status==="failed"&&source.can_ingest&&<button className="secondary" onClick={()=>{void action(`/jobs/${job.id}/retry`);}}>Retry sync</button>}</div>)}
    {!loaded?<p role="status" className="muted">{loadError?"Files could not be loaded. The collection may still contain files.":"Loading files…"}</p>:!assets.length?<div className="empty compact"><p>{source.connector_kind==="upload"?(source.can_ingest ? "Choose files above to add your first originals." : "This collection has no files yet."):"Files will appear after the folder is scanned."}</p></div>:<ul className="file-list">{assets.map(file=><li key={file.id}>
      <div><span className="file-title">{file.title}</span><p className="muted">{file.modality} · {(file.size_bytes/1024).toFixed(1)} KiB</p></div>
      <div className="file-status"><span className={`preparation-status ${fileState(file).tone}`}>{fileState(file).label}</span>{hasLimitations(file) && <span className="limitation-label">Available content has limitations</span>}{file.modality==="image"&&!file.document&&file.status==="stored"&&<button className="secondary" onClick={()=>setViewing(file)}>Open image</button>}{file.media?.status === "stored" && <button className="secondary" onClick={() => setMediaView(file)}>Open media</button>}{file.document?.status === "stored" && <button className="secondary" onClick={() => setViewing(file)}>{file.modality === "image" ? "Open image" : "Open document"}</button>}<details className="processing-details" open={fileState(file).tone === "danger" || undefined}><summary>Processing details</summary><p className="muted">{fileState(file).detail}</p>{file.embedding_status === "ready" && canManage && <button className="text-button" onClick={onSettings}>Review search preparation</button>}{file.embedding_status&&<span>{({indexed:"Ready to search",ready:"Embedded · pending activation",queued:"Waiting for embedding",running:"Embedding…",failed:"Embedding failed",cancelled:"Embedding cancelled"} as Record<string,string>)[file.embedding_status]??file.embedding_status}</span>}{file.media&&<div className="document-status"><span>{file.media.status==="stored"?(file.media.manifest.partial?"Media ready · transcription incomplete":"Media ready"):file.media.status==="running"?`Processing media · ${file.media.manifest.stage??"decode"}`:file.media.status==="queued"?"Waiting for media processing":`Media ${file.media.status}`}</span>
      {file.media.error_code&&<p className="error">{mediaError(file.media.error_code)}</p>}

      {(file.media.status==="failed"||file.media.manifest.partial)&&source.can_ingest&&<button className="secondary" onClick={()=>{void action(`/jobs/${file.media!.job_id}/retry`);}}>Retry media processing</button>}</div>}{file.document&&<div className="document-status"><span>{file.document.status==="stored"?`Document ready · ${file.document.manifest.page_count??1} page(s)`:file.document.status==="running"?`Extracting · ${file.document.manifest.pages_done??0} of ${file.document.manifest.pages_total??"?"} pages`:file.document.status==="queued"?"Waiting for document extraction":`Extraction ${file.document.status}`}</span>
      {file.document.error_code&&<p className="error">{documentError(file.document.error_code)}</p>}

      {file.document.status==="failed"&&source.can_ingest&&<button className="secondary" onClick={()=>{void action(`/jobs/${file.document!.job_id}/retry`);}}>Retry extraction</button>}</div>}<span className={file.status==="failed"?"error":"muted"}>{file.document||file.media?"Original validated":statusText(file.status??"queued")}</span>{file.embedding_status==="failed"&&source.can_ingest&&<button className="secondary" onClick={()=>{void action(`/assets/${file.id}/retry-index`);}}>Retry indexing</button>}{file.error_code&&<p className="error">{file.modality==="document"?documentError(file.error_code):file.error_code.replaceAll("_"," ").toLowerCase()}</p>}
      {file.status==="failed"&&source.can_ingest&&<button className="secondary" onClick={()=>{void action(`/jobs/${file.job_id}/retry`);}}>Retry validation</button>}<a href={`${base}/assets/${file.id}/original`}>Download original</a></details></div>
    </li>)}</ul>}
    {next&&<button className="secondary" onClick={()=>setPages(p=>p+1)}>Load more files</button>}
  </section>;
}

export function SourceList({ workspace, onExpired, canCreate, canImportFolders = false, active = true, onSearch, onSettings, canManage }: { workspace: string; onExpired: () => void; canCreate: boolean; canImportFolders?: boolean; active?: boolean; onSearch: () => void; onSettings: () => void; canManage: boolean }) {
  const [selected, setSelected] = useState("");
  const [intake, setIntake] = useState(false);
  const [intakeBusy, setIntakeBusy] = useState(false);
  const [destination, setDestination] = useState("");
  const [uploadName, setUploadName] = useState("My files");
  const createdTarget = useRef("");
  const [sources,setSources]=useState<Source[]|null>(null);
  const [error,setError]=useState("");
  const [storage,setStorage]=useState<{bytes:number;limit_bytes:number}|null>(null);
  const [adding,setAdding]=useState(false);
  const [name,setName]=useState("");
  const [kind,setKind]=useState("upload");
  const [folders,setFolders]=useState<string[]>([]);
  const [folder,setFolder]=useState("");
  const [saving,setSaving]=useState(false);
  const refresh=useCallback(async()=>{
    try{const values = await api<Source[]>(`/api/workspaces/${workspace}/sources`); setSources(values); setSelected(previous => values.some(value => value.id === previous) ? previous : values[0]?.id ?? ""); setError("");if(canImportFolders)setStorage(await api(`/api/workspaces/${workspace}/storage`));}
    catch(cause){if(cause instanceof ApiError&&cause.status===401)onExpired();else { if(cause instanceof ApiError && [403,404].includes(cause.status)) setSources([]); setError(cause instanceof Error?cause.message:"Unable to load sources"); }}
  },[workspace,onExpired,canImportFolders]);
  useEffect(()=>{setSources(null);setAdding(false);setError("");void refresh();},[refresh]);
  async function add(){setAdding(true);setError("");if(!canImportFolders)return;try{setFolders((await api<{folders:string[]}>(`/api/workspaces/${workspace}/import-folders`)).folders);}catch{/* Uploads remain usable if local folders are unavailable. */}}
  async function create(event:FormEvent){event.preventDefault();setSaving(true);setError("");try{const added = await api<Source>(`/api/workspaces/${workspace}/sources`,{method:"POST",body:JSON.stringify({name,connector_kind:kind,folder:kind==="local_folder"?folder:""})}); setSelected(added.id);setName("");setAdding(false);await refresh();}catch(cause){setError(cause instanceof Error?cause.message:"Unable to add source");}finally{setSaving(false);}}
  return <>
    <div className="source-toolbar"><p className="muted">Your originals, organised into collections.{storage && <> {(storage.bytes / 1024**2).toFixed(1)} MiB used, including history and pending uploads.</>}</p><div className="toolbar-actions">{(canCreate || sources?.some(value => value.can_ingest && value.connector_kind === "upload")) && <button disabled={intakeBusy} onClick={() => { setIntake(value => !value); createdTarget.current = ""; setDestination(sources?.find(value => value.can_ingest && value.connector_kind === "upload")?.id ?? ""); }}>Add files</button>}{canCreate && <button className="secondary" onClick={() => { void add(); }}>Add collection</button>}</div></div>
    {intake && <section className="source-form" aria-label="Add files"><div className="source-heading"><h2>Add files</h2><button className="text-button" disabled={intakeBusy} onClick={() => setIntake(false)}>Close upload</button></div><fieldset disabled={intakeBusy}><label>Destination collection<select value={destination} onChange={event => { setDestination(event.target.value); createdTarget.current = ""; }}>{sources?.filter(value => value.can_ingest && value.connector_kind === "upload").map(value => <option key={value.id} value={value.id}>{value.name}</option>)}{canCreate && <option value="">Create a new collection</option>}</select></label>{!destination && canCreate && <label>New collection name<input value={uploadName} maxLength={100} onChange={event => setUploadName(event.target.value)} /></label>}</fieldset><UploadFiles resolveBase={async () => {
      let target = destination || createdTarget.current;
      if (!target) {
        if (!uploadName.trim()) throw new Error("Enter a collection name first.");
        const added = await api<Source>(`/api/workspaces/${workspace}/sources`, { method: "POST", body: JSON.stringify({ name: uploadName.trim(), connector_kind: "upload", folder: "" }) });
        target = added.id; createdTarget.current = target;
      }
      return `/api/workspaces/${workspace}/sources/${target}`;
    }} onReceived={async base => { await refresh(); setSelected(base.split("/").at(-1) ?? ""); }} onExpired={onExpired} onBusy={setIntakeBusy} /></section>}
    {adding&&<form className="source-form" onSubmit={event=>{void create(event);}}><h2>Add a collection</h2>
      <label>Collection name<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)} placeholder="For example, Research notes"/></label>
      <label>Collection type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="upload">Upload files</option>{canImportFolders&&<option value="local_folder">Local folder (read only)</option>}</select></label>
      {kind==="local_folder"&&<><label>Import folder<select value={folder} onChange={e=>setFolder(e.target.value)}>{folders.map(f=><option key={f} value={f}>{f||"Import area root"}</option>)}</select></label><p className="muted">Place files in the project's .local/imports folder. Only this read-only import area is available; your other laptop folders are not exposed. Up to 200 files and 256 MiB per sync.</p></>}
      {kind==="upload"&&<p className="muted">Create the collection, then choose one or more files from your laptop. Originals are preserved. Files are processed and indexed automatically, then appear in search.</p>}
      <div><button disabled={saving||(kind==="local_folder"&&!folders.length)}>{saving?"Adding…":"Create collection"}</button> <button type="button" className="secondary" onClick={()=>setAdding(false)}>Cancel</button></div>
    </form>}
    {error&&<p role="alert" className="error">{error}</p>}
    {!sources ? <p className="muted" role="status">Loading collections…</p> : !sources.length ? <div className="empty"><h2>{canCreate ? "Your Library starts here." : "No collections shared with you yet."}</h2><p className="muted">{canCreate ? "Choose Add files to upload your first originals." : "Ask your workspace administrator for collection access."}</p>{canCreate && <ol className="onboarding-steps"><li><strong>Add your files</strong><span>Choose files and a collection.</span></li><li><strong>Follow preparation</strong><span>Watch validation, processing and search readiness here.</span></li><li><strong>Find the original</strong><span>Search, open a match and copy its citation.</span></li></ol>}</div> : <><div className="collection-picker"><label>Collection<select value={selected} onChange={event => setSelected(event.target.value)}>{sources.map(source => <option key={source.id} value={source.id}>{source.name}{source.connector_kind === "local_folder" ? " · Local folder" : ""}</option>)}</select></label><button className="text-button" onClick={onSearch}>Go to Search →</button></div>{sources.map(source => <div key={source.id} hidden={source.id !== selected}><SourceFiles source={source} workspace={workspace} active={active && source.id === selected} onExpired={onExpired} onRemoved={() => { void refresh(); }} onSearch={onSearch} onSettings={onSettings} canManage={canManage} /></div>)}</>}
  </>;
}
