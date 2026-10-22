## Introduction

本页汇总 ZooKeeper 的**部署运维**要点与运行期常见问题。内容：

- 源码编译与启动引导 → **[Bootstrap](/docs/CS/Framework/ZooKeeper/Bootstrap.md)**（`QuorumPeerMain` 入口、`QuorumPeer` 状态机、Standalone 模式）。
- 快照/事务日志的自动清理（`DatadirCleanupManager` / `PurgeTxnLog`）→ **[storage](/docs/CS/Framework/ZooKeeper/storage.md)** 的 Purge 节。
- 部署形态（ensemble 规模、quorum、Observer 跨 DC、动态重配置）→ **[cluster](/docs/CS/Framework/ZooKeeper/cluster.md)**。
- **zxid 溢出触发选主** → 本页 issue 一节。

> [!TIP]
> 新手从 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 概念枢纽入门，部署看 [Bootstrap](/docs/CS/Framework/ZooKeeper/Bootstrap.md) 与 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)，运行期排障看 [troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md)。



## zxid 溢出触发选主（zxid rollover）

线上 Flink 用户使用 ZooKeeper 做元数据中心以及集群选主，一些版本的Flink 在 ZooKeeper 选主时会重启 Job，导致非预期的业务损失。而 ZooKeeper 在 **zxid 溢出**时会主动触发一次选主，导致 Flink Job 非预期重启。本节从原理与最佳实践分析并解决该问题。线上 flink 用户使用 ZooKeeper 做元数据中心以及集群选主，一些版本的 flink 在 ZooKeeper 选主时，会重启 Job，导致一些非预期的业务损失。而 ZooKeeper 在 zxid溢出时，会主动触发一次选主，就会导致 flink Job 的非预期重启，造成业务损失。本篇从原理和最佳实践上分析和解决由于 ZooKeeper zxid 溢出导致的集群选主问题。检查 ZooKeeper Server 日志出现

```
zxid lower 32 bits have rolled over, forcing re-election, and therefore new epoch start
```

ZooKeeper 本身提供当前处理的最大的 Zxid，通过 stat 接口可查看到当前处理的最大的 zxid 的值，通过此值可以计算当前 zxid 距离溢出值还有多少差距。

xid 是 ZooKeeper 中一个事务的全局唯一 id，通过 zxid 描述各个事务之间的全序关系。客户端对 ZooKeeper 内部数据的变更都是通过事务在 ZooKeeper 集群内的传播和处理完成的，因此 zxid 就是客户端对数据进行一次变更所产生的事务在全局事务中的一个唯一 id，这个 id 描述了本次变更的事务在全局事务中的位置，并且不会有两个不同的事务拥有相同的 zxid（全序关系）。

zxid 是一个 64bits 的数，有两个部分组成：当前选举周期（epoch，占用高32bits）以及计数部分（counter，占用低32bits），epoch 表示 leader 关系的变化，每当新的集群产生新的leader，都会产生一个新的 epoch表示当前 leader 的选举周期，ZooKeeper  集群选主成功之后保证只会有一个Leader，并且此 Leader 的 epoch 是以前没有使用过的，这就保证了只会有一个 leader 使用本次选举过程中产生的 epoch， 在此基础上，每当客户端对数据进行变更的时候，leader 对产生的事务在当前 counter 的值加一产生新的事务的 zxid，并使用此 zxid 将此事务在集群中进行同步，这样就保证了事务的全序关系

当单个 epoch 中处理的事务过多，以至于当前epoch 对应的 counter 数值超过了 32bits 计数的最大值，如果继续计数 epoch 就会 +1 ， 如果在未来，进行了一次选举，其他的 Server 当选了 leader，但是他产生的新 epoch 可能就会和现在 zxid 中的 epoch 重合，导致不同的事务会有相同的 zxid，破坏了事务之间的全序关系，可能导致脏数据的产生。因此 ZooKeeper 在低 32 位达到最大计数值的时候，就会主动产生一次选主，避免以上问题。

一般情况下使用 ZooKeeper 作为注册配置中心，集群选主对于客户端来说是无感知的，集群选主之后客户端会主动重连恢复，
对于依赖于客户端Disconnected事件的使用场景：例如，Curator Recipes中的LeaderLatch场景，在集群选主时，Server会产生Disconnected事件，表示Client与Server断开了连接。在选主完成之后，Client会通过重连机制重新连接到Server。
在产生Disconnected事件后，LeaderLatch会重新选主（这里的选主是指使用LeaderLatch做集群选主的场景中，重新选择注册上来的其他实例作为主），此时可能会触发业务侧的一些其他逻辑。例如，在Flink 1.14及以下版本使用LeaderLatch作为选主的默认实现，在ZooKeeper集群选主时会导致Flink Job被重启。
在业务的实现中，可通过Curator Recipes中的LeaderSelector替换LeaderLatch的方法，对ZooKeeper短暂的断连做一定的容忍

## Links

- [ZooKeeper（概念枢纽）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Bootstrap（源码编译与启动引导）](/docs/CS/Framework/ZooKeeper/Bootstrap.md)
- [存储 storage（含快照自动清理）](/docs/CS/Framework/ZooKeeper/storage.md)
- [集群运维 cluster](/docs/CS/Framework/ZooKeeper/cluster.md)
- [Election（选主与 epoch）](/docs/CS/Framework/ZooKeeper/Election.md)
- [Curator（LeaderSelector 替代 LeaderLatch）](/docs/CS/Framework/ZooKeeper/Curator.md)
- [故障排查 troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md)

## References

1. [ZooKeeper Admin Guide](https://zookeeper.apache.org/doc/current/zookeeperAdmin.html)
2. [ZooKeeper Internals（zxid 与 epoch）](https://zookeeper.apache.org/doc/current/zookeeperInternals.html)
3. [深入了解 ZooKeeper 核心原理](https://segmentfault.com/a/1190000040297172)
