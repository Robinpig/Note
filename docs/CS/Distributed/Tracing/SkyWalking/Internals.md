## Introduction

前面几篇讲的是 SkyWalking 的「形状」：对象模型、sw8 传播头、OAP 模块划分、存储选型。本篇讲它的「机理」——**这些机制在源码里到底怎么跑的**。所有结论来自 SkyWalking 与 skywalking-java 的一手源码（`apache/skywalking` master、`apache/skywalking-java` main 分支），而不是文档措辞的转述。

要回答的核心问题有五个：

1. Agent 在一个线程里如何把散落的方法调用组装成 **Segment**？
2. 采样到底在**几处**发生，agent 与后端如何协同？
3. OAP 收到一个 Segment 后，如何**派生出**服务、端点、拓扑边和指标？
4. OAL 这门「脚本语言」如何变成运行中的 Java 对象？
5. 时间序列数据在 BanyanDB 里**以什么形状**落地？

## Agent Side: How a Segment Is Assembled

### The Span Stack

Agent 侧的核心是 `TracingContext`（`apm-agent-core/.../context/TracingContext.java`），它持有一个 **ActiveSpanStack**（`LinkedList<AbstractSpan>`）作为线程内的调用栈。Span 的创建与销毁严格遵循栈语义：

```java
// TracingContext#createEntrySpan
final AbstractSpan parentSpan = peek();
final int parentSpanId = parentSpan == null ? -1 : parentSpan.getSpanId();
if (parentSpan != null && parentSpan.isEntry()) {
    parentSpan.setOperationName(operationName);
    entrySpan = parentSpan;   // 复用父 EntrySpan
    return entrySpan.start();
}
```

这里有三条容易被忽略的设计：

| 机制 | 源码行为 | 为什么 |
| --- | --- | --- |
| **EntrySpan 复用** | 若栈顶已是 EntrySpan，`createEntrySpan` **不新建**而是改写其 operationName 并复用 | 一个请求多次进入「入口」语义（如 filter 链、servlet 转发）时，不应产生多个 EntrySpan，否则拓扑会多出伪节点 |
| **ExitSpan 复用** | `createExitSpan` 在父 span 已是 Exit 时同样复用 | 嵌套客户端调用合并为一次出向调用 |
| **spanId 分配** | `spanIdGenerator++` 从 0 起递增，父 id 为 `-1` 表示无父 | spanId 是 **Segment 内局部序号**，跨进程则由 sw8 的第 4 字段携带 |

栈的严谨性由 `stopSpan` 保证——只有栈顶 span 才能被停止，否则抛 `IllegalStateException("Stopping the unexpected span")`。这解释了为什么 SkyWalking 的调用链永远不会出现「悬挂 span」：**没弹栈的 span 不会被归档，也就不会上报**。

### PrimaryEndpoint: 端点名的选择优先级

`inject` 时需要写入「父端点名」（sw8 第 7 字段）。SkyWalking 用一个 `PrimaryEndpoint` 内部类决定它：

```
1. 优先用第一个 EntrySpan 的 operationName
2. 否则用第一个 Span 的 operationName
```

实现方式是每次 `push` 新 span 时调用 `primaryEndpoint.set(span)`，内部只在「当前 span 不是 entry 而新 span 是 entry」时才替换引用。这就是为什么入口 operationName 被后来的普通方法覆盖也不影响拓扑端点命名。

### Segment Identity and Lifecycle

- **Segment ID**：`GlobalIdGenerator.generate()` 生成全局唯一 ID，一个 Segment 一个。
- **上报单位是 Segment**：`TraceSegment#transform()` 把整个 Segment 打包成 protobuf `SegmentObject` 一次性发出，`transform()` 的注释明说这是「high CPU cost method, only called when sending to collector」。
- **Segment 内 Span 全局有序**：`spans` 是一个 list，归档顺序即完成顺序。
- **Trace ID 的传播**：`relatedGlobalTraceId` 初始是 `NewDistributedTraceId`，一旦 `extract`（跨进程）或 `continued`（跨线程）发生，才被替换为上游传来的 ID。这就是「本地创建的 trace」与「继承的 trace」在 agent 内的区分方式。

### Cross-Process Reference: TraceSegmentRef

跨进程关联不是靠全局表，而是靠 **Segment 内嵌对父 Segment 的引用**：

```java
// TracingContext#extract
TraceSegmentRef ref = new TraceSegmentRef(carrier);
this.segment.ref(ref);
this.segment.relatedGlobalTrace(new PropagatedTraceId(carrier.getTraceId()));
```

