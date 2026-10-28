# Transport gRPC

本册讲 Kratos 的 gRPC 实现（`transport/grpc`），以及它把自有服务发现接进 gRPC-Go resolver / balancer 体系的那套桥接代码。HTTP 侧的对照见 [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md)，加权节点管理见 [Discovery_and_Selector](/docs/CS/Go/Framework/Kratos/Discovery_and_Selector.md)。

## Server

```go
type Server struct {
	*grpc.Server
	baseCtx           context.Context
	tlsConf           *tls.Config
	lis               net.Listener
	err               error
	network, address  string
	endpoint          *url.URL
	timeout           time.Duration
	middleware        matcher.Matcher
	streamMiddleware  matcher.Matcher
	unaryInts         []grpc.UnaryServerInterceptor
	streamInts        []grpc.StreamServerInterceptor
	grpcOpts          []grpc.ServerOption
	health            *health.Server
	customHealth      bool
	adminClean        func()
	disableReflection bool
}
```

`NewServer` 默认值（`transport/grpc/server.go`）与 HTTP 侧高度对齐：

| 字段 | 默认值 |
| :-- | :-- |
| `baseCtx` | `context.Background()` |
| `network` | `"tcp"` |
| `address` | `":0"` |
| `timeout` | `1 * time.Second` |
| `health` | `health.NewServer()`（即内置健康检查） |
| `middleware` / `streamMiddleware` | 各一个 matcher |

### 内置组件

与 HTTP 侧不同，gRPC Server **默认挂载三个东西**：

1. **健康检查**：`google.golang.org/grpc/health` 的 `*health.Server`，注册 `grpc_health_v1.RegisterHealthServer`。用 `CustomHealth()` 可关掉内置注册（改为自己注册）。
2. **反射**：`reflection.Register(srv.Server)` **默认开启**，`DisableReflection()` 关闭。gRPC 反射让 `grpcurl` 这类工具能探测服务——生产环境建议关。
3. **admin**：`admin.Register(srv.Server)`，cleanup 存在 `adminClean`。

健康状态有个坑：grpc-go v1.81.0 的 `health.NewServer()` 默认只把 **`""`（空串，代表整个 server）** 设为 `SERVING`，`Check` 对未知 service 名返回 `codes.NotFound`。而 k8s 探针常按具体服务名去查——此时需要在 startup 逻辑里自己调 `SetServingStatus` 覆盖。

### Endpoint scheme

`internal/endpoint/endpoint.go` 的 `Scheme()` 实现是 `if isSecure { return scheme + "s" }`，所以：

- 无 TLS → `grpc://`
- 有 TLS → `grpcs://`

地址同样经过 `internal/host.Extract` 把 `":0"` 解析为本机私有 IP + 实际端口。

### 启动与停止

`Start(ctx)`：`listenAndEndpoint()` → 记录 `baseCtx` → `health.Resume()`（这时才对外报 SERVING）→ `Serve(lis)`。

`Stop(ctx)`：先 `adminClean()`、`health.Shutdown()`，再**起 goroutine 跑 `GracefulStop()`**，同时 select 等 `ctx.Done()`——超时则强制 `s.Server.Stop()`。无论走哪条分支，返回值恒为 `nil`。

## Interceptors

这是 Kratos 把协议无关中间件适配成 gRPC 拦截器的地方（`interceptor.go`）：

```go
func (s *Server) unaryServerInterceptor() grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		ctx, cancel := ic.Merge(ctx, s.baseCtx)
		defer cancel()
		md, _ := grpcmd.FromIncomingContext(ctx)
		replyHeader := grpcmd.MD{}
		tr := &Transport{
			operation:    info.FullMethod,
			reqHeader:    headerCarrier(md),
			replyHeader:  headerCarrier(replyHeader),
		}
		if s.endpoint != nil {
			tr.endpoint = s.endpoint.String()
		}
		ctx = transport.NewServerContext(ctx, tr)
		if s.timeout > 0 {
			ctx, cancel = context.WithTimeout(ctx, s.timeout)
			defer cancel()
		}
		h := func(ctx context.Context, req any) (any, error) { return handler(ctx, req) }
		if next := s.middleware.Match(tr.Operation()); len(next) > 0 {
			h = middleware.Chain(next...)(h)
		}
		reply, err := h(ctx, req)
		if len(replyHeader) > 0 {
			_ = grpc.SetHeader(ctx, replyHeader)
		}
		return reply, err
	}
}
```

三个值得注意的点：

