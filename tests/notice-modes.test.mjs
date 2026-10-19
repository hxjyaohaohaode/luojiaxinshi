import test from 'node:test';
import assert from 'node:assert/strict';
import {noticeModePicker,updateNoticeMode} from '../static/notice-modes.js';
const esc=v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const ai={notice_modes:[{id:'configured',label:'当前配置',description:'沿用配置'},{id:'fast',label:'速度优先',description:'加速但保留复核',price_note:'费用较高',price_source:'https://mimo.mi.com'}]};

test('older or unsupported servers do not offer an unavailable paid mode',()=>{
 assert.equal(noticeModePicker({},esc),'');assert.equal(noticeModePicker({notice_modes:[ai.notice_modes[0]]},esc),'');
 assert.match(noticeModePicker(ai,esc),/id="notice-processing-mode"/);
});

test('changing cost profile clears prior consent and exposes the matching cost note',()=>{
 const fields={'#notice-processing-mode':{value:'fast'},'#notice-mode-description':{},'[data-notice-mode-cost]':{},'[data-notice-mode-price]':{},'[data-notice-mode-price-link]':{},'#ai-consent':{checked:true}};
 const root={querySelector:name=>fields[name]};updateNoticeMode(root,ai);
 assert.equal(fields['#ai-consent'].checked,false);assert.equal(fields['[data-notice-mode-cost]'].hidden,false);assert.equal(fields['[data-notice-mode-cost]'].open,true);
 assert.equal(fields['[data-notice-mode-price]'].textContent,'费用较高');
 fields['#notice-processing-mode'].value='configured';fields['#ai-consent'].checked=true;updateNoticeMode(root,ai);
 assert.equal(fields['#ai-consent'].checked,false);assert.equal(fields['[data-notice-mode-cost]'].hidden,true);assert.equal(fields['[data-notice-mode-price]'].textContent,'');
});
