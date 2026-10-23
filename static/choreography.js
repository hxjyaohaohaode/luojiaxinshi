// 界面编排：页面入场、列表错峰、文字浮现、悬停跟随、完成反馈与滚动层次。
// 只负责“怎么出现”，不改变业务状态；动效关闭或系统减少动态效果时全部跳过。
import {motionAllowed} from './experience-system.js';

const EASE_OUT = 'cubic-bezier(.22,1,.36,1)';
const SPRING = (() => {
  try {
    const probe = document.createElement('div');
    probe.animate([{opacity: 0}, {opacity: 1}], {duration: 1, easing: 'linear(0, 1)'}).cancel();
    return 'linear(0, .012, .047 2.6%, .19 5.8%, .623 12.8%, .82 16.8%, .955 21.3%, 1.024 25.6%, 1.045 29.2%, 1.046 32.3%, 1.03 37.6%, 1.006 45.2%, .995 52.3%, 1)';
  } catch { return 'cubic-bezier(.3,1.22,.55,1)'; }
})();

// 页面中可作为“区块”的元素：按文档顺序错峰出现。
const BLOCKS = [
  '.overview-launch', '.action-metrics', '.overview-week', '.overview-workspace > *', '.dashboard-insights > *',
  '.workspace-page-heading:not(.sr-only)', '.toolbar', '.task-filter-row', '.task-results', '.pagination',
  '.collection-summary', '.library-toolbar', '.library-tabs-row', '#library-results',
  '.notice-primary', '.notice-steps', '.review-grid > *', '.notice-stepper', '.compose-layout > *',
  '.settings-person', '.settings-group', '.companion-setting',
  '.chat-welcome > *', '.calendar-sidebar', '.calendar-main',
  '.source-hero', '.source-directory', '.memory-tree-head', '.memory-tree-shell',
  '.reminder-center > *', '.insight-page > *', '.legal-page > *',
].join(',');
// 区块内部的条目：在所属区块之后依次浮现。
const ITEMS = [
  '.action-metric', '.week-days > button', '.task-row', '.notice-row', '.notice-card', '.task-board-column',
  '.settings-item', '.scene-choice', '.catalog-card', '.source-starter', '.integration-card', '.fact',
  '.calendar-list-row', '.memory-tree-row', '.memory-record', '.reminder-item', '.insight-card', '.insight-bar',
].join(',');
// 适合逐字浮现的短标题。
const HEADINGS = [
  '.overview-focus h2', '.chat-welcome h1', '.chat-welcome h2', '.settings-person h2', '.notice-primary h1',
  '.overview-empty h2', '.empty h3', '.saved-notice-header h2', '.insight-hero h2', '.reminder-hero h2', '.auth-greeting',
].join(',');

const live = new Set();
function track(animation) {
  live.add(animation);
  animation.finished.catch(() => {}).finally(() => live.delete(animation));
  return animation;
}
export function cancelChoreography() { for (const animation of live) animation.cancel(); live.clear(); }

function inViewport(node, margin = 160) {
  const rect = node.getBoundingClientRect();
  return rect.bottom > -margin && rect.top < innerHeight + margin && rect.width > 0 && rect.height > 0;
}
function rise(node, delay, distance = 14, duration = 560) {
  return track(node.animate([
    {opacity: 0, transform: `translate3d(0,${distance}px,0) scale(.985)`},
    {opacity: 1, transform: 'none'},
  ], {duration, delay, easing: SPRING, fill: 'backwards'}));
}

// 把标题拆成逐字元素，按顺序轻轻浮起；读屏仍朗读完整标题。
export function revealText(node, delay = 0) {
  if (!node || !motionAllowed() || node.dataset.revealed === node.textContent) return;
  const text = node.textContent;
  if (!text.trim() || text.length > 40 || node.children.length) { node.dataset.revealed = text; return; }
  const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('zh', {granularity: 'grapheme'}) : null;
  const glyphs = segmenter ? [...segmenter.segment(text)].map(part => part.segment) : [...text];
  node.setAttribute('aria-label', text);
  node.classList.add('text-reveal');
  node.replaceChildren(...glyphs.map((glyph, index) => {
    const span = document.createElement('span');
    span.className = glyph.trim() ? 'tr-char' : 'tr-space';
    span.textContent = glyph;
    span.setAttribute('aria-hidden', 'true');
    if (glyph.trim()) {
      track(span.animate([
        {opacity: 0, transform: 'translate3d(0,.45em,0)', filter: 'blur(3px)'},
        {opacity: 1, transform: 'none', filter: 'blur(0)'},
      ], {duration: 520, delay: delay + index * 22, easing: SPRING, fill: 'backwards'}));
    }
    return span;
  }));
  node.dataset.revealed = text;
}

