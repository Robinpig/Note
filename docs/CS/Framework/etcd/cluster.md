## Introduction

etcd 的运维面和它的数据面一样围绕 [Raft](/docs/CS/Framework/etcd/raft.md) 展开：谁有权提交写、谁能把数据落到磁盘、集群成员怎么增减，都由 Raft 日志与多数派（quorum）决定。

这一篇覆盖三块运维地基：**磁盘上的数据长什么样**、**成员怎么安全地增减**、**数据怎么备份与恢复**。三者都要求读者先理解 quorum 约束——etcd 所有写入都要等多数派确认，因此任何"改配置"的动作本质上都是一次提案，都受同样的可用性前提保护。

etcd 官方反复强调的一条硬约束贯穿全文：

> Reconfiguration requests can only be processed when a majority of cluster members are functioning. It is **highly recommended** to always have a cluster size greater than two in production.

两节点集群的多数派也是 2，摘掉一个就失去 quorum，且**没有第三份副本能容忍移除过程中的失败**，所以不安全。

## Version Baseline

| 项 | 值 |
| :--- | :--- |
| 源码基线 | **3.7.2** |
| Raft 依赖 | `go.etcd.io/raft/v3 v3.7.0` |
| Learner 支持 | v3.4 起；`--max-learners` 默认 **1**，可显式调整 |
| `/livez`、`/readyz` 健康端点 | v3.5.12 起 |
| Raft snapshot-count | **10000**（3.6 起从 100000 下调） |
| 默认配额 | 2 GiB；8 GiB 是**建议上限**，不是硬性配置上限 |

> [!WARNING]
> 3.6 起 `--enable-v2` 与 `experimental-enable-v2v3` 已被移除，v2 API 代码路径彻底下线。新部署不要依赖 v2 接口，迁移前先确认客户端（如老版本 Curator、Dubbo 的 ZooKeeper 抽象层）是否还在用 v2。

## On-disk layout

etcd 启动时把数据目录组织成 **Raft 元数据快照、可选的 v3 backend 快照、WAL 和当前 backend `db`**。以单节点默认布局为例：

```text
${data-dir}/
└── member/
    ├── snap/
    │   ├── 000000000000001f-0000000000c0433e.snap   # raft snapshot（term-index）
    │   ├── 000000000000001f-0000000000c1c9df.snap
    │   ├── 000000000000001f-0000000000c0433e.snap.db # 可选的 v3 backend 快照
    │   └── db                                        # 当前 v3 backend
    └── wal/
        ├── 0000000000000000-0000000000000000.wal     # WAL 段，默认每段 64 MiB
        └── 0000000000000000-0000000000000000.wal.lock
```

这些文件不是可以任意拼装的零件：

- **`.snap`** 保存 Raft 的 `term/index/confState` 等元数据，用于截断该 index 之前的 Raft 日志。v3 中它的 Data 仍是兼容 v2 的 membership 视图，**不能把 `.snap` 理解成完整 v3 KV 镜像**；完整 v3 状态在 backend `db` 及对应的 `.snap.db` 中。
- **`.wal`** 保存 Raft entries、HardState 与 snapshot record。`WAL.Save` 先编码写入，再根据 `raft.MustSync`、段切换与 `UnsafeNoFsync` 决定是否真正 `fdatasync`；因此“收到每个提案都先 fsync WAL 再返回”并不准确。`.wal.lock` 是 **WAL 的文件锁**，与 backend 的 bbolt 锁不是一回事。
- **`db`** 是当前 [boltdb](/docs/CS/Framework/etcd/boltdb.md) backend，保存 MVCC 历史、lease、auth、membership、cluster version、consistent index 等状态。[treeIndex](/docs/CS/Framework/etcd/treeIndex.md) 只是内存索引，重启时从 `db` 重建。

由此得到两条备份纪律：

> [!WARNING]
> **不要主动删除 `snap/db`，也不要只拷贝 `.snap`/`.wal`。** v3 的 Raft `.snap` 不包含完整 KV 状态。当前 backend 缺失时，bootstrap 只有在找到 index 高于 backend consistent index 的匹配 `.snap.db` 时才会用快照恢复；没有可用快照或水位不匹配就会失败。冷备份应使用 `etcdctl snapshot save`，或停服后完整备份 `member/`（包括 `snap/db`、`snap/*.snap.db`、`wal/`）。

