## Introduction

etcd 的报错分两层：一组**哨兵 error 变量**，以及把它们包装成 gRPC `status` 的 `ErrGRPC*` 变量。客户端看到的字符串一律来自后者，形如 `rpc error: code = 8 desc = etcdserver: mvcc: database space exceeded`。

这两层在 3.7 里**分处两个不同的路径**，且第二个是独立 module：

| 层 | 3.7.2 路径 | 定义的变量 |
| :--- | :--- | :--- |
| 服务端哨兵 error | `server/etcdserver/errors/errors.go` | `ErrNoSpace`、`ErrCorrupt`、`ErrLeaderChanged`… |
| gRPC 包装 | `api/v3rpc/rpctypes/error.go` | `ErrGRPCNoSpace`、`ErrGRPCCompacted`… |

> [!WARNING]
> `server/etcdserver/errors.go` 这个路径在 3.7 **已经失效**——文件被移进了 `errors/` 子包，成为独立子包 `errors`。照旧路径去 GitHub 上搜索会 404，或翻到一个历史版本的文件误以为当前如此。另外注意 `api/v3rpc/rpctypes/` 属于**独立 module `go.etcd.io/etcd/api/v3`**，不在 `server/` 下。

每个哨兵错误由三部分构成：变量名、**标准 gRPC code**、以 `etcdserver:` 开头的描述串。描述串前缀按子领域细分（`etcdserver: mvcc:` 表示 MVCC 层），这些字符串同时充当跨进程的"错误 ID"，**必须保持稳定唯一**。

由于 gRPC code 是标准枚举，客户端可以按 code 而非字符串做判断：

| gRPC code | 数值 | etcd 典型场景 |
| :--- | :--- | :--- |
| `InvalidArgument` | 3 | 参数非法、auth 失败、请求过大 |
| `NotFound` | 5 | key / member / lease 不存在 |
| `AlreadyExists` | 6 | 节点已存在（少见） |
| `FailedPrecondition` | 9 | learner 未追平、quorum 不足、auth 未启用 |
| `OutOfRange` | 11 | **revision 已被 compact**、revision 超前 |
| `ResourceExhausted` | 8 | **database space exceeded**、请求过多 |
| `Unavailable` | 14 | 连接不可用、正在选主 |
| `Unauthenticated` | 16 | token 无效或过期 |
| `Internal` | 13 | 状态机异常（`ErrCorrupt` 走这里） |
| `DeadlineExceeded` | 4 | 超时（多与磁盘慢相关） |

关键映射（客户端重试逻辑应该建立在这张表上）：

- `OutOfRange` + `mvcc: required revision has been compacted` → **不可重试**，必须重新 LIST
- `ResourceExhausted` + `mvcc: database space exceeded` → **不可重试**，必须先腾空间
- `Unavailable` → 可重试（重试需配合退避，否则会加剧选举）
- `DeadlineExceeded` → 谨慎重试，可能是磁盘问题导致，盲目重试会加剧压力

> [!TIP]
> `ResourceExhausted`（8）和 `Unavailable`（14）都是 gRPC 官方的**可重试 code**，但 etcd 的 `database space exceeded` 恰好也用了 8。这是"gRPC 重试语义"与"业务语义"错配最明显的一处——**按 gRPC 标准自动重试会陷入死循环**。这也是 [client](/docs/CS/Framework/etcd/client.md) 必须显式处理 NOSPACE 的原因。

> [!NOTE]
> **版本基线**：etcd **3.7.2**（`api/version/version.go` → `Version = "3.7.2"`）。本文所有错误字符串、文件路径、命令与阈值均以 3.7.2 源码为准。命令层面 3.7 与旧版基本兼容（这是本系列里命令最稳的一篇），但**错误信息串在版本演进中改过写法**，用旧字符串去 grep 日志会漏——具体见下文各节的"实际字符串"标注。

## NOSPACE

这是最常见的生产故障。etcd 的 MVCC 保留完整 keyspace 历史（见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)），不定期 [compact](/docs/CS/Framework/etcd/compact.md) 就会耗尽空间；空间低于配额时 etcd 触发 cluster-wide alarm 进入维护模式，**只接受读和删除，拒绝所有写**。

