# Codex 架构适配：增强现有聊天 Agent

源码核对日期：2026-10-22。上游是用户提供的 `D:/项目文件/SKILL_extracted/codex-main` 解压目录；无可验证的 Git 提交号，以 [源码文件 SHA256 清单](CODEX_SOURCE_MANIFEST.json) 固定参考内容。

本实现按现有 Python / FastAPI / SQLite 项目重写，不要求安装或编译 Codex CLI。工具循环已嵌入 `grounding._events`，普通聊天和非流式聊天默认使用它。资料、日程、记忆权限与原聊天一致；同一个 Agent 根据工具结果形成完整答复和自由组合的 GenUI，经原有逐字引文检查、独立语义复核和最终上下文版本检查后发布。用户请求管理本人日历和待办时，直接通过原业务校验执行并返回真实回执；学校正式期限仍须原文依据。

```text
原聊天 / SDK Conversation / 默认 exec
  → 原有鉴权、同意、请求幂等、消息持久化
  → 上下文范围与版本快照、原有记忆召回
  → ChatRun + 共享 Run.loop
      模型选工具 → 类型和权限检查 → 执行/审批 → 返回结果 → 再次判断
      可选并行只读子任务、按需技能、查询扩展、原文分页、公开检索
      submit_answer 提交文字；按需发现 submit_interface 提交导语与自由组合节点
      → 字段与证据反馈 → 必要时修正
      图片、受支持的音视频直接随工具模型调用提供；仅协议确实不支持时交接原生成器
  → 独立复核 → 当前版本检查 → 发布到原回复
  → 从实际操作、引用、组件与未知项生成工作回执
```

`AGENT_ENABLED=false` 保留原有固定检索规划路径，便于兼容回退；默认值为 true。测试中的旧模型录制夹具显式关闭新循环，新集成测试单独启用并从原聊天接口验收。不是仅在新增接口中启用。


## 1.19.3：真实时间、个人操作和预算边界

- `current_time` 从宿主实时读取北京时间，独立于材料日期、旧回复和模型训练时间。个人安排的相对时间可解析；缺失年份的历史正式期限仍保持未知。
- 原聊天、Conversation SDK 与默认 exec 共用 `workspace_read` 和按需加载的 `calendar_write`、`task_write`、`workspace_undo`。写入现有 arrangements/tasks，保留所有权、最新版本、依赖与审核校验。底层 Thread/OSS 不因此获得新的个人写入工具。
- 用户实际请求可授权个人操作，不重复弹应用审批；附件、网页、旧助手回复不能授权。只读和否定请求由服务器拒绝。外部文件、命令与 MCP 继续使用原权限边界。
- 数据库提交成功后才生成 `assistant_operations` 回执。失败回滚；相同请求与参数返回原回执。重新生成时若参数改写，也不能再创建同类副本，必须核对、复用或修改此前记录。撤销遇到后续人工修改会拒绝覆盖。
- `GET /api/conversations/{cid}` 的每个回复版本都包含实际 Agent 状态。即使新回答复核失败、界面保留旧回答，已完成的操作仍显示；`POST /api/conversations/{cid}/agent/operations/{oid}/undo` 撤销当前账号本次操作。
- 提示预算同时计算后续工具目录、工具结果的 JSON 转义和省略标记；初始资料为执行留出空间。查询按完整记录分页；紧凑回执保留成功状态与证据 ID，不能把已提交操作截成不完整 JSON。
- 简单标签拼接不触发深度数学推理，独立事实复核保留。操作回执只证明本站数据变化，不证明手机同步、邮件发送、作业提交或现实任务已完成。
- 最新验证及现场样例见 [TESTING.md](../TESTING.md)。其中合成测试、真实模型工程样例与本机原对话验证分别记录，不将一次耗时当作固定性能保证。

## 十项能力与实现位置

