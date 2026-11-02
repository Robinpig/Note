## Introduction

APF（API Priority and Fairness，KEP-1040）是 kube-apiserver 的过载保护子系统，取代早期的两个粗糙信号量（`--max-requests-inflight` 默认 400、`--max-mutating-requests-inflight` 默认 200）。旧模型只有"读/写各一个总数"，一只失控的 controller 就能打满全部并发，把 kubelet 心跳、leader election 这类系统流量饿死；APF 要解决的问题是：**在过载时让高优先级请求先走、同优先级之间公平、单租户不能把别人挤死**。

实现拆解成四个正交的机制，每个都值得单独记住：

| 机制 | 回答的问题 | 实现位置（v1.37.2） |
|---|---|---|
| 分类 | 这个请求属于哪条流、什么优先级 | FlowSchema / PriorityLevelConfiguration |
| 工作量估算 | 这个请求占几个"座位" | `request/width.go` 的 WorkEstimator |
| 公平排队 | 等待时谁先被放行 | shuffle sharding + 虚拟时钟（queueset） |
| 并发借贷 | 空闲容量的富余怎么分给别人 | `updateBorrowingLocked` 周期重算 |

总并发预算没有变：**`serverConcurrencyLimit = max-requests-inflight + max-mutating-requests-inflight`**（默认 600），在 `staging/src/k8s.io/apiserver/pkg/server/options/feature.go:81` 构造 `utilflowcontrol.New` 时求和传入。APF 做的是把这 600 个并发在优先级之间做动态切分，而不是放大总量。

## Position in the Filter Chain

APF 挂在 `DefaultBuildHandlerChain`（`staging/src/k8s.io/apiserver/pkg/server/config.go:1036`）里，位置是**认证之后、鉴权之前**：

```go
// config.go:1043 —— 自内向外包裹，APF 比 Authorization 更靠外
if c.FlowControl != nil {
	workEstimatorCfg := flowcontrolrequest.DefaultWorkEstimatorConfig()
	requestWorkEstimator := flowcontrolrequest.NewWorkEstimator(
		c.StorageObjectCountTracker.Get, c.FlowControl.GetInterestedWatchCount, workEstimatorCfg, c.FlowControl.GetMaxSeats)
	handler = filterlatency.TrackCompleted(handler)
	handler = genericfilters.WithPriorityAndFairness(handler, c.LongRunningFunc, c.FlowControl, requestWorkEstimator, c.RequestTimeout/4)
	handler = filterlatency.TrackStarted(handler, c.TracerProvider, "priorityandfairness")
} else {
	handler = genericfilters.WithMaxInFlightLimit(handler, c.MaxRequestsInFlight, c.MaxMutatingRequestsInFlight, c.LongRunningFunc)
}
```

三个要点：

1. **分流只需要 user 与 RequestInfo**，不需要鉴权结果，所以 APF 排在 Authorization 之前。副作用是：被 RBAC 拒掉的请求也曾占用过队列席位——这是刻意的，否则匿名/低权限用户能用必败请求挤爆排队。
2. **`FlowControl == nil` 时降级回旧模型** `WithMaxInFlightLimit`，两道信号量（400/200）。`--enable-priority-and-fairness=false` 走的就是这条路。
3. **排队等待上限是 `RequestTimeout/4`**（默认 60s / 4 = 15s），即第四个参数传入的 `newReqWaitCtxFn` 的超时。排了 15 秒还没轮到的请求会被踢出队列返回 429，而不是无限等下去。

filter 本体在 `staging/src/k8s.io/apiserver/pkg/server/filters/priority-and-fairness.go:88`。它把请求包装成 `RequestDigest{RequestInfo, User}` 交给 `cfgCtlr.Handle()`（`apf_controller.go:155`），并回调三个钩子：`noteFn` 记录分类结果、`workEstimator` 估算席位、`queueNoteFn` 维护水位指标。被拒时（`!served`）返回 **429 TooManyRequests**，并带 `Retry-After`（`:308-317`）；无论放行与否，响应头都会带上匹配到的 `X-Kubernetes-PF-FlowSchema-UID` 与 `X-Kubernetes-PF-PriorityLevel-UID`（`:365-374`），方便排查"我的请求被分到了哪一类"。

