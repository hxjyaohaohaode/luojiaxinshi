import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {createMemoryStudio} from './memory-studio.js';
import {createMemoryWorkbench} from './memory-workbench.js';
import {createMemoryAssist} from './memory-assist.js';
const scopes={global:'跨项目通用',project:'仅此项目',topic:'仅选定专题'};
const kinds={preference:'表达与做事偏好',constraint:'约束与边界',decision:'已确认决定',fact:'本人提供的信息',episode:'经历与办理记录',skill:'技能与方法',intention:'待办与计划',summary:'分类概览'};
const states={inactive:'已停用',expired:'已过期',scheduled:'尚未生效',conflict:'冲突待处理',pending:'等待本人核对',source_changed:'来源已变化，暂不调用',cooling:'已冷却，暂停调用',needs_review:'需要重新确认',archived:'已归档，暂停调用'};
const exclusion={...states,shadowed:'由更具体范围覆盖',duplicate:'重复内容已合并',source_changed:'来源已变化，概览待更新'};
const dateValue=value=>{if(value==null)return '';const d=new Date(value*1000),pad=v=>String(v).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;};
const timestamp=value=>value?Math.floor(new Date(value).getTime()/1000):null;

export function createMemoryUI({state,api,esc,icon,showDialog,toast,ask}){
  let data={projects:[],memories:[]};
  const studio=createMemoryStudio({state,api,esc,showDialog,toast,ask,refresh:()=>render()});
  const workbench=createMemoryWorkbench({state,api,esc,icon,studio,onCatalog:value=>{data=value;},toast,ask});
  createMemoryAssist({state,api,esc,showDialog,toast,refresh:()=>render()});
  const guard=()=>{const route=state.renderId,user=state.session?.user?.id,dialog=state.dialogRequest;return ()=>state.renderId===route&&state.session?.user?.id===user&&state.dialogRequest===dialog;};
  const $=selector=>document.querySelector(selector);
  const button=(text,action,id='')=>`<button type="button" class="button small" data-memory-action="${action}" data-id="${esc(id)}">${text}</button>`;
  const options=(items,value)=>Object.entries(items).map(([key,label])=>`<option value="${esc(key)}" ${key===value?'selected':''}>${esc(label)}</option>`).join('');
  async function render(){return workbench.render();}
  async function editor(item={},conversation=null){
    const current=guard(),[catalog,fresh,impact]=await Promise.all([api('/memory'),item.id?api('/memory/items/'+encodeURIComponent(item.id)):Promise.resolve(item),item.id?api('/memory/items/'+encodeURIComponent(item.id)+'/impact'):Promise.resolve(null)]);if(!current())return;item=fresh;data={...data,projects:catalog.projects,topics:catalog.topics};
    const context=conversation?.context||{};
    const entry={scope:context.project_id?'project':'global',project_id:context.project_id||null,kind:'preference',active:true,pinned:false,topic:'',content:'',...item};
    showDialog(item.id?'修改记忆':'确认保存为记忆',`<form class="stack" data-workspace-form="memory-entry"><div class="form-grid"><label class="field">使用范围<select name="scope">${options(scopes,entry.scope)}</select></label><label class="field">内容类型<select name="kind">${options(kinds,entry.kind)}</select></label><label class="field" data-project-field>所属项目<select name="project_id"><option value="">选择项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),entry.project_id)}</select></label><label class="field" data-topic-field>专题名称<input name="topic" maxlength="60" value="${esc(entry.topic)}" placeholder="例如：论文写作、课程规划"></label></div><label class="field">希望记住什么<textarea name="content" rows="5" maxlength="2000" required>${esc(entry.content)}</textarea></label><label class="check"><input name="pinned" type="checkbox" ${entry.pinned?'checked':''}><span>在选定范围内优先使用</span></label><p class="small muted">记忆是你提供的背景，不能替代通知原文。请避免写入密码、密钥或无关的个人信息。${conversation?'这条记忆关联本对话，删除原对话时也会删除。':''}</p><div class="form-footer"><button class="button primary" type="submit">确认保存</button></div></form>`);
    const form=$('[data-workspace-form="memory-entry"]');
    const advanced=document.createElement('details');advanced.className='memory-policy';advanced.innerHTML='<summary>调整分类与使用范围（可选）</summary>';advanced.append(form.querySelector('.form-grid'));form.querySelector('.form-footer').before(advanced);
    if(impact)form.insertAdjacentHTML('afterbegin',`<p class="memory-edit-impact">正在修订第 ${item.version} 版 · ${impact.derived_count} 条派生记录 · 曾提供给 ${impact.answer_count} 次回答。正文或范围改变后，派生依据需要重新核对。</p>`);
    if(item.id&&(item.status!=='active'||!item.active))form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<label class="check"><input type="checkbox" name="reactivate"><span>我已核对，保存时重新启用这条记忆</span></label><p class="small muted">单独编辑正文会保留当前的归档、冷却或停用状态。</p>`);
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<label class="field">整理标签<input name="labels" maxlength="328" value="${esc((entry.labels||[]).join('，'))}" placeholder="用逗号分隔，最多 8 个标签"></label><label class="check"><input type="checkbox" name="locked" checked><span>保护我的编辑；明确要求更正时可自动更新</span></label>`);
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>有效期与同类记忆</summary><label class="field">同类键（可选）<input name="semantic_key" maxlength="80" value="${esc(entry.semantic_key||'')}" placeholder="例如：写作语言、常用校区"></label><p class="small muted">给只能有一个当前值的信息使用同一个键。项目范围优先于专题，专题优先于通用；同一层级有不同值时先暂停调用。没有填键的内容不会自动判断语义冲突。</p><div class="form-grid"><label class="field">生效时间<input name="valid_from" type="datetime-local" value="${dateValue(entry.valid_from)}"></label><label class="field">失效时间<input name="expires_at" type="datetime-local" value="${dateValue(entry.expires_at)}"></label></div><p class="small muted">按本机时区填写。留空表示立即生效或长期有效，失效后仍保留记录供你核对。</p></details>`);
    function fields(){const scope=form.elements.scope.value;form.querySelector('[data-project-field]').hidden=scope!=='project';form.elements.project_id.required=scope==='project';form.querySelector('[data-topic-field]').hidden=scope!=='topic';form.elements.topic.required=scope==='topic';}
    form.elements.scope.addEventListener('change',fields);fields();
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form),scope=fd.get('scope');await submit(form,async()=>{
      const payload={scope,project_id:scope==='project'?fd.get('project_id'):null,topic:scope==='topic'?fd.get('topic'):'',kind:fd.get('kind'),content:fd.get('content'),active:fd.has('reactivate')||!!entry.active,pinned:fd.has('pinned'),source_conversation_id:item.source_conversation_id||conversation?.id||null,locked:fd.has('locked'),labels:fd.get('labels').split(/[,，]/).map(s=>s.trim()).filter(Boolean),semantic_key:fd.get('semantic_key'),valid_from:timestamp(fd.get('valid_from')),expires_at:timestamp(fd.get('expires_at')),...(item.id?{version:item.version,reactivate:fd.has('reactivate')}:{})};
      return workbench.write('/memory/items'+(item.id?'/'+item.id:''),payload,item.id?'PUT':'POST');
    },'记忆已保存，后续回答按范围和状态使用。');});
  }
  async function projectEditor(item={}){
    showDialog(item.id?'修改项目':'新建项目',`<form class="stack" data-workspace-form="memory-project"><label class="field">项目名称<input name="name" required maxlength="80" value="${esc(item.name||'')}"></label><label class="field">项目说明<textarea name="description" rows="3" maxlength="1000">${esc(item.description||'')}</textarea></label><div class="form-footer"><button class="button primary" type="submit">保存项目</button></div></form>`);
    const form=$('[data-workspace-form="memory-project"]');if(item.id)form.querySelector('.form-footer').insertAdjacentHTML('afterbegin',`<button type="button" class="button danger" data-memory-action="project-delete" data-id="${esc(item.id)}">删除项目</button>`);form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,()=>api('/memory/projects'+(item.id?'/'+item.id:''),{method:item.id?'PUT':'POST',json:{...Object.fromEntries(fd),...(item.id?{version:item.version}:{})}}),'项目已保存。');});
  }
  async function submit(form,work,success=''){
    const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.inert=true;
    try{await work();if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash==='#memory')await render();if(success&&view.sameUser())toast(success);}
    catch(e){if(view.sameUser())toast(e.message,true);}finally{form.inert=false;finishFeedback();}
  }
  async function context(cid,onSaved){
    const current=guard();
    const [saved,catalog,preview]=await Promise.all([api(`/conversations/${cid}/context`),api('/memory'),api(`/conversations/${cid}/memory-preview`)]);if(!current())return;data=catalog;
    showDialog('本次对话的项目与记忆',`<form class="stack" data-workspace-form="memory-context"><label class="field">记忆选择方式<select name="selection_mode"><option value="auto" ${saved.selection_mode==='auto'?'selected':''}>AI 自动选择相关项目与专题</option><option value="manual" ${saved.selection_mode==='manual'?'selected':''}>手动限定使用范围</option></select></label><p class="small muted">默认由 AI 根据当前问题寻找相关记忆，自动排除不适用、过期和来源变化的内容。不同项目的背景会分别使用。</p><div data-memory-manual><label class="field">所属项目<select name="project_id"><option value="">不属于特定项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),saved.project_id)}</select></label><label class="field">使用哪些专题记忆<input name="topics" maxlength="480" value="${esc(saved.topics.join('，'))}" placeholder="用逗号分隔，最多 8 个专题" list="memory-topics"></label><datalist id="memory-topics">${(data.topics||[]).map(t=>`<option value="${esc(t)}"></option>`).join('')}</datalist></div><label class="check"><input name="memory_enabled" type="checkbox" ${saved.memory_enabled?'checked':''}><span>允许使用已保存的相关记忆</span></label><p class="small muted">关闭记忆后，原聊天历史和当前附件仍可用于本对话。</p><a href="#memory" data-memory-action="open">管理全部记忆与项目</a><div class="form-footer"><button class="button primary" type="submit">保存设置</button></div></form>`);
    const form=$('[data-workspace-form="memory-context"]');
    const mode=form.elements.selection_mode;const toggleManual=()=>{form.querySelector('[data-memory-manual]').hidden=mode.value!=='manual';};mode.addEventListener('change',toggleManual);toggleManual();
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',studio.workingButton(cid));
    const excluded=Object.entries(preview.excluded.reduce((counts,item)=>(counts[item.reason]=(counts[item.reason]||0)+1,counts),{}));
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>当前保存范围：${preview.enabled?preview.eligible.length+' 条候选记忆':'记忆已关闭'}</summary><p class="small muted">${esc(preview.note)}修改上方设置后，请保存并重新打开查看新范围。</p>${preview.eligible.slice(0,6).map(m=>`<p class="small">${esc(scopes[m.scope])} · ${esc(m.content)}</p>`).join('')}${preview.eligible.length>6?`<p class="small muted">另有 ${preview.eligible.length-6} 条，可在“我的记忆”查看。</p>`:''}${excluded.map(([reason,count])=>`<p class="small muted">${esc(exclusion[reason]||reason)}：${count} 条</p>`).join('')}</details>`);
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,async()=>{await api(`/conversations/${cid}/context`,{method:'PUT',json:{version:saved.version,selection_mode:fd.get('selection_mode'),project_id:fd.get('selection_mode')==='manual'?(fd.get('project_id')||null):null,topics:fd.get('selection_mode')==='manual'?fd.get('topics').split(/[,，\n]/):[],memory_enabled:fd.has('memory_enabled')}});await onSaved();toast('后续回答会使用新的范围。');});});
  }
  document.addEventListener('click',async e=>{
    const target=e.target.closest('[data-memory-action]');if(!target||target.disabled)return;
    const action=target.dataset.memoryAction,id=target.dataset.id,view=captureUiContext(state,target);target.disabled=true;
    try{
      const item=data.memories.find(m=>m.id===id),project=data.projects.find(p=>p.id===id);
      if(action==='new')await editor();
      else if(action==='edit')await editor(item||await api('/memory/items/'+encodeURIComponent(id)));
      else if(action==='project-new')await projectEditor();
      else if(action==='project-edit')await projectEditor(project);
      else if(action==='open')$('#dialog').close();
      else if(action==='toggle'){
        if(!item)throw Error('条目已变化，请重新载入。');
        if(!item.active||item.status!=='active')await workbench.write('/memory/bulk',{action:'activate',items:[{id:item.id,version:item.version}]});
        else {const {scope,project_id,topic,kind,content,source_conversation_id,pinned,version,semantic_key,valid_from,expires_at,locked,labels}=item;
          await workbench.write('/memory/items/'+id,{scope,project_id,topic,kind,content,source_conversation_id,pinned,version,semantic_key,valid_from,expires_at,locked,labels,active:false},'PUT');}
        if(view.sameRoute())await render();
      }else if(action==='resolve'){
        if(!item)throw Error('条目已变化，请重新载入。');
        const conflicts=await api('/memory/items/'+id+'/conflicts');if(!view.sameRoute())return;
        if(!await ask('核对同类记忆',`将保留这条记忆，停用同一范围内另外 ${conflicts.total-1} 条不同说法。请先在来源与历史中核对正文。`,'确认保留'))return;
        if(!view.sameUser())return;
        await api('/memory/items/'+id+'/resolve',{method:'POST',json:{versions:conflicts.versions}});
        if(view.sameRoute())await render();
      }else if(action==='delete'){
        if(!item)throw Error('条目已变化，请重新载入。');
        if(!await ask('遗忘这条记忆','将移除这条记忆及其派生内容，并撤销相关旧回答的后续记忆用途。原聊天和离线备份仍保留。','确认遗忘'))return;
        if(!view.sameUser())return;
        await workbench.write('/memory/items/'+id,{version:item.version},'DELETE');
        if(view.sameRoute())await render();
      }else if(action==='project-delete'){
        if(!project)throw Error('项目已变化，请重新载入。');
        if(!await ask('删除项目','将删除此项目及其专属记忆，对话和材料继续保留。通用与专题记忆不受影响。','删除项目'))return;
        if(!view.sameUser())return;
        await api('/memory/projects/'+id,{method:'DELETE',json:{version:project.version}});
        if(view.sameUser())workbench.projectDeleted(id);
        if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render();
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {render,context,remember:conversation=>editor({content:conversation.messages.findLast(m=>m.role==='user')?.content.slice(0,2000)||''},conversation)};
}
