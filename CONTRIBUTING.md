# 一起开发珞珈信使

仓库根目录就是原项目的“系统_开发”。同学克隆后不需要原电脑的目录、数据库或 Codex 环境。项目方案、调研底稿和视觉设计在 `项目资料/`；运行中的角色、图标和视频已经放入 `static/assets/`。

## 第一次启动

安装 Python 3.12 和 Git。Node.js 22 仅用于前端单元测试，应用本身没有 npm 运行依赖，也不需要前端打包。

```powershell
git clone https://github.com/hxjyaohaohaode/luojiaxinshi.git
cd luojiaxinshi
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

也可以在资源管理器双击 `启动工作台.cmd`。启动器会在仓库内建立 `.venv`、安装锁定依赖、从 `.env.example` 建立本机配置，初始化新的数据库并打开浏览器。如果 Python 不在 PATH 中，可以使用 `start.ps1 -PythonPath '你的python.exe完整路径'`。不要在 GitHub 下载的 ZIP 文件内部直接运行，先完整解压。

默认地址为 `http://127.0.0.1:8765`。首次启动会提供仅供本机使用的管理员注册链接；普通成员可以自行注册。管理员链接、数据库与账号密码不在仓库中，每台开发电脑独立初始化。停止和重启使用仓库中的对应 `.cmd` 文件。

Linux / macOS 可按下面的等价步骤启动；这些启动命令尚未在实体 Linux / macOS 机器验证：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv/bin/python manage.py init
.venv/bin/python manage.py serve
```

无 API 密钥可以保存通知、解析附件、手工整理、编辑待办、使用日历。当前代码使用 MiMo 接口，填入本机 `.env` 的 `MIMO_API_KEY` 后重启；配置和已验证范围见 `MIMO_INTEGRATION.md`。不要把密钥贴进 Issue、提交记录或截图。部署配置由维护者管理，普通用户设置中不提供模型凭证配置。

## 验证修改

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.test.mjs
.\.venv\Scripts\python.exe scripts/genui_catalog.py --check
.\.venv\Scripts\python.exe scripts/evaluate_genui.py
npm audit --omit=dev
.\.venv\Scripts\python.exe -m pip_audit -r requirements.lock
```

前端没有新增 npm 包；`package-lock.json` 仍然保留，用于固定和审计空的依赖树。

互动组件画廊地址为 `/static/genui/gallery.html`，可检查所有组件、亮暗主题和窄屏。需要真实 HTTP 流程但没有模型密钥时，运行 `python scripts/genui_test_server.py`，打开 `http://127.0.0.1:8767`。该服务只用 `artifacts/genui-browser-data` 下的合成测试数据，回复明确标记为工程示例，不代表真实模型输出。测试账号及测试入口见该脚本和 `docs/genui/TESTING.md`。

## 分支与协作

从最新 `main` 建立自己的分支，例如 `feat/calendar-filter` 或 `fix/mobile-alignment`。小步提交并发起 Pull Request，描述实际问题、修改后的行为、验证结果与未验证项。不要直接把其他人的本机数据库同步进仓库。

```sh
git switch main
git pull --ff-only
git switch -c feat/your-change
# 完成修改与检查后
git add 具体修改的文件
git commit -m "描述问题和修改"
git push -u origin feat/your-change
```

不要使用 force push、破坏性数据库迁移或提交真实用户导出文件。`data/`、`.env*`、备份、日志、验收数据、数据库文件和私钥都已排除；`.env.example` 是可以提交的空配置示例。上传测试附件时使用合成内容。历史资料与代码不一致时，以当前代码、README 和明确标注的验收记录为准。

`schema/genui/catalog.json` 是组件目录唯一事实源。改动后运行 `python scripts/genui_catalog.py` 生成派生文件，再运行 `--check` 与相关测试。不要直接改生成文件；模型内容不得成为可执行 HTML、JS 或 CSS。

## 附件与资料

`项目资料/文件清单.json` 记录共享附件的相对路径、大小和 SHA-256。原始 Word/PDF 没有重新排版或覆盖，历史版本保留在原文件名下。应用附件解析器支持的格式和预览限制见 README。真实用户上传文件保存在私有数据库中，不能用 Git 作为账户数据同步或备份渠道。

本仓库未新增一个替用户决定的项目开源许可证。公开可见不等同于所有素材都取得了再分发或商业授权；第三方依赖许可见 `THIRD_PARTY_NOTICES.md`，原创角色来源见 `ASSETS.md`。对外发行前由项目维护者确定项目许可证和校园标识的使用方式。

`scripts/update_mimo_documents.py` 是维护者的本机文档套版辅助脚本，依赖另行提供的个人文档模板，不参与应用启动或测试。协作所需的已生成 Word / PDF 成品已包含在 `项目资料/`，无需运行该脚本。
