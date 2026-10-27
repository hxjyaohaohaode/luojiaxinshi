/* Opaque-origin frame only. Never imported or executed by the host application. */
(()=>{
  'use strict';
  const root=document.getElementById('openui-root'),error=document.getElementById('openui-error');
  const post=parent.postMessage.bind(parent),pending=new Map(),nativeAdd=EventTarget.prototype.addEventListener,now=performance.now.bind(performance);
  const style=document.createElement('style');document.head.append(style);
  let token=null,enabled=false,approved=false,started=false,failed=false,gestureUntil=0,sequence=0,rendered='',initial=null,initialContract=null,scheduled=0,textFrame=0;
  const lockedButtons=new Map();
  const send=(type,data={})=>post({channel:'campus-openui',token,type,...data},'*');
  const reportError=message=>{error.hidden=false;error.textContent=message;measure();};
  function controls(){const values={};for(const input of root.querySelectorAll('input,select,textarea')){const key=input.id||input.name;if(!key||['file','password','button','reset','submit'].includes(input.type))continue;Object.defineProperty(values,key,{value:input.type==='checkbox'||input.type==='radio'?input.checked:input.value,enumerable:true,configurable:true});}return values;}
  function contracts(){const out={};for(const input of root.querySelectorAll('input,select,textarea')){const key=input.id||input.name;if(!key)continue;out[key]={type:input.type||input.tagName,label:input.labels?.[0]?.textContent?.trim()||input.getAttribute('aria-label')||key,min:input.getAttribute('min'),max:input.getAttribute('max'),step:input.getAttribute('step'),options:input.tagName==='SELECT'?[...input.options].map(o=>o.value):null};}return out;}
  function lockActions(){if(approved)return;for(const b of root.querySelectorAll('button:not([data-ui-local])')){if(!lockedButtons.has(b))lockedButtons.set(b,b.disabled);if(!b.disabled)b.disabled=true;}}
  function publishText(){if(textFrame||!enabled)return;textFrame=requestAnimationFrame(()=>{textFrame=0;const values=controls(),fields=[];for(const input of root.querySelectorAll('input,select,textarea')){const key=input.id||input.name;if(!Object.hasOwn(values,key)||input.type==='hidden')continue;const label=input.labels?.[0]?.innerText?.trim()||input.getAttribute('aria-label')||key;fields.push(label+'：'+(typeof values[key]==='boolean'?(values[key]?'已选中':'未选中'):values[key]));}send('text',{text:root.innerText+'\n\n'+fields.join('\n')});});}
  function changed(){if(enabled)send('state',{controls:controls()});if(!approved)queueMicrotask(lockActions);measure();publishText();}
  function measure(){if(scheduled)return;scheduled=requestAnimationFrame(()=>{scheduled=0;const rect=root.getBoundingClientRect();const e=error.hidden?0:error.getBoundingClientRect().height+16;send('resize',{height:Math.ceil(Math.max(rect.height,root.scrollHeight)+e)});});}
  function request(name,args){
    if(!approved)return Promise.reject(Error('内容正在核对，完成后可继续提问或打开来源。'));
    if(!enabled||now()>gestureUntil)return Promise.reject(Error('请点击操作后再继续。'));
    gestureUntil=0;
    const id=++sequence;send('state',{controls:controls()});
    return new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{pending.delete(id);reject(Error('操作未完成，请核对当前对话后重试。'));},60000);pending.set(id,{resolve,reject,timeout});send('action',{id,name,args});});
  }
  function bindForm(config){
    if(!config||!config.inputs||!config.outputs)throw Error('互动表单配置不完整');
    // Unambiguous spelling compatibility: some authors put the numeric
    // precision next to output functions. Move only this metadata field when
    // there is no competing top-level value or actual result element.
    if(config.digits===undefined&&Number.isInteger(config.outputs.digits)&&!root.querySelector('#digits')){
      const {digits,...outputs}=config.outputs;config={...config,digits,outputs};
    }
    const inputs=Object.entries(config.inputs).map(([id,rules])=>{rules=rules||{};const node=root.querySelector('#'+CSS.escape(id));if(!node||!node.matches('input,select,textarea'))throw Error('找不到输入字段：'+id);if(['min','max','step'].some(k=>rules[k]!==undefined&&!Number.isFinite(rules[k]))||rules.step!==undefined&&rules.step<=0||rules.min!==undefined&&rules.max!==undefined&&rules.min>rules.max)throw Error('字段范围配置无效：'+id);return {id,node,rules,label:node.labels?.[0]?.innerText?.trim()||node.getAttribute('aria-label')||id};});
    const outputs=Object.entries(config.outputs).map(([id,compute])=>{const node=root.querySelector('#'+CSS.escape(id));if(!node||typeof compute!=='function')throw Error('计算结果配置无效：'+id);return {id,node,compute};});
    let errorNode=config.error?root.querySelector('#'+CSS.escape(config.error)):null;
    if(!errorNode){errorNode=document.createElement('p');errorNode.className='ui-error';errorNode.setAttribute('role','status');root.append(errorNode);}
    if(config.digits!==undefined&&(!Number.isInteger(config.digits)||config.digits<0||config.digits>6))throw Error('结果精度配置无效');
    const format=new Intl.NumberFormat(document.documentElement.lang||'zh-CN',{maximumFractionDigits:config.digits??2});
    let current={values:{},results:{},valid:false};
    function update(){
      const values={},results={};let issue='';
      for(const {id,node,rules,label}of inputs){
        const raw=node.value.trim();let value;
        if(rules.type==='text')value=raw;
        else if(node.type==='checkbox'||node.type==='radio')value=node.checked;
        else{
          value=raw===''?NaN:Number(raw);
          const invalid=!Number.isFinite(value)||(rules.integer&&!Number.isInteger(value))||(rules.min!==undefined&&value<rules.min)||(rules.max!==undefined&&value>rules.max)||(rules.step!==undefined&&Number.isFinite(value)&&Math.abs((value-(rules.min??0))/rules.step-Math.round((value-(rules.min??0))/rules.step))>1e-7);
          if(invalid&&!issue)issue=raw===''?label+'不能为空':label+'须为'+(rules.min!==undefined&&rules.max!==undefined?rules.min+' 至 '+rules.max+' 的':'有效')+(rules.integer?'整数':'数值');
          if(invalid)node.setAttribute('aria-invalid','true');else node.removeAttribute('aria-invalid');
        }
        values[id]=value;
      }
      if(!issue){try{for(const {id,compute}of outputs){const value=compute(Object.freeze({...values}));if(!['number','string','boolean'].includes(typeof value)||typeof value==='number'&&!Number.isFinite(value))throw Error('当前输入无法计算，请检查取值');results[id]=value;}}catch(e){issue=e.message||'当前输入无法计算';}}
      for(const {id,node}of outputs)node.textContent=issue?'—':typeof results[id]==='number'?format.format(results[id]):String(results[id]);
      errorNode.textContent=issue;errorNode.hidden=!issue;current={values,results,valid:!issue};publishText();measure();return current;
    }
    for(const {node}of inputs){nativeAdd.call(node,'input',update);nativeAdd.call(node,'change',update);}
    if(config.prompt){
      const button=root.querySelector('#'+CSS.escape(config.prompt.id));
      if(!button||typeof config.prompt.text!=='string'||!config.prompt.text.trim())throw Error('继续提问按钮配置无效');
      const status=config.prompt.status?root.querySelector('#'+CSS.escape(config.prompt.status)):errorNode;
      nativeAdd.call(button,'click',async event=>{
        event.preventDefault();event.stopImmediatePropagation();
        const value=update();if(!value.valid)return;button.disabled=true;if(status){status.hidden=false;status.textContent='正在发送…';}
        try{await request('sendPrompt',{text:config.prompt.text,values:{...value.values,...value.results}});if(status)status.textContent='已发送';}
        catch(e){if(status)status.textContent=e.message||'发送未完成，请重试';}
        finally{button.disabled=false;lockActions();publishText();}
      },true);
    }
    update();return Object.freeze({update,values:()=>({...current.values}),results:()=>({...current.results})});
  }
  const api=Object.freeze({form:bindForm,sendPrompt:args=>request('sendPrompt',args),openLink:args=>request('openLink',args),hostAction:args=>request('hostAction',args)});
  Object.defineProperty(window,'CampusUI',{value:api,writable:false,configurable:false});
  Object.defineProperty(window,'Websandbox',{value:Object.freeze({connection:Object.freeze({remote:api})}),writable:false,configurable:false});
  function sanitize(html){
    const body=new DOMParser().parseFromString('<body>'+html,'text/html').body;
    for(const bad of body.querySelectorAll('script,iframe,frame,object,embed,base,link,meta,style,foreignObject,animate,set'))bad.remove();
    for(const node of body.querySelectorAll('*')){
      for(const attr of [...node.attributes])if(/^on/i.test(attr.name)||['srcdoc','formaction','action','ping','target','download','autofocus','srcset'].includes(attr.name)||((attr.name==='src'||attr.name.endsWith(':href'))&&!/^(data:image\/(?:png|jpeg|webp);base64,|#)/i.test(attr.value)))node.removeAttribute(attr.name);
      if(node.tagName==='A'&&node.hasAttribute('href')){const href=node.getAttribute('href');if(!href.startsWith('#')&&!/^https:\/\//i.test(href))node.removeAttribute('href');}
      if(node.tagName==='INPUT'&&['file','password'].includes(node.type))node.remove();
    }
    return body;
  }
  // Reconcile the growing preview in place. Existing nodes, focus and reading
  // position survive arrival of the next chunk and the verified final document.
  function morph(target,source){
    const incoming=[...source.childNodes];let cursor=target.firstChild;
    for(const fresh of incoming){
      let old=cursor;
      if(fresh.nodeType===1&&fresh.id){const keyed=[...target.children].find(n=>n.id===fresh.id);if(keyed)old=keyed;}
      if(old&&old.nodeType===fresh.nodeType&&(old.nodeType!==1||old.tagName===fresh.tagName)){
        if(old!==cursor)target.insertBefore(old,cursor);
        if(old.nodeType===3){if(old.data!==fresh.data)old.data=fresh.data;}
        else if(old.nodeType===1){for(const a of [...old.attributes])if(!fresh.hasAttribute(a.name))old.removeAttribute(a.name);for(const a of [...fresh.attributes])if(old.getAttribute(a.name)!==a.value)old.setAttribute(a.name,a.value);morph(old,fresh);}
        cursor=old.nextSibling;
      }else{const clone=fresh.cloneNode(true);target.insertBefore(clone,cursor);if(clone.nodeType===1&&target===root&&!matchMedia('(prefers-reduced-motion: reduce)').matches)clone.animate([{opacity:.5},{opacity:1}],{duration:160,easing:'ease-out'});}
    }
    while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
  }
  function citations(){
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[];
    while(walker.nextNode())if(!walker.currentNode.parentElement.closest('button,script,style,textarea,code,pre'))nodes.push(walker.currentNode);
    for(const node of nodes){if(!/\[\d+\]/.test(node.data))continue;const fragment=document.createDocumentFragment();let last=0;for(const m of node.data.matchAll(/\[(\d+)\]/g)){fragment.append(node.data.slice(last,m.index));const b=document.createElement('button');b.className='openui-citation';b.type='button';b.textContent='['+m[1]+']';b.dataset.citation=m[1];b.setAttribute('aria-label','查看依据 '+m[1]);fragment.append(b);last=m.index+m[0].length;}fragment.append(node.data.slice(last));node.replaceWith(fragment);}
  }
  function restore(values,previousContract=null){
    if(!values||typeof values!=='object')return;
    for(const input of root.querySelectorAll('input,select,textarea')){const key=input.id||input.name;if(!Object.hasOwn(values,key)||previousContract&&JSON.stringify(previousContract[key])!==JSON.stringify(initialContract?.[key]))continue;const value=values[key];if(input.type==='checkbox'||input.type==='radio')input.checked=value===true;else if(typeof value==='string')input.value=value;}
    for(const input of root.querySelectorAll('input,select,textarea')){input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}
  }
  function run(code){if(!code)return;const script=document.createElement('script');script.textContent=code;document.body.append(script);script.remove();}
  nativeAdd.call(window,'message',event=>{
    if(!event.isTrusted||event.source!==parent||event.data?.channel!=='campus-openui')return;
    const data=event.data;
    if(data.type==='init'&&!token){token=data.token;send('ready');return;}
    if(!token)return;
    if(data.type==='result'){const task=pending.get(data.id);if(task){clearTimeout(task.timeout);pending.delete(data.id);data.error?task.reject(Error(data.error)):task.resolve(data.result);}return;}
    if(data.type==='restore'){restore(data.controls);changed();return;}
    if(data.type!=='render')return;
    const ui=data.content;
    if(!ui||typeof ui.css!=='string'||!Array.isArray(ui.html))return;
    if(!data.complete&&!ui.cssComplete)return;
    style.textContent=ui.css;
    const localReady=!!data.complete||!!ui.localReady;
    const previous=started?controls():null;
    const html=data.complete?ui.html.join(''):ui.html.join('').replace(/\[E\d+\]/g,'');
    if(html!==rendered){morph(root,sanitize(html));rendered=html;}
    if(localReady&&!started){
      started=true;enabled=true;approved=!!data.complete;root.inert=false;initial=controls();initialContract=contracts();
      if(approved)citations();
      run(ui.jsFunctions);for(const expression of ui.jsExpressions||[])run(expression);
      restore(data.snapshot?.state?.controls||initial,data.snapshot?.contract||null);lockActions();send('state',{controls:controls(),initial,contract:initialContract});if(!failed)send(approved?'interactive':'local_ready');
    }else if(data.complete&&started&&!approved&&!failed){
      approved=true;for(const [b,disabled]of lockedButtons)b.disabled=disabled;lockedButtons.clear();citations();restore(previous||controls());send('state',{controls:controls(),initial});send('interactive');
    }else if(started&&previous){
      // A citation-number update can morph the HTML after local use. Restore
      // actual inputs and recalculate without restarting authored listeners.
      restore(previous);lockActions();
    }
    measure();
  });
  nativeAdd.call(document,'click',event=>{if(event.isTrusted&&enabled)gestureUntil=now()+1500;const citation=event.target.closest('[data-citation]');if(citation){event.preventDefault();request('citation',{number:Number(citation.dataset.citation)}).catch(e=>reportError(e.message));return;}const link=event.target.closest('a[href]');if(link&&!link.getAttribute('href').startsWith('#')){event.preventDefault();request('openLink',{url:link.href}).catch(e=>reportError(e.message));}},true);
  nativeAdd.call(document,'keydown',event=>{if(event.isTrusted&&enabled&&['Enter',' '].includes(event.key))gestureUntil=now()+1500;},true);
  nativeAdd.call(document,'submit',event=>event.preventDefault(),true);
  nativeAdd.call(document,'input',changed,true);nativeAdd.call(document,'change',changed,true);
  // Native reading gestures do not bubble across the opaque iframe boundary.
  // Relay direction only; this grants no action/click authority to authored UI.
  let readingAt=-Infinity,readingSign=0,touchPoint=null;
  const readingTarget=event=>!event.target.closest?.('input,textarea,select,button,[contenteditable]');
  function reading(delta){const sign=Math.sign(delta);if(!token||!Number.isFinite(delta)||Math.abs(delta)<4||now()-readingAt<32&&sign===readingSign)return;readingAt=now();readingSign=sign;send('reading',{delta:Math.max(-240,Math.min(240,delta))});}
  nativeAdd.call(document,'wheel',event=>{if(event.isTrusted&&readingTarget(event)&&!event.ctrlKey&&!event.shiftKey&&Math.abs(event.deltaY)>Math.abs(event.deltaX))reading(event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?innerHeight:1));},{capture:true,passive:true});
  nativeAdd.call(document,'touchstart',event=>{touchPoint=event.isTrusted&&readingTarget(event)&&event.touches.length===1?{x:event.touches[0].clientX,y:event.touches[0].clientY}:null;},{capture:true,passive:true});
  nativeAdd.call(document,'touchmove',event=>{if(!touchPoint||!event.isTrusted||event.touches.length!==1)return;const point=event.touches[0],dy=touchPoint.y-point.clientY,dx=touchPoint.x-point.clientX;if(Math.abs(dy)>Math.abs(dx)&&Math.abs(dy)>16){reading(dy);touchPoint={x:point.clientX,y:point.clientY};}},{capture:true,passive:true});
  nativeAdd.call(document,'touchend',()=>touchPoint=null,{capture:true,passive:true});
  nativeAdd.call(document,'touchcancel',()=>touchPoint=null,{capture:true,passive:true});
  // Authored validity handlers can update button.disabled after capture
  // listeners. Keep pending host actions locked after those handlers settle.
  new MutationObserver(()=>{if(!approved)lockActions();publishText();}).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled']});
  nativeAdd.call(document,'click',publishText,false);
  nativeAdd.call(window,'error',()=>{failed=true;enabled=false;root.inert=true;reportError('此界面的计算未能完成，可重新生成或查看文字内容。');send('runtime_error');});
  nativeAdd.call(window,'unhandledrejection',event=>{event.preventDefault();reportError(event.reason?.message||'操作未完成，请重试。');});
  new ResizeObserver(measure).observe(root);nativeAdd.call(window,'resize',measure);
  send('boot');
})();
