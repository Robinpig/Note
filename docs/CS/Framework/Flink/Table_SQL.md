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

### Changelog Conversion Operators（2.3）

DataStream API 早就有 `toChangelogStream()` / `fromChangelogStream()`，2.3 把等价能力带进 SQL（FLIP-564，两个内置 PTF）：

```sql
-- 带操作列的 append 流 → 动态表（op_mapping 可映射自定义 CDC 格式）
SELECT * FROM FROM_CHANGELOG(append_stream, DESCRIPTOR(op), ['I','U','D']);
-- 动态表 → append-only changelog 流（把 retract/upsert 流转成 append）
SELECT * FROM TO_CHANGELOG(aggregated_table);
```

`TO_CHANGELOG` 是**第一个在 SQL 层把 retract / upsert 流转成 append 形式**的算子，适合归档、审计、写 append-only sink。2.3 只覆盖基础场景，`PARTITION BY` / `invalid_op_handling` / `produces_full_deletes` 留到 2.4。

#### Source-level mechanics

> [!NOTE]
> 版本基线：Flink **2.3.0**（tag `release-2.3.0`）。下文源码片段均取自该 tag，路径相对仓库根目录，不带行号。

这两个 PTF 在 `flink-table/flink-table-runtime/.../functions/ptf/` 下各对应一个 `BuiltInProcessTableFunction`，实现比概念描述更直白——**它们只做 RowKind 与操作码字符串的互转，不碰状态**：

`ToChangelogFunction` 把每条输入行的 `RowKind` 映射成操作码，拼到输出行的最前面（输出 schema 为 `[op_column, ...input_columns]`），因此输出一定是 INSERT-only：

```java
/**
 * Converts each input row into an INSERT-only output row with an operation code column. The
 * output schema is {@code [op_column, ...all_input_columns...]}.
 */
public class ToChangelogFunction extends BuiltInProcessTableFunction<RowData> {

    private static final Map<RowKind, String> DEFAULT_OP_MAPPING =
            Map.of(
                    RowKind.INSERT, "INSERT",
                    RowKind.UPDATE_BEFORE, "UPDATE_BEFORE",
                    RowKind.UPDATE_AFTER, "UPDATE_AFTER",
                    RowKind.DELETE, "DELETE");
```

无法映射的 RowKind 直接跳过（不报错），这正是"转换成 append 流"的实现方式——把撤回语义编码进数据列：

```java
public void eval(
        final Context ctx,
        final RowData input,
        @Nullable final ColumnList op,
        @Nullable final MapData opMapping) {
    final StringData opCode = opMap.get(input.getRowKind());
    if (opCode == null) {
        return;
    }

    opRow.setField(0, opCode);
    collect(output.replace(opRow, input));
}
```

`FromChangelogFunction` 是逆过程：从 append 流里读操作码列，设置回 `RowKind`；**NULL 或非法操作码直接抛 `TableRuntimeException`**，不做容错——这与 `TO_CHANGELOG` 的静默跳过不对称，是排障时要留意的点：

```java
public void eval(
        final Context ctx,
        final RowData input,
        @Nullable final ColumnList op,
        @Nullable final MapData opMapping) {
    if (input.isNullAt(opColumnIndex)) {
        throw new TableRuntimeException(
                "Received NULL op code. Every changelog row must carry an operation code.");
    }
    final StringData opCode = input.getString(opColumnIndex);
    final RowKind rowKind = opMap.get(opCode);
    if (rowKind == null) {
        throw new TableRuntimeException(
                String.format(
                        "Received invalid op code '%s'. Defined op codes are: %s.",
                        opCode, opMap.keySet()));
    }

    projectedOutput.replaceRow(input);
    projectedOutput.setRowKind(rowKind);
    collect(projectedOutput);
}
```

操作码映射支持逗号分隔的"多 RowKind → 同一码"（如 `"INSERT, UPDATE_AFTER"`），因此可以把 upsert 流折叠成更粗粒度的语义。

