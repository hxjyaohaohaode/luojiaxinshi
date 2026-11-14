# 冲刺前端逐项审计与候选验收

**候选验收冻结于 2026-11-14T12:18:27.857754+00:00：CI63 的 9 个必需作业实际成功，33 份完整浏览器报告共 1,056/1,056 项通过，连续性 990/990，Linux 与 Windows 的 Node 各 358/358。** 本文当前冻结依据为候选 `70226e910b7fe2ecdfd49b0a34dcd62ba00484bc`；18 张原始截图与对应几何/回执已经人工核阅，具体范围和未覆盖边界见下方 CI63 详细记录。

[CI63 原始运行](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43592108675) · [完整成功审计](../audits/sprint-review-ci-63-success.json) · [PR #5 实际交付入口](https://github.com/hxjyaohaohaode/luojiaxinshi/pull/5) · [main 与后续 Actions 记录](https://github.com/hxjyaohaohaode/luojiaxinshi/actions)

这是明确时点的候选证据；实际 main 合并与 main push 运行以交付入口为准，不预写未来 SHA 或检查结果。三个 JSON 的 `latest_review_followup` 对应本次 CI63，旧值与完整原始数组保持历史身份。209 项仍为 **35 优先候选、79 条件候选、95 暂不采用**，实际完成上游 demo 与源码深核的只有 **3 项**，不是安装了 209 项依赖。

## 历次当时记录（保留原文）

以下折叠区块是 Run52、CI57/58 和 Run59 启动时的历史原文。其中“最新”“当前”“正在等待”等措辞仅对应各段当时的记录时点，不能作为上述 CI63 冻结状态。旧数字、失败和未执行范围均保留；折叠区块结束后是 CI63 的完整验收说明。

<details>
<summary>展开首轮与历次补修历史原文；其中的当前状态词只指当时</summary>

# 冲刺前端逐项审计与证据边界

> 补修轮阅读说明：原 run52 与后续 CI57/Run58 启动记录完整保留为历史。CI58 已核为失败，隔离补修的 341 项 Node 与构建验证已完成；最新整合候选 Run59 正在等待实际浏览器结果。三个 JSON 的 `latest_review_followup` 是当前补修记录，旧 `review_followup` 全文保留为上一阶段快照。

本轮依据用户两份附件逐条映射 128 项业务清单和 209 项参考。原始提取的编号、原文、优先级、附件 SHA-256 保存在 `requirements-extracted.json`；209 项完整决定保存在 `components-209.json`。这里报告前端主责 LJ-085—109 的修改、保留内容与实际验证范围。

**最新候选结果：run52 已完成，官方 9 个作业全部成功。** 原始浏览器 33 份报告全部通过，共 1038/1038 项检查；独立连续性为 990/990，均已下载并校验官方 SHA-256。产品入口仍是 `app-DFTX33VB.js`，同一产物再次通过 7 个 Node22 Linux/Windows 构建一致性门禁。前端 25 项验证元数据已按真实相关套件逐条更新；实体软键盘、读屏、200% 缩放及未逐个实操的上游组件边界继续保留。这是候选 `6b15c745` 的工程证据，不预写后续 main 分支运行结果。前三轮失败历史完整保留。

## 方向与架构

保留 FastAPI、原生 ES 模块、珞珈绿/白底和现有导航。新 API 直接接原工作区：提醒、草稿、来源、校园发布、生命周期和协作都基于本人权限与版本。没有为展示而新增另一套状态，没有安装 209 项依赖。列表中已加载 50 项不能代表全部账号；首页、日历、导出和分析不复用首 50 项冒充完整集合。

每两组修改回看了三个约束：正式原文与个人计划分离；已保存数据和版本不丢；视觉精简不能隐藏失败、变更、证据或可达操作。由此补了草稿排队版本、隐藏 required 字段、拒收后的明确转交和回到未完成列表请求的重新读取。

## 逐项映射

下表中的脚本名表示对应验收门禁，脚本存在本身不是通过证据。实际运行结果按后文的 CI 轮次、提交与报告分别记录；最新候选 run52 的相关门禁已完成，每条需求的具体范围与保留边界见 `frontend-25.json`，不把套件总数直接解释为所有设备和状态组合全验收。

| 编号 | 修改或保留内容 | 对应门禁与剩余边界 |
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
| LJ-106 | 新增菜单 keyboard/Escape/焦点回归，Native dialog/details/fieldset 和错误 live region；保留已有读屏名字及键盘移动。 | run52 相关键盘与焦点自动回归通过；真实读屏、200% 浏览器缩放、实体中文软键盘未在此受限环境完成，不声称全链路通过 |
| LJ-107 | 完成动画集中跟踪与取消；后台、reduced-motion、个人关闭、路由切换、账号切换清理；离屏不启动庆祝。保留现有 observer/输入响应。 | 已有 motion tests 与 run52 sprint 失败/办理不庆祝、成功回执反馈，以及看板减弱动画键盘回归通过；实体设备组合未穷举 |
| LJ-108 | 任务提交后重读当前分页投影；草稿/发布/重试/渠道供应商接受均用实际回执语义；拒收、转交、个人跟进与最小留存回执分别标明。 | 任务/协作/校园 API regressions + pilot workspace；新增 source/task range tests |
| LJ-109 | 209 逐项保留原编号/URL/依赖描述/适用场景/不采用理由；本轮实际打开并检查源码与交互的只有 114/115/133，采纳原生交互原则，不复制源码，不新增运行时库。 | 源码文件 blob SHA、实际 demo 操作及未观察到的部分分别记录；其余 206 不冒充实操 |

## 实际参考检查

本轮通过官方网页实际操作并读取 JavaScript/CSS 的组件是 #114 Prompt Bar、#115 Swipe Toast、#133 Spring Check，文件路径与 blob SHA 在 `reference-source-review.json`。参考内容对应输入主位、明确菜单、成功后状态反馈、暂停/常驻提示与动画清理。未复制其 React 代码；React、motion/react 与 Hugeicons 不进入本产品依赖。

Spring Check 实际经历点击、Space、375px、disabled 检查。Swipe Toast 已点 Show 与 Undo；只观察到退出状态，没有把提示最终消失声称为已测。Prompt Bar 在 375px 实际输入中文并打开菜单；某次 Add 点击显示 effort 面板，未把上游移动命中行为当已通过。我们的按钮使用独立 44px 触达范围，未采纳其微型 28px 按钮或装饰 Canvas。

209 项中的 35 个优先候选是审查优先级，不是全部引入的命令。其余 32 个优先、79 个条件和 95 个不采用项都逐项记录了目标及理由；本轮未逐个打开的组件明确记为未实操。旧仓库的参考融合文档属于历史记录，不能自动转成这轮浏览器证据。上游当前许可实际读取为 **MIT + Commons Clause License Condition v1.0**，不能简写成无限制 MIT；具体链接与本次“未复制代码”记录一并保存。

## 自动化与运行证据

本轮第一次修改后前端 Node 测试 260 项通过；分页控制器新增后 264 项通过。后续任务摘要、重入请求以及校园代理独立模块测试加入后，首轮冻结前 `npm test` **270/270 通过**；补充首次引导与轻量投影隔离后 **275/275 通过**；后续 CI 总数可随根代理新增测试增加。一次语法批检覆盖 157 个 JS/mjs 全部通过；新增文件也分别执行 Node 语法检查。

`verify_sprint_ui.mjs` 已进入默认浏览器门禁，面向固定 Chromium/Firefox/WebKit 编写以下场景：真实 API 建立 54 项、首 50/加载更多/跨页唯一词、迟到响应、500 回滚且无庆祝、移动提示安全区、44px 控件不相交、提醒矩阵/独立事项偏好、生命周期入口、320px 输入与回复菜单、服务器草稿附件重载。是否实际执行到每一场景，以对应轮次的报告为准；首轮在第五项检查中断，未到达后续场景。脚本同时记录冷/热载入请求数、传输量、编码体积、DOMContentLoaded、可输入时点和浏览器支持的长任务；标准 API 不支持精确解析耗时，明确为 null/unknown，不用执行耗时冒充解析。

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

## 首轮真实 CI 与修复后的冻结构建

首轮实际运行是 [GitHub Actions 43558958724](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43558958724)，PR #4，候选提交 `6145f129169aae160d7ae9fcf3ccda3f42cbdbae`，CI 检出的合并提交为 `aa0f12d6930228cc14d568ade72d8e745eae639c`。**主 browser job 的结论是失败，不能把已通过的子套件合并解释成整体通过。** `Async save and recovery` 独立作业的 990 项检查通过；主作业中的原前端回归、参考交互、视觉尺寸、材料、通知事项、Push、QQ、四组 Agent 检查，以及三引擎 OpenUI 和紧凑聊天布局通过。其他失败及精确计数保留在 `docs/audits/sprint-ci-first-round.json` 和该次 CI 原始 artifact 中。

官方浏览器 artifact 为 `synthetic-browser-reports`，ID `14099809716`，24,195,304 字节，下载后校验 SHA-256 为 `979920c9cc611afd1317531e9327240b3d26754f5f6b001a28c931dbb57b042a`。首轮历史没有删除或替换为修复后的结果。

### 已确认的问题与修复边界

| 实际发现 | 处理与保留的验证要求 | 当前结论 |
|---|---|---|
| `composer-browser` 报告两个 `.dictation-panel`。测试导入源码 `dictate()` 启动录音，随后由 bundle 按钮处理停止，两份模块各有自己的 `active`。 | `tests/composer-browser.mjs` 改为点击真实麦克风按钮，并拦截公开的语音配置、转写接口；仍验证实际 AudioWorklet、WAV、分段转写、手工文字、唯一控件、停止与失败重试。 | 脚本已修，下一轮浏览器实测待执行。 |
| 三引擎聊天交互找不到可见的“上一版回复”；恢复套件等待版本选择请求超时；朗读套件后续点击被折叠菜单隐藏。 | 新增 `scripts/reply_menu_checks.mjs`，每次先实际展开原生“更多”再点击。原音频复用、阅读锚点、版本选择及刷新持久化断言均保留。 | 脚本已修，不能提前记为三引擎通过。 |
| 记忆 SVG 检查把整个按钮限制为 32px，而实际按钮已经按触控要求改为 44px。 | 分别验证 SVG 大小不超过 32px、按钮至少 43.9px，并保留图标数量与无障碍标签断言。 | 兼顾视觉图标和触控目标，没有把触控目标缩回旧值。 |
| 导航独立夹具仍只传数组；看板跳转检查仍期待旧计数文字；迟到查询和跨设备测试仍拦截或期待旧全量接口。 | 导航夹具补齐分页合同并等待加载；看板跳转核对已加载/总匹配及真实记录 ID；迟到响应测试先取得旧分页响应，等新响应显示后再释放旧响应，保留 800ms 稳定窗口；跨设备刷新必须走 `/tasks/page`，且不得下载全量任务或通知列表。 | 新合同与原业务断言同时保留，等待真实 CI 复验。 |
| 代码复核确认 `loadTaskList` 在 `onChange` 已绘制后再次重绘；缓存命中也会在 `await` 续体里替换刚取得的行节点。首轮 WebKit 窄屏检查另观察到节点脱离 DOM，尚不能只凭日志认定这是唯一原因。 | 唯一产品修改位于 `static/app.js`：删除重复绘制，保留账号/路由守卫与缓存数据回填。新增 `task_list_stability_checks.mjs`，通过真实点击记录行/手柄，持续 350ms 检查同一节点与焦点，并验证首页返回后原筛选 ID 恢复。 | 产品修复已构建；必须由下一轮浏览器回归确认。 |
| 冲刺套件的三个引擎均在首页任务操作等待撤回提示时超时。截图实际显示办理面板。 | 该夹具创建的是需要核对办理的事项，产品按既有 `submission/preparing` 规则打开面板；根代理负责修正测试前提，不能改产品绕过核对。任务排序、通知收件、来源及其他工作区失败由对应代理处理，完整记录见首轮 CI 总账。 | 首轮 sprint 共 15 项已执行检查：12 通过、3 失败，均在第五项中断。后续分页、提醒和校园草稿场景尚未执行到。 |

`verify_task_board.mjs` 保留原拖动、次序、撤销与失败恢复断言，新增节点稳定性回归，并将手机手柄要求从 27.5px 提升到至少 43.9px。没有使用强制点击、删除失败断言或产品测试专用通道使回归通过。

### 当前构建和已执行的本地检查

首轮修复后的候选入口为 `/static/dist/app-XK3PQMAE.js`，CSS 为 `/static/dist/styles-BKR4PFDD.css`，共 **24 个构建产物、191 个静态源文件**。该候选的构建和验证记录已保存在 `frontend-build-verification.json` 的 `history`，更早的 `/static/dist/app-JL3KAYN2.js` 记录也保留；顶层记录本文最后一节的最新冻结构建。

| 已实际执行的命令或检查 | 结果 |
|---|---|
| `npm run build` | 成功，生成新 JS 入口和对应 manifest/index。 |
| `npm run build:check` | 成功，当前提交产物与重建结果一致。 |
| `npm test` | 275 项通过，0 失败、0 跳过。 |
| `tests/test_frontend_bundle.py` 与 `tests/test_audit_reports.py` | 23 项通过。 |
| 修改文件的 Node 语法检查与 `git diff --check` | 通过。 |
| 修复后的浏览器检查 | 该历史候选 run50 最终失败，完整结果见第二轮记录；最新 run52 已真实通过，精确范围见末节。本机未运行浏览器。 |

已完成构建时记录的 JS 入口大小为 431,421 字节，gzip 147,313 字节、Brotli 115,118 字节；CSS 为 600,210 字节，gzip 114,991 字节、Brotli 89,582 字节。这些数值来自此前实际 `build:check` 输出，本次文档更新只读取既有记录与 manifest，没有在独立性能实验期间重新构建或计算压缩。

首轮 Node 22.23.4 的 Linux 和 Windows 构建一致性门禁均通过，它们验证的是旧候选产物。run 43562060192 在 Linux 主浏览器、continuity、单元作业和四个 Windows 分片中通过相同构建门禁，验证的是当轮 `app-XK3PQMAE.js`。完成的 continuity 作业日志实际记录 Node `v22.23.4`。构建跨平台一致性与浏览器交互验收分别记录；该轮主 browser 最终失败。最新 `app-DFTX33VB.js` 的 Node22 一致性已经第三轮验证，见末节。

### 实际截图与载入测量

已逐张查看官方 artifact 中的以下截图：首轮 sprint 桌面失败图、聊天交互桌面失败图、320px 手机聊天界面、390×420 键盘高度下的聊天布局；另查看独立 continuity artifact 的 320px 恢复弹窗、390px 资料冲突弹窗和 1440px 桌面恢复弹窗。可见的输入、按钮、文字与导航没有明显横向溢出或操作遮挡；桌面聊天失败图明确显示“更多”尚未展开。这个目视结论仅覆盖这些图，不能替代被中断场景的测试。

主要图片在首轮 artifact 内的路径为 `sprint-ui-browser/chromium-failure-5.png`、`chat-interactions/chromium/failure.png`、`visual-review-browser/chat-mobile-320.png`、`chat-layout/chromium/keyboard.png`。首轮新增 sprint 套件未执行到手机校园草稿场景，也没有相应截图。

首轮 sprint 真实记录了 6 条冷/同一上下文热登录测量：

| 引擎 | 冷登录可输入时点 | 热登录可输入时点 | CSS 请求数 |
|---|---:|---:|---:|
| Chromium | 276.6ms | 110.6ms | 两次均为 1 |
| Firefox | 536ms | 161ms | 两次均为 1 |
| WebKit | 324ms | 173ms | 两次均为 1 |

这是 GitHub CI 环回合成夹具的测量，不能作为线上公网或实体手机 SLA。总资源请求为 15—16 个，静态资源请求为 13—14 个；WebKit 的热载入仍有约 1.83MB 传输量，不能把所有引擎的热缓存都写成零字节。精确 JavaScript 解析耗时保持 `null`；只有 Chromium 暴露长任务观测支持，Firefox/WebKit 的不支持状态不能解释为没有长任务。新增任务与校园场景中断后的载入数据没有补造。

## 第二轮 CI：完整结果与修复边界

本轮主 browser 已于 05:57 UTC 完成，结果为 **failure**。33 个报告槽中，30 个完整通过，pilot 报告失败，sprint 与 composer 在失败退出前未生成报告。已生成报告共有 957 条检查：954 通过、pilot 的 3 条失败；pilot 的 `errors` 重复记录这 3 条，不再另算 3 次。缺失报告没有可核验的检查数量，不能计为零失败通过。以下 05:50、05:54 的状态保留为运行过程证据。

[GitHub Actions 43562060192](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43562060192) 对应候选提交 `32c5ce524d553c869816d0264e9cf84b57febe39`。截至 2026-11-14 05:50 UTC，主 browser 作业 `132347708809` 仍在执行。新 sprint 预期 60 条检查、任务看板预期 28 条检查，这些是验收数量要求，当前不能写成实际通过数量。

05:54 UTC 的后续官方步骤记录显示：16 个主套件步骤和 Agent 步骤均已失败，作业继续执行聊天等后续阶段。运行中的正式 job-log 下载仍返回 `404 BlobNotFound`，所以此时只有步骤级失败证据，不能推定具体场景或根因。完整日志和 artifact 发布后将补齐逐项结果；以下 continuity 的成功不能抵消这两个失败步骤。

独立 `Async save and recovery` 作业 `132347708859` 已完成并成功。下载官方 artifact `continuity-browser-reports`（ID `14100383444`，703,372 字节）后，SHA-256 校验为 `ded0a0e322ed67502cc5e3493ddd53fac0c762c29ee5bffa29b454fecf274cdf`，产物记录的提交与本轮候选相同。下面的数量直接从原始报告逐条统计 `checks[].passed`，全部为 `true`，三个报告的 `errors` 数组均为空。

| 本轮原始报告 | Chromium | Firefox | WebKit | 总通过 | 失败 / 页面错误 |
|---|---:|---:|---:|---:|---:|
| `continuity-browser/arrangement-recovery/report.json` | 204 | 204 | 204 | 612 | 0 / 0 |
| `continuity-browser/draft-continuity/report.json` | 68 | 68 | 68 | 204 | 0 / 0 |
| `continuity-browser/ui-continuity/report.json` | 58 | 58 | 58 | 174 | 0 / 0 |
| 合计 | 330 | 330 | 330 | 990 | 0 / 0 |

这些真实检查覆盖了安排保存后清理失败、已保存结果被编辑或删除、成功回执丢失、恢复查询不可用、迟到结果隔离；通知与安排草稿在业务写入或清理等待期间继续编辑；资料冲突保留输入、失败重试、晚响应不覆盖新页面或弹窗。它们不能替代主 browser 中的分页、来源试读、任务拖动、回复版本和校园草稿检查。`frontend-25.json` 已按实际场景增加部分证据，没有把这 990 条整体映射成 25 项需求全部验收。

本轮已实际打开三张截图：`continuity-browser/arrangement-recovery/recovery-320.png`、`continuity-browser/arrangement-recovery/recovery-1440.png`、`continuity-browser/ui-continuity/profile-conflict-390.png`。320px 安排恢复弹窗的四个动作和已保存结果可读；1440px 弹窗居中且操作完整可见；390px 冲突弹窗保留本人填写，明确展示冲突值和核对、保存入口。上述图片没有明显横向溢出或遮挡。该目视范围不包含尚未下载的新 sprint 手机草稿/聊天截图，也不等同于真实软键盘、读屏或 200% 缩放验收。

本轮开始前的 Node 本地结果为 **275 / 275**，构建相关 Python 检查 **23 / 23**，该轮入口、24 个产物和 191 个源文件与其跨平台构建门禁一致。上述运行中检查点只整理既有日志与下载报告，没有在等待阶段修改产品源码。

### 主 browser 的实际通过项与失败项

本轮官方主浏览器 artifact 为 `synthetic-browser-reports`，ID `14101013306`，21,736,325 字节，下载后校验 SHA-256 为 `3f7cb6afb5c80248652ea1376f54410ec4d64e6803c809ee6dd30777ca4f598c`。产物与运行均绑定候选 `32c5ce5`。

任务看板 **28 / 28** 通过（Chromium 10、Firefox 9、WebKit 9），包括每个引擎新增的“同一行节点、手柄及焦点保持 350ms，首页返回恢复筛选”回归。前端稳定性 123、工作区 120、通知办理 45、自然收件 33、来源收件 5、来源预设 7 均通过。回复交互三个引擎为 9 / 8 / 8，回复刷新恢复为 3 / 3 / 3；其他完整通过项见第二轮总账。对所有可比较的报告逐条核对，首轮已经通过的检查名称都仍然存在。

| 实际失败 | 实证与边界 | 修复范围 |
|---|---|---|
| sprint | 唯一原始日志是 `Browser suite exceeded the 360-second deadline.`；无报告、无截图、没有可用的请求尾部，精确停点未知。静态审查发现唯一无界的 `await began`，这是待验证推断，不是日志确认的停点。 | 仅脚本：旧查询等待与抓取设显式截止，每项开始/通过/失败即时写报告，记录最近请求；仍保留原 360 秒总截止。旧查询被取消时记录 abort 与迟到 fulfill 尝试，不声称强迫旧响应送达。外部 API 写入的办理 guard 先真实 reload 并核对已提交状态，再点击一次验证不完成、不庆祝；该 guard 缓存前提不是本轮已观测失败。 |
| pilot 三引擎协作场景 | 三次均在 `scoped collaboration is received, returned, supplemented and resolved across devices` 等待 12 秒超时。首次从待办办理面板进入协作时，懒加载模块尚未注册按钮监听，真实页面没有发出 options 请求。 | 修复产品冷入口：入口由已加载的 app 委托，按需导入后使用捕获的账号/视图守卫；保留首次进入、关闭表单和切换路由的真实回归，不通过预热协作页规避。 |
| composer | `tests/composer-browser.mjs:83:56` 点击 `#chat-composer .composer-voice` 超时，日志明确 `element is not visible`，截图显示“更多”未展开。其余四个 Agent 套件 29 条通过。 | 仅测试先打开真实输入菜单再点麦克风，并按当前 DOM 验证结束后唯一控件回到菜单；真实采集、RIFF、分段、手工输入、503 重试等断言全部保留。 |

本轮另实际查看 `task-board-browser/webkit-320.png`、`task-board-browser/chromium-desktop.png`、`chat-layout/chromium/keyboard.png` 和 `visual-review-browser/chat-mobile-320.png`。320px 待办标题换行、撤销提示位于导航上方；桌面三栏与加载范围可读；390×420 聊天的输入、发送和导航保持可见；320px 聊天没有横向溢出。**新 sprint 手机草稿与聊天截图没有生成，不能以其他页面截图代替。**

修复后的候选需重新运行 CI。协作冷入口修复后的 `app-DZKWHU4J.js` 曾通过一次本地 build/check、275 项 Node 与 23 项构建/审计检查；该值只是中间构建。随后横向审查又发现聊天回复的记忆来源入口需要同类冷启动桥接，最终产物须在该修复冻结后统一重建，不能把中间构建当最终验收。

## 第二轮修复后的最终本地冻结

协作与记忆冷入口、相关关闭/换页守卫，以及 sprint/composer 验收脚本均冻结后，2026-11-14 06:13 UTC 已重新执行 `npm run build`、`npm run build:check`、完整 `npm test` 和构建/审计 Python 定向检查。结果为 **build/check 成功、Node 275 / 275 通过、Python 23 / 23 通过**；没有运行本地浏览器。源码/测试与生成产物的实现指纹按仓库 `scripts.audit_full_suite.fingerprint()` 得到 `d55ba13592713d9de75a6e2344cb0d2092f2302896cc895d15544fc25f603c12`。

最新入口为 `/static/dist/app-DFTX33VB.js`，SHA-256 `b42c391fe6ee581cd9225b323563434b1148ba4b15ee496308448e2fcba65baf`；CSS 仍为 `/static/dist/styles-BKR4PFDD.css`，共 24 个产物、191 个静态源文件。JS 入口 431,979 字节，gzip 147,436 字节、Brotli 115,247 字节。`frontend-build-verification.json` 顶层与 `frontend-25.json` 已记录此次实际门禁，保留旧候选和中间构建历史。

上述本地冻结对应候选 `05498ae`，其第三轮真实 CI 结果已经产生：Node22 跨平台构建通过，主浏览器仍失败，精确结果见下节。run50 的失败继续保存在 `browser.second_ci` 与第二轮总账中，未用后续通过结果覆盖。

## 第三轮 CI：run51 的真实结果

[GitHub Actions 43565458564](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43565458564) 对应候选 `05498ae154403c239ee4efddca0041fd530ce6c3`。官方 browser 日志实际检出 PR 合并提交 `0c17c2dc33c874c21d655f64302a81d4a9a49866`，记录 Node `v22.23.4`。**整体 browser 结论为 failure**：33 份报告全部存在，31 份完整通过，sprint 和 pilot 两份失败。已记录 1005 项检查中 1000 通过、5 失败；sprint 另外 24 项、pilot 另外 9 项没有执行，不能计为通过。pilot 的 `errors` 是其 3 条失败检查的重复记录，不另加失败次数。

官方主产物 ID `14103186594`，22,206,238 字节，下载后 SHA-256 为 `989047ce72c33e33734974b4ac513b13623402bf77f89faefb6f96a9cf89faec`。独立连续性产物 ID `14101379678`，705,888 字节，SHA-256 为 `18400b11f9f55616bc7382b379c682ec3afdce6fec5663b942195d2ffe003f0a`。原始报告分别保存在 `ci-evidence/43565458564/browser/` 和 `continuity/`，逐项审计为同目录的 `browser-report-audit.json`、`continuity-report-audit.json`。

| 套件与范围 | 实际结果 | 引擎边界 |
|---|---:|---|
| Browser stability / regression / reference interactions | 123 / 201 / 48 通过 | 三引擎，分别每引擎 41 / 67 / 16 |
| Workspace / visual layout / notice flow / natural intake | 120 / 168 / 45 / 33 通过 | 三引擎，分别每引擎 40 / 56 / 15 / 11 |
| Task board，含同节点与焦点保持回归 | 28 通过 | Chromium 10、Firefox 9、WebKit 9 |
| Notice matters / QQ intake | 21 / 12 通过 | 三引擎，分别每引擎 7 / 4 |
| Materials / source inbox / push / source presets | 9 / 5 / 8 / 7 通过 | Chromium |
| Agent approvals，含新增 memory 冷入口 | 13 通过 | Chromium |
| 其他三组 Agent / Composer 完整录音链 | 7 / 7 / 5 / 9 通过 | Chromium；不能扩大为三引擎 |
| OpenUI / compact chat / chat recovery | 30 / 12 / 9 通过 | 三引擎，分别每引擎 10 / 4 / 3 |
| Chat interactions | 25 通过 | Chromium 9、Firefox 8、WebKit 8 |
| Sprint | 36 项记录：34 通过、2 失败 | Chromium 7/8、Firefox 20/20、WebKit 7/8；后续 24 项未执行 |
| Pilot | 24 项记录：21 通过、3 失败 | 每引擎 7/8；后续 9 项未执行 |
| 独立 continuity | 990 通过，0 错误 | 三引擎各 330；安排恢复 612、草稿连续性 204、界面连续性 174 |

按引擎与检查名称逐条对比，run50 已记录通过的检查在本轮没有缺失。Agent 13 和 Composer 9 另由校园代理独立检查原始报告与日志：新增 memory 首次入口和迟到守卫、实际录音分段与 RIFF 上传、手工输入保留、停止清理和 503 后真实重试均执行到结束。其证据范围仍是 Chromium。

### 两个失败的精确边界

1. Sprint 在 Chromium、WebKit 的第 8 项旧查询测试失败，原始错误为 `The older task query was not captured within 10 seconds; recent_requests records the observed UI requests.`。Firefox 完整 20 项通过。WebKit 请求尾部确有旧查询的请求与 HTTP 200，但暂停处理器没有捕获，测试没有建立迟到响应的前提。不能把它写成旧响应覆盖新结果，也不能认定认证 API 被缓存。报告正确标记为 `incomplete`。
2. Pilot 三引擎均在新增冷入口关闭检查失败：`#dialog [data-action=close-dialog]` 同时匹配顶栏“关闭”和页尾“返回”，触发 strict-mode 错误。后续关闭守卫和原协作业务链尚未验完。审查还发现原 `waitForRequest` 仅证明请求发生，没有证明模块路由处理器真正暂停了请求。

下一候选仅修夹具：网络拦截场景明确阻止 Service Worker 并记录控制器状态；Sprint 记录旧查询处理器是否进入、是否取得真实响应以及实际迟到处理结果；Pilot 使用唯一的可访问名称“关闭”，等待实际处理器发出的有界暂停信号，保留释放、清理、零收件人请求、不重开和不回退断言。没有更改产品来迁就这些测试。

### 本轮实际截图与性能测量

已实际打开 `sprint-ui-browser/firefox-mobile-chat.png`、`firefox-mobile-draft.png`、`task-board-browser/chromium-desktop.png` 及 `sprint-ui-browser/webkit-failure-36.png`。390px 聊天输入框、代码块与提示条可见，桌面看板三列和撤销入口没有明显横向溢出。手机草稿原文和已保存附件真实恢复，但截图处于中间滚动位置，“核对并发布”按钮部分落在固定底栏之后：这张图不能证明按钮不可达，也不能证明按钮完整无遮挡。这个 run51 的未定边界保留为历史；随后在既有草稿检查内增加正常滚动、`trial` 可点击性和完整边界框检查，run52 已实际通过，详见第四轮数据。

| 引擎 | 冷登录可输入时点 | 同上下文热登录可输入时点 | 两次 CSS 请求数 |
|---|---:|---:|---:|
| Chromium | 351.4ms | 153.7ms | 1 / 1 |
| Firefox | 606ms | 393ms | 1 / 1 |
| WebKit | 423ms | 225ms | 1 / 1 |

Firefox 另完成热聊天载入测量：可输入时点 454ms、29 个资源请求、18 个静态请求、1 个 CSS 请求、传输 78,178 字节。其他两引擎中断后的热聊天测量没有生成。run51 使用默认允许 Service Worker 的上下文，但没有记录控制器状态；run52 的网络故障夹具明确阻止 Worker，因此后续测量必须标注这个差异，不能作无条件性能提升比较。精确 JavaScript 解析耗时仍为未测；Firefox/WebKit 的 Long Task API 不支持保持未知，PWA 与推送行为由独立 Chromium 套件检查。环回 CI 结果不代表公网或实体手机 SLA。

## 第四轮 CI：run52 候选全部门禁通过

[GitHub Actions 43567666000](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43567666000) 对应 `6b15c7452966e7600cca87acf36a2e11ad034fbc`，实现指纹 `a8173b44887b2a4e7aaea494777598105ca12ccafc28c29db17557d500b12f70`。官方状态为 **completed / success，9/9 作业成功**，原始工作流元数据保存在 `artifacts/ci-readonly/run-43567666000-root-official.json`。browser 日志实际检出 PR 合并提交 `ac3e291285b55c0dc28e4acd5f2673ddf29dca22`，并记录 Node `v22.23.4`。本节只描述该候选，不预写后续 main 分支的运行结果。

主 browser 的 33 份原始报告全部存在并完整通过，**1038/1038 项检查、0 失败、0 缺报告、0 预期后续未执行**。独立 continuity 三份报告全部通过，共 **990/990**，三个引擎各 330。与 run51 对照，所有已记录通过的原检查名称仍然存在；没有删断言、降低目标尺寸、提高 360 秒总截止或用重试掩盖错误。

| 关键补验范围 | 本轮真实结果 |
|---|---|
| Sprint | 60/60，Chromium、Firefox、WebKit 各 20；完整执行到提醒、生命周期、输入菜单、账号切换及校园草稿重载。 |
| Pilot | 33/33，三个引擎各 11；原跨设备接收、退回补充、再提交、解决回执与断线同步链全部走完。 |
| 冷协作模块加载 | 6 条实际记录：每引擎关闭与离开路由各一次；`module_held=true`，释放前后 options 请求均为 0，控制器均为 `null`，晚到模块没有重开旧界面或退回路由。 |
| 旧查询处理 | 三引擎处理器均实际进入并捕获响应，再发出新筛选并保持原 800ms 稳定窗口。Firefox 实际观察到迟到响应；Chromium 的旧请求为 `net::ERR_ABORTED`、WebKit 为 `Load request cancelled`，只记录真实迟到 fulfill 尝试，不声称旧响应已经送达。 |
| Task board | 28/28，Chromium 10、Firefox 9、WebKit 9；同节点与焦点保持、首页返回恢复筛选及拖动/撤销原断言继续通过。 |
| Agent / Composer | Agent 13/7/7/5、Composer 9 全部通过，**范围为 Chromium**。新增 memory 冷入口、真实回执与迟到守卫，以及合成录音的分段/RIFF/手工输入/503 重试均由第二位审查者逐日志独立核对。 |
| 其余报告 | 原稳定性123、前端回归201、reference48、workspace120、visual168、notice-flow45、natural-intake33，以及来源/事项/QQ/OpenUI/聊天布局、交互、恢复等原报告全部通过；各自实际引擎在 JSON 中逐份列明。 |

主产物 ID `14103570812`，21,714,160 字节，SHA-256 `fff18d05753717f2bd57e631409efdf10eadd05325f0d9ffae16aa7bef90cad1`；continuity 产物 ID `14102853777`，706,100 字节，SHA-256 `895873452c45c4e85706376e7ebf9e049e781403e481571411c326f72d3bf55c`。两个 ZIP 均只下载一次，解压前校验摘要并检查成员路径；原始数据与逐项计数位于 `ci-evidence/43567666000/`。

### 手机截图与发布按钮的实际结果

已实际打开本轮 `sprint-ui-browser/chromium-mobile-draft.png`、`sprint-ui-browser/webkit-mobile-chat.png` 和 `task-board-browser/chromium-desktop.png`。手机草稿及原附件可见；普通文档滚动后发布按钮完整露出，未提交不完整草稿。聊天输入、发送、代码区与回复菜单入口可见，提示条位于输入框上方；桌面看板三列与撤销入口没有明显横向溢出。根审查者另独立查看 Chromium/Firefox 两张草稿和 WebKit 聊天图，结论一致。

| 引擎，390×844 视口 | 发布按钮高度 | 按钮下沿 | 底栏上沿 | 间隔 |
|---|---:|---:|---:|---:|
| Chromium | 44px | 701.17px | 786px | 84.83px |
| Firefox | 44px | 700.50px | 786px | 85.50px |
| WebKit | 44px | 701.38px | 786px | 84.63px |

三次均先正常滚动，再执行不触发提交的 `trial` 可点击性检查，并核对完整纵向边界框。run51 中途滚动截图的遮挡没有通过改 CSS 掩盖，已有正常滚动可达性由本轮实际断言与截图建立。

### 同一构建的实际冷、热载入记录

| 引擎 | 冷登录可输入时点 | 热登录可输入时点 | 热聊天可输入时点 | 三次 CSS 请求数 |
|---|---:|---:|---:|---:|
| Chromium | 223.3ms | 68ms | 241.4ms | 1 / 1 / 1 |
| Firefox | 362ms | 126ms | 279ms | 1 / 1 / 1 |
| WebKit | 246ms | 87ms | 259ms | 1 / 1 / 1 |

每条测量同时保存 DCL、请求数、传输字节和编码体积。run52 为建立确定的网络故障前提显式使用 `serviceWorkers: block`；run51 默认允许 Worker，因此这些值不能被写成同等条件下的性能提升。精确 JavaScript 解析耗时未测，未支持的 Long Task 观测保持未知；本轮 Chromium 支持观测且三次测量未记录长任务。PWA/推送由独立 Chromium 套件使用实际 Worker 验证，模拟 Push 不等价于实体手机锁屏实收。

产品源码、24 个构建产物和 191 个静态源文件与 run51 相同，入口仍为 `/static/dist/app-DFTX33VB.js`。此前 Node24 本地 build/check、275 项 Node 与 23 项构建/审计结果保留真实执行时间；run52 再次在 7 个 Node22 Linux/Windows 门禁验证相同产物，两份夹具调整没有重新构建产品。`frontend-25.json` 已更新全部 25 条实现/验证元数据，并保留原始 8 个字段、过去证据与未测人工边界。209 项参考数组及 35/79/95 的分类完全不变，只更新应用实际运行范围；其中 206 项未逐个实操的上游组件没有被改成已验证。

## PR5 补修轮：CI57 原始失败与 Run58 待验

本节追加后续证据，不修改前述首轮结果，也不改 `frontend-25.json` 的 25 条完整需求数组或 `components-209.json` 的 209 条参考数组。原文件中 `current_build` 等字段仍属于首轮冻结记录；三个 JSON 的顶层 `review_followup` 记录本节的后续状态。

### CI57：保留完整失败形状

[CI57 原始运行](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43578124182) 测试 head `19d9162fc9395f9c140ca13545f5975e9d74ea81`，日志确认实际 checkout 为 `568111d44b83baecf2f0a5683914294604713fd3`。33 份报告中，31 份通过、Sprint 不完整、WebKit 聊天交互失败。

| 原始记录口径 | 实际数量与含义 |
|---|---|
| 已记录 checks | 1012：1010 项通过，2 项显式 `ok:false` |
| 独立顶层断言失败 | 1：WebKit 聊天第 4 个复合检查中止，未追加到 `checks` 数组 |
| 未形成完整检查记录 | 41：Sprint 后续 36 项未执行；聊天当前 1 项中止、其后 4 项未执行 |
| 独立连续性检查 | 三引擎 990/990，通过原始报告逐条核对 |
| Agent 与录音范围 | Agent 13、Composer 9 均实际完成；这两套仅 Chromium，使用合成服务和模拟麦克风 |

Sprint 的 Chromium/Firefox 均在要求“54 条看板记录且 `aria-busy=false`”时等待 15000ms 超时，位置为该候选脚本第 187 行。失败截图可见 `50 / 54` 和加载更多按钮；当轮未保存失败引擎各自的完整 range 回执，因此不能仅凭截图或 WebKit 的最后请求尾部认定当时精确竞态。三个引擎的温热分钟检查均已实际通过：54 条 ID 保留、焦点和滚动稳定、0 次整页读取、0 次列表 DOM 变动；实际投影返回 200、稀疏时钟数据且请求/响应稳定版本一致。

WebKit Sprint 25/25 完成，包含两种发布回执丢失恢复、缺失附件提示及停止未决发布后的迟到 409。对应 Chromium/Firefox 后续项没有执行，不能据此声称三引擎已完成发布恢复。WebKit 聊天交互则在 `assert.ok(!stream.next.includes('水墨渐显'))` 失败；它只记录了前 3 个完整检查，独立修复必须在下一 CI 重新验证。

主浏览器 ZIP 为 21,454,123 字节，SHA-256 `3ca6e2f04e5f097a9a10f4939d04bb35a114aab58635ec6c5c268d8db4ce65e4`；连续性 ZIP 为 704,564 字节，SHA-256 `e5f9adfe25ddb76259e421f4d48cc3821efa11de52ca591c8ab99bf860e372f0`。两者均与 GitHub 官方元数据匹配。16 个主 runner 中只有 Sprint 非零；Agent 的 5 个 runner 全部为 0。完整逐槽记录位于本次证据目录 `ci-evidence/43578124182/`。

实际查看了 Chromium 看板失败图、WebKit 手机发布恢复图以及连续性恢复截图。恢复面板文字与操作可读；这些截图只说明对应 CI 视口的实际渲染，不证明实体软键盘、系统权限或真实设备投递。冷/热载入记录仍保留服务 Worker 策略；精确 JavaScript 解析耗时仍未测。

### 列表修复的局部红绿证据

隔离提交 `34e55ab3f7d5e907b759fe14b69658c675612410` 修复列表各自的稳定版本归属：首页推进共享投影后，不能把旧分页集合当成同一版本。停在设置或来源页时，已认证的通知/事项/账号稳定变更也会标记列表失效；原已加载范围保留，纯分钟变化不触发失效。请求在开始时捕获版本和失效代次，跨视图、跨代次的旧 pending 请求不能被新刷新复用。

另外，后台刷新期间用户明确点击加载更多时，保留一次同账号、同筛选、同视图的追加意图。重复点击合并；临时禁止后台绘制与真实网络失败分开处理；账号、路由、筛选变化继续取消迟到操作。已用真实分页、轻量投影、列表时钟及数据同步控制器复现修复前失败；没有通过延迟夹具绕开这些产品问题。

| 已执行的局部验证 | 结果 |
|---|---|
| 新增控制器回归 | 27 项，包含新增/删除/状态变化、54 条范围、在飞旧请求、加载更多意图、临时绘制门禁及真实错误 |
| 新旧相关定向检查 | 49/49，通过；原有 22 项保留 |
| 完整 Node 检查 | 329/329，通过；原有 302 项保留 |
| 构建与构建一致性 | `npm run build`、`npm run build:check` 实际通过 |
| 实际 HTTP 构建验证 | 2/2，通过，含产物有效性、缓存/压缩及过期构建回退 |

本地产物入口为 `app-A52BRFJG.js`，25 个文件、194 个静态源；CSS 保持 `styles-BKR4PFDD.css`。这些是隔离修复提交的本地结果，未替代整合候选的全量测试。完整红测原文、命令结果和摘要位于 `artifacts/list-cache-revision/verification.json`；其局部指纹不冒充后续 CI 的整合指纹。

### Run58：目标与已知边界

[整合候选 Run58](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43581184272) 的 head 为 `9e86a1e9b798071e870a0e35d73b46610d435988`，实现指纹为 `81f4a6742ac738468295e007da2571db9d1ea09275eaf11530d0fc02944d3f31`。截至本节记录，原始完整浏览器报告尚未发布，因此 1056 项主浏览器、78 项 Sprint 和 990 项连续性仅为待验清单数量。

Sprint 保留原 25 个检查的名称与顺序，在最后的页面错误检查前新增一个真实跨页面场景；每引擎增加 1 项，共 26 项。该场景分别验证首页已读取新投影、设置页只消费稳定变更信号而不读投影后，返回原筛选列表能够得到真实新增、删除和状态变化后的 ID 与总数。原 360 秒门槛、分钟刷新 0 次整页读取和 0 次 DOM 变动、54 条范围以及看板真实移动断言均未放宽。

实体中文软键盘、读屏、200% 缩放与真实麦克风权限仍保留原验收边界。209 条参考仍为 35 项优先候选、79 项条件候选、95 项暂不采用；未逐个操作的 206 项上游组件没有被改成已验证。


## PR5 后续记录：CI58 失败、反向加载竞态补修与 Run59 待验

### CI58 的完整原件与实际执行范围

[Run58](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43581184272) 已结束，9 个作业中 8 个成功、主浏览器作业失败；该候选没有因其它门禁通过而获得合并结论。原件 head 为 `9e86a1e9b798071e870a0e35d73b46610d435988`，job 日志确认实际 PR checkout 为 `a39babb0406615384323b3ae346ca722a8253f3d`。

| 完整原始报告口径 | 实际结果 |
|---|---|
| 浏览器报告槽 | 33 份：32 份完整通过、Sprint 不完整 |
| 已记录检查 | 1001：998 项通过、3 项显式失败 |
| 后续未执行 | 55 项，全部属于三引擎 Sprint 后续检查；没有另一个未记录的顶层断言 |
| Sprint | 23 项实际记录：20 通过、3 失败；目标 78 不能当作已执行 |
| 连续性 | 三引擎 990/990，官方 ZIP SHA、逐项报告与 runner 均核实 |
| 独立 Agent / Composer | 13 / 9 均实际完成；只覆盖 Chromium、合成服务与模拟麦克风 |
| 独立聊天交互 | Chromium 9、Firefox 8、WebKit 8 全部完成；真实 stream 观测与原断言均在 |

Chromium 在移动后等待 DOM 恰好 50 条超时。其保存的原始 ID 表明：界面实际保留 54 条，且完整顺序精确等于将原第 50 号索引卡片移至第 49 号索引后的排列。这里不能把正确保留范围的产品行为改成截断列表来迎合夹具。Firefox 和 WebKit 则在切回清单、点击加载更多后等待 54 条超时；这两个实际失败与后续独立控制器复现分开记录，原 CI 请求尾部不能证明每个重叠时点。

三个温热分钟检查都真实通过：54 条完整 ID、焦点、滚动均保留，0 次整页读取、0 次列表 DOM 变动，实际投影 200 且稳定版本与稀疏时钟协议一致。既有看板 28、视觉 168、Pilot 33 以及 6 个真实 cold-import hold 也通过。Sprint 后续的发布重试、未决取消、新跨路由案例、旧查询竞态、手机发布按钮边界均未执行，不能沿用旧轮结果声称本轮已完成。

主浏览器 ZIP 为 21,824,453 字节，SHA-256 `2c7e14368ec109594673bfd3c7fe3ad01d28cf9542a2f0c3b80e45b026f0c9cc`；早期诊断的全部 33 个文件与最终 ZIP 对应文件逐字相同。完整审计为 `ci-evidence/43581184272/browser-report-audit.json`，SHA-256 `a659fe1987f3ba444f5bf9af87b611e3885104aa5b137042058facc58e1ec8e2`。实际看过 Chromium 看板保存截图与 WebKit 清单读取截图；截图只作真实视口佐证，精确数量/排列来自原始 ID 回执。

### 用户先加载更多、后台后刷新：产品修复与局部门禁

独立控制器红测确认另一种请求顺序：用户的下一页已经在飞，新的稳定数据刷新才到来。原实现取消旧 append 后，只按已提交的 50 条前缀刷新，导致用户原 promise 返回空值、列表留在 50 条并仍显示有后页。该缺陷有真实控制器复现，不能通过先等待偏好保存、降低 54 条门槛来掩盖。

隔离提交 `d28d93d2631e7720525013090db547e430a72b62` 让明确的加载更多从开始即保存一次固定范围目标与原 promise。同账号、筛选、视图中的新刷新接管目标，旧请求结束不能提前完成新操作；重复点击合并。账号/路由/筛选变化继续取消；临时后台绘制门禁与真实网络/响应格式失败仍分别处理。正式移动和撤销明确保留全部已加载范围。

| 已执行局部验证 | 实际结果 |
|---|---|
| 新增正式用例对冻结源码 | 12 项：6 失败、6 通过；原红日志保留 |
| 修复后相关用例 | 58/58，通过 |
| 完整 Node | 341/341，通过；原 329 个检查名称完整保留，新增 12 个 |
| 构建与一致性 | build、build:check、GenUI catalog check 实际通过 |
| HTTP 构建验证 | 2/2，通过 |

此外还有独立审查脚本的 4 个反向顺序红绿场景，绑定其记录的中间源码 SHA；这 4 项不重复加到 341 项 Node 总数。最初一次扩展红测因测试自身尚未释放 hold 而中断，原 log 保留且不当作完整测试结果。最终证明在 `artifacts/list-more-refresh/verification.json`，SHA-256 `d6831415dd474fdf7e92f9f1bd176a04520badc660baca4c023a30d27c42f741`。

新构建入口 `app-SMVSHCNZ.js`，CSS 仍为 `styles-BKR4PFDD.css`；25 个产物文件由 24 个哈希产物与 manifest 自身组成，静态源为 194 个。最终本地实现指纹为 `e4d5d6adaa2f86c0eb0de6c8c8d856e16d3584dad0336242d68f1f855eb83157`。这些局部结果不替代浏览器实跑。

### Run59 的待验合同

[Run59](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43583884442) 的 head 为 `6701b6534331b9dddd64bdd67a38ac2e524681a9`，tree 为 `2cc780721a3a53acbe5440718b2862e87d809152`，实现指纹与上述冻结版本相同。截至本节记录，其完整浏览器原件尚未发布；1056 个主浏览器检查、78 个 Sprint 检查、990 个连续性检查只是预期清单。

Sprint 保留全部 26 个检查名称、顺序及 360 秒门槛。移动后先要求完整 54 条精确新顺序，再通过真实不同查询、回到原查询重新建立首屏条件；首次 HTTP 50、DOM 50、第 49 号索引卡片、后续加载 54 的原断言全部保留。重建请求精确限定真实 GET、查询、board 排序与无 cursor；没有按正确内容挑选响应。新增逐引擎清单请求链与失败时 DOM 回执，供下一轮诊断。

原 25 条需求数组、209 条参考数组与全部原非后续字段未改变；旧 `review_followup` 全文保留，新的 `latest_review_followup` 及其中逐项 evidence overlay 单独表达后续范围。实体软键盘、读屏、200% 缩放、真实麦克风权限与未逐个实操的上游组件边界继续保留。



</details>

## PR5 候选验收冻结：CI63，2026-11-14T12:18:27.857754+00:00

本节是 **2026-11-14T12:18:27.857754+00:00** 的候选验收快照，追加到全部先前失败和局部验证记录之后。[CI63 原始运行](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43592108675) 的 9 个必需作业已实际成功；33 份浏览器报告、连续性报告及本节列明的人工截图范围均完成核验。候选 head 为 `70226e910b7fe2ecdfd49b0a34dcd62ba00484bc`，实际 PR checkout 为 `e3adde8146fec6fbb9f4f63057fabb97a6a8d975`，对应 tree `894b7ef5b4c77da666177649e853afb0811f1359`，Linux 实现指纹 `4e4d3e2ca56b7ccbc8e9bd9a197b07e539ea8d8d987d47656b7486504b991634`。这里明确区分候选测试与后续 main 交付；[PR #5](https://github.com/hxjyaohaohaode/luojiaxinshi/pull/5) 和 [Actions 交付记录](https://github.com/hxjyaohaohaode/luojiaxinshi/actions) 标识实际合并及 main push 运行。

完整可复核原件索引见 [CI63 成功审计](../audits/sprint-review-ci-63-success.json)。原 25 条完整需求数组、209 条完整参考数组以及原 `application_runtime_evidence` 均保持逐值一致。三个 JSON 的旧 `latest_review_followup` 全文移入追加的 `latest_review_followup_history`；新 `latest_review_followup` 给出本节候选事实，`frontend-25.json` 另有覆盖全部 25 条的当前证据 overlay。原数组中的 Run52 和旧顶层字段属于各自冻结时点，不被改造成 CI63 的执行记录。

### 实际门禁与执行范围

| 门禁 | 本轮实际结果 | 范围 |
|---|---|---|
| Linux 后端 | 139 个文件、1875 个唯一用例：1873 通过、2 声明跳过，0 失败/错误 | 保留平台跳过原名 |
| Windows 后端 | 139 个文件、1875 个唯一用例：1874 通过、1 声明跳过，0 失败/错误 | 各片与汇总原件核对 |
| Node | Linux / Windows 各 358/358 | 旧用例身份保留，非把两平台相加成唯一用例 |
| 浏览器 | 33/33 完整报告，1056/1056 正式检查 | 0 缺失、0 错误；16 个主 runner、5 个 Agent runner 均退出 0 |
| Sprint | 78/78，三引擎各 26 | 旧名称/顺序和 360 秒门槛保留 |
| 连续性 | 990/990，三引擎各 330 | 全部原检查身份与 runner 核对 |
| 看板移动 | 28/28 正式检查，另有 18 份实际阶段观测 | 18 份观测不额外计入检查总数 |
| Agent / Composer | 13 / 9 实际完成 | 仅 Chromium；合成服务与模拟麦克风 |

主浏览器 ZIP 为 22,568,012 字节，SHA-256 `b63b868747042d023023353f543a8aead275d3ed1a9ffdad3249195a62735bcb`；连续性 ZIP 的 SHA-256 为 `39100d6a8db7e7c5ab12174f2ad6af3e77869f2eb6c12b14f42a9a7b9d3cabb0`。早期诊断的全部 33 个文件与最终 ZIP 对应成员逐字节一致，正式 33 个报告与原 ZIP 绑定。成功审计还逐项验证了实际请求、响应、ID 集合和几何值，未用报告总数替代业务语义。

### 已整合的前端行为改善

1. **发布回执丢失可恢复。** 正式发布按上次确认内容和请求身份安全重试，已删除的草稿不再挡住幂等回执；重载后也能恢复。用户后来输入的新草稿与待重新选择的附件提示保持独立。明确停止尚未提交的请求后，迟到请求返回 `publication_cancelled`，不会把“停止未决请求”混成撤回已发布公告。
2. **分页、筛选和跨页面缓存保持真实全量语义。** 服务端在完整集合筛选与排序后分页；看板上移第二页记录后，已加载 54 条完整顺序保留。首页推进投影或设置页只消费稳定变化后返回原列表，18 个真实增删/状态场景都按 3→2→1 的精确 ID 与总数恢复。
3. **分钟变化与稳定数据分开。** 三引擎实际温热时钟场景保留 54 条记录、节点、焦点和滚动，整页读取 0、列表 DOM 变化 0；相同分钟信号不重复读取投影。实际新增、删除和失效代次仍触发必要刷新，不以共享缓存“看起来没变”漏掉未加载记录。
4. **加载更多与强制刷新不丢用户意图。** 前后台两种请求顺序、重复点击、临时绘制保护、真实网络错误和旧请求收尾分开处理。成功业务 mutation 的 force 刷新不复用旧 pending 结果；非强制同范围读取仍去重。原范围、账号、路由、筛选边界继续守住。
5. **手机核心操作与真实反馈保持可达。** 勾选、更多、拖动和发布采用分离的 44 px 操作区；失败不播放完成动效，待提交事项打开办理；保存成功后才反馈。三引擎手机发布按钮正常滚动后完整位于底栏上方。
6. **聊天、录音和认证恢复有明确生命周期。** 文本和发送保持优先，菜单可用键盘退出；录音分段转写保留手写内容，停止清理及失败重试通过。桌面聊天采用不会形成意外横滚的布局边界，三次实际录音快照 `scrollLeft=0`，先前左侧裁切没有出现在本轮图中。真实 401 后同文档登录接纳清除旧登录提示，失败或尚未完成的认证不会提前清掉错误。
7. **来源、阶段、提醒与引导回到真实业务。** 来源试读/生效/回滚、真实发布方、阶段证据与核实入口保留；提醒能力、本人事项/来源覆盖和设备边界有可查看依据。首次引导可跳过、可找回、按账号隔离，用户自填教师不授予校园发布权限。
8. **构建入口与读取成本可审查。** 本轮为 `/static/dist/app-EXBTH7EL.js` 和 `/static/dist/styles-BHHEBXRE.css`，194 个静态源对应 24 个哈希输出与 manifest。Linux/Windows 实际 build:check 一致；首页/日历使用完整轻投影，详细正文按需获取，路由动态模块的冷入口有真实浏览器覆盖。

这些行为对应源码包括 `static/campus.js`、`static/campus-publication-submission.js`、`static/paged-list.js`、`static/list-clock.js`、`static/workspace-projection.js`、`static/app.js`、`static/auth.js`、`static/system/action-targets.css`、`static/system/chat-refinements.css` 及各业务模块；更完整的跨域说明见 [补修总记录](../audits/SPRINT_REVIEW_FOLLOWUP_2026-11-14.md)。

### 动画前提、回执和视觉观察分别核验

本轮看板先记录并等待真实路由初次入场结束，再启动移动阶段观测；保留 mouse-up 后原 0 动画断言，并在实际 POST 回执、之后发起的刷新 GET 及对应 UI 完成后再核对。18 次观测覆盖成功、完成、取消/外部放下及真实 409；取消路径没有等待不存在的 POST。首次三引擎各实际观察到 5 个初次入场动画，此事实没有被写成所有运行必须出现 5 个，也没有倒推 CI62 的唯一触发时序。

实际打开了本轮 18 张原图：三引擎手机跨页面列表、手机草稿、手机聊天、桌面跨页移动和 390 px 看板，以及 Chromium 触摸、Composer 录音与短视口图。手机列表的侧栏已关闭，旧登录提示不再覆盖内容；发布与聊天核心控件可见。看板的临时保存 Toast 位于底栏上方，会覆盖最低卡片的一部分，撤销与关闭仍可见，因此未把图片概括为所有卡片始终无遮挡。精确顺序、44 px 命中区域和 0 横滚由对应原始 DOM/几何补充，不能只靠截图推断。

### 本轮冷、热记录

| 引擎 | 冷登录可输入时点 | 热登录可输入时点 | 热聊天可输入时点 | CSS 请求数 |
|---|---:|---:|---:|---:|
| chromium | 244.4 ms | 79.4 ms | 250.2 ms | 1 / 1 / 1 |
| firefox | 418.0 ms | 143.0 ms | 298.0 ms | 1 / 1 / 1 |
| webkit | 264.0 ms | 73.0 ms | 288.0 ms | 1 / 1 / 1 |

共 9 条真实记录同时保存 DCL、资源数、传输与编码字节及可用的 Long Task 观测。本轮网络夹具显式 `serviceWorkers: block`；不同 Worker 条件的旧轮不能直接当作同条件速度对比。热缓存零传输不是失败；精确 JavaScript 解析耗时保持未测。PWA/Push 是独立 Chromium 场景，不能由这里推断实体手机锁屏实收。

### 209 项参考定位及保留的验收边界

209 项账本原分类为 **35 项优先候选、79 项条件候选、95 项暂不采用**，逐条数组和原采用决定完全不变。实际上游 demo 与完整源码深核只有 **#114 prompt-bar、#115 swipe-toast、#133 spring-check**；吸收交互机制并适配既有品牌/API，没有将未实操的 206 项改成已验证，没有安装 209 项依赖，也没有为此添加 React/motion/Hugeicons 运行时。既有许可记录和上游操作中的限制保留在 [上游源码记录](reference-source-review.json) 与 [209 采用账本](components-209.json)。

当前自动证据与人工截图不替代实体中文输入法/软键盘、真实麦克风权限、读屏、200% 缩放、真实外部服务与设备投递，或累计真实校园试用。LJ-106 等相应边界在新 25 项证据 overlay 明确保留。CI55–60 的失败、CI61 的功能通过与视觉问题、CI62 的看板/Composer 失败均在独立原件中保留；CI62 缺失 Composer 正式结果时，没有把源码推断的前 7 个里程碑冒充已上传的 7 项通过。本轮绿色只证明本节记录的候选、环境与检查范围。
