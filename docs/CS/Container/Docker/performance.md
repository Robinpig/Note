## Introduction

容器性能问题的特殊性在于**它同时属于两个视角**：在容器里看是应用慢，在宿主机上看是某一组进程被 cgroup 掐住了。所以排查链路永远是"容器内指标 → 容器限额 → 宿主 cgroup → 内核"，中间那步换算（容器 ID ↔ PID ↔ cgroup 路径）是关键，见 [容器定位](/docs/CS/Container/locate.md)。

Docker 性能高度依赖 Linux 内核的 cgroup（如今是 v2）、调度器和 I/O 子系统，所以下面每个限额参数都会注明它落到哪个内核机制上。

## 限额参数与内核映射

| Docker 参数 | cgroup v2 文件 | 语义 |
| :-- | :-- | :-- |
| `--cpus=1.5` | `cpu.max` | 每 100ms 周期最多用 150ms CPU（CFS quota） |
| `--cpu-shares=512` | `cpu.weight` | 竞争时的相对权重，不是上限 |
| `--cpuset-cpus=0-3` | `cpuset.cpus.effective` | 绑核，减少缓存失效与迁移 |
| `--memory=512m` | `memory.max` | 硬上限，超过触发 cgroup OOM |
| `--memory-reservation=256m` | `memory.low` | 软下限，宿主内存紧张时优先保住 |
| `--memory-swap=1g` | `memory.swap.max` | 内存 + swap 总量；等于 `--memory` 即禁用 swap |
| `--pids-limit=200` | `pids.max` | 防 fork 炸弹 |
| `--blkio-weight` / `--device-write-bps` | `io.weight` / `io.max` | I/O 权重与带宽上限（blkio 驱动对 buffered IO 效果有限） |
| `--oom-kill-disable` | `memory.oom.group` 相关 | 见下文，**慎用** |

```shell
docker run -d \
  --cpus=1.5 --cpuset-cpus=0-3 \
  --memory=512m --memory-swap=512m \
  --pids-limit=200 \
  --restart unless-stopped \
  app:v1
```

## CPU

CPU 优化平衡利用率与公平性：既要让容器拿到足够的处理时间，也不能让邻居永远排不上队。

- `--cpus` 是**硬上限**，通过 CFS  quota 实现——容器用完配额后在本周期内被 throttle，表现为"明明 CPU 空闲，应用却卡住"。看 throttle 情况：`docker stats` 看不出来，要读 `cpu.stat` 里的 `throttled_time`
- `--cpu-shares` 只在**争抢时**生效，宿主空闲时容器可以用满所有核
- 绑核（`--cpuset-cpus`）对延迟敏感型负载收益明显，但会降低调度弹性
- 容器看到的 CPU 核数是**宿主的核数**而不是配额数，所以 JVM / Go 的 `GOMAXPROCS`、线程池大小会被误导——这是容器内最常见的一类性能坑

CPU 限额如何传导到调度器的完整路径见 [cgroup](/docs/CS/OS/Linux/cgroup.md?id=how-cpu-limit-reaches-the-scheduler)。

## 内存

内存调优防止泄漏、减少碎片化，并避免 OOM killer。

两种 OOM 要分清：

| 类型 | 触发者 | 表现 |
| :-- | :-- | :-- |
| **cgroup OOM** | 内核在容器超过 `memory.max` 时 | 容器内进程被杀，`docker inspect` 里 `OOMKilled: true`，容器状态 Exited(137) |
| **宿主 OOM** | 宿主整体内存耗尽 | 内核按 `oom_score` 挑进程杀，可能杀掉的是别的关键进程 |

判断到底是哪种：

```shell
docker inspect -f '{{.State.OOMKilled}} {{.State.ExitCode}}' web
docker system events --filter 'event=oom' --since 1h
dmesg | grep -i "out of memory"
```

> [!WARNING]
> `--oom-kill-disable` 让容器超限时不杀进程、只让分配阻塞，看起来"容器不会死了"，但宿主内存会被它一路吃干，最后触发宿主全局 OOM，杀掉的可能是数据库或 sshd。不加内存限额又禁用 OOM kill，等于把整台机器的稳定性赌在一个容器上。

内存相关指标要看两处：

```shell
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"
# 更细的分解（anon/file/slab）在 cgroup v2 的 memory.stat
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.stat
```

