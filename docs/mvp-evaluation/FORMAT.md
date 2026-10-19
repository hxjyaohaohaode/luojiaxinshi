# 冻结样本与人工评分格式

入口为 `scripts/evaluate_mvp.py`，协议 `mvp-human-matching-v1`。这是离线证据与计分工具，不调用模型、不读取 `.env`、不连接正式数据库。它不会生成“人工标准答案”，也不会将模型复核意见当作人工裁定。

真实材料放在受控的私有目录，例如被 Git 忽略的 `data/mvp-evaluation/`。目录中同时保留通知原件、附件、标注、未经人工修改的模型输出及每次失败记录；不要将含个人信息的评测原件加入仓库。以下命令均在 `系统_开发` 执行。

## 四类文件

| 文件 | 必须记录的内容 |
|---|---|
| `corpus.json` | 数据集标识、固定协议、每份通知的 ID、事项家族、开发／测试归属、三类业务之一、来源及取得时间、原件与附件路径、使用条件、人工标注路径；人工确认材料完整和使用权限 |
| 每份通知的 `*.gold.json` | 人工标注者代号、标注时间、未看模型输出的声明；完整八类事实及来源依据；按冻结粒度划分的个人任务、责任人、日期、必办／可选／核实、条件、先后关系、材料、提交方式、地点和联系人 |
| 每轮 `run-*.json` | 冻结快照哈希、轮次、归属集、模型／思考／预算配置、实现文件哈希、开始及结束时间；每份通知的终态、原始输出路径和哈希、失败说明及可取得的调用量 |
| 每轮 `judgments-*.json` | 同一快照、轮次及输出哈希；人工裁定者代号和时间；八类事实各自正确／错误；每个个人任务的原始序号、标准任务匹配或错误新增、错误类型和依据 |