| 用户要求 | 实现 | 主要入口与上游依据 |
|---|---|---|
| 核心 Agent Loop | 同一循环自主取证、修正并通过 `submit_answer` 产出最终草稿；成功候选跳过第二个写作调用，保留独立复核。`research_complete` 仅供当前协议不能表达结果时兼容交接。公共引擎有步数、总调用、输出、超时和无进展上限 | `app/grounding.py`、`app/agent_runtime/chat.py`、`authoring.py`、`runtime.py`；参考 `codex-rs/core/src/session/turn.rs` |
| 子智能体并行编排 | `spawn_agent`、`list_agents`、`send_message`、`wait_agents`、`interrupt_agent`；每轮最多三个只读子任务，独立上下文和消息队列，共享模型预算；主任务退出时取消未完成子任务 | `runtime.py`；参考 `core/src/tools/handlers/multi_agents_v2/` |
| 工具调用 | 类型化参数、未知工具拒绝、明确的读写标记；原有资料检索、记忆召回、原文分页、隐私过滤后的公开检索，以及文件、命令、技能、MCP。只读整批并行，混合调用顺序执行；来源 ID 跨检索轮去重 | `chat.py`、`tools.py`、`mcp.py`；参考 `core/src/tools/orchestrator.rs` |
| 沙箱与安全边界 | 账号和任务目录隔离、路径/符号链接/Windows junction/硬链接检查、覆盖 SHA256、原子替换；命令进入无网络、非特权、宿主只读 Docker 容器；无可用沙箱则拒绝 | `sandbox.py`；参考 `codex-rs/sandboxing/src/` |
| 上下文压缩 | UTF-8 字节保守预算，预留模型输出；历史保留用户原话及有上限的先前答复以理解追问，旧答复不作证据。当前轮调用与结果配对压缩、原记录不改写。证据 E 编号只追加不重排，界面目录按需加载和整项分页 | `context.py`、`authoring.py`、现有 `context_snapshot.py`；参考 `core/src/compact.rs` |
| Skills | 启动目录元数据发现、显式选择、`load_skill` 按需读取；提供通知原文核对和材料清单两个技能；技能不能增加工具权限 | `skills.py`、根目录 `skills/*/SKILL.md`；参考 `codex-rs/skills/src/parser.rs` |
| 可编程 SDK | Python `Client.conversation` / `start_conversation`、`Conversation.run` / `run_streamed` 使用原聊天及独立复核；`Thread` 暴露底层执行接口。共用 Cookie/CSRF、审批与取消 | `sdk.py`；参考 `sdk/typescript/src/thread.ts` 的线程和事件模式 |
| App Server | 账号鉴权 REST、JSON-RPC 子集、SSE 真实阶段事件、持久事件游标、审批状态、幂等请求、单会话互斥、进程租约恢复、恢复备份时中断旧任务 | `api.py`、`store.py`；参考 `app-server-protocol/src/protocol/common.rs` |
| 非交互式 exec | `python -m app.agent_runtime exec` 默认使用原聊天；stdin、JSONL、指定请求标识、继续原对话、非零失败退出码；默认拒绝操作审批。`--runtime` 明确选择底层引擎 | `__main__.py`；参考 `codex-rs/exec/src/cli.rs` |
| 本地模型 --oss | 显式选择 Ollama / LM Studio 的回环 OpenAI-compatible Chat Completions；使用单独模型名和上下文设置，不带 MiMo 密钥，失败不回退云端 | `providers.py`、配置 `AGENT_OSS_*`；参考 `codex-rs/ollama/src/lib.rs` |

这些是适配后的能力，不是 Codex 全量实现：未复制 Rust 原生沙箱、Codex 全套 JSON-RPC/WebSocket/stdio 协议、官方 SDK 包、MCP stdio/OAuth 管理、技能自动安装器和无限递归子智能体。原聊天保持生成预览与审核后正文的既有流式方式；工具阶段实时流出实际事件，工具模型的隐藏推理不保存、不展示。

## 第二轮融合的关键适配

