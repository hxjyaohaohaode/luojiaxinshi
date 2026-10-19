import {issueControls} from './notice-resolution.js';
// Review findings remain advisory evidence; users explicitly resolve them.
function readableFinding(message){
  const labels={required:'必办',optional:'可选',verification:'核实',unclassified:'待分类'};
  return String(message||'').replace(/\b(?:plan\.)?action_kind\s*[:=]\s*["'`]?\b(required|optional|verification|unclassified)\b["'`]?/g,(_,kind)=>'“'+labels[kind]+'”');
}
function sourceRecords(checks,esc){
  const labels={covered:'模型认为草稿已覆盖',gaps:'模型提示有遗漏',uncertain:'模型仍待核实',background:'模型判为背景材料'};
  return checks?.length?`<details class="quality-source-checks"><summary>逐份原文核对记录 · ${checks.length} 份</summary>${checks.map(check=>`<section class="quality-source"><strong>${esc(check.name)}</strong><p class="small muted">${esc(labels[check.coverage]||'请核对原文')}</p><p>${esc(check.requirements_summary)}</p><details><summary>对照原句</summary>${(check.evidence||[]).map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${esc(e.source_id)}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details></section>`).join('')}</details>`:'';
}
export function needsQualityResolution(quality){return ['needs_review','unavailable'].includes(quality?.status);}
export function qualityPanel(quality,tasks,resolution,esc,options={}){
  if(!quality||quality.status==='not_run')return '<p class="small muted">本草稿未进行独立动作复核，请逐项对照原文。</p>';
  const issues=quality.issues||[],required=needsQualityResolution(quality);
  const title=quality.status==='passed'?'独立复核未发现实质问题':quality.status==='unavailable'?'独立复核未完成':`独立复核发现 ${issues.length} 处待核对`;
  return `<section class="notice-quality ${required?'alert':''}" aria-label="独立动作复核"><strong>${esc(title)}</strong>
    <p class="small muted">模型复核可能遗漏或误判。请结合原文检查责任人、必办与可选、手续、材料和前置条件；仍由你确认保存。</p>
    ${sourceRecords(quality.source_checks,esc)}
    ${quality.status==='unavailable'?`<p class="small">${esc(quality.reason||'本次未取得完整复核结果。')} 已保留草稿，未自动重试。</p>`:''}
    ${options.structured&&issues.length?'<p class="small" data-quality-count></p>':''}
    ${issues.map((issue,i)=>{const index=issue.task_index===null?-1:tasks.findIndex(task=>task._source_index===issue.task_index);return `<details class="quality-issue"><summary>意见 ${i+1} · ${issue.task_index===null?'整体或漏项':esc(index<0?'原草稿步骤 '+(issue.task_index+1):tasks[index].title)}</summary><p>${esc(readableFinding(issue.message))}</p>${index>=0?`<button type="button" class="button small" data-action="quality-step" data-source-index="${issue.task_index}">定位相关步骤</button>`:''}<details><summary>对照原句</summary>${(issue.evidence||[]).map(e=>`<div class="evidence"><button type="button" data-action="evidence" data-source="${esc(e.source_id)}" data-locator="${esc(e.locator)}">${esc(e.locator)} ↗</button><p>${esc(e.quote)}</p></div>`).join('')}</details></details>${options.structured?issueControls(issue,i,tasks,options.decisions?.[i],esc):''}`;}).join('')}
    ${options.structured&&quality.status==='needs_review'&&resolution?`<details class="quality-legacy-note"><summary>之前暂存的总说明（仍需逐条处理）</summary><p>${esc(resolution)}</p></details><input type="hidden" name="quality_resolution" value="${esc(resolution)}">`:''}
    ${required&&(!options.structured||quality.status==='unavailable')?`<label class="field quality-resolution">核实与修改说明<textarea name="quality_resolution" rows="3" minlength="8" maxlength="2000" required placeholder="说明已修改或暂不保存的步骤；若复核意见不适用，请写明原文依据。">${esc(resolution||'')}</textarea></label><p class="small muted">意见不会自动改写步骤。请先处理上面的意见，再确认保存；说明会保留在修改记录中。</p>${options.structured?`<label class="check"><input type="checkbox" name="manual_quality_reviewed" required ${options.manualReviewed?'checked':''}><span>独立复核未完成，我已逐份人工核对全部原文与所选步骤。</span></label>`:''}`:''}
  </section>`;
}
