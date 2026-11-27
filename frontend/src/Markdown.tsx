import {memo, useEffect, useId, useRef, useState, type RefObject, type TextareaHTMLAttributes} from 'react';
import {createPortal} from 'react-dom';
import ReactMarkdown, {defaultUrlTransform} from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import {Bold, Italic, Heading, List, ListOrdered, ListChecks, Link, Code, Quote, Table, Maximize2, Minimize2} from 'lucide-react';

export const markdownFields = new Set(['work_content','extra_time_notes','scope','exclusions','deliverables','acceptance','notes','planned_deliverable','actual_deliverable','content','details','next_plan','requirement','solution','development_notes','config_info','original','change_reason','impact','description','response','summary','reason']);

export function safeMarkdownUrl(url:string) {
  const safe=defaultUrlTransform(url);
  return /^(?:https?:|mailto:)/i.test(safe)||!/^\s*(?:[a-z][a-z\d+.-]*:|\\)/i.test(safe)?safe:'';
}

/** Raw HTML is displayed as text. No HTML injection or executable URL schemes. */
export const MarkdownContent=memo(function MarkdownContent({text,className='',onOpen}:{text?:string|null,className?:string,onOpen?:()=>void}) {
  const prefix=useId().replace(/:/g,'')+'-';
  return <div className={'markdown-content '+className+(onOpen?' markdown-clickable':'')} onClick={onOpen?event=>{if(!(event.target instanceof Element&&event.target.closest('a')))onOpen();}:undefined}>
    <ReactMarkdown remarkPlugins={[remarkGfm,remarkBreaks]} remarkRehypeOptions={{clobberPrefix:prefix}} urlTransform={safeMarkdownUrl} components={{
      a:({node,...props})=>props.href?<a {...props} target={props.href.startsWith('#')?undefined:'_blank'} rel="noopener noreferrer"/>:<span>{props.children}</span>,
      img:({node,...props})=>props.src?<img {...props} loading="lazy" referrerPolicy="no-referrer"/>:<span>{props.alt}</span>,
      table:({node,...props})=><div className="markdown-table-scroll"><table {...props}/></div>,
    }}>{text||'—'}</ReactMarkdown>
  </div>;
});

export function focusMarkdownInput(input:HTMLElement|null|undefined) {
  input?.dispatchEvent(new Event('markdown-edit',{bubbles:true}));
  requestAnimationFrame(()=>input?.focus());
}

function MarkdownFullscreen({label,value,onChange,disabled,initialPreview,maxLength,onClose}:{label:string;value:string;onChange:(value:string)=>void;disabled:boolean;initialPreview:boolean;maxLength?:number;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null),id=useId();
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return()=>element?.close();
  },[]);
  // Share the form's value; only the fullscreen editor's view and size are local.
  return createPortal(<dialog ref={dialog} className="markdown-fullscreen" aria-labelledby={id+'-title'}
    onCancel={event=>{event.preventDefault();event.stopPropagation();onClose();}}>
    <header className="markdown-fullscreen-head">
      <h2 id={id+'-title'}>{label} <span>{disabled?'全屏阅读':'全屏编辑'}</span></h2>
      <button type="button" autoFocus title="退出全屏（Esc）" aria-label="退出全屏" onClick={onClose}><Minimize2 size={18}/><span>退出全屏</span></button>
    </header>
    <div className="markdown-fullscreen-editor">
      <MarkdownEditor label={label} value={value} onChange={onChange} disabled={disabled} maxLength={maxLength}
        initialPreview={initialPreview} allowFullscreen={false}/>
    </div>
  </dialog>,document.body);
}

type Props=Omit<TextareaHTMLAttributes<HTMLTextAreaElement>,'value'|'onChange'|'onInput'|'ref'> & {
  label:string;value:string;onChange:(value:string)=>void;textareaRef?:RefObject<HTMLTextAreaElement|null>;
  height?:number;onHeightChange?:(height:number)=>void;
  initialPreview?:boolean;allowFullscreen?:boolean;
};

