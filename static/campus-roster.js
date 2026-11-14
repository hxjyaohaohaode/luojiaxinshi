import {beginFormFeedback,captureUiContext} from './ui-request.js';

const roles={student:'学生',counselor:'辅导员',college_admin:'学院管理员'};
const roleKeys={学生:'student',辅导员:'counselor',学院管理员:'college_admin'};
const columns={账号:'username',账号名:'username',username:'username',角色:'role',role:'role',年级:'grade',grade:'grade',班级:'class_name',class_name:'class_name',负责范围:'scopes',scopes:'scopes'};

function tableRows(text,delimiter){
  const rows=[];let row=[],cell='',quoted=false,closed=false;
  for(let index=0;index<=text.length;index++){
    const char=text[index];
    if(quoted){
      if(char==='"'&&text[index+1]==='"'){cell+='"';index++;}
      else if(char==='"'){quoted=false;closed=true;}
      else if(char===undefined)throw Error('表格的引号尚未闭合，请检查多行单元格。');
      else cell+=char;
      continue;
    }
    if(char==='"'){
      if(cell.length||closed)throw Error('单元格中的引号需要写成两个连续的双引号。');
      quoted=true;continue;
    }
    if(char===delimiter||char==='\n'||char==='\r'||char===undefined){
      row.push(cell.trim());cell='';closed=false;
      if(char!==delimiter){
        if(row.some(Boolean))rows.push(row);
        row=[];
        if(char==='\r'&&text[index+1]==='\n')index++;
      }
    }else if(closed){
      if(!/\s/.test(char))throw Error('结束引号后应为分隔符或换行。');
    }else cell+=char;
  }
  return rows;
}

function parseScopes(text){
  return String(text||'').split(/[;；\n]+/).map(x=>x.trim()).filter(Boolean).map(scope=>{
    if(scope==='全院')return {all_college:true};
    const parts=scope.split(/[\/／]/).map(x=>x.trim());
    if(parts.length>2||!parts[0]||parts.length===2&&!parts[1])throw Error('负责范围应填写年级、年级 / 班级，或“全院”；多项用分号分隔。');
    return {grade:parts[0],class_name:parts[1]||''};
  });
}

export function parseRosterInput(raw){
  const text=String(raw||'').replace(/^\uFEFF/,'').trim();
  if(!text)throw Error('请粘贴成员表格，或选择“检查已有名称”。');
  if(text.length>256000)throw Error('内容过大，请分批粘贴，每次最多500行。');
  if(text.startsWith('[')){
    const rows=JSON.parse(text);
    if(!Array.isArray(rows)||!rows.length||rows.length>500||rows.some(x=>!x||typeof x!=='object'||Array.isArray(x)))throw Error('JSON应是1至500个成员对象组成的数组。');
    return rows;
  }
  const rows=tableRows(text,text.split(/\r?\n/,1)[0].includes('\t')?'\t':',');
  if(rows.length<2)throw Error('需要表头和至少一行成员，例如：账号,角色,年级,班级,负责范围。');
  const headers=rows.shift().map(x=>columns[x]);
  if(headers.some(x=>!x)||new Set(headers).size!==headers.length||!headers.includes('username')||!headers.includes('role'))throw Error('表头必须包含账号和角色；其他可用列为年级、班级、负责范围，不能重复。');
  if(rows.length>500)throw Error('一次最多预检500名成员，请分批操作。');
  return rows.map((cells,index)=>{
    if(cells.length!==headers.length)throw Error(`第 ${index+2} 行有 ${cells.length} 列，与表头不一致。`);
    const item=Object.fromEntries(headers.map((key,i)=>[key,cells[i]]));
    item.role=roleKeys[item.role]||item.role;
    if('scopes' in item)item.scopes=parseScopes(item.scopes);
    return item;
  });
}

