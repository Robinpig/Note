## Introduction

STL（Standard Template Library）是 C++ 标准库中最常用的一半：容器、迭代器、算法三件式构成泛型编程范式，也是 [模板](/docs/CS/C++/Templates.md) 与 [内存](/docs/CS/C++/Memory.md) 管理的集中体现。

## 容器

| 类别 | 代表 | 底层 | 关键特性 |
|------|------|------|---------|
| 序列 | `vector` / `deque` / `list` / `forward_list` / `array` | 连续内存 / 分块 / 双向链 / 单向链 / 定长数组 | `vector` 随机访问 O(1)、尾部增删摊还 O(1) |
| 有序关联 | `set` / `map` / `multiset` / `multimap` | 红黑树 | 有序、查找 O(log n)、迭代器稳定 |
| 无序关联 | `unordered_*` | 哈希表 | 平均 O(1)，受负载因子与哈希质量影响 |
| 容器适配器 | `stack` / `queue` / `priority_queue` | 基于序列容器封装 | 受限接口 |

## 迭代器

- 五类：输入 / 输出 / 前向 / 双向 / 随机访问；C++20 新增**连续迭代器（contiguous）**。
- **迭代器失效**规则是常见 bug 源：`vector` 扩容后所有迭代器 / 引用失效；`erase` 返回下一有效迭代器（用 `it = v.erase(it)` 而非 `it++`）。

## 算法

`<algorithm>` 与 `<numeric>` 提供与容器解耦的泛型操作：

- `std::sort` 是**内省排序（introsort）**：快排为主，递归过深转堆排，小子区间用插入排序——最坏 O(n log n)，非稳定（稳定需求用 `stable_sort`）。
- `std::find` / `std::copy` / `std::transform` / `std::reduce`（C++17 并行策略）等。

## 现代字符串 / 视图类型

- `std::string_view`（C++17）：**不拥有**字符缓冲的只读视图，避免为「读一段字符串」而拷贝 `std::string`，函数参数首选。
- `std::span`（C++20）：连续序列的零成本视图（数组 / vector  alike），统一「一段 T」的接口。
- `std::string` 本身仍拥有并管理内存（小字符串优化 SSO 时存栈上）。

## 与 C 的对照

C 没有容器与算法（[数组与字符串](/docs/CS/C/Array_String.md) 靠手管），STL 把这套泛型设施做成零成本抽象——模板实例化后与手写循环等价。

## Links

- [C++](/docs/CS/C++/C++.md)
- [模板](/docs/CS/C++/Templates.md)
- [内存与 new/delete](/docs/CS/C++/Memory.md)
- [初始化](/docs/CS/C++/Init.md)
- [C 数组与字符串](/docs/CS/C/Array_String.md)

## References

1. [cppreference: Containers](https://en.cppreference.com/w/cpp/container)
1. [cppreference: Algorithms](https://en.cppreference.com/w/cpp/algorithm)
