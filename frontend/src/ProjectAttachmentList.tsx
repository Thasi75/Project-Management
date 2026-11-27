import {useState} from 'react';
import {Download, Paperclip} from 'lucide-react';
import type {Row} from './api';
import AttachmentPreview from './AttachmentPreview';
import {AcceptanceToggle,fileSize} from './Attachments';

type Props = {
  pid:string;attachments:Row[];loading:boolean;error:string;readOnly:boolean;
  title?:string;compact?:boolean;onDownload:(file:Row)=>void;
  onRetry:()=>void;onError:(error:unknown)=>void;
};

export default function ProjectAttachmentList({pid,attachments,loading,error,readOnly,title='项目附件',compact=true,onDownload,onRetry,onError}:Props) {
  const [preview,setPreview]=useState<Row|null>(null);
  const files=attachments.filter(file=>!file.removed);
  return <>
    <section className={'project-attachment-list'+(compact?'':' expanded')} aria-label={title} aria-busy={loading}>
      {compact&&<h3>{title} <span>{loading||error?'—':files.length}</span></h3>}
      <div className="overview-resource-scroll" role="region" aria-label={title+'列表'} tabIndex={0}>
        {loading?<p className="resource-empty">正在读取附件…</p>:error?<div className="resource-error" role="alert"><span>{error}</span><button type="button" onClick={onRetry}>重试</button></div>:files.length?<ul className="overview-file-list">
          {files.map(file=><li key={file.id}>
            <Paperclip size={17} aria-hidden="true"/>
            <div className="overview-file-info" title={file.name}>
              <div className="overview-file-heading"><button type="button" className="overview-file-preview" aria-label={'预览 '+file.name} onClick={()=>setPreview(file)}>{file.name}</button><span className="overview-file-size">{fileSize(file.size)}</span></div>
            </div>
            <AcceptanceToggle file={file} disabled={readOnly}/>
            <button type="button" className="icon" title={'下载 '+file.name} aria-label={'下载 '+file.name} onClick={()=>onDownload(file)}><Download size={17}/></button>
          </li>)}
        </ul>:<p className="resource-empty">暂无{title}</p>}
      </div>
    </section>
    {preview&&<AttachmentPreview key={pid+preview.id} pid={pid} file={preview} onClose={()=>setPreview(null)} onError={onError}/>}
  </>;
}
