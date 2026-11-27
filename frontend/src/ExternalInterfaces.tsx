import {MarkdownContent} from './Markdown';
import {useEffect,useRef,useState} from 'react';
import {Search} from 'lucide-react';
import {api,type Row} from './api';
import {Empty,Fields,Modal,ModalCloseButton,Pagination,Section,validateForm,type FieldDef} from './components';
import {PeopleOptions} from './PeopleChoices';
import {useAppDialog} from './AppDialog';
import TableViewport from './TableViewport';
import type {MetricNavigationRequest} from './metricNavigation';

type Props={pid:string,people:Row[],readOnly:boolean,refresh:number,navigationRequest?:MetricNavigationRequest,onFilterChange:()=>void,onSaved:()=>void,onOpenResearch:(row:Row)=>void,onError:(error:unknown)=>void};

export function ExternalInterfaceForm({pid,row,people,readOnly,onClose,onSaved,onOpenResearch}:{pid:string,row:Row,people:Row[],readOnly:boolean,onClose:()=>void,onSaved:()=>void,onOpenResearch:(row:Row)=>void}){
 const [value,setValue]=useState<Row>({...row,development_notes:row.development_notes||'',go_live_date:row.go_live_date||''});
 const [dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[opening,setOpening]=useState(false),[error,setError]=useState('');
 const locked=useRef(false);
 const {confirmAction}=useAppDialog();
 const names=Object.fromEntries(people.filter(p=>p.project_id===pid).map(p=>[p.id,p.name]));
 const fields:FieldDef[]=[
  {key:'sequence',label:'序号',disabled:true},
  {key:'integration_system',label:'对接系统',disabled:true},
  {key:'requirement',label:'需求描述',type:'textarea',wide:true,disabled:true},
  {key:'solution',label:'解决思路',type:'textarea',wide:true,disabled:true},
  {key:'source_name',label:'需求来源',disabled:true},
  {key:'status',label:'状态',type:'select',required:true,options:['设计','开发','上线'].map(name=>({id:name,name}))},
  {key:'development_notes',label:'开发情况',type:'textarea',wide:true},
  {key:'go_live_date',label:'上线日期',type:'date',required:value.status==='上线'},
 ];
 async function submit(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();if(locked.current||readOnly)return;
  const validation=validateForm(event.currentTarget);if(validation){setError(validation);return;}
  const form=new FormData(event.currentTarget);
  locked.current=true;setBusy(true);setError('');
  try{
   await api('/projects/'+pid+'/external-interfaces/'+row.id,'PUT',{version:row.version,status:value.status,development_notes:value.development_notes,go_live_date:form.get('go_live_date')||null});
   onSaved();
  }catch(e){setError((e as Error).message);}finally{locked.current=false;setBusy(false);}
 }
 async function openResearch(){
  if(locked.current)return;locked.current=true;setOpening(true);
  try{
   if(dirty&&!await confirmAction({title:'查看原始需求？',message:'当前外部接口有未保存的修改。打开原始需求后，这些修改将不会保存。',confirmText:'放弃修改并查看',cancelText:'继续编辑',danger:true}))return;
   setError('');
   const original=await api('/projects/'+pid+'/records/research/'+row.id);
   onOpenResearch(original);
  }catch(e){setError((e as Error).message);}finally{locked.current=false;setOpening(false);}
 }
 return <Modal title={(readOnly?'查看':'编辑')+'外部接口'} wide dirty={dirty} onClose={onClose}><form className="external-interface-form" noValidate onSubmit={submit}>
  <div className="modal-body">{error&&<div className="error" role="alert">{error}</div>}<Fields fields={fields} value={{...value,source_name:names[row.source_id]||'—'}} onChange={(key,next)=>{setValue(old=>({...old,[key]:next}));setDirty(true);}} disabled={readOnly||busy||opening}/></div>
  <div className="modal-foot"><span>{readOnly?'归档项目只读':'* 为必填项，保存后同步需求调研状态'}</span><div className="actions"><button type="button" disabled={busy||opening} onClick={()=>void openResearch()}>{opening?'正在打开…':'查看原始需求'}</button><ModalCloseButton>取消</ModalCloseButton>{!readOnly&&<button type="submit" className="primary" disabled={busy||opening}>{busy?'保存中…':'保存'}</button>}</div></div>
 </form></Modal>;
}

export default function ExternalInterfaces({pid,people,readOnly,refresh,navigationRequest,onFilterChange,onSaved,onOpenResearch,onError}:Props){
 const [result,setResult]=useState<Row>({items:[],total:0}),[filters,setFilters]=useState<Row>({page:1}),[query,setQuery]=useState('');
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0),[editing,setEditing]=useState<Row|null>(null),[opening,setOpening]=useState(false);
 const openLock=useRef(false);
 const currentPeople=people.filter(p=>p.project_id===pid),names=Object.fromEntries(currentPeople.map(p=>[p.id,p.name]));
 useEffect(()=>{if(navigationRequest?.projectId===pid){setQuery('');setFilters({...navigationRequest.filters,page:1});}},[navigationRequest,pid]);
 useEffect(()=>{
  let alive=true;setLoading(true);setError('');
  const params=new URLSearchParams();Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
  api('/projects/'+pid+'/external-interfaces?'+params).then(data=>{if(alive){if(filters.page>1&&!data.items.length){setFilters(old=>({...old,page:1}));return;}setResult(data);}}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
  return()=>{alive=false;};
 },[pid,filters,refresh,retry]);
 function filter(key:string,value:string|number){if(key!=='page')onFilterChange();setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
 async function edit(row:Row){
  if(openLock.current)return;openLock.current=true;setOpening(true);
  try{setEditing(await api('/projects/'+pid+'/external-interfaces/'+row.id));}catch(e){onError(e);setRetry(v=>v+1);}finally{openLock.current=false;setOpening(false);}
 }
 const filtersView=<div className="filters external-interface-filters">
  <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索外部接口" placeholder="搜索系统、需求或开发情况" value={query} onChange={e=>{onFilterChange();setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
  <select aria-label="外部接口需求来源筛选" value={filters.source_id||''} onChange={e=>filter('source_id',e.target.value)}><option value="">全部需求来源</option><PeopleOptions people={currentPeople}/></select>
  <select aria-label="外部接口状态筛选" value={filters.status_ne==='上线'?'__unlaunched':filters.status||''} onChange={e=>{onFilterChange();setFilters(old=>({...old,status:e.target.value==='__unlaunched'?'':e.target.value,status_ne:e.target.value==='__unlaunched'?'上线':'',page:1}));}}><option value="">全部状态</option><option value="__unlaunched">未上线（不等于上线）</option>{['设计','开发','上线'].map(status=><option key={status}>{status}</option>)}</select>
  <button className="text-button" onClick={()=>{onFilterChange();setQuery('');setFilters({page:1});}}>重置</button>
 </div>;
 return <><Section id="section-interfaces" title="外部接口" filters={filtersView}>
  {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试</button></div>:loading?<Empty>正在读取外部接口…</Empty>:!result.items.length?<Empty>当前条件下暂无外部接口，请在需求调研中将对应记录的“接口”设为“是”。</Empty>:<TableViewport><table className="external-interface-table">
   <thead><tr><th>序号</th><th>对接系统</th><th>需求描述</th><th>解决思路</th><th>需求来源</th><th>状态</th><th>开发情况</th><th>上线日期</th><th className="right">操作</th></tr></thead>
   <tbody>{result.items.map((row:Row)=><tr key={row.id}><td>{row.sequence}</td><td>{row.integration_system||'—'}</td><td className="interface-text"><MarkdownContent text={row.requirement}/></td><td className="interface-text"><MarkdownContent text={row.solution}/></td><td>{names[row.source_id]||'—'}</td><td className="interface-status">{row.status}</td><td className="interface-text"><MarkdownContent text={row.development_notes}/></td><td className="interface-date">{row.go_live_date||'—'}</td><td><div className="row-actions"><button className="text-button" disabled={opening} onClick={()=>void edit(row)}>{readOnly?'查看':'编辑'}</button></div></td></tr>)}</tbody>
  </table></TableViewport>}
  <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
 </Section>{editing&&<ExternalInterfaceForm key={editing.id} pid={pid} row={editing} people={people} readOnly={readOnly} onClose={()=>setEditing(null)} onSaved={()=>{setEditing(null);onSaved();}} onOpenResearch={row=>{setEditing(null);onOpenResearch(row);}}/>}</>;
}
