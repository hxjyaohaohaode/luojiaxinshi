# 首次 main 验证后：邮件测试时钟补修

本记录冻结于 **2026-11-14T12:56:13.787962+00:00**。首次 main `f5f159407adcd578cb20adb3b4fe8f63e7455e77` 的[实际 push CI65](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43594868365)已完整通过；并行的[文档提交 CI64](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/runs/43594799745)出现一项真实邮件测试失败。两者分别保存，不能互相覆盖。新测试夹具补修及最终 main 必须由其自身 Actions 记录验证，本稿不提前给未执行的提交记通过。

## 1. 已实际完成的首次 main 验证

实际 main、artifact head、所有 checkout 均为 `f5f159407adcd578cb20adb3b4fe8f63e7455e77`，tree 为 `51ea046dac100e1d625b1e5d5344414ee8223c58`，event 为 push、branch 为 main。

| 范围 | 本轮实际结果 |
| --- | --- |
| 官方作业 | 9/9 completed/success |
| Linux 后端 | 139 文件；1,875 唯一，1,873 pass、2 Windows 条件 skip、0 fail/error |
| Windows 后端 | 四片与汇总 union 相等；139 文件；1,875 唯一，1,874 pass、1 POSIX TIME_WAIT skip、0 fail/error |
| Node | 两 OS 各 358/358；与 CI63 全部 case ID 相同，不相加成 716 个场景 |
| 应用浏览器 | 33/33 报告、1,056/1,056 正式检查；Sprint 78；原有序身份全部保留 |
| 看板 | 原 28 正式检查及额外 18 操作观测通过；观测不另加测试数 |
| 连续保存与恢复 | 990/990；三个 runner 均退出 0；原身份不变 |
| Agent / Composer / chat | Chromium 13/9；聊天三引擎 9/8/8，各自原件通过 |
| 几何与视觉 | 13 阶段、41 事件、0 dropped；三个录音快照 clip/clip、scrollLeft=0；实际查看本轮图并重算控件祖先可见交集 |
| 构建和依赖 | `app-EXBTH7EL.js` / `styles-BHHEBXRE.css`；25 产物、194 来源；完整 npm 与严格 Python 审计通过 |
| 容器 | 原日志中 9 组 smoke 实际通过，不混入 JUnit 数量 |

[CI65 完整机器记录](sprint-review-ci-65-main-success.json)与原 proof 逐字节相同，SHA-256 `f9d35f4951c5d9791b125fae8899960febbc26e950d3c7b755db347579800574`。全部官方 ZIP 的 SHA/字节数、实际 Git 对象、JUnit 唯一身份、早期/最终 33 文件逐字节一致性都已核验。CI61 视觉复核未通过记录与 CI62 的实际失败保留；该记录只证明实际查看与采样的范围，不称实体设备或所有帧都完成验收。

本轮共享 Linux / Windows 五人各 766 HTTP / 625 CRUD，写等待 P95 分别 **67.750 / 52.751 ms**，样本各 772、获取失败 0。它们不替代独立本地 9e86 的 **85.079 / 172.555 ms**；十人仍未达到原 `<100ms` 门槛。已有 51 项真实外部条件、8 项条件 P2、许可证选择、累计不少于五天实践与真实需求方确认均继续保留。

## 2. CI64 的真实失败范围

CI64 的 head 为 `b6c14b6811f8c4f9e0e3494c3e3c4db9bfa39fa1`，实际 PR checkout 为 `29950948ac3c3a2d015cec34b8a9e4d736e35b7a`，tree 与首次 main 相同。最终官方 **7 success / 2 failure**：Windows 第1分片失败，Windows 汇总门禁也按真实 JUnit 正确失败。其他作业的官方状态分别保留。

Windows 原汇总共有 139 文件、1,875 唯一用例：**1,873 pass / 1 fail / 1 POSIX skip / 0 error**；Node 358/358，构建、依赖审计、runtime、capacity、release 等后续步骤按原 workflow 实际执行并通过。完整收集不等于全部测试通过。

