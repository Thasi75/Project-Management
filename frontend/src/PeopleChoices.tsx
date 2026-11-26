import {useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {ChevronDown} from 'lucide-react';
import type {Row} from './api';
import {groupPeopleByTeam} from './people';

export function PeopleOptions({people,value,restrictDisabled=false}:{people:Row[];value?:string;restrictDisabled?:boolean}){
  return <>{groupPeopleByTeam(people).map(group=><optgroup key={group.team} label={group.label}>
    {group.people.map(person=><option key={person.id} value={person.id} disabled={restrictDisabled&&person.enabled===false&&value!==person.id}>
      {person.name}{group.team?' · '+group.team:''}{person.enabled===false?'（已停用）':''}
    </option>)}
  </optgroup>)}</>;
}

function PeopleGroups({people,children}:{people:Row[];children:(person:Row)=>ReactNode}){
  return <>{!people.length&&<small>暂无可选人员</small>}{groupPeopleByTeam(people).map(group=><fieldset className="people-choice-group" key={group.team}>
    <legend>{group.label}</legend><div className="people-choice-items">{group.people.map(children)}</div>
  </fieldset>)}</>;
}

export function PeopleCheckboxes({people,value,onChange,disabled=false,label}:{people:Row[];value:string[];onChange:(ids:string[])=>void;disabled?:boolean;label:string}){
  return <div className="checks people-grouped" role="group" aria-label={label}><PeopleGroups people={people}>{person=><label key={person.id}>
    <input type="checkbox" disabled={disabled||person.enabled===false&&!value.includes(person.id)} checked={value.includes(person.id)}
      onChange={event=>onChange(event.target.checked?[...value,person.id]:value.filter(id=>id!==person.id))}/>
    <span>{person.name}{person.enabled===false?'（已停用）':''}</span>
  </label>}</PeopleGroups></div>;
}

export function PeopleMultiSelect({people,value,onChange,disabled=false,label}:{people:Row[];value:string[];onChange:(ids:string[])=>void;disabled?:boolean;label:string}){
  const id=useId(),root=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null),popup=useRef<HTMLDivElement>(null);
  const [open,setOpen]=useState(false),[position,setPosition]=useState<{left:number;width:number;maxHeight:number;top?:number;bottom?:number}>({left:0,width:0,maxHeight:320});
  const names=value.map(id=>{const person=people.find(p=>p.id===id),team=String(person?.team||'').trim();return person?person.name+(team?' · '+team:'')+(person.enabled===false?'（已停用）':''):'未找到的人员';}).join('、');
  function toggle(){
    if(disabled)return;
    if(open){setOpen(false);return;}
    const rect=trigger.current?.getBoundingClientRect();if(!rect)return;
    const below=window.innerHeight-rect.bottom-14,above=rect.top-14,width=Math.min(rect.width,window.innerWidth-24);
    const down=below>=180||below>=above;
    setPosition({left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),width,maxHeight:Math.min(320,Math.max(80,down?below:above)),...(down?{top:rect.bottom+6}:{bottom:window.innerHeight-rect.top+6})});
    setOpen(true);
  }
  useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
  useEffect(()=>{
    if(!open)return;
    (popup.current?.querySelector<HTMLInputElement>('input:checked:not(:disabled)')||popup.current?.querySelector<HTMLInputElement>('input:not(:disabled)'))?.focus({preventScroll:true});
    const outside=(event:Event)=>{if(event.target instanceof Node&&!root.current?.contains(event.target))setOpen(false);};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setOpen(false);trigger.current?.focus({preventScroll:true});}};
    const scroll=(event:Event)=>{if(event.target instanceof Node&&!popup.current?.contains(event.target))setOpen(false);};
    const resize=()=>setOpen(false);
    document.addEventListener('pointerdown',outside,true);document.addEventListener('focusin',outside,true);
    document.addEventListener('keydown',escape,true);document.addEventListener('scroll',scroll,true);window.addEventListener('resize',resize);
    return()=>{document.removeEventListener('pointerdown',outside,true);document.removeEventListener('focusin',outside,true);document.removeEventListener('keydown',escape,true);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',resize);};
  },[open]);
  return <div className="people-multi-select" ref={root}>
    <button ref={trigger} type="button" className="people-select-trigger" disabled={disabled} aria-label={label} aria-describedby={id+'-value'} aria-haspopup="dialog" aria-expanded={open} aria-controls={id} title={names||'请选择'} onClick={toggle} onKeyDown={event=>{if(event.key==='ArrowDown'&&!open){event.preventDefault();toggle();}}}>
      <span id={id+'-value'}>{names||'请选择'}</span><ChevronDown size={16}/>
    </button>
    {open&&<div id={id} ref={popup} className="people-select-popup" role="dialog" aria-label={'选择'+label} style={position}>
      <PeopleCheckboxes people={people} value={value} onChange={onChange} disabled={disabled} label={label}/>
    </div>}
  </div>;
}

export function PeopleRadios({people,value,onChange,disabled=false,name,label,required=false}:{people:Row[];value?:string;onChange:(id:string)=>void;disabled?:boolean;name:string;label:string;required?:boolean}){
  return <div className="checks people-grouped communication-people" role="radiogroup" aria-label={label}><PeopleGroups people={people}>{person=><label key={person.id}>
    <input type="radio" name={name} data-field-label={label} value={person.id} checked={value===person.id} required={required}
      disabled={disabled||person.enabled===false&&value!==person.id} onChange={()=>onChange(person.id)}/>
    <span>{person.name}{person.enabled===false?'（已停用）':''}</span>
  </label>}</PeopleGroups></div>;
}
