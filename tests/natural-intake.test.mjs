import test from 'node:test';
import assert from 'node:assert/strict';
import {batchEntry,validateEntry,prepareEntry} from '../static/notice-intake.js';
import {filterNotices} from '../static/library.js';
import {searchRecords,highlightMatch} from '../static/command-search.js';
import {noticeSearchExcerpt} from '../static/notice-search.js';

test('untitled body and file intake preserve the input for server title inference',()=>{
  const body={...batchEntry(),body:'关于申领奖学金的通知'};
  const fd=prepareEntry(body,[],x=>x);assert.equal(fd.get('title'),'');assert.equal(fd.get('body'),body.body);
  const file=new File(['证明材料要求'],'通知原件.txt',{type:'text/plain'});
  assert.equal(prepareEntry(batchEntry(),[file],x=>x).getAll('files').length,1);
  assert.throws(()=>prepareEntry(batchEntry(),[],x=>x),/请添加/);
});

test('personal inbox next-action filters keep records distinct from model relevance',()=>{
  const items=[{id:'a',intent:'act',status:'confirmed',created_at:1},{id:'b',intent:'verify',status:'received',created_at:1},{id:'c',intent:'followup',status:'confirmed',created_at:1}];
  assert.deepEqual(filterNotices(items,{intent:'followup'}).map(n=>n.id),['c']);
  assert.deepEqual(filterNotices(items,{intent:'verify',status:'received'}).map(n=>n.id),['b']);
  assert.equal(filterNotices(items,{intent:'act',status:'received'}).length,0);
  assert.equal(items.length,3);
});

test('a pasted URL is locally acceptable but cannot submit without fetched content',()=>{
  const entry={...batchEntry(),read_url:'https://notice.example/one'};
  assert.doesNotThrow(()=>validateEntry(entry,[]));
  assert.throws(()=>prepareEntry(entry,[],x=>x),/尚未读取/);
  const ready=prepareEntry({...entry,link_preview:'stored-preview'},[],x=>x);
  assert.equal(ready.get('link_preview'),'stored-preview');assert.equal(ready.has('read_url'),false);
});

test('notice search finds original body and active attachment content beyond list metadata',()=>{
  const notice={id:'n1',title:'申请',source_label:'学院',created_at:1,status:'received',sources:[
    {name:'原件.txt',active:true,sections:[{text:'电子版发送至材料专用邮箱。'}]},
    {name:'旧说明.txt',active:false,sections:[{text:'过期收件方式'}]},
  ]};
  assert.equal(filterNotices([notice],{query:'专用邮箱'}).length,1);
  assert.equal(searchRecords([], [notice],'专用邮箱').notices.length,1);
  assert.equal(filterNotices([notice],{query:'过期收件'}).length,0);
  assert.match(noticeSearchExcerpt(notice,'专用邮箱'),/专用邮箱/);
});

test('server matches survive snippet truncation and snippets remain escaped text',()=>{
  const notice={id:'n2',title:'报名',search_snippet:'<img src=x onerror=alert(1)>材料',search_source:'附件.pdf'};
  const found=searchRecords([], [notice],'在原件更后面出现的词',{noticeMatches:true});
  assert.equal(found.notices.length,1);
  const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  const html=highlightMatch(found.notices[0].excerpt,'材料',esc);
  assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img/);assert.match(html,/<mark>材料<\/mark>/);
});

test('a separate semester is explicit and never applies to a supplement',()=>{
  const entry={...batchEntry(),body:'相同的通知正文'};
  assert.equal(prepareEntry(entry,[],x=>x).has('allow_duplicate'),false);
  entry.allow_duplicate=true;assert.equal(prepareEntry(entry,[],x=>x).get('allow_duplicate'),'true');
  entry.target='existing';entry.target_version=2;assert.equal(prepareEntry(entry,[],x=>x).has('allow_duplicate'),false);
});
