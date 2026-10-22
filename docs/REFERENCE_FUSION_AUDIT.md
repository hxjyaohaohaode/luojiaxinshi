# 历次公开参考的融合核查（2026-10-22）

本次核查扩大到项目早期方案、可读取的项目历史聊天、2026-10-18 的 35 个原始资料目录、后续 13 个记忆仓库、Codex，以及两套前端参考资料。结论不是“所有仓库完整移植”：有明确落地的适配、实现机制的比较、设计参考、未采用及身份尚未确认的资料。不同状态不能混称为已经融合。

机器可查的目录、身份、决策、源码范围和 SHA-256 见 [REFERENCE_FUSION_MANIFEST.json](REFERENCE_FUSION_MANIFEST.json)。它将原目录中的重复仓库保留为目录记录，同时明确同一上游身份。手册中的示例网址、依赖库和推荐链接不自动等于用户要求集成的仓库。没有把不相关或不可读取的历史聊天宣称为已核查。

## 本轮真正补上的连接

| 问题 | 修改及现有能力复用 | 验证 |
|---|---|---|
| 新 Agent 的提示限制了主动记忆；协议还需通过 UI 工具取得 | 独立 `memory_capabilities`，纯文字也可自主维护。模式、项目范围、当前版本、锁定、遗忘、真实回执继续使用原有记忆系统；关闭或限制记忆时工具不可重新开启它 | `tests/test_agent_fusion.py` 的保存、关闭、限制、拒绝发布测试；真实 MiMo 合成输入 |
| 工具协议和证据一起被压缩，合法字段可能丢失 | 参考 LangChain 的排除规则，保护已加载的 Skills/UI/记忆协议；压缩旧数据仍保留调用与结果配对。初始数据只按完整条目装入，并明确延后项，不截断整个 JSON | 超预算、完整 schema、尾部字段、整项证据和权限保留测试 |
| Agent 不知道原 UI 的真实媒体数据；无文字视频在原检索阶段被丢弃 | 参考 CopilotKit 的宿主数据机制，向能力发现返回原有私有素材索引；`conversation_tools → grounding → ChatRun → 原消息组件` 保持媒体及引用顺序，视频字节不进入模型 | 实际 WebM 上传、鉴权 Range 206、浏览器解码播放、刷新回放和四种窗口尺寸 |
| 长期偏好和同条消息里的临时要求可能被模型混写 | 复用现有生命周期规则，对长期提议中的独立临时命令返回修正反馈；不静默改写含义，不放松原有保真检查和独立复核 | 混合句回归；最终真实调用产生 `accepted` 与 `session_saved` 两种独立回执 |
| 视频标签落在播放器深色背景上，层级不清 | 将视频尺寸和深色背景 CSS 限定在 `video` 元素，避免同名宿主节点套用；保留原主题、容器与页面布局 | 浏览器检查及重新渲染截图 |

修改位置：`app/agent_runtime/{chat,authoring,context,providers,runtime}.py`、`app/conversation_tools.py`、`app/grounding.py`、`static/genui/genui.css`。其中运行循环等部分包含此前迭代；本轮没有另建一套产品界面或第二个记忆库。

## 与之前参考形成的实际组合

- **Codex**：循环、工具、子任务、审批、上下文、Skills、SDK、App Server、exec、OSS 的十项适配详见 [CODEX_RUNTIME.md](CODEX_RUNTIME.md)。原聊天是主入口；不是只在新增 API 启用。
- **Mem0、Hermes、LangGraph、Vercel AI SDK、Langfuse**：早期已落实范围与来源、完整轮次、提交版本、持久状态、停止条件、取消释放和真实阶段计量。固定上游及落点见 [OPEN_SOURCE_REVIEW.md](OPEN_SOURCE_REVIEW.md)；本次沿用这些原则，不称为重新移植五个框架。
- **LangChain + LangMem + CopilotKit**：本轮重新读实际工具上下文、记忆操作与宿主状态实现，补上上表中的协议保护、主动记忆独立发现、真实媒体注入；源码哈希与具体读取范围已登记。
- **Activepieces、GenericAgent、BettaFish、autoresearch**：读取等待点恢复、结果反馈循环、协作监视和冻结评估机制，比较本项目现有执行与验证方式。保留结构化事件、有限并发、预算和审批有效期，不引入日志轮询、固定舆情角色或自动改代码训练。
- **前端手册与组件参考**：沿用已有列表键盘操作、自然高度、可中断过渡、树形选择、代码复制和实际宿主数据。见 [REFERENCE_INTERACTIONS.md](REFERENCE_INTERACTIONS.md)、[REFERENCE_VISUAL_REVIEW.md](REFERENCE_VISUAL_REVIEW.md)。本轮补齐媒体数据及显示断点，未重新套用演示模板。

