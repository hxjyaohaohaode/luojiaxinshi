# 验证记录

## 账号验证、邮件与校园导入

`tests/test_verification.py`、`tests/verification.test.mjs` 和 `tests/auth-feedback.test.mjs` 覆盖验证码用途及账号绑定、有效期、限流、尝试次数、一次性消费、改密和联系方式变更，以及注册分步过程中保留已完成的验证。`tests/test_mail_delivery.py` 覆盖经本人验证并授权的收件地址、持久队列、撤回、限额与不确定投递；这些测试不向真实手机或邮箱发送消息。

`tests/test_campus_imports.py` 与 `tests/campus-imports.test.mjs` 覆盖课表及公众号清单识别的同意、预览、核对保存、周次日期、去重、回执、账号隔离、超额回滚和同名学校来源筛选。真实模型联调用合成CSV及截图输入，响应布局另经浏览器界面检查；真实教务导出、本人关注列表、手机桌面安装与锁屏提醒仍需实际参与者核验。

源码交付包会检查 Web App Manifest、离线页和安装图标是否存在；实验性创空间部署须先通过本地持久磁盘条件检查。依赖审计、合成工程测试和配置字段齐全均不构成比赛结项或公网可用性的证明。

## 对话动作、执行轨迹与可取消的新建手势

`OPENUI_VERIFY_SCRIPT=scripts/verify_chat_interactions.mjs` 配合 `python scripts/run_openui_browser_checks.py` 以隔离账号和合成回复检查三种浏览器。覆盖旧轮次无重生成、最后一轮状态检查、按用户发送时间进行 5 分钟分组、执行轨迹和真实耗时、默认收起与 CSS 网格反复展开、等宽数字、重复点击的 5 秒反馈环、增量文字晕染与减少动态效果、尾字保护、材料面板重排锚点、长短回复版本切换、末尾空白，以及间断滚轮、取消窗口和 Chromium 原生触摸上滑。记录在 `artifacts/chat-interactions/{browser}/`，已加入 CI。轮次、时间和复现文字为合成夹具；执行轨迹在实际产品中只读取该回复已有的工具记录和计时，不追加模型调用，也不展示模型私有推理。

手机上滑到阈值后松手、桌面在末尾再次滚动到阈值后停止，均先显示 1.2 秒的取消窗口。回拉、反向滚动、继续操作或点击取消会撤回本次新建；正常滚到末尾不会触发。旧对话和草稿继续保存在原位置。正文、展开记录和材料列的过渡使用 CSS 网格；阅读锚点只修正滚动位置，不参与计算展开高度。

`tests/test_reminder_occurrences.py` 验证真实结束时间、短课结束、未知结束时间、跨日与重复日程、全天边界、已读身份稳定和超过 20 项的未来提醒。`tests/chat-policy.test.mjs` 与 `tests/execution-trace.test.mjs` 验证动作适用状态、分组和轨迹中的未知时间不被编造；`tests/reminders.test.mjs` 保留账号隔离、批量快照与网络恢复检查。看板沿用 `scripts/verify_task_board.mjs` 的原生指针、触摸、键盘菜单、保存冲突、撤销和刷新持久化检查，去掉弹簧跟随与落位淡入。

## 紧凑输入与阅读空间

`OPENUI_VERIFY_SCRIPT=scripts/verify_chat_layout.mjs` 配合 `python scripts/run_openui_browser_checks.py` 检查三种浏览器的单行输入、显式换行增高和删除后收回、超长单行、菜单及附件、桌面阅读收起顶栏、空闲/上滚/重新输入恢复、程序滚动不触发，以及手机/平板/键盘高度。结果与截图在 `artifacts/chat-layout/{browser}/`，已经加入 CI。输入未显式换行时保持单行并随光标横向滚动；多行编辑仍受实际容器高度约束。原 `tests/composer-browser.mjs` 另行覆盖附件保存和真实模拟麦克风的录音转写交互。

阅读顶栏也接收隔离生成式组件内的真实滚动手势；输入控件和业务操作权限保持各自的处理流程。程序跟随、宽度重排和版本切换的滚动修正会跳过阅读手势判断。看板拖动期间固定顶栏状态，并区分触摸手柄的隐式指针捕获和看板的显式捕获；服务端确认位置后也不会重播卡片或列的入场动画。

