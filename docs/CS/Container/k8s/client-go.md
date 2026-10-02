## Introduction

client-go是一个调用kubernetes集群资源对象API的客户端，即通过client-go访问 kube-apiserver 实现对kubernetes集群中资源对象（包括deployment、service、ingress、replicaSet、pod、namespace、node等）的增删改查等操作
大部分对kubernetes进行前置API封装的二次开发都通过client-go这个第三方包来实现

client-go 支持四种客户端对象，分别是 `RESTClient`，`ClientSet`，`DynamicClient` 和 `DiscoveryClient`
每种客户端适用的场景不同，主要是对 `HTTP Request` 做了层层封装
其中，`RESTClient` 是最基础的客户端对象，它封装了 `HTTP Request`，实现了 `RESTful` 风格的 `API`
`ClientSet` 基于 `RESTClient`，封装了对于 `Resource` 和 `Version` 的请求方法
`DynamicClient` 相比于 `ClientSet` 提供了全资源，包括自定义资源的请求方法 `DiscoveryClient` 用于发现 `kube-apiserver` 支持的资源组，资源版本和资源信息

```mermaid
strict digraph {
    rankdir = "BT"
    ClientSet -> RESTClient
    DynamicClient -> RESTClient
    DiscoveryClient -> RESTClient
    RESTClient -> kubeconfig
}
```


kubeconfig用于管理访问kube-apiserver的配置信息
默认情况下 kubeconfig存放在`$HOME/.kube/config`文件中


```go
// veendor/k8s.io/client-go/tools/clientcmd/loader.go
// Load starts by running the MigrationRules and then
// takes the loading rules and returns a Config object based on following rules.
//   if the ExplicitPath, return the unmerged explicit file
//   Otherwise, return a merged config based on the Precedence slice
// A missing ExplicitPath file produces an error. Empty filenames or other missing files are ignored.
// Read errors or files with non-deserializable content produce errors.
// The first file to set a particular map key wins and map key's value is never changed.
// BUT, if you set a struct value that is NOT contained inside of map, the value WILL be changed.
// This results in some odd looking logic to merge in one direction, merge in the other, and then merge the two.
// It also means that if two files specify a "red-user", only values from the first file's red-user are used.  Even
// non-conflicting entries from the second file's "red-user" are discarded.
// Relative paths inside of the .kubeconfig files are resolved against the .kubeconfig file's parent folder
// and only absolute file paths are returned.
func (rules *ClientConfigLoadingRules) Load() (*clientcmdapi.Config, error) {
	if err := rules.Migrate(); err != nil {
		return nil, err
	}

	errlist := []error{}

	kubeConfigFiles := []string{}

	// Make sure a file we were explicitly told to use exists
	if len(rules.ExplicitPath) > 0 {
		if _, err := os.Stat(rules.ExplicitPath); os.IsNotExist(err) {
			return nil, err
		}
		kubeConfigFiles = append(kubeConfigFiles, rules.ExplicitPath)

	} else {
		kubeConfigFiles = append(kubeConfigFiles, rules.Precedence...)
	}

	kubeconfigs := []*clientcmdapi.Config{}
	// read and cache the config files so that we only look at them once
	for _, filename := range kubeConfigFiles {
		if len(filename) == 0 {
			// no work to do
			continue
		}

		config, err := LoadFromFile(filename)
		if os.IsNotExist(err) {
			// skip missing files
			continue
		}
		if err != nil {
			errlist = append(errlist, fmt.Errorf("Error loading config file \"%s\": %v", filename, err))
			continue
		}

		kubeconfigs = append(kubeconfigs, config)
	}

	// first merge all of our maps
	mapConfig := clientcmdapi.NewConfig()

	for _, kubeconfig := range kubeconfigs {
		mergo.Merge(mapConfig, kubeconfig)
	}

	// merge all of the struct values in the reverse order so that priority is given correctly
	// errors are not added to the list the second time
	nonMapConfig := clientcmdapi.NewConfig()
	for i := len(kubeconfigs) - 1; i >= 0; i-- {
		kubeconfig := kubeconfigs[i]
		mergo.Merge(nonMapConfig, kubeconfig)
	}

	// since values are overwritten, but maps values are not, we can merge the non-map config on top of the map config and
	// get the values we expect.
	config := clientcmdapi.NewConfig()
	mergo.Merge(config, mapConfig)
	mergo.Merge(config, nonMapConfig)

	if rules.ResolvePaths() {
		if err := ResolveLocalPaths(config); err != nil {
			errlist = append(errlist, err)
		}
	}
	return config, utilerrors.NewAggregate(errlist)
}
```

