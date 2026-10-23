const labels={extracting:'正在读通知、整理要点',receiving:'正在接收整理结果',verifying:'正在对照原文核对',reviewing:'正在让 AI 自查一遍'};

export function processingStages(stage){
  return [['extracting','整理通知'],['receiving','接收结果'],['verifying','对照原文'],['reviewing','AI 自查']]
    .map(([key,label],index)=>`<li${key===stage?' aria-current="step"':''}><span aria-hidden="true">${index+1}</span><strong>${label}</strong>${key===stage?'<span class="sr-only">当前阶段</span>':''}</li>`).join('');
}

export function noticeProgressPanel(n,{esc,brandMotion,button}){
  const title=labels[n.execution?.stage]||'正在准备处理';
  return `<div class="panel busy-panel" data-notice-progress="${esc(n.id)}" role="status" aria-live="polite">${brandMotion('routing','',{priority:3})}<h3 data-notice-phase>${title}</h3><p>材料已经存好了。整理完会自动显示草稿和 AI 的意见，到时逐项看看就行。</p><ol class="processing-stages" data-processing-stages aria-label="整理进度">${processingStages(n.execution?.stage)}</ol><p class="footnote" data-notice-elapsed>正在处理，可以先去忙别的，回来再看。</p>${button('刷新看看','refresh-notice','small')}</div>`;
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
        panel.querySelector('[data-notice-phase]').textContent=labels[result.execution?.stage]||'正在准备处理';
        const stages=panel.querySelector('[data-processing-stages]');
        const steps=processingStages(result.execution?.stage);
        if(stages&&stages.innerHTML!==steps)stages.innerHTML=steps;
        const seconds=result.elapsed_seconds;
        panel.querySelector('[data-notice-elapsed]').textContent=Number.isFinite(seconds)?`已处理 ${Math.max(0,Math.floor(seconds))} 秒，可以先去忙别的，回来再看。`:'正在处理，可以先去忙别的，回来再看。';
      }catch{
        if(!current())return;
        failures++;
        root.querySelector('[data-notice-elapsed]').textContent='进度暂时刷不出来，材料已经存好了。可以手动刷新，不会自动重新交给 AI 处理。';
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
  if(seconds(metrics.first_answer_seconds))result.push(`等到第一段结果 ${seconds(metrics.first_answer_seconds)}`);
  if(seconds(metrics.provider_seconds))result.push(`AI 处理 ${seconds(metrics.provider_seconds)}`);
  if(seconds(metrics.validation_seconds))result.push(`本地检查 ${seconds(metrics.validation_seconds)}`);
  if(Number.isInteger(metrics.input_tokens)&&Number.isInteger(metrics.output_tokens))result.push(`${metrics.usage_complete===false?'已统计部分 · ':''}AI 用量：读入 ${metrics.input_tokens.toLocaleString()} · 生成 ${metrics.output_tokens.toLocaleString()}`);
  if(Number.isInteger(metrics.call_count))result.push(`这次共请 AI 处理了 ${metrics.call_count} 次${metrics.usage_complete===false?'，部分用量还没统计到':''}`);
  return result;
}
