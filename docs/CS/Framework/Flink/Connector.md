## Introduction

连接器（connector）是 Flink 与外部世界之间的边界：**Source** 把外部数据读进流，**Sink** 把结果写出去。它决定了作业的**端到端一致性**上限——即使 Flink 内部做到 exactly-once，若 Source 不可重放或 Sink 不支持幂等/事务，最终仍只能是 at-least-once。

一致性链路上，连接器与 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)、[State](/docs/CS/Framework/Flink/State.md) 是同一套机制的三段：Source 的读取位置存在 operator state 里，随 checkpoint 一起快照。

## Source：从 SourceFunction 到 FLIP-27

### 老接口的问题

早期的 `SourceFunction`（`addSource()`）把"发现数据分片"和"读取数据"混在一个接口里，还要求用户在 checkpoint lock 下自己处理并发，导致：

- 批、流两套实现要各写一遍；
- 分片（split / partition / shard）不是一等公民，难以实现按分片水位、事件时间对齐、动态分片分配、work stealing；
- 线程模型每个 source 各自造轮子，质量参差；
- checkpoint 锁由 source 持有，容易与数据处理抢锁。

### 新架构：SplitEnumerator + SourceReader

FLIP-27 把两者拆开：

| 组件 | 位置 | 职责 |
| ---- | ---- | ---- |
| `Source` | 工厂 | 创建 enumerator 与 reader 的入口 |
| `SplitEnumerator` | 通常运行在 JobManager | 发现分片（Kafka 分区、文件块、shard），分配给 reader；可周期性再发现（动态分区发现） |
| `SourceReader` | 运行在 TaskManager | 读已分配分片的数据，产出记录；把分片进度写入 checkpoint |

带来的能力：

- **批流统一**：同一份 source 实现，有界/无界只在于 enumerator 是否继续产出新分片；
- **原生水位**：`TimestampAssigner` / `WatermarkGenerator` 作为框架能力内置在 reader 里，天然支持按分片水位与空闲检测、水位对齐（见 [Time](/docs/CS/Framework/Flink/Time.md)）；
- **标准化指标**：跨 source 统一的吞吐、延迟、lag 指标；
- **可协调**：enumerator 在 JobManager 侧，便于做全局协调（如 Kafka 分区分配、文件枚举去重）。

### Source Coordination in Source

> [!NOTE]
> 版本基线：Flink **2.3.0**（tag `release-2.3.0`）。下文源码片段均取自该 tag，路径相对仓库根目录，不带行号。

FLIP-27 的"enumerator 在 JM、reader 在 TM"在源码里由 `SourceCoordinator`（`flink-runtime/.../source/coordinator/`）实现。它不是普通组件，而是**跑在单线程 event loop 上的协调器**——enumerator 的所有回调都被串行化，这才让"简单实现一个 `SplitEnumerator`"成为可能：

```java
/**
 * A source coordinator runs on the coordinator side (JobManager) ... and calls corresponding
 * method of the SplitEnumerator to take actions.
 */
public class SourceCoordinator<SplitT extends SourceSplit, EnumChkT> ...
```

启动顺序有明确约束：先标记 `started`（区分"没调用 start"和"start 失败"），必要时创建 enumerator，再把 `enumerator.start()` 作为 event loop 的**第一个任务**：

```java
public void start() throws Exception {
    LOG.info("Starting split enumerator for source {}.", operatorName);
    started = true;
    if (enumerator == null) {
        enumerator = source.createEnumerator(context);
    }

    // The start sequence is the first task in the coordinator executor.
    // We rely on the single-threaded coordinator executor to guarantee
    // the other methods are invoked after the enumerator has started.
    runInEventLoop(() -> enumerator.start(), "starting the SplitEnumerator.");
}
```

**分片请求不是来者不拒**：reader 发 `RequestSplitEvent` 时，coordinator 先看 `AssignmentTracker` 是否已经宣布该 reader "没有更多 split"，是则直接忽略，避免无意义的枚举器调用：

```java
private void handleRequestSplitEvent(int subtask, int attemptNumber, RequestSplitEvent event) {
    // request splits from the enumerator only if the enumerator has un-assigned splits
    // this helps to reduce unnecessary split requests to the enumerator
    if (!context.hasNoMoreSplits(subtask)) {
        enumerator.handleSplitRequest(subtask, event.hostName());
    }
}
```

**checkpoint 与分片分配对齐**是 exactly-once 的关键。`SplitAssignmentTracker` 注释明确："维护自上次成功 checkpoint 以来的所有分配，是为了让 subtask 能**独立 failover**"：

```java
// All the split assignments since the last successful checkpoint.
// Maintaining this allow the subtasks to fail over independently.
// The mapping is [CheckpointId -> [SubtaskId -> LinkedHashSet[SourceSplits]]].
private final SortedMap<Long, Map<Integer, LinkedHashSet<SplitT>>> assignmentsByCheckpointId;

// The split assignments since the last checkpoint attempt.
private Map<Integer, LinkedHashSet<SplitT>> uncheckpointedAssignments;
```

