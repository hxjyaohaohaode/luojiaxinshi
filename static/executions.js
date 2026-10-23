import {metricLines} from './notice-progress.js';
import {captureUiContext} from './ui-request.js';
const statuses={running:'处理中',succeeded:'已完成',failed:'未完成',cancelled:'已停止',discarded:'旧结果没用上',interrupted:'中途断了'};
const stages={accepted:'已接收',planning:'理解问题',retrieving:'查找资料',searching:'搜公开资料',coverage:'核对资料够不够',writing:'组织回答',verifying:'检查一遍',extracting:'整理通知',receiving:'接收整理结果',reviewing:'对照原文自查'};
const reasons={context_changed:'相关内容有变化，按最新内容再试一次吧',process_lost:'处理中途断开了',backup_restored:'数据从备份恢复过，需要重新处理',superseded:'已停止，或被新的请求代替了',initialization_failed:'没能开始处理',interrupted_request:'处理被打断了',provider_or_validation:'AI 处理或结果检查没通过',protocol_limit:'格式反复出错，先停下了',semantic_limit:'内容改了几次还不理想，先停下了',generation_limit:'生成次数用完了',no_progress:'几次草稿都没改进，先停下了',request_failed:'没处理完，打开原记录看看原因'};

export async function executionDialog({state,api,esc,showDialog,toast}){
  const view=captureUiContext(state);
  const data=await api('/executions');
  if(!view.sameDialog())return;
  showDialog('最近处理记录',`<div class="stack execution-list"><p class="muted">这里记着最近 ${data.limit} 次通知整理和对话。${esc(data.recovery)}</p>${data.items.map(item=>{
    const seconds=Math.max(0,(item.finished_at||Math.floor(Date.now()/1000))-item.started_at);
    return `<article class="memory-card"><div class="between"><strong>${esc(item.title)}</strong><span class="pill">${esc(statuses[item.status]||item.status)}</span></div><p class="small muted">${item.kind==='notice'?'通知整理':'对话处理'} · ${esc(stages[item.stage]||item.stage)} · ${seconds} 秒</p>${metricLines(item.metrics).map(line=>`<p class="small muted">${esc(line)}</p>`).join('')}<p class="small">${esc(reasons[item.stop_reason]||'')}</p><p class="small muted">${esc(new Date(item.started_at*1000).toLocaleString())}</p><a class="button small" href="#${item.kind==='notice'?'notice/'+item.notice_id:'chat/'+item.conversation_id}" data-execution-open>打开原记录</a></article>`;
  }).join('')||'<p class="muted">还没有处理记录。整理一条通知或问个问题，这里就会有了。</p>'}<button type="button" class="button" data-execution-refresh>刷新</button></div>`);
  document.querySelector('[data-execution-refresh]').addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;try{await executionDialog({state,api,esc,showDialog,toast});}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
  document.querySelectorAll('[data-execution-open]').forEach(link=>link.addEventListener('click',()=>document.querySelector('#dialog').close()));
}
