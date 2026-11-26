import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {X, Upload, RefreshCw, FileText, Ellipsis} from 'lucide-react';
import {api, type Row} from './api';
import {useAppDialog} from './AppDialog';
import {PeopleCheckboxes,PeopleOptions} from './PeopleChoices';
import {AcceptanceToggle,useAttachments} from './Attachments';

const ModalCloseContext = createContext<() => void>(() => {});
export function ModalCloseButton({children}: {children: ReactNode}) {
  const close = useContext(ModalCloseContext);
  return <button type="button" onClick={close}>{children}</button>;
}

export function validateForm(form: HTMLFormElement): string | null {
  for (const control of Array.from(form.elements)) {
    if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement)
      || !control.willValidate || control.validity.valid) continue;
    const label = control.getAttribute('data-field-label') || control.closest('label')?.querySelector('span')?.textContent?.replace(/\s*\*\s*$/, '') || '此项';
    control.focus();
    if (control.validity.valueMissing) return (control instanceof HTMLSelectElement || control instanceof HTMLInputElement && control.type==='radio' ? '请选择' : '请填写') + label;
    return '请检查“' + label + '”的格式或取值';
  }
  return null;
}

export function Modal({title,children,onClose,wide=false,dirty=false,fullscreen=false}:{title:string,children:ReactNode,onClose:()=>void,wide?:boolean,dirty?:boolean,fullscreen?:boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  const {confirmAction} = useAppDialog();
  const closing = useRef(false);
  const close = async () => {
    if (closing.current) return;
    closing.current = true;
    try {
      if (!dirty || await confirmAction({title:'放弃未保存的修改？',message:'当前内容尚未保存。放弃修改后，已填写的内容将不会保存。',confirmText:'放弃修改',cancelText:'继续编辑',danger:true})) onClose();
    } finally {closing.current = false;}
  };
  useEffect(() => {ref.current?.showModal(); const handler=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();e.returnValue='';}}; window.addEventListener('beforeunload',handler); return()=>window.removeEventListener('beforeunload',handler);},[dirty]);
  return <ModalCloseContext.Provider value={()=>void close()}><dialog ref={ref} className={'modal '+(wide?'wide ':'')+(fullscreen?'fullscreen':'')} onCancel={e=>{e.preventDefault();void close();}}><div className="modal-head"><div><span className="eyebrow">交付工作台</span><h2>{title}</h2></div><button type="button" className="icon" aria-label="关闭弹窗" onClick={()=>void close()}><X size={22}/></button></div>{children}</dialog></ModalCloseContext.Provider>;
}
export function Empty({children}:{children:ReactNode}) {return <div className="empty"><FileText size={28}/><p>{children}</p></div>;}
export function Badge({value}:{value:string}) {return <span className={'badge '+({'已完成':'done','进行中':'active','暂停':'pause','已取消':'muted','已关闭':'done','高':'danger','处理中':'active'}[value]||'')}>{value}</span>;}
export function Section({id,title,titleActions,filters,actions,children,className=''}:{id?:string,title:string,titleActions?:ReactNode,filters?:ReactNode,actions?:ReactNode,children:ReactNode,className?:string}) {
  const heading=<h2 className="section-title" id={id? id+'-title':undefined}>{title}</h2>;
  return <section id={id} className={'panel '+className} aria-labelledby={id? id+'-title':undefined}>
    <div className={'section-head'+(filters?' has-filters':'')}>
      {titleActions?<div className="section-heading">{heading}{titleActions}</div>:heading}
      {filters}
      {actions&&<div className="actions">{actions}</div>}
    </div>
    {children}
  </section>;
}
export function Pagination({page,total,size=20,onPage}:{page:number,total:number,size?:number,onPage:(n:number)=>void}) {
  return <div className="pagination"><span>共 {total} 条 · 第 {page} / {Math.max(1,Math.ceil(total/size))} 页</span><div><button disabled={page<=1} onClick={()=>onPage(page-1)}>上一页</button><button disabled={page*size>=total} onClick={()=>onPage(page+1)}>下一页</button></div></div>;
}
export function RowMenu({children,label='更多操作'}:{children:ReactNode,label?:string}) {
  const ref=useRef<HTMLDetailsElement>(null);
  const [open,setOpen]=useState(false);
 const [above,setAbove]=useState(false);
  function close(restoreFocus=false) {
    const menu=ref.current;
    if(!menu?.open)return;
    menu.open=false;
    if(restoreFocus)menu.querySelector('summary')?.focus();
  }
  useEffect(()=>{
    if(!open)return;
    const outside=(event:Event)=>{
      if(event.target instanceof Node&&!ref.current?.contains(event.target))close();
    };
    const escape=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&ref.current?.open){event.preventDefault();event.stopPropagation();close(true);}
    };
    const scroll=(event:Event)=>{if(event.target instanceof Element&&event.target.classList.contains('table-body-scroll')&&event.target.contains(ref.current))close();};
    document.addEventListener('pointerdown',outside,true);
    document.addEventListener('focusin',outside,true);
    document.addEventListener('keydown',escape,true);
    document.addEventListener('scroll',scroll,true);
    return()=>{
      document.removeEventListener('pointerdown',outside,true);
      document.removeEventListener('focusin',outside,true);
      document.removeEventListener('keydown',escape,true);
      document.removeEventListener('scroll',scroll,true);
    };
  },[open]);
  return <details ref={ref} className={'row-menu'+(above?' row-menu-above':'')} onToggle={event=>{
    const menu=event.currentTarget;
    if(menu.open){
      const viewport=menu.closest('.table-body-scroll')?.getBoundingClientRect(),trigger=menu.getBoundingClientRect();
      const height=menu.querySelector('div')?.getBoundingClientRect().height||0;
      setAbove(!!viewport&&viewport.bottom-trigger.bottom<height+6&&trigger.top-viewport.top>viewport.bottom-trigger.bottom);
    }
    if(menu.open)document.querySelectorAll<HTMLDetailsElement>('details.row-menu[open]').forEach(other=>{if(other!==menu)other.open=false;});
    setOpen(menu.open);
  }}><summary aria-label={label}><Ellipsis size={18}/></summary><div onClick={event=>{
    const button=event.target instanceof Element?event.target.closest('button'):null;
    if(button&&!button.disabled)close(!!ref.current?.contains(document.activeElement));
  }}>{children}</div></details>;
}

