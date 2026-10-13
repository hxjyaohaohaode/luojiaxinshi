// Native SVG only. All coordinates, colours and layout originate in this module.
import {el,button,dataTable,string} from './dom.js';
const palette=['#0072b2','#d55e00','#009e73','#aa4499','#b8860b','#595959'];
const ns='http://www.w3.org/2000/svg';
function svgEl(tag,attrs={},text){const node=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=String(text);return node;}
export function chart(type,props,{view={},changed=()=>{}}={}){
  const root=el('section','gu-chart'),toolbar=el('div','gu-chart-tools'),title=el('strong','',props.label||'数据图表'),slot=el('div');let tableMode=!!view.table;
  const toggle=button(tableMode?'查看图表':'查看数据',()=>{tableMode=!tableMode;view.table=tableMode;paint();changed();});toolbar.append(title,toggle);root.append(toolbar,slot);
  function paint(){
    toggle.textContent=tableMode?'查看图表':'查看数据';toggle.setAttribute('aria-pressed',String(tableMode));slot.replaceChildren();const data=props.data;
    if(!data?.length){slot.append(el('p','gu-muted','暂无数据'));return;}
    if(tableMode){view.tableView??={};slot.append(dataTable({label:props.label||'图表数据',columns:[{key:'x',label:props.xLabel||'项目'},{key:'y',label:props.yLabel||'数值',unit:props.unit},{key:'series',label:'分组'}],rows:data},{view:view.tableView,changed}));return;}
    if(type==='PieChart'&&data.some(d=>d.y<0)){slot.append(el('p','gu-error','占比图不支持负数，请切换数据视图。'));return;}
    const svg=svgEl('svg',{viewBox:'0 0 600 320',role:'img','aria-label':(props.label||'数据图表')+'，可用“查看数据”访问完整数值'});svg.append(svgEl('title',{},props.label||'数据图表'));slot.append(svg);
    const values=data.map(d=>d.y),min=Math.min(0,...values),max=Math.max(1,...values),range=max-min||1;const sy=value=>254-(value-min)/range*216;
    if(type==='PieChart'){
      const sum=values.reduce((a,b)=>a+b,0);if(sum===0){slot.replaceChildren(el('p','gu-muted','合计为 0，暂无占比。'));return;}
      let angle=-Math.PI/2;data.forEach((item,index)=>{if(!item.y)return;const end=angle+item.y/sum*Math.PI*2,color=palette[index%palette.length];let path;
        if(item.y===sum)path=svgEl('circle',{cx:210,cy:145,r:106,fill:color});else path=svgEl('path',{d:`M210 145 L${210+106*Math.cos(angle)} ${145+106*Math.sin(angle)} A106 106 0 ${end-angle>Math.PI?1:0} 1 ${210+106*Math.cos(end)} ${145+106*Math.sin(end)} Z`,fill:color,stroke:'white','stroke-width':2});
        path.append(svgEl('title',{},`${string(item.label||item.x)}：${item.y}${props.unit||''} (${Math.round(item.y/sum*100)}%)`));svg.append(path);angle=end;
      });
    }else{
      for(let n=0;n<=4;n++){const v=min+range*n/4,y=sy(v);svg.append(svgEl('line',{x1:60,x2:564,y1:y,y2:y,class:'gu-chart-grid'}),svgEl('text',{x:52,y:y+4,'text-anchor':'end',class:'gu-chart-axis'},Number(v.toFixed(2))));}
      svg.append(svgEl('text',{x:60,y:20,class:'gu-chart-axis'},(props.yLabel||'数值')+(props.unit?' / '+props.unit:'')),svgEl('text',{x:564,y:306,'text-anchor':'end',class:'gu-chart-axis'},props.xLabel||'项目'));
      const numeric=type==='ScatterChart'&&data.every(d=>typeof d.x==='number'),xmin=numeric?Math.min(...data.map(d=>d.x)):0,xmax=numeric?Math.max(...data.map(d=>d.x)):1;
      const sx=(d,index)=>numeric?70+(d.x-xmin)/(xmax-xmin||1)*480:60+(index+.5)/data.length*504;
      const series=[...new Set(data.map(d=>d.series||''))];
      if(type==='LineChart')for(const name of series){const points=data.map((d,index)=>({d,index})).filter(({d})=>(d.series||'')===name).map(({d,index})=>sx(d,index)+','+sy(d.y)).join(' ');svg.append(svgEl('polyline',{points,fill:'none',stroke:palette[series.indexOf(name)%palette.length],'stroke-width':2.5}));}
      data.forEach((d,index)=>{const x=sx(d,index),y=sy(d.y),color=palette[series.indexOf(d.series||'')%palette.length];const mark=type==='BarChart'?svgEl('rect',{x:x-Math.min(40,400/data.length)/2,y:Math.min(y,sy(0)),width:Math.min(40,400/data.length),height:Math.max(1,Math.abs(y-sy(0))),rx:2,fill:color}):svgEl('circle',{cx:x,cy:y,r:type==='ScatterChart'?4.5:3.5,fill:color});mark.append(svgEl('title',{},`${string(d.x)}：${d.y}${props.unit||''}${d.series?' · '+d.series:''}`));svg.append(mark);
        if(index%Math.max(1,Math.ceil(data.length/6))===0)svg.append(svgEl('text',{x,y:276,'text-anchor':'middle',class:'gu-chart-axis'},string(d.x).slice(0,12)));
      });
    }
    const legend=el('ul','gu-legend');const entries=type==='PieChart'?data.map(d=>({label:string(d.label||d.x),value:d.y})): [...new Set(data.map(d=>d.series||''))].map(label=>({label:label||props.yLabel||'数值'}));
    for(const [index,item]of entries.slice(0,12).entries()){const li=el('li','gu-series-'+index%palette.length);li.append(el('span','gu-swatch'),document.createTextNode(item.label+(item.value!==undefined?' · '+item.value+(props.unit||''):'')));legend.append(li);}slot.append(legend);
    if(data.length>12&&type==='PieChart')slot.append(el('p','gu-muted','完整分类可在数据视图查看。'));
  }
  paint();return root;
}
