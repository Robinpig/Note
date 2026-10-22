## Introduction

本篇讲 Elasticsearch 的数据模型：索引、文档、字段映射（mapping）与写入侧的刷新/事务日志机制。

**版本基线：Elasticsearch 9.5.5**（Lucene 10.5.1）。默认值均标注 `文件:行号`，可回源码反查。

> [!IMPORTANT]
> **先打破三个直觉**：① **`"index": "not_analyzed"` 在 9.x 会直接抛异常**——`index` 是布尔参数，5.x 起就该写 `type: keyword`；② **mapping type 已彻底移除**，没有 `/index/type/id` 这种 URL，`_doc` 是唯一类型名；③ `index.number_of_shards` 默认是 **1** 而不是 5——那个默认 5 是 6.x 以前的旧闻。

事实来源：Elasticsearch 源码 v9.5.5（`elastic/elasticsearch` tag `v9.5.5`）。

## 数据模型层级

```
Elasticsearch 集群
 └─ Index（索引，类似 Database）         ← 主分片数创建后不可变
     └─ Shard（分片，每个是一个独立 Lucene Index）
         └─ Segment（段，不可变）          ← 详见 Lucene 篇
             ├─ 倒排索引（term → docs）
             ├─ Doc Values（列式正排，排序/聚合）
             └─ Stored Fields / _source
```

- 一个集群可有多个 Index；文档以 JSON 序列化存储，每篇文档带 `_index` / `_id` / `_version` / `_seq_no` 等元字段；
- **mapping type 在 9.x 不存在**：所有文档 API 路由都是无类型形式——`RestIndexAction.java:60` 注册 `POST/PUT /{index}/_doc/{id}`，`RestGetAction.java:42` 是 `GET /{index}/_doc/{id}`；合并 mapping 时强制走单一名字 `_doc`（`MapperService.java:102` `SINGLE_MAPPING_NAME = "_doc"`）；
- `_type` 仅作为 5.x 旧索引的 BWC 元数据存在（`LegacyTypeFieldMapper`），不是可用的 mapping 类型。

## text vs keyword

选择字段类型是建模的第一步。5.x 把 `string` 拆成两类后，取舍就只有一道题：**这个字段要不要被分词搜索？**

| 维度 | `text` | `keyword` |
| ---- | ---- | ---- |
| 用途 | 全文搜索 | 精确匹配、排序、聚合、过滤 |
| 分词 | 走 analyzer | 不走（keyword analyzer 原样保留） |
| `index` 默认 | true（`TextFieldMapper.java:338`） | true（标准模式） |
| `doc_values` 默认 | **false**（`TextFieldMapper.java:267-270`） | **true**（`KeywordFieldMapper.java:187-189`） |
| `fielddata` 默认 | false（`TextFieldMapper.java:291`） | 不适用 |
| `eager_global_ordinals` 默认 | false | false |
| `ignore_above` 默认 | — | `Integer.MAX_VALUE`（logsdb 索引 8191，`Mapper.java:177-178`） |
| 索引选项 | DOCS_AND_FREQS_AND_POSITIONS | DOCS（+ SORTED_SET doc values） |

结论性经验：

- 要搜索的长文本用 `text`；要精确相等、`terms` 聚合、排序、`group by` 的用 `keyword`；
- `keyword` 默认开 doc_values，所以聚合排序零配置可用；`text` 想参与排序/聚合要么显式开 `doc_values`，要么用 `.keyword` 多字段；
- `text` 字段的 `fielddata` 默认关闭——它会把倒排结构装进 JVM 堆，是经典的 OOM 源（见 Troubleshooting 篇）。

## 打假：`not_analyzed` 与 `index: false`

网上大量教程（以及本站历史笔记）写过：

```json
{ "spanEvents": { "type": "text", "index": "not_analyzed" } }
```

**在 9.5.5 上这段 mapping 会让建索引直接失败**。证据链：

1. `index` 参数在 9.x 是布尔参数（`FieldMapper.java:1416-1422`）：

