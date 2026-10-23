// 隐私政策与用户协议。内容与系统实际行为保持一致：改动数据处理方式时同步修改这里，并更新后端 POLICY_VERSION。
const date = version => version ? version.replace(/^(\d{4})-(\d{2})-(\d{2})(?:-r(\d+))?$/, (_,y,m,d,r) => `${y} 年 ${m} 月 ${d} 日${r ? `（修订 ${r}）` : ''}`) : '';

function privacy(info, esc) {
  const contact = info.operator_contact ? esc(info.operator_contact) : '部署管理员公布的联系方式';
  return `
  <section><h2>一、我们是谁</h2>
  <p>珞珈信使是一个帮助同学整理校园通知、安排待办的学生项目，由 <strong>${esc(info.operator_name || '珞珈信使项目团队')}</strong> 开发和维护，参加武汉大学“数智珞珈·青春揭榜”AI 应用场景设计大赛。它不是学校官方系统，不代替学校发布或解释通知，一切以发布单位的正式通知为准。</p>
  <p>对本政策或你的个人信息有任何疑问，可以通过 ${contact} 联系我们。</p></section>

  <section><h2>二、我们会处理哪些信息</h2>
  <ul>
    <li><strong>账号信息</strong>：账号名、称呼、密码（只保存不可还原的加密摘要）、校园角色。</li>
    <li><strong>你主动填写的个人条件</strong>：学校、学院、专业、年级、校区、学期等，用来判断哪条通知和你有关。学号、工号、手机号、微信号、QQ 号都是选填，只保存在你的账号里。</li>
    <li><strong>你提交的内容</strong>：通知正文、附件、截图、对话、录音转写、待办、日程和记忆。</li>
    <li><strong>使用记录</strong>：修改历史、AI 处理状态与用量，用来让你回看和排查问题。</li>
  </ul>
  <p>我们不读取你的微信、QQ 聊天记录或手机通讯录，也不会自动登录任何校园系统。</p></section>

  <section><h2>三、这些信息怎么用</h2>
  <ul>
    <li>保存、整理你的通知，生成待办、提醒和个人看板。</li>
    <li>在你点击“AI 整理”或在对话中发送消息并同意后，把<strong>本次需要的内容</strong>发送给 AI 服务处理。</li>
    <li>保障账号安全，例如登录限流和异常排查。</li>
  </ul>
  <p>我们不会把你的信息用于广告，不会出售，也不会用来训练模型。</p></section>

  <section><h2>四、发送给第三方 AI 服务</h2>
  <p>本站的 AI 能力由 <strong>${esc(info.model_provider || '小米 MiMo')}</strong> 提供。只有在你明确同意时，系统才会把本次处理需要的通知、对话、附件、相关记忆和个人条件（如学院、年级）发给它。系统不会把个人资料字段中的手机号、微信号、QQ 号、学号、工号或账号密码自动加入模型请求。<strong>如果你自己把这些信息写进通知、对话、附件或记忆，它们仍可能随相关内容发送；发送前请自行检查。</strong></p>
  <p>使用语音输入时，你提交的录音会发送给语音识别服务；使用 AI 朗读时，选中的文字会发送给语音合成服务。</p>
  <p>每次整理通知都需要单独勾选同意；对话的授权可以随时在输入框的更多选项里撤回。AI 服务方按其自身的隐私政策处理收到的数据。</p></section>

  <section><h2>五、AI 生成内容的标识</h2>
  <p>由 AI 生成或整理的文字、草稿、图表和合成语音，都会在界面上标注“AI 生成”。AI 可能出错，<strong>重要的时间、资格和材料要求请以学校正式通知为准</strong>，并对照原文核实。草稿只有经过你确认才会变成待办。</p></section>

  <section><h2>六、保存与删除</h2>
  <ul>
    <li>你的数据保存在本服务部署方的服务器上，每个账号只能看到自己的资料。</li>
    <li>你可以随时导出个人数据，删除单条通知、对话、待办或记忆。</li>
    <li>你可以在“个人与账号 → 账号安全”中<strong>注销账号</strong>：删除当前服务中的账号和个人数据。已有备份不会立即改写；系统运行时会清理超过 ${Number(info.backup_retention_days) || 7} 天的自动备份，停机期间需等服务恢复后执行。手动备份由部署管理员另行保管和清理，可通过上述联系方式申请处理。</li>
  </ul></section>

  <section><h2>七、你的权利</h2>
  <p>你有权查阅、复制、更正、删除你的个人信息，撤回对 AI 处理的同意，以及注销账号。大部分操作可以直接在应用内完成；其他请求可以联系我们，我们会在 15 个工作日内答复。</p></section>

  <section><h2>八、未成年人</h2>
  <p>本服务面向在校大学生、研究生和教职工。如果你未满 14 周岁，请在监护人同意并陪同下使用。</p></section>

  <section><h2>九、政策更新</h2>
  <p>政策更新后，可在登录页底部或“个人与账号”中查看最新内容。已有同意记录会保留，登录和切换页面时不会弹窗要求重复确认。</p></section>`;
}

