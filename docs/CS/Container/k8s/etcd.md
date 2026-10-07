## Introduction

Kubernetes 系统对 [Etcd](/docs/CS/Framework/etcd/etcd.md) 存储进行了大量封装，其架构是分层的，而每一层的封装设计又拥有高度的可扩展性。

etcd 是 K8s 唯一的有状态依赖：除短暂缓存外，集群的所有状态（Pod、Service、Secret、CRD……）都保存在 etcd 中。apiserver 是唯一与 etcd 通信的组件，其他组件（scheduler、controller-manager、kubelet）都只通过 apiserver 的 REST/watch API 读写集群状态——这让 etcd 的读写模式非常规整：**读多写少、按 key 前缀（`/registry/`）组织、强一致读 + 大量 watch**。

## Storage Tiering

从下到上大致分为四层：

```
┌────────────────────────────────────────────┐
│ API 层：REST 资源 (Pod/Service/...) + Watch │
├────────────────────────────────────────────┤
│ Registry 层：Scheme/GVK ↔ 存储对象的映射     │
├────────────────────────────────────────────┤
│ Store 层 (storage/cacher)：                 │
│   watch cache（内存） + 底层 store 接口      │
├────────────────────────────────────────────┤
│ etcd3 层：key 编码 (/registry/pods/...)     │
│   value = protobuf + envelope 加密          │
└────────────────────────────────────────────┘
```

- **key 设计**：K8s 资源在 etcd 中的 key 形如 `/registry/pods/default/my-pod`，一个大前缀 `/registry/` 下按资源类型分目录。etcd 的范围查询（range）天然支持"列出某类资源"。
- **value 编码**：对象序列化为 protobuf；Secret 可启用 EncryptionConfiguration 做 envelope 加密（KEK 存在 KMS 或本地文件）。
- **resourceVersion**：直接映射到 etcd 的 MVCC revision（全局单调递增）。list/watch 的增量同步、乐观并发控制（`resourceVersion` 冲突检测）都建立在它之上，详见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)。

## Watch and Informer

apiserver 会为每类资源维护一个 **watch cache**（`storage/cacher`）：客户端的 list/watch 请求优先由内存 cache 服务，避免打穿到 etcd。Informer 机制（见 [client-go](/docs/CS/Container/k8s/client-go.md)）在此基础上工作：

1. Informer 先 List 拿全量快照（带 resourceVersion）；
2. 之后 Watch 从该 resourceVersion 开始收增量事件；
3. 若 watch 断开且 resourceVersion 过旧（已被 compaction），收到 `410 Gone`，触发重新 List。

这条链路决定了 K8s 组件间最终一致的收敛速度，也是 [controller-manager](/docs/CS/Container/k8s/controller-manager.md) 声明式调和的基础。

### Steps 1 and 2 Usually Do Not Hit etcd

上面是客户端视角。从 apiserver 侧看，**List 与 Watch 的绝大多数请求根本不碰 etcd**：每个 group-resource 只有一个 `Cacher`，它先从 etcd 拉一次全量（分页 10000），之后持续 watch；客户端的所有读请求都由内存里的 watch cache 服务。所以"etcd 是唯一事实来源"成立，"每次 list/watch 都要读 etcd"不成立——读放大的成本落在 apiserver 内存上，且与 informer 数量无关，只与被 watch 的资源种类数有关。

`resourceVersion` 的语义要在这个前提下才说得通：它是 etcd 的单调 revision，但服务端可能在**内存缓存**上回答一段 RV 区间内的请求。什么时候能这么做、什么时候必须透传 etcd，以及 `410 Gone` 与 `504` 分别意味着什么，见 [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)。

## Operations Key Points

- **容量与压缩**：etcd 默认 2GB 告警 / 8GB 上限，MVCC 历史版本靠 [compact](/docs/CS/Framework/etcd/compact.md) 回收，K8s 的 apiserver 每 5 分钟自动 compaction 一次。
- **大对象**：etcd 单条 value 默认上限 1.5MB，因此 ConfigMap 上限 1MB——往 ConfigMap 塞大文件是常见翻车点。
- **备份**：`etcdctl snapshot save` 恢复后集群内证书、节点身份等也随之回滚，恢复是有版本回退语义的，不是无损操作。
- **性能**：watch fan-out 大时瓶颈通常在 apiserver 而非 etcd；etcd 本身建议 SSD + 独立部署，见 [raft](/docs/CS/Framework/etcd/raft.md) 对写路径的分析。

## Links

- [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [watch](/docs/CS/Framework/etcd/watch.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
