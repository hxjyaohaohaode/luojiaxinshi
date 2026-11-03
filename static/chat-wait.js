// Shown only after the server has accepted an assistant turn. StreamJob keeps
// that turn running when the browser leaves; reconnecting reads the saved turn.
export function replyWaitHint(message) {
  if (message?.role !== 'assistant' || message.status !== 'processing') return '';
  const steps = message._work || message.grounding?.steps || [];
  const stage = message._phase || [...steps].reverse().find(step => step.state === 'running')?.stage;
  const text = {
    accepted: '正在准备回复，请稍候。',
    planning: '正在核对信息，请稍候。',
    retrieving: '正在查找相关资料，请稍候。',
    searching: '正在查找相关资料，请稍候。',
    writing: '正在整理回复，请稍候。',
    composing: '正在整理回复，请稍候。',
    verifying: '正在核对回复依据，请稍候。',
  }[stage] || '回复仍在处理中，请稍候。';
  return text + '可先切换页面，后台会继续处理。';
}