## 非标准模型输出回归

`tests/test_answer_format.py` 检查普通 Markdown、JSON 围栏、BOM/CRLF、二次编码对象、逐字符及任意分片、真实图片身份引用、空响应、未知引用、重复字段、非有限数、截断结构、独立复核拒绝和记忆协议边界。`tests/test_openui.py` 同时检查围栏内的 UI 能增量显示，以及独立 UI 编排不能用普通正文代替界面。处理和恢复边界见 [答复格式兼容](docs/ANSWER_FORMAT.md)。

## 流式 OpenIntelligentUI 适配

新增 `tests/test_openui.py`、`tests/genui-openui.test.mjs` 覆盖增量 JSON 字段、转义和 Unicode、HTML 先于脚本可见、协议限制、账号与快照版本、保存与后续输入验证。`python scripts/run_openui_browser_checks.py` 在 8794 使用独立合成 Agent，覆盖 Chromium/Firefox/WebKit 的真实流式显示、同 iframe 启用、计算筛选、刷新恢复、键盘与手机尺寸、用户追问和宿主隔离；报告在 `artifacts/openui-browser/{browser}/report.json`，现已加入 CI 浏览器任务。真实 MiMo 验收命令与计费边界见 [实现记录](docs/genui/OPEN_INTELLIGENT_UI.md)。

浏览器回归还检查共享表单的按钮重复监听只发出一次请求，以及修正后只恢复契约兼容的已编辑字段、未编辑初值采用新稿。另有真实模型产物的离线回放脚本，验证实际生成程序的计算、非法输入、保存重算、手机布局及继续提问；它与合成测试和真实模型网络耗时分别记录。

当前版本 1.24.0。本文说明测试体系、运行方法、本轮新增的测试和尚未完成的外部验收。通过数量不在这里手写，以对应提交的 [GitHub Actions](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/workflows/checks.yml) 运行记录和本地实际输出为准。

## 测试体系与运行命令

在仓库根目录执行。Windows 使用 `.\.venv\Scripts\python.exe`，Linux / macOS 使用 `.venv/bin/python`，下面统一写作 `python`。

```powershell
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run build:check
```

| 层级 | 命令 | 范围与边界 |
|---|---|---|
| 后端 | `python -m pytest -q` | `tests/test_*.py`，`pytest.ini` 固定 `testpaths = tests`。每项测试使用临时数据库和模拟模型，不读取正式 `data/`，不发起付费请求 |
| QQ 群回放 | `python -m pytest tests/test_qq_group_intake.py tests/test_group_delivery.py -ra` | 将 `fixtures/qq-group/replay.json` 的标注消息通过签名回调重放，核对分流、原文保存、自动整理资格和提醒候选。另验证迟到退群、过长材料、附件失败补传、独立重试、撤权和下载。附件网络使用合成响应，送达和已读需要真实通道验收 |
| QQ 群浏览器 | `python scripts/run_browser_checks.py --suite verify_qq_group_intake_ui.mjs` | Chromium、Firefox 和 WebKit 上经真实来源页保存规则、筛选和分页、查看原文并下载附件。签名回调、账号和文件响应均为隔离合成夹具 |
| 前端单元 | `node --test tests/*.test.mjs` | 与 `npm test` 相同，使用 Node.js 22 内置测试运行器；应用本身没有 npm 运行依赖 |
| 浏览器回归 | `python scripts/run_browser_checks.py` | 在 `127.0.0.1:8786` 启动 `scripts/push_preview_server.py` 合成夹具，覆盖 Chromium、Firefox、WebKit 的既有界面回归，以及自然导入、个人材料、来源收件和持久推送。夹具沿用原有演示数据，来源读取与推送投递全部在本机模拟。可用 `--suite 脚本名` 只重跑一组。报告写入 `artifacts/<套件目录>/report.json`，日志在 `artifacts/ci-browser/` |
| 异步保存与恢复 | `python scripts/run_continuity_browser_checks.py` | 三组保留的检查全部执行；每组使用系统分配的独立临时端口、全新合成数据库及经过验证码流程创建的夹具账号，手机／桌面与日历横屏等既有尺寸均保留。规范报告和原始场景记录位于 `artifacts/continuity-browser/`，不会复用真实服务 |
| Agent 浏览器 | `python scripts/run_agent_browser_checks.py` | 在 `127.0.0.1:8793` 启动 `scripts/agent_preview_server.py` 离线夹具，运行 `tests/agent-browser.mjs`、`agent-adaptive-browser.mjs`、`agent-fusion-browser.mjs`、`agent-quality-browser.mjs`、`composer-browser.mjs`。汇总在 `artifacts/ci-agent-browser/results.json` |
| 真实进程 | `python scripts/verify_local_runtime.py` | 随机本机端口启动真实服务进程，默认5个合成账号；可显式指定 `--users 10 --notices-per-user 20 --output artifacts/pilot-runtime-10.json`。验证并发收件与修改、隔离、幂等、日历、重启和恢复。JSON分别报告正常CRUD、各路由、写入总等待／持有及恢复实测，默认输出 `artifacts/runtime-acceptance.json`。功能通过后仍须逐项核对试点性能门槛，不代表生产容量 |
| 协议与依赖 | `python scripts/genui_catalog.py --check`、`python scripts/evaluate_genui.py`、`npm audit`、`python -m pip_audit -r requirements.lock --strict` | 组件目录一致性、离线 GenUI 样例、全部 npm 锁定依赖（包括构建工具）与 Python 锁定依赖的已知漏洞审计 |
| 离线检索与容量 | `python scripts/verify_retrieval_quality.py`、`python scripts/verify_campus_capacity.py` | 合成全文尾部证据与截取偏移一致性、10,000 则通知的收件／全文检索／归组候选／容量拒绝和重复重放。测量结果属于本机单进程检查，不代表校园生产吞吐或真实模型准确率 |
| 发布包 | `python scripts/build_release.py` | 按白名单打包源码到 `releases/`，并检查包内没有 `data/`、`artifacts/` 和 `.env` |

