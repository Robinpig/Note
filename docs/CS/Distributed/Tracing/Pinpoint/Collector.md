## Introduction

本篇聚焦 **Pinpoint Collector（采集器）的运行期与落库路径**：gRPC `SpanService` 如何接收 agent 上报的 span、v4 新增的 OTLP 接收器、元数据常量去重的实现位置，以及最终写入 HBase 的代码路径。探针侧机理见 [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md)，存储模型见 [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md)。代码事实基于 Pinpoint v4.0.1 源码（`pinpoint-4.0.1/`），讲解直接贴真实源码，不标注行号。

## gRPC Span Receiver

Collector 通过 gRPC 接收 Pinpoint 原生 agent 上报的 span，入口是 `SpanService`（`collector/src/main/java/com/navercorp/pinpoint/collector/receiver/grpc/service/SpanService.java`），继承 gRPC 生成的服务端骨架 `SpanGrpc.SpanImplBase`。批处理入口 `sendSpanBatch` 把任务丢给执行器异步处理，`handleSpanBatch` 遍历 `request.getSpanList()` 逐个处理 `PSpanMessage`（含 `PSpan` / `PSpanChunk`）：

```java
public class SpanService extends SpanGrpc.SpanImplBase {
    private static final Status EXECUTOR_REJECTED = Status.RESOURCE_EXHAUSTED.withDescription("Executor rejected");
    // ...
    private final SimpleHandler<PSpan> spanHandler;
    private final SimpleHandler<PSpanChunk> spanCheckHandler;

    private final Executor executor;
    // ...

    @Override
    public void sendSpanBatch(PSpanMessageBatch request, StreamObserver<PSpanResultBatch> responseObserver) {
        final Context current = Context.current();
        final Runnable batchTask = current.wrap(() -> handleSpanBatch(current, request, responseObserver));
        try {
            executor.execute(batchTask);
        } catch (RejectedExecutionException e) {
            logger.warn("Failed to request. Executor rejected. header:{}", ServerContext.getAgentInfo(current));
            responseObserver.onError(EXECUTOR_REJECTED.asException());
        }
    }

    private void handleSpanBatch(Context current, PSpanMessageBatch request, StreamObserver<PSpanResultBatch> responseObserver) {
        // ...
        for (PSpanMessage spanMessage : request.getSpanList()) {
            // ...
            if (spanMessage.hasSpan()) {
                final PSpan span = spanMessage.getSpan();
                final ServerRequest<PSpan> serverRequest = serverRequestFactory.newServerRequest(current, fetcher, MessageTypes.SPAN, span);
                handleSpan(spanHandler, serverRequest, errorReporter);
            } else if (spanMessage.hasSpanChunk()) {
                final PSpanChunk spanChunk = spanMessage.getSpanChunk();
                final ServerRequest<PSpanChunk> serverRequest = serverRequestFactory.newServerRequest(current, fetcher, MessageTypes.SPANCHUNK, spanChunk);
                handleSpan(spanCheckHandler, serverRequest, errorReporter);
```

该 service 由 `GrpcSpanReceiverConfiguration` 装配（同一包 `.../grpc/config/GrpcSpanReceiverConfiguration.java`，注入 `GrpcReceiver` 与 `SpanService`），默认监听 **9991（span）/ 9992（stat）/ 9993（agent）** 端口（与枢纽页 *Architecture* 段一致）。

agent 侧对应一个经 Guice qualifier `@SpanDataSender` 注入的 `DataSender`，注解定义在 `agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/context/module/SpanDataSender.java`：

```java
@BindingAnnotation
@Target({PARAMETER, METHOD})
@Retention(RUNTIME)
public @interface SpanDataSender {
}
```

其底层是 `AbstractGrpcDataSender<T>`（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/sender/grpc/AbstractGrpcDataSender.java`），构造时即建立 gRPC `ManagedChannel`，通过 gRPC 把 span 异步推送到上述 `SpanService`：

```java
public abstract class AbstractGrpcDataSender<T> implements DataSender<T> {
    // ...
    protected final ManagedChannel managedChannel;
    protected final long logId;

    // not thread safe
    protected final MessageConverter<T, GeneratedMessageV3> messageConverter;

    protected final ChannelFactory channelFactory;

    protected volatile boolean shutdown;


