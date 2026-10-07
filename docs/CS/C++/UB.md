## Introduction

**未定义行为（Undefined Behavior, UB）**指标准对「程序做了某件非法的事」之后的结果**不作任何保证**——它可能崩溃、可能悄无声息地给出错误答案、也可能在不同优化级别下表现完全不同。C++ 的 UB 面比多数语言更广，正是因为把「不检查」换成了「零运行时成本」。

## 常见雷区

| 行为 | 后果 |
|------|------|
| 数组 / 容器越界访问 | 读脏数据、踩内存、崩溃 |
| 解引用空指针 / 悬垂指针（use-after-free） | 段错误或更隐蔽的破坏 |
| **有符号整数溢出** | UB（注意：Java / C# 会回绕或抛异常，C++ 不保证） |
| 数据竞争（无同步的多线程写） | 不可复现的错误 |
| 迭代器失效后仍使用 | 读写越界 |
| 双重 `delete` / 释放后读写 | 堆破坏 |
| 左移位数 ≥ 类型宽度 | UB |
| 违反 ODR（同一对象多重定义） | 链接或运行时诡异行为 |
| 读取未初始化的非静态变量 | 不确定值被使用 |

## 为何 C++ 容忍 UB

核心取舍是**性能与零成本**：若每次数组访问都插入边界检查，就不再是「接近手写 C」的语言。代价是安全责任完全交给程序员——这也是 [智能指针](/docs/CS/C++/SmartPtr.md) 与 RAII 存在的理由。

## 防御手段

- 编译期：`-Wall -Wextra -Werror`，开启静态分析。
- 运行期：`-fsanitize=address,undefined`（ASan / UBSan）捕获越界、泄漏、溢出、数据竞争。
- 语言层：优先用 `std::vector` / 视图类型替代裸数组；用 [智能指针](/docs/CS/C++/SmartPtr.md) 替代裸 `new`；C++20 / 26 的 **Contracts** 正逐步把前置条件变成可检查的一等公民。
- 与 [C 的 UB](/docs/CS/C/UB.md) 同源（共享大量底层陷阱），但 C++ 多了 ODR、迭代器失效等特有项。

## Links

- [C++](/docs/CS/C++/C++.md)
- [智能指针](/docs/CS/C++/SmartPtr.md)
- [内存与 new/delete](/docs/CS/C++/Memory.md)
- [并发与内存模型](/docs/CS/C++/Concurrency.md)
- [C 的未定义行为](/docs/CS/C/UB.md)

## References

1. [cppreference: Undefined behavior](https://en.cppreference.com/w/cpp/language/ub)
1. [A Guide to Undefined Behavior (Regehr)](https://blog.regehr.org/archives/213)
