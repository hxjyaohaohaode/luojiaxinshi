# 开源参考源码审查

2026-10-18。按用户提供的 `D:\项目文件\SKILL_extracted` 实际内容筛选。先读取目录中的 README、包清单与仓库链接，再定位实现源码；目录的中文名称不作为功能或质量证据。35 个原顶层目录的初筛记录保存在忽略目录中的 `reference-inventory.json`，并非对其中全部代码完成审计。

## 上游版本与本次借鉴

通过 GitHub 官方仓库 API 取得默认分支的确切提交，再从该提交下载所读源码、包清单和 LICENSE。下表记录本次快照；分支会继续变化，不把发布页中其他子包的版本当作整个项目版本。

| 项目与固定上游 | 本地与上游核对 | 本次采用的原则与代码落点 |
|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py) | 本地 Python 包 2.0.9；该提交为 2.2.1；Apache-2.0 | 检索前建立所有者与会话范围；落实为 `app/memory.py` 中账号、项目、专题过滤和版本检查 |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/06671b70756452c9bb45c0e7297835f7728143fc/agent/context_compressor.py) | 本地 0.17.0；最新稳定发布核对为 v0.22.2；所读 main 和 release 包版本均为占位 0.0.0，不当作发布版本；MIT | 保护当前问题、保持完整轮次、历史时间与压缩边界；新增 `context-v2` 的完整问答保留和时间标注。摘要采用本地原句抽取，未复制其辅助模型摘要流程 |
| [LangGraph](https://github.com/langchain-ai/langgraph/blob/0870f5efcec9d486046ae8abce0735aa7d1f3b79/libs/checkpoint/langgraph/store/base/__init__.py) | 所读主包 1.2.16；MIT | 区分对话状态与跨对话记忆、明确命名空间；落实为独立 `conversation_context` 与账号所属的长期记忆表，分支继承范围后可独立调整 |
| [Vercel AI SDK](https://github.com/vercel/ai/blob/fce9210c6405c0ad8452fee3f50717e8ea910b97/packages/ai/src/generate-text/stop-condition.ts) | 所读 `ai` 包 7.0.143；LICENSE 为 Apache-2.0；该停止条件文件与本地相同 | 显式循环退出条件；`harness-v2` 集中记录生成／修复限制和退出原因，并结合现有超时、取消、无进展退出 |
| [Langfuse](https://github.com/langfuse/langfuse/blob/e3a2bee2a2c048adf29b8d8a18b29bd4a8bf8ac3/packages/shared/src/domain/observations.ts) | 本地 4.1.0；所读 4.63.0；通用部分 MIT，企业目录另有许可证 | 区分阶段、生成及核验观测；本地 harness 记录实际调用耗时与用量，不引入外部遥测或上传私人上下文 |

参考源码快照在 `D:\项目文件\SKILL_extracted\.upstream-verified\2026-10-18`，附每个文件的原始 URL、提交、SHA-256、下载状态和与原目录是否一致的 `manifest.json`。此次下载的是实际审查的源码文件和许可证，不是完整仓库镜像；未覆盖可能已有用户修改的原资料，也未运行其中的安装脚本。

应用使用自行实现的适配逻辑，没有复制这些项目的大段源码、引入它们的运行依赖或声称与其 API 兼容。后续若直接引入实现，需随具体文件保留其授权与通知，并单独验证迁移和依赖成本。

## 1.5.0 第二次实时核对与代码采用

2026-10-18 13:09:32（北京时间）重新读取 GitHub 官方元数据，并分别取得默认分支及最新发布标签对应的源码；保存 38 份源码、许可证和包清单，下载全部为 HTTP 200。Hermes 的默认分支已从第一次的 `ccc6956` 前进到 `06671b7`，因此保留两次快照，不把分支最新开发内容冒充稳定发布。

| 仓库 | 最新 GitHub 发布标签及提交 | 本次默认分支提交 | 具体包版本 |
|---|---|---|---|
| Mem0 | [ts-v3.3.1](https://github.com/mem0ai/mem0/releases/tag/ts-v3.3.1)，`94c3fe9` | `0724291` | 所读 Python 包为 2.2.1；发布标签属于 Node SDK |
| Hermes Agent | [v0.22.2](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.2)，`d923a5e` | `06671b7` | 使用发布标签；pyproject 的 0.0.0 是占位值 |
| LangGraph | [1.2.16](https://github.com/langchain-ai/langgraph/releases/tag/1.2.16)，`41c9c22` | `0870f5e` | langgraph 1.2.16 |
| Vercel AI SDK | [@ai-sdk/zai@3.0.33](https://github.com/vercel/ai/releases/tag/%40ai-sdk%2Fzai%403.0.33)，`b7f6255` | `fce9210` | 核心 ai 为 7.0.143；zai 提供商包是另一版本 |
| Langfuse | [v4.63.0](https://github.com/langfuse/langfuse/releases/tag/v4.63.0)，`88c02ea` | `e3a2bee` | langfuse 4.63.0 |

实际阅读和采用点如下，不以 README 中的功能口号代替实现分析：

- **Mem0**：[main.py](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py) 的批内／已有哈希去重、仅报告成功落库项，强调“声称已保存”和真实写入一致。本系统在 `memory_policy.py` 与 `memory.py` 做来源保留的重复检测、事务保存及显式互斥项处理；不照搬模型自动删除记忆。
- **Hermes**：[conversation_compression.py](https://github.com/NousResearch/hermes-agent/blob/06671b70756452c9bb45c0e7297835f7728143fc/agent/conversation_compression.py) 区分提交令牌和尝试代次，避免迟到压缩回调清掉后继任务。本系统新增 `context_snapshot.py` 校验回答使用的资料／记忆版本，`execution.py` 约束终态更新；旧任务的清理不能覆盖新任务令牌。
- **LangGraph**：[release 的 _loop.py](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/libs/langgraph/langgraph/pregel/_loop.py) 在检查点提交前等待相关写入，也处理错误路径的持久化。本系统把最终输出与执行终态放在同一事务，记录失联执行，并明确交由本人重试；没有假设远程模型调用可以恰好执行一次。
- **Vercel AI SDK**：[stop-condition.ts](https://github.com/vercel/ai/blob/fce9210c6405c0ad8452fee3f50717e8ea910b97/packages/ai/src/generate-text/stop-condition.ts) 和 [stream-text.ts](https://github.com/vercel/ai/blob/fce9210c6405c0ad8452fee3f50717e8ea910b97/packages/ai/src/generate-text/stream-text.ts) 明确循环停止，并在取消时先结束待决状态、释放读取器。本系统维持生成／修复上限，并修复任务尚未开始就被取消时，订阅者等待不结束、并发槽不释放的问题。
- **Langfuse**：[observations.ts](https://github.com/langfuse/langfuse/blob/e3a2bee2a2c048adf29b8d8a18b29bd4a8bf8ac3/packages/shared/src/domain/observations.ts) 区分耗时、输出开始和实际用量。本系统继续在本地保存阶段与模型调用计量；没有把应用等待时间当作供应商首 token 延迟，也没有上传私人资料。

第二次快照及逐文件 SHA-256 位于 `D:\项目文件\SKILL_extracted\.upstream-verified\2026-10-18\followup-20261018T050932Z\manifest.json`。仅下载审查所需文件，未整包替换原资料。架构取舍、失败行为和扩展边界见 [ADR-001](ADR-001-execution-and-memory.md)；对应验证位于 `tests/test_memory_lifecycle.py`、`tests/test_execution.py` 和 `tests/test_stream_job.py`（当轮的浏览器脚本已在 1.20.0 清理，见 git 历史）。

## 为什么没有整包引入

- `mem0` 的模型抽取、向量存储和多后端能力有价值，但当前 SQLite 用户规模下，直接接入会增加模型调用、配置项和外部存储维护。当前实现保留明确确认与有界本地检索，未来可替换召回器。
- Hermes 是具备工具执行、网关和多提供商的完整代理系统。这里借鉴上下文边界，不把其自主执行权限移植到校园通知助手。
- LangGraph 与 Langfuse 适合更复杂的持久执行和观测部署。1.5.0 已持久保存执行状态、恢复失联状态并提供原记录重试入口；尚无模型调用中途续跑、工具检查点重放或 Langfuse 导出协议。
- `caveman` 的实际 README 以大幅缩短输出表达为主。简短不自动等于压缩上下文或提高事实质量；本产品不能因此删掉办理主体、期限条件和材料细节。
- `context7` 的实际用途是版本化开发文档检索，不能替代校园通知原文；GraphRAG 是图索引检索系统，原文规模和收益尚不足以支撑新增图索引建设。
- CopilotKit、Activepieces、前端动画与组件项目分别提供应用交互、工作流平台或视觉能力。此次既有前端与办理模型能够承载需求，没有仅为目录名称或示例效果重写技术栈。

## 已新增的针对性验证

记忆所有者与范围隔离、撤销及版本变化、无内联引用时的旧回答排除、分支继承、原对话删除、迁移幂等与缺失项目回滚、已有容量校验、历史完整轮次、相对日期时间标注、重复约束去重，以及修复循环无进展退出。当前结果与真实模型样本见 [TESTING.md](../TESTING.md)。

## 1.8.0：应用到办理条件

沿用上述已核实源码中的显式状态、人工确认、提交版本与事务原则，补充了办理分类／依赖提案的原子确认、外部条件的本人核实、旧回执保护和条件变化后的复核传播。没有为这次变更再次下载同一快照，也没有复制框架源码或增加依赖。具体数据契约与失败取舍见 [ADR-004](ADR-004-confirmed-action-conditions.md)。

## 1.8.1：把观测原则落实到通知接收

沿用已固定核验的 Langfuse 观测区分，通知适配器现在分别记录首段答案等待、模型请求和本地校验耗时；未知用量和缓冲响应的首段等待保持未知。执行存活沿用 Hermes／LangGraph 借鉴后的进程租约与最终提交规则，修复活跃长任务被旧读取超时阈值误判。实现为本地 `notice_stream.py`、`notice_progress.py` 与执行扩展版本 2；未增加框架依赖或上传遥测。具体实验、失败观察与不采用全局关闭思考的理由见 [ADR-005](ADR-005-notice-streaming-and-measurement.md)。

## 1.9.0：语义复核、人工处理与分阶段计量

把同一批固定源码中明确停止、状态一致性和分阶段观测的原则继续应用到通知整理：最多一次提取和一次独立复核，追加请求前检查版本与有效执行；每次请求分别记录模型、实际用量及失败。复核意见与原文进入人工确认，原始意见和处理说明一同保留，模型不能自动确认学校要求。复核使用本项目独立适配模块，没有复制框架代理或新增外部运行依赖。见 [ADR-006](ADR-006-independent-action-review.md)。本节是本地实现进展，未声称这些上游在第二次快照之后又发布新版本。

## 1.10.0：在相同观测与停止规则下加入加速选择

继续使用已核验源码对应的有界执行、状态隔离和实际用量观测原则：模型选择通过请求级配置副本解析，分阶段保留实际模型及失败状态，未完成复核不标为通过，失败不自动换档重试。加速能力与价格另据小米官方资料核验，不把框架版本更新等同于模型提速。未复制这些项目的运行时或增加依赖，详见 [ADR-007](ADR-007-notice-processing-modes.md)。本次没有为了反复刷新版本而重新下载未变化的文件。

### 2026-10-18 16:58（北京时间）最近一次上游核对

再次从 GitHub 官方 API 取得五个仓库的最新发布和默认分支提交。五个发布标签均与 13:09 的记录一致；Mem0、LangGraph 和 Vercel AI SDK 的默认分支提交也未变化。Hermes 默认分支前进到 [`6f572e1`](https://github.com/NousResearch/hermes-agent/commit/6f572e154f7b19b486055f364b1edff987c02188)，Langfuse 前进到 [`564f800`](https://github.com/langfuse/langfuse/commit/564f800fb5301a1edf68ed8c0498fd880880bcd5)，两者稳定发布仍分别为 v0.22.2 和 v4.63.0。

按新提交重新下载这两个项目已审查的七份相关文件：许可证、包清单、上下文压缩模块及观测定义。逐文件 SHA-256 与上次相同，因此已借鉴的相关实现没有变化，不因分支前进而改动应用或升级依赖。元数据证据为 `artifacts/mvp-acceptance/upstream-metadata-final-1.9.0.json`；新增文件快照及哈希位于 `D:\项目文件\SKILL_extracted\.upstream-verified\2026-10-18\followup-20261018T085812Z\manifest.json`。这是对相关源码的核验，不是对两个仓库所有新增提交作全量审计。