- **结束条件由任务决定。** 参考 `session/turn.rs` 的继续推理与工具反馈边界，证据足够就直接提交答案；不强制经过覆盖分析、第二次写作等固定阶段。字段不合法时反馈字段位置和错误类型，不回显敏感输入。最终提交不能与副作用工具混在同一批。
- **工具协议与模型兼容。** `submit_answer` 描述明确的可选 UI 对象；兼容部分服务把嵌套对象再次序列化的情况，仅解码展示字段一次，随后照常进行严格图、绑定、动作和引文检查。文件、命令、MCP 参数不做宽松转换。返回不完整时不执行工具。组件定义不能按字节截断；超出当前预算时返回完整组件和待取名称。
- **更早显示真实答复。** 流式解析支持普通 JSON 答复和 `submit_answer` 参数的增量，仅预览顶层 `answer`。工具参数仍完整缓冲，其他工具内容和隐藏推理不会进入预览。图与操作在复核后一次挂载，避免草稿控件反复重排。
- **按复杂度分配复核预算。** 单来源、少量直接事实和普通清单使用独立 Pro 模型的非推理模式，初始输出上限 2048 token。实际计算、条件推导、多个外部来源、大段证据和数值组件保留推理，初始上限 8192；原有截断修复仍允许一次扩展至配置总上限。程序校验和独立审查始终保留，不根据“模型说已完成”发布。
- **复用现有记忆。** 参考 `memories/read` 的按需读取、引用与使用记录，继续使用本项目的会话记忆、工作记忆、项目范围、来源版本、撤回与遗忘检查；不导入无账号边界的共享磁盘记忆。初始上下文携带当前会话状态，需要记忆动作时再读取完整字段协议。
- **工作回执来自实际结果。** 删除旧 `BRIEFS` 和用于改写阶段套话的额外模型调用。记录本轮查到的来源、读过的段落、文件操作、实际组件、失败与未知项；阶段标题只表示进行中状态。摘要和详细执行记录默认折叠，折叠期间不重建隐藏 DOM。
- **在原聊天改善生成式 UI。** `compact` 不再强制退回旧整页模板；原有兼容层仍可显式选择。`answer-surface.css` 统一主次、留白、清单、按钮、标签页与折叠区域，避免容器套容器；工作记录取消固定高度和内部滚动。清单继续使用原保存接口，不引入第二套状态。

Codex 的并行工具使用共享读写锁和取消令牌。本项目根据现有工具语义采用“整批只读可并行、混合批次顺序执行”，并用 TaskGroup 在权限变化时取消同批读取。取消标记可能先于异步取消回调到达，执行终态以数据库已提交的取消状态为准，防止把本人停止误记为失败。

## 第三轮：用反例检查结束条件、上下文和原生界面协议

继续实际阅读 `agent/control.rs` 的子任务完成监听与通知注入、`multi_agents_v2/wait.rs` 的事件唤醒、`send_message.rs` 的队列投递、`context_manager/history.rs` 的成对移除，以及 `tool_search.rs` 的按需工具发现。源码清单现固定 21 个文件，未将“读过文件数量”作为功能完成度指标。

| 实际发现的问题 | 当前实现与适配理由 |
|---|---|
| `submit_answer` 可以在子任务结束前提交；子任务恰在主模型生成时结束也可能被遗漏 | `completion_needs_followup` 在文字结束、两种提交工具和视觉交接处统一检查；完成、失败、取消结果进入主模型下一步后才能结束。`observed_agents` 区分已经结束与已经交付结果；子任务意见仍不升级为事实证据 |
| 子模型在最终回答期间收到补充，可能直接结束而丢掉要求 | 每次模型返回后再次检查邮箱；补充必须进入下一模型步骤。新消息或完成通知重置“相同请求”判定；等待实际子任务不误判为无进展 |
| 等待多个子任务会等最慢的一个 | `wait_agents` 首个结果到达就返回，其他子任务继续运行；主任务可根据实际结果继续协调，不靠频繁模型轮询 |
| 长的新回复放不进预算，反而保留更旧内容 | 历史按完整对话轮保留连续的近期部分；最近一轮太长时保留原文首尾并明确标注省略。不会留下没有所属用户问题的旧助手答复，也不会用模型摘要重写权限要求 |
| 老工具结果仅保留开头，尾部错误可能消失 | 压缩副本保留首尾，标明不完整及不能重放副作用；调用/结果仍配对，原执行记录保持原样 |
| 同时要求“完整 answer”和“简短 UI 导语”，导致正文与界面重复 | 新原生工具 `submit_interface(lead,state,nodes,claims,memory_actions)` 在取得组件协议后才公开，导语最多 80 字；主要内容自由写入节点。纯文字工具不再向模型暴露 UI 字段，旧提交格式仅作为兼容输入 |
| 旧 `citation_indices` 出现在参数目录中，真实模型与 E 编号混用并多花一轮修复 | 原生 `AgentClaim` 只暴露 `kind/text/evidence_refs`；服务端继续解析真实引用并独立核验，不猜测或自动换算错误编号 |
| 提供商把容器 children 放进 props，或生成完全相同的相邻清单标题 | 仅对无歧义结构做本地规范化；相同清单标题仅在没有动作、子节点、引用或额外属性时去重。冲突字段、未知组件、非法动作、无来源事实继续拒绝；规范化记录进入执行报告 |
| 每次调用重建连接，缓存 token 数据丢失，换参数重复报错仍耗尽整轮 | 同一轮主子任务复用 HTTP 连接、退出时关闭；保留可信数值范围内的 cached/reasoning token 统计；删除 Schema 展示 title，保留验证约束和真实字段；同一工具连续三次失败停止无效重试 |
| 工作摘要只有“执行几次工具”，长对话每个流片段又复制全部正文字符串 | 摘要加入已经通过复核的本轮具体结论与未知项；不调用额外摘要模型。前端直接比较内容值，以 Map/Set 查找消息，避免每帧序列化全部历史正文和逐条全表搜索，保留原交互状态与焦点 |

