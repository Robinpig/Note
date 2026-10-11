# Full Text Search

## Introduction

向量检索擅长语义相近，但对精确词项匹配有明显盲区：订单号、错误码、产品型号这类 Token 既没有稳定的语义邻近性，也不适合被 embedding 抹平。Milvus 3.0 用两条互补的路径补齐这块能力：一是 tantivy 倒排索引支撑的精确词项谓词，二是把文本处理链 analyzer 提为一等公民——文本字段可经 function 直接生成稀疏向量，让 BM25 评分与向量检索共存于同一次混合查询。

本笔记覆盖：analyzer 的定义、执行与资源管理；倒排实现的三个分支各自解决什么；全文谓词面与执行路径；BM25 function 字段从文本到稀疏向量的链路及文档频率统计的落点；相关配置键的默认值与适用边界。

边界声明：稀疏向量索引的类型矩阵与 AutoIndex 细节归 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)；filter 表达式在 segcore 的总体执行框架归 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)；索引构建任务在 DataNode 上的调度归属归 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)；BM25Stats 随 segment 持久化与加载的完整生命周期归 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)。本篇只写与文本处理、倒排索引、BM25 直接相关的机制。

## Analyzer Architecture

analyzer 的权威实现在 C++ / Rust 侧：`internal/core/thirdparty/tantivy` 下的 tantivy-binding 提供 analyzer 构建与 token 流，C++ 用 `milvus::tantivy::Tokenizer` 包装，再经 `segcore/tokenizer_c.h` 暴露 C 接口。

Go 侧的 `internal/util/analyzer` 只是一层别名包，把 `interfaces` 里的 `Analyzer` / `TokenStream` 接口重新导出；真正干活的是 `internal/util/analyzer/canalyzer`——它用 cgo 持有 `C.CTokenizer` 指针，`NewTokenStream` / `Clone` / `Destroy` 全部转发到 C++。这样设计的原因是 analyzer 定义只能有一份：Proxy 插入路径用 Go 侧 tokenizer 生成稀疏向量，DDL 校验与查询执行用 C++ 侧的同一实现，两侧各写一份必然分叉。

注意 Go 侧的 `ValidateAnalyzer` 并不在本地执行——create collection 时 RootCoord 收集 schema 中所有 `analyzer_params`，经 `ValidateAnalyzer` RPC 转发到某个 QueryNode，在 C++ 侧试建 analyzer 并返回其依赖的文件资源 ID，资源 ID 记入 schema。参数写错在建集时就报错，不会拖到插入或查询。

### Built-in Analyzers

`analyzer_params` 为空或 `{}` 时使用默认 standard，即 tantivy standard tokenizer 加 lowercase filter。内置模板固定：

| type | tokenizer | filter 链 |
| --- | --- | --- |
| standard | standard | lowercase，可选 stop_words |
| english | standard | lowercase、english stemmer、ENGLISH 停用词表 |
| chinese | jieba | cn alphanum only |
| arabic | standard | lowercase、decimal digit、arabic normalization、arabic stemmer、ARABIC 停用词表 |
| thai | thai | lowercase、decimal digit、THAI 停用词表 |

### Custom Analyzer Chains

自定义分析器写成 `tokenizer` 加 `filter` 两段 JSON，或直接给 `type` 引用内置模板。tokenizer 可选 standard、whitespace、jieba、lindera、icu、char_group、thai、language_identifier、grpc。filter 分两类：字符串短写形式有 lowercase、asciifolding、alphanumonly、cncharonly、cnalphanumonly、removepunct、pinyin、decimaldigit、arabic_normalization；对象形式有 length、stop、decompounder、stemmer、regex、synonym、pinyin，可自带参数或引用字典资源。`stop_words` 作为顶层键被所有内置模板消费。

### Resources and Hot Reload

运行时选项经 `function.analyzer.` 前缀直推 C++：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| function.analyzer.local_resource_path | /var/lib/milvus/analyzer | lindera 字典等本地资源目录 |
| function.analyzer.lindera.download_urls.语言 | 空 | lindera 词典下载地址 |
| function.analyzer.concurrency_per_cpu_core | 8 | analyzer 池大小按 CPU 核数乘此值 |
| function.analyzer.runner_concurrency | 8 | 单个 function runner 内 tokenize 的并发度 |

各角色进程启动时调用 `analyzer.InitOptions`：把上述配置序列化为 JSON，经 `set_tokenizer_option` 推入 C++ 的全局选项，并 Watch `function.analyzer.` 前缀，配置变更即热更新进程内 analyzer 选项。

自定义字典 / 停用词文件属于 file resource，节点侧 manager 有 SyncMode 与 RefMode 两种模式：前者同步全量资源并向 C++ 推送 名称到 ID 的全局映射，后者按请求懒下载、带引用计数与 GC。构建路径还会把本次请求用到的资源打包成 extra info，让 C++ 侧按 resource map 把资源名解析为具体文件。

