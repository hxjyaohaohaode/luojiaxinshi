# 验证记录

当前版本 1.23.0。本文说明测试体系、运行方法、本轮新增的测试和尚未完成的外部验收。通过数量不在这里手写，以对应提交的 [GitHub Actions](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/workflows/checks.yml) 运行记录和本地实际输出为准。

## 测试体系与运行命令

在仓库根目录执行。Windows 使用 `.\.venv\Scripts\python.exe`，Linux / macOS 使用 `.venv/bin/python`，下面统一写作 `python`。

```powershell
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
```

| 层级 | 命令 | 范围与边界 |
|---|---|---|
| 后端 | `python -m pytest -q` | `tests/test_*.py`，`pytest.ini` 固定 `testpaths = tests`。每项测试使用临时数据库和模拟模型，不读取正式 `data/`，不发起付费请求 |
| 前端单元 | `node --test tests/*.test.mjs` | 与 `npm test` 相同，使用 Node.js 22 内置测试运行器；应用本身没有 npm 运行依赖 |
| 浏览器回归 | `python scripts/run_browser_checks.py` | 在 `127.0.0.1:8786` 启动 `scripts/push_preview_server.py` 合成夹具，覆盖 Chromium、Firefox、WebKit 的既有界面回归，以及自然导入、个人材料、来源收件和持久推送。夹具沿用原有演示数据，来源读取与推送投递全部在本机模拟。可用 `--suite 脚本名` 只重跑一组。报告写入 `artifacts/<套件目录>/report.json`，日志在 `artifacts/ci-browser/` |
| Agent 浏览器 | `python scripts/run_agent_browser_checks.py` | 在 `127.0.0.1:8793` 启动 `scripts/agent_preview_server.py` 离线夹具，运行 `tests/agent-browser.mjs`、`agent-adaptive-browser.mjs`、`agent-fusion-browser.mjs`、`agent-quality-browser.mjs`、`composer-browser.mjs`。汇总在 `artifacts/ci-agent-browser/results.json` |
| 真实进程 | `python scripts/verify_local_runtime.py` | 随机本机端口启动真实服务进程，5 个合成账号并发提交、确认、修改通知与待办，再验证账号隔离、幂等、日历导出、停止重启和备份恢复。结果写入 `artifacts/runtime-acceptance.json`。不调用 AI，也不代表生产容量 |
| 协议与依赖 | `python scripts/genui_catalog.py --check`、`python scripts/evaluate_genui.py`、`npm audit --omit=dev`、`python -m pip_audit -r requirements.lock --strict` | 组件目录一致性、离线 GenUI 样例、npm 生产依赖与 Python 锁定依赖的已知漏洞审计 |
| 发布包 | `python scripts/build_release.py` | 按白名单打包源码到 `releases/`，并检查包内没有 `data/`、`artifacts/` 和 `.env` |

两个浏览器入口需要 Playwright 浏览器（版本锁定在 `package-lock.json`）。本机首次运行先执行 `npx playwright install chromium firefox webkit`，或用 `PLAYWRIGHT_PATH` 指向已有安装。端口 8786 / 8793 被占用时脚本直接退出，不会复用或结束其他进程，也不会碰 8765 上的正式服务。浏览器夹具清除了模型密钥环境变量，回复均为明确标注的合成数据。

下面的脚本会调用真实的小米 MiMo 接口并可能计费，只在需要验证凭证或模型行为时手动运行，没有放进 CI：`scripts/verify_notice_model.py`、`scripts/verify_business_notice.py --live`、`scripts/verify_speech_models.py --live`、`scripts/verify_personalization.py --live`、`scripts/verify_agent_adaptive_live.py --allow-paid-synthetic-test`、`scripts/verify_media_review_live.py --allow-paid-synthetic-test`。它们使用临时数据库和合成或项目自带材料，不读取正式账号。单次结果不代表固定耗时、准确率或费用。

## CI

`.github/workflows/checks.yml` 在推送到 `main`、Pull Request 和手动触发时运行：

