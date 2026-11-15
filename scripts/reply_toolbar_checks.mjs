import assert from 'node:assert/strict';

export async function waitForReplyTools(reply) {
  const tools=reply.locator('.message-footer > .reply-tools');
  await tools.waitFor({state:'visible'});
  assert.equal(await tools.count(),1,'The reply has one inline group of tools');
}
