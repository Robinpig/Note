## Introduction

DuckDB 的性能来自三件事：**向量化执行**（按 2048 行一批处理，摊薄每次函数调用的开销）、**压缩态执行**（dictionary / constant 向量不解物化就推进执行层）、**morsel 级并行**（行组内再切细单元，任务调度器动态分发给工作线程）。本页把这三件事的机制讲透：Vector 的五种格式、`DataChunk` 的流转、嵌套类型的向量布局、并行模型与优化器规则。编译流水线的全貌见 [Architecture](/docs/CS/DB/DuckDB/Architecture.md)。

## Vectors and DataChunks

执行层的容器是两级结构：**Vector** 是单列的定长批量，**DataChunk** 是一组 Vector（相当于一行块的多列视图）。所有算子都按这个批量工作，固定大小即源码里的 `STANDARD_VECTOR_SIZE`：

```cpp
constexpr idx_t STANDARD_VECTOR_SIZE = 2048;  // 默认 2048 行/批
```

2048 是一个折中：足够摊薄算子切换与函数调用开销，又小到能留在 L2/L3 缓存里做完一趟过滤。查询结果、扫描产出、join 输出全部以这个粒度流动，`EXPLAIN ANALYZE` 里看到的 cardinality 也是批数而非行数。

### Vector Formats

同一列逻辑数据可以有五种物理表示，这是「压缩态执行」的载体：

| 格式 | 物理表示 | 典型来源 |
| :--- | :--- | :--- |
| Flat | 连续数组，逻辑=物理 | 默认、物化结果 |
| Constant | 只存一个常量值 | 常量表达式；解压 constant 压缩 |
| Dictionary | child 向量 + selection vector（下标） | 解压 dictionary 压缩 |
| Sequence | 偏移 + 步长 | 行标识、`range()`、递增序列 |
| Unified | 通用视图，任何格式可转入 | 泛型代码读取向量 |

Constant 向量的价值一眼可见：`SELECT lst || 'duckdb' FROM range(1000)` 里字符串字面量只存一次，不必复制 1000 份。Dictionary 向量让存储层的字典压缩一路带进执行层——过滤、投影、哈希都可以在压缩表示上做，只有必要处才 flatten。

要写「不管输入是什么格式都能工作」的泛型算子，用 `UnifiedVectorFormat`：它提供任意格式向量的统一读视图，避免为每种格式组合写特化代码的组合爆炸。

### String Vectors

字符串用 `string_t` 表示，是一个 16 字节的联合体：

```cpp
struct string_t {
    union {
        struct { uint32_t length; char prefix[4]; char *ptr; } pointer;  // 长串：指针
        struct { uint32_t length; char inlined[12]; } inlined;            // 短串：内联
    } value;
};
```

- **≤ 12 字节的字符串内联**在结构体里，分配与拷贝归零；更长的走指针，指向辅助字符串缓冲区。
- `length` 常驻避免反复 `strlen`；`prefix`（前 4 字节）用于比较时快速否决——前缀不同直接判定不等，不必 chase 指针。

### Nested Vectors

嵌套类型的向量布局解释了它们的性能特征：

- **LIST**：`list_entry_t { offset, length }` 序列 + 一个 child 向量，child 里连续存放所有行的元素。可递归嵌套（`BIGINT[][]` 的 child 还是 list 向量）。
- **ARRAY**（2.0 引入）：定长列表，没有 per-row 的 `list_entry_t`——第 i 行的元素在 child 的 `[i*n, (i+1)*n)`，布局比 LIST 更密。
- **STRUCT**：一组 child 向量，数量与类型由结构体 schema 决定。
- **MAP**：内部就是 `LIST[STRUCT(key, value)]`。
- **UNION**：结构与 STRUCT 相同，但第一个 child 固定是 Tag 向量，逐行记录当前生效的成员类型。

## Push-Based Execution

物理算子以推式执行：每个算子实现 `Sink`/`Finalize` 或流式 `Execute` 接口，被上游要数据时向下游推 DataChunk。好处是批量边界清晰、分支预测友好；代价是 **pipeline breaker**——算子需要看完全部输入才能产出第一行：

| Breaker | 物化什么 |
| :--- | :--- |
| Hash Join | 建侧整表哈希表 |
| Sort / Order By | 全部输入 |
| Hash Aggregate | 分组表（可 spill） |
| Window | 分区内全部行 |
| Blockwise NL Join | 右表块 |

Breaker 之前的算子是「源端并行」，breaker 本身承担并行归并，breaker 之后是「汇端并行」。一条查询通常被切成多条 pipeline，由任务调度器统一调度；pipeline 之间的边界就是内存占用与 spill 决策发生的地方。

## Parallelism

DuckDB 的并行单位是 **morsel**：行组（默认 122,880 行）在扫描时被切成更细的 morsel（典型 122,880 / 线程数 量级，随负载动态调整），工作线程从任务队列领取。与「一个线程扫一个行组」的粗粒度方案相比，morsel 让尾长（tail latency）与倾斜都更可控——大行的表、快慢混合的谓词都能均匀摊开。

并行的三个约束值得记住：

1. `SET threads = N` 控制工作线程数，**默认等于 CPU 核数**；嵌入式部署里这是最常见的撞车点。
2. 阻塞算子（排序、聚合、join）各自做并行归并，不是简单的「一份输入一个线程」。
3. 结果顺序默认保持（`preserve_insertion_order = true`），关掉它可以换取更高吞吐——此时无 `ORDER BY` 的结果行序不保证。

## Optimizer Rules

逻辑优化是一组顺序作用的规则（无 CBO），按 `Architecture` 一节列出的顺序执行。对排障最有用的三条：

- **Filter Pushdown + 剪枝**：静态为假的过滤（如 `WHERE 1 = 0`）会让整棵子树被剪掉，`EXPLAIN` 直接看不到扫描。
- **DPhyp 连接重排**：纯动态规划最小化中间结果基数，不依赖统计信息——因此「给 DuckDB `ANALYZE` 提升计划质量」这条路不存在，连接顺序对统计不敏感。
- **In Clause Rewriter**：大 `IN (...)` 列表会被改写成 join，计划形态因此变化，读 `EXPLAIN` 时要认得。

物理层则提供多套连接算法（nested loop、hash join、piecewise merge join、IEJoin）与聚合策略（哈希/排序），由启发式规则选择；2.0 的异步 I/O 让扫描端可以把多个远程请求同时压在飞，与 morsel 并行叠加。

## Links

- [DuckDB](/docs/CS/DB/DuckDB/DuckDB.md)
- [Architecture](/docs/CS/DB/DuckDB/Architecture.md)
- [Storage Format](/docs/CS/DB/DuckDB/Storage_Format.md)
- [Type System](/docs/CS/DB/DuckDB/Type_System.md)
- [Indexes](/docs/CS/DB/Concept/Index.md)

## References

1. [DuckDB Internals – Execution Format](https://duckdb.org/docs/2.0/internals/vector.html)
2. [DuckDB Internals – Overview](https://duckdb.org/docs/2.0/internals/overview.html)
3. [DuckDB Configuration Overview](https://duckdb.org/docs/2.0/configuration/overview.html)
4. [FSST: Fast Random Access String Compression (VLDB 2020)](https://www.vldb.org/pvldb/vol13/p2649-boncz.pdf)
