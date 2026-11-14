/** Observe the reader used by the page, including bundled/lazy-loaded apps.
 * A separately imported module has different private WeakMaps and cannot tell
 * whether the application is still preserving its own reading position. */
export async function waitForReaderStable(page,selector='#chat-thread'){
  await page.locator(selector).waitFor({state:'visible'});
  await page.locator(selector).evaluate(reader=>new Promise((resolve,reject)=>{
    const started=performance.now(),limit=12000,stableWindow=700;
    let last='',unchanged=started,frames=0,frame=0,done=false;
    const finish=error=>{if(done)return;done=true;clearTimeout(deadline);cancelAnimationFrame(frame);error?reject(error):resolve();};
    const deadline=setTimeout(()=>finish(Error('The active reader did not settle within '+limit+' ms: '+last)),limit);
    const sample=()=>{
      if(done)return;
      if(!reader.isConnected){finish(Error('The active reader detached before its layout settled'));return;}
      const now=performance.now(),r=reader.getBoundingClientRect();
      const geometry=[reader.scrollTop,reader.clientWidth,reader.clientHeight,reader.scrollHeight,r.x,r.y,r.width,r.height].map(value=>Math.round(value*100)/100);
      let animating=false;
      for(let node=reader;node;node=node.parentElement){
        if((node.getAnimations?.()||[]).some(animation=>animation.effect?.getTiming().iterations!==Infinity&&(animation.playState==='running'||animation.pending))){animating=true;break;}
      }
      const value=JSON.stringify(geometry);
      if(value!==last||animating){last=value;unchanged=now;frames=0;}else frames++;
      if(frames>=3&&now-unchanged>=stableWindow){finish();return;}
      if(now-started>limit){finish(Error('Reader geometry did not remain stable for '+stableWindow+' ms: '+value+'; animation='+animating));return;}
      frame=requestAnimationFrame(sample);
    };
    frame=requestAnimationFrame(sample);
  }));
}
