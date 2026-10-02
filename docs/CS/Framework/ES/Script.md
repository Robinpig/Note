## Introduction

Elasticsearch 支持在请求中嵌入**脚本（scripting）**，用于在查询、更新、聚合、ingest pipeline、reindex、排序等环节做字段级的动态计算，而不必把逻辑预先固化进文档结构。脚本在数据节点上、针对每个文档（或每个 term bucket）执行。

由于脚本在服务端执行任意逻辑，它同时带来**性能开销与安全风险**，ES 在脚本语言选择、沙箱限制、编译缓存上做了专门设计。

## Painless

ES 历史上支持过 Groovy、JavaScript(Painless 前身)、Python、Expressions、Mustache 等，**默认且推荐的语言是 Painless**（从 5.x 起），这是 Elastic 专门为 ES 设计的一种语法接近 Java/JavaScript 的安全、高性能脚本语言：

- 白名单式的类型与方法限制，默认不允许反射、文件/网络访问、死循环，沙箱可控；
- 可直接访问文档字段：`doc['field'].value`（走 Doc Values，适用于 keyword/数值/日期）、`params._source.field`（读 `_source`，较慢）、`ctx._source`（update/reindex 场景）；
- 编译为字节码并缓存，性能远高于早期的 Groovy。

典型 update 脚本（给计数器加一、用 params 避免硬编码）：

```http
POST /orders/_update/1
{
  "script": {
    "source": "ctx._source.count += params.n; ctx._source.updated = params.now",
    "lang": "painless",
    "params": { "n": 1, "now": "2026-09-17" }
  }
}
```

## Script Types by Context

脚本可以出现在不同上下文，访问的变量与代价不同：

| 上下文 | 入口 | 可用变量 | 典型用途 |
| ---- | ---- | ---- | ---- |
| Update / Upsert | `_update`、`_bulk` | `ctx._source`、`ctx.op`、`params` | 原子更新、条件删除、upsert |
| 查询 / 过滤 | `script` query、`script_score` | `doc[...]` | 无法用 DSL 表达的条件、自定义算分 |
| 排序 | `script_sort` | `doc[...]` | 按计算值排序 |
| 聚合 | `script` metric/bucket、`bucket_script` | `doc[...]`、`params` | 派生指标、桶间计算 |
| Ingest pipeline | `script` processor | `ctx` | 入库前清洗、字段加工 |
| Reindex / Update by query | `script` | `ctx._source` | 批量改造存量数据 |

### doc vs _source

- `doc['field'].value` 走 **column-stride / Doc Values**，读取快，但只对开启 doc_values 的字段（非分析型 text）有效，且默认只看到字段值、看不到原始结构。
- `params['_source'].field` / `ctx._source` 读原始 JSON，灵活但每行都要解析，明显更慢，一般只在 update/reindex 必须改原文时使用。
- 对 text 字段做词项级访问需要 `_terms` 或 fielddata（后者把倒排装入堆内存，开销大、慎用）。

## Stored Scripts

脚本可以用 `_scripts/{id}` 存储在集群状态里反复引用，配合编译缓存降低重复编译开销：

```http
PUT _scripts/increment-count
{
  "script": {
    "lang": "painless",
    "source": "ctx._source.count += params.n"
  }
}

POST /orders/_update/1 { "script": { "id": "increment-count", "params": { "n": 2 } } }
```

## Performance and Security

脚本是 ES 的常见性能与安全隐患，需要注意：

- **编译开销**：脚本的 `source` 会被编译并按内容哈希缓存。**永远不要把变化的值拼进 source 字符串**（会导致每次都产生新脚本、打爆编译缓存与堆），应通过 `params` 传参——这是最常见的线上事故点。
- **执行代价**：脚本逐文档执行，无法像倒排那样提前剪枝，`script` 查询/`script_score` 在大数据量上可能很慢；能用 DSL（`function_score`、runtime fields、ingest）替代就替代。
- **Runtime fields**：7.11+ 提供 runtime field，可在查询时用 Painless 动态定义字段（不入库、schema-on-read），在不 reindex 的前提下做临时派生与映射修正，代价是查询时计算。
- **安全沙箱与开关**：`script.allowed_types` / `allowed_contexts` 可限制是否允许 inline/stored 脚本与允许的上下文；生产应限制非沙箱语言（如 `expression` 之外的任意脚本）并配合安全插件的 RBAC，避免用户提交恶意/死循环脚本拖垮数据节点。
- update 脚本依赖版本号/序列号做乐观并发控制，高并发更新同一文档仍受“每分片单线程写入”模型制约。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Lucene](/docs/CS/Framework/ES/Lucene.md)
- [ES Cluster](/docs/CS/Framework/ES/Cluster.md)
- [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md)

## References

1. [Elastic Docs - Scripting](https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-scripting.html)
2. [Painless scripting language](https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-scripting-painless.html)
3. [Runtime fields](https://www.elastic.co/guide/en/elasticsearch/reference/current/runtime.html)
