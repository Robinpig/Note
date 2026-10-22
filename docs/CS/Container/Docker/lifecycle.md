## Introduction

容器从 `docker create` / `run` 到 `stop` / `rm`，中间横亘着几个容易踩坑的机制：**PID 1 与僵尸回收、信号转发与优雅终止、重启策略、健康检查**。很多"容器莫名重启""退出码 137""僵尸进程堆积"的故障都落在这四个点上。

本篇只讲单机容器的生命周期；多机编排是在这之上叠加调度，见 [Docker Compose](/docs/CS/Container/Docker/compose.md)、[Swarm](/docs/CS/Container/Docker/swarm.md) 与 [Kubernetes](/docs/CS/Container/k8s/K8s.md)。

## 进程模型与 PID 1

容器内 PID 1 就是 `ENTRYPOINT` / `CMD` 启动的那个进程。它有两个特殊责任，普通进程没有：

1. **接收并转发信号**给子进程（如把 SIGTERM 转给真正干活的应用）。
2. **回收僵尸进程**（对退出的子进程调用 `wait()`）。

两个经典坑：

```dockerfile
# 坑 1：shell 形式。/bin/sh -c 不会把 SIGTERM 转发给 node，导致优雅终止失效
CMD node server.js
# 等价展开为：/bin/sh -c "node server.js"

# 坑 2：子进程退出后没人 wait()，变成僵尸（defunct）
```

修复手段：

- **exec 形式**避免额外 shell 层：`CMD ["node", "server.js"]`（注意中括号 JSON 数组写法）。
- 注入 `tini`（轻量 init，专门做信号转发 + 僵尸回收）：`docker run --init myapp`，或 Dockerfile 里 `ENTRYPOINT ["/tini", "--", "node", "server.js"]`。
- 部分基础镜像（如 `node:xx-slim` 不一定，但 distroless 等）自带 init 行为，需确认。

## 信号与优雅终止

```bash
docker stop <c>      # 先发 SIGTERM，等 --time（默认 10s）后再 SIGKILL
docker stop -t 30 <c># 给 30s 宽限
docker kill <c>      # 直接 SIGKILL
docker kill -s SIGINT <c>   # 指定信号
```

- 应用必须**自己捕获 SIGTERM** 做清理（关连接、刷盘、摘流量），否则 10s 一到被 SIGKILL 强杀，可能丢数据。
- `STOPSIGNAL` 指令可改停止信号（如 `STOPSIGNAL SIGQUIT`），适应不认 SIGTERM 的老程序。

## 重启策略

`docker run --restart` 决定容器退出后 daempon 是否拉起它：

| 值 | 行为 |
| :-- | :-- |
| `no` | 默认，不重启 |
| `on-failure[:max]` | 非 0 退出才重启，可选最多重试次数 |
| `always` | 无论退出码都重启；daemon 重启也会拉起 |
| `unless-stopped` | 同 `always`，但**手动 `docker stop` 后不会随 daemon 重启而复活**（推荐） |

```bash
docker run --restart unless-stopped nginx
docker run --restart on-failure:5 worker
```

Compose 里是顶层 `restart:`（四值相同）；注意 `deploy.restart_policy` **只在 Swarm 生效**，单机上被忽略（详见 [Compose](/docs/CS/Container/Docker/compose.md) 的字段陷阱）。

与 K8s 对比：K8s 只有 `Always` / `OnFailure` / `Never` 且作用在 Pod，语义和单机 restart 不同——K8s 的"重启"是重建容器而非重启进程。

## 健康检查

健康检查的任务是区分"**进程活着**"和"**能正常服务**"。

**Dockerfile 内声明**：

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:8080/health || exit 1
```

**状态反映在 `docker ps` 的 STATUS 列**：`starting` → `healthy` / `unhealthy`；`docker inspect` 的 `State.Health` 能看到最近几次探测。

**Compose 内**：

```yaml
services:
  api:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
```

`depends_on: condition: service_healthy` 可让依赖方等健康后再起（但仍**不等于"依赖方已就绪可用"**，只是健康探针过了；编排细节见 [Compose](/docs/CS/Container/Docker/compose.md)）。

用途：配合 `restart` 做"不健康就重启"、给外部探针/LB 判断依据。在 K8s 里对应的角色由 liveness / readiness 探针承担。

## 退出与清理

退出码含义速查：

- `0`：正常退出。
- `137` = 128 + 9（SIGKILL）：被强杀，常见于 **OOM**（cgroup 内存超限，见 [性能](/docs/CS/Container/Docker/performance.md)）。
- `143` = 128 + 15（SIGTERM）：收到终止信号后退出。

其他常用命令：

```bash
docker wait <c>          # 阻塞到容器退出并返回退出码
docker update --cpus 2 <c>   # 运行时改限额 / restart 策略
docker rename <old> <new>
docker run --rm ...      # 一次性容器，退出即删（不推荐与生产长期服务混用）
```

## 与编排的衔接

单机生命周期是底座，编排层在此之上加调度与自愈：

- Compose 把多容器按依赖/网络/卷组织起来（[compose.md](/docs/CS/Container/Docker/compose.md)）。
- Swarm / K8s 用"期望状态调和"在节点故障时重新调度，并叠加滚动更新、探针、自动重启。

## Links

- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker Compose](/docs/CS/Container/Docker/compose.md)
- [Docker 性能](/docs/CS/Container/Docker/performance.md)

## References

1. [Docker container lifecycle & restart policy](https://docs.docker.com/engine/containers/start-containers/)
2. [HEALTHCHECK reference](https://docs.docker.com/engine/reference/builder/#healthcheck)
3. [Docker run --init (tini)](https://docs.docker.com/engine/reference/commandline/run/#init)