## Clients


### RESTClient

```go
// veendor/k8s.io/client-go/rest/config.go
// RESTClientFor returns a RESTClient that satisfies the requested attributes on a client Config
// object. Note that a RESTClient may require fields that are optional when initializing a Client.
// A RESTClient created by this method is generic - it expects to operate on an API that follows
// the Kubernetes conventions, but may not be the Kubernetes API.
func RESTClientFor(config *Config) (*RESTClient, error) {
	if config.GroupVersion == nil {
		return nil, fmt.Errorf("GroupVersion is required when initializing a RESTClient")
	}
	if config.NegotiatedSerializer == nil {
		return nil, fmt.Errorf("NegotiatedSerializer is required when initializing a RESTClient")
	}
	qps := config.QPS
	if config.QPS == 0.0 {
		qps = DefaultQPS
	}
	burst := config.Burst
	if config.Burst == 0 {
		burst = DefaultBurst
	}

	baseURL, versionedAPIPath, err := defaultServerUrlFor(config)
	if err != nil {
		return nil, err
	}

	transport, err := TransportFor(config)
	if err != nil {
		return nil, err
	}

	var httpClient *http.Client
	if transport != http.DefaultTransport {
		httpClient = &http.Client{Transport: transport}
		if config.Timeout > 0 {
			httpClient.Timeout = config.Timeout
		}
	}

	return NewRESTClient(baseURL, versionedAPIPath, config.ContentConfig, qps, burst, config.RateLimiter, httpClient)
}

```


```go

// Do formats and executes the request. Returns a Result object for easy response
// processing.
//
// Error type:
//  * If the request can't be constructed, or an error happened earlier while building its
//    arguments: *RequestConstructionError
//  * If the server responds with a status: *errors.StatusError or *errors.UnexpectedObjectError
//  * http.Client.Do errors are returned directly.
func (r *Request) Do() Result {
	r.tryThrottle()

	var result Result
	err := r.request(func(req *http.Request, resp *http.Response) {
		result = r.transformResponse(resp, req)
	})
	if err != nil {
		return Result{err: err}
	}
	return result
}
```

request

