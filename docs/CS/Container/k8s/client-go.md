## Introduction

client-go 是 Kubernetes 官方 Go 客户端，核心职责是把 REST HTTP API 封装成一个**可复用的、支持多种客户端类型的、带本地缓存的**对象。它暴露四种高层客户端：

```
ClientSet        强类型，覆盖所有内置组/版本，编译期类型安全
DynamicClient    弱类型（runtime.Unstructured），覆盖所有资源包括 CRD
DiscoveryClient  发现 apiserver 支持哪些 GVR
RESTClient       底层原语，以上三种都基于它
```

所有四种最终都收敛到同一条链路：`rest.Config → Transport → Request → http.Client`。Informer 机制则在 REST 层之上叠加了"List + Watch + 本地缓存 + 事件回调"这一整套声明式同步模式。

```mermaid
strict digraph {
    rankdir = "BT"
    ClientSet -> RESTClient
    DynamicClient -> RESTClient
    DiscoveryClient -> RESTClient
    RESTClient -> Request -> http.Client -> RoundTripper
    RoundTripper -> tlsCache
    RoundTripper -> [auth wrappers]
    tlsCache -> rest.Config
    [auth wrappers] -> rest.Config
    rest.Config -> kubeconfig
}
```

## Configuration Loading

client-go 的配置来自 `rest.Config`——但用户通常不直接构造它，而是通过三种标准入口加载：

| 入口 | 适用场景 | 源码 |
|---|---|---|
| `clientcmd.BuildConfigFromFlags(masterUrl, kubeconfigPath)` | 大多数 kubectl 风格 CLI | `tools/clientcmd/client_config.go` |
| `clientcmd.NewDefaultClientConfigLoadingRules().Load()` | 多配置文件优先级合并 | `tools/clientcmd/loader.go` |
| `rest.InClusterConfig()` | Pod 内运行的应用 | `rest/config.go:275` |

### Precedence 链

`ClientConfigLoadingRules.Precedence` 是一个字符串 slice，默认为：

```
KUBERNETES_SERVICE_HOST / KUBERNETES_SERVICE_PORT → InCluster 分支
  → KUBECONFIG 环境变量（可能多个，用 : 分隔）
  → ~/.kube/config
  → /etc/kubernetes/admin.conf
```

合并规则由 `tools/clientcmd/loader.go:Load()` 严格定义：

```go
// 1. Migrate() — 处理旧格式 kubeconfig
// 2. 逐个 ReadConfigFile()，不存在的跳过，读失败的收集到 errlist
// 3. map 字段（clusters/contexts/users）→ mergo.Merge 正向遍历，先到先赢
// 4. struct 字段（current-context）    → mergo.Merge 反向遍历，后到覆盖
// 5. ResolveLocalPaths() — 相对路径全部转绝对路径
```

"先到先赢"只作用于 map——如果两个文件都定义了 `red-user`（map key），**第一个文件的值永不被覆盖**，哪怕第二个文件多了非冲突字段。这是 mergo 的默认行为，也是 kubeconfig 合并最容易踩坑的点。

### In-Cluster Config

Pod 内的路径完全不同——不走 kubeconfig 文件，而是读取：

- `/var/run/secrets/kubernetes.io/serviceaccount/token`   → BearerToken
- `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt`  → CAData
- 环境变量 `KUBERNETES_SERVICE_HOST` + `KUBERNETES_SERVICE_PORT` → Host

这三项由 service account 的 admission controller 自动写入 Pod manifest（见 [准入控制](/docs/CS/Container/k8s/apiserver.md) 的 MutatingAdmissionWebhook）。

## Transport Construction

`rest.TransportFor(config)` 是连接 apiserver 的 RoundTripper 工厂，内部组装链分三层：

```
rest.Config.TransportConfig() → transport.Config → transport.New(cfg) → HTTPWrappersForConfig(cfg, rt)
```

### 底层 RoundTripper：tlsCache

`transport.New(config)`（`transport/transport.go:38`）第一步决定**基础 Transport**：

```go
if config.Transport != nil {
    rt = config.Transport                    // 用户直接传了 http.RoundTripper → 用它
} else {
    rt, err = tlsCache.get(config)           // 正常路径：走 TLS 缓存
}
return HTTPWrappersForConfig(config, rt)     // 再套一层认证/UA/Impersonate
```

