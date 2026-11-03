export function createSystemHome({state,api,esc,icon}) {
  return {async render(id=state.renderId){
    const [stats,channels,runtime]=await Promise.all([api('/admin/insights'),api('/integrations'),api('/admin/runtime')]);
    if(id!==state.renderId)return;
    const service=state.session.ai;
    document.querySelector('#content').innerHTML=`<section class="role-home" data-home-context="system">
      <header class="home-heading"><div><h1>系统维护</h1><p>账号访问、学院权限与运行配置</p></div><a class="button small" href="#campus/members">${icon('shield')} 管理权限</a></header>
      <div class="home-counts" aria-label="全站匿名统计"><span>账号 <b>${Number(stats.users.total)}</b></span><span>近七天活跃 <b>${Number(stats.users.active_7d)}</b></span><span>通知 <b>${Number(stats.notices.total)}</b></span></div>
      <div class="home-columns"><section class="home-section"><div class="home-section-heading"><h2>运行配置</h2><button class="button small plain" data-action="settings-model">模型与记录 ${icon('arrow')}</button></div><dl class="service-status-list">
        <div><dt>AI 模型</dt><dd>${esc(service.model)} · ${service.configured?'已配置':'未配置'}</dd></div>
        <div><dt>短信验证码</dt><dd>${runtime.configuration.sms_verification?'已配置，待实际送达核验':'未配置'}</dd></div>
        <div><dt>邮件发送</dt><dd>${runtime.configuration.email?'已配置，待实际送达核验':'未配置'}</dd></div>
        <div><dt>后台处理</dt><dd>${runtime.worker_observation==='started'?`${Object.values(runtime.workers).filter(s=>s==='running').length} / ${Object.keys(runtime.workers).length} 项任务运行中`:'尚未观察到任务启动'}</dd></div>
        <div><dt>自动整理</dt><dd>${Number(runtime.analysis.jobs.queued||0)} 等待 · ${Number(runtime.analysis.jobs.running||0)} 处理中 · ${Number(runtime.analysis.jobs.failed||0)} 失败待核对</dd></div>
        <div><dt>访问环境</dt><dd>${runtime.configuration.public_https&&runtime.configuration.production?'公网 HTTPS 配置':'本机或非生产配置'}</dd></div>
        <div><dt>QQ 消息接入</dt><dd>${channels.qq.configured?'已配置':'未配置'}</dd></div>
        <div><dt>自有公众号接口</dt><dd>${channels.wechat_publisher.configured?'已配置':'未配置'}</dd></div>
        <div><dt>学校统一认证</dt><dd>等待学校授权</dd></div>
      </dl><p class="small muted">${esc(runtime.note)}</p></section>
      <section class="home-section"><h2>需要关注</h2><div class="home-link-list"><button data-action="settings-model"><span>近 30 天 AI 调用失败</span><b>${Number(stats.ai_30d.failed)}</b>${icon('arrow')}</button><a href="#campus/members"><span>学院身份与负责范围</span>${icon('arrow')}</a><a href="#campus/audit"><span>权限调整记录</span>${icon('arrow')}</a></div><p class="small muted">这里只展示匿名计数。切换至“我的事务”可查看自己的通知和办理记录。</p></section></div>
      <details class="system-statistics"><summary>查看全站匿名统计</summary><dl class="service-status-list"><div><dt>通知</dt><dd>共 ${Number(stats.notices.total)} · 近 30 天 ${Number(stats.notices.last_30d)} · 已确认办理路径 ${Number(stats.notices.confirmed)}</dd></div><div><dt>待办</dt><dd>${Number(stats.tasks.pending)} 待完成 · ${Number(stats.tasks.done)} 已完成 · ${Number(stats.tasks.cancelled)} 已取消</dd></div><div><dt>近 30 天 AI 调用</dt><dd>${Number(stats.ai_30d.calls)} 次 · 失败 ${Number(stats.ai_30d.failed)} 次</dd></div></dl></details>
    </section>`;
  }};
}