> [!WARNING]
> NOSPACE 是 **cluster-wide** 的：任意一个成员触发，全集群拒绝写入。所以处理时必须对所有成员分别操作，不能只修一台。

### Positioning

```shell
$ etcdctl --write-out=table endpoint status
+----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------------------------------+
| ENDPOINT       | ID               | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS                         |
+----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------------------------------+
| 127.0.0.1:2379 | 8e9e05c52164694d | 3.7.2   | 25 kB   | true      | false      | 2         | 5          | 5                  | memberID:10276657743932975437 |
|                |                  |         |         |           |            |           |            |                    | alarm:NOSPACE                  |
+----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------------------------------+

$ etcdctl endpoint health -w table
+----------------+--------+------------+---------------------------+
| ENDPOINT       | HEALTH | TOOK       | ERROR                     |
+----------------+--------+------------+---------------------------+
| 127.0.0.1:2379 | false  | 1.850456ms | Active Alarm(s): NOSPACE |
+----------------+--------+------------+---------------------------+
```

也可以直接看文件大小，或用 alarm 命令：

```shell
$ ls -lrt /path-to-data-dir/member/snap
-rw-r--r-- 1 vcap vcap     13503 Nov 15 00:48 000000000000001f-0000000000c0433e.snap
-rw------- 1 vcap vcap   5148672 Nov 17 02:44 db          # 只有 db 持续增长

$ etcdctl alarm list
memberID:13803658152347727308 alarm:NOSPACE
```

> [!NOTE]
> 观察 `member/snap` 目录的 `ls -lrt` 输出有个实用技巧：**`.snap` 文件大小基本不变、只有 `db` 在长**，说明增长完全来自新数据而非快照累积，这决定了该 compact 而不是排查快照机制。

### Actual Error String

三个字符串对应三层，排查时要知道自己看到的是哪一层：

| 你看到的 | 出处 | gRPC code |
| :--- | :--- | :--- |
| `etcdserver: mvcc: database space exceeded` | `api/v3rpc/rpctypes/error.go:34`（`ErrGRPCNoSpace`） | 8 `ResourceExhausted` |
| `etcdserver: no space` | `server/etcdserver/errors/errors.go:38`（`ErrNoSpace`，哨兵） | — |
| `Active Alarm(s): NOSPACE` | `etcdctl endpoint health` 自行拼装 | — |

> [!NOTE]
> NOSPACE 有一个反直觉的边界：**收到 `ErrGRPCNoSpace` 不代表写操作没生效**。配额检查发生在 API 层与内部 Apply 层两处，Apply 层只会**触发 NOSPACE alarm 而不阻止事务继续执行**。所以可能出现"客户端收到报错、但数据其实写进去了"。把 `etcdctl compact` 的目标 revision 取错（取了 alarm 之后的 revision）会连带把这次写入一起 compact 掉——这也是官方文档单独强调这一点的原因。

### Four-Step Remediation

```shell
# 1. 取当前 revision
$ rev=$(etcdctl --endpoints=:2379 endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9]*')

# 2. 压缩掉旧 revision
$ etcdctl compact $rev
compacted revision 1516

# 3. 碎片整理（阻塞操作，3 节点要逐台跑）
$ etcdctl defrag
Finished defragmenting etcd member[127.0.0.1:2379]

# 4. 解除告警
$ etcdctl alarm disarm
memberID:13803658152347727308 alarm:NOSPACE
```

> [!WARNING]
> `defrag` 会**独占锁并阻塞该节点的所有请求**（官方 FAQ 明确说明：节点 defrag 期间不响应请求）。三节点集群要逐台执行，且这一步不能省——compact 只清 MVCC 索引，磁盘占用要靠 defrag 归还。
>
> 3.7 有个 alpha 级 feature gate `StopGRPCServiceOnDefrag`（默认 **false**）与这个行为直接相关：开启后 defrag 期间会**显式停止 gRPC 服务**。也就是说关着它时是"请求被阻塞住"，开着它时是"请求直接被拒"——排障时若发现 defrag 期间收到的是连接错误而非超时，先确认这个 gate 的状态。

长期方案是配置自动压缩，避免人工介入：

