import {Plus} from 'lucide-react';
import type {Row} from './api';
import {groupPeopleByTeam} from './people';

export default function ProjectPeople({people,loading,error,readOnly,onNew,onEdit,onRetry}:{
  people:Row[];loading:boolean;error:string;readOnly:boolean;onNew:()=>void;onEdit:(person:Row)=>void;onRetry:()=>void;
}) {
  return <section className="project-people" aria-labelledby="project-people-title" aria-busy={loading}>
    <div className="project-people-heading"><h3 id="project-people-title">人员资料 <span>{loading||error?'—':people.length}</span></h3>
      <button className="primary" disabled={readOnly||loading||!!error} onClick={onNew}><Plus size={16}/>新增人员</button>
    </div>
    {loading?<p className="resource-empty">正在读取人员资料…</p>:error?<div className="resource-error" role="alert"><span>{error}</span><button onClick={onRetry}>重试</button></div>:people.length?
      <div className="people-grid">{groupPeopleByTeam(people).flatMap(group=>group.people).map(person=><button className="person-card" key={person.id} onClick={()=>onEdit(person)} aria-label={(readOnly?'查看人员 ':'编辑人员 ')+person.name}>
        <span className="avatar">{person.name.slice(0,1)}</span><span className="person-details"><strong>{person.name}</strong><small>{person.team||'未填写单位 / 团队'}</small></span><span className={'badge '+(person.enabled?'active':'muted')}>{person.enabled?'启用':'停用'}</span>
      </button>)}</div>:<p className="resource-empty">本项目暂无人员资料{readOnly?'。':'，请点击“新增人员”登记。'}</p>}
  </section>;
}
