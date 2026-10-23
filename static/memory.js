import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {createMemoryStudio} from './memory-studio.js';
import {createMemoryWorkbench} from './memory-tree.js';
import {createMemoryAssist} from './memory-assist.js';
const scopes={global:'跨项目通用',project:'只用于这个项目',topic:'只用于选定专题'};
const kinds={preference:'说话和做事习惯',constraint:'限制和底线',decision:'定下来的事',fact:'我提供的信息',episode:'经历和办过的事',skill:'技能与方法',intention:'待办与计划',summary:'分类概览'};
const states={inactive:'已停用',expired:'已过期',scheduled:'还没生效',conflict:'有冲突，待处理',pending:'暂时不用',source_changed:'来源有变，先不用',cooling:'近期没用到，先暂停',needs_review:'自动检查中',archived:'已归档，先暂停'};
const exclusion={...states,shadowed:'被更具体的记忆代替',duplicate:'重复内容已合并',source_changed:'来源有变，概览稍后更新'};
const dateValue=value=>{if(value==null)return '';const d=new Date(value*1000),pad=v=>String(v).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;};
const timestamp=value=>value?Math.floor(new Date(value).getTime()/1000):null;

export function createMemoryUI({state,api,esc,icon,showDialog,toast,ask}){
  let data={projects:[],memories:[]};
  const studio=createMemoryStudio({state,api,esc,showDialog,toast,ask,refresh:()=>render()});
  const workbench=createMemoryWorkbench({state,api,esc,icon,studio,onCatalog:value=>{data=value;},toast,ask,showDialog});
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
    showDialog(item.id?'修改记忆':'记住这条',`<form class="stack" data-workspace-form="memory-entry"><div class="form-grid"><label class="field">使用范围<select name="scope">${options(scopes,entry.scope)}</select></label><label class="field">内容类型<select name="kind">${options(kinds,entry.kind)}</select></label><label class="field" data-project-field>所属项目<select name="project_id"><option value="">选择项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),entry.project_id)}</select></label><label class="field" data-topic-field>专题名称<input name="topic" maxlength="60" value="${esc(entry.topic)}" placeholder="例如：论文写作、课程规划"></label></div><label class="field">想让小信使记住什么<textarea name="content" rows="5" maxlength="2000" required>${esc(entry.content)}</textarea></label><label class="check"><input name="pinned" type="checkbox" ${entry.pinned?'checked':''}><span>在这个范围里优先用</span></label><p class="small muted">记忆只是给小信使的背景，具体要求还是看通知原文。别写密码、密钥这类敏感信息。${conversation?'这条记忆跟这个对话绑在一起，删掉对话时它也会一起删掉。':''}</p><div class="form-footer"><button class="button primary" type="submit">确认保存</button></div></form>`);
    const form=$('[data-workspace-form="memory-entry"]');
    const advanced=document.createElement('details');advanced.className='memory-policy';advanced.innerHTML='<summary>调整分类和范围（可选）</summary>';advanced.append(form.querySelector('.form-grid'));form.querySelector('.form-footer').before(advanced);
    if(impact)form.insertAdjacentHTML('afterbegin',`<p class="memory-edit-impact">这是第 ${item.version} 版 · ${impact.derived_count} 条相关整理 · 用在过 ${impact.answer_count} 次回答里。改了内容或范围后，相关整理会重新核对。</p>`);
    if(item.id&&(item.status!=='active'||!item.active))form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<label class="check"><input type="checkbox" name="reactivate"><span>我看过了，保存时重新启用这条记忆</span></label><p class="small muted">只改内容的话，它会保持现在的归档、暂停或停用状态。</p>`);
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<label class="field">标签<input name="labels" maxlength="328" value="${esc((entry.labels||[]).join('，'))}" placeholder="用逗号分隔，最多 8 个标签"></label><label class="check"><input type="checkbox" name="locked" checked><span>保留我改过的内容；我明确说要更正时才自动更新</span></label>`);
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>有效期与同类记忆</summary><label class="field">同类名称（可选）<input name="semantic_key" maxlength="80" value="${esc(entry.semantic_key||'')}" placeholder="例如：写作语言、常用校区"></label><p class="small muted">同一件事只能有一个答案时（比如常用校区），给它们填同一个名称。项目里的优先于专题，专题优先于通用；同一层有不同说法时会先暂停使用。不填就不会自动检查冲突。</p><div class="form-grid"><label class="field">生效时间<input name="valid_from" type="datetime-local" value="${dateValue(entry.valid_from)}"></label><label class="field">失效时间<input name="expires_at" type="datetime-local" value="${dateValue(entry.expires_at)}"></label></div><p class="small muted">按你设备的时区填。留空就是马上生效、一直有效；过期后记录还在，方便你回看。</p></details>`);
    function fields(){const scope=form.elements.scope.value;form.querySelector('[data-project-field]').hidden=scope!=='project';form.elements.project_id.required=scope==='project';form.querySelector('[data-topic-field]').hidden=scope!=='topic';form.elements.topic.required=scope==='topic';}
    form.elements.scope.addEventListener('change',fields);fields();
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form),scope=fd.get('scope');await submit(form,async()=>{
      const payload={scope,project_id:scope==='project'?fd.get('project_id'):null,topic:scope==='topic'?fd.get('topic'):'',kind:fd.get('kind'),content:fd.get('content'),active:fd.has('reactivate')||!!entry.active,pinned:fd.has('pinned'),source_conversation_id:item.source_conversation_id||conversation?.id||null,locked:fd.has('locked'),labels:fd.get('labels').split(/[,，]/).map(s=>s.trim()).filter(Boolean),semantic_key:fd.get('semantic_key'),valid_from:timestamp(fd.get('valid_from')),expires_at:timestamp(fd.get('expires_at')),...(item.id?{version:item.version,reactivate:fd.has('reactivate')}:{})};
      return workbench.write('/memory/items'+(item.id?'/'+item.id:''),payload,item.id?'PUT':'POST');
    },'记住了，之后相关的回答会用上它。');});
  }
  async function projectEditor(item={}){
    showDialog(item.id?'修改项目':'新建项目',`<form class="stack" data-workspace-form="memory-project"><label class="field">项目名称<input name="name" required maxlength="80" value="${esc(item.name||'')}"></label><label class="field">项目说明<textarea name="description" rows="3" maxlength="1000">${esc(item.description||'')}</textarea></label><div class="form-footer"><button class="button primary" type="submit">保存项目</button></div></form>`);
    const form=$('[data-workspace-form="memory-project"]');if(item.id)form.querySelector('.form-footer').insertAdjacentHTML('afterbegin',`<button type="button" class="button danger" data-memory-action="project-delete" data-id="${esc(item.id)}">删除项目</button>`);form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,()=>api('/memory/projects'+(item.id?'/'+item.id:''),{method:item.id?'PUT':'POST',json:{...Object.fromEntries(fd),...(item.id?{version:item.version}:{})}}),'项目存好了。');});
  }
  async function projectManagement(){
    const current=guard(),catalog=await api('/memory?limit=1');if(!current())return;data.projects=catalog.projects;
    showDialog('我的项目',`<div class="stack"><p class="small muted">AI 会根据对话自动建项目、选项目，你也可以在这里改名字或说明。</p><button class="button primary" data-memory-action="project-new">新建项目</button>${data.projects.map(p=>`<article class="memory-session-entry"><strong>${esc(p.name)}</strong><p class="memory-content small muted">${esc(p.description||'还没有说明')}</p><button class="button small" data-memory-action="project-edit" data-id="${esc(p.id)}">修改项目</button></article>`).join('')||'<p class="muted">还没有项目，直接聊就好，AI 会自动帮你建。</p>'}</div>`);
  }
  async function submit(form,work,success=''){
    const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.inert=true;
    try{await work();if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await render();if(success&&view.sameUser())toast(success);}
    catch(e){if(view.sameUser())toast(e.message,true);}finally{form.inert=false;finishFeedback();}
  }
  async function context(cid,onSaved){
    const current=guard();
    const [saved,catalog,preview]=await Promise.all([api(`/conversations/${cid}/context`),api('/memory'),api(`/conversations/${cid}/memory-preview`)]);if(!current())return;data=catalog;
    showDialog('这次对话用到的项目和记忆',`<form class="stack" data-workspace-form="memory-context"><label class="field">怎么选记忆<select name="selection_mode"><option value="auto" ${saved.selection_mode==='auto'?'selected':''}>让 AI 自动挑相关的项目和专题</option><option value="manual" ${saved.selection_mode==='manual'?'selected':''}>我自己指定范围</option></select></label><p class="small muted">默认由 AI 按你的问题找相关记忆，不适用、过期或来源有变的会自动跳过，不同项目的背景不会混在一起。</p><div data-memory-manual><label class="field">所属项目<select name="project_id"><option value="">不属于哪个项目</option>${options(Object.fromEntries(data.projects.map(p=>[p.id,p.name])),saved.project_id)}</select></label><label class="field">用哪些专题的记忆<input name="topics" maxlength="480" value="${esc(saved.topics.join('，'))}" placeholder="用逗号分隔，最多 8 个专题" list="memory-topics"></label><datalist id="memory-topics">${(data.topics||[]).map(t=>`<option value="${esc(t)}"></option>`).join('')}</datalist></div><label class="check"><input name="memory_enabled" type="checkbox" ${saved.memory_enabled?'checked':''}><span>允许用上我保存的相关记忆</span></label><p class="small muted">关掉记忆后，这个对话的聊天记录和附件还是照常能用。</p><a href="#memory" data-memory-action="open">管理所有记忆和项目</a><div class="form-footer"><button class="button primary" type="submit">保存设置</button></div></form>`);
    const form=$('[data-workspace-form="memory-context"]');
    const mode=form.elements.selection_mode;const toggleManual=()=>{form.querySelector('[data-memory-manual]').hidden=mode.value!=='manual';};mode.addEventListener('change',toggleManual);toggleManual();
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',studio.workingButton(cid));
    const excluded=Object.entries(preview.excluded.reduce((counts,item)=>(counts[item.reason]=(counts[item.reason]||0)+1,counts),{}));
    form.querySelector('.form-footer').insertAdjacentHTML('beforebegin',`<details class="memory-policy"><summary>目前会用到：${preview.enabled?preview.eligible.length+' 条记忆':'记忆已关闭'}</summary><p class="small muted">${esc(preview.note)}改了上面的设置，保存后重新打开就能看到新范围。</p>${preview.eligible.slice(0,6).map(m=>`<p class="small">${esc(scopes[m.scope])} · ${esc(m.content)}</p>`).join('')}${preview.eligible.length>6?`<p class="small muted">另有 ${preview.eligible.length-6} 条，去“我的记忆”里看。</p>`:''}${excluded.map(([reason,count])=>`<p class="small muted">${esc(exclusion[reason]||reason)}：${count} 条</p>`).join('')}</details>`);
    form.addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(form);await submit(form,async()=>{await api(`/conversations/${cid}/context`,{method:'PUT',json:{version:saved.version,selection_mode:fd.get('selection_mode'),project_id:fd.get('selection_mode')==='manual'?(fd.get('project_id')||null):null,topics:fd.get('selection_mode')==='manual'?fd.get('topics').split(/[,，\n]/):[],memory_enabled:fd.has('memory_enabled')}});await onSaved();toast('好了，之后的回答会按新范围来。');});});
  }
  document.addEventListener('click',async e=>{
    const target=e.target.closest('[data-memory-action]');if(!target||target.disabled)return;
    const action=target.dataset.memoryAction,id=target.dataset.id,view=captureUiContext(state,target);target.disabled=true;
    try{
      const item=data.memories.find(m=>m.id===id),project=data.projects.find(p=>p.id===id);
      if(action==='new')await editor();
      else if(action==='edit')await editor(item||await api('/memory/items/'+encodeURIComponent(id)));
      else if(action==='project-new')await projectEditor();
      else if(action==='project-manage')await projectManagement();
      else if(action==='project-edit')await projectEditor(project);
      else if(action==='open')$('#dialog').close();
      else if(action==='toggle'){
        if(!item)throw Error('这条内容在别的页面改过了，刷新看看最新的。');
        if(!item.active||item.status!=='active')await workbench.write('/memory/bulk',{action:'activate',items:[{id:item.id,version:item.version}]});
        else {const {scope,project_id,topic,kind,content,source_conversation_id,pinned,version,semantic_key,valid_from,expires_at,locked,labels}=item;
          await workbench.write('/memory/items/'+id,{scope,project_id,topic,kind,content,source_conversation_id,pinned,version,semantic_key,valid_from,expires_at,locked,labels,active:false},'PUT');}
        if(view.sameRoute())await render();
      }else if(action==='resolve'){
        if(!item)throw Error('这条内容在别的页面改过了，刷新看看最新的。');
        const conflicts=await api('/memory/items/'+id+'/conflicts');if(!view.sameRoute())return;
        if(!await ask('同类记忆说法不一',`会保留这条，停用同一范围里另外 ${conflicts.total-1} 条不同说法。拿不准的话，先去来源与历史里看看。`,'确认保留'))return;
        if(!view.sameUser())return;
        await api('/memory/items/'+id+'/resolve',{method:'POST',json:{versions:conflicts.versions}});
        if(view.sameRoute())await render();
      }else if(action==='delete'){
        if(!item)throw Error('这条内容在别的页面改过了，刷新看看最新的。');
        if(!await ask('遗忘这条记忆','这条记忆和由它整理出的内容都会被删掉，以后的回答也不会再用它。'+(['resource','source_claim','task'].includes(item.origin)?'相关资料或任务也不会再自动生成记忆。':'')+'原资料、聊天记录和离线备份都还在。','确认遗忘'))return;
        if(!view.sameUser())return;
        await workbench.write('/memory/items/'+id,{version:item.version},'DELETE');
        if(view.sameRoute())await render();
      }else if(action==='project-delete'){
        if(!project)throw Error('这个项目在别的页面改过了，刷新看看最新的。');
        if(!await ask('删除项目','会删掉这个项目和它专属的记忆；对话和材料都还在，通用和专题记忆也不受影响。','删除项目'))return;
        if(!view.sameUser())return;
        await api('/memory/projects/'+id,{method:'DELETE',json:{version:project.version}});
        if(view.sameUser())workbench.projectDeleted(id);
        if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render();
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {render,context,openRecord:id=>editor({id}),clearPrivate:()=>{data={projects:[],memories:[]};workbench.clearPrivate();},remember:conversation=>editor({content:conversation.messages.findLast(m=>m.role==='user')?.content.slice(0,2000)||''},conversation)};
}
