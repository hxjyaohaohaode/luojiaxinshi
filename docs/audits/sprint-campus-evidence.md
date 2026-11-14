# 冲刺审查：校园发布、组织与协作证据

日期：2026-11-14（UTC）。范围：用户《珞珈信使_冲刺前全量审查与优化清单》的LJ-004／005／006／010／057—068，以及F01、F05、F06和相应角色走查项。基线为`b362ab2100f835ace66bbc2b92921e865af1e1ce`。

本文记录代码和合成回归证据，不把自动化测试当作真实校园身份、实际外发渠道或真人三轮走查。全项目构建、浏览器与其他模块证据由总审查报告统一汇总。所有代码保持FastAPI、SQLite及原有原生前端架构，没有新增未获授权的学校接口或角色。

## 逐项完成与边界

| 清单项 | 本轮结果与定位 | 可重复证据 | 仍依赖的外部条件／明确边界 |
|---|---|---|---|
| LJ-004 名称规范与迁移 | `campus_roster.py`提供NFKC和空白规范化，`2026`转为`2026级`，对`一年级`提示而不猜。预览显示原身份、规范后身份和已有正式受众的增减账号。`campus-roster.js`提供表格、CSV、JSON录入及逐行核对。 | `test_normalization_preview_shows_exact_recipient_change_without_mutating_it`；Node表格解析4例。 | 现有授权仍按明确年级／班级范围；旧发布范围不会被名称迁移隐式扩大。院方需确认模糊历史名称对应哪一届。 |
| LJ-005 批量预检提交 | 最多500行；重复、未注册、无效字段、角色和跨院越权逐行报告；只提交明确选中的有效行。预检绑定目标及操作者授权，10分钟有效，原预检重放幂等。 | `test_roster_preflight_normalizes_years_reports_every_error_and_replays_once`、`test_roster_preflight_rejects_membership_changes_and_cannot_self_escalate`。 | 账号注册和真实身份核验仍由现有注册流程、管理者完成；不伪造学籍验证。 |
| LJ-006 撤权与交接 | 成员变更、后台执行、发布管理、协作读写均检查当前范围；旧个人通知与原件保留，新范围不自动开放旧内容。原发布由当前本院管理者管理；跨负责人协作需学生重新确认分享。 | 既有`test_correction_withdrawal_and_authorization_changes_keep_personal_data`；新增队列撤权、转交、跟进撤权用例。 | 学校毕业、任期与离院规则未提供，使用明确授予／修改／移除授权，不按年龄或自填年级自动推定。旧事项更正只给原收件且当前仍有权限者。 |
| LJ-010 注销留存 | `deletion-impact`展示影响；注销前保留对方最小脱敏回执，删被注销者私人说明和文件元数据，撤文件授权；已接收的正式原件继续可查，发布人匿名。 | 受理人、学生、发布人分别注销3例；协作跟进随case删除，未授权人仍404。 | 留存仅限参与事项必要动作、时间和存续方自己的说明；数据库备份依既有保留期轮换，不宣称立即物理抹除全部历史备份。 |
| LJ-057 发布草稿 | `campus_drafts.py`保存未完整正文／范围和原附件；每人最多50份；版本冲突409；刷新、重启、另一端可取；发布成功删本草稿。前端自动保存状态和冲突保留输入。 | `test_server_draft_version_and_files_restore_then_publish_once`、重启保草稿用例。 | 草稿不分发、不提醒、不计为已发布；网络失败而未保存的输入须继续重试。 |
| LJ-058 强制受众复核 | 随机复核凭据绑定发布人完整授权、受众范围、具体成员／角色／授权版本；省略、过期、同人数换人、重启旧签名均拒绝；已提交请求按幂等回执恢复。 | `test_missing_expired_review_rejected_but_committed_retry_is_returned`、`test_review_changes_when_same_identity_is_reauthorized`、既有同人数换人用例、正常重启用例。 | 核对不是校方审批。旧请求的幂等重放仍先验证当前发布权限，不能借重放绕过撤权。 |
| LJ-059 发布前真实限制 | 复核分学生和工作人员；零学生单列警告；返回1000人／3附件／8MiB容量边界，附件投影带实际size／SHA。单文件5MiB、文本总量10000字，原件和草稿存储预算强制执行。 | 现有范围预览与文件验证；新增真正写入版本的作者预算用例；63人附件样本。 | 没有机构任职到期数据，不显示虚构的“身份即将过期”；执行时仍查当前授权。容量上限不是吞吐量保证。 |
| LJ-060 共享原件与可恢复分发 | `campus_assets.py`不可变原件＋归属通知的授权引用；短事务逐人处理，默认每批24人；后台续传、逐人失败、撤权复核；逻辑容量保持。 | 63人×约1.03MiB合成PNG超过旧50MiB门槛：1份原件、63个引用，重建DB连接续完；旧版下载与跨账号404；队列撤权及失败重试。 | 测试证明此样本与故障边界，不据此宣称全部硬件上的1000人性能。 |
| LJ-061 版本、摘要、回滚 | 正式版本史和授权原件下载、正文／标题／附件摘要；回滚新建版本，记录原因与目标版本。有效期沿用所选历史版本。同内容附件改名更新本人名称，保存旧新名审计，不换source_id／原件。 | `test_publication_rollback_keeps_all_versions_and_exact_immutable_originals`、政策回滚、`test_official_attachment_rename_keeps_source_citations_bytes_and_name_history`。 | 回滚不重写过去审计；撤回版本须走正式恢复。 |
| LJ-062 正式恢复 | 独立`restore`接口，要求当前撤回版本及实际说明；保留撤回→恢复链，生成新版本、重新投递原合法受众。个人任务状态不被强制恢复。 | `test_official_restore_has_new_evidence_and_does_not_reopen_personal_work`：3版历史、原notice_id、个人task版本和data不变、学生403。 | 正式恢复由当前有权发布者／管理者确认原文依据；系统不杜撰恢复公告。 |
| LJ-063 新成员补发 | 补发强制当前版本＋新受众复核。当前授权成员才可新增，已收不重复、撤回不补发。显式有效期／历史参考由发布人填写；过期／参考须确认参考用途并抑制外发。 | `test_expired_backfill_requires_version_audience_and_reference_confirmation`、政策继承／回滚、历史任务外发抑制、既有补发用例。 | 不从正文猜有效期；未填显示“未设置有效期”。历史站内记录保留，补发不创建或重启任务。 |
| LJ-064 送审 | 保持原清单“如学院需要”的P2条件，没有把受众核对冒充独立审批。 | 权限模型只有现有四类职责；接口不提供假审核通过状态。 | 需明确拟稿人、审核员、审批失效与权限条件，尚未建立独立送审流。 |
| LJ-065 定时发布 | 保持P2独立功能边界；本轮持久队列处理的是已经明确发布的收件任务，草稿不因时间而自动发布。 | 草稿零分发、正常重启只续已有队列。 | 未建立定时发布及送审执行链，不能把后台分发队列称为定时公告。 |
| LJ-066 分层统计 | 站内分发独立显示。`campus_policy.delivery_evidence`仅用现存30天Push／邮件收件引用台账计算状态、次数、不同账号数，显示供应商接受≠展示。本人打开、显式回执无证据时为null／unknown。 | `test_publication_channel_metrics_only_count_linked_existing_ledger_evidence`：多设备人数去重、31天外记录排除、无引用不猜、邮箱／设备／私人标题不泄露。 | 无真实平台回执时不宣称真实发送成功；没有发布级打开／确认采集，就如实显示未知，不从私人办理数据推断。 |
| LJ-067 完整协作与跟进 | 新增拒收／不再负责、重新确认负责人和材料的转交、每人独立跟进时刻。改期／取消有版本；跟进不更改校方截止、原task或对方设置；关闭／撤权／注销停止。 | 原协作完整链；新增拒收、转交、稳定个人跟进、范围撤销和删除用例；北京时间输入转换Node用例。 | 跟进到期后按本人提醒偏好计算，未到期计划在协作详情可见；不冒充校方超时结论。 |
| LJ-068 职责范围、分页审计和交接 | 发布记录按权限SQL过滤、分页搜索；管理审计使用before_id游标及action筛选；协作收件箱在SQL分页合并活动和留存回执；材料分享固定明确版本。 | `test_campus_audit_cursor_does_not_lose_or_repeat_rows`、原跨账号／跨院／私有材料测试、转交拒绝受理人自行扩大共享。 | 系统管理员不能仅凭系统身份读取协作；辅导员查看本人合法发布版本史，不扩大为整个组织审计读取权。 |

