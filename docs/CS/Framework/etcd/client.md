# etcd clientv3: Connection Management, Retry and Authentication

## Introduction

etcd 客户端有 v2 / v3 两代 API 库。v2 用 HTTP+JSON，靠 1.1 长连接维持推送，通信效率不高；v3 改用 gRPC + protobuf（基于 HTTP/2.0），二进制压缩、服务端主动推送、Watch 用单一 stream 替代长轮询。我们代码中读写 etcd 一般直接用 clientv3——它屏蔽了多节点负载均衡与断链重连，k8s 的 storage 也是在它之上封了一层 Storage API。

本篇聚焦 clientv3 的三个内核问题：连接怎么建、哪些 RPC 可以安全重试、认证 token 怎么注入。三点反直觉，均为 3.7.4 源码核验所得：

- **连接建立已换成 `grpc.NewClient`，且默认不再阻塞等待。** 3.7.4 的 `dial()` 末尾是 `grpc.NewClient(target, opts...)`，不再是旧版的 `grpc.DialContext(dctx, ...)`；`DialTimeout` 也不再包成 dial 的 context。这意味着构造 `Client` 很快返回，真正的连接失败推迟到首次 RPC（除非显式配 `grpc.WithBlock()`）。
- **重试拦截器已拆到独立文件，且默认值与旧资料不同。** `unaryClientInterceptor` / `isSafeRetry` 在 `client/v3/retry_interceptor.go`（旧版在 `retry.go`），默认退避 `defaultBackoffWaitBetween = 25ms`、`defaultBackoffJitterFraction = 0.10`、`defaultUnaryMaxRetries = 100`——都不是旧资料常见的 250ms / 0.5。
- **写操作保证 at-most-once，不进重试循环。** `retryKVClient.Put` 连 repeatable policy 都不传；只有 immutable 读（`Range`）标记 `repeatable`。把 `Unavailable` 的 Put 盲目重试会造成重复写，应用层必须自己读回判断或用 Txn 保证幂等。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag；client/v3 module 通过 `replace` 指向主仓库，api/v3 版本为 3.7.4。旧笔记基于 v3.5.34，凡冲突处以本节源码为准并用 `[!WARNING]` 标注。

## The v2 Client (Historical)

v2 的客户端是纯 REST：`Client` 接口含 `Sync` / `AutoSync` / `Endpoints` / `SetEndpoints` / `GetVersion`，`client.New` 返回 `httpClusterClient`，另有 `KeysAPI`、`MembersAPI` 封装操作。负载均衡很朴素：从一个 `pinned` 地址开始遍历节点直到成功，成功节点成为新的 `pinned`；初始化和 `Sync` 时用随机数打乱节点顺序，避免所有客户端都打到第一个节点。Watch 走长轮询——客户端循环调 `Do` 并带 `wait` 参数，服务端 hold 住连接直到 key 更新或超时。

v2 已被 v3 全面取代，此处只留认知锚点，主线看 v3。

## The v3 Client and ResponseHeader

v3 的 RPC 定义在 `api/etcdserverpb/rpc.proto`，gRPC 生成接口、注册函数与 client 代码，分 KV / Watch / Lease / Cluster / Maintenance / Auth 六组。3.7 新增 **`RangeStream` RPC**（服务端流式 range），这是旧版本资料里没有的：

```protobuf
// api/etcdserverpb/rpc.proto
  rpc RangeStream(RangeRequest) returns (stream RangeStreamResponse) {
```

所有响应都带 `ResponseHeader`，四个字段各有用途：

```protobuf
// api/etcdserverpb/rpc.proto
message ResponseHeader {
  uint64 cluster_id = 1;
  uint64 member_id = 2;
  // revision is the key-value store revision when the request was applied, and it's
  // unset (so 0) in case of calls not interacting with key-value store.
  int64 revision = 3;
  uint64 raft_term = 4;
}
```

- `Cluster_ID` / `Member_ID`：确认通信对象正是预期的集群与成员。
- `Revision`：键值库的最新修订号，做历史版本查询与时程比较。注意 3.7 的注释明确它"在不与 KV 交互的调用里为 0"——旧笔记没这条限定。
- `Raft_Term`：检测集群何时完成新的 leader 选举。

