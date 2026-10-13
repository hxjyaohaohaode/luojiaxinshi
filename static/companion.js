const preferenceKey='campus.companion.enabled';
let enabled=true,tipTimer,activeButton,lastTap=0,taps=0,lastBloom=0,tipIndex=0;
try{enabled=localStorage.getItem(preferenceKey)!=='false';}catch{/* Private mode still works. */}
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;

export function greeting(now=new Date()){
  const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hour12:false}).format(now));
  return hour<6?'夜深了':hour<12?'早上好':hour<18?'下午好':'晚上好';
}

export function companion(pose='welcome',className=''){
  if(pose==='welcome'&&greeting()==='夜深了')pose='rest';
  return `<button type="button" class="companion ${className}" data-companion aria-label="和珞珈小信使打个招呼" aria-expanded="false" aria-controls="companion-bubble" ${enabled?'':'disabled'}><img src="/static/assets/luojia-messenger-${pose}.png" width="1280" height="1280" alt="珞珈小信使" decoding="async" ${pose==='reading'?'loading="lazy"':''}></button>`;
}

export function companionSetting(){
  return `<section class="panel stack"><h2>使用偏好</h2><label class="check"><input type="checkbox" id="companion-enabled" ${enabled?'checked':''}><span>保留小信使的轻声问候与小动作</span></label><p class="small muted">想安静专注时，随时关闭。此偏好仅保存在当前浏览器，必要的保存和错误提示始终保留。</p></section>`;
}

function closeTip(){
  clearTimeout(tipTimer);
  const bubble=document.querySelector('#companion-bubble');if(bubble)bubble.hidden=true;
  activeButton?.setAttribute('aria-expanded','false');activeButton=null;
}

function showTip(anchor,message){
  if(!enabled)return;
  let bubble=document.querySelector('#companion-bubble');
  if(!bubble){bubble=document.createElement('div');bubble.id='companion-bubble';bubble.className='companion-bubble';bubble.setAttribute('role','status');bubble.setAttribute('aria-live','polite');document.body.append(bubble);}
  closeTip();activeButton=anchor;anchor?.setAttribute('aria-expanded','true');
  bubble.textContent=message;bubble.hidden=false;
  const bounds=anchor?.getBoundingClientRect()||{left:innerWidth/2-60,right:innerWidth/2+60,top:100,bottom:150,width:120};
  const width=Math.min(278,innerWidth-32);
  bubble.style.width=width+'px';
  bubble.style.left=Math.max(16,Math.min(innerWidth-width-16,bounds.left+bounds.width/2-width/2))+'px';
  const height=bubble.getBoundingClientRect().height;
  bubble.style.top=Math.max(12,Math.min(innerHeight-height-16,bounds.bottom+12+height<innerHeight?bounds.bottom+12:bounds.top-height-12))+'px';
  tipTimer=setTimeout(closeTip,6500);
}

function bloom(anchor){
  const now=Date.now();
  if(!enabled||reduced()||now-lastBloom<12000)return;
  lastBloom=now;
  const rect=anchor?.getBoundingClientRect()||{left:innerWidth/2-30,top:innerHeight-105,width:60,height:30};
  for(let i=0;i<7;i++){
    const petal=document.createElement('i');petal.className='companion-petal';petal.setAttribute('aria-hidden','true');
    petal.style.left=Math.max(10,Math.min(innerWidth-10,rect.left+rect.width/2))+'px';
    petal.style.top=Math.max(10,Math.min(innerHeight-30,rect.top+rect.height*.4))+'px';
    document.body.append(petal);
    const animation=petal.animate([
      {transform:'translate(0,0) rotate(0deg)',opacity:0},
      {opacity:.95,offset:.15},
      {transform:`translate(${(i-3)*23}px,${50+(i%3)*20}px) rotate(${i*63+120}deg)`,opacity:0}
    ],{duration:1250+i*85,easing:'ease-out'});
    animation.finished.catch(()=>{}).finally(()=>petal.remove());
  }
}

export function celebrateCompletion(){
  if(!enabled||document.querySelector('#dialog')?.open)return;
  bloom(document.querySelector('.hero-companion')||document.querySelector('#toast'));
}

