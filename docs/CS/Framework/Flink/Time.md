## Introduction

时间语义（time semantics）回答的是"Flink 用哪一把尺子丈量数据"：决定窗口何时触发、乱序数据如何取舍、以及结果是否可复现。Flink 的核心卖点之一是**基于事件时间（event time）得到确定性结果**——同一份输入重跑一遍，输出完全一致，这与 [Spark Streaming](/docs/CS/Framework/Spark/Streaming.md) 的微批按到达时间切批、以及"按处理时间聚一批"的做法有本质区别。

> [!NOTE]
> 本页以 Flink 2.x（最新稳定版 2.3.0，2026-06 发布）官方文档为基线。1.x 与 2.x 在配置载体上有差异（2.x 主用 `config.yaml`），时间语义本身没有破坏性变化。

## 三种时间语义

| 时间语义 | 含义 | 时间戳来源 | 特点 |
| ---- | ---- | ---- | ---- |
| Event Time（事件时间） | 事件**实际发生**的时间 | 数据自带字段（如日志里的 `ts`） | 结果确定、可重放；需要 watermark 处理乱序；有延迟 |
| Processing Time（处理时间） | 数据被算子**处理**时的机器时钟 | 算子所在机器的系统时间 | 延迟最低、无需 watermark；结果不可重放，受背压/重跑影响 |
| Ingestion Time（摄入时间） | 数据进入 Flink Source 的时间 | Source 算子本地时钟打戳 | 介于两者之间：比处理时间稳定（不受下游背压影响），但无法表达真实事件顺序 |

实践中的取舍：

- 要"算准"（计费、风控、报表对账）→ **Event Time**；
- 要"算快"且允许结果随运行波动（监控阈值告警）→ **Processing Time**；
- 数据里没有可信时间戳，又想比处理时间稳定一些 → Ingestion Time。

## Watermark

事件时间不能靠"看时钟"推进，因为数据会乱序、会迟到。Flink 用 **Watermark（水位线）** 表达事件时间的推进进度：

> 一条时间戳为 $T$ 的 watermark 表示：此后不会再有时间戳 $\le T$ 的（正常）记录到达。

它是一条夹在数据流里的特殊记录，随数据一起在算子间流动，因此**单调不减**且**由上游向下游传播**。

几个关键推论：

- Watermark 不是"数据的最大时间戳"，而是"对乱序程度的承诺"。设得越激进（更接近最大时间戳），延迟越低但丢数据风险越高；设得越保守，延迟越高但结果越完整；
- 窗口触发条件由 watermark 决定：当 $watermark \ge window\_end - 1ms$ 时窗口触发计算；
- 只有事件时间语义才需要 watermark；处理时间不需要。

### 生成策略

Flink 把"抽取时间戳"与"生成水位"两件事拆成两个接口，由 `WatermarkStrategy` 组合：

```java
WatermarkStrategy
    .<MyEvent>forBoundedOutOfOrderness(Duration.ofSeconds(5))   // 允许 5s 乱序
    .withTimestampAssigner((event, ts) -> event.getEventTimeMs());
```

- `TimestampAssigner`：从记录里取出事件时间戳；
- `WatermarkGenerator`：决定何时发水位。常用两种内置策略：
  - `forMonotonousTimestamps()`：假定数据严格递增，水位 = 当前最大时间戳；
  - `forBoundedOutOfOrderness(Duration)`：允许固定乱序界，水位 = 最大时间戳 − 乱序界，这是生产最常见的选择。

自定义场景（如按业务字段判断乱序、周期性发水位）实现 `WatermarkGenerator` 即可：

```java
public interface WatermarkGenerator<T> {
    void onEvent(T event, long eventTimestamp, WatermarkOutput output);
    void onPeriodicEmit(WatermarkOutput output);   // 由 watermarkInterval 触发
}
```

