## Introduction

数组（array）是最基础的**顺序存储**结构：一整块连续内存按下标 $0, 1, \dots, n-1$ 依次存放同类型元素。因为元素大小相同且物理相邻，第 $i$ 个元素的地址可以一步算出：

```
address(a[i]) = base + i × sizeof(element)
```

一次乘法加一次加法，与 $n$ 无关，所以**随机访问是严格的 $O(1)$**——这是数组相对一切链表结构的根本优势，也是「数组」在各类语言中都是内置类型的原因。

**优点**：简单、按下标访问快、缓存友好（顺序遍历时硬件预取几乎全命中）。

**缺点**：

- 需要一块连续内存，大数组可能分配失败；
- 容量通常预先划定，空位浪费空间；
- 中间插入/删除要搬移后续元素，头部插入代价 $O(n)$。

## Static and Dynamic Arrays

- **静态数组**：编译期定长，`int a[100]` 或 Go 的定长数组，长度不可变。
- **动态数组**（dynamic array / vector / ArrayList）：容量不足时开辟更大的块并把旧元素整体拷贝过去。常见策略是翻倍扩容，使 $n$ 次追加的总拷贝量构成等比级数、不到 $2n$，因此**追加摊还 $O(1)$**，见 [Amortized](/docs/CS/Algorithms/paradigm/Amortized.md)。
- 工程细节：多数动态数组只自动扩容、**不自动缩容**（避免反复搬移的抖动），或要求缩容阈值明显低于扩容阈值；`std::vector` 的 `capacity` 与 `size` 分离正是为此暴露出来的。

## Two-Dimensional Arrays

二维数组 $a[i][j]$ 的逻辑形状是矩阵，物理布局取决于语言：

- **行优先（row-major）**：先存第 0 行全部元素，再存第 1 行。C/C++ 的真二维数组、NumPy 默认如此，地址为 `base + (i × 列数 + j) × size`。
- **列优先（column-major）**：先存第 0 列。Fortran、MATLAB、R 默认如此。
- 二维数组在内存中是否连续**取决于语言实现**：C/C++ 的二维数组是真·连续块；Java/C# 的「二维数组」本质是**数组的数组**（array of arrays），各行可能是独立对象、物理上不连续。

行优先/列优先直接影响性能：遍历顺序与布局一致才能顺序命中缓存；按列遍历一个行优先的大矩阵会因每次跳行导致 cache 频繁失效，慢数倍很常见。

## Sparse Arrays

当绝大多数元素都是默认值（如 0）时，按二维下标完整存储是巨大浪费。**稀疏数组**只记录非默认元素：

- 三元组表 `(行, 列, 值)`（COO）：直观，适合一次性写入后按行扫描。
- CSR（压缩稀疏行）：把三元组按行分组，配一个行偏移数组，随机访问某行是 $O(1)$、查询非零元是 $O(\text{该行个数})$，是科学计算与图算法（邻接结构）的标准表示。
- 适用场景：稀疏矩阵运算、大图的邻接关系；代价是实现与常数更复杂，见 [Structure](/docs/CS/Algorithms/struct/Structure.md) 中邻接矩阵/邻接表的取舍。

## Cache Friendliness

数组的连续布局让它在多级缓存体系下天然占优，这是链表难以企及的：

- 顺序访问：硬件预取器可提前加载后续 cache line，吞吐远高于随机访问。
- **AoS vs SoA**：结构体数组（每个元素一个完整 struct）利于一次访问用全字段；数组结构体（每个字段一个独立数组）利于只用一个字段时紧凑扫射，是数据密集型程序（游戏、数据库、SIMD）的常用改写。
- 同理，哈希表拉链法的桶数组、堆的完全二叉树数组表示，都是在享受「连续内存 + 下标寻址」的红利。

## Complexity

| 操作 | 静态数组 | 动态数组 |
| :-- | :-- | :-- |
| 按下标访问 | $O(1)$ | $O(1)$ |
| 头部/中间插入 | $O(n)$ | $O(n)$ |
| 删除 | $O(n)$ | $O(n)$ |
| 尾部追加 | — | 摊还 $O(1)$ |
| 查找（无序） | $O(n)$ | $O(n)$ |
| 查找（有序） | $O(\log n)$（二分） | $O(\log n)$ |

## Links

- [List](/docs/CS/Algorithms/struct/list.md)
- [Linked List](/docs/CS/Algorithms/struct/linked-list.md)
- [Amortized Analysis](/docs/CS/Algorithms/paradigm/Amortized.md)
- [Structure](/docs/CS/Algorithms/struct/Structure.md)

## References

1. [数组 - OI Wiki](https://oi-wiki.org/lang/array/)
2. [位运算/分块数组 - OI Wiki](https://oi-wiki.org/ds/bit-in-block-array/)
