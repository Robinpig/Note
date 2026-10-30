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

## StorageFactory: Per-Resource Store Assembly

上面讲了 key/value 长什么样，但没说**谁决定**某个资源用什么 prefix、什么 codec、连哪个 etcd 集群。答案是 `DefaultStorageFactory`（`staging/.../server/storage/storage_factory.go`）。它是 apiserver 初始化阶段为每个 GVR 构建 `storagebackend.ConfigForResource` 的中心。

### 构建入口

构建链从 `NewStorageFactoryConfigEffectiveVersion`（`pkg/kubeapiserver/default_storage_factory_builder.go:70`）开始：

```go
// pkg/kubeapiserver/default_storage_factory_builder.go:95
return &StorageFactoryConfig{
    Serializer:                legacyscheme.Codecs,
    DefaultResourceEncoding:   serverstorage.NewDefaultResourceEncodingConfigForEffectiveVersion(...),
    ResourceEncodingOverrides: resources,   // 某些资源强制存成旧 version
}
```

然后 `.Complete(etcdOptions).New()` → `DefaultStorageFactory.NewConfig(groupResource, example)`（`storage_factory.go:229`），内部做五件事：

```
① getStorageGroupResource(groupResource)   — 找 cohabitating 伙伴（extensions/networking 共用 ingress）
② 合并 Overrides                          — prefix / etcdLocation / mediaType / serializer / encoderDecoratorFn
③ ResourceEncodingConfig.StorageEncodingFor(chosenStorageResource)   — storage version（存成哪个 GV）
④ ResourceEncodingConfig.InMemoryEncodingFor(groupResource)        — memory version（进程内用哪个 GV）
⑤ newStorageCodecFn(codecConfig)          — 组装 Codec + EncodeVersioner
```

最终返回一个 `*storagebackend.ConfigForResource`，它把原始 `storagebackend.Config`（etcd 连接参数 + 全局 prefix `/registry`）和 per-resource 的覆盖项拼在一起。

### Cohabitating Resources

一个经典坑：为什么 apps/extensions 的 Deployment 数据互相可见？答案在 `AddCohabitatingResources`（`default_storage_factory_builder.go:141`）：

```go
storageFactory.AddCohabitatingResources(
    networking.Resource("networkpolicies"), extensions.Resource("networkpolicies"),
    apps.Resource("deployments"), extensions.Resource("deployments"),
    ...
)
```

`getStorageGroupResource` 查 Overrides 时，如果一个资源有 cohabitating 伙伴且伙伴的 group 已启用，就用**伙伴的 GroupResource** 来查存储位置。这保证了 `apps/v1.Deployment` 和 `extensions/v1beta1.Deployment` 用同一个 etcd prefix 和 codec，数据物理上是同一份。

### Special Resource Prefixes

`SpecialDefaultResourcePrefixes`（`default_storage_factory_builder.go:46`）是另一组特殊映射：

```go
{Group: "", Resource: "nodes"}:          "minions"
{Group: "", Resource: "services"}:       "services/specs"
{Group: "networking.k8s.io", Resource: "ingresses"}: "ingress"
```

`nodes` 存成 `minions`、`services` 存成 `services/specs`——这些是历史遗留的目录名，`ResourcePrefix()` 在找不到 override 时会查这个 map，仍然找不到才退化成 `strings.ToLower(chosenStorageResource.Resource)`。

## etcd3 Store 源码：从 Object 到 Transaction

DefaultStorageFactory 产出的 `ConfigForResource` 最终被 `newETCD3Storage`（`staging/.../storagebackend/factory/etcd3.go:455`）消费，构造真正的 `etcd3.store`。这层封装是 K8s 到 etcd 的最后一跳。

### Store 组装

```go
// storagebackend/factory/etcd3.go:455
func newETCD3Storage(c storagebackend.ConfigForResource, newFunc, newListFunc func() runtime.Object, resourcePrefix string) (storage.Interface, DestroyFunc, error) {
    client, err := newETCD3Client(c.Transport)       // etcd clientv3 + kubernetes-mode 扩展
    client.KV = etcd3.NewETCDLatencyTracker(client.KV)  // 加延迟指标
    
    transformer := c.Transformer                     // identity + encryption 链
    if transformer == nil {
        transformer = identity.NewEncryptCheckTransformer()  // 默认：identity
    }
    
    store, err := etcd3.New(client, compactor, c.Codec, newFunc, newListFunc,
        c.Prefix, resourcePrefix, c.GroupResource, transformer, c.LeaseManagerConfig,
        decoder, versioner)
    
    return &CacheDelegator{cacher, store}, destroyFunc, nil  // 最终返回：Store → CacheDelegator 装饰
}
```