浏览器入口需要 Playwright 浏览器（版本锁定在 `package-lock.json`）。本机首次运行先执行 `npx playwright install chromium firefox webkit`，或用 `PLAYWRIGHT_PATH` 指向已有安装。通用／Agent 套件使用 8786 / 8793，异步恢复协调器逐组分配空闲临时端口；已占用端口不复用，其他进程不结束，也不会碰 8765 上的正式服务。浏览器夹具清除了模型密钥环境变量，回复均为明确标注的合成数据。

下面的脚本会调用真实的小米 MiMo 接口并可能计费，只在需要验证凭证或模型行为时手动运行，没有放进 CI：`scripts/verify_notice_model.py`、`scripts/verify_business_notice.py --live`、`scripts/verify_speech_models.py --live`、`scripts/verify_personalization.py --live`、`scripts/verify_agent_adaptive_live.py --allow-paid-synthetic-test`、`scripts/verify_media_review_live.py --allow-paid-synthetic-test`。它们使用临时数据库和合成或项目自带材料，不读取正式账号。单次结果不代表固定耗时、准确率或费用。

## CI

`.github/workflows/checks.yml` 在推送到 `main`、Pull Request 和手动触发时运行：

- `tests`：Ubuntu 全量后端，Python 3.12、Node.js 22；继续执行 Node 单元测试、GenUI 目录检查与离线样例、两项依赖审计、`verify_local_runtime.py` 和 `build_release.py`。
- `windows-backend`：同一完整文件清单确定四个不重叠分片，分别在隔离 Windows 作业执行。每片报告只声明 `selected_complete`，不能声明整个项目 `complete`。
- `windows-results`：只下载本次 workflow attempt 的四份报告，验证源码摘要、完整文件清单、分片归属及真实 JUnit 一致后合并；缺片、重复、陈旧报告或伪造计数均失败。随后完整执行 Windows Node、GenUI、依赖审计、HTTP 并发恢复及打包，即使分片失败也继续保留其余检查结果。
- `browser`：使用固定摘要的 Playwright 容器镜像，先确认三种浏览器都能启动，再运行 `run_browser_checks.py`；即使前者失败，也继续运行 `run_agent_browser_checks.py`，避免一组失败遮住另一组结果。
- `continuity`：在同一固定浏览器镜像中执行全部异步保存与恢复检查，保留每个场景的实际断言、三浏览器／尺寸清单及独立夹具日志。它与其他作业共同组成同一次提交的完整验收。
- `container`：构建镜像后以只读根文件系统、去除全部权限、非 root 用户和 production 配置启动，检查健康接口、运行用户、`manage.py check`、提示资源和首页。不包含公网域名、HTTPS 证书或真实服务器部署。

