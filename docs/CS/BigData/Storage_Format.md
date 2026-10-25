## Introduction

文件格式回答的是"一个文件内部的字节怎么摆"。它是大数据栈里最容易被忽视、但收益最确定的一层：换一个格式不动任何代码，存储成本与扫描耗时就可能差出数倍。原因很简单——分析型查询的共性是**读少数列、扫大量行**，而行存格式强迫你为了三列把整行读出来。

这一层的选择独立于上层引擎：同一份 Parquet 文件，[Spark](/docs/CS/Framework/Spark/Spark.md)、Trino、Impala、[Flink](/docs/CS/Framework/Flink/Flink.md) 都能读。正因如此，Parquet 成了跨引擎共享的公约数，而绑定更深的 ORC 则在 [Hive](/docs/CS/DB/Hive.md) 生态里不可替代（ACID 事务必需）。Hive 视角下的两格式结构对比见 [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)，本页讲编码与列存原理本身。

> [!NOTE]
> 版本口径：Parquet 的格式规范（thrift 定义）最新为 **2.13.0**（2026-06-13），ORC 最新实现为 **2.3.1**（2026-07-16）。规范版本号与实现版本号是两套编号——`parquet-format` 独立于 parquet-java / arrow-rs 发布，且主版本号对应文件里 `FileMetadata.version` 字段。

## Row-Oriented vs Column-Oriented

行存把一行的所有字段连续存放，列存把同一列跨行的值连续存放。差别在 IO 量与压缩率两处被同时放大：

- **IO**："查一亿行里的两个字段"，行存要读完整行，列存只读那两列。这是列存最大的收益来源，列越宽、查询用到的列越少，差距越大。
- **压缩**：同一列的数据类型相同、值域相近、重复度高，压缩比远高于混合了多种类型的行。字典编码对低基数列尤其有效。

代价在写入侧：一行数据要拆散写到 N 个列块，写入路径变复杂，单行点查退化成 N 次随机读。所以列存适合**扫描聚合**，不适合**按主键点查**——后者是 [HBase](/docs/CS/DB/HBase.md) 这类 LSM 宽列存储的领地。注意"列存"与"宽列存储"是两回事，前者按列跨行压，后者按列族内行存。

## Encoding

压缩之前先做编码。编码是针对数据类型与分布做**可逆的紧凑表示**，它决定了压缩算法的输入质量，也决定了能否直接在编码态上做过滤。

| 编码 | 原理 | 适用 |
| :--- | :--- | :--- |
| Dictionary | 把去重后的值建成字典，列里只存整数下标 | 低基数列（性别、国家、状态码） |
| RLE（Run Length Encoding） | 把连续重复值记成「值 + 重复次数」 | 排序后重复连续的列、稀疏的 null 位图 |
| Bit-packing | 按该列最大值的实际位宽存整数，不用满 32/64 位 | 小整数、字典下标 |
| Delta | 存相邻值的差而非值本身 | 时间戳、自增 ID、有序数值 |
| ZigZag + Varint | 负数映射成正数后用变长字节编码 | 有符号整数 |
| Byte Stream Split | 把浮点按字节拆分后各自成块压缩 | 浮点数（IEEE 754 的指数位破坏压缩） |

Dictionary + RLE + Bit-packing 的组合是列存的默认起点：先字典化把字符串变成整数，再 bit-packing 压整数，重复段用 RLE。这就是为什么字典大小是有意义的配置项（ORC 的 `orc.dictionary.include/size.threshold`、Parquet 的 `parquet.dictionary.page.size`）——字典溢出后退化成 PLAIN，压缩率显著下降。

编码还决定了一个重要能力：**能否在编码态上直接过滤**。字典编码的列做等值过滤时可以先在字典里比对下标，不必解码全部值；Delta 编码的列做范围过滤时可以只在块边界解码。

## Compression

编码之后是通用压缩（块级）。它压的是编码输出的字节流，与数据类型无关。选型是在压缩比与 CPU 之间权衡：

| 算法 | 压缩比 | 速度 | 说明 |
| :--- | :--- | :--- | :--- |
| Snappy | 中 | 很快 | 默认选择，CPU 便宜，冷热数据都合适 |
| Zstd | 高 | 快（可调 level） | 压缩比与速度都可调，冷数据归档的首选 |
| LZ4 | 中低 | 极快 | 追求解压吞吐，ORC 2.3 起有基于 lz4-java 的新 Lz4Codec |
| Gzip | 高 | 慢 | 高压缩比但 CPU 贵，且**不可分片**（split）会影响并行度 |
| none | — | — | CPU 极廉价、数据已高度压缩或纯内存场景 |

"能不能分片"是个容易被忽略的硬约束：一个不可分片的压缩文件只能由单个 task 读，等于放弃了并行度。这是 gzip 在分析场景失宠的主因，也是列存的块（Parquet 的 page、ORC 的 stripe）必须独立可解压的原因。

