# Nacos 的 CP 共识：JRaft

## Introduction

Nacos 的「配置中心」与「命名里的持久实例」需要**强一致 + 持久化**，这部分不能走 Distro 的 AP 最终一致，于是 Nacos 在 CP 侧引入了 **JRaft**——阿里巴巴基于 Raft 共识算法实现的 Java 库（源自 SOFA-JRaft，包路径 `com.alibaba.nacos.core.distributed.raft`）。

理解 JRaft 的关键是先分清 Nacos 的一致性分工：

- **AP 侧（Distro）**：临时实例（ephemeral instance）的注册 / 心跳 / 下线，追求可用性与写扩展，节点间异步同步，重启可能丢内存数据。详见 [Registry](/docs/CS/Framework/nacos/registry.md) 的 `## Distro`。
- **CP 侧（JRaft）**：配置（config）的全部写、以及**持久实例（persistent instance）**的元数据，必须过 Raft：先复制到多数派再提交、落盘、再应用到状态机。**持久实例一旦注册，即使全部 Nacos 节点重启也能从 DB + Raft 日志恢复**。

换句话说，同一个 naming 模块里，**临时实例走 Distro、持久实例走 JRaft**——这是 Nacos 一致性模型最容易混淆的点。

## 为什么配置侧用 Raft

配置变更的应用语义要求「读己之写」「全局有序」「不丢」：

- 发布配置后，所有节点、所有客户端必须立即看到同一份值（不能出现 A 节点看到新值、B 节点还是旧值）。
- 灰度 / 回滚 / 监听依赖配置的全局版本单调。
- 配置要持久化，节点宕机不能丢。

这些正好是 Raft 的强项：单一 Leader 定序、日志复制到多数派、提交后应用。etcd 的 etcd-raft、ZooKeeper 的 Zab 也是为同样的诉求服务，只是 Nacos 选了 JRaft 并把它限定在 CP 子系统内（etcd / ZK 是全程 Raft/Zab）。

## 组件与启动链路

Nacos 把一个 CP 数据类型抽象成 `LogProcessor4CP`：每种需要 Raft 一致的数据（配置、持久实例元数据……）注册自己的 processor，Raft 日志提交后由对应 processor 应用到内存状态机。启动链路大致是：

```java
// ProtocolManager 根据一致性协议类型选择 RaftProtocol
//   -> RaftConfig（group / peers / dataDir）
//   -> JRaftProtocol.init()
//   -> JRaftServer.start()：为每个 Raft group 起一个 RaftGroupService
//   -> 日志提交后回调对应的 LogProcessor4CP.onApply(...)
```

要点：

- **Raft group**：JRaft 以 group 为单位组织复制组，每个 group 有独立的 Leader / 日志 / 快照。Nacos 按 CP 数据类型划分 group（配置、命名持久元数据等）。
- **StateMachine = LogProcessor4CP**：JRaft 的 `StateMachine.onApply(task)` 在 Nacos 侧由 `LogProcessor4CP` 实现，把已提交日志落到内存结构 + 外部 DB。
- **多数派**：写入成功的判定是「日志复制到半数以上节点」，与 etcd / ZK 一致。

## Leader 选举

JRaft 遵循标准 Raft 选举：

- 节点角色：**Leader / Candidate / Follower**。
- **Follower** 在 election timeout（随机化，避免同时竞选）内收不到 Leader 心跳 → 自增 `term`、转 Candidate、投自己一票并广播 `RequestVote`。
- 获**多数派**选票 → 成为 Leader，定期发心跳维持权威。
- `term` 单调增；带更大 term 的消息会让旧 Leader 退位为 Follower。

Nacos 集群里 CP 侧同一时刻只有一个 Leader；`nacos_monitor{name='leaderStatus'}`（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）可观测当前节点是否为 Leader。

## 日志复制与提交

一次 CP 写（例如 `publishConfig`）的路径：