每次运行的 Summary 由 `scripts/write_ci_summary.py` 写入实际数量，JUnit、浏览器 JSON 和合成截图作为 Artifacts 保留 14 天。

## 1.22.0 新增测试

后端测试覆盖统一收件与跨入口去重、原通知变更和不同批次保护、来源订阅与群消息逐用户重试、自动整理授权与配额、当前个人条件核对、个人材料版本与提交快照、材料包下载、持久推送队列与撤销。新增浏览器套件为 `verify_natural_intake.mjs`、`verify_task_materials.mjs`、`verify_source_inbox.mjs`、`verify_push_browser.mjs`，均已纳入默认 CI 入口。

推送浏览器测试使用真实应用接口和 Service Worker，PushManager 与服务商投递由本机夹具模拟；它验证用户授权、关闭重开、退出解绑和服务商接收状态，不证明真实手机已收到通知。来源浏览器测试使用合成官网内容，不代表公众号、QQ 或微信群已经完成真实授权联调。

公开网站的真实采集可另行运行 `python scripts/verify_public_source.py --url 列表地址 --article-path-prefix 正文路径前缀 --allow-public-network`。该脚本明确访问指定公开网站，在临时账号验证真实保存、重复刷新和待核实归类，不读取正式账号，也不启动模型或推送；报告在 `artifacts/public-source-verification/report.json`。只证明所选来源和路径范围内的结果，不保证整站、登录后内容或其他渠道。

## 1.21.0 新增测试

通知接入、信息型通知处理、灵活前置与办理清单、活动时段、迁移和三浏览器完整流程的测试见 [通知接入与办理契约](docs/NOTICE_FLOW.md)。链接内容与模型均使用明确标识的合成夹具；实际写入和导出经过应用接口，不用浏览器假回执代替保存。

## 1.20.0 新增测试

| 测试 | 覆盖内容 |
|---|---|
| `tests/test_account_and_insights.py`（新增） | 注册与邀请注册都必须同意隐私政策和用户协议，同意按 `POLICY_VERSION` 记录；政策版本与已有同意记录分开保存，登录后不自动弹窗或补写同意；`GET /api/legal` 返回模型服务方和备份保留天数。注销账号要求正确密码和“注销账号”确认词；删除本人私域及全文索引、关闭私密分享。1.24.0 的 `test_campus_sprint.py` 另验证对方最小脱敏回执、已正式发布的公告／原件按接收权限保留、发布者名称脱敏，不能概括为所有历史记录均消失。提醒中心覆盖已过期、24 小时内截止、未确认期限标注、本人提醒、重复课程安排和未整理通知，并排除远期、他人负责和已完成的事项。`/api/reminders`、`/api/insights` 只返回本人数据，普通账号访问 `/api/admin/insights` 返回 403，管理员看板只含计数、不含通知标题或账号名。通知列表带有 `applicability` 字段 |
| `tests/test_mimo_speech.py` | 默认配置下声音复刻请求返回 403，且不会发到模型服务；WAV 写入 RIFF INFO 隐式标识后音频帧不变、重复标注不叠加，非 WAV 数据原样返回 |
| `tests/test_speech_cache.py` | 语音缓存重放返回同一份已加标识的 WAV |
| `tests/test_boundaries.py` | 原生源脚本返回 `Cache-Control: no-cache` 和 ETag，带 `If-None-Match` 时返回 304；首页仍为 `no-store`。1.24.0 的内容哈希构建资源另由 `test_frontend_bundle.py` 验证 immutable 缓存和产物完整性 |
| `tests/test_workflow.py` | 邀请注册夹具补充同意字段，适配新的注册要求 |
| `tests/test_verification_evidence.py` | 随已删除的证据导出脚本移除两项依赖它的测试，保留浏览器夹具限流重置只作用于自有合成数据库的边界测试 |

上列为历史版本新增测试。当前完整结果以本轮提交的 CI 与本地运行记录为准；1.24.0 新增对构建样式层、完成回执动效、移动点击区及窄屏的自动化断言，但有限视口不能推断所有平板、横屏、输入法或真机条件均已验收。

