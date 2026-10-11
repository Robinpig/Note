## Introduction

Milvus 不自己实现 ANN 算法。IVF 的聚类中心、HNSW 的图层、Vamana 图、PQ 与 RaBitQ 码本全部在 **Knowhere** 里；`internal/core/src/index/` 这层 C++ 代码的职责是把「某个 segment 的某一列」翻译成 Knowhere 能吃的 dataset 与 config，再把 Knowhere 的产物翻译成对象存储上的索引文件、内存/磁盘预算与检索接口。所以读这一层的重点不是算法，而是**边界**：谁能建哪些索引、参数在哪个进程被校验、加载要花多少内存由谁算。

v3.0.1 有两个容易踩错的结构性事实。其一，**向量索引类型的权威清单不在 Milvus 源码里**：`internal/util/vecindexmgr` 在启动时经 cgo 调 `knowhere::IndexFactory::Instance().GetIndexFeatures()` 拉取一张「索引名 → 特性位」表，Go 里所有 `hnsw_checker.go` / `ivf_pq_checker.go` 之类的逐类型校验器都已消失，只剩同名测试文件，向量索引统一走 `vecIndexChecker`，参数合法性由 `C.ValidateIndexParams` 交给 Knowhere 判定。其二，**标量索引是另一套实现**，完全不经 Knowhere：C++ 侧由 `IndexFactory` 分派到 `ScalarIndexSort` / `StringIndexMarisa` / `BitmapIndex` / `InvertedIndexTantivy` / `HybridScalarIndex` / `NgramInvertedIndex` / `RTreeIndexWrapper`，其中倒排与全文落在 Rust 的 tantivy 绑定上。

本篇的边界：索引构建任务的调度与执行者归属（DataCoord 下发、DataNode 本地执行）见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md) 与 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)；segcore 的检索执行、cgo 边界与双态 segment 见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)；索引文件在对象存储里怎么摆见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)。HNSW / IVF / PQ 的算法原理见 [vector](/docs/CS/DB/vector.md)，向量召回的工程语境见 [Recall](/docs/CS/RecommenderSystem/Recall.md)，本篇不重讲。末尾的能力矩阵与竞品定位是这一篇存在的另一半理由：索引面广不等于适合你。

## Knowhere Position and Call Path

| 事实 | v3.0.1 取值 | 锚点 |
| :-- | :-- | :-- |
| 仓库 | `github.com/zilliztech/knowhere` | `internal/core/thirdparty/knowhere/CMakeLists.txt` |
| 版本 | `KNOWHERE_VERSION = v3.0.11`，FetchContent 从源码编译 | 同上 |
| 磁盘索引开关 | `BUILD_DISK_ANN` → `WITH_DISKANN` | 同上 |
| GPU 开关 | `MILVUS_GPU_VERSION` → `WITH_CUVS`（RAFT/RMM） | 同上 |
| Intel SVS | `-DWITH_SVS=ON`（`scripts/core_build.sh -S`），默认 OFF | 同上 |
| 可替换引擎 | `INDEX_ENGINE`，默认 `KNOWHERE`；`cardinal` → `WITH_CARDINAL` | `scripts/core_build.sh` |

**构建路径**：Proxy 校验并补齐参数 → DataCoord 生成任务 → DataNode 经 `internal/util/indexcgowrapper.CreateIndex` 进入 `indexbuilder/index_c.cpp` 的 `CreateIndex` → `IndexFactory::CreateIndex` 按 `IsVectorDataType` 分成 `VectorMemIndex` 或 `VectorDiskAnnIndex<T>` → `knowhere::Index::Build(dataset, config, use_knowhere_build_pool)` → `Serialize` / `Upload` 写成索引文件。标量走同一入口的 `ScalarIndexCreator`，`BuildTextIndex` / `BuildJsonKeyIndex` 另有两个专用 cgo 入口。

**加载与检索路径**：QueryNode 的 segment loader 构造 `LoadIndexInfo` 并调 `C.EstimateLoadIndexResource` 做准入判定，真正把索引读进来是 `VectorMemIndex::DeserializeFromFile` / `VectorDiskAnnIndex` 的对应实现；检索期 `VectorIndex::Query(dataset, search_info, bitset, ...)` 内部调 `knowhere::Index::Search` / `RangeSearch` / `AnnIterator`。**标量过滤结果以 bitset 形式传进 Knowhere**，由索引内部完成过滤，而不是先取 topk 再后过滤；执行计划层面的 `FilterBitsNode` 与 `IterativeFilterNode` 之争归 Query_Path。

