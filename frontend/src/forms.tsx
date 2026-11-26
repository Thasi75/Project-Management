import {useState,useRef,useEffect} from 'react';
import {api,download,day,localTime,taskStates,expenseItems,labels,type RecordKind,type Row,type ResearchNavigation} from './api';
import {useAppDialog} from './AppDialog';
import {PeopleMultiSelect} from './PeopleChoices';
import {AttachmentChoices,useAttachments} from './Attachments';
import {Fields,Modal,ModalCloseButton,Uploader,validateForm,type FieldDef} from './components';

type Props={kind:RecordKind|'project'|'person'|'module',row?:Row,researchNavigation?:ResearchNavigation,pid:string,people:Row[],modules:Row[],onClose:()=>void,onSaved:(row:Row,continueAdding?:boolean)=>void,onError:(e:unknown)=>void};
const options=(values:string[])=>values.map(x=>({id:x,name:x}));
export function RecordForm(props:Props){
 const {kind,pid,people,modules,onClose,onSaved,onError}=props;
 const {confirmAction}=useAppDialog();
 const [researchRow,setResearchRow]=useState(props.row),[researchPosition,setResearchPosition]=useState(props.researchNavigation);
 const [sequenceRequest,setSequenceRequest]=useState(0);
 const row=kind==='research'?researchRow:props.row;
 const [navigating,setNavigating]=useState(false),navigationLock=useRef(false);
 const {remember,forProject}=useAttachments();
 const readOnly=!!row?.readOnly;
 const [value,setValue]=useState<Row>(()=>({status:kind==='research'?'设计':kind==='risks'?'待处理':'未开始',importance:'中',responded:'是',research_date:day(),level:'中',enabled:true,sort:0,plan_start:day(),plan_end:day(),work_date:day(),config_date:day(),expense_date:day(),project_id:pid,change_date:day(),raised_date:day(),effective_date:day(),member_ids:[],participant_ids:[],attachment_ids:[],change_ids:[],task_ids:[],reason:'',...row,...(kind==='communications'?{module_id:row?.module_id||modules.find(m=>m.project_id===pid&&m.name==='项目公共事务'&&m.enabled)?.id}:{}),occurred_at:row?.occurred_at?.replace(' ','T')||localTime()}));
 const [dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[uploading,setUploading]=useState(false),[error,setError]=useState('');
 const [exporting,setExporting]=useState<'docx'|'pdf'|null>(null),exportLock=useRef(false);
 const [related,setRelated]=useState<Row>({tasks:[],changes:[],scopes:[],attachments:[]});
 const staged=useRef<string[]>([]),key=useRef(crypto.randomUUID());
 const formRef=useRef<HTMLFormElement>(null),submitting=useRef(false),focusAfterSave=useRef<'name'|'requirement'|null>(null);
 useEffect(()=>{if(!busy&&focusAfterSave.current){const field=focusAfterSave.current;focusAfterSave.current=null;formRef.current?.querySelector<HTMLInputElement|HTMLTextAreaElement>('[name="'+field+'"]')?.focus();}},[busy]);
 const set=(k:string,v:any)=>{setValue(old=>({...old,[k]:v}));setDirty(true);};
 // Load all relation choices through paginated endpoints without truncation.
 useEffect(()=>{let alive=true;void(async()=>{if(!pid||['communications','configurations','costs','research'].includes(kind))return;try{async function all(k:string){let items:Row[]=[],page=1;while(true){const data=await api('/records/'+k+'?project_id='+pid+'&size=200&page='+page);items.push(...data.items);if(items.length>=data.total)break;page++;}return items;}
 const [tasks,changes,scopes,attachments]=await Promise.all([all('tasks'),all('changes'),api('/projects/'+pid+'/scopes'),api('/projects/'+pid+'/attachments')]);if(alive){setRelated({tasks,changes,scopes,attachments});remember(attachments);}}catch(e){onError(e);}})();return()=>{alive=false;};},[pid]);
 useEffect(()=>{if(kind!=='research'||row?.id)return;let alive=true;api('/projects/'+pid+'/research/next-sequence').then(data=>{if(alive)setValue(old=>old.sequence===undefined?{...old,sequence:data.sequence}:old);}).catch(e=>{if(alive)setError('读取下一条序号失败：'+e.message+'。可手工填写序号后继续。');});return()=>{alive=false;};},[kind,pid,row?.id,sequenceRequest]);
 const memberOptions=people.filter(p=>p.project_id===pid).map(p=>({id:p.id,enabled:p.enabled,name:p.name,team:p.team}));
 const sourceOptions=[...memberOptions].sort((a,b)=>Number(b.enabled)-Number(a.enabled)).map(person=>({...person,id:person.name+(person.team?.trim()?' · '+person.team.trim():'')})).filter((person,index,all)=>all.findIndex(other=>other.id===person.id)===index);
 if(kind==='changes'&&row?.source&&!sourceOptions.some(person=>person.id===row.source))sourceOptions.push({id:row.source,name:row.source,team:'原有来源',enabled:true});
 useEffect(()=>{if(kind!=='communications')return;const defaultModule=modules.find(m=>m.project_id===pid&&m.name==='项目公共事务'&&m.enabled);if(defaultModule)setValue(old=>old.module_id===undefined?{...old,module_id:defaultModule.id}:old);},[modules,pid,kind]);
 const moduleOptions=modules.filter(p=>p.project_id===pid).sort((a,b)=>Number(b.name==='项目公共事务')-Number(a.name==='项目公共事务')).map(p=>({id:p.id,name:p.name,enabled:p.enabled}));
 const taskOptions=related.tasks.map((x:Row)=>({id:x.id,name:x.code+' · '+x.name}));
 const changeOptions=related.changes.map((x:Row)=>({id:x.id,name:x.code+' · '+x.title}));
 const attachOptions=forProject(pid,related.attachments).filter((x:Row)=>!x.removed||value.attachment_ids?.includes(x.id));
 const owner:FieldDef={key:'owner_id',label:'责任人',type:'select',options:memberOptions,groupByTeam:true,required:true};
 const module:FieldDef={key:'module_id',label:'功能模块',type:'select',options:moduleOptions};
 const participants:FieldDef={key:'participant_ids',label:'参与人员',wide:true,content:<PeopleMultiSelect people={memberOptions} value={value.participant_ids||[]} onChange={ids=>set('participant_ids',ids)} disabled={readOnly||busy||kind==='logs'&&!!row?.communication_id} label="参与人员"/>};
 const attachment:FieldDef={key:'attachment_ids',label:'关联附件',type:'multi',wide:true,content:<AttachmentChoices files={attachOptions} selected={value.attachment_ids||[]} onChange={ids=>set('attachment_ids',ids)} disabled={!!row?.readOnly||busy}/>};
 const notes:FieldDef={key:'notes',label:'备注',type:'textarea',wide:true};
 let fields:FieldDef[]=[];
 if(kind==='project') fields=[{key:'name',label:'项目名称',required:true},{key:'customer',label:'客户 / 所属单位'},
 ...(row?.id?[{...owner,label:'项目负责人',required:false}]:[]),
 {key:'status',label:'项目状态',type:'select',options:options(taskStates.slice(0,4)),required:true},
 {key:'plan_start',label:'计划开始',type:'date'},{key:'plan_end',label:'计划结束',type:'date'},
 {key:'scope',label:'范围描述',type:'textarea',wide:true,required:true},{key:'exclusions',label:'不包含范围',type:'textarea',wide:true},
 {key:'deliverables',label:'主要交付成果',type:'textarea'},{key:'acceptance',label:'验收要求',type:'textarea'},
 ...(row?[{key:'change_id',label:'范围修订依据（可选变更）',type:'select',options:changeOptions}]:[]),notes];
 if(kind==='tasks') fields=[{key:'name',label:'任务名称',required:true},{key:'phase',label:'所属阶段'},module,owner,
 {key:'plan_start',label:'计划开始',type:'date',required:true},{key:'plan_end',label:'计划结束',type:'date',required:true},
 {key:'planned_deliverable',label:'计划交付物',type:'textarea',wide:true,required:true},participants,
 {key:'status',label:'任务状态',type:'select',options:options(taskStates),required:true},
 {key:'actual_start',label:'实际开始',type:'date',required:['进行中','暂停','已完成'].includes(value.status)},
 {key:'actual_end',label:'实际结束',type:'date',required:value.status==='已完成'},
 {key:'delivery_url',label:'交付链接',type:'url'},
 {key:'actual_deliverable',label:'实际交付物 / 成果说明',type:'textarea',wide:true,required:value.status==='已完成'},attachment,
 {key:'change_ids',label:'关联需求变更',type:'multi',options:changeOptions,wide:true},notes];
 if(kind==='logs') fields=[{key:'work_date',label:'工作日期',type:'date',required:true},module,owner,
 {key:'task_id',label:'关联任务',type:'select',options:taskOptions},participants,{key:'content',label:'工作内容',type:'textarea',wide:true,required:true},
 {key:'details',label:'工作详情',type:'textarea',wide:true},{key:'next_plan',label:'后续安排',type:'textarea',wide:true},notes];
 if(kind==='costs') fields=[{key:'expense_date',label:'费用日期',type:'date',required:true},
 {key:'expense_item',label:'费用项目',type:'select',required:true,options:options(expenseItems)},
 {key:'amount',label:'金额（元）',type:'money',required:true},notes];
 if(kind==='research') fields=[{key:'sequence',label:'序号',type:'number',required:true,min:1,max:2147483647},{key:'research_date',label:'日期',type:'date',required:true},{...module,required:true},
 {key:'requirement',label:'需求描述',type:'textarea',required:true,wide:true},
 {key:'source_id',label:'需求来源',type:'select',options:memberOptions,groupByTeam:true,required:true},
 {key:'recorder_id',label:'记录人',type:'select',options:memberOptions,groupByTeam:true,required:true},
 {key:'importance',label:'重要性',type:'select',options:options(['高','中','低']),required:true},
 {key:'responded',label:'是否响应',type:'select',options:options(['是','否']),required:true},
 {key:'status',label:'状态',type:'select',options:options(['设计','开发','上线']),required:true},
 {key:'solution',label:'解决思路',type:'textarea',required:true,wide:true},notes];
 if(kind==='configurations') fields=[{key:'config_name',label:'项目',required:true},
 {key:'config_date',label:'创建或变更日期',type:'date',required:true},
 {key:'config_info',label:'配置信息',type:'textarea',required:true,wide:true},notes];
 if(kind==='changes') fields=[{key:'title',label:'变更标题',required:true},{key:'change_date',label:'变更日期',type:'date',required:true},
 {key:'content',label:'变更内容',type:'textarea',wide:true,required:true},{key:'original',label:'原需求',type:'textarea',wide:true},
 {key:'change_reason',label:'变更原因',type:'textarea'},{key:'source',label:'提出人 / 来源',type:'select',options:sourceOptions,groupByTeam:true},module,
 {key:'scope_id',label:'关联范围版本',type:'select',options:related.scopes.map((x:Row)=>({id:x.id,name:'V'+x.number+' · '+x.effective_date}))},
 {key:'impact',label:'影响说明',type:'textarea',wide:true},{key:'task_ids',label:'关联任务',type:'multi',options:taskOptions,wide:true},attachment,notes];
 if(kind==='risks') fields=[{key:'description',label:'风险描述',type:'textarea',wide:true,required:true},
 {key:'level',label:'等级',type:'select',options:options(['低','中','高']),required:true},{key:'raised_date',label:'提出日期',type:'date',required:true},
 {...owner,required:false},{key:'task_id',label:'关联任务',type:'select',options:taskOptions},
 {key:'response',label:'应对措施',type:'textarea',wide:true},{key:'status',label:'处理状态',type:'select',options:options(['待处理','处理中','已关闭']),required:true},
 {key:'closed_date',label:'关闭日期',type:'date',required:value.status==='已关闭'},notes];
 if(kind==='communications') fields=[{key:'occurred_at',label:'时间',type:'datetime-local',required:true},{key:'location',label:'地点'},
 {key:'subject',label:'主题',required:true},{...module,required:true},participants,
 ...(['host_id','recorder_id'] as const).map(key=>({key,label:key==='host_id'?'主持人':'记录人',type:'select',options:memberOptions,groupByTeam:true,required:true})),
 {key:'summary',label:'沟通概况',type:'textarea',required:true,wide:true,heightKey:'summary_height'},{key:'details',label:'沟通详情',type:'textarea',wide:true,heightKey:'details_height'}];
 if(kind==='person') fields=[{key:'name',label:'姓名',required:true},{key:'team',label:'单位 / 团队'},notes,{key:'enabled',label:'启用',type:'checkbox'}];
 if(kind==='module') fields=[{key:'name',label:'模块名称',required:true},{key:'sort',label:'排序',type:'number'},{key:'enabled',label:'启用',type:'checkbox'}];
 const business=!['person','module','configurations','costs','research'].includes(kind);
 if(business)fields.push({key:'effective_date',label:'本次修订业务生效日',type:'date',required:true,hint:'用于历史还原；实际开始和完成按对应实际日期记录。'},{key:'reason',label:row?'修订原因':'登记说明',required:!!row&&['tasks','project'].includes(kind)});
 if(kind==='logs'&&row?.communication_id)fields=fields.map(field=>['work_date','module_id','owner_id','participant_ids','content','details'].includes(field.key)?{...field,disabled:true}:field);
 const canContinue=['module','research'].includes(kind)&&!row?.id&&!readOnly;
 const canNavigate=kind==='research'&&!!row?.id&&!!researchPosition;
 async function navigateResearch(direction:-1|1){
  if(!canNavigate||!researchPosition||navigationLock.current||submitting.current||busy||uploading)return;
  const index=researchPosition.index+direction;
  if(index<0||index>=researchPosition.total)return;
  navigationLock.current=true;setNavigating(true);
  try{
   if(dirty&&!await confirmAction({title:'切换需求记录？',message:'当前记录有未保存的修改。切换后这些修改将不会保存。',confirmText:'放弃修改并切换',cancelText:'继续编辑',danger:true}))return;
   setError('');
   const params=new URLSearchParams({project_id:pid});
   Object.entries(researchPosition.filters).forEach(([name,value])=>{if(!['page','size','project_id'].includes(name)&&value)params.set(name,String(value));});
   params.set('page',String(index+1));params.set('size','1');
   const result=await api<{items:Row[];total:number}>('/records/research?'+params);
   const next=result.items[0];
   if(!next)throw new Error('该记录已不在当前筛选结果中，请关闭编辑窗口后刷新列表。');
   setResearchRow({...next,readOnly});setValue({...next});setDirty(false);key.current=crypto.randomUUID();
   setResearchPosition({...researchPosition,index,total:result.total});
  }catch(e){setError((e as Error).message);}finally{navigationLock.current=false;setNavigating(false);}
 }
 const title=(readOnly?'查看':row?.id?'编辑':'新建')+(kind==='project'?'项目':kind==='person'?'人员':kind==='module'?'功能模块':labels[kind]);
 async function exportCommunication(extension:'docx'|'pdf'){
  if(kind!=='communications'||!row?.id||busy||exportLock.current)return;
  exportLock.current=true;setExporting(extension);setError('');
  try{await download('/projects/'+pid+'/communications/'+row.id+'/export/'+extension+'?version='+row.version);}
  catch(e){setError((e as Error).message);onError(e);}
  finally{exportLock.current=false;setExporting(null);}
 }
 async function close(){for(const id of staged.current)await api('/attachments/staged/'+id,'DELETE').catch(()=>{});onClose();}
 async function submit(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(submitting.current||busy||uploading||readOnly||navigationLock.current||exportLock.current)return;const validation=validateForm(e.currentTarget);if(validation){setError(validation);return;}const nativeValues=new FormData(e.currentTarget);const continueAdding=canContinue&&(e.nativeEvent as SubmitEvent).submitter?.getAttribute('value')==='continue';submitting.current=true;setBusy(true);setError('');try{
  const data:Row={}; for(const field of fields){const v=(field.type==='date'||field.type==='datetime-local')&&!field.disabled?(nativeValues.get(field.key)||null):value[field.key];if(v!==undefined)data[field.key]=v;
   if(field.heightKey){const textarea=e.currentTarget.elements.namedItem(field.key);if(textarea instanceof HTMLTextAreaElement)data[field.heightKey]=Math.max(80,Math.round(textarea.getBoundingClientRect().height));}
  }if(row?.id)data.version=row.version;
  if(kind==='communications'){const time=String(data.occurred_at||'').replace('T',' ');data.occurred_at=time.length===16?time+':00':time;if(!data.host_id||!data.recorder_id)throw new Error('请选择主持人和记录人。');}
  if(kind==='changes')data.source=data.source||'';
  if(kind==='project')data.attachment_ids=value.attachment_ids;
  if(kind==='tasks'&&value.status!=='已完成')data.actual_end=null;
  if(kind==='risks'&&value.status!=='已关闭')data.closed_date=null;
  const base=kind==='project'?'/projects':kind==='person'?'/projects/'+pid+'/people':kind==='module'?'/projects/'+pid+'/modules':'/projects/'+pid+'/records/'+kind;
  const transition=row?.id&&['tasks','risks'].includes(kind)&&data.status!==row.status;const result=await api(base+(row?.id?'/'+row.id:'')+(transition?'/transition':''),transition?'POST':row?.id?'PUT':'POST',data,key.current);staged.current=[];
  if(continueAdding){
   if(kind==='research'){
    setValue({research_date:result.research_date,module_id:result.module_id,source_id:result.source_id,recorder_id:result.recorder_id,
     requirement:'',solution:'',notes:'',importance:'中',responded:'是',status:'设计'});
    setSequenceRequest(request=>request+1);focusAfterSave.current='requirement';
   }else{setValue(old=>({...old,name:'',sort:result.sort+1}));focusAfterSave.current='name';}
   setDirty(false);key.current=crypto.randomUUID();
  }
  onSaved(result,continueAdding);
 }catch(e){setError((e as Error).message);}finally{submitting.current=false;setBusy(false);}}
 return <Modal title={title} wide dirty={dirty} onClose={()=>void close()}><form className={kind==='costs'?'cost-form':undefined} ref={formRef} noValidate onSubmit={submit}><div className="modal-body">
 {kind==='communications'&&<div className="note">保存后同步生成一条工作日志；编辑和移除将同步处理对应日志。</div>}
 {kind==='logs'&&row?.communication_id&&<div className="note">此日志由项目沟通同步生成。日期、功能模块、责任人、参与人员、内容和详情请在项目沟通中修改；可在此补充关联任务、后续安排和备注。</div>}
 {kind==='changes'&&<div className="note">保存即完成登记。变更内容可供简报引用；范围和任务分别维护。</div>}
 {kind==='project'&&!row?.id&&<div className="note">保存项目后，可在项目概况中维护人员资料，再编辑项目指定负责人。</div>}
 {error&&<div className="error" role="alert">{error}</div>}{kind==='research'?<div className="research-fields">
 {[
  {className:'research-core-fields',keys:['sequence','research_date','module_id']},
  {className:'research-text-fields',keys:['requirement']},
  {className:'research-choice-fields',keys:['source_id','recorder_id','importance','responded','status']},
  {className:'research-text-fields',keys:['solution','notes']},
 ].map(group=><div className={group.className} key={group.keys[0]}><Fields fields={fields.filter(field=>group.keys.includes(field.key))} value={value} onChange={set} disabled={readOnly||busy||navigating}/></div>)}
 </div>:<Fields fields={fields} value={value} onChange={set} disabled={readOnly||busy}/>}
 {['project','tasks','changes'].includes(kind)&&!readOnly&&<div className="field"><span>补充上传附件</span><Uploader onBusy={setUploading} pid={kind==='project'?row?.id:pid} onStaged={id=>staged.current.push(id)} onUploaded={id=>{setValue(old=>({...old,attachment_ids:[...old.attachment_ids,id]}));setDirty(true);if(pid)void api('/projects/'+pid+'/attachments').then(attachments=>{setRelated(old=>({...old,attachments}));remember(attachments);}).catch(onError);}}/></div>}
 </div><div className={'modal-foot'+(canContinue?' module-create-footer':'')+(canNavigate?' research-navigation-footer':'')+(kind==='communications'?' communication-export-footer':'')}><span>{kind==='communications'&&row?.id?(dirty?'有未保存的修改；导出使用已保存内容。':readOnly?'归档项目只读，可导出已保存内容。':'导出使用已保存内容。'):readOnly?'归档项目只读':'* 为必填项，保存后保留修订记录'}</span><div className="actions">{kind==='communications'&&row?.id&&<><button type="button" disabled={busy||uploading||!!exporting} aria-busy={exporting==='docx'} onClick={()=>void exportCommunication('docx')}>{exporting==='docx'?'正在导出 Word…':'导出 Word'}</button><button type="button" disabled={busy||uploading||!!exporting} aria-busy={exporting==='pdf'} onClick={()=>void exportCommunication('pdf')}>{exporting==='pdf'?'正在导出 PDF…':'导出 PDF'}</button></>}<ModalCloseButton>取消</ModalCloseButton>{!readOnly&&<button type="submit" className="primary" disabled={busy||uploading||navigating||!!exporting}>{uploading?'等待上传完成…':busy?'保存中…':'保存'}</button>}{canContinue&&<button type="submit" value="continue" disabled={busy||uploading}>保存并继续新增</button>}{canNavigate&&researchPosition&&<div className="research-record-navigation" role="group" aria-label="切换需求记录"><span role="status">{navigating?'正在切换…':`第 ${researchPosition.index+1} / ${researchPosition.total} 条`}</span><button type="button" disabled={busy||navigating||researchPosition.index===0} onClick={()=>void navigateResearch(-1)}>上一条</button><button type="button" disabled={busy||navigating||researchPosition.index>=researchPosition.total-1} onClick={()=>void navigateResearch(1)}>下一条</button></div>}</div></div></form></Modal>;
}