没有照搬大型工具市场的搜索基础设施：目前是规模有限的本地工具集，给常用工具再强加一次发现请求会增加延迟。只把较大的组件协议、记忆动作协议以及交互提交工具按需开放。学校业务仍使用原账号、资料权限、记忆版本、发布检查和通知审核边界。

第三轮真实模型试验均为隔离数据库中的合成资料，未读取真实用户材料。最终交互协议样本为 **11.86 秒、3 次完整链路模型调用、输入 14722 / 输出 542 token**，工具为 `load_skill`、`ui_capabilities`、`submit_interface`，没有模型字段重试；服务器本地移动了一处容器 children。上一轮同题为 23.55 秒、4 次调用、23498 / 1169 token。此前第三轮试验曾出现混用引用协议的失败，已经保留记录并据此修正 Schema，不能把这些试验算作全部一次成功。

空目录查询的本轮样本为 **6.36 秒、11810 / 91 token**；上一轮样本 5.16 秒更快，说明服务波动与单次样本不足以证明所有场景都会更快。冲突通知样本 **29.78 秒**，明确保留“最终截止时间无法确定”，没有擅自选取 16:00 或 18:00 为正式截止；缺少报名信息的样本 **6.66 秒**，直接请求具体原文，没有调用写入、命令、MCP 或子任务，也没有声称完成报名。记录见 `artifacts/agent-quality-interface-final/`、`agent-quality-live-files/`、`agent-quality-live-conflict/`、`agent-quality-live-clarify/`。

全量后端回归 `artifacts/agent-quality-final.json`：**979 项、62 个模块，0 失败、0 错误**。最终展示规范化与等待边界的小修正另外运行 **145 项展示/工具回归**和 **56 项生命周期回归**，全部通过，分别见 `artifacts/agent-quality-presentation-final.xml`、`agent-quality-lifecycle-final.xml`；这些与全量重叠，不相加。最终前端单元测试 **139 项通过**，见 `artifacts/agent-quality-frontend-final.log`。真实模型合成产出回放在原聊天通过清单保存、刷新恢复、折叠详情和 1440×1000 / 390×844 / 320×720 / 390×420 检查；另通过原位审批、拒绝、下载及取消验收。截图见 `artifacts/agent-quality-interface-browser/`。

浏览器另在 **202 条消息、100 项清单、40 个流更新帧**下验证历史 DOM 不重建、勾选不丢失、焦点保持且没有渲染错误；本机该次更新中位数 21.6 ms、P95 29.9 ms，记录在 `artifacts/agent-quality-browser/performance.json`。这是合成负载下的本机结果，不等于服务端并发、全设备或真实用户长期使用的性能承诺。

## 使用入口

重启本项目服务后，继续使用原“和小信使聊聊”。发送问题时自动调用增强后的 Agent，不需要新建另一种任务。工作摘要显示实际工具与子任务状态，详细记录默认折叠；需要写文件、运行命令或调用 MCP 时，在当前回复内显示具体操作及批准/拒绝按钮。刷新仍能恢复待审批项，原停止按钮和补充问题会取消旧循环与子任务。

原聊天沿用 `account_access`、`message_scope_start`、`memory_access`、`context_snapshot` 的范围和撤回规则，子任务无法扩权。记忆工具返回的条目也绑定到原有快照；资料或授权在生成期间变化时停止采纳旧回答。文件位于 `DATA_DIR/agent-workspaces/<user_id>/<thread_id>/`，生成后附在当前回复下供下载；不允许读取应用源码目录、`.env` 或其他账号目录。文件不是校园通知原件，也不会自动成为正式待办。

