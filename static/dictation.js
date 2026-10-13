import {toWav} from './audio-wav.js';
let active=null;
export async function dictate(input,button,{api,toast,ask}){
 if(active){active.stop();return;}
 if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){toast('此浏览器无法录音，请使用文字输入。',true);return;}
 const session={cancelled:false,recorder:null,stop(){if(this.recorder?.state==='recording')this.recorder.stop();else this.cancelled=true;}};
 active=session;let stream,timer,controller;
 const cancel=()=>{session.cancelled=true;session.stop();controller?.abort();};
 const reset=()=>{clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());window.removeEventListener('hashchange',cancel);window.removeEventListener('pagehide',cancel);button.classList.remove('listening');button.setAttribute('aria-pressed','false');button.setAttribute('aria-label','语音输入');if(active===session)active=null;};
 window.addEventListener('hashchange',cancel);window.addEventListener('pagehide',cancel);
 try{
  const config=await api('/speech/config');if(!config.configured)throw new Error('请先在服务端填写 MIMO_API_KEY 并重启。');
  if(session.cancelled||!input.isConnected){reset();return;}
  if(!await ask('小米语音输入','录音结束后会发送至小米 MiMo 识别，最多 60 秒。识别结果先填入输入框，由你核对后发送。','同意并开始录音')){reset();return;}
  if(session.cancelled||!input.isConnected){reset();return;}
  stream=await navigator.mediaDevices.getUserMedia({audio:true});
  if(session.cancelled||!input.isConnected){reset();return;}
  const recorder=new MediaRecorder(stream),chunks=[];session.recorder=recorder;
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  recorder.onerror=()=>{session.cancelled=true;reset();toast('录音失败，请重试或输入文字。',true);};
  recorder.onstop=async()=>{
   clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());button.classList.remove('listening');button.setAttribute('aria-pressed','false');
   try{
    if(session.cancelled||!input.isConnected)return;
    toast('录音已结束，正在通过小米识别…');const wav=await toWav(new Blob(chunks,{type:recorder.mimeType}));
    if(session.cancelled||!input.isConnected)return;
    const form=new FormData();form.append('audio',wav,'dictation.wav');form.append('allow_external_processing','true');controller=new AbortController();
    const result=await api('/speech/transcribe',{method:'POST',body:form,signal:controller.signal});
    if(session.cancelled||!input.isConnected)return;
    const text=input.value+(input.value?'\n':'')+result.text,limit=input.maxLength>0?input.maxLength:10000;
    if(text.length>limit){toast('识别文字超过输入框上限，请缩短录音重试；原输入未修改。',true);return;}
    input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));toast('听写已填入，请核对人名、数字和日期后发送。');
   }catch(error){if(!session.cancelled)toast(error.message||'语音识别失败，请重试。',true);}finally{reset();}
  };
  recorder.start();timer=setTimeout(()=>session.stop(),59000);button.classList.add('listening');button.setAttribute('aria-pressed','true');button.setAttribute('aria-label','停止录音并识别');toast('正在录音，再点麦克风结束并识别。');
 }catch(error){reset();toast(error.name==='NotAllowedError'?'未获得麦克风权限，可以继续打字。':error.message,true);}
}
