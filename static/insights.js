// 数据看板：个人完成情况、期限分布、来源与相关性；管理员另有全站匿名计数。
import {numberMarkup, ringMarkup} from './experience-system.js';

const RELEVANCE = [
  ['matches_known', '和你有关', '#2f7d54'],
  ['needs_review', '需要确认是否适用', '#b88a3e'],
  ['not_matching', '可能不适用', '#9aa79f'],
  ['unprocessed', '还没整理', '#d6ddd7'],
];

function percent(part, total) { return total ? Math.round(part / total * 100) : 0; }

function barChart(rows, {label, value, max, caption, stack}) {
  const top = Math.max(1, max ?? Math.max(...rows.map(row => stack ? stack.reduce((sum, key) => sum + row[key], 0) : row[value])));
  return `<div class="insight-bars" role="img" aria-label="${caption}">${rows.map((row, index) => {
    const parts = stack ? stack.map(key => [key, row[key]]) : [[value, row[value]]];
    const total = parts.reduce((sum, [, n]) => sum + n, 0);
    return `<div class="insight-bar" data-i="${index}"><span class="insight-bar-value">${total || ''}</span><span class="insight-bar-track">${parts.map(([key, n]) => `<i class="seg-${key}" data-height="${(n / top * 100).toFixed(1)}"></i>`).join('')}</span><span class="insight-bar-label">${row[label]}</span></div>`;
  }).join('')}</div>`;
}

function donut(segments, total, caption) {
  let offset = 0;
  const arcs = segments.filter(([, , , n]) => n > 0).map(([key, , color, n]) => {
    const length = n / total * 100, arc = `<circle class="donut-seg" cx="50" cy="50" r="38" pathLength="100" stroke="${color}" stroke-dasharray="${length} ${100 - length}" stroke-dashoffset="${-offset}" data-key="${key}"/>`;
    offset += length; return arc;
  }).join('');
  return `<figure class="insight-donut"><svg viewBox="0 0 100 100" role="img" aria-label="${caption}"><circle cx="50" cy="50" r="38" class="donut-track"/>${arcs}</svg><figcaption><b>${total}</b><span>则通知</span></figcaption></figure>`;
}

