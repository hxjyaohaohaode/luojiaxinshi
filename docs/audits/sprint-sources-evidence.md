# 来源、通知生命周期与 AI 证据审查

复核日期：2026-11-14。来源与生命周期原冻结：2026-11-14 04:22:16 UTC；经授权补齐 HTTP 缓存策略后于 04:33:53 UTC 冻结；再补 LJ-019 群内候选，于 04:43 UTC 再冻结。

本报告对应《珞珈信使_冲刺前全量审查与优化清单》的 LJ-011—044，另附 LJ-111—116 的独立只读核查。目标仍是把有来源的校园信息变成经本人核对的行动、个人日历与后续办理；收件、原文效力、本人进度和触达回执保持分离。

**“实现及合成回归通过”不表示“真实校园与供应商验收通过”。** 本轮没有新增真实渠道授权，没有向同学或老师发送消息，没有发起付费模型请求，也没有生成冒充人工标注的标准答案。

## 1. 本轮实际改动

- 收件按同一外部键的年度／批次查找已有记录。新年、第二轮、补录可新建，迟到的旧年内容只更新旧事项；同业务年跨日历年的更正仍保持原事项。校园发布使用明确的发布 ID，正式更正可纠正标题年份而不误拆分。
- 新增有边界的匿名公共 HTTP 缓存、条件请求、持久域名租约与 Retry-After；相同公开栏目可共享 HTTP 响应，每人的通知、任务和权限独立。QQ／授权公众号不进入该缓存。
- Feed 服务、允许的原文 origin 和真实发布方分别配置。每次正文及重定向请求前检查范围；保留 Feed entry ID、原文地址、列表日期、规则版本和列表快照哈希。
- 来源规则通过真实读取函数试读列表及最多两篇正文后才安装。原 PUT、预设首次启用、前端编辑和回滚均不能绕过门禁；失败不替换有效规则。暂停不依赖来源网络。相同已验证配置的响应丢失重放不会重复升版。
- 来源回执分别保留登记入口、列表、正文、附件和失败原因。登记入口未被实际读取时标为 `registered_only`，不把登记网址当验证成功。有效空 Feed 与无法解析的 HTML 分开处理。
- 新增有持久化、版本约束和所有权检查的阶段跟踪：未公告／预告／正式公告／补充／公示／结果。结果需本人核实身份并引用原文；公示窗口必须有日期依据。后续动作复用现有任务、材料与办理回执；个人查进展复用现有安排、日历和提醒。
- JSON 导入完整保存阶段历史引句与结果，但当前结果重置为未知、通知版本置为待复核；不恢复未经重新核实的名单结论、正式窗口或提醒。完整数据库备份保留真实持久状态。
- 通知分页的事项与阶段投影只读取本页 ID 及其显式关联版本，避免每页重新扫全账号的阶段数据。

主要实现：[source_sync.py](../../app/source_sync.py)、[source_fetch.py](../../app/source_fetch.py)、[notice_ingest.py](../../app/notice_ingest.py)、[notice_network.py](../../app/notice_network.py)、[notice_tracking.py](../../app/notice_tracking.py)、[notice_matters.py](../../app/notice_matters.py)、[sources.js](../../static/sources.js)、[notice-lifecycle.js](../../static/notice-lifecycle.js)。

## 2. 可重复的本轮验证记录

补齐缓存策略后的来源／生命周期回归：**109 passed，1 warning，59.85 s**（此前 86 项通过，新增公共缓存策略 23 项；重复轮次不叠加计数）。告警为 Starlette 对 httpx TestClient 的弃用提示，没有把告警解释为业务失败。执行：

```bash
.venv/bin/python -m pytest -q \
  tests/test_notice_phase_tracking.py tests/test_source_cache_policy.py \
  tests/test_source_fetch_contracts.py \
  tests/test_intake_round_isolation.py tests/test_notice_matters.py \
  tests/test_source_subscriptions.py tests/test_source_presets.py \
  tests/test_evidence_acquisition.py tests/test_unified_intake.py \
  tests/test_proactive_tracking.py tests/test_proactive_monitoring.py \
  -o addopts=''
```

更早的阶段回归发现并修复了异议日期校验参数错误、来源规则误写入通知专属审计表、回滚意外启用暂停来源等具体问题。规则门禁增加后再次独立回归来源核心 29 项，再执行上面的完整 86 项。`node --check static/sources.js`、`node --check static/notice-lifecycle.js`、`git diff --check` 均通过。

