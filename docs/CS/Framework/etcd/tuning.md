## Introduction

[etcd.md](/docs/CS/Framework/etcd/etcd.md) 的 `Tuning` 段讲了**心跳/选举/磁盘/网络/CPU** 的调优原理（为什么 heartbeat≈RTT、election≥5×heartbeat、磁盘延迟如何引发丢心跳）。本文换一个角度：列出**可直接改的运维 flag 与默认值**，并给每项的适用场景与风险。所有默认值取自 `server/embed/config.go` 与 `server/etcdserver` 常量（v3.5.34 源码），不凭文档记忆。

> [!NOTE]
> 调优的优先级：先保证磁盘 I/O 与网络（etcd.md Tuning 段），再动下面这些 flag。绝大多数 3/5/7 节点集群用默认就能跑好；flag 主要解决"单 key 大值 / 高频写 / 跨数据中心高 RTT / 磁盘慢"这几类问题。

## 事务与请求规模

| flag | 默认 | 作用 | 调大场景 / 风险 |
| :--- | :--- | :--- | :--- |
| `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单 Txn 最多包含的操作数 | 一次事务要批量很多 key 时调大；过大易触发大请求、拖慢 apply |
| `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes`) | 单请求最大字节（含 value） | 存大 value（如大 JSON）时调大；过大撑爆内存、放大慢 apply（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 slow apply） |

## Raft 日志与快照

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--snapshot-count` | **100000** (`etcdserver.DefaultSnapshotCount`) | 每累积多少条 Raft entry 做一次快照，压缩 raft log |
| `--max-snapshots` | **5** (`DefaultMaxSnapshots`) | 保留的快照文件数 |
| `--max-wals` | **5** (`DefaultMaxWALs`) | 保留的 WAL 文件数 |

> [!NOTE]
> `--snapshot-count=100000` 是 **Raft 层**日志压缩频率，与 MVCC 历史无关。etcd.md Tuning 段提到的"每 10,000 次变更做快照"是 **V2 后端**旧值；V3 当前默认是 100000。想回收 MVCC 历史空间要靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact + defrag，而不是调这个 flag。`--max-snapshots` / `--max-wals` 调小省磁盘、调大便于故障回滚与调试。

## 后端（boltdb）批处理

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--backend-batch-interval` | `0`（etcd 内部约 **100ms** 批处理） | 后端事务提交前的最大等待时间 |
| `--backend-batch-limit` | **10000** | 后端事务提交前的最大操作数 |

etcd 把多个写操作在内存里攒成一批再提交给 boltdb，以摊薄 fsync 开销。`batch-interval` 越大、单次提交越聚合、吞吐越高，但写延迟毛刺越大；`batch-limit` 是每批操作数上限。磁盘慢、写多的集群可适当调大 interval；对写延迟敏感则调小。

> [!WARNING]
> 改 backend 批处理参数会直接影响**写延迟的分布**。调大 interval 可能让 P99 写延迟升高（请求在等批次），但提升总吞吐；调小时延迟更平稳但 fsync 更频繁、磁盘压力更大。务必配合 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 的 `etcd_disk_backend_commit_duration_seconds` 看实际效果。

## 配额与压缩

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--quota-backend-bytes` | **2 GiB**（上限 8 GiB） | boltdb 后端配额；超限触发 `NOSPACE` alarm |
| `--auto-compaction-mode` | 默认**不开启** | `periodic`（如 `1h`）或 `revision`（如 `1000`） |
| `--auto-compaction-retention` | 同上，需同时设 | 配合 mode 的保留窗口 |

配额超限会进入 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。**默认不开启 auto-compaction**——长期写入的集群必须显式开，否则 MVCC 历史无限增长、db 文件只增不减（需 defrag 才回收，见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。`revision` 模式按版本数保留、`periodic` 模式按时间保留。

## 选举时序（与 etcd.md Tuning 呼应）

| flag | 默认 | 约束 |
| :--- | :--- | :--- |
| `--heartbeat-interval` | **100** ms (`TickMs`) | 必须 > 0 |
| `--election-timeout` | **1000** ms (`ElectionMs`) | 必须 ≥ 5× heartbeat-interval，上限 50000 ms |

跨数据中心、RTT 大时按 `heartbeat ≈ RTT`、`election ≈ 10×RTT` 上调；所有成员必须一致，否则集群不稳。这组在 etcd.md Tuning 段有原理展开，这里只列 flag 与校验边界（`config.go` 的 `Verify()` 会强制这些比例）。

## 嵌入式场景的等价字段

用 [embed](/docs/CS/Framework/etcd/embed.md) 嵌入 etcd 时，上述 flag 一一对应 `embed.Config` 字段（如 `cfg.MaxTxnOps`、`cfg.SnapshotCount`、`cfg.QuotaBackendBytes`、`cfg.TickMs`、`cfg.ElectionMs`），默认值完全一致。

## Links

- [etcd（Tuning 段：心跳/选举/磁盘/网络/CPU 原理）](/docs/CS/Framework/etcd/etcd.md)
- [embed（Config 字段与默认值）](/docs/CS/Framework/etcd/embed.md)
- [cluster（数据目录、配额、备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [boltdb（backend 批处理落地的存储引擎）](/docs/CS/Framework/etcd/boltdb.md)
- [compact（MVCC 历史压缩，区别于 snapshot-count）](/docs/CS/Framework/etcd/compact.md)
- [troubleshooting（NOSPACE / slow apply）](/docs/CS/Framework/etcd/troubleshooting.md)
- [monitoring（commit 延迟等告警指标）](/docs/CS/Framework/etcd/monitoring.md)

## References

1. [etcd source - server/embed/config.go（MaxTxnOps / MaxRequestBytes / TickMs / ElectionMs / 默认值常量）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/embed/config.go)
2. [etcd source - server/etcdserver（DefaultSnapshotCount=100000 / DefaultMaxSnapshots / DefaultMaxWALs）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/etcdserver)
3. [etcd Documentation - Tuning（heartbeat / election / disk / network / CPU）](https://etcd.io/docs/v3.5/op-guide/configuration/)