`tlsCache`（`transport/cache.go`）是一个包级单例 `var tlsCache = newTlsCache()`，它缓存的是 **TLS 配置完全相同** 的 `http.Transport`，key 由 CA cert hash + client cert/key hash + serverName + insecure 拼接而成。缓存命中直接返回，不命中才新建 `http.Transport` + `tls.Config`。

TLS 配置的关键默认值（`transport/transport.go:80`）：

| 字段 | 值 |
|---|---|
| MinVersion | tls.VersionTLS12 |
| InsecureSkipVerify | 来自 `Config.TLS.Insecure`（即 kubeconfig 的 `insecure-skip-tls-verify: true`） |
| RootCAs | 来自 CAData 或 CAFile；两者都空时用系统默认 |
| GetClientCertificate | 静态 cert/key 或 cachingCertificateLoader（每秒最多读一次磁盘） |

### HTTPWrappersForConfig：认证/UA/Impersonate 层

拿到底层 Transport 后，`HTTPWrappersForConfig`（`transport/round_trippers.go:41`）按**自内向外**的顺序包装——实际请求进来时先遇到的是最后一层 Impersonate，然后逐层下钻到底层 TLS Transport：

```
① config.WrapTransport(rt)          // 用户自定义 wrapper（最内层）
② DebugWrappers(rt)                 // klog V(6) 以上才启用，加 httptrace 埋点
③ 认证 wrapper（三选一，互斥）：
   ├── NewBearerAuthWithRefreshRoundTripper   // 优先
   ├── NewBasicAuthRoundTripper               // 回退
   └── 都没有 → 裸 rt（x509 认证由 TLS 层承担，不在 HTTP 层）
④ NewUserAgentRoundTripper          // 加 User-Agent: client-go/<version>
⑤ NewImpersonatingRoundTripper      // 加 Impersonate-User / Impersonate-Group 等 headers
```

> [!TIP]
> **Bearer Token 可以动态刷新**。`NewBearerAuthWithRefreshRoundTripper` 在 tokenFile 非空时构造 `CachedFileTokenSource`，用 `os.Stat().ModTime()` 检测文件变化（每秒最多一次），一旦变化就读取新 token。这对 mount 了 ServiceAccount token 的 Pod 很重要——kubelet 会定期轮换 token 文件。

`WrapTransport` 是另一条可以插入自定义 wrapper 的入口，最终用 `Wrappers(fns ...)` 合成：

```go
func Wrappers(fns ...WrapperFunc) WrapperFunc {
    return func(rt http.RoundTripper) http.RoundTripper {
        base := rt
        for _, fn := range fns {
            if fn != nil { base = fn(base) }
        }
        return base
    }
}
```

### 连接池参数

Go 标准库 `http.Transport` 会从 `http.DefaultTransport` 复制默认值，client-go 没有显式覆盖这些（`transport/transport.go` 里没有改 MaxIdleConns 等字段）。所以**最终连接池参数就是 Go runtime 默认值**：

| 参数 | Go 默认 |
|---|---|
| MaxIdleConns | 100 |
| MaxIdleConnsPerHost | 2（Go 1.20 起变成基于 `Dial` 动态决定，可能更大） |
| IdleConnTimeout | 90s |
| TLSHandshakeTimeout | 10s |

> [!WARNING]
> 如果你在高 QPS 场景下观察到大量 TIME_WAIT 连接或新建连接延迟，问题可能就在 `MaxIdleConnsPerHost` 这个默认 2 上——client-go 没有调大它。解决办法是在 `rest.Config.WrapTransport` 里传入一个预配好连接池参数的 Transport。

## RESTClient + Request

拿到 `rest.Config` 后，`RESTClientFor(config)`（`rest/config.go`）组装最终产物：

```go
// rest/config.go:218
func RESTClientFor(config *Config) (*RESTClient, error) {
    baseURL, versionedAPIPath := defaultServerUrlFor(config)
    transport := TransportFor(config)
    var httpClient *http.Client
    if transport != http.DefaultTransport || config.Timeout > 0 {
        httpClient = &http.Client{Transport: transport, Timeout: config.Timeout}
    }
    return NewRESTClient(baseURL, versionedAPIPath, config.ContentConfig,
        qps, burst, config.RateLimiter, httpClient)
}
```

关键：`versionedAPIPath` 由 `GroupVersion` 决定——Core 组是 `/api/v1`，apps 组是 `/apis/apps/v1`。RESTClient 只服务一个固定的 baseURL + versionedAPIPath + Serializer 组合，这就是为什么 ClientSet 需要为每个 GV 创建独立子 client。

