import {el,button} from './dom.js';

// Server-issued approvals live in the original assistant reply. Model HTML or
// prose never creates executable controls; digest binds the exact operation.
export class AgentView{
  constructor(parent,before){this.root=el('section','chat-agent-actions');parent.insertBefore(this.root,before);}
  update(message){
    const state=message.agent,key=JSON.stringify([message.status,state]);if(key===this.key)return;this.key=key;
    this.root.replaceChildren();this.root.hidden=!state||!(state.approvals?.length||state.files?.length);if(!state)return;
    if(message.status==='processing')for(const approval of state.approvals||[]){
      const card=el('div','chat-agent-approval'),label={write_file:'保存文件',exec_command:'执行沙箱命令',mcp_call:'调用外部工具'}[approval.tool]||'执行操作';
      card.append(el('strong','',label+' · 等待确认'));
      const args=approval.arguments;
      if(approval.tool==='write_file')card.append(el('p','small',args.path+(args.expected_sha256?' · 将覆盖现有文件':'')));
      if(approval.tool==='mcp_call')card.append(el('p','small muted','以下参数将发送给 '+args.server+' / '+args.tool));
      const details=el('details'),summary=el('summary','',approval.tool==='write_file'?'查看完整文件内容':approval.tool==='mcp_call'?'查看发送参数':'查看完整操作'),pre=el('pre');pre.textContent=approval.tool==='write_file'?args.content:JSON.stringify(approval.tool==='mcp_call'?args.arguments:args,null,2);details.append(summary,pre);card.append(details);
      const actions=el('div','actions');for(const [value,title] of [['approve','批准本次'],['deny','拒绝']]){const control=button(title,null,'button small'+(value==='approve'?' primary':''));control.dataset.chatAction='agent-approval';control.dataset.id=message.id;control.dataset.approval=approval.id;control.dataset.digest=approval.digest;control.dataset.decision=value;actions.append(control);}card.append(actions);this.root.append(card);
    }
    if(state.files?.length&&/^[a-f0-9]{32}$/.test(state.thread_id)){
      const list=el('ul','chat-agent-files');for(const file of state.files){const row=el('li'),a=el('a','',file.path);a.href='/api/agent/threads/'+state.thread_id+'/file?path='+encodeURIComponent(file.path);a.setAttribute('download','');row.append(a);list.append(row);}this.root.append(list);
    }
  }
}
