// Pure geometry keeps equal x values aligned across series and on narrow screens.
export function chartLayout(type,data,width=600){
  width=Math.max(160,Math.min(1200,Math.round(width)||600));
  const height=250,left=52,right=width-18,top=36,bottom=204;
  const series=[...new Set(data.map(d=>d.series||''))],domain=[...new Set(data.map(d=>d.x))];
  const numeric=['ScatterChart','Plot'].includes(type)&&data.every(d=>typeof d.x==='number');
  const xmin=numeric?Math.min(...domain):0,xmax=numeric?Math.max(...domain):1;
  const values=data.map(d=>d.y),min=Math.min(0,...values),max=Math.max(1,...values);
  const scale=Math.max(Math.abs(min),Math.abs(max),1),xscale=Math.max(Math.abs(xmin),Math.abs(xmax),1);
  const groupWidth=(right-left)/Math.max(1,domain.length);
  const x=value=>numeric?left+(xmax===xmin?.5:(value/xscale-xmin/xscale)/(xmax/xscale-xmin/xscale))*(right-left):left+(domain.indexOf(value)+.5)*groupWidth;
  const y=value=>bottom-(value/scale-min/scale)/(max/scale-min/scale||1)*(bottom-top);
  const barWidth=Math.min(40,groupWidth*.8/Math.max(1,series.length));
  const barX=d=>x(d.x)+(series.indexOf(d.series||'')-(series.length-1)/2)*barWidth;
  return {width,height,left,right,top,bottom,series,domain,min,max,x,y,barX,barWidth};
}
