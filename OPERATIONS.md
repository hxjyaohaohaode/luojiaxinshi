# 运行、备份与迁移

## Windows 本机

维护命令和验收脚本的重定向输出统一为 UTF-8；外部程序读取命令输出时应按 UTF-8 解码，避免英文 Windows 的默认代码页造成中文乱码或命令错误。

双击 `启动工作台.cmd`。当前电脑已安装项目虚拟环境；在新电脑使用时需要带 `venv` 的 Python 3.12 或更新兼容版本，首次启动联网安装 `requirements.lock` 中的依赖。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -NoBrowser
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Restart
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1
```

可用 `-PythonPath 'C:\Python312\python.exe'` 指定新环境的 Python。已有 `.venv` 不会被覆盖。启动脚本先验证本目录的进程身份，再复用或停止服务；占用端口的其他应用不会被结束。更换端口须同时修改 `.env` 中的 `APP_PORT` 和 `APP_ORIGIN`。

运行记录保存在 `data/logs/server.log`、`data/logs/server-error.log`；启动时超过 2 MB 的旧日志留存为 `.previous`。请求访问日志默认关闭，不记录通知正文或模型密钥。`data/campus-runtime.json` 记录本目录的服务进程，用于停止和重启。停止时正在进行的请求可能中断，日常操作应先完成保存；未完成的 AI 作业会提示重试。

健康状态：`GET /api/health`。数据检查：

```powershell
.\.venv\Scripts\python.exe manage.py check
```

检查输出包含数据库完整性、用户数、配置状态和模型名，不打印密钥。

## 账号维护

```powershell
.\.venv\Scripts\python.exe manage.py init
.\.venv\Scripts\python.exe manage.py invite
.\.venv\Scripts\python.exe manage.py invite --admin
.\.venv\Scripts\python.exe manage.py reset-password --username your_name
```

首次 `init` 在尚无管理员时生成管理员一次性邀请；普通成员可直接注册，不影响管理员初始化。已有数据不会覆盖。邀请有效 7 天且只能使用一次。密码重置通过本机交互输入并使旧会话失效。管理员可管理邀请和导入获授权公众号文章，无权浏览其他账号的通知与对话。普通成员注册后保存一次性恢复码，用于自助重设密码；使用后会轮换新恢复码并退出原有会话。

## 数据与备份

主数据库 `data/campus.sqlite3` 包含通知原件、文字、个人条件、对话与材料、来源目录、待办和修改记录。运行时还有 SQLite WAL 文件，**不要在运行中只复制主数据库文件当作备份**。

有账号后，服务启动及每小时检查是否需要当天备份，使用 SQLite 在线备份生成 `data/backups/auto-YYYY-MM-DD.sqlite3`，执行完整性校验，默认保留 7 天。首次创建账号后，最迟下一次小时检查生成首份自动备份。可以立即手工备份：

```powershell
.\.venv\Scripts\python.exe manage.py backup
```

手工备份写入项目 `backups/`，也可指定 `--file 'D:\受控备份目录\campus.sqlite3'`。目标文件必须不存在。备份包含私人原件；登录会话、未使用邀请、QQ 收件绑定、未使用绑定码、回复分享令牌及对话模型授权从快照中清除。恢复旧版原始快照时也会清理这些授权。对话消息仍保留；恢复后需要本人重新绑定 QQ、重新确认对话模型授权，分享链接须重新创建，避免旧快照复活已经撤销的授权。将重要快照另存至有访问控制的加密磁盘或备份系统，以覆盖本机硬盘故障；本机同盘副本不能解决磁盘损坏。

保留天数通过 `BACKUP_RETENTION_DAYS` 调整。自动清理只处理应用创建的命名文件。通知删除会删除在线关联记录；历史备份在保留期届满后清理。`.env` 需另行保管，不在数据库备份中。恢复操作不会恢复已经失效的登录会话。

## 恢复到新目录

先停止服务，保持旧目录可回退。恢复工具拒绝覆盖已存在的数据库。

```powershell
.\stop.ps1
$env:DATA_DIR = 'D:\校园通知恢复数据'
.\.venv\Scripts\python.exe manage.py restore --file 'D:\受控备份目录\campus.sqlite3'
.\.venv\Scripts\python.exe manage.py check
Remove-Item Env:DATA_DIR
```

确认恢复成功后，将 `.env` 的 `DATA_DIR` 改成该新目录，再启动工作台。用原有账号登录，核对通知原件、待办数量和历史记录。恢复前已经导入的外部日历不受数据库恢复控制。

恢复会先校验备份版本、必要数据表、完整性和数据关联，在同目录的临时文件中完成恢复及清理旧会话，最后一次性发布新数据库。校验失败或目标被其他进程占用时不会覆盖已有文件。目标目录需使用支持硬链接的本机文件系统，如 NTFS 或 ext4；文件系统不支持时会明确报错，请换到受支持目录后重试。

可运行 `.\.venv\Scripts\python.exe scripts/verify_local_runtime.py` 复现隔离的真实进程验收：5 个测试账号并发提交、确认、修改，随后验证停止进程、重启及备份恢复。它使用独立临时目录和随机本机端口，不调用 AI，不使用正式账号，结果写入 `artifacts/runtime-acceptance.json`。

## 后续服务器部署

提供单实例应用加 Caddy HTTPS 的 `compose.yaml`、`Dockerfile`、`Caddyfile`。SQLite 数据卷持续保存；前端与 API 同源，应用端口不直接发布到公网。请使用独立 Linux 服务器或兼容 Docker 的主机，域名解析到服务器并开放 80 / 443。

本机镜像构建曾被 Docker Hub 身份服务网络超时阻断。仓库 CI 另行构建并检查非 root、只读根文件系统、健康、数据库与界面提示资源，结果以当前提交的 GitHub Checks 为准；容器使用 production 配置和占位 HTTPS 源，主机只发布回环测试端口。此检查不包含公网域名、Caddy 证书或真实服务器部署，服务器阶段仍须实际复验下面的步骤。

在服务器目录复制 `.env.example` 为 `.env`，设置：

```dotenv
APP_ENV=production
APP_DOMAIN=你的域名
APP_ORIGIN=https://你的域名
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_TEXT_MODEL=mimo-v2.6-pro
MIMO_API_KEY=在服务器本地填写小米按量API密钥
BACKUP_RETENTION_DAYS=7
```

```sh
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose exec app python manage.py init
docker compose exec app python manage.py check
docker compose ps
```

首次 `init` 输出的管理员链接使用生产域名。不要把已有本地 HTTP 配置直接复制到公网使用。Compose 设置单应用进程、768 MB 内存、只读应用文件系统、临时目录、低权限用户和健康检查；仅适合当前小规模 MVP。当前未做多实例 SQLite 共享部署，勿直接增加应用副本。

迁移现有数据：在本机生成一份完整备份，通过自己控制的安全渠道送到服务器；停止应用，用备份恢复到全新的数据目录／数据卷，再挂载该卷启动。恢复过程清空会话和未使用邀请，已有用户重新登录。不要在未验证恢复前删除本地数据和备份。

部署验收至少包括：HTTPS 正常、普通账号间相互不可读写、AI 真实调用成功且引用可回查、重启持久化、备份可恢复、改期状态和手机日历行为。公网上线后配置主机告警、磁盘剩余空间与 `/api/health` 监控，并定期更新已锁定依赖和重跑测试。

## 1.1 升级与渠道配置

升级前运行 `manage.py backup`，妥善保留旧版代码及快照。启动新版本时数据库从版本 1 / 2 升至 3，增加会话、恢复码、来源和接入记录，不删除原通知及待办；旧版代码不能直接打开新结构。回退应恢复到新的空数据目录并使用对应旧版本程序。

`compose.yaml` 通过 `env_file: .env` 读取 AI 和渠道凭证。QQ、公众号的环境变量和平台控制台配置见 `INTEGRATIONS.md`。本机回环模式不能接收公网平台回调；请在具备 HTTPS 域名的服务器部署后配置 QQ Webhook。填写凭证后重启服务，前端不提供密钥输入或查看。

全部模型配置及语音联调参见 [MIMO_INTEGRATION.md](MIMO_INTEGRATION.md)。
