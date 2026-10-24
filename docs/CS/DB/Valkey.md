## Version Baseline

> [!IMPORTANT]
> 基线 **Valkey 9.1.2（2026-09-01）**，许可自始至终 **BSD-3-Clause从未改变**（9.1.2 的 `COPYING` 首行即 `SPDX-License-Identifier: BSD-3-Clause`）。
> 对照的 Redis 基线是 [8.10.2](/docs/CS/DB/Redis/Redis.md?id=version-baseline)，两者已不是同一代码基。

| Valkey 版本 | 发布日期 | 关键变化 |
| :-- | :-- | :-- |
| 7.2.4-rc1 | 2024-04-09 | 分叉后首个 release（仓库建于 2024-03-22），指向 Redis 原始 commit `d2c8a4b9` |
| 7.2.6 | 2024-07-31 | 修模块与 Redis 的兼容问题 |
| **8.0.0** | 2024-09-15 | **首个 GA 主版本**，`fully compatible with Redis OSS 7.2.4` |
| 8.1.0 | 2025-03-31 | `COMMANDLOG` 命令族；`io-threads` 改为可运行时修改；双通道复制 |
| 9.0.0 | 2025-10-21 | `CLUSTER MIGRATESLOTS`/`FLUSHSLOT`/`GETSLOTMIGRATIONS`；`DELIFEQ`；`HGETEX`/`HSETEX` |
| 9.1.0 | 2026-05-19 | `CLUSTER SCAN` |
| **9.1.2** | 2026-09-01 | 当前最新稳定版；安全修复（RDMA UAF、Lua 解释器 UAF） |
| 9.2.0-rc1 | 2026-09-16 | forkless BGSAVE（opt-in）、流式压缩复制/快照、B+ 树有序集、Path Hash 新类型；GA 目标 2026-11-15 |

旧线 8.1.10 / 7.2.14 仍接收安全更新（valkey.io「latest supported version of past releases」）。9.2.0-rc1 已于 2026-09-16 放出，GA 目标 2026-11-15（见上表）。

## Introduction