function contextualTip(){
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).format(new Date());
  if(today.endsWith('11-29'))return '今天是珞珈的生日。愿每一次认真出发，都有新的收获。';
  if(greeting()==='夜深了')return '晚啦。忙完眼前这一步，也记得给自己留一点休息时间。';
  const page=document.querySelector('#content')?.dataset.page||'welcome';
  if(page.startsWith('chat')){
    const count=document.querySelectorAll('.material-item').length;
    const tips=count?['材料已经收在旁边啦。忘记是哪一句，点开原文就能找回来。','只差一个条件也没关系，直接在对话里补充就好。','先问清楚，再决定做什么。你的下一步，始终由你确认。']:['截图和附件都可以带过来，我们把散落的信息放在一起。','不知道从哪里问起？先写一句“我需要做什么”也可以。'];
    return tips[tipIndex++%tips.length];
  }
  if(page==='sources')return '同名的群，也可能是不同学期。写上用途，以后就不会认错啦。';
  if(page.startsWith('notice/'))return '不确定的日期可以先留空，核实后再补上。每一步，都有原文可循。';
  const tips={
    new:['先把完整原文留下来，不必一次填得完美。','附件里也可能藏着关键要求，记得一起看看。'],
    tasks:['先理清下一步，再按自己的节奏完成。','误点了完成？刚出现的提示里可以撤回，也能在已完成中恢复。'],
    calendar:['行程之间，记得留一点走到下一间教室的时间。','空下来的一小会儿，也可以留给珞珈山的风。'],
    settings:['按目前的实际情况填写身份条件，以后随时可以更新。'],
    dashboard:['通知再长，也可以从清楚的一步开始。','认真核对的一小步，也是在照顾未来的自己。','有些事暂时没有答案，先记下待核实，也很好。'],
    welcome:['你好，我是珞珈小信使。把通知理清，我们从第一步开始。']
  };
  const options=tips[page]||tips.dashboard;return options[tipIndex++%options.length];
}

export function initializeCompanion(){
  let milestoneCount=0;
  document.addEventListener('campus:milestone',event=>{
    if(!enabled||document.querySelector('#dialog')?.open)return;
    milestoneCount++;
    const anchor=[...document.querySelectorAll('[data-companion]')].find(b=>b.getBoundingClientRect().width>0&&b.getBoundingClientRect().top>=0&&b.getBoundingClientRect().bottom<innerHeight);
    if(!anchor)return;
    if(event.detail==='arrangement-saved'&&milestoneCount===1)showTip(anchor,'时间记好啦。路上从容一点，也给课间留一点喘息。');
    if(event.detail==='materials-saved'&&milestoneCount===1)showTip(anchor,'收到啦。原文替你收好了，下次不用再从群消息里翻找。');
    if(event.detail==='notice-confirmed'&&milestoneCount%3===0){bloom(anchor);showTip(anchor,'又把一件模糊的事理清楚了。帽檐上的这朵小花，送给你。');}
  });
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-companion]');
    if(!target){if(!event.target.closest('#companion-bubble'))closeTip();return;}
    if(!enabled)return;
    const now=Date.now();taps=now-lastTap<1100?taps+1:1;lastTap=now;
    if(!reduced())target.animate([{transform:'rotate(0deg)'},{transform:'rotate(-5deg)',offset:.3},{transform:'rotate(4deg)',offset:.65},{transform:'rotate(0deg)'}],{duration:450,easing:'ease-out'});
    if(taps>=3){taps=0;const picture=target.querySelector('img'),original=picture?.getAttribute('src');if(picture){picture.src='/static/assets/luojia-messenger-blossom.png';setTimeout(()=>{if(picture.isConnected)picture.src=original;},6500);}bloom(target);showTip(target,'欸，帽檐上落了一朵樱花。送给认真生活的你。');}
    else showTip(target,contextualTip());
  });
  document.addEventListener('change',event=>{
    if(event.target.id!=='companion-enabled')return;
    enabled=event.target.checked;
    try{localStorage.setItem(preferenceKey,String(enabled));}catch{/* Keep this page's preference. */}
    document.querySelectorAll('[data-companion]').forEach(button=>button.disabled=!enabled);
    if(!enabled){closeTip();document.querySelectorAll('.companion-petal').forEach(node=>node.remove());}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeTip();});
  window.addEventListener('hashchange',closeTip);
  window.addEventListener('resize',closeTip);
  window.addEventListener('scroll',closeTip,{passive:true});
}