参数校验的错误也在这一层归一化：Knowhere 把用户参数错误报成 `ConfigInvalid`（2006），`vecIndexChecker.HandleCStatus` 在 cgo 边界把它翻译成 Milvus 对外的 `ParameterInvalid`（1100），其余按 segcore 错误分类。

## Vector Index Registry and Feature Bits

`vecindexmgr` 的特性位定义了一张索引 × 能力的位掩码，`IsDataTypeSupport` 要求「该位全部命中」才算支持：

| 位 | 名称 | 语义 |
| :-- | :-- | :-- |
| 0-5 | `BinaryFlag` `Float32Flag` `Float16Flag` `BFloat16Flag` `SparseFloat32Flag` `Int8Flag` | 支持的向量数据类型 |
| 15 | `EmbeddingListFlag` | 能否作为 `ArrayOfVector` 字段的索引 |
| 16 | `NOTrainFlag` | 无需训练，暴力结构（FLAT / BIN_FLAT） |
| 17 | `KNNFlag` | 精确 KNN，召回 100% |
| 18 | `GpuFlag` | 需要 GPU |
| 19 | `MmapFlag` | 索引主体可 mmap |
| 20 | `MvFlag` | 支持物化视图加速过滤检索 |
| 21 | `DiskFlag` | 需要本地盘 |

⚠️ 两个前提偏差值得记下：**没有「多向量字段」位**——一个集合多个向量字段是 schema 层限制（`proxy.maxVectorFieldNum` 默认 10，`enableMultipleVectorFields` 恒为 true，多字段时检索必须显式给 `anns_field`），与索引类型无关；位掩码里的 `MvFlag` 是 materialized view，不是 multi-vector。另外 `IsDiskANN` / `IsAISAQ` 是**硬编码字符串比较**（只认 `DISKANN`、`AISAQ`），新增磁盘索引不会自动被这两处资源估算分支接住。

`internal/util/vecindexmgr/vector_index_mgr_test.go` 把运行时位钉成了断言，可当作 v3.0.1 的最小可信矩阵：

| 索引 | Float32 | Float16 | BFloat16 | Binary | Sparse | 需训练 | 磁盘 | 物化视图 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| FLAT | ✅ | ✅ | ✅ | ❌ | ❌ | 否 | ❌ | ❌ |
| BIN_FLAT | ❌ | ❌ | ❌ | ✅ | ❌ | 否 | ❌ | ❌ |
| IVF_FLAT | ✅ | ✅ | ✅ | ❌ | ❌ | 是 | ❌ | ❌ |
| IVF_PQ | ✅ | ✅ | ✅ | ❌ | ❌ | 是 | ❌ | ❌ |
| HNSW | ✅ | ✅ | ✅ | ✅ | ❌ | 是 | ❌ | ✅ |
| DISKANN | ✅ | ✅ | ✅ | ❌ | ❌ | 是 | ✅ | ❌ |

Int8 向量在 python 用例里只对 `HNSW`（`int8_vector_index = ["HNSW"]`），但 C++ 磁盘索引分支同样为 `VECTOR_INT8` 实例化，最终仍以 Knowhere 位为准。

## Dense Vector Index Types

清单来自 `indexparamcheck` / `vecindexmgr` 测试、`tests/python_client/common/common_type.py`、`configs/milvus.yaml` 与 C++ 分派分支的并集；Knowhere 运行时清单可能更宽。

