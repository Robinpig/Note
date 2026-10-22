## Introduction

etcd 是 Kubernetes 的默认后端存储，也是一个通用的强一致键值仓库。本目录按"从对外 API 到底层存储"的纵向分层来组织笔记：请求先进入客户端 / API 接入层，经 Raft 达成共识，再落到 KV 状态机（MVCC + boltdb）完成持久化；协调原语、安全、运维、版本与横向对比则横贯或补充在这条主链之外。

[etcd](/docs/CS/Framework/etcd/etcd.md) 是概念枢纽：版本基线、分层导航与逐页索引都在这里。原先承载全部细节的单一长文（架构、构建部署、启动链、server、quota、节点消息处理、网络、Peer、特性）已按「启动 → 请求 → 特性」拆成 [boot](/docs/CS/Framework/etcd/boot.md) / [request](/docs/CS/Framework/etcd/request.md) / [features](/docs/CS/Framework/etcd/features.md)，避免与成熟的 [raft](/docs/CS/Framework/etcd/raft.md) / [net](/docs/CS/Framework/etcd/net.md) 分册重复。本页是这些笔记的导航索引：建议阅读顺序是「枢纽 → 启动与生命周期 → 请求处理路径 → 共识层 Raft → 存储与 MVCC 引擎 → 客户端与 API」，再按需跳到协调原语、安全、运维与版本对比。

## Layered Architecture Diagram

下图把每条笔记映射到它在 etcd 中的层次。实线箭头表示一次写请求自上而下经过的主链路；协调原语建立在客户端之上，安全横切传输层。

```dot
digraph etcd_index {
  rankdir=TB;
  node [shape=box, style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica"];
  edge [color="#555", fontsize=10];

  subgraph cluster_api {
    label="客户端与 API 接入层";
    color="#c9d8ef";
    client   [label="client.md\n客户端与重试"];
    net      [label="net.md\n传输层 / gRPC"];
    gateway  [label="gateway.md\nREST + grpc-proxy"];
    naming   [label="naming.md\n服务发现"];
    read     [label="read.md\n读路径与一致性"];
  }
  subgraph cluster_raft {
    label="Raft 共识层";
    color="#d6ead0";
    raft    [label="raft.md\n共识算法"];
    tracker [label="tracker.md\nProgressTracker / 流控"];
  }
  subgraph cluster_store {
    label="KV 状态机 / MVCC 存储层";
    color="#f6e4cf";
    mvcc    [label="MVCC.md\n多版本"];
    tree    [label="treeIndex.md\n内存索引"];
    bolt    [label="boltdb.md\n持久化 B+tree"];
    compact [label="compact.md\n压缩回收"];
    lease   [label="lease.md\n租约 TTL"];
    watch   [label="watch.md\n监听推送"];
  }
  subgraph cluster_coord {
    label="分布式协调原语";
    color="#efe0ef";
    conc    [label="concurrency.md\n锁 / 选举 / STM"];
  }
  subgraph cluster_sec {
    label="安全（横切）";
    color="#f2cfcf";
    sec     [label="security.md\nTLS / 认证 / RBAC"];
  }
  subgraph cluster_ops {
    label="生产运维";
    color="#e6e6e6";
    cluster [label="cluster.md\n成员 / 备份"];
    monitor [label="monitoring.md\n监控"];
    trouble [label="troubleshooting.md\n排查"];
    tuning  [label="tuning.md\n调优"];
  }
  subgraph cluster_form {
    label="形态与版本";
    color="#dcdcc9";
    embed   [label="embed.md\n嵌入式"];
    v2      [label="v2.md\nv2 vs v3"];
    compare [label="compare.md\n横向对比"];
  }
  subgraph cluster_boot {
    label="启动与请求路径（从 etcd.md 拆出）";
    color="#dfeaf5";
    boot    [label="boot.md\n启动与生命周期"];
    req     [label="request.md\n请求处理路径"];
    feat    [label="features.md\n服务发现 / 事务"];
  }

  client -> net -> raft;
  gateway -> net;
  naming -> client;
  read -> raft;
  raft -> mvcc;
  mvcc -> tree;
  mvcc -> bolt;
  mvcc -> compact;
  mvcc -> lease;
  mvcc -> watch;
  conc -> client;
  sec -> net;
  boot -> raft;
  req -> raft;
  feat -> client;
}
```

## Overview and Startup

[etcd](/docs/CS/Framework/etcd/etcd.md) 是概念枢纽：版本基线、分层导航与逐页索引都在这里；原来承载全部细节的单一长文已按「启动 → 请求 → 特性」拆开，避免与成熟的 [raft](/docs/CS/Framework/etcd/raft.md) / [net](/docs/CS/Framework/etcd/net.md) 分册重复。顺着一条写请求理解全貌，建议顺序是「枢纽 → [boot](/docs/CS/Framework/etcd/boot.md)（启动与生命周期）→ [request](/docs/CS/Framework/etcd/request.md)（请求处理路径）→ Raft 共识 → MVCC 存储」，再按需跳到协调原语、安全、运维与版本对比。

- **启动与生命周期** —— [boot](/docs/CS/Framework/etcd/boot.md)：构建部署、整体架构、v2/v3 数据模型、`start → startEtcd → NewServer → serveClients → run` 启动链，以及启动时如何把外置 Raft 接线进来。
- **请求处理路径** —— [request](/docs/CS/Framework/etcd/request.md)：gRPC 拦截器、`KVServer`、quota 请求限流（`ErrTooManyRequests` / `MaxRequestBytes` / 7s 超时），以及 `get` / `put` 在 etcd 内部的全链路（propose → Raft → apply → 通知客户端）。
- **高层特性** —— [features](/docs/CS/Framework/etcd/features.md)：基于 etcd 的服务发现原理与 Apache APISIX 实战、v3 迷你事务（Txn）与 ACID。更完整的横向对比见 [compare](/docs/CS/Framework/etcd/compare.md)。