注意最终返回的不是裸 `*etcd3.store`，而是 `CacheDelegator` 装饰过的——这是"写请求绕过 Cacher、读请求分流"的关键设计点。

### etcd Client：Kubernetes-mode 扩展

v1.37.2 依赖 etcd v3.6，client 是标准 `clientv3.New(cfg)` 包了一层 `kubernetes.Client`（`vendor/go.etcd.io/etcd/client/v3/kubernetes/client.go:28`）。它只扩了 6 个方法：

```
OptimisticPut(ctx, key, value, expectedRevision, PutOptions)
OptimisticDelete(ctx, key, expectedRevision, DeleteOptions)
Get / List / Count
```

`OptimisticPut`（`kubernetes/client.go:83`）是整条封装链的核心：

```go
func (k Client) OptimisticPut(ctx context.Context, key string, value []byte,
    expectedRevision int64, opts PutOptions) (resp PutResponse, err error) {
    
    txn := k.KV.Txn(ctx).If(
        clientv3.Compare(clientv3.ModRevision(key), "=", expectedRevision),  // CAS 条件
    ).Then(
        clientv3.OpPut(key, string(value), clientv3.WithLease(opts.LeaseID)),
    )
    
    if opts.GetOnFailure {
        txn = txn.Else(clientv3.OpGet(key))   // 🔑 冲突时把当前值带回来
    }
    
    txnResp, _ := txn.Commit()
    resp.Succeeded = txnResp.Succeeded
    resp.Revision = txnResp.Header.Revision
    if opts.GetOnFailure && !txnResp.Succeeded {
        resp.KV = kvFromTxnResponse(txnResp.Responses[0])  // 当前值随响应返回
    }
    return
}
```

原来的手写事务是冲突后 apiserver 再发一次 Get，`GetOnFailure` 把这两步合并成一条——**省掉一次 GRT 和一次 etcd 往返**。

### Create 事务

store.Create（`etcd3/store.go:284`）的完整调用链：

```go
// 1. 前置检查
if version, err := s.versioner.ObjectResourceVersion(obj); err == nil && version != 0 {
    return storage.ErrResourceVersionSetOnCreate   // 客户端不能带 RV
}
s.versioner.PrepareObjectForStorage(obj)          // 清空 RV + SelfLink

// 2. 编码
data, _ := runtime.Encode(s.codec, obj)           // JSON/Protobuf 序列化

// 3. Transformer
newData, _ := s.transformer.TransformToStorage(ctx, data, authenticatedDataString(preparedKey))
//    identity.NewEncryptCheckTransformer() → 原样 + 校验是否真的加密了

// 4. 申请 Lease（ttl != 0 时，Event 专属）
var lease clientv3.LeaseID
if ttl != 0 { lease, _ = s.leaseManager.GetLease(ctx, int64(ttl)) }

// 5. etcd 事务 — 🔑 expectedRevision = 0 → Compare(ModRevision, "=", 0)
txnResp, _ := s.client.Kubernetes.OptimisticPut(ctx, preparedKey, newData, 0, kubernetes.PutOptions{LeaseID: lease})

if !txnResp.Succeeded {
    return storage.NewKeyExistsError(preparedKey, 0)   // 409 Conflict
}

// 6. 把 RV 写回对象
s.decoder.Decode(data, out, txnResp.Revision)     // ← 直接把 etcd revision 设成 metadata.resourceVersion
```

关键：`expectedRevision = 0` 在 etcd 中等价于"key 不存在"（ModRevision 是 etcd 的 key 创建/修改版本号，新 key 初始为 0），所以天然实现了 create 的幂等冲突检测。

### GuaranteedUpdate：Update / Patch / Delete 共用

所有修改类操作最终都收敛到 GuaranteedUpdate（`etcd3/store.go:473`），这是 K8s etcd 封装里最精巧的一段——**乐观锁 + 无锁重试 + "值未变短路"优化**：

