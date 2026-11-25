## Introduction

etcd 是 Kubernetes 的默认后端存储，也是一个通用的强一致键值仓库。本页是 etcd 家族的入口，负责版本基线、阅读顺序与分册导航；具体机制按“启动 → 请求 → 共识 → 存储 → 特性”拆开，避免与 [raft](/docs/CS/Framework/etcd/raft.md) / [net](/docs/CS/Framework/etcd/net.md) 等成熟分册重复。

> [!NOTE]
> **版本基线**：etcd **3.7.2**，Raft 在 3.6 起外置为 `go.etcd.io/raft/v3`，本基线使用 **v3.7.0**。默认配额 2 GiB、建议上限 8 GiB；`/livez`、`/readyz` 自 v3.5.12 引入；3.6 起移除 v2 启用开关。生产版本应结合 Kubernetes 与客户端兼容矩阵选择，不把本文的源码基线等同于部署建议。详见 [cluster](/docs/CS/Framework/etcd/cluster.md) 的版本基线表。

etcd 用 Go 编写，通过 [Raft](/docs/CS/Distributed/Consensus/Raft.md) 管理高可用复制日志；对外提供 gRPC API，并可选 TLS 与 RBAC。它还能提供服务发现、分布式锁、选举等协调原语。

## 分层导航

按“一次写请求自上而下经过的主链路”阅读，建议顺序是「启动与生命周期 → 请求处理路径 → 跨层主链 → Raft 共识 → MVCC 存储 → 协调原语 / 安全 / 运维 / 横向对比」：

- **启动与生命周期** —— [boot](/docs/CS/Framework/etcd/boot.md)：构建部署、整体架构、v2/v3 数据模型、`start → startEtcd → NewServer → serveClients → run` 启动链，以及启动时如何把外置 Raft 接线进来。
- **请求处理路径** —— [request](/docs/CS/Framework/etcd/request.md)：gRPC 拦截器、`KVServer`、quota 请求限流（`ErrTooManyRequests` / `MaxRequestBytes` / 7s 超时），以及 `get` / `put` 在 etcd 内部的全链路（propose → Raft → apply → 通知客户端）。
- **跨层主链** —— [Core_Mechanisms](/docs/CS/Framework/etcd/Core_Mechanisms.md)：以 v3.7.2 源码贯通 `Propose → Raft → Apply → MVCC → Watch / Read → Recovery`，讲清 committed/applied、三套序号、并发与持久化边界、故障恢复和反直觉行为。
- **共识层 Raft** —— [raft](/docs/CS/Framework/etcd/raft.md)（外置库的调用侧、`Ready` 五步消费、落盘、线性读）与 [tracker](/docs/CS/Framework/etcd/tracker.md)（ProgressTracker / 流控）。
- **KV 状态机 / MVCC 存储** —— [MVCC](/docs/CS/Framework/etcd/MVCC.md)、[treeIndex](/docs/CS/Framework/etcd/treeIndex.md)、[boltdb](/docs/CS/Framework/etcd/boltdb.md)、[compact](/docs/CS/Framework/etcd/compact.md)、[lease](/docs/CS/Framework/etcd/lease.md)、[watch](/docs/CS/Framework/etcd/watch.md)。
- **客户端与 API 接入** —— [client](/docs/CS/Framework/etcd/client.md)、[net](/docs/CS/Framework/etcd/net.md)（gRPC 传输与 Peer）、[gateway](/docs/CS/Framework/etcd/gateway.md)、[naming](/docs/CS/Framework/etcd/naming.md)、[read](/docs/CS/Framework/etcd/read.md)（线性读 / 串行读语义）。
- **协调原语 / 安全 / 运维** —— [concurrency](/docs/CS/Framework/etcd/concurrency.md)（锁 / 选举 / STM）、[security](/docs/CS/Framework/etcd/security.md)（TLS / 认证 / RBAC）、[cluster](/docs/CS/Framework/etcd/cluster.md)、[monitoring](/docs/CS/Framework/etcd/monitoring.md)、[troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)、[tuning](/docs/CS/Framework/etcd/tuning.md)。
- **形态与版本 / 高层特性** —— [embed](/docs/CS/Framework/etcd/embed.md)、[v2](/docs/CS/Framework/etcd/v2.md)、[features](/docs/CS/Framework/etcd/features.md)（服务发现 / 事务）、[compare](/docs/CS/Framework/etcd/compare.md)（etcd / ZooKeeper / Nacos / Consul）。

完整的分层架构图与逐页索引见 [etcd 目录 README](/docs/CS/Framework/etcd/README.md)。

## Links

- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [K8s](/docs/CS/Container/k8s/K8s.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Consul](/docs/CS/Framework/consul/README.md)

## References

1. [etcd 官方文档](https://etcd.io/docs/)
2. [深入浅出 etcd 系列 part 1 – 解析 etcd 的架构和代码框架](https://mp.weixin.qq.com/s/C2WKrfcJ1sVQuSxlpi6uNQ)
3. [深入浅出etcd/raft —— 0x00 引言](https://blog.mrcroxx.com/posts/code-reading/etcdraft-made-simple/0-introduction/)
4. [etcd 原理解析：读etcd 技术内幕](http://www.xuyasong.com/?p=1706)
