import TableViewport from './TableViewport';
import {useEffect,useState} from 'react';
import {FileSpreadsheet,Plus,Search} from 'lucide-react';
import {api,download,type Row,type ResearchNavigation} from './api';
import {RowMenu,Empty,Pagination,Section} from './components';
import {PeopleOptions} from './PeopleChoices';

type Props={pid:string,people:Row[],modules:Row[],readOnly:boolean,refresh:number,onNew:()=>void,onEdit:(row:Row,navigation:ResearchNavigation)=>void,onRemove:(row:Row)=>void,onHistory:(row:Row)=>void,onError:(error:unknown)=>void};

export default function Research({pid,people,modules,readOnly,refresh,onNew,onEdit,onRemove,onHistory,onError}:Props){
 const [result,setResult]=useState<Row>({items:[],total:0}),[filters,setFilters]=useState<Row>({page:1}),[query,setQuery]=useState('');
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0),[exporting,setExporting]=useState(false);
 const currentPeople=people.filter(p=>p.project_id===pid),names=Object.fromEntries(currentPeople.map(p=>[p.id,p.name]));
 const currentModules=modules.filter(m=>m.project_id===pid).sort((a,b)=>Number(b.name==='项目公共事务')-Number(a.name==='项目公共事务')),moduleNames=Object.fromEntries(currentModules.map(m=>[m.id,m.name]));
 useEffect(()=>{
  let alive=true;setLoading(true);setError('');
  const params=new URLSearchParams({project_id:pid});
  Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
  api('/records/research?'+params).then(data=>{if(alive)setResult(data);}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
  return()=>{alive=false;};
 },[pid,filters,refresh,retry]);
 function filter(key:string,value:string|number){setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
 function edit(row:Row,index:number){onEdit(row,{filters:{...filters},index:(filters.page-1)*20+index,total:result.total});}
 async function exportExcel(){
  if(exporting)return;
  const params=new URLSearchParams();
  Object.entries(filters).forEach(([key,value])=>{if(key!=='page'&&value)params.set(key,String(value));});
  setExporting(true);
  try{await download('/projects/'+pid+'/research/export?'+params);}catch(e){onError(e);}finally{setExporting(false);}
 }
 const filtersView=<div className="filters research-filters">
  <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索需求调研" placeholder="搜索需求、思路或备注" value={query} onChange={e=>{setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
  <select aria-label="调研功能模块筛选" value={filters.module_id||''} onChange={e=>filter('module_id',e.target.value)}><option value="">全部模块</option>{currentModules.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select>
  <select className="research-person-filter" aria-label="调研需求来源筛选" value={filters.source_id||''} onChange={e=>filter('source_id',e.target.value)}><option value="">全部需求来源</option><PeopleOptions people={currentPeople}/></select>
  <select className="research-person-filter" aria-label="调研记录人筛选" value={filters.recorder_id||''} onChange={e=>filter('recorder_id',e.target.value)}><option value="">全部记录人</option><PeopleOptions people={currentPeople}/></select>
  <select aria-label="调研状态筛选" value={filters.status||''} onChange={e=>filter('status',e.target.value)}><option value="">全部状态</option>{['设计','开发','上线'].map(s=><option key={s}>{s}</option>)}</select>
  <input type="date" aria-label="调研开始日期筛选" value={filters.start||''} onInput={e=>filter('start',e.currentTarget.value)} onChange={e=>filter('start',e.target.value)}/><span>至</span><input type="date" aria-label="调研结束日期筛选" value={filters.end||''} onInput={e=>filter('end',e.currentTarget.value)} onChange={e=>filter('end',e.target.value)}/>
  <button className="text-button" onClick={()=>{setQuery('');setFilters({page:1});}}>重置</button>
 </div>;
 return <Section id="section-research" title="需求调研" filters={filtersView} actions={<><button className="export-excel" disabled={exporting||loading||!!error} title="导出当前筛选条件下的全部需求调研" aria-busy={exporting} onClick={()=>void exportExcel()}><FileSpreadsheet size={16}/>{exporting?'导出中…':'导出 Excel'}</button><button className="primary" disabled={readOnly} onClick={onNew}><Plus size={16}/>登记调研</button></>}>
  {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试</button></div>:loading?<Empty>正在读取需求调研…</Empty>:!result.items.length?<Empty>当前条件下暂无需求调研记录。</Empty>:<TableViewport><table className="research-table">
   <thead><tr><th>序号</th><th>日期</th><th>功能模块</th><th>需求描述</th><th>需求来源</th><th className="research-recorder">记录人</th><th>重要性</th><th>是否响应</th><th className="research-status">状态</th><th>解决思路</th><th>备注</th><th className="right">操作</th></tr></thead>
   <tbody>{result.items.map((row:Row,index:number)=><tr key={row.id}>
    <td>{row.sequence}</td><td className="research-date">{row.research_date}<small>{row.code}</small></td><td>{moduleNames[row.module_id]||'—'}</td>
    <td className="research-text"><button className="record-title" onClick={()=>edit(row,index)}>{row.requirement}</button></td>
    <td>{names[row.source_id]||'—'}</td><td className="research-recorder">{names[row.recorder_id]||'—'}</td><td>{row.importance}</td><td>{row.responded}</td><td className="research-status">{row.status}</td>
    <td className="research-text">{row.solution}</td><td className="research-notes">{row.notes||'—'}</td>
    <td><div className="row-actions"><button className="text-button" onClick={()=>edit(row,index)}>{readOnly?'查看':'编辑'}</button><RowMenu label="调研更多操作"><button onClick={()=>onHistory(row)}>修订记录</button>{!readOnly&&<button className="error-text" onClick={()=>onRemove(row)}>移除</button>}</RowMenu></div></td>
   </tr>)}</tbody>
  </table></TableViewport>}
  <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
 </Section>;
}