> [!NOTE]
> 别把这里的 `ChangelogStreamWrapper` 与 SQL changelog 混淆：`flink-dstl/flink-dstl-dfs/.../ChangelogStreamWrapper.java` 是 **DSTL 状态变更日志的文件流包装器**（Snappy 压缩 + seek），服务于 changelog state backend，与 `FROM_CHANGELOG` / `TO_CHANGELOG` 两个 SQL PTF 无关。

changelog 模式本身在 `flink-table-common/.../connector/ChangelogMode.java` 定义，四种标准模式由 `RowKind` 集合 + `keyOnlyDeletes` 标志构成：

```java
private static final ChangelogMode INSERT_ONLY =
        ChangelogMode.newBuilder().addContainedKind(RowKind.INSERT).build();

private static final ChangelogMode UPSERT =
        ChangelogMode.newBuilder()
                .addContainedKind(RowKind.INSERT)
                .addContainedKind(RowKind.UPDATE_AFTER)
                .addContainedKind(RowKind.DELETE)
                .keyOnlyDeletes(true)
                .build();

private static final ChangelogMode ALL =
        ChangelogMode.newBuilder()
                .addContainedKind(RowKind.INSERT)
                .addContainedKind(RowKind.UPDATE_BEFORE)
                .addContainedKind(RowKind.UPDATE_AFTER)
                .addContainedKind(RowKind.DELETE)
                .build();
```

`UPSERT` 与 `UPSERT_WITH_FULL_DELETES` 的**唯一差别是 `keyOnlyDeletes`**——这决定 DELETE 消息是否只带主键。这就是为什么 Upsert Kafka 能只靠 key 删除，而普通 sink 需要整行。

### Upsert Sink 的显式冲突策略（2.3）

当上游 upsert key 与 sink 主键不一致时（多级变换、projection、join 常见），旧版靠 `SinkUpsertMaterializer` 物化全量更新历史，状态无界增长。2.3（FLIP-558）改为**默认在 plan 阶段直接报错**，必须显式声明冲突策略：

```sql
INSERT INTO target_table SELECT * FROM source
ON CONFLICT DO DEDUPLICATE;   -- DO NOTHING / DO ERROR / DO DEDUPLICATE
```

> [!WARNING]
> 这是 2.3 的**有意为之的破坏性变化**：2.2 能正常规划的查询，在 2.3 可能因缺 `ON CONFLICT` 而规划失败。升级前先检查所有写入主键表的 INSERT 语句。

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
- 2.3 进一步（FLIP-557 / FLIP-550）支持**原地演进查询定义**：改定义不必 drop + recreate 再重跑全部历史，直接省掉重算开销；
- 与 Paimon 等湖格式结合后，就是 Flink 主推的 **Streaming Lakehouse**：实时写入湖表，查询侧既能读实时增量也能读历史快照。

#### Source-level refresh workflow

`MaterializedTableManager`（`flink-table/flink-sql-gateway/.../materializedtable/`）按 `RefreshMode` 走两条完全不同的路，这是理解"物化表到底跑什么作业"的关键：

```java
if (RefreshMode.CONTINUOUS == materializedTable.getRefreshMode()) {
    createMaterializedTableInContinuousMode(
            operationExecutor, handle, createMaterializedTableOperation);
} else {
    createMaterializedTableInFullMode(
            operationExecutor, handle, createMaterializedTableOperation);
}
```

