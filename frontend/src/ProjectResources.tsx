import {Download, Paperclip} from 'lucide-react';
import type {Row} from './api';
import {AcceptanceToggle,fileSize} from './Attachments';

type Props = {
  attachments: Row[];
  modules: Row[];
  attachmentsLoading: boolean;
  attachmentsError: string;
  modulesLoading: boolean;
  readOnly: boolean;
  onDownload: (file: Row) => void;
  onRetry: () => void;
};

export default function ProjectResources({attachments,modules,attachmentsLoading,attachmentsError,modulesLoading,readOnly,onDownload,onRetry}:Props) {
  const files=attachments.filter(file=>!file.removed);
  const orderedModules=[...modules].sort((a,b)=>Number(b.name==='项目公共事务')-Number(a.name==='项目公共事务'));
  return <div className="overview-resources">
    <section aria-labelledby="overview-attachments-title" aria-busy={attachmentsLoading}>
      <h3 id="overview-attachments-title">项目附件 <span>{attachmentsLoading||attachmentsError?'—':files.length}</span></h3>
      {attachmentsLoading?<p className="resource-empty">正在读取附件…</p>:attachmentsError?<div className="resource-error" role="alert"><span>{attachmentsError}</span><button type="button" onClick={onRetry}>重试</button></div>:files.length?<ul className="overview-file-list">
        {files.map(file=><li key={file.id}>
          <Paperclip size={17} aria-hidden="true"/>
          <div className="overview-file-info" title={[file.name,file.description].filter(Boolean).join('\n')}>
            <div className="overview-file-heading"><strong>{file.name}</strong><span className="overview-file-size">{fileSize(file.size)}</span></div>
            {file.description&&<small>{file.description}</small>}
          </div>
          <AcceptanceToggle file={file} disabled={readOnly}/>
          <button type="button" className="icon" title={'下载 '+file.name} aria-label={'下载 '+file.name} onClick={()=>onDownload(file)}><Download size={17}/></button>
        </li>)}
      </ul>:<p className="resource-empty">暂无项目附件</p>}
    </section>
    <section aria-labelledby="overview-modules-title" aria-busy={modulesLoading}>
      <h3 id="overview-modules-title">功能模块 <span>{modulesLoading?'—':modules.length}</span></h3>
      {modulesLoading?<p className="resource-empty">正在读取模块…</p>:modules.length?<ul className="overview-module-list">
        {orderedModules.map(module=><li key={module.id}><span className={'overview-module-name'+(module.name==='项目公共事务'?' is-default':'')}>{module.name}</span></li>)}
      </ul>:<p className="resource-empty">暂无功能模块</p>}
    </section>
  </div>;
}