```go
// request connects to the server and invokes the provided function when a server response is
// received. It handles retry behavior and up front validation of requests. It will invoke
// fn at most once. It will return an error if a problem occurred prior to connecting to the
// server - the provided function is responsible for handling server errors.
func (r *Request) request(fn func(*http.Request, *http.Response)) error {
	//Metrics for total request latency
	start := time.Now()
	defer func() {
		metrics.RequestLatency.Observe(r.verb, r.finalURLTemplate(), time.Since(start))
	}()

	if r.err != nil {
		glog.V(4).Infof("Error in request: %v", r.err)
		return r.err
	}

	// TODO: added to catch programmer errors (invoking operations with an object with an empty namespace)
	if (r.verb == "GET" || r.verb == "PUT" || r.verb == "DELETE") && r.namespaceSet && len(r.resourceName) > 0 && len(r.namespace) == 0 {
		return fmt.Errorf("an empty namespace may not be set when a resource name is provided")
	}
	if (r.verb == "POST") && r.namespaceSet && len(r.namespace) == 0 {
		return fmt.Errorf("an empty namespace may not be set during creation")
	}

	client := r.client
	if client == nil {
		client = http.DefaultClient
	}

	// Right now we make about ten retry attempts if we get a Retry-After response.
	// TODO: Change to a timeout based approach.
	maxRetries := 10
	retries := 0
	for {
		url := r.URL().String()
		req, err := http.NewRequest(r.verb, url, r.body)
		if err != nil {
			return err
		}
		if r.ctx != nil {
			req = req.WithContext(r.ctx)
		}
		req.Header = r.headers

		r.backoffMgr.Sleep(r.backoffMgr.CalculateBackoff(r.URL()))
		if retries > 0 {
			// We are retrying the request that we already send to apiserver
			// at least once before.
			// This request should also be throttled with the client-internal throttler.
			r.tryThrottle()
		}
		resp, err := client.Do(req)
		updateURLMetrics(r, resp, err)
		if err != nil {
			r.backoffMgr.UpdateBackoff(r.URL(), err, 0)
		} else {
			r.backoffMgr.UpdateBackoff(r.URL(), err, resp.StatusCode)
		}
		if err != nil {
			// "Connection reset by peer" is usually a transient error.
			// Thus in case of "GET" operations, we simply retry it.
			// We are not automatically retrying "write" operations, as
			// they are not idempotent.
			if !net.IsConnectionReset(err) || r.verb != "GET" {
				return err
			}
			// For the purpose of retry, we set the artificial "retry-after" response.
			// TODO: Should we clean the original response if it exists?
			resp = &http.Response{
				StatusCode: http.StatusInternalServerError,
				Header:     http.Header{"Retry-After": []string{"1"}},
				Body:       ioutil.NopCloser(bytes.NewReader([]byte{})),
			}
		}

		done := func() bool {
			// Ensure the response body is fully read and closed
			// before we reconnect, so that we reuse the same TCP
			// connection.
			defer func() {
				const maxBodySlurpSize = 2 << 10
				if resp.ContentLength <= maxBodySlurpSize {
					io.Copy(ioutil.Discard, &io.LimitedReader{R: resp.Body, N: maxBodySlurpSize})
				}
				resp.Body.Close()
			}()

			retries++
			if seconds, wait := checkWait(resp); wait && retries < maxRetries {
				if seeker, ok := r.body.(io.Seeker); ok && r.body != nil {
					_, err := seeker.Seek(0, 0)
					if err != nil {
						glog.V(4).Infof("Could not retry request, can't Seek() back to beginning of body for %T", r.body)
						fn(req, resp)
						return true
					}
				}

				glog.V(4).Infof("Got a Retry-After %s response for attempt %d to %v", seconds, retries, url)
				r.backoffMgr.Sleep(time.Duration(seconds) * time.Second)
				return false
			}
			fn(req, resp)
			return true
		}()
		if done {
			return nil
		}
	}
}
```
### ClientSet

ClientSet 对比RESTClient使用更加便捷

```go
func NewForConfig(c *rest.Config) (*CoreV1Client, error) {
	config := *c
	if err := setConfigDefaults(&config); err != nil {
		return nil, err
	}
	client, err := rest.RESTClientFor(&config)
	if err != nil {
		return nil, err
	}
	return &CoreV1Client{client}, nil
}
```


```go
type Clientset struct {
	*discovery.DiscoveryClient
	admissionregistration *admissionregistrationinternalversion.AdmissionregistrationClient
	core                  *coreinternalversion.CoreClient
	apps                  *appsinternalversion.AppsClient
	authentication        *authenticationinternalversion.AuthenticationClient
	authorization         *authorizationinternalversion.AuthorizationClient
	autoscaling           *autoscalinginternalversion.AutoscalingClient
	batch                 *batchinternalversion.BatchClient
	certificates          *certificatesinternalversion.CertificatesClient
	events                *eventsinternalversion.EventsClient
	extensions            *extensionsinternalversion.ExtensionsClient
	networking            *networkinginternalversion.NetworkingClient
	policy                *policyinternalversion.PolicyClient
	rbac                  *rbacinternalversion.RbacClient
	scheduling            *schedulinginternalversion.SchedulingClient
	settings              *settingsinternalversion.SettingsClient
	
```


CoreV1Client
```go
// CoreV1Client is used to interact with features provided by the  group.
type CoreV1Client struct {
	restClient rest.Interface
}
```
CoreV1Interface中包含了各种kubernetes对象的调用接口，例如PodsGetter是对kubernetes中pod对象增删改查操作的接口。ServicesGetter是对service对象的操作的接口

