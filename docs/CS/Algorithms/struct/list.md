## Introduction

**线性表**（list）是 $n$（$n \ge 0$）个数据元素组成的有限序列，记为 $L = (a_1, a_2, \dots, a_n)$。除首尾元素外，每个元素有且仅有一个直接前驱与一个直接后继。元素类型相同、个数有限、位置决定先后——这三点是「线性表」与数组、链表这些具体实现的区别所在：**线性表是逻辑结构，数组与链表是它的两种存储实现**。

线性表的抽象操作包括：初始化、求长度、取第 $i$ 个元素、按值查找、插入、删除、判空。评价一个实现的好坏，就看这些操作各自花多少时间、以及内存开销与局部性。

## Two Storage Strategies

| 维度 | 顺序表（sequential list） | 链表（linked list） |
| :-- | :-- | :-- |
| 存储 | 逻辑相邻 = 物理相邻，一块连续内存 | 节点分散存放，指针串联 |
| 随机访问 | $O(1)$（地址 = 基址 + 下标 × 元素大小） | $O(n)$（需顺序遍历） |
| 插入/删除 | 平均移动 $n/2$ 个元素，$O(n)$ | 已知位置后改指针，$O(1)$ |
| 空间 | 紧凑，无额外开销 | 每节点多存指针，且不连续 |
| 缓存局部性 | 好（顺序扫描命中 cache） | 差（节点跳跃） |
| 容量 | 静态定长；动态表靠扩容 | 按需分配，无需预估 |

## Sequential List

顺序表把元素按次序存进一整块连续内存，第 $i$ 个元素的地址为 `base + (i-1) × sizeof(element)`，一次乘法一次加法即可定位，因此随机访问是 $O(1)$。

- **静态顺序表**：编译期定长，容量不可变，适合规模已知的场景。
- **动态顺序表**（dynamic array / vector / ArrayList）：满时翻倍扩容、拷贝旧元素，插入摊还 $O(1)$，见 [array](/docs/CS/Algorithms/struct/array.md) 与 [Amortized](/docs/CS/Algorithms/paradigm/Amortized.md)。
- 主要代价是**插入/删除要搬移元素**：在头部插入需要移动全部 $n$ 个元素，这也是「数组不适合频繁头插」的原因。

## Linked List

链表把每个元素包进一个节点：**数据域 + 指针域**（指向后继）。节点之间不要求连续，因此插入删除只需改指针，不必搬移数据；代价是失去随机访问能力，且每个节点多付一份指针空间。

按链接方式分：

- **单链表**：只有 `next`，从头节点开始单向遍历；找前驱必须从头走。
- **双向链表**：有 `prev` 与 `next`，删除已知节点 $O(1)$（不必找前驱），是 [LRU](/docs/CS/Algorithms/systems/LRU.md)（哈希表 + 双向链表）的骨架。
- **循环链表**：尾节点指回头节点，适合需要环形遍历的场景（如时间片轮转的进程队列）。
- **静态链表**：用数组下标代替指针，为不提供指针的语言设计。

工程上普遍加一个**头结点（哨兵）**：它的数据域无意义，但让「空表」「在头部插入」「删除第一个节点」不再需要特殊分支，显著减少边界 bug。快慢指针判环（Floyd）等技巧见 [linked-list](/docs/CS/Algorithms/struct/linked-list.md) 与 [Two-Pointers](/docs/CS/Algorithms/paradigm/Two-Pointers.md)。

## Operation Complexity

| 操作 | 顺序表 | 单链表 | 双向链表 |
| :-- | :-- | :-- | :-- |
| 访问第 $i$ 个 | $O(1)$ | $O(n)$ | $O(n)$ |
| 头部插入/删除 | $O(n)$ | $O(1)$ | $O(1)$ |
| 尾部插入/删除 | $O(1)$（维护尾指针） | $O(1)$（维护尾指针） | $O(1)$ |
| 已知节点前插/删 | $O(n)$（需找前驱） | $O(n)$ | $O(1)$ |
| 按值查找 | 无序 $O(n)$ / 有序 $O(\log n)$ | $O(n)$ | $O(n)$ |

## Choosing Between Them

- **默认选顺序表**：缓存友好、常数小，`vector` / `ArrayList` 是绝大多数场景的默认容器。
- **下列情况选链表**：插入删除远多于访问、规模不可预估、需要在 $O(1)$ 内摘除已知节点（LRU、定时器链表、工作队列）。
- 混合方案很常见：跳表 = 多层链表 + 随机晋升（见 [skiplist](/docs/CS/Algorithms/struct/skiplist.md)）；邻接表 = 数组 + 链表；Redis 的数据编码甚至会在小数据时用连续数组、变大后整体换成链表/跳表，见 [Structure](/docs/CS/Algorithms/struct/Structure.md)。

## Links

- [Array](/docs/CS/Algorithms/struct/array.md)
- [Linked List](/docs/CS/Algorithms/struct/linked-list.md)
- [Stack](/docs/CS/Algorithms/struct/stack.md)
- [Queue](/docs/CS/Algorithms/struct/queue.md)
- [Structure](/docs/CS/Algorithms/struct/Structure.md)

## References

1. [链表 - OI Wiki](https://oi-wiki.org/ds/linked-list/)
2. [Slow and Fast Pointers, Floyd's Cycle Detection - CP-Algorithms](https://cp-algorithms.com/others/tortoise_and_hare.html)
