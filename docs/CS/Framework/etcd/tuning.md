## Introduction

[etcd](/docs/CS/Framework/etcd/etcd.md) 是版本与分层导航枢纽。本文列出**可直接改的运维 flag 与默认值**，并给每项的适用场景与风险。默认值以 **v3.7.2** 的 `server/embed/config.go` 与 `server/etcdserver/server.go` 为准；涉及版本变化时单独标注。

> [!NOTE]
> 调优的优先级：先保证磁盘 I/O 与网络，再动下面这些 flag。绝大多数 3/5/7 节点集群用默认就能跑好；flag 主要解决"单 key 大值 / 高频写 / 跨数据中心高 RTT / 磁盘慢"这几类问题。

## Transactions and Request Scale

| flag | 默认 | 作用 | 调大场景 / 风险 |
| :--- | :--- | :--- | :--- |
| `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单 Txn 最多包含的操作数 | 一次事务要批量很多 key 时调大；过大易触发大请求、拖慢 apply |
| `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes`) | 单请求最大字节（含 value） | 存大 value（如大 JSON）时调大；过大撑爆内存、放大慢 apply（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 slow apply） |

## Raft Log and Snapshot

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--snapshot-count` | **10000** (`etcdserver.DefaultSnapshotCount`) | 每累积多少条 Raft entry 做一次快照，压缩 raft log |
| `--max-snapshots` | **5** (`DefaultMaxSnapshots`) | 保留的快照文件数 |
| `--max-wals` | **5** (`DefaultMaxWALs`) | 保留的 WAL 文件数 |

> [!NOTE]
> `--snapshot-count=10000` 是 **Raft 层**日志压缩频率，与 MVCC 历史无关。3.6 起默认值从 100000 降到 10000，v3.7.2 保持 10000；这不是 V2 后端快照逻辑。想回收 MVCC 历史空间要靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact + defrag，而不是调这个 flag。`--max-snapshots` / `--max-wals` 调小省磁盘、调大便于故障回滚与调试。

## Backend (boltdb) Batching

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--backend-batch-interval` | `0`（etcd 内部约 **100ms** 批处理） | 后端事务提交前的最大等待时间 |
| `--backend-batch-limit` | **10000** | 后端事务提交前的最大操作数 |

etcd 把多个写操作在内存里攒成一批再提交给 boltdb，以摊薄 fsync 开销。`batch-interval` 越大、单次提交越聚合、吞吐越高，但写延迟毛刺越大；`batch-limit` 是每批操作数上限。磁盘慢、写多的集群可适当调大 interval；对写延迟敏感则调小。

> [!WARNING]
> 改 backend 批处理参数会直接影响**写延迟的分布**。调大 interval 可能让 P99 写延迟升高（请求在等批次），但提升总吞吐；调小时延迟更平稳但 fsync 更频繁、磁盘压力更大。务必配合 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 的 `etcd_disk_backend_commit_duration_seconds` 看实际效果。

## Quota and Compaction

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--quota-backend-bytes` | **2 GiB**（8 GiB 为建议上限） | boltdb 后端配额；超限触发 `NOSPACE` alarm |
| `--auto-compaction-mode` | 默认**不开启** | `periodic`（如 `1h`）或 `revision`（如 `1000`） |
| `--auto-compaction-retention` | 同上，需同时设 | 配合 mode 的保留窗口 |

配额超限会进入 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。**默认不开启 auto-compaction**——长期写入的集群必须显式开，否则 MVCC 历史无限增长、db 文件只增不减（需 defrag 才回收，见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。`revision` 模式按版本数保留、`periodic` 模式按时间保留。

## Election Timing

| flag | 默认 | 约束 |
| :--- | :--- | :--- |
| `--heartbeat-interval` | **100** ms (`TickMs`) | 必须 > 0 |
| `--election-timeout` | **1000** ms (`ElectionMs`) | 必须 ≥ 5× heartbeat-interval，上限 50000 ms |

跨数据中心、RTT 大时按 `heartbeat ≈ RTT`、`election ≈ 10×RTT` 上调；所有成员必须一致，否则集群不稳。这里只列 flag 与校验边界（`config.go` 的 `Verify()` 会强制这些比例）。

