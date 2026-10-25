import {taskTimeLabel} from './notice-timing.js';
export function createNoticeMatters({state,api,esc,showDialog,toast,refreshData}){
  let sequence=0;
  const field=(label,name,value='')=>`<label class="field">${label}<input name="${name}" value="${esc(value)}" maxlength="160" required></label>`;
  const date=n=>n.published_at?new Date(n.published_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):new Date(n.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' 收件';
  const tasks=n=>n.tasks?.length?`<ul class="matter-tasks">${n.tasks.map(t=>`<li><a href="#tasks/${encodeURIComponent(t.id)}">${esc(t.title)}</a><span>${t.status==='done'?'已完成':t.status==='cancelled'?'已取消':'待办'}${t.stage==='submitted'?' · 已记录提交':t.stage==='waiting'?' · 待结果':''}</span><span>${esc(taskTimeLabel(t))}${t.due_date&&!t.deadline_confirmed||t.scheduled&&!t.scheduled.confirmed?'（待核实）':''}</span>${!t.due_date&&t.deadline_text?`<span>原文期限：${esc(t.deadline_text)}（待核实）</span>`:''}${t.planned_at?`<span>个人计划：${esc(new Date(t.planned_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}</span>`:''}${t.submission?`<span>提交要求：${esc(t.submission)}</span>`:''}${t.materials?.length?`<span>材料：${esc(t.materials.join('、'))}</span>`:''}</li>`).join('')}</ul>`:'<p class="small muted">尚未形成办理记录</p>';
  const member=(n,current)=>`<article class="matter-member"><div class="between"><a href="#notice/${encodeURIComponent(n.id)}" ${n.id===current?'aria-current="page"':''}>${esc(n.title)}</a>${n.id===current?'<span class="pill">当前通知</span>':''}</div><p class="small muted">${esc(n.source_label||'本人提交')} · ${esc(date(n))}</p>${tasks(n)}</article>`;
  function decorate(notice){
    const prior=document.querySelector('#notice-matters');prior?.remove();
    const anchor=document.querySelector('.notice-primary');if(!anchor)return;
    const host=document.createElement('section');host.id='notice-matters';host.className='panel notice-matters';anchor.insertAdjacentElement('afterend',host);
    let memberIds=new Set([notice.id]);
    const ticket=++sequence,session=state.session,route=state.renderId;
    const current=()=>ticket===sequence&&session===state.session&&route===state.renderId&&host.isConnected;
    host.innerHTML='<p class="small" role="status">正在查找同一事项…</p>';
    const load=async()=>{
      try{
        const data=await api(`/notices/${encodeURIComponent(notice.id)}/matter`);if(!current())return;
        memberIds=new Set(data.group?.members.map(n=>n.id)||[notice.id]);
        host.innerHTML=`<details ${data.group?'open':''}><summary><strong>同一事项${data.group?' · '+esc(data.group.title):''}</strong> <span class="small muted">${data.group?data.group.members.length+' 则通知':data.suggestions.length?'有 '+data.suggestions.length+' 则待核对':'未归组'}</span></summary><div class="matter-content">${data.group?data.group.members.map(n=>member(n,notice.id)).join(''):''}${data.suggestions.length?`<h3>可能属于同一事项</h3>${data.suggestions.map(n=>`<article class="matter-candidate"><div><a href="#notice/${encodeURIComponent(n.id)}">${esc(n.title)}</a><p class="small muted">${n.reasons.map(esc).join('；')}</p></div><button type="button" class="button small" data-matter-review="${esc(n.id)}">核对归组</button></article>`).join('')}`:''}<div class="form-footer"><button type="button" class="button small" data-matter-choose>选择其他通知归组</button>${data.group?'<button type="button" class="button small" data-matter-remove>将本通知移出事项</button>':''}</div></div></details>`;
        host.querySelectorAll('[data-matter-review]').forEach(b=>b.addEventListener('click',()=>review(b.dataset.matterReview,b)));
        host.querySelector('[data-matter-choose]').addEventListener('click',choose);
        host.querySelector('[data-matter-remove]')?.addEventListener('click',async e=>{
          const control=e.currentTarget;control.disabled=true;
          try{await api(`/notices/${notice.id}/matter`,{method:'DELETE',json:{token:data.token}});if(current()){toast('本通知已移出事项，原文与办理记录保留');await refreshData();await load();}}
          catch(error){if(current()){toast(error.message,true);if(error.status===409)await load();}}finally{if(control.isConnected)control.disabled=false;}
        });
      }catch(error){if(current()){host.innerHTML=`<p role="alert">${esc(error.message)} <button class="button small" type="button">重试</button></p>`;host.querySelector('button').onclick=load;}}
    };
    async function review(otherId,control){
      const requestedDialog=state.dialogRequest;
      if(control)control.disabled=true;
      try{
        const preview=await api(`/notices/${notice.id}/matter/preview`,{method:'POST',json:{other_id:otherId}});if(!current()||requestedDialog!==state.dialogRequest)return;
        showDialog('核对同一事项',`<form id="matter-confirm-form" class="stack">${field('事项名称','title',preview.groups[0]?.title||notice.title)}<ul class="small">${preview.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul><div class="matter-preview">${preview.members.map(n=>member(n,notice.id)).join('')}</div><div class="form-footer"><button class="button" type="button" data-matter-dismiss>不是同一事项</button><button class="button primary" type="submit">确认归入同一事项</button></div></form>`);
        const form=document.querySelector('#matter-confirm-form'),dialog=state.dialogRequest;
        const visible=()=>current()&&dialog===state.dialogRequest&&form.isConnected;
        let needsPreview=false;
        const submit=async(action)=>{
          if(needsPreview){await review(otherId);return;}
          if(form.inert)return;form.inert=true;
          try{
            await api(`/notices/${notice.id}/matter${action==='dismiss'?'/dismiss':''}`,{method:'POST',json:{other_id:otherId,token:preview.token,title:form.elements.title.value}});
            if(!current())return;
            if(visible())document.querySelector('#dialog').close();
            toast(action==='dismiss'?'已排除这组候选':'已归入同一事项');await refreshData();await load();
          }catch(error){if(visible()){toast(error.message,true);if(error.status===409){needsPreview=true;form.querySelector('[type=submit]').textContent='重新核对';}}}finally{form.inert=false;}
        };
        form.addEventListener('submit',e=>{e.preventDefault();e.stopPropagation();submit('merge');});
        form.querySelector('[data-matter-dismiss]').addEventListener('click',()=>submit('dismiss'));
      }catch(error){if(current())toast(error.message,true);}finally{if(control?.isConnected)control.disabled=false;}
    }
    async function choose(){
      const existing=new Set(memberIds);
      showDialog('选择归组通知','<div class="stack"><label class="field">查找通知<input id="matter-notice-search" type="search" placeholder="标题或来源"></label><div id="matter-notice-options"></div></div>');
      const search=document.querySelector('#matter-notice-search'),list=document.querySelector('#matter-notice-options'),dialog=state.dialogRequest;
      let candidates=[];search.disabled=true;list.innerHTML='<p class="small" role="status">正在加载通知…</p>';
      try{candidates=await api('/notices');if(!current()||dialog!==state.dialogRequest||!search.isConnected)return;}
      catch(error){if(current()&&dialog===state.dialogRequest){list.innerHTML=`<p role="alert">${esc(error.message)}</p><button type="button" class="button small">重试</button>`;list.querySelector('button').onclick=choose;}return;}
      search.disabled=false;
      const render=()=>{
        const q=search.value.trim().toLocaleLowerCase();
        const all=candidates.filter(n=>!existing.has(n.id)&&(n.title+' '+(n.source_label||'')).toLocaleLowerCase().includes(q));
        list.innerHTML=all.slice(0,40).map(n=>`<div class="matter-candidate"><span>${esc(n.title)}<small class="muted"> ${esc(n.source_label||'')}</small></span><button class="button small" type="button" data-id="${esc(n.id)}">核对归组</button></div>`).join('')+(!all.length?'<p class="small">没有匹配通知</p>':all.length>40?`<p class="small">共 ${all.length} 则，请输入更具体的标题查找。</p>`:'');
        list.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>review(b.dataset.id,b));
      };
      search.addEventListener('input',render);render();
    }
    load();
  }
  return {decorate};
}
