import {captureUiContext,beginFormFeedback} from './ui-request.js';

// DOM selection counts UTF-16 code units; the API uses Unicode characters.
export function characterRange(text,start,end){return [Array.from(text.slice(0,start)).length,Array.from(text.slice(0,end)).length];}

export function createMemoryAssist({state,api,esc,showDialog,toast,refresh}){
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-memory-assist]');if(!target||target.disabled)return;
    const view=captureUiContext(state,target);target.disabled=true;
    try{
      const item=await api('/memory/items/'+encodeURIComponent(target.dataset.id));if(!view.sameDialog())return;
      showDialog('让 AI 修改记忆',`<form class="stack" data-memory-assist-form><p class="small muted">选中某段即可只改这段；不选文字则整理整条。范围外的正文保持原样。</p><label class="field">当前正文<textarea name="original" readonly rows="7">${esc(item.content)}</textarea></label><p class="small" data-assist-range>将整理整条记忆</p><label class="field">修改或补充要求<textarea name="instruction" required maxlength="1500" rows="3" placeholder="例如：只把所选部分的办理地点改为行政楼 201，保留其他内容"></textarea></label><p class="small muted">点击后，会把选中内容和修改要求发送给已配置的模型，并保存结果。自动保留历史版本；原文不足以支持的新事实不会要求 AI 自行补全。</p><p role="status" data-assist-status></p><div class="form-footer"><button class="button primary" type="submit">AI 修改并保存</button></div></form>`);
      const form=document.querySelector('[data-memory-assist-form]'),original=form.elements.original,status=form.querySelector('[data-assist-status]');
      original.closest('label').insertAdjacentHTML('beforebegin','<label class="field">修改方式<select name="edit_mode"><option value="selection">修改选中部分，未选则整理整条</option><option value="append">仅在末尾补充，保留全部原文</option><option value="all">整理整条记忆</option></select></label>');
      let failedRequest=false;
      let start=0,end=Array.from(item.content).length,lastPayload='',key='';
      let selection=[start,end];
      function range(){
        const total=Array.from(item.content).length,mode=form.elements.edit_mode.value;
        [start,end]=mode==='append'?[total,total]:mode==='all'?[0,total]:selection;
        form.querySelector('[data-assist-range]').textContent=mode==='append'?`仅在末尾补充；原文保持原样，还可补充 ${2000-total} 个字符`:start===0&&end===total?'将整理整条记忆':`只修改选中的 ${end-start} 个字符，其余保持原样`;
      }
      form.elements.edit_mode.addEventListener('change',range);
      original.addEventListener('select',()=>{
        selection=characterRange(item.content,original.selectionStart,original.selectionEnd);
        if(selection[0]===selection[1])selection=[0,Array.from(item.content).length];
        range();
      });
      form.addEventListener('submit',async event=>{
        event.preventDefault();const current=captureUiContext(state,form),finish=beginFormFeedback(form);if(!finish)return;
        range();const payload={version:item.version,instruction:form.elements.instruction.value,start,end,allow_external_processing:true};
        const serialized=JSON.stringify(payload);if(serialized!==lastPayload||!key){key=crypto.randomUUID();lastPayload=serialized;}
        form.inert=true;status.textContent='AI 正在修改，完成后自动保存…';
        try{
          await api(`/memory/items/${encodeURIComponent(item.id)}/assist`,{method:'POST',json:payload,headers:{'Idempotency-Key':key}});
          if(!current.sameUser())return;if(current.sameDialog())document.querySelector('#dialog').close();if(current.sameRoute())await refresh();toast('AI 修改已保存，可以在来源与历史中查看修改前的版本。');
        }catch(error){
          if(current.sameDialog()){status.textContent=error.message;if(error.status===502){key='';failedRequest=true;}}
          if(current.sameUser())toast(error.message,true);
        }finally{form.inert=false;finish();if(failedRequest)form.querySelector('[type="submit"]').textContent='重新请求 AI 修改（可能再次计费）';}
      });
    }catch(error){if(view.sameUser())toast(error.message,true);}finally{target.disabled=false;}
  });
}