controller 本体由 PostStartHook 启动（`config.go:944` 的 `go c.FlowControl.Run(...)`），通过 informer 监听 FlowSchema / PriorityLevelConfiguration 对象并热更新配置；调试端点挂在 `/debug/api_priority_and_fairness/` 下（`config.go:1154` 的 `Install`）。

## Classification: FlowSchema First Match Wins

分类入口是 `startRequest`（`apf_controller.go:1022`）。FlowSchema 集合**按 `matchingPrecedence` 升序排序**（`:784` 的 `sort.Sort(fsSeq)`），遍历取第一个命中的：

```go
// apf_controller.go:1030
for _, fs := range cfgCtlr.flowSchemas {
	if matchesFlowSchema(rd, fs) {
		selectedFlowSchema = fs
		break
	}
	if fs.Name == flowcontrol.FlowSchemaNameCatchAll {
		catchAllFlowSchema = fs
	}
}
```

单条规则的匹配（`rule.go:39`）是两个条件的合取：subject 命中（user / group / serviceaccount，通配符 `*`），且 resource rule（verb + apiGroup + resource + namespace 作用域）或 non-resource rule（verb + URL 路径）命中。**precedence 数字越小越优先**，所以精确的 FlowSchema 用小数字、兜底用大数字。

兜底的健壮性设计值得注意（`:1039-1052`）：

- 没有任何 FS 命中 → 强制回落到内置的 `catch-all` FlowSchema（precedence 10000，匹配所有已认证与未认证用户）；
- 连 catch-all 都缺席（理论上不可能，因为 digest 阶段会补建 mandatory 对象）→ **直接 panic**。注释原文："This should absolutely never, ever happen!"

分类完还要算 `flowDistinguisher`（`:1063` 与 `:1116`）：`ByUser` 取用户名、`ByNamespace` 取 namespace。它是 shuffle sharding 的哈希输入，决定"同一租户/同一命名空间的请求被散到哪些队列"。**exempt 优先级的请求跳过这一切**（`:1058` 的 `pl.Spec.Type != Exempt` 判断），不算 distinguisher、不排队。

匹配上之后从 FlowSchema 拿到 PriorityLevelConfiguration，请求进入该 PL 的 queueSet。FlowSchema 只决定"分到哪个 PL、用什么区分维度"，真正的并发预算全在 PL 上。

## Work Estimation: Seats

APF 不是"一个请求占一个并发"，而是"一个请求占若干个 seat"。估算结果是一个三元组（`request/width.go:34`）：

```go
type WorkEstimate struct {
	InitialSeats      uint64        // 执行期间占的座位
	FinalSeats        uint64        // 收尾阶段（AdditionalLatency 期间）占的座位
	AdditionalLatency time.Duration // 请求完成后座位还要继续保留的时长
}
```

`AdditionalLatency` 是最反直觉的字段：**请求已经返回给客户端了，座位还没释放**。它用于给 watch fanout 这类"响应结束后影响仍在扩散"的写请求记账——占座多记一会儿，防止估算偏低导致雪崩。

按 verb 分派估算器（`width.go:119-135`）：

| 请求 | 估算依据 |
|---|---|
| `list` | listWorkEstimator：按该资源在 etcd 中的对象数与对象大小估算，席位随数据规模增长 |
| `create/update/patch/delete` | mutatingWorkEstimator：按对该资源感兴趣的 watcher 数量（fanout）估算 |
| `watch`（WatchList 开启时） | 初始化阶段等同 list，按 list 估算（`width.go:122-130`） |
| 其余（get 等） | `MinimumSeats = 1` |

上限由 `DefaultWorkEstimatorConfig`（`request/config.go:69`）约束：list 默认上限 10 seats，`SizeBasedListCostEstimate` 特性门开启后放宽到 100；mutating 上限 10。换句话说，一个大 list 最多记 10~100 个并发席位——这就是"大 list 比 get 更容易触发限流"的源码依据。

## QueueSet: Shuffle Sharding and Virtual Time

每个非 exempt 的 PriorityLevel 持有一个 queueSet，内部是经典公平排队算法的"seat-seconds"推广版。两个核心数据结构：

