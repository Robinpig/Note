## Introduction

Table API 与 SQL 是 Flink 的**声明式**编程接口：用户描述"要什么结果"，由优化器（基于 Apache Calcite）生成执行计划，最终仍然编译成 DataStream 算子，跑在同一个流式运行时上。相比手写 [DataStream](/docs/CS/Framework/Flink/Dataflow.md) 拓扑，它把状态管理、窗口触发、[时间语义](/docs/CS/Framework/Flink/Time.md) 细节都交给了框架。

一句话概括这层的核心抽象：**动态表（Dynamic Table）上的连续查询（Continuous Query）**。

## 流与动态表的对偶

- 流 → 动态表：一条条 INSERT/UPDATE/DELETE 变更事件，累积成一张不断被修改的表；
- 动态表 → 流：表上的查询结果再以变更日志（changelog）的形式流出去。

因此流上的 SQL 与数据库里的 SQL 有一个关键差别：**结果不是一次算完的，而是持续被更新的**。这直接引出 changelog 模式：

| 模式 | 语义 | 常见来源 |
| ---- | ---- | ---- |
| Append-only | 只有插入，结果不再变 | 纯过滤、`GROUP BY` 后无迟到修正的 append 流 |
| Upsert | 带主键的插入/更新（`+U`、`-U` 合并为 upsert） | 带主键的聚合、维表 join 结果 |
| Retract | 撤回旧值 + 发出新值（`-D`/`+I`） | 无主键的聚合更新 |

下游 sink 必须能匹配上游的 changelog 模式：upsert 流写普通 Kafka topic 会产生重复行，应写入 Upsert Kafka、JDBC（带主键）、湖表等支持更新的目标（见 [Connector](/docs/CS/Framework/Flink/Connector.md)）。

## 时间属性

SQL 里的时间与 DataStream 一一对应，通过 DDL 定义：

```sql
CREATE TABLE orders (
    order_id   BIGINT,
    user_id    BIGINT,
    amount     DECIMAL(10, 2),
    event_time TIMESTAMP(3),
    WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND,   -- 事件时间 + 水位
    PRIMARY KEY (order_id) NOT ENFORCED
) WITH (
    'connector' = 'kafka',
    'topic' = 'orders',
    'properties.bootstrap.servers' = 'broker:9092',
    'format' = 'json'
);
```

- `WATERMARK FOR ... AS ...`：声明 rowtime 属性与水位生成策略（对应 `WatermarkStrategy`）；
- `PROCTIME()`：声明处理时间属性；
- 时间属性是**窗口 TVF、interval join、temporal join 能否生效的前提**——没有时间属性，很多算子只能退化为普通 join（全量状态）。

## 窗口表值函数（Window TVF）

Flink 1.13 起推荐用**窗口表值函数**替代早期的 `GROUP BY TUMBLE(...)` 分组窗口语法。TVF 把窗口表达成一张"带窗口列的表"，可以参与 join、聚合、Top-N，表达能力更强：

```sql
SELECT window_start, window_end, user_id, SUM(amount) AS total
FROM TABLE(
    TUMBLE(TABLE orders, DESCRIPTOR(event_time), INTERVAL '5' MINUTES)
)
GROUP BY window_start, window_end, user_id;
```

四种窗口 TVF：

| 函数 | 语义 | 对应 DataStream |
| ---- | ---- | ---- |
| `TUMBLE` | 固定长度不重叠 | 滚动窗口 |
| `HOP` | 固定长度 + 滑动步长 | 滑动窗口 |
| `CUMULATE` | 累积窗口，按步长逐步扩大统计区间 | 常见于"从零点累计到当前"的指标 |
| `SESSION` | 按活跃间隙切分 | 会话窗口 |

窗口 TVF 的输出带上 `window_start` / `window_end` 列，天然支持"窗口结束后再与其他流 join"这类需求，这是旧分组窗口语法做不到的。

## Join 的几种形态

| Join 类型 | 语义 | 状态 |
| ---- | ---- | ---- |
| Regular Join | 两条流任意匹配，无时间约束 | 双流状态**无界增长**，必须配 TTL 或改其他 join |
| Interval Join | 时间区间内匹配（`ltime BETWEEN rtime AND rtime + INTERVAL`） | 状态随区间自动清理，推荐 |
| Temporal Join（版本表） | 按**某一时刻的维表快照**关联（如汇率快照表） | 需要带时间属性的维表（变更日志/CDC） |
| Lookup Join | 每条记录实时查外部维表（JDBC/HBase/Redis） | 算子内缓存维表，可配缓存 TTL；吞吐受外部系统限制 |
| Window Join | 先开窗再在同一窗口内 join | 状态随窗口清理 |

## 优化器与批流同一引擎

- SQL 经过 Calcite 的解析 → 校验 → 逻辑优化（RBO/CBO）→ 物理计划 → 生成 `Transformation` → 走 StreamGraph/JobGraph 那套流程（见 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)）；
- 流式计划与批式计划由 `execution.runtime-mode`（STREAMING / BATCH / AUTOMATIC）决定，批模式会启用阻塞式 shuffle、sort-merge shuffle、批处理算子实现等更"批处理化"的物理策略；
- Flink 2.x 的**自适应批执行（Adaptive Batch Execution）**更进一步：除了物理计划，还能基于已执行阶段的运行时统计**动态调整逻辑计划**（如动态改广播 join、倾斜 join 处理）。

## 物化表（Materialized Table）

Flink 1.20 引入 MVP、2.0 增强的**物化表**，目标是让"实时"与"离线"用同一份声明管理：

```sql
CREATE MATERIALIZED TABLE user_orders_mv
REFRESH_INTERVAL = '1 min'
AS SELECT user_id, COUNT(*) AS cnt, SUM(amount) AS total
   FROM orders GROUP BY user_id;
```

- 用户只写查询结果的定义，框架按刷新间隔在后台持续维护这张表；
- 2.0 起支持**修改 schema 与查询定义**（无需重跑历史数据），并支持把刷新作业提交到 YARN / Kubernetes；
- 与 Paimon 等湖格式结合后，就是 Flink 主推的 **Streaming Lakehouse**：实时写入湖表，查询侧既能读实时增量也能读历史快照。

## 与 DataStream 的关系

两者不是二选一，而是可以互转：`StreamTableEnvironment.fromDataStream()` / `toDataStream()` / `toChangelogStream()`。常见分工是：

- 主体 ETL、聚合、join 用 SQL 写（开发快、优化器兜底）；
- 复杂状态机、CEP、自定义调度用 DataStream 的 `ProcessFunction` 写（控制力强）；
- 二者在中间通过 changelog 流衔接。

## Links

- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Window](/docs/CS/Framework/Flink/Window.md)
- [Connector](/docs/CS/Framework/Flink/Connector.md)
- [Spark SQL](/docs/CS/Framework/Spark/SQL.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - Table API & SQL Concepts（Dynamic Tables）](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/table/concepts/dynamic_tables/)
2. [Flink Docs - Window TVF](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/table/sql/queries/window-tvf/)
3. [Flink Docs - Joins in Continuous Queries](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/table/sql/queries/joins/)
4. [Apache Flink 2.0.0 Release Announcement（物化表、自适应批执行、Streaming Lakehouse）](https://flink.apache.org/2025/03/24/apache-flink-2.0.0-a-new-era-of-real-time-data-processing)
