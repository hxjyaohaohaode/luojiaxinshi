import {dictate} from './dictation.js';
import {installNoticeFiles} from './notice-files.js';

export function createNoticeComposer({esc,field,area,icon,toast,persist,showDialog,api,ask,onRender=()=>{}}) {
  const $=selector=>document.querySelector(selector);
  const files=installNoticeFiles({esc,icon,toast,onChange:updateReadiness});
  function render(){
    $('#content').innerHTML=`<div class="notice-compose natural-intake">
      <div class="page-title between"><h1>收通知</h1><a class="button small" href="#notices">返回通知</a></div>
      <form id="notice-form" class="panel stack">
        <div class="compose-section-heading"><h2>通知原文</h2></div>
        ${area('正文','body','',6,'maxlength="10000" placeholder="粘贴通知，或添加原件、截图"')}
        <div class="between small muted"><button type="button" class="button small plain" data-notice-voice aria-label="语音补充通知正文">${icon('mic')} 语音补充</button><span id="char-count">0 / 10,000 字</span></div>
        <label class="upload notice-upload"><span class="upload-symbol">${icon('upload')}</span><strong>添加通知原件或截图</strong><span class="small muted">可拖入或粘贴 · 最多 5 份，每份 5 MB</span><input type="file" name="files" multiple accept=".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="添加通知原件或截图" aria-describedby="notice-file-help"></label>
        <p class="field-note" id="notice-file-help">申请表填写件、成绩单等本人办理文件，请到对应待办中添加。</p>
        <div class="files-list" id="files-list"></div>
        <details class="details intake-metadata"><summary>标题与来源（选填）</summary><div class="stack">
          ${field('标题','title','','text','maxlength="160" placeholder="留空时从通知内容生成"')}
          <div class="form-grid">${field('来源名称','source_label','','text','maxlength="100" placeholder="学院官网、年级群等"')}${field('原发布时间（北京时间）','published_at','','datetime-local')}</div>
          <p class="field-note">原文使用“明天”等相对日期时，需要原发布时间才能核实期限。</p>
          ${field('原文地址','source_url','','url','maxlength="2000" placeholder="https://…"')}
          <label class="check"><input type="checkbox" name="allow_duplicate" value="true"><span>这是另一学期或批次，单独收件</span></label>
        </div></details>
        <label class="check"><input type="checkbox" name="materials_complete"><span>已核对通知正文和关键附件齐全</span></label>
        <label class="check"><input type="checkbox" name="rights" required><span>确认有权保存这些通知原件</span></label>
        <div class="form-footer"><span id="notice-intake-count" class="small muted" role="status"></span><button class="button primary" type="submit">保存通知 ${icon('arrow')}</button></div>
      </form></div>`;
    onRender($('#notice-form'));updateReadiness();
  }
  function updateReadiness(){
    const form=$('#notice-form');if(!form)return;
    const length=form.elements.body.value.length,count=form.elements.files.files.length,linked=!!form.elements.link_preview?.value;
    $('#char-count').textContent=`${length.toLocaleString()} / 10,000 字`;
    const status=$('#notice-intake-count');if(status)status.textContent=[length?`${length.toLocaleString()} 字正文`:'',count?`${count} 份原件`:'',linked?'1 份链接原文':''].filter(Boolean).join(' · ');
  }
  document.addEventListener('click',event=>{
    const voice=event.target.closest('[data-notice-voice]');if(voice)dictate($('#notice-form').elements.body,voice,{api,toast,ask});
  });
  document.addEventListener('invalid',event=>{
    if(event.target.closest('#notice-form')){const details=event.target.closest('details');if(details)details.open=true;}
  },true);
  document.addEventListener('input',event=>{if(event.target.closest('#notice-form'))updateReadiness();});
  function advanceIfNeeded(){
    const form=$('#notice-form');if(!form)return false;
    if(!form.elements.body.value.trim()&&!form.elements.files.files.length&&!form.elements.link_preview?.value){
      toast('请粘贴通知正文、原文链接，或添加原件。',true);form.elements.body.focus();return true;
    }
    return false;
  }
  return {render,advanceIfNeeded,restoreFiles:files.restore};
}
