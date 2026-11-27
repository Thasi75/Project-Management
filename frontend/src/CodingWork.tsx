import {useEffect,useState} from 'react';
import {Plus,Search} from 'lucide-react';
import {api,type Row} from './api';
import {Empty,Pagination,RowMenu,Section} from './components';
import {MarkdownContent} from './Markdown';
import TableViewport from './TableViewport';
import type {MetricNavigationRequest} from './metricNavigation';

type Props={pid:string;modules:Row[];readOnly:boolean;refresh:number;navigationRequest?:MetricNavigationRequest;onFilterChange:()=>void;onNew:()=>void;onEdit:(row:Row)=>void;onRemove:(row:Row)=>void;onHistory:(row:Row)=>void};
export default function CodingWork({pid,modules,readOnly,refresh,navigationRequest,onFilterChange,onNew,onEdit,onRemove,onHistory}:Props){
 const [result,setResult]=useState<Row>({items:[],total:0}),[filters,setFilters]=useState<Row>({page:1}),[query,setQuery]=useState('');
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const currentModules=modules.filter(m=>m.project_id===pid),names=Object.fromEntries(currentModules.map(m=>[m.id,m.name]));
 useEffect(()=>{if(navigationRequest?.projectId===pid){setQuery('');setFilters({...navigationRequest.filters,page:1});}},[navigationRequest,pid]);
 useEffect(()=>{
  let alive=true;setLoading(true);setError('');
  const params=new URLSearchParams({project_id:pid});Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
  api('/records/coding?'+params).then(data=>{if(alive){if(filters.page>1&&!data.items.length){setFilters(old=>({...old,page:1}));return;}setResult(data);}}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
  return()=>{alive=false;};
 },[pid,filters,refresh,retry]);
 function filter(key:string,value:string|number){if(key!=='page')onFilterChange();setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
 return <Section id="section-coding" title="代码编写" filters={<div className="filters coding-filters">
  <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索代码编写" placeholder="搜索功能点、主要工作或异常说明" value={query} onChange={e=>{onFilterChange();setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
  <select aria-label="代码编写模块筛选" value={filters.module_id||''} onChange={e=>filter('module_id',e.target.value)}><option value="">全部模块</option>{currentModules.map(m=><option key={m.id} value={m.id}>{m.name}{!m.enabled?'（已停用）':''}</option>)}</select>
  <input type="date" aria-label="代码编写开始日期筛选" value={filters.start||''} onChange={e=>filter('start',e.target.value)}/><span>至</span><input type="date" aria-label="代码编写结束日期筛选" value={filters.end||''} onChange={e=>filter('end',e.target.value)}/>
  <button className="text-button" onClick={()=>{onFilterChange();setQuery('');setFilters({page:1});}}>重置</button>
 </div>} actions={<button className="primary" disabled={readOnly} onClick={onNew}><Plus size={16}/>登记代码编写</button>}>
  {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试</button></div>:loading?<Empty>正在读取代码编写记录…</Empty>:!result.items.length?<Empty>当前条件下暂无代码编写记录。</Empty>:<TableViewport><table className="coding-work-table">
   <thead><tr><th>日期</th><th>功能模块</th><th>功能点</th><th>主要工作</th><th>耗时（分钟）</th><th>异常或额外耗时说明</th><th className="right">操作</th></tr></thead>
   <tbody>{result.items.map((row:Row)=><tr key={row.id}>
    <td className="coding-date">{row.work_date}</td><td>{names[row.module_id]||'—'}</td><td><button className="record-title" onClick={()=>onEdit(row)}>{row.feature}</button><small>{row.code}</small></td>
    <td className="coding-text"><MarkdownContent text={row.work_content} onOpen={()=>onEdit(row)}/></td><td className="coding-duration">{row.duration_minutes}</td><td className="coding-text"><MarkdownContent text={row.extra_time_notes}/></td>
    <td><div className="row-actions"><button className="text-button" onClick={()=>onEdit(row)}>{readOnly?'查看':'编辑'}</button><RowMenu label="代码编写更多操作"><button onClick={()=>onHistory(row)}>修订记录</button>{!readOnly&&<button className="error-text" onClick={()=>onRemove(row)}>移除</button>}</RowMenu></div></td>
   </tr>)}</tbody>
  </table></TableViewport>}
  <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
 </Section>;
}
