import {day,type Row} from './api';
import {Empty} from './components';
export type GanttScale = '日' | '周' | '月';
export function GanttScaleSwitch({scale,onChange}:{scale:GanttScale,onChange:(scale:GanttScale)=>void}) {
 return <div className="segmented gantt-scale" role="group" aria-label="甘特图时间尺度">
  {(['日','周','月'] as const).map(value=><button type="button" key={value} className={scale===value?'selected':''} aria-pressed={scale===value} onClick={()=>onChange(value)}>{value}</button>)}
 </div>;
}
const stamp=(x:string)=>Date.parse(x+'T00:00:00Z')/86400000;
const date=(n:number)=>new Date(n*86400000).toISOString().slice(0,10);
export default function Gantt({tasks,onEdit,scale}:{tasks:Row[],onEdit:(r:Row)=>void,scale:GanttScale}){
 if(!tasks.length)return <Empty>当前条件下没有任务。新建任务后，这里会显示计划与实际进度。</Empty>;
 const start=Math.min(...tasks.map(x=>stamp(x.plan_start)),...tasks.filter(x=>x.actual_start).map(x=>stamp(x.actual_start)))-2;
 const end=Math.max(...tasks.map(x=>stamp(x.plan_end)),...tasks.filter(x=>x.actual_end).map(x=>stamp(x.actual_end)))+3;
 const per=scale==='日'?38:scale==='周'?13:4, width=Math.max(760,(end-start+1)*per), step=scale==='日'?1:scale==='周'?7:30;
 const ticks=Array.from({length:Math.ceil((end-start)/step)},(_,i)=>start+i*step),todayX=(stamp(day())-start)*per;
 return <><div className="gantt-scroll"><div className="gantt" style={{width:width+230}}><div className="gantt-header"><strong>任务 / 责任人</strong><div style={{width}}>{ticks.map(t=><span key={t} style={{left:(t-start)*per}}>{date(t).slice(5)}</span>)}</div></div>{tasks.map(task=><div className="gantt-row" key={task.id}><button className="gantt-name" title={`${task.name} · ${task.owner_name||task.code}`} onClick={()=>onEdit(task)}><strong>{task.name}</strong><small>{task.owner_name||task.code}</small></button><div className="gantt-track" style={{width}}>{ticks.map(t=><i className="gridline" key={t} style={{left:(t-start)*per}}/>)}<button title={`${task.name}\n计划 ${task.plan_start} 至 ${task.plan_end}\n实际 ${task.actual_start||'未开始'} 至 ${task.actual_end||'未结束'}`} onClick={()=>onEdit(task)} className={'gantt-bar '+(task.status==='已完成'?'complete':task.status==='已取消'?'canceled':'')} style={{left:(stamp(task.plan_start)-start)*per,width:Math.max(per,(stamp(task.plan_end)-stamp(task.plan_start)+1)*per)}} aria-label={'编辑任务 '+task.name}><span>{task.status}</span></button>{task.actual_start&&<div className="actual-bar" style={{left:(stamp(task.actual_start)-start)*per,width:Math.max(per,(Math.min(stamp(task.actual_end||day()),end)-stamp(task.actual_start)+1)*per)}}/>}</div></div>)}{todayX>=0&&todayX<=width&&<div className="today-line" style={{left:230+todayX}}><span>今天</span></div>}</div></div></>;
}
