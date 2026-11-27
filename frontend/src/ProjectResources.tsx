import type {Row} from './api';
import ProjectAttachmentList from './ProjectAttachmentList';

type Props = {
  pid: string;
  attachments: Row[];
  modules: Row[];
  attachmentsLoading: boolean;
  attachmentsError: string;
  modulesLoading: boolean;
  readOnly: boolean;
  onDownload: (file: Row) => void;
  onRetry: () => void;
  onError: (error: unknown) => void;
};

export default function ProjectResources({pid,attachments,modules,attachmentsLoading,attachmentsError,modulesLoading,readOnly,onDownload,onRetry,onError}:Props) {
  const files=attachments.filter(file=>!file.removed&&file.is_acceptance);
  const orderedModules=[...modules].sort((a,b)=>Number(b.name==='项目公共事务')-Number(a.name==='项目公共事务'));
  return <><div className="overview-resources">
    <ProjectAttachmentList pid={pid} title="验收材料" attachments={files} loading={attachmentsLoading} error={attachmentsError} readOnly={readOnly} onDownload={onDownload} onRetry={onRetry} onError={onError}/>
    <section aria-labelledby="overview-modules-title" aria-busy={modulesLoading}>
      <h3 id="overview-modules-title">功能模块 <span>{modulesLoading?'—':modules.length}</span></h3>
      <div className="overview-resource-scroll" role="region" aria-label="功能模块列表" tabIndex={0}>
      {modulesLoading?<p className="resource-empty">正在读取模块…</p>:modules.length?<ul className="overview-module-list">
        {orderedModules.map(module=><li key={module.id}><span title={module.name} className={'overview-module-name'+(module.name==='项目公共事务'?' is-default':'')}>{module.name}</span></li>)}
      </ul>:<p className="resource-empty">暂无功能模块</p>}
      </div>
    </section>
  </div></>;
}
