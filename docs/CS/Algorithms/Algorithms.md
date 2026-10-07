## Introduction

「算法」一词古已有之：中文里至少唐代就出现了，更早还有「术」「算术」等说法，最早见于《周髀算经》《九章算术》，且含义自古至今几乎未变。英文 *algorithm* 源自 9 世纪波斯数学家花拉子米（al-Khwārizmī，约 780–850）——解决一次与一元二次方程的那位；其拉丁译名 *Algoritmi* 在 12 世纪指用阿拉伯数字做算术的过程，18 世纪演变为 *algorithm*。

约公元前 300 年《几何原本》中的辗转相除法（欧几里得算法）被视作史上第一个算法——求两数最大公约数。1936 年图灵在《论数学计算在决断难题中之应用》中提出图灵机，解决了「算法」的精确定义问题，为整个学科奠定根基。此后算法全面转向计算机科学，覆盖排序、统计、线性规划、搜索、压缩等方向；而如今随着机器学习的发展，神经网络相关算法的重要性与日俱增。

本页是算法领域的**入口与总纲**。它不堆砌细节，而是先给出组织全领域的**三根轴**，再按轴分派到各子笔记；每根轴的深入展开由对应子目录或专题笔记承担。

## 纲领：一条主线与三根轴

**主线**：算法要解决的是——把一个问题实例，映射到一个**正确**的解，并度量这个映射的**代价**。因此任何算法都可拆成三部分：问题（要解什么）、方法（怎么解）、代价（花多少）。

由此，整个领域可沿**三根轴**组织：

