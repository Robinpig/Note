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
| **9.1.2** | 2026-09-01 | 当前最新；安全修复（RDMA UAF、Lua 解释器 UAF） |

另有9.2.0-rc1（2026-09-16，预发布），GA 未发布。

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

- **多线程 I/O**：network read/write 与命令执行解耦（类似 Redis 6 的 I/O threads 并持续增强），单线程命令执行保证无锁语义。Redis 侧 `io-threads` 是 `IMMUTABLE_CONFIG`（8.10.2 `src/config.c:3507`），Valkey 侧可通过 `updateIOThreads` 回调动态调整。
- **Cluster**：无中心分片（16384 slot），Gossip 维护拓扑，支持 reshard/replica。
- **数据结构**：string/hash/list/set/zset/stream 等，RDB/AOF 持久化，pub-sub、Lua 脚本。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

- [Valkey GitHub](https://github.com/valkey-io/valkey)
- [Valkey: A New In-Memory Data Store](https://valkey.io/)