工具回执只证明执行结果，工作文件、外部 MCP 输出与子任务总结不能替代学校原文。子任务实际检索到的来源进入共享证据集，子任务总结以不可信辅助信息交给主流程。

文件写入、命令与 MCP 调用需要审批。审批记录包含具体工具、完整参数、操作摘要哈希和五分钟有效期，只能使用一次；相同请求被拒绝后本轮不重复请求审批。命令或外部服务可能已经产生结果再遇到中断，因此中断后只保留记录，不能自动重放来猜测成功与否。

## 配置

所有新选项已加入 `.env.example`，现有 `.env` 没有被本轮覆盖。默认模型仍使用现有 `MIMO_*` 设置。

```dotenv
AGENT_ENABLED=true
AGENT_CONTEXT_BYTES=96000
AGENT_OSS_URL=http://127.0.0.1:11434/v1
AGENT_OSS_MODEL=本机已加载且支持工具调用的模型名称
AGENT_OSS_CONTEXT_TOKENS=32768
AGENT_SANDBOX_IMAGE=
AGENT_MCP_SERVERS_JSON={}
```

LM Studio 可使用 `http://127.0.0.1:1234/v1`。`AGENT_OSS_CONTEXT_TOKENS` 必须与本地服务实际加载的上下文相符；不会自动下载模型。MiMo 保留 8192 输出 token，本地模型保留 4096；在扣除保留量后按每 token 约 2 个 UTF-8 字节估算输入空间，并受 `AGENT_CONTEXT_BYTES` 的硬上限约束。这是应用预算估计，不是供应商精确分词或计费用量；模型仍可能因具体分词、配置不匹配而拒绝超长请求，届时不执行不完整的工具输出。最新用户消息保持完整，旧用户原话单独按预算保留，当前工具调用与结果不拆散。

命令沙箱要求宿主已安装可用的 Docker 和明确带 `@sha256:` 的本地镜像；设置不完整时直接拒绝，永不退回宿主 shell。容器使用 `--pull=never`，工作区与根文件系统只读，网络禁用，限制 30 秒、256 MB、1 CPU、64 个进程，输出最多 32 KB。创建文件通过 `write_file` 单独审批。应用自身的 Docker 部署默认不挂载 Docker socket，因此不会因此获得宿主容器管理权限。

MCP 示例仅说明结构，须替换为维护者实际拥有并允许的地址与工具：

```json
{"campus":{"url":"https://mcp.example.edu/mcp","tools":["lookup"],"token_env":"AGENT_MCP_CAMPUS_TOKEN"}}
```

服务器地址由维护者固定，模型不能改写。HTTP 仅允许回环地址，远程使用 HTTPS，不跟随重定向；只允许配置列出的工具，忽略 `readOnlyHint` 的授权含义。支持有界 JSON 或 SSE 响应、初始化、会话头和工具分页；每次调用重新初始化，不自动重试远程副作用。当前不支持 MCP stdio、OAuth 流程、远端资源订阅与服务端反向采样。

## SDK 与命令行

```python
import asyncio
import os
from app.agent_runtime.sdk import Client

async def main():
    async with Client('http://127.0.0.1:8765') as client:
        await client.login('自己的账号', os.environ['CAMPUS_AGENT_PASSWORD'])
        conversation = client.conversation('本人已有对话的32位ID')
        # 或 await client.start_conversation('核对材料')
        result = await conversation.run('核对本人需要准备的材料', allow_external_processing=True)
        print(conversation.id, result['status'], result['final_response'])
        print(result['grounding']['status'])  # checked 才通过原有独立核验

asyncio.run(main())
```

`Conversation.run()` 默认拒绝审批，可提供异步 `on_approval` 回调逐项核对；`run_streamed()` 返回原聊天的 `start/phase/work/agent/preview/delta/done` 事件，审批在 `agent.state.approvals`。中断时用 `read()` 核对已保存消息；重复提交保留相同 request_id，不以新标识盲目重跑。

底层 `Client.start_thread` / `resume_thread` 与 `Thread.run` / `run_streamed` 仍可用于嵌入工具引擎、本地模型和自动化；该自由文本结果是未经过原聊天最终独立复核的草稿。底层事件支持 `events(turn_id, after=seq)` 重连与持久重放。原聊天绑定的执行线程拒绝通过底层 turn/start 继续，避免绕过原聊天复核。

