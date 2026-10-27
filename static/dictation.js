import {encodeWav} from './audio-wav.js';
import {SpeechSegments,appendTranscript} from './dictation-segments.js';
let active=null;
export const isDictating=input=>!!active&&(!input||active.input===input);
export async function finishDictation(input){if(active?.input===input)await active.finish();}
export async function dictate(input,button,{api,toast}){
  if(active){if(active.input===input)await (active.action?.()??active.finish());else active.cancel();return;}
  if(!navigator.mediaDevices?.getUserMedia||!(window.AudioContext||window.webkitAudioContext)){toast('此浏览器不支持录音，请使用文字输入。',true);return;}
  const session={input,cancelled:false,stopping:false};active=session;
  let stream,context,capture,source,gain,timer,frame,panel,controller,segments,queue=[],working=null,failure=null,stopAck,stopTimer;
  const levels=[];let recordingAt=performance.now();
  const original={parent:button.parentNode,next:button.nextSibling,html:button.innerHTML};
  const control=(label,retry=false)=>{button.setAttribute('aria-label',label);button.title=label;button.innerHTML=retry?'↻':'<span class="stop-square" aria-hidden="true"></span>';};
  const state=text=>{if(panel)panel.querySelector('.dictation-status').textContent=text;};
  const cleanup=()=>{
    clearTimeout(timer);clearTimeout(stopTimer);cancelAnimationFrame(frame);stream?.getTracks().forEach(track=>track.stop());source?.disconnect();capture?.disconnect();gain?.disconnect();context?.close().catch(()=>{});
    window.removeEventListener('hashchange',session.cancel);window.removeEventListener('pagehide',session.cancel);window.removeEventListener('keydown',escape);
    if(original.parent.isConnected)original.parent.insertBefore(button,original.next?.parentNode===original.parent?original.next:null);
    panel?.remove();button.innerHTML=original.html;button.title='语音输入';button.disabled=false;
    button.classList.remove('listening');button.setAttribute('aria-pressed','false');button.setAttribute('aria-label','语音输入');if(active===session)active=null;
  };
  session.cancel=()=>{session.cancelled=true;queue=[];controller?.abort();stopAck?.();cleanup();};
  const escape=event=>{if(event.key==='Escape'){event.preventDefault();session.cancel();}};
  window.addEventListener('keydown',escape);
  window.addEventListener('hashchange',session.cancel);window.addEventListener('pagehide',session.cancel);
  const process=()=>{
    if(working||failure||session.cancelled||!queue.length)return working;
    working=(async()=>{
      while(queue.length&&!session.cancelled){
        const samples=queue[0];controller=new AbortController();state(session.stopping?'转写中':'边说边转写');
        const form=new FormData();form.append('audio',encodeWav([samples],context.sampleRate),'dictation.wav');form.append('allow_external_processing','true');
        try{const result=await api('/speech/transcribe',{method:'POST',body:form,signal:controller.signal});if(session.cancelled||!input.isConnected)return;if(result.text?.trim())appendTranscript(input,result.text);queue.shift();}
        catch(error){if(!session.cancelled){failure=error;session.lastFailure=error;control('重试转写（Esc 取消剩余录音）',true);state('转写未完成');panel.title=error.message;void session.finish().catch(()=>{});toast(error.message||'这段听写未完成，点击录音按钮重试，或按 Esc 保留已有文字并取消剩余录音。',true);}break;}
      }
    })().finally(()=>{working=null;if(!session.stopping&&!failure)state('正在聆听');});return working;
  };
  session.finish=async()=>{
    if(session.cancelled)return;
    if(!capture){session.cancel();return;}
    if(!session.stopping){session.stopping=true;clearTimeout(timer);button.classList.remove('listening');button.setAttribute('aria-pressed','false');if(!failure)state('转写中');session.stopped=new Promise(resolve=>{stopAck=resolve;stopTimer=setTimeout(resolve,1000);capture.port.postMessage('stop');});}
    await session.stopped;clearTimeout(stopTimer);stream?.getTracks().forEach(track=>track.stop());segments.flush();
    if(working)await working;if(!failure)await process();
    if(session.cancelled)return;
    if(failure)throw Error('有一段听写未完成，点击录音按钮重试，或按 Esc 保留已有文字并取消剩余录音。');
    cleanup();input.focus({preventScroll:true});
  };
  session.action=async()=>{if(failure){failure=null;session.lastFailure=null;control('正在转写');button.disabled=true;try{await process();if(!failure&&session.stopping)await session.finish();}finally{button.disabled=false;}}else await session.finish();};
  try{
    const config=await api('/speech/config');if(!config.configured)throw Error(config.unavailable_reason||'语音服务尚未配置。');
    if(session.cancelled||!input.isConnected){cleanup();return;}
    // Clicking the microphone starts dictation. Browser microphone permission
    // remains authoritative; do not repeat an application confirmation per use.
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(session.cancelled||!input.isConnected){cleanup();return;}
    context=new (window.AudioContext||window.webkitAudioContext)();
    if(!context.audioWorklet)throw Error('此浏览器不支持实时录音，请使用新版 Chrome、Edge 或 Safari。');
    await context.audioWorklet.addModule('/static/dictation-capture.js');
    if(session.cancelled||!input.isConnected){cleanup();return;}
    panel=document.createElement('div');panel.className='dictation-panel';panel.setAttribute('role','group');panel.setAttribute('aria-label','语音输入');
    panel.innerHTML='<span class="dictation-time">0:00</span><canvas aria-label="麦克风实时音量"></canvas><span class="dictation-status" role="status">正在聆听</span>';
    (input.closest('#chat-composer')||input.parentElement).append(panel);panel.append(button);control('结束录音');
    segments=new SpeechSegments(context.sampleRate,samples=>{queue.push(samples);process();if(queue.length>=4&&!session.stopping)session.finish().catch(()=>{});});
    capture=new AudioWorkletNode(context,'dictation-capture');source=context.createMediaStreamSource(stream);gain=context.createGain();gain.gain.value=0;source.connect(capture).connect(gain).connect(context.destination);
    capture.port.onmessage=event=>{if(session.cancelled)return;if(event.data.samples){const rms=segments.push(event.data.samples);levels.push(Math.min(1,rms*6));if(levels.length>120)levels.shift();}if(event.data.stopped)stopAck?.();};
    await context.resume();recordingAt=performance.now();
    const canvas=panel.querySelector('canvas'),paint=()=>{
      if(session.cancelled||!panel.isConnected)return;const rect=canvas.getBoundingClientRect(),scale=devicePixelRatio||1,width=Math.max(1,Math.round(rect.width*scale)),height=Math.round(32*scale);if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
      const ctx=canvas.getContext('2d');ctx.clearRect(0,0,width,height);ctx.fillStyle='#5a7e69';const count=Math.floor(width/(6*scale)),values=levels.slice(-count);
      for(let i=0;i<count;i++){const h=Math.max(2,Math.round((values[i-count+values.length]||0)*height));ctx.beginPath();ctx.roundRect(i*6*scale,(height-h)/2,3*scale,h,1.5*scale);ctx.fill();}
      if(!session.stopping){const seconds=Math.floor((performance.now()-recordingAt)/1000);panel.querySelector('.dictation-time').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;frame=requestAnimationFrame(paint);}
    };paint();timer=setTimeout(()=>session.finish().catch(error=>toast(error.message,true)),Math.min(60,config.max_recording_seconds||60)*1000);
    button.classList.add('listening');button.setAttribute('aria-pressed','true');button.setAttribute('aria-label','结束录音');
  }catch(error){cleanup();if(!session.cancelled)toast(error.name==='NotAllowedError'?'未获得麦克风权限，可以继续打字。':error.message,true);}
}