## Dialing: Load Balancing and Unix Sockets

`clientv3.New` 要求的配置里 `Endpoints` 必填，为空直接返回 `ErrNoAvailableEndpoints`。`Client` 结构体聚合了六个子系统，3.7.4 相比旧版有几处字段变化：

```go
// client/v3/client.go
type Client struct {
	Cluster
	KV
	Lease
	Watcher
	Auth
	Maintenance

	conn *grpc.ClientConn

	cfg      Config
	creds    grpccredentials.TransportCredentials
	resolver *resolver.EtcdManualResolver

	epMu      *sync.RWMutex
	endpoints []string

	ctx    context.Context
	cancel context.CancelFunc

	Username string
	Password string
	// Token is a JWT used for authentication instead of a password.
	Token string

	authTokenBundle credentials.PerRPCCredentialsBundle

	callOpts []grpc.CallOption

	lg atomic.Pointer[zap.Logger]
}
```

> [!WARNING]
> 相比 v3.5.34，3.7.4 的 `Client` 有几处结构性变化，别照旧代码写：`mu *sync.RWMutex` 换成 `epMu` + `endpoints` 切片；`authTokenBundle` 类型从 `credentials.Bundle` 变成 `credentials.PerRPCCredentialsBundle`；`Token` 升为独立字段（与 `Username`/`Password` 互斥）；logger 从 `lgMu + lg` 换成 `lg atomic.Pointer[zap.Logger]`。

负载均衡由 gRPC 的 round-robin resolver 完成：每个请求轮询地从 endpoint 列表选一个连接访问。`dialWithBalancer` 把自定义 resolver 注入，`dial` 完成实际连接——注意末尾已是 `grpc.NewClient`：

```go
// client/v3/client.go
func (c *Client) dialWithBalancer(dopts ...grpc.DialOption) (*grpc.ClientConn, error) {
	creds := c.credentialsForEndpoint(c.Endpoints()[0])
	opts := append(dopts, grpc.WithResolvers(c.resolver))
	return c.dial(creds, opts...)
}

// dial configures and dials any grpc balancer target.
func (c *Client) dial(creds grpccredentials.TransportCredentials, dopts ...grpc.DialOption) (*grpc.ClientConn, error) {
	opts := c.dialSetupOpts(creds, dopts...)

	if c.authTokenBundle != nil {
		opts = append(opts, grpc.WithPerRPCCredentials(c.authTokenBundle.PerRPCCredentials()))
	}

	opts = append(opts, c.cfg.DialOptions...)

	target := fmt.Sprintf("%s://%p/%s", resolver.Schema, c, authority(c.endpoints[0]))
	return grpc.NewClient(target, opts...)
}
```

`authority()` 是 3.7 支持 **Unix socket（单成员）** 的关键：它从 endpoint 里剥掉 scheme，`unix:` / `unixs:` 前缀单独处理。这是新版本支持的部署形态。

```go
// client/v3/client.go
func authority(endpoint string) string {
	spl := strings.SplitN(endpoint, "://", 2)
	if len(spl) < 2 {
		if strings.HasPrefix(endpoint, "unix:") {
			return endpoint[len("unix:"):]
		}
		if strings.HasPrefix(endpoint, "unixs:") {
			return endpoint[len("unixs:"):]
		}
		return endpoint
	}
	return spl[1]
}
```

## Interceptor Setup: Backoff and Quorum

`dialSetupOpts` 装配 keepalive、transport credentials 和两个重试拦截器。注意它**不再返回 error**（旧版签名带 `err error`），且 insecure 分支用 `grpc.WithTransportCredentials(insecure.NewCredentials())` 而非废弃的 `grpc.WithInsecure()`：