```
for {
    ① preconditions.Check(preparedKey, origState.obj)    // ResourceVersion / UID 等前提
    ② ret, ttl, err := s.updateState(origState, tryUpdate)  // tryUpdate 是 strategy.PrepareForUpdate + admission 链
    ③ bytes.Equal(data, origState.data)?                  // 值没变化 → 短路：直接返回，不写 etcd
    ④ data = runtime.Encode(s.codec, ret)
    ⑤ newData = s.transformer.TransformToStorage(ctx, data, ...)
    ⑥ OptimisticPut(ctx, preparedKey, newData, origState.rev, {GetOnFailure: true})
       ├── Succeeded → decoder.Decode(data, dest, txnResp.Revision) → return nil
       └── 冲突 → txnResp.KV 已经是最新值 → getState 解出来 → origState = 最新值 → continue
}
```

"值未变短路"（第 ③ 步）是一个容易忽略的优化——如果 Update 后 JSON 序列化结果和 etcd 里已有的完全一样，直接返回，**连 etcd 事务都不发**。这在 SSA（Server-Side Apply）场景下很常见：客户端 apply 的字段没有变化，就不产生写放大。

冲突处理（第 ⑥ 步的 else）也很优雅——因为 `GetOnFailure: true`，etcd 直接把当前值放在事务的 Else 分支响应里返回，apiserver 拿到 `txnResp.KV` 后直接解出来当新的 `origState`，然后重新走一遍整个循环。**全程无锁**——所有并发更新靠 etcd 的 CAS 事务串行化。

### Delete 路径

Delete（`etcd3/store.go:352`）也复用 `OptimisticDelete`——和 OptimisticPut 对称：

```go
txn := k.KV.Txn(ctx).If(
    clientv3.Compare(clientv3.ModRevision(key), "=", expectedRevision),
).Then(clientv3.OpDelete(key))
```

它同样是 CAS + `GetOnFailure` 的模式，冲突时把当前值带回来让调用方重试。区别是 **Delete 不直接从 store.Delete 调用**——它先穿过 `CacheDelegator`，后者在调 etcd store.Delete 之前会先从自己的 watchCache 取一份当前对象当 `cachedExistingObject` 传下去。这样做的好处是 GuaranteedUpdate 里就能用缓存里的旧对象（而不是再 Get 一次 etcd）来做 preconditions 和 updateState。

## CacheDelegator: 读写分流

最终 REST Storage 拿到的不是裸 `*etcd3.store`，而是 `CacheDelegator` 装饰过的版本。它的分流逻辑（`cacher/delegator.go`）决定了请求走内存缓存还是透传 etcd：

```
Create / Update / Patch / Delete → 全部透传 store（绕过 Cacher）
                                   因为 Cacher 只会读 store 不会让 store 读它
                                   写请求 → etcd 事务 → 成功后 Cacher 通过自己的 watch 感知变化

Get:
  RV 未指定 → 透传 store     （兼容旧行为，拿到最新值）
  RV 指定  → 走 Cacher
    Cacher 未 ready → 透传 store   （防止缓存未初始化时返回空）

GetList (最复杂):
  delegator.ShouldDelegateList(opts, cacher) 判定
    ShouldDelegate = true  → 透传 store
      条件: resourceVersionMatch=Exact && RV 非空 && RV 不匹配 watch cache 滑窗
            或 limit/offset 组合需要从 etcd 算正确的 continue token
    ShouldDelegate = false → 走 Cacher
      ConsistentRead = true 时还有 TooLargeResourceVersion fallback
    Cacher 未 ready        → 透传 store

Watch → 始终走 Cacher.Watch
  （Cacher 自己就是在 etcd 上开了一条持续 watch，客户端的 watch 都由 Cacher 扇出）
```

"读请求优先走缓存、写请求始终透传"这个设计的好处：**写路径没有任何额外等待**（不用等 cache 同步），读路径享受缓存的低延迟，watch fan-out 由 apiserver 进程统一承担。

### Cacher 自身的初始化

每个 CacheDelegator 后面挂一个 Cacher（`cacher/cacher.go:264`），它初始化时：

1. 从 etcd 拉一次全量 List（默认分页 10000），填进内存的 btree；
2. 在 etcd 上开一条持续 Watch，把增量事件塞进 `incoming chan watchCacheEvent`；
3. 内部的事件分发循环从 `incoming` 取事件，更新 watchCache，然后扇出给所有等待的客户端 watcher。

这样 **N 个 informer × M 个资源种类** 被收敛成 **apiserver 进程内 M 条到 etcd 的 watch**。

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

## Transformer: Identity + Encryption 链

Store 的 `transformer` 字段是 apiserver 到 etcd 之间的**最后一层变换**——在编码之后、写入之前做加密，在读取之后、解码之前做解密。接口极简（`value/transformer.go:59`）：