Java 应用在容器里还要额外注意：JVM 默认按宿主内存和核数算堆大小，需要 `-XX:MaxRAMPercentage` 或显式 `-Xmx`，否则会被 cgroup OOM 杀掉。

## I/O

I/O 常常成为无声的瓶颈——CPU 和内存都很闲，吞吐却上不去。

影响因素按重要性排：

1. **数据落在容器可写层还是 volume**：写可写层要过联合挂载与 CoW，改大文件有整份上浮开销；数据库、日志这类重 IO 一律放 volume，见 [Docker 存储](/docs/CS/Container/Docker/storage.md)
2. **storage driver**：overlay2 是常态；`vfs` 性能极差只适合测试
3. **宿主文件系统与调度器**：ext4/xfs + mq-deadline/none，SSD 用 noop 类调度器
4. **块设备限额**：`--device-read-bps` / `--device-write-iops` 走 cgroup v2 的 `io.max`，但**只对 direct IO 有效**，buffered IO 写回是异步的，限额效果有限——这也是常说 "Buffered IO isolation level 低" 的原因
5. **日志驱动**：`json-file` 同步写且默认无轮转，高频日志直接变成磁盘瓶颈

观测手段：

```shell
docker stats --format "table {{.Name}}\t{{.BlockIO}}"
# 容器内按进程看 IO
docker exec web sh -c 'cat /proc/self/io'
# 宿主侧
iostat -x 1
pidstat -d 1
```

## 观测工具

| 工具 | 看什么 | 适用 |
| :-- | :-- | :-- |
| `docker stats` | 容器级 CPU/内存/IO/网络实时值 | 第一眼，快 |
| `docker system df -v` | 磁盘占用分解 | 空间问题 |
| `docker system events` | OOM、die、create 等事件流 | 事后追因 |
| cAdvisor | 容器指标导出成 Prometheus 格式 | 长期监控 |
| sysdig / falco | 系统调用级内省 | 深挖行为 |
| `perf` + 火焰图 | 内核/用户态热点 | CPU 侧根因 |
| `sar` | 历史趋势 | "昨晚是不是有问题" |

```shell
docker stats                                # 实时
docker stats --no-stream                    # 抓一帧
docker stats --format "{{.Name}} {{.CPUPerc}} {{.MemPerc}}"
```

## 排查工作流

性能调查遵循一个结构化流程：

1. **症状观察**：应用变慢时，先看延迟直方图和百分位分布（P99 比平均值有用得多），确认是"整体变慢"还是"长尾变差"
2. **层级诊断**：应用 profiler（Go 的 pprof、Java 的 VisualVM/async-profiler）→ `docker inspect HostConfig` 确认限额 → 宿主 `top`/`htop` → `perf record` 火焰图下钻到内核
3. **身份换算**：`top` 里那个吃 CPU 的进程要先认出它属于哪个容器——`docker inspect -f '{{.State.Pid}}'` 正向查，`cat /proc/PID/cgroup` 反向查，之后 `perf -p`、读 `/proc/PID/{stack,fd,mountinfo}`、`nsenter` 才有着落
4. **对照限额与用量**：用量贴着上限说明是配额问题而不是代码问题；用量很低却慢，说明瓶颈在依赖（网络、磁盘、下游服务）

第 3 步的完整方法见 [容器定位](/docs/CS/Container/locate.md)。

## 优化清单

- 每个容器都设 `--memory` 和 `--cpus`，别让默认无限制成为常态
- `--pids-limit` 兜底防 fork 炸弹
- 日志驱动设 `max-size` / `max-file`
- 有状态服务的重 IO 路径放 volume
- JVM/Go/Node 显式设置内存与线程/协程上限，别依赖"宿主有多少核"
- 延迟敏感服务考虑绑核，批处理服务用低 `--cpu-shares`
- 定期 `docker system df -v` 看构建缓存和 dangling 镜像
- 长期监控上 cAdvisor + Prometheus，别只靠 `docker stats`

## Links

- [Docker 运行时](/docs/CS/Container/Docker/runtime.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [K8s 驱逐](/docs/CS/Container/k8s/Eviction.md)

## References

1. [Runtime options with Memory, CPUs, and GPUs](https://docs.docker.com/engine/containers/resource_constraints/)
2. [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
3. [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/)
