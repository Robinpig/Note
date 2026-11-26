## Introduction

本篇聚焦 **SkyWalking 探针（skywalking-java agent）侧** 的实现机理：一个线程内如何把散落的方法调用组装成 Segment、两级采样中的 agent 侧那一层、以及 Segment 跨进程关联的真相。服务端运行期（SPI 装配、接收、按 scope 分发、确定性采样、L1/L2 聚合）与 OAL 编译、BanyanDB 物理模型见 [OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) 与 [存储抽象与 BanyanDB 写路径](/docs/CS/Distributed/Tracing/SkyWalking/Storage.md)。所有结论来自 skywalking / skywalking-java 一手源码。

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

## Agent-Side Sampling (Head-Based, Layer 1)

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

## How the Two Sampling Layers Compose

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

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 枢纽页
- [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md) — Trace / Segment / Span 三类
- [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md) — sw8 传播头字段
- [SkyWalking 采样与流控](/docs/CS/Distributed/Tracing/SkyWalking/Sampling.md) — 后端确定性采样（两级采样之 OAP 侧）
- [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) — OAL 编译、运行期分发
- [SkyWalking 存储抽象与 BanyanDB 写路径](/docs/CS/Distributed/Tracing/SkyWalking/Storage.md) — TimeBucket、BanyanDB 三模型、Series 分片

## References

1. [TracingContext (skywalking-java)](https://github.com/apache/skywalking-java/blob/main/apm-sniffer/apm-agent-core/src/main/java/org/apache/skywalking/apm/agent/core/context/TracingContext.java) — span 栈、EntrySpan 复用、SegmentRef
2. [SamplingService (skywalking-java)](https://github.com/apache/skywalking-java/blob/main/apm-sniffer/apm-agent-core/src/main/java/org/apache/skywalking/apm/agent/core/sampling/SamplingService.java) — 滑窗采样与 CAS 上界
3. [SegmentAnalysisListener (skywalking)](https://github.com/apache/skywalking/blob/master/oap-server/analyzer/agent-analyzer/src/main/java/org/apache/skywalking/oap/server/analyzer/provider/trace/parser/listener/SegmentAnalysisListener.java) — Segment 落地与后端采样状态机
