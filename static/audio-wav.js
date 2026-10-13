// Local encoding only; all speech recognition is performed by Xiaomi MiMo.
export function encodeWav(channels,sourceRate,targetRate=16000){
 if(!channels.length||!channels[0].length||!Number.isFinite(sourceRate)||sourceRate<8000||sourceRate>192000||targetRate!==16000)throw new Error('录音采样参数无效');
 const size=channels[0].length;if(channels.some(c=>c.length!==size))throw new Error('录音声道长度不一致');
 const count=Math.floor(size*targetRate/sourceRate),buffer=new ArrayBuffer(44+count*2),view=new DataView(buffer);
 const word=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));};
 word(0,'RIFF');view.setUint32(4,36+count*2,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,targetRate,true);view.setUint32(28,targetRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,count*2,true);
 for(let i=0;i<count;i++){const start=Math.floor(i*sourceRate/targetRate),end=Math.min(size,Math.max(start+1,Math.floor((i+1)*sourceRate/targetRate)));let sample=0;for(const channel of channels)for(let k=start;k<end;k++)sample+=channel[k];sample=Math.max(-1,Math.min(1,sample/(channels.length*(end-start))));view.setInt16(44+i*2,Math.round(sample*(sample<0?32768:32767)),true);}
 return new Blob([buffer],{type:'audio/wav'});
}
export async function toWav(blob,maxSeconds=60){
 const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw new Error('此浏览器不支持录音转换，请使用文字输入');
 const context=new Audio();
 try{const audio=await context.decodeAudioData(await blob.arrayBuffer());if(!audio.duration||audio.duration>maxSeconds)throw new Error(`录音不能超过 ${maxSeconds} 秒`);return encodeWav(Array.from({length:audio.numberOfChannels},(_,i)=>audio.getChannelData(i)),audio.sampleRate);}
 finally{await context.close();}
}