1. **`ic.Merge(ctx, s.baseCtx)`** 把请求 ctx 与 server 的 baseCtx 合并（任一方取消即整体取消）。`ic.Merge` 让 App ctx 的取消能传导到在飞 RPC，这是优雅关机能真正中断请求的前提。
2. **超时只在 unary 里施加**。`streamServerInterceptor` **完全不读 `s.timeout`**——流式方法没有超时保护，需要自行处理 deadline。这与 HTTP 侧 v3 才开始把流式与请求超时解绑的方向正好相反。
3. gRPC 侧**没有 requestDecoder / responseEncoder / errorEncoder** 这类钩子（HTTP 侧有四个）。错误转换靠 `errors.Error` 自己实现 grpc-go 的 `GRPCStatus()` 接口（见 [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)），中间件想改返回值只能自己 wrap。

> [!WARNING]
>
> 流式拦截器里 `middleware.Chain(next...)(h)` 的**返回值被丢弃了**（构造完就扔），真正生效的路径是把 `grpc.ServerStream` 包成 `*wrappedStream`，在 `SendMsg` / `RecvMsg` 里逐消息串联中间件。同时 `streamServerInterceptor` 里直接 `s.endpoint.String()` 而没有做 nil 判断——若在 `Endpoint()` / `Start()` 之前就收到流请求会 panic。这是源码可见的不对称处理，写代码时留意。

## Client

v3 只有一个入口，`NewConn` / `Dial` / `DialInsecure` 这些 v2 名字已不存在：

```go
func NewClient(ctx context.Context, opts ...ClientOption) (*grpc.ClientConn, error)
```

返回**原生 `*grpc.ClientConn`**，取到之后就退回 grpc-go 的标准用法。核心逻辑：

```go
grpcOpts := []grpc.DialOption{
	grpc.WithDefaultServiceConfig(fmt.Sprintf(`{"loadBalancingConfig": [{"%s":{}}]%s}`,
		options.balancerName, options.healthCheckConfig)),
	grpc.WithChainUnaryInterceptor(ints...),
	grpc.WithChainStreamInterceptor(sints...),
}
...
conn, err := grpc.NewClient(options.endpoint, grpcOpts...)
if err != nil {
	return nil, err
}
conn.Connect()
return conn, nil
```

用的是 grpc-go v1.81.0 的 `grpc.NewClient` + 显式 `Connect()`（惰性建连 API），而非旧的 `DialContext`。

客户端 unary 拦截器负责：把 `tr.RequestHeader()` 的 KV 注入 outgoing metadata、按 `options.timeout` 给 ctx 加超时、串联 `middleware.Middleware`、塞入 `selector.NewPeerContext` 供 Picker 回填实际选中的节点。**流式客户端拦截器不施加超时。**

### ClientOption

| Option | 默认 | 说明 |
| :-- | :-- | :-- |
| `WithEndpoint(string)` | `""` | 支持 `discovery:///svc-name` 或 `direct:///ip:port` |
| `WithTimeout(d)` | **2s** | 同时作用于 RPC ctx 与 discovery watcher 创建 |
| `WithSubset(int)` | **25** | 子集过滤，0 表示关闭 |
| `WithDiscovery(registry.Discovery)` | nil | 非空才挂 discovery resolver |
| `WithTLSConfig(*tls.Config)` | nil | nil 则 insecure credentials |
| `WithMiddleware(m...)` | 空 | unary |
| `WithStreamMiddleware(m...)` | 空 | stream，逐 Send/Recv 生效 |
| `WithUnaryInterceptor(i...)` | 无 | 追加在 kratos 内建之后 |
| `WithStreamInterceptor(i...)` | 无 | 同上 |
| `WithOptions(dialOpts...)` | 无 | 追加到最后，可覆盖前面的默认项 |
| `WithNodeFilter(f...)` | 无 | 传给 balancer picker |
| `WithHealthCheck(bool)` | **开** | `false` 时从 service config 里摘掉 healthCheckConfig |

`balancerName` 的值固定为 `"selector"`，**且没有任何 ClientOption 能改它**——想换负载均衡算法只能走 `selector.SetGlobalSelector(...)`。

> [!NOTE]
>
> `discovery.NewBuilder` 自身默认 `timeout=10s`、`subsetSize=25`，但 `NewClient` 会把它们覆盖为 `WithTimeout(options.timeout)`（默认 2s）与 `WithSubset(options.subsetSize)`。**所以实际创建 watcher 的超时是 2 秒，不是 10 秒**，注册中心慢的时候这里会先超时。

## Resolver and Balancer Bridge

Kratos 不是自己实现负载均衡然后硬塞给 gRPC，而是**把自己实现为 grpc-go 标准的两类插件**：

### Resolver

自带两条：

