# 深度交互与内容优先改造

承接全量主动监控、证据、自动追踪、纠正、权限与试点要求。本次新增重点是信息优先级、连续消息可靠性、引用回复、表情与图片、生成式 UI 与实际操作的衔接。测试结果只代表覆盖场景；不得据此宣称产品全部达标。

## 实测基线

- 真实讲座通知在 390×844 视口下，办理路径起点 y=789、首个可选步骤 y=1267；两次来源修订被展开成两块重复的大状态卡。
- `static/chat.js` 在上一条请求确认前拒绝连续发送；补充在确认后直接替换流。没有有回执的快速消息队列。
- 已有点赞/点踩、回复版本、分支、附件、互动快照与 sandbox，不再另建工作台或替换技术栈。

## 当前验收清单

- [x] 通知首屏先显示关键时间、办理步骤和实际风险；流程/来源/原文记录后置，重要修订保留紧凑提示。
- [x] 引用本人/助手消息、撤销引用、返回原消息、刷新恢复；后端按账号和会话校验，拒绝伪造片段。选中文字引用已有实现和片段 API 回归；原生手机选区手柄手势未验收。
- [x] 表情反馈与输入、本人 GIF 图片发送和私有预览，持久化且账号隔离；GIF 明示模型未读取该格式，不能冒充官方文字或动画理解。
- [x] 快速多条消息全部保留，顺序提交，短时批次合并；503 未接收、刷新及同编号重试均经过浏览器验证，不丢消息或多造一条输入。
- [x] GenUI 内容优先、选择带入追问、快照保留、原生数值校验和重置；真实写入继续走原有权限/证据/业务回执，不由 iframe 文案声称成功。
- [x] 通知列表增加“为你优先”，使用共享、可核验的时效投影；原有首页和通知策略继续遵守过期、质量、相关性和用户纠正规则。
- [x] 留存真实模型、浏览器手机/平板/桌面、多条发送/503恢复/引用/GIF/界面追问证据。没有据此宣称正式试点验收通过。

## 结构与业务改变

| 改变 | 实现入口 | 实际约束 |
|---|---|---|
| 内容先于状态 | `static/notice-focus.js`、`static/system/content-priority.css`、`static/app.js`、`static/notice-intake.js` | 真实通知 390×844：草稿起点从 y=789 到 y=203，首个步骤从 y=1267 到 y=253。两次来源修订折叠为一项入口，原文比较和确认保留。 |
| 统一的时间与优先级 | `app/notice_lifecycle.py:focus_projection`、`app/proactive_policy.py:assess`、`static/library.js` | 仅当前且通过核对的草稿突出关键时间；日期、时间必须在原文中配对，不补年份、不把活动开始当结束。前后端时间戳单位一致。未知内容仍可查找。 |
| 逐条回执与快速消息 | `static/chat-outbox.js`、`app/message_interactions.py`、`app/workspace.py` | 220ms 收拢短输入，每批最多16条，后续继续排队；每条独立 ID、正文摘要与回执。整体事务校验，部分旧回执或同 ID 改正文拒绝提交。未确认输入本机暂存，恢复前核对服务端回执。 |
| 引用的事实边界 | `app/context_engine.py`、`app/grounding.py`、`app/genui_state.py` | 引文只能来自本会话真实完整消息；旧助手文字仅作上下文，不提升为用户原话或官方证据。分支、导入导出重映射引用，失去原引用时保留脱离链接的快照。 |
| 反馈及时同步 | `static/chat-feedback.js`、`/api/conversations/{cid}/message-feedback` | emoji 与赞踩独立于模型执行；幂等写入、15秒可见页检查、页面恢复焦点检查。独立客户端移除 emoji 后，当前浏览器自动消失；不覆盖未提交的 GenUI 参数。 |
| 界面状态与输入可靠性 | `static/genui/sandbox-runtime.js`、`app/openui.py`、`app/genui_state.py` | 合并原生 min/max/step 校验；空值不是0；错误清除旧计算。原生 reset 等默认动作结束后重算。服务端能读取包裹式 label；无效控件可以保留编辑，但不会伪装成有效提交值。 |
| 主结果阅读位置 | `static/chat-viewport.js:revealLatestChatReply`、`static/genui/chat-presenter.js` | 已完成的互动工具首次显示时定位到结果，避免手机浮动标题遮挡；本轮截图和输入检查覆盖390、834、1440像素。用户离开自动跟随时不强拉回。 |
| 一致的界面编排路由 | `app/agent_runtime/chat.py` | 修复能力工具仍引导主模型直接写完整代码的说明冲突。预加载或动态发现后都推荐 `compose_interface`；专用 UI 生成器沿用配置，主规划与独立复核保持开启；直接生成协议继续兼容。 |

新增持久表为 `message_quotes`、`message_emojis`、`message_input_receipts`，由原数据库迁移与备份校验管理；没有建立第二套通知事实库、身份体系或工作台。既有私有附件、SSE、GenUI sandbox 和业务动作接口继续复用。

## 真实模型与浏览器证据

`scripts/verify_deep_interaction_live.py --allow-paid-synthetic-test` 通过原应用的 chat/Agent/Harness/grounding/GenUI 路径请求实际 MiMo。使用隔离合成账号与数据库；没有读取实际用户会话，也没有向真实联系人发短信或邮件。

