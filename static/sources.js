import {brandMotion} from './motion.js';
import {searchControls,WorkspaceSearch} from './workspace-search.js';
const $=(s)=>document.querySelector(s);
const platforms={website:'学校 / 学院官网',wechat_public:'微信公众号',qq_group:'QQ 群',wechat_group:'微信群',campus:'校内平台',other:'其他来源'};
export function createSourcesUI({state,api,esc,icon,field,area,showDialog,ask,toast,route}){
  let entries=[],query='',editing=null,integrations=null,publisherItems=[],publisherNext=null,page=1,searchController=null,matchedIds=null;
  const action=(text,name,id='',cls='')=>`<button type="button" class="button ${cls}" data-source-action="${name}" data-id="${id}">${text}</button>`;
  async function render(renderId){
    const [result,channels]=await Promise.all([api('/source-catalog'),api('/integrations')]);if(renderId!==state.renderId)return;entries=result;integrations=channels;query='';page=1;matchedIds=null;searchController?.dispose();
    $('#content').innerHTML=`<div class="page-title between"><div><div class="eyebrow">知道消息从哪里来</div><h1>我的通知来源</h1><p>把官网、公众号和群整理在一起。每个来源的用途、学期和接入方式都清楚可见。</p></div>${action(icon('plus')+' 添加来源','add','','primary')}</div>
      <div class="toolbar source-toolbar"><h2>我登记的来源 <span class="muted small" id="catalog-total"></span></h2>${searchControls({id:"source",esc,icon,scope:"sources",kinds:Object.entries(platforms)})}</div><div id="source-catalog-list" class="source-catalog-list"></div><nav id="source-pages" class="calendar-pagination" aria-label="来源分页" hidden></nav>
      <div class="source-access">${action('平台接入与覆盖范围 '+icon('arrow'),'platforms','','small plain')}</div>`;
    searchController=new WorkspaceSearch(document.querySelector('[data-search-host="source"]'),{api,scope:'sources',onResult:result=>{matchedIds=new Set(result.items.map(s=>s.id));query=result.query;page=1;list();},onError:message=>toast(message,true)});list();
  }
  function integrationCards(){
    if(!$('#integration-cards')||!integrations)return;const q=integrations.qq,w=integrations.wechat_publisher;
    const card=(title,status,detail,footer,ready=false)=>`<article class="integration-card"><div class="between"><h3>${title}</h3><span class="pill ${ready?'green':''}">${status}</span></div><p>${detail}</p><div class="integration-path">${footer}</div></article>`;
    $('#integration-cards').innerHTML=card('QQ 机器人单聊',q.bound?'已绑定 · 等待本人提交':q.configured?'已配置 · 待本人绑定':'未配置机器人',
      '绑定后，只接收你主动发给此机器人的单聊消息，存入你的对话。附件、聊天记录卡片和引用需补交原件。本入口不抓取群历史，也不向好友发消息。',
      q.configured?`<div class="row wrap">${action(q.bound?'刷新收件状态':'绑定我的 QQ','qq-bind','','small primary')}${q.bound?action('解除绑定','qq-unlink','','small plain danger'):''}</div>${q.binding?.last_received_at?`<p class="small">最近收件：${esc(new Date(q.binding.last_received_at*1000).toLocaleString('zh-CN'))}</p>`:''}`:'<span>需要管理员配置</span>机器人 AppID、Secret 和公开 HTTPS 回调地址。现在仍可主动上传文字、截图和附件。',q.bound)+
      card('获授权公众号文章',w.configured?'已配置 · 权限以平台为准':'未配置发布账号',
        '读取获授权发布账号的已发布文章，由管理员选择导入。正文和 HTML 原件会保存；图片与外链附件需补齐。不读取个人微信聊天或公众号关注列表。',
        w.configured&&w.can_import?action('选择文章导入','publisher','','small primary'):w.configured?'请联系此服务管理员导入获授权文章。':'<span>需要管理员配置</span>获授权发布账号的 AppID、Secret、接口权限及 IP 白名单。',false)+
      card('智慧珞珈与校内身份','待校方接口授权','学校统一身份、课表和通知接口需要校方接入协议。填写学号或工号用于辅助判断适用范围，目前属于本人自填。','<a href="#settings" class="button small">完善我的个人条件</a>')+
      card('个人日历','文件导出已实现','已核对的待办可导出 .ics。导入后的修改与取消需要在目标日历核对，导出不代表锁屏提醒已送达。','<a href="#calendar" class="button small">查看日历与提醒指引</a>',true);
  }
  async function refreshIntegrations(){integrations=await api('/integrations');integrationCards();return integrations;}
  async function bindingDialog(){
    const result=await refreshIntegrations();
    if(result.qq.bound){toast('账号已绑定。发给机器人的新单聊会出现在历史对话中。');return;}
    showDialog('绑定我的 QQ 机器人收件',`<div class="stack"><p>只将自己主动发送给此机器人的内容收进自己的账号。绑定并不代表学校认证，也不会授予读取群历史的权限。</p><label class="check"><input id="qq-binding-consent" type="checkbox"><span>我同意接收本人主动提交给此机器人的单聊内容，并保存在当前服务中。</span></label><div id="qq-binding-code" aria-live="polite"></div><div class="row wrap">${action('生成一次性绑定指令','qq-code','','primary')}${action('我已发送，检查绑定','qq-check','','small')}</div></div>`);
  }
  async function publisherDialog(offset=0){
    const result=await api('/integrations/wechat/articles?offset='+offset);publisherItems=result.items;publisherNext=result.next_offset;
    showDialog('选择获授权的公众号文章',`<div class="stack"><p class="small muted">选择后保存到你自己的对话，可继续上传附件、提问，再转为通知核对。接口列表中的多图文按篇显示。</p><div class="publisher-articles">${publisherItems.length?publisherItems.map((item,i)=>`<div class="publisher-article"><strong>${esc(item.title)}</strong>${action('导入','publisher-import',String(i),'small primary')}</div>`).join(''):'<p>发布账号中没有可读取的已发布文章。</p>'}</div><div class="row wrap">${offset?action('回到第一批','publisher','','small'):''}${publisherNext!==null?action('下一批','publisher-next','','small'):''}</div></div>`);
  }
  function list(){
    if(!$('#source-catalog-list'))return;
    const matched=entries.filter(e=>matchedIds?matchedIds.has(e.id):Object.values(e.data).join(' ').toLowerCase().includes(query.toLowerCase()));
    const pages=Math.max(1,Math.ceil(matched.length/12));page=Math.min(page,pages);const pager=$('#source-pages');pager.hidden=pages===1;pager.innerHTML=action('上一页','page-prev','','small')+`<span>${page} / ${pages}</span>`+action('下一页','page-next','','small');pager.querySelector('[data-source-action=page-prev]').disabled=page===1;pager.querySelector('[data-source-action=page-next]').disabled=page===pages;
    $('#catalog-total').textContent=`${matched.length} / ${entries.length}`;
    const searching=!!query||!!matchedIds&&entries.length>0,emptyKey=matched.length?'':searching?'search':'radar',target=$('#source-catalog-list');
    if(!emptyKey||target.dataset.emptyKey!==emptyKey)target.innerHTML=matched.length?matched.slice((page-1)*12,page*12).map(e=>`<details class="catalog-card"><summary><div class="catalog-heading"><span class="catalog-icon">${icon(e.data.platform==='website'?'doc':'grid')}</span><div><span class="small muted">${platforms[e.data.platform]}</span><h3>${esc(e.data.name)}</h3></div><span class="pill">手工提交</span></div></summary><div class="catalog-body"><p>${esc(e.data.purpose||'还未填写用途，编辑后方便以后识别。')}</p><div class="catalog-meta"><span>${esc(e.data.institution||'发布主体待补充')}</span>${e.data.semester?`<span>${esc(e.data.semester)}</span>`:''}${e.data.platform==='wechat_public'?`<span>${e.data.followed?'本人标记已关注':'未标记关注'}</span>`:''}</div><div class="catalog-actions">${action('提交该来源通知','submit',e.id,'small primary')}${e.data.url?`<a class="button small" href="${esc(e.data.url)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a>`:''}${action('编辑','edit',e.id,'small plain')}${action('移除','delete',e.id,'small plain danger')}</div></div></details>`).join(''):`<div class="source-directory-empty">${brandMotion(searching?'search':'radar','',{priority:2})}<h3>${searching?'没有找到这个来源':'记下一个经常收到通知的地方'}</h3><p>${searching?'可以换一个词，也可以清空搜索。':'例如学院官网、年级群，或你关注的公众号。'}</p>${searching?'<button type="button" class="button small" data-source-action="clear-search">清空搜索</button>':action('添加第一个来源','add','','small')}</div>`;
    target.dataset.emptyKey=emptyKey;
  }
  function editor(entry){
    editing=entry;const d=entry?.data||{};
    showDialog(entry?'编辑来源':'添加常用通知来源',`<form class="stack" data-workspace-form="source-catalog"><div class="form-grid">${field('来源名称','name',d.name||'','text','required maxlength="100" placeholder="例如：资环学院官网、2026 级年级群"')}<label class="field">平台<select name="platform">${Object.entries(platforms).map(([k,v])=>`<option value="${k}" ${d.platform===k?'selected':''}>${v}</option>`).join('')}</select></label>${field('发布主体','institution',d.institution||'','text','maxlength="100" placeholder="学院、课程组或组织"')}${field('关联学期（选填）','semester',d.semester||'','text','maxlength="40" placeholder="用于区分本学期与往期课程群"')}</div>${field('可回查的公开链接（选填）','url',d.url||'','url','maxlength="2000" placeholder="https://…"')}${area('我主要从这里接收什么','purpose',d.purpose||'',3,'maxlength="300" placeholder="例如：本学期课程调整、报名通知、组织活动"')}<label class="check" data-followed-field ${d.platform==='wechat_public'?'':'hidden'}><input type="checkbox" name="followed" ${d.followed?'checked':''}><span>我已关注此公众号（由本人登记，不读取微信关注列表）</span></label><p class="small muted">目前通过本人主动提交收件。群成员资格、公众号发布授权、学校认证分别核实，不会因为登记而自动获取聊天记录。</p><div class="form-footer"><button class="button" type="button" data-action="close-dialog">返回</button><button class="button primary" type="submit">保存来源</button></div></form>`);
  }
  document.addEventListener('change',e=>{if(e.target.name==='platform'&&e.target.closest('[data-workspace-form=source-catalog]')){const f=e.target.form.querySelector('[data-followed-field]');f.hidden=e.target.value!=='wechat_public';}});

  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-source-action]');if(!b||b.disabled)return;b.disabled=true;
    try{const item=entries.find(s=>s.id===b.dataset.id),action=b.dataset.sourceAction;
      if(action==='page-prev'||action==='page-next'){page+=action==='page-prev'?-1:1;list();$('#source-catalog-list').scrollIntoView({block:'start'});}
      else if(action==='platforms'){showDialog('平台接入与覆盖范围','<div id="integration-cards" class="stack"></div>');integrationCards();}
      else if(action==='clear-search'){searchController.clear();}
      else if(action==='add')editor(null);
      else if(action==='edit'&&item)editor(item);
      else if(action==='submit'&&item){state.sourcePreset=item.data;location.hash='new';}
      else if(action==='delete'&&item&&await ask('移除这个来源','来源登记将移除，已经保存的通知、对话和待办仍保留。','移除')){await api('/source-catalog/'+item.id,{method:'DELETE',json:{version:item.version}});entries=entries.filter(s=>s.id!==item.id);list();toast('来源已移除。');}
      else if(action==='qq-bind')await bindingDialog();
      else if(action==='qq-code'){
        if(!$('#qq-binding-consent')?.checked){toast('请先确认仅接收自己主动提交的内容。',true);return;}
        const result=await api('/integrations/qq/link-code',{method:'POST',json:{receive_my_submissions:true}});
        if(!$('#qq-binding-code'))return;
        $('#qq-binding-code').innerHTML=`<label class="field">复制整条指令，发给 AppID 为 ${esc(result.app_id)} 的机器人<input id="qq-copy-command" readonly value="${esc(result.command)}"></label><p class="small muted">5 分钟内有效，用一次即失效。请只发送给管理员指定的机器人，勿转发给其他人。</p>`;
        $('#qq-copy-command').select();toast('指令已生成，可长按复制。');
      }
      else if(action==='qq-check'){const result=await refreshIntegrations();if(result.qq.bound){$('#dialog').close();toast('绑定成功。现在可以主动发送第一条通知给机器人了。');}else toast('还没有收到有效绑定，请核对机器人和指令是否正确、是否已过期。',true);}
      else if(action==='qq-unlink'&&await ask('解除 QQ 收件绑定','解除后不再接收后续消息，已保存的对话仍保留。','解除绑定')){await api('/integrations/qq/unlink',{method:'POST'});await refreshIntegrations();toast('已解除 QQ 收件绑定。');}
      else if(action==='publisher')await publisherDialog();
      else if(action==='publisher-next'&&publisherNext!==null)await publisherDialog(publisherNext);
      else if(action==='publisher-import'){
        const selected=publisherItems[Number(b.dataset.id)];if(!selected)return;
        const result=await api('/integrations/wechat/import',{method:'POST',json:{article_id:selected.article_id,index:selected.index}});
        if(result.deleted_before){toast('这篇文章曾导入后删除；本次没有重新创建。',true);return;}
        $('#dialog').close();location.hash='chat/'+result.conversation_id;toast(result.already_imported?'已打开之前导入的对话。':'文章已存入对话，请核对正文并补齐图片与附件。');
      }
    }catch(error){toast(error.message,true);}finally{b.disabled=false;}
  });
  document.addEventListener('submit',async e=>{
    const form=e.target;if(form.dataset.workspaceForm!=='source-catalog')return;e.preventDefault();const submit=form.querySelector('[type=submit]');if(submit.disabled)return;submit.disabled=true;const routeId=state.renderId,selected=editing;
    try{const fd=new FormData(form),payload=Object.fromEntries(fd);payload.followed=payload.platform==='wechat_public'&&fd.get('followed')==='on';if(selected)payload.version=selected.version;await api('/source-catalog'+(selected?'/'+selected.id:''),{method:selected?'PUT':'POST',json:payload});if(routeId===state.renderId){$('#dialog').close();await render(routeId);}toast('来源已保存，以后提交时可以直接选用。');}
    catch(error){toast(error.message,true);}finally{submit.disabled=false;}
  });
  return {render};
}