| 轴 | 回答什么 | 取值 | 展开位置 |
| :-- | :-- | :-- | :-- |
| **问题形态** | 要解什么 | 判定与构造 / 搜索 / 排序与选择 / 最优化 / 计数与统计 | 见[经典算法专题](#经典算法专题) |
| **构造方式** | 怎么解 | 暴力枚举 / 分治 / 动态规划 / 贪心 / 回溯 / 随机化 | 见[设计范式](#设计范式) |
| **支撑结构** | 拿什么解 | 线性表 / 堆与队列 / 树 / 图 / 哈希 | 见[数据结构](#数据结构) |

**三轴交叉处即具体算法**。举几个例子说明这张网怎么用：

- **最短路** = 搜索问题 + 「按累计权值逐步扩展」的贪心式构造 + 图结构
- **最小生成树** = 最优化问题 + 贪心 + 图结构
- **KMP 字符串匹配** = 搜索问题 + 复用已知前缀信息的构造方式 + 线性表
- **PageRank** = 计数与统计问题 + 迭代求不动点 + 有向图结构

**复杂度**（见下一节）是横贯三轴的统一判据：不论走哪根轴，最终都要用渐进记号回答「最坏情况下花多少」。而**正确性**则是另一条贯穿线：不同形状的算法对应不同的证明手法。

## 复杂度分析

算法是为完成特定任务而遵循的有限指令集，必须满足五条性质：**输入**（零个或多个外部输入）、**输出**（至少一个产出）、**确定性**（每条指令清晰无歧义）、**有限性**（对任何情况都在有限步后终止）、**有效性**（每条指令都基本到原则上可用纸笔完成）。

我们对一个计算机算法有两方面诉求：**正确性**与**效率**。对部分问题（如近似算法、随机算法）可以容忍可控的错误率或近似解；但对绝大多数情形，先证正确性、再谈效率。

### 正确性证明

不同形状的算法对应不同的证明手法：

- **归纳法**：分治、递归类算法——对规模归纳，并证明递归分解与合并步骤正确。
- **交换论证**：贪心、排序类算法——证明「任何解都不优于贪心解」，常通过交换相邻元素把最优解改造成贪心解。
- **反证法**：图论结论、下界证明——假设结论不成立则推出矛盾。
- **循环不变式**：循环类算法——证明每轮结束时某性质成立且被保持，并说明它如何导出最终结果。

### 渐进复杂度

衡量效率的首要指标是**时间**，其次是**空间**（内存占用），此外还可能关心网络通信、随机比特、磁盘 I/O 等资源。

对规模为 $n$ 的输入，算法耗时（或耗空间）随 $n$ 增长的行为称为**时间复杂度 / 空间复杂度**，其极限行为称为**渐进复杂度**。通常以最坏情况（worst-case）为主——它最易分析且普适；平均情况（expected）更贴近实际，但依赖输入分布假设，往往难以求得。理论分析常用大 O、大 Ω、大 Θ 记号刻画渐进上界 / 下界 / 紧界（Ω 与 Θ 由 Knuth 倡导，以纠正只用 O 同时表示上下界的草率做法）。

> 一个算法的运行时间是多项式级的，则称它是**高效的**。

**均摊复杂度**（见 [Amortized](/docs/CS/Algorithms/Amortized.md)）是第三种视角：它不看单次操作的极端耗时，而把一系列操作的总代价摊到每个操作上，从而描述「偶发一次昂贵、但长期平均便宜」的结构（如动态数组扩容、并查集按秩合并）。它与平均复杂度不是一回事——后者依赖输入分布，前者是对任意操作序列成立的确定性保证。

### 计算模型与可计算性

精确的（非渐进的）效率度量通常需要假定一个**计算模型**（如随机访问机RAM、图灵机，或规定某些操作为单位时间）。模型有弱点：它假设所有操作耗时相同、内存无限，因而忽略磁盘分页、cache 等现实因素。关于「哪些问题原则上不可判定」的形式化讨论见 [Computability](/docs/CS/Algorithms/Computability.md)；资源度量的前提正是计算模型，否则「一条指令耗多少」无从谈起。

### 递归与分治

递归（recursion）在定义中调用自身，把原问题化为同构但规模更小的子问题；程序上靠栈帧实现，层数过深会栈溢出。分治（divide-and-conquer）是递归的典型套路：分解 → 递归求解子问题 → 合并。详见 [Recursion](/docs/CS/Algorithms/Recursion.md) 与 [Divide and Conquer](/docs/CS/Algorithms/Divide-and-Conquer.md)；斐波那契数列的递推式求解（定义式、记忆化、矩阵幂、快倍增）也是这一思路的经典示例。

## 数据结构

数据结构是计算机中**存储与组织数据的特定方式**，目的是高效使用数据。按元素组织方式可分两类：**线性结构**（按顺序访问，但不必顺序存储，如链表、栈、队列）与**非线性结构**（树、图）。它是「支撑结构」轴的展开——同一算法换一种支撑结构，复杂度往往就变了。

### 线性表

列表（线性表）是按线性顺序排列的数据项有限序列，具有顺序且长度可变。常见线性结构包括：

- 数组与链表：数组是列表的一种实现，兼具列表特征与自身特性；链表像手拉手的人，只记住前后节点。见 [array](/docs/CS/Algorithms/struct/array.md)、[linked-list](/docs/CS/Algorithms/struct/linked-list.md)、[list](/docs/CS/Algorithms/struct/list.md)。
- 栈与队列：栈像一叠盘子只能顶端取放；队列像排队买票先来先服务。见 [stack](/docs/CS/Algorithms/struct/stack.md)、[queue](/docs/CS/Algorithms/struct/queue.md)。
- 数据结构总论（数组/链表在图、树、哈希中的取舍）见 [Structure](/docs/CS/Algorithms/struct/Structure.md)。

### 堆、队列与变体结构

- 堆（heap）：完全二叉树，数组实现，支撑优先队列。见 [heap](/docs/CS/Algorithms/struct/heap.md)。
- 布隆过滤器（Bloom Filter）：用位数组做集合成员判定，有假阳性、无假阴性。见 [BloomFilter](/docs/CS/Algorithms/struct/BloomFilter.md)。
- 跳表（skiplist）、树状数组（Fenwick Tree）、单调栈（Monotonic Stack）等变体：见 [skiplist](/docs/CS/Algorithms/struct/skiplist.md)、[Fenwick-Tree](/docs/CS/Algorithms/struct/Fenwick-Tree.md)、[MonotonicStack](/docs/CS/Algorithms/struct/MonotonicStack.md)。

### 哈希

哈希表（hash table）支持字典操作 INSERT / DELETE / SEARCH，最坏情况 $Θ(n)$，期望 $O(1)$。冲突处理（拉链法、开放寻址）依赖链表与数组特性；扩容策略与一致性哈希是分布式场景的关键补充。见 [hash](/docs/CS/Algorithms/hash.md)。

### 树

树是支撑结构里分支最密的一支：

- 总论与基础：[tree](/docs/CS/Algorithms/tree/tree.md)、[Binary-Tree](/docs/CS/Algorithms/tree/Binary-Tree.md)。
- 平衡与检索：红黑树 [Red-Black-Tree](/docs/CS/Algorithms/tree/Red-Black-Tree.md)、B 树 [B-tree](/docs/CS/Algorithms/tree/B-tree.md) 与 B⁺ 树 [B_Link_Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)。
- 前缀与区间：Trie [Trie](/docs/CS/Algorithms/tree/Trie.md)、线段树 [Segment-Tree](/docs/CS/Algorithms/tree/Segment-Tree.md)、基数树 [Radix](/docs/CS/Algorithms/tree/Radix.md)、哈夫曼树 [Huffman-Tree](/docs/CS/Algorithms/tree/Huffman-Tree.md)。
- 集合与存储：并查集 [Disjoint_Set](/docs/CS/Algorithms/tree/Disjoint_Set.md)、LSM 树 [LSM](/docs/CS/Algorithms/tree/LSM.md)、后缀树 [Suffix_Tree](/docs/CS/Algorithms/tree/Suffix_Tree.md)。

### 图

图（graph）由顶点与边构成，邻接矩阵（数组）适合判连通与矩阵运算但稀疏时费空间，邻接表（链表）省空间但部分操作慢。图论枢纽见 [graph](/docs/CS/Algorithms/graph/graph.md)，它同时展开了「问题形态」轴上的搜索、连通性、最优化三类问题。

## 设计范式

这是「构造方式」轴的展开——同一问题常有多种解法，按**设计思想**归为若干族：

- 枚举（Enumeration）：暴力遍历所有可能，常与剪枝配合。见 [Enumeration](/docs/CS/Algorithms/Enumeration.md)。
- 回溯（Backtracking）：在枚举基础上按约束回退搜索。见 [Backtracking](/docs/CS/Algorithms/Backtracking.md)。
- 贪心（Greedy）：每步取局部最优，依赖最优子结构。见 [Greedy](/docs/CS/Algorithms/Greedy.md)。
- 动态规划（Dynamic Programming）：子问题重叠时，每个子问题只算一次并存入表格，避免分治的重复计算，常用于最值与计数。见 [DP](/docs/CS/Algorithms/DP/DP.md)，含背包、LCS、LIS、树形与区间 DP 及优化技巧。
- 分治（Divide and Conquer）：分解 → 递归 → 合并。见 [Divide and Conquer](/docs/CS/Algorithms/Divide-and-Conquer.md)（已在复杂度一节提及）。
- 随机算法（Randomized）：引入随机性以简化或加速。见 [Randomized](/docs/CS/Algorithms/Randomized.md)。
- 均摊分析（Amortized Analysis）：把偶发的昂贵操作摊到一系列廉价操作上。见 [Amortized](/docs/CS/Algorithms/Amortized.md)。
- 双指针（Two Pointers）：用两个游标收缩区间，常配合有序性。见 [Two-Pointers](/docs/CS/Algorithms/Two-Pointers.md)。
- 位运算（Bits）：用二进制位直接操作提升效率。见 [Bits](/docs/CS/Algorithms/Bits.md)。
- 前缀和 / 差分：区间求和与区间修改的预处理技巧；文本差分（Myers 等）的写法见 [diff](/docs/CS/Algorithms/diff.md)。

## 经典算法专题

按**问题形态**归类的具体算法：

- 判定与构造：[Computability](/docs/CS/Algorithms/Computability.md)（可判定性与图灵机）、[NP](/docs/CS/Algorithms/NP.md)（NP 完全与 $P \neq NP$，自 1971 年起是理论计算机科学最深的开问题之一）。
- 搜索：[search](/docs/CS/Algorithms/search.md)（二分、DFS、BFS）、[string-search](/docs/CS/Algorithms/string/string-search.md)（朴素 / Rabin-Karp / KMP / BM / 后缀数组）、[string](/docs/CS/Algorithms/string/string.md)（字符串基础与哈希）。
- 排序与次序统计：[sort](/docs/CS/Algorithms/sort.md)（比较排序与非比较排序、外排）。
- 最优化：[graph](/docs/CS/Algorithms/graph/graph.md) 下的最小生成树与最短路，二分图 [Matching](/docs/CS/Algorithms/graph/Matching.md)，以及 [Network_Flow](/docs/CS/Algorithms/Network_Flow.md)（网络流）。题解见 [Shortest-Path](/docs/CS/Algorithms/question/Shortest-Path.md)。
- 计数与统计：[PageRank](/docs/CS/Algorithms/PageRank.md)（随机游走平稳分布）、[HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md)（基数估计）、[Number_Theory](/docs/CS/Algorithms/Number_Theory.md)（筛法、快速幂、模逆元、Pollard–Rho）。
- 几何与游戏：[Computational_Geometry](/docs/CS/Algorithms/Computational_Geometry.md)（凸包、扫描线、鲁棒性）、[Algorithmic Game Theory](/docs/CS/Algorithms/Algorithmic_Game_Theory.md)（Minimax、α-β 剪枝、PVS、MCTS/UCT）。
- 压缩：[JPEG](/docs/CS/Algorithms/JPEG.md)（DCT + 量化 + 游程 / 哈夫曼）。

### 页面置换算法

页面置换决定内存满了之后淘汰哪一页，是操作系统与各级缓存的共同基础（CPU cache、Redis、Buffer Pool、业务缓存），也是「最优化」轴上一个取材于真实系统的完整案例。

| 算法规则                | 优缺点                                                                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| OPT                     | 优先淘汰最长时间内不会被访问的页面；缺页率最小、性能最好，但无法实现                                                              |
| FIFO                    | 优先淘汰最先进入内存的页面；实现简单，但性能很差，可能出现 Belady 异常                                                          |
| LRU                     | 优先淘汰最近最久没访问的页面；性能很好，但需要硬件支持、算法开销大。详见 [LRU](/docs/CS/Algorithms/LRU.md)                    |
| CLOCK (NRU)             | 循环扫描，第一轮淘汰访问位=0 的页面并把扫过的访问位置 1；若没选中则第二轮再扫。实现简单、开销小，但未考虑页面是否被修改过          |
| 改进型 CLOCK (改进型 NRU) | 以（访问位，修改位）表述：第一轮淘汰 (0,0)，第二轮淘汰 (0,1) 并把扫过的访问位置 0，第三轮淘汰 (0,0)，第四轮淘汰 (0,1)。开销较小、性能也不错 |

## 系统与工程中的算法

算法不止于教科书：现实系统中的性能、存储、时延问题都靠专门算法支撑，且常需要在前沿理论之外做工程取舍。

- 基数估计：[HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md) 以极小内存近似计数。
- 定时器管理：[TimingWheel](/docs/CS/Algorithms/TimingWheel.md) 以空间换时间，把海量定时器扫描降到接近 $O(1)$。
- 存储权衡：[The_Five_Minute_Rule](/docs/CS/Algorithms/The_Five_Minute_Rule.md) 给出内存与磁盘 I/O 的经典经验律。
- 缓存淘汰：[LRU](/docs/CS/Algorithms/LRU.md) 及其 $O(1)$ 实现（哈希表 + 双向链表）。
- 共识算法（Paxos / Raft）属于分布式系统范畴，本域不展开，见 [Distributed](/docs/CS/Distributed/Distributed.md)。

## 题目与练习

把算法落到题目里才能内化。`question/` 目录收录典型题解：汉诺塔 [Hanoi](/docs/CS/Algorithms/question/Hanoi.md)、N 皇后 [N-Queens](/docs/CS/Algorithms/question/N-Queens.md)、最短路 [Shortest-Path](/docs/CS/Algorithms/question/Shortest-Path.md)、动态规划题集 [Dynamic-Programming](/docs/CS/Algorithms/question/Dynamic-Programming.md)。

常用在线评测：

- [洛谷](https://luogu.com.cn)
- [LibreOJ](https://loj.ac)
- [Codeforces](https://codeforces.com)
- [POJ](https://poj.org)
- [HDU](https://acm.hdu.edu.cn)
- [ZOJ](https://acm.zju.edu.cn)

## Links

- [数据结构（本页锚点）](/docs/CS/Algorithms/Algorithms.md?id=数据结构)
- [复杂度分析（本页锚点）](/docs/CS/Algorithms/Algorithms.md?id=复杂度分析)
- [Computer Organization](/docs/CS/CO/CO.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [Mathematics](/docs/Mathematics/Mathematics.md)

## References

1. Wirth, N. *Algorithms + Data Structures = Programs*.
2. Cormen, T. H. et al. *Introduction to Algorithms* (3rd ed.).
3. Anany, L. *Introduction to The Design and Analysis of Algorithms* (3rd ed.).
4. Sedgewick, R. & Wayne, K. *Algorithms* (4th ed.).
5. Weiss, M. A. *Data Structures and Algorithm Analysis in C*.
6. Aho, A. V. et al. *The Design and Analysis of Computer Algorithms*.