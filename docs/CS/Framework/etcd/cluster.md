# Cluster Operations

## Introduction

etcd 的运维面和数据面一样围绕 [Raft](/docs/CS/Framework/etcd/raft.md) 展开：谁有权提交写、谁能落盘、成员怎么增减，都由 Raft 日志与多数派（quorum）决定。本篇覆盖三块运维地基：**磁盘数据长什么样**、**成员怎么安全增减**、**数据怎么备份恢复**。三者都要求先理解 quorum——etcd 所有写入都要等多数派确认，任何"改配置"的动作本质都是一次提案，受同样的可用性前提保护。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下状态与默认值均以该 tag 源码为准。

官方反复强调的硬约束贯穿全文：

> Reconfiguration requests can only be processed when a majority of cluster members are functioning. It is **highly recommended** to always have a cluster size greater than two in production.

两节点集群的多数派也是 2，摘掉一个就失去 quorum，且没有第三份副本容忍移除过程中的失败，所以不安全。

3.7.4 相对旧资料的纠偏点：

- **启动完全从 v3store 引导**：`bootstrap.go` 的 `buildConfStateFromV3store` 从 backend 成员表重建 `ConfState`，不再读 v2store（见 [v2](/docs/CS/Framework/etcd/v2.md)）。
- **raft 外置**为独立 module `go.etcd.io/raft/v3` v3.7.0，主仓库只有调用侧。
- **默认配额 2 GB，建议上限 8 GB**；`/livez` / `/readyz` 自 v3.5.12 提供；`--snapshot-count` 默认已降到 10000。

| 项 | 值（3.7.4） |
| :--- | :--- |
| raft module | `go.etcd.io/raft/v3` v3.7.0 |
| bbolt | v1.5.0 |
| 默认配额 | 2 GB（建议上限 8 GB） |
| learner 支持 | v3.4 起，单集群最多 1 个 |
| `/livez`、`/readyz` | v3.5.12 起 |

> [!WARNING]
> 3.6 起 `--enable-v2` 与 `--experimental-enable-v2v3` 已被移除，v2 API 代码路径彻底下线。新部署不要依赖 v2 接口，迁移前确认客户端（老版本 Curator、Dubbo 的 ZooKeeper 抽象层）是否还在用 v2。

## On-disk Layout

etcd 启动时把数据目录整理成"快照 + 日志 + 索引"组合。单节点默认布局：

```text
${data-dir}/
└── member/
    ├── snap/
    │   ├── 000000000000001f-0000000000c0433e.snap   # raft 快照（term-index 命名）
    │   └── db                                        # boltdb 后端，承载全部 key-value
    └── wal/
        ├── 0000000000000000-0000000000000000.wal     # WAL 段
        └── 0000000000000000-0000000000000000.wal.lock
```

三类文件分工对应 Raft 的持久化要求：

- **`.snap`**：Raft 快照，按 `term-index` 命名，把该 index 前的日志压成状态机镜像，作用是**截断日志**。
- **`.wal`**：预写日志，提案先落 WAL 再返回，崩溃后靠回放重建未落盘条目。
- **`db`**：[boltdb](/docs/CS/Framework/etcd/boltdb.md) 后端，key-value、lease、member、cluster、auth 全部数据在此；[treeIndex](/docs/CS/Framework/etcd/treeIndex.md) 只在内存存 key→revision，重启由 `db` 回放重建。

启动如何重建 ConfState——`bootstrap.go` 从 backend 成员表读 voters/learners：

```go
func buildConfStateFromV3store(lg *zap.Logger, be backend.Backend) raftpb.ConfState {
	members, _ := schema.NewMembershipBackend(lg, be).MustReadMembersFromBackend()
	var (
		voters   []uint64
		learners []uint64
	)
	for _, m := range members {
		if m.IsLearner {
			learners = append(learners, uint64(m.ID))
		} else {
			voters = append(voters, uint64(m.ID))
		}
	}
	return raftpb.ConfState{Voters: voters, Learners: learners}
}
```

