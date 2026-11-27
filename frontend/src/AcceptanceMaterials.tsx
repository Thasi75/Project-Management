import {MarkdownContent} from './Markdown';
import TableViewport from './TableViewport';
import {useState} from 'react';
import {Download, Eye, Upload} from 'lucide-react';
import {api, download, type Row} from './api';
import {Empty, Modal, Section, Uploader} from './components';
import {AcceptanceToggle, fileSize, useAttachments} from './Attachments';
import {useAppDialog} from './AppDialog';
import AttachmentPreview from './AttachmentPreview';

export default function AcceptanceMaterials({pid,files,loading,error,readOnly,onRetry,onError}:{
  pid:string;files:Row[];loading:boolean;error:string;readOnly:boolean;onRetry:()=>void;onError:(error:unknown)=>void;
}) {
  const [uploading,setUploading]=useState(false);
  const [preview,setPreview]=useState<Row|null>(null);
  const {askText}=useAppDialog(),{remember}=useAttachments();
  const materials=files.filter(file=>file.is_acceptance&&!file.removed);
  async function describe(file:Row) {
    const description=await askText({title:'编辑附件说明',message:file.name,label:'附件说明',initialValue:file.description,confirmText:'保存说明'});
    if(description===null)return;
    try {remember([await api('/attachments/'+file.id,'PUT',{version:file.version,removed:file.removed,description})]);}
    catch(e){onError(e);onRetry();}
  }
  return <>
    <Section id="section-acceptance" title="验收材料" actions={<button className="primary" disabled={readOnly} onClick={()=>setUploading(true)}><Upload size={16}/>上传材料</button>}>
      {loading?<Empty>正在读取验收材料…</Empty>:error?<div className="acceptance-empty" role="alert">{error}<button onClick={onRetry}>重试</button></div>:!materials.length?<Empty>暂无验收材料，可上传材料或打开已有附件的“验收材料”开关。</Empty>:<TableViewport><table className="acceptance-table">
        <thead><tr><th>附件名称</th><th>材料说明</th><th>上传时间</th><th>验收材料</th><th className="right">操作</th></tr></thead>
        <tbody>{materials.map(file=><tr key={file.id}>
          <td><div className="overview-file-heading"><strong>{file.name}</strong><span className="overview-file-size">{fileSize(file.size)}</span></div></td>
          <td className="acceptance-description"><MarkdownContent text={file.description}/></td>
          <td className="acceptance-uploaded-at"><time dateTime={file.created_at}>{file.created_at.slice(0,16).replace('T',' ')}</time></td>
          <td><AcceptanceToggle file={file} disabled={readOnly}/></td>
          <td><div className="row-actions"><button onClick={()=>setPreview(file)}><Eye size={15}/>预览</button><button onClick={()=>void download('/attachments/'+file.id+'/download').catch(onError)}><Download size={15}/>下载</button><button disabled={readOnly} onClick={()=>void describe(file)}>说明</button></div></td>
        </tr>)}</tbody>
      </table></TableViewport>}
    </Section>
    {preview&&<AttachmentPreview pid={pid} file={preview} onClose={()=>setPreview(null)} onError={onError}/>}
    {uploading&&<Modal title="上传验收材料" wide onClose={()=>setUploading(false)}><div className="modal-body">
      <Uploader pid={pid} acceptance onUploaded={()=>{}}/>
    </div><div className="modal-foot"><span>支持图片、PDF、Word、Excel 和 CSV</span><button onClick={()=>setUploading(false)}>关闭</button></div></Modal>}
  </>;
}
