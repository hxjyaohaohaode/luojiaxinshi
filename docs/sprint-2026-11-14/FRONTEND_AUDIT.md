# 冲刺前端逐项审计与证据边界

本轮依据用户两份附件逐条映射 128 项业务清单和 209 项参考。原始提取的编号、原文、优先级、附件 SHA-256 保存在 `requirements-extracted.json`；209 项完整决定保存在 `components-209.json`。这里报告前端主责 LJ-085—109 的修改、保留内容与实际验证范围。

## 方向与架构

保留 FastAPI、原生 ES 模块、珞珈绿/白底和现有导航。新 API 直接接原工作区：提醒、草稿、来源、校园发布、生命周期和协作都基于本人权限与版本。没有为展示而新增另一套状态，没有安装 209 项依赖。列表中已加载 50 项不能代表全部账号；首页、日历、导出和分析不复用首 50 项冒充完整集合。

每两组修改回看了三个约束：正式原文与个人计划分离；已保存数据和版本不丢；视觉精简不能隐藏失败、变更、证据或可达操作。由此补了草稿排队版本、隐藏 required 字段、拒收后的明确转交和回到未完成列表请求的重新读取。

## 逐项映射

| 编号 | 修改或保留内容 | 验证与剩余边界 |
|---|---|---|
| LJ-085 | 学院、事项、材料 CSS 进入统一 legacy/system 层序；删除独立无层 link 和运行时材料 link，修正 bundle 相对路径。已有各 feature CSS 保持必要规则，未凭静态猜测整片删除。 | npm run build；现有 visual / source-inbox / pilot suites |
| LJ-086 | 保留珞珈绿/白底与原导航。统一 control-target=44px 和 page/row 密度 token，明确 850px 断点；没有 scale 全页缩小。 | 新 sprint suite 320/390/1280 及原 visual suites |
| LJ-087 | 任务勾选、更多、拖动、聊天入口用独立 44px 格；删除桌面负 margin 并保留视觉图标大小。 | sprint: task targets and 320px composer geometry |
| LJ-088 | 主行搜索和收通知；来源/日期/关系/展示方式在明确 disclosure 内，筛选摘要保持可见，列表范围显示已加载/总匹配。 | source-inbox / visual / sprint pagination |
| LJ-089 | 一项主状态、一项关键时间和下一步；重要变更优先，多警告放更多菜单，未核实时间不冒充有效期限。 | tests/task-summary.test.mjs |
| LJ-090 | 保留分组、长标题换行；拖动入口明确提供点按/Enter 位置选择；当前加载范围写明，避免把 50 项当全部。 | verify_task_board.mjs；sprint task geometry |
| LJ-091 | 移除全局点击捕获庆祝；只有同账号/同路由的服务端 done 回执后庆祝。失败回滚、打开办理、撤回均不庆祝。 | sprint failed PUT + no confetti + real persisted completion |
| LJ-092 | 保留原 noticeFocus 证据顺序；公开阶段/公示/结果入口接真实生命周期编辑器，原文证据和版本关系可达。 | verify_notice_flow / notice_matters；sprint lifecycle entry |
| LJ-093 | 保留固定标题/滚动正文/保存区与服务器草稿机制；新增正式活动/办理窗口编辑；未勾选时间补丁的 required 输入禁用，避免隐藏字段阻止保存。 | verify_draft_continuity / notice_flow；official-time API tests |
| LJ-094 | 保留现有附件/文本/链接 intake 队列及失败重试、成功材料保留机制；没有用 CSS 把回执隐藏成加载装饰。 | 现有 verify_natural_intake / qq_group_intake / draft_continuity 门禁；本轮主要为回归 |
| LJ-095 | 文字与发送独立占位，表情和语音进入更多菜单；录音中控制仍移动到原录音面板可停止/取消。输入法与草稿恢复逻辑保留。 | verify_chat_layout / draft_continuity；sprint 320px keyboard menu |
| LJ-096 | 复制/引用等常用动作保留，朗读/版本/重生成/分支/分享进入有标签 disclosure；Escape 返回 summary 焦点。 | sprint secondary reply action；更新旧 review/stability 脚本操作新菜单 |
| LJ-097 | 保留已存在的用户上滑/流式读写/停止/断线恢复语义；本轮没有换掉对话运行时。懒加载不改变真实 stream API。 | verify_chat_layout / chat_recovery / reference_interactions / openui suites |
| LJ-098 | 高级筛选改为原生 details，搜索与当前范围保持主位；批量选择工具与原返回条件机制保留。 | verify_reference_interactions / memory continuity suites |
| LJ-099 | 来源代理新增规则试读、应用、回滚、跨域 Feed 发布者；卡片收起仍展示真实读取状态与最近成功。该文件由来源审计代理负责验证。 | source-presets / source-inbox suites；来源代理后端回归 |
| LJ-100 | 保留手机默认 agenda 与明确日/周视图；安排新增显式 reminder_minutes，默认不提醒课程；无虚构锁屏送达保证。正式活动时段编辑走原变更确认。 | arrangement_recovery / notice_flow；新 reminder API tests |
| LJ-101 | 480px 表单单列，导航仍可横向滚动且触达 44px；批量成员前后对照、持久草稿、附件、真实受众复核、投递版本、撤回/恢复/回滚、历史参考补发均接真实 API。 | sprint persisted draft；pilot workspace / campus API tests |
| LJ-102 | 分页区分加载、保留旧范围刷新、无匹配与失败；失败有重试，409 list_changed 保留筛选重新读。角色和删除结果依后端处理，不把读取失败当空列表。 | tests/paged-list.test.mjs；原 owner/route/isolation tests |
| LJ-103 | 测量实际底部导航/聊天输入和 visualViewport，错误常驻；成功提示暂停于 hover/focus/hidden；dialog 上层可操作，异步 Undo 按真实结果反馈。 | sprint persistent failure/mobile nav；需真实软键盘设备补验证 |
| LJ-104 | 所有筛选在服务器完整集合执行；50 项分页/总匹配/加载范围明确；请求带 epoch/账号/路由守卫；返回恢复滚动及可定位焦点。重入尚未完成路由会重发新读，不永远停加载。 | tests/paged-list.test.mjs (5)；sprint >50 and stale query |
| LJ-105 | 最终覆盖层关键中文字号提高到 12px，任务标题/日期不压到 11px；回复工具有文字、文件和公告正文保留展开。 | visual/layout suites；320px 断点新增检查 |
| LJ-106 | 新增菜单 keyboard/Escape/焦点回归，Native dialog/details/fieldset 和错误 live region；保留已有读屏名字及键盘移动。 | 新增/原键盘与焦点自动检查待 CI；真实读屏、200% 浏览器缩放、实体中文软键盘未在此受限环境完成，不声称全链路通过 |
| LJ-107 | 完成动画集中跟踪与取消；后台、reduced-motion、个人关闭、路由切换、账号切换清理；离屏不启动庆祝。保留现有 observer/输入响应。 | 已有 motion tests；sprint failed mutation；CI runtime pending |
| LJ-108 | 任务提交后重读当前分页投影；草稿/发布/重试/渠道供应商接受均用实际回执语义；拒收、转交、个人跟进与最小留存回执分别标明。 | 任务/协作/校园 API regressions + pilot workspace；新增 source/task range tests |
| LJ-109 | 209 逐项保留原编号/URL/依赖描述/适用场景/不采用理由；本轮实际打开并检查源码与交互的只有 114/115/133，采纳原生交互原则，不复制源码，不新增运行时库。 | 源码文件 blob SHA、实际 demo 操作及未观察到的部分分别记录；其余 206 不冒充实操 |

