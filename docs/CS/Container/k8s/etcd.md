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

## Key Layout and Encoding

key 不是随机生成的，由 `etcd3store.go` 两层前缀拼出：

```go
// staging/src/k8s.io/apiserver/pkg/storage/etcd3/store.go:148
func New(c *kubernetes.Client, compactor Compactor, codec runtime.Codec,
	newFunc, newListFunc func() runtime.Object, prefix, resourcePrefix string, ...) (*store, error) {
	// no-op for default prefix of '/registry'.
	pathPrefix := path.Join("/", prefix)
	...
}
```

- `prefix` 是全局前缀，由 `--etcd-prefix` 控制（默认 `/registry`）；
- `resourcePrefix` 是资源类型前缀，例如 `pods`、`secrets`；
- 落库时 `prepareKey`（`:1116`）把三者拼成 `/registry/pods/default/my-pod`。

于是 etcd 的一个 `WithPrefix()` range 就等价于"列出某类资源"，namespace 只是 key 路径中的一段——**K8s 的 namespace 隔离在存储层就是前缀隔离**，没有独立的表或租户概念。这也解释了为什么按 namespace 列出是高效操作，而按 label 列出只能全量拉回再在 apiserver 侧过滤。

### Storage Media Type

`--storage-media-type` 的**代码默认值是 `application/json`**（`staging/src/k8s.io/apiserver/pkg/server/options/etcd.go:81`），但落到具体某类资源用什么 codec，取决于该资源 store 构造时传入的 codec，而不是这个 flag 单独决定。这就是为什么直接 `etcdctl get` 常常看到二进制而非 JSON——内建资源用的是 protobuf 编解码。

判断某类资源实际存成什么，只能看该资源的 store 构造，不能只看 flag。

### Encryption at Rest

> [!WARNING]
> **默认不加密。** 静态加密必须显式提供 `EncryptionConfiguration` 并给资源指定 provider（默认 provider 是 identity，即原样存储）。etcd 备份或磁盘泄露时明文可读，这在多数发行版里都是需要主动加固的项。

envelope（信封）加密的格式很紧凑（`storage/value/encrypt/envelope/envelope.go:81`）：

```
[ uint16 加密后 DEK 的长度 ][ 加密后的 DEK ][ 用该 DEK 加密的数据 ]
```

三个实现要点：

1. **每条数据一个 DEK**：`TransformToStorage` 每次都 `generateKey(32)`（256 位）新生成，用 KEK（KMS 或本地密钥）加密后前置在密文里；
2. **DEK 不是每条都去问 KMS**：已解密的 DEK 放在 LRU 缓存里（`cacheSize > 0` 时，`envelope.go:71`），读多写少的场景下 KMS 调用量远小于请求量；
3. **长度前缀用 uint16 而不是 uint8**，因为 256 位密钥的长度放不进单字节（源码注释明确写了这个原因）。

密钥轮换的实际效果是：新写入用新 KEK，旧数据仍用旧 KEK 解密，因此**必须保留旧密钥直到所有数据被重写**，通常需要跑一次全量 rewrite。

## Compaction and the resourceVersion Lifecycle

etcd 保留每个 key 的历史版本，revision 单调增长；`compact` 把某个 revision 之前的历史全部丢弃。三者串起来的关系是：

```
写入 → revision 递增 → watch 从任意历史 revision 续接
                    → compact(rv) 之后 rv 之前的历史不可再读
                    → 客户端拿着过旧 RV 来 watch → 410 Gone，只能重新 List
```

apiserver 侧由 `--etcd-compaction-interval` 控制压缩节奏（0 表示禁用；`etcd.go:193`）。压缩与 watch cache 的滑动窗口是两件事：compact 决定 etcd 里还能回溯多远，watch cache 决定 apiserver 内存里还能回溯多远——**客户端先撞到哪个，就先报哪个的错**。区分见 [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)。

## Lease and TTL

etcd 的 lease 在 K8s 里用得非常克制：`store.Create` 只在 `ttl != 0` 时才申请（`etcd3store.go:301`），绝大多数资源 ttl 为 0，即永不自动过期。

真正依赖它的是 Event——`lease_manager.go:53` 处的注释直接写着"since all the events have the same ttl"。问题是每个 Event 都 Grant 一次 lease 会打爆 etcd，所以有个复用机制（`lease_manager.go:90`）：

```go
reuseDurationSeconds := l.getReuseDurationSecondsLocked(ttl)   // min(ttl*5%, 60s)
valid      := now.Add(ttl).Before(l.prevLeaseExpirationTime)
sufficient := now.Add(ttl + reuseDurationSeconds).After(l.prevLeaseExpirationTime)
if valid && sufficient && l.leaseAttachedObjectCount <= l.leaseMaxAttachedObjectCount {
	return l.prevLeaseID, nil    // 复用上一个 lease
}
ttl += reuseDurationSeconds
lcr, err := l.client.Lease.Grant(ctx, ttl)
```

即：复用窗口取 `min(ttl*5%, 60s)`（`defaultLeaseReuseDurationSeconds = 60`，`:29`），Grant 时额外多申请一段，且单个 lease 上挂载的对象数有上限。这样同一时刻产生的一批 Event 共享一个 lease，过期时间略晚于各自 ttl。

> [!NOTE]
> 注意区分两个"ttl"：这里是**etcd lease 的 TTL**，用于让 Event 自动消失；`Lease` 这个 K8s 资源（`coordination.k8s.io`）是节点心跳与 leader election 用的，两者完全不同。

## Storage Version Migration

同一资源会有多个 version（`v1`、`v1beta1`…），但 etcd 里只存**一个**——storage version。升级 K8s 时若 storage version 变了，已存在的数据仍是旧版本格式，需要迁移。

APIService / CRD 的 `status.storageVersions` 记录各 apiserver 实例实际在用什么版本；v1.36 的 controller-manager 里新增了 `storageversionmigrator` 控制器来驱动改写。迁移本质是"读出来按新 storage version 写回去"，会产生大量写请求，因此必须在低峰期做，并先确认 etcd 有足够空间承接 compaction 前的版本堆积。

## Operations Key Points

- **容量与压缩**：etcd 默认 2GB 告警 / 8GB 上限，MVCC 历史版本靠 [compact](/docs/CS/Framework/etcd/compact.md) 回收，K8s 的 apiserver 每 5 分钟自动 compaction 一次。
- **大对象**：etcd 单条 value 默认上限 1.5MB，因此 ConfigMap 上限 1MB——往 ConfigMap 塞大文件是常见翻车点。
- **备份**：`etcdctl snapshot save` 恢复后集群内证书、节点身份等也随之回滚，恢复是有版本回退语义的，不是无损操作。
- **性能**：watch fan-out 大时瓶颈通常在 apiserver 而非 etcd；etcd 本身建议 SSD + 独立部署，见 [raft](/docs/CS/Framework/etcd/raft.md) 对写路径的分析。

## Links

- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [etcd lease](/docs/CS/Framework/etcd/lease.md)
- [etcd 安全](/docs/CS/Framework/etcd/security.md)
- [etcd watch](/docs/CS/Framework/etcd/watch.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [kube-apiserver v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/cmd/kube-apiserver)
2. [Operating etcd clusters for Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/)
3. [Encrypting Secret data at rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
4. [Using a KMS provider for data encryption](https://kubernetes.io/docs/tasks/administer-cluster/kms-provider/)
5. [etcd storage limits and options](https://etcd.io/docs/latest/op-guide/configuration/)
