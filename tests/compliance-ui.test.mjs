import test from 'node:test';
import assert from 'node:assert/strict';
import {legalMarkup} from '../static/legal.js';
import {filterNotices} from '../static/library.js';

const esc = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const info = {version: '2026-10-23-r2', operator_name: '合成团队<script>', operator_contact: '', model_provider: '小米 MiMo', backup_retention_days: 9};

test('privacy policy names the AI provider, excluded fields, retention and deletion path', () => {
  const html = legalMarkup('privacy', info, esc);
  assert.match(html, /小米 MiMo/);
  assert.match(html, /个人资料字段中的手机号、微信号、QQ 号、学号、工号/);
  assert.match(html, /仍可能随相关内容发送/);
  assert.match(html, /录音会发送给语音识别服务/);
  assert.match(html, /清理超过 9 天的自动备份/);
  assert.match(html, /停机期间需等服务恢复/);
  assert.match(html, /手动备份由部署管理员/);
  assert.match(html, /修订 2/);
  assert.match(html, /注销账号/);
  assert.match(html, /不是学校官方系统/);
  assert.match(html, /AI 生成/);
  assert.ok(!html.includes('<script>'), 'operator name must be escaped');
  assert.match(html, /部署管理员公布的联系方式/);
});

test('terms say AI output is for reference and the official notice prevails', () => {
  const html = legalMarkup('terms', {...info, operator_contact: 'team@example.edu'}, esc);
  assert.match(html, /仅供参考/);
  assert.match(html, /以发布单位的正式通知为准/);
  assert.match(html, /team@example\.edu/);
  assert.match(html, /aria-current="page">用户协议/);
});

test('notice library can be filtered by relevance to the student', () => {
  const now = Date.UTC(2026, 9, 22) / 1000;
  const items = [
    {title: '奖学金申请', source_label: '学院', status: 'draft', created_at: now, applicability: 'matches_known'},
    {title: '研究生开题', source_label: '研究生院', status: 'draft', created_at: now, applicability: 'not_matching'},
    {title: '新收通知', source_label: '群', status: 'received', created_at: now, applicability: null},
  ];
  assert.deepEqual(filterNotices(items, {relevance: 'matches_known'}).map(n => n.title), ['奖学金申请']);
  assert.deepEqual(filterNotices(items, {relevance: 'unknown'}).map(n => n.title), ['新收通知']);
  assert.equal(filterNotices(items, {relevance: 'all'}).length, 3);
  assert.deepEqual(filterNotices(items, {relevance: 'not_matching', query: '开题'}).map(n => n.title), ['研究生开题']);
});
