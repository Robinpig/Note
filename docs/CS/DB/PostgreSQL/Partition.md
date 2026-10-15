## Introduction

PostgreSQL 10 引入声明式分区（declarative partitioning），把大表按 range/list/hash 切成子表，查询时由规划器做分区剪枝（partition pruning），只扫描相关分区。本文覆盖分区类型、剪枝、维护操作与分区表索引。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 声明式分区 | PG 10+（早期为继承式分区，已不推荐） |
| 核实日期 | 2026-10-15 |

## Partition Types

| 类型 | 路由规则 | 典型场景 |
| :--- | :--- | :--- |
| range | 按范围（如时间） | 日志、订单按月份 |
| list | 按离散值（如地区） | 多租户按 tenant_id |
| hash | 按哈希取模 | 均匀分布、无自然范围 |

```sql
-- range 分区
CREATE TABLE orders (id bigint, created_at date, amount numeric)
  PARTITION BY RANGE (created_at);
CREATE TABLE orders_2026_01 PARTITION OF orders
  FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- list 分区
CREATE TABLE events (id bigint, region text)
  PARTITION BY LIST (region);
CREATE TABLE events_east PARTITION OF events FOR VALUES IN ('east', 'north');

-- hash 分区
CREATE TABLE metrics (id bigint, payload jsonb)
  PARTITION BY HASH (id);
CREATE TABLE metrics_p0 PARTITION OF metrics FOR VALUES WITH (MODULUS 4, REMAINDER 0);
```

## Partition Pruning

规划器在生成计划时根据 WHERE 条件排除无关分区：

- **静态剪枝**：WHERE 含常量条件（如 `created_at = '2026-01-15'`）时，规划期即可确定目标分区
- **动态剪枝**：WHERE 含运行时参数（如绑定变量）时，执行期首趟确定

开启 `enable_partition_pruning = on`（默认），`EXPLAIN` 中只出现被选中分区，未选中的分区根本不开子计划。

## Indexes on Partitioned Tables

- 分区表上建的索引是"分区索引"：父表建索引，每个子分区自动各建一份
- 唯一约束/主键必须包含分区键（否则无法跨分区保证唯一）
- 子分区可独立建本地索引；PG 不直接支持"全局索引"（跨分区单一索引），需用表达式/触发器变通

## Maintenance

```sql
-- 在线挂载新分区（不阻塞读写）
ALTER TABLE orders ATTACH PARTITION orders_2026_02
  FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- 卸载分区（转为普通表，可单独归档/删除）
ALTER TABLE orders DETACH PARTITION orders_2025_old;
```

`ATTACH` 时 PG 会校验数据是否满足分区约束；大分区 ATTACH 可能锁表并全表扫描校验，建议在低峰执行。

> [!NOTE]
>
> 分区数过多（上千个）会让规划器开销上升——分区剪枝本身很快，但打开每个子分区的锁与 relcache 成本随分区数线性增长。月度分区通常安全，避免过细（如按天）导致分区爆炸。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Index](/docs/CS/DB/PostgreSQL/Index.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [MySQL file](/docs/CS/DB/MySQL/file.md)

## References

1. [PostgreSQL 官方文档: Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)
2. [MySQL file](/docs/CS/DB/MySQL/file.md)