- **CONTINUOUS**：直接提交一个常驻流作业（`executeContinuousRefreshJob`）。提交失败时会反过来 drop 已建的表，源码注释明确这是 "weak atomicity"——不是事务，靠补偿动作兜底：
```java
} catch (Exception e) {
    // drop materialized table while submit flink streaming job occur exception. Thus, weak
    // atomicity is guaranteed
    operationExecutor.callExecutableOperation(
            handle, new DropMaterializedTableOperation(materializedTableIdentifier, true));
    throw new SqlExecutionException(...);
}
```
- **FULL**：不提交常驻作业，而是把 freshness 转成 cron，通过 `WorkflowScheduler.createRefreshWorkflow()` 交给外部调度器（`CreatePeriodicRefreshWorkflow`），并把序列化后的 `RefreshHandler` 写回 catalog。没有配置 scheduler 就直接报错：
```java
if (workflowScheduler == null) {
    throw new SqlExecutionException(
            "The workflow scheduler must be configured when creating materialized table in full refresh mode.");
}
final IntervalFreshness freshness = catalogMaterializedTable.getDefinitionFreshness();
String cronExpression = convertFreshnessToCron(freshness);
CreateRefreshWorkflow createRefreshWorkflow =
        new CreatePeriodicRefreshWorkflow(
                materializedTableIdentifier,
                catalogMaterializedTable.getExpandedQuery(),
                cronExpression,
                ...);
RefreshHandler refreshHandler = workflowScheduler.createRefreshWorkflow(createRefreshWorkflow);
```

`RefreshMode` 枚举只有 `CONTINUOUS` 与 `FULL` 两个值（在 `CatalogMaterializedTable` 内定义）。所以"改查询定义原地演进"不是改了作业本身，而是按模式分别更新流作业或周期 workflow 的定义。

> [!WARNING]
> 2.3 修复了 `MiniBatchGroupAggFunction` 的**静默丢数据**缺陷（FLINK-35661）：当某个 key 的 mini-batch 全是撤回且无既有状态时，函数会提前返回，把 bundle 里剩余 key 全部丢掉。触发条件是 `ONE_PHASE` 聚合 + minibatch，这是从 2.2 升级到 2.3 的硬理由。

## 与 DataStream 的关系

两者不是二选一，而是可以互转：`StreamTableEnvironment.fromDataStream()` / `toDataStream()` / `toChangelogStream()`。常见分工是：

- 主体 ETL、聚合、join 用 SQL 写（开发快、优化器兜底）；
- 复杂状态机、CEP、自定义调度用 DataStream 的 `ProcessFunction` 写（控制力强）；
- 二者在中间通过 changelog 流衔接。

## Why This Shape

- **为什么 changelog 模式是 connector 契约**：`ChangelogMode` 用 `RowKind` 集合 + `keyOnlyDeletes` 精确描述"上游会发什么"，sink 据此决定能否接受；模式不匹配要在规划期发现，而不是运行时写出重复行。
- **为什么 `TO_CHANGELOG` 只是加操作码列**：它不维护任何状态，把 `-U/-D` 的语义编码进 append 行的首列，从而让不支持 retract 的 append-only sink 也能消费更新流；代价是下游必须理解操作码才能还原语义。
- **为什么两个 PTF 的错误处理不对称**：`FROM_CHANGELOG` 遇到非法操作码抛异常（数据本身坏了，继续跑只会污染结果），`TO_CHANGELOG` 遇到无法映射的 RowKind 跳过（正常的模式收敛行为）。
- **为什么物化表要分 CONTINUOUS / FULL 两条路**：前者是常驻流作业、低延迟；后者是 cron 触发的批作业、省资源。把二者塞进一个执行模型会同时在延迟和成本上妥协，所以源码在 `RefreshMode` 处就分叉。

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
5. [Flink 2.3.0 Source: ToChangelogFunction.java](https://github.com/apache/flink/blob/release-2.3.0/flink-table/flink-table-runtime/src/main/java/org/apache/flink/table/runtime/functions/ptf/ToChangelogFunction.java)
6. [Flink 2.3.0 Source: FromChangelogFunction.java](https://github.com/apache/flink/blob/release-2.3.0/flink-table/flink-table-runtime/src/main/java/org/apache/flink/table/runtime/functions/ptf/FromChangelogFunction.java)
7. [Flink 2.3.0 Source: ChangelogMode.java](https://github.com/apache/flink/blob/release-2.3.0/flink-table/flink-table-common/src/main/java/org/apache/flink/table/connector/ChangelogMode.java)
8. [Flink 2.3.0 Source: MaterializedTableManager.java](https://github.com/apache/flink/blob/release-2.3.0/flink-table/flink-sql-gateway/src/main/java/org/apache/flink/table/gateway/service/materializedtable/MaterializedTableManager.java)
