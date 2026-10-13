import test from 'node:test';
import assert from 'node:assert/strict';
import {encodeWav} from '../static/audio-wav.js';
test('PCM WAV is mono, 16 kHz, 16 bit and retains duration across common browser sample rates',async()=>{
 for(const rate of [44100,48000]){
  const channel=new Float32Array(rate).fill(0.5),blob=encodeWav([channel,channel],rate),view=new DataView(await blob.arrayBuffer());
  assert.equal(blob.type,'audio/wav');assert.equal(blob.size,32044);assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint16(34,true),16);assert.equal(view.getUint32(40,true),32000);assert.equal(view.getInt16(44,true),16384);
 }
});
test('negative samples and mixed stereo are bounded',async()=>{
 const a=new Float32Array(160).fill(-2),b=new Float32Array(160).fill(1),view=new DataView(await encodeWav([a,b],16000).arrayBuffer());assert.equal(view.getInt16(44,true),-16384);
 assert.throws(()=>encodeWav([],48000));assert.throws(()=>encodeWav([a,b.subarray(1)],48000));
});