    public AbstractGrpcDataSender(String host, int port,
                                  MessageConverter<T, GeneratedMessageV3> messageConverter,
                                  ChannelFactory channelFactory) {
        // ...
        this.messageConverter = Objects.requireNonNull(messageConverter, "messageConverter");

        this.managedChannel = channelFactory.build(host, port);
        this.logId = ManagedChannelUtils.getLogId(managedChannel);

        final ConnectivityState state = managedChannel.getState(false);
        this.managedChannel.notifyWhenStateChanged(state, new ConnectivityStateMonitor(state));

    }
```

## OTLP Receivers (v4 新增)

v4.0.1 起 Collector 还能接收标准 OTLP，模块 `otlptrace/otlptrace-collector`：

- **HTTP/JSON**：`OtlpTraceController`（`otlptrace/.../collector/controller/OtlpTraceController.java`）暴露 OTLP/HTTP 端点，配 `OtlpTraceDecompressionFilter` / `OtlpTraceHttpAdmissionFilter` 做解压与鉴权。
- **gRPC**：`GrpcOtlpTraceService`（`otlptrace/.../collector/service/GrpcOtlpTraceService.java`）承接 OTLP/gRPC 的 trace 导出。
- 落地：OTLP span 经 `OtlpTraceExportService` → `HbaseOtlpTraceService`（`otlptrace/.../collector/service/HbaseOtlpTraceService.java`）写入 HBase，复用与 Pinpoint 原生 trace 相同的存储模型；`LinkIndexTraceService` 负责链路索引。

这意味着 **Collector 侧已 OTel-ingestible**，但 Pinpoint 原生 Java agent 仍走私有协议（详见 [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) 的 *OpenTelemetry & OTLP* 段）。

## Metadata / Constant Deduplication

Pinpoint 不在 span 里写高基数字符串（SQL 模板、API 路径、异常类），而是**先在 agent 端归一成整数 ID**：

- `DefaultTraceContext.cacheApi(MethodDescriptor)` 与 `cacheString(String)` 分别把 API 描述符 / 任意字符串交给 `apiMetaDataService` / `stringMetaDataService` 缓存并返回整数 ID；span 只携带该 ID（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/context/DefaultTraceContext.java`）：

```java
    @Override
    public int cacheApi(final MethodDescriptor methodDescriptor) {
        return this.apiMetaDataService.cacheApi(methodDescriptor);
    }

    @Override
    public int cacheString(final String value) {
        return this.stringMetaDataService.cacheString(value);
    }
```
- 元数据本身由 agent 作为独立消息上报，Collector 落进元数据表（如 `HbaseApiMetaDataDao`、`HbaseAgentInfoDao`，均在 `collector/.../dao/hbase/`），UI 查询时再 `join` 回原文。

这套「写入前先去重」的设计，是 HBase 行键体积可控、写吞吐能扛住门户级流量的关键（与之对照，[SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 在 OAP 端做相似的元数据/网络地址字典归一）。

## HBase Write Path

原生 span 落库链路（均位于 `collector/src/main/java/com/navercorp/pinpoint/collector/dao/hbase/`）。

`HbaseTraceDaoV2 implements TraceDao` 的 `insert(SpanBo span)` 是核心写路径：用 `RowKeyEncoder<ServerTraceId>` 按 `TransactionId` 编码行键，构造 `Put`，经 `spanSerializer.serialize(...)` 写入列，最后 `putWriter.put(traceTableName, put)` 落到名为 `Trace` 的 HBase 表：

```java
public class HbaseTraceDaoV2 implements TraceDao {
    // ...
    @Override
    public boolean insert(SpanBo span) {
        CompletableFuture<Void> future = asyncInsert(span);
        try {
            future.get(3, TimeUnit.SECONDS);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            logger.debug("insert interrupted", e);
            return false;
        } catch (ExecutionException | TimeoutException e) {
            logger.debug("insert failed", e);
            return false;
        }
    }

    @Override
    public CompletableFuture<Void> asyncInsert(final SpanBo spanBo) {
        Objects.requireNonNull(spanBo, "spanBo");
        // ...

        long acceptedTime = spanBo.getCollectorAcceptTime();

        ServerTraceId transactionId = spanBo.getTransactionId();
        final byte[] rowKey = this.rowKeyEncoder.encodeRowKey(transactionId);
        final Put put = new Put(rowKey, acceptedTime, true);

        this.durabilityApplier.apply(put);

        this.spanSerializer.serialize(spanBo, put, null);

        TableName traceTableName = tableNameProvider.getTableName(descriptor.getTable());
        return putWriter.put(traceTableName, put);
    }

    @Override
    public void insertSpanChunk(SpanChunkBo spanChunkBo) {
        Objects.requireNonNull(spanChunkBo, "spanChunkBo");

        final List<SpanEventBo> spanEventBoList = spanChunkBo.getSpanEventBoList();
        if (CollectionUtils.isEmpty(spanEventBoList)) {
            return;
        }
        // ... 同样按 TransactionId 编码行键、构造 Put、序列化、写入
    }
}
```

`insertSpanChunk(...)` 处理超长 trace 的分块（异步 span 事件等），写路径与 `insert` 同构。

行键以 `TransactionId` 组织，因此 Web 端按 `TX_ID` / 时间范围拉取即可还原调用树；表名 `traceTableName` 由配置注入（默认 `Trace`）。指标与 Inspector 统计则不走 HBase，改落 **Pinot**（经 Kafka 流式摄入），见 [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md)。

## Links

- [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md) — 探针侧生成并异步上报 trace
- [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md) — HBase / Pinot 选型与运维权重
- [SkyWalking 存储抽象与 BanyanDB 写路径](/docs/CS/Distributed/Tracing/SkyWalking/Storage.md) — 对照「可插拔 StorageModule + 默认 BanyanDB」路线
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — 枢纽页：三段式架构、插件体系与四大视图

## References

- Pinpoint 官方文档（Collector / Storage / v3.0 变更）：https://pinpoint-apm.github.io/pinpoint/
- Pinpoint v4.0.1 源码（tag `v4.0.1`，commit `a7410bb`）：https://github.com/pinpoint-apm/pinpoint/releases/tag/v4.0.1
