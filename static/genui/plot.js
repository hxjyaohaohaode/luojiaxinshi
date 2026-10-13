// Deterministic bounded sampling. Model expressions never execute as JavaScript.
import {evaluateExpression} from './expression.js';
import {CATALOG} from './catalog.js';
import {safeKey} from './security.js';
export function samplePlot(props){
  const {expression,parameters={},xMin,xMax,samples=81}=props;
  if(!Number.isFinite(xMin)||!Number.isFinite(xMax)||xMin>=xMax||Math.max(Math.abs(xMin),Math.abs(xMax))>1000000)throw Error('invalid_plot_domain');
  if(!Number.isInteger(samples)||samples<10||samples>120)throw Error('plot_sample_limit');
  const entries=Object.entries(parameters);
  if(entries.length>12||entries.some(([key,value])=>key==='x'||!safeKey(key)||typeof value!=='number'||!Number.isFinite(value)))throw Error('invalid_plot_parameter');
  const state=Object.assign(Object.create(null),parameters),limits={...CATALOG.limits,expressionSteps:Math.min(200,CATALOG.limits.expressionSteps)};
  return Array.from({length:samples},(_,index)=>{
    const x=xMin+(xMax-xMin)*index/(samples-1);state.x=x;
    const y=evaluateExpression(expression,state,limits);
    if(typeof y!=='number'||!Number.isFinite(y)||Math.abs(y)>1e12)throw Error('invalid_plot_value');
    return {x:Number(x.toPrecision(8)),y};
  });
}
