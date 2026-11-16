import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceCategory} from '../static/source-categories.js';
import {isSchoolOfficial,schoolSourcePresentation} from '../static/source-presentation.js';

test('official and custom sources are grouped without a model',()=>{
  for(const [data,preset,category] of [
    [{name:'武汉大学通知公告'},{id:'whu-notices'},'学校公告'],
    [{name:'本科生院教务安排'},{id:'whu-undergrad-teaching'},'教务教学'],
    [{name:'学生资助通知公告'},{id:'whu-student-aid'},'资助奖助'],
    [{name:'校园宣讲会'},{id:'whu-employment-fairs'},'就业招聘'],
    [{name:'第一临床学院研究生招生'},{id:'whu-college-rmhospital'},'学院通知'],
    [{name:'武汉大学图书馆通知公告'},{id:'whu-library-notices'},'图书馆'],
    [{name:'自定义来源',platform:'qq_group'},{},'群聊与公众号'],
    [{name:'自定义',category:'校园服务'},{id:'whu-notices'},'校园服务'],
  ])assert.equal(sourceCategory(data,preset),category);
});

test('received original files are not described as collection errors',()=>{
  const base='https://future.whu.edu.cn/info/1.htm';
  assert.equal(isSchoolOfficial(base),true);
  assert.equal(isSchoolOfficial('https://fake-whu.edu.cn/info/1.htm'),false);
  assert.equal(isSchoolOfficial('javascript:alert(1)'),false);
  const attachment=schoolSourcePresentation({kind:'docx',status:'review',warning:'表格需复核',origin:{url:base}});
  assert.equal(attachment.state,'原件已接收');assert.equal(attachment.note,'');
  const failed=schoolSourcePresentation({kind:'pdf',status:'failed',origin:{url:base}});
  assert.equal(failed.state,'原件已收 · 文字未提取');
  const missing=schoolSourcePresentation({kind:'text',status:'ok',origin:{url:base,attachments:['https://future.whu.edu.cn/one.pdf'],received_attachments:[]}});
  assert.match(missing.note,/附件尚未接收/);
  const link=schoolSourcePresentation({kind:'text',status:'review',origin:{url:base,list_only:true}});
  assert.equal(link.state,'原文链接');assert.match(link.note,/正文与附件请在原文查看/);
  assert.equal(schoolSourcePresentation({kind:'text',status:'review',origin:{url:'https://example.org'}}),null);
});
