## Introduction

etcd 的运维面和它的数据面一样围绕 [Raft](/docs/CS/Framework/etcd/raft.md) 展开：谁有权提交写、谁能把数据落到磁盘、集群成员怎么增减，都由 Raft 日志与多数派（quorum）决定。

这一篇覆盖三块运维地基：**磁盘上的数据长什么样**、**成员怎么安全地增减**、**数据怎么备份与恢复**。三者都要求读者先理解 quorum 约束——etcd 所有写入都要等多数派确认，因此任何"改配置"的动作本质上都是一次提案，都受同样的可用性前提保护。

etcd 官方反复强调的一条硬约束贯穿全文：

> Reconfiguration requests can only be processed when a majority of cluster members are functioning. It is **highly recommended** to always have a cluster size greater than two in production.

两节点集群的多数派也是 2，摘掉一个就失去 quorum，且**没有第三份副本能容忍移除过程中的失败**，所以不安全。

## 版本基线

| 项 | 值 |
| :--- | :--- |
| 最新稳定版 | **3.7.2** |
| 维护分支 | 3.6.15 / 3.5.34（三条线并行维护） |
| 建议生产版本 | 3.5.x（Kubernetes 长期支持版本，生态兼容面最广） |
| Learner 支持 | v3.4 起 |
| `/livez`、`/readyz` 健康端点 | v3.5.12 起 |
| 默认配额 | 2 GB，**建议上限 8 GB** |

> [!WARNING]
> 3.6 起 `--enable-v2` 与 `experimental-enable-v2v3` 已被移除，v2 API 代码路径彻底下线。新部署不要依赖 v2 接口，迁移前先确认客户端（如老版本 Curator、Dubbo 的 ZooKeeper 抽象层）是否还在用 v2。

## On-disk layout

etcd 启动时把数据目录整理成"一份快照 + 一段日志 + 一个索引"的组合。以单节点默认布局为例：

```
${data-dir}/
└── member/
    ├── snap/
    │   ├── 000000000000001f-0000000000c0433e.snap   # raft 快照（term.index 命名）
    │   ├── 000000000000001f-0000000000c1c9df.snap
    │   └── db                                        # boltdb 后端，承载全部 key-value
    └── wal/
        ├── 0000000000000000-0000000000000000.wal     # WAL 段，每段 64MiB
        └── 0000000000000000-0000000000000000.wal.lock
```

三类文件的分工对应 Raft 的持久化要求：

- **`.snap`** 是 Raft 快照，按 `term-index` 命名。它把该 index 之前的整条日志压缩成一份状态机镜像，作用是**截断日志**——否则日志会无限增长。快照之后的新写入继续追加到 WAL。
- **`.wal`** 是预写日志（Write-Ahead Log）。每次 Raft 收到提案先落 WAL 再返回，崩溃重启后靠回放 WAL 重建未落盘的条目。段文件按固定大小滚动，`.wal.lock` 是 bbolt 对 `db` 的文件锁。
- **`db`** 就是 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 后端，key-value、lease、member、cluster、auth 等**全部**数据都在这里（[treeIndex](/docs/CS/Framework/etcd/treeIndex.md) 只在内存中存 key→revision 索引，重启后由 `db` 回放重建）。

这个布局直接推导出两条运维结论：

> [!TIP]
> **`db` 文件删除不会丢数据。** 有了 `.snap` + `.wal`，etcd 能重建全部状态。因此换机迁移时可以直接拷 `.snap`/`.wal` 而不必拷 `db`（`db` 通常是几个 G，`.snap`+`.wal` 往往小得多）——反之只拷 `db` 则会丢失未压缩的历史版本与 lease 状态。

> [!NOTE]
> 反过来，**`.snap`/`.wal` 删掉但保留 `db` 会有风险**：`db` 里的 MVCC 历史版本能让 etcd 提供旧版本读，但 Raft 层面的提交索引会退回到快照记录的位置，等于放弃了这段时间的写历史。官方推荐的无损做法是 `etcdutl snapshot restore`，而不是手工拼文件。

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
Member 9e29bbaa45d74461 promoted in cluster a7ef944b95711739
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
> **一个集群最多只能有 1 个 learner**（v3.4 起的设计约束，官方理由是限制 leader 向 learner 传播数据带来的额外负载）：
> ```shell
> $ etcdctl member add infra4 --peer-urls=http://10.0.1.14:2380 --learner
> Error: etcdserver: too many learner members in cluster
> ```
> 这意味着 learner 扩容是**串行**的，一次只能加一个、追平、提升，再加下一个。

### strict-reconfig-check

