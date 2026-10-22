## Introduction

ZooKeeper 的 watch 是一种**一次性（one-shot）**的事件通知机制：客户端在读取 znode 时注册 watch，当该 znode 发生变化，服务端触发并**清除**该 watch，随后向客户端推送一个 `WatcherEvent` 通知。watch 让客户端可以缓存数据、避免轮询，是"读本地 + 客户端缓存"高性能读模型的基础（见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 的架构全景）。

> **New in 3.6.0：** 支持**持久 watch（persistent / persistent_recursive）**，触发后不被清除，可递归监听子节点，缓解一次性模型的"错过窗口"问题。

本页聚焦 **watch 的服务端实现与一致性边界**；客户端如何注册、使用 watch 的 API 语义见 [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)。

## 一次性语义与一致性边界

watch 与**客户端 session**绑定：session 超时或关闭，所有 watch 失效，需重连后重新注册。由于触发后即被删除，**若在"收到通知"与"重新注册"之间 znode 再次变化，客户端会错过这次变化**——因此 watch 只能保证**最终一致性**，不能保证线性一致。

> [!WARNING]
> 经典陷阱：收到 `NodeChildrenChanged` 后若只重新注册对该节点的 child watch，而未处理"通知期间可能已发生的多次变更"，会读到陈旧子集。Recipes（如顺序临时节点的选主）必须配合 `getChildren` / `getData` 的**显式拉取**而非依赖"恰好一次"的事件（见 [Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md)）。

## 事件类型 EventType

服务端用 `EventType` 枚举区分通知（`org.apache.zookeeper.Watcher.Event`）：

- `NodeCreated` / `NodeDeleted` / `NodeDataChanged` / `NodeChildrenChanged`（标准四类）
- `DataWatchRemoved` / `ChildWatchRemoved` / `PersistentWatchRemoved`（移除类，3.6+）

> 注意：`NodeChildrenChanged` 只在子节点**集合**变化时触发，子节点自身的数据变化**不会**触发父节点的 child watch——这是设计而非 bug。`NodeDataChanged` 在 `data` 或 `stat`（含版本号）变化时触发。

## 服务端实现：WatchManager

`DataTree` 维护两个 `IWatchManager`（`org.apache.zookeeper.server` 包）：

- `dataWatches`：节点数据 / 存在性层面的 watch
- `childWatches`：子节点集合层面的 watch

服务端 `WatchManager`（默认实现）用 `watchTable`（`path → Set<Watcher>`）与 `watch2Paths`（`Watcher → paths`）双索引。`IWatchManager.triggerWatch(path, type, zxid, acl)` 的核心逻辑：

- 对 **STANDARD** 模式 watch：取出后**立即从 watchTable 移除**（一次性语义的来源）；
- 对 **PERSISTENT_RECURSIVE** 模式 watch：保留，并随父路径迭代向下触发；
- 最终调用 `watcher.process(event)`（即客户端侧 `Watcher.process`）。

> **惊群（thundering herd）：** 一次 `NodeChildrenChanged` 会同时通知该路径下所有注册者；大量客户端 watch 同一热节点时，单次变更会放大成 N 次通知 + N 次回调，是 watch 泄漏与毛刺的常见根因（见 [troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md) 的 watch Leak 一节）。

## 客户端实现：ZKWatchManager 与 ClientCnxn

客户端侧由 `ZKWatchManager`（`org.apache.zookeeper` 包）维护 `dataWatches` / `existWatches` / `childWatches` / `persistentWatches` / `persistentRecursiveWatches` 五张表，外加 `defaultWatcher`（构造 `ZooKeeper` 时传入、整个会话期的默认回调）。

`ClientCnxn` 内部两个线程协同：

- `SendThread`：负责与服务端通信、收发事件信息；
- `EventThread`：串行回调用户注册的 `Watcher.process()`。

服务端通知经 `SendThread.readResponse()` 反序列化为 `WatcherEvent`，再由 `EventThread.queueEvent()` 入队，最终 `processEvent()` 执行回调。**回调在独立线程、且严格 FIFO**，避免重入与乱序。当 `disableAutoWatchReset=false`（默认）时，重连成功会自动把本地 watch 重新注册到新服务端。

## 与 etcd watch 的对照

| 维度 | ZooKeeper watch | etcd watch |
| :--- | :--- | :--- |
| 触发模型 | 一次性，需重注册 | gRPC 双向流，可续接 |
| 历史回溯 | 无（错过的变更即丢失） | 按 `revision` 可回溯 |
| 递归监听 | 3.6+ `persistent_recursive` | 前缀监听天然覆盖子树 |
| 一致性 | 最终一致（存在错过窗口） | 可线性一致（伴随 compacted revision） |

选型上，etcd 的 watch 更适合"不丢事件"的强一致场景；ZK 的 watch 胜在简单、与 znode 树语义贴合，但需用 Recipes / Curator 兜底错过窗口（见 [Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md) 与 [Curator](/docs/CS/Framework/ZooKeeper/Curator.md)）。

## Links

- [ZooKeeper 枢纽](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Session](/docs/CS/Framework/ZooKeeper/Session.md)
- [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)
- [安全 security](/docs/CS/Framework/ZooKeeper/security.md)
- [请求处理链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [Zab（共识与排序）](/docs/CS/Framework/ZooKeeper/Zab.md)

## References

1. [ZooKeeper Programmer's Guide — Watches](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html#ch_zkWatches)
2. [ZooKeeper 3.6.0 Release Notes（persistent watch）](https://zookeeper.apache.org/doc/r3.6.0/releaseNotes.html)
