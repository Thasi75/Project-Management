import {Children,cloneElement,isValidElement,useLayoutEffect,useRef,useState,type ComponentPropsWithRef,type ReactElement} from 'react';

type TableElement=ReactElement<ComponentPropsWithRef<'table'>>;

/** Keep native table sizing and semantics while the scrollbar starts below the visible header. */
export default function TableViewport({children}:{children:TableElement}) {
 const table=useRef<HTMLTableElement>(null),body=useRef<HTMLDivElement>(null),header=useRef<HTMLDivElement>(null);
 const [layout,setLayout]=useState({width:0,height:0,viewport:0,columns:[] as number[]});
 const heading=Children.toArray(children.props.children).find(child=>isValidElement(child)&&child.type==='thead');
 useLayoutEffect(()=>{
  const element=table.current,scroll=body.current;
  if(!element||!scroll)return;
  function measure(){
   if(!element||!scroll||!element.offsetWidth)return;
   const head=element.tHead;
   if(!head)return;
   const next={width:element.getBoundingClientRect().width,height:head.getBoundingClientRect().height,
    viewport:scroll.clientWidth,columns:Array.from(head.rows[0].cells).map(cell=>cell.getBoundingClientRect().width)};
   setLayout(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);
  }
  measure();
  const observer=new ResizeObserver(measure);
  observer.observe(element);observer.observe(scroll);
  if(element.tHead)observer.observe(element.tHead);
  return()=>observer.disconnect();
 },[children]);
 useLayoutEffect(()=>{if(header.current&&body.current)header.current.scrollLeft=body.current.scrollLeft;},[layout]);
 return <div className="table-viewport">
  <div className="table-fixed-head" aria-hidden="true">
   <div ref={header} className="table-head-clip" style={{width:layout.viewport||'100%'}}>
    <table className={children.props.className} style={{width:layout.width||'100%',tableLayout:'fixed'}}>
     <colgroup>{layout.columns.map((width,index)=><col key={index} style={{width}}/>)}</colgroup>{heading}
    </table>
   </div>
  </div>
  <div ref={body} className="table-scroll table-body-scroll" tabIndex={0} aria-label="列表数据滚动区域"
   onScroll={event=>{if(header.current)header.current.scrollLeft=event.currentTarget.scrollLeft;}}>
   {cloneElement(children,{ref:table,style:{...children.props.style,marginTop:-layout.height}})}
  </div>
 </div>;
}