### Request 生命周期

`RESTClient.Get().Namespace("default").Resource("pods").Do()` 是一条典型的 Request 构造链，最终走到 `request.Do()`：

```go
// rest/request.go
func (r *Request) Do() Result {
    r.tryThrottle()                              // rate limiter 扣 token
    return r.request(func(req, resp) Result {
        return r.transformResponse(resp, req)   // HTTP 响应 → Result
    })
}
```

`request()` 方法（`rest/request.go`）内部是一个带重试的循环：

```
maxRetries = 10
for {
    url := r.URL().String()                              // 从 baseURL + path 拼接
    req, _ := http.NewRequest(r.verb, url, r.body)       // body 已由 Request 自己管理
    
    req.Header = r.headers                                // Accept, Content-Type 等
    req = req.WithContext(r.ctx)                          // 带 context
    
    resp, err := client.Do(req)                           // ← RoundTripper 包装链在这里生效
    if err != nil {
        if IsConnectionReset(err) && verb == "GET" {
            resp = &http.Response{                        // GET 请求的 "connection reset" 特殊处理
                StatusCode: 500, Header: Retry-After: 1s
            }
        }
        if !IsConnectionReset(err) || verb != "GET" { return err }
    }
    
    // 关键：无论 retry 与否，都要确保 resp.Body 被完整读取并关闭
    // 否则 TCP 连接不会回收到连接池
    defer func() {
        if resp.ContentLength <= 2 << 10 {
            io.Copy(Discard, &LimitedReader{resp.Body, N: 2KB})
        }
        resp.Body.Close()
    }()
    
    seconds, wait := checkWait(resp)                      // 读 Retry-After header
    retries++
    if wait && retries < maxRetries {
        if seeker, ok := r.body.(io.Seeker); ok {
            seeker.Seek(0, 0)                             // body 可回退才能重试写操作
        }
        Sleep(Retry-After 秒)
        continue
    }
    fn(req, resp)    // 最终处理
    return nil
}
```

三个最容易忽略的点：

1. **写请求只有 body 实现了 `io.Seeker` 才能重试**——`bytes.Buffer` 满足这个接口，但 `os.File` 不满足。所以如果你用文件对象当 POST body，遇到 `Retry-After` 就会直接失败。
2. **Retry-After header 是 apiserver 在 APF 排队超时（503）或优雅关闭时返回的**，client-go 严格遵守它。
3. **resp.Body 必须读完才 Close**——不读完的话 Go 认为"连接可能还有数据"，直接关掉而不是复用。这是"为什么你的 client 总是新建 TCP 连接"的常见原因。

### URL 拼接

URL 构造（`rest/request.go:URL()`）最终是 `r.URL().Path + query params`。各层逐步追加：

```
baseURL:     https://cluster.example.com
  → + versionedAPIPath: /api/v1
  → + Namespace:        /namespaces/default
  → + Resource:         /pods
  → + Name:             /my-pod
  → + Query params:     ?limit=100&resourceVersion=12345
```

最终：`https://cluster.example.com/api/v1/namespaces/default/pods/my-pod?resourceVersion=12345`

### 请求级 Headers

`Request` 在 `newHTTPRequest()` 里设置这些 headers（在 RoundTripper 包装之前）：

| Header | 值 | 来源 |
|---|---|---|
| Accept | `application/json, application/yaml, application/vnd.kubernetes.protobuf, application/appleprotobuf;stream=watch` | `ContentConfig.AcceptContentTypes` |
| Content-Type | 与 Accept 匹配的首项 | 协商结果 |
| User-Agent | `client-go/<git-version>`（可由 Config 覆盖） | RoundTripper 层追加 |
| Authorization | `Bearer <token>` | RoundTripper 层追加 |
| Impersonate-* | 用户伪装值 | RoundTripper 层追加 |

## ClientSet vs DynamicClient

### ClientSet

`k8s.io/client-go/kubernetes` 包是代码生成的强类型客户端，`NewForConfig(c *rest.Config)` 内部就是为每个 GV 调一次 `RESTClientFor`。`CoreV1Client` 就是最简单的一例：

```go
// kubernetes/clientset.go
type CoreV1Client struct { restClient rest.Interface }
func (c *CoreV1Client) Pods(namespace string) PodInterface {
    return newPods(c, namespace)  // newPods 里再构造 Resource("pods") 请求
}
```