| 样例 | 实测结果 | 证据 |
|---|---|---|
| 三条用户信息含两次变更 | 最终保留11月7日16:00、仅报名表，明确合成数据；三份回执完整。修复前18.20秒、复测14.08秒，均通过独立复核。 | `artifacts/deep-live-20261102-150359/results.json`、`artifacts/deep-live-20261102-151422/results.json` |
| 引用后生成互动工具 | 引用持久化，助手旧话不作官方证据，结果14小时、输入、重置与显式追问按钮真实生成；两轮均独立复核通过。 | 同上；各目录 `conversation-turn-2.json` |
| 界面可用与核对完成分开 | 修复前首次HTML52.28秒、控件56.38秒、完整75.19秒；修复后HTML19.52秒、控件26.58秒、完整104.80秒。后者独立复核耗时73.99秒，没有修复重试。只证明该样例更早可试算，不能宣称总体延迟下降。 | `turns[].timeline` 与 `harness.calls` |
| 实际模型界面原生浏览器检查 | 小数天数1.5与空值显示错误并清掉旧结果，重置恢复2×7=14；390/834/1440外层和iframe均无横向内容溢出。 | `artifacts/full-audit-ui/deep/real-model-genui-*.jpg` |
| 合成故障和连续发送 | 实际HTTP503在接收前拒收，刷新保留、同ID恢复后只有一份；慢回复中补充甲乙均进入最终上下文。 | `artifacts/deep-interaction-browser-data/`、`deep/outbox-recovery.jpg` |
| 显式界面追问 | 20/4的当前值发送到既有模型入口；未发送草稿仍留输入栏，接收后才显示“已发送”；刷新恢复已提交参数。 | `deep/genui-followup.jpg`、消息回执和模型调用夹具日志 |

浏览器在独立预览应用中查看真实模型留存结果时不带模型/短信/邮箱凭据，页面会提示 AI 未接通；这不是生产服务缺钥匙的证据。预览中的本地运算、私有快照和反馈 API 仍走相同应用代码。

## 当前全项目质量边界

只读快照 `artifacts/deep-pilot-snapshot.json`：实际19则通知有当前判断，11则通过、7则仍需核对、1则独立核对不可用；13份材料记录仍有读取缺口，不能称已读全。两条官网来源和每天25则自动整理配置仍在，未因聊天改造而扩大调用额度。数据库 quick_check=ok、外键违规0。

完整回归及本次布局末次前端回归的准确结果见本文件末尾验收记录。自动测试不是实际通知全量通过、模型统计准确率或比赛结项的替代证据。复杂生成的最终复核仍有明显延迟；Android/iOS原生选区、GIF动画语义、系统后台投递、公开HTTPS与五天真实试用未验收。任意公众号连续接收、QQ与自有公众号凭据、真实试点短信/邮件送达仍沿用前轮外部缺口，本轮未采购服务器/域名或发送外部通知。

## 本轮最终验收记录

- 上游已重新 fetch，本地 HEAD `7e1e904` 与 `origin/main` 为0/0；保留原有及本轮未提交修改，没有重置、丢弃或推送。
- `artifacts/deep-frozen-suite/summary.json`：105个Python测试文件，1533通过、1跳过、0失败/错误。跳过项为Windows不适用的POSIX TIME_WAIT语义检查。
- 该后端运行中又修正了 `static/chat.js` 和 `static/chat-viewport.js` 的手机结果定位，所以整体 `implementation_unchanged=false`，协调器因此返回退出码1，保留原记录。没有在此期间修改app或tests的Python；末次前端在两处修正后重跑，`artifacts/deep-final-frontend-after-layout.log` 的242个用例全部通过。不能将它改写为一次整个源码树始终不变的全绿运行。
- 真实浏览器另行核验了最终首屏、空会话、原生控件错误、重置、引用、表情与跨客户端移除同步；真实模型生成留存结果与故障夹具分开。最终结果定位已复核，关键结果不再被手机浮动标题遮挡。
- 实际配置密钥对712条可发布路径精确扫描，0处匹配；`.env`仍被Git忽略。`git diff --check`通过，仅有既有换行符提示。没有展示密钥或将其写入报告。
- 本机主服务已按归属验证后重启，`http://127.0.0.1:8765/api/health`返回ok。浏览器实际账号需要重新登录，入口已保留，未代填用户凭据。真实模型留存预览进程已结束、标签已关闭、临时视口已恢复。
- 关闭旧合成夹具进程的操作被自动审批拒绝，工具只返回策略阻止；未绕过，旧夹具仍仅监听本机8793。它使用独立合成数据库，未调用外部模型、短信或邮箱服务。

汇总证据：`artifacts/deep-delivery-result.json`。该文件明确保存整体冻结不成立的原因、末次前端检查、真实模型两轮耗时及外部未验收范围，不以自动测试替代试点验收。

## 参考边界

重新核对 [CopilotKit/OpenIntelligentUI 互动答复说明](https://github.com/CopilotKit/OpenIntelligentUI/blob/main/docs/interactive-answers.md)，采用任务决定呈现、证据与假设区分、本地校验、明确追问和快照原则。GitHub本轮元数据：4115 stars、MIT、未归档、最近推送2026-10-13；不是只看星标。

[Grok Bot 官方交互说明](https://docs.x.ai/grok-bot/chat-and-collaboration) 和 [ChatGPT 官方更新说明](https://help.openai.com/en/articles/6825453-chatgpt-release-notes) 用于引用、反馈、补充和分支交互参考。两者为产品行为参考，不称其闭源产品代码为开源。`assistant-ui/assistant-ui` 仅核对候选元数据（12912 stars、MIT、未归档、2026-11-02推送），没有据此宣称已阅读其实现或接入其框架。本轮没有新增React、Next、LangGraph或另一套完整Agent依赖。