```go
type CoreV1Interface interface {
	RESTClient() rest.Interface
	ComponentStatusesGetter
	ConfigMapsGetter
	EndpointsGetter
	EventsGetter
	LimitRangesGetter
	NamespacesGetter
	NodesGetter
	PersistentVolumesGetter
	PersistentVolumeClaimsGetter
	PodsGetter
	PodTemplatesGetter
	ReplicationControllersGetter
	ResourceQuotasGetter
	SecretsGetter
	ServicesGetter
	ServiceAccountsGetter
}



### DynamicClient



## informer



`informer` 机制的核心组件包括：

```
  Reflector
```

  : 主要负责两类任务：

  1. 通过 `client-go` 客户端对象 list `kube-apiserver` 资源，并且 watch `kube-apiserver` 资源变更。
  2. 作为生产者，将获取的资源放入 `Delta FIFO` 队列。

```


## Informer

> [!WARNING]
> 以下描述基于 **DeltaFIFO**。从 **Kubernetes v1.36 起，默认队列已经换成 RealFIFO**（`InOrderInformers` 已 GA 且 LockToDefault，不可关闭），同一 key 的多次变更不再被合并。老的手写 informer 代码如果依赖"同一 key 只会被处理一次"的旧语义，行为会发生变化。详见下文「队列实现的变化」。


在Informer架构设计中，有多个核心组件，分别介绍如下。 

1. Reflector 
   Reflector用于监控（Watch）指定的Kubernetes资源，当监控的资源发生变化时，触发相应的变更事件，例如Added（资源添加）事件、Updated（资源更新）事件、Deleted（资源删除）事件，并将其资源对象存放到本地缓存DeltaFIFO中。 
2. DeltaFIFO 
   DeltaFIFO可以分开理解，FIFO是一个先进先出的队列，它拥有队列操作的基本方法，例如Add、Update、Delete、List、Pop、Close等，而Delta是一个资源对象存储，它可以保存资源对象的操作类型，例如Added（添加）操作类型、Updated（更新）操作类型、Deleted（删除）操作类型、Sync（同步）操作类型等。 
3. Indexer 
   Indexer是client-go用来存储资源对象并自带索引功能的本地存储，Reflector从DeltaFIFO中将消费出来的资源对象存储至Indexer。Indexer与Etcd集群中的数据完全保持一致。client-go可以很方便地从本地存储中读取相应的资源对象数据，而无须每次从远程Etcd集群中读取，以减轻Kubernetes API Server和Etcd集群的压力



Informer是一个持久运行的goroutine

通过Informer机制可以很容易地监控我们所关心的资源事件，例如，当监控Kubernetes Pod资源时，如果Pod资源发生了Added（资源添加）事件、Updated（资源更新）事件、Deleted（资源删除）事件，就通知client-go，告知Kubernetes资源事件变更了并且需要进行相应的处理



Informer是可以共享使用的 也称为Shared Informer 同一类资源Informer可以共享Reflector

主要负责三类任务：

1. 作为消费者，将 `Reflector` 放入队列的资源拿出来。
2. 将资源交给 `indexer` 组件。
3. 交给 `indexer` 组件之后触发回调函数，处理回调事件。

`Indexer`: `indexer` 组件负责将资源信息存入到本地内存数据库（实际是 `map` 对象），该数据库作为缓存存在，
其资源信息和 `ETCD` 中的资源信息完全一致（得益于 `watch` 机制）。
因此，`client-go` 可以从本地 `indexer` 中读取相应的资源，而不用每次都从 `kube-apiserver` 中获取资源信息
这也实现了 `client-go` 对于实时性的要求。





### Resync

Resync机制会将Indexer本地存储中的资源对象同步到DeltaFIFO中，并将这些资源对象设置为Sync的操作类型。Resync函数在Reflector中定时执行，它的执行周期由NewReflector函数传入的resyncPeriod参数设定

