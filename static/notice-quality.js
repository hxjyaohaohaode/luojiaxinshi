import {issueControls} from './notice-resolution.js';
// Review findings remain advisory evidence; users explicitly resolve them.
function readableFinding(message){
  const labels={required:'必办',optional:'可选',verification:'核实',unclassified:'待分类'};
  return String(message||'').replace(/\b(?:plan\.)?action_kind\s*[:=]\s*["'`]?\b(required|optional|verification|unclassified)\b["'`]?/g,(_,kind)=>'“'+labels[kind]+'”');
}
function sourceRecords(checks,esc){
  const labels={covered:'AI 觉得草稿都整理到了',gaps:'AI 提示可能有遗漏',uncertain:'AI 也拿不准',background:'AI 认为是背景材料'};
  return checks?.length?`<details class="quality-source-checks"><summary>每份原文的核对情况 · ${checks.length} 份</summary>${checks.map(check=>`<section class="quality-source"><strong>${esc(check.name)}</strong><p class="small muted">${esc(labels[check.coverage]||'对照原文看看')}</p><p>${esc(check.requirements_summary)}</p><details><summary>对照原句</summary>${(check.evidence||[]).map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${esc(e.source_id)}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details></section>`).join('')}</details>`:'';
}
export function needsQualityResolution(quality){return ['needs_review','unavailable'].includes(quality?.status);}
export function qualityPanel(quality,tasks,resolution,esc,options={}){
  if(!quality||quality.status==='not_run')return '<p class="small muted">这份草稿还没让 AI 自查过，保存前对照原文看一遍吧。</p>';
  const issues=quality.issues||[],required=needsQualityResolution(quality);
  const title=quality.status==='passed'?'AI 自查了一遍，没发现明显问题':quality.status==='unavailable'?'AI 自查没做完':`AI 自查发现 ${issues.length} 处要看看`;
  return `<section class="notice-quality ${required?'alert':''}" aria-label="AI 自查"><strong>${esc(title)}</strong>
    <p class="small muted">AI 也可能看漏或看错。对照原文看看谁来办、必办还是可选、手续、材料和前置条件，确认没问题再保存。</p>
    ${sourceRecords(quality.source_checks,esc)}
    ${quality.status==='unavailable'?`<p class="small">${esc(quality.reason||'这次没拿到完整的自查结果。')} 草稿已经留好了，不会自动重试。</p>`:''}
    ${options.structured&&issues.length?'<p class="small" data-quality-count></p>':''}
    ${issues.map((issue,i)=>{const index=issue.task_index===null?-1:tasks.findIndex(task=>task._source_index===issue.task_index);return `<details class="quality-issue"><summary>意见 ${i+1} · ${issue.task_index===null?'整体或漏项':esc(index<0?'原草稿步骤 '+(issue.task_index+1):tasks[index].title)}</summary><p>${esc(readableFinding(issue.message))}</p>${index>=0?`<button type="button" class="button small" data-action="quality-step" data-source-index="${issue.task_index}">找到这一步</button>`:''}<details><summary>对照原句</summary>${(issue.evidence||[]).map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${esc(e.source_id)}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details></details>${options.structured?issueControls(issue,i,tasks,options.decisions?.[i],esc):''}`;}).join('')}
    ${options.structured&&quality.status==='needs_review'&&resolution?`<details class="quality-legacy-note"><summary>之前写的总说明（每条意见还要单独处理）</summary><p>${esc(resolution)}</p></details><input type="hidden" name="quality_resolution" value="${esc(resolution)}">`:''}
    ${required&&(!options.structured||quality.status==='unavailable')?`<label class="field quality-resolution">你的说明<textarea name="quality_resolution" rows="3" minlength="8" maxlength="2000" required placeholder="写写改了哪些步骤、哪些先不存；觉得意见不对的话，说说原文是怎么写的。">${esc(resolution||'')}</textarea></label><p class="small muted">这些意见不会自动改你的步骤。处理完上面的意见再保存就好，说明会记在修改记录里。</p>${options.structured?`<label class="check"><input type="checkbox" name="manual_quality_reviewed" required ${options.manualReviewed?'checked':''}><span>AI 自查没做完，我已经自己对照每份原文检查过选中的步骤。</span></label>`:''}`:''}
  </section>`;
}