## Inverted Index Trio

三个倒排实现都基于 tantivy，但职责完全不同，先区分再展开：

| 实现 | 与 Tantivy 的关系 | 解决什么 | 谁触发 |
| --- | --- | --- | --- |
| InvertedIndexTantivy | 直接包装 tantivy | 标量比较、范围、前缀、LIKE；BM25 输出字段的稀疏索引是另一条线 | create_index 的 INVERTED |
| TextMatchIndex | 与倒排同族的文本索引实现 | analyzer 处理后的 match / phrase / fuzzy 文本谓词 | `enable_match` 字段在 growing 段建索引，加载时由 loader 重建 |
| NgramInvertedIndex | 继承 InvertedIndexTantivy | ngram 粗筛加速子串、后缀、regex 等标量谓词 | create_index 的 NGRAM |

### InvertedIndexTantivy

通用倒排索引，按字段类型实例化模板，字符串实例对外提供 `PrefixMatch`、`PatternMatch`、正则匹配几条通道：LIKE 模式经 `PatternQuery` 翻译成 tantivy 正则查询，前缀走 prefix 查询。索引自己声明哪些 op 值得走倒排——`ShouldUseOp` 对模式匹配类算子分流：`Match` 与 `PrefixMatch` 依索引能力放行，后缀 / 子串 LIKE 与 regex 明确声明不走倒排索引（短 varchar 上直接扫原始数据更快），其余算子（等值、范围等）默认放行。表达式层就是在决定执行路径时读这份声明，字符串谓词只有在索引认可该 op 时才走 index 路径，否则回落原始数据扫描。

### TextMatchIndex

面向已分词文本的匹配索引，仍然继承 `InvertedIndexTantivy<std::string>`，索引类型对外仍表现为 INVERTED。它有两种生命周期：

- growing 段：内存写，`commit_interval_in_ms` 目前硬编码 200ms，并按需后台合并，允许尚未可见的行短暂多于查询时间戳对应的行数，查询侧会把结果裁剪到 active count。
- sealed 段：三种来源——加载已构建的 index、从原始数据现建、或直接载入 flusher 阶段生成的 text index 产物。

查询接口只有三个：`MatchQuery` 带 `min_should_match`、`PhraseMatchQuery` 带 `slop`、`FuzzyMatchQuery` 带上限编辑距离，分别对应 tantivy-binding 的 match、phrase、fuzzy 查询。sealed 段若字段 `enable_match` 但缺少 text index 统计，segment loader 会把它标为 unindexedTextFields，在加载时从原始数据重建；查询时找不到 text index 直接报 TextIndexNotFound，不会静默回退。

### NgramInvertedIndex

面向标量谓词加速的字符 ngram 倒排，`min_gram` / `max_gram` 必填，只支持 VARCHAR 与 JSON 加 VARCHAR cast。它执行分两段：Phase1 用 ngram 粗筛产生候选位图、与已有过滤结果做 AND 合并；Phase2 回到原始数据对候选逐行复核，保证谓词语义精确。literal 长度小于 `min_gram` 时 `CanHandleLiteral` 拒绝处理，回落普通路径；regex 场景会先从模式中提取"必然出现"的字面量用于粗筛，提不出安全字面量就放弃优化。它优化的是 LIKE / regex 这类标量谓词的执行成本，不承担 analyzer 语义。

## Full Text Predicates

谓词面与执行路径以源码为准：

| 谓词 | 语法要点 | 前置条件 | 执行路径 |
| --- | --- | --- | --- |
| text_match | `text_match(field, "query")`，可选 minimum_should_match | 字段 `enable_match` 为 true | TextMatchIndex.MatchQuery |
| text_match_fuzzy | 必须给 `max_edit_distance`，范围 0 到 2 | 同上 | TextMatchIndex.FuzzyMatchQuery |
| phrase_match | 可选 slop，uint32 范围，默认 0 | 同上 | TextMatchIndex.PhraseMatchQuery |
| LIKE / Match | `like "abc%"` 等模式 | 无，索引存在即可能加速 | 字符串倒排 index 路径或原始扫描 |
| 前缀 | startsWith 语义 | 无 | 同上 |
| regex / 后缀 / 子串 | `=~` 等 | 无 | 默认原始扫描；NGRAM 索引可加速 |

执行路径的选择在 `PhyUnaryRangeFilterExpr::DetermineExecPath`：text match 系列被直接判给 TextIndex 路径，`ExecTextMatch` 通过 `segment_->GetTextIndex` 拿 TextMatchIndex 结果，且不支持带 offset 的迭代过滤——遇到 iterative filter 直接报错而不是降级。ngram 优化发生在普通比较路径内部：先试 `ExecNgramMatch`，超出能力则返回空并转到常规的分支。普通 LIKE 与前缀是否使用标量倒排，取决于索引自身的 op 支持声明，即上一节的 `ShouldUseOp`。