[Valkey](https://github.com/valkey-io/valkey) 是 Redis 的分支：基于 Redis 7.2.4 继续开发，采用 **BSD 3-clause** 开源许可（2024 年 Redis 改双许可后，由社区与 Linux 基金会发起）。定位仍是高性能内存数据结构服务器，承载 KV/缓存/消息等负载。

## Relationship with Redis

-代码同源 7.2.4，协议/命令/数据结构高度兼容，客户端可平滑迁移；Valkey 8.0.0 与 8.1.0 的 release notes 都明确写着 `fully compatible with Redis OSS 7.2.4`。
- 治理转向 **Linux Foundation** 中立社区，多厂商（AWS/Akamai/Google/Oracle 等）共建。
- **许可差异是分叉主因**，但 Redis 侧的许可变更细节极易记错，准确时间线见 [Redis 版本基线](/docs/CS/DB/Redis/Redis.md?id=version-baseline)：

| 项目 | 许可 |
| :-- | :-- |
| Redis ≤ 7.2.x | BSD-3-Clause |
| Redis 7.4.0 起 | RSALv2 + SSPLv1 双许可（首个非BSD 版本） |
| Redis 8.0.0 起 | RSALv2 + SSPLv1 + **AGPLv3** 三选一 |
| **Valkey 全系** | **始终 BSD-3-Clause** |

> [!WARNING]
> 常见错误说法：**「Redis 7.4+ 转向 RSALv2/SSPLv2」是错的** —— Redis 从未采用 SSPLv2（只有 SSPLv1）；7.4 是双许可而非 AGPLv3；AGPLv3 是 8.0 起新增的第三个**可选**许可，不是「8.0 改成 AGPLv3」。

## Divergence from Redis

两者的命令集已明显分叉（Valkey 425 个 vs Redis 459 个，按各自源码树统计），**不能假设「Valkey 就是 Redis」**：

**Valkey 独有命令**：`CLUSTER SCAN`、`CLUSTER MIGRATESLOTS` / `FLUSHSLOT` / `GETSLOTMIGRATIONS` / `CANCELSLOTMIGRATIONS`（Redis 走的是另一套 `CLUSTER MIGRATION`）、`COMMANDLOG` 命令族 5 个、`SCRIPT SHOW`、`CLIENT CAPA` / `IMPORT-SOURCE`、`DELIFEQ`，以及 4 个 Sentinel 专用命令（`SENTINEL GET-PRIMARY-ADDR-BY-NAME` 等）。

**Redis 独有命令**：Array 全家桶 18 个 `AR*`（8.8.0）、`BACKUP` 命令族 7 个（8.10.0，基于 MP-AOF）、`HIMPORT` 命令族 5 个（8.10.0，compact hash）、`HOTKEYS`、`LMOVEM`/`BLMOVEM`、`XACKDEL`/`XDELEX`/`XNACK`、`INCREX`、`SFLUSH`。

**配置层差异**：Valkey 独有 8 个配置键（含 `commandlog-*` 系列与 `dual-channel-replication-enabled`）；**`slowlog-log-slower-than` / `slowlog-max-len` 在 Valkey 已改名**为 `commandlog-execution-slower-than` / `commandlog-slow-execution-max-len`（旧名保留为 deprecated 别名，单位微秒）；Valkey 独有 RDMA 支持（`rdma-*` 共 4 个键，Redis 无此文件）；`io-threads` 在 Redis 是 `IMMUTABLE_CONFIG`，在 Valkey 是可运行时修改。

**默认值差异**：`lazyfree-lazy-expire` 在 Valkey 默认为 **1（yes）**，Redis 为 0 —— Valkey 刻意默认开启惰性释放。淘汰策略 Valkey 仍是 **8 种**（无 LRM），Redis 8.6+ 是 10 种。

> [!NOTE]
> Redis 8.0 内建了 JSON / Time Series / Bloom / Cuckoo / Count-min sketch / Top-k / t-digest / Vector set 等数据结构，Valkey 走的是独立的模块生态，迁移时不能按「Redis 8 才有」来判断能力可用性。

## Architecture Evolution

### I/O Threading

- **多线程 I/O、单线程命令执行**：网络 read/write 与命令解析可 offload 到 I/O 线程，主线程与 I/O 线程并发（8.0 起异步 I/O threading + 命令批处理 + key 预取），但**命令仍在主线程串行执行**以保证无锁语义——这是与 Dragonfly shared-nothing 多线程执行的根本区别（其架构见 `Dragonfly.md` 的 `## Architecture`）。
- 8.0 在 AWS r7g 上可达 **1.2M QPS**（旧上限 380K）；8.1 把 TLS 卸载也移出主线程，解除新连接接纳瓶颈。
- `io-threads` 在 Valkey 可运行时动态调整（通过 `updateIOThreads` 回调）；Redis 侧是 `IMMUTABLE_CONFIG`（8.10.2 `src/config.c:3507`）。经验起点是「物理核心数 / 2」，过配反而因上下文切换受损。

### Cluster

- 无中心分片（16384 slot），Gossip 维护拓扑，支持 reshard / replica。
- 8.0 每个 slot 引入独立字典与 per-slot 指标（key 数、CPU、网络吞吐），`CLUSTER SLOT-STATS` 可观测，开销约 0.7% QPS。
- 8.0 起 slot migration 状态在 `CLUSTER SETSLOT` 执行前先同步复制到 replica，故障切换时自动恢复迁移状态，缩小空窗。

### Dual-Channel Replication

- 8.0 引入**双通道复制**：RDB 快照走专用通道，增量命令流走主通道，两者并行传输，主节点不再把整段写流缓在 Client Output Buffer（COB）里。
- 对主节点内存压力显著下降；重读场景下同步时间最多缩短 **50%**。
- **仅在主节点开启 diskless sync 时生效**（`repl-diskless-sync yes` + `dual-channel-replication-enabled yes`，均可运行时切换）；8.0+ replica 协商双通道，旧 replica 透明回退单通道。

### Memory Structure Rewrites

Valkey 的内存效率提升来自对核心数据结构的**连续低层重构**，而非一次性重写；按版本累加，简单 `SET` 负载下单 key 内存从 7.2.14 的 102.48 B 降到 9.1.1 的 64.02 B（**累计 −37.5%**）：

| 版本 | 改动 | 收益 |
| :-- | :-- | :-- |
| 8.0 | 键内联进 `dictEntry`（`embeddedDictEntry`），一次分配替代两次 | −8 B/key |
| 8.1 | **缓存行大小哈希表**：桶正好 64 B（一个 cache line），key+value 内嵌，取消 `dictEntry` 结构体，查找路径 4 跳→约 2 跳 | −20~−30 B/kv（**单版最大降幅 −23.8%**） |
| 9.0 | 未针对内存 | 基本无变化 |
| 9.1 | `embstr` 阈值 64→128 B；复用 `robj->ptr` 的 8 字节直接内嵌短字符串 | 短字符串最多 −20%（均值约 −26%，区间 17%~44%） |

> [!NOTE]
>
> 8.1 的 64 B 缓存行哈希表是对标内存效率的关键一步，思路与 Dragonfly 的 DashTable「减少元数据 / 内存跳数」一致，但路径不同：Valkey 仍保持单线程命令执行的链式/内嵌哈希，Dragonfly 则是 shared-nothing 段式开放寻址。

### Persistence

- 沿用 **RDB + AOF**（MP-AOF）持久化；RDB 可被 Redis/Valkey 各版本互加载，但 **Valkey 刻意使用独立的 RDB 版本号空间**（9.1 写入版本 **80**，与 Redis 的版本号不重叠），以保证跨引擎可识别性——把 Valkey 9.1 的 RDB 喂给不理解该版本的旧引擎会失败。
- **9.2 引入 opt-in 的 forkless BGSAVE**：快照由后台线程直接写出，而非 fork 子进程，消除写时复制内存尖峰。实测 1.1 GB 数据集在持续写入下，fork() 方式内存上涨 354 MB，forkless 仅 **9.9 MB**；代价是保存更慢（约 5–6 s vs 3 s）、写入吞吐略降约 15%，但最差 PING 反而更低（无 fork() 卡主线程）。

### Observability

- **`COMMANDLOG` 命令族**（8.1 起）：取代/增强 slowlog；`slowlog-log-slower-than` / `slowlog-max-len` 已改名为 `commandlog-execution-slower-than` / `commandlog-slow-execution-max-len`（旧名保留为 deprecated 别名，单位微秒）。
- per-slot 指标（`CLUSTER SLOT-STATS`）、`CLIENT LIST` 每连接网络/命令指标、key 内存取样（`MEMORY USAGE`）。

### Valkey 9.2 Internals

9.2（rc1 已出，GA 目标 2026-11-15）在「降低内存开销 + 提升复制效率」上继续推进：

- **B+ 树有序集**：较大有序集（skiplist 编码）改写为优化的 B+ 树，叶子 512 B 紧凑打包，提升内存局部性；特定负载下 mutation 最多快约 **2×**（issue #3166）。
- **Path Hash**：面向层次/前缀查询的新数据类型，直接用例是 LLM 推理 KV 缓存的 token 前缀复用（PR #4506）；索引留在 Valkey，大 tensor 仍在 GPU/主机内存。
- **流式压缩复制/快照**：跨更大字节流做 LZ4/ZSTD 压缩，跨 region 传输字节数降 **50%~60%**（issue #3195）。
- 运维弹性：replica 落后时的复制节流、管理员保留连接、cluster 流量优先级、热 key 可观测、ACL 角色、条件事务。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

- [Valkey GitHub](https://github.com/valkey-io/valkey)
- [Valkey: A New In-Memory Data Store](https://valkey.io/)
- [Valkey 8.0: Enhanced Performance and Reliability](https://valkey.io/blog/valkey-8-0-0-rc1)
- [Reducing Memory Overhead in Valkey 9.1](https://valkey.io/blog/9.1-memory-efficiency)