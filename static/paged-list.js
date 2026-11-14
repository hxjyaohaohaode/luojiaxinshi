// A page is an explicitly bounded projection. Filters and totals belong to the
// server; this controller never treats an initial slice as the whole account.
export function createPagedList({api, path, owner, context = () => null, onChange = () => {}, limit = 50}) {
  let account, filters = {}, key = '', epoch = 0, controller, pending, requestView;
  let data = empty();
  function empty() { return {items: [], total: 0, has_more: false, next_cursor: null, facets: {}, loaded: false, loading: false, error: '', notice: '', limit}; }
  const snapshot = () => ({...data, items: [...data.items], filters: {...filters}});
  const emit = () => onChange(snapshot());
  function clear() {
    epoch++; controller?.abort(); pending = null; account = owner(); key = ''; filters = {}; data = empty();
  }
  function normalize(values) {
    return Object.fromEntries(Object.entries(values).filter(([,value]) => value !== '' && value != null).sort(([a],[b]) => a.localeCompare(b)));
  }
  async function request(append = false, refreshed = false) {
    const ticket = ++epoch, uid = account, view = context();
    controller?.abort(); controller = new AbortController(); requestView = view;
    const params = new URLSearchParams({...filters, limit: String(limit)});
    if (append && data.next_cursor) params.set('cursor', data.next_cursor);
    data = {...data, loading: true, error: ''}; emit();
    const valid = () => ticket === epoch && uid === owner() && view === context();
    const work = (async () => {
      try {
        const result = await api(path + '?' + params, {signal: controller.signal});
        if (!valid()) return null;
        if (!Array.isArray(result.items) || !Number.isFinite(result.total)) throw Error('列表响应不完整，请重试。');
        const records = new Map((append ? data.items : []).map(item => [item.id, item]));
        for (const item of result.items) records.set(item.id, item);
        data = {...data, ...result, items: [...records.values()], loaded: true, loading: false, error: '',
          notice: refreshed ? '列表已有更新，已保留筛选并重新读取第一页。' : data.notice};
        emit(); return snapshot();
      } catch (error) {
        if (!valid()) return null;
        if (append && error.status === 409 && error.detail?.code === 'list_changed') {
          data = {...empty(), notice: '列表已有更新，正在按原筛选重新读取。'};
          return request(false, true);
        }
        if (error.name !== 'AbortError') data = {...data, loading: false, error: error.message || '列表暂时无法读取。'};
        else data = {...data, loading: false};
        emit(); return null;
      } finally {
        if (ticket === epoch) { pending = null; if (data.loading) data = {...data, loading: false}; }
      }
    })();
    pending = work; return work;
  }
  function load(values = filters, {force = false} = {}) {
    if (account !== owner()) clear();
    const normalized = normalize(values), nextKey = JSON.stringify(normalized);
    if (!force && nextKey === key) {
      if (data.loading && pending) return requestView === context() ? pending : request();
      if (data.loaded) return Promise.resolve(snapshot());
    }
    if (nextKey !== key) data = empty();
    filters = normalized; key = nextKey;
    return request();
  }
  function more() {
    if (account !== owner()) { clear(); emit(); return Promise.resolve(null); }
    if (data.loading) return pending || Promise.resolve(null);
    if (!data.has_more || !data.next_cursor) return Promise.resolve(snapshot());
    return request(true);
  }
  return {load, more, clear, snapshot, reload: () => load(filters, {force: true})};
}