- **`currentR`**（`queueset.go:117`）：虚拟时钟，单位是 seat-second。每 tick 按 `min(正在请求的席位, 并发上限) / 活跃队列数` 的比率前进（`getVirtualTimeRatioLocked`，`:526-540`）。它把"处理速率随负载变化"这件事归一化成单调递增的进度表。
- **shuffle sharding**：`shufflesharding.Dealer`（`:199-203`）从 `Queues` 个队列中按哈希抽 `HandSize`（默认 6）个候选，**挑其中队列和最小的一个**入队（`shuffleShardLocked`，`:583-609`）。这样不同租户大概率被隔离到不同的队列子集——单个租户的突发只会打满自己那 hand 个队列，邻居租户受影响有限。这正是 AWS 那篇 shuffle sharding 论文在 apiserver 里的落地。

入队与拒绝（`StartRequest`，`:308`）：

```
DesiredNumQueues < 1  →  不排队，只卡总并发（超出 → 拒绝，metric 原因 concurrency-limit）
正常路径  →  shuffle 选队 → 队满（QueueLengthLimit）→ 拒绝（queue-full）
        →  否则入队 → dispatchAsMuchAsPossibleLocked
```

放行决策在 `dispatchLocked`（`:695`）：轮询扫描所有队列，选 **`nextDispatchR + 队首请求 totalWork` 最小**（即虚拟完成时间最早）的队列，取出队首请求执行，然后 `queue.nextDispatchR += request.totalWork()`（`:741`）——用工作量把该队列的"下次可派发时刻"往后推，这就是公平的来源：刚刚被服务过的队列，下一次派发轮到的概率就低了。

两个边界处理值得记住：

1. **虚拟时钟溢出**：`currentR` 越过 `highR` 阈值时整体回绕一个 `rDecrement`（`:481-487`），所有队列的 `nextDispatchR` 与请求的 `arrivalR` 同步回拨，防止 uint64 转一圈之后的相对顺序错乱。
2. **超大请求**：请求要的 seats 超过该 PL 当前并发上限时，只有在**整个 queueSet 完全空闲**时才放行（`canAccommodateSeatsLocked`，`:753-763`）；派发时还会把 `FinalSeats` 压缩到容量上限、等比拉长 `AdditionalLatency`，保持"席位 × 时长"的总工作量守恒（`:827-832`）。

## Watch Requests Are Special

Watch 在 APF 里的记账方式与普通请求完全不同：**只有初始化阶段（发送 init events）占席位，之后的常驻连接不占**（`priority-and-fairness.go:224-230` 的注释明确说了原因——watch 生命周期可能是小时级，拿它占座毫无意义）。

实现是一段双 goroutine 交接（`:171-306`）：

```
goroutine A: fcIfc.Handle(...)          // 排队、分类、估算，跑得快
  → execute() 内: RegisterWatch + close(shouldStartWatchCh)
  → watchInitializationSignal.Wait()    // 等存储层发完 init events
goroutine B（主）: <-shouldStartWatchCh 放行后
  → handler.ServeHTTP(w, watchReq)      // 真正的 watch 长连接
```

`forgetWatch` 在请求结束时注销 watcher，保证 `GetInterestedWatchCount`（喂给 mutating 估算器的 fanout 计数）准确。

另一条豁免线：**long-running 且非 watch 的请求完全绕过 APF**（`:104`）——`kubectl logs -f`、`exec`、`port-forward`、聚合层 proxy 这类流式请求直接 `ServeHTTP` 放行，不参与分类也不占座。否则一个 8 小时的 logs -f 会永久占着一个席位。

## Concurrency Borrowing

静态份额之外，APF 周期性（由 `updateBorrowing`，`apf_controller.go:393` 触发）按**实测需求**重算每个 PL 的当前并发上限 `currentCL`。

份额到并发的换算在 digest 阶段完成（`:863`）：

```go
concurrencyLimit := ceil(serverConcurrencyLimit * nominalConcurrencyShares / shareSum)
plState.minCL = concurrencyLimit - lendableCL    // 可借出的部分扣掉
plState.maxCL = concurrencyLimit + borrowingCL   // 允许借入的上限
```

每次重算（`updateBorrowingLocked`，`:399`）的算法：