export function MarkdownEditor({label,value,onChange,textareaRef,height,onHeightChange,disabled,rows=3,className='',initialPreview,allowFullscreen=true,...props}:Props) {
  const ownRef=useRef<HTMLTextAreaElement>(null),ref=textareaRef||ownRef,wrapper=useRef<HTMLDivElement>(null);
  const locked=!!(disabled||props.readOnly);
  const [preview,setPreview]=useState(initialPreview??locked),[help,setHelp]=useState(false),id=useId();
  const [fullscreen,setFullscreen]=useState(false),fullscreenTrigger=useRef<HTMLButtonElement>(null);
  const heightChange=useRef(onHeightChange);heightChange.current=onHeightChange;
  useEffect(()=>{
    const el=wrapper.current;
    const edit=()=>{if(!locked)setPreview(false);};
    el?.addEventListener('markdown-edit',edit);
    return()=>el?.removeEventListener('markdown-edit',edit);
  },[locked]);
  useEffect(()=>{
    const textarea=ref.current;if(!textarea||locked||!onHeightChange)return;
    let previous:number|undefined;
    const observer=new ResizeObserver(()=>{
      const current=Math.round(textarea.getBoundingClientRect().height);
      if(current<80)return;
      textarea.dataset.markdownHeight=String(current);
      if(previous!==undefined&&current!==previous)heightChange.current?.(current);
      previous=current;
    });
    observer.observe(textarea);return()=>observer.disconnect();
  },[locked,!!onHeightChange]);
  function insert(before:string,after='',placeholder='文字',line=false) {
    const el=ref.current;if(!el||locked)return;
    const start=el.selectionStart,end=el.selectionEnd,selection=value.slice(start,end)||placeholder;
    const prefix=line&&start>0&&value[start-1]!=='\n'?'\n':'';
    onChange(value.slice(0,start)+prefix+before+selection+after+value.slice(end));
    setPreview(false);
    requestAnimationFrame(()=>{el.focus();el.setSelectionRange(start+prefix.length+before.length,start+prefix.length+before.length+selection.length);});
  }
  const formats=[
    {title:'加粗',icon:Bold,run:()=>insert('**','**')},{title:'斜体',icon:Italic,run:()=>insert('*','*')},
    {title:'标题',icon:Heading,run:()=>insert('## ','','标题',true)},{title:'无序列表',icon:List,run:()=>insert('- ','','列表项',true)},
    {title:'有序列表',icon:ListOrdered,run:()=>insert('1. ','','列表项',true)},{title:'任务清单',icon:ListChecks,run:()=>insert('- [ ] ','','待办事项',true)},
    {title:'链接',icon:Link,run:()=>insert('[','](https://example.com)','链接文字')},{title:'代码块',icon:Code,run:()=>insert('```\n','\n```','代码',true)},
    {title:'引用',icon:Quote,run:()=>insert('> ','','引用内容',true)},
    {title:'表格',icon:Table,run:()=>insert('| 列一 | 列二 |\n| --- | --- |\n| ',' | 内容 |\n','内容',true)},
  ];
  return <div ref={wrapper} className={'markdown-editor'+(locked?' markdown-readonly':'')} role="group" aria-label={label+' Markdown 编辑器'}>
    <div className="markdown-toolbar">
      <div className="markdown-modes"><button type="button" aria-pressed={!preview} onClick={()=>setPreview(false)}>{locked?'原文':'编辑'}</button><button type="button" aria-pressed={preview} onClick={()=>setPreview(true)}>预览</button>{allowFullscreen&&<button ref={fullscreenTrigger} type="button" title={locked?'全屏阅读':'全屏编辑 / 预览'} aria-label={locked?'全屏阅读':'全屏编辑'} aria-haspopup="dialog" onClick={()=>setFullscreen(true)}><Maximize2 size={15}/></button>}</div>
      {!locked&&<div className="markdown-formats">{formats.map(item=><button key={item.title} type="button" title={item.title} aria-label={item.title} disabled={preview} onMouseDown={e=>e.preventDefault()} onClick={item.run}><item.icon size={14}/></button>)}</div>}
      <button type="button" className="markdown-help-toggle" aria-expanded={help} aria-controls={id+'-help'} onClick={()=>setHelp(!help)}>Markdown</button>
    </div>
    {help&&<div id={id+'-help'} className="markdown-help">支持标题、**加粗**、*斜体*、~~删除线~~、列表、任务清单、引用、链接、图片、代码块和表格。普通换行会保留。图片语法：![说明](图片地址)；Word/PDF 中保留图片说明及链接。</div>}
    <textarea {...props} ref={ref} aria-label={label} data-field-label={label} value={value} onChange={e=>onChange(e.target.value)} disabled={disabled} rows={rows}
      hidden={preview} className={className} style={{...props.style,...(height?{height}: {})}} onKeyDown={e=>{props.onKeyDown?.(e);if(!locked&&(e.ctrlKey||e.metaKey)&&['b','i'].includes(e.key.toLowerCase())){e.preventDefault();const marker=e.key.toLowerCase()==='b'?'**':'*';insert(marker,marker);}}}/>
    {preview&&<div className="markdown-preview" role="region" aria-label={label+'预览'} style={height?{minHeight:height}:undefined}>{value.trim()?<MarkdownContent text={value}/>:<span className="muted">暂无内容</span>}</div>}
    {fullscreen&&<MarkdownFullscreen label={label} value={value} onChange={onChange} disabled={locked} initialPreview={locked||preview} maxLength={props.maxLength}
      onClose={()=>{setFullscreen(false);requestAnimationFrame(()=>fullscreenTrigger.current?.focus({preventScroll:true}));}}/>}
  </div>;
}