function terms(info, esc) {
  return `
  <section><h2>一、服务内容</h2>
  <p>珞珈信使帮助你把校园通知整理成待办：保存原文、提取时间和材料、提醒期限、记录办理进度，并提供 AI 对话助手。它是辅助工具，不代表学校，也不替你向学校提交任何材料。</p></section>

  <section><h2>二、关于 AI</h2>
  <ul>
    <li>AI 生成的内容可能不准确或不完整，仅供参考。请以发布单位的正式通知为准，对照原文核实关键信息。</li>
    <li>待办、期限和提醒以你确认保存的内容为准；“标记完成”只是你自己的记录，不代表学校已受理。</li>
    <li>请不要用本服务生成违法、侵权或误导他人的内容。</li>
  </ul></section>

  <section><h2>三、账号与安全</h2>
  <ul>
    <li>请为本服务单独设置密码，并妥善保存注册时显示的恢复码。</li>
    <li>学号、工号、手机号作为账号名时只是你自己的填写，不等同于学校或运营商认证。</li>
    <li>不得冒用他人身份，不得尝试访问他人的数据或干扰服务运行。</li>
  </ul></section>

  <section><h2>四、你上传的内容</h2>
  <p>你对上传的通知、附件和其他资料负责，请确保有权保存和使用它们。内容的权利仍归原作者或发布单位所有，我们只为向你提供服务而处理。</p></section>

  <section><h2>五、提醒与日历</h2>
  <p>站内提醒在页面打开时出现；导出的日历文件需要你导入手机或电脑日历，提醒能否送达取决于设备设置。重要期限请自己再确认一遍。</p></section>

  <section><h2>六、服务变更与终止</h2>
  <p>这是学生团队的竞赛项目，可能会调整功能或暂停服务。我们会尽量提前告知，并保证你可以导出自己的数据。你可以随时注销账号。</p></section>

  <section><h2>七、其他</h2>
  <p>个人信息的处理规则见《隐私政策》。对本协议有疑问，可以联系 ${esc(info.operator_name || '珞珈信使项目团队')}${info.operator_contact ? '（' + esc(info.operator_contact) + '）' : ''}。</p></section>`;
}

export function legalMarkup(kind, info, esc) {
  const title = kind === 'terms' ? '用户协议' : '隐私政策';
  return `<article class="legal-page">
    <header class="legal-head"><span class="legal-kicker">珞珈信使</span><h1>${title}</h1><p>版本 ${esc(date(info.version))}</p>
    <nav class="legal-switch" aria-label="协议切换"><a href="#privacy" ${kind !== 'terms' ? 'aria-current="page"' : ''}>隐私政策</a><a href="#terms" ${kind === 'terms' ? 'aria-current="page"' : ''}>用户协议</a></nav></header>
    <div class="legal-body">${kind === 'terms' ? terms(info, esc) : privacy(info, esc)}</div>
  </article>`;
}