```go
// client/v3/client.go
func (c *Client) dialSetupOpts(creds grpccredentials.TransportCredentials, dopts ...grpc.DialOption) []grpc.DialOption {
	var opts []grpc.DialOption

	if c.cfg.DialKeepAliveTime > 0 {
		params := keepalive.ClientParameters{
			Time:                c.cfg.DialKeepAliveTime,
			Timeout:             c.cfg.DialKeepAliveTimeout,
			PermitWithoutStream: c.cfg.PermitWithoutStream,
		}
		opts = append(opts, grpc.WithKeepaliveParams(params))
	}
	opts = append(opts, dopts...)

	if creds != nil {
		opts = append(opts, grpc.WithTransportCredentials(creds))
	} else {
		opts = append(opts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	}
	// ... 省略 MaxUnaryRetries / backoff 读取
	rrBackoff := withBackoff(c.roundRobinQuorumBackoff(backoffWaitBetween, backoffJitterFraction))
	opts = append(opts,
		// Disable stream retry by default since go-grpc-middleware/retry does not support client streams.
		// Streams that are safe to retry are enabled individually.
		grpc.WithStreamInterceptor(c.streamClientInterceptor(withMax(0), rrBackoff)),
		grpc.WithUnaryInterceptor(c.unaryClientInterceptor(withMax(unaryMaxRetries), rrBackoff)),
	)

	return opts
}
```

stream 拦截器的 `withMax(0)` 是**故意的**：client stream 重试不被支持，需要自己单独处理。默认值集中在 `options.go`：

```go
// client/v3/options.go
	defaultUnaryMaxRetries uint = 100
	defaultBackoffWaitBetween = 25 * time.Millisecond
	defaultBackoffJitterFraction = 0.10
```

> [!WARNING]
> **默认退避值已变。** 旧资料写 `BackoffWaitBetween = 250ms`、`BackoffJitterFraction = 0.5`，3.7.4 源码是 **25ms** 与 **0.10**；`MaxUnaryRetries` 默认 100。运维脚本若依赖旧默认值调整超时，需以本节为准重新核对。

`roundRobinQuorumBackoff` 的语义不变：重试次数没达到 quorum 就直接返回 0（立刻轮询到下一节点重试），达到 quorum 才真正计算退避等待——配合 round-robin 负载均衡，实现"单节点故障秒切、集群多数故障才退避"。

```go
// client/v3/client.go
func (c *Client) roundRobinQuorumBackoff(waitBetween time.Duration, jitterFraction float64) backoffFunc {
	return func(attempt uint) time.Duration {
		// after each round robin across quorum, backoff for our wait between duration
		n := uint(len(c.Endpoints()))
		quorum := (n/2 + 1)
		if attempt%quorum == 0 {
			c.GetLogger().Debug("backoff", zap.Uint("attempt", attempt), zap.Uint("quorum", quorum), zap.Duration("waitBetween", waitBetween), zap.Float64("jitterFraction", jitterFraction))
			return jitterUp(waitBetween, jitterFraction)
		}
		c.GetLogger().Debug("backoff skipped", zap.Uint("attempt", attempt), zap.Uint("quorum", quorum))
		return 0
	}
}
```

## The Retry Interceptor

3.7.4 的重试拦截器在 `retry_interceptor.go`，比旧版多了 `grpc.Peer(&p)` 记录实际命中的对端、日志带 `method` 与 `peer`，失败路径也多了 `refreshToken`。类型用 `any` 替代 `interface{}`。

```go
// client/v3/retry_interceptor.go
func (c *Client) unaryClientInterceptor(optFuncs ...retryOption) grpc.UnaryClientInterceptor {
	intOpts := reuseOrNewWithCallOptions(defaultOptions, optFuncs)
	return func(ctx context.Context, method string, req, reply any, cc *grpc.ClientConn, invoker grpc.UnaryInvoker, opts ...grpc.CallOption) error {
		ctx = withVersion(ctx)
		grpcOpts, retryOpts := filterCallOptions(opts)
		var p peer.Peer
		grpcOpts = append(grpcOpts, grpc.Peer(&p))
		callOpts := reuseOrNewWithCallOptions(intOpts, retryOpts)
		// short circuit for simplicity, and avoiding allocations.
		if callOpts.max == 0 {
			return invoker(ctx, method, req, reply, cc, grpcOpts...)
		}
		var lastErr error
		for attempt := uint(0); attempt < callOpts.max; attempt++ {
			if err := waitRetryBackoff(ctx, attempt, callOpts); err != nil {
				return err
			}
			lastErr = invoker(ctx, method, req, reply, cc, grpcOpts...)
			if lastErr == nil {
				return nil
			}
			// ... 省略日志与 context / token 判断
			if isContextError(lastErr) {
				if ctx.Err() != nil {
					return lastErr
				}
				continue
			}
			if c.shouldRefreshToken(lastErr, callOpts) {
				gtErr := c.refreshToken(ctx)
				if gtErr != nil {
					return gtErr // lastErr must be invalid auth token
				}
				continue
			}
			if !isSafeRetry(c, lastErr, callOpts) {
				return lastErr
			}
		}
		return lastErr
	}
}
```

