import {captureUiContext,beginFormFeedback} from './ui-request.js';
import {searchControls,WorkspaceSearch} from './workspace-search.js';
import {detailsExpanded} from './reference-interactions.js';
const $=(s)=>document.querySelector(s);
const platforms={website:'学校 / 学院官网',wechat_public:'微信公众号',qq_group:'QQ 群',wechat_group:'微信群',campus:'校内平台',other:'其他来源'};
export function createSourcesUI({state,api,esc,icon,field,area,showDialog,ask,toast,route}){
  let entries=[],query='',editing=null,integrations=null,publisherItems=[],publisherNext=null,page=1,searchController=null,matchedIds=null,subscriptions=[],automation=null;
  const expanded=new Map();let expansionOwner=null;
  const action=(text,name,id='',cls='')=>`<button type="button" class="button ${cls}" data-source-action="${name}" data-id="${id}">${text}</button>`;
  async function render(renderId){
    if(expansionOwner!==state.session?.user?.id){expanded.clear();expansionOwner=state.session?.user?.id;}
    const [result,channels,sync,auto]=await Promise.all([api('/source-catalog'),api('/integrations'),api('/source-subscriptions'),api('/notice-automation')]);if(renderId!==state.renderId)return;entries=result;integrations=channels;subscriptions=sync;automation=auto;query='';page=1;matchedIds=null;searchController?.dispose();
    $('#content').innerHTML=`<div class="page-title between"><div><h1>我的通知来源</h1></div></div>
      <div class="toolbar source-toolbar"><h2>我常看的来源 <span class="muted small" id="catalog-total"></span></h2>${searchControls({id:"source",esc,icon,scope:"sources",kinds:Object.entries(platforms)})}${action(icon('plus')+' 添加来源','add','','primary')}</div><div id="source-catalog-list" class="source-catalog-list"></div><nav id="source-pages" class="calendar-pagination" aria-label="来源分页" hidden></nav>
      <div class="source-access row wrap">${action('能接入哪些平台 '+icon('arrow'),'platforms','','small plain')}${action('自动整理'+(automation.enabled?' · 已开启':' · 未开启'),'automation','','small')}${automation.counts?.failed?`<span class="small">${automation.counts.failed} 条整理失败</span>`:''}</div>`;
    searchController=new WorkspaceSearch(document.querySelector('[data-search-host="source"]'),{api,scope:'sources',onResult:result=>{matchedIds=new Set(result.items.map(s=>s.id));query=result.query;page=1;list();},onError:message=>toast(message,true)});list();
  }
  function integrationCards(){
    if(!$('#integration-cards')||!integrations)return;const q=integrations.qq,w=integrations.wechat_publisher;
    const card=(title,status,detail,footer,ready=false,href='')=>`<${href?'a':'article'} class="integration-card${href?' integration-link':''}"${href?` href="${esc(href)}" data-action="close-dialog"`:''}><div class="between"><h3>${title}</h3><span class="pill ${ready?'green':''}">${status}</span></div><p>${detail}</p><div class="integration-path">${footer}</div></${href?'a':'article'}>`;
    $('#integration-cards').innerHTML=card('QQ 机器人私聊',q.bound?'已绑定 · 等你发消息':q.configured?'可以绑定了':'还没开通',
      '私聊投递后进入通知收件箱。消息中的文字会保留，缺失附件会标出。',
      q.configured?`<div class="row wrap">${action(q.bound?'刷新状态':'绑定我的 QQ','qq-bind','','small primary')}${q.bound?action('解除绑定','qq-unlink','','small plain danger'):''}</div>${q.binding?.last_received_at?`<p class="small">最近收到：${esc(new Date(q.binding.last_received_at*1000).toLocaleString('zh-CN'))}</p>`:''}`:'<span>需要管理员开通</span>还没开通也没关系，你可以直接上传文字、截图和附件。',q.bound)+
      card('QQ 群通知',q.groups?.length?`${q.groups.length} 个群已接收`:q.configured?'待群内授权':'还没开通',
        '群主或管理员在群内启用后，每位成员自行选择接收。全量消息还需 QQ 侧开启接收所有消息。',
        q.configured?`${action('接入群通知','qq-group','','small primary')}${(q.groups||[]).map(g=>`<div class="row wrap"><span>群 ${esc(g.group_id.slice(0,10))}${g.last_received_at?' · 最近收到 '+esc(new Date(g.last_received_at*1000).toLocaleString('zh-CN')):' · 等待新消息'}</span>${action('停止本人接收','qq-group-unsubscribe',g.group_id,'small plain')}${g.can_disable?action('停用此群','qq-group-disable',g.group_id,'small plain danger'):''}</div>`).join('')}`:'需要管理员配置机器人',!!q.groups?.length)+
      card('已授权的公众号文章',w.subscription?.enabled?w.subscription.error?'同步异常':'自动接收':w.configured?'可接入':'还没开通',
        '获授权发布账号的新文章和更正进入本人收件箱；图片和关键附件需核对。',
        w.configured&&w.can_import?`<div class="row wrap">${action('自动同步设置','publisher-sync','','small primary')}${w.subscription?.enabled?action('立即同步','publisher-refresh','','small'):''}${action('选择文章','publisher','','small')}</div>${w.subscription?.checked_at?`<p class="small muted">最近检查 ${esc(new Date(w.subscription.checked_at*1000).toLocaleString('zh-CN'))} · 新收 ${w.subscription.received_count||0} · 更新 ${w.subscription.updated_count||0}</p>`:''}${w.subscription?.error?`<p class="alert error">${esc(w.subscription.error)}</p>`:''}`:w.configured?'需要发布账号的管理员授权':'需要管理员配置发布账号凭证',!!w.subscription?.enabled)+
      card('智慧珞珈与校内身份','等学校开放','统一身份、课表和通知还要等学校开放接口。现在可以自己填学号或工号，帮小信使判断哪些通知和你有关。','<span class="integration-link-label">完善我的个人条件 →</span>',false,'#settings')+
      card('个人日历','可以导出','确认过的待办可以导出成日历文件（.ics），要自己导入手机日历才会提醒。之后有改动或取消，记得在手机日历里也改一下。','<span class="integration-link-label">看看怎么设置日历提醒 →</span>',true,'#calendar');
    if(q.pending_deliveries?.length)$('#integration-cards').insertAdjacentHTML('beforeend',`<section class="stack"><h3>群通知待收件 · ${q.pending_deliveries.length}</h3>${q.pending_deliveries.map(d=>`<article class="panel"><strong>${esc(d.title)}</strong><p class="small">${esc(d.error||'等待收件')}${d.state==='failed'?' · 自动重试已停止':''}</p>${action('重试收件','qq-delivery-retry',d.id,'small')}</article>`).join('')}</section>`);
  }
  async function refreshIntegrations(){integrations=await api('/integrations');integrationCards();return integrations;}
  async function bindingDialog(){
    const result=await refreshIntegrations();
    if(result.qq.bound){toast('已绑定，新消息会进入通知收件箱。');return;}
    showDialog('绑定 QQ 机器人',`<div class="stack"><p>只有你主动私聊发给机器人的内容，才会收进你的账号。它读不到群聊记录，绑定也不算学校认证。</p><label class="check"><input id="qq-binding-consent" type="checkbox"><span>我同意把自己私聊发给机器人的内容保存到珞珈信使。</span></label><div id="qq-binding-code" aria-live="polite"></div><div class="row wrap">${action('生成绑定指令','qq-code','','primary')}${action('发好了，检查一下','qq-check','','small')}</div></div>`);
  }
  async function groupDialog(){
    showDialog('接入 QQ 群通知',`<div class="stack"><p>先由群主或管理员启用该群，再由成员分别接收；只会保存授权之后的新消息。</p><label class="check"><input id="qq-group-consent" type="checkbox"><span>我同意接收所在群的新通知到本人账号。</span></label><div id="qq-group-code" aria-live="polite"></div><div class="row wrap">${action('生成群内指令','qq-group-code','','primary')}${action('检查接入状态','qq-group-check','','small')}</div></div>`);
  }
  async function publisherSyncDialog(){
    const view=captureUiContext(state),s=await api('/integrations/wechat/subscription');if(!view.sameDialog())return;
    showDialog('公众号自动同步',`<form class="stack" data-workspace-form="publisher-sync" data-version="${s.version}"><label class="check"><input name="enabled" type="checkbox" ${s.enabled||!s.version?'checked':''}><span>将获授权发布账号的新文章同步到本人收件箱</span></label><label class="field">首次接收范围<select name="initial_pages" ${s.version?'disabled':''}>${[[1,'最近 10 次发布'],[3,'最近 30 次发布'],[10,'最近 100 次发布']].map(([v,t])=>`<option value="${v}" ${s.initial_pages===v?'selected':''}>${t}</option>`).join('')}</select></label>${field('检查间隔（分钟）','interval_minutes',s.interval_minutes,'number','required min="5" max="1440"')}<p class="small muted">一次发布多篇文章时分别收件。首次范围保存后固定；后续自动检查新增和更正。只进入你的账号。</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存</button></div></form>`);
  }
  async function automationDialog(){
    const view=captureUiContext(state),s=await api('/notice-automation');if(!view.sameDialog())return;automation=s;
    const states={queued:'等待整理',running:'正在整理',succeeded:'草稿待核对',failed:'整理失败',cancelled:'已停止',stale:'已有新版本'};
    showDialog('来源通知自动整理',`<form class="stack" data-workspace-form="notice-automation" data-version="${s.version}"><label class="check"><input name="enabled" type="checkbox" ${s.enabled?'checked':''}><span>新收通知自动判断相关性并整理行动草稿</span></label><label class="check"><input name="allow_external_processing" type="checkbox" ${s.consented_at?'checked':''}><span>我同意将通知原文、附件和相关个人条件发送给当前配置的外部 AI 模型。</span></label>${field('每天最多自动整理多少则','daily_limit',s.daily_limit,'number',`required min="1" max="${s.daily_limit_max}"`)}<p class="small muted">每则可能多次调用模型并产生费用。只形成草稿，待办由你确认。停用会取消未开始的整理；失败不会自动重复调用。</p><p class="small">今天已尝试 ${s.used_today} 则 · 等待 ${s.counts?.queued||0} 则</p><div class="form-footer"><button type="button" class="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存</button></div></form><div class="stack">${s.jobs.slice(0,12).map(j=>`<article class="publisher-article"><div><a href="#notice/${esc(j.notice_id)}" data-action="close-dialog">${esc(j.title)}</a><p class="small">${states[j.state]||esc(j.state)}${j.error?' · '+esc(j.error):''}</p></div>${j.state==='failed'&&s.enabled?action('重试','automation-retry',j.id,'small'):''}</article>`).join('')}</div>`);
  }
  function subscriptionFor(id){return subscriptions.find(s=>s.source_id===id)||{state:'manual',enabled:false};}
  function subscriptionLabel(id){const s=subscriptionFor(id);return ({manual:'手动转入',waiting:'等待同步',active:'自动接收',syncing:'正在同步',paused:'已暂停',error:'同步异常'})[s.state]||'待连接';}
  function syncControls(entry){
    if(entry.data.platform!=='website')return '';
    const s=subscriptionFor(entry.id);
    return `<div class="stack">${s.error?`<p class="alert error" role="status">${esc(s.error)}</p>`:''}${s.checked_at?`<p class="small muted">最近检查 ${esc(new Date(s.checked_at*1000).toLocaleString('zh-CN'))} · 新收 ${s.received_count||0} · 更新 ${s.updated_count||0}${s.pending_count?' · 等待读取 '+s.pending_count:''}</p>`:''}<div class="row wrap">${action(s.config?'订阅设置':'开启自动接收','sync-config',entry.id,'small')}${s.enabled?action('立即刷新','sync-refresh',entry.id,'small'):''}</div></div>`;
  }
  function syncDialog(entry){
    const s=subscriptionFor(entry.id),c=s.config||{url:entry.data.url||'',mode:'html',article_path_prefix:'/info/',interval_minutes:30};
    showDialog('官网自动接收',`<form class="stack" data-workspace-form="source-sync" data-source-id="${esc(entry.id)}" data-version="${s.version||0}"><label class="check"><input name="enabled" type="checkbox" ${s.config?s.enabled?'checked':'':'checked'}><span>持续接收此来源的新通知</span></label>${field('通知列表或 RSS/Atom 地址','url',c.url,'url','required maxlength="2000"')}<label class="field">列表格式<select name="mode"><option value="html" ${c.mode==='html'?'selected':''}>网页通知列表</option><option value="feed" ${c.mode==='feed'?'selected':''}>RSS / Atom</option></select></label>${field('通知正文路径前缀（网页列表必填）','article_path_prefix',c.article_path_prefix||'','text','maxlength="300" placeholder="例如 /info/ 或 /news/"')}${field('检查间隔（分钟）','interval_minutes',c.interval_minutes,'number','min="5" max="1440" required')}<p class="small muted">首次读取列表现有通知，之后增量接收并检查原文更新。只读取同域名下的指定范围；关键附件仍需核对。服务运行时生效。</p><div class="form-footer"><button class="button" type="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存订阅</button></div></form>`);
  }
  async function publisherDialog(offset=0){
    const result=await api('/integrations/wechat/articles?offset='+offset);publisherItems=result.items;publisherNext=result.next_offset;
    showDialog('挑一篇公众号文章',`<div class="stack"><p class="small muted">导入后进入本人通知收件箱；相同文章的更正关联原通知。</p><div class="publisher-articles">${publisherItems.length?publisherItems.map((item,i)=>`<div class="publisher-article"><strong>${esc(item.title)}</strong>${action('导入','publisher-import',String(i),'small primary')}</div>`).join(''):'<p>这个公众号还没有能导入的文章。</p>'}</div><div class="row wrap">${offset?action('回到最前面','publisher','','small'):''}${publisherNext!==null?action('下一批','publisher-next','','small'):''}</div></div>`);
  }
  function list(){
    if(!$('#source-catalog-list'))return;
    for(const card of document.querySelectorAll('[data-source-record]'))expanded.set(card.dataset.sourceRecord,detailsExpanded(card));
    const matched=entries.filter(e=>matchedIds?matchedIds.has(e.id):Object.values(e.data).join(' ').toLowerCase().includes(query.toLowerCase()));
    const pages=Math.max(1,Math.ceil(matched.length/12));page=Math.min(page,pages);const pager=$('#source-pages');pager.hidden=pages===1;pager.innerHTML=action('上一页','page-prev','','small')+`<span>${page} / ${pages}</span>`+action('下一页','page-next','','small');pager.querySelector('[data-source-action=page-prev]').disabled=page===1;pager.querySelector('[data-source-action=page-next]').disabled=page===pages;
    $('#catalog-total').textContent=`${matched.length} / ${entries.length}`;
    const searching=!!query||!!matchedIds&&entries.length>0,emptyKey=matched.length?'':searching?'search':'radar',target=$('#source-catalog-list');
    if(!emptyKey||target.dataset.emptyKey!==emptyKey)target.innerHTML=matched.length?matched.slice((page-1)*12,page*12).map(e=>`<details class="catalog-card" data-source-record="${esc(e.id)}"><summary><div class="catalog-heading"><span class="catalog-icon">${icon(e.data.platform==='website'?'doc':'grid')}</span><div><span class="small muted">${platforms[e.data.platform]}</span><h3>${esc(e.data.name)}</h3></div><span class="pill">${esc(subscriptionLabel(e.id))}</span></div></summary><div class="catalog-body"><p>${esc(e.data.purpose||'还没写用途，补一句以后更好认。')}</p><div class="catalog-meta"><span>${esc(e.data.institution||'还没填发布方')}</span>${e.data.semester?`<span>${esc(e.data.semester)}</span>`:''}${e.data.platform==='wechat_public'?`<span>${e.data.followed?'我已关注':'没标关注'}</span>`:''}</div>${syncControls(e)}<div class="catalog-actions">${action('转入这里的通知','submit',e.id,'small primary')}${e.data.url?`<a class="button small" href="${esc(e.data.url)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a>`:''}${action('编辑','edit',e.id,'small plain')}${action('移除','delete',e.id,'small plain danger')}</div></div></details>`).join(''):`<div class="source-directory-empty"><h3>${searching?'没找到匹配的来源':'还没有来源，先加一个常看的吧'}</h3>${searching?'<button type="button" class="button small" data-source-action="clear-search">清空搜索</button>':`<div class="source-starters">${[['website','doc','学校与学院官网','记下网址，回头好找'],['wechat_public','doc','微信公众号','记下常看的公众号'],['qq_group','grid','课程与年级群','按用途和学期区分']].map(([key,symbol,title,note])=>`<button type="button" class="source-starter" data-source-action="preset" data-id="${key}" data-spotlight>${icon(symbol)}<strong>${title}</strong>${icon('plus')}</button>`).join('')}</div>${action('添加其他来源','add','','small plain')}`}</div>`;
    target.dataset.emptyKey=emptyKey;
    for(const card of target.querySelectorAll('[data-source-record]'))card.open=expanded.get(card.dataset.sourceRecord)||false;
  }
  function editor(entry,preset={}){
    editing=entry;const d=entry?.data||preset;
    showDialog(entry?'编辑来源':'添加常看的通知来源',`<form class="stack" data-workspace-form="source-catalog"><div class="form-grid">${field('来源名称','name',d.name||'','text','required maxlength="100" placeholder="例如：资环学院官网、2026 级年级群"')}<label class="field">平台<select name="platform">${Object.entries(platforms).map(([k,v])=>`<option value="${k}" ${d.platform===k?'selected':''}>${v}</option>`).join('')}</select></label>${field('发布方','institution',d.institution||'','text','maxlength="100" placeholder="学院、课程组或组织"')}${field('学期（选填）','semester',d.semester||'','text','maxlength="40" placeholder="方便区分这学期和以前的课程群"')}</div>${field('公开链接（选填）','url',d.url||'','url','maxlength="2000" placeholder="https://…"')}${area('主要在这里看什么通知','purpose',d.purpose||'',3,'maxlength="300" placeholder="例如：本学期课程调整、报名通知、组织活动"')}<label class="check" data-followed-field ${d.platform==='wechat_public'?'':'hidden'}><input type="checkbox" name="followed" ${d.followed?'checked':''}><span>我关注了这个公众号（只是自己标记，不会读你的关注列表）</span></label><p class="small muted">保存网站来源后可开启自动接收；公众号和群须另行完成平台授权。</p><div class="form-footer"><button class="button" type="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存来源</button></div></form>`);
  }
  document.addEventListener('change',e=>{if(e.target.name==='platform'&&e.target.closest('[data-workspace-form=source-catalog]')){const f=e.target.form.querySelector('[data-followed-field]');f.hidden=e.target.value!=='wechat_public';}});

  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-source-action]');if(!b||b.disabled)return;b.disabled=true;
    try{const item=entries.find(s=>s.id===b.dataset.id),action=b.dataset.sourceAction;
      if(action==='page-prev'||action==='page-next'){page+=action==='page-prev'?-1:1;list();$('#source-catalog-list').scrollIntoView({block:'start'});}
      else if(action==='platforms'){showDialog('能接入哪些平台','<div id="integration-cards" class="stack"></div>');integrationCards();}
      else if(action==='automation')await automationDialog();
      else if(action==='automation-retry'){const view=captureUiContext(state,b);await api('/notice-automation/'+encodeURIComponent(b.dataset.id)+'/retry',{method:'POST'});if(view.sameDialog()){await automationDialog();toast('已重新排队');}}
      else if(action==='clear-search'){searchController.clear();}
      else if(action==='add')editor(null);
      else if(action==='preset'&&Object.hasOwn(platforms,b.dataset.id))editor(null,{platform:b.dataset.id});
      else if(action==='edit'&&item)editor(item);
      else if(action==='sync-config'&&item)syncDialog(item);
      else if(action==='sync-refresh'&&item){const view=captureUiContext(state,b);const result=await api('/source-catalog/'+item.id+'/refresh',{method:'POST'});if(!view.sameUser())return;subscriptions=subscriptions.filter(s=>s.source_id!==item.id);if(result)subscriptions.push(result);if(view.sameRoute())list();toast(result?.error||'检查完成，新通知已进入收件箱',!!result?.error);}
      else if(action==='submit'&&item){state.sourcePreset=item.data;location.hash='new';}
      else if(action==='delete'&&item&&await ask('移除这个来源','只是把这个来源从列表里拿掉，已经保存的通知、对话和待办都还在。','移除')){await api('/source-catalog/'+item.id,{method:'DELETE',json:{version:item.version}});entries=entries.filter(s=>s.id!==item.id);list();toast('来源已移除。');}
      else if(action==='qq-bind')await bindingDialog();
      else if(action==='qq-group')await groupDialog();
      else if(action==='qq-delivery-retry'){const result=await api('/integrations/qq/deliveries/'+encodeURIComponent(b.dataset.id)+'/retry',{method:'POST'});await refreshIntegrations();toast(result.ok?'已收件':'尚未收件，请查看失败原因',!result.ok);}
      else if(action==='qq-group-code'){
        if(!$('#qq-group-consent')?.checked){toast('请先选择同意接收',true);return;}
        const view=captureUiContext(state,b),result=await api('/integrations/qq/group-code',{method:'POST',json:{receive_group_notices:true}});
        if(!view.sameDialog()||!$('#qq-group-code'))return;
        $('#qq-group-code').innerHTML=`<label class="field">群主或管理员：在目标群发送给机器人<input readonly value="${esc(result.authorize_command)}"></label><label class="field">已启用群的成员：在目标群发送给机器人<input readonly value="${esc(result.command)}"></label><p class="small muted">两条任选对应身份的一条，5 分钟内一次有效。未开全量接收时请 @机器人。指令只发往你的目标群。</p>`;
      }
      else if(action==='qq-group-check'){const result=await refreshIntegrations();toast(result.qq.groups?.length?`已接收 ${result.qq.groups.length} 个群；等待新消息`:'尚未收到群内授权指令',!result.qq.groups?.length);}
      else if(action==='qq-group-unsubscribe'){await api('/integrations/qq/groups/'+encodeURIComponent(b.dataset.id),{method:'DELETE'});await refreshIntegrations();toast('已停止本人接收');}
      else if(action==='qq-group-disable'&&await ask('停用此群','将停止此群所有已订阅成员的新通知接收，已有通知保留。','停用')){await api('/integrations/qq/groups/'+encodeURIComponent(b.dataset.id)+'/disable',{method:'POST'});await refreshIntegrations();toast('已停用此群');}
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
      else if(action==='publisher-sync')await publisherSyncDialog();
      else if(action==='publisher-refresh'){const view=captureUiContext(state,b),result=await api('/integrations/wechat/refresh',{method:'POST'});if(!view.sameUser())return;await refreshIntegrations();toast(result?.error||'公众号同步完成',!!result?.error);}
      else if(action==='publisher-next'&&publisherNext!==null)await publisherDialog(publisherNext);
      else if(action==='publisher-import'){
        const selected=publisherItems[Number(b.dataset.id)];if(!selected)return;
        const result=await api('/integrations/wechat/import',{method:'POST',json:{article_id:selected.article_id,index:selected.index}});
        if(result.deleted_before){toast('这篇文章之前导入过又删掉了，这次就不重复导入了。',true);return;}
        $('#dialog').close();location.hash='notice/'+result.notice_id;toast(result.updated?'原通知已收到更新，请核对变化':result.already_imported?'已打开已有通知':'文章已进入通知收件箱');
      }
    }catch(error){toast(error.message,true);}finally{b.disabled=false;}
  });
  document.addEventListener('submit',async e=>{
    if(e.target.dataset.workspaceForm==='notice-automation'){
      e.preventDefault();const form=e.target,view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;form.inert=true;
      try{const fd=new FormData(form);automation=await api('/notice-automation',{method:'PUT',json:{enabled:fd.get('enabled')==='on',allow_external_processing:fd.get('allow_external_processing')==='on',daily_limit:Number(fd.get('daily_limit')),version:Number(form.dataset.version)}});if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render(state.renderId);toast(automation.enabled?'自动整理已启用，收件后会生成待核对草稿':'已停止未开始的自动整理');}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finish();}return;
    }
    if(e.target.dataset.workspaceForm==='publisher-sync'){
      e.preventDefault();const form=e.target,view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;form.inert=true;
      try{const fd=new FormData(form),result=await api('/integrations/wechat/subscription',{method:'PUT',json:{enabled:fd.get('enabled')==='on',initial_pages:Number(form.querySelector('[name=initial_pages]').value),interval_minutes:Number(fd.get('interval_minutes')),version:Number(form.dataset.version)}});if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();await refreshIntegrations();toast(result.enabled?'公众号自动同步已启用':'公众号同步已暂停');}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finish();}return;
    }
    if(e.target.dataset.workspaceForm==='source-sync'){
      e.preventDefault();const form=e.target,view=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;form.inert=true;
      try{const fd=new FormData(form),payload=Object.fromEntries(fd);payload.enabled=fd.get('enabled')==='on';payload.interval_minutes=Number(payload.interval_minutes);payload.version=Number(form.dataset.version);const result=await api('/source-catalog/'+form.dataset.sourceId+'/subscription',{method:'PUT',json:payload});if(!view.sameUser())return;subscriptions=subscriptions.filter(s=>s.source_id!==form.dataset.sourceId);subscriptions.push(result);if(view.sameDialog())$('#dialog').close();if(view.sameRoute())list();toast(payload.enabled?'订阅已启用，可立即刷新或等待后台接收':'订阅已暂停');}
      catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finish();}return;
    }
    const form=e.target;if(form.dataset.workspaceForm!=='source-catalog')return;e.preventDefault();const submit=form.querySelector('[type=submit]');if(submit.disabled)return;const view=captureUiContext(state,form),finishFeedback=beginFormFeedback(form);if(!finishFeedback)return;form.inert=true;const routeId=state.renderId,selected=editing;
    try{const fd=new FormData(form),payload=Object.fromEntries(fd);payload.followed=payload.platform==='wechat_public'&&fd.get('followed')==='on';if(selected)payload.version=selected.version;await api('/source-catalog'+(selected?'/'+selected.id:''),{method:selected?'PUT':'POST',json:payload});if(!view.sameUser())return;if(view.sameDialog())$('#dialog').close();if(view.sameRoute())await render(routeId);toast('来源存好了，下次提交可以直接选。');}
    catch(error){if(view.sameUser())toast(error.message,true);}finally{form.inert=false;finishFeedback();}
  });
  return {render};
}
