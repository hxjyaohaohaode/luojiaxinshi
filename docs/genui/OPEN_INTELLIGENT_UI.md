# 生成式智能 UI：OpenIntelligentUI 适配

复杂交互任务现在由现有 Agent 通过 `compose_interface` 提交简短编排目标，再由专用 UI 生成器流式生成 HTML、CSS 和 JavaScript。明确请求互动且上下文足够时，直接提供编排入口，省去重复加载协议；其他任务仍可按需加载 `openui_capabilities`，直接 `generateSandboxedUi` 和历史组件图继续兼容。用户问题、已有证据、当前个人权限与真实工作台操作由原聊天链路管理，简单问题可直接回答。

## 上游与实际采用范围

参考 [CopilotKit/OpenIntelligentUI](https://github.com/CopilotKit/OpenIntelligentUI)，核对提交 `8391a94c1c3939c679e40ddd7bfc08a9ef690e70`（MIT）：

| 上游文件 | 本项目采用的机制 |
| --- | --- |
| `docs/interactive-answers.md`、`apps/agent/src/visualization_router.py` | 按任务选择文字或可操作界面；输入、假设、结果和真实操作区分；用户主动追问 |
| `apps/app/src/components/generative-ui/open-generative-ui/schema.ts` | `initialHeight → placeholderMessages → css → html → jsFunctions → jsExpressions` 顺序；正文与行为分开传送 |
| 同目录 `renderer.tsx`、`frame-content.ts` | CSS 完成后显示渐进 HTML；就地更新 DOM；持续测量高度；保留同一画布到最终交互 |
| `apps/app/src/lib/sandbox/sandbox-functions.ts` | 验证宿主桥参数；显式用户操作才继续模型；外部原文按已登记来源打开 |
| `packages/design-system/src/index.ts` | 主题变量、原生表单、SVG 色组和图形辅助类；适配为本地共享设计系统，统一珞珈绿、字阶、间距与状态 |

本项目将这些机制适配为 Python/FastAPI、现有 SSE 与浏览器原生 iframe；模型仍为已配置的 MiMo。不新增 CopilotKit、Next.js、LangGraph、Jev、Websandbox 或 CDN 运行依赖。宿主桥兼容 `Websandbox.connection.remote.sendPrompt/openLink` 的调用写法，执行边界由本项目实现。上游许可保留在 `docs/licenses/open-intelligent-ui/LICENSE.txt`。

## 真实流式路径

1. 主 Agent 根据原问题和已登记证据提交 `compose_interface`，专用生成器只负责展示与代码，不获得工具权限。直接工具参数流和编排器的 JSON 流均使用同一个增量解码器。证据 E 编号沿用本轮追加索引，避免交接后换号。
2. `app/openui.py::UIStreamDecoder` 跟踪 JSON 路径、转义、Unicode 与数组边界，在整个 JSON 和 JavaScript 完成前提取 CSS/HTML。`packet()` 只发送追加内容，避免反复传送整页。
3. 原 `POST /api/conversations/{cid}/messages/stream` 增加 `ui_preview` 事件。`grounding` 与 `work_summary` 原样转发预览；预览先单独落盘为未完成检查点，可在刷新与断线后恢复，不当作已核验回复保存。
4. `static/chat.js` 累积预览，`MessageRenderer` 将其交给 `SandboxRenderer`。CSS 完成后，隔离画布逐段就地更新 HTML；代码尚未完整时根节点保持 `inert`。
5. 完整 UI 字段与代码结构检查后发送 `localReady`，同一个 iframe 按序执行完整的函数与表达式，先启用本地计算、筛选及输入。此时宿主桥仍拒绝操作，普通操作按钮保持禁用；明确标为 `data-ui-local` 的本地按钮可先使用。正在核对的内容不保存为已验证历史。
6. 原有独立证据复核通过后，服务器保存产物并发送正常 `delta/done`；同一 iframe 放开宿主动作，保留已经调整的参数、计算与阅读位置，不重新执行初始化。
7. 画布内 `ResizeObserver` 按内容和容器变化报告高度；高度不使用初始提示值锁死，未出现 HTML 时不占用整块预估高度。原文与计算说明可用 `details` 展开。

这条路径没有在生成结束后人为切片播放预览。复核期间可以阅读界面并进行本地操作，发起模型请求、打开来源与保存进度等待复核完成。中断或失败的预览不会变成已验证的历史产物。

## 外观与生成耗时

`static/genui/design-system.css` 预先提供主题、基础控件、SVG 色组与可组合布局；模型只写当前工具特有的样式。可直接组合 `ui-split/ui-grid/ui-stack/ui-field/ui-result/ui-value/ui-primary/ui-list/ui-segmented` 等原语，不固定整页模板。重点结果、参数与主操作各自成组，窄屏自然纵排。提示词限制重复统计卡、额外换算和无用分析文案，减少生成量与误算入口。

简单试算使用隔离运行时的 `CampusUI.form({inputs,outputs,digits,error,prompt})`：`inputs` 定义已有控件的范围、整数和步长，`outputs` 只放结果元素 ID 与计算函数，`digits` 是顶层精度（0..6）。共享实现处理空值、校验、错误清除旧结果、即时重算和显式追问，减少每次生成的重复程序。`prompt` 独占该按钮的点击处理，阻止后加监听重复发送；每次真实手势最多发出一个宿主请求。仅对没有竞争顶层值、也没有同名结果元素的情况，兼容把数字 `digits` 放在 `outputs` 内的明确拼写，计算函数不改写。

`MIMO_UI_MODEL` 默认 `mimo-v2.6-pro`，`MIMO_UI_THINKING=false` 只用于独立的展示编排调用；需要时可显式开启。主 Agent 的需求与事实判断、独立 Pro 审查继续完整思考，输出上限保持配置值。编排器没有业务工具，复用同轮证据并再次通过引用与独立复核。审查输入保留全部 CSS/HTML/脚本与 claims，但解开重复 JSON 围栏，减少转义开销。处理记录分别记录各阶段实际模型与思考模式。

编排工具使用模型生成的专门超时，避免普通工具 45 秒限制造成截流；超时直接终止当轮，不进入“副作用状态不明”的工具重试。真实速度受模型服务影响，报告分别记录首段 HTML、本地控件可用与最终复核完成，不能用合成延迟替代真实延迟。

## 宿主交互与保存

| 接口 | 行为 |
| --- | --- |
| `CampusUI.sendPrompt({text, values?})` | 用户点击/键盘提交后，在原对话发起下一轮，并通过原 `ui_context` 验证和保存当前原生输入 |
| `CampusUI.openLink({url})` | 只接受本回答证据来源登记的 HTTPS 地址 |
| `CampusUI.hostAction({name, params})` | 原有 `open_sources/open_calendar/upload_material/review_material` 入口；材料 ID 仍在当前会话核对 |
| 原“保存互动进度”按钮 | 原 `PUT .../messages/{mid}/ui-state` 保存；版本冲突返回 409，账号隔离不变 |
| 原生输入的稳定 `id` | 自动捕获文本、数字、选择、滑块、勾选；刷新后恢复，并派发输入事件重算 |

服务器从真实生成的 HTML 提取输入 ID、类型、选项、初始值和标签，再检查快照与 `interaction.selections`。客户端不能凭空增加输入或替换标签；初始值与已改变值分别标识。自定义视图选择可同步到带稳定 ID 的隐藏输入。任意 JavaScript 堆、动画时间和第三方组件内部状态不自动持久化。

独立复核要求修正界面时，旧脚本在原隔离文档中停止，新稿使用新的隔离文档。只恢复用户实际改过、且 ID、类型、标签、范围、步长与选项仍一致的字段；未改过的初值采用新稿。这样既保留兼容输入，也不会用旧初值覆盖纠正后的事实。普通流式到最终完成仍保持同一 iframe，不走修正重建路径。

## 执行边界与恢复

生成代码只在 `sandbox="allow-scripts"`、无 `allow-same-origin` 的隔离文档运行。主应用 CSP 保持原严格脚本规则；仅 `/static/genui/sandbox.html` 允许自己的引导脚本与内联生成脚本，禁止连接、子框架、Worker、表单提交和远程图片。生成标记进入 iframe 前移除脚本标签、事件属性与嵌入对象，脚本只通过完整且经过结构校验的独立通道启用。

宿主验证消息来源、一次初始化的私有通道标识、动作参数和来源网址；运行时桥只接受真实点击/键盘操作，不能在加载、普通输入变化或计时器里自动调用。生成代码读不到宿主 DOM、cookie 或账号存储。桥不会直接写待办或日历；真实写操作继续由原有 Agent 业务工具执行。

JavaScript 运行错误会停用该画布的交互并显示恢复信息；文字内容与原聊天的重新生成入口仍可用。独立复核与格式检查不能证明所有生成程序都正确，新增任务仍须在实际界面中核对。

## 验证入口

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_openui.py tests/test_genui_state.py tests/test_agent_chat.py
node --test tests/genui-openui.test.mjs
.venv/Scripts/python.exe scripts/run_openui_browser_checks.py
```

浏览器入口在 8794 启动独立合成账号，使用实际编排入口、增量解码、原聊天接口与数据库，覆盖 Chromium、Firefox、WebKit 的生成中首段可见、复核中本地计算、同画布开放宿主动作、输入保留、计算与筛选、非法数值、原生键盘、保存刷新、当前结果复制、手机/键盘高度、显式追问与隔离。报告在 `artifacts/openui-browser/{browser}/report.json`；合成延时不代表真实模型速度。WebKit 截图同步器注入的空 `body {}` 被主应用 CSP 拒绝时，仅在截图期间单独登记为工具日志，不放宽主应用 CSP。

共享表单按钮另行注入重复监听，检查一次点击只生成一条用户消息；修正回归同时检查已编辑字段保留与未编辑初值更新。真实模型产物可通过 `OPENUI_REPLAY_FILE=artifacts/…/generated-ui.json`、`OPENUI_VERIFY_SCRIPT=scripts/verify_openui_generated.mjs` 离线重放；回放仅将已发布的显示引用恢复到当前合成输入的证据编号，再走正常编译，CSS/JavaScript 不改写。

真实模型验证沿用 `scripts/verify_agent_adaptive_live.py --case openui --allow-paid-synthetic-test --output-name openui-live`：使用临时账号、合成输入和原聊天完整复核链，会计费，不进入 CI。生成产物保存在 `artifacts/openui-live/generated-ui.json`。单次通过不能代表所有题型的生成质量或延迟。

刷新恢复通过原会话 GET 返回 `preview`，无需重复生成。`preview.text/ui/revision/sequence` 与 `genui.raw/validated` 分开；失败、取消的预览可读且代码保持禁用。完整版本与未完成版本的主动回看选择均保存在服务器；模型上下文只使用完成回复，回看失败稿不会把该草稿送入后续事实依据。完整执行轨迹改由摘要里的短入口打开独立窗口，默认摘要不嵌入时间线或步骤表。