## Nested Data and the Dremel Encoding

半结构化数据（JSON、protobuf）的难点是**嵌套与重复**：一个字段可能出现 0 次、1 次或多次。关系型列存假设每列每行的值固定，装不下这种结构。

Dremel 的解法是用**两个整数**把嵌套结构完全编码进列式表示，从而让嵌套数据也能按列存：

- **Repetition Level**：这个值相对前一个值，在哪一层发生了重复（用于区分"新的一行/新的一层"与"同一层里多一个值"）。
- **Definition Level**：这个值在其路径上有多少层是实际存在的（用于区分 null 是字段缺失还是整层缺失）。

有了这两个 level，任意嵌套结构都能展平成若干列 + 两个 level 列，读取时无损重组。Parquet 就建立在这个模型上，这也是它能直接存 protobuf / Thrift / Avro schema 的原因。代价是**写与读的逻辑复杂度显著高于扁平表**，且深层嵌套会让 level 列本身也变大。

这条脉络延续到了今天的类型系统：Parquet 定义了 `VARIANT` 逻辑类型来存半结构化值，Iceberg v3 在其上加了 Variant 类型，Spark 4.0 与 4.1 也各自引入了 VARIANT。**嵌套不再是"要不要支持"的问题，而是"引擎能否向量化地读它"的问题**。

## Statistics and Predicate Pushdown

列存真正的杀手锏不是省空间，而是**跳过数据**。文件里除了数据本身，还写着各级统计信息，查询 planner 用它们在读盘之前就排除掉整块数据：

- **min/max**：块级的值域。范围过滤与等值过滤都能用。这是收益最大、成本最低的一项。
- **count / null count**：用于快速回答 count 与空值率。
- **Bloom filter**：用于等值过滤（尤其 `IN` 与点查），判断"某值肯定不在这个文件里"。Parquet 与 ORC 都支持，是向后兼容特性——不认识它的旧 reader 只是忽略它，仍能正确读数据。
- **Column index / Offset index**：Parquet 在页级记录值域与页偏移，配合 min/max 实现页级跳过；ORC 的等价物是 stripe 尾部的行组级索引。

这里有个重要的实践结论：**统计信息只在数据有序时才有价值**。如果一列的值随机散布，每个块的 min/max 都覆盖全域，什么都跳不掉。这就是 Z-ordering、聚簇（clustering）、按常用过滤列排序能带来数量级提升的原因——它们改变的不是数据量，而是 min/max 的区分度。

## Vectorized Reading

向量化是列存落地的另一半。传统行式执行是一次处理一行：每个算子反复调用 next()，虚函数调用与解释开销远超实际计算。列存的布局天然适合**一次处理一批（batch，通常 1024~4096 行）的同列值**：

- 循环在数组上连续跑，CPU cache 与分支预测友好，编译器可以自动向量化（SIMD）。
- 函数调用从"每行一次"降到"每批一次"。
- 与 Arrow 这类列式内存格式天然对齐，跨引擎零拷贝交换成为可能。

向量化与列存是共生关系：行存做向量化需要先转列，收益打折；列存不做向量化则浪费了布局优势。这也是为什么"读 Parquet 却用行式 reader"是常见的性能陷阱。

## Choosing a Format

| 场景 | 选择 | 理由 |
| :--- | :--- | :--- |
| 多引擎共享的湖仓 | Parquet | 跨引擎一等公民，Iceberg / Delta / Hudi 的默认底座 |
| Hive 托管表、需要 ACID | ORC | 与 Hive 事务、向量化、统计协同最深 |
| 流式写入、schema 频繁演进 | Avro | 行存，写入友好，schema 演进语义成熟 |
| 临时导入、人工排查 | TextFile（CSV/JSON） | 可读，但无列裁剪、无压缩优势，别长期留在生产 |
| 嵌套 / 半结构化 | Parquet + Variant | Dremel 编码原生支持嵌套 |

遗留格式 RCFile 与 SequenceFile 已被 ORC / Parquet 取代，仅历史兼容时用。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)
- [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)
- [SQL Engine](/docs/CS/BigData/SQL_Engine.md)
- [Parquet / ORC in Spark](/docs/CS/Framework/Spark/SQL.md)

## References

1. [Apache Parquet Documentation](https://parquet.apache.org/docs/)
2. [Parquet format versions](https://parquet.apache.org/docs/file-format/versions/)
3. [Apache ORC Documentation](https://orc.apache.org/docs/)
4. [Dremel: Interactive Analysis of Web-Scale Datasets (VLDB 2010)](https://research.google/pubs/dremel-interactive-analysis-of-web-scale-datasets/)
5. [Apache Arrow Columnar Format](https://arrow.apache.org/docs/format/Columnar.html)