| 索引 | 结构族 | 构建参数 | 检索参数 | 取舍 |
| :-- | :-- | :-- | :-- | :-- |
| FLAT | 暴力 | 仅 `dim` | 无 | 精确、小数据量、召回基线 |
| IVF_FLAT | 倒排 + 原始向量 | `nlist` | `nprobe` | 构建最省、内存中等 |
| IVF_SQ8 | 倒排 + 标量量化 | `nlist` | `nprobe` | 1/4 内存，精度略降 |
| IVF_PQ | 倒排 + 乘积量化 | `nlist` `m` `nbits` 1-16 默认 8 | `nprobe` | 内存最省，召回最难拉 |
| IVF_RABITQ | 倒排 + RaBitQ | `nlist` `refine` `refine_type` 如 `SQ8` | `nprobe` `rbq_bits_query` `refine_k` | 量化 + 重排换召回 |
| HNSW | 近邻图 | `M` 1-2048 `efConstruction` | `ef` | 延迟最优，全内存 |
| HNSW_SQ / HNSW_PQ / HNSW_PRQ | 图 + 量化 | `M` `efConstruction` `sq_type` 如 `SQ8` `SQ4U` | `ef` | 图的速度 + 量化省内存；AutoIndex 默认走 `HNSW_SQ` 并用 `refine`/`refine_type` 补精度 |
| SCANN | 各向异性量化 + 重排 | `nlist` | `nprobe` `reorder_k` | 高维 fp32 常用，重排开销可控 |
| DISKANN | Vamana 图 + 磁盘 | `max_degree` `pq_code_budget_gb_ratio` `search_cache_budget_gb_ratio` `search_list_size` | `search_list` `beam_width_ratio` | 内存只放 PQ 码与缓存，省内存吃本地 NVMe |
| AISAQ | 磁盘图 + 量化 | `max_degree` `pq_code_budget_gb_ratio` `search_list_size` | `search_list` `beam_width_ratio` | 同为磁盘型，Go 侧按 `IndexSize/64` 估内存（DISKANN 是 `/4`） |
| MINHASH_LSH | LSH 分带 | `mh_lsh_band` `mh_element_bit_width` | 检索期由 `BruteForceIndexParams` 带同名参数 | 近似去重，配 `MHJACCARD` 与 MinHash function |
| GPU_IVF_FLAT / GPU_IVF_PQ / GPU_CAGRA / GPU_BRUTE_FORCE | cuVS / RAFT | CAGRA: `intermediate_graph_degree` `graph_degree` `build_algo` ∈ `IVF_PQ` \| `NN_DESCENT`；`cache_dataset_on_device` | `search_list` 等 | 吞吐最高；`GPU_CUVS_*` 是新名，两套并存；`adapt_for_cpu=true` 可让段加载不再要求 GPU |

**growing 段的 interim index 不在这张表里**：稠密向量默认 `IVF_FLAT_CC`（可选 `SCANN_DVR`），稀疏用 `SPARSE_INVERTED_INDEX_CC` / `SPARSE_WAND_CC`，由 segcore 的 `IndexConfigGenerator` 生成，见 Query_Path；`queryNode.segcore.interimIndex.enableIndex` 三处不一致：随包 yaml 为 `true`、代码 `DefaultValue` 为 `false`、Doc 写 "This defaults to true"——常规部署加载随包 yaml，实际生效为开启；裸装无 yaml 时才落回代码默认的关闭。

## Sparse Binary and Embedding List Indexes

- **稀疏向量**：`SPARSE_INVERTED_INDEX`、`SPARSE_WAND`，构建期 `drop_ratio_build`、检索期 `drop_ratio_search` 丢低权重项换速度与内存。算法实现由 `inverted_index_algo` 选择，合法值 `TAAT_NAIVE` `DAAT_WAND` `DAAT_MAXSCORE` `BLOCK_MAX_MAXSCORE` `BLOCK_MAX_WAND` `SINDI`。这个枚举校验**在 Go 侧**做——注释写明 Knowhere 已移除该校验，属于「校验责任回流」的例子。度量只允许 `IP` 与 `BM25`，而 `BM25` 只允许出现在 BM25 function 的输出字段上。
- **二进制向量**：`BIN_FLAT`、`BIN_IVF_FLAT`（度量 `HAMMING` `JACCARD` `SUBSTRUCTURE` `SUPERSTRUCTURE` `MHJACCARD`），以及唯一同时吃二进制稠密索引 `HNSW`。`MHJACCARD` 是去重度量的特殊通道，会把 AutoIndex 解析到 `MINHASH_LSH`。
- **EmbeddingList / StructArray**：`DataType_ArrayOfVector` 字段用 `MAX_SIM*` 度量走 MaxSim（ColBERT 式 late interaction）；不带 MaxSim 的 `COSINE`/`L2`/`IP` 则把数组内每个向量当独立向量建普通索引，此时索引能力按 `element_type` 判定。可建类型（v3.0.1 用例覆盖）：`HNSW` `HNSW_SQ` `HNSW_PQ` `HNSW_PRQ` `IVF_FLAT` `IVF_FLAT_CC` `DISKANN`。另有 `emb_list_strategy` ∈ `tokenann` | `muvera` | `lemur`（后者带 `muvera_num_projections`、`lemur_hidden_dim` 等训练参数）与检索期 `retrieval_ann_ratio`、`emb_list_rerank` 做段内再精排。

