import {useEffect, useState} from 'react';
import {Download, Maximize2, Minimize2, RefreshCw} from 'lucide-react';
import {download, type Row} from './api';
import {Modal} from './components';

type Preview = {type:'pdf';url:string}|{type:'image';url:string}|{type:'text';text:string}|{type:'table';rows:string[][];truncated:boolean};

export default function AttachmentPreview({pid,file,onClose,onError}:{pid:string;file:Row;onClose:()=>void;onError:(error:unknown)=>void}) {
  const [preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[full,setFull]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();
    let url='';
    setPreview(null);setError('');
    async function load() {
      try {
        const response=await fetch(`/api/projects/${encodeURIComponent(pid)}/attachments/${encodeURIComponent(file.id)}/preview`,{signal:controller.signal});
        if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'预览加载失败，请重试或下载原文件查看');}
        const mime=response.headers.get('Content-Type')||'';
        let result:Preview;
        if(mime.includes('application/json')){const body=await response.json();result={type:'table',rows:body.rows,truncated:body.truncated};}
        else if(mime.startsWith('text/plain'))result={type:'text',text:await response.text()};
        else if(mime.includes('application/pdf')||mime.startsWith('image/')){
          const blob=await response.blob();
          if(controller.signal.aborted)return;
          url=URL.createObjectURL(blob);result={type:mime.startsWith('image/')?'image':'pdf',url};
        }else throw new Error('此文件类型暂不支持预览，请下载原文件查看');
        if(!controller.signal.aborted)setPreview(result);
      } catch(e){if(!controller.signal.aborted)setError(e instanceof TypeError?'服务连接失败，请重试':(e as Error).message);}
    }
    void load();
    return()=>{controller.abort();if(url)URL.revokeObjectURL(url);};
  },[pid,file.id,attempt]);
  return <Modal title="附件预览" wide fullscreen={full} onClose={onClose}>
    <div className="attachment-preview-toolbar"><strong title={file.name}>{file.name}</strong><div className="actions">
      <button onClick={()=>void download('/attachments/'+file.id+'/download').catch(onError)}><Download size={16}/>下载原文件</button>
      <button className="icon" aria-label={full?'退出全屏预览':'全屏预览'} title={full?'退出全屏预览':'全屏预览'} onClick={()=>setFull(!full)}>{full?<Minimize2 size={18}/>:<Maximize2 size={18}/>}</button>
    </div></div>
    <div className="attachment-preview-content" aria-busy={!preview&&!error}>
      {error?<div className="attachment-preview-status" role="alert"><p>{error}</p><button onClick={()=>setAttempt(value=>value+1)}><RefreshCw size={16}/>重试</button></div>:!preview?<div className="attachment-preview-status" role="status"><RefreshCw size={24} className="preview-spinner"/><p>正在准备预览，首次打开文档可能需要一些时间…</p></div>:
        preview.type==='pdf'?<iframe title="文档预览" src={preview.url+'#view=FitH'} onError={()=>setError('文档显示失败，请重试或下载原文件查看')}/>:
        preview.type==='image'?<div className="attachment-preview-image"><img src={preview.url} alt={file.name} onError={()=>setError('图片无法显示，文件可能已损坏，请下载原文件查看')}/></div>:
        preview.type==='text'?<pre className="attachment-preview-text">{preview.text||'文件内容为空'}</pre>:
        <div className="attachment-preview-sheet">{preview.truncated&&<p className="note">当前预览最多显示前 1000 行、100 列，完整内容请下载原文件查看。</p>}{preview.rows.length?<table><tbody>{preview.rows.map((row,index)=><tr key={index}><th scope="row">{index+1}</th>{row.map((cell,column)=><td key={column}>{cell}</td>)}</tr>)}</tbody></table>:<p>文件内容为空</p>}</div>}
    </div>
  </Modal>;
}
