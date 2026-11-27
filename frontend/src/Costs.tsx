import {MarkdownContent} from './Markdown';
import TableViewport from './TableViewport';
import {useEffect,useState} from 'react';
import {Plus,Search} from 'lucide-react';
import {api,expenseItems,formatMoney,type Row} from './api';
import {RowMenu,Empty,Pagination,Section} from './components';
import type {MetricNavigationRequest} from './metricNavigation';

type Props={pid:string,readOnly:boolean,refresh:number,navigationRequest?:MetricNavigationRequest,onFilterChange:()=>void,onNew:()=>void,onEdit:(row:Row)=>void,onRemove:(row:Row)=>void,onHistory:(row:Row)=>void};

export default function Costs({pid,readOnly,refresh,navigationRequest,onFilterChange,onNew,onEdit,onRemove,onHistory}:Props){
 const [result,setResult]=useState<Row>({items:[],total:0}),[filters,setFilters]=useState<Row>({page:1}),[query,setQuery]=useState('');
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{if(navigationRequest?.projectId===pid){setQuery('');setFilters({...navigationRequest.filters,page:1});}},[navigationRequest,pid]);
 useEffect(()=>{
  let alive=true;setLoading(true);setError('');
  const params=new URLSearchParams({project_id:pid});
  Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
  api('/records/costs?'+params).then(data=>{if(alive)setResult(data);}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
  return()=>{alive=false;};
 },[pid,filters,refresh,retry]);
 function filter(key:string,value:string|number){if(key!=='page')onFilterChange();setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
 const filtersView=<div className="filters cost-filters">
  <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索费用备注" placeholder="搜索备注，按回车" value={query} onChange={e=>{onFilterChange();setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
  <select aria-label="费用项目筛选" value={filters.expense_item||''} onChange={e=>filter('expense_item',e.target.value)}><option value="">全部费用项目</option>{expenseItems.map(item=><option key={item}>{item}</option>)}</select>
  <button className="text-button" onClick={()=>{onFilterChange();setQuery('');setFilters({page:1});}}>重置</button>
 </div>;
 return <Section id="section-costs" title="成本管理" filters={filtersView} actions={<button className="primary" disabled={readOnly} onClick={onNew}><Plus size={16}/>登记费用</button>}>
  {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(v=>v+1)}>重试</button></div>:loading?<Empty>正在读取费用记录…</Empty>:!result.items.length?<Empty>当前条件下暂无费用记录。</Empty>:<TableViewport><table className="cost-table">
   <thead><tr><th>费用日期</th><th>费用项目</th><th className="cost-amount">金额（元）</th><th>备注</th><th className="right">操作</th></tr></thead>
   <tbody>{result.items.map((row:Row)=><tr key={row.id}>
    <td className="cost-date">{row.expense_date||'未登记'}</td>
    <td><button className="record-title" onClick={()=>onEdit(row)}>{row.expense_item}</button><small>{row.code}</small></td>
    <td className="cost-amount">{formatMoney(row.amount)}</td><td className="cost-notes"><MarkdownContent text={row.notes}/></td>
    <td><div className="row-actions"><button className="text-button" onClick={()=>onEdit(row)}>{readOnly?'查看':'编辑'}</button><RowMenu label="费用更多操作"><button onClick={()=>onHistory(row)}>修订记录</button>{!readOnly&&<button className="error-text" onClick={()=>onRemove(row)}>移除</button>}</RowMenu></div></td>
   </tr>)}</tbody>
  </table></TableViewport>}
  <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
 </Section>;
}
