## Introduction

etcd 是 Kubernetes 的默认后端存储，也是一个通用的强一致键值仓库。本目录按“从对外 API 到底层存储”的纵向分层组织笔记；[etcd](/docs/CS/Framework/etcd/etcd.md) 原本是承载全部细节的单一长文，现按“启动 → 请求 → 特性”拆为中心枢纽 + 分册，避免与 [raft](/docs/CS/Framework/etcd/raft.md) / [net](/docs/CS/Framework/etcd/net.md) 等已成熟的分册重复。

> [!NOTE]
> **版本基线**：etcd **3.7.2**（维护线 3.6.15 / 3.5.34），生产建议 3.5.x。v3.6 起 `--enable-v2` 与 `experimental-enable-v2v3` 已移除；默认配额 2 GB、建议上限 8 GB；`/livez`、`/readyz` 自 v3.5.12 引入。Raft 在 3.6 起外置为独立 module `go.etcd.io/raft/v3` v3.7.0，主仓库只剩调用侧。详见 [cluster.md](/docs/CS/Framework/etcd/cluster.md) 的版本基线表。

etcd 用 Go 编写，通过 [Raft](/docs/CS/Distributed/Consensus/Raft.md) 管理高可用复制日志；对外提供 gRPC API，并可选 TLS 与 RBAC。它还能提供服务发现、分布式锁、选举等协调原语。

## 分层导航

按“一次写请求自上而下经过的主链路”阅读，建议顺序是「启动与生命周期 → 请求处理路径 → Raft 共识 → MVCC 存储 → 协调原语 / 安全 / 运维 / 横向对比」：

- **启动与生命周期** —— [boot](/docs/CS/Framework/etcd/boot.md)：构建部署、整体架构、v2/v3 数据模型、`start → startEtcd → NewServer → serveClients → run` 启动链，以及启动时如何把外置 Raft 接线进来。
- **请求处理路径** —— [request](/docs/CS/Framework/etcd/request.md)：gRPC 拦截器、`KVServer`、quota 请求限流（`ErrTooManyRequests` / `MaxRequestBytes` / 7s 超时），以及 `get` / `put` 在 etcd 内部的全链路（propose → Raft → apply → 通知客户端）。
- **共识层 Raft** —— [raft](/docs/CS/Framework/etcd/raft.md)（外置库的调用侧、`Ready` 五步消费、落盘、线性读）与 [tracker](/docs/CS/Framework/etcd/tracker.md)（ProgressTracker / 流控）。
- **KV 状态机 / MVCC 存储** —— [MVCC](/docs/CS/Framework/etcd/MVCC.md)、[treeIndex](/docs/CS/Framework/etcd/treeIndex.md)、[boltdb](/docs/CS/Framework/etcd/boltdb.md)、[compact](/docs/CS/Framework/etcd/compact.md)、[lease](/docs/CS/Framework/etcd/lease.md)、[watch](/docs/CS/Framework/etcd/watch.md)。
- **客户端与 API 接入** —— [client](/docs/CS/Framework/etcd/client.md)、[net](/docs/CS/Framework/etcd/net.md)（gRPC 传输与 Peer）、[gateway](/docs/CS/Framework/etcd/gateway.md)、[naming](/docs/CS/Framework/etcd/naming.md)、[read](/docs/CS/Framework/etcd/read.md)（线性读 / 串行读语义）。
- **协调原语 / 安全 / 运维** —— [concurrency](/docs/CS/Framework/etcd/concurrency.md)（锁 / 选举 / STM）、[security](/docs/CS/Framework/etcd/security.md)（TLS / 认证 / RBAC）、[cluster](/docs/CS/Framework/etcd/cluster.md)、[monitoring](/docs/CS/Framework/etcd/monitoring.md)、[troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)、[tuning](/docs/CS/Framework/etcd/tuning.md)。
- **形态与版本 / 高层特性** —— [embed](/docs/CS/Framework/etcd/embed.md)、[v2](/docs/CS/Framework/etcd/v2.md)、[features](/docs/CS/Framework/etcd/features.md)（服务发现 / 事务）、[compare](/docs/CS/Framework/etcd/compare.md)（etcd / ZooKeeper / Nacos / Consul）。

完整的分层架构图与逐页索引见 [etcd 目录 README](/docs/CS/Framework/etcd/README.md)。

## Links

- [etcd 目录索引（按层导航）](/docs/CS/Framework/etcd/README.md)
- [boot（启动与生命周期）](/docs/CS/Framework/etcd/boot.md)
- [request（请求处理路径）](/docs/CS/Framework/etcd/request.md)
- [features（服务发现 / 事务）](/docs/CS/Framework/etcd/features.md)
- [raft（共识模块）](/docs/CS/Framework/etcd/raft.md)
- [net（gRPC 传输与 Peer）](/docs/CS/Framework/etcd/net.md)
- [MVCC（多版本并发控制）](/docs/CS/Framework/etcd/MVCC.md)
- [boltdb（底层存储引擎）](/docs/CS/Framework/etcd/boltdb.md)
- [client（客户端与重试）](/docs/CS/Framework/etcd/client.md)
- [read（线性读 / 串行读语义）](/docs/CS/Framework/etcd/read.md)
- [cluster（集群运维与备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [compare（etcd / ZooKeeper / Nacos / Consul 对比）](/docs/CS/Framework/etcd/compare.md)
- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)

## References

1. [etcd 官方文档](https://etcd.io/docs/)
2. [深入浅出 etcd 系列 part 1 – 解析 etcd 的架构和代码框架](https://mp.weixin.qq.com/s/C2WKrfcJ1sVQuSxlpi6uNQ)
3. [深入浅出etcd/raft —— 0x00 引言](https://blog.mrcroxx.com/posts/code-reading/etcdraft-made-simple/0-introduction/)
4. [etcd 原理解析：读etcd 技术内幕](http://www.xuyasong.com/?p=1706)
