## Introduction

无界流没有"算完"的时刻，要得到聚合结果就必须把无限数据切成有限的块——**窗口（window）**就是这块切法。Flink 的窗口是**把无界流切分成有界"桶"（bucket）**的机制：每个事件按规则落入一个或多个桶，桶满足触发条件时输出一次结果。

窗口与 [时间语义](/docs/CS/Framework/Flink/Time.md) 强耦合：事件时间窗口靠 watermark 触发，处理时间窗口靠机器时钟触发。窗口内累积的中间结果就是 [State](/docs/CS/Framework/Flink/State.md) 的一部分，靠 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md) 保证容错。

## 窗口的分类

按**分配方式（assigner）**分四类：

| 类型 | 定义 | 是否有重叠 | 典型 API |
| ---- | ---- | ---- | ---- |
| Tumbling（滚动） | 固定长度、首尾相接 | 否，一条数据只进一个窗口 | `TumblingEventTimeWindows.of(Duration.ofMinutes(5))` |
| Sliding（滑动） | 固定长度 + 滑动步长 | 是，一条数据进多个窗口 | `SlidingEventTimeWindows.of(Duration.ofMinutes(10), Duration.ofMinutes(1))` |
| Session（会话） | 按活跃间隙（gap）切分，间隙超时则窗口关闭 | 否，窗口长度不固定 | `EventTimeSessionWindows.withGap(Duration.ofMinutes(10))` |
| Global（全局） | 所有数据进同一个窗口 | —— | `GlobalWindows.create()`，必须自定义 Trigger |

按**驱动维度**：

- Time Window：按时间（上面四种都是）；
- Count Window：`countWindow(n)`，攒够 n 条触发，全局窗口与 keyed 窗口语义差别很大，生产较少用。

按**是否按键分组**：

- Keyed Window：`keyBy(...).window(...)`，可并行，每个 key 独立开窗，是最常用形态；
- Non-Keyed Window：`windowAll(...)`，并行度强制为 1，**只有一个子任务**处理全量数据，仅适合小数据量或调试。

## 窗口的生命周期

一个窗口从创建到销毁，由四个部件协作：

```
数据到达 → WindowAssigner 分配窗口(可多个)
        → 数据进入 Window State（按 key + window 隔离）
        → Trigger 判断：FIRE(触发计算) / PURGE(清空状态) / FIRE_AND_PURGE / CONTINUE
        → 触发时交给 Window Function 计算
        → 可选 Evictor 在计算前后剔除元素
        → watermark 超过窗口最大时间戳 + allowedLateness → 窗口销毁，状态清除
```

### WindowAssigner

决定元素属于哪些窗口。除了内置四种，也可以实现 `WindowAssigner` 自定义（如按业务日期切分）。

### Trigger（触发器）

决定**什么时候**输出结果。内置实现：

- `EventTimeTrigger`：watermark 越过窗口末尾时触发，事件时间窗口的默认触发器；
- `ProcessingTimeTrigger`：处理时间到达窗口末尾时触发；
- `CountTrigger`：计数达到阈值触发；
- `PurgingTrigger`：包装其他触发器，触发后强制清空状态（不保留后续迟到更新）；
- `ContinuousEventTimeTrigger`：按固定间隔周期性输出（提前发出、后续覆盖，适合大窗口看趋势）。

Trigger 让"窗口何时关"变成可编程的：比如"每分钟输出一次当前 UV，窗口结束时再输出最终值"就是 `ContinuousEventTimeTrigger`。

### Evictor（驱逐器）

可选，在窗口函数计算前/后剔除元素，如 `CountEvictor`（只保留最近 N 条）、`TimeEvictor`。使用 Evictor 会阻止预聚合优化（数据必须全量留存）。

### 增量聚合 vs 全量聚合

这是窗口性能的分水岭：

| 方式 | API | 状态占用 | 说明 |
| ---- | ---- | ---- | ---- |
| 增量聚合 | `reduce()` / `aggregate()` | 只存一个累加器 | 来一条聚合一条，**窗口触发时才输出一次**；状态小、性能好 |
| 全量聚合 | `ProcessWindowFunction` | 存窗口内所有元素 | 能拿到窗口上下文（`window()`、`currentWatermark()`、窗口状态）；状态随窗口数据量增长 |
| 两者组合 | `aggregate(aggFunc, processWindowFunction)` | 只存累加器 | 推荐写法：增量聚合的高效 + 全量函数的上下文信息 |

```java
stream
    .keyBy(Event::getUserId)
    .window(TumblingEventTimeWindows.of(Duration.ofMinutes(5)))
    // 增量聚合：把结果包进 ProcessWindowFunction 拿到窗口元信息
    .aggregate(new CountAggregate(), new WindowResultFunction())
    .name("5min-uv-per-user");
```

## 会话窗口的特殊之处

会话窗口没有固定起止时间，**窗口的边界由数据本身决定**：相邻两条数据间隔超过 `gap` 就切一个新窗口。更进一步，会话窗口支持**窗口合并（merging）**——后出现的数据可以把它两侧的窗口连起来，因此它的 assigner 是 `MergingWindowAssigner`，触发器需要语义支持（`EventTimeTrigger` 对会话窗口的处理包含合并逻辑）。

会话窗口不能预先知道窗口数量与长度，状态管理成本高于滚动/滑动窗口，但非常适合"用户一次访问""一次设备联网周期"这类场景。

## 迟到与结果修正

窗口不是"一次算完就丢"：

1. watermark 越过窗口末尾 → 触发**第一次**计算（可能不完整）；
2. 若设置了 `allowedLateness(t)`，窗口状态保留到 `window_end + t`，期间迟到数据会**再次触发**计算，输出修正后的结果（下游需要能处理更新，如用 upsert sink 或幂等写入）；
3. 超过允许迟到时间的数据进 `sideOutputLateData`（细节见 [Time](/docs/CS/Framework/Flink/Time.md)）。

因此使用事件时间窗口时，下游要区分**追加流（append）**与**更新流（upsert/retract）**：带迟到修正的窗口输出是更新流，写入 Kafka 普通 topic 会产生重复行，写入支持主键的 sink（Upsert Kafka、JDBC、Paimon/湖存储）才语义正确。

## 窗口状态与清理

- 每个 key + 每个窗口一份状态，key 基数大 × 窗口多会放大状态规模；
- 处理时间窗口靠定时器触发，事件时间窗口靠 watermark，两者都会在窗口超时后清理；
- `GlobalWindows` + 无 Trigger 时状态永不释放，是常见的内存泄漏来源；
- 状态规模与 TTL 的权衡见 [State](/docs/CS/Framework/Flink/State.md)。

## Links

- [Time](/docs/CS/Framework/Flink/Time.md)
- [State](/docs/CS/Framework/Flink/State.md)
- [Table_SQL](/docs/CS/Framework/Flink/Table_SQL.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - Windows](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/)
2. [Flink Docs - Window Functions / ProcessWindowFunction](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/#processwindowfunction)
3. [Flink Docs - Triggers](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/#triggers)
