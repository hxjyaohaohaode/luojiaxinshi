import {dictate} from './dictation.js';
import {installNoticeFiles} from './notice-files.js';
import {animateStepChange,syncStepMarkers,finishReferenceMotion} from './reference-interactions.js';
export function createNoticeComposer({esc,field,area,icon,toast,persist,showDialog,api,ask}) {
  const $=selector=>document.querySelector(selector);
  const files=installNoticeFiles({esc,icon,toast,onChange:updateReadiness});
  function render(){
    $('#content').innerHTML=`<div class="notice-compose">
      <h1 class="sr-only">处理通知</h1>
      <nav class="notice-stepper" aria-label="提交通知的步骤"><ol>
        <li><button type="button" class="active" data-notice-stage="content" aria-current="step" aria-controls="notice-content-step"><b>1</b><span><strong>内容与附件</strong></span></button></li>
        <li><button type="button" data-notice-stage="review" aria-controls="notice-review-step"><b>2</b><span><strong>来源与核对</strong></span></button></li>
      </ol></nav>
      <div class="notice-compose-layout">
      <form id="notice-form" class="panel stack">
        <section class="stack" id="notice-content-step" data-notice-step="content">
          <div class="compose-section-heading"><span class="compose-section-icon">${icon('doc')}</span><div><h2>通知内容</h2></div><span class="compose-step-count">01 / 02</span></div>
          ${field('通知标题','title','','text','required maxlength="160" placeholder="起个以后好找的标题"')}
          ${area('通知正文','body','',5,'maxlength="10000" placeholder="粘贴完整原文，或在下面上传附件。"')}
          <div class="between small muted"><button type="button" class="button small plain" data-notice-voice aria-label="语音补充通知正文">${icon('mic')} 语音补充</button><span id="char-count">0 / 10,000 字</span></div>
          <label class="upload notice-upload"><span class="upload-symbol">${icon('upload')}</span><strong>点击选择，或把附件拖到这里</strong><span class="small muted">也可以直接粘贴截图 · 最多 5 份，每份 5 MB</span><span class="upload-formats" aria-hidden="true">PDF / Word / Excel / 文字 / 图片 / 视频</span><input type="file" name="files" multiple accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="上传通知附件" aria-describedby="notice-file-help"></label>
          <p class="sr-only" id="notice-file-help">支持 PDF、DOCX、XLSX、CSV、MD、TXT、PNG、JPG、JPEG、WebP、MP4、WebM，最多 5 份，每份不超过 5 MB。选好后可以逐个移除，点保存时才会上传。</p>
          <div class="files-list" id="files-list"></div>
          <div class="form-footer"><a class="button" href="#notices">返回资料</a><button type="button" class="button primary" data-notice-step-to="review">下一步 ${icon('arrow')}</button></div>
        </section>
        <section class="stack" id="notice-review-step" data-notice-step="review" hidden>
          <div class="compose-section-heading"><span class="compose-section-icon">${icon('shield')}</span><div><h2>来源与核对</h2></div><span class="compose-step-count">02 / 02</span></div>
          <div class="notice-preview"><strong id="notice-review-title"></strong><span class="small muted" id="notice-review-count"></span></div>
          <div class="form-grid">${field('来源名称（选填）','source_label','','text','maxlength="100" placeholder="学院官网、年级群等"')}${field('发布时间（北京时间）','published_at','','datetime-local')}</div>
          <p class="field-note">原文里有“明天”“本周五”这类说法的话，记得填上发布时间。</p>
          <details class="details"><summary>原文链接与材料说明</summary><div class="stack">${field('原文链接（选填）','source_url','','url','disabled maxlength="2000" placeholder="https://…"')}<p class="small muted">链接方便以后回看，正文还是要贴进来。PDF 最多 50 页，正文和附件加起来不超过 10,000 字。扫描件和复杂表格容易识别出错，记得对照原件看看。</p><p class="small muted">保存后可以自己整理，也可以确认后交给 AI 整理。</p></div></details>
          <label class="check"><input type="checkbox" name="materials_complete"><span>正文和重要附件都齐了。</span></label>
          <label class="check"><input type="checkbox" name="rights" required disabled><span>这些材料我有权使用，也去掉了不必要的个人敏感信息。</span></label>
          <div class="form-footer"><button type="button" class="button" data-notice-step-to="content">上一步</button><button class="button primary" type="submit">保存并核对 ${icon('arrow')}</button></div>
        </section>
      </form>
      <aside class="compose-guide" aria-label="提交材料提示">
        <section class="compose-envelope" aria-label="通知预览（还没保存）" data-spotlight data-tilt><span class="section-eyebrow">预览 · 还没保存</span><h3 id="compose-preview-title">通知预览</h3><p id="compose-preview-body"></p><div class="compose-envelope-footer">${icon('doc')}<span id="compose-preview-meta">等你添加材料</span></div></section>
        <section class="compose-readiness"><div class="aside-heading">${icon('tasks')}<h2>这次带来了什么</h2></div><ul>
          <li data-ready="title"><span class="readiness-mark" aria-hidden="true"></span><span>通知标题</span><small>待填写</small></li>
          <li data-ready="body"><span class="readiness-mark" aria-hidden="true"></span><span>原文正文</span><small>待补充</small></li>
          <li data-ready="files"><span class="readiness-mark" aria-hidden="true"></span><span>相关附件</span><small>按需添加</small></li>
        </ul></section>

      </aside></div></div>`;
    updateReadiness();
  }
  function updateReadiness(){
    const form=$('#notice-form');if(!form)return;
    const title=!!form.elements.title.value.trim(),length=form.elements.body.value.trim().length,count=form.elements.files.files.length;
    $('#compose-preview-title').textContent=form.elements.title.value.trim()||'通知预览';
    $('#compose-preview-body').textContent=form.elements.body.value.trim().slice(0,180)||'';
    $('#compose-preview-meta').textContent=length||count?`${length.toLocaleString()} 字正文 · ${count} 份附件`:'等你添加材料';
    const reviewCount=$('#notice-review-count');
    if(reviewCount)reviewCount.textContent=`${form.elements.body.value.length.toLocaleString()} 字 · ${count} 份附件`;
    for(const [name,ready,text] of [['title',title,title?'已填写':'待填写'],['body',!!length,length?`${length.toLocaleString()} 字`:'待补充'],['files',!!count,count?`${count} 份待保存`:'按需添加']]){
      const item=$(`[data-ready="${name}"]`);if(!item)continue;item.classList.toggle('is-ready',ready);item.querySelector('small').textContent=text;
    }
  }
  function step(next){
    const form=$('#notice-form');if(!form||form.inert)return;
    if(form.querySelector(`[data-notice-step="${next}"]`)?.hidden===false)return;
    if(next==='review'){
      if(!form.elements.title.reportValidity())return;
      if(!form.elements.body.value.trim()&&!form.elements.files.files.length){toast('先贴上通知正文，或者选个附件吧。',true);form.elements.body.focus();return;}
      $('#notice-review-title').textContent=form.elements.title.value;
      $('#notice-review-count').textContent=`${form.elements.body.value.length.toLocaleString()} 字 · ${form.elements.files.files.length} 份附件`;
    }
    finishReferenceMotion();const before=form.getBoundingClientRect().height;
    for(const panel of form.querySelectorAll('[data-notice-step]'))panel.hidden=panel.dataset.noticeStep!==next;
    for(const label of document.querySelectorAll('[data-notice-stage]')){const active=label.dataset.noticeStage===next;label.classList.toggle('active',active);label.classList.toggle('is-complete',next==='review'&&label.dataset.noticeStage==='content');if(active)label.setAttribute('aria-current','step');else label.removeAttribute('aria-current');}
    form.elements.rights.disabled=next!=='review';
    // A malformed optional link must be visible when native form validation runs.
    form.elements.source_url.disabled=next!=='review';
    persist();form.scrollIntoView({block:'start'});
    syncStepMarkers(document.querySelector('.notice-stepper'));
    animateStepChange(form,form.querySelector(`[data-notice-step="${next}"]`),before,next==='review'?1:-1);
    form.querySelector(`[data-notice-step="${next}"] input`)?.focus({preventScroll:true});
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-notice-step-to],[data-notice-stage]');if(button)step(button.dataset.noticeStepTo||button.dataset.noticeStage);const voice=event.target.closest('[data-notice-voice]');if(voice)dictate($('#notice-form').elements.body,voice,{api,toast,ask});});
  document.addEventListener('invalid',event=>{if(event.target.name==='source_url'&&event.target.closest('#notice-form'))event.target.closest('details').open=true;},true);
  document.addEventListener('input',event=>{if(event.target.closest('#notice-form'))updateReadiness();});
  function advanceIfNeeded(){if($('#notice-form [data-notice-step="content"]')?.hidden===false){step('review');return true;}return false;}
  return {render,advanceIfNeeded,restoreFiles:files.restore};
}
