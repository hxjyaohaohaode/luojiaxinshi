import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {searchControls,WorkspaceSearch} from './workspace-search.js';
import {detailsExpanded} from './reference-interactions.js';
const $=(s)=>document.querySelector(s);
const platforms={website:'学校 / 学院官网',wechat_public:'微信公众号',qq_group:'QQ 群',wechat_group:'微信群',campus:'校内平台',other:'其他来源'};
export function createSourcesUI({state,api,esc,icon,field,area,showDialog,ask,toast,route}){
  let entries=[],query='',editing=null,integrations=null,publisherItems=[],publisherNext=null,page=1,searchController=null,matchedIds=null;
  const expanded=new Map();let expansionOwner=null;
  const action=(text,name,id='',cls='')=>`<button type="button" class="button ${cls}" data-source-action="${name}" data-id="${id}">${text}</button>`;
  async function render(renderId){
    if(expansionOwner!==state.session?.user?.id){expanded.clear();expansionOwner=state.session?.user?.id;}
    const [result,channels]=await Promise.all([api('/source-catalog'),api('/integrations')]);if(renderId!==state.renderId)return;entries=result;integrations=channels;query='';page=1;matchedIds=null;searchController?.dispose();
    $('#content').innerHTML=`<div class="page-title between"><div><h1>我的通知来源</h1></div></div>
      <div class="toolbar source-toolbar"><h2>我常看的来源 <span class="muted small" id="catalog-total"></span></h2>${searchControls({id:"source",esc,icon,scope:"sources",kinds:Object.entries(platforms)})}${action(icon('plus')+' 添加来源','add','','primary')}</div><div id="source-catalog-list" class="source-catalog-list"></div><nav id="source-pages" class="calendar-pagination" aria-label="来源分页" hidden></nav>
      <div class="source-access">${action('能接入哪些平台 '+icon('arrow'),'platforms','','small plain')}</div>`;
    searchController=new WorkspaceSearch(document.querySelector('[data-search-host="source"]'),{api,scope:'sources',onResult:result=>{matchedIds=new Set(result.items.map(s=>s.id));query=result.query;page=1;list();},onError:message=>toast(message,true)});list();
  }
  function integrationCards(){
    if(!$('#integration-cards')||!integrations)return;const q=integrations.qq,w=integrations.wechat_publisher;
    const card=(title,status,detail,footer,ready=false,href='')=>`<${href?'a':'article'} class="integration-card${href?' integration-link':''}"${href?` href="${esc(href)}" data-action="close-dialog"`:''}><div class="between"><h3>${title}</h3><span class="pill ${ready?'green':''}">${status}</span></div><p>${detail}</p><div class="integration-path">${footer}</div></${href?'a':'article'}>`;
    $('#integration-cards').innerHTML=card('QQ 机器人私聊',q.bound?'已绑定 · 等你发消息':q.configured?'可以绑定了':'还没开通',
      '绑定后，你私聊发给机器人的消息会存进你的对话。附件、聊天记录卡片和引用的内容，要另外上传原件。它不会读群聊记录，也不会给好友发消息。',
      q.configured?`<div class="row wrap">${action(q.bound?'刷新状态':'绑定我的 QQ','qq-bind','','small primary')}${q.bound?action('解除绑定','qq-unlink','','small plain danger'):''}</div>${q.binding?.last_received_at?`<p class="small">最近收到：${esc(new Date(q.binding.last_received_at*1000).toLocaleString('zh-CN'))}</p>`:''}`:'<span>需要管理员开通</span>还没开通也没关系，你可以直接上传文字、截图和附件。',q.bound)+
      card('已授权的公众号文章',w.configured?'已开通':'还没开通',
        '可以导入已授权公众号发过的文章，正文会完整保存，图片和外链附件需要自己补上。不会读你的微信聊天或关注列表。',
        w.configured&&w.can_import?action('挑文章导入','publisher','','small primary'):w.configured?'想导入文章的话，找管理员帮忙就行。':'<span>需要管理员开通</span>开通后就能直接导入公众号文章。',false)+
      card('智慧珞珈与校内身份','等学校开放','统一身份、课表和通知还要等学校开放接口。现在可以自己填学号或工号，帮小信使判断哪些通知和你有关。','<span class="integration-link-label">完善我的个人条件 →</span>',false,'#settings')+
      card('个人日历','可以导出','确认过的待办可以导出成日历文件（.ics），要自己导入手机日历才会提醒。之后有改动或取消，记得在手机日历里也改一下。','<span class="integration-link-label">看看怎么设置日历提醒 →</span>',true,'#calendar');
  }
  async function refreshIntegrations(){integrations=await api('/integrations');integrationCards();return integrations;}
  async function bindingDialog(){
    const result=await refreshIntegrations();
    if(result.qq.bound){toast('已经绑定好了，发给机器人的新消息会出现在历史对话里。');return;}
    showDialog('绑定 QQ 机器人',`<div class="stack"><p>只有你主动私聊发给机器人的内容，才会收进你的账号。它读不到群聊记录，绑定也不算学校认证。</p><label class="check"><input id="qq-binding-consent" type="checkbox"><span>我同意把自己私聊发给机器人的内容保存到珞珈信使。</span></label><div id="qq-binding-code" aria-live="polite"></div><div class="row wrap">${action('生成绑定指令','qq-code','','primary')}${action('发好了，检查一下','qq-check','','small')}</div></div>`);
  }
  async function publisherDialog(offset=0){
    const result=await api('/integrations/wechat/articles?offset='+offset);publisherItems=result.items;publisherNext=result.next_offset;
    showDialog('挑一篇公众号文章',`<div class="stack"><p class="small muted">选好后会存进你的对话，可以接着传附件、提问，再整理成通知。一次推送多篇的会分开显示。</p><div class="publisher-articles">${publisherItems.length?publisherItems.map((item,i)=>`<div class="publisher-article"><strong>${esc(item.title)}</strong>${action('导入','publisher-import',String(i),'small primary')}</div>`).join(''):'<p>这个公众号还没有能导入的文章。</p>'}</div><div class="row wrap">${offset?action('回到最前面','publisher','','small'):''}${publisherNext!==null?action('下一批','publisher-next','','small'):''}</div></div>`);
  }
  function list(){
    if(!$('#source-catalog-list'))return;
    for(const card of document.querySelectorAll('[data-source-record]'))expanded.set(card.dataset.sourceRecord,detailsExpanded(card));
    const matched=entries.filter(e=>matchedIds?matchedIds.has(e.id):Object.values(e.data).join(' ').toLowerCase().includes(query.toLowerCase()));
    const pages=Math.max(1,Math.ceil(matched.length/12));page=Math.min(page,pages);const pager=$('#source-pages');pager.hidden=pages===1;pager.innerHTML=action('上一页','page-prev','','small')+`<span>${page} / ${pages}</span>`+action('下一页','page-next','','small');pager.querySelector('[data-source-action=page-prev]').disabled=page===1;pager.querySelector('[data-source-action=page-next]').disabled=page===pages;
    $('#catalog-total').textContent=`${matched.length} / ${entries.length}`;
    const searching=!!query||!!matchedIds&&entries.length>0,emptyKey=matched.length?'':searching?'search':'radar',target=$('#source-catalog-list');
    if(!emptyKey||target.dataset.emptyKey!==emptyKey)target.innerHTML=matched.length?matched.slice((page-1)*12,page*12).map(e=>`<details class="catalog-card" data-source-record="${esc(e.id)}"><summary><div class="catalog-heading"><span class="catalog-icon">${icon(e.data.platform==='website'?'doc':'grid')}</span><div><span class="small muted">${platforms[e.data.platform]}</span><h3>${esc(e.data.name)}</h3></div><span class="pill">手动提交</span></div></summary><div class="catalog-body"><p>${esc(e.data.purpose||'还没写用途，补一句以后更好认。')}</p><div class="catalog-meta"><span>${esc(e.data.institution||'还没填发布方')}</span>${e.data.semester?`<span>${esc(e.data.semester)}</span>`:''}${e.data.platform==='wechat_public'?`<span>${e.data.followed?'我已关注':'没标关注'}</span>`:''}</div><div class="catalog-actions">${action('提交这里的通知','submit',e.id,'small primary')}${e.data.url?`<a class="button small" href="${esc(e.data.url)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a>`:''}${action('编辑','edit',e.id,'small plain')}${action('移除','delete',e.id,'small plain danger')}</div></div></details>`).join(''):`<div class="source-directory-empty"><h3>${searching?'没找到匹配的来源':'还没有来源，先加一个常看的吧'}</h3>${searching?'<button type="button" class="button small" data-source-action="clear-search">清空搜索</button>':`<div class="source-starters">${[['website','doc','学校与学院官网','记下网址，回头好找'],['wechat_public','doc','微信公众号','记下常看的公众号'],['qq_group','grid','课程与年级群','按用途和学期区分']].map(([key,symbol,title,note])=>`<button type="button" class="source-starter" data-source-action="preset" data-id="${key}" data-spotlight>${icon(symbol)}<strong>${title}</strong>${icon('plus')}</button>`).join('')}</div>${action('添加其他来源','add','','small plain')}`}</div>`;
    target.dataset.emptyKey=emptyKey;
    for(const card of target.querySelectorAll('[data-source-record]'))card.open=expanded.get(card.dataset.sourceRecord)||false;
  }
  function editor(entry,preset={}){
    editing=entry;const d=entry?.data||preset;
    showDialog(entry?'编辑来源':'添加常看的通知来源',`<form class="stack" data-workspace-form="source-catalog"><div class="form-grid">${field('来源名称','name',d.name||'','text','required maxlength="100" placeholder="例如：资环学院官网、2026 级年级群"')}<label class="field">平台<select name="platform">${Object.entries(platforms).map(([k,v])=>`<option value="${k}" ${d.platform===k?'selected':''}>${v}</option>`).join('')}</select></label>${field('发布方','institution',d.institution||'','text','maxlength="100" placeholder="学院、课程组或组织"')}${field('学期（选填）','semester',d.semester||'','text','maxlength="40" placeholder="方便区分这学期和以前的课程群"')}</div>${field('公开链接（选填）','url',d.url||'','url','maxlength="2000" placeholder="https://…"')}${area('主要在这里看什么通知','purpose',d.purpose||'',3,'maxlength="300" placeholder="例如：本学期课程调整、报名通知、组织活动"')}<label class="check" data-followed-field ${d.platform==='wechat_public'?'':'hidden'}><input type="checkbox" name="followed" ${d.followed?'checked':''}><span>我关注了这个公众号（只是自己标记，不会读你的关注列表）</span></label><p class="small muted">目前还是要你自己把通知发进来。登记来源只是方便整理，不会因此自动读取群聊或公众号内容。</p><div class="form-footer"><button class="button" type="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存来源</button></div></form>`);
  }
  document.addEventListener('change',e=>{if(e.target.name==='platform'&&e.target.closest('[data-workspace-form=source-catalog]')){const f=e.target.form.querySelector('[data-followed-field]');f.hidden=e.target.value!=='wechat_public';}});

  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-source-action]');if(!b||b.disabled)return;b.disabled=true;
    try{const item=entries.find(s=>s.id===b.dataset.id),action=b.dataset.sourceAction;
      if(action==='page-prev'||action==='page-next'){page+=action==='page-prev'?-1:1;list();$('#source-catalog-list').scrollIntoView({block:'start'});}
      else if(action==='platforms'){showDialog('能接入哪些平台','<div id="integration-cards" class="stack"></div>');integrationCards();}
      else if(action==='clear-search'){searchController.clear();}
      else if(action==='add')editor(null);
      else if(action==='preset'&&Object.hasOwn(platforms,b.dataset.id))editor(null,{platform:b.dataset.id});
      else if(action==='edit'&&item)editor(item);
      else if(action==='submit'&&item){state.sourcePreset=item.data;location.hash='new';}
      else if(action==='delete'&&item&&await ask('移除这个来源','只是把这个来源从列表里拿掉，已经保存的通知、对话和待办都还在。','移除')){await api('/source-catalog/'+item.id,{method:'DELETE',json:{version:item.version}});entries=entries.filter(s=>s.id!==item.id);list();toast('来源已移除。');}
      else if(action==='qq-bind')await bindingDialog();
      else if(action==='qq-code'){
        if(!$('#qq-binding-consent')?.checked){toast('先勾选上面的同意，再生成指令。',true);return;}
        const result=await api('/integrations/qq/link-code',{method:'POST',json:{receive_my_submissions:true}});
        if(!$('#qq-binding-code'))return;
        $('#qq-binding-code').innerHTML=`<label class="field">复制整条指令，私聊发给编号为 ${esc(result.app_id)} 的 QQ 机器人<input id="qq-copy-command" readonly value="${esc(result.command)}"></label><p class="small muted">5 分钟内有效，只能用一次。只发给这个机器人，别转发给别人。</p>`;
        $('#qq-copy-command').select();toast('指令生成好了，长按就能复制。');
      }
      else if(action==='qq-check'){const result=await refreshIntegrations();if(result.qq.bound){$('#dialog').close();toast('绑定成功，现在可以把第一条通知发给机器人了。');}else toast('还没收到绑定，看看是不是发错了机器人，或者指令过期了。',true);}
      else if(action==='qq-unlink'&&await ask('解除 QQ 绑定','解除后就收不到新消息了，已保存的对话还在。','解除绑定')){await api('/integrations/qq/unlink',{method:'POST'});await refreshIntegrations();toast('已解除 QQ 绑定。');}
      else if(action==='publisher')await publisherDialog();
      else if(action==='publisher-next'&&publisherNext!==null)await publisherDialog(publisherNext);
      else if(action==='publisher-import'){
        const selected=publisherItems[Number(b.dataset.id)];if(!selected)return;
        const result=await api('/integrations/wechat/import',{method:'POST',json:{article_id:selected.article_id,index:selected.index}});
        if(result.deleted_before){toast('这篇文章之前导入过又删掉了，这次就不重复导入了。',true);return;}
        $('#dialog').close();location.hash='chat/'+result.conversation_id;toast(result.already_imported?'这篇之前导入过，已经帮你打开了。':'文章存进对话了，看看正文，再补上图片和附件。');
      }
    }catch(error){toast(error.message,true);}finally{b.disabled=false;}
  });
  document.addEventListener('submit',async e=>{
    const form=e.target;if(form.dataset.workspaceForm!=='source-catalog')return;e.preventDefault();const submit=form.querySelector('[type=submit]');if(submit.disabled)return;const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.inert=true;const routeId=state.renderId,selected=editing;
    try{const fd=new FormData(form),payload=Object.fromEntries(fd);payload.followed=payload.platform==='wechat_public'&&fd.get('followed')==='on';if(selected)payload.version=selected.version;await api('/source-catalog'+(selected?'/'+selected.id:''),{method:selected?'PUT':'POST',json:payload});if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render(routeId);toast('来源存好了，下次提交可以直接选。');}
    catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finishFeedback();}
  });
  return {render};
}
