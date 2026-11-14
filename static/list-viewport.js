// Background refreshes may change a time label or move a newly expired row.
// Keep the reader's visible surviving record, keyboard target and board lane.
export function preserveListViewport(render, root = document.querySelector('#content')) {
  if (!root) return render();
  const focused = document.activeElement, scroll = root.scrollTop, left = root.scrollLeft;
  const windowX = window.scrollX, windowY = window.scrollY, boardLeft = root.querySelector('.task-board-scroll')?.scrollLeft;
  const selector = node => {
    if (!node) return null;
    if (node.id) return '#' + CSS.escape(node.id);
    if (node.dataset?.taskId) return '[data-task-id="' + CSS.escape(node.dataset.taskId) + '"]';
    for (const attribute of ['data-workflow-task', 'data-id', 'href']) {
      const value = node.getAttribute(attribute);
      if (value) return node.tagName.toLowerCase() + '[' + attribute + '="' + CSS.escape(value) + '"]' +
        (node.dataset.action ? '[data-action="' + CSS.escape(node.dataset.action) + '"]' : '');
    }
    return null;
  };
  const row = focused?.closest('[data-task-id],.notice-row'), rowSelector = selector(row);
  const focusSelector = root.contains(focused) ? selector(focused) : null;
  const focusIndex = row && !focusSelector ? [...row.querySelectorAll('button,a,summary,input,select,textarea')].indexOf(focused) : -1;
  const top = Math.max(0, root.getBoundingClientRect().top);
  const anchors = [...root.querySelectorAll('[data-task-id],a.notice-row,.matter-library-card>a')]
    .filter(node => node.getBoundingClientRect().bottom > top && node.getBoundingClientRect().top < innerHeight)
    .map(node => ({selector:selector(node), top:node.getBoundingClientRect().top})).filter(item => item.selector);
  const result = render();
  const board = root.querySelector('.task-board-scroll'); if (board && boardLeft != null) board.scrollLeft = boardLeft;
  root.scrollTop = scroll; root.scrollLeft = left; window.scrollTo(windowX, windowY);
  for (const anchor of anchors) {
    const current = root.querySelector(anchor.selector); if (!current) continue;
    const delta = current.getBoundingClientRect().top - anchor.top;
    if (root.scrollHeight > root.clientHeight + 1) root.scrollTop += delta;
    else window.scrollTo(windowX, windowY + delta);
    break;
  }
  if (root.contains(focused)) return result;
  const replacement = focusSelector ? root.querySelector(focusSelector) : rowSelector && focusIndex >= 0 ?
    root.querySelector(rowSelector)?.querySelectorAll('button,a,summary,input,select,textarea')[focusIndex] : null;
  replacement?.focus({preventScroll:true});
  return result;
}