`TraceSegmentRef` 保存父 Segment ID、父 Span ID、父服务 / 实例 / 端点，以及「父是否被采样」。**注意 `TraceSegment#ref` 只保留第一个引用**（`if (null == ref)`）——源码注释明确：批处理场景下一个 Segment 可能面对多个父，但只缓存第一个。因此 SkyWalking 对批处理 / MQ 扇入场景是「弱关联」，不是真正的多父树。

这一设计直接决定了 SkyWalking **不是 OpenTracing 意义上的严格 Span 树**：它的父子关系是「Segment 引用 + Segment 内 spanId」，跨进程靠 ID 拼接而非引用计数。

### Span Limit: 主动降级而非崩溃

`isLimitMechanismWorking()` 检查 `spanIdGenerator >= spanLimitWatcher.getSpanLimit()`（默认 300，来自 `agent.span_limit_per_segment`）。超限时：

- 返回 **`NoopSpan` / `NoopExitSpan`** 而不是抛异常；
- 打印警告（30 秒节流）并附线程栈；
- Segment 打上 `isSizeLimited` 标记上报，OAP 侧可识别出「被截断的 segment」。

这是 APM 探针的典型取舍：**宁可丢失精度，不可拖垮业务**。与之并列的还有 `agent.trace_segment_ref_limit_per_span`（默认 500），限制单个 span 内缓存的 SegmentRef 数量，保证内存开销可估算。

## Sampling: Two Independent Layers

这是最容易被误读的部分——SkyWalking 有**两级完全独立的采样**，且都在源码里明确实现。

### Layer 1: Agent-Side Rate Sampling (Head-Based)

`SamplingService`（`apm-agent-core/.../sampling/SamplingService.java`）实现的是**滑动窗口限流**，不是百分比：

```java
public boolean trySampling(String operationName) {
    if (on) {
        int factor = samplingFactorHolder.get();
        if (factor < samplingRateWatcher.getSamplingRate()) {
            return samplingFactorHolder.compareAndSet(factor, factor + 1);  // CAS 抢占
        } else {
            return false;
        }
    }
    return true;
}
```

关键点：

| 特性 | 实现 |
| --- | --- |
| 语义 | **每 3 秒最多采样 N 个 Segment**（`agent.sample_n_per_3_secs`），不是「N% 的请求」 |
| 窗口 | `scheduleAtFixedRate(this::resetSamplingFactor, 0, 3, TimeUnit.SECONDS)`，每 3 秒把计数器清零 |
| 并发 | 用 `AtomicInteger` + **CAS** 而非 `incrementAndGet`，保证「不超过 N 个」的硬上界 |
| 动态调参 | `SamplingRateWatcher` 注册进 `ConfigurationDiscoveryService`，OAP 可动态下发新采样率，无需重启 |
| 关闭 | 采样率 ≤ 0 时取消定时任务，`on = false`，全量上报 |

`forceSampled()` 则是反向调节：本地发起的分布式 trace 采样机会更少，注释写明「If many distributed traces require sampled, the trace beginning at local, has less chance to be sampled」——用本地 trace 的采样额度去补贴分布式 trace。

**滑窗 vs 百分比的差异是实际影响**：QPS=1000 时设 `sample_n_per_3_secs=5`，实际采样率约 0.17%，远低于「5%」的直觉。这是从源码能推出、文档不会强调的运维陷阱。

### Layer 2: Backend-Side Deterministic Sampling

OAP 收到 Segment 后**还会再采样一次**，实现在 `TraceSegmentSampler`：

```java
public boolean shouldSample(SegmentObject segmentObject, int duration) {
    int sample = Math.abs(segmentObject.getTraceId().hashCode()) % 10000;
    String serviceName = segmentObject.getService();
    return traceSamplingPolicyWatcher.shouldSample(serviceName, sample, duration);
}
```

这一层的巧妙之处在于**用 traceId 哈希做确定性采样**：

- 同一 trace 的**所有** Segment 哈希值相同 → **整条 trace 同生共死**，不会出现「上游段被采、下游段被丢」的断裂；
- 无状态、无计数器，OAP 集群各节点 independently 决策也一致；
- 采样值域 0..9999，支持万分比的细粒度策略；
- `shouldSample` 还接收 `duration`，策略可对**慢请求单独放行**（长尾不采样会丢掉最有价值的慢 trace）。