type UploadItem={file:File,id?:string,attachment?:Row,error?:string,busy:boolean};
export function Uploader({pid,onUploaded,onStaged,onBusy,acceptance=false}:{pid?:string,acceptance?:boolean,onUploaded:(id:string)=>void,onStaged?:(id:string)=>void,onBusy?:(busy:boolean)=>void}) {
  const [items,setItems]=useState<UploadItem[]>([]), [drag,setDrag]=useState(false);
  const input=useRef<HTMLInputElement>(null);
  const {remember}=useAttachments();
  useEffect(()=>{onBusy?.(items.some(x=>x.busy));},[items]);
  async function send(item:UploadItem){
    setItems(old=>old.map(x=>x===item?{...x,busy:true,error:undefined}:x));
    const body=new FormData(); body.append('file',item.file);
    try {const params=new URLSearchParams();if(pid)params.set('project_id',pid);if(acceptance)params.set('is_acceptance','true');const result=await api<Row>('/attachments/upload?'+params,'POST',body);remember([result]);setItems(old=>old.map(x=>x.file===item.file?{...x,id:result.id,attachment:result,busy:false}:x));onUploaded(result.id);if(!pid)onStaged?.(result.id);}
    catch(e){setItems(old=>old.map(x=>x.file===item.file?{...x,error:(e as Error).message,busy:false}:x));}
  }
  function add(files:FileList|null){if(!files)return;const added=Array.from(files).map(file=>({file,busy:true}));setItems(old=>[...old,...added]);added.forEach(item=>void send(item));}
  return <div className="upload"><input ref={input} hidden type="file" accept={acceptance?'.png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.csv':undefined} multiple onChange={e=>{add(e.target.files);e.target.value='';}}/><button type="button" className={'dropzone '+(drag?'drag':'')} onClick={()=>input.current?.click()} onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);add(e.dataTransfer.files);}}><Upload size={21}/><strong>选择多个文件，或拖拽到这里</strong><span>每个文件独立上传，失败后可重试</span></button>{items.map((item,i)=><div className="upload-item" key={i}><span>{item.file.name}</span><small className={item.error?'error-text':''}>{item.busy?'上传中…':item.error||'上传成功'}</small>{item.attachment&&<AcceptanceToggle file={item.attachment}/>}
{item.error&&<button type="button" onClick={()=>void send(item)}><RefreshCw size={14}/>重试</button>}</div>)}</div>;
}
export type FieldDef={key:string,label:string,type?:string,required?:boolean,options?:{id:string,name:string,enabled?:boolean,team?:string}[],groupByTeam?:boolean,wide?:boolean,hint?:string,content?:ReactNode,disabled?:boolean,heightKey?:string,min?:number,max?:number};
export function Fields({fields,value,onChange,disabled=false}:{fields:FieldDef[],value:Row,onChange:(key:string,value:any)=>void,disabled?:boolean}) {
  return <div className="form-grid">{fields.map(field=>field.groupByTeam&&field.type==='multi'?<div key={field.key} className={'field '+(field.wide?'span-2':'')}><span>{field.label}{field.required&&<b> *</b>}</span><PeopleCheckboxes label={field.label} people={field.options||[]} value={value[field.key]||[]} onChange={ids=>onChange(field.key,ids)} disabled={disabled||field.disabled}/></div>:field.content?<div key={field.key} className={'field '+(field.wide?'span-2':'')}><span>{field.label}{field.required&&<b> *</b>}</span>{field.content}</div>:<label key={field.key} className={'field '+(field.wide?'span-2':'')}><span>{field.label}{field.required&&<b> *</b>}</span>{field.type==='textarea'?<TextareaField field={field} value={value} onChange={onChange} disabled={disabled||!!field.disabled}/>:field.type==='multi'?<div className="checks">{!field.options?.length&&<small>暂无可选资料</small>}{field.options?.map(opt=><label key={opt.id}><input disabled={disabled||field.disabled||opt.enabled===false&&!(value[field.key]||[]).includes(opt.id)} type="checkbox" checked={(value[field.key]||[]).includes(opt.id)} onChange={e=>onChange(field.key,e.target.checked?[...(value[field.key]||[]),opt.id]:(value[field.key]||[]).filter((x:string)=>x!==opt.id))}/><span>{opt.name}{opt.enabled===false?'（已停用）':''}</span></label>)}</div>:field.type==='select'?<select disabled={disabled||field.disabled} required={field.required} value={value[field.key]||''} onChange={e=>onChange(field.key,e.target.value||null)}><option value="">请选择</option>{field.groupByTeam?<PeopleOptions people={field.options||[]} value={value[field.key]} restrictDisabled/>:field.options?.map(opt=><option key={opt.id} value={opt.id} disabled={opt.enabled===false&&value[field.key]!==opt.id}>{opt.name}{opt.enabled===false?'（已停用）':''}</option>)}</select>:field.type==='checkbox'?<input disabled={disabled||field.disabled} type="checkbox" checked={value[field.key]??true} onChange={e=>onChange(field.key,e.target.checked)}/>:<input name={field.key} step={field.type==='money'?'0.01':field.type==='datetime-local'?1:undefined} min={field.min??(field.type==='money'?'0':undefined)} max={field.max??(field.type==='money'?'99999999999999.99':undefined)} inputMode={field.type==='money'?'decimal':undefined} onInput={e=>{if(field.type==='date'||field.type==='datetime-local')onChange(field.key,e.currentTarget.value||null);}} disabled={disabled||field.disabled} type={field.type==='money'?'number':field.type||'text'} required={field.required} value={value[field.key]??''} onChange={e=>onChange(field.key,field.type==='number'?Number(e.target.value):field.type==='date'?e.target.value||null:e.target.value)}/>} {field.hint&&<small>{field.hint}</small>}</label>)}</div>;
}


function TextareaField({field,value,onChange,disabled}:{field:FieldDef,value:Row,onChange:(key:string,value:any)=>void,disabled:boolean}) {
  const ref=useRef<HTMLTextAreaElement>(null), change=useRef(onChange);
  change.current=onChange;
  const heightKey=field.heightKey;
  useEffect(()=>{
    const textarea=ref.current;
    if(!textarea||!heightKey||disabled)return;
    // Ignore the initial observation: opening an unchanged record must stay clean.
    let previous:number|undefined;
    const observer=new ResizeObserver(()=>{
      const height=Math.round(textarea.getBoundingClientRect().height);
      if(height<80)return;
      if(previous!==undefined&&height!==previous)change.current(heightKey,height);
      previous=height;
    });
    observer.observe(textarea);
    return()=>observer.disconnect();
  },[heightKey,disabled]);
  return <textarea ref={ref} name={field.key} disabled={disabled} rows={field.wide?3:2} required={field.required}
    className={heightKey?'remember-textarea-height':undefined} style={heightKey&&value[heightKey]?{height:value[heightKey]}:undefined}
    value={value[field.key]||''} onChange={e=>onChange(field.key,e.target.value)}/>;
}