> [!NOTE]
> **只热拷贝 `db` 也不能替代一致性备份。** bbolt 可能仍有未提交事务，而且文件本身不包含恢复所需的 Raft 身份、HardState 与 WAL snapshot record。`db` 里的 lease 并不会因为“没拷 WAL”而凭空消失；真正的问题是 MVCC 水位与 Raft 提交边界无法由单个热拷贝文件共同保证。

## Member management

成员变更走 Raft 提案，因此每一次 `member add/remove/update` 都会被写入日志并同步到全集群——这和"改本地配置文件"有本质区别，也正因如此，**改 peer URLs 必须在集群层面显式执行，而改 client URLs 只需重启**：

| 变更类型 | 是否需要 `member` 命令 | 原因 |
| :--- | :--- | :--- |
| `clientURLs` | 否 | 纯本地通告配置，不影响集群拓扑，重启即自我发布 |
| `peerURLs` | **是** | peer 地址是 Raft 拓扑的一部分，写错会直接破坏 quorum |
| 增删成员 | **是** | 改变 quorum 计算基数 |

查看当前成员：

```shell
$ etcdctl member list
6e3bd23ae5f1eae0: name=node2 peerURLs=http://localhost:23802 clientURLs=http://127.0.0.1:23792
924e2e83e93f2560: name=node3 peerURLs=http://localhost:23803 clientURLs=http://127.0.0.1:23793
a8266ecf031671f3: name=node1 peerURLs=http://localhost:23801 clientURLs=http://127.0.0.1:23791
```

更新 peer URL：

```shell
$ etcdctl member update a8266ecf031671f3 --peer-urls=http://10.0.1.10:2380
Updated member with ID a8266ecf031671f3 in cluster
```

移除成员：

```shell
$ etcdctl member remove a8266ecf031671f3
Removed member a8266ecf031671f3 from cluster
```

被移除的成员会自行退出：

```text
etcd: this member has been permanently removed from the cluster. Exiting.
```

> [!NOTE]
> 移除 leader 是**允许**的，但会有一段时间不可用，约为一个 election timeout 加上投票过程。所以生产环境更推荐先 `etcdctl move-leader` 把 leader 挪到别处，再摘除目标节点。

### Add as learner

直接从 v3.4 开始支持 learner（非投票成员），推荐的生产添加流程是**三步法**——先让新节点以 learner 身份追赶，追上后再提升为投票成员：

```shell
# 1. 以 learner 身份加入
$ etcdctl member add infra3 --peer-urls=http://10.0.1.13:2380 --learner
Member 9bf1b35fc7761a23 added to cluster a7ef944b95711739

ETCD_NAME="infra3"
ETCD_INITIAL_CLUSTER="infra0=http://10.0.1.10:2380,infra1=http://10.0.1.11:2380,infra2=http://10.0.1.12:2380,infra3=http://10.0.1.13:2380"
ETCD_INITIAL_CLUSTER_STATE=existing
```

```shell
# 2. 用上述环境变量启动新进程
$ export ETCD_NAME="infra3"
$ export ETCD_INITIAL_CLUSTER="infra0=http://10.0.1.10:2380,infra1=http://10.0.1.11:2380,infra2=http://10.0.1.12:2380,infra3=http://10.0.1.13:2380"
$ export ETCD_INITIAL_CLUSTER_STATE=existing
$ etcd --listen-client-urls http://10.0.1.13:2379 --advertise-client-urls http://10.0.1.13:2379 \
       --listen-peer-urls http://10.0.1.13:2380 --initial-advertise-peer-urls http://10.0.1.13:2380 \
       --data-dir %data_dir%
```

```shell
# 3. 追上日志后提升为投票成员
$ etcdctl member promote 9bf1b35fc7761a23
Member 9bf1b35fc7761a23 promoted in cluster a7ef944b95711739
```

learner 的价值在于它**不计入 quorum**。直接以投票成员身份加入时，新成员一旦配置错误（比如 peer URL 写错）就被计入多数派基数，可能直接把集群推进失去 quorum 的死局；learner 阶段它只接收数据、不参与投票，失败了直接摘掉重来，代价极低。

promote 不是无条件成功的，etcd 服务端会校验其运行安全性：

