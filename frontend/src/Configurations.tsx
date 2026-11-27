import {MarkdownContent} from './Markdown';
import TableViewport from './TableViewport';
import {useEffect,useState} from 'react';
import {Plus,Search} from 'lucide-react';
import {api,type Row} from './api';
import {RowMenu,Empty,Pagination,Section} from './components';

type Props={pid:string,readOnly:boolean,refresh:number,onNew:()=>void,onEdit:(row:Row)=>void,onRemove:(row:Row)=>void,onHistory:(row:Row)=>void};

export default function Configurations({pid,readOnly,refresh,onNew,onEdit,onRemove,onHistory}:Props){
 const [result,setResult]=useState<Row>({items:[],total:0}),[filters,setFilters]=useState<Row>({page:1}),[query,setQuery]=useState('');
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{
  let alive=true;setLoading(true);setError('');
  const params=new URLSearchParams({project_id:pid});
  Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
  api('/records/configurations?'+params).then(data=>{if(alive)setResult(data);}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
  return()=>{alive=false;};
 },[pid,filters,refresh,retry]);
 function filter(key:string,value:string|number){setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
 const filtersView=<div className="filters configuration-filters">
  <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索配置信息" placeholder="搜索项目、配置信息或备注，按回车" value={query} onChange={e=>{setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
  <input type="date" aria-label="配置开始日期筛选" value={filters.start||''} onInput={e=>filter('start',e.currentTarget.value)} onChange={e=>filter('start',e.target.value)}/><span>至</span><input type="date" aria-label="配置结束日期筛选" value={filters.end||''} onInput={e=>filter('end',e.currentTarget.value)} onChange={e=>filter('end',e.target.value)}/>
  <button className="text-button" onClick={()=>{setQuery('');setFilters({page:1});}}>重置</button>
 </div>;
 return <Section id="section-configurations" title="配置管理" filters={filtersView} actions={<button className="primary" disabled={readOnly} onClick={onNew}><Plus size={16}/>登记配置</button>}>
  {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试</button></div>:loading?<Empty>正在读取配置信息…</Empty>:!result.items.length?<Empty>当前条件下暂无配置记录。</Empty>:<TableViewport><table className="configuration-table">
   <thead><tr><th>项目</th><th>配置信息</th><th>创建或变更日期</th><th>备注</th><th className="right">操作</th></tr></thead>
   <tbody>{result.items.map((row:Row)=><tr key={row.id}>
    <td>{row.config_name}<small>{row.code}</small></td>
    <td className="configuration-info"><MarkdownContent text={row.config_info} onOpen={()=>onEdit(row)}/></td>
    <td className="configuration-date">{row.config_date}</td><td className="configuration-notes"><MarkdownContent text={row.notes}/></td>
    <td><div className="row-actions"><button className="text-button" onClick={()=>onEdit(row)}>{readOnly?'查看':'编辑'}</button><RowMenu label="配置更多操作"><button onClick={()=>onHistory(row)}>修订记录</button>{!readOnly&&<button className="error-text" onClick={()=>onRemove(row)}>移除</button>}</RowMenu></div></td>
   </tr>)}</tbody>
  </table></TableViewport>}
  <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
 </Section>;
}