## 实际参考检查

本轮通过官方网页实际操作并读取 JavaScript/CSS 的组件是 #114 Prompt Bar、#115 Swipe Toast、#133 Spring Check，文件路径与 blob SHA 在 `reference-source-review.json`。参考内容对应输入主位、明确菜单、成功后状态反馈、暂停/常驻提示与动画清理。未复制其 React 代码；React、motion/react 与 Hugeicons 不进入本产品依赖。

Spring Check 实际经历点击、Space、375px、disabled 检查。Swipe Toast 已点 Show 与 Undo；只观察到退出状态，没有把提示最终消失声称为已测。Prompt Bar 在 375px 实际输入中文并打开菜单；某次 Add 点击显示 effort 面板，未把上游移动命中行为当已通过。我们的按钮使用独立 44px 触达范围，未采纳其微型 28px 按钮或装饰 Canvas。

209 项中的 35 个优先候选是审查优先级，不是全部引入的命令。其余 32 个优先、79 个条件和 95 个不采用项都逐项记录了目标及理由；本轮未逐个打开的组件明确记为未实操。旧仓库的参考融合文档属于历史记录，不能自动转成这轮浏览器证据。上游当前许可实际读取为 **MIT + Commons Clause License Condition v1.0**，不能简写成无限制 MIT；具体链接与本次“未复制代码”记录一并保存。

## 自动化与运行证据

本轮第一次修改后前端 Node 测试 260 项通过；分页控制器新增后 264 项通过。后续任务摘要、重入请求以及校园代理独立模块测试加入后，首轮冻结前 `npm test` **270/270 通过**；补充首次引导与轻量投影隔离后 **275/275 通过**；后续 CI 总数可随根代理新增测试增加。一次语法批检覆盖 157 个 JS/mjs 全部通过；新增文件也分别执行 Node 语法检查。