## Equivalent Fields in Embedded Scenarios

用 [embed](/docs/CS/Framework/etcd/embed.md) 嵌入 etcd 时，上述 flag 一一对应 `embed.Config` 字段（如 `cfg.MaxTxnOps`、`cfg.SnapshotCount`、`cfg.QuotaBackendBytes`、`cfg.TickMs`、`cfg.ElectionMs`），默认值完全一致。

## Tuning Principles

调优的目标不是把某个 flag 调到最大，而是让 **Raft 复制、WAL/backend 落盘、apply 与客户端超时** 处在同一个延迟预算内。

### Election Timing

`heartbeat-interval` 决定 leader 多频繁发送心跳，`election-timeout` 决定 follower 多久没收到心跳后发起选举。硬约束是 `ElectionMs >= 5 × TickMs` 且不超过 50000ms；工程经验通常取 heartbeat 接近成员间 RTT、election 约为 10×RTT，以吸收调度与网络抖动。所有成员应使用一致的值：心跳过密浪费 CPU 与网络，选举过慢则故障切换更久，心跳过慢或选举过近又会造成无谓换主。

### Disk Latency

etcd 的延迟对磁盘非常敏感。Raft `Ready` 中的 WAL 保存、backend batch commit、snapshot 写入与 compaction 都可能产生 `fsync`；同盘上的其他进程会与这些操作争抢 I/O，放大 P99 延迟并导致心跳超时。优先使用低延迟磁盘、隔离 WAL 与 backend、监控 `etcd_disk_wal_fsync_duration_seconds` 和 `etcd_disk_backend_commit_duration_seconds`，再考虑调整 batch 参数。

`--backend-batch-interval` / `--backend-batch-limit` 控制 backend 的聚合程度：调大提高吞吐但增加单次提交前的等待，调小降低批内等待但增加提交次数。它们不改变 Raft 的共识顺序，也不能消除慢盘造成的选举抖动。

### Network and Apply

跨数据中心或高 RTT 环境应同时调整选举参数并监控 peer 流量。客户端 gRPC 与 rafthttp peer 共用主机网络时，大量客户端请求可能挤压 MsgApp/MsgAppResp，follower 追日志变慢，最终表现为请求超时或 leader 变更。必要时在操作系统层为 peer 端口优先分配带宽，但不要只靠调大 client timeout 掩盖网络问题。

CPU 调优的重点是减少序列化、锁竞争与 apply 排队，而不是简单增加节点。etcd 的写路径最终仍要按 Raft 顺序 apply；更多投票成员会增加复制消息与 quorum 等待，只在确实需要更高容错能力时才扩容。

### Cluster Size and Availability

3、5、7 个投票成员分别容忍 1、2、3 个成员故障。偶数节点不会比少一个节点的奇数集群提供更高容错，却增加一台机器与复制开销。生产上通常从 3 或 5 开始，逐台变更并确认健康。

Raft 保证同一 term 最多一个 leader，且写提案必须获得多数派；但这不等于网络分区两端都能继续服务。失去 quorum 的一侧不能提交线性一致写，isolated leader 也不能完成需要 ReadIndex 的线性一致读。监控 quorum 与 leader 变化，比追求“永不换主”更重要。

### Snapshot and History

`--snapshot-count` 控制 Raft 日志快照频率，不控制 MVCC 历史保留。长期写入的集群还应配置 auto-compaction，并在需要回收 bbolt 空闲页时执行 defrag；三者分别解决日志增长、历史版本增长和文件空闲页问题，不能互相替代。

## Links

- [Core_Mechanisms（apply、WAL 与 backend 的延迟边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [raft（心跳、选举与日志复制）](/docs/CS/Framework/etcd/raft.md)
- [cluster（成员变更与 quorum）](/docs/CS/Framework/etcd/cluster.md)

## References

1. [etcd v3.7.2 source - server/embed/config.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/embed/config.go)
2. [etcd v3.7.2 source - server/etcdserver/server.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/server.go)
3. [etcd Documentation - Configuration](https://etcd.io/docs/v3.7/op-guide/configuration/)