```java
public static Parameter<Boolean> indexParam(Function<FieldMapper, Boolean> initializer, boolean defaultValue) {
    return Parameter.boolParam("index", false, initializer, defaultValue);
}
```

2. 布尔解析对非布尔值抛异常（`libs/core/.../Booleans.java:56-64`）：

```java
public static boolean parseBoolean(String value) {
    if (isFalse(value)) { return false; }
    if (isTrue(value)) { return true; }
    throw new IllegalArgumentException("Failed to parse value [" + value + "] as only [true] or [false] are allowed.");
}
```

即 `"not_analyzed"` 会以 `IllegalArgumentException: Failed to parse value [not_analyzed] ...` 被拒。全树仅剩的 `not_analyzed` 字样在 `DynamicTemplate.java:528-536`（动态模板把旧式写法降级为 keyword 的历史兼容分支，注释还写着 "TODO: remove this in 6.0"）和一处高亮注释里。

语义对照（三者完全不同，混用即事故）：

| 写法 | 语义 | 状态 |
| ---- | ---- | ---- |
| `type: text`（默认） | 分词、建倒排、可全文搜索 | 现行 |
| `type: keyword` | 不分词、精确匹配、默认开 doc_values | 现行（5.0 起） |
| `type: text, index: false` | **不建倒排**（`TextParams.java:185-188` → `IndexOptions.NONE`），但仍可存 `_source` / doc_values | 现行 |
| `type: string` | 已移除（7.0 起拆分为 text/keyword） | 死配置 |
| `type: text, index: "not_analyzed"` | 建索引直接抛 `IllegalArgumentException` | 死配置 |

那个把大字段误配成 `text` 导致高并发写入 OOM 的经典案例，正解就是改成 `keyword` 或 `index: false`，而不是加一个语法非法的 `not_analyzed`。

## 动态映射

不预定义 mapping 时，ES 按文档内容推断字段（`DynamicFieldsBuilder.java:326-343`）。9.x 的 `dynamic` 有**四档**（`ObjectMapper.java:97-111`）：

| 值 | 行为 |
| ---- | ---- |
| `true`（默认，`ObjectMapper.java:94`） | 自动添加新字段 |
| `false` | 新字段可存进 `_source` 但不建索引 |
| `strict` | 遇到新字段**拒绝文档** |
| `runtime` | 新字段建成 runtime field（8.x 新增，查询时计算、不落索引结构） |

相关开关默认值（`RootObjectMapper.java`）：

- `numeric_detection`：**false**（`:61`）——字符串里的数字不会被自动转成数值字段；
- `date_detection`：**true**（`:60`）——匹配 `strict_date_optional_time||epoch_millis` 等默认格式的字符串会被推断为 date；
- `index.mapping.dynamic_strings.auto_text`：**true**（`IndexSettings.java:1250-1260`）——动态字符串默认建成 `text` + `.keyword` 子字段（子字段 `ignore_above` 256）。

> [!WARNING]
> 「动态字符串一律变 keyword」不成立：标准模式下动态字符串是 **text + .keyword 多字段**；只有 `dynamic_strings.auto_text=false`（或 COLUMNAR/LOGSDB 模式）时才只建 keyword。这直接影响 `field.raw` / `field.keyword` 聚合是否可用。

## 索引级默认值

全部默认 1 个主分片、1 个副本——「默认 5 主 1 副」是 6.x 以前的旧默认（`IndexMetadata.java:222-240`）：

| 配置项 | 默认值 | 定义处 |
| ---- | ---- | ---- |
| `index.number_of_shards` | **1** | `IndexMetadata.java:222-228` |
| `index.number_of_replicas` | **1** | `IndexMetadata.java:234-240` |
| `index.refresh_interval` | **1s** | `IndexSettings.java:310` |
| `index.max_result_window` | **10000** | `IndexSettings.java:146-152` |
| `index.mapping.total_fields.limit` | 1000 | `MapperService.java:150-157` |
| `index.mapping.depth.limit` | 20 | `MapperService.java:178-184` |
| `index.mapping.nested_fields.limit` | **100**（9.5.0+ 新索引）/ 50（旧索引） | `MapperService.java:105-118` |
| `index.mapping.nested_objects.limit` | 10000 | `MapperService.java:134-140` |
| `index.mapping.nested_parents.limit` | 50（新）/ Integer.MAX_VALUE（旧） | `MapperService.java:119-132` |
| `index.mapping.array_objects.limit` | 50000 | `MapperService.java:142-148` |
| `index.mapping.dimension_fields.limit` | 32768 | `MapperService.java:198-204` |
| `es.index.max_number_of_shards`（单索引分片上限） | 1024 | `IndexMetadata.java:220` |