如果需要把 etcd 作为库嵌进自己的进程，而不是独立部署，看 [embed](/docs/CS/Framework/etcd/embed.md)（`server/embed` 模块，3.5 起稳定）。

## Consensus Layer: Raft

etcd 的一致性由 [raft](/docs/CS/Framework/etcd/raft.md) 提供——日志复制、领导人选举、状态机应用都在这里。想深入"Leader 如何感知每个 Follower 追到哪了、如何做窗口流控与暂停"，读 [tracker](/docs/CS/Framework/etcd/tracker.md)：它拆解 `ProgressTracker`、`Inflights` 环形窗口、`Probe` / `Replicate` / `Snapshot` 三种状态，以及 `IsPaused()`、`Committed()`、`QuorumActive()` 跳过 learner 的细节。读路径的线性一致性也依赖 Raft 的 ReadIndex，见 [read](/docs/CS/Framework/etcd/read.md)。

## Storage and MVCC Engine

共识层之上是 KV 状态机。[MVCC](/docs/CS/Framework/etcd/MVCC.md) 讲解多版本模型：每次写生成全局递增的 `revision`（`main` + `sub`），put / delete / tx 如何借此保留历史。[treeIndex](/docs/CS/Framework/etcd/treeIndex.md) 是内存中的 B-tree 键索引，维护 `key → revision` 的映射；真正落盘的是 [boltdb](/docs/CS/Framework/etcd/boltdb.md)（bbolt 的 B+tree、页结构、bucket 与事务）。历史不会被无限保留——[compact](/docs/CS/Framework/etcd/compact.md) 负责压缩与回收，[lease](/docs/CS/Framework/etcd/lease.md) 管理带 TTL 的租约及其附加键，[watch](/docs/CS/Framework/etcd/watch.md) 则把键变更以事件流推送给监听方（含 synced / unsynced 两条队列）。

## Client, Network and API

对使用者而言，起点是 [client](/docs/CS/Framework/etcd/client.md)：clientv3 的连接管理、`isSafeRetry` 重试策略与认证。底层传输见 [net](/docs/CS/Framework/etcd/net.md)（gRPC server 与 peer 通信）；请求进入 server 后的拦截、`KVServer`、quota 限流与 `get`/`put` 内部流转见 [request](/docs/CS/Framework/etcd/request.md)。若需要 REST / JSON 或一层无状态代理，看 [gateway](/docs/CS/Framework/etcd/gateway.md)——它区分 gRPC-gateway（需单独进程暴露 REST）与 grpc-proxy（L7 代理，可做 watch / lease 合并与 namespace）。基于 etcd 自身实现服务发现，见 [naming](/docs/CS/Framework/etcd/naming.md)（gRPC resolver + endpoints，借助 `WithLease` 自动下线）。读请求的一致性语义单独拆在 [read](/docs/CS/Framework/etcd/read.md)：linearizable 走 ReadIndex，serializable 直接读本地。

## Distributed Coordination Primitives

在客户端之上，[concurrency](/docs/CS/Framework/etcd/concurrency.md) 提供开箱即用的分布式原语：`Session`、`Mutex`（含 `NewLocker`）、`STM`、`Election`，默认隔离级别 `SerializableSnapshot`。注意 clientv3 并发包没有 Queue 实现。

## Security

[security](/docs/CS/Framework/etcd/security.md) 横切传输与访问：TLS 加密、认证（auth）与 RBAC 鉴权。它与 [compare](/docs/CS/Framework/etcd/compare.md) 中提到的"etcd 实现 RBAC、ZooKeeper / Consul 仅 ACL"形成对照。

## Production Operations

落地到生产，四篇互为补充：[cluster](/docs/CS/Framework/etcd/cluster.md) 讲成员变更、快照备份恢复与 learner；[monitoring](/docs/CS/Framework/etcd/monitoring.md) 讲 Prometheus 指标与告警阈值；[troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 汇总常见故障（如 `database space exceeded`、成员异常）；[tuning](/docs/CS/Framework/etcd/tuning.md) 汇总运维调优旋钮与默认值（如 `--snapshot-count`、`/livez`、`/readyz`）。

## Form and Version

[embed](/docs/CS/Framework/etcd/embed.md) 覆盖嵌入式形态；[v2](/docs/CS/Framework/etcd/v2.md) 讲 v2 与 v3 的差异、迁移路径，以及 3.6 起移除 v2 的事实；[compare](/docs/CS/Framework/etcd/compare.md) 把 etcd 与 ZooKeeper / Nacos / Consul 在共识算法、一致性读、权限、事务、多数据中心等维度做横向对比。

## Links

- [etcd（概念枢纽）](/docs/CS/Framework/etcd/etcd.md)
- [boot（启动与生命周期）](/docs/CS/Framework/etcd/boot.md)
- [request（请求处理路径）](/docs/CS/Framework/etcd/request.md)
- [features（服务发现 / 事务）](/docs/CS/Framework/etcd/features.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [K8s](/docs/CS/Container/k8s/K8s.md)

## References

1. [etcd 官方文档](https://etcd.io/docs/)
2. [深入浅出 etcd 系列 part 1 – 解析 etcd 的架构和代码框架](https://mp.weixin.qq.com/s/C2WKrfcJ1sVQuSxlpi6uNQ)
3. [深入浅出etcd/raft —— 0x00 引言](https://blog.mrcroxx.com/posts/code-reading/etcdraft-made-simple/0-introduction/)
