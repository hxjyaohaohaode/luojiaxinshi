import {captureUiContext} from './ui-request.js';
import {memoryTimestamp} from './memory-list-text.js';

const tiers={long_term:'长期记忆',episodic:'经历记录'};
const statusNames={active:'正常使用',cooling:'近期没用到，先暂停',needs_review:'需要重新确认',archived:'已归档，先暂停'};
const stamps=value=>memoryTimestamp(value,true)||'—';

export function createLifecycleUI({state,api,esc,showDialog,toast,ask,refresh}){
  const $=selector=>document.querySelector(selector);
  const btn=(text,action,id='',extra='')=>'<button type="button" class="button small" data-memory-life="'+action+'" data-id="'+esc(id)+'" '+extra+'>'+text+'</button>';
  let projects=[];
  const scopeLabel=item=>{
    if(!item.context_key)return '旧片段，范围待确认';
    let key=['',[]];try{key=JSON.parse(item.context_key||'["",[]]');}catch{}
    return key[0]?(projects.find(p=>p.id===key[0])?.name||'原项目'):key[1]?.length?'专题：'+key[1].join('、'):'这个对话';
  };
  function panel(data){
    projects=data.projects||projects;
    return '<div class="memory-layer-summary" aria-label="记忆层级"><span>长期 '+(data.lifecycle_counts?.long_term||0)+'</span><span>经历 '+(data.lifecycle_counts?.episodic||0)+'</span><span>临时记忆 '+(data.session_count||0)+'</span></div><div class="memory-studio-actions">'+btn('临时记忆与转长期','sessions')+btn('保留与遗忘设置','settings')+btn('记忆整理记录','audit')+'</div>';
  }
  function controls(item){return btn('层级与使用范围','item',item.id);}
  async function sessions(){
    const view=captureUiContext(state);
    const result=await api('/memory/session-items');if(!view.sameDialog())return;
    const kinds={request:'我的要求',goal:'这次的目标',preference:'临时偏好',constraint:'这次的限制',decision:'这次的决定',fact:'临时条件',intention:'当前计划',episode:'这次的经历'};
    showDialog('临时记忆与转为长期','<div class="stack"><p class="small muted">这些内容只在原来的对话和项目、专题里用；“仅本轮”的条件不会带到下一轮。值得长期记住的，你确认后再存；要自动转为长期，得是你在不同对话里都这么说过。</p>'+(
      result.items.length?result.items.slice(0,60).map(item=>'<article class="memory-session-entry"><div class="between"><strong>'+esc(kinds[item.kind]||'对话片段')+'</strong><span class="pill">'+esc(scopeLabel(item))+'</span></div><p class="memory-content">'+esc(item.content)+'</p><p class="small muted">'+esc(item.title)+' · '+esc(item.lifetime==='turn'?'仅本轮':'对话内')+' · 保留至 '+esc(stamps(item.expires_at))+'</p><div class="memory-studio-actions"><a class="button small" href="#chat/'+encodeURIComponent(item.conversation_id)+'">查看原对话</a>'+(!item.promoted_id?btn('确认保存为长期记忆','promote',item.id):'<span class="pill">已转为长期</span>')+btn('遗忘这段和相关记忆','forget-session',item.id)+'</div></article>').join(''):'<p>现在没有保留中的对话片段。</p>')+'</div>');
  }
  async function settings(){
    const view=captureUiContext(state),result=await api('/memory/lifecycle');if(!view.sameDialog())return;
    const s=result.settings;
    showDialog('记忆保留设置','<form class="stack" id="memory-lifecycle-form"><p class="small muted">对话还在继续时，临时片段会一直保留；很久没确认的自动记录可以自动暂停使用。暂停和归档都不会删掉内容，你锁定的内容也不会被自动暂停。</p><div class="form-grid"><label class="field">临时记忆保留天数<input name="session_days" type="number" min="1" max="90" value="'+s.session_days+'" required></label><label class="field">经历多久回顾一次（天）<input name="episode_days" type="number" min="7" max="365" value="'+s.episode_days+'" required></label></div>'+[
      ['cross_session','确认过的长期记忆，可以在同项目、同专题的其他对话里用'],
      ['auto_promote','在不同对话里反复说过的事，自动转为长期记忆'],
      ['auto_cooldown','很久没确认的自动记录，自动暂停使用'],
      ['semantic_reflection','空闲时让 AI 回顾记忆、整理归纳，结果先给我看（会用掉 AI 额度）']
    ].map(([name,label])=>'<label class="check"><input type="checkbox" name="'+name+'" '+(s[name]?'checked':'')+'><span>'+label+'</span></label>').join('')+'<label class="field">每天最多回顾几次<input type="number" name="reflection_budget" min="1" max="8" value="'+s.reflection_budget+'" required></label><p class="small muted">AI 回顾默认关闭。打开后只会用你已经同意发给 AI 的对话内容，也受 AI 额度限制；失败或中断不会自动重试扣额度。</p><div class="form-footer"><button class="button primary" type="submit">保存设置</button></div></form>');
    const form=$('#memory-lifecycle-form');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const view=captureUiContext(state,form),fd=new FormData(form);form.inert=true;
      try{
        await api('/memory/lifecycle/settings',{method:'PUT',json:{version:s.version,session_days:Number(fd.get('session_days')),episode_days:Number(fd.get('episode_days')),auto_promote:fd.has('auto_promote'),auto_cooldown:fd.has('auto_cooldown'),cross_session:fd.has('cross_session'),semantic_reflection:fd.has('semantic_reflection'),reflection_budget:Number(fd.get('reflection_budget'))}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast('保留设置更新好了。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function itemSettings(id){
    const view=captureUiContext(state),item=await api('/memory/items/'+id);if(!view.sameDialog())return;
    showDialog('记忆层级与使用范围','<form class="stack" id="memory-item-lifecycle"><p class="memory-content">'+esc(item.content)+'</p><label class="field">记忆层级<select name="tier">'+Object.entries(tiers).map(([key,label])=>'<option value="'+key+'" '+(item.tier===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label class="field">使用状态<select name="status">'+Object.entries(statusNames).filter(([key])=>key!=='needs_review').map(([key,label])=>'<option value="'+key+'" '+(item.status===key?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label class="check"><input type="checkbox" name="shared" '+(item.shared?'checked':'')+'><span>同一范围的其他对话也能用；关掉后只在原来的对话里用</span></label><label class="field">适用场景（可选，用逗号分隔）<input name="applies_to" maxlength="600" value="'+esc((item.applies_to||[]).join('，'))+'" placeholder="例如：论文、课程复习"></label><p class="small muted">填了场景，就只在这些场景里自动用，项目和专题范围不变。重新启用过时的内容前，先看看内容还对不对。</p><div class="form-footer"><button type="submit" class="button primary">保存层级与范围</button></div></form>');
    const form=$('#memory-item-lifecycle');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{
        await api('/memory/items/'+id+'/lifecycle',{method:'PUT',json:{version:item.version,tier:fd.get('tier'),status:fd.get('status'),shared:fd.has('shared'),applies_to:String(fd.get('applies_to')).split(/[,，]/).map(x=>x.trim()).filter(Boolean)}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('这条记忆的层级和范围更新好了。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function promotion(id){
    const view=captureUiContext(state),item=await api('/memory/session-items/'+encodeURIComponent(id));if(!view.sameDialog())return;
    let original;try{original=JSON.parse(item.context_key);}catch{}
    const known=original&&(original[0]||original[1]?.length<=1);
    showDialog('确认长期记忆','<form class="stack" id="memory-promotion-form"><label class="field">确认保留的内容<textarea name="content" maxlength="2000" rows="5" required>'+esc(item.content)+'</textarea></label><label class="field">长期使用范围<select name="scope" required>'+(known?'<option value="current">原对话所在的项目或范围</option>':'<option value="" selected disabled>选一个长期使用范围</option>')+'<option value="global">跨项目通用</option>'+(projects.length?'<option value="project">指定项目</option>':'')+'<option value="topic">指定专题</option></select></label><label class="field" data-promotion-project hidden>使用项目<select name="project_id"><option value="">请选择项目</option>'+projects.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.name)+'</option>').join('')+'</select></label><label class="field" data-promotion-topic hidden>专题名称<input name="topic" maxlength="60"></label><p class="small muted">原话会保留。确认后你的修改会被锁定，之后 AI 想改需要你再确认。</p><div class="form-footer"><button class="button primary" type="submit">确认保存为长期记忆</button></div></form>');
    const form=$('#memory-promotion-form');
    const scope=form.elements.scope;
    const showFields=()=>{for(const name of ['project','topic']){const field=form.querySelector('[data-promotion-'+name+']');field.hidden=scope.value!==name;field.querySelector('input,select').required=scope.value===name;}};
    scope.addEventListener('change',showFields);showFields();
    form.addEventListener('submit',async event=>{
      event.preventDefault();const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{
        await api('/memory/session-items/'+id+'/promote',{method:'POST',json:{scope:fd.get('scope'),project_id:fd.get('scope')==='project'?fd.get('project_id'):null,topic:fd.get('scope')==='topic'?fd.get('topic'):'',content:fd.get('content'),session_version:item.edit_version}});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('已转为长期记忆，来源和你的修改都保留着。');}
      }catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function editSession(id){
    const view=captureUiContext(state),item=await api('/memory/session-items/'+encodeURIComponent(id));if(!view.sameDialog())return;
    showDialog('编辑临时要求',`<form class="stack" id="memory-session-edit"><label class="field">现在用的要求<textarea name="content" required rows="5" maxlength="2000">${esc(item.content)}</textarea></label><label class="field">使用时长<select name="lifetime"><option value="turn" ${item.lifetime==='turn'?'selected':''}>仅本轮</option><option value="session" ${item.lifetime==='session'?'selected':''}>这个对话内</option></select></label><details class="memory-policy"><summary>当时的原话</summary><p class="memory-content">${esc(item.original_content)}</p></details><p class="small muted">保留期内只在原来的对话和项目、专题里用。改了之后原话还在，自动整理不会覆盖你的修改，也不会把它自动转为长期记忆。</p><div class="form-footer"><button type="submit" class="button primary">保存临时要求</button></div></form>`);
    const form=$('#memory-session-edit');
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(form.inert)return;const fd=new FormData(form),view=captureUiContext(state,form);form.inert=true;
      try{await api('/memory/session-items/'+id,{method:'PUT',json:{version:item.edit_version,content:fd.get('content'),lifetime:fd.get('lifetime')}});if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await refresh();toast('临时要求存好了，原话还能查到。');}}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;}
    });
  }
  async function trace(cid,aid){
    const view=captureUiContext(state),result=await api('/conversations/'+cid+'/messages/'+aid+'/memory-trace');if(!view.sameDialog())return;
    showDialog('这次回答用了哪些记忆','<div class="stack"><p class="small muted">'+esc(result.note)+'</p>'+result.items.map(item=>'<article class="memory-session-entry"><p class="memory-content">'+esc(item.content)+'</p><p class="small muted">'+(item.can_feedback===false?'这是当时的第 '+item.memory_version+' 版；之后改过了，没法给新版本打分':item.outcome==='used'?'AI 说用上了':'给过 AI，但没说用上')+'</p><div class="memory-studio-actions">'+(item.can_feedback===false?'':[['helpful','有帮助'],['irrelevant','这次不适用'],['outdated','内容已过时']].map(([outcome,label])=>btn(label,'feedback',item.memory_id,'data-cid="'+esc(cid)+'" data-aid="'+esc(aid)+'" data-outcome="'+outcome+'" data-version="'+item.memory_version+'" aria-pressed="'+(item.feedback===outcome)+'"')).join(''))+'</div></article>').join('')+(result.items.length?'':'<p>这次没有能反馈的长期记忆，删掉的也不会再显示。</p>')+'</div>');
  }
  async function audit(){
    const view=captureUiContext(state),result=await api('/memory/lifecycle');if(!view.sameDialog())return;
    const labels={created:'记下新记忆',promoted:'转为长期',cooling:'自动暂停',feedback:'使用反馈',forgotten:'主动遗忘',forgotten_all:'清空记忆',configured:'手动调整',forgotten_session:'遗忘临时记忆',reflected:'AI 回顾建议'};
    const jobNames={queued:'等空闲时处理',running:'正在回顾',done:'回顾完成',failed:'回顾没成功，不会自动重试',cancelled:'情况变了，这次回顾已取消'};
    const jobs=(result.reflection_jobs||[]).map(job=>'<article class="memory-session-entry"><strong>AI 回顾 · '+esc(jobNames[job.state]||'状态待确认')+'</strong><p class="small muted">'+esc(stamps(job.created_at))+' · 形成 '+Number(job.proposal_count||0)+' 条建议等你看</p></article>').join('');
    showDialog('记忆整理记录','<div class="stack"><p class="small muted">给过 AI、AI 用上了、你的反馈，会分开记。这里只记做了什么和为什么，不保留已遗忘的内容。</p><div class="memory-studio-actions">'+btn('现在检查一遍保留期和长期记忆','maintain')+'</div>'+jobs+result.events.map(e=>'<p><strong>'+esc(labels[e.event]||e.event)+'</strong> · '+esc(stamps(e.created_at))+'<br>'+esc(e.reason)+'</p>').join('')+(result.events.length?'':'<p>还没有记录，用一阵子就会有了。</p>')+'</div>');
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
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast(result.deferred?'等这条回复结束后接着整理。':'检查好了：转为长期 '+result.promoted+' 条，暂停 '+result.cooled+' 条，清理过期的临时片段 '+result.expired_session+' 条。');}
      }else if(action==='retry-reflection'){
        if(!await ask('再让 AI 回顾一次','上次可能已经用掉了额度。再来一次，会把你已同意范围内的记忆内容重新发给 AI，也受每日次数和 AI 额度限制。','再来一次'))return;
        if(!view.sameUser())return;
        await api('/memory/reflections/'+id+'/retry',{method:'POST',json:{finished_at:Number(target.dataset.finished),allow_external_processing:true}});
        if(view.sameRoute())await refresh();if(view.sameUser())toast('已经重新排队，额度够、情况没变时就会开始。');
      }else if(action==='forget-session'){
        if(!await ask('遗忘这段临时记忆','这段和由它整理出的记忆都会删掉，也不会再从原来的地方重新记下；原对话还在。','确认遗忘'))return;
        if(!view.sameUser())return;
        await api('/memory/session-items/'+id,{method:'DELETE'});
        if(view.sameUser()){if(view.sameDialog())$('#dialog').close();if(view.sameRoute()&&location.hash.split('/')[0]==='#memory')await refresh();toast('已遗忘，也不会再从原来的地方重新记下。');}
      }
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
  return {panel,controls};
}