## Metrics and Defaults

| 向量类型 | 合法度量 | 未指定时的默认 |
| :-- | :-- | :-- |
| Float32 / Float16 / BFloat16 / Int8 | `L2` `IP` `COSINE` | `COSINE` |
| SparseFloatVector | `IP` `BM25` | `IP` |
| BinaryVector | `HAMMING` `JACCARD` `SUBSTRUCTURE` `SUPERSTRUCTURE` `MHJACCARD` | `HAMMING` |
| ArrayOfVector | 元素类型的度量 + `MAX_SIM` `MAX_SIM_COSINE` `MAX_SIM_L2` `MAX_SIM_IP` `MAX_SIM_HAMMING` `MAX_SIM_JACCARD` | 按元素类型 |

`constraints.go` 仍保留 `HnswMetrics` `BinIvfMetrics` `RaftMetrics` `MaxNList` 等旧逐类型常量，但 v3.0.1 的向量路径只在 `StaticCheck` 里按**数据类型**查度量白名单，其余（含参数取值范围）交给 Knowhere，别把这些常量当成生效的门禁。默认度量由 `SetDefaultMetricTypeIfNotExist` 注入。

## Scalar Index Types

`conf_adapter_mgr.go` 注册的标量 checker 与 C++ 实现类对应如下。`IsScalarIndexType` 只覆盖 `STL_SORT` `TRIE` `Trie` `BITMAP` `HYBRID` `INVERTED`，**不含 `NGRAM` 与 `RTREE`**，判断「是否标量索引」时别依赖这个函数。

| 索引 | C++ 实现 | 适合谓词 | 可建字段 | mmap |
| :-- | :-- | :-- | :-- | :-- |
| STL_SORT | `ScalarIndexSort` / `StringIndexSort` | 范围 `>` `>=` `<` `<=` `==`、`in`、`json_path` 投影 | 数值 / VARCHAR / TIMESTAMPTZ | ❌ 不在白名单 |
| TRIE / Trie / marisa-trie | `StringIndexMarisa` | 等值 + 前缀 | 仅 VARCHAR | ✅ 但只认拼写 `Trie` |
| BITMAP | `BitmapIndex<T>`（Roaring） | 低基数等值、`in`、`!=`、JSON `bool`/`varchar` | 标量与 ARRAY 元素 | ✅ 且唯一支持 `indexoffsetcache.enabled` |
| INVERTED | `InvertedIndexTantivy<T>` | 等值、范围、ARRAY 元素、JSON 路径、前缀 | 数值 / bool / VARCHAR / TEXT / ARRAY / JSON | ✅ |
| HYBRID | `HybridScalarIndex<T>` | 自动在低/高基数间选 | 同上 | ✅ |
| NGRAM | `NgramInvertedIndex` | `LIKE '%x%'`、前缀、正则字面量抽取 | 仅 VARCHAR / JSON 且 `json_cast_type=VARCHAR`；`min_gram` `max_gram` 必填 | ✅ |
| RTREE | `RTreeIndexWrapper` + GEOS | `st_contains` `st_within` `st_intersects` `st_dwithin` `st_equals` `st_touches` `st_crosses` `st_isvalid` | 仅 GEOMETRY | ❌ |

两个反直觉点：**HYBRID 不是「BITMAP + INVERTED 叠加」**（`index_type.go` 的注释已过时）。它在建索引时扫一遍去重值，数量 ≥ `bitmap_cardinality_limit`（`scalarAutoIndex.params.bitmapCardinalityLimit` 默认 100，上限 1000）就用高基数类型，否则用低基数类型；两者分别取自 `dataCoord.index.hybridIndex.{lowCardinalityIndexType,highCardinalityIndexType}`，默认 `BITMAP` 与 `STL_SORT`（旧数据无这两个键时按类型回退：字符串 INVERTED、整型 STLSORT）。选中的内部类型写进索引文件，加载时 `ResolveHybridInternalIndexType` 读回来——所以 HYBRID 的真实形态是**每段可能不同**。**INVERTED 不接所有 LIKE**：`ShouldUseOp` 对模式匹配类算子分流——`Match` / `PrefixMatch` 依索引能力放行，`RegexMatch` / `PostfixMatch` / `InnerMatch` 明确返回假走原始数据扫描（短 varchar 上倒排反而更慢），其余算子默认放行。