```shell
--auto-compaction-mode=periodic --auto-compaction-retention=1h
# 或
--auto-compaction-mode=revision --auto-compaction-retention=1000    # 保留最近 1000 个 revision
```

> [!TIP]
> `--auto-compaction-mode=revision` 是**按数量**保留，检查周期固定为 5 分钟（`server/etcdserver/api/v3compactor/revision.go:62` 的 `revInterval`），每次压缩到 `最新 revision - 1000`。**不是**到达阈值立刻压缩——两次实际压缩之间至少隔 5 分钟。
>
> `periodic` 则是按时间窗口，行为更微妙：源码注释（`v3compactor/periodic.go:65-73`）说明它把窗口切成 10 份、每份记一个 revision，**满一个完整周期后才执行第一次压缩**，之后按 1/10 周期滑动。因此设了 `--auto-compaction-retention=10h` 不是"10 小时才动一次"，而是"第一次压缩发生在 10 小时后，此后每 1 小时一次"。排查"压缩频率与预期不符"时这条最容易被误判。

同时用 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 里的 `etcdExcessiveDatabaseGrowth`（线性外推 4 小时超配额）做提前预警。

## Slow apply

官方给出的判据很具体：**平均 apply 耗时超过 100ms 就会打 `apply request took too long` 警告**（阈值常量 `DefaultWarningApplyDuration = 100 * time.Millisecond`，`server/embed/config.go:65`）。正常情况下即使是慢机械盘或云盘（EBS、PD），单次 apply 也不应超过 50ms。

> [!WARNING]
> **实际字符串是 `apply request took too long`，不是 `apply entries took too long`。** 旧资料里流传的是后者，源码里已无此串——`server/etcdserver/txn/util.go:94` 的字面量就是 `apply request took too long`。用错字符串去 grep 日志会**一条都搜不到**，从而误判"没有触发该警告"。这条警告是判断 apply 是否变慢的第一手证据，搜不到就等于失去了最直接的线索。

```go
// 位置：server/etcdserver/txn/util.go:92-94
func warnOfExpensiveGenericRequest(lg *zap.Logger, warningApplyDuration time.Duration, now time.Time, reqStringer fmt.Stringer, prefix string, resp string, err error) {
	lg.Warn(
		"apply request took too long",
```

同一条警告会被三类请求共用，靠 `prefix` 字段区分——`""`（普通请求，`util.go:37`）、`"read-only txn "`（只读事务，`:77`）、`"read-only range "`（只读区间查询，`:88`）。**排查时务必看 prefix 字段**：如果是 `read-only range` 超时，那瓶颈在读路径而不是写入路径，方向完全不同。

阈值可由 `--warning-apply-duration` 调整。

### Root Cause 1: Slow Disk (Most Common)

```shell
# 看 p99，应该 < 25ms
$ curl -L http://localhost:2379/metrics | grep backend_commit_duration
```

若 p99 明显超过 25ms，就是磁盘的问题。解法是给 etcd 分配独立磁盘或换更快的盘。

### Root Cause 2: CPU Starvation

第二常见。监控机器 CPU 使用率，若长期打满，说明算力不足。手段：迁移到独立机器、提高 cgroup 资源隔离优先级、用 `renice` 提升 etcd 进程优先级。

### Root Cause 3: Too Many Keys per Request

"取走整个 keyspace"这类请求会让 apply 变慢。官方给的经验数字是**单请求访问的 key 数控制在几百以内就一定没问题**。

> [!TIP]
> 这个结论反过来给了容量规划依据：etcd 适合"读多写少、访问局部"的工作负载，**不适合当分析型数据库用**。海量数据应该写进对象存储或时序库，etcd 只存指针和元信息。

## Leader Frequent Election

官方告警阈值是 **15 分钟内 leader 切换 >= 4 次**（`etcdHighNumberOfLeaderChanges`，持续 5m 告警）。频繁选举通常意味着：资源不足、网络延迟高，或被其他组件反复干扰。

对应的 Raft 机制在 [raft.md](/docs/CS/Framework/etcd/raft.md) 的选举章节有展开，这里只列排查顺序：