### DynamicClient

DynamicClient（`client-go/dynamic/simple.go`）是一个基于 `RESTClient` + `DiscoveryClient` 的泛型客户端，核心差异是它的 **Resource() 接受 `schema.GroupVersionResource` 作为运行时参数**：

```go
// dynamic/simple.go
func (c *simpleClient) Resource(resource schema.GroupVersionResource) NamespaceableResourceInterface {
    return &dynamicResourceClient{restClientForResource(c, resource), resource, ...}
}
```

`restClientForResource` 会根据 GVR 拼装正确的 `versionedAPIPath`——它用 `DiscoveryClient.ServerGroups()` 找 group/version 的 API path（core 组是 `/api/v1`，其它是 `/apis/<group>/<version>`）。

DynamicInformers（`client-go/dynamic/dynamicinformer/informer.go`）更进一步：它用 `SharedInformerFactory` 为每个发现到的 GVR 创建 Informer 实例，这样一个 DynamicInformer 就能监听集群里**所有资源**的变更，包括运行时才装的 CRD。

## Watch Chain

Watch 是 client-go 到 apiserver 的长连接核心。它的链路从 `Request.Watch()` 开始，到 Reflector 的事件循环结束。

### Request.Watch

`rest/request.go:Watch(ctx)` 和 `Do()` 的关键差异：**Do 会 retry 写操作，Watch 不做 QPS 限流**（因为 watch 不是高频操作）。它直接发 `GET ?watch=true` 请求，收到 200 OK 后进入 `newStreamWatcher`：

```go
// rest/request.go:760
func (r *Request) Watch(ctx context.Context) (watch.Interface, error) {
    // 直接 client.Do，不走 rateLimiter
    resp, err := r.c.Client.Do(req)
    if err == nil && resp.StatusCode == 200 {
        return r.newStreamWatcher(ctx, resp)   // ← 持有 resp.Body，不关闭
    }
    // retryable 错误（EOF, timeout）用 retryFn 重发
}

// rest/request.go:833
func (r *Request) newStreamWatcher(ctx context.Context, resp *http.Response) (watch.Interface, error) {
    // 1. Negotiator.StreamDecoder → framer.NewFrameReader(resp.Body)
    //    framer 负责把 HTTP 响应体按帧切分（JSON 是按行，protobuf 是 varint 长度前缀）
    frameReader := framer.NewFrameReader(resp.Body)
    
    // 2. streaming.NewDecoder → 每帧解出一个 watch.Event{}
    watchEventDecoder := streaming.NewDecoder(frameReader, streamingSerializer)
    
    // 3. NewStreamWatcherWithLogger → 一个 goroutine 不停地 Read()，解出的事件写入 resultChan
    return watch.NewStreamWatcherWithLogger(...,
        restclientwatch.NewDecoder(watchEventDecoder, objectDecoder), ...), nil
}
```

注意 `resp.Body` 的生命周期——它**不在这里关闭**，而是由 StreamWatcher 内部的 goroutine 持有，持续读 JSON 行直到流关闭或出错。一旦连接断了（EOF 或 error），goroutine 会关闭 resultChan，Reflector 那边检测到 channel close 就知道该重连了。

### Reflector 主循环

Reflector（`tools/cache/reflector.go`）是 Informer 的数据入口，它在一个后台 goroutine 里跑 `RunWithContext`：

```go
// reflector.go:423
func (r *Reflector) RunWithContext(ctx context.Context) {
    r.delayHandler.Until(ctx, true, true, func(ctx) (bool, error) {
        if err := r.ListAndWatchWithContext(ctx); err != nil {
            r.watchErrorHandler(ctx, r, err)   // 指数退避后重进 ListAndWatch
        }
        return false, nil   // 永不返回
    })
}
```

`delayHandler` 内部是标准的 800ms 起始、2x 乘、30s 封顶的指数退避，且有 "2 分钟没退过就 reset" 机制——这就是为什么集群恢复后 Reflector 很快就能追上来。

### ListAndWatch 主入口