标量索引另有版本轴：`CurrentScalarIndexEngineVersion = 3`、`Maximum = 4`，JSON 路径多类型（v4）与嵌套 HYBRID-STL_SORT（v4）按版本门控；`ClampScalarIndexVersion` 会把请求钳到上限。全文/倒排的 tantivy 格式版本 `TANTIVY_INDEX_LATEST_VERSION = 7`。全文谓词与 analyzer 链是独立的一层机制，见 [Full Text Search](/docs/CS/DB/Milvus/Full_Text_Search.md)。

## JSON Dynamic Schema and Function Output Fields

**JSON 索引 = 一条投影路径上的标量索引**。建索引时给 `json_path` + `json_cast_type`（可选 `json_cast_function`），`CreateJsonIndex` 按 cast 类型包一个对应的标量索引：STL_SORT ∈ `DOUBLE|VARCHAR`，BITMAP ∈ `BOOL|VARCHAR`，HYBRID ∈ `BOOL|DOUBLE|VARCHAR`，INVERTED ∈ `BOOL|DOUBLE|VARCHAR|ARRAY_*|JSON`，NGRAM 强制 `VARCHAR`；`json_cast_function=STRING_TO_DOUBLE` 只能配 `cast_type=DOUBLE`。`json_cast_type=JSON`（整棵子树）只有倒排实现，AUTOINDEX 会把 HYBRID 改写为 INVERTED，走 `JsonFlatIndex`。动态字段（`dynamicfield.enabled`）就落在 `$meta` 这个 JSON 列上，`create_index` 时若未显式给 `json_path`，Proxy 会用字段名自动补。⚠️ JSON/ARRAY/`VECTOR_ARRAY` 的索引**永远不能替代原始列**（`CanUseIndexRawDataForField` 对这三类恒 false），别指望靠索引省掉向量/JSON 原始数据的内存。

除显式索引外还有两条自动路径：`BuildJsonKeyIndex` 产出 **JSON key stats**（`json_stats/` 或 V3 的 `_stats/json_stats.{fieldID}`，写进 segment manifest），以及 **skip index**（从 Parquet statistics 生成 chunk 级 min/max，`CanSkipUnaryRange` / `CanSkipBinaryRange` 用来整块跳过过滤扫描）。

**全文检索**由字段 type_params 打开：`enable_match` 决定是否为该字符串字段自动建全文索引，`enable_analyzer` + `analyzer_params` 决定分词（BM25 function 的输入字段强制要求 `enable_analyzer`）。sealed 段的全文索引**不是用户 create_index 的结果**，而是 stats 子任务 `StatsSubJob_TextIndexJob` 遍历 `enable_match` 字段、复用 `indexcgowrapper.CreateIndex` 并注入 `index_type=INVERTED` + `is_text_match=true` 建成 `TextMatchIndex`（tantivy + 名为 `milvus_tokenizer` 的回调分词器）；growing 段由 segcore 现建（`BuildTextIndexForMeta`）。谓词三个：`text_match`、`phrase_match`（slop 由 Proxy RPC `ComputePhraseMatchSlop` 计算）、`text_match_fuzzy`（`max_edit_distance` 限 0-2）。分析器在 Rust 侧（`tantivy-binding/src/analyzer`）：内置 `standard` `chinese` `english` `arabic` `thai`，tokenizer 有 `standard` `whitespace` `jieba` `lindera` `char_group` `icu` `thai` `language_identifier` `grpc`，filter 覆盖停用词、词干、拼音、同义词、去标点、数字归一、德 compound 等；`multi_analyzer_params`（`by_field` + `analyzers` + alias）支持一行文本按字段值选不同分析器；词典、同义词表等外部文件走 file resource 机制下发（`analyzer_extra_info`）。

