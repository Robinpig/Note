## Introduction

本篇展开 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 的核心数据模型：trace 如何由 **Segment** 与 **Span** 构成，Span 的三种类型（EntrySpan / ExitSpan / LocalSpan）分别对应什么角色，以及跨进程（ContextCarrier / sw8）与跨线程（ContextSnapshot）的上下文传播机制。理解这套模型是正确解读 UI 拓扑与编写 OAL 的前提。

## Trace, Segment and Span

- **Trace**：一次完整请求在分布式系统中流经的所有操作的集合，由全局唯一的 `trace id` 标识。
- **Trace Segment**：**一个服务实例、一个线程**在一次请求上下文中产生的所有 Span 的集合。SkyWalking 的上报基本单位是 Segment，而非单条 Span——一个 Segment 内的 Span 通过 `trace segment id` 关联，跨实例的多个 Segment 通过 `trace id` 串成一条 Trace。
- **Span**：一个工作单元（一次 RPC、一次 DB 查询、一段本地处理）。SkyWalking 把 Span 扩展为三种类型：

| 类型 | 角色 | 典型位置 |
| --- | --- | --- |
| **EntrySpan** | 服务端入口，代表服务提供者 | HTTP server、RPC server、MQ consumer |
| **ExitSpan**（早期称 **LeafSpan**） | 客户端 / 消息生产者 | HTTP client、JDBC 调用、Redis 读、MQ producer |
| **LocalSpan** | 不涉远程服务的本地逻辑块 | 普通 Java 方法 |

几乎所有对外服务与 MQ-consumer 都是 EntrySpan；访问 DB、Redis 或调用下游服务则是 ExitSpan。一个 Segment 通常以一个 EntrySpan 起始，内部可嵌套若干 LocalSpan / ExitSpan，ExitSpan 在跨进程调用时通过 ContextCarrier 把上下文传给下游的 EntrySpan。

## Span Attributes

除了类型，每个 Span 还必须设置 **component** 与 **layer**（对 Entry/Exit 尤其重要）。`SpanLayer` 取值有 `UNKNOWN`（默认）、`DB`、`RPC_FRAMEWORK`、`HTTP`、`MQ`；component 由 SkyWalking 项目保留并分配 ID（如 Tomcat、HttpClient、MySQL）。Span 上还可挂：

- **tag**：`key:value` 标签，如 `http.method=GET`、`http.status_code=200`、`db.statement=<SQL>`。
- **log**：带时间戳的事件，用于记录异常 `log(Throwable)` 或自定义事件。
- **errorOccurred**：标记该 Span 是否出错。

## Cross-Process Propagation: ContextCarrier

分布式追踪要把跨进程的调用链接起来，上下文必须在进程间传播——这就是 **ContextCarrier** 的职责。以 A→B 的调用为例：

1. A 端创建一个空 `ContextCarrier`，`ContextManager#createExitSpan` 或 `inject` 把上下文写入它。
2. 把所有 item 放进请求头（HTTP HEAD）、attachment（Dubbo RPC）或消息体（Kafka）。
3. `ContextCarrier` 随调用到达 B 端。
4. B 端取出 item，`ContextManager#createEntrySpan` 或 `extract` 绑定客户端与服务端，使 A 的 ExitSpan 与 B 的 EntrySpan 属于同一条 trace。

底层实际落地的协议是 **sw8**（见 [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md)）：`ContextCarrier` 的字段被编码进 `sw8` 请求头。

## Cross-Thread Propagation: ContextSnapshot

除了跨进程，跨线程（如内存 MQ、批处理）也要传播上下文，区别是跨线程不需要序列化。步骤：

1. 父线程 `ContextManager#capture` 得到 `ContextSnapshot`。
2. 把 snapshot 通过方法参数或既有参数传给子线程。
3. 子线程 `ContextManager#continued` 恢复上下文。

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 对象层级（Service/Instance/Endpoint）
- [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md) — sw8 传播头字段
- [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md) — span 栈与 Segment 装配、TraceSegmentRef 跨进程关联
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — OpenTracing 数据模型对照
- [Zipkin Data Model](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md) — Zipkin 的 Span/Annotation 模型

## References

1. [Java Plugin Development Guide](https://skywalking.apache.org/docs/skywalking-java/v9.1.0/en/setup/service-agent/java-agent/java-plugin-development-guide/) — Span 三类、ContextCarrier / ContextSnapshot
2. [Cross Process Propagation Headers (sw8)](https://skywalking.apache.org/docs/main/next/en/api/x-process-propagation-headers-v3/) — sw8 协议规范
