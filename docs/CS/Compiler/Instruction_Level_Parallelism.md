# Instruction-Level Parallelism

## Introduction

指令级并行（ILP）是**单线程内**的并行：CPU 每个周期发射多条指令，前提是它们之间没有依赖且资源不冲突。
编译器通过重排指令、展开循环、消除假依赖，把源代码的顺序语义映射到硬件的并行执行能力上。

ILP 的收益受限于**依赖链长度**而非硬件宽度——一条 10 拍延迟的依赖链，4-wide 的 CPU 也只能跑到 10% 利用率。
所以编译器的工作重心是"缩短关键路径"与"填满发射槽"，而不是简单堆指令。

## Hardware Model: Pipeline and Hazards

经典五级流水线：取指 → 译码 → 执行 → 访存 → 写回。

| 冒险 | 原因 | 硬件缓解 | 编译期配合 |
| :--- | :--- | :--- | :--- |
| 结构冒险 | 资源冲突 | 多端口 | 分散资源使用 |
| 数据冒险 RAW | 真依赖 | 前递（forwarding） | 调度错开延迟 |
| 数据冒险 WAR / WAW | 假依赖 | 寄存器重命名 | SSA + 重命名 |
| 控制冒险 | 分支 | 分支预测 | if-conversion、预取 |

前递（forwarding）解决大部分 RAW 延迟，但 load→use 的延迟通常无法完全掩盖（访存拍数固定），这就是"调度独立指令到 load 之后"的动机。

## Dependences

正确调度的前提是分类依赖：

| 类型 | 定义 | 可否打破 |
| :--- | :--- | :--- |
| 真依赖 RAW | 写后读 | 不可 |
| 反依赖 WAR | 读后写 | 寄存器重命名 |
| 输出依赖 WAW | 写后写 | 重命名 + 调度 |
| 控制依赖 | 分支结果 | 推测执行 |

数据依赖图（DAG）里，节点是指令、边是最小延迟约束；调度的目标是在满足边的前提下最小化总长度——这正是指令调度的算法核心。

## Scheduling Techniques

### List Scheduling

最常用：从就绪集（所有前驱已调度）里按启发式挑一条放下一条发射槽。
启发式包括关键路径长度优先（缩短总延迟）、发射宽度均衡、资源占用最小化。
它本质是贪心，不保证最优，但在实际程序上接近手工编排。

### Loop Unrolling and Software Pipelining

循环体复制 k 份（展开）把循环分支开销摊薄到 1/k，同时创造跨迭代的并行空间：

```
for (i = 0; i < n; i++) a[i] = b[i] * c;
// 展开 4 次后：4 条独立的乘载可同时发射
```

软件流水（software pipelining）把不同迭代的同一阶段错开调度——迭代 i 的 store 与迭代 i+1 的 load 重叠，稳态下每周期完成一个迭代，是 VLIW 与 DSP 编译器的标准武器。

### If-Conversion and Predication

把短分支转成条件执行（ARM 的 `IT` 块、Itanium 的谓词寄存器）：

```
if (c) x = a; else x = b;
// 转为无分支谓词执行，消除不可预测分支
```

代价是两个分支都执行，只在"分支高度不可预测 + 分支体短"时划算；长分支体反而拖累流水。
编译器用 profile 数据决定是否 if-convert，这正属于 PGO 的输入（见 [Optimization](/docs/CS/Compiler/Optimization.md)）。

## Vectorization: Data-Level Parallelism

SIMD 是 ILP 的批量形态：一条指令处理 4/8/16 个数据元素。
编译器自动向量化的三个条件：

1. **无循环携带依赖**：迭代间不冲突（`a[i]` 与 `a[i+1]` 的归约需要重结合）；
2. **无别名**：`a[i]` 与 `b[i]` 不重叠（依赖别名分析，或 `#pragma omp simd` / `__restrict` 断言）；
3. **可向量化操作**：循环体内的除法/函数调用可能阻止向量化（缺对应指令）。

运行时检查（runtime alias check）让编译器生成"先检查、再选标量/向量路径"的代码，是安全向量化的标准手法。
手写 intrinsics 与 `#pragma` 提示仍是向量化不可替代的补充。

## Superscalar, VLIW, and the Compiler's Role

| 架构 | 并行决策者 | 编译器负担 |
| :--- | :--- | :--- |
| 超标量（x86、ARM） | 硬件动态调度 | 中——静态调度打底，硬件兜底 |
| VLIW / EPIC（Itanium） | 编译器静态打包 | 重——编译器决定每周期发射 |
| SIMD（x86 AVX、ARM NEON） | 编译器 + 程序员 | 数据并行完全由向量化决定 |

x86 的乱序执行掩盖了部分调度失误，所以 C 编译器即使静态调度一般也能跑；Itanium 的失败从反面证明：把全部调度负担压给编译器、没有硬件兜底的架构，对编译器质量的要求是灾难级的。

## Links

- [Compiler](/docs/CS/Compiler/Compiler.md)
- [Optimization](/docs/CS/Compiler/Optimization.md)
- [Code Generation](/docs/CS/Compiler/Code_Generation.md)
- [CO](/docs/CS/CO/CO.md)

## References

1. [uops.info — Instruction Latency, Throughput and Port Usage](https://uops.info/)
2. [Auto-Vectorization in LLVM — The LLVM Vectorizers](https://llvm.org/docs/Vectorizers.html)