```powershell
# CAMPUS_AGENT_PASSWORD 由运行环境提供，不放进代码或命令行参数。
.\.venv\Scripts\python.exe -m app.agent_runtime exec "核对材料" --username 自己的账号 --allow-external-processing --json
.\.venv\Scripts\python.exe -m app.agent_runtime exec "继续核对" --username 自己的账号 --conversation 原聊天ID --allow-external-processing
.\.venv\Scripts\python.exe -m app.agent_runtime exec "整理本地任务" --username 自己的账号 --oss --json
.\.venv\Scripts\python.exe -m app.agent_runtime exec "运行底层工具" --username 自己的账号 --runtime --allow-external-processing
```

`--conversation` 继续原聊天；`--resume` 继续底层执行会话，保留原模型、范围和技能。重复请求使用原 `--request-id`；相同标识对应不同问题会返回冲突。非交互式执行默认拒绝审批。`--oss` 使用底层本地工具引擎，不调用云端写作/复核，不代表原聊天所有多模态、联网与 GenUI 组件已本地化。

## 接口与存储

| 接口 | 行为 |
|---|---|
| `POST /api/conversations/{cid}/messages`、`/messages/stream` | 现有聊天入口，默认经过新工具循环与原有最终核验 |
| `GET /api/conversations/{cid}` | 回复中包含执行绑定、待审批项、文件与持久工作记录 |
| `POST /api/conversations/{cid}/agent/approvals/{aid}` | 当前原回复内审批，校验账号、活跃消息和操作 digest |
| `GET /api/agent/config` | 技能目录、服务是否配置、执行上限 |
| `GET / POST /api/agent/threads` | 本账号会话列表 / 创建会话 |
| `GET / DELETE /api/agent/threads/{tid}` | 读取记录 / 删除已停止会话 |
| `POST /api/agent/threads/{tid}/turns` | 幂等提交，返回持久 turn ID |
| `POST /api/agent/threads/{tid}/turns/{rid}/interrupt` | 停止并保留已完成操作 |
| `POST /api/agent/threads/{tid}/approvals/{aid}` | 校验 digest 后批准或拒绝 |
| `GET /api/agent/threads/{tid}/events?after=N` | 每页最多 200 条事件 |
| `GET /api/agent/threads/{tid}/stream?after=N` | SSE，支持 `Last-Event-ID` |
| `GET /api/agent/threads/{tid}/files`、`/file?path=...` | 列出、下载本任务文件 |
| `POST /api/agent/rpc` | `initialize`、`thread/start`、`thread/read`、`turn/start`、`turn/interrupt`、`approval/respond`、`events/read` |

JSON-RPC 协议标识为 `campus-agent/1`，响应明确返回 `codex_wire_compatible: false`。现有登录、来源校验、CSRF、账号所有权与本地/生产配置继续生效。

新增 `agent_threads`、`agent_turns`、`agent_events`、`agent_messages`、`agent_approvals` 五张表和 `agent_schema_version=1`。迁移为追加式，拒绝未知高版本与缺表结构。数据库备份包含运行记录；恢复时取消旧审批并将活跃任务标记为中断。

底层 SDK 每账号最多 100 个执行会话，每个执行会话最多 100 轮；原聊天只绑定一个内部执行线程，不增加对话数量。数据库最多 4 个活跃执行。每轮最多 12 个主步骤、每子任务 6 步、3 个子任务、主子合计 24 次工具模型请求；公开检索额外最多 4 次，之后的写作/复核仍用原流程预算。原聊天总时限使用 `AI_WORKFLOW_TIMEOUT`，底层执行总时限 10 分钟。Agent 模型请求单独按账号计数，上限复用 `AI_DAILY_LIMIT`；这不是费用金额上限，也不与原聊天的业务请求计数合并。SSE 每次状态快照至多 48 个近期步骤，完整步骤保存在报告内。

工作文件不在 SQLite 备份内；完整迁移须另备份 `agent-workspaces/`，并保持账号 ID 一致。删除任务记录撤销 API 文件访问，磁盘工作文件仍需维护者清理；原有个人文本导出/导入暂未包含 Agent 历史，不要将该导出当作完整 Agent 备份。