## 保留的异步交互回归

试点联动使用 `python scripts/run_browser_checks.py --suite verify_pilot_workspace.mjs` 在 Chromium、Firefox、WebKit 各开独立电脑、手机尺寸和接收人会话。覆盖真实注册提交、独立会话、设置更新、通知转待办、日程、正在编辑的办理详情、站内协作及断线恢复。记录每步 HTTP 状态、请求耗时和另一端可见耗时，前台本机的更新目标是五秒内。验证码由隔离服务捕获，浏览器和数据写入是真实执行。完整回归默认包含本套件；详细口径见 [试点链路](docs/proactive/PILOT_RUNTIME.md)。

`scripts/verify_ui_continuity.mjs`、`verify_draft_continuity.mjs` 和 `verify_arrangement_recovery.mjs` 覆盖延迟保存后切页、并发草稿编辑、已保存但响应丢失、清理草稿失败及重新加载恢复。这些不是一次性截图脚本，保留在仓库中。

统一运行 `python scripts/run_continuity_browser_checks.py`，它为每组检查创建并清理自己拥有的全新夹具，执行所有默认浏览器和尺寸；原脚本仍可单独诊断。协调器清除场景／视口过滤环境变量，并核对全部声明浏览器及尺寸，不允许局部选择冒充全套。报告保留场景原文并汇总真实检查，空场景、失败、缺失报告及超时均失败。它已加入 CI 的 `continuity` 作业；只有本次提交的实际结果才能证明通过。

新增的提醒回归位于 `tests/test_account_and_insights.py` 和 `tests/reminders.test.mjs`，检查已读与归档持久化、账号隔离、全部已读只操作点击时的提醒、改期重新提醒、超过 60 条提醒、旧请求回流、切换账号及网络失败重试。`tests/test_motion_assets.py` 在临时目录重建动效并对比当前生成资源。

## 尚未完成的外部验收

工程测试和合成数据不能替代下面这些验收，在完成前不应对外宣称已经达到：

- 真实手机提醒：在目标手机开启持久推送并验证关闭页面、锁屏、到期、改期及撤销；分别记录服务商接收和设备实际显示。另行导入 `.ics`，验证新建、重复导入、改期和取消。尚未开启持久推送时，页面提醒仅在页面打开期间运行。
- 真机多浏览器：Android、iOS、HarmonyOS 实机及其软键盘、系统音频、触摸手感和录音兼容性。目前只有桌面浏览器引擎和模拟视口的结果。
- 真实学生试点：真实学生在真实通知上的完整流程、使用日记录和效果对比。原方案要求的样本量和对照条件见 [办理闭环与演进契约](docs/MVP_WORKFLOW.md)。
- 校方统一认证：学号、工号目前仍是自填信息，没有接入学校统一身份认证。短信验证码已实现并有本人收码记录；邮箱验证码已实现发送适配，仍须完成真实送达验证。这些验证不授予学校身份或学院权限。
- 生产部署容量：公网 HTTPS、反向代理、真实服务器的容量、监控、备份恢复演练。当前仅适合单实例小规模部署，`verify_local_runtime.py` 的合成负载不是容量上限。

此外，模型真实准确率、延迟和费用，声音复刻（默认关闭）的授权流程与效果，QQ / 公众号的真实平台授权联调，以及隐私政策、用户协议和 AI 标识是否满足适用规定，都需要在实际配置下另行确认。

## 历史验证记录

1.19.x 及更早各轮的逐项结果、真实模型样例、本机升级记录和当时的证据文件已从当前文档中移除，完整内容见 git 历史（例如 `git log -p -- TESTING.md`、`git log --stat -- docs/verification`）。历史数字只代表当时的版本和范围，不与本轮结果累计。

## 1.23 容量与事项归组回归

- `tests/test_usage_limits.py`：超过旧 200 则门槛的收件及导入、可配置额度、重复收件、导入事务回滚、跨入口存储和会话容量、账号隔离、检索 SQL 数量。
- `tests/test_notice_matters.py`：保守候选、跨年度／场次排除、确认归组、合并已有组、任务或归组变化后的旧预览拒绝、排除候选、拆组与删除、JSON 往返、备份与缺表检测。
- `tests/notice-matters.test.mjs`：列表归组完整保留当前筛选的通知，不重新加入已筛除的成员。
- `scripts/verify_notice_matters.mjs`：Chromium、Firefox、WebKit 的账号容量、候选核对、归组预览、列表聚合／逐则切换、手机及键盘高度、拆组真实操作。运行 `python scripts/run_browser_checks.py --suite verify_notice_matters.mjs`。
- 当前实现的吞吐不因容量提高自动变成大规模部署能力；容量验证与并发／真实渠道验收分别记录。