[source_trial_fixture.py](../../tests/source_trial_fixture.py) 只在测试准备阶段显式替换公开 reader 的响应，退出 context 后恢复。它不绕过产品 API 门禁；失败、更改、暂停、重放和越权断言仍经过真实路由。独立门禁用例验证：首次失败不启用、改规则失败保留旧版、暂停不读网络、恢复需重新试读、预设不能绕过、同故障连续失败键不变但恢复后再次失败产生新键。

### 公共缓存协议补充复验

对照 [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html) 的存储、Vary 和条件复验规则，补充 [test_source_cache_policy.py](../../tests/test_source_cache_policy.py) 23 个合成合同用例。`no-store`、`private`、`Set-Cookie`、`Vary:*` 或未编码进键的请求头变体不落公共缓存，并清除同 URL 的旧配置／变体缓存。允许复用的 Accept、Accept-Encoding、Accept-Language、User-Agent、Referer、Host 值全部进入键，缺失与空值不混同；304 保留旧策略并应用本次新策略。`no-cache`、零有效期逐次复验，明确较短有效期及 Age／Date／Expires 限制优先于部署 30 秒上限。新策略标记升级只淘汰无法证明可复用的公共缓存，不删除个人通知证据。初次专项 34 项通过（缓存 23＋原来源合同 11），之后执行完整 109 项回归。

### 群内短更正与补件候选补充

总账交叉审查发现先前只有官网候选／标题相似候选，不足以覆盖 LJ-019；因此经授权补齐群内邻近候选。新增 6 项通过实际签名合成回调进入持久队列，验证短更正、真实字节附件下载、补交文本、跨账号／跨群／年度隔离、时间窗口、撤授权、无信号不关联和排除后不复活。候选不新增业务状态或修改正式期限，拒绝记录复用现有持久排除表。之后执行 6 个文件共 **41 passed，1 warning，35.28 s**：`test_group_context_candidates.py`、`test_notice_matters.py`、`test_qq_group_intake.py`、`test_group_delivery.py`、`test_source_subscriptions.py`、`test_intake_round_isolation.py`。这轮与前述 109 项范围有重叠，不累加为全项目测试数。

### 2.1 真实公开来源只读采样

机器记录：[sprint-public-source-sample.json](sprint-public-source-sample.json)。2026-11-14 04:08:44 UTC，使用应用实际 `fetch_index`／`PublicHTTPTransport`，只尝试现有三个官网预设，没有登录、站点写入或扩展来源。结果：