> [!TIP]
> **`db` 文件删除不会丢数据**：有 `.snap` + `.wal` 就能重建全部状态。换机迁移可直接拷 `.snap`/`.wal`（通常比几个 G 的 `db` 小得多）。反之只拷 `db` 会丢失未压缩的历史版本与 lease 状态。

> [!NOTE]
> **删掉 `.snap`/`.wal` 但保留 `db` 有风险**：`db` 的 MVCC 历史能支持旧版本读，但 Raft 提交索引会退回快照位置，等于放弃这段写历史。官方无损做法是 `etcdutl snapshot restore`，而不是手工拼文件。

## Member Management

成员变更走 Raft 提案，每次 `member add/remove/update` 都写入日志并同步全集群——这跟"改本地配置"有本质区别。也正因此，**改 peer URLs 必须显式执行成员变更，改 client URLs 只需重启**：

| 变更类型 | 是否需要 `member` 命令 | 原因 |
| :--- | :--- | :--- |
| `clientURLs` | 否 | 本地通告配置，不影响拓扑，重启自我发布 |
| `peerURLs` | **是** | peer 地址是 Raft 拓扑的一部分，写错破坏 quorum |
| 增删成员 | **是** | 改变 quorum 计算基数 |

```shell
$ etcdctl member list
$ etcdctl member update a8266ecf031671f3 --peer-urls=http://10.0.1.10:2380
$ etcdctl member remove a8266ecf031671f3
```

被移除的成员会自行退出并打印 `this member has been permanently removed from the cluster. Exiting.`

> [!NOTE]
> 移除 leader 是**允许**的，但会有一段时间不可用（约一个 election timeout 加投票过程）。生产更推荐先 `etcdctl move-leader` 把 leader 挪走，再摘除目标节点。

### Add as learner

learner（非投票成员）自 v3.4 支持，推荐**三步法**——先以 learner 追赶，追平后提升为投票成员：

```shell
# 1. 以 learner 身份加入
$ etcdctl member add infra3 --peer-urls=http://10.0.1.13:2380 --learner
# 2. 用输出的 ETCD_NAME / ETCD_INITIAL_CLUSTER / ETCD_INITIAL_CLUSTER_STATE=existing 启动新进程
# 3. 追上日志后提升为投票成员
$ etcdctl member promote 9bf1b35fc7761a23
```

learner 的价值在于**不计入 quorum**：直接以投票成员加入时，新成员配置错误（如 peer URL 写错）就被计入多数派基数，可能把集群推进失去 quorum 的死局；learner 只接收数据不投票，失败直接摘掉重来，代价极低。`promote` 会校验安全性，未追平会报 `can only promote a learner member which is in sync with leader`。

> [!WARNING]
> **单集群最多 1 个 learner**（v3.4 起的设计约束，官方理由是限制 leader 向 learner 传播数据的额外负载）：加第二个会报 `too many learner members in cluster`。所以 learner 扩容是**串行**的，一次加一个、追平、提升，再加下一个。

### strict-reconfig-check

`--strict-reconfig-check` 控制重配置时是否做 quorum 校验，**默认开启**：若这次重配置会导致"已启动成员数 < 新集群多数派"，直接拒绝提案。该校验专门防"一次加多个、其中一个没起来"——未启动的新成员仍被计入 quorum 基数。

| 场景 | 操作序列 |
| :--- | :--- |
| 3 → 5 节点 | 两次 `member add`（不能一次加俩） |
| 5 → 3 节点 | 两次 `member remove` |
| 替换健康节点 | 先 `remove` 旧，再 `add` 新 |
| 滚动升级 | 一次只动一个成员，确认恢复再动下一个 |

### Common Startup Errors

