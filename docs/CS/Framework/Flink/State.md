## Introduction

**状态（state）** 是 Flink 区别于"无状态转发"类系统的根本：算子可以记住之前看过的数据，从而做聚合、去重、join、模式匹配。Flink 的状态由运行时托管（managed state），与 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md) 机制结合实现故障后精确恢复——这也是"有状态流计算"这一称谓的由来。

状态与窗口的关系很直接：[Window](/docs/CS/Framework/Flink/Window.md) 里累积的中间结果本质上就是状态，窗口超时后状态被清理。

## 两大类状态

Flink 把状态分成两类，划分依据是**是否按键（key）分区**：

### Keyed State

只能用在 `keyBy()` 之后的算子上。逻辑上每个 key 一份状态，物理上按 **key-group** 组织（key-group 数量由 `maxParallelism` 决定，是并行度调整时的最小再分配单元）。

| 类型 | 接口 | 语义 |
| ---- | ---- | ---- |
| ValueState | `ValueState<T>` | 单值，可读可写 |
| ListState | `ListState<T>` | 元素列表，可追加、可遍历 |
| MapState | `MapState<UK, UV>` | 一个 key 下的二级 map |
| ReducingState | `ReducingState<T>` | 按 `ReduceFunction` 自动聚合，只存聚合结果 |
| AggregatingState | `AggregatingState<IN, OUT>` | 按 `AggregateFunction` 聚合，输入/输出类型可不同 |

```java
public class DedupFunction extends KeyedProcessFunction<String, Event, Event> {
    private transient ValueState<Boolean> seen;

    @Override
    public void open(OpenContext ctx) {
        StateTtlConfig ttl = StateTtlConfig.newBuilder(Time.days(1))
                .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
                .build();
        ValueStateDescriptor<Boolean> desc = new ValueStateDescriptor<>("seen", Boolean.class);
        desc.enableTimeToLive(ttl);          // 1 天未更新则过期
        seen = getRuntimeContext().getState(desc);
    }

    @Override
    public void processElement(Event e, Context ctx, Collector<Event> out) throws Exception {
        if (Boolean.TRUE.equals(seen.value())) return;   // 已见过，去重丢弃
        seen.update(true);
        out.collect(e);
    }
}
```

### Operator State

绑定到**算子并行实例**（subtask）而非 key，常见于 Source 与 Sink：Kafka Source 用 `ListState` 记录各分区的 offset，就是典型的 operator state。

- 实现 `CheckpointedFunction` 或 `ListCheckpointed`；
- 并行度变化时支持三种重分配模式：`SPLIT_DISTRIBUTE`（均分）、`UNION`（每个实例拿到全量）、`BROADCAST`；
- 只有 `ListState` 支持重分配（union list state）。

### Broadcast State

第三类特殊形态：把一条低吞吐的流（如规则表）广播到所有并行实例，与主流在 `connect()` 后做匹配。它的 checkpoint 语义是"所有实例持有全量副本"，恢复时每个实例都能拿到完整广播状态。

## 状态后端（State Backend）

状态后端决定**状态存在哪里、怎么存**：

| 后端 | 存储位置 | 特点 | 适用 |
| ---- | ---- | ---- | ---- |
| `HashMapStateBackend` | JVM 堆内存（Java 对象 / hash 表） | 读写最快；受 GC 与堆大小限制；**只能做全量快照** | 状态小（MB~GB 级）、低延迟、调试 |
| `EmbeddedRocksDBStateBackend` | 本地磁盘上的 RocksDB 实例（堆外 + 本地文件） | 状态可远大于内存；支持**增量 checkpoint**；读写需序列化，延迟高于堆内 | 大状态（TB 级）、长周期作业 |
| 分离式状态后端（Flink 2.x 的 ForSt） | 远程分布式文件系统为主存 + 本地缓存 | 计算与状态**解耦**：扩缩容不必迁移状态、checkpoint 轻量；需要异步状态访问 API 才能发挥性能 | 云原生 / K8s、超大状态、频繁扩缩容 |

```java
// 堆内
env.setStateBackend(new HashMapStateBackend());
// RocksDB + 增量快照
env.setStateBackend(new EmbeddedRocksDBStateBackend(true));
```

几个必须记住的差别：

- 堆内后端的状态以 Java 对象形式存在，读写无需序列化，但**大状态会拖垮 GC**；
- RocksDB 后端每次读写都要序列化/反序列化，单次访问更慢，但内存可控、支持增量快照（只上传自上次以来的 SST 文件），是生产大状态作业的默认选择；
- Flink 2.x 引入**分离式状态管理**：状态主存放在远程 DFS，本地只做缓存，配合异步执行模型（把状态访问从计算中解耦，避免阻塞线程）。SQL 层可通过 `table.exec.async-state.enabled` 让支持的算子切换到异步状态访问。

> [!WARNING]
> Flink 1.x 与 2.x 之间**不保证状态兼容**：从 1.x 升级到 2.x 通常无法直接用旧 savepoint 恢复，需要通过重放或双跑切换。

## State TTL

无界流里状态只增不减，TTL 是控制规模的主要手段。`StateTtlConfig` 提供三个维度：

- **更新时机** `UpdateType`：`OnCreateAndWrite`（默认，写操作刷新）、`OnReadAndWrite`（读也刷新，代价更高）；
- **过期数据可见性**：`NeverReturnExpired`（默认，过期即不可见）、`ReturnExpiredIfNotCleanedUp`（物理未清除前仍返回，用于可接受脏读的场景）；
- **清理策略**：
  - `cleanupIncrementally`：访问时惰性清理部分条目（堆内后端）；
  - `cleanupInRocksDBCompactFilter`：借 RocksDB compaction 过滤（RocksDB 后端）；
  - `cleanupFullSnapshot`：只在做全量快照时清理（不减运行时状态规模）；
  - `cleanupInBackground`：后台线程周期清理。

TTL 解决的是"状态无限增长"，而**不解决**"短时间内 key 基数爆炸"——后者要去看 key 设计或加盐打散。

## 扩缩容时的状态重分配

- **Keyed State**：按 key-group 重新划分到新的并行子任务。key-group 数 = `maxParallelism`，因此**并行度不能超过 maxParallelism**，且扩缩容的粒度受它限制。改 `maxParallelism` 会破坏 savepoint 兼容性。
- **Operator State**：按上面三种重分配模式分发。
- **分离式状态后端（2.x）**：状态不在本地，扩缩容不需要搬运大块状态，这是它相对 RocksDB 本地方案最大的运维收益。

## 状态与容错的关系

- 状态快照由 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md) 周期性地持久化到远端存储；
- 恢复时按 key-group 把状态重新装载到各子任务，并从对应 source 位置重放；
- Source 侧的 offset 也是 operator state，二者一起构成端到端一致性（见 [Connector](/docs/CS/Framework/Flink/Connector.md)）。

## Links

- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)
- [Window](/docs/CS/Framework/Flink/Window.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - Stateful Stream Processing / Working with State](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/stateful-stream-processing/)
2. [Flink Docs - State Backends](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/state_backends/)
3. [Flink Docs - State TTL](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/state/#state-time-to-live-ttl)
4. [Apache Flink 2.0.0: A New Era of Real-Time Data Processing（分离式状态与异步执行模型）](https://flink.apache.org/2025/03/24/apache-flink-2.0.0-a-new-era-of-real-time-data-processing)