```go
// reflector.go:470
func (r *Reflector) ListAndWatchWithContext(ctx context.Context) error {
    fallbackToList := !r.useWatchList
    
    // 路径 A: WatchList（流式 list，默认开启）
    if r.useWatchList {
        w, err = r.watchList(ctx)    // 内部已经把 snapshot 存进 store 了
        if err != nil {
            fallbackToList = true    // 服务端不支持就降级
        }
    }
    
    // 路径 B: 传统 List + Watch
    if fallbackToList {
        r.list(ctx)                  // 全量 List → store.Replace
        w = nil                      // 后面的 watchWithResync 会重新建 Watch
    }
    
    return r.watchWithResync(ctx, w)  // 开始增量 Watch + 后台 Resync
}
```

两个路径的共同点是**最终都走到同一个增量 Watch 循环**——WatchList 只是省去了单独一次 list 请求，把"全量快照"合成事件流的形式通过同一条 watch 连接返回。

### WatchList 路径（流式 List）

`watchList`（`reflector.go:804`）发的是一条特殊 Watch 请求：

```go
options := metav1.ListOptions{
    ResourceVersion:      lastKnownRV,
    AllowWatchBookmarks:  true,
    SendInitialEvents:    ptr.To(true),               // 🔑 关键：告诉 apiserver 先把"当前全量"合成事件流回来
    ResourceVersionMatch: metav1.ResourceVersionMatchNotOlderThan,
    TimeoutSeconds:       &timeoutSeconds,
}
w, err = r.listerWatcher.WatchWithContext(ctx, options)
```

然后它用一个**临时 Store**（`NewStore(...)`）来收集事件，直到收到带 `k8s.io/initial-events-end` 注解的 **Bookmark** 事件：

```go
// handleListWatch 收到 Bookmark 时退出事件消费循环
exitOnWatchListBookmarkReceived := true
watchListBookmarkReceived, err := handleListWatch(..., exitOnWatchListBookmarkReceived=true, ...)
if watchListBookmarkReceived { break }

// 成功拿到快照 → 替换正式 Store
r.store.Replace(temporaryStore.List(), resourceVersion)
// 然后继续复用同一个 w 做增量 Watch
return w, nil
```

这就是为什么 WatchList 更高效——**一条 HTTP 连接同时承载了"全量同步"和"后续增量"两段职责**，省掉了传统路径里"先 List 再单独建 Watch"的第二次 TLS 握手和第二次请求开销。

### 传统 list() 路径

`list()`（`reflector.go:674`）的关键设计：

1. **分页**：`pager.SimplePageFunc`，默认每次 500 条，但在 `ResourceVersion != ""` 时把 `PageSize = 0`——这是为了**强制从 watch cache 走**（带 `resourceVersion` 的 list 在 apiserver 侧会优先用 watch cache，不带 Limit 时一次性返回全量）。
2. **资源版本过期处理**：如果 list 时带的 resourceVersion 被 etcd 截断（Expired / TooLarge），自动 fallback 到 RV="" 重走一次。
3. **store.Replace**：拿到完整 list 后直接替换——不是 Update + Delete 对账，而是全量替换。这意味着旧对象整体被覆盖掉。

### handleWatch 事件消费循环

拿到 Watch 连接后，`watch()` 方法（`reflector.go:561`）进入**增量事件循环**：

```go
// reflector.go:620 → handleWatch
for {
    w, err := r.listerWatcher.WatchWithContext(ctx, options)   // WatchList 路径复用已有 w；传统路径新建
    err = handleWatch(ctx, start, w, r.store, ...)             // 消费事件直到出错
    w = nil                                                     // 触发下一次循环重建
    
    if isExpiredError(err) { ... }                              // RV 过期 → 重新 ListAndWatch
    if IsTooManyRequests(err) { Sleep(backoff); continue }      // 429 退避重连
    if IsInternalError(err) && retry.ShouldRetry() { continue } // 500 短暂重连
    if errorStopRequested { return nil }                        // context 取消 → 干净退出
}
```

`handleWatch` 内部是 `handleAnyWatch`（`reflector.go:972`）——就是一个简单的 `for-select` 消费 `w.ResultChan()`：

```go
loop:
for {
    select {
    case event, ok := <-w.ResultChan():
        if !ok { break loop }            // channel 关了 → watch 连接断了
        switch event.Type {
        case watch.Added:    store.Add(event.Object)
        case watch.Modified: store.Update(event.Object)
        case watch.Deleted:  store.Delete(event.Object)
        case watch.Bookmark: setLastSyncResourceVersion(...)   // 只记 RV，不写 store
        case watch.Error:    return apierrors.FromObject(event.Object)
        }
    case <-ctx.Done(): return errorStopRequested
    case err := <-errCh: return err     // Resync 出错
    }
}
```