`verify_sprint_ui.mjs` 已进入默认浏览器门禁，固定 Chromium/Firefox/WebKit 分别执行：真实 API 建立 54 项、首 50/加载更多/跨页唯一词、迟到响应、500 回滚且无庆祝、移动提示安全区、44px 控件不相交、提醒矩阵/独立事项偏好、生命周期入口、320px 输入与回复菜单、服务器草稿附件重载。它同时记录冷/热载入请求数、传输量、编码体积、DOMContentLoaded、可输入时点和浏览器支持的长任务；标准 API 不支持精确解析耗时，明确为 null/unknown，不用执行耗时冒充解析。

本机浏览器安装下载失败；系统 Chromium 在浏览器启动阶段因环境 socket 权限策略失败，尚未执行到页面。正式提升权限路径也被环境自动审批策略拒绝；没有绕过该策略。云浏览器无法访问本机隔离夹具。因此本轮应用真实浏览器证据必须来自 GitHub CI 的固定三引擎，本报告不预先标为通过。现场/实体设备补验证包括屏幕阅读器、200% 浏览器缩放、中文软键盘与锁屏推送到达；供应商接受、站内收件、打开与完成办理始终使用不同语义。

## 文件与所有权

- 统一入口与密度：`static/styles.css`、`static/system/tokens.css`，最终任务/工作区尺寸由 `workspace-clarity.css` 负责，聊天由 `chat-conversation.css` 负责。
- 页面数据：`static/paged-list.js` 是有界投影控制器；`library.js` 与 `app.js` 负责既有页面和焦点/滚动还原。
- 校园/协作：`campus.js`、`campus-roster.js`、`campus-delivery-evidence.js`、`collaboration.js`、`collaboration-followup.js`；后端权限与版本为最终依据。
- 通知阶段/来源：`notice-lifecycle.js` 与来源代理维护的 `sources.js`。合法来源配置先试读，回滚重新试读，真实正式引用由原文选择。
- 发布构建：路由级原生动态 import；构建脚本由根代理维护、整合 CSS 与带内容标识资源，源文件变化后开发回退，避免 stale bundle。

管理员运行就绪入口已按角色挂在“设置 → 账号服务”；本人通知追踪入口在通知操作菜单内。独立模块 `operations.js` 由根代理维护，显示配置、记录的连接与管理员实际验收三类证据，不把保存记录当设备已读。


## 收尾审计发现与具体修复

- **LJ-001 首次使用说明**：首页提供可跳过的“现在能用什么”轻量卡片，不强制弹窗；可从“个人与账号 → 个人资料”找回。跳过通过原 `profile.dismissed_hints` 乐观并发保存，按账号持久化。身份说明只取服务端已授权 `campus_membership`，自填教师不获得学院发布权限。晚响应、切换账号与离开对话框均有守卫。
- **完整轻量投影**：首页、日历、批量收件目标和聊天只读日历面板使用 `/workspace/projection` 的完整本人范围。`revision` 与分钟 `clock` 分离，分钟刷新只合并时效字段；通知详情仅在稳定版本真的变化时重读全文。查询列表仍走有界分页。新增 Node 用例验证 84 条不截成 50、差量保留稳定字段、缓存重置与账号/路由迟到隔离。
- **精简展示不回写数据缺失**：轻量任务标记 `projection:light`。首页完成操作先读取完整单项并核对版本，日历查看备注与编辑也按单项取完整内容；全文材料和证据不会从轻量数据构造写入。日历原有按标题、地点、备注检索语义由 `/workspace/calendar-search` 返回完整命中 ID 保留，输入防抖、旧请求失效，失败保留上一范围并提供重试。
- **真实模块实例验证**：原两份 reader 稳定性脚本读取独立 source 模块的私有 WeakMap，在 bundle 模式下会形成另一实例。现在测量实际 reader 的尺寸与滚动位置连续稳定至少 700ms，并等待祖先有限动画结束；原阅读字词/锚点断言保持。聊天布局通过真实“回到最新”按钮触发应用内部滚动并核对位置与标题状态。
- **构建与统计**：静态 URL 路径检查改为 `relative + isAbsolute`，Windows/Linux 均明确拒绝根目录和越界；代码与已提交构建文本统一 LF，参考资料保持原始字节，未对二进制强制文本化。新 sprint 截图、报告及日志进入 CI artifact；CI summary 对顶层失败、文字步骤报告保留真实失败，不重复计数，不把缺少报告记成零失败通过。
- **设备策略**：提醒矩阵明确每台设备由本人单独开启，事件发往本人全部已启用设备，每台按事件去重；本机关闭/退出不撤销其他设备，不声称自动选择主设备。

收尾新增浏览器场景覆盖首次跳过/重载/个人页找回/另账号独立身份、首页 54 条完整计数、轻量任务完成后原 `data` 完整保留、日历备注命中及按需详情、首页和日历没有请求旧全量正文列表。这里记录的是已编写门禁；应用的真实三引擎运行结果仍必须以最终 GitHub CI 产物为准。
