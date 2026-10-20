import {companion} from './companion.js';
import {contextHint} from './motion.js';
import {dictate} from './dictation.js';
import {installNoticeFiles} from './notice-files.js';
import {animateSurface} from './experience-system.js';
export function createNoticeComposer({esc,field,area,icon,toast,persist,showDialog,api,ask}) {
  const $=selector=>document.querySelector(selector);
  const files=installNoticeFiles({esc,icon,toast,onChange:updateReadiness});
  function render(){
    $('#content').innerHTML=`<div class="notice-compose">
      <div class="notice-welcome"><div><span class="section-eyebrow">收好原文 · 从这里开始</span><h1>处理一则通知</h1><p>把消息放在一起，把下一步留给清楚的自己。</p></div>${companion('organize','compose-companion')}</div>
      <nav class="notice-stepper" aria-label="提交通知的步骤"><ol>
        <li><button type="button" class="active" data-notice-stage="content" aria-current="step" aria-controls="notice-content-step"><b>1</b><span><strong>内容与附件</strong><small>保留完整的原文</small></span></button></li>
        <li><button type="button" data-notice-stage="review" aria-controls="notice-review-step"><b>2</b><span><strong>来源与核对</strong><small>确认材料后再保存</small></span></button></li>
      </ol><span class="stepper-note">${icon('shield')} 保存后由你确认行动</span></nav>
      <div class="notice-compose-layout">
      <form id="notice-form" class="panel stack">
        <section class="stack" id="notice-content-step" data-notice-step="content">
          <div class="compose-section-heading"><span class="compose-section-icon">${icon('doc')}</span><div><h2>通知内容</h2><p>粘贴正文，或上传原文件与截图。</p></div><span class="compose-step-count">01 / 02</span></div>
          ${field('通知标题','title','','text','required maxlength="160" placeholder="给这则通知一个便于查找的标题"')}
          ${area('通知正文','body','',5,'maxlength="10000" placeholder="粘贴完整原文，或在下面上传附件。"')}
          <div class="between small muted"><button type="button" class="button small plain" data-notice-voice aria-label="语音补充通知正文">${icon('mic')} 语音补充</button><span id="char-count">0 / 10,000 字</span></div>
          <label class="upload notice-upload"><span class="upload-symbol">${icon('upload')}</span><strong>点击选择，或把附件拖到这里</strong><span class="small muted">也可以直接粘贴截图 · 最多 5 份，每份 5 MB</span><span class="upload-formats" aria-hidden="true">PDF / Word / Excel / 文字 / 图片 / 视频</span><input type="file" name="files" multiple accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="上传通知附件" aria-describedby="notice-file-help"></label>
          <p class="sr-only" id="notice-file-help">支持 PDF、DOCX、XLSX、CSV、MD、TXT、PNG、JPG、JPEG、WebP、MP4、WebM。最多 5 份，每份不超过 5 MB。选中后可逐项移除，点击保存后上传。</p>
          <div class="files-list" id="files-list"></div>
          <div class="form-footer"><a class="button" href="#notices">返回资料</a><button type="button" class="button primary" data-notice-step-to="review">下一步 ${icon('arrow')}</button></div>
        </section>
        <section class="stack" id="notice-review-step" data-notice-step="review" hidden>
          <div class="compose-section-heading"><span class="compose-section-icon">${icon('shield')}</span><div><h2>来源与核对</h2><p>给材料留下出处，方便日后回查。</p></div><span class="compose-step-count">02 / 02</span></div>
          <div class="review-reassurance">这一步只是保存材料。之后还会逐项核对本人责任和期限，再由你确认待办。</div><div class="notice-preview"><strong id="notice-review-title"></strong><span class="small muted" id="notice-review-count"></span></div>
          <div class="form-grid">${field('来源名称（选填）','source_label','','text','maxlength="100" placeholder="学院官网、年级群等"')}${field('原发布时间（北京时间）','published_at','','datetime-local')}</div>
          <p class="field-note">原文有“明天”“本周五”等说法时，请补充发布时间。</p>
          <details class="details"><summary>原文链接与材料说明</summary><div class="stack">${field('原文链接（选填）','source_url','','url','disabled maxlength="2000" placeholder="https://…"')}<p class="small muted">链接供回查，不代替正文。PDF 最多 50 页；正文和附件合计不超过 10,000 字。扫描件与复杂表格需要对照原件核对。</p><p class="small muted">保存后可手工整理，或另行确认交给 AI 处理。</p></div></details>
          <label class="check"><input type="checkbox" name="materials_complete"><span>我已核对正文和关键附件齐全。</span></label>
          <label class="check"><input type="checkbox" name="rights" required disabled><span>我有权处理这些材料，已移除不必要的个人敏感信息。</span></label>
          <div class="form-footer"><button type="button" class="button" data-notice-step-to="content">上一步</button><button class="button primary" type="submit">保存并核对 ${icon('arrow')}</button></div>
        </section>
      </form>
      <aside class="compose-guide" aria-label="提交材料提示">
        <section class="compose-envelope" aria-label="尚未保存的通知预览" data-spotlight data-tilt><span class="section-eyebrow">收件预览 · 尚未保存</span><h3 id="compose-preview-title">这一封来信，关于什么？</h3><p id="compose-preview-body">填入标题和正文，这里会留下这次材料的简短预览。</p><div class="compose-envelope-footer">${icon('doc')}<span id="compose-preview-meta">等待添加材料</span></div></section>
        <section class="compose-readiness"><div class="aside-heading">${icon('tasks')}<h2>这次带来了什么</h2></div><ul>
          <li data-ready="title"><span class="readiness-mark" aria-hidden="true"></span><span>通知标题</span><small>待填写</small></li>
          <li data-ready="body"><span class="readiness-mark" aria-hidden="true"></span><span>原文正文</span><small>待补充</small></li>
          <li data-ready="files"><span class="readiness-mark" aria-hidden="true"></span><span>相关附件</span><small>按需添加</small></li>
        </ul><p>有正文或附件即可继续。是否完整，还需要你对照原通知核对。</p></section>
        ${contextHint('notice-original','原文多留一点，判断稳妥一点','请保留适用对象、日期和附件说明。不确定的地方先标记待核实。')}
        <section class="compose-after"><span class="section-eyebrow">保存之后</span><h2>重要的事，由你确认。</h2><p>先查看材料，再选择手工整理或交给 AI 处理。逐项核对后，才会留下个人待办。</p><a href="#notices">查看已有通知 ${icon('arrow')}</a></section>
      </aside></div></div>`;
    updateReadiness();
  }
  function updateReadiness(){
    const form=$('#notice-form');if(!form)return;
    const title=!!form.elements.title.value.trim(),length=form.elements.body.value.trim().length,count=form.elements.files.files.length;
    $('#compose-preview-title').textContent=form.elements.title.value.trim()||'这一封来信，关于什么？';
    $('#compose-preview-body').textContent=form.elements.body.value.trim().slice(0,180)||'填入标题和正文，这里会留下这次材料的简短预览。';
    $('#compose-preview-meta').textContent=length||count?`${length.toLocaleString()} 字正文 · ${count} 份附件`:'等待添加材料';
    const reviewCount=$('#notice-review-count');
    if(reviewCount)reviewCount.textContent=`${form.elements.body.value.length.toLocaleString()} 字 · ${count} 份附件`;
    for(const [name,ready,text] of [['title',title,title?'已填写':'待填写'],['body',!!length,length?`${length.toLocaleString()} 字`:'待补充'],['files',!!count,count?`${count} 份待保存`:'按需添加']]){
      const item=$(`[data-ready="${name}"]`);if(!item)continue;item.classList.toggle('is-ready',ready);item.querySelector('small').textContent=text;
    }
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
    for(const label of document.querySelectorAll('[data-notice-stage]')){const active=label.dataset.noticeStage===next;label.classList.toggle('active',active);label.classList.toggle('is-complete',next==='review'&&label.dataset.noticeStage==='content');if(active)label.setAttribute('aria-current','step');else label.removeAttribute('aria-current');}
    form.elements.rights.disabled=next!=='review';
    // A malformed optional link must be visible when native form validation runs.
    form.elements.source_url.disabled=next!=='review';
    persist();form.scrollIntoView({block:'start'});
    animateSurface(form.querySelector(`[data-notice-step="${next}"]`),next==='review'?1:-1);
    form.querySelector(`[data-notice-step="${next}"] input`)?.focus({preventScroll:true});
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-notice-step-to],[data-notice-stage]');if(button)step(button.dataset.noticeStepTo||button.dataset.noticeStage);const voice=event.target.closest('[data-notice-voice]');if(voice)dictate($('#notice-form').elements.body,voice,{api,toast,ask});});
  document.addEventListener('invalid',event=>{if(event.target.name==='source_url'&&event.target.closest('#notice-form'))event.target.closest('details').open=true;},true);
  document.addEventListener('input',event=>{if(event.target.closest('#notice-form'))updateReadiness();});
  function advanceIfNeeded(){if($('#notice-form [data-notice-step="content"]')?.hidden===false){step('review');return true;}return false;}
  return {render,advanceIfNeeded,restoreFiles:files.restore};
}