**function 字段**是索引层的上游生产者。`FunctionType` 有 `BM25` `TextEmbedding` `Rerank` `MinHash`：BM25 输入单个 VARCHAR/TEXT、输出必须 `SparseFloatVector`，索引参数被强制补 `bm25_k1=1.2` `bm25_b=0.75` `bm25_avgdl=100`（Knowhere 建 BM25 索引必需）且度量强制 `BM25`；MinHash 输出必须 `BinaryVector`，AutoIndex 会选到 `MINHASH_LSH`；TextEmbedding 把文本推到模型 provider（`openai` `cohere` `huggingface` `tei` `gemini` `vertexai` `bedrock` `siliconflow` `voyageai` `ali` `zilliz` 等）。要点是**这些派生向量在数据进入 segment 前就算好了**——`FunctionRunnerLocalStore.FillEmbeddingData` 挂在落盘流水线与 QueryNode growing 流水线，compaction 时由 `record_materializer` 重算，不是在建索引时算。检索期的 `Rerank` / function chain 支持 `rrf` `weighted` `decay` `model` 四类 reranker，与 merge/sort/filter/group_by/limit 算子，执行位置在 Proxy，见 Query_Path。

## AutoIndex

`AUTOINDEX` 的 checker 是彻底的空实现（`AUTOINDEXChecker` 两个方法直接 `return nil`），真实策略是 **Proxy 里的一张服务端配置查表**，不是 Knowhere 的自动调参：

| 场景 | 默认策略 | 配置键 |
| :-- | :-- | :-- |
| 稠密 float 向量 | `HNSW_SQ` `M=18` `efConstruction=240` `sq_type=SQ4U` `refine=true` `refine_type=FP16` `COSINE` | `autoIndex.params.build`（CUDA 构建的发行版编译期换成 `GPU_CAGRA`） |
| 大 topK 模式 | `IVF_SQ8` `nlist=128` | `autoIndex.params.largeTopK.build`，需 `autoIndex.enable` 且集合属性 `queryMode=large_topk` |
| 稀疏向量 | `SPARSE_INVERTED_INDEX` `IP` | `autoIndex.params.sparse.build` |
| 二进制向量 | `BIN_IVF_FLAT` `nlist=1024` `HAMMING` | `autoIndex.params.binary.build` |
| Int8 向量 | `HNSW` `M=18` `efConstruction=240` `COSINE` | `autoIndex.params.int8.build` |
| 去重 | `MINHASH_LSH` `MHJACCARD` | `autoIndex.params.deduplicate.build`，云端受 `.enable` 门控 |
| 标量 | int/varchar/float/json → `HYBRID`，bool → `BITMAP`，geometry → `RTREE`，timestamptz → `STL_SORT` | `scalarAutoIndex.params.build`（`scalarAutoIndex.enable` 默认 false） |

行为约束值得记全：用 `AUTOINDEX` 时**除 `metric_type` 外不许传任何参数**（否则报 "only metric type can be passed when use AutoIndex"），用户显式给的度量优先于配置；`autoIndex.enable=true`（面向云实例）会**覆盖用户显式指定的 index_type**；对 fp16/bf16 向量，`refine_type` 会被 `AdjustAutoIndexParamsByDataType` 自动纠正成 `FP16`/`BF16`（`sq8` 之类不动）；AutoIndex 模式下向量字段不允许写 `mmap.enabled`。真正"自适应"的只有两处：标量 HYBRID 按基数选类型，以及 growing 段的 interim index 按段生成——检索侧的自适应要靠下面两个 3.0 新开关。

参数注入还有第三层：`knowhere.enable`（默认 true）会把 `configs/milvus.yaml` 里 `knowhere.<TYPE>.build.*` 并进建索引参数（Proxy create_index、DataCoord、RootCoord 三处，`override_index_type` 还能借用另一类型的参数并改写 index_type），load 阶段由 `AppendPrepareLoadParams` 处理 `knowhere.<TYPE>.load.*`，建索引前 DataNode 还会 `MergeResourceParams` 注入 `build_dram_budget_gb`（本机空闲内存）与 `vec_field_size_gb`。⚠️ 但 `SearchStage` 常量在 v3.0.1 **没有任何生产调用点**——YAML 里的 `knowhere.DISKANN.search.beam_width_ratio: 4` 不会被自动并入检索请求，检索期参数只能由请求里的 `search_params` 透传。「配置项存在 ≠ 生效」在这一层同样成立。

## Search Parameters and Resource Budget

检索期参数逐次请求传给 Knowhere：IVF 系 `nprobe`、HNSW 系 `ef`、DISKANN/AISAQ `search_list`、SCANN `reorder_k`、IVF_RABITQ `rbq_bits_query` + `refine_k`、稀疏 `drop_ratio_search`，加上与索引无关的 `radius` / `range_filter`（范围检索）与 `iterative_filter`（先过滤后检索的执行策略）。方向上是一致的：调大候选集 → 召回升、延迟升，量化索引还得靠 `refine` 用原始或高精度表示重排把召回找回来。内存维度上，IVF+量化与磁盘图最省（HNSW 是全内存的代表），磁盘型省内存的代价是本地 NVMe 与并发 IO——`beam_width_ratio` 控的正是「每次搜索的 IO 请求数 / CPU 数」。

