import assert from 'node:assert/strict';

// Exercise the same native disclosure a reader uses. Reply actions intentionally
// live inside this menu; hidden descendants are not directly clickable targets.
export async function openReplyMenu(reply) {
  const menu=reply.locator('.reply-more');
  assert.equal(await menu.count(),1,'The reply has one more-actions disclosure');
  if(await menu.getAttribute('open')===null)await menu.locator(':scope > summary').click();
  await menu.locator('.reply-tools').waitFor({state:'visible'});
}