1. 查 `etcd_disk_wal_fsync_duration_seconds`（p99 > 0.5s）→ 磁盘 fsync 慢
2. 查 `etcd_network_peer_round_trip_time_seconds`（p99 > 0.15s）→ 网络抖动
3. 查成员数与分布 → 跨机房/跨可用区部署会让心跳往返时间天然偏大

> [!WARNING]
> 调整 `--heartbeat-interval` / `--election-timeout`（默认 100ms / 1000ms）是**最后手段**。把它们调大虽然能减少误选举，但同时也拉长了真正故障时的恢复时间——etcd 的默认值本就是 1:10 的宽松比例。正确做法是先解决磁盘与网络。

## Compaction and Watch Invalidation

### mvcc: required revision has been compacted

这个错误在 Kubernetes 场景中极为常见（kube-apiserver 日志里成片出现）。实际字符串分两层，均已核对一致：

- 哨兵：`mvcc: required revision has been compacted`（`server/storage/mvcc/kvstore.go:38` 的 `ErrCompacted`）
- gRPC：`etcdserver: mvcc: required revision has been compacted`（`api/v3rpc/rpctypes/error.go:32`，`codes.OutOfRange`）

含义是客户端 watch 或读的 revision 已被 compact 永久删除。根因通常是 **watch 存活时间超过了压缩周期**。

处置有两种方向：

```shell
# 方案 A：客户端从当前 revision 重新建立 watch
$ etcdctl endpoint status -w json | jq '.[].Status.header.revision'
$ etcdctl compact <rev>
$ etcdctl defrag      # 阻塞操作，3 节点逐台执行

# 方案 B：重启卡住的客户端 Pod
$ kubectl get pods -A --no-headers -o custom-columns=":metadata.namespace,:metadata.name" \
    | xargs -n2 sh -c 'kubectl logs -n $0 $1 --tail=100 2>/dev/null | grep -i "compacted" && echo "Found in: $0/$1"'
$ kubectl delete pod -n <namespace> <pod>
```

删 Pod 后，apiserver 会清掉本地缓存的旧 `resourceVersion`，重新 LIST 拿到最新 revision 并重建 WATCH。

> [!TIP]
> **根因在 compact 策略而非 etcd 本身**。只要 watch 的最长持有期 <= 压缩保留期，这个错误就不会出现。设置压缩周期时务必保证 `auto-compaction-retention` 大于任何客户端可能的最长 watch 时长。

## cluster ID mismatch

```
request ignored (cluster ID mismatch)
```

每个新集群都会根据初始集群配置和一个**用户提供的唯一 `initial-cluster-token`** 生成新的 cluster ID。不同集群 ID 之间的请求会被直接忽略并打这条警告（哨兵在 `server/etcdserver/api/rafthttp/http.go:65`，注意它**不带** `etcdserver:` 前缀，因为是 peer 层错误而非 server 层）。

典型场景是：拆掉旧集群后复用了相同的 peer 地址，如果有旧 etcd 进程还在运行，它会不断联系新集群。

解法是保证不同集群的 peer 地址**互不重叠**，并清理残留进程。

## Reconfiguration Rejected

```text
etcdserver: re-configuration failed due to not enough started members
```

> [!WARNING]
> **实际字符串没有 `reconfig: cluster ` 前缀。** 旧资料里写的是 `etcdserver: reconfig: cluster re-configuration failed due to not enough started members`，3.7.2 源码里不存在这个前缀。真实字面量在 `server/etcdserver/errors/errors.go:33`（`ErrNotEnoughStartedMembers`），gRPC 包装在 `api/v3rpc/rpctypes/error.go:44`（`codes.FailedPrecondition`），两处都不带该前缀。

这是 quorum 保护在起作用，详见 [cluster.md](/docs/CS/Framework/etcd/cluster.md) 的 `strict-reconfig-check` 章节（3.7 中**默认开启**）。etcd 会拒绝那些会导致"已启动成员 < 新多数派"的重配置提案。

> [!NOTE]
> `EtcdServer` 侧还有几条相邻的成员错误，排查时容易互相混淆：`can only promote a learner member which is in sync with leader`（promote 时 learner 未追平）、`too many learner members in cluster`（3.4 起限制单集群最多 1 个 learner）、`member ID already exist`。它们的共同点是**都拒绝改变成员构成的提案**，区别在于拒绝的具体原因。