三个 3.0 新增的自适应检索开关默认全关，都在 `autoIndex.*` 名下：`autoIndex.twoStageSearch.{enabled,minTopk=2000,minNumSegments=5}` 先只跑过滤拿到真实选择率，再据此优化向量检索参数；`autoIndex.globalRefine.{enabled,minDimThreshold=256,searchTopkRatio,refineTopkRatio}` 段内多取一批后截断并重算精确距离；`common.materializedView.enabled` 默认 **true**，建索引时把分区键列作为 optional field 一起喂给 Knowhere（仅稠密 float/binary 且索引带 `MvFlag`，v3.0.1 断言里是 HNSW），检索期再把「命中值数、是否纯 AND、是否含 NOT」作为 `MaterializedViewSearchInfo` 传下去；开启 partition key isolation 时 hints 会被置 `disable`。

加载准入由 C++ 算：`IndexFactory::VecIndexLoadResource` 调 Knowhere 的 `EstimateLoadResource`，返回 `final_/max_{memory,disk}_cost`。规则里能读出设计意图——非 mmap 且非磁盘索引 `max_memory_cost = 2 × memoryCost`（预留一倍峰值），磁盘型或 mmap 索引内存只按 `max(memoryCost, 下载缓冲)`、磁盘按实际大小，DISKANN/AISAQ 再叠加 id-map 的 mmap 磁盘开销，`has_raw_data` 决定是否还得留原始向量列。Go 侧 `index_attr_cache.go` 保留粗粒度回退：DISKANN 内存 `IndexSize/4`、AISAQ `IndexSize/64`、标量 INVERTED 记 0 内存并把 binlog 计入磁盘（`IsLoadWithDisk` 对 INVERTED 恒真）。

mmap 与预热是同一层的第二组开关：进程级 `queryNode.mmap.{vectorField,scalarField,vectorIndex,scalarIndex}`（仅 `vectorField` 默认 true，旧的 `queryNode.mmap.mmapEnabled` 已废弃且会强制拉齐四项），索引级 `mmap.enabled` 需命中 `MmapFlag` 或标量 mmap 白名单，`queryNode.mmap.populate` 控制 `MAP_POPULATE`；预热策略 `disable|sync|async` 可按字段 `warmup` 或集合级 `warmup.{vectorField,vectorIndex,scalarField,scalarIndex}` 设置，落到 `queryNode.segcore.tieredStorage.warmup.*`（`vectorIndex` 默认 `sync`、`vectorField` 默认 `disable`），同组还有 eviction 水位与 `loadingResourceFactor` 等。mmap 的操作系统侧机制见 [mmap](/docs/CS/OS/Linux/mm/mmap.md)。

## Capability Matrix

索引与检索面（本篇逐条核实）：

| 能力 | 落点 |
| :-- | :-- |
| 多向量字段 | ≤ `proxy.maxVectorFieldNum`(10)，检索须指定 `anns_field` |
| 多数据类型向量 | fp32/fp16/bf16/int8/binary/sparse + `ArrayOfVector`(MaxSim) |
| 索引广度 | 内存图/IVF/量化/磁盘图/GPU/LSH/稀疏倒排，见上表 |
| 标量过滤与谓词 | 范围、等值、ARRAY 元素、JSON 路径、LIKE、全文、GIS |
| 混合检索 | 服务端 BM25 稀疏 + 稠密 + rerank（rrf/weighted/decay/model）+ function chain |
| 流式可见性 | 无索引 growing 段靠 interim index，写路径见 Write_Path |
| 成本控制 | mmap、磁盘索引、tiered storage warmup、量化 + refine |
| 近似去重 | MinHash function + `MINHASH_LSH` + `MHJACCARD` |
| 自动策略 | AutoIndex 查表 + 标量 HYBRID 按基数 + two-stage / global refine |

平台面能力（副本、一致性等级、WAL 流式、CDC、Database/Resource Group/RBAC、配额）不在本篇核实范围，归属见 [Milvus](/docs/CS/DB/Milvus/Milvus.md) 与 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。

