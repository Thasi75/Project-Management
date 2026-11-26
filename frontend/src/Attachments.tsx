import {createContext, useCallback, useContext, useRef, useState, type ReactNode} from 'react';
import {api, type Row} from './api';

type Store={rows:Record<string,Row>;remember:(rows:Row[])=>void;clear:()=>void};
const Context=createContext<Store|null>(null);

export function AttachmentProvider({children}:{children:ReactNode}) {
  const [rows,setRows]=useState<Record<string,Row>>({});
  const remember=useCallback((items:Row[])=>setRows(old=>{
    const next={...old};
    for(const item of items)if(!next[item.id]||item.version>=next[item.id].version)next[item.id]={...next[item.id],...item};
    return next;
  }),[]);
  const clear=useCallback(()=>setRows({}),[]);
  return <Context.Provider value={{rows,remember,clear}}>{children}</Context.Provider>;
}

export function useAttachments() {
  const store=useContext(Context);
  if(!store)throw new Error('Attachment provider is missing');
  const resolve=(file:Row)=>store.rows[file.id]?.version>=file.version?{...file,...store.rows[file.id]}:file;
  const forProject=(pid:string,base:Row[]=[])=>{
    const combined=new Map<string,Row>();
    for(const file of [...base,...Object.values(store.rows)])if(file.project_id===pid) {
      const current=combined.get(file.id);
      if(!current||file.version>=current.version)combined.set(file.id,file);
    }
    return [...combined.values()].sort((a,b)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id));
  };
  return {...store,resolve,forProject};
}

export function AcceptanceToggle({file,disabled=false}:{file:Row;disabled?:boolean}) {
  const {resolve,remember}=useAttachments();
  const current=resolve(file),lock=useRef(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function toggle() {
    if(lock.current||disabled||current.removed)return;
    lock.current=true;setBusy(true);setError('');
    try {
      const updated=await api('/attachments/'+current.id+'/acceptance','PUT',{version:current.version,is_acceptance:!current.is_acceptance});
      remember([updated]);
    } catch(e) {
      setError(e instanceof Error?e.message:String(e));
      if(current.project_id)void api<Row[]>('/projects/'+current.project_id+'/attachments').then(remember).catch(()=>{});
    } finally {lock.current=false;setBusy(false);}
  }
  return <div className="acceptance-control">
    <button type="button" role="switch" aria-checked={!!current.is_acceptance}
      aria-label={'验收材料 · '+current.name} className="acceptance-toggle"
      disabled={disabled||current.removed||busy} onClick={()=>void toggle()}
      title={current.removed?'恢复附件后可调整验收材料标记':current.is_acceptance?'关闭后移出验收材料，原附件保留':'设为验收材料'}>
      <span className="switch-track" aria-hidden="true"><span/></span><span>验收材料</span>
    </button>
    {error&&<small className="error-text" role="alert">{error}</small>}
  </div>;
}

export function AttachmentChoices({files,selected,onChange,disabled=false}:{files:Row[];selected:string[];onChange:(ids:string[])=>void;disabled?:boolean}) {
  return <div className="checks attachment-choices">
    {!files.length&&<small>暂无可选资料</small>}
    {files.map(file=><div className="attachment-choice" key={file.id}>
      <label><input type="checkbox" disabled={disabled||file.removed&&!selected.includes(file.id)} checked={selected.includes(file.id)}
        onChange={e=>onChange(e.target.checked?[...selected,file.id]:selected.filter(id=>id!==file.id))}/>
        <span>{file.name}{file.removed?'（已移除）':''}</span></label>
      <AcceptanceToggle file={file} disabled={disabled}/>
    </div>)}
  </div>;
}

export function fileSize(bytes:number) {
  if(bytes>=1024*1024)return (bytes/(1024*1024)).toFixed(1)+' MB';
  if(bytes>=1024)return (bytes/1024).toFixed(1)+' KB';
  return bytes+' B';
}