> [!IMPORTANT]
> resync 的真实语义极易被误解，有三点必须说清楚：
> 
> 1. **`Reflector.Resync` 不发起任何 apiserver 请求**，它只是调用 `store.Resync()`，把本地缓存里的对象重新投递一遍 Sync delta。最终 handler 收到的是 `OnUpdate(old, new)` 且 `old == new`。
> 2. **周期性的全量 re-LIST 只在 watch 断连时发生**，与 resync 毫无关系。
> 3. **`HasSynced()` 与 resync 完全无关**（源码注释里明确写了 "This is unrelated to 'resync'"），它标记的是本地缓存是否已经灌满第一轮数据。
> 
> 另外，resync 事件只会投递给**显式请求了 resync 的 handler**——分发时会按 listener 是否订阅来过滤。
> kube-controller-manager 的 resync 周期实际落在 **12h~24h** 之间（`MinResyncPeriod` 默认 12h，`ResyncPeriod()` 里乘 `rand.Float64() + 1`，即因子落在 `[1, 2)`），刻意随机化以避免多个控制器 lock-step 同时打爆 apiserver。回源码核对：`cmd/kube-controller-manager/app/controllermanager.go:191`、`staging/src/k8s.io/controller-manager/config/v1alpha1/defaults.go:31`。

### 队列实现的变化

v1.36 最容易被忽略的底层改动：Informer 的队列从 `DeltaFIFO` 换成了 `RealFIFO`。选择逻辑在 `tools/cache/controller.go` 的 `newQueueFIFO` 里：

```go
if clientgofeaturegate.FeatureGates().Enabled(clientgofeaturegate.InOrderInformers) {
	options := RealFIFOOptions{...}
	if clientgofeaturegate.FeatureGates().Enabled(clientgofeaturegate.AtomicFIFO) {
		options.AtomicEvents = true
		options.UnlockWhileProcessing = ...
	}
	f := NewRealFIFOWithOptions(options)
} else {
	f := NewDeltaFIFOWithOptions(...)   // 1.36 中此分支已不可达
}
```

| 对比项 | DeltaFIFO（已不可达） | RealFIFO（当前默认） |
|---|---|---|
| 内部结构 | `map[string]Deltas` + `queue []string` | `items []Delta` 扁平切片 |
| 同一 key 多次变更 | **合并**成一条 Deltas | **逐条独立投递**，保持顺序 |
| Pop 处理期间 | 全程持 FIFO 锁 | 满足条件时释放锁（UnlockWhileProcessing） |
| 批量消费 | 不支持 | 支持 PopBatch，默认批大小 1000 |
| 原子事件 | 无 | ReplacedAll / SyncAll 单条携带全量对象列表 |

连带影响：默认路径下 `KnownObjects == nil`，DeltaFIFO 那套靠 knownObjects 做删除判定与去重的逻辑不再生效，改由 `reconcileReplacement` 在消费侧对账。

### 拉取方式的演进：流式 list

v1.36 另一处影响握手方式的改动是 **WatchList（流式 list）**：Reflector 不再"先 LIST 再 WATCH"，而是直接发一个 `watch=true` + `sendInitialEvents=true` 的请求，由服务端把"当前全量"作为一串合成的 ADDED 事件流回来，最后用一个带 `k8s.io/initial-events-end` 注解的 BOOKMARK 收尾。

客户端侧由**独立的** `WatchListClient` gate 控制，1.35 起默认开启：

| 层 | gate | v1.36 状态 |
|---|---|---|
| client-go | `WatchListClient` | Beta，默认 true |
| kube-apiserver | `WatchList` | Beta，默认 true |

判定逻辑只有两行（`tools/cache/reflector.go:361`）：gate 开着、且 listerWatcher 没声明"不支持该语义"。服务端不支持时会**自动回退**到传统 List 并打一条日志——生产集群里看到 "Falling back to regular list" 是正常现象，不是故障。

两处容易搞错的细节：

- `WatchListPageSize` 只影响传统 List 的分页，对流式 list **无效**（流式路径不设 `Limit`）。
- 流式 list 收到结束 BOOKMARK 后会**复用同一条 watch 流**继续收增量，不重新建连。

服务端如何合成这串事件、以及缓存层怎么服务这类请求，见 [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)。

## WorkQueue

