## Introduction

作为etcd的基础模块，etcd 客户端包括 client v2 和 v3 两个大版本 API 客户端库，提供了简洁易用的 API，同时支持负载均衡、节点间故障自动转移，可极大降低业务使用 etcd 复杂度，提升开发效率、服务可用性

v2通过HTTP+JSON暴露外部API，由于经常需要服务感知节点配置变动或者监听推送，客户端和服务端需要频繁通信，早期的v2采用HTTP1.1的长连接来维持，经过如此通信效率依然不高
etcd v3版本引进了grpc+protobuf的通信方式(基于HTTP/2.0)，其优势在于
1. 采用二进制压缩传输，序列/反序列化更加高效
2. 基于HTTP2.0的服务端主动推送特性，对事件多路复用做了优化
3. Watch功能使用grpc的stream流进行感知，同一个客户端和服务端采用单一连接，替代v2的HTTP长轮询检测，直接减少连接数和内存开销
 
etcd v3版本为了向上兼容v2 API版本，提供了grpc网关来支持原HTTP JSON接口支持 

但是一般来说，我们代码中操作etcd的读写还是会通过etcd提供的client来做
client 屏蔽了etcd server多节点访问的负载均衡问题，v3的的client采用grpc client可以维持长连接，断链自动重连
k8s的storage也是封装了etcd的client给上层提供了一个Storage的API出去的




## v2

v2开发的api完全是rest方式的，因此客户端的代码也都是通过rest访问server的。代码比较简单

```go

type Client interface {
	// Sync updates the internal cache of the etcd cluster's membership.
	Sync(context.Context) error

	// AutoSync periodically calls Sync() every given interval.
	// The recommended sync interval is 10 seconds to 1 minute, which does
	// not bring too much overhead to server and makes client catch up the
	// cluster change in time.
	//
	// The example to use it:
	//
	//  for {
	//      err := client.AutoSync(ctx, 10*time.Second)
	//      if err == context.DeadlineExceeded || err == context.Canceled {
	//          break
	//      }
	//      log.Print(err)
	//  }
	AutoSync(context.Context, time.Duration) error

	// Endpoints returns a copy of the current set of API endpoints used
	// by Client to resolve HTTP requests. If Sync has ever been called,
	// this may differ from the initial Endpoints provided in the Config.
	Endpoints() []string

	// SetEndpoints sets the set of API endpoints used by Client to resolve
	// HTTP requests. If the given endpoints are not valid, an error will be
	// returned
	SetEndpoints(eps []string) error

	// GetVersion retrieves the current etcd server and cluster version
	GetVersion(ctx context.Context) (*version.Versions, error)

	httpClient
}
```
client包中提供了这个接口的几种实现，如果直接调用client包的New函数创建client，会生成一个httpClusterClient 结构的对象。这个对象有一个工厂方法，创建针对单个节点的http client
如果直接使用Client接口操作etcd，虽然已经屏蔽了多节点的路由选择问题，但是对每种操作构造http请求依然比较复杂，因此client包中另外还有两个接口KeysAPI、MembersAPI，封装了对key-value的操作和对member的操作

负载均衡

etcdv2负载均衡其实非常简单，它是从一个pinned的地址开始，遍历所有的节点，直到请求成功或者遍历了所有的服务器。pinned是一个状态变量，如果某次请求成功了，就会把成功返回的服务端节点地址设置为pinned。如此，下一个请求会首先尝试这个pinned。
可能有人会有疑问，如果所有客户端都是按照相同的方式传入服务端节点的url。那么只要第一个节点没有挂，那岂不是所有的流量都导到第一个节点上了吗？实际不是的，我们看到httpClusterClient有一个随机数生成变量rand，这个是在初始化和每次Sync重新获取节点以后打乱节点顺序用的。所以，不会出现所有流量都聚集在第一个节点的问题了。当然，client还提供了一种leader节点优先的路由选择模式，请求首先尝试leader，leader不成功尝试其他节点



Watch机制

客户端调用KeyAPI的Watcher函数，可以获得一个Watcher，连续调用Watcher的Next函数，可以获取**的key值的修改，获得最新修改的value。Next的逻辑是循环调用client的Do函数，传入一个wait参数，服务端在看到wait参数的时候，会hold住连接，直到key上有数据更新，或者时间超过了wait定义的时间，就返回。client从返回的数据中解析出Response，如果Response是空的，就继续下一趟循环。如果获取到了value，先把nextWait的等待index加1。表示等待下一个index的数据。

服务端的处理，如果在请求url中设置了stream=true，那么就会一直hold住连接，发送更新，直到超过了wait定义的超时时间。否则一旦有更新就立即返回。实际上，前者就是长连接的方式，后者即是长轮询的方式。而client端的代码中，是没有在url中设置stream=true的，并且从处理逻辑看也不是长连接的方式，而是长轮询的方式。k8s apiserver对外提供的watch机制是长连接的，而apiserver向后端etcd v2的watch则是采用长轮询的方式



## v3



