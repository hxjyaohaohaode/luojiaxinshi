# 同一宿主机复用反向代理

本方案供部署者在**已有宿主机反向代理**的 Linux Docker 主机上运行珞珈信使。它不启动第二个 Caddy，不占用宿主机的 80/443；应用只向宿主机 `127.0.0.1` 发布一个由部署者选择的端口。适用于腾讯云等普通 Linux 主机，但本文没有读取或验证任何实际服务器、域名、资源余额和证书。

使用独立的 [compose.shared-host.yaml](../compose.shared-host.yaml)。原 [compose.yaml](../compose.yaml) 仍是应用与 Caddy 一起运行的方案。**只选择一个文件，不能把两个文件通过多次 `-f` 合并**，否则原代理及端口可能仍在合并结果中。

## 部署者需要填写的值

在服务器上创建仅部署账户可读的环境文件，例如 `.env.shared-host`。应用原有的 `OPERATOR_*`、模型、注册验证、邮件等配置仍按 [OPERATIONS.md](../OPERATIONS.md) 填写；这里不提供虚构的供应商凭证或学校接口。

| 变量 | 实际选择依据 |
| --- | --- |
| `CAMPUS_PROJECT_NAME` | 此主机上唯一且后续保持稳定的 Compose 项目名，使用小写字母、数字、短横线或下划线。 |
| `CAMPUS_IMAGE` | 已验证并存在于此主机的应用镜像。优先使用仓库 digest；若用本地构建标签，应同时记录实际 image ID。模板不自动拉取或构建镜像。 |
| `CAMPUS_ENV_FILE` | 本项目私有应用环境文件的绝对路径；可指向这份环境文件本身。 |
| `APP_ORIGIN` | 本项目对外的完整 HTTPS 源地址，不含路径；须与现有反代域名一致。 |
| `CAMPUS_TRUSTED_PROXY_IPS` | 应用实际看到的可信反代连接来源地址，显式列举；不能根据公网 IP 或容器中的 `127.0.0.1` 猜测，也不要直接写 `*`。 |
| `CAMPUS_LOOPBACK_PORT` | 已检查未占用的固定宿主机端口，不使用 0、80、443；不同项目分别选择。 |
| `CAMPUS_MEMORY_LIMIT`、`CAMPUS_CPU_LIMIT`、`CAMPUS_PIDS_LIMIT` | 此项目的正数内存、CPU 和进程上限。先核对主机总量、已有服务预算和运行开销；模板不预设机器规格。 |
| `CAMPUS_TMPFS_SIZE` | `/tmp` 的内存预算，计入运行内存规划；文件解析等操作会使用这里。 |
| `CAMPUS_LOG_MAX_SIZE`、`CAMPUS_LOG_MAX_FILES` | 正数日志轮转大小与保留份数，例如大小使用 `m` 单位；按磁盘空间和日志保留要求决定。 |

不要额外用 `-p` 或 `COMPOSE_PROJECT_NAME` 覆盖项目名。Compose 对这些值有更高优先级；应检查最终 `config` 中的实际 `name`。项目名改变会指向另一组卷和网络，**不会自动搬迁旧数据**。迁移现有实例须先按原运维文档执行完整备份和恢复，不把新空卷当成原账户数据。

## 校验配置与接入现有反代

以下是部署者在目标主机上执行的配置检查，本文没有替你执行。`config --quiet` 不启动服务；不要公开完整 `config` 输出，它可能包含环境文件中的敏感配置。

```bash
docker compose --env-file .env.shared-host -f compose.shared-host.yaml config --quiet
```

检查渲染结果只有 `app` 一个服务，端口只绑定 `127.0.0.1`，项目名符合预期，资源上限均为正数，日志大小与份数已设置。仓库另提供仅用无敏感虚拟值的合同检查：

```bash
python scripts/verify_shared_host_config.py --output artifacts/shared-host-config.json
```

该检查只调用 Compose 的 `version` 和 `config`：验证两个虚拟项目的卷/网络名称互异、只有回环端口、资源及安全选项保留，并逐项验证必填变量缺失会失败。它**不启动容器、不访问供应商、不证明目标主机已部署成功**；没有 Docker/Compose CLI 时明确返回非零状态。

现有宿主机反代应将该域名转到 `http://127.0.0.1:所选端口`，保留原来的 TLS 管理与其他项目路由。上传正文限制应与现有 [Caddyfile](../Caddyfile) 的 26 MB 边界协调。应核对转发的 Host、HTTPS 协议和客户端地址，确认应用只信任实际的反代来源。

此模式假定反代进程在宿主机网络空间。**另一个普通容器内的 `127.0.0.1` 指向那个容器自身**；如果现有反代也在容器内，应单独设计共享入口网络和信任边界，不直接套用这里的回环地址，也不要为了方便发布到 `0.0.0.0`。

## 资源与数据边界

应用保持 UID/GID `10001:10001`、只读根文件系统、独立 `/data` 卷、限定大小的 `/tmp`、禁用新增权限和全部 Linux capabilities。项目作用域的 bridge 网络使用 IPv4 NAT；它允许应用访问实际配置的外部服务，没有设成禁止外网的 internal 网络。它不为现有反代或其他项目分配资源；宿主机整体的 CPU、内存、磁盘和日志预算仍需部署者统筹。

日志轮转仅限制该容器的 Docker 日志。`/data` 中的数据库、附件和备份仍需磁盘监测、备份保留策略与异机副本。只运行一个应用实例；不要通过复制 SQLite 写入实例来扩容。恢复后原会话失效，完整恢复流程见 [OPERATIONS.md](../OPERATIONS.md)。

Docker 官方说明：低于 Engine 28.0.0 的版本存在同一二层网络访问 localhost 发布端口的历史边界。因此目标机应核对受支持的 Engine 版本和实际网络/防火墙配置；仅看到 YAML 中的 `127.0.0.1` 不能代替目标环境隔离验证。部署后还需从外部确认应用端口未直接暴露，并按现有运维文档验证 HTTPS、账户隔离、文件、提醒、重启与恢复。CI 的虚拟配置检查和已有共享 runner 性能数据都不代表这台服务器验收通过。

## 官方依据

- [Compose 项目名称和优先级](https://docs.docker.com/compose/how-tos/project-name/)
- [Compose 服务配置：端口、资源、只读文件系统、日志、卷和网络](https://docs.docker.com/reference/compose-file/services/)
- [Docker 端口发布、回环地址及 Engine 28 之前的边界](https://docs.docker.com/engine/network/port-publishing/)
- [JSON File 日志轮转选项](https://docs.docker.com/engine/logging/drivers/json-file/)