完整字段定义可以从实际校验模型导出，避免文档与程序各维护一份 schema：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py schema corpus
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py schema gold
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py schema run
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py schema judgments
```

这些命令只显示 JSON Schema，不生成已填好的人为声明。`format_version` 为 `1`，`protocol` 为 `mvp-human-matching-v1`。ID 使用英文字母、数字、下划线、点或短横线；标注者使用代号。时间必须含时区，例如 `2026-10-18T18:00:00+08:00`。文件路径相对私有评测目录，不能用绝对路径、`..`、越界符号链接或 Windows 附加数据流。

## 样本与标准答案

`split` 使用 `development` 或 `holdout`；至少分别 10 和 20 份，两部分都覆盖 `application`、`materials`、`activity`。同一事项的更正、补充、同内容转载和不同语言版本属于同一个 `family_id`，不能跨两部分。程序拒绝完全重复的主文，TXT／Markdown 还忽略排版空白后查重；其他语义重复和家族划分仍需人工审核。共享表格附件不自动视为重复通知。

每份通知的 `sources` 恰有一个 `kind=body`，其他为 `attachment`；每份来源有局部 ID、路径、原始来源说明和取得时间。`source_kind` 必须为 `real_notice`，`materials_complete` 与 `source_use_confirmed` 须由实际核实者填写。超过产品上传限制或包含不支持格式的完整通知仍可成为测试案例，运行时如实记录不支持／人工兜底，不能删掉难处理材料后声称输入完整。

`profile_kind=synthetic` 表示测试画像，或以 `consented_self_report` 记录获同意的本人自报条件。画像进入冻结快照；合成画像不能计算为真实试用学生。

标准答案中 `annotation_kind=human_independent`、`prepared_without_model_output=true` 是人工真实性声明。程序检查格式与时间先后，但**不能认证填写者身份，也不能证明声明属实**。只有 AI 整理的候选不得填写为人工独立标注。

八类事实使用以下固定键，不能因未知而省略：

```text
theme, audience, dates, actions, materials, submission, location, contact
```

每类包含 `state`、`value`、`evidence`。原文未给出时为 `not_stated`、空字符串、空依据；已给出为 `stated`；主文和附件未解决的矛盾为 `conflicting`，值中保留冲突。每条依据包含 `source_id`、`locator`、`quote`。工具核对来源存在，并校验 TXT／Markdown 引文确实出现；PDF、DOCX、图片等只核对文件与引用关系，页码、引文及含义仍由人工核对。

个人任务必须在看输出之前固定 `task_unit_rule`，并以同样粒度标注。例如，“取得学院签章”与“上传已签章申请表”是不同交付步骤。每步包含唯一 ID、行动、责任人、义务类型、可为 `null` 的截止日期／时刻、条件、前置步骤、材料、提交方式、地点、联系人和证据。未知时间保持 `null`；日期为 `YYYY-MM-DD`，时刻为 `HH:MM`。依赖不可引用不存在的步骤、自己或形成环。

本协议是**严格的一对一任务匹配**，不以标题相似度自动认定正确，也不在看到结果后临时拆分或合并标准任务。合并／拆分差异若影响既定匹配，使用 `granularity` 错误标记，在报告中单列，不能把所有粒度分歧解释成模型语义错误。需要不同粒度规则时，应在新的开发阶段预先修改协议，重新冻结测试版本。

## 冻结与验证

```powershell
$evaluationRoot = Join-Path (Get-Location) 'data/mvp-evaluation'
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py validate --root $evaluationRoot --manifest corpus.json
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py freeze --root $evaluationRoot --manifest corpus.json --output frozen-v1.json
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py verify --root $evaluationRoot --frozen frozen-v1.json
```

目录和资料需要先准备好。候选清单 `public-notice-candidates.json` 不是 `corpus.json`，不能直接拿来冻结。

快照保存原清单、原件、附件、人工标注的 SHA-256 和字节数，同时固定画像、标准答案、计分协议及评测脚本的哈希。再次计分会重新核对这些文件。任何改动都需要保留旧证据，建立新的数据集版本；已看过模型结果的测试通知不能因此重新变成“未见过”的独立测试通知。

哈希用于检查内容一致，不是签名或可信时间戳。它不能防止拥有目录写入权限的人重建全部记录；真实评测仍需保留人工标注过程和审核责任。

## 运行记录与人工裁定

工具本身不发起模型调用。真实评测在独立测试账号／数据库中执行，保存未经人工改写的应用草稿响应 JSON，可以是 `{"draft": ...}` 外层响应，也可以是原始草稿对象。`output_stage` 固定为 `model_draft_before_human_edit`；本人核对后的最终任务不能冒充模型原始输出。

一轮记录只对应一种配置和一个归属集。`config` 记录提供方、提取模型、复核模型、处理模式、两个思考开关及输入／两个输出预算；不要记录 API 密钥。`implementation_sha256` 记录实际参与运行的实现／提示文件及其 SHA-256，尤其是 `app/ai.py`、`app/notice_semantics.py`、`app/grounding.py`、`app/deadline_evidence.py`、`app/notice_references.py`、`app/models.py` 和相关配置逻辑。它们是执行记录提供的信息，评分器不会向提供方认证模型身份或重新执行该版本。

每个案例一轮最多一个结果，重跑使用新的轮次和文件名，并保留首次失败。`status` 为以下之一：

- `complete`：草稿完整，保存原始响应和哈希，随后必须有完整人工裁定。
- `error`、`timeout`、`cancelled`：保存相应原因，不记为成功。
- `unsupported`：完整输入不被当前处理链支持，保留为失败／回退案例。
- `invalid_output`：响应格式不完整或无效，不能改写后标为成功。

没有结果的冻结案例由评分器列为 `not_run`，不从分母删除。评分器不自动重试，也不从多次结果中挑最好的一次。输出和人工裁定都绑定原文件哈希；某份原始输出被修改后，原裁定不能继续套用。

对完整输出的八类事实逐类裁定：`correct` 表示这一类所有相关内容均正确且没有遗漏，原文未知时模型也未臆造；任何错误、遗漏或错误肯定均记 `incorrect`，不是按模型是否填了字段计分。每个 `scope=personal` 的任务都须按原始零起始索引裁定一次，`other`／`uncertain` 不当作已正确提出的个人任务，标准答案中相应个人行动仍可能计遗漏。

`verdict=correct` 需要一个实际存在的 `gold_task_id`、无错误标签及人工依据；日期、责任人、材料、条件、依赖等实质要求必须一致。`incorrect` 指试图对应某个标准步骤但有错误；`extra` 指无标准依据的新增步骤，`gold_task_id=null`。错误标签支持责任人、期限、材料、渠道、条件、依赖、义务、无依据新增、粒度及其他。只有完整结果需要人工裁定；失败记录不能套上成功的裁定。

## 计分

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_mvp.py score --root $evaluationRoot --frozen frozen-v1.json --run run-01.json --judgments judgments-01.json --output score-01.json
```

- 八类事实准确率：人工判对的类别数 ÷ 全部冻结案例数的 8 倍；失败和未运行仍占八项分母。报告同时列出每一类别的正确数和分母。
- 任务 TP：正确预测命中的不同标准任务数。一个标准任务最多记一次，重复预测另外计入 FP。
- 任务 FP：全部个人预测任务数减 TP；错误新增、错误对应和重复预测均保留。
- 任务 FN：标准个人任务数减 TP；失败和未运行案例中的所有标准任务计入 FN。
- 精确率为 `TP/(TP+FP)`，召回率为 `TP/(TP+FN)`；分母为零时显示 `null`，不会伪装成 100%。

报告按三类业务分别统计，开发集与测试集不能混算。它还列出终态分布、独立事项家族数、错误类型、重复预测和是否全部运行。运行记录漏项会令 `all_cases_attempted=false`；完整输出缺人工裁定时直接拒绝出分。**命令退出码为 0 仅说明校验和计算成功，不代表模型通过验收**；工具没有凭空设定“合格准确率”。

耗时仅统计所记录请求的区间，中位数、最小值、最大值包含已记录的失败请求，不声称完整办理时间或服务 P95。未知调用量与 token 量使用 `null`，同时报告已知／未知案例数，不推算为零或实际账单。

五位学生、三条件、五个实际使用日、真实手机日历、HTTPS、声音复刻和发榜单位确认仍需独立的实际证据。本工具不会代替这些门槛。
