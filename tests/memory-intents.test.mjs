import test from 'node:test';
import assert from 'node:assert/strict';
import {createMemoryIntents} from '../static/memory-intents.js';

test('retry preserves the same write intent, while edits and accounts get new intents',async()=>{
  const intents=createMemoryIntents();
  const first=await intents.headers('alice','update:a',{content:'本人条件',version:1});
  assert.deepEqual(await intents.headers('alice','update:a',{version:1,content:'本人条件'}),first);
  assert.notDeepEqual(await intents.headers('alice','update:a',{content:'修订条件',version:1}),first);
  assert.notDeepEqual(await intents.headers('bob','update:a',{content:'本人条件',version:1}),first);
  assert.notDeepEqual(await intents.headers('alice','update:a',{content:'本人条件',version:1}),first);
  assert.match(first['Idempotency-Key'],/^[a-f\d-]{36}$/);
});