`isSafeRetry` 按 `retryPolicy` 分派到 immutable / mutable 两个判定，并新增一条 **learner 特判**：当错误是 `ErrGRPCNotSupportedForLearner` 且 endpoint 多于一个时允许重试，因为下一个尝试可能轮到 voter（为了兼容" learner 与 voter 混用"的部署）。

```go
// client/v3/retry_interceptor.go
func isSafeRetry(c *Client, err error, callOpts *options) bool {
	if isContextError(err) {
		return false
	}

	// Situation when learner refuses RPC it is supposed to not serve is from the server
	// perspective not retryable. But for backward-compatibility reasons we need to support
	// situation that customer provides mix of learners (not yet voters) and voters with an
	// expectation to pick voter in the next attempt.
	if errors.Is(err, rpctypes.ErrGRPCNotSupportedForLearner) && len(c.Endpoints()) > 1 {
		return true
	}

	switch callOpts.retryPolicy {
	case repeatable:
		return isSafeRetryImmutableRPC(err)
	case nonRepeatable:
		return isSafeRetryMutableRPC(err)
	default:
		c.GetLogger().Warn("unrecognized retry policy", zap.String("retryPolicy", callOpts.retryPolicy.String()))
		return false
	}
}
```

## Retry Semantics: Immutable vs Mutable

etcd 把 RPC 分成两类，策略截然不同。类型定义在 `retry.go`：

```go
// client/v3/retry.go
type retryPolicy uint8

const (
	repeatable retryPolicy = iota
	nonRepeatable
)
```

**读操作**（`Range` 等）标记 `repeatable`，只放行 `Unavailable`，且用 `errors.As` 识别 etcd 服务端错误（旧版是类型断言 `.(rpctypes.EtcdError)`，对包装 error 会失效）：

```go
// client/v3/retry.go
func isSafeRetryImmutableRPC(err error) bool {
	eErr := rpctypes.Error(err)
	var serverErr rpctypes.EtcdError
	if errors.As(eErr, &serverErr) && serverErr.Code() != codes.Unavailable {
		// interrupted by non-transient server-side or gRPC-side error
		// client cannot handle itself (e.g. rpctypes.ErrCompacted)
		return false
	}
	// only retry if unavailable
	ev, ok := status.FromError(err)
	if !ok {
		return false
	}
	return ev.Code() == codes.Unavailable
}
```

**写操作**（Put / Delete / Txn）根本不进重试循环——`retryKVClient.Put` 连 policy 都不传，只有 `Range` 传 `withRepeatablePolicy()`（旧版叫 `withRetryPolicy(repeatable)`）。新增的 `RangeStream` 同样不重试。

```go
// client/v3/retry.go
func (rkv *retryKVClient) Range(ctx context.Context, in *pb.RangeRequest, opts ...grpc.CallOption) (resp *pb.RangeResponse, err error) {
	return rkv.kc.Range(ctx, in, append(opts, withRepeatablePolicy())...)
}

func (rkv *retryKVClient) RangeStream(ctx context.Context, in *pb.RangeRequest, opts ...grpc.CallOption) (pb.KV_RangeStreamClient, error) {
	return rkv.kc.RangeStream(ctx, in, opts...)
}

func (rkv *retryKVClient) Put(ctx context.Context, in *pb.PutRequest, opts ...grpc.CallOption) (resp *pb.PutResponse, err error) {
	return rkv.kc.Put(ctx, in, opts...)
}
```

写操作遇 `Unavailable` 时，由 `isSafeRetryMutableRPC` 把许可压到极窄——只在**连接都还没建起来**（error desc 是 "there is no address available" 或 "there is no connection available"）时才允许：

```go
// client/v3/retry.go
func isSafeRetryMutableRPC(err error) bool {
	if ev, ok := status.FromError(err); ok && ev.Code() != codes.Unavailable {
		// not safe for mutable RPCs
		return false
	}
	desc := rpctypes.ErrorDesc(err)
	return desc == "there is no address available" || desc == "there is no connection available"
}
```