1. 请求到达 Leader（若打到 Follower，Follower 转发给 Leader）。
2. Leader 把变更追加为 Raft 日志条目（未提交）。
3. Leader 并行复制日志给所有 Follower。
4. **多数派（quorum）持久化成功** → Leader 将该条目标记为 **committed**。
5. Leader 将 committed 日志 **apply** 到状态机（`LogProcessor4CP.onApply`）：更新内存 + 写 MySQL。
6. 应答客户端；Follower 在收到 commit 位点后也 apply。

只有 committed 的日志才对读可见——这保证了 `readAfterWrite` 与崩溃恢复后日志不丢（已提交日志不会被新 Leader 覆盖）。

## 快照

Raft 日志会无限增长，JRaft 通过**快照（Snapshot）**给日志「瘦身」：

- 当日志长度 / 体积超过阈值，状态机做一次快照，把当前内存状态序列化落地。
- 新加入节点或落后太多的节点，可先拉快照再追增量日志，避免重放全部历史。
- 快照与「外部 DB（MySQL）里的 config_info」是两套：DB 是 Nacos 的业务持久层，Raft 快照是共识层自身的恢复点。

## 成员变更

集群扩缩容时 CP 侧要改 Raft group 的成员（peers）：

- JRaft 支持**成员变更**（addPeer / removePeer），通过 `RaftServer` 的 `CliService` 或 Nacos 的运维接口下发。
- 成员变更本身是 Raft 日志的一种，需经多数派提交，保证「加/减节点」过程不丢 committed 日志。
- 变更期间注意：新旧 peer 列表重叠的过渡窗口，Nacos 要求 `cluster.conf` / 地址服务器里的成员与 Raft group 成员保持一致，否则会出现「成员列表不一致 → 数据不一致」（见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)）。

## 端口（与 Distro / gRPC 区分）

Nacos 把同一个 `server.port`（默认 8848）派生出一组端口，容易混淆：

| 端口 | 含义 | 一致性 |
| :-- | :-- | :-- |
| 8848 | 主端口（HTTP / OpenAPI / Console） | — |
| 9848 | gRPC 客户端端口（= `8848 + 1000`） | SDK 长连接 |
| 9849 | gRPC 服务端端口（= `8848 + 1001`） | 节点间 gRPC |
| **7848** | **JRaft 端口（= `8848 - 1000`）** | **CP 共识** |

JRaft 只在 CP 节点间用 7848 通信；Distro（AP）走另一套临时实例同步通道。集群部署必须保证 7848 在节点间互通，否则 CP 侧选不出 Leader 或日志复制失败。

## 与 etcd-raft / Zab 的对照

三者都解决「单 Leader 定序 + 多数派复制 + 提交后应用」，差异在**作用范围**：

- **etcd**：全程 Raft（etcd-raft），KV 全部强一致，无 AP 分支 → [etcd/raft.md](/docs/CS/Framework/etcd/raft.md)。
- **ZooKeeper**：全程 Zab（原子广播），znode 树全强一致 → [ZooKeeper/Zab.md](/docs/CS/Framework/ZooKeeper/Zab.md)。
- **Nacos**：Raft 只覆盖 CP 子系统，命名默认 AP（Distro）→ 维度矩阵见 [etcd 横向对照](/docs/CS/Framework/etcd/compare.md) 的 Nacos 段。

这也是 Nacos「既能做注册中心又能做配置中心」的代价：注册中心的高可用来自 AP，配置中心的可靠来自 CP，二者在同一进程内用不同协议实现。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Registry](/docs/CS/Framework/nacos/registry.md)
- [Storage](/docs/CS/Framework/nacos/storage.md)
- [etcd Raft](/docs/CS/Framework/etcd/raft.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://nacos.io/docs/v3.0/manual/admin/cluster/>
- <https://github.com/alibaba/nacos/tree/master/consistency>
- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
