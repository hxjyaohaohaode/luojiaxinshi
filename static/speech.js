import {captureUiContext} from './ui-request.js';
export async function speechDialog({state,api,esc,toast,showDialog}){
 const view=captureUiContext(state);
 const config=await api('/speech/config');if(!view.sameDialog())return;
 if(!config.configured){toast('请先在服务端填写 MIMO_API_KEY 并重启。',true);return;}
 showDialog('小米语音播报',`<form id="speech-form" class="stack"><label class="field">播报内容<textarea name="text" maxlength="2000" required rows="4" placeholder="粘贴已核对的通知、回答或待办内容"></textarea></label><label class="field">声音模式<select name="mode"><option value="default">普通播报</option><option value="design">设计小信使音色</option><option value="clone">使用已授权的声音</option></select></label><p class="small muted" data-speech-model>${esc(config.models.default)}</p><label class="field" data-description hidden>音色描述<textarea name="description" maxlength="500" rows="2" placeholder="例如：清晰温和的青年声音，普通话，语速适中"></textarea></label><div data-clone hidden><label class="field">参考录音（16 位 PCM WAV，最长 30 秒，5 MB 以内）<input type="file" name="reference" accept=".wav,audio/wav"></label><label><input type="checkbox" name="clone_authorized"> 这是本人声音，或已获声音所有者的复刻授权</label></div><label><input type="checkbox" name="allow_external_processing" required> 同意将本次文字及所选参考录音发送至小米 MiMo</label><p class="small muted">输出为 AI 合成语音。音色设计仅改变声音，播报正文保持提交内容；日期、姓名请以已核对文字为准。</p><button class="button primary" type="submit">生成语音</button><div data-speech-result aria-live="polite"></div></form>`);
 const form=document.querySelector('#speech-form'),dialog=document.querySelector('#dialog');let url=null,busy=false,controller=null;
 const release=()=>{if(url){URL.revokeObjectURL(url);url=null;}};
 const current=()=>form.isConnected&&dialog.open;
 const modeChanged=()=>{const mode=form.elements.mode.value;form.querySelector('[data-description]').hidden=mode!=='design';form.querySelector('[data-clone]').hidden=mode!=='clone';form.elements.description.required=mode==='design';form.elements.reference.required=mode==='clone';form.elements.clone_authorized.required=mode==='clone';form.querySelector('[data-speech-model]').textContent=config.models[mode];};
 form.elements.mode.addEventListener('change',modeChanged);modeChanged();
 dialog.addEventListener('close',()=>{controller?.abort();release();},{once:true});
 form.addEventListener('submit',async event=>{
  event.preventDefault();event.stopPropagation();if(busy||!form.reportValidity())return;
  const body=new FormData();const mode=form.elements.mode.value;
  body.set('text',form.elements.text.value);body.set('mode',mode);body.set('allow_external_processing','true');
  if(mode==='design')body.set('description',form.elements.description.value);
  if(mode==='clone'){const file=form.elements.reference.files[0];if(!file||file.size>5*1024*1024){toast('请选择不超过 5 MB 的 WAV 参考录音。',true);return;}body.set('reference',file);body.set('clone_authorized',String(form.elements.clone_authorized.checked));}
  busy=true;const submit=form.querySelector('[type=submit]'),result=form.querySelector('[data-speech-result]');submit.disabled=true;result.textContent='正在生成语音…';controller=new AbortController();
  try{const blob=await api('/speech/synthesize',{method:'POST',body,blob:true,signal:controller.signal});if(!current())return;release();url=URL.createObjectURL(blob);const player=document.createElement('audio');player.controls=true;player.src=url;player.setAttribute('aria-label','AI 合成语音');result.replaceChildren(player);}
  catch(error){if(current()){result.textContent=error.message;toast(error.message,true);}}
  finally{busy=false;if(current())submit.disabled=false;}
 });
}
