// Native, shared adaptations of the handbook's motion and feedback primitives.
// Business state stays in each feature; this module only presents that state.
export const motionAllowed = () => !document.hidden &&
  document.documentElement.dataset.uiMotion !== 'off' &&
  !matchMedia('(prefers-reduced-motion: reduce)').matches;
const easing = 'cubic-bezier(.22,.8,.24,1)';
const running = new Set();

export function animateSurface(node, direction = 1, delay = 0) {
  if (!node || !motionAllowed() || !node.animate) return;
  const animation = node.animate([
    {opacity: .25, transform: `translate3d(${direction * 10}px,6px,0)`},
    {opacity: 1, transform: 'translate3d(0,0,0)'},
  ], {duration: 320, delay, easing});
  running.add(animation);
  animation.finished.catch(() => {}).finally(() => running.delete(animation));
  return animation;
}

export function numberMarkup(value) {
  const number = Number(value), n = Number.isFinite(number) ? Math.max(0, Math.trunc(number)) : 0;
  return `<span class="number-ticker" data-number="${n}"><span class="sr-only">${n}</span><span aria-hidden="true" class="number-face">${n}</span></span>`;
}

export function ringMarkup(value, total, label) {
  const max = Number.isFinite(Number(total)) ? Math.max(0, Number(total)) : 0;
  const current = Number.isFinite(Number(value)) ? Math.min(max, Math.max(0, Number(value))) : 0;
  const percent = max ? Math.round(current / max * 100) : 0;
  // The label is supplied by our own fixed component copy, never user input.
  return `<div class="progress-ring" role="img" aria-label="${label}：${current} / ${max}" data-ring="${percent}">
    <svg viewBox="0 0 100 100" aria-hidden="true"><circle class="ring-track" cx="50" cy="50" r="42"/><circle class="ring-value" cx="50" cy="50" r="42" pathLength="100"/></svg>
    <span class="ring-caption" aria-hidden="true"><b>${percent}<small>%</small></b><span>${max ? '已完成' : '待开始'}</span></span>
  </div>`;
}

