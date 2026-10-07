## Introduction

[client.md](/docs/CS/Framework/etcd/client.md) 讲过的 `EtcdManualResolver` 是**手工**模式：端点列表在 `clientv3.Config.Endpoints` 里写死，要更新只能调 `SetEndpoints` 或靠 `AutoSyncInterval` 周期性拉 `MemberList`。这在成员会变动的生产集群里很别扭——扩缩容后客户端拿到的还是旧地址。

etcd 自带一套基于 **Watch** 的服务发现原语，位于 `go.etcd.io/etcd/client/v3/naming`：服务端把"我这个实例的地址"写进 etcd 的某个 key 前缀，客户端用一个 gRPC `resolver.Builder` 去 **Watch 这个前缀**，端点一变就自动 `cc.UpdateState`，对上层 gRPC 调用完全无感。这叫 **watch 式服务发现**，和 `EtcdManualResolver` 的静态解析是两套东西。

> [!NOTE]
> 这套机制的本质就是「把 endpoints 当作 etcd 里普通 KV 存，再用 Watch 感知变化」。没有任何黑魔法——`endpoints_impl.go` 里的 `Update` 就是把注册/注销翻译成 `clientv3.OpPut` / `clientv3.OpDelete`，`NewWatchChannel` 就是先 `Get(prefix)` 拿全量、再 `Watch(prefix)` 拿增量。

> [!NOTE]
> **版本基线**：etcd **3.7.2**。`client/v3/naming` 在 3.7.2 **完整存在**（`doc.go` + `endpoints/` + `resolver/`），接口与早期版本一致，无需迁移。`Endpoint` 结构的两个字段自 **etcd 3.1** 起就是这个形状（源码注释即标 `Since etcd 3.1`）。`naming/resolver` 需 grpc-go 提供 `resolver.Builder`，与 grpc-go 版本有耦合，升级 grpc-go 时一并验证。

## Two-Phase API

naming 包拆成两个子包，职责分离得很干净：

- **`naming/endpoints`** —— 服务**注册方**（provider）用的 `Manager`：往 etcd 写/删/列 endpoint。
- **`naming/resolver`** —— 服务**消费方**（client）用的 `Builder`：把 endpoint 变化喂给 gRPC 连接。

一个 prefix（如 `/services/foo`）对应一个"服务"，该 prefix 下的所有 key 就是该服务的可用实例。

### endpoints.Manager (Registration Side)

`Manager` 接口（源码 `client/v3/naming/endpoints/endpoints.go`）：

```go
type Manager interface {
    Update(ctx context.Context, updates []*UpdateWithOpts) error
    AddEndpoint(ctx context.Context, key string, endpoint Endpoint, opts ...clientv3.OpOption) error
    DeleteEndpoint(ctx context.Context, key string, opts ...clientv3.OpOption) error
    List(ctx context.Context) (Key2EndpointMap, error)
    NewWatchChannel(ctx context.Context) (WatchChannel, error)
}

type Endpoint struct {
    Addr     string // 自 etcd 3.1：可被 dial 的server地址，如 "1.2.3.4:2380"
    Metadata any    // 自 etcd 3.1：附在地址上的元数据
}
```

注册一个实例：

```go
em, _ := endpoints.NewManager(client, "/services/foo")
// key 习惯写成 <prefix>/<addr>，value 是 Endpoint 的 JSON
em.AddEndpoint(ctx, "/services/foo/1.2.3.4:2380",
    endpoints.Endpoint{Addr: "1.2.3.4:2380"})
```

底层 `Update`（`endpoints/endpoints_impl.go:56`）把每个 `UpdateWithOpts` 翻译成 etcd 事务：

```go
case Add:    ops = append(ops, clientv3.OpPut(update.Key, string(v), update.Opts...))
case Delete: ops = append(ops, clientv3.OpDelete(update.Key, update.Opts...))
```

`opts` 是透传的，所以可以带 `clientv3.WithLease(leaseID)`——**把 endpoint 挂到一个 lease 上，实例进程挂了 lease 不续期，endpoint 自动从 etcd 里消失，消费方 Watch 到 Delete 后摘掉这个实例**。这是优雅下线的标准做法，比显式 `DeleteEndpoint` 更可靠（不怕进程被 kill 来不及注销）。

### resolver.Builder (Consumer Side)

`resolver.NewBuilder(client)` 返回一个 gRPC `resolver.Builder`，scheme 固定是 `"etcd"`：

```go
b, _ := resolver.NewBuilder(client)
conn, _ := grpc.Dial(
    "etcd:///<prefix>",                  // target.URL.Path 去掉前导/就是 Manager 的 target
    grpc.WithResolvers(b),               // 关键：把 etcd builder 注册进 gRPC
    grpc.WithTransportCredentials(...),
)
// 之后用 conn 发的 RPC，地址由 resolver 自动维护
```

`Build`（`naming/resolver/resolver.go:34`）里做三件事：

1. 从 `target.URL.Path` 取出 prefix（去掉前导 `/`）；
2. `endpoints.NewManager(c, prefix)` 然后 `em.NewWatchChannel(ctx)` 拿到监听 channel；
3. 起一个 `watch()` goroutine，把每次 `Update` 累积进 `allUps` map，变化即 `cc.UpdateState(gresolver.State{Endpoints: eps})`。

