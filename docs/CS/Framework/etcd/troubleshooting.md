# Troubleshooting

## Introduction

etcd 的报错分两层：一组**哨兵 error 变量**，以及把它们包装成 gRPC `status` 的 `ErrGRPC*` 变量。客户端看到的字符串一律来自后者，形如 `rpc error: code = 8 desc = etcdserver: mvcc: database space exceeded`。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。本文所有错误字符串、文件路径、命令与阈值均以 3.7.4 源码为准；错误信息串在版本演进中改过写法，用旧字符串 grep 日志会漏。

3.7 里这两层分处不同路径，且第二层是独立 module：

| 层 | 3.7.4 路径 | 定义的变量 |
| :--- | :--- | :--- |
| 服务端哨兵 error | `server/etcdserver/errors/errors.go` | `ErrNoSpace`、`ErrCorrupt`、`ErrNotEnoughStartedMembers`… |
| gRPC 包装 | `api/v3rpc/rpctypes/error.go` | `ErrGRPCNoSpace`、`ErrGRPCCompacted`… |

> [!WARNING]
> `server/etcdserver/errors.go` 这个路径在 3.7 **已失效**——文件移进了 `errors/` 子包成为独立子包。照旧路径去 GitHub 搜索会 404。另外 `api/v3rpc/rpctypes/` 属于独立 module `go.etcd.io/etcd/api/v3`，不在 `server/` 下。

哨兵错误定义在 `server/etcdserver/errors/errors.go`：

```go
ErrNotEnoughStartedMembers     = errors.New("etcdserver: re-configuration failed due to not enough started members")
ErrLearnerNotReady             = errors.New("etcdserver: can only promote a learner member which is in sync with leader")
ErrNoSpace                     = errors.New("etcdserver: no space")
ErrTooManyRequests             = errors.New("etcdserver: too many requests")
ErrCorrupt                     = errors.New("etcdserver: corrupt cluster")
```

gRPC 包装层在 `api/v3rpc/rpctypes/error.go`，带上标准 code 与 `etcdserver:` 前缀描述串：

```go
ErrGRPCCompacted               = status.Error(codes.OutOfRange, "etcdserver: mvcc: required revision has been compacted")
ErrGRPCFutureRev               = status.Error(codes.OutOfRange, "etcdserver: mvcc: required revision is a future revision")
ErrGRPCNoSpace                 = status.Error(codes.ResourceExhausted, "etcdserver: mvcc: database space exceeded")
ErrGRPCMemberNotEnoughStarted = status.Error(codes.FailedPrecondition, "etcdserver: re-configuration failed due to not enough started members")
ErrGRPCTooManyLearners        = status.Error(codes.FailedPrecondition, "etcdserver: too many learner members in cluster")
```

描述串前缀按子领域细分（`etcdserver: mvcc:` 表示 MVCC 层），这些字符串同时充当跨进程"错误 ID"，必须保持稳定唯一。客户端可按 gRPC code 判断：

| gRPC code | 数值 | etcd 典型场景 |
| :--- | :--- | :--- |
| `InvalidArgument` | 3 | 参数非法、auth 失败、请求过大 |
| `NotFound` | 5 | key / member / lease 不存在 |
| `FailedPrecondition` | 9 | learner 未追平、quorum 不足、auth 未启用 |
| `OutOfRange` | 11 | **revision 已被 compact**、revision 超前 |
| `ResourceExhausted` | 8 | **database space exceeded**、请求过多 |
| `Unavailable` | 14 | 连接不可用、正在选主 |
| `Unauthenticated` | 16 | token 无效或过期 |
| `Internal` | 13 | 状态机异常（`ErrCorrupt` 走这里） |
| `DeadlineExceeded` | 4 | 超时（多与磁盘慢相关） |

关键映射（客户端重试逻辑应建立在这张表上）：

- `OutOfRange` + `mvcc: required revision has been compacted` → **不可重试**，必须重新 LIST
- `ResourceExhausted` + `mvcc: database space exceeded` → **不可重试**，必须先腾空间
- `Unavailable` → 可重试（配合退避，否则加剧选举）
- `DeadlineExceeded` → 谨慎重试，可能磁盘问题，盲目重试加剧压力

> [!TIP]
> `ResourceExhausted`（8）和 `Unavailable`（14）都是 gRPC 官方**可重试 code**，但 etcd 的 `database space exceeded` 恰好也用 8。这是"gRPC 重试语义"与"业务语义"错配最明显处——**按 gRPC 标准自动重试会陷入死循环**，这也是 [client](/docs/CS/Framework/etcd/client.md) 必须显式处理 NOSPACE 的原因。

## NOSPACE

