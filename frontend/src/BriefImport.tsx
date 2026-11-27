import {useEffect,useRef,useState} from 'react';
import {FileUp} from 'lucide-react';
import {api,day,type Row} from './api';
import {Modal,ModalCloseButton} from './components';
import {MarkdownEditor} from './Markdown';

export default function BriefImport({pid,onClose,onImported}:{pid:string,onClose:()=>void,onImported:(result:Row)=>void}) {
 const [file,setFile]=useState<File|null>(null),[preview,setPreview]=useState<Row|null>(null);
 const [title,setTitle]=useState(''),[start,setStart]=useState(day().slice(0,8)+'01'),[end,setEnd]=useState(day());
 const [markdown,setMarkdown]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const alive=useRef(true),token=useRef(''),key=useRef(crypto.randomUUID()),locked=useRef(false);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;if(token.current)void api('/projects/'+pid+'/brief-imports/'+token.current,'DELETE').catch(()=>{});};},[pid]);
 async function discard(){const old=token.current;token.current='';if(old)await api('/projects/'+pid+'/brief-imports/'+old,'DELETE').catch(()=>{});}
 async function choose(next:File|null){
  const cleanup=discard();setFile(next);setPreview(null);setMarkdown('');setError('');setTitle(next?.name.replace(/\.[^.]+$/,'')||'');key.current=crypto.randomUUID();await cleanup;
 }
 async function convert(){
  if(!file||locked.current)return;
  locked.current=true;setBusy(true);setError('');
  try{
   await discard();setPreview(null);const data=new FormData();data.append('file',file);
   const result=await api('/projects/'+pid+'/brief-imports/preview','POST',data);
   if(!alive.current){await api('/projects/'+pid+'/brief-imports/'+result.token,'DELETE').catch(()=>{});return;}
   token.current=result.token;setPreview(result);setMarkdown(result.markdown);key.current=crypto.randomUUID();
  }catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}
  finally{locked.current=false;if(alive.current)setBusy(false);}
 }
 async function save(){
  if(!preview||locked.current)return;
  if(!title.trim()||!start||!end||!markdown.trim()){setError('请填写报告名称、报告期间和正文。');return;}
  if(start>end||end>day()){setError('报告开始日不得晚于结束日，结束日不得晚于今天。');return;}
  locked.current=true;setBusy(true);setError('');
  try{
   const result=await api('/projects/'+pid+'/brief-imports','POST',{token:preview.token,title:title.trim(),start,end,markdown},key.current);
   token.current='';if(alive.current)onImported(result);
  }catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}
  finally{locked.current=false;if(alive.current)setBusy(false);}
 }
 return <Modal title="报告导入" wide dirty={!!file} onClose={()=>{if(!locked.current)onClose();}}>
  <div className="modal-body report-import">
   <div className="report-import-fields">
    <label className="field"><span>报告名称 *</span><input aria-label="报告名称" required maxLength={200} value={title} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label>
    <label className="field"><span>报告开始日 *</span><input aria-label="报告开始日" type="date" required value={start} disabled={busy} max={end} onChange={e=>setStart(e.target.value)}/></label>
    <label className="field"><span>报告结束日 *</span><input aria-label="报告结束日" type="date" required value={end} disabled={busy} min={start} max={day()} onChange={e=>setEnd(e.target.value)}/></label>
   </div>
   <div className="report-import-file"><label className="field"><span>报告文件 *</span><input aria-label="报告文件" type="file" accept=".pdf,.docx,.doc" disabled={busy} onChange={e=>void choose(e.target.files?.[0]||null)}/></label><button disabled={!file||busy} onClick={()=>void convert()}><FileUp size={16}/>{busy&&!preview?'正在转换…':'转换预览'}</button></div>
   <p className="muted">支持 PDF、Word（.docx、.doc）。保留原报告结构，转换后可编辑并导出。</p>
   {error&&<div className="error" role="alert">{error}</div>}
   {preview&&<><div className="report-import-notes">{preview.warnings.map((warning:string)=><div className="note" key={warning}>{warning}</div>)}</div><MarkdownEditor label="报告正文" value={markdown} onChange={setMarkdown} rows={18} disabled={busy} initialPreview/></>}
  </div>
  <div className="modal-foot"><span>{preview?'确认后新增一份独立简报，原报告同时保留。':'先选择文件并转换预览。'}</span><ModalCloseButton disabled={busy}>取消</ModalCloseButton><button className="primary" disabled={!preview||busy} onClick={()=>void save()}>{busy&&preview?'导入中…':'确认导入'}</button></div>
 </Modal>;
}