// 页面切换后调用：区块 → 条目 → 标题，带轻微延迟的跟随感。
export function choreograph(root) {
  if (!root || !motionAllowed()) return;
  cancelChoreography();
  const blocks = [...root.querySelectorAll(BLOCKS)].filter(node => inViewport(node) && !node.closest('.sr-only'));
  const top = blocks.filter(node => !blocks.some(other => other !== node && other.contains(node))).slice(0, 12);
  const seen = new Set();
  top.forEach((block, index) => {
    const delay = index * 55;
    rise(block, delay);
    const items = [...block.querySelectorAll(ITEMS)].filter(node => inViewport(node, 40)).slice(0, 10);
    items.forEach((item, j) => { seen.add(item); rise(item, delay + 120 + j * 34, 10, 520); });
  });
  // 聊天、记忆这类整屏工作区没有可错峰的区块：只淡入，不位移不缩放。
  // 弹性曲线会过冲，整屏容器会被放大约 0.07%，测量和布局都会受影响。
  if (!top.length) track((root.firstElementChild || root).animate([{opacity: 0}, {opacity: 1}], {duration: 320, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards'}));
  root.querySelectorAll(HEADINGS).forEach(node => { if (inViewport(node)) revealText(node, 160); });
  markSeen(root, seen);
}

// 列表在页面内刷新（筛选、翻页、切换视图）时，新条目错峰补位。
// 以“记录身份”判断是否新出现：同一条记录因数据刷新重绘时不再重复入场。
const known = new WeakSet();
let seenKeys = new Set();
function itemKey(node) {
  const ref = node.querySelector('[data-workflow-task],[data-id],[data-overview-day],[data-source-record]');
  const id = node.dataset.key || node.dataset.sourceRecord || node.dataset.overviewDay ||
    ref?.dataset.workflowTask || ref?.dataset.id || ref?.dataset.overviewDay || ref?.dataset.sourceRecord;
  return (node.className.split(' ')[0] || '') + ':' + (id || node.textContent.trim().slice(0, 80));
}
function markSeen(root) {
  seenKeys = new Set();
  root.querySelectorAll(ITEMS).forEach(node => { known.add(node); seenKeys.add(itemKey(node)); });
}
function animateNewItems(nodes) {
  let index = 0;
  for (const node of nodes) {
    known.add(node);
    const key = itemKey(node), fresh = !seenKeys.has(key);
    seenKeys.add(key);
    if (fresh && motionAllowed() && index < 12 && inViewport(node, 40)) rise(node, index++ * 30, 8, 460);
  }
}

// 悬停跟随底板：比指针慢半拍地滑到悬停项。
function installHoverFollower(selector, itemSelector) {
  const fine = matchMedia('(hover:hover) and (pointer:fine)');
  const followers = new WeakMap();
  document.addEventListener('pointerover', event => {
    if (!fine.matches || !motionAllowed()) return;
    const group = event.target.closest(selector);
    if (!group) return;
    const item = event.target.closest(itemSelector);
    let follower = followers.get(group);
    if (!follower || !follower.isConnected) {
      follower = document.createElement('span');
      follower.className = 'hover-follower';
      follower.setAttribute('aria-hidden', 'true');
      group.prepend(follower);
      followers.set(group, follower);
      follower.style.transition = 'none';
      requestAnimationFrame(() => { follower.style.transition = ''; });
    }
    if (!item || !group.contains(item) || item.classList.contains('active')) { follower.classList.remove('is-visible'); return; }
    follower.style.transform = `translate(${item.offsetLeft}px,${item.offsetTop}px)`;
    follower.style.width = item.offsetWidth + 'px';
    follower.style.height = item.offsetHeight + 'px';
    follower.classList.add('is-visible');
  }, {passive: true});
  document.addEventListener('pointerout', event => {
    const group = event.target.closest?.(selector);
    if (group && !group.contains(event.relatedTarget)) followers.get(group)?.classList.remove('is-visible');
  }, {passive: true});
}

// 完成一项：勾选框回弹，并洒出几片品牌色小纸片。
export function celebrateCheck(control) {
  if (!control) return;
  control.classList.remove('just-checked');
  void control.offsetWidth;
  control.classList.add('just-checked');
  setTimeout(() => control.classList.remove('just-checked'), 700);
  if (!motionAllowed()) return;
  const rect = control.getBoundingClientRect();
  const colors = ['#2f7d54', '#b88a3e', '#7fb064', '#e5a3ad', '#115740'];
  for (let i = 0; i < 9; i++) {
    const bit = document.createElement('span');
    bit.className = 'confetti-bit';
    bit.style.setProperty('--bit', colors[i % colors.length]);
    bit.style.left = rect.left + rect.width / 2 + 'px';
    bit.style.top = rect.top + rect.height / 2 + 'px';
    document.body.append(bit);
    const angle = (Math.PI * 2 * i) / 9 + Math.random() * .4, distance = 26 + Math.random() * 22;
    const animation = bit.animate([
      {transform: 'translate(-50%,-50%) scale(.6) rotate(0deg)', opacity: 1},
      {transform: `translate(calc(-50% + ${Math.cos(angle) * distance}px), calc(-50% + ${Math.sin(angle) * distance}px)) scale(1) rotate(${120 + i * 40}deg)`, opacity: .95, offset: .55},
      {transform: `translate(calc(-50% + ${Math.cos(angle) * distance * 1.25}px), calc(-50% + ${Math.sin(angle) * distance * 1.25 + 18}px)) scale(.4) rotate(${200 + i * 50}deg)`, opacity: 0},
    ], {duration: 760 + Math.random() * 200, easing: EASE_OUT});
    animation.finished.catch(() => {}).finally(() => bit.remove());
  }
}

// 文字内容变化时轻轻“换字”。
function installTextSwap() {
  const selector = '.autosave-status,.save-state,[data-live-text],#task-count,.week-agenda,.deck-controls [aria-live]';
  const observer = new MutationObserver(records => {
    if (!motionAllowed()) return;
    const targets = new Set();
    for (const record of records) {
      const node = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      const host = node?.closest?.(selector);
      if (host) targets.add(host);
    }
    for (const host of targets) { host.classList.remove('text-swap'); void host.offsetWidth; host.classList.add('text-swap'); }
  });
  observer.observe(document.body, {subtree: true, characterData: true, childList: true});
}

// 内容滚动后顶栏出现柔和阴影。
function installScrollDepth() {
  document.addEventListener('scroll', event => {
    const scroller = event.target;
    if (!(scroller instanceof Element) || scroller.id !== 'content') return;
    scroller.closest('.workspace')?.classList.toggle('is-scrolled', scroller.scrollTop > 8);
  }, {passive: true, capture: true});
}

// 小信使随指针轻微偏转，带一点延迟。
function installParallax() {
  const fine = matchMedia('(hover:hover) and (pointer:fine)');
  let frame = 0, last = null;
  document.addEventListener('pointermove', event => {
    if (!fine.matches || !motionAllowed()) return;
    last = event;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      for (const node of document.querySelectorAll('[data-parallax]')) {
        if (!inViewport(node, 0)) continue;
        const rect = node.getBoundingClientRect();
        const dx = (last.clientX - (rect.left + rect.width / 2)) / innerWidth;
        const dy = (last.clientY - (rect.top + rect.height / 2)) / innerHeight;
        const depth = Number(node.dataset.parallax) || 10;
        node.style.transform = `translate3d(${(dx * depth).toFixed(2)}px,${(dy * depth).toFixed(2)}px,0) rotate(${(dx * depth * .25).toFixed(2)}deg)`;
      }
    });
  }, {passive: true});
}

let installed = false;
export function initializeChoreography() {
  if (installed) return;
  installed = true;
  installHoverFollower('.sidebar nav', '.nav-item');
  // Settings cards already have hover feedback. Inserting a follower into
  // their grid changed child-index layout rules and moved click targets.
  installTextSwap();
  installScrollDepth();
  installParallax();
  // 页面内局部刷新带来的新条目
  const observer = new MutationObserver(records => {
    const fresh = [];
    for (const record of records) for (const node of record.addedNodes) {
      if (!(node instanceof Element) || node.closest('#dialog,.chat-thread')) continue;
      const candidates = node.matches(ITEMS) ? [node] : [...node.querySelectorAll(ITEMS)];
      for (const item of candidates) if (!known.has(item)) fresh.push(item);
    }
    if (!fresh.length) return;
    requestAnimationFrame(() => {
      // 整页切换由 choreograph() 统一编排，这里只处理页面内的局部刷新。
      const content = document.querySelector('#content');
      if (!content || content.classList.contains('route-pending')) { fresh.forEach(node => known.add(node)); return; }
      animateNewItems(fresh.filter(node => node.isConnected));
    });
  });
  const watch = () => {
    const content = document.querySelector('#content');
    if (content && !content.dataset.choreographed) { content.dataset.choreographed = '1'; observer.observe(content, {childList: true, subtree: true}); }
  };
  new MutationObserver(watch).observe(document.querySelector('#app'), {childList: true});
  watch();
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-action="toggle-task"]');
    if (control && !control.classList.contains('checked')) requestAnimationFrame(() => celebrateCheck(control));
  }, true);
}
