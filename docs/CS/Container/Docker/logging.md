## Introduction

容器的"日志"不是指应用写到磁盘的文件，而是**应用进程打到 stdout / stderr 的内容**被 Docker 捕获后，再交给一个可插拔的 **logging driver** 处理。整条链路是：

```
应用 stdout/stderr → 容器内 pipe → dockerd 捕获 → logging driver → 目的地（文件 /  syslog / 远端）
```

`docker logs` 读的是 driver 暴露的接口，而不是去 `cat` 某个文件（只有本地文件类驱动才有实体文件可查）。这条链路决定了三件事：日志去哪、磁盘会不会被撑爆、能不能对接集中式采集。

## 两层模型：应用日志 vs 容器日志

常见误区是把"应用自己写 `app.log`"当成容器日志——**那 Docker 完全看不到**，因为 Docker 只认 stdout/stderr。两种写法：

```dockerfile
# 反例：日志进文件，docker logs 读不到，也绕过了 driver 的轮转
RUN echo 'logging.file=/var/log/app.log' > /etc/app.conf

# 正例：打到 stdout，交给 Docker 与 driver 统一管理
CMD ["sh", "-c", "java -jar app.jar 2>&1"]
```

如果程序只会写文件，用软链把文件接到 stdout 也是一种折中：

```dockerfile
RUN ln -sf /dev/stdout /var/log/app.log
```

## 内置驱动清单

`docker info` 的 `Logging Driver` 显示当前默认驱动；`docker inspect -f '{{.HostConfig.LogConfig.Type}}' <c>` 看单个容器用的什么。

| Driver | 目的地 | 支持 `docker logs` | 适用场景 |
| :-- | :-- | :-- | :-- |
| `none` | 直接丢弃 | 否 | 完全不需要日志的批处理 |
| `local` | 容器本地文件（自带轮转） | 是 | 想省盘又不想裸奔 json-file 的默认替代 |
| `json-file` | 容器本地文件（每行一个 JSON） | 是 | **Engine 默认**，最通用 |
| `syslog` | 宿主机 `/dev/log` 或远程 syslog | 否（走 syslog） | 已有 syslog 基建 |
| `journald` | systemd journal（仅 Linux） | 否（`journalctl`） | 宿主机用 systemd |
| `gelf` | Graylog (`gelf` 协议) | 否 | Graylog 用户 |
| `fluentd` | fluentd 守护进程 | 否 | EFK 栈 |
| `awslogs` | AWS CloudWatch Logs | 否 | AWS 环境 |
| `splunk` | Splunk HTTP Event Collector | 否 | Splunk 用户 |
| `etwlogs` | Windows ETW | 否 | Windows 容器 |

> `json-file` 与 `local` 是仅有的两个**既落本地文件、又支持 `docker logs` 和大小轮转**的驱动，二者也是生产里最该被显式配置的。

## 配置方式

 logging driver 有三层作用域：**daemon 全局默认 → 单容器 `--log-driver` → Compose `logging:`**。

**1. daemon 全局默认**（`/etc/docker/daemon.json`）——推荐在此钉死轮转，避免个别容器忘记设而撑爆磁盘：

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

改完 `systemctl restart docker`（或对应平台重启 daemon）。

**2. 单容器覆盖**：

```bash
docker run --log-driver syslog \
           --log-opt syslog-address=udp://192.0.2.1:514 \
           nginx
```

**3. Compose**：

```yaml
services:
  api:
    image: myapi:1.4
    logging:
      driver: "json-file"
      options:
        max-size: "20m"
        max-file: "5"
```

## 日志轮转：不配就会撑爆磁盘

只有 `json-file` 和 `local` 自带 `max-size` / `max-file` 轮转；远程类驱动（syslog/gelf/awslogs）的"轮转"发生在下游系统，Docker 侧无大小上限。

- `max-size`：单个日志文件上限，到顶后滚动。
- `max-file`：保留几个历史文件，超出删除最旧的。
- 没设这两个值时，`json-file` 会**无限增长**——这正是 storage.md 里"日志是磁盘杀手"那一节的根因。

```bash
# 查看各容器日志占用
docker ps -q | xargs docker inspect --format \
  '{{.Id}} {{.HostConfig.LogConfig.Type}}' | head
# 直接看某容器日志文件路径（json-file/local 才有）
docker inspect -f '{{.LogPath}}' <container>
```

## dual logging（故障兜底）

当主驱动是远程（syslog/fluentd/awslogs 等）且**下游不可达**时，Docker 会自动把日志转存到本地 `local` 驱动，避免故障期间日志全丢。这是 daemon 级能力，无需额外配置即可在断连时兜底，恢复后正常路径继续生效。它解决的是"远端挂了丢了现场"的痛点，不是长期存储方案。

## 读取与排障

`docker logs` 的常用参数：

```bash
docker logs -f <c>            # 跟踪
docker logs --tail 100 <c>   # 只看最后 100 行
docker logs --since 1h <c>   # 最近一小时
docker logs --until 2026-10-22T10:00 <c>
docker logs --timestamps <c> # 带时间戳
```

常见现象与原因：

- **`docker logs` 报空或说不支持**：驱动是 `none` / 远程类（syslog 等本就不经 `docker logs`）；或应用根本没打 stdout。
- **磁盘满**：`json-file` 没设 `max-size/max-file`，或 `local` 的 `max-size` 也该设。用 `docker system df` 看占用，清法见 storage.md 的清理一节。
- **journald 驱动看不到**：用 `journalctl CONTAINER_NAME=<name>` 或 `journalctl CONTAINER_ID_FULL=<id>` 查，而不是 `docker logs`。

## 与性能、安全的衔接

- 日志写入是 **I/O 与磁盘**消耗大户，封顶轮转是性能与可用性的硬要求，详见 [Docker 性能](/docs/CS/Container/Docker/performance.md) 与 [Docker 存储](/docs/CS/Container/Docker/storage.md)。
- 远程驱动把负载从本地磁盘转移到网络与下游系统，但引入了外部依赖与可用性耦合。
- 别把**密钥、令牌**打进日志——日志会落到磁盘甚至远端，扩大泄露面，相关治理见 [Docker 安全](/docs/CS/Container/Docker/security.md)。

## Links

- [Docker 存储](/docs/CS/Container/Docker/storage.md)
- [Docker 性能](/docs/CS/Container/Docker/performance.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)

## References

1. [Docker logging drivers overview](https://docs.docker.com/config/containers/logging/configure/)
2. [Docker dual logging](https://docs.docker.com/config/containers/logging/dual-logging/)
3. [Configure the docker daemon (log-opts)](https://docs.docker.com/engine/daemon/)
