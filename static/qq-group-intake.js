import {beginFormFeedback,captureUiContext} from './ui-request.js';

const categories={all:'全部记录',notice:'通知候选',review:'待核对',discussion:'普通讨论',unclassified:'早期收件'};
const outcomes={new:'已加入收件箱',merged:'已关联已有通知',updated:'已保存来源更新',superseded:'较早版本已跳过'};
const analysis={queued:'等待自动整理',running:'正在整理',succeeded:'已有草稿',failed:'整理失败',cancelled:'整理已停止',stale:'已有新版本'};
const media={waiting:'等待原件',complete:'原件已保存',partial:'部分原件待补',missing:'原件待补'};
const receipt={pending:'等待收件',failed:'收件待重试',delivered:'已收件',superseded:'较早版本'};

function time(value){
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value*1000));
}

export function createQQGroupIntake({state,api,esc,showDialog,toast}){
  function settingsMarkup(s){
    return `<form class="stack" data-workspace-form="qq-group-intake" data-version="${s.version}">
      <div class="form-grid">
        <label class="field">群显示名<input name="name" maxlength="60" value="${esc(s.name)}" placeholder="仅本人可见"></label>
        <label class="field">收件方式<select name="mode"><option value="notices" ${s.mode==='notices'?'selected':''}>通知优先</option><option value="all" ${s.mode==='all'?'selected':''}>全部消息进入待处理</option></select></label>
        <label class="field span-2">关注词<input name="keywords" maxlength="383" value="${esc(s.keywords.join('，'))}" placeholder="最多 12 个，用逗号分隔"></label>
      </div>
      <p class="small muted">设置用于之后收到的消息。通知优先会收起明确的应答和表情，可在全部记录查看。</p>
      <div class="form-footer"><button type="submit" class="button primary">保存群设置</button></div>
    </form>`;
  }

  function record(item){
    const mediaState=media[item.media_state];
    const materialCount=item.media_total&&item.media_state!=='waiting'?` ${item.media_saved||0} / ${item.media_total} 份`:'';
    const status=item.media_state==='waiting'&&item.state==='pending'?'等待原件':outcomes[item.result]||receipt[item.state];
    return `<article class="panel stack" data-qq-intake-record="${esc(item.id)}">
      <div class="between"><strong>${esc(item.title)}</strong><time class="small muted">${esc(time(item.created_at))}</time></div>
      <div class="row wrap">
        <span class="pill ${item.category==='review'?'orange':item.category==='notice'?'green':''}">${esc(categories[item.category]||categories.unclassified)}</span>
        <span class="small">${esc(status||'状态待核对')}</span>
        ${item.quiet?'<span class="small muted">普通讨论默认收起</span>':''}
        ${item.repeats?`<span class="small muted">重复上报 ${item.repeats} 次</span>`:''}
      </div>
      ${item.reasons.length?`<p class="small muted">${esc(item.reasons.join(' · '))}</p>`:''}
      ${mediaState&&item.media_state!=='waiting'?`<p class="small">${esc(mediaState+materialCount)}${item.media_note?' · '+esc(item.media_note):''}</p>`:''}
      ${item.error?`<p class="small" role="status">${esc(item.error)}</p>`:''}
      <div class="row wrap">${item.notice_id?`<a class="button small plain" data-action="close-dialog" href="#notice/${encodeURIComponent(item.notice_id)}">查看原文</a>`:''}
        ${['failed','pending'].includes(item.state)&&item.media_state!=='waiting'?`<button type="button" class="button small" data-qq-intake-retry="${esc(item.id)}">重试收件</button>`:''}
        ${analysis[item.automation_state]?`<span class="small muted">${esc(analysis[item.automation_state])}</span>`:''}
      </div>
    </article>`;
  }

  function paint(list,data,trail){
    const counts=data.counts;
    list.innerHTML=`<p class="small">近 7 天 · 已收件 ${counts.delivered} · 通知候选 ${counts.notice} · 待核对 ${counts.review} · 普通讨论 ${counts.discussion}${counts.merged?' · 关联已有通知 '+counts.merged:''}</p>
      <div class="stack">${data.items.length?data.items.map(record).join(''):'<p class="small muted">没有符合条件的收件记录。</p>'}</div>
      ${trail.length||data.next_before?`<div class="row wrap"><button type="button" class="button small" data-qq-intake-page="prev" ${trail.length?'':'disabled'}>上一页</button><button type="button" class="button small" data-qq-intake-page="next" ${data.next_before?'':'disabled'}>下一页</button></div>`:''}`;
  }

  async function open(groupId,onSaved){
    const path='/integrations/qq/groups/'+encodeURIComponent(groupId)+'/intake';
    showDialog('QQ 群收件与规则',`<div class="stack" id="qq-intake-panel"><p role="status">正在读取群收件…</p>
      <div class="form-footer"><button type="button" class="button" data-dialog-cancel>返回上一级</button></div></div>`);
    const root=document.querySelector('#qq-intake-panel');
    const view=captureUiContext(state,root);
    const current=()=>view.sameDialog()&&root.isConnected;
    let data;
    try{data=await api(path);}
    catch(error){if(current())root.textContent=error.message;return;}
    if(!current())return;

    root.innerHTML=settingsMarkup(data.settings)+`<section class="stack">
      <div class="between wrap"><h3>收件记录</h3><div class="row wrap"><label class="field"><span class="sr-only">筛选收件记录</span><select data-qq-intake-filter>${Object.entries(categories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><button type="button" class="button small" data-qq-intake-refresh>刷新</button></div></div>
      <p class="small" role="status" data-qq-intake-status></p><div class="stack" data-qq-intake-records tabindex="-1"></div>
    </section>`;
    const list=root.querySelector('[data-qq-intake-records]'),filter=root.querySelector('[data-qq-intake-filter]');
    const status=root.querySelector('[data-qq-intake-status]');
    let trail=[],category='all',sequence=0;
    paint(list,data,trail);

    async function refresh(nextTrail=trail,nextCategory=category,moveFocus=false){
      const ticket=++sequence,params=new URLSearchParams({category:nextCategory});
      if(nextTrail.length)params.set('before',String(nextTrail.at(-1)));
      list.setAttribute('aria-busy','true');status.textContent='正在读取…';
      try{
        const result=await api(path+'?'+params);
        if(!current()||ticket!==sequence)return;
        data=result;trail=nextTrail;category=nextCategory;
        paint(list,data,trail);status.textContent='';
        if(moveFocus)list.focus();
      }catch(error){
        if(current()&&ticket===sequence){filter.value=category;status.textContent=error.message;}
      }finally{if(current()&&ticket===sequence)list.removeAttribute('aria-busy');}
    }

    root.addEventListener('change',event=>{if(event.target===filter)void refresh([],filter.value);});
    root.addEventListener('click',async event=>{
      const control=event.target.closest('[data-qq-intake-page],[data-qq-intake-refresh],[data-qq-intake-retry]');
      if(!control||control.disabled||!current())return;
      const page=control.dataset.qqIntakePage;
      if(page==='prev')return refresh(trail.slice(0,-1),category,true);
      if(page==='next'&&data.next_before)return refresh([...trail,data.next_before],category,true);
      if(control.hasAttribute('data-qq-intake-refresh'))return refresh([],category);
      if(!control.dataset.qqIntakeRetry)return;
      control.disabled=true;
      try{
        const result=await api('/integrations/qq/deliveries/'+encodeURIComponent(control.dataset.qqIntakeRetry)+'/retry',{method:'POST'});
        if(!current())return;
        toast(result.ok?'已收件':result.waiting_attachments?'原件仍在读取':'尚未收件，请查看记录',!result.ok);
        await refresh();
      }catch(error){if(current())toast(error.message,true);}
      finally{control.disabled=false;}
    });

    root.querySelector('form').addEventListener('submit',async event=>{
      event.preventDefault();
      const form=event.currentTarget,finish=beginFormFeedback(form);
      if(!finish)return;
      const fields=new FormData(form);
      form.inert=true;
      try{
        const keywords=String(fields.get('keywords')).split(/[,，]/).map(word=>word.trim()).filter(Boolean);
        const value=await api(path,{method:'PUT',json:{version:Number(form.dataset.version),
          name:String(fields.get('name')),mode:String(fields.get('mode')),keywords}});
        if(!current())return;
        form.dataset.version=String(value.version);
        form.elements.name.value=value.name;form.elements.keywords.value=value.keywords.join('，');
        onSaved(value);
        toast('群设置已保存');
      }catch(error){if(current())toast(error.message,true);}
      finally{form.inert=false;finish();}
    });
  }

  return {open};
}
