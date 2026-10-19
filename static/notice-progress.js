const labels={extracting:'正在结合原文整理',receiving:'正在接收整理结果',verifying:'正在校验结构与原文依据',reviewing:'正在复核动作与原文是否一致'};

export function noticeProgressPanel(n,{esc,brandMotion,button}){
  const title=labels[n.execution?.stage]||labels.extracting;
  return `<div class="panel busy-panel" data-notice-progress="${esc(n.id)}" role="status" aria-live="polite">${brandMotion('routing','',{priority:3})}<h3 data-notice-phase>${title}</h3><p>材料已保存。接收和复核结束后会自动显示草稿及核对意见，请逐项确认。</p><p class="footnote" data-notice-elapsed>正在处理，离开页面后可返回查看。</p>${button('刷新状态','refresh-notice','small')}</div>`;
}

export function createNoticeProgress({state,api,refresh,root=document,schedule=setTimeout,unschedule=clearTimeout}){
  let timer=null,serial=0;
  function stop(){serial++;if(timer!==null)unschedule(timer);timer=null;}
  function watch(n,{pending=false}={}){
    stop();if(n.status!=='processing'&&!pending)return;
    const revision=serial,route=state.renderId,user=state.session?.user?.id;
    let observed=!pending,failures=0;
    const current=()=>serial===revision&&state.renderId===route&&state.session?.user?.id===user&&!!root.querySelector('[data-notice-progress]');
    async function poll(){
      timer=null;if(!current())return;
      if(root.hidden){timer=schedule(poll,4000);return;}
      try{
        const result=await api(`/notices/${encodeURIComponent(n.id)}/processing`);
        if(!current())return;
        failures=0;
        if(result.status==='processing')observed=true;
        else if(observed){stop();await refresh();return;}
        const panel=root.querySelector('[data-notice-progress]');
        panel.querySelector('[data-notice-phase]').textContent=labels[result.execution?.stage]||labels.extracting;
        const seconds=result.elapsed_seconds;
        panel.querySelector('[data-notice-elapsed]').textContent=Number.isFinite(seconds)?`已处理 ${Math.max(0,Math.floor(seconds))} 秒。离开页面后可返回查看。`:'正在处理，离开页面后可返回查看。';
      }catch{
        if(!current())return;
        failures++;
        root.querySelector('[data-notice-elapsed]').textContent='状态暂时无法更新，已保存材料。可以手动刷新；不会自动重新调用模型。';
      }
      if(current())timer=schedule(poll,Math.min(15000,3000*(failures+1)));
    }
    timer=schedule(poll,1500);
  }
  return {watch,stop};
}

export function metricLines(metrics={}){
  const seconds=value=>Number.isFinite(value)&&value>=0?`${value.toFixed(1)} 秒`:null;
  const result=[];
  if(seconds(metrics.first_answer_seconds))result.push(`首段结果等待 ${seconds(metrics.first_answer_seconds)}`);
  if(seconds(metrics.provider_seconds))result.push(`模型请求 ${seconds(metrics.provider_seconds)}`);
  if(seconds(metrics.validation_seconds))result.push(`本地校验 ${seconds(metrics.validation_seconds)}`);
  if(Number.isInteger(metrics.input_tokens)&&Number.isInteger(metrics.output_tokens))result.push(`${metrics.usage_complete===false?'已返回用量 · ':''}输入 ${metrics.input_tokens.toLocaleString()} / 输出 ${metrics.output_tokens.toLocaleString()} tokens`);
  if(Number.isInteger(metrics.call_count))result.push(`本次已发起 ${metrics.call_count} 次模型请求${metrics.usage_complete===false?'，部分用量尚未返回':''}`);
  return result;
}
