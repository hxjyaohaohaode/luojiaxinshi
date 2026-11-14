const states={pending:'等待发送',leased:'执行中',sending:'提交中',accepted:'供应商接受',uncertain:'提交结果未确认',failed:'失败',cancelled:'已取消'};

export function renderCampusDeliveryEvidence(evidence,esc){
  if(!evidence)return '<p class="small muted">正在读取现存渠道台账，尚不能据此判断本人是否打开。</p>';
  const rows=['push','email'].map(key=>{
    const channel=evidence.channels?.[key]||{},detail=Object.entries(channel.states||{}).map(([state,count])=>
      `${esc(states[state]||state)} ${Number(count.events)||0} 次 / ${Number(count.recipients)||0} 人`).join('；');
    return `<li><strong>${key==='push'?'浏览器推送':'邮件'}：</strong>供应商接受 ${Number(channel.accepted_events)||0} 次，涉及 ${Number(channel.accepted_recipients)||0} 人。${detail?`<p class="small muted">${detail}</p>`:''}</li>`;
  }).join('');
  const unknown=(value,fallback)=>value?.count===null||value?.count===undefined?`未知 · ${esc(value?.note||fallback)}`:esc(String(value.count));
  return `<section class="stack" aria-label="可证实的渠道投递统计"><h3>渠道证据</h3><ul>${rows}</ul>
    <dl class="detail-list"><dt>本人打开</dt><dd>${unknown(evidence.opened,'未采集可证明本人打开的记录')}</dd><dt>显式回执</dt><dd>${unknown(evidence.explicit_receipt,'未采集发布级显式回执')}</dd></dl>
    <p class="small muted">${esc(evidence.note||'供应商接受不表示设备展示、本人打开或办理完成。')} 同一人的多个设备可形成多次渠道记录。</p></section>`;
}