这几类错误共同根因都是 **peer URL 与集群记录不匹配**，排查时优先核对 `etcdctl member list` 与启动参数：

```text
etcdserver: assign ids error: the member count is unequal
etcdserver: assign ids error: unmatched member while checking PeerURLs
etcd: this member has been permanently removed from the cluster. Exiting.
```

> [!NOTE]
> 第三条尤其容易踩：删掉节点后把它的 `data-dir` 拷到新机器再启动，etcd 一连上集群就自杀。**换机必须换新的 `data-dir`**，数据靠 `member add` + 重新同步（或迁移 `.snap`/`.wal`）送过去。

## Backup and Restore

### Snapshot Backup

etcd 的备份是后端 db 文件的一致性快照：`etcdctl snapshot save backup.db`，再用 `etcdutl snapshot status backup.db` 查看 hash / revision / keys / size。注意这与 raft 快照不是一回事——raft 快照用于截断日志，`snapshot save` 是运维离线备份。

> [!NOTE]
> `snapshot save` 仍在 `etcdctl`（需通过 gRPC 触发），`snapshot status` / `snapshot restore` 在 `etcdutl`（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 snapshot 命令分工）。

### Restore from Snapshot

`etcdutl` 是 3.5 从 etcd 拆出的独立工具（`make build` 产出 `etcd` / `etcdctl` / `etcdutl`）：

```shell
$ etcdutl snapshot restore backup.db \
    --name infra0 \
    --initial-cluster infra0=http://10.0.1.10:2380,infra1=http://10.0.1.11:2380 \
    --initial-advertise-peer-urls http://10.0.1.10:2380 \
    --data-dir /var/lib/etcd
```

恢复必须走 `etcdutl` 而非直接启动，因为要重写一份**全新集群身份**：

- **cluster ID 与 member ID 重新生成**：旧 member ID 仍被其他成员持有，沿用会导致重复 member、破坏投票唯一性。
- **`--initial-cluster` 必填且必须与后续扩容计划一致**，写死在恢复出的数据里。
- **`--bump-revision` 把 revision 往上推**，避免恢复后集群与存活旧集群产生 revision 冲突（分裂脑场景必须加）。

多节点恢复标准顺序：每个成员各恢复一份 → 全部用新的 `--initial-cluster` 启动 → 逐个 `member add` 扩容。所有成员必须用同一份 `--initial-cluster` 字符串。

## Disaster Recovery

按故障范围分两类：

### Minority Members Failure

单节点故障等于"替换坏机器"，走常规成员变更：`member remove` 坏的，`member add` 新的。

> [!WARNING]
> **已故障但还没 remove 的成员会继续影响 quorum**：虽不可用却仍算在多数派基数里，降低对"再挂一个"的容忍度。故障节点要尽快摘除。

### Majority Members Failure

多数派丢失或所有节点 IP 都变了，Raft 无法自行恢复，须手工介入。官方套路三步：用旧数据创建新集群（`etcdutl snapshot restore`）→ 强制单成员成为 leader（`--force-new-cluster`）→ 用运行时重配置把其余成员逐个加回。

> [!WARNING]
> `restore` 出来的是**新集群**（新 cluster ID），与旧集群没有任何 Raft 关联。若旧集群还有存活节点，必须先停掉——两个集群同时对外服务会写出两套不同数据，即分裂脑。

## Links

- [raft](/docs/CS/Framework/etcd/raft.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [treeIndex](/docs/CS/Framework/etcd/treeIndex.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [naming](/docs/CS/Framework/etcd/naming.md)
- [gateway](/docs/CS/Framework/etcd/gateway.md)

## References

1. [etcd v3.7.4 源码（server/etcdserver/bootstrap.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/bootstrap.go)
2. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.7/op-guide/runtime-configuration/)
3. [etcd Documentation - Disaster recovery](https://etcd.io/docs/v3.7/op-guide/recovery/)
4. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.7/op-guide/maintenance/)
