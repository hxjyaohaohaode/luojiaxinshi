import {speechChunks,SPEECH_STYLE} from './speech-text.js';
const svg=path=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
const playIcon=svg('<path d="m9 5 11 7-11 7Z"/>'),pauseIcon=svg('<path d="M8 5v14M16 5v14"/>');
const stamp=n=>Number.isFinite(n)?`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`:'0:00';

export function createReplySpeech({api,toast,owner=()=>''}){
 let active=null,scope=owner(),lifetime=new AbortController(),bytes=0;
 const cache=new Map(),pending=new Map(),MAX_BYTES=40*1024*1024;
 function stop(){
  if(!active)return;const old=active;active=null;old.audio.pause();old.audio.removeAttribute('src');old.audio.load();
  if(old.url)URL.revokeObjectURL(old.url);old.bar.remove();old.control.removeAttribute('data-speaking');old.control.setAttribute('aria-label','朗读这条回复');
 }
 function reset(){stop();lifetime.abort();lifetime=new AbortController();cache.clear();pending.clear();bytes=0;scope=owner();}
 async function obtain(text,messageId,config){
  const account=scope,key=JSON.stringify([account,messageId,config.models?.default,config.voice,SPEECH_STYLE,text]);
  if(cache.has(key)){const blob=cache.get(key);cache.delete(key);cache.set(key,blob);return blob;}
  if(pending.has(key))return pending.get(key);
  const body=new FormData();body.set('text',text);body.set('mode','default');body.set('description',SPEECH_STYLE);body.set('allow_external_processing','true');if(messageId)body.set('message_id',messageId);
  const task=(async()=>{
   const blob=await api('/speech/synthesize',{method:'POST',body,blob:true,signal:lifetime.signal});
   if(account===scope&&account===owner()&&blob.size<=MAX_BYTES){cache.set(key,blob);bytes+=blob.size;while(bytes>MAX_BYTES){const first=cache.keys().next().value;bytes-=cache.get(first).size;cache.delete(first);}}
   return blob;
  })();pending.set(key,task);
  try{return await task;}finally{if(pending.get(key)===task)pending.delete(key);}
 }
 async function toggle(id,text,control){
  if(owner()!==scope)reset();
  if(active?.id===id&&active.text===text){
   if(active.loading)return;
   if(active.completed){active.index=0;active.completed=false;await active.load();}
   else if(active.audio.paused){try{await active.audio.play();}catch{toast('点击播放按钮继续朗读');}}
   else active.audio.pause();return;
  }
  stop();const chunks=speechChunks(text);if(!chunks.length){toast('这条回复没有可播报的文字');return;}
  const bar=document.createElement('div');bar.className='reply-audio';bar.setAttribute('role','group');bar.setAttribute('aria-label','回复朗读');
  const audio=document.createElement('audio');audio.preload='auto';audio.hidden=true;
  const make=(label,icon,action)=>{const b=document.createElement('button');b.type='button';b.className='icon-button';b.setAttribute('aria-label',label);b.innerHTML=icon;b.addEventListener('click',action);return b;};
  const playback=make('暂停朗读',pauseIcon,()=>toggle(id,text,control));
  const seek=document.createElement('input');seek.type='range';seek.min=0;seek.max=100;seek.step=.1;seek.value=0;seek.setAttribute('aria-label','朗读进度');seek.disabled=true;
  const clock=document.createElement('span');clock.className='reply-audio-time';
  const label=document.createElement('span');label.className='sr-only';label.setAttribute('role','status');label.setAttribute('aria-live','polite');
  const part=document.createElement('span');part.className='reply-audio-part';part.hidden=chunks.length<2;
  const cancel=make('关闭播放器',svg('<path d="m6 6 12 12M18 6 6 18"/>'),stop);
  const download=document.createElement('a');download.className='reply-audio-download';download.textContent='下载语音';download.hidden=true;
  bar.append(playback,seek,clock,part,cancel,label,audio,download);control.closest('.message-footer').before(bar);
  const session={id,text,control,audio,bar,index:0,loading:true,url:null,completed:false};active=session;
  const paint=()=>{
   if(active!==session)return;
   control.dataset.speaking=session.loading?'loading':audio.paused?'paused':'playing';
   const status=session.loading?'正在准备语音':session.completed?'朗读完成':audio.paused?'继续朗读':'暂停朗读';
   control.setAttribute('aria-label',status);playback.setAttribute('aria-label',status);playback.disabled=session.loading;
   playback.innerHTML=audio.paused||session.completed?playIcon:pauseIcon;clock.textContent=session.loading?'准备中':`${stamp(audio.currentTime)} / ${stamp(audio.duration)}`;
   part.textContent=`${session.index+1}/${chunks.length}`;seek.disabled=session.loading||!Number.isFinite(audio.duration);label.textContent=status;
  };
  const progress=()=>{if(Number.isFinite(audio.duration)&&audio.duration>0){seek.value=audio.currentTime/audio.duration*100;seek.setAttribute('aria-valuetext',`${stamp(audio.currentTime)}，共 ${stamp(audio.duration)}`);}clock.textContent=`${stamp(audio.currentTime)} / ${stamp(audio.duration)}`;};
  seek.addEventListener('input',()=>{if(Number.isFinite(audio.duration)){audio.currentTime=Number(seek.value)/100*audio.duration;session.completed=false;progress();}});
  for(const event of ['play','pause','loadedmetadata'])audio.addEventListener(event,paint);
  audio.addEventListener('timeupdate',progress);
  audio.addEventListener('error',()=>{if(active!==session||!session.url)return;download.hidden=false;label.textContent='当前浏览器无法播放，可下载语音';});
  let config;
  async function load(){
   if(active!==session)return;session.loading=true;paint();
   try{
    config??=await api('/speech/config');if(active!==session)return;
    const blob=await obtain(chunks[session.index],id,config);if(active!==session||scope!==owner())return;
    if(session.url)URL.revokeObjectURL(session.url);session.url=URL.createObjectURL(blob);audio.src=session.url;seek.value=0;download.href=session.url;download.download=`珞珈信使-回复-${session.index+1}.wav`;download.hidden=true;session.loading=false;
    try{await audio.play();}catch{paint();label.textContent='语音已就绪，点击播放';}
   }catch(error){if(active!==session)return;stop();if(error.name!=='AbortError')toast(error.message,true);}
  }
  session.load=load;
  audio.addEventListener('ended',()=>{if(active!==session)return;if(session.index+1<chunks.length){session.index++;void load();}else{session.completed=true;paint();}});
  await load();
 }
 window.addEventListener('hashchange',()=>{if(owner()!==scope||location.hash==='#login')reset();else stop();});
 return {toggle,stop,reset};
}
