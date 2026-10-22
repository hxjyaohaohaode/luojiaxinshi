import {captureUiContext} from './ui-request.js';

const tiers={long_term:'长期记忆',episodic:'经历记录'};
const statusNames={active:'正常调用',cooling:'冷却，暂停调用',needs_review:'需要重新确认',archived:'归档，暂停调用'};
const stamps=value=>value?new Date(value*1000).toLocaleString():'—';

export function createLifecycleUI({state,api,esc,showDialog,toast,ask,refresh}){
  const $=selector=>document.querySelector(selector);
  const btn=(text,action,id='',extra='')=>'<button type="button" class="button small" data-memory-life="'+action+'" data-id="'+esc(id)+'" '+extra+'>'+text+'</button>';
  let projects=[];
  const scopeLabel=item=>{
    if(!item.context_key)return '旧片段，原范围待确认';
    let key=['',[]];try{key=JSON.parse(item.context_key||'["",[]]');}catch{}
    return key[0]?(projects.find(p=>p.id===key[0])?.name||'原项目'):key[1]?.length?'专题：'+key[1].join('、'):'本会话';
  };
  function panel(data){
    projects=data.projects||projects;
    return '<div class="memory-layer-summary" aria-label="记忆层级"><span>长期 '+(data.lifecycle_counts?.long_term||0)+'</span><span>经历 '+(data.lifecycle_counts?.episodic||0)+'</span><span>会话暂存 '+(data.session_count||0)+'</span></div><div class="memory-studio-actions">'+btn('会话暂存与晋升','sessions')+btn('生命周期与遗忘设置','settings')+btn('形成与整理记录','audit')+'</div>';
  }
  function controls(item){return btn('层级与调用范围','item',item.id);}
  async function sessions(){
    const view=captureUiContext(state);
    const result=await api('/memory/session-items');if(!view.sameDialog())return;
    const kinds={request:'用户请求',goal:'会话目标',preference:'临时偏好',constraint:'会话约束',decision:'本次决定',fact:'会话条件',intention:'当前计划',episode:'本次经历'};
    showDialog('会话暂存与长期晋升','<div class="stack"><p class="small muted">这里的内容只在所属对话及原项目、专题中使用。仅本轮条件不会沿用到下一轮。明确有长期价值时，再由你确认保存；自动晋升要求不同会话的独立原话依据。</p>'+(
      result.items.length?result.items.slice(0,60).map(item=>'<article class="memory-session-entry"><div class="between"><strong>'+esc(kinds[item.kind]||'会话片段')+'</strong><span class="pill">'+esc(scopeLabel(item))+'</span></div><p class="memory-content">'+esc(item.content)+'</p><p class="small muted">'+esc(item.title)+' · '+esc(item.lifetime==='turn'?'仅本轮':'会话内')+' · 保留至 '+esc(stamps(item.expires_at))+'</p><div class="memory-studio-actions"><a class="button small" href="#chat/'+encodeURIComponent(item.conversation_id)+'">查看原对话</a>'+(!item.promoted_id?btn('确认保存为长期记忆','promote',item.id):'<span class="pill">已晋升</span>')+btn('遗忘片段与派生记忆','forget-session',item.id)+'</div></article>').join(''):'<p>当前没有仍在保留期内的会话片段。</p>')+'</div>');
  }
  async function settings(){
    const view=captureUiContext(state),result=await api('/memory/lifecycle');if(!view.sameDialog())return;
    const s=result.settings;
    showDialog('记忆生命周期设置','<form class="stack" id="memory-lifecycle-form"><p class="small muted">短期片段随会话活动延长保留期；长期未确认的自动记录可以进入冷却。冷却和归档保留原文，暂停自动调用，人工锁定内容不会自动冷却。</p><div class="form-grid"><label class="field">会话保留天数<input name="session_days" type="number" min="1" max="90" value="'+s.session_days+'" required></label><label class="field">经历复核间隔（天）<input name="episode_days" type="number" min="7" max="365" value="'+s.episode_days+'" required></label></div>'+[
      ['cross_session','允许已确认长期记忆按项目与专题范围跨会话使用'],
      ['auto_promote','允许不同会话的重复稳定陈述自动晋升'],
      ['auto_cooldown','自动冷却长期未确认的自动记录'],
      ['semantic_reflection','空闲时使用已配置模型进行语义复盘，生成的归纳先等我核对（可能计费）']
    ].map(([name,label])=>'<label class="check"><input type="checkbox" name="'+name+'" '+(s[name]?'checked':'')+'><span>'+label+'</span></label>').join('')+'<label class="field">每天最多语义复盘次数<input type="number" name="reflection_budget" min="1" max="8" value="'+s.reflection_budget+'" required></label><p class="small muted">模型复盘默认关闭；开启后仅在已有模型授权的对话范围内进行，仍受应用的 AI 额度限制。失败或中断不会自动重复计费。</p><div class="form-footer"><button class="button primary" type="submit">保存生命周期设置</button></div></form>');
    const form=$('#memory-lifecycle-form');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const view=captureUiContext(state,form),fd=new FormData(form);form.inert=true;
      try{
        await api('/memory/lifecycle/settings',{method:'PUT',json:{version:s.version,session_days:Number(fd.get('session_days')),episode_days:Number(fd.get('episode_days')),auto_promote:fd.has('auto_promote'),auto_cooldown:fd.has('auto_cooldown'),cross_session:fd.has('cross_session'),semantic_reflection:fd.has('semantic_reflection'),reflection_budget:Number(fd.get('reflection_budget'))}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast('已更新保留、晋升与跨会话设置。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function itemSettings(id){
    const view=captureUiContext(state),item=await api('/memory/items/'+id);if(!view.sameDialog())return;
    showDialog('记忆层级与调用范围','<form class="stack" id="memory-item-lifecycle"><p class="memory-content">'+esc(item.content)+'</p><label class="field">记忆层级<select name="tier">'+Object.entries(tiers).map(([key,label])=>'<option value="'+key+'" '+(item.tier===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label class="field">使用状态<select name="status">'+Object.entries(statusNames).filter(([key])=>key!=='needs_review').map(([key,label])=>'<option value="'+key+'" '+(item.status===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label class="check"><input type="checkbox" name="shared" '+(item.shared?'checked':'')+'><span>允许在原有范围内跨会话使用；关闭后仅来源对话可用</span></label><label class="field">适用场景（可选，用逗号分隔）<input name="applies_to" maxlength="600" value="'+esc((item.applies_to||[]).join('，'))+'" placeholder="例如：论文、课程复习"></label><p class="small muted">场景提示会限制自动调用；项目和专题权限仍以原设置为准。重新启用过时内容前请核对正文。</p><div class="form-footer"><button type="submit" class="button primary">保存层级与范围</button></div></form>');
    const form=$('#memory-item-lifecycle');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{
        await api('/memory/items/'+id+'/lifecycle',{method:'PUT',json:{version:item.version,tier:fd.get('tier'),status:fd.get('status'),shared:fd.has('shared'),applies_to:String(fd.get('applies_to')).split(/[,，]/).map(x=>x.trim()).filter(Boolean)}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('已更新这条记忆的层级与调用范围。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function promotion(id){
    const view=captureUiContext(state),item=await api('/memory/session-items/'+encodeURIComponent(id));if(!view.sameDialog())return;
    let original;try{original=JSON.parse(item.context_key);}catch{}
    const known=original&&(original[0]||original[1]?.length<=1);
    showDialog('确认长期记忆','<form class="stack" id="memory-promotion-form"><label class="field">确认保留的内容<textarea name="content" maxlength="2000" rows="5" required>'+esc(item.content)+'</textarea></label><label class="field">长期使用范围<select name="scope" required>'+(known?'<option value="current">原对话记录时的项目或范围</option>':'<option value="" selected disabled>请选择明确的长期使用范围</option>')+'<option value="global">跨项目通用</option>'+(projects.length?'<option value="project">指定项目</option>':'')+'<option value="topic">指定专题</option></select></label><label class="field" data-promotion-project hidden>使用项目<select name="project_id"><option value="">请选择项目</option>'+projects.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.name)+'</option>').join('')+'</select></label><label class="field" data-promotion-topic hidden>专题名称<input name="topic" maxlength="60"></label><p class="small muted">来源原话仍保留。确认后会锁定你的编辑，Agent 更改需再核对。</p><div class="form-footer"><button class="button primary" type="submit">确认保存为长期记忆</button></div></form>');
    const form=$('#memory-promotion-form');
    const scope=form.elements.scope;
    const showFields=()=>{for(const name of ['project','topic']){const field=form.querySelector('[data-promotion-'+name+']');field.hidden=scope.value!==name;field.querySelector('input,select').required=scope.value===name;}};
    scope.addEventListener('change',showFields);showFields();
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{
        await api('/memory/session-items/'+id+'/promote',{method:'POST',json:{scope:fd.get('scope'),project_id:fd.get('scope')==='project'?fd.get('project_id'):null,topic:fd.get('scope')==='topic'?fd.get('topic'):'',content:fd.get('content'),session_version:item.edit_version}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('已确认晋升，来源与人工编辑均已保留。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function editSession(id){
    const view=captureUiContext(state),item=await api('/memory/session-items/'+encodeURIComponent(id));if(!view.sameDialog())return;
    showDialog('编辑会话条件',`<form class="stack" id="memory-session-edit"><label class="field">当前使用的条件<textarea name="content" required rows="5" maxlength="2000">${esc(item.content)}</textarea></label><label class="field">使用时长<select name="lifetime"><option value="turn" ${item.lifetime==='turn'?'selected':''}>仅本轮</option><option value="session" ${item.lifetime==='session'?'selected':''}>本会话内</option></select></label><details class="memory-policy"><summary>形成时的原话</summary><p class="memory-content">${esc(item.original_content)}</p></details><p class="small muted">保留期内仅在原会话及原项目、专题使用。修订保留原话，自动整理不会覆盖本次编辑，也不会将它自动晋升为长期记忆。</p><div class="form-footer"><button type="submit" class="button primary">保存会话条件</button></div></form>`);
    const form=$('#memory-session-edit');
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(form.inert)return;const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{await api('/memory/session-items/'+id,{method:'PUT',json:{version:item.edit_version,content:fd.get('content'),lifetime:fd.get('lifetime')}});if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('已保存会话条件，原话仍可核对。');}}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function trace(cid,aid){
    const view=captureUiContext(state),result=await api('/conversations/'+cid+'/messages/'+aid+'/memory-trace');if(!view.sameDialog())return;
    showDialog('这次回答的记忆使用','<div class="stack"><p class="small muted">'+esc(result.note)+'</p>'+result.items.map(item=>'<article class="memory-session-entry"><p class="memory-content">'+esc(item.content)+'</p><p class="small muted">'+(item.can_feedback===false?'显示当时第 '+item.memory_version+' 版；当前已修改，本次不能评价新版本':item.outcome==='used'?'Agent 报告已用于回答':'曾提供给回答，未报告采用')+'</p><div class="memory-studio-actions">'+(item.can_feedback===false?'':[['helpful','有帮助'],['irrelevant','这次不适用'],['outdated','内容已过时']].map(([outcome,label])=>btn(label,'feedback',item.memory_id,'data-cid="'+esc(cid)+'" data-aid="'+esc(aid)+'" data-outcome="'+outcome+'" data-version="'+item.memory_version+'" aria-pressed="'+(item.feedback===outcome)+'"')).join(''))+'</div></article>').join('')+(result.items.length?'':'<p>这次没有可反馈的长期记忆；已删除的条目不会在这里重新展示。</p>')+'</div>');
  }
  async function audit(){
    const view=captureUiContext(state),result=await api('/memory/lifecycle');if(!view.sameDialog())return;
    const labels={created:'记忆形成',promoted:'长期晋升',cooling:'自动冷却',feedback:'使用反馈',forgotten:'主动遗忘',forgotten_all:'清空记忆',configured:'人工调整',forgotten_session:'会话遗忘',reflected:'语义复盘提议'};
    const jobNames={queued:'等待空闲处理',running:'正在复盘',done:'复盘完成',failed:'复盘失败，未自动重复请求',cancelled:'条件已变化，复盘已取消'};
    const jobs=(result.reflection_jobs||[]).map(job=>'<article class="memory-session-entry"><strong>语义复盘 · '+esc(jobNames[job.state]||'状态待核对')+'</strong><p class="small muted">'+esc(stamps(job.created_at))+' · 形成 '+Number(job.proposal_count||0)+' 条待核对提议</p></article>').join('');
    showDialog('记忆形成与整理记录','<div class="stack"><p class="small muted">曝光、实际采用和本人反馈分别记录。审计仅保留动作及原因，不保留被遗忘的正文。</p><div class="memory-studio-actions">'+btn('执行一轮保留期与晋升检查','maintain')+'</div>'+jobs+result.events.map(e=>'<p><strong>'+esc(labels[e.event]||e.event)+'</strong> · '+esc(stamps(e.created_at))+'<br>'+esc(e.reason)+'</p>').join('')+(result.events.length?'':'<p>还没有形成、反馈或遗忘记录。</p>')+'</div>');
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-memory-life]');if(!target||target.disabled)return;
    const action=target.dataset.memoryLife,id=target.dataset.id,view=captureUiContext(state,target);target.disabled=true;
    try{
      if(action==='sessions')await sessions();
      else if(action==='settings')await settings();
      else if(action==='item')await itemSettings(id);
      else if(action==='promote')await promotion(id);
      else if(action==='edit-session')await editSession(id);
      else if(action==='audit')await audit();
      else if(action==='trace')await trace(target.dataset.cid,id);
      else if(action==='feedback'){
        await api('/memory/items/'+id+'/feedback',{method:'POST',json:{version:Number(target.dataset.version),message_id:target.dataset.aid,outcome:target.dataset.outcome}});
        if(view.sameDialog())await trace(target.dataset.cid,target.dataset.aid);
      }else if(action==='maintain'){
        const result=await api('/memory/lifecycle/maintain',{method:'POST'});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast(result.deferred?'当前回复结束后继续整理。':'已检查：晋升 '+result.promoted+' 条，冷却 '+result.cooled+' 条，清理过期会话片段 '+result.expired_session+' 条。');}
      }else if(action==='retry-reflection'){
        if(!await ask('重新请求模型语义复盘','上次请求可能已经计费。重新请求将再次发送当前授权范围内的记忆依据，受每日预算及应用额度限制。','确认重新请求'))return;
        if(!view.sameUser())return;
        await api('/memory/reflections/'+id+'/retry',{method:'POST',json:{finished_at:Number(target.dataset.finished),allow_external_processing:true}});
        if(view.sameRoute())await refresh();if(view.sameUser())toast('已重新排队；后台会在额度允许且条件未变化时请求。');
      }else if(action==='forget-session'){
        if(!await ask('遗忘会话片段','将移除这个片段及其派生记忆，并阻止旧来源重新写入；原对话原文仍保留。','确认遗忘'))return;
        if(!view.sameUser())return;
        await api('/memory/session-items/'+id,{method:'DELETE'});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast('已遗忘该片段，并阻止从旧来源重新学习。');}
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {panel,controls};
}