```go
type Transformer interface {
    TransformToStorage(ctx, data, dataCtx) (out []byte, err error)
    TransformFromStorage(ctx, data, dataCtx) (out []byte, stale bool, err error)
}
```

注意 `stale` 返回值——它告诉 apiserver"我读到的是旧格式，应该趁这次顺便写回新格式"，这是密钥轮换时自动触发 rewrite 的关键信号。

### 默认：Identity + EncryptCheckTransformer

当 `StorageFactoryConfig` 没有显式提供 encryption transformer 时，`newETCD3Storage` 用 `identity.NewEncryptCheckTransformer()`（`etcd3.go:472`）。它做两件事：

1. **TransformToStorage**：原样返回 data，不加密；
2. **TransformFromStorage**：原样返回，但对有 `k8s:enc:` 前缀的数据**报错**——这意味着集群之前加密过但现在没配置加密，不能静默解密失败。

> [!WARNING]
> `EncryptCheckTransformer` 对"已有密文但配置缺失"是硬报错不是降级。集群从加密迁移到不加密必须先跑全量 rewrite 把密文都写回明文，再撤掉 EncryptionConfiguration。

### EncryptionConfiguration：按资源指定 Provider

用户通过 `--encryption-provider-config=encryption.conf` 提供 YAML，apiserver 启动时把它解析成 **`prefixTransformers`**（`value/transformer.go:81`）——这是一组按 **key prefix 匹配**的 transformer 链：

```go
type PrefixTransformer struct {
    Prefix      []byte       // k8s:enc:aescbc:v1:   或   (空，identity)
    Transformer Transformer  // envelope transformer  或   identity transformer
}
```

`prefixTransformers.TransformFromStorage`（`transformer.go:105`）按 prefix 匹配顺序尝试：

```go
for i, transformer := range t.transformers {
    if bytes.HasPrefix(data, transformer.Prefix) {
        result, stale, err := transformer.Transformer.TransformFromStorage(ctx, data[len(transformer.Prefix):], dataCtx)
        // 密钥轮换场景：匹配到的 transformer 不是列表第一个 → stale = true
        return result, stale || i != 0, err
    }
}
```

关键点：**从存储中读取时匹配到的 transformer 不是列表第一个，`stale` 就标记为 true**——apiserver 会把这个 stale 信号带到 GuaranteedUpdate，一旦后续触发写操作，就自动把对象用当前（第一个）provider 加密后写回。这就是"密钥轮换靠自然流量完成，不需要停机 rewrite"的实现机制。

`TransformToStorage`（`transformer.go:172`）始终用**列表第一个 transformer**，并在数据前加上它的 prefix：

```go
transformer := t.transformers[0]                  // 写入始终用第一个
result, _ := transformer.Transformer.TransformToStorage(ctx, data, dataCtx)
prefixedData := transformer.Prefix
prefixedData = append(prefixedData, result...)     // 前缀 + 加密后数据
return prefixedData, nil
```

### EncryptionConfiguration 到 prefixTransformers 的组装链

```
EncryptionConfiguration YAML
  → encryptionconfig.NewTransformerOverrides(file)
    → 遍历 resources：
      - each resource → 选定 provider
      - provider.NewTransformer() → PrefixTransformer{prefix, transformer}
    → 组 prefixTransformers 链（identity 在最后，作为 fallback）
  → storagebackend.Config.Transformer = 这条链
```

### 特殊资源绕过

某些资源（ClusterRole / ClusterRoleBinding / Role / RoleBinding）**强制不加密**——apiserver 不把它们注册进 encryption config，也不注册 transformer override。这是因为 RBAC 规则在集群升级期间可能被旧 apiserver 读取，旧版本不认识新的加密格式会导致集群启动失败。

## Links

- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [etcd lease](/docs/CS/Framework/etcd/lease.md)
- [etcd 安全](/docs/CS/Framework/etcd/security.md)
- [etcd watch](/docs/CS/Framework/etcd/watch.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [kube-apiserver v1.37.2 source (本地仓库)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/cmd/kube-apiserver)
2. [etcd client v3 kubernetes-mode vendor (本地仓库)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/vendor/go.etcd.io/etcd/client/v3/kubernetes)
3. [Operating etcd clusters for Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/)
4. [Encrypting Secret data at rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
5. [Using a KMS provider for data encryption](https://kubernetes.io/docs/tasks/administer-cluster/kms-provider/)
6. [etcd storage limits and options](https://etcd.io/docs/latest/op-guide/configuration/)