## Competitor Positioning

| 维度 | Milvus 3.0 | pgvector | Qdrant | Weaviate | Elasticsearch | Pinecone | Faiss |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 形态 | 分布式、存算分离 + standalone/Lite | PostgreSQL 扩展，单机 | Rust，单机为主、可集群 | Go，单机为主、可集群 | 分布式搜索集群 | 闭源托管 serverless | C++ 库，不是数据库 |
| 索引广度 | **最全**：内存/磁盘/量化/GPU/稀疏/LSH/全文/JSON/GIS | IVFFlat + HNSW | HNSW 为主 + 量化与 payload 索引 | HNSW + 动态索引 | Lucene HNSW + BM25 一体 | 托管内建 | IVF/PQ/HNSW 等算法集 |
| 过滤能力 | 标量索引 + bitset 下推进索引 + 物化视图 | SQL 谓词即过滤（无专用索引生态） | payload 过滤是招牌 | 属性过滤 + 模块化 | 查询 DSL 最成熟 | metadata filter | 无（要自己写过滤） |
| 一致性与事务 | 四级一致性 + 单 VChannel 事务，无跨 shard 事务 | 强，ACID 完整 | 弱一致为主 | 最终一致 | 最终一致 | 托管语义 | 无 |
| 多租户与安全 | Database / RG / RBAC / TLS | 复用 PG 角色体系 | API key / 集合级 | 租户 + RBAC | 空间 + RBAC 成熟 | 项目/命名空间 | 无 |
| 运维成本 | **高**：MixCoord + DataNode + QueryNode + StreamingNode + Proxy + etcd + 对象存储 + WAL | 低（已在 PG 里） | 低 | 中 | 中-高（团队通常已有） | 极低 | 不适用 |
| 合适场景 | 亿级以上、需要湖仓与流式、要索引可选面 | 已有 PG、量级千万以下、要强一致 | 单机高性能、边缘 | 多模态模块化 | 全文 + 向量一体、已有 ES | 不想运维 | 自研引擎的算法底座 |

Milvus 的取舍很直白：它是唯一「开源 + 存算分离 + 水平伸缩 + 索引类型面覆盖到磁盘/GPU/LSH」的组合，代价是外部依赖三件套和参数面广。小数据量上这套架构是纯亏——同样的召回用 pgvector 或单机 Qdrant 就能拿到，而 Milvus 的调优收益（mmap、compaction、索引参数、tiered storage）要量级大到一定程度才回本；托管体验不如 Pinecone，OLTP 语义不如 Postgres。真正该先看的是本篇那张能力矩阵：需要 GPU、需要磁盘索引压成本、需要 GIS 或 JSON 路径索引、需要 MinHash 去重，这几条里命中越多，Milvus 的复杂度越值。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [vector](/docs/CS/DB/vector.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)

## References

- [Knowhere](https://github.com/zilliztech/knowhere)
- [Knowhere v3.0.11](https://github.com/zilliztech/knowhere/tree/v3.0.11)
- [Faiss](https://github.com/facebookresearch/faiss)
- [DiskANN](https://github.com/microsoft/DiskANN)
- [Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs](https://arxiv.org/abs/1603.09320)
- [Accelerating Large-Scale Inference with Anisotropic Vector Quantization](https://arxiv.org/abs/1908.10396)
- [RaBitQ: Quantizing High-Dimensional Vectors with a Theoretical Error Bound](https://arxiv.org/abs/2405.12497)
- [ScaNN](https://github.com/google-research/google-research/tree/master/scann)
- [Tantivy](https://github.com/quickwit-oss/tantivy)
- [CRoaring](https://github.com/RoaringBitmap/CRoaring)
- [marisa-trie](https://github.com/s-yata/marisa-trie)
- [cuVS](https://github.com/rapidsai/cuvs)
- [GEOS](https://libgeos.org/)
- [jieba](https://github.com/fxsjy/jieba)
- [pgvector](https://github.com/pgvector/pgvector)
- [Qdrant indexing](https://qdrant.tech/documentation/concepts/indexing/)
- [Weaviate search](https://weaviate.io/developers/weaviate/search)
- [Elasticsearch vector search](https://www.elastic.co/docs/solutions/search/vector)
- [Pinecone documentation](https://docs.pinecone.io/)
- [Milvus 3.0 发布说明](https://zilliz.com.cn/blog/milvus-3-0-release)