export function createInsightsUI({state, api, esc, icon, companion}) {
  const $ = selector => document.querySelector(selector);

  function personal(data) {
    const t = data.tasks, finished = t.on_time + t.late;
    const weekDone = data.trend.at(-1)?.done || 0, lastWeek = data.trend.at(-2)?.done || 0;
    const delta = weekDone - lastWeek;
    const mood = !t.total ? '还没有待办，处理第一则通知后这里就会热闹起来。'
      : t.overdue ? `有 ${t.overdue} 件事过了期限，先看看还能不能补救。`
      : weekDone ? `这周已经完成 ${weekDone} 件，${delta > 0 ? '比上周多了 ' + delta + ' 件，节奏很好。' : delta < 0 ? '慢慢来，稳稳推进就好。' : '和上周差不多，保持住。'}`
      : '这周还没有完成记录，挑一件最小的事开始吧。';
    const sourceMax = Math.max(1, ...data.sources.map(s => s.count));
    const relevanceTotal = RELEVANCE.reduce((sum, [key]) => sum + (data.relevance[key] || 0), 0);
    return `
    <section class="insight-hero">
      <div class="insight-hero-copy"><span class="insight-kicker">我的数据看板</span><h2>${esc(mood)}</h2><p class="small muted">只统计你自己的通知和待办，数据每次打开时重新计算。</p></div>
      ${companion('complete', 'insight-companion')}
    </section>
    <div class="insight-grid">
      <article class="insight-card insight-completion">${ringMarkup(t.done, t.done + t.pending, '完成率')}<div><h3>完成情况</h3><p><strong>${numberMarkup(t.done)}</strong> 件已完成 · <span class="nowrap">${t.pending} 件进行中</span></p><p class="small muted">${t.cancelled ? t.cancelled + ' 件已取消，不算在内' : '已取消的不算在内'}</p></div></article>
      <article class="insight-card"><h3>按时完成</h3><p class="insight-number">${finished ? percent(t.on_time, finished) + '<small>%</small>' : '—'}</p><p class="small muted">${finished ? `有期限的 ${finished} 件里，${t.on_time} 件按时完成` : '完成有期限的事项后会统计'}</p></article>
      <article class="insight-card ${t.overdue ? 'is-warning' : ''}"><h3>已过期未完成</h3><p class="insight-number">${numberMarkup(t.overdue)}</p><p class="small muted">${t.overdue ? '去待办看看还能怎么补救' : '没有拖着的事，真好'}</p></article>
      <article class="insight-card"><h3>通知转成待办</h3><p class="insight-number">${numberMarkup(data.notices.confirmed)}<small> / ${data.notices.total}</small></p><p class="small muted">${data.notices.waiting ? data.notices.waiting + ' 则还在等你整理' : '收到的通知都处理过了'}</p></article>
    </div>
    <div class="insight-grid two">
      <article class="insight-card wide"><header><h3>近 8 周完成数</h3><span class="small muted">以完成时间计</span></header>${barChart(data.trend, {label: 'label', value: 'done', caption: '近 8 周每周完成的事项数'})}</article>
      <article class="insight-card wide"><header><h3>接下来 4 周的期限</h3><span class="insight-legend"><i class="seg-confirmed"></i>已确认 <i class="seg-unconfirmed"></i>待确认</span></header>${barChart(data.horizon, {label: 'label', stack: ['confirmed', 'unconfirmed'], caption: '未来 4 周每周到期的事项数'})}</article>
    </div>
    <div class="insight-grid two">
      <article class="insight-card wide"><header><h3>通知和你的关系</h3><span class="small muted">来自 AI 整理时的判断</span></header>
        <div class="insight-relevance">${relevanceTotal ? donut(RELEVANCE.map(([key, label, color]) => [key, label, color, data.relevance[key] || 0]), relevanceTotal, '通知与你的相关程度分布') : '<p class="small muted">还没有通知。</p>'}
        <ul class="insight-legend-list">${RELEVANCE.map(([key, label, color]) => `<li><i data-color="${color}"></i>${label}<b>${data.relevance[key] || 0}</b></li>`).join('')}</ul></div>
        <a class="link-button small" href="#notices">去通知资料按“和我有关”筛选 →</a></article>
      <article class="insight-card wide"><header><h3>通知从哪里来</h3><span class="small muted">按你填写的来源</span></header>
        ${data.sources.length ? `<ol class="insight-sources">${data.sources.map((s, i) => `<li data-i="${i}"><span>${esc(s.label)}</span><span class="insight-source-bar"><i data-width="${(s.count / sourceMax * 100).toFixed(1)}"></i></span><b>${s.count}</b></li>`).join('')}</ol>` : '<p class="small muted">还没有通知来源。</p>'}
      </article>
    </div>
    <p class="insight-foot small muted">待办共 ${t.total} 件，其中 ${t.from_ai} 件来自 AI 整理、${t.manual} 件为手工添加，全部经你确认后保存。</p>`;
  }

  function site(data) {
    return `<section class="insight-site"><header><h3>全站概况</h3><span class="small muted">管理员可见 · 只有匿名计数，不含任何人的通知内容</span></header>
      <div class="insight-grid">
        <article class="insight-card"><h3>注册账号</h3><p class="insight-number">${numberMarkup(data.users.total)}</p><p class="small muted">近 7 天活跃 ${data.users.active_7d}</p></article>
        <article class="insight-card"><h3>收录通知</h3><p class="insight-number">${numberMarkup(data.notices.total)}</p><p class="small muted">近 30 天 ${data.notices.last_30d} · 已转办 ${data.notices.confirmed}</p></article>
        <article class="insight-card"><h3>待办完成率</h3><p class="insight-number">${percent(data.tasks.done, data.tasks.done + data.tasks.pending)}<small>%</small></p><p class="small muted">${data.tasks.done} 已完成 · ${data.tasks.pending} 进行中</p></article>
        <article class="insight-card"><h3>近 30 天 AI 整理</h3><p class="insight-number">${numberMarkup(data.ai_30d.calls)}</p><p class="small muted">${data.ai_30d.failed ? data.ai_30d.failed + ' 次没成功' : '都顺利完成'}</p></article>
      </div></section>`;
  }

  async function render(renderId) {
    const isAdmin = state.session.user.role === 'admin';
    const [mine, all] = await Promise.all([api('/insights'), isAdmin ? api('/admin/insights').catch(() => null) : null]);
    if (renderId !== state.renderId) return;
    $('#content').innerHTML = `<div class="insight-page"><h1 class="sr-only">数据看板</h1>${personal(mine)}${all ? site(all) : ''}</div>`;
    // 页面启用了严格 CSP，不允许内联 style 属性；尺寸与颜色通过 CSSOM 设置。
    const page = $('#content .insight-page');
    page.querySelectorAll('[data-i]').forEach(node => node.style.setProperty('--i', node.dataset.i));
    page.querySelectorAll('[data-height]').forEach(node => { node.style.height = node.dataset.height + '%'; });
    page.querySelectorAll('[data-width]').forEach(node => { node.style.width = node.dataset.width + '%'; });
    page.querySelectorAll('[data-color]').forEach(node => { node.style.background = node.dataset.color; });
  }

  return {render};
}
