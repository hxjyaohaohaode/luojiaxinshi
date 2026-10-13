export function createNoticeComposer({esc,field,area,icon,toast,persist}) {
  const $=selector=>document.querySelector(selector);
  function render(){
    $('#content').innerHTML=`<div class="notice-compose">
      <h1 class="sr-only">处理一则通知</h1>
      <div class="steps" aria-label="提交进度"><span class="active" data-notice-stage="content"><b>1</b> 内容与附件</span><i></i><span data-notice-stage="review"><b>2</b> 来源与核对</span></div>
      <form id="notice-form" class="panel stack">
        <section class="stack" data-notice-step="content">
          ${field('通知标题','title','','text','required maxlength="160" placeholder="给这则通知一个便于查找的标题"')}
          ${area('通知正文','body','',5,'maxlength="10000" placeholder="粘贴完整原文，或在下面上传附件。"')}
          <div class="between small muted"><span>正文、附件至少填写一项</span><span id="char-count">0 / 10,000 字</span></div>
          <label class="upload">${icon('upload')}<strong>选择或拖入附件</strong><span class="small muted">PDF、DOCX、TXT、图片 · 最多 5 份，每份 5 MB</span><input type="file" name="files" multiple accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp" aria-label="上传通知附件"></label>
          <div class="files-list" id="files-list"></div>
          <div class="form-footer"><a class="button" href="#notices">返回资料</a><button type="button" class="button primary" data-notice-step-to="review">下一步 ${icon('arrow')}</button></div>
        </section>
        <section class="stack" data-notice-step="review" hidden>
          <div class="notice-preview"><strong id="notice-review-title"></strong><span class="small muted" id="notice-review-count"></span></div>
          <div class="form-grid">${field('来源名称（选填）','source_label','','text','maxlength="100" placeholder="学院官网、年级群等"')}${field('原发布时间（北京时间）','published_at','','datetime-local')}</div>
          <p class="field-note">原文有“明天”“本周五”等说法时，请补充发布时间。</p>
          <details class="details"><summary>原文链接与材料说明</summary><div class="stack">${field('原文链接（选填）','source_url','','url','disabled maxlength="2000" placeholder="https://…"')}<p class="small muted">链接供回查，不代替正文。PDF 最多 50 页；正文和附件合计不超过 10,000 字。扫描件与复杂表格需要对照原件核对。</p><p class="small muted">保存后可手工整理，或另行确认交给 AI 处理。</p></div></details>
          <label class="check"><input type="checkbox" name="materials_complete"><span>我已核对正文和关键附件齐全。</span></label>
          <label class="check"><input type="checkbox" name="rights" required disabled><span>我有权处理这些材料，已移除不必要的个人敏感信息。</span></label>
          <div class="form-footer"><button type="button" class="button" data-notice-step-to="content">上一步</button><button class="button primary" type="submit">保存并核对 ${icon('arrow')}</button></div>
        </section>
      </form></div>`;
  }
  function step(next){
    const form=$('#notice-form');if(!form||form.inert)return;
    if(next==='review'){
      if(!form.elements.title.reportValidity())return;
      if(!form.elements.body.value.trim()&&!form.elements.files.files.length){toast('请粘贴通知正文，或选择要处理的附件。',true);form.elements.body.focus();return;}
      $('#notice-review-title').textContent=form.elements.title.value;
      $('#notice-review-count').textContent=`${form.elements.body.value.length.toLocaleString()} 字 · ${form.elements.files.files.length} 份附件`;
    }
    for(const panel of form.querySelectorAll('[data-notice-step]'))panel.hidden=panel.dataset.noticeStep!==next;
    for(const label of document.querySelectorAll('[data-notice-stage]')){const active=label.dataset.noticeStage===next;label.classList.toggle('active',active);if(active)label.setAttribute('aria-current','step');else label.removeAttribute('aria-current');}
    form.elements.rights.disabled=next!=='review';
    // A malformed optional link must be visible when native form validation runs.
    form.elements.source_url.disabled=next!=='review';
    persist();form.scrollIntoView({block:'start'});
    form.querySelector(`[data-notice-step="${next}"] input`)?.focus({preventScroll:true});
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-notice-step-to]');if(button)step(button.dataset.noticeStepTo);});
  document.addEventListener('invalid',event=>{if(event.target.name==='source_url'&&event.target.closest('#notice-form'))event.target.closest('details').open=true;},true);
  function advanceIfNeeded(){if($('#notice-form [data-notice-step="content"]')?.hidden===false){step('review');return true;}return false;}
  return {render,advanceIfNeeded};
}