- `tests`：Ubuntu 与 Windows 各一组，Python 3.12、Node.js 22。依次运行 pytest、Node 单元测试、GenUI 目录检查与离线样例、两项依赖审计、`verify_local_runtime.py` 和 `build_release.py`。
- `browser`：使用固定摘要的 Playwright 容器镜像，先确认三种浏览器都能启动，再运行 `run_browser_checks.py`；即使前者失败，也继续运行 `run_agent_browser_checks.py`，避免一组失败遮住另一组结果。
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
| `tests/test_account_and_insights.py`（新增） | 注册与邀请注册都必须同意隐私政策和用户协议，同意按 `POLICY_VERSION` 记录；政策版本与已有同意记录分开保存，登录后不自动弹窗或补写同意；`GET /api/legal` 返回模型服务方和备份保留天数。注销账号要求正确密码和“注销账号”确认词，之后该账号在所有带 `user_id` 的表和全文索引中不留文字，其他账号数据不受影响。提醒中心覆盖已过期、24 小时内截止、未确认期限标注、本人提醒、重复课程安排和未整理通知，并排除远期、他人负责和已完成的事项。`/api/reminders`、`/api/insights` 只返回本人数据，普通账号访问 `/api/admin/insights` 返回 403，管理员看板只含计数、不含通知标题或账号名。通知列表带有 `applicability` 字段 |
| `tests/test_mimo_speech.py` | 默认配置下声音复刻请求返回 403，且不会发到模型服务；WAV 写入 RIFF INFO 隐式标识后音频帧不变、重复标注不叠加，非 WAV 数据原样返回 |
| `tests/test_speech_cache.py` | 语音缓存重放返回同一份已加标识的 WAV |
| `tests/test_boundaries.py` | 前端脚本返回 `Cache-Control: no-cache` 和 ETag，带 `If-None-Match` 时返回 304；首页仍为 `no-store` |
| `tests/test_workflow.py` | 邀请注册夹具补充同意字段，适配新的注册要求 |
| `tests/test_verification_evidence.py` | 随已删除的证据导出脚本移除两项依赖它的测试，保留浏览器夹具限流重置只作用于自有合成数据库的边界测试 |

本轮结果见本轮提交的 CI 与本地运行。以下改动目前没有专门的自动化断言，依靠现有浏览器回归和人工查看：通知整理与聊天的独立并发槽、统一样式入口 `static/styles.css`、12px 字号下限、`static/choreography.js` 编排动效，以及平板、手机横屏和矮屏的响应式修复。

## 保留的异步交互回归

`scripts/verify_ui_continuity.mjs`、`verify_draft_continuity.mjs` 和 `verify_arrangement_recovery.mjs` 覆盖延迟保存后切页、并发草稿编辑、已保存但响应丢失、清理草稿失败及重新加载恢复。这些不是一次性截图脚本，保留在仓库中。

单独启动 `python scripts/mvp_preview_server.py` 后运行上述脚本（例如 `node scripts/verify_ui_continuity.mjs`）。默认仅连接 `127.0.0.1:8780` 合成环境；首次运行或政策版本更新后，用 `MVP_DATA_DIR=artifacts/continuity-新的运行编号/data` 指向新的夹具目录，避免复用旧账号和旧同意记录。`MVP_BROWSERS` 可选浏览器，`MVP_ARTIFACT_DIR` 可指定 `artifacts/` 内的独立输出目录。它们未合并进默认五组浏览器套件；保留源码不代表本轮已重跑通过。

新增的提醒回归位于 `tests/test_account_and_insights.py` 和 `tests/reminders.test.mjs`，检查已读与归档持久化、账号隔离、全部已读只操作点击时的提醒、改期重新提醒、超过 60 条提醒、旧请求回流、切换账号及网络失败重试。`tests/test_motion_assets.py` 在临时目录重建动效并对比当前生成资源。

## 尚未完成的外部验收

工程测试和合成数据不能替代下面这些验收，在完成前不应对外宣称已经达到：

- 真实手机提醒：在目标手机开启持久推送并验证关闭页面、锁屏、到期、改期及撤销；分别记录服务商接收和设备实际显示。另行导入 `.ics`，验证新建、重复导入、改期和取消。尚未开启持久推送时，页面提醒仅在页面打开期间运行。
- 真机多浏览器：Android、iOS、HarmonyOS 实机及其软键盘、系统音频、触摸手感和录音兼容性。目前只有桌面浏览器引擎和模拟视口的结果。
- 真实学生试点：真实学生在真实通知上的完整流程、使用日记录和效果对比。原方案要求的样本量和对照条件见 [办理闭环与演进契约](docs/MVP_WORKFLOW.md)。
- 校方统一认证：学号、工号和手机号目前只是自填账号名，没有接入学校统一身份认证或短信验证。
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
