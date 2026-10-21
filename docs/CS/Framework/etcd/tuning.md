## Introduction

[etcd.md](/docs/CS/Framework/etcd/etcd.md) 的 `Tuning` 段讲了**心跳/选举/磁盘/网络/CPU** 的调优原理（为什么 heartbeat≈RTT、election≥5×heartbeat、磁盘延迟如何引发丢心跳）。本文换一个角度：列出**可直接改的运维 flag 与默认值**，并给每项的适用场景与风险。所有默认值取自 `server/embed/config.go` 与 `server/etcdserver` 常量（v3.5.34 源码），不凭文档记忆。

> [!NOTE]
> 调优的优先级：先保证磁盘 I/O 与网络（etcd.md Tuning 段），再动下面这些 flag。绝大多数 3/5/7 节点集群用默认就能跑好；flag 主要解决"单 key 大值 / 高频写 / 跨数据中心高 RTT / 磁盘慢"这几类问题。

## Transactions and Request Scale

| flag | 默认 | 作用 | 调大场景 / 风险 |
| :--- | :--- | :--- | :--- |
| `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单 Txn 最多包含的操作数 | 一次事务要批量很多 key 时调大；过大易触发大请求、拖慢 apply |
| `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes`) | 单请求最大字节（含 value） | 存大 value（如大 JSON）时调大；过大撑爆内存、放大慢 apply（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 slow apply） |

## Raft Log and Snapshot

| flag | 默认 | 作用 |
| :--- | :--- | :--- |
| `--snapshot-count` | **100000** (`etcdserver.DefaultSnapshotCount`) | 每累积多少条 Raft entry 做一次快照，压缩 raft log |
| `--max-snapshots` | **5** (`DefaultMaxSnapshots`) | 保留的快照文件数 |
| `--max-wals` | **5** (`DefaultMaxWALs`) | 保留的 WAL 文件数 |

> [!NOTE]
> `--snapshot-count=100000` 是 **Raft 层**日志压缩频率，与 MVCC 历史无关。etcd.md Tuning 段提到的"每 10,000 次变更做快照"是 **V2 后端**旧值；V3 当前默认是 100000。想回收 MVCC 历史空间要靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact + defrag，而不是调这个 flag。`--max-snapshots` / `--max-wals` 调小省磁盘、调大便于故障回滚与调试。

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
| `--quota-backend-bytes` | **2 GiB**（上限 8 GiB） | boltdb 后端配额；超限触发 `NOSPACE` alarm |
| `--auto-compaction-mode` | 默认**不开启** | `periodic`（如 `1h`）或 `revision`（如 `1000`） |
| `--auto-compaction-retention` | 同上，需同时设 | 配合 mode 的保留窗口 |

配额超限会进入 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。**默认不开启 auto-compaction**——长期写入的集群必须显式开，否则 MVCC 历史无限增长、db 文件只增不减（需 defrag 才回收，见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。`revision` 模式按版本数保留、`periodic` 模式按时间保留。

## Election Timing (Echoes etcd.md Tuning)

| flag | 默认 | 约束 |
| :--- | :--- | :--- |
| `--heartbeat-interval` | **100** ms (`TickMs`) | 必须 > 0 |
| `--election-timeout` | **1000** ms (`ElectionMs`) | 必须 ≥ 5× heartbeat-interval，上限 50000 ms |

跨数据中心、RTT 大时按 `heartbeat ≈ RTT`、`election ≈ 10×RTT` 上调；所有成员必须一致，否则集群不稳。这组在 etcd.md Tuning 段有原理展开，这里只列 flag 与校验边界（`config.go` 的 `Verify()` 会强制这些比例）。

## Equivalent Fields in Embedded Scenarios

用 [embed](/docs/CS/Framework/etcd/embed.md) 嵌入 etcd 时，上述 flag 一一对应 `embed.Config` 字段（如 `cfg.MaxTxnOps`、`cfg.SnapshotCount`、`cfg.QuotaBackendBytes`、`cfg.TickMs`、`cfg.ElectionMs`），默认值完全一致。

## 调优原理（心跳 / 选举 / 磁盘 / 网络 / CPU）

下面是从 etcd.md 合并过来的原理层内容：flag 级默认值与适用场景见本页上方的各表。

flag 级默认值见本页上方的「Transactions and Request Scale / Raft Log and Snapshot / Election Timing」等节。

The default settings in etcd should work well for installations on a local network where the average network latency is low. However, when using etcd across multiple data centers or over networks with high latency, the heartbeat interval and election timeout settings may need tuning.
The network isn’t the only source of latency. Each request and response may be impacted by slow disks on both the leader and follower. Each of these timeouts represents the total time from request to successful response from the other machine.

The underlying distributed consensus protocol relies on two separate time parameters to ensure that nodes can handoff leadership if one stalls or goes offline. The first parameter is called the Heartbeat Interval. This is the frequency with which the leader will notify followers that it is still the leader. For best practices, the parameter should be set around round-trip time between members. By default, etcd uses a 100ms heartbeat interval.

The second parameter is the Election Timeout. This timeout is how long a follower node will go without hearing a heartbeat before attempting to become leader itself. By default, etcd uses a 1000ms election timeout.

Adjusting these values is a trade off. The value of heartbeat interval is recommended to be around the maximum of average round-trip time (RTT) between members, normally around 0.5-1.5x the round-trip time. If heartbeat interval is too low, etcd will send unnecessary messages that increase the usage of CPU and network resources. On the other side, a too high heartbeat interval leads to high election timeout. Higher election timeout takes longer time to detect a leader failure. The easiest way to measure round-trip time (RTT) is to use PING utility.

The election timeout should be set based on the heartbeat interval and average round-trip time between members. Election timeouts must be at least 10 times the round-trip time so it can account for variance in the network.
The upper limit of election timeout is 50000ms (50s), which should only be used when deploying a globally-distributed etcd cluster.

The heartbeat interval and election timeout value should be the same for all members in one cluster. Setting different values for etcd members may disrupt cluster stability.

etcd appends all key changes to a log file. This log grows forever and is a complete linear history of every change made to the keys. A complete history works well for lightly used clusters but clusters that are heavily used would carry around a large log.
To avoid having a huge log etcd makes periodic snapshots. These snapshots provide a way for etcd to compact the log by saving the current state of the system and removing old logs.

Creating snapshots with the V2 backend can be expensive, so snapshots are only created after a given number of changes to etcd. By default, snapshots will be made after every 10,000 changes.

disk

An etcd cluster is very sensitive to disk latencies. Since etcd must persist proposals to its log, disk activity from other processes may cause long fsync latencies. The upshot is etcd may miss heartbeats, causing request timeouts and temporary leader loss. An etcd server can sometimes stably run alongside these processes when given a high disk priority.

On Linux, etcd’s disk priority can be configured with ionice:

```
# best effort, highest priority
$ sudo ionice -c2 -n0 -p `pgrep etcd`
```

Network

If the etcd leader serves a large number of concurrent client requests, it may delay processing follower peer requests due to network congestion. This manifests as send buffer error messages on the follower nodes:

```
dropped MsgProp to 247ae21ff9436b2d since streamMsg’s sending buffer is full
dropped MsgAppResp to 247ae21ff9436b2d since streamMsg‘s sending buffer is full

```

These errors may be resolved by prioritizing etcd’s peer traffic over its client traffic. On Linux, peer traffic can be prioritized by using the traffic control mechanism:

```
tc qdisc add dev eth0 root handle 1: prio bands 3
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip sport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip dport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip sport 2379 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip dport 2379 0xffff flowid 1:1
```

CPU

As etcd is very sensitive to latency, performance can further be optimized on Linux systems by setting the CPU governor to performance or conservative mode.

On Linux, the CPU governor can be configured to performance mode:

```
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

偶数节点虽然多了一台机器，但是容错能力是一样的 多一台机器增加不了性能，反而会拉低写入速度

etcd 集群是一个 Raft Group，没有 shared。所以它的极限有两部分，一是单机的容量限制，内存和磁盘；二是网络开销，每次 Raft 操作需要所有节点参与
每一次写操作需要集群中大多数节点将日志落盘成功后，Leader 节点才能修改内部状态机，并将结果返回给客户端 节点越多性能越低，所以扩展很多 etcd 节点是没有意义的，一般是 3、5、7， 7 个也足够了

The majority side becomes the available cluster and the minority side is unavailable; there is no “split-brain” in etcd.

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
