# Tuning

## Introduction

[etcd](/docs/CS/Framework/etcd/etcd.md) 是版本与分层导航枢纽。本文列出**可直接改的运维 flag 与默认值**，并给每项的适用场景与风险。默认值以 **v3.7.2** 的 `server/embed/config.go` 与 `server/etcdserver/server.go` 为准；涉及版本变化时单独标注。

> [!NOTE]
> 调优的优先级：先保证磁盘 I/O 与网络，再动下面这些 flag。绝大多数 3/5/7 节点集群用默认就能跑好；flag 主要解决"单 key 大值 / 高频写 / 跨数据中心高 RTT / 磁盘慢"这几类问题。
[etcd.md](/docs/CS/Framework/etcd/etcd.md) 的 Tuning 段讲了**心跳/选举/磁盘/网络/CPU** 的调优原理（为什么 heartbeat≈RTT、election≥5×heartbeat、磁盘延迟如何引发丢心跳）。本页换一个角度：列出**可直接改的运维 flag 与默认值**，每项给适用场景与风险。默认值取自 `server/embed/config.go` 与 `server/etcdserver` 常量（3.7.4），不凭文档记忆。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下默认值均取自该 tag 的源码常量。

调优优先级：先保证磁盘 I/O 与网络，再动 flag。绝大多数 3/5/7 节点集群用默认就能跑好；flag 主要解决"单 key 大值 / 高频写 / 跨数据中心高 RTT / 磁盘慢"这几类问题。

从源码核实的关键默认值常量：

```go
// server/embed/config.go
DefaultMaxSnapshots                = 5
DefaultMaxWALs                     = 5
DefaultMaxTxnOps                   = uint(128)
DefaultWarningApplyDuration        = 100 * time.Millisecond
DefaultMaxRequestBytes             = 1.5 * 1024 * 1024
```

> [!WARNING]
> **`--snapshot-count` 默认值在 3.6 起从 100000 降到 10000**（3.7.4 的 `etcdserver.DefaultSnapshotCount = 10000`），换来相比 3.5 约 50% 的内存下降。旧资料普遍写 100000，照抄会 misjudge 快照频率。若负载依赖大 snapshot 间隔，升级后需重新评估。

## Transactions and Request Scale

| flag | 默认 | 作用 | 调大场景 / 风险 |
| :--- | :--- | :--- | :--- |
| `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单 Txn 最多操作数 | 批量很多 key 时调大；过大触发大请求、拖慢 apply |
| `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes`) | 单请求最大字节 | 存大 value 时调大；过大撑爆内存、放大慢 apply（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)） |

## Raft Log and Snapshot

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--snapshot-count` | **10000** (`etcdserver.DefaultSnapshotCount`) | 每累积多少条 Raft entry 做一次快照，压缩 raft log |
| `--snapshot-count` | **10000** (`etcdserver.DefaultSnapshotCount`) | 每累积多少条 Raft entry 做一次快照、压缩 raft log |
| `--max-snapshots` | **5** (`DefaultMaxSnapshots`) | 保留的快照文件数 |
| `--max-wals` | **5** (`DefaultMaxWALs`) | 保留的 WAL 文件数 |

> [!NOTE]
> `--snapshot-count=10000` 是 **Raft 层**日志压缩频率，与 MVCC 历史无关。3.6 起默认值从 100000 降到 10000，v3.7.2 保持 10000；这不是 V2 后端快照逻辑。想回收 MVCC 历史空间要靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact + defrag，而不是调这个 flag。`--max-snapshots` / `--max-wals` 调小省磁盘、调大便于故障回滚与调试。
> `--snapshot-count` 是 **Raft 层**日志压缩频率，与 MVCC 历史无关。早期 V2 后端"每 10,000 次变更做快照"的旧值与当前的 100000/10000 不是一回事——3.7.4 当前是 10000。想回收 MVCC 历史空间要靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact + defrag，而不是调这个 flag。`--max-snapshots` / `--max-wals` 调小省磁盘、调大便于故障回滚与调试。

