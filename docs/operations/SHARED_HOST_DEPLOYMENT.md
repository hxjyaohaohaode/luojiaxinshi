# 同一宿主机复用反向代理

本方案供部署者在**已有反向代理**的 Linux Docker 主机上运行珞珈信使。两种独立模板都不启动第二个 Caddy，不占用宿主机的 80/443。选择取决于反代实际运行的位置；模板渲染通过不代表目标服务器、域名、资源余额、证书和网络已经验收。

| 实际反代位置 | 独立模板 | 应用入口 |
| --- | --- | --- |
| 宿主机进程，与 Docker 主机共用网络空间 | [compose.shared-host.yaml](../../compose.shared-host.yaml) | 只发布到宿主机 `127.0.0.1` 的自选端口 |
| 已有普通 Docker 容器 | [compose.proxy-network.yaml](../../compose.proxy-network.yaml) | 不发布宿主机端口，通过专用共享代理网络的项目别名访问 |

原 [compose.yaml](../../compose.yaml) 仍是应用与 Caddy 一起运行的方案。**三者只选择一个文件，不能通过多次 `-f` 合并**，否则原代理、端口或网络可能仍在合并结果中。公开模板不包含实际实例地址、其他项目名称或访问凭据。

## 部署者需要填写的值

在服务器上创建仅部署账户可读的环境文件，例如 `.env.shared-host`。应用原有的 `OPERATOR_*`、模型、注册验证、邮件等配置仍按 [docs/operations/OPERATIONS.md](OPERATIONS.md) 填写；这里不提供虚构的供应商凭证或学校接口。

| 变量 | 实际选择依据 |
| --- | --- |
| `CAMPUS_PROJECT_NAME` | 此主机上唯一且后续保持稳定的 Compose 项目名，使用小写字母、数字、短横线或下划线。 |
| `CAMPUS_IMAGE` | 已验证并存在于此主机的应用镜像。优先使用仓库 digest；若用本地构建标签，应同时记录实际 image ID。模板不自动拉取或构建镜像。 |
| `CAMPUS_ENV_FILE` | 本项目私有应用环境文件的绝对路径；可指向这份环境文件本身。 |
| `APP_ORIGIN` | 本项目对外的完整 HTTPS 源地址，不含路径；须与现有反代域名一致。 |
| `CAMPUS_TRUSTED_PROXY_IPS` | 应用实际看到的可信反代连接来源地址，显式列举；不能根据公网 IP 或容器中的 `127.0.0.1` 猜测，也不要直接写 `*`。 |
| `CAMPUS_LOOPBACK_PORT` | 仅宿主机进程反代模式：已检查未占用的固定宿主机端口，不使用 0、80、443；不同项目分别选择。 |
| `CAMPUS_PROXY_NETWORK` | 仅容器反代模式：由部署者事先准备的专用代理 bridge 网络名称。应用和已有反代都须明确加入；不直接填入其他项目包含数据库的默认网络。 |
| `CAMPUS_MEMORY_LIMIT`、`CAMPUS_CPU_LIMIT`、`CAMPUS_PIDS_LIMIT` | 此项目的正数内存、CPU 和进程上限。先核对主机总量、已有服务预算和运行开销；模板不预设机器规格。 |
| `CAMPUS_TMPFS_SIZE` | `/tmp` 的内存预算，计入运行内存规划；文件解析等操作会使用这里。 |
| `CAMPUS_LOG_MAX_SIZE`、`CAMPUS_LOG_MAX_FILES` | 正数日志轮转大小与保留份数，例如大小使用 `m` 单位；按磁盘空间和日志保留要求决定。 |

不要额外用 `-p` 或 `COMPOSE_PROJECT_NAME` 覆盖项目名。Compose 对这些值有更高优先级；应检查最终 `config` 中的实际 `name`。项目名改变会指向另一组卷和网络，**不会自动搬迁旧数据**。迁移现有实例须先按原运维文档执行完整备份和恢复，不把新空卷当成原账户数据。

## 宿主机进程反代：回环端口

以下是部署者在目标主机上执行的配置检查，本文没有替你执行。`config --quiet` 不启动服务；不要公开完整 `config` 输出，它可能包含环境文件中的敏感配置。

```bash
docker compose --env-file .env.shared-host -f compose.shared-host.yaml config --quiet
```

检查渲染结果只有 `app` 一个服务，端口只绑定 `127.0.0.1`，项目名符合预期，资源上限均为正数，日志大小与份数已设置。仓库另提供仅用无敏感虚拟值的合同检查：

```bash
python scripts/verify_shared_host_config.py --output artifacts/shared-host-config.json
```

该检查只调用 Compose 的 `version` 和 `config`：验证两个虚拟项目的卷/网络名称互异、只有回环端口、资源及安全选项保留，并逐项验证必填变量缺失会失败。它**不启动容器、不访问供应商、不证明目标主机已部署成功**；没有 Docker/Compose CLI 时明确返回非零状态。

现有宿主机反代应将该域名转到 `http://127.0.0.1:所选端口`，保留原来的 TLS 管理与其他项目路由。上传正文限制应与现有 [Caddyfile](../../Caddyfile) 的 26 MB 边界协调。应核对转发的 Host、HTTPS 协议和客户端地址，确认应用只信任实际的反代来源。

