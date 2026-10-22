import {captureUiContext} from './ui-request.js';
export {speechChunks} from './speech-text.js';
export {createReplySpeech} from './reply-speech.js';

export async function speechDialog({state,api,esc,toast,showDialog}){
 const view=captureUiContext(state);
 const config=await api('/speech/config');if(!view.sameDialog())return;
 showDialog('对话语音播报',`<div class="speech-settings stack"><p>在小信使的每条回复下方，点击「朗读」即可听取这条回答。播放中可暂停、继续或停止，长回复会分段连续播报。</p><p class="small muted">${config.configured?'当前使用小米 MiMo · '+esc(config.models.default):esc(config.unavailable_reason||'当前语音服务尚未配置。')}</p><a class="button primary" href="#chat">前往对话</a></div>`);
 return;
}