## Backend Batching

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--backend-batch-interval` | `0`（etcd 内部约 **100ms** 批处理） | 后端事务提交前最大等待 |
| `--backend-batch-limit` | **10000** | 后端事务提交前最大操作数 |

etcd 把多个写在内存攒成一批再提交给 boltdb，以摊薄 fsync 开销。`batch-interval` 越大、单次提交越聚合、吞吐越高，但写延迟毛刺越大；`batch-limit` 是每批操作数上限。磁盘慢、写多的集群可上调 interval；写延迟敏感则调小。

> [!WARNING]
> 改 backend 批处理参数直接影响**写延迟分布**。调大 interval 可能抬高 P99 写延迟（请求等批次）但提升吞吐；调小则延迟平稳但 fsync 更频繁、磁盘压力更大。务必配合 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 的 `etcd_disk_backend_commit_duration_seconds` 看实际效果。

## Quota and Compaction

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--quota-backend-bytes` | **2 GiB**（上限 8 GiB，生产建议 8 GiB） | boltdb 后端配额，超限触发 NOSPACE |
| `--auto-compaction-mode` | 默认**不开启** | `periodic`（如 `1h`）或 `revision`（如 `1000`） |
| `--auto-compaction-retention` | 需同时设 | 配合 mode 的保留窗口 |

配额超限进入 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。**默认不开启 auto-compaction**——长期写入集群必须显式开，否则 MVCC 历史无限增长、db 只增不减（需 defrag 才回收，见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。

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
`Config.Verify()` 强制这些比例，源码里的校验：

```go
if cfg.ElectionMs == 0 {
	return fmt.Errorf("--election-timeout must be >0 (set to %dms)", cfg.ElectionMs)
}
if 5*cfg.TickMs > cfg.ElectionMs {
	return fmt.Errorf("--election-timeout[%vms] should be at least as 5 times as --heartbeat-interval[%vms]", cfg.ElectionMs, cfg.TickMs)
}
if cfg.ElectionMs > maxElectionMs { // maxElectionMs = 50000
	return fmt.Errorf("--election-timeout[%vms] is too long, and should be set less than %vms", cfg.ElectionMs, maxElectionMs)
}
```

跨数据中心、RTT 大时按 `heartbeat ≈ RTT`、`election ≈ 10×RTT` 上调；**所有成员必须一致**，否则集群不稳。

## Principles of Heartbeat Election Disk Network and CPU

flag 级默认值见上方各表，这里补充原理。默认设置对局域网（低延迟）表现良好；跨多数据中心或高延迟网络时需调心跳与选举超时。网络不是唯一延迟源——leader 与 follower 的慢盘都会拖慢每次请求响应。

- **Heartbeat Interval**：leader 通知 follower"我还在"的频率，建议设为成员间 RTT 附近（约 0.5–1.5×RTT），默认 100ms。太低浪费 CPU/网络，太高则推高 election timeout、延长故障发现时间。用 `ping` 测 RTT。
- **Election Timeout**：follower 多久没收到心跳就发起选举，默认 1000ms，至少 10×RTT，上限 50000ms（仅用于全球分布式集群）。同一集群所有成员必须一致。
- **Disk**：etcd 把每次变更追加到日志并持久化提案，其他进程的磁盘活动会造成长 fsync 延迟，导致丢心跳、请求超时、临时丢 leader。Linux 下可用 `ionice -c2 -n0 -p $(pgrep etcd)` 提优先级。
- **Network**：leader 并发大时可能因网络拥塞延迟处理 follower 请求，follower 出现 `dropped MsgApp ... sending buffer is full`。可用 `tc qdisc` 让 peer 流量（2380）优先于 client 流量（2379）。
- **CPU**：对延迟敏感，Linux 下可设 CPU governor 为 performance：`echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`。

> [!NOTE]
> 偶数节点虽多一台机器，容错能力不变，反而拉低写入速度——每次写要多数派落盘，节点越多性能越低。所以集群规模一般是 3、5、7，7 个已足够。etcd 是单个 Raft Group，没有 shared-nothing 分片，极限受单机内存/磁盘与网络开销双重约束。多数派成为可用侧、少数派不可用，**不存在 split-brain**。

## Embedded Scenarios

用 [embed](/docs/CS/Framework/etcd/embed.md) 嵌入 etcd 时，上述 flag 一一对应 `embed.Config` 字段（`cfg.MaxTxnOps`、`cfg.SnapshotCount`、`cfg.QuotaBackendBytes`、`cfg.TickMs`、`cfg.ElectionMs`），默认值完全一致。

## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [embed](/docs/CS/Framework/etcd/embed.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [monitoring](/docs/CS/Framework/etcd/monitoring.md)

## References

1. [etcd v3.7.4 源码（server/embed/config.go — 默认值常量）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/embed/config.go)
2. [etcd v3.7.4 源码（server/etcdserver/server.go — DefaultSnapshotCount）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/server.go)
3. [etcd Documentation - Tuning](https://etcd.io/docs/v3.7/op-guide/configuration/)
