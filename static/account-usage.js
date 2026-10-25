export function installAccountUsage({state,api,esc,showDialog,toast}){
  document.addEventListener('click',async event=>{
    if(!event.target.closest('[data-action="account-usage"]'))return;
    event.preventDefault();event.stopPropagation();
    const session=state.session,route=state.renderId;
    try{
      const data=await api('/account/usage');if(session!==state.session||route!==state.renderId)return;
      const number=value=>Number(value).toLocaleString('zh-CN');
      const bytes=value=>value>=1024**3?(value/1024**3).toFixed(2)+' GB':value>=1024**2?(value/1024**2).toFixed(1)+' MB':number(value)+' 字节';
      const names={notices:'通知',conversations:'会话',sources:'来源',memory_projects:'项目',arrangements:'个人安排',tasks:'待办',storage_bytes:'文件与材料'};
      showDialog('账号容量',`<div class="stack"><dl class="usage-capacities">${Object.entries(names).map(([key,label])=>`<div class="between"><dt>${label}</dt><dd>${esc(key==='storage_bytes'?bytes(data.used[key]):number(data.used[key]))} / ${esc(key==='storage_bytes'?bytes(data.limits[key]):number(data.limits[key]))}</dd></div>`).join('')}</dl><p class="small">每天最多 ${number(data.limits.ai_daily)} 次 AI 整理与对话处理。自动整理可设置的上限为每天 ${number(data.limits.automation_daily_max)} 则。</p><p class="small">每个事项可保存 ${number(data.limits.materials_per_task)} 份本人材料，每份保留 ${number(data.limits.versions_per_material)} 个版本，保留 ${number(data.limits.submissions_per_task)} 次提交记录。</p></div>`);
    }catch(error){if(session===state.session&&route===state.renderId)toast(error.message,true);}
  },true);
}