> [!WARNING]
> **这是 etcd 客户端最重要的设计取舍**：写操作保证 **at-most-once** 而非 at-least-once。客户端无法区分"请求没到达"和"请求已提交但响应丢失"，重试一个可能已成功的 Put 就会造成重复写。应用层收到 `Unavailable` 的 Put 不能盲目重试，应重新读回目标 key 判断是否生效，或用带 CAS 的 Txn 保证幂等。

对照 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的错误码表还能看出一处错配：`database space exceeded` 的 code 是 `ResourceExhausted`，落在 gRPC 官方"可重试"集合里，但 etcd 的 `isSafeRetry*` 只放行 `Unavailable`——所以 NOSPACE 不会被客户端自动重试，这个坑实际上被客户端挡住了。

## Authentication: Token Injection and Refresh

认证 token 的注入点在 `dial()`：`authTokenBundle != nil` 时通过 `grpc.WithPerRPCCredentials(...)` 挂到连接上。token 的获取由 `getToken` 完成——`Token` 字段直接用，`Username`/`Password` 则调 `Auth.Authenticate`，若服务端未开启 auth（`ErrAuthNotEnabled`）就清空 token 继续。

```go
// client/v3/client.go
func (c *Client) getToken(ctx context.Context) error {
	var err error // return last error in a case of fail

	if c.Token != "" {
		c.authTokenBundle.UpdateAuthToken(c.Token)
		return nil
	}

	if c.Username == "" || c.Password == "" {
		return nil
	}

	resp, err := c.Auth.Authenticate(ctx, c.Username, c.Password)
	if err != nil {
		if errors.Is(err, rpctypes.ErrAuthNotEnabled) {
			c.authTokenBundle.UpdateAuthToken("")
			return nil
		}
		return err
	}
	c.authTokenBundle.UpdateAuthToken(resp.Token)
	return nil
}
```

服务端对 token 的校验是 fail-closed：改了权限后旧 token 的 auth revision 落后，请求会报 `revision of auth store is old`（`ErrAuthOldRevision`），客户端的应对是重新 `Authenticate` 拿新 token 而非重试。拦截器里的 `shouldRefreshToken` + `refreshToken` 正是这条路径。认证与 RBAC 的服务端实现见 [security](/docs/CS/Framework/etcd/security.md)。

## Config Items

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `Endpoints` | 无（必填） | 成员地址列表，支持 `http://`、`https://`、`unix://`、`unixs://`；为空 `New` 直接报错 |
| `DialTimeout` | 2s | 用于建连等操作的超时；租约 keepalive 超时为 `DialTimeout + 1s` |
| `DialKeepAliveTime` | 0（禁用） | 客户端主动 ping 探测连接存活的间隔 |
| `DialKeepAliveTimeout` | 20s | keep-alive 探测等待响应的超时，超时则断开 |
| `AutoSyncInterval` | 0（关闭） | 周期性 `MemberList` 拉取最新成员并更新 Endpoints |
| `MaxCallSendMsgSize` | 2 MiB | 请求发送字节上限；须小于服务端 `--max-request-bytes` |
| `MaxCallRecvMsgSize` | `math.MaxInt32` | 响应接收字节上限 |
| `MaxUnaryRetries` | 100 | Unary RPC 最大重试次数（3.7.4 默认值） |
| `BackoffWaitBetween` | 25ms | 重试退避的基础等待时间（3.7.4 默认值） |
| `BackoffJitterFraction` | 0.10 | 退避抖动系数（3.7.4 默认值） |
| `RejectOldCluster` | false | 拒绝连接低于"当前主版本前一 minor"的旧集群 |
| `TLS` | nil | 客户端 TLS 凭据，配双向认证时必填 |
| `Username` / `Password` / `Token` | 空 | 用户名密码认证，或直接用 token（二者互斥） |

几处需要结合场景判断的：

> [!TIP]
> **`AutoSyncInterval` 默认关闭**，但集群扩缩容后 endpoints 会变陈旧。成员会变动时建议开启（如 `10m`）；规模固定则关掉以省掉周期性 `MemberList`。

