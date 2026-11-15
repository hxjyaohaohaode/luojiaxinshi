import {dictate} from './dictation.js';
import {installNoticeFiles} from './notice-files.js';
import {noticeModePicker} from './notice-modes.js';

export function createNoticeComposer({esc,field,area,icon,toast,persist,showDialog,api,ask,getAI=()=>({}),onRender=()=>{}}) {
  const $=selector=>document.querySelector(selector);
  const files=installNoticeFiles({esc,icon,toast,onChange:updateReadiness});
  function render(){
    $('#content').innerHTML=`<div class="notice-compose natural-intake">
      <header class="notice-compose-head"><h1>收通知</h1><div class="notice-compose-actions">
        <a class="button small plain" href="#intake">批量收通知</a>
        <a class="button small plain notice-compose-back" href="#notices">返回通知</a>
      </div></header>
      <form id="notice-form" class="panel stack">
        <section class="notice-original" aria-label="通知原文">
          <div data-intake-link></div>
          ${area('通知正文','body','',4,'maxlength="10000" placeholder="粘贴通知，或添加原件、截图"')}
          <div class="notice-compose-tools small muted"><button type="button" class="button small plain" data-notice-voice aria-label="语音补充通知正文">${icon('mic')} 语音补充</button><span id="char-count">0 / 10,000 字</span></div>
          <label class="upload notice-upload"><span class="upload-symbol">${icon('upload')}</span><span class="notice-upload-copy">
            <strong>添加通知原件或截图</strong><span class="small muted">可拖入或粘贴 · 最多 5 份，每份 5 MB</span>
          </span><input type="file" name="files" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg,.webp,.mp4,.webm" aria-label="添加通知原件或截图" aria-describedby="notice-file-help"></label>
          <p class="field-note" id="notice-file-help">申请表、成绩单等个人办理材料，请在对应待办中添加。</p>
          <div class="files-list" id="files-list"></div>
        </section>
        <details class="details intake-metadata"><summary>标题与来源（选填）</summary><div class="stack">
          ${field('标题','title','','text','maxlength="160" placeholder="留空时从通知内容生成"')}
          <div class="form-grid">${field('来源名称','source_label','','text','maxlength="100" placeholder="学院官网、年级群等"')}${field('原发布时间（北京时间）','published_at','','datetime-local')}</div>
          <p class="field-note">原文使用“明天”等相对日期时，需要原发布时间才能核实期限。</p>
          ${field('原文地址','source_url','','url','maxlength="2000" placeholder="https://…"')}
          <label class="check"><input type="checkbox" name="allow_duplicate" value="true"><span>这是另一学期或批次，单独收件</span></label>
        </div></details>
        <div class="notice-confirmations">
          <label class="check"><input type="checkbox" name="materials_complete"><span>已核对通知正文和关键附件齐全</span></label>
          <label class="check"><input type="checkbox" name="rights" required><span>确认有权保存这些通知原件</span></label>
        </div>
        ${getAI().configured?`${noticeModePicker(getAI(),esc)}<label class="check"><input type="checkbox" name="prepare_consent"><span>同意将本则通知和必要个人条件交给小米 MiMo，整理办理路径</span></label><p class="field-note">先保存原件，再整理步骤、材料和入口。${getAI().notice_auto_repair?'通常整理和复核各一次，发现问题时最多再补正、复核各一次。':''}结果由你确认后保存。</p>`:''}
        <div class="form-footer"><span id="notice-intake-count" class="small muted" role="status"></span><button class="button ${getAI().configured?'':'primary'}" type="submit" name="intent" value="save">仅保存原件</button>${getAI().configured?`<button class="button primary" type="submit" name="intent" value="prepare">整理成办理路径 ${icon('arrow')}</button>`:''}</div>
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
  document.addEventListener('input',event=>{if(event.target.closest('#notice-form')){updateReadiness();if(['body','files','source_url','source_label','published_at','title'].includes(event.target.name)){const consent=$('#notice-form').elements.prepare_consent;if(consent)consent.checked=false;}}});
  function advanceIfNeeded(intent='save'){
    const form=$('#notice-form');if(!form)return false;
    if(!form.elements.body.value.trim()&&!form.elements.files.files.length&&!form.elements.link_preview?.value){
      toast('请粘贴通知正文、原文链接，或添加原件。',true);form.elements.body.focus();return true;
    }
    if(intent==='prepare'&&!form.elements.prepare_consent?.checked){toast('请先勾选同意由 AI 整理；也可以仅保存原件。',true);form.elements.prepare_consent?.focus();return true;}
    return false;
  }
  return {render,advanceIfNeeded,restoreFiles:files.restore};
}