export function initializeExperience() {
  const watched = new WeakSet(), continuous = new Set(), inView = new Set(), pendingEntrance = new Set();
  let frame = 0, pointer = null, hovered = null;
  const fine = matchMedia('(hover:hover) and (pointer:fine)');
  const reduced = matchMedia('(prefers-reduced-motion:reduce)');
  const readers = new Map();
  const readingResize = new ResizeObserver(entries => {for(const entry of entries) updateReading(entry.target);});
  function updateReading(scroller) {
    const pane = scroller.matches('.source-pane') ? scroller : scroller.closest('.source-pane');
    const meter = readers.get(pane);if (!meter) return;
    const distance = scroller.scrollHeight - scroller.clientHeight;
    meter.hidden = distance < 2;
    const percent = distance > 0 ? Math.max(0,Math.min(100,scroller.scrollTop / distance * 100)) : 0;
    meter.querySelector('i').style.transform = `scaleX(${percent / 100})`;
    meter.querySelector('span').textContent = `原文阅读位置 ${Math.round(percent)}%`;
  }
  const revealSelector = '[data-reveal],.action-metric,.scene-choice,.notice-card,.task-board-column,.selected-file,.settings-group,.source-card,.memory-card';
  const ornamentSelector = '[data-orbit],.processing-steps,.chat-composer';
  const entrance = new IntersectionObserver(entries => {
    let index = 0;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const node = entry.target;
      entrance.unobserve(node);
      pendingEntrance.delete(node);
      if (node.matches('.number-ticker')) rollNumber(node);
      else if (node.matches('.progress-ring')) drawRing(node);
      else animateSurface(node, 0, Math.min(index++ * 35, 140));
    }
  }, {threshold: .08});
  const visibility = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) inView.add(entry.target); else inView.delete(entry.target);
    }
    pauseDecorations();
  }, {threshold: .1});

  function drawRing(node) {
    const value = Math.max(0, Math.min(100, Number(node.dataset.ring) || 0));
    const circle = node.querySelector('.ring-value');
    circle.style.strokeDasharray = `${value} 100`;
    if (motionAllowed()) {
      const animation = circle.animate([{strokeDasharray: '0 100'}, {strokeDasharray: `${value} 100`}], {duration: 800, easing});
      running.add(animation); animation.finished.catch(() => {}).finally(() => running.delete(animation));
    }
  }
  function rollNumber(node) {
    if (!motionAllowed()) return;
    const face = node.querySelector('.number-face'), value = node.dataset.number;
    face.replaceChildren(...[...value].map((digit, i) => {
      const slot = document.createElement('span'); slot.className = 'number-slot';
      const column = document.createElement('span'); column.className = 'number-column';
      for (let n = 0; n <= Number(digit); n++) {
        const item = document.createElement('span'); item.textContent = String(n); column.append(item);
      }
      slot.append(column);
      const to = `translateY(-${Number(digit)}em)`;
      column.style.transform = to;
      const animation = column.animate([{transform: 'translateY(0)'}, {transform: to}], {duration: 650 + i * 65, easing});
      running.add(animation); animation.finished.catch(() => {}).finally(() => running.delete(animation));
      return slot;
    }));
  }
  function watch(root) {
    if (!(root instanceof Element)) return;
    for(const pane of [...(root.matches('.source-pane')?[root]:[]),...root.querySelectorAll('.source-pane')]){
      if(readers.has(pane))continue;
      const meter=document.createElement('div');meter.className='source-reading-progress';meter.setAttribute('aria-hidden','true');
      meter.innerHTML='<span>原文阅读位置</span><b><i></i></b>';pane.prepend(meter);readers.set(pane,meter);
      readingResize.observe(pane);updateReading(pane);
    }
    const selector = `${revealSelector},.number-ticker,.progress-ring,${ornamentSelector}`;
    const nodes = [...(root.matches(selector) ? [root] : []), ...root.querySelectorAll(selector)];
    for (const node of nodes) {
      if (watched.has(node)) continue;
      watched.add(node);
      if (node.matches(ornamentSelector)) {continuous.add(node); visibility.observe(node);}
      else {pendingEntrance.add(node); entrance.observe(node);}
    }
  }
  function pauseDecorations() {
    const foreground = document.querySelector('dialog[open]');
    for (const node of pendingEntrance) if (!node.isConnected) {entrance.unobserve(node);pendingEntrance.delete(node);}
    for (const [pane] of readers) if (!pane.isConnected) {readingResize.unobserve(pane);readers.delete(pane);}
    for (const node of continuous) {
      if (!node.isConnected) {visibility.unobserve(node); continuous.delete(node); inView.delete(node); continue;}
      node.classList.toggle('fx-paused', !motionAllowed() || !inView.has(node) || !!(foreground && !foreground.contains(node)));
    }
  }
  function resetPointer() {
    if (hovered) {
      hovered.classList.remove('pointer-active');
      hovered.style.removeProperty('--tilt-x'); hovered.style.removeProperty('--tilt-y');
    }
    hovered = null;
  }
  function synchronize() {
    if (!motionAllowed()) {
      for (const animation of running) animation.cancel();
      running.clear(); resetPointer();
    }
    pauseDecorations();
  }
  document.addEventListener('pointermove', event => {
    if (!fine.matches || !motionAllowed()) return;
    const node = event.target.closest('[data-spotlight],.action-metric,.scene-choice,.notice-card,.notice-upload');
    if (hovered !== node) {resetPointer(); hovered = node;}
    if (!node) return;
    pointer = {node, x: event.clientX, y: event.clientY};
    if (!frame) frame = requestAnimationFrame(() => {
      frame = 0;
      const {node, x, y} = pointer;
      if (node !== hovered || !node.isConnected) return;
      const rect = node.getBoundingClientRect();
      node.style.setProperty('--spot-x', `${x - rect.left}px`);
      node.style.setProperty('--spot-y', `${y - rect.top}px`);
      if (node.hasAttribute('data-tilt')) {
        node.style.setProperty('--tilt-x', `${-(y - rect.top - rect.height / 2) / rect.height * 4}deg`);
        node.style.setProperty('--tilt-y', `${(x - rect.left - rect.width / 2) / rect.width * 4}deg`);
      }
      node.classList.add('pointer-active');
    });
  }, {passive: true});
  document.addEventListener('pointerout', event => {
    if (hovered && (!event.relatedTarget || !hovered.contains(event.relatedTarget))) resetPointer();
  }, {passive: true});
  document.addEventListener('scroll',event=>{
    if(event.target instanceof Element && event.target.matches('.source-pane,.source-content'))updateReading(event.target);
  },{passive:true,capture:true});
  document.addEventListener('click', event => {
    const button = event.target.closest('.button.primary,.sidebar-create,.send-button');
    if (!button || button.disabled || !motionAllowed()) return;
    const rect = button.getBoundingClientRect(), size = Math.hypot(rect.width, rect.height) * 2;
    const ripple = document.createElement('span');
    ripple.className = 'press-ripple'; ripple.setAttribute('aria-hidden', 'true');
    Object.assign(ripple.style, {
      width: `${size}px`, height: `${size}px`,
      left: `${(event.detail ? event.clientX - rect.left : rect.width / 2) - size / 2}px`,
      top: `${(event.detail ? event.clientY - rect.top : rect.height / 2) - size / 2}px`,
    });
    button.append(ripple);
    const animation = ripple.animate([{transform: 'scale(0)', opacity: .22}, {transform: 'scale(1)', opacity: 0}], {duration: 520, easing});
    running.add(animation);
    animation.finished.catch(() => {}).finally(() => {ripple.remove(); running.delete(animation);});
  }, true);
  // Native details retain native keyboard behavior; only their revealed contents animate.
  document.addEventListener('toggle', event => {
    if (event.target instanceof HTMLDetailsElement && event.target.open) {
      [...event.target.children].filter(node => node.tagName !== 'SUMMARY').slice(0, 6).forEach(node => animateSurface(node, 0));
    }
  }, true);
  document.addEventListener('click', event => {
    const tab = event.target.closest('[role=tab]');
    if (!tab) return;
    const group = tab.closest('[role=tablist]'), tabs = [...group.querySelectorAll('[role=tab]')];
    const direction = tabs.indexOf(tab) >= Number(group.dataset.previousIndex || 0) ? 1 : -1;
    group.dataset.previousIndex = String(tabs.indexOf(tab));
    requestAnimationFrame(() => {
      const id = tab.getAttribute('aria-controls');
      const panel = (id && document.getElementById(id)) ||
        document.querySelector('#task-results,#library-results,#calendar-body');
      animateSurface(panel, direction);
    });
  }, true);
  const dialog = document.querySelector('#dialog');
  const dialogChanges = new MutationObserver(() => {
    pauseDecorations();
    if (dialog.open) animateSurface(dialog.querySelector('.dialog-body'), 0);
  });
  dialogChanges.observe(dialog, {attributes: true, attributeFilter: ['open']});
  const mutations = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) watch(node);
    // Release detached nodes, even if no new ornament was added.
    pauseDecorations();
  });
  mutations.observe(document.body, {childList: true, subtree: true});
  new MutationObserver(synchronize).observe(document.documentElement, {attributes: true, attributeFilter: ['data-ui-motion']});
  reduced.addEventListener('change', synchronize);
  document.addEventListener('visibilitychange', synchronize);
  watch(document.body);
}