## Data corruption

etcd 内置了数据损坏检查（`/readyz?verbose` 中的 `data_corruption` 项），确认方式：

```bash
curl -k http://localhost:2379/readyz?verbose
# 若输出 data_corruption failed，即确认 boltdb 已损坏
```

损坏后的恢复路径：

1. 隔离故障成员，从健康成员取最新快照
2. 用 `etcdutl snapshot restore` 重建（见 [cluster.md](/docs/CS/Framework/etcd/cluster.md) 的备份恢复章节）
3. 重新以 learner 身份加入集群

> [!WARNING]
> 如果**多数成员同时损坏**（例如所有节点共用一块存储、同时断电），就没有健康快照可依，只能靠 `db` 文件尽力恢复，且必须接受**丢失最后一次快照之后的数据**。这就是为什么定期 `etcdctl snapshot save` 到集群外的存储是硬要求——快照存在集群内部时，它和被保护的数据库一起坏掉。

### snapshot Command Division: etcdctl and etcdutl

3.5 引入了独立的 `etcdutl` 工具做快照相关操作，但**并非整个 snapshot 子命令都迁走了**。这是最容易误解的一点：

| 子命令 | 3.7.2 归属 | 源码依据 |
| :--- | :--- | :--- |
| `snapshot save` | **仍在 `etcdctl`** | `etcdctl/ctlv3/command/snapshot_command.go:57` 只挂 `NewSnapshotSaveCommand()` |
| `snapshot restore` | 已迁到 `etcdutl` | `etcdutl/etcdutl/snapshot_command.go:53` |
| `snapshot status` | 已迁到 `etcdutl` | `etcdutl/etcdutl/snapshot_command.go:54` |

也就是说切分是按"是否需要接触数据目录"划的：

- **`save` 需要一个活着的 etcd 端点**（要通过 gRPC 触发快照），所以留在客户端工具 `etcdctl`；
- **`restore` 要直接读写数据目录、且必须在 etcd 未运行时执行**，属于服务端离线操作，交给独立的 `etcdutl`；
- **`status` 只读一个快照文件**做校验，跟着 `restore` 一起搬了过去。

```shell
# save 仍在 etcdctl
$ etcdctl snapshot save backup.db

# status 与 restore 在 etcdutl
$ etcdutl --write-out=table snapshot status backup.db
+----------+----------+------------+------------+
|   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
+----------+----------+------------+------------+
| fe01cf57 |       10 |          7 | 2.1 MB     |
+----------+----------+------------+------------+

$ etcdutl snapshot restore backup.db --data-dir /var/lib/etcd
```

`etcdutl` 的其它子命令还有 `migrate`、`hashkv`、以及**离线 `defrag`**（`etcdutl defrag --data-dir <path>`，用于 etcd 未运行时直接整理数据目录）。

> [!TIP]
> `snapshot status` 迁到 `etcdutl` 后带来一个实际收益：**可以在 restore 之前先校验快照文件**。用 `etcdctl snapshot status` 确认 hash / revision 正常再执行 restore，能避免拿一个损坏的快照去覆盖数据目录。

## Troubleshooting Quick Reference Table

| 现象 | 首要检查 | 处置方向 |
| :--- | :--- | :--- |
| 写入报 `database space exceeded` | `etcdctl alarm list` | compact -> defrag -> alarm disarm |
| watch 报 `has been compacted` | 压缩周期 vs watch 时长 | 调大 retention，重建 watch |
| `apply request took too long` | `backend_commit_duration` p99 + 日志的 `prefix` 字段 | 独立磁盘 / 提升 CPU / 减少单请求 key 数 |
| leader 频繁切换 | WAL fsync、peer RTT | 先治磁盘网络，慎调超时 |
| `InsufficientMembers` | 存活成员数 | 已失去 quorum，紧急扩容或恢复 |
| `not enough started members` | 成员变更计划 | 串行增删，勿一次改多个 |
| `cluster ID mismatch` | 是否有残留进程 | 清理进程，peer 地址去重叠 |
| `data_corruption failed` | `/readyz?verbose` | 隔离成员，从快照恢复 |
| `permission denied` | 角色权限 / 认证态 | 见 [security](/docs/CS/Framework/etcd/security.md) 的 RBAC 章节 |
| `revision of auth store is old` | 是否刚改过权限 | 重新认证拿新 Token，非 etcd 故障 |
| `invalid auth token` | Token TTL 是否已过 | 重新 `Authenticate` |

