## Introduction

PostgreSQL 同时提供 `json`（文本）与 `jsonb`（二进制）两种 JSON 类型，并内建全文检索（FTS）能力。本文覆盖两者存储差异、jsonb 的 GIN 索引、tsvector/tsquery 全文检索，以及常用函数。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| jsonb 引入 | PG 9.4 |
| 核实日期 | 2026-10-15 |

## JSON vs JSONB

| 维度 | json | jsonb |
| :--- | :--- | :--- |
| 存储 | 原文文本，每次读取重新解析 | 分解后的二进制，读取无需解析 |
| 重复键 | 保留（按输入顺序） | 去重，只留最后一个 |
| 空格/顺序 | 保留 | 不保留 |
| 索引 | 仅表达式（如 `lower(json::text)`） | 支持 GIN / 专用操作符 |
| 写入 | 略快 | 略慢（需解析分解） |

**结论**：除非必须保留键顺序/重复键/空白，否则一律用 `jsonb`。

## Indexing JSONB

```sql
-- GIN + jsonb_path_ops：最佳点查性能，体积小，不支持 `@>` 以外的键存在查询
CREATE INDEX idx_attrs_gin ON orders USING GIN (attrs jsonb_path_ops);

-- GIN + 默认 ops：支持 `@>`、`?`、`?|`、`?&` 全套操作符，体积更大
CREATE INDEX idx_attrs_gin_default ON orders USING GIN (attrs);
```

`jsonb_path_ops` 仅服务 `@>`（包含）查询，是"JSON 文档内嵌过滤"场景的首选。

## Querying JSONB

```sql
-- 取字段
SELECT attrs->'user'->>'name' FROM orders;
-- 包含某键值
SELECT * FROM orders WHERE attrs @> '{"status":"PAID"}';
-- 路径存在
SELECT * FROM orders WHERE attrs ? 'discount';
```

## Full Text Search

PG 全文检索用 `tsvector`（已分词的文档）与 `tsquery`（查询），`@@` 做匹配：

```sql
-- 建 tsvector（可预计算存生成列）
ALTER TABLE articles ADD COLUMN tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', body)) STORED;
CREATE INDEX idx_articles_tsv ON articles USING GIN (tsv);

SELECT title FROM articles WHERE tsv @@ to_tsquery('english', 'postgres & replication');
```

- `to_tsvector` 分词 + 归一化（去停用词、词干）；`to_tsquery` 构造查询
- GIN 索引 tsvector 实现倒排，是 FTS 性能关键
- 支持多语言配置（'english'/'simple'/中文需额外扩展如 zhparser）

> [!NOTE]
>
> 中文全文检索 PG 原生不支持词典分词，常用 `zhparser`（SCWS 分词）或 `pg_jieba` 扩展生成 tsvector；否则只能用 `pg_trgm` + GIN 做 trigram 模糊匹配。

## Common Functions

| 函数 | 作用 |
| :--- | :--- |
| `jsonb_set(jsonb, path, value)` | 更新某路径的值（返回新 jsonb） |
| `jsonb_insert` / `jsonb_delete` | 插入/删除路径 |
| `->` / `->>` | 取对象/数组元素（后者转文本） |
| `#>` / `#>>` | 按路径取 |
| `to_tsvector` / `to_tsquery` | 全文检索分词/查询 |
| `ts_rank` | 相关性打分 |

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Index](/docs/CS/DB/PostgreSQL/Index.md)
- [Extensions](/docs/CS/DB/PostgreSQL/Extensions.md)
- [pgvector 与向量检索](/docs/CS/DB/Concept/vector.md)

## References

1. [PostgreSQL 官方文档: JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)
2. [PostgreSQL 官方文档: Full Text Search](https://www.postgresql.org/docs/current/textsearch.html)
