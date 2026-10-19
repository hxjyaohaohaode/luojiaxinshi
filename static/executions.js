import {metricLines} from './notice-progress.js';
import {captureUiContext} from './ui-request.js';
const statuses={running:'处理中',succeeded:'已完成',failed:'未完成',cancelled:'已停止',discarded:'旧结果未采纳',interrupted:'进程中断'};
const stages={accepted:'已接收',planning:'确认范围',retrieving:'查找资料',searching:'查找公开来源',coverage:'检查证据覆盖',writing:'组织回答',verifying:'复核内容',extracting:'整理通知',receiving:'接收整理结果',reviewing:'复核动作与原文'};
const reasons={context_changed:'相关上下文已变化，需要按最新内容重试',process_lost:'原处理进程已失联',backup_restored:'从备份恢复，需要重新处理',superseded:'已被停止或新的请求替代',initialization_failed:'执行未能启动',interrupted_request:'请求处理发生中断',provider_or_validation:'模型调用或结果校验未通过',protocol_limit:'格式修复次数达到上限',semantic_limit:'内容修复次数达到上限',generation_limit:'生成次数达到上限',no_progress:'重复草稿没有改善，已停止循环',request_failed:'处理未能完成，请打开原记录查看原因'};

export async function executionDialog({state,api,esc,showDialog,toast}){
  const view=captureUiContext(state);
  const data=await api('/executions');
  if(!view.sameDialog())return;
  showDialog('最近处理记录',`<div class="stack execution-list"><p class="muted">记录最近 ${data.limit} 次通知整理与对话处理。${esc(data.recovery)}</p>${data.items.map(item=>{
    const seconds=Math.max(0,(item.finished_at||Math.floor(Date.now()/1000))-item.started_at);
    return `<article class="memory-card"><div class="between"><strong>${esc(item.title)}</strong><span class="pill">${esc(statuses[item.status]||item.status)}</span></div><p class="small muted">${item.kind==='notice'?'通知整理':'对话处理'} · ${esc(stages[item.stage]||item.stage)} · ${seconds} 秒</p>${metricLines(item.metrics).map(line=>`<p class="small muted">${esc(line)}</p>`).join('')}<p class="small">${esc(reasons[item.stop_reason]||'')}</p><p class="small muted">${esc(new Date(item.started_at*1000).toLocaleString())}</p><a class="button small" href="#${item.kind==='notice'?'notice/'+item.notice_id:'chat/'+item.conversation_id}" data-execution-open>打开原记录</a></article>`;
  }).join('')||'<p class="muted">暂无处理记录。开始通知整理或发送问题后会在这里记录。</p>'}<button type="button" class="button" data-execution-refresh>刷新处理状态</button></div>`);
  document.querySelector('[data-execution-refresh]').addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;try{await executionDialog({state,api,esc,showDialog,toast});}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
  document.querySelectorAll('[data-execution-open]').forEach(link=>link.addEventListener('click',()=>document.querySelector('#dialog').close()));
}
