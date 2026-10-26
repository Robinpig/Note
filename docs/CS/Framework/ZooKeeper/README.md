## Introduction

本目录是 ZooKeeper 的系统性笔记集合，按"对外 API → 服务端请求处理 → Zab 共识 → 存储/内存"的纵向分层组织。建议阅读路线：先读 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 建立整体心智模型（数据模型、znode、watch、session、ACL），再按需下钻共识 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md)、[请求处理器链](/docs/CS/Framework/ZooKeeper/pipeline.md) 与 [存储层](/docs/CS/Framework/ZooKeeper/storage.md)，最后看生产运维（[cluster](/docs/CS/Framework/ZooKeeper/cluster.md) / [monitoring](/docs/CS/Framework/ZooKeeper/monitoring.md) / [troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md) / [security](/docs/CS/Framework/ZooKeeper/security.md)）与上层协调原语（[Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md) / [Curator](/docs/CS/Framework/ZooKeeper/Curator.md)）。

> [!NOTE]
> 版本基线：当前主线 **3.9.6**（2026-09），维护线 3.9.x / 3.8.x；3.7 已于 2024-02 EOL；3.10.0 / 4.0.0 规划中。横向对比见 [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)。

## Layered Architecture Diagram

```dot
digraph "ZooKeeperStack" {
  rankdir = "TB";
  node [shape = box, style = "rounded,filled", fillcolor = "#e6f2ff"];

  subgraph client {
    label = "客户端 / 协议";
    C [label = "ZooKeeper 客户端\n(client / Jute)"];
  }
  subgraph srv {
    label = "服务端请求处理 (pipeline)";
    Prep [label = "PrepRequestProcessor"];
    Proposal [label = "ProposalRequestProcessor"];
    Commit [label = "CommitProcessor"];
    Final [label = "FinalRequestProcessor"];
  }
  subgraph consensus {
    label = "Zab 共识 (仅 Leader 写)";
    Zab [label = "Zab\n(选举 / PROPOSAL / COMMIT)"];
  }
  subgraph storage {
    label = "存储 / 内存";
    Txn [label = "FileTxnLog (WAL)"];
    Snap [label = "FileSnap (快照)"];
    Tree [label = "DataTree / ZKDatabase"];
  }

  C -> Prep;
  Prep -> Proposal -> Zab;
  Zab -> Commit -> Final;
  Final -> Tree;
  Txn -> Tree [style = dashed, label = "replay"];
  Snap -> Tree [style = dashed, label = "load"];
}
```

实线为一次写请求的主链路：客户端 → 预处理 → 提案（经 Zab 广播）→ 提交 → 应用内存树；虚线为启动恢复时快照/日志回填内存。

## Layered Navigation