## F01、F05、F06的关闭依据

### F01：不存在省略受众复核字段的兼容旁路

`Publication.audience_review`为请求可解析字段，但实际新发布必须通过`require_audience_review`。这样既让旧客户端得到明确409复核指引，也保留已经成功的相同request_id回执恢复。缺失字段不是重新选择受众或放宽权限的理由。回归直接调用原始POST省略字段，没有使用会自动获取复核的测试helper掩盖缺口。

备份恢复同时清除未提交复核和分发授权。即使重新授予原姓名账号，旧复核仍不可用；失败任务需要新复核才可重试。后台也拒绝没有当前版本分发授权的任务。正常进程重启作废未提交复核，但已保存的草稿、正式版本和幂等回执保持。

### F05：注销不抹掉对方必要历史，也不复制全部私人内容

原协作继续使用删除级联，分享链接和原case文件关系被回收。在删除前单独创建存续方的最小留存记录：动作／时间、存续方自己的说明；被注销者的具体身份和说明不复制，全部文件列表为空。学生仍可访问自己已有任务和材料；受理方只得到匿名回执，并在以后每次读取时检查当前负责范围。

发布者注销采用不同的事实边界：已经送达的正式公告原件仍是其他人可回溯的依据，原件保留且发布名匿名。没有借注销删除别人的原件，也没有授予新收件权限。