| 既有来源 | 本环境应用读取链路 | 独立网页读取渠道观察 | 能证明的范围 |
|---|---|---|---|
| [资源与环境科学学院通知公告](https://sres.whu.edu.cn/xxgk/tzgg.htm) | 列表返回应用 502 连接失败；未进入正文／附件阶段 | 403 Forbidden | 本轮未验证该栏目可读；没有绕过访问限制 |
| [武汉大学通知公告](https://www.whu.edu.cn/tzgg.htm) | 列表返回应用 502 连接失败 | 可读到公开列表及发布日期；另读到 [第 552 讲预告](https://www.whu.edu.cn/info/5231/277904.htm) | 该正文显示发布于 2026-11-07，活动开始为 2026-11-11 15:00；两者不能混成截止，也不能据开始时间编造结束时间 |
| [新闻与传播学院学生事务](https://journal.whu.edu.cn/undergraduate/affairs/index) | 列表返回应用 502 连接失败 | 可读列表，并读到 [2027 年接收推荐免试研究生实施细则](https://journal.whu.edu.cn/graduate/notice/20260918whfl) | 该页发布日期 2026-09-18；列表实际包含研究生栏目文章，不能按菜单路径推断为仅本科生适用 |

对一个既有官网做的底层同路径诊断返回 `ConnectError: Public reader DNS lookup failed`。这是本执行环境观察到的 DNS 失败；独立网页读取成功不能代替应用链路验收，也不能由应用失败推断官网全局宕机。**本轮真实正文／附件的应用端到端验收未通过。** 现有 2026-10-29 HTML fixture 的来源说明仍保留在 [fixtures/official-sources/README.md](../../fixtures/official-sources/README.md)，没有把历史捕获日期写成本轮采集日期。

## 3. LJ-011—024：逐项证据

| 编号 | 本轮状态 | 代码／测试证据与当前行为 | 未覆盖或需继续验收 |
|---|---|---|---|
| LJ-011 | 深化并合成验证 | `source_sync.status`、来源卡片分别显示手动、等待、自动、部分可读、失败、暂停；显示尝试、无采集错误检查与范围。登记公众号不自动显示接通。 | 真实 QQ／公众号凭据及平台后台状态，本轮没有联调通过证据。 |
| LJ-012 | 深化并合成验证 | `source_acquisition_runs` 保存规则／配置哈希、入口状态、列表快照、正文与附件回执；空 Feed 明确为空；异常 HTML 不算空栏目。`test_source_fetch_contracts`。 | 独立入口未实际读取仍为 registered_only；实网 DNS 失败，不能填造验证时间。 |
| LJ-013 | 深化并合成验证 | 两账号相同栏目复用一次匿名列表＋正文抓取，分别建立本人记录；越权读返回 404。`test_trusted_cross_origin_feed_public_cache_and_304_owner_separation`。 | 当前共享 HTTP 响应，解析及个人收件仍分别运行；未声称大型公共抓取集群或跨账号共享私有消息。 |
| LJ-014 | 深化并合成验证 | ETag／Last-Modified、304、最多 30 秒缓存、64 MiB 缓存上限、持久域名租约、Retry-After；no-store／private／Set-Cookie 与不支持的 Vary 清除旧公共缓存；no-cache／max-age=0 每次复验；Age、Date、Expires 与更短有效期不被忽略。域名队列不占住另一域名空闲 worker。 | 真实站点速率／长时吞吐仍须在部署环境验证；本轮未做高频实网压测。 |
| LJ-015 | 新增强制门禁并验证 | `trial_rule`、`apply_trial`、PUT、首次预设与 rollback 共用生产 reader；失败原子保留旧版；版本冲突拒绝；回滚保持暂停；回执保留安装版本。 | 新站改版仍需真实页面样本；规则历史与合成样本不证明未来页面结构永远可用。 |
| LJ-016 | 修复并验证 | 精确 origin、真实发布方与 Feed 服务分离；默认仍同域；危险地址／跨域重定向在发请求前拦截；拒绝原因和 Feed ID 持久化。 | 未擅自添加第三方 Feed 服务或声称外部提供方已授权。 |
| LJ-017 | 既有行为复验并补显示 | 首轮当前列表建立静默历史基线；积压条目持久化；一次处理有上限；暂停保留通知和任务。`test_initial_website_snapshot_stays_readable_but_only_later_notices_are_announced`。 | 不把当前栏目页等同全部历史；未实现无边界历史翻页补采。 |
| LJ-018 | 合成合同保留；真实验收待完成 | `test_source_subscriptions`、`test_qq_group_intake` 有群主授权、成员订阅、退群、迟到撤权、附件过期与重投场景。 | 本轮未对真实 QQ 私聊／群、平台普通消息与 @ 权限做实机联调；不能标验收通过。 |
| LJ-019 | 新增群内邻近候选并验证 | `notice_matters.group_context_candidates` 只读取同 owner、同一当前获授权群的持久分发回执；10 分钟邻近且有更正／附件／补交信号才提候选。保留 delivery ID、message key、实际时间依据、规则窗口，未有线程或同作者证据明确为 null。复用原归组预览／确认／排除；已排除的弱邻近依据不因附件新版本复活。`test_group_context_candidates` 六例及相关群域共 41 项通过。 | 没有保留可核实回复线程时只称邻近候选，绝不编造 thread；实际 QQ 授权与真实连续消息语料仍需联调。无任何候选自动改期限、合并通知或提交材料。 |
| LJ-020 | 既有合成合同复验；真实待完成 | 授权发布账号同步已有游标、更正、分页、失效与管理员边界；`test_publisher_continuous_sync_keeps_cursor_updates_and_admin_scope` 等。 | 不是读取个人关注列表；本轮无真实公众号图片／附件／失权联调通过记录。 |
| LJ-021 | 条件尚未建立 | 入站邮箱是清单中的条件 P2 项；本次没有真实入站邮件接口的完成证据。 | 出站验证码和提醒邮件不算入站能力；需试点确认渠道与授权后接入。 |
| LJ-022 | 已知边界保留 | 未连接的平台保留人工导入，来源页明确学校 SSO 仍需开放；没有伪造连接成功按钮。 | 微信群、教务 SSO、企微／钉钉／飞书的实际范围和授权仍未建立本轮验收证据。 |
| LJ-023 | 既有链路复验 | `notice_intake`／`notice_ingest` 保留正文、原件、出处、时间及重复回执；`test_unified_intake`、`test_evidence_acquisition` 覆盖重投、不同账号、版本还原与失败。 | 不把受支持的文件类型等同所有真实 Office／扫描样本都可读；真实复杂批量样本仍需人工验收。 |
| LJ-024 | 分层合同复验 | `source_coverage` 区分取得原件、解析失败、待视觉核对、未读附件、保留旧快照；测试覆盖扫描、超时、第五份附件、旧 Office 失败及解压大小。 | 本轮没有新的低清真实扫描／缺页人工标准；机器接收成功不是语义核对完成。 |

## 4. LJ-025—044：逐项证据

| 编号 | 本轮状态 | 代码／测试证据与当前行为 | 未覆盖或需继续验收 |
|---|---|---|---|
| LJ-025 | 新增并验证 | `notice_phase_tracking` 区分个人线索、往年规律、官方预告；未公告只允许本人查进展安排，不创建正式窗口。独立安排幂等，复用真实日历。 | 线索真实性仍需本人核对；系统不猜测公告日期。 |
| LJ-026 | 深化并验证 | 每则通知保留独立原文与版本；事项归组保留独立任务／期限；阶段跟踪绑定显式相关通知版本；相关版本变化触发 review_required。 | 自动相似度仅作候选，不能证明正式效力或覆盖关系。 |
| LJ-027 | 已有模型与合同复核 | `TaskData.scheduled` 的 event/window 与 due_date、published_at 分离；`test_notice_timing` 检查独立事件与提醒。 | 不凭发布时间生成开放提醒；真实开放平台／个人资格仍由使用者核实。 |
| LJ-028 | 深化并验证 | 来源页有尝试、成功、错误、范围、积压与人工转入；`recent_failures` 只返回本人已启用来源；同故障稳定键含最近成功轮次。 | 应用 DNS 失败就是未完成采集，不能解释为学校没有通知。 |
| LJ-029 | 深化并验证 | 来源原文、parent_url、relationship、Feed 服务／真实发布方、列表／正文日期分别保留；候选关系有未核实标记。 | 发布／转载／提及单位的语言语义仍需人工核对，不凭名称关键词自动认证组织身份。 |
| LJ-030 | 既有关系复验 | `test_group_preserves_independent_requirements_deadlines_and_personal_plans` 保留校级与学院通知各自任务、期限和个人计划。 | 冲突效力由本人依据核实；收到时间和模型置信度不决定优先级。 |
| LJ-031 | 修复并验证 | `test_intake_round_isolation` 四场景：复用 URL 跨年、同批更正、迟到旧版、同文第二轮／补录、同业务年跨日历年、明确校园发布修订。 | 保守结构规则不能解决没有任何年份／批次线索的语义歧义；可用既有人工新副本、归组与拆分。 |
| LJ-032 | 既有去重复验并加轮次保护 | 相同正文跨入口复用但保留收件出处；不同年份／批次不合并；人工归组／拆分保留各自通知和办理记录。`test_unified_intake`、`test_notice_matters`。 | 字节相同文件的新名称是元数据，校园共享原件名称历史由校园专项核查；未把相似标题直接判同一事项。 |
| LJ-033 | 既有工作流与适用判断复核 | 现有任务 action_kind／participation、通知知悉／不适用处理和逐动作条件分离；阶段跟踪没有替代这些状态。 | 多动作真实校园通知仍需样本验证；未知资格不等于不适用。 |
| LJ-034 | 既有证据门槛复核 | `proactive_policy.assess` 只使用当前通知／画像版本且已核对的适用结论；兴趣关键词只影响偏好，不认证资格；不充分结论保留待核实。 | 本轮未取得真实画像与独立人工适用标准，不能报告真实判断准确率。 |
| LJ-035 | 既有合同复验＋新窗口复用 | 原文日期、时刻、范围、明确时区分别校验；异议窗口复用 `deadline_evidence`。未知时刻不保存 23:59，未知活动结束不编时长。 | 相对日期需要原文发布日期和时区；省略年份不能仅据今年猜补。 |
| LJ-036 | 主工作流专项负责 | 本轮主工作流修订涉及正式 event/window 更正及依赖影响，仍复用既有来源证据和个人记录。 | 最终全量结果见工作流专项与总回归，本报告不以源码阅读替代其新测试结论。 |
| LJ-037 | 既有变更／材料合同复核 | 来源更新先成为待核对变化，保留旧证据、已提交／已准备历史；`test_action_workflow` 与 `test_change_review` 覆盖要求变化和依赖。 | 复杂费用／模板语义仍需真实样本，未声称全部自然语言变化可自动解释。 |
| LJ-038 | 失败保护复验 | HTTP／连接／附件失败记为来源问题；保留已读旧快照并标本轮未复查；不自动取消任务。`test_failed_related_recheck_preserves_last_snapshot_and_original_retrieval_time`。 | 原文撤回需要正式证据，404、维护、权限失败与正式取消不同。 |
| LJ-039 | 既有取消恢复合同复核 | 既有变更目标、版本和证据约束；取消／恢复不抹除历史，已完成保护与设备日历提示独立。`test_cancellation_restoration_and_completed_protection`。 | 不把恢复关注当作资格恢复；真实场次歧义需核实。 |
| LJ-040 | 既有聚合复验＋轮次隔离 | 事项聚合保留成员通知，各自期限和任务不合并；新轮次、跨年度隔离。 | 本硕博／联合团队的具体子流程仍依真实材料拆分，不按名单或标题自行推断。 |
| LJ-041 | 新增并验证 | 公示结束标记与结果无自动转换；异议意愿、明确窗口、现有任务材料和回执独立；本人结果需要身份核实说明；有越权／伪造引句／过期版本测试。 | 同名检索不能直接下结论；本轮没有真实异议业务办理／官方受理回执。 |
| LJ-042 | 新增动作关联并集成独立事件 | 支持入围、入选、未入选、候补、补录；关联确认名额／领取／签约／报到等真实任务；主通知模块 `phase_updates` 用当前阶段版本生成独立事件，不以旧报名期限抑制。 | 外发仍按主通知模块的本人偏好与渠道授权，未做真实设备到达验收；本人记录不等于学校最终确认。 |
| LJ-043 | 既有更正保护复验 | 更正保留已完成任务与材料，不因旧阶段完成而丢弃来源更新；`test_completed_action_still_receives_correction_reminder`、变更复核链。 | 新更正仍需本人核实效力与资格；不会自动复活所有旧提醒。 |
| LJ-044 | 分层深化 | 原文阶段、采集覆盖、平台处理、个人办理、提交／受理和触达分开；生命周期面板关联现有回执而不覆盖任务进度。 | Provider accepted 不代表设备展示或本人已读，官方办理结果需独立依据。 |

## 5. LJ-111—116：AI、记忆与安全只读审查

这一部分区分既有能力与本轮改动。这里没有新增模型输出或人为标准，也没有凭“存在测试”声称真实模型已通过。

| 编号 | 已核对的已有证据 | 本轮结论与剩余条件 |
|---|---|---|
| LJ-111 | [evaluate_mvp.py](../../scripts/evaluate_mvp.py)、[评测格式](../mvp-evaluation/FORMAT.md)、`test_mvp_evaluation` 已检查至少 10 开发／20 独立测试、事项家族隔离、原件／人工标准／配置哈希、不可删除失败分母、重复预测 FP 和缺结果 not_run。候选目录标记 `candidate_registry_only`，各项尚无独立人工标注且不具冻结资格。 | 工具既有，不是本轮新成果；没有真实冻结集与模型指标。历史候选 URL、HTML 解析 fixture、合成测试都不能替代人工标准。程序能核对声明格式，不能认证“人工独立”的真实性。 |
| LJ-112 | `notice_semantics` 对全部来源／任务进行有界复核；`deadline_evidence`、`notice_references`、`source_coverage` 区分引句、未知、缺附件；已有伪造引句、错来源、失效版本、扫描待核对测试。 | 本轮仅把这些门槛复用到新阶段／异议窗口，并补跨年度与 Feed 证据；未改成凭模型置信度认定事实。PDF／图像真实语义准确率仍未测得。 |
| LJ-113 | `agent_runtime/tools.py` 的资料查询显式受 server uid／scope 控制；写文件、沙箱执行、MCP 调用经过批准与精确参数；子代理无写权限。`test_agent_runtime`／`test_agent_chat` 有越权、取消、权限收回、MCP重定向、目录穿越、重复请求与最终发布门。 | 未发现本轮来源改动扩大 AI 工具权限。来源正文始终是材料，不能授权取他人资料或外发。本结论是代码边界审查，不能宣称通过所有提示注入攻防；生产 MCP／Docker 和真实模型对抗仍需环境证据。 |
| LJ-114 | `memory_lifecycle`／`memory_policy`／`memory_reliability` 及 v3—v7 测试覆盖来源、适用域、时效、跨项目、撤回、反馈、忘记旧版本、修改后的上下文作废。 | 本轮未重写已有记忆体系；过期／禁用／来源撤销不得作为当前依据。真实长期使用和身份变更仍需人工案例，不将自填资料升级为学校认证。 |
| LJ-115 | `test_notice_stream`、`test_notice_budget`、`test_notice_repair`、`test_execution`、`test_agent_runtime` 覆盖流未终结、预算前置、版本变化、取消、重启标失效、保留原件、显式重试及调用记账。 | 本轮没发付费请求，不能报告真实供应商断流成功率或账单。既有有界补正请求会记入调用量；“保留草稿与原件”不等于“远端供应商一定未计费”。 |
| LJ-116 | `genui.py` 有受限表达式与数据键校验；`openui.js` 使用仅 allow-scripts 的 opaque iframe，宿主消息带实例边界；`genui_state`／`test_genui_state` 校验控件、快照、版本与所有权。前端 Node 套件含状态、恢复、复制、传输和事件检查。 | 本轮前端专项另行处理集成；这里没有新浏览器实测证据。合成／源码证据不代替真实手机、读屏、完整浏览器隔离与迟到消息验收。 |

本轮只读 AI 复核没有发现足以支持仓促改写原提示词／记忆框架的新增实证缺陷，因此保留现有严格校验。真实评测应先补齐原件与实际人工标准，再冻结、运行和计分；不能为了得到通过数字自行填写 `human_independent`。

## 6. 发布说明应保留的限制

真实官网应用链路、QQ／公众号平台权限、真实手机触达、独立人工标注和大赛要求的真实使用日仍是外部验收条件。来源与阶段本轮新增功能已得到离线合同验证，但总分支的全量回归、构建、部署与主分支状态应引用主执行记录。任何后续真实联调结果都应附实际日期、来源、账号权限范围和可复核回执，不能用本文件的合成通过替代。

## 7. 全套发现的查询回归与重新冻结

第一次完整后端运行实际出现 1 项回归：`test_search_query_count_does_not_grow_per_notice` 对 100 条合成通知检索的限制为少于 15 条 SELECT，新阶段摘要令实际数达到 15。原断言没有放宽。先独立原样复现，再将归组和阶段元数据合并为同一 owner／通知 ID 范围查询，复用已加载的当前版本；只有关联证据通知不在本次范围内时，才另用一次 owner 限定查询核对版本。没有减少库存、跳过阶段状态或删除版本保护。

修复后相同 100 条记录仍完整返回，查询数为 **14**。新增两个参数化用例分别验证关联通知在批次内／外，覆盖归组投影保持一致、其他账号不泄露、关联通知更正与删除仍要求复核。阶段摘要单独读取与列表批量读取使用同一逻辑。

```bash
CAMPUS_AUTO_LOAD_ENV=0 .venv/bin/python -m pytest \
  tests/test_usage_limits.py tests/test_notice_matters.py \
  tests/test_notice_phase_tracking.py tests/test_sprint_lists.py \
  tests/test_workspace_projection.py -o addopts='' --tb=short \
  --junitxml=artifacts/sprint-final/notice-query-regression.xml
```

该轮实际 **45 passed、1 warning、28.82 秒**，重新冻结于 **2026-11-14 05:01:09 UTC**。结果及失败→修复记录见 [查询回归记录](sprint-query-regression.json)。45 项与之前来源、校园、投影定向范围存在重叠，不累加为完整测试总数；修复后的整个分支仍须重新执行完整后端与最终 CI。
