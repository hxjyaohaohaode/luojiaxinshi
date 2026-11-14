import {createDraftStore} from './continuity.js';

const KEY = 'campus-publication';
const FORMAT = 'campus-publication-v1';

// The confirmed request is durable before it can publish. A transport failure
// never turns new editor input into a second publication: recover the original
// request ID first, even when publishing already deleted its server draft.
export function createCampusPublicationSubmission({api, owner}) {
  let account, cache, flight;
  function current() {
    if (!cache || account !== owner()) {
      cache?.clear(); account = owner(); const boundOwner = account;
      cache = createDraftStore((path, options) => {
        if (!boundOwner || owner() !== boundOwner) throw Error('账号已变化，请重新打开发布页面。');
        return api(path, options);
      });
    }
    return cache;
  }
  function pending() {
    const entry = current().peek(KEY);
    return !entry.retired && entry.payload?.format === FORMAT ? structuredClone(entry.payload) : null;
  }
  async function load() {
    const store = current(), uid = account;
    await store.load(KEY);
    return store === cache && uid === owner() ? pending() : null;
  }
  async function prepare(payload, draft) {
    const store = current(), uid = account;
    const previous = await load();
    if (store !== cache || uid !== owner()) return null;
    if (previous) {
      if (previous.payload.request_id !== payload.request_id) throw Error('上一次发布结果尚未核对，请先重试上次确认的发布；本次输入仍保留为草稿。');
      const keys = new Set([...Object.keys(previous.payload), ...Object.keys(payload)]);
      if ([...keys].some(key => JSON.stringify(previous.payload[key]) !== JSON.stringify(payload[key]))) throw Error('本次输入与上次确认的发布内容不同，不能替换原发布；新输入仍保留为草稿。');
      await store.flush(KEY);
      return store === cache && uid === owner() ? pending() : null;
    }
    if (store.peek(KEY).retired) store.activate(KEY);
    store.stage(KEY, {format:FORMAT, payload:structuredClone(payload), draft:structuredClone(draft)});
    await store.flush(KEY);
    return store === cache && uid === owner() ? pending() : null;
  }
  async function performReplay({audienceReview,canSend=()=>true} = {}) {
    const store = current(), uid = account;
    let intent = await load();
    if (!intent || store !== cache || uid !== owner()) return null;
    if (audienceReview) {
      // This is the only mutable part of a replay: the backend explicitly
      // excludes the renewed audience token from its request-content digest.
      intent = {...intent, payload:{...intent.payload, audience_review:audienceReview}};
      store.stage(KEY, intent);
    }
    await store.flush(KEY);
    if (store !== cache || uid !== owner() || !canSend()) return null;
    const ticket = store.checkpoint(KEY), body = new FormData();
    body.append('data', JSON.stringify(intent.payload));
    const result = await api('/campus/publications', {method:'POST', body});
    if (store !== cache || uid !== owner()) return {result, intent, current:false};
    let cleanupError = null;
    try { await store.retire(KEY, ticket); } catch (error) { cleanupError = error.message; }
    return {result, intent, current:store === cache && uid === owner(), cleanupError};
  }
  function replay(options){
    const store=current();if(flight?.store===store)return flight.promise;
    const request={store,promise:null};request.promise=performReplay(options).finally(()=>{if(flight===request)flight=null;});flight=request;return request.promise;
  }
  async function cancel({canSend=()=>true}={}){
    const store=current(),uid=account,intent=await load();
    if(!intent||store!==cache||uid!==owner()||!canSend())return null;
    const ticket=store.checkpoint(KEY),outcome=await api('/campus/submissions/'+encodeURIComponent(intent.payload.request_id)+'/cancel',{method:'POST'});
    if(store!==cache||uid!==owner())return {...outcome,intent,current:false};
    if(!['published','cancelled'].includes(outcome.state))throw Error('未能确认停止结果，请重试；上次发布仍保留待核对。');
    let cleanupError=null;try{await store.retire(KEY,ticket);}catch(error){cleanupError=error.message;}
    // The minimal receipt is authoritative even after the author has moved to
    // another college and can no longer read the old publication's details.
    let result=null,detailError=null;
    if(outcome.state==='published'&&store===cache&&uid===owner())try{result=await api('/campus/publications/'+encodeURIComponent(outcome.publication_id));}catch(error){detailError={status:error.status,message:error.message};}
    return {...outcome,intent,result,detailError,cleanupError,current:store===cache&&uid===owner()};
  }
  return {load, pending, prepare, replay, cancel, clear(){cache?.clear();cache=null;account=undefined;flight=null;}};
}
