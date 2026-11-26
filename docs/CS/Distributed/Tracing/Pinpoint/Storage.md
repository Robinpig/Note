## Introduction

本篇聚焦 **Pinpoint 的存储模型**：为什么它以 HBase 为链路主存、v3.0 又引入 Pinot，v4 又如何把 OTLP 落进同一套 HBase，以及这套选型带来的运维权重。探针侧机理见 [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md)，接收与落库链路见 [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md)。代码事实基于 Pinpoint v4.0.1 源码（`pinpoint-4.0.1/`），讲解直接贴真实源码，不标注行号。

## HBase as Primary Store

Pinpoint 诞生于「要扛住 NAVER 门户级写吞吐」的背景，HBase 的分布式写能力正好匹配，因此长期作为**链路主存**。落库代码位于 `collector/src/main/java/com/navercorp/pinpoint/collector/dao/hbase/HbaseTraceDaoV2.java`，`insert` 按 `TransactionId` 编码行键、序列化后写 `Put`：

```java
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
```

即落到名为 `Trace` 的 HBase 表；超长 trace 分块走同文件里的 `insertSpanChunk(...)`。其余要点：

- 典型表：`Trace`（span / SpanEvent 数据，按 TX_ID 组织）、`AgentInfo`（agent 注册元数据，对应 `HbaseAgentInfoDao`）、`ApplicationIndex`（应用索引）、`ApiMetaData`（API 元数据，配合 agent 端常量去重）、`ApplicationTraceIndex` 等。
- **强依赖 ZooKeeper**：既供 HBase 自身，也供 Collector 发现 agent、协调集群。
- **留存靠 TTL**：HBase 表上的 TTL 控制保留期；磁盘消耗随**请求量**而非服务数增长——繁忙 API 会产生大量 trace 数据。
- 读取路径：Web 从 HBase 按 TX_ID / 时间范围拉取，排序成调用树。

HBase 的代价是真实的运维负担：region server、compaction、region-splitting 都是专门学问。社区常有「2 GB 是最低能启动的栈、不是能跑的栈」的说法——生产需要成倍资源。

## v3.0: Pinot + Kafka for Metrics

v3.0 起存储按**数据类型拆分**（模块 `pinot/`）：

- 链路 **Trace** 仍写 **HBase**。
- 指标与新版 **Inspector** 统计改写 **Apache Pinot**（OLAP 列存），经 **Kafka** 做流式摄入。

拆分动机：HBase 适合「写多、按 key 读 trace」，但不适合 URI 统计、Inspector 这类聚合分析查询；Pinot 的列存 + 倒排更适合即席 OLAP。这也是为什么新版安装文档里会多出 Kafka + Pinot 两个组件——阅读部署清单时极易漏看。

## v4.0.1: OTLP → HBase

v4 新增的 OTLP 接收链路也**复用 HBase 主存**，而非独立存储（模块 `otlptrace/otlptrace-collector`）：

- `HbaseOtlpTraceService`（`otlptrace/otlptrace-collector/src/main/java/com/navercorp/pinpoint/otlp/trace/collector/service/HbaseOtlpTraceService.java`）实现 `TraceService` 接口，内部直接持有与原生 span 相同的 `TraceDao`（即上面的 `HbaseTraceDaoV2`），把 OTLP trace 写入同一套 HBase 模型：

```java
@Service
public class HbaseOtlpTraceService implements TraceService {
    // ...
    private final TraceDao traceDao;
    private final ScatterService scatterService;
    private final ApplicationMapService applicationMapService;
    // ...

    @Override
    public void insertSpan(SpanBo spanBo) {
        SpanInsertEvent event = publisher.captureContext(spanBo);
        CompletableFuture<Void> future = traceDao.asyncInsert(spanBo);
        scatterService.insert(spanBo);
        applicationMapService.insertSpan(spanBo);

        future.whenCompleteAsync((unused, throwable) -> {
            final boolean result = throwable == null;
            if (!result) {
                asyncInsertErrorCounter.increment();
                throttledLogger.warn("Failed async span insert (HBase). spanId={}", spanBo.getSpanId(), throwable);
            }
            // ...
        }, grpcOtlpTraceServerExecutor);
    }
}
```

- `HbaseOtlpAgentInfoService` / `HbaseOtlpApplicationIndexV2Service` 负责 OTLP 侧的 agent 信息与应用索引落库。

因此无论是 Pinpoint 原生 agent 还是外部 OTLP 导出，最终 trace 都收敛到同一套 HBase 表，Web 端统一查询。

## Operational Weight

选型决策里最该想清的一句评价：**「Pinpoint 是你有一堆 Java 服务、想要 New Relic 级调用树、且有人愿意运维 HBase 时选的 APM」**。HBase 的 ZooKeeper + Hadoop 家族习惯，是它和 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md)（默认 BanyanDB / ES）、[Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)（可走 Elasticsearch / Cassandra / Badger）在运维成本上的根本差异。若不愿运维 HBase，应考虑把数据落到 ClickHouse 或 Elasticsearch 的后端（如 SigNoz）。

## Links

- [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md) — 探针侧如何生成并异步上报 trace
- [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md) — gRPC SpanService / OTLP 接收 / HBase 写路径
- [SkyWalking 存储抽象与 BanyanDB 写路径](/docs/CS/Distributed/Tracing/SkyWalking/Storage.md) — 对照「可插拔 StorageModule + 默认 BanyanDB」路线
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — 枢纽页：三段式架构与四大视图

## References

- Pinpoint 官方文档（Storage / v3.0 变更）：https://pinpoint-apm.github.io/pinpoint/
- Pinpoint v4.0.1 源码（tag `v4.0.1`，commit `a7410bb`）：https://github.com/pinpoint-apm/pinpoint/releases/tag/v4.0.1
