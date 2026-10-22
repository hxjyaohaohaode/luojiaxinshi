# 视觉复核证据

应用源码提交：`c77a94669a46b1f737c6cbe7f67c973b786e91c3`。本地独立合成环境：五组浏览器检查 **477/477**，Node **136/136**，无失败、跳过或页面脚本错误。公开文件不包含真实账号数据、Cookie、日志环境变量或服务凭据。

截图为实际浏览器渲染，使用合成通知和记忆。截图不是设计稿；边界断言和测试数量也不代表美观程度已经得到用户认可。参考读取范围、发现的问题、修正和限制见 [视觉复核记录](../../REFERENCE_VISUAL_REVIEW.md)。

| 场景 | 截图 |
| --- | --- |
| 工作台，1413 px | [查看](screenshots/dashboard-1413.png) |
| 待办，1413 / 390 px | [桌面](screenshots/tasks-1413.png) · [手机](screenshots/tasks-390.png) |
| 记忆，1413 / 390 px | [桌面](screenshots/memory-1413.png) · [手机](screenshots/memory-390.png) |
| 来源，1413 / 390 px | [桌面](screenshots/sources-1413.png) · [手机](screenshots/sources-390.png) |

`manifest.json` 将证据绑定到实际验收的应用源码与逐文件哈希。云端结果以 GitHub Actions 对应提交的运行状态为准，不把本地报告标成云端通过。