export function createCampusRoster({state,api,esc,showDialog,toast}){
  const $=(selector,root=document)=>root.querySelector(selector);
  let active=null,controller=null,request=0;
  const scopeLabel=item=>!item?'未加入学院':[roles[item.role]||item.role,item.grade,item.class_name,
    ...(item.scopes||[]).map(s=>s.all_college||!s.grade?'全院':s.grade+(s.class_name?' / '+s.class_name:''))].filter(Boolean).join(' · ');
  const valid=entry=>active===entry&&entry.owner===state.session?.user?.id;
  function dispose(){controller?.abort();controller=null;active=null;request++;}
  function input(){
    if(!active)return;
    showDialog('批量录入与名称核对',`<section class="campus-roster-tool"><p class="small muted">先预检每个人的账号、学院身份和范围。确认前不会修改权限或补发通知。</p>
      <form id="campus-roster-input" class="stack"><label class="field">粘贴成员表格<textarea name="roster" rows="7" maxlength="256000" spellcheck="false" placeholder="账号,角色,年级,班级,负责范围">${esc(active.text||'')}</textarea></label>
      <details class="details"><summary>表格格式</summary><p class="small">可从表格软件复制带表头的单元格，也可粘贴CSV或JSON。表头：账号、角色、年级、班级、负责范围。角色使用学生、辅导员或学院管理员；能授予哪些角色仍由当前权限决定。</p><p class="small">学生填写年级和班级，负责范围留空；辅导员的年级和班级留空，在负责范围填“2026级 / 一班”或“2026级”，多项用分号分隔。只在确实负责全院时填写“全院”。</p><p class="small">2026可规范为2026级，“一年级”不会猜成某届。同名班级仍按年级区分。</p></details>
      <p class="small" data-roster-status role="status"></p><div class="row wrap"><button type="submit" class="button primary">预检成员表</button><button type="button" class="button" data-roster-normalize>检查已有名称</button></div></form></section>`,{replaceHistory:true});
  }
  function preview(result){
    if(!active)return;
    active.preview=result;
    if(!result.items?.length){
      $('[data-roster-status]').textContent=result.note||'没有需要修改的名称。';return;
    }
    const entries=result.items.map(item=>`<article class="roster-review-row ${item.errors.length?'roster-row-invalid':''}">
      <div class="row wrap"><label class="check"><input type="checkbox" name="roster_row" value="${item.index}" ${item.errors.length?'disabled':'checked'}><strong>${esc(item.username||'未填账号')}</strong></label><span class="small">第 ${item.index+1} 行 · ${item.errors.length?'需修正':'可提交'}</span></div>
      <dl class="roster-comparison"><dt>当前</dt><dd>${esc(scopeLabel(item.before))}</dd><dt>将改为</dt><dd>${esc(scopeLabel(item.normalized))}</dd></dl>
      ${item.errors.map(message=>`<p class="roster-error">${esc(message)}</p>`).join('')}${item.warnings.map(message=>`<p class="small muted">${esc(message)}</p>`).join('')}</article>`).join('');
    const impacts=(result.audience_impacts||[]).map(item=>`<li><strong>${esc(item.audience==='college'?'全院':item.grade+(item.class_name?' / '+item.class_name:''))}</strong>：${item.before_count} → ${item.after_count} 人${item.added.length?`<p class="small">新增：${item.added.map(esc).join('、')}</p>`:''}${item.removed.length?`<p class="small">移出：${item.removed.map(esc).join('、')}</p>`:''}</li>`).join('');
    showDialog('逐项核对成员',`<section class="campus-roster-tool"><p>可提交 ${result.valid} 行，需修正 ${result.invalid} 行。请选择本次要更新的无错行。</p>
      <form id="campus-roster-review" class="stack"><div class="roster-review-list">${entries}</div>
      ${impacts?`<details class="details"><summary>已有发布范围的成员变化</summary><p class="small muted">${esc(result.impact_note)}</p><ul>${impacts}</ul></details>`:''}
      <label class="check"><input type="checkbox" name="reviewed" required><span>已核对所选账号、变更前后身份和负责范围</span></label>
      <p class="small muted">预检10分钟内有效；成员或管理权限变化会要求重新核对。新权限即时生效，个人旧通知与办理记录保留，不会自动补发历史公告。</p>
      <p class="small" data-roster-status role="status"></p><div class="row wrap"><button class="button primary" type="submit" ${result.valid?'':'disabled'}>确认所选变更</button><button class="button plain" type="button" data-roster-back>返回修改</button></div></form></section>`,{replaceHistory:true});
  }
  async function loadPreview(form,normalize=false){
    if(!active)return;
    const entry=active,context=captureUiContext(state,form),sequence=++request;
    const finish=beginFormFeedback(form);if(!finish)return;
    const status=$('[data-roster-status]',form);
    controller?.abort();controller=new AbortController();const signal=controller.signal;
    form.inert=true;
    try{
      let json={college_id:entry.collegeId};
      if(!normalize){entry.text=form.elements.roster.value;json.rows=parseRosterInput(entry.text);}
      status.textContent='正在检查账号和当前授权范围…';
      const result=await api('/campus/roster/'+(normalize?'normalization-preview':'preview'),{method:'POST',json,signal});
      if(!valid(entry)||sequence!==request||!context.sameDialog())return;
      preview(result);
    }catch(error){if(valid(entry)&&context.sameDialog()&&error.name!=='AbortError')status.textContent=error.message;}
    finally{form.inert=false;finish();}
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-roster-normalize],[data-roster-back]');
    if(!button||button.disabled||!active)return;
    if(button.hasAttribute('data-roster-back')){active.preview=null;input();return;}
    loadPreview(button.closest('form'),true);
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;
    if(form.id==='campus-roster-input'){event.preventDefault();await loadPreview(form);return;}
    if(form.id!=='campus-roster-review'||!active)return;
    event.preventDefault();
    const indices=[...form.querySelectorAll('[name="roster_row"]:checked')].map(input=>Number(input.value));
    if(!indices.length){$('[data-roster-status]',form).textContent='请至少选择一行无错误的成员。';return;}
    if(!form.reportValidity())return;
    const entry=active,context=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
    form.inert=true;
    try{
      $('[data-roster-status]',form).textContent='正在保存所选身份，重复提交不会重复授权…';
      const result=await api('/campus/roster/commit',{method:'POST',json:{review:entry.preview.review,indices,reviewed:true}});
      if(!valid(entry)||!context.sameDialog())return;
      showDialog('成员变更已保存',`<section class="campus-roster-tool"><h3>已更新 ${Number(result.changed)} 名成员</h3><p>${esc(result.note)}</p><ul class="roster-receipt">${result.items.map(item=>`<li><strong>${esc(item.username)}</strong><span>${item.state==='saved'?'已更新':'内容一致，无需更改'} · 第 ${item.version} 版</span></li>`).join('')}</ul><p class="small muted">返回学院成员页可查看最新身份。需要补发有效公告时，再从发布记录明确选择补发。</p></section>`,{replaceHistory:true});
      toast('所选成员已保存');
      document.dispatchEvent(new CustomEvent('campus-roster-updated',{detail:{collegeId:entry.collegeId}}));
      entry.preview=null;
    }catch(error){if(valid(entry)&&context.sameDialog())$('[data-roster-status]',form).textContent=error.message;}
    finally{form.inert=false;finish();}
  });
  $('#dialog')?.addEventListener('close',dispose);
  $('#dialog')?.addEventListener('dialog-back',dispose);
  window.addEventListener('hashchange',dispose);
  return {open(collegeId){dispose();active={collegeId,owner:state.session?.user?.id,text:'',preview:null};input();},close:dispose};
}
