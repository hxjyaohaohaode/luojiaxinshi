// A page is an explicitly bounded projection. Filters and totals belong to the
// server; this controller never treats an initial slice as the whole account.
export function createPagedList({api, path, owner, context = () => null, onChange = () => {}, limit = 50}) {
  let account, filters = {}, key = '', epoch = 0, controller, pending, requestView;
  let data = empty();
  function empty() { return {items: [], total: 0, has_more: false, next_cursor: null, facets: {}, loaded: false, loading: false, error: '', notice: '', limit}; }
  const snapshot = () => ({...data, items: [...data.items], filters: {...filters}});
  const emit = (options = {}) => onChange(snapshot(), options);
  function clear() {
    epoch++; controller?.abort(); pending = null; account = owner(); key = ''; filters = {}; data = empty();
  }
  function normalize(values) {
    return Object.fromEntries(Object.entries(values).filter(([,value]) => value !== '' && value != null).sort(([a],[b]) => a.localeCompare(b)));
  }
  async function request(append = false, refreshed = false, {preserveRange = false, targetSize = 0, canApply = () => true, equal = (a,b) => JSON.stringify(a) === JSON.stringify(b)} = {}) {
    const ticket = ++epoch, uid = account, view = context();
    controller?.abort(); controller = new AbortController(); const signal = controller.signal; requestView = view;
    const params = new URLSearchParams({...filters, limit: String(limit)});
    if (append && data.next_cursor) params.set('cursor', data.next_cursor);
    const target = preserveRange ? Math.max(limit, data.items.length, targetSize) : 0, previousError = data.error;
    data = {...data, loading: true, error: ''}; if (!preserveRange) emit();
    const valid = () => ticket === epoch && uid === owner() && view === context() && canApply();
    const work = (async () => {
      try {
        const records = new Map((append ? data.items : []).map(item => [item.id, item]));
        let result, restart = 0;
        const cursors = new Set();
        // Re-evaluate time-dependent membership/order on the server, then
        // publish the whole previously loaded range as one atomic update.
        // Partial pages and transient failures never replace the visible list.
        while (true) {
          try { result = await api(path + '?' + params, {signal}); }
          catch (error) {
            if (preserveRange && valid() && error.status === 409 && error.detail?.code === 'list_changed' && restart++ === 0) {
              records.clear(); cursors.clear(); params.delete('cursor'); continue;
            }
            throw error;
          }
          if (!valid()) return null;
          if (!Array.isArray(result.items) || !Number.isFinite(result.total)) throw Error('列表响应不完整，请重试。');
          for (const item of result.items) records.set(item.id, item);
          if (!preserveRange || records.size >= target || !result.has_more) break;
          if (!result.next_cursor || cursors.has(result.next_cursor) || !result.items.length) throw Error('列表分页信息已变化，请稍后重试。');
          cursors.add(result.next_cursor); params.set('cursor', result.next_cursor);
        }
        const items = [...records.values()];
        const unchanged = preserveRange && equal(data.items, items) && data.total === result.total && data.has_more === result.has_more && !previousError;
        data = {...data, ...result, items, loaded: true, loading: false, error: '',
          notice: refreshed ? '列表已有更新，已保留筛选与已加载范围，并重新读取后续记录。' : data.notice};
        if (!unchanged) emit({preserveViewport: preserveRange}); return snapshot();
      } catch (error) {
        if (!valid()) return null;
        if (append && error.status === 409 && error.detail?.code === 'list_changed') {
          return request(false, true, {preserveRange:true,targetSize:data.items.length+limit,canApply,equal});
        }
        if (error.name !== 'AbortError') data = {...data, loading: false, error: error.message || '列表暂时无法读取。'};
        else data = {...data, loading: false};
        emit({preserveViewport: preserveRange}); return null;
      } finally {
        if (ticket === epoch) { pending = null; if (data.loading) data = {...data, loading: false}; }
      }
    })();
    pending = work; return work;
  }
  function load(values = filters, {force = false, preserveRange = false, canApply, equal} = {}) {
    if (account !== owner()) clear();
    const normalized = normalize(values), nextKey = JSON.stringify(normalized);
    if (!force && nextKey === key) {
      if (data.loading && pending) return requestView === context() ? pending : request();
      if (data.loaded) { requestView = context(); return Promise.resolve(snapshot()); }
    }
    preserveRange = preserveRange && nextKey === key && data.loaded && requestView === context();
    if (preserveRange && data.loading && pending) return pending;
    if (nextKey !== key) data = empty();
    filters = normalized; key = nextKey;
    return request(false, false, {preserveRange, canApply, equal});
  }
  function more() {
    if (account !== owner()) { clear(); emit(); return Promise.resolve(null); }
    if (data.loading) return pending || Promise.resolve(null);
    if (!data.has_more || !data.next_cursor) return Promise.resolve(snapshot());
    return request(true);
  }
  function patch(mapper, {canApply = () => true, equal = (a,b) => JSON.stringify(a) === JSON.stringify(b)} = {}) {
    if (account !== owner() || requestView !== context() || !data.loaded || data.loading || !canApply()) return null;
    const items = data.items.map(mapper), changed = !equal(data.items, items);
    data = {...data, items}; if (changed) emit({preserveViewport:true});
    return snapshot();
  }
  return {load, more, clear, snapshot, patch, reload: options => load(filters, {...options, force: true})};
}
