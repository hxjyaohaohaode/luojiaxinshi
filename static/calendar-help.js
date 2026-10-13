export function calendarHelp(){
  return `<details class="calendar-guide">
    <summary>第一次导入？按你使用的日历查看方法</summary>
    <div class="calendar-guide-body">
      <p class="small muted">电脑、手机和平板可以使用同一份日历文件。本机运行时先在电脑下载；部署到服务器后，可在其他设备登录工作台下载。</p>
      <div class="calendar-guide-options">
        <details><summary>苹果 · Mac / iPhone / iPad</summary>
          <p>有 Mac 时，在“日历”中选择“文件 → 导入”，将下载的 .ics 文件导入自己的 iCloud 日历，再到使用同一账户的 iPhone 或 iPad 核对事件。</p>
          <p>只用手机时，如果打开文件后出现日历添加入口，按设备提示导入；如果只能预览文件，请使用下方的手动添加方式。</p>
          <a href="https://support.apple.com/zh-cn/guide/calendar/-icl1023/mac" target="_blank" rel="noopener noreferrer">Apple 官方导入说明 ↗</a>
        </details>
        <details><summary>Google 日历 · 电脑导入后同步</summary>
          <p>在电脑浏览器打开 Google 日历，进入“设置 → 导入和导出”，选择 .ics 文件与目标日历。随后在手机的同一账户中检查事件是否出现。</p>
          <a href="https://support.google.com/calendar/answer/37118?hl=zh-Hans" target="_blank" rel="noopener noreferrer">Google 官方导入说明 ↗</a>
        </details>
        <details><summary>Outlook · Windows / 网页 / 手机</summary>
          <p>在 Outlook 网页日历选择“添加日历 → 从文件上传”，选择 .ics 文件及目标日历后导入。使用手机时，在同一账户中核对同步结果。</p>
          <a href="https://support.microsoft.com/en-us/outlook/import-or-subscribe-to-a-calendar-in-outlook-com-or-outlook-on-the-web" target="_blank" rel="noopener noreferrer">Microsoft 官方导入说明 ↗</a>
        </details>
        <details><summary>安卓、鸿蒙或其他日历 · 无法导入时</summary>
          <p>各品牌和版本的文件导入入口不同。如果日历支持 .ics，可在下载文件的打开方式或日历设置中导入。</p>
          <p>找不到入口也没关系：打开工作台里的对应待办，对照标题、正式期限、个人计划和提醒时间，在自己常用的日历中手动新建一项。日期不确定时先核实，不要补一个猜测的时刻。</p>
        </details>
      </div>
      <div class="calendar-check"><strong>留两分钟，确认提醒真的能响</strong><p>先用一项明确标注的测试日程，把提醒设在几分钟后；核对时间和通知权限，关闭页面并锁屏等待。收到提醒后再使用重要事项。未收到时，请检查日历内的提醒设置、系统通知和专注／省电设置。</p><p>改期或取消后，也要在外部日历处理旧事件。重复导入前先检查旧事件，避免重复提醒。</p></div>
    </div>
  </details>`;
}