所以 gRPC 层看到的 endpoint 列表永远和 etcd 里 `/services/foo` 前缀下的 key 一致，**成员扩缩容、实例上下线都不需要重启客户端**。

> [!WARNING]
> 这套 watch 式发现依赖 etcd 本身健康。如果 etcd 集群整体不可用，`NewWatchChannel` 拿不到全量、或 Watch 中断，gRPC 会保留最后一次 `UpdateState` 的地址（不会主动清空），已经建立的连接照常工作，只是拿不到新端点。它解决的是「etcd 活着但成员列表在变」的场景，不是「etcd 挂了」的场景——后者要靠 [client.md](/docs/CS/Framework/etcd/client.md) 的 `AutoSyncInterval` / 多 `Endpoints` 兜底。

## Complete Example

服务端（provider）注册并租约保活：

```go
cli, _ := clientv3.New(clientv3.Config{Endpoints: []string{"127.0.0.1:2379"}})
em, _ := endpoints.NewManager(cli, "/services/foo")

// 用 lease 自动下线
resp, _ := cli.Grant(ctx, 10) // TTL 10s
em.AddEndpoint(ctx, "/services/foo/10.0.0.1:8080",
    endpoints.Endpoint{Addr: "10.0.0.1:8080"},
    clientv3.WithLease(resp.ID))
// 实践中用 concurrency.NewSession 或手动 KeepAlive 维持这个 lease
```

客户端（consumer）解析：

```go
conn, _ := grpc.Dial("etcd:///services/foo",
    grpc.WithResolvers(resolver.NewBuilder(cli)),
    grpc.WithTransportCredentials(insecure.NewCredentials()))
greeter.NewGreeterClient(conn).SayHello(ctx, &greeter.HelloRequest{Name: "vito"})
```

## Relationship with Surrounding Mechanisms

- **vs `EtcdManualResolver`**：`client.md` 的 manual resolver 是静态 target（`http://ip:port`），地址在 `Config.Endpoints` 里定死；naming/resolver 是动态的、基于 Watch。选型：集群固定且客户端会随集群一起重启 → manual + `AutoSyncInterval` 够用；集群成员频繁变 → 上 naming/resolver。
- **vs [grpc-proxy](/docs/CS/Framework/etcd/gateway.md)**：grpc-proxy 的 `--resolver-prefix` / `--resolver-ttl` 也是基于这个 naming 机制做 proxy 自身的 endpoint 自动刷新——proxy 作为 consumer 去 Watch 一个 prefix，背后的真实 etcd 成员变了，proxy 自动重连。两者同源。
- **vs [cluster.md](/docs/CS/Framework/etcd/cluster.md) 的静态 endpoints**：cluster 运维讲的是成员增删的 Raft 层操作；naming 是**业务层**的服务发现，存的是业务实例地址，和 etcd 集群成员不是一回事，但实现原理都是「KV + Watch」。

## Pitfall List

> [!WARNING]
> 这套 API 看着简单，几个位置最容易写错：

1. **target 的 path 必须带前导斜杠，且 prefix 会被 `TrimPrefix` 去掉** —— `Build` 里对 `target.URL.Path` 做 `strings.TrimPrefix(..., "/")` 再交给 `NewManager`。所以 `"etcd:///services/foo"` 与 `"etcd://services/foo"` 行为不同，别图省事省掉第三个斜杠。
2. **`grpc.WithResolvers(b)` 不能忘** —— `NewBuilder` 只是造一个 `resolver.Builder`，不注册进 grpc 就不生效，dial 会报 scheme 未注册。
3. **scheme 固定是 `"etcd"`，不能改** —— 也没有内置的 fallback scheme（不像 `dns:///` 那样可以多写几个地址做多地址解析）。
4. **别用 `EndPoint` / `endpoints_manager` 这类旧名** —— 现行的包路径是 `client/v3/naming/endpoints` 与 `client/v3/naming/resolver`（`Manager` 接口在 `endpoints/endpoints.go`）。网上残留的老示例里的包路径已不存在。
5. **etcd 整体挂掉时 resolver 不会清空地址** —— gRPC 保留最后一次 `UpdateState` 的结果（见上方 WARNING），这是设计而非 bug；兜底要靠多 `Endpoints` + `AutoSyncInterval`。
6. **注册方必须自己维持 lease** —— `WithLease` 只是挂上，进程不再 `KeepAlive` 才自动消失。用 `concurrency.NewSession` 时注意 Session 默认 TTL 只有 60s（见 [concurrency.md](/docs/CS/Framework/etcd/concurrency.md)），显式设 TTL 更安全。

## Links

- [client（客户端配置与 resolver）](/docs/CS/Framework/etcd/client.md)
- [gateway（grpc-proxy 的 resolver-prefix）](/docs/CS/Framework/etcd/gateway.md)
- [cluster（成员 endpoints 与扩缩容）](/docs/CS/Framework/etcd/cluster.md)

## References

1. [etcd client/v3/naming/resolver — resolver.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/naming/resolver/resolver.go)
2. [etcd client/v3/naming/endpoints — endpoints.go / endpoints_impl.go](https://github.com/etcd-io/etcd/blob/v3.7.2/client/v3/naming/endpoints/)
3. [gRPC Name Resolution (resolver package)](https://github.com/grpc/grpc-go/blob/master/resolver/resolver.go)
