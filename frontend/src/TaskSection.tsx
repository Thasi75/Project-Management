import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Maximize, Minimize} from 'lucide-react';
import {Section} from './components';

export default function TaskSection({projectId,active,filters,actions,children}:{
  projectId:string; active:boolean; filters:ReactNode; actions:ReactNode; children:ReactNode;
}) {
  const [fullscreen,setFullscreen]=useState(false);
  const expanded=useRef(false);
  const ownsNativeFullscreen=useRef(false);
  const request=useRef(0);
  const button=useRef<HTMLButtonElement>(null);

  function restoreFocus() {
    if(!document.querySelector('dialog[open]'))button.current?.focus({preventScroll:true});
  }

  function leave(restore=true) {
    request.current++;
    expanded.current=false;
    setFullscreen(false);
    if(ownsNativeFullscreen.current&&document.fullscreenElement===document.documentElement) {
      void document.exitFullscreen().catch(()=>{});
    }
    ownsNativeFullscreen.current=false;
    if(restore)restoreFocus();
  }

  async function toggle() {
    if(expanded.current){leave();return;}
    const current=++request.current;
    expanded.current=true;
    setFullscreen(true);
    // Fullscreen the app root so task editors and system dialogs remain usable.
    // The fixed panel also works when native fullscreen is unavailable or denied.
    if(document.fullscreenEnabled&&!document.fullscreenElement) {
      ownsNativeFullscreen.current=true;
      try {
        await document.documentElement.requestFullscreen();
        if(request.current!==current&&document.fullscreenElement===document.documentElement) {
          await document.exitFullscreen();
        }
      } catch {
        ownsNativeFullscreen.current=false;
      }
    }
  }

  useEffect(()=>{
    function nativeChange() {
      if(ownsNativeFullscreen.current&&!document.fullscreenElement) {
        ownsNativeFullscreen.current=false;
        expanded.current=false;
        setFullscreen(false);
        restoreFocus();
      }
    }
    function escape(event:KeyboardEvent) {
      if(event.key==='Escape'&&expanded.current&&!document.querySelector('dialog[open]')) {
        event.preventDefault();
        leave();
      }
    }
    document.addEventListener('fullscreenchange',nativeChange);
    document.addEventListener('keydown',escape);
    return()=>{
      document.removeEventListener('fullscreenchange',nativeChange);
      document.removeEventListener('keydown',escape);
    };
  },[]);
  useEffect(()=>()=>leave(false),[projectId,active]);

  return <Section id="section-tasks" title="任务计划" className={fullscreen?'task-fullscreen':''}
    titleActions={<button ref={button} type="button" className="icon task-fullscreen-toggle"
      aria-label={fullscreen?'退出任务计划全屏':'全屏显示任务计划'} title={fullscreen?'退出全屏（Esc）':'全屏显示'}
      aria-pressed={fullscreen} onClick={()=>void toggle()}>
      {fullscreen?<Minimize size={17}/>:<Maximize size={17}/>}
    </button>} filters={filters} actions={actions}>{children}</Section>;
}