需要强调的一点：analyzer 链只作用于 text_match 系列与 BM25 function。`like` 模式与大小比较不经过 analyzer，匹配的是字段原始值。

## BM25 Function Field

BM25 字段由 function 定义驱动：输入一个文本字段，输出一个稀疏向量字段，函数类型为 BM25。schema 校验要求输入字段 `enable_analyzer` 为 true，输出字段的索引 metric 必须是 BM25；建索引参数里的 `bm25_k1` / `bm25_b` / `bm25_avgdl` 由 `FillFunctionOutputIndexParams` 统一补默认值，Proxy 建索引与 RootCoord 补字段两条路径共用同一逻辑，保证两边产物一致。

写入侧在 Go 完成：`BM25FunctionRunner` 用字段的 analyzer 对文本分词，每个 token 经 `HashString2LessUint32` 哈希后按词频累加成 `map[uint32]float32`，即稀疏向量的每一维是"词项特征值 → 该词在本文档中的词频"。存进 segment 的是纯 TF，不含 IDF。

查询侧分两步：

1. QueryNode delegator 的 IDF oracle 汇总本 shard 内全部相关 segment 的统计——growing 段在内存注册，sealed 段从 segment stats 文件加载——形成全局视图。查询文本先按同一 analyzer 分词得到 TF 向量，随后 `BuildIDF` 把每个词项的值乘以 `log(1 + (N - nq + 0.5) / (nq + 0.5))`，N 是总行数，nq 是包含该词项的行数。
2. 实际打分发生在稀疏向量检索里，metric 为 BM25。查询请求会把 `bm25_avgdl` 填进 QueryInfo，segcore 再连同 `bm25_k1` / `bm25_b` 一起传给 knowhere，由其完成计分。avgdl 来自统计视图的 numToken / numRow，不是建索引时写入的占位值。

由此得到一个与 tantivy 全文路线根本不同的点：**BM25 的文档频率与平均长度统计落在 segment stats 这一侧**，即 `internal/storage` 的 BM25Stats——每段记录行数、总词数与每个 token 命中的行数，由落盘侧在 stats 阶段从输出的稀疏向量逐行累计，随 segment 持久化；tantivy 完全不参与 BM25 的 IDF 计算。检索形态上，BM25 字段与普通稀疏向量同构：同一套稀疏检索与混合查询、rerank 可组合使用，差别只在 metric 与查询向量的 IDF 加权预处理。

`multi_analyzer_params` 是 BM25 的进阶：通过 `by_field` 指定一行内记录分析器名称的字段，加 `analyzers` 映射，让同一文本列按行选用不同 analyzer；它与 `enable_match` 互斥，且不能同时再给 `analyzer_params`。

## Configuration and Parameters

字段级参数：

| 键 | 类型与默认值 | 适用边界 |
| --- | --- | --- |
| enable_analyzer | bool，默认 false | 打开后字段才接 analyzer；text_match 与 BM25 输入字段强制要求 |
| analyzer_params | JSON 字符串，空等价 standard | `enable_analyzer` 为 false 时被忽略 |
| enable_match | bool，默认 false | 仅 VARCHAR；为 true 必须 enable_analyzer；字段 text 索引在 growing 段构建、加载时重建 |
| multi_analyzer_params | JSON 字符串，无默认 | 仅 BM25；与 enable_match 互斥 |

索引级参数：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| min_gram / max_gram | 无，NGRAM 必填 | 正整数且 min 不大于 max；仅 VARCHAR 或 JSON cast VARCHAR |
| bm25_k1 | 1.2 | BM25 function 输出字段的建索引参数 |
| bm25_b | 0.75 | 同上 |
| bm25_avgdl | 100 | 建索引占位；检索时被 IDF oracle 的真实统计覆盖 |

标量索引类型在文本语境下的选择依据：

| 索引类型 | 适用字段 | 与文本检索的关系 |
| --- | --- | --- |
| INVERTED | 数值、字符串标量、JSON 路径 | 标量谓词与 LIKE / 前缀；text index 的类型底座 |
| NGRAM | VARCHAR、JSON cast VARCHAR | 子串 / 后缀 / regex 粗筛，两阶段复核 |
| TRIE | 仅 varchar | 主键与前缀、字典序查询 |
| BITMAP | 低基数标量 | 常规过滤，与文本无关 |
| STL_SORT | 数值 / varchar / timestamptz | 范围查询，与文本无关 |
| HYBRID | BITMAP 与 INVERTED 组合 | 按列的过滤画像选择 |

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Tantivy](https://github.com/quickwit-oss/tantivy)
- [Milvus InvertedIndexTantivy.h](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/core/src/index/InvertedIndexTantivy.h)
- [Milvus bm25_function.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/util/function/bm25_function.go)
- [Milvus 3.0 Release Blog](https://zilliz.com.cn/blog/milvus-3-0-release)
- [Lucene BM25Similarity](https://lucene.apache.org/core/9_11_0/core/org/apache/lucene/search/similarities/BM25Similarity.html)
