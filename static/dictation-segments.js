// Non-overlapping chunks end on silence or at six seconds. Silence is not billed.
export class SpeechSegments{
  constructor(rate,onSegment){this.rate=rate;this.onSegment=onSegment;this.parts=[];this.frames=0;this.voiced=0;this.silence=0;}
  push(samples){let energy=0;for(const sample of samples)energy+=sample*sample;const rms=Math.sqrt(energy/samples.length);this.parts.push(samples);this.frames+=samples.length;if(rms>.008){this.voiced+=samples.length;this.silence=0;}else this.silence+=samples.length;if(this.frames/this.rate>=6||(this.frames/this.rate>=1.5&&this.silence/this.rate>=.55))this.flush();return rms;}
  flush(){const parts=this.parts,frames=this.frames,voiced=this.voiced;this.parts=[];this.frames=this.voiced=this.silence=0;if(voiced/this.rate>=.12){const samples=new Float32Array(frames);let offset=0;for(const part of parts){samples.set(part,offset);offset+=part.length;}this.onSegment(samples);}}
}
export function appendTranscript(input,text){
  const next=input.value+(input.value&&!/\s$/.test(input.value)?'\n':'')+text.trim();
  if(next.length>(input.maxLength>0?input.maxLength:10000))throw Error('听写文字超过输入上限，原有文字保留。');
  const atEnd=input.selectionStart===input.value.length&&input.selectionEnd===input.value.length,selection=[input.selectionStart,input.selectionEnd];input.value=next;if(atEnd)input.setSelectionRange(next.length,next.length);else input.setSelectionRange(...selection);input.dispatchEvent(new Event('input',{bubbles:true}));
}