**首选在 Source 上指定策略**（`env.fromSource(source, watermarkStrategy, name)`），而不是在任意算子后 `assignTimestampsAndWatermarks()`。原因见下节：Source 知道分区（split）信息，可以按分区生成更精确的水位。

## 多分区与水位传播

算子通常有多个输入（多个上游并行子任务、或多条流 `union`/`connect`），水位必须合并：

$$
watermark_{out} = \min(watermark_{in_1}, watermark_{in_2}, \dots)
$$

取最小保证了"慢的那个说了算"，否则快分区的水位会提前关掉慢分区还未来数据的窗口。这也带来两个经典问题：

### 空闲输入（idle source）

某个 Kafka 分区长时间没数据，它就不产生水位，$\min$ 被它卡住，**整条流的时间停滞**，下游窗口永不触发。解法是标记空闲：

```java
WatermarkStrategy
    .<MyEvent>forBoundedOutOfOrderness(Duration.ofSeconds(5))
    .withIdleness(Duration.ofMinutes(1));   // 1 分钟无数据则视为空闲，不再参与 min
```

### 事件时间倾斜（event time skew）

反过来的情形：多个分区都有数据，但进度差异极大（例如一个分区在追历史数据、另一个在追实时）。$\min$ 让整体水位被拖慢，而快分区的数据滞留在状态里，**状态持续膨胀**。

Flink 提供 **watermark alignment**：为 source 配置允许的最大漂移（例如 1 分钟），当某个分区领先太多时暂停从该分区读取，等慢的追上来再继续。代价是该分区吞吐被人为压低，收益是状态规模可控——本质是用吞吐量换状态大小。

## 迟到数据

水位只保证"一般不会更迟"，超出的记录叫迟到数据（late records），有三种处理姿势：

| 方式 | 行为 | 适用 |
| ---- | ---- | ---- |
| 默认丢弃 | 窗口已触发并清除，迟到记录被丢弃 | 允许少量丢失 |
| `allowedLateness(t)` | 窗口触发后保留状态一段时间，迟到记录**再次触发**计算（可多次） | 需要修正结果，如补算金额 |
| 侧输出 `sideOutputLateData` | 迟到数据单独收集到旁路流，另行处理/落库补偿 | 要求不丢，且需要可观测 |

```java
OutputTag<MyEvent> lateTag = new OutputTag<MyEvent>("late") {};

SingleOutputStreamOperator<Result> result = stream
    .keyBy(MyEvent::getUserId)
    .window(TumblingEventTimeWindows.of(Duration.ofMinutes(5)))
    .allowedLateness(Duration.ofMinutes(1))       // 额外容忍 1 分钟
    .sideOutputLateData(lateTag)                  // 再晚的进侧输出
    .aggregate(new MyAgg());

DataStream<MyEvent> late = result.getSideOutput(lateTag);
```

注意：`allowedLateness` 意味着窗口状态不能在触发后立即清理，会**延长状态存活时间**，与 [State](/docs/CS/Framework/Flink/State.md) 里的 TTL 需要一起权衡。

## 与处理时间的对照

同一段 5 分钟窗口，两种语义的差异：

| 维度 | Event Time + Watermark | Processing Time |
| ---- | ---- | ---- |
| 结果是否可复现 | 是，重跑一致 | 否，取决于当时机器负载 |
| 需要 watermark | 是 | 否 |
| 端到端延迟 | 高一个水位间隔 | 最低 |
| 乱序/迟到处理 | 有完整机制 | 无，数据到了就算 |
| 典型场景 | 结算、对账、报表 | 实时监控、近似统计 |

## Links

- [Window](/docs/CS/Framework/Flink/Window.md)
- [State](/docs/CS/Framework/Flink/State.md)
- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)
- [Connector](/docs/CS/Framework/Flink/Connector.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - Notions of Time: Event Time and Watermarks](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/)
2. [Flink Docs - Generating Watermarks](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/event-time/generating_watermarks/)
3. [Flink Docs - Watermark Alignment](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/event-time/alignment/)