rpc服务都定义在etcdserver/etcdserverpb/rpc.proto文件中，grpc框架根据proto文件生成rpc.pb.go文件，go文件中定义了grpc的接口、注册函数和client代码

- KV
- Watch
- Lease
- Cluster
- Maintenance
- Auth

此外，etcd API 的所有响应都有一个附加的响应标头，其中包括响应的群集元数据

```go
message ResponseHeader {
  // cluster_id is the ID of the cluster which sent the response.
  uint64 cluster_id = 1;
  // member_id is the ID of the member which sent the response.
  uint64 member_id = 2;
  // revision is the key-value store revision when the request was applied.
  // For watch progress responses, the header.revision indicates progress. All future events
  // recieved in this stream are guaranteed to have a higher revision number than the
  // header.revision number.
  int64 revision = 3;
  // raft_term is the raft term when the request was applied.
  uint64 raft_term = 4;
}
```
这些元数据在实际使用过程中，都提供了如下功能
1. 应用服务可以通过 Cluster_ID 和 Member_ID 字段来确保，当前与之通信的正是预期的那个集群或者成员
2. 应用服务可以使用修订号字段来知悉当前键值存储库最新的修订号。当应用程序指定历史修订版以进行时程查询并希望在请求时知道最新修订版时，此功能特别有用
3. 应用服务可以使用 Raft_Term 来检测集群何时完成一个新的 leader 选举
 

Package clientv3 implements the official Go etcd client for v3.


Create client using `clientv3.New`:

```go
// expect dial time-out on ipv4 blackhole
_, err := clientv3.New(clientv3.Config{
	Endpoints:   []string{"http://254.0.0.1:12345"},
	DialTimeout: 2 * time.Second,
})
```


```go
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
	mu       *sync.RWMutex

	ctx    context.Context
	cancel context.CancelFunc

	// Username is a user name for authentication.
	Username string
	// Password is a password for authentication.
	Password        string
	authTokenBundle credentials.Bundle

	callOpts []grpc.CallOption

	lgMu *sync.RWMutex
	lg   *zap.Logger
}
```

etcd client v3库针对gRPC服务的实现采用的负载均衡算法为 Round-robin。即针对每一个请求，Round-robin 算法通过轮询的方式依次从 endpoint 列表中选择一个 endpoint 访问(长连接)，使 etcd server 负载尽量均衡

```go
// dialWithBalancer dials the client's current load balanced resolver group.  The scheme of the host
// of the provided endpoint determines the scheme used for all endpoints of the client connection.
func (c *Client) dialWithBalancer(dopts ...grpc.DialOption) (*grpc.ClientConn, error) {
	creds := c.credentialsForEndpoint(c.Endpoints()[0])
	opts := append(dopts, grpc.WithResolvers(c.resolver))
	return c.dial(creds, opts...)
}

// dial configures and dials any grpc balancer target.
func (c *Client) dial(creds grpccredentials.TransportCredentials, dopts ...grpc.DialOption) (*grpc.ClientConn, error) {
	opts, err := c.dialSetupOpts(creds, dopts...)
	if err != nil {
		return nil, fmt.Errorf("failed to configure dialer: %v", err)
	}
	if c.authTokenBundle != nil {
		opts = append(opts, grpc.WithPerRPCCredentials(c.authTokenBundle.PerRPCCredentials()))
	}

	opts = append(opts, c.cfg.DialOptions...)

	dctx := c.ctx
	if c.cfg.DialTimeout > 0 {
		var cancel context.CancelFunc
		dctx, cancel = context.WithTimeout(c.ctx, c.cfg.DialTimeout)
		defer cancel() // TODO: Is this right for cases where grpc.WithBlock() is not set on the dial options?
	}
	target := fmt.Sprintf("%s://%p/%s", resolver.Schema, c, authority(c.Endpoints()[0]))
	conn, err := grpc.DialContext(dctx, target, opts...)
	if err != nil {
		return nil, err
	}
	return conn, nil
}
```
自动重试是ETCD能提供高可用特性的重要保证，此处需要注意的是：自动重试不会在etcd集群的同一节点上进行，这跟我们平常做的重试不同，就如前面提到的 etcd是通过grpc框架提供对集群访问的负载均衡策略的，所以此时client端会轮询的重试集群的每个节点，此外，自动重试只会重试一些特定的错误