## 发布前运行脚本检查

`tests/test_runtime_fixture_cleanup.py` 验证 Windows 临时文件句柄的有限重试、永久错误不被隐藏，以及清理目录的范围检查。`verify_local_runtime.py` 仅在服务退出与临时目录清理全部完成后写入通过报告。

工作区及布局回归只等待可见元素当前运行的有限动画，并给出明确超时；折叠筛选中的隐藏动画及暂停的提示条不作为页面就绪条件。布局、焦点、草稿和真实保存行为继续分别断言。

布局回归显式创建并选中合成会话，再验证 `#chat` 恢复为 `#chat/{id}`；页面就绪判断同时核对实际路由与已渲染页面，覆盖有历史会话时的正常跳转。

## 刷新恢复与浮动顶栏回归（2026-10-27）

- `tests/test_reply_preview.py`：生成/核验中连续 GET、改稿清空旧 UI、失败稿恢复、账号隔离、主动选择版本持久化，以及未完成稿不进入后续模型上下文。
- `tests/test_chat_continuity.py`：同账号同对话的真实操作回执、当前状态与撤销状态；作者和审核者同步取得回执；纯表扬零模型调用且不冒充业务操作，授权和后续任务不走捷径。
- `OPENUI_VERIFY_SCRIPT=scripts/verify_chat_recovery.mjs .venv/Scripts/python.exe scripts/run_openui_browser_checks.py`：三个浏览器在真实 SSE 核验等待期间刷新，检查最新 UI 恢复、最终原文一致以及旧版/最新版选择后的再次刷新。模型边界仍使用合成输入，专用夹具显式保持核验阶段，在检查完刷新恢复后才释放；45 秒未释放时失败。这是可重复的状态验收，不是速度基准。
- `scripts/verify_chat_layout.mjs` 验证顶栏显隐采用浮层透明度/位移动画；显隐和空闲恢复前后阅读区域的高度、位置、滚动位置一致。
- `scripts/verify_chat_interactions.mjs` 验证执行摘要没有内嵌时间线，完整轨迹通过独立窗口打开，搜索和真实详情仍可使用。

实质性事实和互动代码继续执行原有程序检查与独立模型审查；模型仍使用配置的完整思考和输出上限，不用合成计时承诺真实服务延迟。


## 完整一轮与 main 交付（2026-11-03）

最后一次代码修改后重新执行全部检查，以同一份源码为基础。整轮之间修改代码，原批次只保留为诊断记录，不计为冻结版本通过。完整入口和范围见 [main 整轮验收](docs/proactive/MAIN_SYNC.md)，CI 的全部任务见 `.github/workflows/checks.yml`。

后端可使用 `python scripts/audit_full_suite.py --workers 4 --output artifacts/full-audit-suite --junitxml artifacts/ci/python-tests.xml`；它执行全部后端文件，合并真实 JUnit，核对源码前后摘要。Node 用例、当前16组通用浏览器（以本提交 `run_browser_checks.py` 的 `SUITES` 及实际报告为准）、五组 Agent，以及 OpenUI/聊天布局/交互/恢复仍须完整执行。依赖审计、GenUI 检查、`verify_local_runtime.py`、`build_release.py` 与生产 Docker 启动和解析验证也包含在整轮内。

本地完整一轮通过后再正常推送，检查新 main 提交实际触发的 Actions 全部 jobs，再确认功能分支已合入并清理。旧提交、局部补跑、离线模型夹具及桌面模拟视口不替代当前 main CI、真实渠道或真实试点验收。

隔离运行设置 `CAMPUS_AUTO_LOAD_ENV=0`，使配置模块在导入时不读取项目 `.env`。本机正常启动仍按原规则读取配置，操作员显式的 `--local-env` 入口继续生效。后端协调器、浏览器夹具和 CI 均设置隔离标记；测试分组仅由当前文件清单决定，不读取旧报告作为分组输入。

