import {captureUiContext} from './ui-request.js';
export function speechChunks(markdown,limit=1800){
 const text=String(markdown||'').replace(/```[\s\S]*?```/g,'').replace(/!\[[^\]]*\]\([^)]*\)/g,'').replace(/\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/\[(?:E)?\d+\]/g,'').replace(/(^|\n)\s{0,3}#{1,6}\s+/g,'$1').replace(/[*_`>|]/g,'').trim();
 const chunks=[];let rest=text;
 while(rest.length>limit){let cut=Math.max(rest.lastIndexOf('。',limit),rest.lastIndexOf('！',limit),rest.lastIndexOf('？',limit),rest.lastIndexOf('\n',limit));if(cut<limit/2)cut=limit-1;if(/[\uD800-\uDBFF]/.test(rest[cut]))cut--;chunks.push(rest.slice(0,cut+1));rest=rest.slice(cut+1).trim();}
 if(rest)chunks.push(rest);return chunks;
}

export function createReplySpeech({api,toast}){
 let active=null,sequence=0;
 function stop(){
  sequence++;if(!active)return;active.controller?.abort();active.audio?.pause();if(active.url)URL.revokeObjectURL(active.url);active.bar?.remove();active.control.removeAttribute('data-speaking');active.control.setAttribute('aria-label','朗读这条回复');active.control.disabled=false;active=null;
 }
 async function toggle(id,text,control){
  if(active?.id===id){
   active.control=control;
   if(active.loading){stop();return;}
   if(active.audio.paused){try{await active.audio.play();}catch{toast('点击播放器继续播放。');}}else active.audio.pause();
   return;
  }
  stop();const ticket=sequence;
  const chunks=speechChunks(text);if(!chunks.length){toast('这条回复没有可播报的文字');return;}
  const bar=document.createElement('div');bar.className='reply-audio';const label=document.createElement('span');label.setAttribute('role','status');const audio=document.createElement('audio');audio.controls=true;audio.setAttribute('aria-label','回复语音');const cancel=document.createElement('button');cancel.type='button';cancel.className='icon-button';cancel.setAttribute('aria-label','停止朗读');cancel.textContent='×';cancel.addEventListener('click',stop);bar.append(label,audio,cancel);control.closest('.message-footer').before(bar);
  const download=document.createElement('a');download.className='reply-audio-download';download.textContent='下载本段语音';download.hidden=true;bar.append(download);
  const session={id,control,bar,audio,label,index:0,chunks,loading:true,playbackError:false,controller:new AbortController(),url:null};active=session;
  const paint=()=>{
   if(active!==session)return;
   const status=session.playbackError?'当前浏览器无法播放，可下载本段语音':session.loading?'正在生成语音':audio.paused?'已暂停':'正在朗读';
   session.control.dataset.speaking=session.playbackError?'error':session.loading?'loading':audio.paused?'paused':'playing';
   session.control.setAttribute('aria-label',session.playbackError?'重试语音播放':session.loading?'取消语音生成':audio.paused?'继续朗读':'暂停朗读');
   label.textContent=`${status}${chunks.length>1?' · '+(session.index+1)+' / '+chunks.length:''}`;
  };
  audio.addEventListener('play',paint);audio.addEventListener('pause',paint);
  audio.addEventListener('error',()=>{if(active===session){session.playbackError=true;download.hidden=false;paint();}});
  async function next(){
   if(active!==session||ticket!==sequence)return;
   session.loading=true;paint();const body=new FormData();body.set('text',chunks[session.index]);body.set('mode','default');body.set('allow_external_processing','true');
   try{
    const blob=await api('/speech/synthesize',{method:'POST',body,blob:true,signal:session.controller.signal});
    if(active!==session||ticket!==sequence)return;
    if(session.url)URL.revokeObjectURL(session.url);session.url=URL.createObjectURL(blob);audio.src=session.url;download.href=session.url;download.download=`珞珈信使-回复-${session.index+1}.wav`;session.loading=false;session.playbackError=false;download.hidden=true;
    try{await audio.play();}catch{paint();if(!session.playbackError)label.textContent='语音已就绪，点击播放';}
   }catch(error){if(active!==session)return;stop();if(error.name!=='AbortError')toast(error.message,true);}
  }
  audio.addEventListener('ended',()=>{if(active!==session)return;if(++session.index<chunks.length)void next();else{session.index=chunks.length-1;session.control.dataset.speaking='paused';session.control.setAttribute('aria-label','重新播放最后一段');label.textContent='朗读完成';}});
  control.disabled=false;await next();
 }
 window.addEventListener('hashchange',stop);
 return {toggle,stop};
}

export async function speechDialog({state,api,esc,toast,showDialog}){
 const view=captureUiContext(state);
 const config=await api('/speech/config');if(!view.sameDialog())return;
 showDialog('对话语音播报',`<div class="speech-settings stack"><p>在小信使的每条回复下方，点击「朗读」即可听取这条回答。播放中可暂停、继续或停止，长回复会分段连续播报。</p><p class="small muted">${config.configured?'当前使用小米 MiMo · '+esc(config.models.default):esc(config.unavailable_reason||'当前语音服务尚未配置。')}</p><a class="button primary" href="#chat">前往对话</a></div>`);
 return;
}
