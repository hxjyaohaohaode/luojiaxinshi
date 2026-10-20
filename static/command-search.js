/* Grouped, keyboard-operable search. Each response belongs to its dialog and
   account; opening search never replaces the active page's records. */
export function searchRecords(tasks, notices, value = '') {
  const query = value.trim().toLowerCase();
  const rank = item => {
    const title = item.title.toLowerCase();
    return !query ? 0 : title === query ? 4 : title.startsWith(query) ? 3 : title.includes(query) ? 2 : item.search.toLowerCase().includes(query) ? 1 : 0;
  };
  const select = items => items.map((item, index) => ({ ...item, rank: rank(item), index }))
    .filter(item => !query || item.rank > 0).sort((a, b) => b.rank - a.rank || a.index - b.index);
  return {
    tasks: select(tasks.map(task => ({
      title: task.data?.title || '未命名行动',
      search: [task.notice_title, ...(task.data?.materials || [])].join(' '),
      meta: [task.status === 'done' ? '已完成' : task.status === 'cancelled' ? '已取消' : '待办', task.notice_title].filter(Boolean).join(' · '),
      url: '#notice/' + encodeURIComponent(task.notice_id),
    }))),
    notices: select(notices.map(notice => ({
      title: notice.title || '未命名通知',
      search: [notice.source_label, notice.source_name].filter(Boolean).join(' '),
      meta: notice.source_label || notice.source_name || '已保存的通知原文',
      url: '#notice/' + encodeURIComponent(notice.id),
    }))),
  };
}

export function highlightMatch(text, value, esc) {
  const query = value.trim().toLowerCase(), source = String(text), lower = source.toLowerCase();
  if (!query) return esc(source);
  let from = 0, at, result = '';
  while ((at = lower.indexOf(query, from)) !== -1) {
    result += esc(source.slice(from, at)) + '<mark>' + esc(source.slice(at, at + query.length)) + '</mark>';
    from = at + query.length;
  }
  return result + esc(source.slice(from));
}