## 验证与实际边界

测试只使用隔离数据库和明确标记的合成资料。真实模型测试需要 `--allow-paid-synthetic-test`；不把离线模型的固定回答当作生成质量证明。

第二轮留存的后端回归为 **963 项通过，0 失败、0 错误**，覆盖当时所有 `tests/test_*.py`，分四个独立测试进程运行，汇总见 `artifacts/agent-adaptive-backend-final.json` 和四份同名前缀 XML。此前全量回归暴露的取消状态竞态、旧 compact 模板预期与已删除摘要函数夹具均已修复。第二轮定向回归 **204 项通过**（与全量重叠，不相加），见 `artifacts/agent-adaptive-final-regression.xml`；前端 **133 项通过**，见 `artifacts/agent-adaptive-frontend.log`。最新第三轮结果以上节为准。

原聊天浏览器验收：

- `tests/agent-browser.mjs`：审批前完整内容、批准写入与下载、刷新恢复与拒绝、停止取消、桌面/手机/键盘展开，7 项检查通过。
- `tests/agent-adaptive-browser.mjs`：自由组合清单、折叠原文、工作回执、勾选保存与刷新恢复；1440×1000、390×844、320×720、390×420 无横向溢出、内容内部滚动或遮住输入区，7 项检查通过。
- 设置 `AGENT_LIVE_UI=1` 后运行同一浏览器脚本，可把已通过独立复核的真实模型合成产出放回原聊天渲染，验证相同交互。截图保存在 `artifacts/agent-adaptive-live-browser/`。这是产出回放，浏览器步骤本身不再次调用收费模型。

真实 MiMo `mimo-v2.6-pro` 工程样本：

| 场景 | 耗时 | 完整链路调用 | 输入 / 输出 token | 验证结果 |
|---|---:|---:|---:|---|
| 上一轮：空目录查询 | 11.92 秒 | 采集两轮，再写作和复核 | 12992 / 319 | checked |
| 本轮：相同空目录查询 | 5.16 秒 | 3 次 | 12470 / 97 | list_files → submit_answer → 独立复核，checked |
| 本轮：自由生成截止时间、清单与折叠原文 | 23.55 秒 | 4 次 | 23498 / 1169 | 原生 UI 发布，checked；包含一次组件字段纠正 |
| 故意把 18:00 改成 19:00 的答复 | 2.05 秒 | 1 次独立复核 | 629 / 74 | 明确拒绝错误时刻 |

结果分别见 `artifacts/agent-chat-live/results.json`、`artifacts/agent-adaptive-live/results.json`、`artifacts/agent-adaptive-live-ui/results.json`、`artifacts/agent-adaptive-review/results.json`。`scripts/verify_agent_adaptive_live.py` 提供 files/ui/review 三种案例。首个 UI 试验暴露了字符串化对象、无字段反馈、被预算截断的组件目录，以及简单界面过度深度复核的问题；修复后重新验收。当前仍可能出现需要一次修正的组件字段错误，不能宣称任意生成一次成功。时间数据来自单次样本，受服务波动影响，不代表稳定延迟、总体成本降幅或全部通知的准确率。

`scripts/verify_agent_sandbox.py --image 已有镜像@sha256:...` 在真实容器中验证 UID 65534、任务目录/根目录只读、无网络、NoNewPrivs=1、有效 capabilities 为零；上轮已通过，相关实现本轮没有削弱。Ollama / LM Studio 的实际本地模型和用户自有 MCP 尚未配置联调，目前仅有协议与错误边界测试。`--oss` 是底层本地工具引擎，原聊天全部多模态、公开检索、GenUI 与复核尚未全部迁入本地。

源码核对和行为适配不等于完整复刻 Codex。十项能力的实现范围、权限边界和不支持部分见上表与各配置段。模型仍可能误解需求或产生错误草稿；程序与独立复核降低风险，但不能替代重要校园手续的原文核对。

## 历次参考的共同融合核查

更早的开源执行框架、13 个记忆仓库和前端资料的采用、未采用及验证边界见 [REFERENCE_FUSION_AUDIT.md](REFERENCE_FUSION_AUDIT.md)，目录与源码哈希见 [REFERENCE_FUSION_MANIFEST.json](REFERENCE_FUSION_MANIFEST.json)。该清单明确区分原则适配和完整框架移植。