### F06：真实超旧门槛样本、授权引用与逐人恢复

测试生成600×600随机RGB PNG，原件约1.03MiB（约1.08MB）；63名合成接收者的逻辑总量超过50MiB。发布回执存在待投递，最多首批24人；重新创建数据库对象后续处理完成。数据库中`campus_materials`只保留一份二进制、`campus_material_refs`有63项、个人`sources.content`不复制BLOB。本人下载返回完全相同字节，无关账号404；更正移除附件后旧个人证据仍能下载。

下载、导出、Agent读源和个人文件计量分别通过公共集成调用共享原件helper。helper本身不授予权限，调用方须先验证本人notice归属；原件SHA与引用kind／SHA一致性在读取时检查。发布人草稿及其实际写入版本单独受预算限制，学院管理员修改他人发布也不能绕过自己写入原件的容量。

## 三类验证轮次

| 轮次 | 范围 | 证据结果 |
|---|---|---|
| 正常完整链 | 发布、附件、个人收件、持久草稿、恢复／回滚、批量成员录入、协作接收补件办结 | 既有`test_campus_permissions.py`和`test_pilot_workspace.py`与新增专项测试共同覆盖。 |
| 异常与恢复 | 网络回执重放、逐人失败、原件容量、重启分发、草稿冲突、过期参考补发、跟进取消 | 新增`test_campus_sprint.py`及`test_campus_policies.py`；Node验证准确时区、表格解析和统计未知态。 |
| 权限与并发 | 同人数换人、缺省签名、撤权、版本冲突、换班、跨院、账号删除、备份恢复后重授权 | 旧安全断言保留，新增所有关键边界；省略字段和未分享文件使用直接原始请求验证。 |

这些是代码层合成回归轮次，不替代原清单要求的真实人员、真实设备和真实渠道验收。本文不编造“所有真人走查已完成”。

## 复现命令与输出