最常见的生产故障。etcd 的 MVCC 保留完整 keyspace 历史（见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)），不定期 [compact](/docs/CS/Framework/etcd/compact.md) 就会耗尽空间；低于配额时触发 cluster-wide alarm 进入维护模式，**只接受读和删除，拒绝所有写**。

> [!WARNING]
> NOSPACE 是 **cluster-wide** 的：任意成员触发，全集群拒绝写入。处理时须对所有成员分别操作，不能只修一台。

### Positioning

```shell
$ etcdctl --write-out=table endpoint status
# ERRORS 列出现 alarm:NOSPACE
$ etcdctl endpoint health -w table
# HEALTH=false, ERROR=Active Alarm(s): NOSPACE
$ etcdctl alarm list
memberID:13803658152347727308 alarm:NOSPACE
```

观察 `member/snap` 目录的 `ls -lrt` 有个技巧：`.snap` 文件大小基本不变、只有 `db` 在长，说明增长完全来自新数据而非快照累积，该 compact 而不是排查快照机制。

### Actual Error String

三层字符串对应三层，排查时要知道看到的是哪一层：

| 你看到的 | 出处 | gRPC code |
| :--- | :--- | :--- |
| `etcdserver: mvcc: database space exceeded` | `api/v3rpc/rpctypes/error.go`（`ErrGRPCNoSpace`） | 8 `ResourceExhausted` |
| `etcdserver: no space` | `server/etcdserver/errors/errors.go`（`ErrNoSpace` 哨兵） | — |
| `Active Alarm(s): NOSPACE` | `etcdctl endpoint health` 自行拼装 | — |

> [!NOTE]
> NOSPACE 有反直觉边界：**收到 `ErrGRPCNoSpace` 不代表写操作没生效**。配额检查在 API 层与 Apply 层两处，Apply 层只**触发 alarm 而不阻止事务继续**。可能出现"客户端收到报错、数据其实写进去了"。取 `etcdctl compact` 的 revision 时别取到 alarm 之后的，否则会把这次写入一起 compact 掉。

### Four-Step Remediation

```shell
# 1. 取当前 revision
$ rev=$(etcdctl --endpoints=:2379 endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9]*')
# 2. 压缩旧 revision
$ etcdctl compact $rev
# 3. 碎片整理（阻塞操作，3 节点逐台跑）
$ etcdctl defrag
# 4. 解除告警
$ etcdctl alarm disarm
```

> [!WARNING]
> `defrag` 会**独占锁并阻塞该节点所有请求**，三节点集群要逐台执行，且这步不能省——compact 只清 MVCC 索引，磁盘占用要靠 defrag 归还。3.7 的 alpha feature gate `StopGRPCServiceOnDefrag`（默认 false）与之相关：关着时是"请求被阻塞住"，开着时是"请求直接被拒"——若 defrag 期间收到连接错误而非超时，先确认该 gate 状态。

长期方案是自动压缩：`--auto-compaction-mode=periodic --auto-compaction-retention=1h` 或 `--auto-compaction-mode=revision --auto-compaction-retention=1000`。两种模式的实际触发时机与直觉不符（见 [compact](/docs/CS/Framework/etcd/compact.md)）。用 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 的 `etcdExcessiveDatabaseGrowth` 做提前预警。

## Slow apply

官方判据很具体：**平均 apply 耗时超过 100ms 就打警告**（阈值常量 `DefaultWarningApplyDuration = 100 * time.Millisecond`），可由 `--warning-apply-duration` 调整。正常即使慢机械盘或云盘，单次 apply 也不应超过 50ms。

> [!WARNING]
> **实际字符串是 `apply request took too long`，不是 `apply entries took too long`。** 旧资料的写法在源码里已无此串，用错字符串 grep 日志一条都搜不到，从而误判"没触发该警告"。真实实现在 `server/etcdserver/txn/util.go`：

```go
func warnOfExpensiveGenericRequest(lg *zap.Logger, warningApplyDuration time.Duration, now time.Time, reqStringer fmt.Stringer, prefix string, resp string, err error) {
	lg.Warn(
		"apply request took too long",
		zap.Duration("took", time.Since(now)),
		zap.Duration("expected-duration", warningApplyDuration),
		zap.String("prefix", prefix),
		// ... 省略
	)
}
```

同一条警告被三类请求共用，靠 `prefix` 区分：`""`（普通请求）、`"read-only txn "`（只读事务）、`"read-only range "`（只读区间查询）。**排查时务必看 prefix**：`read-only range` 超时说明瓶颈在读路径，方向完全不同。

三类根因，按常见度排序：

1. **慢磁盘（最常见）**：`curl -L http://localhost:2379/metrics | grep backend_commit_duration`，p99 应 < 25ms；超了就给 etcd 独立磁盘或换更快的盘。
2. **CPU 饥饿**：监控 CPU 长期打满则算力不足，迁移到独立机器、提高 cgroup 优先级、`renice` 提升进程优先级。
3. **单请求 key 太多**："取走整个 keyspace"这类请求让 apply 变慢。官方经验数字是单请求访问 key 数控制在几百以内。