每次 checkpoint 把"未快照的分配"挂到该 checkpoint ID 下，这样某个 reader 失败时只需重放它自己那部分 split，不必让整个 source 回滚：

```java
public void onCheckpoint(long checkpointId) throws Exception {
    // Include the uncheckpointed assignments to the snapshot.
    assignmentsByCheckpointId.put(checkpointId, uncheckpointedAssignments);
    uncheckpointedAssignments = new HashMap<>();
}
```

快照内容分两种：流模式只序列化 enumerator 状态；批模式（`BATCH_CHECKPOINT_ID`）额外把 assignment tracker 一起写入——因为批作业没有周期性 checkpoint 来持续记录分配：

```java
if (checkpointId == BATCH_CHECKPOINT_ID) {
    // assignments
    byte[] assignmentData = context.getAssignmentTracker().snapshotState(splitSerializer);
    out.writeInt(assignmentData.length);
    out.write(assignmentData);

    // enumerator
    byte[] enumeratorData = toBytes(checkpointId);
    out.writeInt(enumeratorData.length);
    out.write(enumeratorData);
} else {
    context.onCheckpoint(checkpointId);
    result.complete(toBytes(checkpointId));
}
```

**HybridSource 的 source 切换**也由 coordinator 驱动：只有当 `finishedReaders.size() == context.currentParallelism()`（所有 reader 都读完当前 source）才切到下一个 enumerator，并**先给所有 reader 发切换事件、再发新分片**，避免 reader 收到不属于当前 source 的 split：

```java
finishedReaders.add(subtaskId);
if (finishedReaders.size() == context.currentParallelism()) {
    LOG.debug("All readers finished, ready to switch enumerator!");
    if (currentSourceIndex + 1 < sources.size()) {
        switchEnumerator();
        // switch all readers prior to sending split assignments
        for (int i = 0; i < context.currentParallelism(); i++) {
            sendSwitchSourceEvent(i, currentSourceIndex);
        }
    }
}
```

> [!WARNING]
> 源码位置提醒：`SplitEnumerator` / `SourceReader` 接口在 **`flink-core`**，而 `SourceCoordinator` / `SplitAssignmentTracker` 在 **`flink-runtime`**。旧资料常把整个 FLIP-27 说成"一个包里的接口"，按类找源码时别被误导。

> [!WARNING]
> Flink 2.x 已**移除** `SourceFunction`。新写连接器一律基于 FLIP-27 的 `Source` 接口；仍在用 `FlinkKafkaConsumer` 等老实现的作业，需要在升级到 2.x 前迁移到新实现（如 `KafkaSource`）。

### Kafka Source 示例

```java
KafkaSource<Event> source = KafkaSource.<Event>builder()
        .setBootstrapServers("broker:9092")
        .setTopics("clicks")
        .setGroupId("flink-group")
        .setStartingOffsets(OffsetsInitializer.committedOffsets(OffsetResetStrategy.EARLIEST))
        .setValueOnlyDeserializer(new EventDeserializer())
        .setProperty("partition.discovery.interval.ms", "60000")   // 动态发现新分区
        .build();

DataStream<Event> stream = env.fromSource(
        source,
        WatermarkStrategy.<Event>forBoundedOutOfOrderness(Duration.ofSeconds(5))
                .withTimestampAssigner((e, ts) -> e.getEventTimeMs()),
        "kafka-source");
```

注意 `KafkaSource` 现在与 [Kafka](/docs/CS/MQ/Kafka/Kafka.md) 的事务、消费者组语义直接相关：offset 由 Flink 托管在状态里（而非提交给 Kafka），恢复时以 Flink 状态为准。

## Sink：三种一致性级别

| 保证 | 实现方式 | 代价 |
| ---- | ---- | ---- |
| At-least-once | 普通 `SinkFunction` / `Sink` V2 直写 | 可能重复，最快 |
| Exactly-once（幂等） | Sink 侧按主键覆盖：Upsert Kafka、HBase、Redis、JDBC（带主键 upsert）、湖表（Paimon / Iceberg） | 要求下游支持幂等；不依赖事务 |
| Exactly-once（事务） | 两阶段提交（2PC）：预提交 → checkpoint 完成后提交 | 输出可见性被推迟到 checkpoint 完成，等于给端到端延迟加了一个 checkpoint 间隔 |

Kafka Sink 的事务写法：

```java
KafkaSink<Event> sink = KafkaSink.<Event>builder()
        .setBootstrapServers("broker:9092")
        .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                .setTopic("result")
                .setValueSerializationSchema(new EventSerializer())
                .build())
        .setDeliveryGuarantee(DeliveryGuarantee.EXACTLY_ONCE)
        .setTransactionalIdPrefix("flink-")      // 开启 Kafka 事务
        .build();

stream.sinkTo(sink);
```

