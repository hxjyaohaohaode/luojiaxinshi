export function noticeModePicker(ai,esc){
  const modes=ai.notice_modes||[];
  if(modes.length<2)return '';
  return `<section class="notice-mode"><label class="field">本次整理方式<select id="notice-processing-mode" aria-describedby="notice-mode-description">${modes.map(mode=>`<option value="${esc(mode.id)}">${esc(mode.label)}</option>`).join('')}</select></label><p id="notice-mode-description" class="small muted">${esc(modes[0].description)}</p><details data-notice-mode-cost hidden><summary>查看加速费用</summary><p data-notice-mode-price></p><a data-notice-mode-price-link target="_blank" rel="noopener noreferrer">小米官方价格说明 ↗</a></details></section>`;
}

export function updateNoticeMode(root,ai){
  const select=root.querySelector('#notice-processing-mode');
  const mode=(ai.notice_modes||[]).find(item=>item.id===select?.value);
  if(!mode)return;
  root.querySelector('#notice-mode-description').textContent=mode.description;
  const costs=root.querySelector('[data-notice-mode-cost]');
  costs.hidden=!mode.price_note;
  costs.open=!!mode.price_note;
  root.querySelector('[data-notice-mode-price]').textContent=mode.price_note||'';
  root.querySelector('[data-notice-mode-price-link]').href=mode.price_source||'https://mimo.mi.com';
  const consent=root.querySelector('#ai-consent');
  if(consent)consent.checked=false;
}