Informer 负责把数据搬到缓存并触发回调，**真正的业务解耦发生在 WorkQueue**。它在 `client-go/util/workqueue/` 下，值得单独看，因为它的双集合设计是整套声明式模型的关键一环。

> [!TIP]
> WorkQueue 里放的**只有 `namespace/name` 这样一个字符串，没有对象**。worker 取出 key 之后必须重新从 lister 读最新状态。队列里没有对象，这是"水平触发"能成立的前提。

核心是 `dirty` 与 `processing` 两个集合：

```go
func (q *Type) Add(item interface{}) {
	q.cond.L.Lock()
	defer q.cond.L.Unlock()
	if q.shuttingDown { return }
	if q.dirty.Has(item) {            // 已在待处理集合 → 幂等丢弃
		return
	}
	q.dirty.Insert(item)
	if q.processing.Has(item) {       // 正在处理 → 只标脏，不入队
		return
	}
	q.queue.Push(item)
	q.cond.Signal()
}

func (q *Type) Done(item interface{}) {
	q.processing.Delete(item)
	if q.dirty.Has(item) {            // 处理期间又被标脏 → 重新入队
		q.queue.Push(item)
		q.cond.Signal()
	}
}
```

不变式：`queue` 中的元素绝不在 `processing` 集合中。由此得出两个性质——同一 key 不会被两个 worker 同时 Get 到（**串行**）；而 `dirty` 保证处理期间到达的事件不会丢失（**丢的是"值"，不是"信号"**）。

限速是三层嵌套：基础类型（dirty/processing）→ delayingType（最小堆 + 10s heartbeat 兜底）→ rateLimitingType。默认参数：

| 参数 | 值 |
|---|---|
| per-item 指数退避基数 | 5ms |
| per-item 退避上限 | 1000s |
| 全局 token bucket QPS | 10 |
| 全局 bucket burst | 100 |

退避序列为 `5ms × 2^(n-1)`，即 5ms → 10ms → 20ms → … → 82s。控制器通常设有最大重试次数（Deployment 为 15 次），超过才丢弃并记录 error。

## reconcile 循环

把所有部件拼起来，就是几乎每个控制器都在复制的同一个模板：

```go
func (dc *DeploymentController) processNextWorkItem(ctx context.Context) bool {
	key, quit := dc.queue.Get()      // 阻塞取出一个 key
	if quit { return false }
	defer dc.queue.Done(key)         // 必须配对，否则该 key 永久锁死在 processing
	err := dc.syncHandler(ctx, key)
	dc.handleErr(ctx, err, key)
	return true
}

func (dc *DeploymentController) handleErr(ctx context.Context, err error, key string) {
	if err == nil { dc.queue.Forget(key); return }
	if dc.queue.NumRequeues(key) < maxRetries {
		dc.queue.AddRateLimited(key)  // 带退避重新入队
		return
	}
	utilruntime.HandleError(err)
	dc.queue.Forget(key)              // 超过上限才放弃
}
```

`syncHandler` 内部则是：拆 key → 从 lister 取对象 → `DeepCopy()` 防止污染缓存 → 对比期望与实际 → 写 apiserver。注意这里**遇错不做任何缓存清理**，只是重新入队，错误处理全靠"下一次再读一遍最新状态重算"。

这个模板之所以能自愈，正因为队列里只有 key：中间丢多少次事件都无所谓，只要最后一次被看到，系统就收敛到正确状态。

具体的控制器实现可对照 [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)（级联 RS/Pod 的关系维护）与 [Job Controller](/docs/CS/Container/k8s/jobController.md)（终态与重试语义）。

> [!NOTE]
> 因为 resync 会投递大量 `old == new` 的无变化事件，控制器里常见 `if cur.ResourceVersion == old.ResourceVersion { return }` 这样的显式过滤（如 Deployment controller 的 `updateReplicaSet`），专门用来砍掉 resync 噪音。

## Links

- [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [Kubernetes: client-go 源码剖析（一）](https://www.cnblogs.com/xingzheanan/p/17904625.html)
2. [client-go v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/staging/src/k8s.io/client-go)
3. [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