### The Two Layers Compose

```text
Agent: trySampling()  →  未命中则整个 Segment 不上报（本地直接丢弃）
                            ↓ 命中的 Segment 上报
OAP:    shouldSample() →  未命中则 Segment 不落库（解析后丢弃）
                            ↓ 命中的 Segment 派生全部指标与拓扑
```

`SegmentAnalysisListener` 里的三态 `SAMPLE_STATUS`（`UNKNOWN` / `SAMPLED` / `IGNORE`）正是这个二段决策的状态机实现。还有一条**兜底**：

```java
} else if (isError && forceSampleErrorSegment) {
    sampleStatus = SAMPLE_STATUS.SAMPLED;   // 错误 segment 强制保留
}
```

即 `forceSampleErrorSegment` 打开后，**出错请求即使两级采样都未命中也会入库**。这正是 APM 场景最需要的语义：正常流量可以丢，异常不能丢。

> 注意 agent 采样是**按 Segment**（即按「服务实例 + 线程」的一次处理）而非按请求计数，这与 Zipkin / Jaeger 常见的「按 trace 采样」在语义上不等价——SkyWalking 的策略是「每个上游服务各采 N 条」，而不是「全局每 3 秒采 N 条完整 trace」。

## OAP Side: From Segment to Sources

OAP 的分析管线是**声明式**的：分析结果不写在代码里，而是由 listener 与 dispatcher 两层协作完成。

### Stage 1: Parse (agent-analyzer)

`SegmentParserServiceImpl` 遍历 Segment 的每个 Span，按 Span 类型分派给不同 **AnalysisListener**（`parseFirst` / `parseEntry` / `parseExit` / `parseLocal` / `parseSegment`）。这些 listener 做的是**语义提取**，产出 SkyWalking 内部的 **Source** 对象（`ISource`），而非最终存储实体。

产物举例：

- `SegmentAnalysisListener` → `Segment` source：装 `traceId`、`segmentId`、`serviceId`、`serviceInstanceId`、`endpointId`、`latency`、`isError`，并把整个 `SegmentObject` 的 protobuf 字节塞进 `dataBinary`（**明细原样保留**，查询时才反序列化）。
- `EndpointDependencyBuilder` / `RPCTrafficSourceBuilder` → `EndpointRelation` / `ServiceRelation` source：这是**拓扑边的来源**。
- `TagAutocomplete` source：给 UI 提供标签自动补全。

`SegmentAnalysisListener` 里还有两个值得注意的细节：

```java
// 时长不是累加 span，而是取整个 segment 的时间跨度
if (startTimestamp == 0 || startTimestamp > span.getStartTime()) startTimestamp = span.getStartTime();
if (span.getEndTime() > endTimestamp) endTimestamp = span.getEndTime();
duration = endTimestamp - startTimestamp;
```

即 **service 级延迟 = 段内最早开始到最晚结束**，不是各 span 时长之和（后者会因并行调用而失真）。

另外，**可搜索标签（searchable tags）**是白名单机制：只有出现在 `searchableTagKeys` 中的 tag 才会被索引，且超过 `Tag.TAG_LENGTH` 的直接丢弃——这是防止高基数标签打爆存储。

### Stage 2: Dispatch (core)

`SourceReceiverImpl#receive` 把 Source 交给 `DispatcherManager#forward`：

```java
List<SourceDispatcher<ISource>> dispatchers = dispatcherMap.get(source.scope());
if (dispatchers != null) {
    source.prepare();
    for (SourceDispatcher<ISource> dispatcher : dispatchers) {
        dispatcher.dispatch(source);
    }
}
```

`dispatcherMap` 的 key 是 **scope id**（Source 的类型编号）。dispatcher 的注册是**运行期扫描 classpath** 完成的——`SourceReceiverImpl#scan()` 遍历 `org.apache.skywalking` 下所有顶层类，凡是实现了 `SourceDispatcher<ISource>` 的就注册进来。

这条链路的含义是：**新增一种指标不需要改分发代码**。OAL 编译产物就是一个 `SourceDispatcher` 实现类；`DispatcherManager` 在启动时扫到它，自动挂到对应 scope 上。Source 的 `prepare()` 在分发前统一触发（生成 ID、算时间桶等），保证同一批 dispatcher 看到一致的数据。

### Stage 3: Aggregation (MetricsStreamProcessor)

`MetricsStreamProcessor#in` 是指标流式聚合的总入口：

