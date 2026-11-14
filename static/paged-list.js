// A page is an explicitly bounded projection. Filters and totals belong to the
// server; this controller never treats an initial slice as the whole account.
export function createPagedList({api, path, owner, context = () => null, revision = () => null, onChange = () => {}, limit = 50}) {
  let account, filters = {}, key = '', epoch = 0, controller, pending, requestView;
  let data = empty(), dataRevision = null, invalidation = 0, verifiedInvalidation = 0, requestMode, queuedMore, moreTimer;
  function empty() { return {items: [], total: 0, has_more: false, next_cursor: null, facets: {}, loaded: false, loading: false, error: '', notice: '', limit}; }
  const stale = () => data.loaded && (dataRevision !== revision() || verifiedInvalidation !== invalidation);
  const snapshot = () => ({...data, items: [...data.items], filters: {...filters}, projection_revision: dataRevision, projection_stale: stale()});
  const emit = (options = {}) => onChange(snapshot(), options);
  const moreScopeMatches = entry => entry.uid === owner() && entry.key === key && entry.view === context();
  function cancelMore() {
    clearTimeout(moreTimer); moreTimer = null;
    const entry = queuedMore; queuedMore = null; entry?.resolve(null);
  }
  function finishMore(entry, value) {
    if (queuedMore !== entry) return;
    clearTimeout(moreTimer); moreTimer = null; queuedMore = null; entry.resolve(value);
  }
  function startMore(entry, explicit = false) {
    if (queuedMore !== entry) return;
    if (!moreScopeMatches(entry) || (!explicit && data.error)) { cancelMore(); return; }
    if (data.loading) return;
    const work = stale() ? request(false, true, {preserveRange:true,targetSize:entry.targetSize}) :
      data.has_more && data.next_cursor ? request(true) : null;
    if (!work) { finishMore(entry, snapshot()); return; }
    const startedTicket = epoch;
    // The request may be superseded by a newer stable refresh. Only the
    // current request's commit/failure may settle this user intention.
    work.catch(error => {
      if (queuedMore !== entry || startedTicket !== epoch) return;
      clearTimeout(moreTimer); moreTimer = null; queuedMore = null; entry.reject(error);
    });
  }
  function scheduleMore() {
    if (!queuedMore || moreTimer) return;
    // Finish the refresh's own callers before starting the user's next page;
    // otherwise an older continuation could overwrite the appended state.
    moreTimer = setTimeout(() => {
      moreTimer = null; const entry = queuedMore;
      if (entry) startMore(entry);
    }, 0);
  }
  function queueMore() {
    if (!queuedMore) {
      const entry = {uid:account,key,view:context(),targetSize:data.items.length+(data.has_more?limit:0)};
      entry.promise = new Promise((resolve,reject) => { entry.resolve = resolve; entry.reject = reject; });
      queuedMore = entry;
    }
    return queuedMore.promise;
  }
  function clear() {
    cancelMore(); epoch++; controller?.abort(); pending = null; account = owner(); key = ''; filters = {}; data = empty(); dataRevision = null;
    invalidation = verifiedInvalidation = 0;
  }
  function invalidate() { if (account !== owner()) clear(); invalidation++; }
  function normalize(values) {
    return Object.fromEntries(Object.entries(values).filter(([,value]) => value !== '' && value != null).sort(([a],[b]) => a.localeCompare(b)));
  }
  async function request(append = false, refreshed = false, {preserveRange = false, targetSize = 0, canApply = () => true, equal = (a,b) => JSON.stringify(a) === JSON.stringify(b)} = {}) {
    const ticket = ++epoch, uid = account, view = context();
    // Stable data can change after the user has already started an append.
    // A same-scope refresh inherits that explicit range instead of reducing
    // the user's pending request to the last committed first page.
    if (!append && queuedMore && moreScopeMatches(queuedMore) && data.loaded) {
      preserveRange = true; targetSize = Math.max(targetSize, queuedMore.targetSize);
    }
    // Capture before starting I/O. A newer shared projection cannot certify
    // an older in-flight page, or the unchanged prefix of an appended page.
    const requestedRevision = revision(), prefixRevision = dataRevision;
    const requestedInvalidation = invalidation, prefixInvalidation = verifiedInvalidation;
    requestMode = {append,preserveRange,invalidation:requestedInvalidation,revision:requestedRevision};
    controller?.abort(); controller = new AbortController(); const signal = controller.signal; requestView = view;
    const params = new URLSearchParams({...filters, limit: String(limit)});
    if (append && data.next_cursor) params.set('cursor', data.next_cursor);
    const target = preserveRange ? Math.max(limit, data.items.length, targetSize) : 0, previousError = data.error;
    data = {...data, loading: true, error: ''}; if (!preserveRange) emit();
    const sameScope = () => ticket === epoch && uid === owner() && view === context();
    const valid = () => sameScope() && canApply();
    const work = (async () => {
      let committed = false, deferredByGate = false;
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
          if (!sameScope()) return null;
          if (!Array.isArray(result.items) || !Number.isFinite(result.total)) throw Error('列表响应不完整，请重试。');
          if (!canApply()) { deferredByGate = true; return null; }
          for (const item of result.items) records.set(item.id, item);
          if (!preserveRange || records.size >= target || !result.has_more) break;
          if (!result.next_cursor || cursors.has(result.next_cursor) || !result.items.length) throw Error('列表分页信息已变化，请稍后重试。');
          cursors.add(result.next_cursor); params.set('cursor', result.next_cursor);
        }
        const items = [...records.values()];
        const unchanged = preserveRange && equal(data.items, items) && data.total === result.total && data.has_more === result.has_more && !previousError;
        data = {...data, ...result, items, loaded: true, loading: false, error: '',
          notice: refreshed ? '列表已有更新，已保留筛选与已加载范围，并重新读取后续记录。' : data.notice};
        dataRevision = append ? prefixRevision : requestedRevision;
        verifiedInvalidation = append ? prefixInvalidation : requestedInvalidation;
        committed = true;
        if (!unchanged) emit({preserveViewport: preserveRange}); return snapshot();
      } catch (error) {
        if (!sameScope()) return null;
        const apply = canApply();
        if (append && apply && error.status === 409 && error.detail?.code === 'list_changed') {
          return request(false, true, {preserveRange:true,targetSize:data.items.length+limit,canApply,equal});
        }
        if (error.name !== 'AbortError') data = {...data, loading: false, error: error.message || '列表暂时无法读取。'};
        else data = {...data, loading: false};
        if (apply) emit({preserveViewport: preserveRange}); return null;
      } finally {
        if (ticket === epoch) {
          pending = null; if (data.loading) data = {...data, loading: false};
          // An interaction can block a background paint without invalidating
          // the user's queued request. It runs with its own scope and gate.
          // Real failures or a changed owner/view/filter never release it.
          if (committed && queuedMore && moreScopeMatches(queuedMore) &&
              (append || data.items.length >= queuedMore.targetSize || !data.has_more)) finishMore(queuedMore, snapshot());
          else if (committed || deferredByGate) scheduleMore(); else cancelMore();
        }
      }
    })();
    pending = work; return work;
  }
  function load(values = filters, {force = false, preserveRange = false, canApply, equal} = {}) {
    if (account !== owner()) clear();
    const normalized = normalize(values), nextKey = JSON.stringify(normalized), outdated = stale();
    const pendingCurrent = requestView === context() && requestMode?.invalidation === invalidation && requestMode?.revision === revision();
    if (queuedMore && (!moreScopeMatches(queuedMore) || nextKey !== key)) cancelMore();
    if (!force && nextKey === key) {
      if (data.loading && pending) return requestView === context() && pendingCurrent ? pending : request(false, false, {preserveRange:outdated,canApply,equal});
      if (data.loaded && !outdated) { requestView = context(); return Promise.resolve(snapshot()); }
    }
    preserveRange = (preserveRange || outdated) && nextKey === key && data.loaded && (requestView === context() || outdated);
    if (preserveRange && data.loading && pending && pendingCurrent) return pending;
    if (nextKey !== key) { data = empty(); dataRevision = null; }
    filters = normalized; key = nextKey;
    return request(false, false, {preserveRange, canApply, equal});
  }
  function more() {
    if (account !== owner()) { clear(); emit(); return Promise.resolve(null); }
    if (queuedMore) { if (moreScopeMatches(queuedMore)) return queuedMore.promise; cancelMore(); }
    if (data.loading) {
      if (data.loaded && data.has_more && requestView === context() && requestMode?.preserveRange && !requestMode.append) return queueMore();
      return pending || Promise.resolve(null);
    }
    if (!stale() && (!data.has_more || !data.next_cursor)) return Promise.resolve(snapshot());
    const promise = queueMore(); startMore(queuedMore, true); return promise;
  }
  function patch(mapper, {canApply = () => true, equal = (a,b) => JSON.stringify(a) === JSON.stringify(b)} = {}) {
    if (account !== owner() || requestView !== context() || !data.loaded || data.loading || !canApply()) return null;
    const items = data.items.map(mapper), changed = !equal(data.items, items);
    data = {...data, items}; if (changed) emit({preserveViewport:true});
    return snapshot();
  }
  return {load, more, clear, invalidate, snapshot, patch, reload: options => load(filters, {...options, force: true})};
}