## 13 个记忆仓库与保留的本项目实现

完整固定提交和代码证据见 [MEMORY_SOURCE_REVIEW.md](MEMORY_SOURCE_REVIEW.md)。此次复查沿用其此前已核查的源码证据，不把计算文件哈希称为逐行理解全部源码。

| 参考 | 在本项目采用的机制 | 现有实现 |
|---|---|---|
| EverOS | 分层、来源依赖、增量对账和编辑后的保护 | memory_reliability、memory_tree、memory_store |
| MemOS | 明确纠错、历史版本、替换边界 | memory_autonomy、memory_learning、memory_store |
| memU | 语义理解交给宿主 Agent，存储负责范围与提交 | memory_learning、agent_runtime/chat |
| ReMe | 持久作业、增量整理、检查点 | memory_learning、memory_reliability |
| Graphiti | 有效期与来源时间分离、派生关系失效 | memory_lifecycle、memory_store |
| LangGraph | 状态与记忆分离、命名空间和事务提交 | execution、memory_context |
| LangMem | 结构化受控记忆操作 | memory_learning、agent_runtime/chat |
| Letta Code | 人工编辑、锁定保护、可理解的目录 | memory_tree、memory_autonomy |
| Mem0 | 去重、版本与真实写入回执 | memory_policy、memory_learning |
| Memobase | 个人资料、事件和会话条件分层 | memory_context、memory_lifecycle |
| Cognee | 有界后台整理与作业管理 | memory_reflection、memory_reliability |
| Hindsight | 来源、租户边界、多路召回与融合 | memory_search、memory_store |
| OpenViking | 分层与渐进读取的抽象思路 | memory_tree、memory_search |

这些是本项目自己的 Python / SQLite 实现。没有部署十三个外部记忆引擎，也没有移植 OpenViking 的 AGPL 代码。涉及图数据库、PostgreSQL、向量服务和额外模型反思的部分未因“覆盖仓库数量”而加入。

## 当前验证与实际限制

- 四个并行分片跑完 63 个后端测试模块，**988 项通过，0 失败**。最终记忆混合句保护后又针对相关路径补跑 **59 项通过**；两组覆盖有重叠，不相加当作独立用例数。
- 前端 **142 项通过**。媒体浏览器检查覆盖实际本地文件播放、Range、刷新与 1440×1000、390×844、320×720、390×420；使用隔离合成账号和离线模型夹具，不能当作真实模型生成质量测试。
- 真实 MiMo 的记忆样本最终完成，长期偏好返回 `accepted`，临时要求返回 `session_saved`；初期失败、暂缓、协议修复记录保留在 `artifacts/reference-fusion/`，没有只保存成功样本。
- **该真实样本耗时 28.06 秒，共 6 次模型调用**：Agent 三次、独立复核两次、一次拒绝后的旧生成链修复；输入 29,484、输出 1,070 token，其中报告缓存输入 13,824。它证明保护和修复链路可运行，**不能作为提速或降本成功证据**。正文仍出现偏多的记忆过程说明，生成自然度与最短路径稳定性尚未达到全面验收标准。此前界面、文件等任务的较快单样本也不能外推到全部任务。
- 工具请求可提示供应商必须使用调用协议，但实际服务仍可能返回自由文本；服务端校验及有限修复必须保留。不得以请求参数声称协议错误已消失。
- OSS 的底层适配、MCP 的受控 HTTP 调用已具备；用户实际本地模型、实际 MCP 服务未配置的端到端行为没有在此冒充验证。Codex 全量协议、原生平台沙箱、MCP stdio/OAuth、自动技能安装等边界沿用 CODEX_RUNTIME。
- 现阶段没有证据支持“从立项到现在所有参考的所有能力都完整融合且最优”。可确认的是已追回已知参考清单、明确采用取舍，并修复上述实际连接问题。后续应以固定任务集的成功率、错误记忆率、首段响应、总耗时与调用成本继续评估，而非继续增加框架和漂亮样例。