唯一失败为 `tests.test_mail_delivery::test_cancel_done_changed_contacts_and_do_not_replay_ambiguous_send`，旧第38行没有观察到 `uncertain`。原第1分片538用例与完整汇总逐项一致。[CI64 失败原件归档](sprint-review-ci-64-failure.json)包含官方终态、实际 checkout、完整 Windows 汇总与第1分片的原 ZIP 文本成员、日志、JUnit、SHA，以及独立分析。其余三分片和非 Windows 原件没有在本次归档中独立下载，不扩大成又一次完整原件重算。

旧失败日志没有记录早先固定的 `now`、实际入队 `due_at`、当时的 recent 全部状态或 provider 调用次数。原用例耗时不是唯一因果证据，后续通过也不能反写旧失败不存在。

## 3. 独立证明的测试前提缺口

旧用例先执行 `now=int(time.time())+1`，随后插入旧任务、执行一次 tick、再通过真实 `/api/notifications/email/test` 入队。HTTP 生产者按实际当前时间写 `due_at`；第二次 tick 却仍收到旧固定 `now`。生产合同明确只允许 `due_at <= now` 的 pending 任务被选中；如果 HTTP 入队的 due_at 已大于旧固定 now，合法未来任务不应调用供应商，也不应产生 uncertain。

受控复现直接调用仓库的原同名测试函数，使用真实 HTTP 路由、SQLite 和 tick。只替换 `mail` 模块自己的 `time` 引用，使实际新任务 `due_at=旧固定时刻+2`，没有修改全局/测试模块时钟，没有 sleep，没有改产品源或替换供应商行为。实际旧结果为 **done-task cancelled、test pending、provider 调用0，在原 uncertain 断言失败**。

## 4. 最小修复及已执行验证

本地单文件准备提交为 `dafc462aae68dbff7b8f824fcb1ab4b79a791077`，父提交为实际首次 main f5f；这是本地准备身份，最终远端交付身份由后续 PR/Actions 记录。

- 在当前 owner 的 outbox 中对比实际 POST 前后，要求恰好新增一个 `test:` 且 pending 的任务，取得其准确 ID 和 `due_at`。
- 将显式 tick 时刻向前对齐到该任务实际到期时刻，再执行原 uncertain 场景；不让未来邮件提前发送。
- 保留原全部业务断言和 `+120` / `+180` 偏移；新增准确任务 ID 的 uncertain 保留、不重发、邮箱变更后 cancelled 以及供应商调用恰好一次的检查。
- 同一受控 runner 修后一次通过：第一次实际发送1次并进入 uncertain，后续没有重发，第二个实际入队任务在邮箱变更后 cancelled。
- 该文件原有 **7 个用例一次全部通过，4.82 秒**。用例名称与顺序不变，没有新增正式 case；仍是后端 139 文件 / 1,875 用例。单个目标用例原7个 assert逐字保留并加强到14；全文件32个原 assert全部保留，现39个。

[修复完整证据](sprint-mail-clock-fixture-repair.json)保存原红绿观测、实际 runner、日志、JUnit、独立交叉审查及整合身份。新 Linux 源指纹为 `5f06785eb58102f9d5528d310a843e4dc5a1b376ee60b4c282df81a5d457117d`；指纹包含测试文件，因此与首次 main 不同。单文件准备树中只有 `tests/test_mail_delivery.py` 改变，其余 **883 条 Git blob/mode 完全一致**。产品、依赖、workflow、静态构建和运行时/容量脚本没有变化；未重跑独立负载来挑选更快数字。

## 5. 方向复查与交付边界

原 [128 项总账](sprint-requirements-128.json)、[25 项前端要求](../sprint-2026-11-14/frontend-25.json)、[209 项参考](../sprint-2026-11-14/components-209.json)和历史失败原件不改写。保持 FastAPI/SQLite/原生 ESM、绿色浅色视觉与既有业务权限。新增记录只区分旧事实、受控复现与后续实际运行，不将测试通过写成供应商、实体设备、模型人工评价或学校试点通过。

后续补修提交与最终 main 的完整执行状态，以[仓库 Actions](https://github.com/hxjyaohaohaode/luojiaxinshi/actions)及对应合并 PR 的明确提交、checkout、run 和原件为准。未完成的运行不计通过；CI64 的失败保持原样。