Watch 的超时处理：Reflector 每次建 Watch 时给 `TimeoutSeconds` 一个**随机值**（`[5min, 10min]`），目的是**让所有客户端的 watch 断开时刻错开**，避免在 apiserver 侧形成"watch 惊群"。apiserver 会在这个时间点主动关闭连接，客户端收到 channel close 就重连——如果数据正常流动，重连时带上的是**已推进的 LastSyncResourceVersion**，所以不会丢事件也不会重复处理。

### Resync 机制

`watchWithResync` 在后台起一个 goroutine 跑 `startResync`：

```go
// reflector.go:514
func (r *Reflector) startResync(ctx, errc) {
    for {
        <-r.clock.After(r.resyncPeriod)   // 到期
        if r.ShouldResync == nil || r.ShouldResync() {
            r.store.Resync()              // ← 只投 Sync delta，不碰 apiserver
        }
    }
}
```

> [!TIP]
> Resync **不发起任何 apiserver 请求**——它只是把本地缓存里的对象重新投递一遍，handler 收到的是 `OnUpdate(old, new)` 且 `old == new`。周期性全量 re-LIST 只在 watch 断连时发生，与 resync 无关。kube-controller-manager 默认 resync 周期 12h~24h（`MinResyncPeriod = 12h`，乘 `rand.Float64() + 1` 因子）。

## Informer Architecture

Informer 是一个持久运行的 goroutine，职责是**从队列取对象 → 存进 Indexer → 触发回调**。Reflector 只负责 List + Watch，它把事件塞进 **FIFO 队列**（DeltaFIFO 或 RealFIFO），Informer 则从队列另一端消费。

### RealFIFO（当前默认）

从 Kubernetes v1.36 起，**默认队列已经换成 RealFIFO**（`InOrderInformers` 已 GA 且 LockToDefault）。选择逻辑在 `tools/cache/controller.go` 的 `newQueueFIFO` 里：

```go
if clientgofeaturegate.FeatureGates().Enabled(clientgofeaturegate.InOrderInformers) {
    options := RealFIFOOptions{...}
    if clientgofeaturegate.FeatureGates().Enabled(clientgofeaturegate.AtomicFIFO) {
        options.AtomicEvents = true
        options.UnlockWhileProcessing = ...
    }
    f := NewRealFIFOWithOptions(options)
} else {
    f := NewDeltaFIFOWithOptions(...)   // 1.37 中此分支已不可达
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

### SharedInformer 与 ProcessorListener

**SharedInformerFactory** 让同一种资源的多个 Informer 实例**共享同一个 Reflector + 同一个 FIFO 队列 + 同一个 Indexer**，只有**回调监听器（ProcessorListener）** 各自独立。这个设计避免了"N 个控制器每个都独立 Watch Pod"这种浪费。

## WorkQueue

Informer 负责把数据搬到缓存并触发回调，**真正的业务解耦发生在 WorkQueue**。它在 `client-go/util/workqueue/` 下，值得单独看，因为它的双集合设计是整套声明式模型的关键一环。

> [!TIP]
> WorkQueue 里放的**只有 `namespace/name` 这样一个字符串，没有对象**。worker 取出 key 之后必须重新从 lister 读最新状态。队列里没有对象，这是"水平触发"能成立的前提。

核心是 `dirty` 与 `processing` 两个集合：

```go
// queue.go:Add
func (q *Type) Add(item interface{}) {
    q.cond.L.Lock()
    defer q.cond.L.Unlock()
    if q.shuttingDown { return }
    if q.dirty.Has(item) { return }    // 已在待处理集合 → 幂等丢弃
    q.dirty.Insert(item)
    if q.processing.Has(item) { return } // 正在处理 → 只标脏，不入队
    q.queue.Push(item)
    q.cond.Signal()
}

// queue.go:Done
func (q *Type) Done(item interface{}) {
    q.processing.Delete(item)
    if q.dirty.Has(item) {                // 处理期间又被标脏 → 重新入队
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

## Reconcile Loop

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

1. [client-go ARCHITECTURE.md](https://github.com/kubernetes/kubernetes/blob/v1.37.2/staging/src/k8s.io/client-go/ARCHITECTURE.md)
2. [client-go v1.37.2 source (本地仓库)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/staging/src/k8s.io/client-go)
3. [KEP-3157 Watch-List](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/3157-watch-list)
4. [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