```java
public void in(Metrics metrics) {
    MetricsAggregateWorker worker = entryWorkers.get(metrics.getClass());
    if (worker != null) { worker.in(metrics); return; }
    unroutableSampleCount.incrementAndGet();
    // 每个 class 只告警一次，避免日志洪水
}
```

以 **metrics class** 为键路由到对应的 `MetricsAggregateWorker`。worker 内部是 **session cache**（`MetricsSessionCache`），按 `StorageID` 聚合——`StorageID` 由「时间桶 + 实体 ID」构成，例如 `ServiceRelationClientSideMetrics` 的 `id0()`：

```java
return new StorageID().append(TIME_BUCKET, getTimeBucket())
                      .append(ENTITY_ID, entityId);
```

`entityId` 被标注为 `@BanyanDB.SeriesID(index = 0)`——**它就是 BanyanDB 里的 Series 身份**。聚合缓冲的合并逻辑由 `combine()` 定义，例如关系指标的合并是 **componentIds 集合并**（记录「这条调用链上出现过哪些组件 / 是否 TLS」）：

```java
public boolean combine(Metrics metrics) {
    for (int i = 0; i < targetIDs.size(); i++) {
        if (!sourceIDs.include(targetIDs.get(i))) { sourceIDs.add(targetIDs.get(i)); changed = true; }
    }
    return changed;
}
```

`calculate()` 在关系指标里是**空实现**——因为拓扑边不需要数值聚合，只需要「这条边存在过、出现过哪些组件」。这解释了为什么拓扑图能在**零额外配置**下自动出现：分析器只要产出 `ServiceRelation` source，聚合器就会自然形成边。

### Topology Derivation: DetectPoint 双端检测

拓扑边的生成机制在 `ServiceCallRelationDispatcher`：

```java
public void dispatch(ServiceRelation source) {
    switch (source.getDetectPoint()) {
        case SERVER: serverSide(source); break;
        case CLIENT: clientSide(source); break;
    }
}
```

同一类调用关系被**从两端各检测一次**：

| DetectPoint | 视角 | 产出指标 |
| --- | --- | --- |
| **CLIENT** | 调用方看到「我调了谁」 | `ServiceRelationClientSideMetrics`（index `service_relation_client_side`） |
| **SERVER** | 被调方看到「谁调了我」 | `ServiceRelationServerSideMetrics`（index `service_relation_server_side`） |

为什么两端都要？因为**单端检测会丢数据**：若只靠 CLIENT 侧，被调服务重启或 agent 未接入时这条边就断了；反之只靠 SERVER 侧，调用方未接入时同样断。两侧独立记录，UI 合并展示，任意一侧存活即可维持拓扑。TLS 状态也在这时被编码成 component id（`m-tls = 142`、`tls = 130`），使拓扑图能区分加密链路。

`ServiceRelation` 的 `entityId` 同样是 `source_service_id` + `dest_service_id` 的组合去重键——**同一对服务在同一个时间桶内只有一条关系记录**，`combine` 只负责把 componentIds 合并进去。

## OAL: A Compiled Script Language

OAL 不是解释执行的 DSL，而是**编译成 Java 字节码**。链路是：

```text
OAL 脚本 (.oal)
   ↓ 解析 + 校验
   ↓ 生成 Java 源码
   ↓ 动态编译（可 dump .class 调试）
   ↓
SourceDispatcher<ISource> 实现类 + Metrics 实现类
   ↓ 注册进 DispatcherManager
   ↓
运行时按 scope 路由
```

这解释了几个之前只能观察到、无法解释的现象：

1. **改 OAL 必须重启 OAP**——它是编译期产物，不是运行时解析；
2. **集群各节点 OAL 必须一致**——生成的类不同则聚合结果不一致；
3. **`SW_DYNAMIC_CLASS_ENGINE_DEBUG=Y` 能 dump 出 `.class` 文件**——因为生成的确实是标准 Java 类；
4. **DispatcherManager 靠扫描 classpath 拿到 dispatcher**——dispatcher 就是编译产物。

OAL 的 `from(Scope)` 声明数据源，`filter` 加条件，`.FUNCTION` 做聚合；生成的 dispatcher 对每个指标实现一个 `do<Metric>` 方法。`DispatcherManager#debugHolderForOalMetric` 的注释还揭示了一个细节：**OAL 的调试闸门（gate）是 per-metric 的**——每个 `do<Metric>` 有独立的 holder，一个 debug session 只捕获目标指标，其余指标静默。