> [!WARNING]
> **批量写入必须同步调大两侧限制**。`MaxCallSendMsgSize` 默认 2 MiB，但真正卡住的往往是服务端 `--max-request-bytes`（默认 1.5 MiB）。客户端调大而不动服务端，会得到 `etcdserver: request is too large`。

## Consistent Read

`Range` 默认是**线性一致读**（需走 ReadIndex 与 leader 确认，多一次网络往返），proto 里对 serializable 有明确说明：

```protobuf
// api/etcdserverpb/rpc.proto
  // serializable sets the range request to use serializable member-local reads.
  // Range requests are linearizable by default; linearizable requests have higher
  // latency and lower throughput than serializable requests but reflect the current
  // consensus of the cluster. For better performance, in exchange for possible stale reads,
  // a serializable range request is served locally without needing to reach consensus
  // with other nodes in the cluster.
  bool serializable = 7;
```

可容忍读旧数据的场景（如 informer 缓存刷新）应显式请求 serializable：

```go
// 线性一致（默认）：保证读到最新
resp, err := client.Get(ctx, "/registry/pods/default/my-pod")

// 序列化读：可能读到略旧数据，但省掉一次网络往返
resp, err := client.Get(ctx, "/registry/pods/default/my-pod", clientv3.WithSerializable())
```

判据是数据性质：**参与准入 / 调度决策的数据必须线性读；仅用于展示或缓存预热的可以 serializable**。

## Lease and KeepAlive

[lease](/docs/CS/Framework/etcd/lease.md) 的续期由客户端 `KeepAlive` 循环自动完成：`NoLease = 0` 表示不挂租约，首次 keepalive 截止时间在真实 TTL 未知前按 `defaultTTL = 5s` 处理，请求失败后重连等待 500ms。

> [!WARNING]
> **TTL 设定要留足续期冗余**。续期循环是周期性的，网络抖动或 GC 停顿会漏掉某次续期；TTL 设得过短（如 2s），一次抖动就可能让 key 被误删。建议 TTL ≥ 5s。

若自动续期循环因意外错误终止，客户端返回 `ErrKeepAliveHalted`——此时续期已失效，但 `KeepAliveOnce` 仍可单次续租。服务端侧对应机制是 leader 切换后的 `CheckPointScheduledLeases` 定时任务（见 [lease](/docs/CS/Framework/etcd/lease.md)）。

## Range Query Semantics

`Range` 的 `range_end` 有几种约定（来自 `rpc.proto`），容易踩错：

| `range_end` 取值 | 含义 |
| :--- | :--- |
| 未设置 | 只查 `key` 这一个 key |
| `'\0'` | 所有 ≥ `key` 的 key（等价 `--from-key`） |
| `key + 1`（如 `"aa"+1 == "ab"`） | 所有以 `key` 为前缀的 key（等价 `--prefix`） |
| 其他 key | 半开区间 `[key, range_end)`，**含 key 不含 range_end** |
| 两者都是 `'\0'` | 全部 key |

```shell
$ etcdctl get foo foo3     # foo3 不含在内
foo = bar
foo1 = bar1
foo2 = bar2
```

> [!TIP]
> 区间是**左闭右开**的。想闭区间得显式算 `range_end = 目标key + 1`。

## Links

- [etcd（架构与启动流程）](/docs/CS/Framework/etcd/etcd.md)
- [watch（订阅与断线重连）](/docs/CS/Framework/etcd/watch.md)
- [naming（gRPC naming / resolver 服务发现）](/docs/CS/Framework/etcd/naming.md)
- [concurrency（基于 clientv3 Session 的分布式原语）](/docs/CS/Framework/etcd/concurrency.md)
- [request（请求处理全链路）](/docs/CS/Framework/etcd/request.md)

## References

1. [etcd v3.7.4 源码（client/v3/client.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/client.go)
2. [etcd v3.7.4 源码（client/v3/retry.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/retry.go)
3. [etcd v3.7.4 源码（client/v3/retry_interceptor.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/retry_interceptor.go)
4. [etcd v3.7.4 源码（client/v3/options.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/client/v3/options.go)
5. [etcd Documentation - Interacting with etcd](https://etcd.io/docs/v3.7/dev-guide/interacting_v3/)
