// Native SVG only. All coordinates, colours and layout originate in this module.
import {el,button,dataTable,string} from './dom.js';
import {chartLayout} from './chart-layout.js';
import {samplePlot} from './plot.js';
const palette=Array.from({length:6},(_,i)=>'var(--gu-chart-'+i+')');
const ns='http://www.w3.org/2000/svg';
function svgEl(tag,attrs={},text){const node=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=String(text);return node;}
export function chart(type,props,{view={},changed=()=>{},width=600}={}){
  if(type==='Plot')props={...props,data:samplePlot(props)};
  const root=el('section','gu-chart'),toolbar=el('div','gu-chart-tools'),title=el('strong','',props.label||'数据图表'),slot=el('div');let tableMode=!!view.table,frame=0;
  const toggle=button(tableMode?'查看图表':'查看数据',()=>{tableMode=!tableMode;view.table=tableMode;paint();changed();});toolbar.append(title,toggle);root.append(toolbar,slot);
  function paint(){
    toggle.textContent=tableMode?'查看图表':'查看数据';toggle.setAttribute('aria-pressed',String(tableMode));slot.replaceChildren();const data=props.data;
    if(!data?.length){slot.append(el('p','gu-muted','暂无数据'));return;}
    if(tableMode){view.tableView??={};slot.append(dataTable({label:props.label||'图表数据',columns:[{key:'x',label:props.xLabel||'项目'},{key:'y',label:props.yLabel||'数值',unit:props.unit},{key:'series',label:'分组'}],rows:data},{view:view.tableView,changed}));return;}
    if(type==='PieChart'&&data.some(d=>d.y<0)){slot.append(el('p','gu-error','占比图不支持负数，请切换数据视图。'));return;}
    const g=chartLayout(type,data,width),svg=svgEl('svg',{viewBox:`0 0 ${g.width} ${g.height}`,role:'img','aria-label':(props.label||'数据图表')+'，可用“查看数据”访问完整数值'});svg.append(svgEl('title',{},props.label||'数据图表'));slot.append(svg);
    const values=data.map(d=>d.y),{min,max}=g,sy=g.y;
    if(type==='PieChart'){
      const scale=Math.max(1,...values),sum=values.reduce((a,b)=>a+b/scale,0);if(sum===0){slot.replaceChildren(el('p','gu-muted','合计为 0，暂无占比。'));return;}
      let angle=-Math.PI/2;const cx=g.width/2,cy=122,radius=Math.min(100,g.width/2-16);data.forEach((item,index)=>{if(!item.y)return;const end=angle+(item.y/scale)/sum*Math.PI*2,color=palette[index%palette.length];let path;
        if(item.y/scale===sum)path=svgEl('circle',{cx,cy,r:radius,fill:color});else path=svgEl('path',{d:`M${cx} ${cy} L${cx+radius*Math.cos(angle)} ${cy+radius*Math.sin(angle)} A${radius} ${radius} 0 ${end-angle>Math.PI?1:0} 1 ${cx+radius*Math.cos(end)} ${cy+radius*Math.sin(end)} Z`,fill:color,stroke:'var(--gu-bg)','stroke-width':2});
        path.append(svgEl('title',{},`${string(item.label||item.x)}：${item.y}${props.unit||''} (${Math.round((item.y/scale)/sum*100)}%)`));svg.append(path);angle=end;
      });
    }else{
      for(let n=0;n<=4;n++){const v=min*(1-n/4)+max*n/4,y=sy(v);svg.append(svgEl('line',{x1:g.left,x2:g.right,y1:y,y2:y,class:'gu-chart-grid'}),svgEl('text',{x:g.left-8,y:y+4,'text-anchor':'end',class:'gu-chart-axis'},Number(v.toPrecision(3))));}
      const axisText=(text,attrs)=>{const limit=Math.max(6,Math.floor((g.width-60)/12)),node=svgEl('text',{...attrs,class:'gu-chart-axis'},text.length>limit?text.slice(0,limit-1)+'…':text);node.append(svgEl('title',{},text));return node;};
      svg.append(axisText((props.yLabel||'数值')+(props.unit?' / '+props.unit:''),{x:g.left,y:20}),axisText(props.xLabel||'项目',{x:g.right,y:g.height-4,'text-anchor':'end'}));
      const sx=d=>g.x(d.x),series=g.series;
      if(['LineChart','Plot'].includes(type))for(const name of series){const points=data.map((d,index)=>({d,index})).filter(({d})=>(d.series||'')===name).sort((a,b)=>sx(a.d)-sx(b.d)).map(({d,index})=>sx(d,index)+','+sy(d.y)).join(' ');svg.append(svgEl('polyline',{points,fill:'none',stroke:palette[series.indexOf(name)%palette.length],'stroke-width':2.5}));}
      data.forEach((d,index)=>{const x=type==='BarChart'?g.barX(d):sx(d),y=sy(d.y),color=palette[series.indexOf(d.series||'')%palette.length];const mark=type==='BarChart'?svgEl('rect',{x:x-g.barWidth/2,y:Math.min(y,sy(0)),width:g.barWidth,height:Math.max(1,Math.abs(y-sy(0))),rx:2,fill:color}):svgEl('circle',{cx:x,cy:y,r:type==='ScatterChart'?4.5:3.5,fill:color});mark.append(svgEl('title',{},`${string(d.x)}：${d.y}${props.unit||''}${d.series?' · '+d.series:''}`));svg.append(mark);
        if(type==='Plot')mark.remove();

      });
      const step=Math.max(1,Math.ceil(g.domain.length/Math.max(2,Math.floor((g.right-g.left)/70))));
      g.domain.forEach((value,index)=>{if(index%step===0){const text=string(value),tick=svgEl('text',{x:g.x(value),y:g.bottom+20,'text-anchor':'middle',class:'gu-chart-axis'},text.length>5?text.slice(0,4)+'…':text);tick.append(svgEl('title',{},text));svg.append(tick);}});
    }
    const legend=el('ul','gu-legend');const entries=type==='PieChart'?data.map(d=>({label:string(d.label||d.x),value:d.y})): [...new Set(data.map(d=>d.series||''))].map(label=>({label:label||props.yLabel||'数值'}));
    for(const [index,item]of entries.slice(0,12).entries()){const li=el('li','gu-series-'+index%palette.length);li.append(el('span','gu-swatch'),document.createTextNode(item.label+(item.value!==undefined?' · '+item.value+(props.unit||''):'')));legend.append(li);}slot.append(legend);
    if(data.length>12&&type==='PieChart')slot.append(el('p','gu-muted','完整分类可在数据视图查看。'));
  }
  const observer=new ResizeObserver(entries=>{const next=Math.round(entries[0].contentRect.width);if(next>0&&next!==width){width=next;cancelAnimationFrame(frame);frame=requestAnimationFrame(paint);}});observer.observe(root);
  root.dispose=()=>{observer.disconnect();cancelAnimationFrame(frame);};paint();return root;
}
