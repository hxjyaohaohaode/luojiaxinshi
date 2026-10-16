import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMessage,resolve,blockMarkdown,StateStore} from '../static/genui/core.js';
import {SCENARIOS} from '../static/genui/scenarios.js';

const specFor=name=>parseMessage('```genui\n'+SCENARIOS[name].ops.map(v=>JSON.stringify(v)).join('\n')+'\n```')[0].spec;

test('nullable answers accept only declared primitive choices without relaxing ordinary state types',()=>{
  const store=new StateStore({answer:null,hours:2});assert.throws(()=>store.set('answer','b'),/state_type_changed/);
  store.set('answer','b',{choices:['a','b']});assert.equal(store.get('answer'),'b');
  assert.throws(()=>store.set('answer','unknown',{choices:['a','b']}),/invalid_choice_value/);
  assert.throws(()=>store.set('hours','2'),/state_type_changed/);assert.throws(()=>store.set('answer',{}, {choices:['a','b']}),/invalid_choice_value/);
  store.set('answer',null,{choices:['a','b']});assert.equal(store.get('answer'),null);
});

test('qualitative compositions validate and retain their registered evidence',()=>{
  for(const name of ['news','brief','notice']){
    const spec=specFor(name);assert.equal(spec.complete,true);assert.deepEqual(spec.errors,[]);
    const scene=SCENARIOS[name];for(const citation of scene.citations){const source=scene.evidence_sources.find(s=>s.id===citation.source_id);assert.ok(source?.preview.includes(citation.quote));}
  }
});

test('reading focus changes comparison dimensions without changing the source records',()=>{
  const spec=specFor('news'),matrix=spec.nodes.matrix.props,original=JSON.stringify(spec.state.reports);
  const borders=resolve(matrix,{...spec.state,focus:'difference'},{}),facts=resolve(matrix,{...spec.state,focus:'confirmed'},{});
  assert.deepEqual(borders.dimensions,['表达的性质','解释不能越过']);assert.deepEqual(facts.dimensions,['已经明确','并未明确']);
  assert.equal(JSON.stringify(spec.state.reports),original);assert.deepEqual(borders.items,facts.items);
});

test('personalized briefs and exercise feedback export the current visible state',()=>{
  const brief=specFor('brief'),organizer=blockMarkdown(brief,{...brief.state,audience:'organizer'});
  assert.match(organizer,/向同伴转发时/);assert.doesNotMatch(organizer,/起草一页问题说明/);
  const notice=specFor('notice'),state={...notice.state,exercise:{answer:'b',revealed:false}};
  assert.doesNotMatch(blockMarkdown(notice,state),/这个判断守住了原文边界/);
  state.exercise.revealed=true;assert.match(blockMarkdown(notice,state),/这个判断守住了原文边界/);
  const quote=specFor('brief');assert.match(blockMarkdown(quote,{...quote.state,depth:1}),/> 本次工作坊/);assert.match(blockMarkdown(quote,{...quote.state,depth:1}),/原文节选 \[1\]/);
});