**总览与数据模型** —— 一切的起点。[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 是**概念枢纽**：讲清 znode 树、createNode、watch 一次性语义、session、ACL、一致性保证、Zab 总览，以及与 Chubby / etcd 的对照；序列化线格式见 [Jute](/docs/CS/Framework/ZooKeeper/Jute.md)。

**共识：Zab 与选主** —— [Zab](/docs/CS/Framework/ZooKeeper/Zab.md) 讲协议本身：Leader/Follower/Observer 角色、proposal 广播与提交（zxid、过半 ACK）、discovery→synchronization→broadcast 三阶段、与 Raft 对照；[Election](/docs/CS/Framework/ZooKeeper/Election.md) 是**选主源码深潜**——QuorumCnxManager 通信层、FastLeaderElection 四步状态机、QuorumPeer::run 主循环、故障切换与状态同步。

**存储与内存** —— [storage](/docs/CS/Framework/ZooKeeper/storage.md) 拆解 FileTxnLog / FileSnap / FileTxnSnapLog 与 ZKDatabase / DataTree / DataNode，解释 zxid、快照触发（shouldSnapshot）、启动恢复（快照 + 日志 replay）与**自动清理**（DatadirCleanupManager / PurgeTxnLog）。

**请求处理链** —— [pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md) 梳理 Leader / Follower / Observer 各自的 RequestProcessor 链，澄清"读本地、写经 Leader"以及 `sync()` 如何实现线性读。

**网络层** —— [IO](/docs/CS/Framework/ZooKeeper/IO.md) 是网络层汇总与对比（Netty 实现、NIO vs Netty、连接处理）；[NIO](/docs/CS/Framework/ZooKeeper/NIO.md) 是默认实现 `NIOServerCnxnFactory` 的源码深潜（configure / Queue / AcceptThread / SelectorThread / doIO）。

**客户端与协议** —— [client](/docs/CS/Framework/ZooKeeper/client.md) 覆盖连接串/chroot、会话生命周期、watch 用法、异常分类与重试策略、最佳实践；watch / session / ACL 的**服务端实现与数据模型深潜**分别见 [Watches](/docs/CS/Framework/ZooKeeper/Watches.md) / [Session](/docs/CS/Framework/ZooKeeper/Session.md) / [ACL](/docs/CS/Framework/ZooKeeper/ACL.md)。

**协调原语** —— [Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md) 记录屏障 / 队列 / 锁 / 两阶段提交 / 选主等配方的原理，[Curator](/docs/CS/Framework/ZooKeeper/Curator.md) 是 Netflix 出品的高层客户端（重试、缓存、配方实现），生产首选。

**安全** —— [ACL](/docs/CS/Framework/ZooKeeper/ACL.md) 讲权限数据模型（scheme:id:permission、aversion CAS、ACL 不继承陷阱），[security](/docs/CS/Framework/ZooKeeper/security.md) 梳理五种身份来源（digest / ip / sasl / x509 / super）、SASL（Kerberos）、3.9 起补齐的 TLS 与 superDigest 应急。

**部署与引导** —— [Bootstrap](/docs/CS/Framework/ZooKeeper/Bootstrap.md) 是源码编译与启动引导深潜（QuorumPeerMain 入口、QuorumPeer 状态机、Standalone 模式）；[start](/docs/CS/Framework/ZooKeeper/start.md) 汇总部署运维要点与 **zxid 溢出触发选主**这一高价值坑。

**生产运维** —— [cluster](/docs/CS/Framework/ZooKeeper/cluster.md) 讲 ensemble 规模、quorum、Observer 跨 DC 只读扩展、动态重配置、滚动升级与备份；[monitoring](/docs/CS/Framework/ZooKeeper/monitoring.md) 列四字命令、mntr 指标、JMX、Prometheus 与告警；[troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md) 是磁盘爆满、只读模式、leader 切换、watch 泄漏、会话过期的 on-call 速查。

**横向对照** —— 与 etcd / Nacos / Consul 的差异由 [etcd 横向对照](/docs/CS/Framework/etcd/compare.md) 枢纽统一承载（同层对比笔记经枢纽连接，不互相直链）。

## Links

- [Chubby](/docs/CS/Distributed/Chubby.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Consul](/docs/CS/Framework/consul/Consul.md)
- [Election（选主源码深潜）](/docs/CS/Framework/ZooKeeper/Election.md)
- [NIO（默认网络层深潜）](/docs/CS/Framework/ZooKeeper/NIO.md)
- [Bootstrap（启动引导深潜）](/docs/CS/Framework/ZooKeeper/Bootstrap.md)
- [Watches](/docs/CS/Framework/ZooKeeper/Watches.md)
- [Session](/docs/CS/Framework/ZooKeeper/Session.md)
- [ACL](/docs/CS/Framework/ZooKeeper/ACL.md)
- [Curator](/docs/CS/Framework/ZooKeeper/Curator.md)
- [Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md)
- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)

## References

1. [ZooKeeper: Wait-free coordination for Internet-scale systems](https://www.usenix.org/legacy/event/atc10/tech/full_papers/Hunt.pdf)
2. [Apache ZooKeeper Documentation](https://zookeeper.apache.org/doc/current/)
3. [ZooKeeper 3.9.0 Release Notes](https://zookeeper.apache.org/doc/r3.9.0/releaseNotes.html)