```shell
# 日志尚未追平
$ etcdctl member promote 9bf1b35fc7761a23
Error: etcdserver: can only promote a learner member which is in sync with leader

# 目标不是 learner
Error: etcdserver: can only promote a learner member

# 成员不存在
Error: etcdserver: member not found
```

> [!WARNING]
> v3.7.2 的 `--max-learners` **默认值是 1，但不是不可变上限**。该参数控制 membership 允许的 learner 数量，默认配置下确实一次只能有一个未提升的 learner：
> ```shell
> $ etcdctl member add infra4 --peer-urls=http://10.0.1.14:2380 --learner
> Error: etcdserver: too many learner members in cluster
> ```
> 如果显式调高 `--max-learners`，可以容纳多个 learner；但 bootstrap 与成员变更仍会按配置校验。没有明确的容量与网络规划时，仍应保持“加一个、追平、提升”的串行节奏。

### strict-reconfig-check

`--strict-reconfig-check` 控制 etcd 是否在重配置时做 quorum 校验。**默认开启**，行为是：如果这次重配置会导致"已启动成员数 < 新集群的多数派"，直接拒绝该提案。

这个校验专门防的是“一次加多个、其中一个没起来”这类事故——因为未启动的新成员仍被计入 quorum 基数。生产操作应把成员变更拆成**可验证的串行步骤**，每步确认新集群仍有 quorum、目标成员已健康，再继续下一步：

| 场景 | 操作序列 |
| :--- | :--- |
| 3 → 5 节点 | 两次 `member add`（不能一次加俩） |
| 5 → 3 节点 | 两次 `member remove` |
| 替换健康节点 | 先 `remove` 旧的，再 `add` 新的 |
| 滚动升级 | 一次只动一个成员，确认恢复再动下一个 |

### Common Startup Errors

这几类错误的共同根因都是 **peer URL 与集群记录不匹配**，排查时优先核对 `etcdctl member list` 的输出与启动参数：

```text
# 启动参数里的成员列表与实际集群成员数不等
etcdserver: assign ids error: the member count is unequal

# 加进来的地址和加入时用的地址不是同一个
etcdserver: assign ids error: unmatched member while checking PeerURLs

# 直接复用了已被移除成员的数据目录
etcd: this member has been permanently removed from the cluster. Exiting.
```

> [!NOTE]
> 第三条尤其容易踩：删掉节点后把它的 `data-dir` 拷到新机器再启动，etcd 一连上集群就会发现自己是已移除成员并退出。**替换已被移除的成员必须使用新的 `data-dir`**，数据通过 `member add` 后的正常同步获得；如果要做整集群灾难恢复，则走下面的 snapshot restore，生成新的集群身份。

## Backup & restore

### Snapshot Backup

etcd 的备份就是后端 `db` 文件的一致性快照，可以定期跑：

```shell
$ etcdctl snapshot save backup.db
$ etcdctl --write-out=table snapshot status backup.db
+----------+----------+------------+------------+
| HASH | REVISION | TOTAL KEYS | TOTAL SIZE |
+----------+----------+------------+------------+
| fe01cf57 | 10       | 7          | 2.1 MB     |
+----------+----------+------------+------------+
```

对每个成员单独做快照，拿到的是**该成员的完整状态**——注意这与 raft 快照不是一回事：raft 快照用于截断日志，而 `snapshot save` 是给运维用的离线备份。

### Restore from Snapshot

`etcdutl` 是 3.5 起从 etcd 二进制里拆出的独立工具（`make build` 产出 `etcd` / `etcdctl` / `etcdutl` 三个可执行文件），恢复动作由它完成：

```shell
$ etcdutl snapshot restore backup.db \
    --name infra0 \
    --initial-cluster infra0=http://10.0.1.10:2380,infra1=http://10.0.1.11:2380,infra2=http://10.0.1.12:2380 \
    --initial-advertise-peer-urls http://10.0.1.10:2380 \
    --data-dir /var/lib/etcd
```

恢复之所以必须走 `etcdutl` 而不是直接启动 etcd，是因为它要重写一份**全新的集群身份**：