## Pitfall List

> [!WARNING]
> 这一篇的坑集中在**"搜不到"和"以为是 etcd 挂了"两类**：

1. **`server/etcdserver/errors.go` 路径已失效** —— 3.7 里是 `server/etcdserver/errors/errors.go`（独立子包）。`api/v3rpc/rpctypes/error.go` 也没变，但它属于独立 module `go.etcd.io/etcd/api/v3`，不在 `server/` 下。
2. **慢 apply 的警告串是 `apply request took too long`** —— 不是 `apply entries took too long`。用旧串 grep 日志一条都搜不到，会误判"没触发警告"。
3. **重配置错误的串没有 `reconfig: cluster ` 前缀** —— 真实串是 `etcdserver: re-configuration failed due to not enough started members`（`server/etcdserver/errors/errors.go:33`）。
4. **慢 apply 警告要看 `prefix` 字段** —— `read-only range` / `read-only txn` 超时说明瓶颈在读路径，不是写入路径。
5. **`snapshot save` 还在 `etcdctl`，没迁到 `etcdutl`** —— 只有 `restore` 与 `status` 迁了。误以为整个子命令都迁走，会在备份脚本里写错工具名。
6. **收到 NOSPACE 报错不代表写操作被阻止** —— Apply 层只触发 alarm、不阻止事务执行，可能"报了错但数据写进去了"。取 compact 目标 revision 时要考虑这点。
7. **defrag 期间的报错形态取决于 feature gate** —— 默认（`StopGRPCServiceOnDefrag=false`）是阻塞超时；开启后是显式停止 gRPC 服务，表现为连接错误。
8. **`peer` 层错误不带 `etcdserver:` 前缀** —— 例如 `cluster ID mismatch` 出自 rafthttp 包，不在 `server/etcdserver/errors/` 里。按前缀筛选错误会漏掉这类。
9. **别把 `etcdInsufficientMembers` 当预警** —— 它触发时集群**已经**失去 quorum、不能写了，处置优先级最高。
10. **`etcdctl compact` 的 revision 别取太新** —— 取到 alarm 之后的 revision 可能把"报错但其实已写入"的数据一起 compact 掉。
11. **自动压缩的实际触发时机与直觉不符** —— `revision` 模式每 5 分钟检查一次；`periodic` 模式把窗口切成 10 份，**首次压缩发生在满一个周期之后**。设 `10h` 不是"10 小时才动一次"。
12. **`etcdctl auth enable` 不接受参数** —— 身份要用全局 flag `--user` 传，写成子命令参数会报错（详见 [security](/docs/CS/Framework/etcd/security.md)）。

## Links

- [cluster（集群运维与备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [monitoring（监控与指标阈值）](/docs/CS/Framework/etcd/monitoring.md)
- [compact（历史版本压缩）](/docs/CS/Framework/etcd/compact.md)
- [MVCC（多版本并发控制）](/docs/CS/Framework/etcd/MVCC.md)
- [security（鉴权与权限相关报错）](/docs/CS/Framework/etcd/security.md)
- [client（客户端库与重试语义）](/docs/CS/Framework/etcd/client.md)

## References

1. [etcd Documentation - FAQ](https://etcd.io/docs/v3.7/faq/)
2. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.7/op-guide/maintenance/)
3. [etcd Documentation - Monitoring](https://etcd.io/docs/v3.7/op-guide/monitoring/)
4. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.7/op-guide/runtime-configuration/)
5. [etcd server/etcdserver/errors/errors.go（v3.7.2 哨兵错误）](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/errors/errors.go)
6. [etcd api/v3rpc/rpctypes/error.go（gRPC 包装）](https://github.com/etcd-io/etcd/blob/v3.7.2/api/v3rpc/rpctypes/error.go)
7. [How to debug large db size issue?](https://etcd.io/blog/2023/how_to_debug_large_db_size_issue/)