后端每个分片默认最多 2400 秒，超时返回失败并只终止该分片创建的进程树。Windows 单机四片曾实测用时 2396.67 秒，因此 CI 将同一分组分配到四个独立作业，各作业限时仍为 45 分钟，未提高分片期限或删除用例。执行前移除同名旧 JUnit；缺失报告不能通过。分片保留逐用例日志和超过 90 秒时的线程栈，便于区分慢用例、等待和退出阻塞。

`--only-shard 1` 仅供上述 CI 调度，不替代本地全量命令。`--merge-partitions artifacts/windows-partitions` 要求同一源码的所有声明分片，并核对每个 JUnit 用例所属文件及计数。需要重跑时应重跑完整 workflow；不同 attempt 的部分成功不能拼成当前整轮验收。

## 冲刺新增回归与证据口径

新增 `test_sprint_lists.py`、`test_sprint_notifications.py`、`test_sprint_official_time.py`、`test_campus_sprint.py`、`test_intake_round_isolation.py`、`test_notice_phase_tracking.py`、`test_source_fetch_contracts.py` 以及分页、名册前端行为测试。真实浏览器入口 `verify_sprint_ui.mjs` 已加入默认门禁；源网络、模型和外发通道仍使用隔离的合成输入。

`verify_campus_capacity.py` 对相同一万条样本并排测量旧全量读法与新分页、完整语义筛选、全文索引及短中文查询。每项记录冷态、五次热态 P50/P95、响应体及正确性；五样本 P95 使用最近秩最大值，不冒称生产 SLA。

本次执行环境禁止提升权限启动本地浏览器；该限制不会被记为通过。浏览器实际结果以指定提交的 CI 报告为准。真实手机后台/锁屏、真实消息供应商、独立人工标注和校园现场使用仍是独立验收，不能由 CI 合成数据替代。

### 发布中断、持久停止与缺件恢复回归

本轮补修的后端用例位于 [test_campus_submissions.py](tests/test_campus_submissions.py)，使用真实 API、隔离 SQLite 和当前权限模型，覆盖以下边界：

- 停止和发布竞争时只产生一个有效结果；已经解析但尚未提交的迟到发布不能绕过已落库的停止记录。停止响应丢失后重试保持同一结果，同编号发布持续返回 `publication_cancelled`。
- 已提交发布只返回本人原请求的最小标识，不撤回正文、原件或既有投递。跨学院调任后，最小回执仍属于原发布人；全文详情和完整发布重放继续拒绝越权访问，其他账号不能读取该回执或停止原请求。
- 旧草稿版本失效时，验证先确认停止旧请求，再另行核对新编号的恢复流程。缺件名称随草稿保存、刷新和旧客户端正文更新保留，显式清空后才能发布；名称不被当作已上传原件。
- 在停止动作之后建立的备份，恢复后仍保留其中的停止记录，同时撤销旧成员与外发授权。测试另外覆盖旧库迁移、已有结构标记但缺表、未来结构版本、个人导出和账号注销级联删除。这不证明早于停止动作的快照能恢复后来发生的决定。

前端 [campus-publication-submission.test.mjs](tests/campus-publication-submission.test.mjs) 验证原请求内容不可替换、受众凭据续期、版本冲突、同账号恢复、账号切换与路由迟到、重复重试及停止结果处理；共用暂存的写入／清理响应丢失由 [continuity.test.mjs](tests/continuity.test.mjs) 单独验证。[campus-publication-retry.test.mjs](tests/campus-publication-retry.test.mjs) 使用实际页面委托处理器，验证新输入独立草稿、附件缺件提示和明确移除。取得已发布的权威最小回执后，先按版本清理原暂存；即使随后获取旧详情被拒绝，也保留新草稿并允许继续编辑。

真实浏览器场景仍在 [verify_sprint_ui.mjs](scripts/verify_sprint_ui.mjs) 内核对丢失发布响应后的原内容重试、独立新草稿和停止操作，并用迟到原请求验证后端拒绝。Node 夹具、单项后端回归与浏览器报告分别记录；新增场景是否通过以包含本轮补修的实际 CI 报告为准，不沿用此前提交的浏览器通过结果，也不把合成发布当作真实学校通知或真实渠道验收。