| scheme | 位置 | 注册方式 | 用法 |
| :-- | :-- | :-- | :-- |
| `direct` | `transport/grpc/resolver/direct` | `client.go` 里空白导入，init 自动注册 | `direct:///<ip:port>,<ip:port>` |
| `discovery` | `transport/grpc/resolver/discovery` | 只在 `WithDiscovery` 时按 ClientConn 注册 | `discovery:///<service-name>` |

`direct` 的 builder 极其简单，直接把 path 按逗号切成多个 `resolver.Address` 然后 `UpdateState`：

```go
func (d *directBuilder) Build(target resolver.Target, cc resolver.ClientConn, _ resolver.BuildOptions) (resolver.Resolver, error) {
	parts := strings.Split(strings.TrimPrefix(target.URL.Path, "/"), ",")
	addrs := make([]resolver.Address, 0, len(parts))
	for _, addr := range parts {
		addrs = append(addrs, resolver.Address{Addr: addr})
	}
	err := cc.UpdateState(resolver.State{Addresses: addrs})
	...
}
```

`discovery` 才是重点：它在 goroutine 里 `watcher.Watch(ctx, serviceName)`，用 `time.After(b.timeout)` 限时；收到变更时先从 `Endpoint()` 列表里过滤出 `grpc://` / `grpcs://` 地址，再做子集裁剪，然后：

```go
addr := resolver.Address{
	ServerName: in.Name,
	Attributes: parseAttributes(in.Metadata).WithValue("rawServiceInstance", in),
	Addr:       ept,
}
```

注意那个 `rawServiceInstance` attribute——它是 resolver 与 balancer 之间的**私有传递通道**，把整个 `*registry.ServiceInstance` 塞给了 balancer，后者才能构造出带 version / metadata / weight 的 `selector.Node`。

### Balancer

```go
const (
	balancerName = "selector"
)

func init() {
	b := base.NewBalancerBuilder(
		balancerName,
		&balancerBuilder{
			builder: selector.GlobalSelector(),
		},
		base.Config{HealthCheck: true},
	)
	balancer.Register(b)
}
```

注册名 `"selector"`，客户端默认 service config 的 `loadBalancingConfig` 引用的就是它。**注意 `HealthCheck: true` 依赖的是 grpc-go 的 Outlier Detection / health-check LB policy**，而不是上面 `healthCheckConfig` 里那个 `serviceName`（后者是 grpc health service 检查）。

`balancerBuilder.Build()` 从 `info.Address.Attributes.Value("rawServiceInstance")` 还原实例，包成 `grpcNode`，交给 selector：

```go
p := &balancerPicker{
	selector: b.builder.Build(),
}
p.selector.Apply(nodes)
```

而 `balancerPicker.Pick()` 只是把 kratos 的 `Select` 结果翻译成 grpc 的 `PickResult`，并把 `Done` 回调接到 `selector.DoneInfo`——**负载统计的反馈闭环在这里闭合**，eWMA 的权重更新就靠它。

> [!WARNING]
>
> **源码可见的初始化时序陷阱**：`balancer.go` 的 init 在**包初始化那一刻**就把 `selector.GlobalSelector()` 的返回值快照进 `builder` 字段；而把全局 selector 设为 wrr 的 init 写在**同包的 `client.go`** 里：
>
> ```go
> // transport/grpc/client.go
> func init() {
> 	if selector.GlobalSelector() == nil {
> 		selector.SetGlobalSelector(wrr.NewBuilder())
> 	}
> }
> ```
>
> Go 同一 package 内多个 `init` 按文件呈现顺序执行（通常是文件名序），`balancer.go` 早于 `client.go`——因此那个快照很可能取到的是 `nil`，而后续 `b.builder.Build()` 一旦被调用就会 panic。
>
> **稳妥做法**：应用侧在早期显式调用 `selector.SetGlobalSelector(...)`（例如在自己的 `main` 或 `init` 里指定 `p2c.NewBuilder()`）。需要说明的是，这条结论是**源码层面的推断**，本环境未编译运行验证；这里如实标注，实际行为请以运行时为准。

## Links

- [Kratos](/docs/CS/Go/Framework/Kratos.md)
- [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md)
- [Discovery_and_Selector](/docs/CS/Go/Framework/Kratos/Discovery_and_Selector.md)
- [Architecture](/docs/CS/Go/Framework/Kratos/Architecture.md)
- [Errors_and_Validation](/docs/CS/Go/Framework/Kratos/Errors_and_Validation.md)

## References

- <https://pkg.go.dev/github.com/go-kratos/kratos/v3/transport/grpc>
- <https://github.com/grpc/grpc-go/blob/master/Documentation/load-balancing.md>
- <https://go-kratos.dev/docs/component/transport/grpc>
