import {useEffect,useState} from 'react';
import {Sparkles, Download, ExternalLink, Save, RefreshCw, Plus, Trash2} from 'lucide-react';
import {api,download,day,type Row} from './api';
import {Modal,Section,Empty,Pagination} from './components';

export default function Briefs({id,pid,archived,refresh,onError,onSaved}:{id:string,pid:string,archived:boolean,refresh:number,onError:(e:unknown)=>void,onSaved:()=>void}) {
 const [briefs,setBriefs]=useState<Row[]>([]),[jobs,setJobs]=useState<Row[]>([]),[page,setPage]=useState(1),[total,setTotal]=useState(0);
 const [generate,setGenerate]=useState(false),[period,setPeriod]=useState({start:day().slice(0,8)+'01',end:day()}),[preview,setPreview]=useState<Row|null>(null),[busy,setBusy]=useState(false),[full,setFull]=useState(false);
 const [selected,setSelected]=useState<Row|null>(null),[version,setVersion]=useState<Row|null>(null),[content,setContent]=useState<Row|null>(null),[dirty,setDirty]=useState(false),[editing,setEditing]=useState(false);
 async function load(){if(!pid){setBriefs([]);setJobs([]);return;}const [b,j]=await Promise.all([api('/projects/'+pid+'/briefs?page='+page),api('/projects/'+pid+'/jobs')]);setBriefs(b.items);setTotal(b.total);setJobs(j);}
 useEffect(()=>{setPage(1);setPreview(null);setGenerate(false);setVersion(null);},[pid]);
 useEffect(()=>{void load().catch(onError);},[pid,page,refresh]);
 useEffect(()=>{if(!jobs.some(j=>['等待中','生成中'].includes(j.status)))return;const timer=setInterval(()=>void load().catch(onError),2000);return()=>clearInterval(timer);},[jobs,pid,page]);
 async function view(brief:Row,vid:string){try{const v=await api('/brief-versions/'+vid);setVersion(v);setContent(structuredClone(v.content));setSelected(brief);setDirty(false);setEditing(false);}catch(e){onError(e);}}
 function quick(mode:string){const now=new Date(day()+'T00:00:00Z');if(mode==='week'){const weekday=(now.getUTCDay()+6)%7;now.setUTCDate(now.getUTCDate()-weekday);}else now.setUTCDate(1);setPeriod({start:now.toISOString().slice(0,10),end:day()});setPreview(null);}
 async function run(){setBusy(true);try{await api('/projects/'+pid+'/generate','POST',period);setGenerate(false);await load();}catch(e){onError(e);}finally{setBusy(false);}}
 async function save(){if(!version||!selected||!content)return;setBusy(true);try{const v=await api('/briefs/'+selected.id+'/versions','POST',{version:selected.version,base_version_id:version.id,content});setVersion(v);setDirty(false);setEditing(false);setSelected({...selected,version:selected.version+1});await load();onSaved();}catch(e){onError(e);}finally{setBusy(false);}}
 const update=(si:number,pi:number,key:string,value:any)=>{setContent(old=>{const next=structuredClone(old!);next.sections[si].paragraphs[pi][key]=value;return next;});setDirty(true);};
 return <><Section id={id} title="项目简报" actions={<button className="primary" disabled={!pid||archived} onClick={()=>{setGenerate(true);setPreview(null);}}><Sparkles size={16}/>生成简报</button>}>
 {!pid?<Empty>请选择一个项目，生成和查看该项目的简报。</Empty>:<>
 {jobs.filter(j=>j.status!=='成功').slice(0,3).map(j=><div className={'job '+(j.status==='失败'?'failed':'')} key={j.id}><Sparkles size={17}/><span>{j.status==='失败'?j.error:'正在生成简报，刷新页面后仍可查询进度…'}</span>{j.status==='失败'&&j.retryable&&j.attempts<3&&!archived&&<button onClick={()=>void api('/jobs/'+j.id+'/retry','POST').then(load).catch(onError)}>重试 ({j.attempts}/3)</button>}</div>)}
 {!briefs.length?<Empty>还没有项目简报。登记任务、日志或配置信息后，即可选择期间生成。</Empty>:<div className="brief-grid">{briefs.map(b=><article className="brief-card" key={b.id}><FileIcon/><div><span className="eyebrow">项目简报</span><h3>{b.start} — {b.end}</h3><p>{b.versions.length?'共 '+b.versions.length+' 个正文版本':'尚未生成成功的正文'}</p>{b.versions.length>0&&<div className="actions"><button onClick={()=>void view(b,b.versions[0].id)}>查看简报<ExternalLink size={14}/></button><select aria-label="查看历史简报版本" value="" onChange={e=>{if(e.target.value)void view(b,e.target.value);}}><option value="">历史版本</option>{b.versions.map((v:Row)=><option value={v.id} key={v.id}>V{v.number}</option>)}</select></div>}</div></article>)}</div>}
 {total>20&&<Pagination page={page} total={total} onPage={setPage}/>}</>}
 </Section>
 {generate&&<Modal title="生成项目简报" onClose={()=>setGenerate(false)}><div className="modal-body"><p className="muted">仅将当前项目所选期间的结构化业务内容发送给 OpenAI，不读取附件正文。</p><div className="actions"><button onClick={()=>quick('week')}>本周</button><button onClick={()=>quick('month')}>本月</button></div><div className="form-grid"><label className="field"><span>报告开始日</span><input type="date" onInput={e=>{setPeriod({...period,start:e.currentTarget.value});setPreview(null);}} value={period.start} onChange={e=>{setPeriod({...period,start:e.target.value});setPreview(null);}}/></label><label className="field"><span>报告结束日</span><input type="date" onInput={e=>{setPeriod({...period,end:e.currentTarget.value});setPreview(null);}} value={period.end} max={day()} onChange={e=>{setPeriod({...period,end:e.target.value});setPreview(null);}}/></label></div><button disabled={busy} onClick={()=>{setBusy(true);void api('/projects/'+pid+'/report-preview','POST',period).then(setPreview).catch(onError).finally(()=>setBusy(false));}}>预览取数范围</button>{preview&&<><div className="preview-counts">{Object.entries(preview.counts).map(([k,v])=><div key={k}><strong>{String(v)}</strong><span>{{tasks:'相关任务',logs:'工作日志',configurations:'配置记录',changes:'需求变更',risks:'风险记录'}[k]}</span></div>)}</div>{preview.warnings.map((w:string)=><div className="note" key={w}>{w}</div>)}<p className="muted">本期完成 {preview.metrics['本期完成任务数']} 项 · 期末逾期 {preview.metrics['期末逾期任务数']} 项。数据包含开始日与结束日。</p></>}</div><div className="modal-foot"><span>每次生成保存独立版本</span><button className="primary" disabled={!preview||busy} onClick={()=>void run()}><Sparkles size={16}/>{busy?'处理中…':'调用 OpenAI 生成'}</button></div></Modal>}
 {version&&content&&selected&&<Modal title={'项目简报 · V'+version.number} wide fullscreen={full} dirty={dirty} onClose={()=>{setVersion(null);setDirty(false);}}>
  <div className="brief-toolbar"><div className="actions"><button onClick={()=>setFull(!full)}>{full?'退出全屏':'全屏查看'}</button>{!archived&&<button onClick={()=>setEditing(!editing)}>{editing?'预览正文':'编辑正文'}</button>}</div><div className="actions">
   <button onClick={()=>void download('/brief-versions/'+version.id+'/export/docx').catch(onError)}><Download size={15}/>Word</button><button onClick={()=>void download('/brief-versions/'+version.id+'/export/pdf').catch(onError)}><Download size={15}/>PDF</button>
   <button disabled={archived||busy||dirty} onClick={()=>{setBusy(true);void api('/projects/'+pid+'/generate','POST',{start:selected.start,end:selected.end,brief_id:selected.id}).then(()=>{setVersion(null);return load();}).catch(onError).finally(()=>setBusy(false));}}><RefreshCw size={15}/>重新生成</button>
  </div></div>
  <div className="modal-body brief-editor"><article className="brief-document">
   <header><h1>{version.snapshot.project_name}<br/>项目简报</h1><p className="brief-period">{reportDate(selected.start)}至{reportDate(selected.end)}</p></header>
   {content.sections.filter((section:Row)=>editing||section.paragraphs.some((p:Row)=>p.text.trim())).map((section:Row,index:number)=>{
    const si=content.sections.indexOf(section);
    return <section key={si}><h2>{'一二三四五六七八九十'[index]}、{section.heading}</h2>
     {section.paragraphs.map((p:Row,pi:number)=>editing?<div className="brief-edit-paragraph" key={pi}><textarea aria-label={section.heading+'正文'+(pi+1)} value={p.text} rows={Math.max(3,Math.ceil(p.text.length/36))} onChange={e=>update(si,pi,'text',e.target.value)}/><button className="icon small" title="移除此段" onClick={()=>{setContent(old=>{const next=structuredClone(old!);next.sections[si].paragraphs.splice(pi,1);return next;});setDirty(true);}}><Trash2 size={14}/></button></div>:p.text.trim()&&<p key={pi}>{p.text}</p>)}
     {editing&&<button className="text-button" onClick={()=>{setContent(old=>{const next=structuredClone(old!);next.sections[si].paragraphs.push({text:'',source_ids:[]});return next;});setDirty(true);}}><Plus size={14}/>添加段落</button>}
    </section>;
   })}
  </article></div>
  <div className="modal-foot"><span>{dirty?'有未保存的修改；导出使用当前已保存版本。':''}</span><button disabled={!dirty||busy||archived} className="primary" onClick={()=>void save()}><Save size={16}/>保存新版本</button></div>
 </Modal>}
 </>;
}
function FileIcon(){return <div className="brief-icon"><Sparkles size={25}/></div>;}
function reportDate(value:string){const [year,month,date]=value.split('-');return `${year}年${Number(month)}月${Number(date)}日`;}