## TimeBucket: Time as a Sortable Integer

时间序列存储的效率取决于时间编码。SkyWalking 的 `TimeBucket` 把时间压成一个**十进制前缀整数**：

| 粒度 | 格式 | 示例 | 数值区间 |
| --- | --- | --- | --- |
| Second | `yyyyMMddHHmmss` | `20240711221830` | 1e13 ~ 1e14 |
| Minute | `yyyyMMddHHmm` | `202407112218` | 1e11 ~ 1e12 |
| Hour | `yyyyMMddHH` | `2024071122` | 1e9 ~ 1e10 |
| Day | `yyyyMMdd` | `20240711` | 1e7 ~ 1e8 |

编码是**定长数字前缀**而非字符串，这带来三个直接好处：

1. **天然按时间排序**，字典序即时间序，无需额外时间索引；
2. **降采样是位/位段截断**：`toTimeBucketInHour()` / `toTimeBucketInDay()` 直接截掉低位（`retainToDay4MinuteBucket` 把 `202407112218` 变成 `202407110000`），无需日期计算；
3. **粒度靠数值区间判别**：`isSecondBucket` / `isMinuteBucket` / `isHourBucket` / `isDayBucket` 各自用固定区间判断——这既省了字段，也保证了「反查时间戳」能自动得出原粒度。

L1/L2 降采样正建立在这个编码之上：OAP 按分钟聚合（`l1FlushPeriod` 默认 500ms 是**聚合窗口刷新周期**，不是数据粒度），再由 `toHour()` / `toDay()` 产出小时级、天级指标。

## BanyanDB: Three Physical Models

BanyanDB 不是「又一个时序库」，它提供**三种数据模型**，SkyWalking 按数据性质映射：

| 模型 | 语义 | SkyWalking 映射 | 关键特征 |
| --- | --- | --- | --- |
| **Stream** | 明细型时序 | Trace、Segment、日志、Records | 保留明细，一条不落；支持 Trace retention pipeline（Hot 阶段 LSM compaction 时整条丢弃） |
| **Measure** | 可聚合指标 | 分钟 / 小时 / 天级 Metrics（`metricsMinute` / `metricsHour` / `metricsDay`） | 围绕标签预聚合，支持服务端 TopN |
| **Property** | 非时序属性 | UI、Profiling | 不按时间分段，无 `segmentInterval` / `ttl` |

对应的存储插件类分别是 `StreamModel` / `MeasureModel` / `PropertyModel`，三者都携带一组 `IndexRule`——即**索引规则由 SkyWalking 侧定义并下发**，而非 BanyanDB 自动推断。

### Series and Sharding

BanyanDB 的 **Series** 是核心概念：由**相同的 Tag 组合**标识的一组时间序列数据。SkyWalking 侧由 `@BanyanDB.SeriesID(index = 0)` 指定哪个字段充当 Series ID（关系指标里是 `entityId`）。

分片规则是 **对 Series ID 取 hash**：

```
Tags → Series 身份 → Series ID → hash → Shard
```

这解释了 SkyWalking 为什么把 `entityId` 设计成「源服务 + 目标服务」的组合：它既是聚合的幂等键，也是分片的路由键——**同一对服务的所有数据必定落在同一 shard**，拓扑查询因此无需跨节点 join。

### TopN 服务端预聚合

`bydb.yaml` 里的度量定义支持：

```yaml
- name: endpoint_cpm-service
  metricName: endpoint_cpm
  groupByTagNames:
    - service_id
  sort: des
```

按 `service_id` 分组、降序维护 TopN，**排序在 BanyanDB 服务端完成**，查询时无需扫全量再排序。这是 Measure 相对 Stream 的核心优势，也是「OAP 只写指标、聚合交给存储」这一分工的基础。

## Putting It Together

一次 HTTP 请求的完整生命周期：