要自动重试只需两步：(1)  创建backoff函数，也就是计算重试等待时间的函数。(2)  通过WithXXXInterceptor()，注册重试拦截器，这样每次GRPC有请求都会回调该拦截器。值得注意的是，这里我们看到Stream的重试拦截器的注册，其最大重试次数设置为了0(withMax())，也就是不重试，这其实是故意为之，因为Client端的Stream重试不被支持，即Client端需要重试Stream，需要自己做单独处理，不能通过拦截器
```go
// dialSetupOpts gives the dial opts prior to any authentication.
func (c *Client) dialSetupOpts(creds grpccredentials.TransportCredentials, dopts ...grpc.DialOption) (opts []grpc.DialOption, err error) {
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
		opts = append(opts, grpc.WithInsecure())
	}

	unaryMaxRetries := defaultUnaryMaxRetries
	if c.cfg.MaxUnaryRetries > 0 {
		unaryMaxRetries = c.cfg.MaxUnaryRetries
	}

	backoffWaitBetween := defaultBackoffWaitBetween
	if c.cfg.BackoffWaitBetween > 0 {
		backoffWaitBetween = c.cfg.BackoffWaitBetween
	}

	backoffJitterFraction := defaultBackoffJitterFraction
	if c.cfg.BackoffJitterFraction > 0 {
		backoffJitterFraction = c.cfg.BackoffJitterFraction
	}

	// Interceptor retry and backoff.
	// TODO: Replace all of clientv3/retry.go with RetryPolicy:
	// https://github.com/grpc/grpc-proto/blob/cdd9ed5c3d3f87aef62f373b93361cf7bddc620d/grpc/service_config/service_config.proto#L130
	rrBackoff := withBackoff(c.roundRobinQuorumBackoff(backoffWaitBetween, backoffJitterFraction))
	opts = append(opts,
		// Disable stream retry by default since go-grpc-middleware/retry does not support client streams.
		// Streams that are safe to retry are enabled individually.
		grpc.WithStreamInterceptor(c.streamClientInterceptor(withMax(0), rrBackoff)),
		grpc.WithUnaryInterceptor(c.unaryClientInterceptor(withMax(unaryMaxRetries), rrBackoff)),
	)

	return opts, nil
}
```

roundRobinQuorumBackoff返回了一个闭包，内部是重试间隔时长计算逻辑，这个逻辑说来也简单：(1) 若重试次数已经达到集群的法定人数(quorum)，则真正的计算间隔时长，间隔时长到期后，才进行重试。(2) 否则，直接返回0，也就是马上重试。就如前面所提到的，负载均衡策略是轮询，而这个重试逻辑一定要配合负载均衡是轮询策略才能达到的效果：假如你访问集群中的一台节点失败，可能是那台节点出问题了，但如果整个集群是好的，这时候马上重试，轮询到下台节点就行。但是，如果重试多次，集群大多数节点（法定人数）都失败了，那应该是集群出问题了，这时候就需要计算间隔时间，等会儿再重试看看问题能不能解决 
```go
// roundRobinQuorumBackoff retries against quorum between each backoff.
// This is intended for use with a round robin load balancer.
func (c *Client) roundRobinQuorumBackoff(waitBetween time.Duration, jitterFraction float64) backoffFunc {
	return func(attempt uint) time.Duration {
		// after each round robin across quorum, backoff for our wait between duration
		n := uint(len(c.Endpoints()))
		quorum := (n/2 + 1)
		if attempt%quorum == 0 {
			c.lg.Debug("backoff", zap.Uint("attempt", attempt), zap.Uint("quorum", quorum), zap.Duration("waitBetween", waitBetween), zap.Float64("jitterFraction", jitterFraction))
			return jitterUp(waitBetween, jitterFraction)
		}
		c.lg.Debug("backoff skipped", zap.Uint("attempt", attempt), zap.Uint("quorum", quorum))
		return 0
	}
}
```
重试拦截器

```go
// unaryClientInterceptor returns a new retrying unary client interceptor.
//
// The default configuration of the interceptor is to not retry *at all*. This behaviour can be
// changed through options (e.g. WithMax) on creation of the interceptor or on call (through grpc.CallOptions).
func (c *Client) unaryClientInterceptor(optFuncs ...retryOption) grpc.UnaryClientInterceptor {
	intOpts := reuseOrNewWithCallOptions(defaultOptions, optFuncs)
	return func(ctx context.Context, method string, req, reply interface{}, cc *grpc.ClientConn, invoker grpc.UnaryInvoker, opts ...grpc.CallOption) error {
		ctx = withVersion(ctx)
		grpcOpts, retryOpts := filterCallOptions(opts)
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
			c.GetLogger().Debug(
				"retrying of unary invoker",
				zap.String("target", cc.Target()),
				zap.Uint("attempt", attempt),
			)
			lastErr = invoker(ctx, method, req, reply, cc, grpcOpts...)
			if lastErr == nil {
				return nil
			}
			c.GetLogger().Warn(
				"retrying of unary invoker failed",
				zap.String("target", cc.Target()),
				zap.Uint("attempt", attempt),
				zap.Error(lastErr),
			)
			if isContextError(lastErr) {
				if ctx.Err() != nil {
					// its the context deadline or cancellation.
					return lastErr
				}
				// its the callCtx deadline or cancellation, in which case try again.
				continue
			}
			if c.shouldRefreshToken(lastErr, callOpts) {
				gterr := c.refreshToken(ctx)
				if gterr != nil {
					c.GetLogger().Warn(
						"retrying of unary invoker failed to fetch new auth token",
						zap.String("target", cc.Target()),
						zap.Error(gterr),
					)
					return gterr // lastErr must be invalid auth token
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
## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

1. [【深入浅出etcd系列】4. 客户端](https://bbs.huaweicloud.com/blogs/100128)