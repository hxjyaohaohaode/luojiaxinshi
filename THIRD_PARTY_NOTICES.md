# 第三方资源与新增依赖登记

## Codex 智能任务运行时适配（2026-10-22）

参考用户提供的 OpenAI Codex 源码目录（Apache-2.0，Copyright 2025 OpenAI），按现有 Python/FastAPI 项目独立重写执行循环、工具权限编排、子任务、上下文与 SDK/API 模式；未复制 Rust 实现、完整提示词或官方 SDK 源码。参考路径与文件 SHA256 见 `docs/CODEX_SOURCE_MANIFEST.json`，能力边界见 `docs/CODEX_RUNTIME.md`。上游 LICENSE 与 NOTICE 原文保留在 `docs/licenses/codex/`。没有新增 Python 或 npm 运行依赖；命令沙箱为维护者可选的已有 Docker 运行环境，所选镜像的分发许可另行遵守。

## genui 本次新增

无新增 npm 或 Python 运行依赖。协议、校验、表达式、DOM/SVG 图表、组件画廊均独立实现；不复制第三方产品前端、样式、提示词或商标。

| 资源 | 版本/许可证 | 用途 |
| --- | --- | --- |
| 浏览器 DOM、SVG、MathML、TextDecoder、fetch | 浏览器原生能力，不分发第三方代码 | 界面、图表、公式子集、UTF-8 和流式传输 |
| 现有系统字体栈 | 操作系统已有字体；不复制或打包字体文件 | 中英文字体回退 |
| 现有本地 SVG 图标 | 项目现有路径图标，自行组合绘制 | 页面和动作图标 |
| 珞珈小信使 PNG | 本应用生成的原创角色资产，来源见 ASSETS.md | 类型化宿主组件与情境反馈 |

既有 Python 依赖继续使用 `requirements.lock` 固定版本，本次不升级。安全审计结果在 `docs/genui/TESTING.md` 记录；没有新增依赖不代表不存在既有依赖风险。

## 本轮媒体、附件与协作工具

CSV / XLSX 预览使用 Python 标准库和已锁定的 defusedxml 0.7.1（PSF 许可证）；未新增解析依赖。`static/assets/genui-demo.webm` 是本项目用 Canvas 绘制并录制的合成演示，无第三方片段、音轨或远程资源。V4 图标为本项目生成资源的尺寸适配，来源见 ASSETS.md。

GitHub Actions 只在仓库检查环境中运行，不进入产品包。以下工具均经官方仓库许可证接口核验为 MIT，固定提交而非浮动版本：

| 名称 | 版本 / 固定提交 | 许可证 | 用途 |
| --- | --- | --- | --- |
| actions/checkout | v4 / 11d5960a326750d5838078e36cf38b85af677262 | MIT | 获取待检代码 |
| actions/setup-python | v5 / a26af69be951a213d495a4c3e4e4022e16d87065 | MIT | Python 3.12 测试环境 |
| actions/setup-node | v4 / 49933ea5288caeca8642d1e84afbd3f7d6820020 | MIT | Node.js 22 测试环境 |

参考资料中的原始文档和历史方案是用户明确指定共享的项目附件，不作为第三方 UI 库、字体或运行时依赖。两张第三方标识/建筑参考图片没有打包再分发。

## 历次参考融合核查（2026-10-22）

本轮重新阅读 LangChain 工具上下文、LangMem 记忆工具、CopilotKit 宿主状态，以及 Activepieces、GenericAgent、BettaFish 的相关实现和 autoresearch 评估说明。借鉴接口边界和执行原则，使用本项目原有 Python/SQLite/原生 DOM 独立适配；未复制上述框架源码、安装其运行依赖或引入品牌素材。具体文件、读取范围和 SHA-256 见 `docs/REFERENCE_FUSION_MANIFEST.json`；采用与未采用边界见 `docs/REFERENCE_FUSION_AUDIT.md`。前端目录中的混合许可、示例代码和依赖链接不构成统一的再分发授权。
