## Introduction

ZooKeeper 生产故障大多集中在四类：**磁盘（快照+日志堆积）**、**quorum（分区/只读模式）**、**会话与 watch（过期/泄漏）**、**升级与数据损坏**。本篇把高频问题、根因与处置步骤串起来，作为 on-call 速查。配套看板指标见 [monitoring](/docs/CS/Framework/ZooKeeper/monitoring.md)；恢复原理见 [storage](/docs/CS/Framework/ZooKeeper/storage.md)；选举与角色见 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md)。

> [!NOTE]
> 当前主线 3.9.6，维护线 3.9.x / 3.8.x；3.7 已于 2024-02 EOL，老集群应规划升级（见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）。

## Disk Full: Snapshot and Log Accumulation

**症状**：节点宕机、日志刷 `No space left on device`、`zk_outstanding_requests` 飙升。

**根因**：每次写都先落 TxnLog（`dataLogDir`），`SyncRequestProcessor` 按 `shouldSnapshot()` 物化快照（`dataDir`）。高频写入下，若 `autopurge` 间隔（最小 1 小时）内产生的文件来不及清理，就可能写满盘。

**处置**：

1. 立即排查 `dataDir` / `dataLogDir` 占用；临时释放空间（如停非关键进程）。
2. 调 `autopurge.snapRetainCount`（保留数，默认 3）+ `autopurge.purgeInterval`（小时，默认 0=关，设 > 0 开启）。
3. 调 `snapCount`（`zookeeper.snapCount`，默认 100000）/ `snapSizeLimitInKb`（3.6+，默认 4GB）：调大降低快照频率，但会拉长重启恢复（见 [storage](/docs/CS/Framework/ZooKeeper/storage.md)）。
4. 应急手工清理：`zkCleanup.sh -n <保留数>`（停服或低峰执行）。
5. **根治**：`dataLogDir` 单独挂高性能盘，监控磁盘使用率（见 [monitoring](/docs/CS/Framework/ZooKeeper/monitoring.md) 的 data size 指标）。

> [!WARNING]
> 清理必须**快照与日志配套删除**——不可只删日志不删快照，否则保留的快照与其后日志不匹配会丢数据。手工删除前备份。

## Read-Only Mode / Quorum Loss

**症状**：日志出现 `will be dropped if server is in read-only mode`，写请求被拒。

**根因**：集群无法选出/维持 Leader（Leader 失效、网络分区、超过半数节点不可用），存活节点退化为只读，避免脑裂写不一致。详见 [ZooKeeper Issues 段](/docs/CS/Framework/ZooKeeper/ZooKeeper.md?id=issues) 与只读模式机制（[pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md?id=readonlyrequestprocessor-and-read-only-mode)）。

**处置**：

1. `zkServer.sh status` 或 `mntr` 确认有无 Leader、各节点健康。
2. 查网络：节点间 2888（quorum）/ 3888（选举）/ 2181（客户端）是否通，防火墙有无阻断。
3. 等自动重选；切勿在不确定 quorum 时随意重启多节点——可能把可用副本数打到更低。
4. 长期：扩容到 5/7 提升容错，或跨 DC 用 Observer 扩展读（见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）。

## Leader Frequent Switching (Flapping)

**症状**：`zk_server_state` 在 leader/follower 间抖动，`zk_followers != zk_synced_followers`。

**根因**：

- **GC 停顿过长**：Leader 在 `maxSessionTimeout` 内未发心跳，被判定失联触发重选。调 JVM GC（G1/ZGC）、避免大堆全 STW。
- **磁盘 fsync 慢**：`forceSync=yes` 下写延迟高，`SyncRequestProcessor` 阻塞，Leader 来不及推进。
- **网络抖动 / 时钟漂移**：选举超时（`initLimit` / `syncLimit`）被触发。
- **Follower 落后**：`zk_pending_syncs` 高，Leader 追不上。

**处置**：看 `mntr` 延迟与 `zk_heap_used`；优先治理 GC 与磁盘 I/O；必要时调整 `initLimit` / `syncLimit`（见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）。

## watch Leak

**症状**：`zk_watch_count` 单调增长不回落，内存随之上涨。

**根因**：客户端注册 watch 后未正常 `close()`，或一次性 watch 未被回收；大量短命客户端反复注册。查 `wchc` / `wchp`（按路径/会话）定位来源。

**处置**：找到泄漏客户端让其正确关闭；高频场景改用 3.6+ 持久化 `addWatch` 并统一管理生命周期；必要时重启泄漏客户端会话。

## Session Expiration SessionExpired

**症状**：客户端收到 `KeeperState.Expired`，ephemeral 节点被删、watch 失效。

**根因**：`sessionTimeout` 内无任何心跳到达服务端——客户端 GC 停顿、网络长时间中断、或服务端过载。

**处置**：在默认 Watcher 捕获 `Expired` 后**重建 `ZooKeeper` 实例**（不可重试原请求），重新 `addAuthInfo`、重新注册 watch（重试语义见 [client](/docs/CS/Framework/ZooKeeper/client.md)）。优化：调大 `sessionTimeout`（仍在服务端允许区间内）、减少客户端 GC 停顿。

> [!TIP]
> `ConnectionLossException`（连接抖断、结果未知）**可重试**且需幂等校验；`SessionExpiredException` **不可重试**、必须重建。两者处置完全不同，监控与日志要区分。

## Upgrade and Data Inconsistency / Log Corruption

**症状**：启动报 TxnLog 校验失败、DataTree 加载异常、节点间数据对不上。

**处置**：

1. `zkTxnLogToolkit.sh`：检查 / 修复事务日志（Adler-32 校验）。
2. `zkSnapShotToolkit.sh`：检查 / 导出 / 比较快照。
3. 若单节点数据损坏且其余节点健康：停掉坏节点，删其 `dataDir` / `dataLogDir`，重新加入让其从 Leader **快照 + 日志**重新同步（replication 机制见 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md)）。
4. 升级路径：3.7（EOL）→ 3.8.x → 3.9.x 滚动升级，客户端 3.5+ 与 3.9 服务端兼容；3.5.3 起动态重配置默认关，需显式开（见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）。

## Port Conflict

| 端口 | 用途 | 冲突后果 |
| :--- | :--- | :--- |
| 2181 | 客户端 | 客户端连不上 |
| 2888 | quorum（Leader↔Follower 数据） | 无法同步 |
| 3888 | Leader 选举 | 选不出 Leader |
| 8080 | AdminServer | 管理接口不可用 |

部署前用 `ss -lntp` 核对；容器化注意端口映射与 `clientPort` / `secureClientPort`（2182）/ `admin.serverPort` 不重叠。

## Links

- [ZooKeeper（架构与数据模型）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Zab（共识与日志复制）](/docs/CS/Framework/ZooKeeper/Zab.md)
- [存储层 storage](/docs/CS/Framework/ZooKeeper/storage.md)
- [请求处理器链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [监控 monitoring](/docs/CS/Framework/ZooKeeper/monitoring.md)
- [集群运维 cluster](/docs/CS/Framework/ZooKeeper/cluster.md)
- [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)

## References

1. [ZooKeeper Administrator's Guide: Troubleshooting](https://zookeeper.apache.org/doc/current/zookeeperAdmin.html#sc_troubleshooting)
2. [ZooKeeper FAQ](https://cwiki.apache.org/confluence/display/ZOOKEEPER/FAQ)
3. [Dynamic Reconfiguration (USENIX ATC '12)](https://www.usenix.org/system/files/conference/atc12/atc12-final74.pdf)
