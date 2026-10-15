## Introduction

PG 在 Heap 之上支持六类索引访问方法，每种针对不同的数据分布与查询模式。本文覆盖索引类型对比、创建最佳实践，以及 B-Tree 的物理组织与源码位置。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Index Types

| 索引 | 默认 | 适合场景 |
| :--- | :--- | :--- |
| B-Tree | ✅ 默认 | 范围查询、排序、等值匹配；几乎所有 OLTP 场景 |
| Hash | 否 | 仅等值；PG 10 起 WAL 可记，但仍极少使用 |
| GiST | 否 | 几何、IP、范围、全文搜索、hstore |
| SP-GiST | 否 | 大稀疏空间、电话号码、IP |
| GIN | 否 | JSONB、数组、tsvector（倒排索引） |
| BRIN | 否 | 时序、地理大表（块级摘要） |

> [!NOTE]
>
> Hash 索引在 PG 10 前不写 WAL（崩溃后需 REINDEX），10 起补上，但除"纯等值"外仍不如 B-Tree 通用，几乎不推荐新建。

## Creation Best Practices

```sql
-- 复合索引：等值在前、范围在后
CREATE INDEX idx_orders_tenant_status_created
  ON orders (tenant_id, status, created_at DESC);

-- 部分索引：过滤活跃订单
CREATE INDEX idx_orders_open ON orders (created_at)
  WHERE status = 'OPEN';

-- 表达式索引
CREATE INDEX idx_users_lower_email ON users (lower(email));

-- 包含列（Index-Only Scan）
CREATE INDEX idx_orders_tenant_id ON orders (tenant_id) INCLUDE (status, created_at);

-- GIN 加速 JSONB 查询
CREATE INDEX idx_orders_attrs_gin ON orders USING GIN (attrs jsonb_path_ops);
```

### Index-Only Scan

Index-Only Scan 成立需满足：查询列都在索引中（含 `INCLUDE`），且目标页在 **VM（Visibility Map）** 中标记全部可见——否则仍需回表查堆可见性。因此落后 autovacuum（VM 不准）会直接让 index-only scan 退化为普通 index scan。

## B-Tree Access Method

`src/backend/access/nbtree/`：

- `nbtinsert.c` / `nbtsplitloc.c` / `nbtpage.c` / `nbtsearch.c`
- 物理页结构：Meta Page / Internal Page / Leaf Page
- 高效删除：标记 `LP_DEAD`；空间在 VACUUM 时回收

B-Tree 是 Lehman & Yao 的 B-Link 变体（高并发下无锁读、分裂只锁相邻页），与经典的 B+Tree 略有差异（见 [B-Link Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)）。

## Maintenance

- `REINDEX CONCURRENTLY`：在线重建索引，不阻塞读写（普通 `REINDEX` 会拿 `ACCESS EXCLUSIVE`）
- `CREATE INDEX CONCURRENTLY`：建索引不阻塞写入
- BRIN 特别适合按时间/物理有序的大表，体积小但仅对"列值与块范围强相关"有效

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [B-Link Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)
- [MySQL Index](/docs/CS/DB/MySQL/Index.md)

## References

1. [PostgreSQL 官方文档: Indexes](https://www.postgresql.org/docs/current/indexes.html)
2. [PostgreSQL 官方文档: B-Tree](https://www.postgresql.org/docs/current/btree.html)
3. [MySQL Index](/docs/CS/DB/MySQL/Index.md)
