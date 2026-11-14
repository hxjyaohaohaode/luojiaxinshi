# 冲刺前端逐项审计与证据边界

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