```text
[Agent]
  Tomcat filter 拦截 → createEntrySpan（栈顶）
  Controller 方法    → createLocalSpan
  HTTP client        → createExitSpan + peer
      ↓ inject：写 sw8 头（含 traceId / 父段 / 父 spanId / 父服务 / 父端点 / 目标地址）
[网络]
      ↓
[下游 Agent]
  extract → 建 TraceSegmentRef → 关联父段
      ↓ Segment 完成 → transform() → SegmentObject
[OAP receiver]
  ↓ gRPC 11800
[agent-analyzer]
  ↓ 遍历 Span，按 First/Entry/Exit/Local 分派 listener
  ↓ 产出 Source：Segment / ServiceRelation / EndpointRelation / ...
  ↓ 后端采样：traceId.hashCode() % 10000 → 命中或 IGNORE
[core]
  ↓ SourceReceiver.receive → DispatcherManager.forward(scope)
  ↓ 命中 OAL 生成的 dispatcher → 产出 Metrics
[MetricsStreamProcessor]
  ↓ 按 metrics class 路由 → MetricsAggregateWorker
  ↓ session cache 按 StorageID（时间桶 + entityId）聚合
  ↓ L1（分钟）→ L2（小时/天）
[BanyanDB]
  ↓ Metrics → Measure（按 Series hash 分片，可服务端 TopN）
  ↓ Trace / Segment → Stream（明细，protobuf 原样）
[GraphQL / UI]
  ↓ 拓扑由 ServiceRelation 双端检测的结果合并而来
```

## Design Trade-offs Worth Noting

深挖源码后，几个「为什么这样设计」比「用了什么」更有价值：

| 设计 | 收益 | 代价 |
| --- | --- | --- |
| 上报单位是 Segment 而非 Span | 网络与序列化开销降一个量级 | Segment 内 Span 数受限（默认 300） |
| 拓扑边双端检测 | 任一端 agent 存活即可维持拓扑 | 存储两套关系指标 |
| 拓扑边只存 componentIds 集合，无数值 | 零配置自动成图 | 无法直接回答「这条边有多慢」（需另行关联指标） |
| 采样用滑窗而非百分比 | 突发流量下采样行为平滑可预测 | 实际采样率与直觉差距大，需按 QPS 反推 |
| 后端采样用 traceId 哈希 | 无状态、集群一致、整条 trace 同生共死 | 策略变更需重算，缺少 tail-based 的延迟决策能力 |
| TraceSegmentRef 只留首个父 | 内存与序列化可控 | 批处理扇入场景弱关联，非严格多父树 |
| OAL 编译成 Java 类 | 运行期零解释开销、可用标准调试器 | 改脚本需重启、集群需一致 |
| 时间用定长数字前缀 | 排序/截断降采样极廉价 | 区间判别粒度固定，新增粒度需改编码 |
| Series 按 hash 分片 | 同 Series 数据聚簇、免跨节点 join | 扩分片需重分布，冷热不均需处理 |

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 枢纽页
- [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md) — Trace / Segment / Span 三类
- [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md) — sw8 传播头字段
- [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) — OAL / MAL / LAL 与存储选型
- [Java Agent](/docs/CS/Java/JDK/Agent.md) — 字节码增强与插件体系
- [Zipkin Data Model](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md) — 严格 Span 树模型对照

## References

1. [TracingContext (skywalking-java)](https://github.com/apache/skywalking-java/blob/main/apm-sniffer/apm-agent-core/src/main/java/org/apache/skywalking/apm/agent/core/context/TracingContext.java) — span 栈、EntrySpan 复用、SegmentRef
2. [SamplingService (skywalking-java)](https://github.com/apache/skywalking-java/blob/main/apm-sniffer/apm-agent-core/src/main/java/org/apache/skywalking/apm/agent/core/sampling/SamplingService.java) — 滑窗采样与 CAS 上界
3. [SegmentAnalysisListener (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/analyzer/agent-analyzer/src/main/java/org/apache/skywalking/oap/server/analyzer/provider/trace/parser/listener/SegmentAnalysisListener.java) — Segment 落地与后端采样状态机
4. [TraceSegmentSampler (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/analyzer/agent-analyzer/src/main/java/org/apache/skywalking/oap/server/analyzer/provider/trace/parser/listener/TraceSegmentSampler.java) — traceId 哈希确定性采样
5. [ServiceCallRelationDispatcher (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/server-core/src/main/java/org/apache/skywalking/oap/server/core/analysis/manual/relation/service/ServiceCallRelationDispatcher.java) — 拓扑边双端检测
6. [DispatcherManager (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/server-core/src/main/java/org/apache/skywalking/oap/server/core/analysis/DispatcherManager.java) — 按 scope 路由与 classpath 扫描注册
7. [TimeBucket (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/server-core/src/main/java/org/apache/skywalking/oap/server/core/analysis/TimeBucket.java) — 时间桶编码与降采样
8. [Backend storage — BanyanDB](https://skywalking.apache.org/docs/main/next/en/setup/backend/storages/banyandb/) — Stream / Measure / Property、Series 与分片