```bash
CAMPUS_AUTO_LOAD_ENV=0 .venv/bin/python -m pytest \
  tests/test_campus_sprint.py tests/test_campus_policies.py \
  tests/test_campus_permissions.py tests/test_pilot_workspace.py \
  tests/test_account_and_insights.py \
  --junitxml=artifacts/sprint-campus/backend.xml --disable-warnings

node --test tests/campus-roster.test.mjs tests/collaboration-followup.test.mjs
```

专项验证记录：

- 第一轮核心修复＋既有权限／协作／账号回归：39／39通过。
- 第二轮扩展边界：独立新增的拒收提醒、规范化受众差异、正常重启复核和版本回滚均通过；063／067／066新增6例＋既有补发，共7／7通过。
- 第三轮上述五个Python文件：54／54通过，耗时87.48秒，JUnit为本地`artifacts/sprint-campus/backend.xml`。
- 最后名称更正缺陷：新增`test_official_attachment_rename_keeps_source_citations_bytes_and_name_history`，最终补充回归1／1通过，耗时3.23秒，覆盖名称回滚和改名提示不重复膨胀。完整冻结后的五个文件现在共有55例，最终全项目回归由总报告记录。
- 两个Node文件共6／6通过。Python语法、Node语法及相关已跟踪文件的`git diff --check`通过。

以上运行产物不作为生产用户数据或源代码提交。新增代码均为本地工作树待总集成提交，本文不声称已自行推送或部署。

## 数据兼容与新增表

保留原`campus_schema_version=1`基本表集合。新增`campus_sprint_schema_version=1`要求以下9表齐全，启动／备份恢复验证缺表和不兼容版本，不把损坏结构当作正常空数据：

1. `campus_audience_reviews`
2. `campus_dispatch_authority`
3. `campus_material_refs`
4. `campus_drafts`
5. `campus_draft_files`
6. `campus_roster_previews`
7. `collaboration_retained_receipts`
8. `campus_publication_policy`
9. `collaboration_followups`

从基线升级的旧正式版本没有有效期记录时，投影为`valid_until:null,reference_only:false`，不猜旧期限。旧个人原件仍从原字段读取；只有新的共享引用走不可变原件解析。管理员审计、原私有数据和既有安全测试未删除。

## 最终通知链路独立集成审查

`tests/test_sprint_campus_delivery.py`将校园发布策略、个人协作跟进、本人路由与Push／邮件真实队列连接起来，供应商边界均由捕获器代替。初始运行10例中4例失败、6例通过，确证了以下三个产品缺口，并已修补：

1. 校园仅供参考或已过显式有效期的版本关联协作跟进时，协作事件没有继承原版本的外发限制。现在按实际接收版本核查策略。
2. 发送人关闭本人通知的提醒路由后，关联协作事件仍可外发。现在仅对通知真正所有者应用其路由；接收人不获得发送人的私人通知ID，也不继承其个人设置。站内提醒中心遵循同一所有者边界。
3. 发出补件请求后，接收人被撤销负责范围，旧补件事件仍可能进入外发队列。现在所有协作外发候选再次读取当前双方身份、范围、状态与版本；保留发送人已有的最小站内历史不构成新外发授权。

其余用例证明：已排队跟进在改期、取消、关闭、撤权或另一方注销后，会在供应商调用前取消旧计划；改期的新版本只发送一次；已被供应商接受或邮件提交结果不确定的事件，切换为摘要后不再重放。联合`test_sprint_notifications.py`共17／17通过，耗时20.21秒。后续性能集成回归再次包含这10例，与通知队列、生命周期、分页及轻量投影共47／47通过，耗时34.15秒。上述为合成供应商回归，不证明真实设备展示或真人阅读。

校园有效期的分钟投影另由`test_received_publication_validity_rechecks_clock_without_changing_stable_revision`覆盖：原接收版本保持不变，跨过显式有效期后切换为禁止外发，正文与草稿不重新传输。详细接口与容量界限见[sprint-workspace-projection.md](sprint-workspace-projection.md)。