export function createCommandSearch({ state, api, esc, icon, showDialog, loadingState, empty }) {
  const $ = selector => document.querySelector(selector);
  let records = null, limit = 6;
  function render() {
    const input = $('#global-search'), results = $('#global-results');
    if (!input || !results || !records) return;
    const query = input.value, found = searchRecords(records.tasks, records.notices, query);
    const total = found.tasks.length + found.notices.length;
    const group = (key, title, symbol) => {
      const items = found[key];
      if (!items.length) return '';
      return `<section class="command-group" aria-labelledby="command-${key}-heading">
        <h3 id="command-${key}-heading">${title}<span>${items.length}</span></h3>
        ${items.slice(0, limit).map((item, index) => `<a class="command-result" data-command-item data-command-key="${key}-${index}" href="${esc(item.url)}">
          <span class="command-symbol">${icon(symbol)}</span><span class="command-copy"><strong>${highlightMatch(item.title, query, esc)}</strong><small>${highlightMatch(item.meta, query, esc)}</small></span>${icon('arrow')}</a>`).join('')}
      </section>`;
    };
    const quick = query.trim() ? '' : `<section class="command-group command-shortcuts" aria-labelledby="command-actions-heading"><h3 id="command-actions-heading">快捷前往</h3>
      ${[['new', 'plus', '处理一则通知'], ['chat', 'spark', '和小信使聊聊'], ['calendar', 'calendar', '查看日历']].map(([route, symbol, title]) => `<a class="command-shortcut" data-command-item href="#${route}">${icon(symbol)}<span>${title}</span>${icon('arrow')}</a>`).join('')}</section>`;
    results.removeAttribute('aria-busy');
    $('#command-count').textContent = query.trim() ? `找到 ${total} 条已存记录` : `${total} 条已存记录，可输入标题、来源或材料关键词`;
    results.innerHTML = quick + (total ? group('tasks', '行动与待办', 'tasks') + group('notices', '通知原文', 'doc') : empty(query.trim() ? '暂时没有匹配的内容' : '从第一则通知开始', query.trim() ? '换一个更短的标题、来源或材料关键词。' : '保存后的通知和行动，会一起出现在这里。', query.trim() ? '<button type="button" class="button small" data-clear-global-search>清空搜索</button>' : '', true, query.trim() ? 'search' : 'listening'))
      + (found.tasks.length > limit || found.notices.length > limit ? '<button type="button" class="button small command-more" data-command-more data-command-item>展开更多结果</button>' : '');
  }
  async function load() {
    const request = state.dialogRequest, user = state.session?.user?.id;
    const current = () => request === state.dialogRequest && user === state.session?.user?.id && !!$('#global-search');
    records = null;
    $('#global-results').setAttribute('aria-busy', 'true');
    $('#global-results').innerHTML = loadingState('正在读取通知与待办', '可以先输入关键词，加载后会显示结果。');
    $('#command-count').textContent = '正在读取已存记录';
    try {
      const [tasks, notices] = await Promise.all([api('/tasks'), api('/notices')]);
      if (!current()) return;
      records = { tasks, notices };
      render();
    } catch (error) {
      if (!current()) return;
      $('#global-results').removeAttribute('aria-busy');
      $('#command-count').textContent = '读取失败，可以重新加载';
      $('#global-results').innerHTML = empty('暂时未能读取', error.message, '<button type="button" class="button small" data-command-retry>重新加载</button>', true, 'static');
    }
  }
  function open() {
    limit = 6;
    showDialog('查找通知和待办', `<div class="command-search">
      <div class="command-input">${icon('search')}<label class="sr-only" for="global-search">输入标题、来源或材料关键词</label><input id="global-search" type="search" placeholder="想找哪则通知，或哪一步？" autocomplete="off" autofocus aria-controls="global-results" aria-describedby="command-count"><button type="button" class="icon-button" data-clear-global-search aria-label="清空搜索">${icon('close')}</button></div>
      <p class="command-count" id="command-count" role="status" aria-live="polite"></p><div id="global-results" class="global-results"></div>
      <div class="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> 选择 <kbd>Enter</kbd> 打开</span><span><kbd>Esc</kbd> 返回</span></div></div>`);
    load();
  }
  document.addEventListener('input', event => {
    if (event.target.id === 'global-search') { limit = 6; render(); }
  });
  document.addEventListener('click', event => {
    if (!$('#global-search')) return;
    if (event.target.closest('[data-clear-global-search]')) {
      $('#global-search').value = ''; limit = 6; render(); $('#global-search').focus();
    } else if (event.target.closest('[data-command-more]')) {
      const prior = new Set([...$('#global-results').querySelectorAll('[data-command-key]')].map(item => item.dataset.commandKey));
      limit += 6; render();
      [...$('#global-results').querySelectorAll('[data-command-key]')].find(item => !prior.has(item.dataset.commandKey))?.focus();
    } else if (event.target.closest('[data-command-retry]')) {
      $('#global-search').focus(); load();
    } else if (event.target.closest('a[data-command-item]')) $('#dialog').close();
  });
  document.addEventListener('keydown', event => {
    if (event.isComposing || event.altKey) return;
    // Some engines consume Escape in type=search before native dialog cancel.
    // The visible shortcut must close the palette consistently with text present.
    if (event.key === 'Escape' && $('#global-search') && $('#dialog').open) {
      event.preventDefault(); $('#dialog').close(); return;
    }
    const command = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k';
    const slash = event.key === '/' && !event.ctrlKey && !event.metaKey && !event.target.closest('input,textarea,select,[contenteditable]');
    if (state.session && (command || slash)) {
      if (!$('#dialog').open) { event.preventDefault(); open(); }
      else if (command && $('#global-search')) { event.preventDefault(); $('#global-search').focus(); }
      return;
    }
    if (!$('#global-search') || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const items = [...$('#global-results').querySelectorAll('[data-command-item]')];
    const index = items.indexOf(event.target), inInput = event.target.id === 'global-search';
    if ((!inInput && index < 0) || (inInput && ['Home', 'End'].includes(event.key)) || !items.length) return;
    event.preventDefault();
    if (event.key === 'Home') items[0].focus();
    else if (event.key === 'End') items.at(-1).focus();
    else if (event.key === 'ArrowUp' && index === 0) $('#global-search').focus();
    else items[inInput ? (event.key === 'ArrowDown' ? 0 : items.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  });
  return { open };
}
