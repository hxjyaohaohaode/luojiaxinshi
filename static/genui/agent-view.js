import {el,button} from './dom.js';
import {protectOrphans} from './typography.js';

// Server-issued approvals live in the original assistant reply. Model HTML or
// prose never creates executable controls; digest binds the exact operation.
export class AgentView{
  constructor(parent,before){this.root=el('section','chat-agent-actions');parent.insertBefore(this.root,before);}
  update(message,{busy=false,readOnly=false}={}){
    // Regeneration may keep an older verified answer visible. Committed
    // operations from every attempt remain real and must stay visible too.
    const operations=[...new Map([...(message.versions||[]),message].flatMap(v=>v.agent?.operations||[]).map(o=>[o.operation_id,o])).values()];
    const state={...message.agent,operations},key=JSON.stringify([message.status,state,busy,readOnly]);if(key===this.key)return;this.key=key;
    const previous=this.root.querySelector('.chat-research'),wasOpen=previous?.open;
    const restoreFocus=previous?.querySelector('summary')===document.activeElement;
    this.root.replaceChildren();
    this.root.hidden=!(state.approvals?.length||state.files?.length||state.operations?.length||state.research_items?.length);
    if(state.research_items?.length){
      const items=state.research_items,details=el('details','chat-research'),summary=el('summary');
      const open=items.filter(item=>item.state==='open').length,blocked=items.filter(item=>item.state==='blocked').length;
      details.open=wasOpen??(message.status==='processing');
      summary.append(el('strong','','本轮资料核对'),el('span','small muted',
        [items.length+' 项',open?'待核 '+open:'',blocked?'缺少依据 '+blocked:''].filter(Boolean).join(' · ')));
      const list=el('ul');
      for(const item of items){
        const row=el('li'),label={open:'待核对',sourced:'已找到依据',blocked:'待补充'}[item.state]||'待核对';
        row.dataset.state=item.state;
        row.append(el('span','research-state',label),el('span','research-topic',item.topic));
        if(item.detail)row.append(el('p','small muted',item.detail));
        list.append(row);
      }
      details.append(summary,list);this.root.append(details);
      if(restoreFocus)summary.focus({preventScroll:true});
    }
    for(const operation of state.operations||[]){
      const row=el('div','chat-operation'),content=el('div'),label={'calendar.create':'已添加到日历','calendar.update':'已修改日历','calendar.delete':'已删除日历安排','tasks.create':'已创建待办','tasks.update':operation.record?.status==='done'?'已标记完成':operation.record?.status==='cancelled'?'已取消待办':'已修改待办'}[operation.operation]||'操作已保存';
      content.append(el('strong','',operation.title),el('span','small muted',operation.status==='undone'?'已撤销':label));row.append(content);
      const link=el('a','button small plain',operation.destination==='#calendar'?'查看日历':'查看待办');link.href=operation.destination==='#calendar'?'#calendar':'#tasks';row.append(link);
      if(operation.undo_available&&message.status!=='processing'&&!busy&&!readOnly){const undo=button('撤销',null,'button small plain');undo.dataset.chatAction='undo-operation';undo.dataset.operation=operation.operation_id;row.append(undo);}
      this.root.append(row);
    }
    if(message.status==='processing')for(const approval of state.approvals||[]){
      const card=el('div','chat-agent-approval'),label={write_file:'保存文件',exec_command:'执行沙箱命令',mcp_call:'调用外部工具',task_write:'确认待办状态变更',calendar_write:'确认移除日历安排'}[approval.tool]||'执行操作';
      card.append(el('strong','',label+' · 等待确认'));
      const args=approval.arguments;
      if(args.target_title)card.append(el('p','small',args.target_title+({done:' · 标记完成',pending:' · 恢复待办',cancelled:' · 取消待办'}[args.status]||'')));
      if(approval.tool==='write_file')card.append(el('p','small',args.path+(args.expected_sha256?' · 将覆盖现有文件':'')));
      if(approval.tool==='mcp_call')card.append(el('p','small muted','以下参数将发送给 '+args.server+' / '+args.tool));
      const details=el('details'),summary=el('summary','',approval.tool==='write_file'?'查看完整文件内容':approval.tool==='mcp_call'?'查看发送参数':'查看完整操作'),pre=el('pre');pre.textContent=approval.tool==='write_file'?args.content:JSON.stringify(approval.tool==='mcp_call'?args.arguments:args,null,2);details.append(summary,pre);card.append(details);
      const actions=el('div','actions');for(const [value,title] of [['approve','批准本次'],['deny','拒绝']]){const control=button(title,null,'button small'+(value==='approve'?' primary':''));control.dataset.chatAction='agent-approval';control.dataset.id=message.id;control.dataset.approval=approval.id;control.dataset.digest=approval.digest;control.dataset.decision=value;actions.append(control);}card.append(actions);this.root.append(card);
    }
    protectOrphans(this.root);
    if(state.files?.length&&/^[a-f0-9]{32}$/.test(state.thread_id)){
      const list=el('ul','chat-agent-files');for(const file of state.files){const row=el('li'),a=el('a','',file.path);a.href='/api/agent/threads/'+state.thread_id+'/file?path='+encodeURIComponent(file.path);a.setAttribute('download','');row.append(a);list.append(row);}this.root.append(list);
    }
  }
}
