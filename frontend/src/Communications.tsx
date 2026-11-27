import {MarkdownContent} from './Markdown';
import TableViewport from './TableViewport';
import {useEffect,useState} from 'react';
import {Plus,Search} from 'lucide-react';
import {api,type Row} from './api';
import {RowMenu,Empty,Pagination,Section} from './components';
import {PeopleOptions} from './PeopleChoices';

export default function Communications({pid,people,readOnly,refresh,onNew,onEdit,onRemove,onHistory,onLog}:{
  pid:string;people:Row[];readOnly:boolean;refresh:number;onNew:()=>void;onEdit:(row:Row)=>void;
  onRemove:(row:Row)=>void;onHistory:(row:Row)=>void;onLog:(id:string)=>void;
}) {
  const [query,setQuery]=useState(''),[filters,setFilters]=useState<Row>({page:1}),[result,setResult]=useState<Row>({items:[],total:0});
  const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const names=Object.fromEntries(people.filter(person=>person.project_id===pid).map(person=>[person.id,person.name]));
  useEffect(()=>{let alive=true;setLoading(true);setError('');const params=new URLSearchParams({project_id:pid});
    Object.entries(filters).forEach(([key,value])=>{if(value)params.set(key,String(value));});
    api('/records/communications?'+params).then(data=>{if(alive)setResult(data);}).catch(e=>{if(alive){setResult({items:[],total:0});setError(e.message);}}).finally(()=>{if(alive)setLoading(false);});
    return()=>{alive=false;};
  },[pid,filters,refresh,retry]);
  function filter(key:string,value:string|number){setFilters(old=>({...old,[key]:value,page:key==='page'?value:1}));}
  const tools=<div className="filters communication-filters">
    <form className="search" onSubmit={e=>{e.preventDefault();filter('q',query);}}><Search size={16}/><input aria-label="搜索项目沟通" placeholder="搜索主题、地点或内容" value={query} onChange={e=>{setQuery(e.target.value);if(!e.target.value)filter('q','');}}/></form>
    <select aria-label="主持人筛选" value={filters.host_id||''} onChange={e=>filter('host_id',e.target.value)}><option value="">全部主持人</option><PeopleOptions people={people.filter(person=>person.project_id===pid)}/></select>
    <input type="date" aria-label="沟通开始日期筛选" value={filters.start||''} onInput={e=>filter('start',e.currentTarget.value)} onChange={e=>filter('start',e.target.value)}/><span>至</span><input type="date" aria-label="沟通结束日期筛选" value={filters.end||''} onInput={e=>filter('end',e.currentTarget.value)} onChange={e=>filter('end',e.target.value)}/>
    <button className="text-button" onClick={()=>{setQuery('');setFilters({page:1});}}>重置</button>
  </div>;
  return <Section id="section-communications" title="项目沟通" filters={tools} actions={<button className="primary" disabled={readOnly} onClick={onNew}><Plus size={16}/>登记沟通</button>}>
    {error?<div className="acceptance-empty" role="alert">{error}<button onClick={()=>setRetry(value=>value+1)}>重试</button></div>:loading?<Empty>正在读取项目沟通…</Empty>:!result.items.length?<Empty>当前条件下暂无项目沟通记录。</Empty>:<TableViewport><table className="communication-table">
      <thead><tr><th>时间 / 地点</th><th>主题 / 沟通概况</th><th>主持人 / 记录人</th><th>参与人员</th><th className="right">操作</th></tr></thead>
      <tbody>{result.items.map((row:Row)=><tr key={row.id}>
        <td><span className="communication-time">{row.occurred_at}</span><small>{row.location||'未填写地点'}</small></td>
        <td><button className="record-title" onClick={()=>onEdit(row)}>{row.subject}</button><MarkdownContent className="markdown-excerpt" text={row.summary}/></td>
        <td>{names[row.host_id]||'—'}<small>记录：{names[row.recorder_id]||'—'}</small></td>
        <td>{row.participant_ids.map((id:string)=>names[id]||'—').join('、')||'未选择'}</td>
        <td><div className="row-actions"><button className="text-button" onClick={()=>onEdit(row)}>{readOnly?'查看':'编辑'}</button><button className="text-button" onClick={()=>onLog(row.log_id)}>工作日志</button><RowMenu label="沟通更多操作"><button onClick={()=>onHistory(row)}>修订记录</button>{!readOnly&&<button className="error-text" onClick={()=>onRemove(row)}>移除</button>}</RowMenu></div></td>
      </tr>)}</tbody>
    </table></TableViewport>}
    <Pagination page={filters.page} total={result.total} onPage={page=>filter('page',page)}/>
  </Section>;
}
