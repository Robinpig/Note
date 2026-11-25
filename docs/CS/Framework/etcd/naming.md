# Naming

## Introduction

[client.md](/docs/CS/Framework/etcd/client.md) 里的 `EtcdManualResolver` 是**手工**模式：端点写死在 `clientv3.Config.Endpoints`，更新靠 `SetEndpoints` 或 `AutoSyncInterval` 周期性拉 `MemberList`。etcd 另有一套基于 **Watch** 的服务发现原语 `go.etcd.io/etcd/client/v3/naming`：服务端把实例地址写进某个 key 前缀，客户端用 gRPC `resolver.Builder` **Watch 这个前缀**，端点一变就 `cc.UpdateState`，对上层 RPC 完全无感。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

这套机制的本质是"把 endpoints 当普通 KV 存，再用 Watch 感知变化"：`Update` 把注册/注销翻译成 `clientv3.OpPut` / `OpDelete`，`NewWatchChannel` 先 `Get(prefix)` 拿全量再 `Watch(prefix)` 拿增量。反直觉点：

- **scheme 固定是 `"etcd"`，不能改**，也没有 `dns:///` 那样的多地址 fallback。
- **target path 会被 `TrimPrefix(..., "/")`**，所以 `"etcd:///services/foo"` 与 `"etcd://services/foo"` 行为不同。
- **etcd 整体挂掉时 resolver 不清空地址**——gRPC 保留最后一次 `UpdateState`，这是设计而非 bug。

## Two-Phase API

naming 拆成两个子包，职责分离：

- **`naming/endpoints`**：服务注册方（provider）用的 `Manager`，往 etcd 写/删/列 endpoint。
- **`naming/resolver`**：服务消费方（client）用的 `Builder`，把 endpoint 变化喂给 gRPC。

一个 prefix（如 `/services/foo`）对应一个"服务"，其下所有 key 是该服务的可用实例。

### endpoints.Manager

`Manager` 接口（`client/v3/naming/endpoints/endpoints.go`）定义在注册侧，`Endpoint` 自 etcd 3.1 起就是 `{Addr, Metadata}` 两字段：

```go
type Manager interface {
	Update(ctx context.Context, updates []*UpdateWithOpts) error
	AddEndpoint(ctx context.Context, key string, endpoint Endpoint, opts ...clientv3.OpOption) error
	DeleteEndpoint(ctx context.Context, key string, opts ...clientv3.OpOption) error
	List(ctx context.Context) (Key2EndpointMap, error)
	NewWatchChannel(ctx context.Context) (WatchChannel, error)
}

type Endpoint struct {
	Addr     string // 可被 dial 的 server 地址，如 "1.2.3.4:2380"
	Metadata any    // 附在地址上的元数据
}
```

底层 `Update`（`endpoints_impl.go`）先校验 key 前缀，再把每个更新翻译成 etcd 事务操作。`opts` 透传，所以可带 `clientv3.WithLease(leaseID)`：

```go
func (m *endpointManager) Update(ctx context.Context, updates []*UpdateWithOpts) (err error) {
	ops := make([]clientv3.Op, 0, len(updates))
	for _, update := range updates {
		if !strings.HasPrefix(update.Key, m.target+"/") {
			return status.Errorf(codes.InvalidArgument, "endpoints: endpoint key should be prefixed with '%s/' got: '%s'", m.target, update.Key)
		}
		switch update.Op {
		case Add:
			internalUpdate := &internal.Update{Op: internal.Add, Addr: update.Endpoint.Addr, Metadata: update.Endpoint.Metadata}
			var v []byte
			if v, err = json.Marshal(internalUpdate); err != nil {
				return status.Error(codes.InvalidArgument, err.Error())
			}
			ops = append(ops, clientv3.OpPut(update.Key, string(v), update.Opts...))
		case Delete:
			ops = append(ops, clientv3.OpDelete(update.Key, update.Opts...))
		// ... 省略：default 分支
		}
	}
	// ... 省略：client.Txn(ctx).Then(ops...).Commit()
}
```

> [!TIP]
> 把 endpoint 挂到 lease 上是优雅下线的标准做法：实例进程挂了 lease 不续期，endpoint 自动从 etcd 消失，消费方 Watch 到 Delete 后摘掉实例——比显式 `DeleteEndpoint` 更可靠（不怕进程被 kill 来不及注销）。

### resolver.Builder

`resolver.NewBuilder(client)` 返回 gRPC `resolver.Builder`。`Build` 做三件事：从 `target.URL.Path` 取 prefix（去掉前导 `/`）、建 `Manager` 拿 watch channel、起 `watch()` goroutine 把每次 update 累积进 `allUps` 并 `UpdateState`：

