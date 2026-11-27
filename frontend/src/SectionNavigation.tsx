import {useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode} from 'react';
import {BookOpen, ClipboardList, FilePenLine, Flag, Layers, FileText, FolderCheck, MessagesSquare, SlidersHorizontal, Wallet, ListChecks, PlugZap, Code2, Paperclip} from 'lucide-react';
import type {Kind} from './api';

type WorkspaceSection = Kind | 'research' | 'interfaces' | 'communications' | 'configurations' | 'costs' | 'briefs' | 'overview' | 'acceptance' | 'coding' | 'attachments';

const sections = [
  {kind:'overview', title:'项目概况', icon:Layers},
  {kind:'tasks', title:'任务计划', icon:ClipboardList},
  {kind:'research', title:'需求调研', icon:ListChecks},
  {kind:'interfaces', title:'外部接口', icon:PlugZap},
  {kind:'communications', title:'项目沟通', icon:MessagesSquare},
  {kind:'coding', title:'代码编写', icon:Code2},
  {kind:'logs', title:'工作日志', icon:BookOpen},
  {kind:'configurations', title:'配置管理', icon:SlidersHorizontal},
  {kind:'changes', title:'需求变更', icon:FilePenLine},
  {kind:'risks', title:'项目风险', icon:Flag},
  {kind:'briefs', title:'项目简报', icon:FileText},
  {kind:'acceptance', title:'验收材料', icon:FolderCheck},
  {kind:'costs', title:'成本管理', icon:Wallet},
  {kind:'attachments', title:'项目附件', icon:Paperclip},
] as const;
export const sectionId = (kind:WorkspaceSection) => 'section-'+kind;
const tabId = (kind:WorkspaceSection) => 'workspace-tab-'+kind;
const panelId = (kind:WorkspaceSection) => 'workspace-panel-'+kind;

export function useWorkspaceSidebar() {
  const [open,setOpen]=useState(()=>{try{return localStorage.getItem('pm.workspace.sidebar')==='open';}catch{return false;}});
  const [overlay,setOverlay]=useState(()=>!window.matchMedia('(min-width:1740px)').matches);
  const toggleRef=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    const media=window.matchMedia('(min-width:1740px)');
    const update=()=>setOverlay(!media.matches);
    media.addEventListener('change',update);return()=>media.removeEventListener('change',update);
  },[]);
  function change(next:boolean){setOpen(next);try{localStorage.setItem('pm.workspace.sidebar',next?'open':'closed');}catch{/* Navigation still works when storage is unavailable. */}}
  function close(){change(false);toggleRef.current?.focus({preventScroll:true});}
  return {open,overlay,toggleRef,close,toggle:()=>change(!open)};
}

export function useSectionNavigation(projectId:string) {
  const [selection,setSelection] = useState<{kind:WorkspaceSection,projectId:string}>({kind:'tasks',projectId});
  const active = selection.projectId===projectId ? selection.kind : 'tasks';
  useEffect(()=>{setSelection({kind:'tasks',projectId});},[projectId]);
  useLayoutEffect(()=>{
    document.querySelector('.workspace-scroll')?.scrollTo({top:0,behavior:'instant'});
    document.querySelector('.project-overview-scroll')?.scrollTo({top:0,behavior:'instant'});
  },[active,projectId]);
  return {
    active,
    navigate:(kind:WorkspaceSection)=>{
      setSelection({kind,projectId});
    },
  };
}

export function WorkspacePanel({kind,active,children}:{kind:WorkspaceSection,active:WorkspaceSection,children:ReactNode}) {
  // Keep filters, chart scale and brief state intact when switching functional tabs.
  return <div id={panelId(kind)} role="tabpanel" aria-labelledby={tabId(kind)} hidden={active!==kind} tabIndex={0}>{children}</div>;
}

export default function SectionNavigation({active,onNavigate,open,overlay,onClose}:{active:WorkspaceSection,onNavigate:(kind:WorkspaceSection)=>void,open:boolean,overlay:boolean,onClose:()=>void}) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!open)return;
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({block:'nearest',inline:'nearest'});
  },[active,open]);
  useEffect(()=>{if(open)list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus({preventScroll:true});},[open,overlay]);
  function navigate(event:KeyboardEvent<HTMLButtonElement>,index:number) {
    let next:number;
    if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%sections.length;
    else if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index+sections.length-1)%sections.length;
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=sections.length-1;
    else return;
    event.preventDefault();
    onNavigate(sections[next].kind);
    list.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }
  function sidebarKeys(event:KeyboardEvent<HTMLElement>){
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();return;}
    if(!overlay||event.key!=='Tab')return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')).filter(button=>button.tabIndex>=0);
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  return <aside id="workspace-navigation" className="workspace-sidebar" hidden={!open} aria-label="功能导航" role={overlay?'dialog':undefined} aria-modal={overlay&&open?true:undefined} onKeyDown={sidebarKeys}>
    <div className="sidebar-heading"><strong>项目功能</strong></div>
    <div className="section-navigation" ref={list} role="tablist" aria-label="项目功能" aria-orientation="vertical">
    {sections.map(({kind,title,icon:Icon},index)=><button type="button" key={kind}
      id={tabId(kind)} role="tab" aria-controls={panelId(kind)} aria-selected={active===kind}
      tabIndex={active===kind?0:-1} onClick={()=>{onNavigate(kind);if(overlay)onClose();}} onKeyDown={event=>navigate(event,index)}
    ><Icon size={18}/><span>{title}</span></button>)}
  </div></aside>;
}
