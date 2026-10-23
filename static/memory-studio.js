import {captureUiContext} from './ui-request.js';
import {createLifecycleUI} from './memory-lifecycle.js';
import {memoryTimestamp} from './memory-list-text.js';

const modes={auto:'自动记忆',manual:'只手动保存',off:'暂停全部记忆'};
const origins={resource:'资料自动整理',source_claim:'AI 资料提炼',manual:'我保存的',automatic:'对话原话',agent:'AI 整理',organizer:'自动概览',reflection:'AI 回顾建议',task:'办理记录',import:'文件导入'};
const stamp=value=>memoryTimestamp(value,true)||'—';

export function createMemoryStudio({state,api,esc,showDialog,toast,ask,refresh}){
  const lifecycle=createLifecycleUI({state,api,esc,showDialog,toast,ask,refresh});
  const $=selector=>document.querySelector(selector);
  const button=(label,action,id='')=>`<button type="button" class="button small" data-memory-studio="${action}" data-id="${esc(id)}">${label}</button>`;
  let settings={mode:'auto',auto_organize:true,learn_tasks:true,version:0};
  function configure(data){settings=data.settings||settings;lifecycle.panel(data);}
  function panel(data){
    configure(data);
    return `<section class="memory-management-hub" aria-label="记忆管理">
      <div class="memory-hub-status"><span class="memory-mode-dot" aria-hidden="true"></span><strong>${esc(modes[settings.mode]||'自动记忆')}</strong>${button('记忆设置','settings')}</div>
      <section><h3>自动维护</h3><div class="memory-hub-actions">${button('现在整理','organize')}${button('整理旧对话','backfill')}${button('整理进度','jobs')}</div></section>
      <section><h3>使用与保留</h3><div class="memory-hub-actions"><button type="button" class="button small" data-memory-action="project-manage">项目管理</button></div>${lifecycle.panel(data)}</section>
      <section><h3>导入与导出</h3><div class="memory-hub-actions">${button('导出记忆','export')}${button('导入编辑文件','import')}</div><input type="file" id="memory-import-file" accept=".json,.md,text/markdown,application/json" hidden></section>
    </section>`;
  }
  function management(data){showDialog('记忆管理',panel(data));}
  function meta(item){
    return `<div class="memory-provenance"><span>${esc(origins[item.origin]||'我保存的')}</span>${item.locked?'<span>我锁定的</span>':''}${(item.labels||[]).map(label=>`<span>${esc(label)}</span>`).join('')}</div>`;
  }
  function controls(item){
    return `${item.origin==='resource'&&(item.state==='source_changed'||item.locked)?'<p class="small muted">这条保留着你改过的内容。可以按现在的原资料重新整理，之后会自动跟着原资料更新；以前的版本都还在。</p>'+button('按原资料重新整理','source-sync',item.id):''}<details class="memory-record-tools"><summary>层级、范围与导出</summary><div class="memory-studio-actions">${lifecycle.controls(item)}${button('导出 Markdown','markdown',item.id)}</div></details>`;
  }
  function download(content,name,type){
    const url=URL.createObjectURL(new Blob([content],{type})),anchor=document.createElement('a');
    anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function detail(id){
    const user=state.session?.user?.id,generation=state.renderId,request=state.dialogRequest;
    const [item,impact]=await Promise.all([api('/memory/items/'+id),api('/memory/items/'+id+'/impact')]);
    if(user!==state.session?.user?.id||generation!==state.renderId||request!==state.dialogRequest)return;
    showDialog('记忆来源与版本',`<div class="memory-detail"><p class="memory-detail-version">当前第 ${item.version} 版 · ${esc(stamp(item.updated_at))}</p><p class="memory-content memory-detail-current">${esc(item.content)}</p>${meta(item)}<div class="memory-impact-facts"><span>相关整理 <strong>${impact.derived_count}</strong></span><span>用在过的回答 <strong>${impact.answer_count}</strong></span><span>依据检查：${esc({current:'依据还在',changed:'需要再看看',not_checked:'目前暂停使用'}[impact.source_check]||'待检查')}</span></div>
      <h3>从哪来的</h3>${item.evidence.length?item.evidence.map(e=>`<blockquote><p>${esc(e.quote)}</p><footer>${esc(({message:'我在对话里说的',task:'我的办事记录',resource_notice:'通知资料',resource_material:'上传资料',resource_project:'项目说明'}[e.source_kind]||'关联来源'))} · ${esc(stamp(e.created_at))} · ${esc({available:'来源还在',changed:'来源改过了',missing:'来源已经没了'}[e.source_status]||'待核对')}${e.conversation_id?` · <a href="#chat/${encodeURIComponent(e.conversation_id)}" data-memory-studio="source">查看来源对话</a>`:''}${e.notice_id?` · <a href="#notice/${encodeURIComponent(e.notice_id)}" data-memory-studio="source">查看通知原文</a>`:''}</footer></blockquote>`).join(''):'<p class="muted">没有关联的原始记录，按你保存的内容来看就好。</p>'}
      ${item.links.length?`<h3>关联依据</h3>${item.links.map(link=>`<div class="memory-link"><span>${link.relation==='supersedes'?'准备替换':'记下时的来源'} · 第 ${link.parent_version} 版 · ${link.source_current?'依据没变':'依据变了，看一下'}</span><p>${esc(link.content)}</p>${link.current_version!==link.parent_version?`<small>来源当前已到第 ${link.current_version} 版</small>`:''}</div>`).join('')}`:''}
      ${item.imported_provenance?`<details class="memory-policy"><summary>导入文件里记的来源</summary><pre class="memory-import-history">${esc(JSON.stringify(item.imported_provenance,null,2).slice(0,12000))}</pre><p class="small muted">这里只是保留导入文件里写的来源，不会当成你账号里真实的对话或办事记录；导出时会一起带上。</p></details>`:''}<h3>修改历史</h3><ol class="memory-revision-list">${item.revisions.map((rev,index)=>`<li><details class="memory-policy" ${index===0?'open':''}><summary>第 ${rev.version} 版 · ${esc(stamp(rev.created_at))} · ${esc(rev.actor.startsWith('user')?'我改的':origins[rev.actor]||rev.actor)}</summary><p class="memory-content">${esc(rev.snapshot.content)}</p>${item.revisions[index+1]&&rev.snapshot.content!==item.revisions[index+1].snapshot.content?`<details class="memory-revision-comparison"><summary>和上一版对比</summary><div><strong>修改前</strong><p class="memory-content">${esc(item.revisions[index+1].snapshot.content)}</p><strong>修改后</strong><p class="memory-content">${esc(rev.snapshot.content)}</p></div></details>`:''}${rev.version!==item.version?`<button type="button" class="button small" data-memory-restore="${rev.version}" data-id="${esc(item.id)}" data-version="${item.version}">恢复这一版</button>`:'<p class="small muted">当前版本</p>'}</details></li>`).join('')}</ol>
      <p class="small muted">恢复会存成一个新版本。永久删除会把这条记忆的历史和相关概览一起删掉，删了就找不回来；原对话要另外删。</p></div>`);
  }
  function settingsDialog(){
    showDialog('记忆设置',`<form class="stack" id="memory-settings-form"><label class="field">记忆方式<select name="mode">${Object.entries(modes).map(([key,label])=>`<option value="${key}" ${key===settings.mode?'selected':''}>${label}</option>`).join('')}</select></label><p class="small muted">自动记忆只记你明确说过的话；依据不够时会先不用、自动检查或归档。只手动保存时，已有记忆照常能用；暂停全部记忆后，既不会用，也不会再记新的。</p><label class="check"><input type="checkbox" name="auto_organize" ${settings.auto_organize?'checked':''}><span>后台自动整理分类概览，每条原始记忆都保留</span></label><label class="check"><input type="checkbox" name="learn_tasks" ${settings.learn_tasks?'checked':''}><span>把我的办事进度记成待办和经历</span></label><p class="small muted">后台整理在本地完成，不会额外花 AI 额度；AI 只会在你已同意的回答里顺带提出记忆修改。</p><div class="form-footer"><button type="submit" class="button primary">保存设置</button></div></form>`);
    const form=$('#memory-settings-form'),version=settings.version,before={mode:settings.mode,auto_organize:settings.auto_organize,learn_tasks:settings.learn_tasks};
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{const saved=await api('/memory/settings',{method:'PUT',json:{version,mode:fd.get('mode'),auto_organize:fd.has('auto_organize'),learn_tasks:fd.has('learn_tasks')}});if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('设置存好了。',false,{duration:15000,action:{label:'撤销',run:async()=>{if(!view.sameUser())throw Error('账号切换了，没法撤销原账号的设置。');await api('/memory/settings',{method:'PUT',json:{...before,version:saved.version}});if(view.sameRoute())await refresh();}}});}catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function working(cid){
    const user=state.session?.user?.id,generation=state.renderId,request=state.dialogRequest;
    const item=await api(`/conversations/${cid}/working-memory`);
    if(user!==state.session?.user?.id||generation!==state.renderId||request!==state.dialogRequest)return;
    showDialog('这个对话的工作记忆',`<form class="stack" id="memory-working-form"><p class="small muted">记着这次的目标、计划和还没解决的问题。锁定后，自动更新不会覆盖你改过的内容。</p><label class="field">当前目标与进度<textarea name="content" rows="10" maxlength="4000">${esc(item.content)}</textarea></label><label class="check"><input type="checkbox" name="locked" ${item.locked?'checked':''}><span>锁定我的修改，不被自动更新覆盖</span></label><div class="form-footer"><button class="button primary" type="submit">保存工作记忆</button></div></form>`);
    const form=$('#memory-working-form');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{await api(`/conversations/${cid}/working-memory`,{method:'PUT',json:{version:item.version,content:fd.get('content'),locked:fd.has('locked')}});if(view.sameUser()){if(view.sameDialog())$('#dialog').close();toast('工作记忆存好了。');}}catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-memory-studio],[data-memory-restore]');if(!target||target.disabled)return;
    const action=target.dataset.memoryStudio,id=target.dataset.id,view=captureUiContext(state,target);target.disabled=true;
    try{
      if(target.dataset.memoryRestore){
        if(!await ask('恢复历史版本','会把这一版存成最新版本，启用或暂停状态不变，修改记录也都还在。','恢复版本'))return;
        await api(`/memory/items/${id}/restore`,{method:'POST',json:{version:Number(target.dataset.version),revision:Number(target.dataset.memoryRestore)}});if(view.sameUser()){if(view.sameRoute())await refresh();toast('已恢复，现在是最新版本了。');}
      }else if(action==='settings')settingsDialog();
      else if(action==='detail')await detail(id);
      else if(action==='source-sync'){const item=await api('/memory/items/'+id);await api('/memory/items/'+id+'/source-sync',{method:'POST',json:{version:item.version}});if(view.sameUser()){if(view.sameRoute())await refresh();toast('已按原资料重新整理，之后会自动跟着原资料更新。');}}
      else if(action==='source')$('#dialog').close();
      else if(action==='working')await working(id);
      else if(action==='import')$('#memory-import-file').click();
      else if(action==='export'){const data=await api('/memory/export');if(view.sameUser())download(JSON.stringify(data,null,2),'我的记忆.json','application/json');}
      else if(action==='markdown'){
        const item=await api('/memory/items/'+id);
        if(!view.sameUser())return;
        const header=Object.fromEntries(['id','version','scope','project_id','topic','kind','semantic_key','valid_from','expires_at','labels'].map(key=>[key,item[key]]));
        download('---\n'+JSON.stringify({format:'campus-memory-v1',...header})+'\n---\n'+item.content,`记忆-${id}.md`,'text/markdown');
      }else if(action==='accept'||action==='reject'){
        const item=await api('/memory/items/'+id);if(!view.sameUser())return;
        await api(`/memory/items/${id}/review`,{method:'POST',json:{version:item.version,accept:action==='accept'}});
        if(view.sameUser()){if(view.sameRoute())await refresh();toast(action==='accept'?'已采用，你确认的内容会被保护起来。':'这条建议已移除。');}
      }else if(action==='organize'||action==='backfill'){
        if(action==='backfill')await api('/memory/backfill',{method:'POST'});
        const result=await api('/memory/organize',{method:'POST'});
        if(view.sameUser()){if(view.sameRoute())await refresh();toast(`已处理 ${result.processed} 条记录，新增 ${result.created.length} 份概览，剩下的会在后台接着整理。`);}
      }else if(action==='retry'){const result=await api('/memory/jobs/retry',{method:'POST'});if(view.sameUser()){if(view.sameDialog())$('#dialog').close();toast(`已将 ${result.queued} 条记录重新排队整理。`);}}
      else if(action==='jobs'){
        const jobs=await api('/memory/jobs');if(!view.sameDialog())return;
        const names={queued:'待整理',done:'已处理',failed:'需处理'};
        showDialog('记忆整理状态',`<div class="stack">${Object.entries(jobs.counts).map(([key,count])=>`<p>${esc(names[key]||key)}：<strong>${count}</strong></p>`).join('')||'<p>没有要整理的记录，都处理好了。</p>'}<p class="small muted">后台会在空闲时分批整理。没整理成功的会单独标出来，不会当成已完成。</p>${jobs.counts.failed?button('重试没成功的','retry'):''}${jobs.recent.map(job=>`<p class="small">${esc(({message:'对话',task:'办理记录',resource_notice:'通知资料',resource_material:'上传资料',resource_project:'项目说明'}[job.source_kind]||'来源记录'))} · ${esc(names[job.state]||job.state)} · ${esc(stamp(job.created_at))}</p>`).join('')}</div>`);
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  document.addEventListener('change',async event=>{
    if(event.target.id!=='memory-import-file')return;
    const file=event.target.files?.[0];if(!file)return;
    const view=captureUiContext(state,event.target);
    try{if(file.size>20000000)throw new Error('记忆文件不能超过 20 MB。');const text=await file.text();if(!view.sameUser())return;const result=await api('/memory/import',{method:'POST',json:{text,format:file.name.toLowerCase().endsWith('.md')?'markdown':'json'}});if(view.sameUser()){if(view.sameRoute())await refresh();toast(`已处理 ${result.count} 条记忆。${result.note}`);}}catch(error){if(view.sameUser())toast(error.message,true);}finally{event.target.value='';}
  });
  return {panel,configure,management,meta,controls,workingButton:cid=>button('查看与编辑工作记忆','working',cid)};
}
