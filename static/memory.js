import {captureUiContext,beginFormFeedback} from './ui-request.js';
const scopes={global:'跨项目通用',project:'仅此项目',topic:'仅选定专题'};
const kinds={preference:'表达与做事偏好',constraint:'约束与边界',decision:'已确认决定',fact:'本人提供的信息'};
const states={inactive:'已停用',expired:'已过期',scheduled:'尚未生效',conflict:'冲突待处理'};
const exclusion={...states,shadowed:'由更具体范围覆盖',duplicate:'重复内容已合并'};
const dateValue=value=>{if(value==null)return '';const d=new Date(value*1000),pad=v=>String(v).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;};
const timestamp=value=>value?Math.floor(new Date(value).getTime()/1000):null;

export function createMemoryUI({state,api,esc,icon,showDialog,toast,ask}){
  let data={projects:[],memories:[]};
  const guard=()=>{const route=state.renderId,user=state.session?.user?.id,dialog=state.dialogRequest;return ()=>state.renderId===route&&state.session?.user?.id===user&&state.dialogRequest===dialog;};
  const $=s=>document.querySelector(s);
  const button=(text,action,id='')=>`<button type="button" class="button small" data-memory-action="${action}" data-id="${esc(id)}">${text}</button>`;
  const projectName=id=>data.projects.find(p=>p.id===id)?.name||'未选择项目';
  const options=(items,value)=>Object.entries(items).map(([key,label])=>`<option value="${esc(key)}" ${key===value?'selected':''}>${esc(label)}</option>`).join('');
  async function render(){
    const generation=state.renderId,user=state.session?.user?.id;
    if(location.hash!=='#memory')return;
    const catalog=await api('/memory');
    if(state.renderId!==generation||state.session?.user?.id!==user||location.hash!=='#memory')return;
    data=catalog;
    $('#content').innerHTML=`<div class="memory-page"><div class="page-heading"><div><a class="small" href="#settings">← 个人设置</a><h1>我的记忆</h1><p class="muted">让后续回答接上你的习惯、项目与决定。</p></div>${button(icon('plus')+' 新建记忆','new')}</div>
      <p class="memory-note">只有你确认保存的内容会进入长期记忆。通用记忆可跨项目使用，项目与专题记忆只在选定范围生效。新要求优先；你可以随时停用、修改或删除。</p>
      <section class="memory-projects"><div class="between"><h2>项目</h2>${button('新建项目','project-new')}</div><div class="memory-project-list">${data.projects.map(p=>`<article class="memory-project"><strong>${esc(p.name)}</strong><p>${esc(p.description||'在对话的“项目与记忆”中选择此项目。')}</p><div class="row">${button('编辑','project-edit',p.id)}${button('删除','project-delete',p.id)}</div></article>`).join('')||'<p class="muted">还没有项目。课程、比赛或申请事项可以各建一个。</p>'}</div></section>
      <div class="between"><h2>已保存的记忆 <span class="muted">${data.memories.length}</span></h2><label class="memory-filter">查找记忆<input type="search" id="memory-search" placeholder="搜索内容、项目或专题"></label></div><div id="memory-items" class="memory-items">${cards(data.memories)}</div></div>`;
    $('#memory-search').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();$('#memory-items').innerHTML=cards(data.memories.filter(m=>(m.content+' '+m.topic+' '+projectName(m.project_id)).toLowerCase().includes(q)));});
  }
  function cards(items){return items.map(m=>`<article class="memory-card ${m.state&&m.state!=='active'?'memory-inactive':''}"><div class="row"><span class="pill">${esc(scopes[m.scope])}</span><span class="small muted">${esc(m.scope==='project'?projectName(m.project_id):m.topic||kinds[m.kind])}</span>${m.pinned?'<span class="pill">优先使用</span>':''}${states[m.state]?`<span class="pill">${states[m.state]}</span>`:''}</div><p class="memory-content">${esc(m.content)}</p>${m.semantic_key?`<p class="small muted">同类键：${esc(m.semantic_key)}</p>`:''}${m.valid_from!=null||m.expires_at!=null?`<p class="small muted">${m.valid_from!=null?'生效：'+esc(new Date(m.valid_from*1000).toLocaleString()):'立即生效'}<br>${m.expires_at!=null?'失效：'+esc(new Date(m.expires_at*1000).toLocaleString()):'长期有效'}</p>`:''}${m.state==='conflict'?`<p class="memory-conflict">同范围有不同内容的同类记忆，暂不调用。可修改内容、停用旧记录，或明确保留这一条。</p>${button('保留此条并停用冲突项','resolve',m.id)}`:''}<div class="between"><small class="muted">${esc(kinds[m.kind])} · 第 ${m.version} 版</small><div class="row">${button('修改','edit',m.id)}${button(m.active?'停用':'启用','toggle',m.id)}${button('删除','delete',m.id)}</div></div></article>`).join('')||'<div class="memory-empty"><strong>暂时没有匹配的记忆</strong><p>保存常用表达偏好、项目边界或已确认的决定，下一次对话即可按范围使用。</p></div>';}
  async function editor(item={},conversation=null){
    const current=guard(),catalog=await api('/memory');if(!current())return;data=catalog;
    const context=conversation?.context||{};
    const entry={scope:context.project_id?'project':'global',project_id:context.project_id||null,kind:'preference',active:true,pinned:false,topic:'',content:'',...item};
    showDialog(item.id?'修改记忆':'确认保存为记忆',`<form class="stack" data-workspace-form="memory-entry"><div class="form-grid"><label class="field">使用范围<select name="scope">${options(scopes,entry.scope)}</select></label><label class="field">内容类型<select name="kind">${options(kinds,entry.kind)}</select></label><label class="field" data-project-field>所属项目<select name="project_id"><option value="">选择项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),entry.project_id)}</select></label><label class="field" data-topic-field>专题名称<input name="topic" maxlength="60" value="${esc(entry.topic)}" placeholder="例如：论文写作、课程规划"></label></div><label class="field">希望记住什么<textarea name="content" rows="5" maxlength="2000" required>${esc(entry.content)}</textarea></label><label class="check"><input name="pinned" type="checkbox" ${entry.pinned?'checked':''}><span>在选定范围内优先使用</span></label><p class="small muted">记忆是你提供的背景，不能替代通知原文。请避免写入密码、密钥或无关的个人信息。${conversation?'这条记忆关联本对话，删除原对话时也会删除。':''}</p><div class="form-footer"><button class="button primary" type="submit">确认保存</button></div></form>`);
    const form=$('[data-workspace-form="memory-entry"]');
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>有效期与同类记忆</summary><label class="field">同类键（可选）<input name="semantic_key" maxlength="80" value="${esc(entry.semantic_key||'')}" placeholder="例如：写作语言、常用校区"></label><p class="small muted">给只能有一个当前值的信息使用同一个键。项目范围优先于专题，专题优先于通用；同一层级有不同值时先暂停调用。没有填键的内容不会自动判断语义冲突。</p><div class="form-grid"><label class="field">生效时间<input name="valid_from" type="datetime-local" value="${dateValue(entry.valid_from)}"></label><label class="field">失效时间<input name="expires_at" type="datetime-local" value="${dateValue(entry.expires_at)}"></label></div><p class="small muted">按本机时区填写。留空表示立即生效或长期有效，失效后仍保留记录供你核对。</p></details>`);
    function fields(){const scope=form.elements.scope.value;form.querySelector('[data-project-field]').hidden=scope!=='project';form.elements.project_id.required=scope==='project';form.querySelector('[data-topic-field]').hidden=scope!=='topic';form.elements.topic.required=scope==='topic';}
    form.elements.scope.addEventListener('change',fields);fields();
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form),scope=fd.get('scope');await submit(form,async()=>{
      const payload={scope,project_id:scope==='project'?fd.get('project_id'):null,topic:scope==='topic'?fd.get('topic'):'',kind:fd.get('kind'),content:fd.get('content'),active:!!entry.active,pinned:fd.has('pinned'),source_conversation_id:item.source_conversation_id||conversation?.id||null,semantic_key:fd.get('semantic_key'),valid_from:timestamp(fd.get('valid_from')),expires_at:timestamp(fd.get('expires_at')),...(item.id?{version:item.version}:{})};
      await api('/memory/items'+(item.id?'/'+item.id:''),{method:item.id?'PUT':'POST',json:payload});toast('记忆已保存，后续回答按范围使用。');
    });});
  }
  async function projectEditor(item={}){
    showDialog(item.id?'修改项目':'新建项目',`<form class="stack" data-workspace-form="memory-project"><label class="field">项目名称<input name="name" required maxlength="80" value="${esc(item.name||'')}"></label><label class="field">项目说明<textarea name="description" rows="3" maxlength="1000">${esc(item.description||'')}</textarea></label><div class="form-footer"><button class="button primary" type="submit">保存项目</button></div></form>`);
    const form=$('[data-workspace-form="memory-project"]');form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,async()=>{await api('/memory/projects'+(item.id?'/'+item.id:''),{method:item.id?'PUT':'POST',json:{...Object.fromEntries(fd),...(item.id?{version:item.version}:{})}});toast('项目已保存。');});});
  }
  async function submit(form,work){
    const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.inert=true;
    try{await work();if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash==='#memory')await render();}
    catch(e){if(view.sameUser())toast(e.message,true);}finally{form.inert=false;finishFeedback();}
  }
  async function context(cid,onSaved){
    const current=guard();
    const [saved,catalog,preview]=await Promise.all([api(`/conversations/${cid}/context`),api('/memory'),api(`/conversations/${cid}/memory-preview`)]);if(!current())return;data=catalog;
    showDialog('本次对话的项目与记忆',`<form class="stack" data-workspace-form="memory-context"><label class="field">所属项目<select name="project_id"><option value="">不属于特定项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),saved.project_id)}</select></label><label class="field">使用哪些专题记忆<input name="topics" maxlength="480" value="${esc(saved.topics.join('，'))}" placeholder="用逗号分隔，最多 8 个专题" list="memory-topics"></label><datalist id="memory-topics">${[...new Set(data.memories.map(m=>m.topic).filter(Boolean))].map(t=>`<option value="${esc(t)}"></option>`).join('')}</datalist><label class="check"><input name="memory_enabled" type="checkbox" ${saved.memory_enabled?'checked':''}><span>允许使用已保存的相关记忆</span></label><p class="small muted">启用时会使用通用记忆、此项目记忆和选定专题记忆；不使用其他项目的记忆。关闭后，原聊天历史和当前附件仍可用于本对话。</p><a href="#memory" data-memory-action="open">管理全部记忆与项目</a><div class="form-footer"><button class="button primary" type="submit">保存设置</button></div></form>`);
    const form=$('[data-workspace-form="memory-context"]');
    const excluded=Object.entries(preview.excluded.reduce((counts,item)=>(counts[item.reason]=(counts[item.reason]||0)+1,counts),{}));
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>当前保存范围：${preview.enabled?preview.eligible.length+' 条候选记忆':'记忆已关闭'}</summary><p class="small muted">${esc(preview.note)}修改上方设置后，请保存并重新打开查看新范围。</p>${preview.eligible.slice(0,6).map(m=>`<p class="small">${esc(scopes[m.scope])} · ${esc(m.content)}</p>`).join('')}${preview.eligible.length>6?`<p class="small muted">另有 ${preview.eligible.length-6} 条，可在“我的记忆”查看。</p>`:''}${excluded.map(([reason,count])=>`<p class="small muted">${esc(exclusion[reason]||reason)}：${count} 条</p>`).join('')}</details>`);
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,async()=>{await api(`/conversations/${cid}/context`,{method:'PUT',json:{version:saved.version,project_id:fd.get('project_id')||null,topics:fd.get('topics').split(/[,，\n]/),memory_enabled:fd.has('memory_enabled')}});await onSaved();toast('后续回答会使用新的范围。');});});
  }
  document.addEventListener('click',async e=>{const target=e.target.closest('[data-memory-action]');if(!target)return;const action=target.dataset.memoryAction,id=target.dataset.id;if(target.disabled)return;target.disabled=true;try{
    const item=data.memories.find(m=>m.id===id),project=data.projects.find(p=>p.id===id);
    if(action==='new')await editor();else if(action==='edit')await editor(item);else if(action==='project-new')await projectEditor();else if(action==='project-edit')await projectEditor(project);
    else if(action==='open')$('#dialog').close();
    else if(action==='toggle'){const {scope,project_id,topic,kind,content,source_conversation_id,pinned,version,semantic_key,valid_from,expires_at}=item;await api('/memory/items/'+id,{method:'PUT',json:{scope,project_id,topic,kind,content,source_conversation_id,pinned:!!pinned,active:!item.active,version,semantic_key,valid_from,expires_at}});await render();}
    else if(action==='resolve'){
      const peers=data.memories.filter(m=>m.id===id||item.conflicts.includes(m.id));
      if(await ask('保留当前记忆',`保留“${item.content}”。将停用同范围的 ${peers.length-1} 条冲突记忆，停用后仍可在列表核对。`,'保留此条')){
        await api('/memory/items/'+id+'/resolve',{method:'POST',json:{versions:Object.fromEntries(peers.map(m=>[m.id,m.version]))}});await render();toast('冲突已处理，后续按保留的内容使用。');
      }
    }
    else if(action==='delete'&&await ask('删除这条记忆','后续回答不再主动使用这条保存的记忆。原对话内容仍在，可另行删除。','删除记忆')){await api('/memory/items/'+id,{method:'DELETE',json:{version:item.version}});await render();}
    else if(action==='project-delete'&&await ask('删除项目','将删除此项目及其专属记忆，对话和材料继续保留。通用与专题记忆不受影响。','删除项目')){await api('/memory/projects/'+id,{method:'DELETE',json:{version:project.version}});await render();}
  }catch(error){toast(error.message,true);}finally{target.disabled=false;}});
  return {render,context,remember:conversation=>editor({content:conversation.messages.findLast(m=>m.role==='user')?.content.slice(0,2000)||''},conversation)};
}
