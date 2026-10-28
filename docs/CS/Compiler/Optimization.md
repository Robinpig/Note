# Optimization

## Introduction

优化在 IR 上做**保持语义的等价变换**，目标是让程序更快、更小、更省电。
它不是可选的装饰：未优化的中间代码里充斥着"为每个运算符老实生成一条指令"的冗余，优化器把这些冗余系统性消掉。

优化的边界由理论划定——语义等价性不可判定（见 [Computability](/docs/CS/Algorithms/Computability.md)），所以每个变换都必须**保守**：宁可漏掉，不可错做。
本页的骨架是数据流分析框架，其余章节都是它在不同问题上的实例。

## Data-Flow Analysis

数据流分析回答"在程序点 p，某性质成立吗"，用三个组件描述：

| 组件 | 含义 | 例子（到达定值） |
| :--- | :--- | :--- |
| 域 D | 事实空间 | 定值集合的幂集 |
| 方向 | 前向 / 后向 | 前向（沿 CFG 流） |
| 传递函数 | 基本块对事实的变换 | `gen ∪ (in − kill)` |
| 边界 | 入口 / 出口初值 | `gen(entry)` |

在格上迭代到不动点即得解。经典问题一览：

| 问题 | 方向 | 格运算 | 用途 |
| :--- | :--- | :--- | :--- |
| 到达定值 reaching definitions | 前向 | ∪ | 常量传播、复写传播 |
| 活跃变量 live variables | 后向 | ∪ | 寄存器分配 |
| 可用表达式 available expressions | 前向 | ∩ | 公共子表达式消除 |
| 非常忙表达式 very busy | 后向 | ∩ | 代码提升（部分冗余消除） |

**位向量**实现让每次传递函数调用变成几次按位或/与，分析 10^4 条指令的基本块是微秒级。
LLVM 把这一模式标准化为 `AnalysisPass` + `PassManager`，用户以 `getAnalysis<DominatorTreeAnalysis>()` 声明依赖，pass 的失效与缓存自动管理。

## Peephole and Local Optimizations

窥孔优化直接在指令序列上替换局部模式（`x = x + 0` → `x`，`goto L1; L1: goto L2` → `goto L2`）。
它简单、局部、无风险，但看不到跨基本块的事实。

更强大的变换建立在数据流分析之上：

- **常量传播 + 常量折叠**：沿到达定值传播常量，编译期计算 `60 * 60`；
- **公共子表达式消除**（CSE）：可用表达式分析找出重复计算；
- **复写传播**：`t = x; y = t` 直接改写为 `y = x`，消掉临时变量；
- **死代码消除**（DCE）：沿活跃变量后向分析，无使用的定值整体删除；
- **强度削弱**：`i * 2` → `i << 1`，`i * 15` → `(i << 4) − i`。

## Loop Optimizations

程序 90% 的时间花在 10% 的循环里，循环是优化的主战场：

| 变换 | 机制 | 收益 |
| :--- | :--- | :--- |
| 循环不变代码外提（LICM） | 循环内不变表达式提到入口前 | 消掉重复计算 |
| 归纳变量强度削弱 | `i = i + c` 系列用加法/递减代替乘法 | 减少寻址开销 |
| 归纳变量删除 | 基本归纳变量冗余时整体删除 | 寄存器压力下降 |
| 循环展开 | 复制循环体若干份 | 摊薄分支开销 |
| 循环交换/分块 | 嵌套循环改善访存局部性 | 缓存命中率 |
| 自动向量化 | 循环转 SIMD | 4~16× 数据级并行 |

LICM 与活跃分析的配合是安全性的关键：外提只在"出口一定执行"（至少一次循环）或出口处也计算该表达式的条件下安全。
自动向量化的前提是**无别名**（两次访问不重叠），这依赖别名分析（见 [Code Generation](/docs/CS/Compiler/Code_Generation.md) 对指针分析的引用）。

## Interprocedural and Profile-Guided Optimizations

过程间优化突破函数边界，代价是编译时间与实现复杂度：

- **函数内联**：用调用点展开函数体，打开调用者内的常数传播与后续所有变换；
- **过程间常量传播**：参数是常量时把常量"注入"被调用者；
- **逃逸分析**：对象未逃逸出方法时栈上分配 + 标量替换（Java JIT、Go 逃逸分析同源）；
- **PGO**（profile-guided optimization）：先用插桩/采样跑真实负载，再按分支频率排布基本块、决定内联与展开规模；
- **LTO**（link-time optimization）：跨编译单元在链接期统一优化，是"过程间"的最大化形态（GCC `-flto`、LLVM LTO）。

内联不是免费的：代码膨胀拖垮指令缓存，所有生产编译器都带内联成本模型（阈值 + PGO 频率）。

## What Compilers Actually Do

`-O0` 只做前端必需的生成；`-O1/2` 全开中端安全变换；`-O3` 加激进循环变换（展开、向量化）；`-Os` 以代码大小为目标。
调参的现实建议：先 `-O2`，用 perf 找到热点，再针对性开特定 pass，而不是无脑 `-O3`——向量化对别名未决的循环经常适得其反。

## Links

- [Compiler](/docs/CS/Compiler/Compiler.md)
- [Intermediate Representation](/docs/CS/Compiler/Intermediate_Representation.md)
- [Code Generation](/docs/CS/Compiler/Code_Generation.md)
- [Instruction-Level Parallelism](/docs/CS/Compiler/Instruction_Level_Parallelism.md)
- [Computability](/docs/CS/Algorithms/Computability.md)

## References

1. [LLVM's Analysis and Transform Passes](https://llvm.org/docs/Passes.html)
2. [GCC Optimize Options](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html)