> [!TIP]
> `nested_fields.limit` 从 50 提到 100 是 9.5.0 的变化（`IndexVersions.java:211` `NESTED_PATH_LIMIT = def(9_050_0_00)`），**只对 9.5.0 之后创建的索引生效**，旧索引保持 50。写「默认 50」的教程在 9.5 上已过时。

## 写入侧：translog 与刷新

写入链路的关键默认值（定义均在 `IndexSettings.java`）：

| 配置项 | 默认值 | 定义处 |
| ---- | ---- | ---- |
| `index.translog.durability` | `request`（每次请求 fsync） | `IndexSettings.java:116-122` |
| `index.translog.sync_interval` | 5s（`async` 模式生效） | `IndexSettings.java:102-108` |
| `index.translog.flush_threshold_size` | 10GB | `IndexSettings.java:375-391` |
| `index.translog.flush_threshold_age` | 1m | `IndexSettings.java:393-406` |

- `durability: request` 是安全默认（每写必刷盘）；换成 `async` 用吞吐换「最多丢 `sync_interval` 窗口」的风险；
- refresh 的实现在 `InternalEngine.refresh()`（`InternalEngine.java:2610-2653`），底层调 Lucene `ReferenceManager.maybeRefreshBlocking()` 把 IndexWriter 缓冲中已成段的数据纳入新 reader——这就是「写入默认 1 秒后可搜」的来源（Lucene 细节见 Lucene 篇）；
- `_refresh` API / `refresh=true` / `refresh=wait_for` 可强制或等待刷新，以写延迟换实时性。

## 索引模板与 Data Stream

- 索引模板（index templates）+ 组件模板（component templates）：把 mapping/settings/别名策略固化，新索引自动命中；data stream 的 backing index 由模板统一管理；
- Data Stream 的保留与滚动由 **DLM**（data stream lifecycle）负责，`_data_stream/{name}/_lifecycle` API；普通索引的 ILM 用 `index.lifecycle.name`。两者 9.x 并存，poll 间隔分别默认 5m / 10m——详见 Troubleshooting 篇。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| `"index": "not_analyzed"` | 抛 `IllegalArgumentException`；用 `type: keyword` 或 `index: false` |
| `/index/type/id` 文档 API | type 已移除，只有 `/{index}/_doc/{id}` |
| `type: string` | 7.0 起移除，拆为 text / keyword |
| 主分片默认 5 | 默认 1（6.x 以前的旧默认） |
| `dynamic` 只有 true/false/strict | 9.x 有四档，`runtime` 是 8.x 新增 |
| 动态字符串一律 keyword | 标准模式是 text + `.keyword` 多字段，由 `dynamic_strings.auto_text`（默认 true）控制 |
| `nested_fields.limit` 默认 50 | 9.5.0+ 新索引默认 100，旧索引才是 50 |
| text 字段默认开 doc_values | 默认 false；keyword 默认 true |
| translog 先写、Lucene 后写 | 相反：**Lucene 先写、translog 后写**（`InternalEngine.java:1310-1325`，详见 Troubleshooting 篇） |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Query DSL：查询两阶段与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Analyzer：分词体系](/docs/CS/Framework/ES/Analyzer.md)
- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)

## References

1. [Elasticsearch Reference - Mapping](https://www.elastic.co/guide/en/elasticsearch/reference/current/mapping.html)
2. [Elasticsearch Reference - Dynamic Mapping](https://www.elastic.co/guide/en/elasticsearch/reference/current/dynamic-mapping.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