1. **exempt PL 先切走**：`max(minCL, 实测高水位)` 从总预算 600 里直接扣除（`:410-413`）——exempt 流量（如 system:masters）不设上限，但要记账，防止它悄悄吃掉非 exempt 的预算。
2. **非 exempt PL 求公平分配**：每个 PL 给出三元组——`lowerBound = max(minCL, min(nominalCL, 高水位))`、`upperBound = maxCL`、`target = max(lowerBound, 平滑需求)`，交给 `computeConcurrencyAllocation` 解一个带上下界的水填充分配（`:423-445`）。
3. 结果写回 `plState.currentCL` 并完成 queueSet 的 `DispatchingConfig` 热更新（`:494`）。`apiserver_flowcontrol_fair_frac` 指标暴露分配公平度。

含义很直白：**闲置优先级的富余并发会自动借给繁忙优先级，但它自己的需求回来时（高水位上升）又能拿回来**。minCL/maxCL 两道边界保证借贷不会失控。

## Default Configuration

apiserver 启动时通过 bootstrap 对象保证可用配置恒存在（`staging/src/k8s.io/apiserver/pkg/apis/flowcontrol/bootstrap/default.go`），digest 阶段缺什么补什么（`apf_controller.go:691-697`）：

| PriorityLevel | shares | 用途 |
|---|---|---|
| `exempt`（mandatory） | 0 | 不受限，`system:masters` 组走这里 |
| `catch-all`（mandatory） | 5 | 最终兜底，只配 5 份，且 LimitResponse 是 Reject |
| `node-high`（suggested） | 40 | kubelet 心跳与状态上报 |
| `system`（suggested） | 30 | system:nodes 组其它请求 |
| `leader-election`（suggested） | 10 | 租约续期，与常规流量隔离 |
| `workload-high` / `workload-low` | 40 / 100 | 业务流量的两档 |
| `global-default`（suggested） | 20 | 未匹配其它 FS 的请求 |

exempt 在实现上不是"份额无穷大"，而是 queueSet 的 `DesiredNumQueues = -1`（`queueSetCompleterForPL`，`apf_controller.go:941`）：`canAccommodateSeatsLocked` 对负数恒真（`queueset.go:750-752`），请求 `dispatchSansQueueLocked` 立即执行，连虚拟时钟都不过。

对照默认配置读自己的集群时有两条实用结论：**catch-all 只有 5/600 且超限即拒**，所以自定义 FlowSchema 覆盖不全的流量会最先拿到 429；**leader-election 独立成级**意味着即使 apiserver 被打爆，controller-manager 的租约续期也不会断——这是"过载时不发生级联选主"的设计来源。

## Debugging Surface

- 响应头：`X-Kubernetes-PF-FlowSchema-UID` / `X-Kubernetes-PF-PriorityLevel-UID` 直接告诉你分类结果。
- 指标：`apiserver_flowcontrol_rejected_requests_total`（按 reason 区分 `queue-full` / `concurrency-limit` / `time-out`）、`apiserver_flowcontrol_current_executing_seats`、`apiserver_flowcontrol_fair_frac`、`apiserver_flowcontrol_seat_demands`。
- 调试端点：`/debug/api_priority_and_fairness/dump_priority_levels`、`dump_queues`、`dump_requests`（由 `FlowControl.Install` 注册）。
- 日志键：`apf_pl` / `apf_fs` / `apf_iseats` / `apf_fseats` / `apf_additionalLatency` 在请求的 httplog 上下文里可查。

## Links

- [kube-apiserver](/docs/CS/Container/k8s/apiserver.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)
- [访问控制](/docs/CS/Container/k8s/acl.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [KEP-1040: API Priority and Fairness](https://github.com/kubernetes/enhancements/blob/master/keps/sig-api-machinery/1040-priority-and-fairness/README.md)
2. [API Priority and Fairness 官方文档](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)
3. [flowcontrol.apiserver.k8s.io/v1 API 参考](https://kubernetes.io/docs/reference/kubernetes-api/cluster-resources/flow-schema-v1/)
4. [kubernetes v1.37.2 flowcontrol 源码（本地仓库）](https://github.com/kubernetes/kubernetes/tree/v1.37.2/staging/src/k8s.io/apiserver/pkg/util/flowcontrol)
