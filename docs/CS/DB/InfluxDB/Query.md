## Introduction

InfluxDB 3 的查询侧只保留两种语言：**SQL**（主力，由 DataFusion 全功能执行）与 **InfluxQL**（向后兼容层，内部翻译成 SQL 执行）。与 2.x 最大的断裂是 **Flux 全线移除**——官方明确任何 3.x 产品都不提供 Flux 兼容层，2.x 的 Flux 脚本必须改写。传输层走 Arrow Flight SQL，HTTP API 留给不需要 Flight 性能的简单请求。

## SQL

SQL 是 3.x 的一等公民，能力就是 DataFusion 的能力：完整解析器、优化器、向量化执行器，支持 JOIN、窗口函数、子查询、CTE、聚合、排序。典型查询：

```sql
-- 最近一小时按 region 分组的均值
SELECT region, AVG(usage_user) AS avg_user, AVG(usage_system) AS avg_sys
FROM cpu
WHERE time >= now() - INTERVAL '1 hour'
GROUP BY region
ORDER BY avg_user DESC;

-- 时间分桶降采样
SELECT time_bucket(INTERVAL '5 minutes', time) AS bucket,
       host,
       AVG(usage_user) AS user_avg
FROM cpu
WHERE time >= now() - INTERVAL '1 day'
GROUP BY bucket, host;
```

`now()`、`INTERVAL`、`time_bucket()` 是 DataFusion 的时序扩展。3.12 起 `EXPLAIN` 与 `EXPLAIN ANALYZE` 支持 Explain in SQL 输出，执行计划可以直接看到 `PachaTreeWindowExec` 之类的自定义节点。

## InfluxQL

3.x 保留 InfluxQL 与 v1 查询 API，1.x 的查询大多原样可用：

```sql
SELECT mean(usage_user) FROM cpu WHERE time > now() - 1h GROUP BY time(5m), host
```

InfluxQL 在内部被翻译成 DataFusion SQL 再执行，因此 InfluxQL 能用到的最终都是 SQL 引擎的能力。官方迁移建议：能写 SQL 就写 SQL，InfluxQL 只作为存量查询的兼容层。

## Flight SQL

查询结果通过 Arrow Flight SQL 传输，百万行结果不需要昂贵的序列化。客户端库（Python / JavaScript / Rust / Go / Java 等）都支持 Flight；简单请求或脚本场景用 HTTP API：

```shell
influxdb3 query --database mydb "SELECT * FROM cpu LIMIT 5"
```

## No Flux

这是从 2.x 迁移最贵的一刀。官方 FAQ 原文：**Flux 在任何 InfluxDB 3 产品上都不被官方支持**，Flux 自身进入维护模式。替代路径：

| Flux 能力 | 3.x 替代 |
| :-- | :-- |
| 查询与变换 | SQL（JOIN / 窗口函数 / CTE 比 Flux 更完整） |
| 任务与定时计算 | Processing Engine 的 schedule trigger |
| 写入侧变换 | Processing Engine 的 WAL flush trigger |
| 告警 | Processing Engine + 通知类插件 |

## Downsampling Without Continuous Queries

1.x/2.x 的 Continuous Query 引擎在 3.x 不存在，降采样改由两种方式承担：

1. **SQL 物化**：直接 `CREATE TABLE ... AS SELECT time_bucket(...)` 建汇总表，后续查询打汇总表。一次性、灵活，但不自动滚动。
2. **Downsampler 插件**：Processing Engine 官方插件，定时把原始 measurement 聚合成目标 measurement，自动滚动。

```shell
influxdb3 create trigger \
  --database system_metrics \
  --plugin-filename gh:influxdata/downsampler/downsampler.py \
  --trigger-spec "every:1h" \
  --trigger-arguments 'source_measurement=cpu,target_measurement=cpu_hourly,interval=1h,window=6h,calculations=avg,specific_fields=usage_user.usage_system' \
  cpu_hourly_downsample
```

每条降采样记录附带三个元数据列：`record_count`（压缩掉的原始点数）、`time_from` / `time_to`（原始时间范围）。插件的完整机制见 [Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md)。

配套的 **resampler** 插件处理不规则采样：把抖动时间戳重采样到规则网格，支持线性插值（grid 模式下超 `max_gap` 的洞不写点）与 snap 模式（就近对齐，值不变）。

## Recent-Data Query Shortcuts

查询"最新值"和"去重值"不必扫表，直接查缓存 UDTF（毫秒级返回，详见 [Architecture](/docs/CS/DB/InfluxDB/Architecture.md) 的缓存体系）：

```sql
-- 某传感器最近 2 个值
SELECT * FROM last_cache('sensors') WHERE sensor_id = 's-101';

-- 某列的全部去重值
SELECT * FROM distinct_cache('sensors') WHERE machine_id = 'm-07';
```

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [Architecture](/docs/CS/DB/InfluxDB/Architecture.md)
- [Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md)
- [Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md)
- [Timeseries](/docs/CS/DB/Concept/Timeseries.md)

## References

1. [InfluxDB 3 Query Documentation](https://docs.influxdata.com/influxdb3/core/query-data/)
2. [Which InfluxDB 3 should I use](https://docs.influxdata.com/influxdb3/which-influxdb-3/)
3. [Downsampler Plugin](https://docs.influxdata.com/influxdb3/enterprise/plugins/library/official/downsampler)
4. [Resampler Plugin](https://docs.influxdata.com/influxdb3/core/plugins/library/official/resampler)
5. [What's New in InfluxDB 3.12](https://www.influxdata.com/blog/influxdb-3-12)