## 35 个原始资料目录逐项处理

下表保留初始目录顺序与重复身份，避免挑选几个熟悉项目代替全量清单。除标明读过实现的项目外，未采用项主要完成 README/清单和业务适配筛选，不宣称全仓库代码审计。


| 原目录 | 上游身份 | 本项目处理 | 落点 |
|---|---|---|---|
| langchain-master | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | 保护已加载工具协议；不把权限或 JSON 截成半段 | [app/agent_runtime/context.py](../app/agent_runtime/context.py) |
| langfuse-main | [langfuse/langfuse](https://github.com/langfuse/langfuse) | 阶段、调用、缓存与推理 token 分别计量；无外传遥测 | [app/harness.py](../app/harness.py) |
| langgraph-main | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 持久状态、命名空间、最终提交与恢复；未移植整个图执行框架 | [app/execution.py](../app/execution.py) |
| motion-v14.1.0 | [motiondivision/motion](https://github.com/motiondivision/motion) | 浏览器原生可中断动画覆盖当前需求；未引入第二套动画运行时 | [static/reference-interactions.js](../static/reference-interactions.js) |
| postiz-app-main | [gitroomhq/postiz-app](https://github.com/gitroomhq/postiz-app) | 社交账号发布平台，当前未授权实现社交发布业务 | 未引入 |
| UI组件资料-已核验部分与待复核目录 | 本地资料／身份未完全确认 | 五站目录含部分核验状态；许可证和实现覆盖不统一，不能宣称全量融合 | [docs/REFERENCE_INTERACTIONS.md](../docs/REFERENCE_INTERACTIONS.md) |
| video-dedup-batch-skill-package-20260430-130354 | 本地资料／身份未完全确认 | 本地视频处理工具包；当前目标是 Agent 与 UI 质量，不是视频去重 | 未引入 |
| VideoProcessorApp-Windows-Installer-Ready | 本地资料／身份未完全确认 | 独立 Windows 视频处理应用，未把安装器嵌入校园助手 | 未引入 |
| WeChatDataAnalysis-main | [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis) | 聊天记录分析不是校园通知原文；未加入自动读取私人微信数据 | 未引入 |
| xiaohongshu-content-tools | 本地资料／身份未完全确认 | 本地内容工具合集，未确认为单一上游；业务不需要内容运营 | 未引入 |
| 上下文记忆压缩优化 | [mem0ai/mem0](https://github.com/mem0ai/mem0) | 所有者范围、来源、去重与真实回执，使用本系统已有记忆 | [app/memory_learning.py](../app/memory_learning.py) |
| 代码质量的矫正器 | 本地资料／身份未完全确认 | andrej-karpathy-skills 目录；未证实唯一上游身份，不按名称归功 | 未引入 |
| 优质开源前端部件 | [juliangarnier/anime](https://github.com/juliangarnier/anime) | 实际是动画库；当前原生动效无需重复依赖 | [static/reference-interactions.js](../static/reference-interactions.js) |
| 前端品味 | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | 设计指导可供取舍；不称为运行时能力，不覆盖用户主题和容器要求 | [docs/REFERENCE_VISUAL_REVIEW.md](../docs/REFERENCE_VISUAL_REVIEW.md) |
| 前端设计 | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 设计指导；未把演示主题、营销文案搬入现有产品 | [docs/REFERENCE_VISUAL_REVIEW.md](../docs/REFERENCE_VISUAL_REVIEW.md) |
| 吉祥物动画 | [jeremy-prt/bloub](https://github.com/jeremy-prt/bloub) | 保留本项目原创角色与已有宿主状态，不复制第三方品牌资产 | [ASSETS.md](../ASSETS.md) |
| 基于知识图谱的RAG系统 | [microsoft/graphrag](https://github.com/microsoft/graphrag) | 图索引与社区总结尚无本项目收益证据；保留逐字原文、来源版本与召回 | [app/grounding.py](../app/grounding.py) |
| 多Agent舆情分析助手 | [666ghj/BettaFish](https://github.com/666ghj/BettaFish) | 读论坛监视与协作实现；本项目使用结构化子任务事件，不采用日志轮询和固定舆情角色 | [app/agent_runtime/runtime.py](../app/agent_runtime/runtime.py) |
| 多模态知识图谱构建 | [safishamsi/graphify](https://github.com/safishamsi/graphify) | 知识图谱构建未证明优于当前受控原文检索；无整包接入 | 未引入 |
| 小红书_MCP | [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) | 不接社交账户工具；通用 MCP 走服务端白名单与逐次审批 | [app/agent_runtime/mcp.py](../app/agent_runtime/mcp.py) |
| 把你的 AI 产品从“聊天框”升级为“智能应用” | [CopilotKit/CopilotKit](https://github.com/CopilotKit/CopilotKit) | 宿主真实数据进入 Agent；稳定媒体引用贯通发现、发布和回放，不伪造素材 | [app/agent_runtime/chat.py](../app/agent_runtime/chat.py) |
| 最适合补齐后台自动化与工作流 | [activepieces/activepieces](https://github.com/activepieces/activepieces) | 读等待点、领取与恢复实现；本项目审批摘要、有效期、单次决定和恢复仍由原执行系统管理 | [app/agent_runtime/store.py](../app/agent_runtime/store.py) |
| 极简主义的自主进化体 | [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent) | 读结果反馈、nextprompt 和停止循环；采用本项目按结果继续的有界循环，不赋予自改代码权限 | [app/agent_runtime/runtime.py](../app/agent_runtime/runtime.py) |
| 构建AI产品的瑞士军刀 | [vercel/ai](https://github.com/vercel/ai) | 显式停止条件、流取消与资源释放；未移植 JS SDK API | [app/execution.py](../app/execution.py) |
| 消除幻觉的事实之源 | [upstash/context7](https://github.com/upstash/context7) | 用途是开发文档检索，不能替代校园原通知的事实核验 | 未引入 |
| 社交平台数据爬取 | [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | 未引入社交爬取业务或凭证；公开来源取证沿用既有链路 | [app/evidence_web.py](../app/evidence_web.py) |
| 社交平台视频上传 | [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) | 社交上传业务不在当前范围；与另一个目录属于重复仓库身份 | 未引入 |
| 科研数据可视化 | [Haojae/scipilot-figure-skill](https://github.com/Haojae/scipilot-figure-skill) | 面向科研出图；不把示例数据搬入通知 UI，已有可信数值 Plot 协议 | [docs/genui/DESIGN.md](../docs/genui/DESIGN.md) |
| 科研领域的自我进化革命 | [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | 读固定预算、冻结评估规则；采用有限回归与真实样本验收，不运行 GPU 自改训练 | [tests/test_agent_fusion.py](../tests/test_agent_fusion.py) |
| 自动化上传视频到社交媒体 | [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) | 与社交平台视频上传去重；不接社交发布账号 | 未引入 |
| 自我进化的认知基石 | [Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything) | 代码知识图谱工具，用于代码理解；不是用户长期记忆的替代引擎 | 未引入 |
| 视频剪辑 | [browser-use/video-use](https://github.com/browser-use/video-use) | 独立视频编辑能力未要求；本轮修复的是已有私有媒体展示链路 | [app/chat_media.py](../app/chat_media.py) |
| 超高级管理后台 | 本地资料／身份未完全确认 | 本地 Spring Boot/Vue 脚手架；无已证实唯一上游，未重写现有技术栈 | 未引入 |
| 降低token成本 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | 极短表达不能代替上下文管理；不删事实条件换取表面 token 降低 | [app/agent_runtime/context.py](../app/agent_runtime/context.py) |
| 陪你共同成长的智能体 | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 完整轮次、上下文快照与迟到结果边界；不引入全量网关 | [app/context_snapshot.py](../app/context_snapshot.py) |