```go
func (b builder) Build(target gresolver.Target, cc gresolver.ClientConn, opts gresolver.BuildOptions) (gresolver.Resolver, error) {
	endpoint := target.URL.Path
	if endpoint == "" {
		endpoint = target.URL.Opaque
	}
	endpoint = strings.TrimPrefix(endpoint, "/")
	r := &resolver{c: b.c, target: endpoint, cc: cc}
	// ... 省略：WithCancel / NewManager / NewWatchChannel / go r.watch()
}

func (b builder) Scheme() string {
	return "etcd"
}
```

`watch()` 内部把 `Add`/`Delete` 事件折算进 map，再统一转换并推给 gRPC：

```go
func (r *resolver) watch() {
	defer r.wg.Done()
	allUps := make(map[string]*endpoints.Update)
	for {
		select {
		case <-r.ctx.Done():
			return
		case ups, ok := <-r.wch:
			if !ok {
				return
			}
			for _, up := range ups {
				switch up.Op {
				case endpoints.Add:
					allUps[up.Key] = up
				case endpoints.Delete:
					delete(allUps, up.Key)
				}
			}
			eps := convertToGRPCEndpoint(allUps)
			r.cc.UpdateState(gresolver.State{Endpoints: eps})
		}
	}
}
```

> [!WARNING]
> 这套 watch 式发现依赖 etcd 本身健康。etcd 整体不可用时，gRPC 保留最后一次 `UpdateState` 的地址（不主动清空），已建连接照常工作，只是拿不到新端点。它解决的是"etcd 活着但成员在变"，不是"etcd 挂了"——后者要靠 [client.md](/docs/CS/Framework/etcd/client.md) 的多 `Endpoints` / `AutoSyncInterval` 兜底。

## Complete Example

服务端（provider）注册并租约保活：

```go
cli, _ := clientv3.New(clientv3.Config{Endpoints: []string{"127.0.0.1:2379"}})
em, _ := endpoints.NewManager(cli, "/services/foo")

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
```

## Relationship with Surrounding Mechanisms

- **vs `EtcdManualResolver`**：manual 是静态 target，地址在 `Config.Endpoints` 定死；naming/resolver 动态、基于 Watch。集群固定且客户端一起重启 → manual + `AutoSyncInterval` 够用；成员频繁变 → naming/resolver。
- **vs [gateway](/docs/CS/Framework/etcd/gateway.md)**：grpc-proxy 的 `--resolver-prefix` / `--resolver-ttl` 同源——proxy 作为 consumer 去 Watch 一个 prefix，背后真实 etcd 成员变了自动重连。
- **vs [cluster](/docs/CS/Framework/etcd/cluster.md) 的 endpoints**：cluster 运维讲的是 Raft 层成员增删；naming 是**业务层**服务发现，存的是业务实例地址，二者不是一回事，但原理都是"KV + Watch"。

## Pitfall List

> [!WARNING]
> 这套 API 看着简单，几个位置最容易写错。

1. **target 必须带前导斜杠且 prefix 会被 `TrimPrefix` 去掉** —— `"etcd:///services/foo"` 与 `"etcd://services/foo"` 行为不同。
2. **`grpc.WithResolvers(b)` 不能忘** —— `NewBuilder` 只造 builder，不注册进 grpc 就不生效，dial 报 scheme 未注册。
3. **scheme 固定 `"etcd"`** —— 没有内置 fallback scheme。
4. **别用旧包名 `EndPoint` / `endpoints_manager`** —— 现行路径是 `client/v3/naming/endpoints` 与 `client/v3/naming/resolver`。
5. **etcd 整体挂掉时 resolver 不清空地址** —— 兜底靠多 `Endpoints` + `AutoSyncInterval`。
6. **注册方必须自己维持 lease** —— `WithLease` 只是挂上，不再 `KeepAlive` 才会自动消失；`concurrency.NewSession` 默认 TTL 只有 60s，显式设 TTL 更安全。

## Links

- [client](/docs/CS/Framework/etcd/client.md)
- [gateway](/docs/CS/Framework/etcd/gateway.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [concurrency](/docs/CS/Framework/etcd/concurrency.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)

## References

1. [etcd v3.7.4 源码（client/v3/naming/resolver/resolver.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/naming/resolver/resolver.go)
2. [etcd v3.7.4 源码（client/v3/naming/endpoints/endpoints_impl.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/naming/endpoints/endpoints_impl.go)
3. [gRPC Name Resolution（resolver package）](https://github.com/grpc/grpc-go/blob/master/resolver/resolver.go)