> [!TIP]
> 第 3 点反过来给了容量规划依据：etcd 适合"读多写少、访问局部"的工作负载，**不适合当分析型数据库**。海量数据应写进对象存储或时序库，etcd 只存指针和元信息。

## Leader Frequent Election

官方告警阈值是 **15 分钟内 leader 切换 >= 4 次**（`etcdHighNumberOfLeaderChanges`，持续 5m）。频繁选举通常意味着资源不足、网络延迟高，或被其他组件反复干扰。排查顺序：

1. `etcd_disk_wal_fsync_duration_seconds`（p99 > 0.5s）→ 磁盘 fsync 慢
2. `etcd_network_peer_round_trip_time_seconds`（p99 > 0.15s）→ 网络抖动
3. 成员数与分布 → 跨机房/可用区让心跳往返天然偏大

> [!WARNING]
> 调整 `--heartbeat-interval` / `--election-timeout`（默认 100ms / 1000ms）是**最后手段**。调大虽减少误选举，但拉长真正故障时的恢复时间——默认值本就是 1:10 的宽松比例。正确做法是先解决磁盘与网络。

## Compaction and Watch Invalidation

Kubernetes 场景里 `mvcc: required revision has been compacted` 极为常见（kube-apiserver 日志成片出现）。哨兵在 `server/storage/mvcc/kvstore.go` 的 `ErrCompacted`，gRPC 层是 `api/v3rpc/rpctypes/error.go` 的 `ErrGRPCCompacted`（`codes.OutOfRange`）。含义是客户端 watch/读的 revision 已被 compact 永久删除，根因通常是 **watch 存活时间超过压缩周期**。

两种处置方向：客户端从当前 revision 重新建 watch，或重启卡住的客户端 Pod 让其重新 LIST 拿最新 revision。

> [!TIP]
> **根因在 compact 策略而非 etcd 本身**。只要 watch 最长持有期 ≤ 压缩保留期就不会出现。设压缩周期时务必保证 `auto-compaction-retention` 大于任何客户端可能的最长 watch 时长。

## cluster ID mismatch

```text
request ignored (cluster ID mismatch)
```

每个新集群根据初始配置和用户提供的唯一 `initial-cluster-token` 生成 cluster ID，不同 ID 之间的请求被直接忽略并打这条警告。哨兵在 peer 层 `server/etcdserver/api/rafthttp/http.go`，**不带** `etcdserver:` 前缀（因为是 peer 层而非 server 层错误）。典型场景是拆掉旧集群后复用相同 peer 地址、旧进程还活着。解法是保证不同集群 peer 地址互不重叠、清理残留进程。

## Reconfiguration Rejected

```text
etcdserver: re-configuration failed due to not enough started members
```

> [!WARNING]
> **实际字符串没有 `reconfig: cluster ` 前缀。** 旧资料的写法在 3.7.4 源码里不存在。哨兵在 `server/etcdserver/errors/errors.go`（`ErrNotEnoughStartedMembers`），gRPC 包装在 `api/v3rpc/rpctypes/error.go`（`ErrGRPCMemberNotEnoughStarted`，`codes.FailedPrecondition`），两处都不带该前缀。

这是 quorum 保护在起作用，详见 [cluster](/docs/CS/Framework/etcd/cluster.md) 的 `strict-reconfig-check`（3.7 默认开启）。etcd 拒绝那些会导致"已启动成员 < 新多数派"的提案。相邻的成员错误还有 `can only promote a learner member which is in sync with leader`（未追平）、`too many learner members in cluster`（最多 1 个 learner）、`member ID already exist`，共同点是都拒绝改变成员构成的提案。

## Data corruption

etcd 内置损坏检查（`/readyz?verbose` 的 `data_corruption` 项）：

```bash
curl -k http://localhost:2379/readyz?verbose
# 输出 data_corruption failed 即确认 boltdb 已损坏
```

恢复路径：隔离故障成员 → 从健康成员取最新快照 → `etcdutl snapshot restore` 重建（见 [cluster](/docs/CS/Framework/etcd/cluster.md)）→ 以 learner 身份重新加入。

> [!WARNING]
> 若**多数成员同时损坏**（如共用存储、同时断电），没有健康快照可依，只能靠 `db` 文件尽力恢复且必须接受**丢失最后一次快照之后的数据**。这就是定期 `etcdctl snapshot save` 到集群外存储是硬要求的原因——快照存在集群内部时，它和被保护的数据库一起坏掉。

### snapshot Command Division

3.5 引入独立的 `etcdutl` 做快照操作，但**并非整个 snapshot 子命令都迁走**：

