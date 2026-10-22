// PCM capture stays off the UI thread; stopping flushes the last partial block.
class DictationCapture extends AudioWorkletProcessor{
  constructor(){super();this.buffer=new Float32Array(4096);this.offset=0;this.stopped=false;this.port.onmessage=event=>{if(event.data==='stop'){this.flush();this.stopped=true;this.port.postMessage({stopped:true});}};}
  flush(){if(this.offset){const samples=this.buffer.slice(0,this.offset);this.port.postMessage({samples},[samples.buffer]);this.offset=0;}}
  process(inputs){if(this.stopped)return false;const channels=inputs[0];if(!channels?.length)return true;for(let i=0;i<channels[0].length;i++){let sample=0;for(const channel of channels)sample+=channel[i]||0;this.buffer[this.offset++]=sample/channels.length;if(this.offset===this.buffer.length)this.flush();}return true;}
}
registerProcessor('dictation-capture',DictationCapture);