此模式假定反代进程在宿主机网络空间。**另一个普通容器内的 `127.0.0.1` 指向那个容器自身**；如果现有反代也在容器内，使用下一节的独立模板，不直接套用这里的回环地址，也不要为了方便发布到 `0.0.0.0`。

## 容器反代：专用代理网络

使用 `compose.proxy-network.yaml`，在本项目的私有环境文件中填写 `CAMPUS_PROXY_NETWORK`；不需要 `CAMPUS_LOOPBACK_PORT`。应用没有 `ports`，不会另外打开宿主机入口。它通过 `${CAMPUS_PROJECT_NAME}-app` 这个网络别名在容器端口8765上提供服务。已有反代的上游须使用这个完整项目别名，例如项目名为 `example-campus` 时使用 `example-campus-app:8765`，不使用可能冲突的通用 `app` 名称。

部署者在启动前需要确认以下实际条件：

1. 专用 Docker bridge 网络已经存在；应用与反代都在其中。若尚不存在，须由部署者在核对现有网络和地址范围后实际创建，再接入两个服务；本模板与CI配置检查都不执行这些动作。网络最好只连接这两个服务；不能因为某个网络名称已有就把应用接入另一项目的数据库网络。网络生命周期由部署者维护，模板中的 `external: true` 不创建或删除它。
2. 在已有反代项目的持久 Compose 配置中加入该网络，并保留其原网络、卷和80/443绑定。临时连接容器不等于重建后仍保持；此模板不修改另一项目。实际更改、配置校验和重新加载由部署者操作。
3. 核对网络实际驱动、成员、路由和外网出口。应用需要访问用户配置的验证码、邮件或模型供应商时，不能把隔绝外网的网络误当成可用出口。`config` 不向 Docker daemon 查询这些实际条件。
4. 根据应用实际看到的反代连接来源填写 `CAMPUS_TRUSTED_PROXY_IPS`，优先明确可信代理地址；若使用网段，须确认网段内每个成员都属于可信代理边界。不能用公网地址猜测，也不能用 `*` 代替核验。共享网络中的成员可以访问彼此端口，项目名和别名不构成网络防火墙。
5. 现有反代只为本项目新增正确域名到项目别名的路由，保留TLS、上传限制和转发头合同；再验证真实HTTPS访问、Host及反代来源，并核对宿主机没有新增应用公开端口。

以下命令只检查配置，不创建网络、连接容器或启动服务：

```bash
docker compose --env-file .env.shared-host -f compose.proxy-network.yaml config --quiet
python scripts/verify_shared_host_config.py --mode proxy-network --output artifacts/proxy-network-config.json
```

第二条仍使用无敏感信息的合成环境：两个项目共用一个显式代理网络，检查各自别名和数据卷互异、没有宿主端口，并验证12个必填变量的缺失拒绝，独立形成14项记录。原默认回环模式的14项保持不变。CI分别上传 `shared-host-compose-config` 与 `proxy-network-compose-config` 原件；两份配置报告都通过，也只证明渲染及配置合同，**不证明网络真实存在、反代已接入或目标主机部署成功**。

## 资源与数据边界

两种模式都保持 UID/GID `10001:10001`、只读根文件系统、独立 `/data` 卷、限定大小的 `/tmp`、禁用新增权限和全部 Linux capabilities。回环模式创建项目作用域的IPv4 NAT bridge；容器代理模式只引用已有的专用代理网络，不修改其驱动或出口。两种模板都不为现有反代或其他项目分配资源；宿主机整体的 CPU、内存、磁盘和日志预算仍需部署者统筹。

日志轮转仅限制该容器的 Docker 日志。`/data` 中的数据库、附件和备份仍需磁盘监测、备份保留策略与异机副本。只运行一个应用实例；不要通过复制 SQLite 写入实例来扩容。恢复后原会话失效，完整恢复流程见 [docs/operations/OPERATIONS.md](OPERATIONS.md)。

Docker 官方说明：低于 Engine 28.0.0 的版本存在同一二层网络访问 localhost 发布端口的历史边界。因此目标机应核对受支持的 Engine 版本和实际网络/防火墙配置；仅看到 YAML 中的 `127.0.0.1` 不能代替目标环境隔离验证。部署后还需从外部确认应用端口未直接暴露，并按现有运维文档验证 HTTPS、账户隔离、文件、提醒、重启与恢复。CI 的虚拟配置检查和已有共享 runner 性能数据都不代表这台服务器验收通过。

## 官方依据

- [Compose 项目名称和优先级](https://docs.docker.com/compose/how-tos/project-name/)
- [Compose 服务配置：端口、资源、只读文件系统、日志、卷和网络](https://docs.docker.com/reference/compose-file/services/)
- [跨Compose项目复用网络和服务发现](https://docs.docker.com/compose/how-tos/networking/)
- [外部网络与其独立生命周期](https://docs.docker.com/reference/compose-file/networks/#external)
- [网络别名及同名冲突边界](https://docs.docker.com/reference/compose-file/services/#aliases)
- [Docker 端口发布、回环地址及 Engine 28 之前的边界](https://docs.docker.com/engine/network/port-publishing/)
- [JSON File 日志轮转选项](https://docs.docker.com/engine/logging/drivers/json-file/)