| 子命令 | 3.7.4 归属 | 原因 |
| :--- | :--- | :--- |
| `snapshot save` | **仍在 `etcdctl`** | 需要活着的端点通过 gRPC 触发快照 |
| `snapshot restore` | 已迁到 `etcdutl` | 直接读写数据目录、须在 etcd 未运行时执行 |
| `snapshot status` | 已迁到 `etcdutl` | 只读快照文件校验，跟着 restore 一起 |

```shell
$ etcdctl snapshot save backup.db       # save 仍在 etcdctl
$ etcdutl --write-out=table snapshot status backup.db
$ etcdutl snapshot restore backup.db --data-dir /var/lib/etcd
```

`etcdutl` 还有 `migrate`、`hashkv`、离线 `defrag`（`etcdutl defrag --data-dir <path>`，用于 etcd 未运行时整理数据目录）。

> [!TIP]
> `snapshot status` 迁到 `etcdutl` 的收益：可在 restore 前先校验快照文件，避免拿损坏快照覆盖数据目录。

## Troubleshooting Quick Reference

| 现象 | 首要检查 | 处置方向 |
| :--- | :--- | :--- |
| 写入报 `database space exceeded` | `etcdctl alarm list` | compact → defrag → alarm disarm |
| watch 报 `has been compacted` | 压缩周期 vs watch 时长 | 调大 retention，重建 watch |
| `apply request took too long` | `backend_commit_duration` p99 + 日志 `prefix` | 独立磁盘 / 提 CPU / 减单请求 key 数 |
| leader 频繁切换 | WAL fsync、peer RTT | 先治磁盘网络，慎调超时 |
| `InsufficientMembers` | 存活成员数 | 已失去 quorum，紧急扩容或恢复 |
| `not enough started members` | 成员变更计划 | 串行增删，勿一次改多个 |
| `cluster ID mismatch` | 是否有残留进程 | 清理进程，peer 地址去重叠 |
| `data_corruption failed` | `/readyz?verbose` | 隔离成员，从快照恢复 |
| `permission denied` | 角色权限 / 认证态 | 见 [security](/docs/CS/Framework/etcd/security.md) 的 RBAC |
| `invalid auth token` | Token TTL 是否已过 | 重新 `Authenticate` |

## Pitfall List

> [!WARNING]
> 这一篇的坑集中在"搜不到"和"以为是 etcd 挂了"两类。

1. **`server/etcdserver/errors.go` 路径已失效** —— 3.7 是 `server/etcdserver/errors/errors.go`（独立子包），rpctypes 属独立 module。
2. **慢 apply 警告串是 `apply request took too long`** —— 不是 `apply entries took too long`，用旧串 grep 一条都搜不到。
3. **重配置错误串没有 `reconfig: cluster ` 前缀** —— 真实串是 `etcdserver: re-configuration failed due to not enough started members`。
4. **慢 apply 警告要看 `prefix` 字段** —— `read-only range` / `read-only txn` 超时说明瓶颈在读路径。
5. **`snapshot save` 还在 `etcdctl`** —— 只有 `restore` 与 `status` 迁到 `etcdutl`，别在备份脚本里写错工具名。
6. **收到 NOSPACE 报错不代表写被阻止** —— Apply 层只触发 alarm 不阻止事务，可能"报错但数据写进去了"。
7. **defrag 期间的报错形态取决于 feature gate** —— 默认 `StopGRPCServiceOnDefrag=false` 是阻塞超时，开启后是显式停 gRPC 服务（连接错误）。
8. **peer 层错误不带 `etcdserver:` 前缀** —— 如 `cluster ID mismatch` 出自 rafthttp，按前缀筛选会漏。
9. **别把 `etcdInsufficientMembers` 当预警** —— 触发时已失去 quorum、不能写，优先级最高。
10. **自动压缩触发时机与直觉不符** —— `revision` 模式每 5 分钟检查；`periodic` 模式首次压缩在满一个周期之后。
11. **`etcdctl auth enable` 不接受参数** —— 身份用全局 flag `--user` 传（见 [security](/docs/CS/Framework/etcd/security.md)）。

## Links

- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [monitoring](/docs/CS/Framework/etcd/monitoring.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [security](/docs/CS/Framework/etcd/security.md)
- [client](/docs/CS/Framework/etcd/client.md)

## References

1. [etcd v3.7.4 源码（server/etcdserver/errors/errors.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/errors/errors.go)
2. [etcd v3.7.4 源码（api/v3rpc/rpctypes/error.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/api/v3rpc/rpctypes/error.go)
3. [etcd v3.7.4 源码（server/etcdserver/txn/util.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/txn/util.go)
4. [etcd Documentation - FAQ](https://etcd.io/docs/v3.7/faq/)
5. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.7/op-guide/maintenance/)