`--strict-reconfig-check` 控制 etcd 是否在重配置时做 quorum 校验。**默认开启**，行为是：如果这次重配置会导致"已启动成员数 < 新集群的多数派"，直接拒绝该提案。

这个校验专门防的是"一次加多个、其中一个没起来"这类事故——因为未启动的新成员仍被计入 quorum 基数。这个约束反过来要求所有变更**必须串行**：

| 场景 | 操作序列 |
| :--- | :--- |
| 3 → 5 节点 | 两次 `member add`（不能一次加俩） |
| 5 → 3 节点 | 两次 `member remove` |
| 替换健康节点 | 先 `remove` 旧的，再 `add` 新的 |
| 滚动升级 | 一次只动一个成员，确认恢复再动下一个 |

### 常见启动报错

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
> 第三条尤其容易踩：删掉节点后把它的 `data-dir` 拷到新机器再启动，etcd 一连上集群就自杀。**换机必须换新的 `data-dir`**，数据要靠 `member add` + 重新同步（或迁移 `.snap`/`.wal`）送过去。

## Backup & restore

### 快照备份

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

### 从快照恢复

`etcdutl` 是 3.5 起从 etcd 二进制里拆出的独立工具（`make build` 产出 `etcd` / `etcdctl` / `etcdutl` 三个可执行文件），恢复动作由它完成：

```shell
$ etcdutl snapshot restore backup.db \
    --name infra0 \
    --initial-cluster infra0=http://10.0.1.10:2380,infra1=http://10.0.1.11:2380,infra2=http://10.0.1.12:2380 \
    --initial-advertise-peer-urls http://10.0.1.10:2380 \
    --data-dir /var/lib/etcd
```

恢复之所以必须走 `etcdutl` 而不是直接启动 etcd，是因为它要重写一份**全新的集群身份**：

- **cluster ID 与 member ID 重新生成**。旧集群的 member ID 仍被其他成员持有，若沿用会导致同一集群出现重复 member，进而破坏 Raft 的投票唯一性。
- **`--initial-cluster` 必填且必须与后续扩容计划一致**，它写死在恢复出的数据里。
- **`--bump-revision` 会把 revision 往上推**，用于避免恢复后的集群与仍存活的旧集群产生 revision 冲突（分裂脑场景下必须加）。

多节点恢复的标准顺序是：**对每个成员各恢复一份 → 全部改用新的 `--initial-cluster` 启动 → 逐个 `member add` 扩容**。所有成员必须使用同一份 `--initial-cluster` 字符串。

## Disaster recovery

按故障范围，官方把恢复场景分成两类，处置思路完全不同。

### 少数成员失败

单节点故障等价于"替换一台坏机器"，走 [成员变更](#add-as-learner) 的常规流程：先 `member remove` 掉坏的，再 `member add` 新节点。

> [!WARNING]
> **已经故障但还没被 remove 的成员会继续影响 quorum**。它虽然不可用，却仍被算在多数派基数里，从而降低集群对"再挂一个"的容忍度。所以故障节点要尽快摘除，不要让它挂着占席位。

### 多数成员失败

多数派丢失，或所有节点 IP 都变了，Raft 已无法自行恢复，必须手工介入。官方给的基本套路是三步：

1. **用旧数据创建一个新集群**（`etcdutl snapshot restore`）；
2. **强制单个成员成为 leader**（`--force-new-cluster`）；
3. **用运行时重配置把其余成员一个个加回来**。

> [!WARNING]
> `restore` 出来的集群是**一个新的集群**（新 cluster ID），它与旧集群没有任何 Raft 关联。如果旧集群里还有存活节点，必须先把它们停掉——两个集群同时对外服务会写出两套互不相同的数据，这就是分裂脑。

## Links

- [raft（共识模块）](/docs/CS/Framework/etcd/raft.md)
- [boltdb（底层存储引擎）](/docs/CS/Framework/etcd/boltdb.md)
- [treeIndex（内存键索引）](/docs/CS/Framework/etcd/treeIndex.md)
- [compact（历史版本压缩）](/docs/CS/Framework/etcd/compact.md)
- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [naming（成员/实例 endpoints 的服务发现）](/docs/CS/Framework/etcd/naming.md)
- [gateway（grpc-proxy：水平扩展 / watch-lease 合并）](/docs/CS/Framework/etcd/gateway.md)

## References

1. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.5/op-guide/runtime-configuration/)
2. [etcd Documentation - Disaster recovery](https://etcd.io/docs/v3.5/op-guide/recovery/)
3. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.5/op-guide/maintenance/)
4. [etcd v3.5 upgrade guide](https://etcd.io/docs/v3.5/upgrades/upgrade_3_5/)
5. [How to debug large db size issue?](https://etcd.io/blog/2023/how_to_debug_large_db_size_issue/)