- **cluster ID 与 member ID 重新生成**。恢复出来的集群不能与仍存活的旧集群同时写入，否则会出现两套独立历史。
- **`--initial-cluster` 定义恢复后的初始成员集**。所有恢复成员必须使用完全相同的字符串，但各自的 `--name`、`--initial-advertise-peer-urls` 与 `--data-dir` 不同。
- **`--bump-revision` 维护客户端看到的 revision 单调性**。它让恢复后的 revision 高于旧值，避免仍持有旧 revision 的客户端把新数据误判为回退；它不是为了解决两个 Raft 集群之间的 ID 冲突。Kubernetes 恢复通常还会使用 `--mark-compacted`，让旧 informer 的缓存失效。

多节点恢复的标准顺序是：**停掉并隔离旧集群 → 对每个成员分别 restore 到全新目录 → 所有成员使用同一 `--initial-cluster` 启动 → 验证 quorum 后恢复流量**。这些成员在 restore 时就已经写入初始 membership，启动后直接组成新集群，**不需要再逐个 `member add`**；后续扩容才走运行时重配置。

## Disaster recovery

按故障范围，官方把恢复场景分成两类，处置思路完全不同。

### Minority Members Failure

单节点故障等价于"替换一台坏机器"，走 [成员变更](#add-as-learner) 的常规流程：先 `member remove` 掉坏的，再 `member add` 新节点。

> [!WARNING]
> **已经故障但还没被 remove 的成员会继续影响 quorum**。它虽然不可用，却仍被算在多数派基数里，从而降低集群对"再挂一个"的容忍度。所以故障节点要尽快摘除，不要让它挂着占席位。

### Majority Members Failure

多数派丢失、所有节点 IP 都变化，或数据目录已无法形成 quorum 时，优先用一致性快照恢复出一个**新集群**：

1. **停止并隔离所有旧进程与旧客户端写入路径**，防止恢复期间出现分裂脑。
2. **用同一份有效快照为每个成员执行 `etcdutl snapshot restore`**，写入各自的新目录；所有成员的 `--initial-cluster` 必须一致。
3. **用恢复时的新 `--initial-cluster` 启动全部目标成员**，先形成新集群的 quorum，再验证 key、revision、lease 与 endpoint 健康。
4. 对仍持有旧 revision 的客户端使用 `--bump-revision`；Kubernetes 场景按官方恢复指南同时使用 `--mark-compacted`。

`--force-new-cluster` 是另一种**最后手段**，不是 snapshot restore 后的第二步。它用于尝试复用某个成员现有的数据目录与 WAL 恢复旧集群身份：bootstrap 会把 HardState.Commit 提升到 `max(WAL Commit, backend consistent index)`，丢弃未提交尾部，并强制提交配置变更 entries。它可能造成数据取舍，且旧成员仍在线时可能 panic，因此官方强烈不建议将其作为常规备份方案。只有确认所有旧成员都已隔离、且没有可用快照时，才考虑使用；恢复出一个成员后，再通过运行时重配置补回其他成员。

> [!WARNING]
> `restore` 出来的集群是**一个新的集群**（新 cluster ID），它与旧集群没有任何 Raft 关联。如果旧集群里还有存活节点，必须先把它们停掉——两个集群同时对外服务会写出两套互不相同的数据，这就是分裂脑。

## Links

- [Core_Mechanisms（WAL、snapshot 与 consistent index 的恢复边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [compact（MVCC 历史压缩）](/docs/CS/Framework/etcd/compact.md)
- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [naming（成员/实例 endpoints 的服务发现）](/docs/CS/Framework/etcd/naming.md)
- [gateway（grpc-proxy：水平扩展 / watch-lease 合并）](/docs/CS/Framework/etcd/gateway.md)

## References

1. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.7/op-guide/runtime-configuration/)
2. [etcd Documentation - Disaster recovery](https://etcd.io/docs/v3.7/op-guide/recovery/)
3. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.7/op-guide/maintenance/)
4. [etcd v3.7.2 - WAL implementation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/wal/wal.go)
5. [etcd v3.7.2 - Raft snapshotter](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/snap/snapshotter.go)
6. [etcd v3.7.2 - Backend snapshot database](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/snap/db.go)
7. [etcd v3.7.2 - Bootstrap recovery](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/bootstrap.go)
8. [etcd v3.7.2 - Membership learner validation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/membership/cluster.go)
9. [etcd v3.7.2 - Snapshot restore](https://github.com/etcd-io/etcd/blob/v3.7.2/etcdutl/snapshot/v3_snapshot.go)