生产上踩过的两个坑：

- **Kafka 事务超时必须大于 checkpoint 间隔**：`transaction.max.timeout.ms` 若小于 checkpoint 完成时间，事务会被 Kafka 主动中止，表现为 "transaction timed out"；
- **读取侧要跳过未提交事务**：消费方需设置 `isolation.level=read_committed`，否则会读到被回滚的事务数据。

## 常用连接器一览

| 类别 | 代表 | 说明 |
| ---- | ---- | ---- |
| 消息队列 | Kafka、Pulsar、RabbitMQ | Kafka 最成熟，支持 Source/Sink 双向 exactly-once |
| 文件系统 | FileSink（HDFS / S3 / OSS） | 流式写文件，靠滚动策略 + 分区提交（part file 状态机：in-progress → pending → finished）保证可见性 |
| 湖存储 | Paimon、Iceberg、Hudi | Flink 2.x 主推的 Streaming Lakehouse 方向，Paimon 与 Flink 集成最深（支持物化表、自适应批执行等） |
| 数据库 / KV | JDBC、HBase、Redis、MongoDB | 多为幂等写入；JDBC 也可用 XA 做 2PC |
| 数仓 / 表格式 | Hive（读写 Hive 表、HiveCatalog） | 批流统一读写 Hive，适合离线数仓实时化 |

选型时的判断顺序：

1. 下游是否支持幂等/upsert？支持就走幂等，成本最低；
2. 不支持但支持事务？走 2PC，但接受延迟增加；
3. 都不支持（如普通文件追加、普通 Kafka topic）？只能是 at-least-once，下游自行去重。

## 端到端 Exactly-once 的完整条件

```
Source 可重放（Kafka / 文件系统，能按 offset、位置回到过去）
  + Flink 内部状态快照（Checkpoint + 对齐/非对齐）
  + Sink 幂等 或 两阶段提交事务
  = 端到端 exactly-once
```

三者缺一不可。也正因如此，"Flink 宣称的 exactly-once"落到具体链路上，一定要回到这三个环节逐个确认，而不是只看框架名。

## Why This Shape

- **为什么 enumerator 跑在单线程 event loop**：`SplitEnumerator` 的实现者只需处理串行回调，不必自己加锁；coordinator 把并发的 split 请求、checkpoint、reader 事件排成一队，这是 FLIP-27"降低 connector 作者门槛"的核心手段。
- **为什么要单独追踪 split 分配**：数据源的 exactly-once 靠"可重放 + 记住读到哪"，而分配记录决定"哪些 split 已经给了谁"。按 checkpoint 分桶保存后，单个 reader 失败可以局部恢复，不必全局回滚。
- **为什么批模式快照多存一份 assignment**：流式作业有周期性 checkpoint 持续记录分配；批模式没有，必须在唯一那次快照里把分配一起写进去，否则恢复时不知道每个 reader 拿到过哪些分片。
- **为什么 HybridSource 切换要等所有 reader 完成**：两个 source 的 offset / split 语义可能完全不同，只有全部 reader 越过边界、位置转换完成后才能安全地换 enumerator，否则会出现跨 source 的重复或丢失。

## Links

- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)
- [State](/docs/CS/Framework/Flink/State.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - DataStream Connectors](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/overview/)
2. [FLIP-27: Refactor Source Interface](https://cwiki.apache.org/confluence/display/FLINK/FLIP-27%3A+Refactor+Source+Interface)
3. [Flink Docs - Kafka Connector](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/kafka/)
4. [Flink Blog - Introducing the new Kinesis/DynamoDB Streams sources（说明 2.x 移除 SourceFunction）](https://flink.apache.org/2024/11/25/introducing-the-new-amazon-kinesis-data-stream-and-amazon-dynamodb-stream-sources)
5. [Flink 2.3.0 Source: SourceCoordinator.java](https://github.com/apache/flink/blob/release-2.3.0/flink-runtime/src/main/java/org/apache/flink/runtime/source/coordinator/SourceCoordinator.java)
6. [Flink 2.3.0 Source: SplitAssignmentTracker.java](https://github.com/apache/flink/blob/release-2.3.0/flink-runtime/src/main/java/org/apache/flink/runtime/source/coordinator/SplitAssignmentTracker.java)
7. [Flink 2.3.0 Source: SplitEnumerator.java](https://github.com/apache/flink/blob/release-2.3.0/flink-core/src/main/java/org/apache/flink/api/connector/source/SplitEnumerator.java)
8. [Flink 2.3.0 Source: HybridSourceSplitEnumerator.java](https://github.com/apache/flink/blob/release-2.3.0/flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/hybrid/HybridSourceSplitEnumerator.java)