export function createToastPresenter({esc, icon,owner=()=>null}) {
  const host = document.querySelector('#toast');
  let timer, remaining = 0, duration = 0, started = 0, progress, paused = true, revision=0;
  function close() {revision++;clearTimeout(timer); progress?.cancel(); paused = true; host.className = ''; host.replaceChildren();}
  function pause() {
    if (paused) return;
    paused = true;
    clearTimeout(timer);
    remaining = Math.max(0, remaining - (performance.now() - started));
    progress?.pause();
  }
  function resume() {
    if (!host.classList.contains('visible') || !paused) return;
    paused = false;
    clearTimeout(timer); started = performance.now();
    if(motionAllowed() && progress){progress.currentTime=duration-remaining;progress.play();}else progress?.cancel();
    timer = setTimeout(close, remaining);
  }
  host.addEventListener('pointerenter', pause);
  host.addEventListener('pointerleave', () => {if (!host.contains(document.activeElement)) resume();});
  host.addEventListener('focusin', pause);
  host.addEventListener('focusout', event => {if (!host.contains(event.relatedTarget)) resume();});
  host.addEventListener('click', event => {if (event.target.closest('[data-toast-close]')) close();});
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause(); else if (!host.matches(':hover') && !host.contains(document.activeElement)) resume();
  });
  const present = (message, error = false, options = {}) => {
    const ticket=++revision,account=owner();
    clearTimeout(timer); progress?.cancel(); paused = true;
    remaining = Math.max(error ? 7000 : 4500, Math.min(15000, Number.isFinite(options.duration) ? options.duration : String(message).length * 90));
    duration = remaining;
    host.innerHTML = `<span class="toast-symbol" aria-hidden="true">${icon(error ? 'info' : 'check')}</span><span class="toast-copy">${esc(message)}</span><button type="button" class="icon-button" aria-label="关闭提示" data-toast-close>${icon('close')}</button><span class="toast-lifetime" aria-hidden="true"></span>`;
    host.className = 'visible' + (error ? ' error' : '');
    if(options.action){
      host.classList.add('has-action');
      const action=document.createElement('button');action.type='button';action.className='button small toast-action';action.textContent=options.action.label||'撤销';host.querySelector('[data-toast-close]').before(action);
      action.addEventListener('click',async()=>{
        if(account!==owner()){close();return;}
        if(action.disabled)return;action.disabled=true;pause();
        try{await options.action.run();if(ticket===revision&&account===owner())present(options.action.success||'已撤销。');}
        catch(cause){if(ticket===revision&&account===owner())present(cause.message||'撤销未完成，请稍后重试。',true,{...options,duration:15000});}
      });
    }
    if (motionAllowed()) {
      animateSurface(host.querySelector('.toast-symbol'), 0);
      progress = host.querySelector('.toast-lifetime').animate([{transform: 'scaleX(1)'}, {transform: 'scaleX(0)'}], {duration: remaining, fill: 'forwards'});
      const animation = progress;
      running.add(animation);animation.finished.catch(() => {}).finally(() => running.delete(animation));
    }
    resume();
    if (document.hidden || host.matches(':hover') || host.contains(document.activeElement)) pause();
  };
  return present;
}
