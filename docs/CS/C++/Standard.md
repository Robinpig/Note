## Introduction

C++ 自 1998 年首次 ISO 标准化后，演化节奏明显加快：C++11 是一次「现代化」大版本，此后基本保持三年一版。理解每个标准带来了什么，是判断「这段代码依赖哪版特性」「该开哪个 `-std=`」的基础（对照 [C 标准演进](/docs/CS/C/Standard.md) 与 [Java 升级史](/docs/CS/Java/JDK/Upgrade.md)）。

## 版本与特性线

| 版本 | 代号 | 标志特性 |
|------|------|---------|
| C++98 / C++03 | 第一版 / 缺陷修复 | 模板、STL、`string`、IO 流 |
| C++11 | C++0x | **现代 C++ 起点**：`auto`、范围 for、右值引用与移动、`unique_ptr` / `shared_ptr`、lambda、`constexpr`、`nullptr`、线程库、强类型枚举 |
| C++14 | — | 泛型 lambda、返回类型推导、放宽 `constexpr`、二进制字面量 |
| C++17 | — | 结构化绑定、`if` / `switch` 带初始化、内联变量、`std::string_view`、`std::filesystem`、折叠表达式、**强制拷贝消除**、`std::optional` / `variant` / `any` |
| C++20 | — | **大版本**：Concepts、Ranges、`<chrono>` 日历、Modules、`coroutines`、`operator<=>`（三路比较）、`constexpr` 容器与 `std::vector`、`std::span`、`std::jthread` |
| C++23 | — | `std::print` / `std::format` 增强、`std::mdspan`、`std::flat_map` / `flat_set`、推导 `this`（`[this]` 显式对象形参）、多维下标、`import std`、修复 `std::ranges` |
| C++26 | 进行中 | Contracts（合约）、静态反射、`std::execution`（senders / receivers）、增强包扩展、更好的人机错误处理（仍在 TS / 草案阶段） |

## 编译与 ABI

- 用 `-std=c++11/14/17/20/23` 显式指定；不指定时 GCC / Clang 默认可能停留在较旧标准（GCC 11 起默认 C++17）。
- **ABI 稳定性**：在 Linux / macOS 上 GCC / Clang 遵循 Itanium ABI，**跨标准保持二进制兼容**（老 .so 仍可链接）；MSVC 则每个工具集可能破坏 ABI，需统一工具链版本。
- `inline` 变量（C++17）解决了「头文件里放 constexpr / 常量定义导致 ODR 重复」的老问题。

## 选型建议

- 新项目直接以 **C++20** 起步（Concepts + Ranges + coroutines 收益最大）；维护老代码按需局部采用 C++17 特性（`string_view`、结构化绑定几乎零风险）。
- 在 [模板](/docs/CS/C++/Templates.md) 里用 Concepts 取代 SFINAE，可读性显著提升。

## Links

- [C++](/docs/CS/C++/C++.md)
- [模板与 Concepts](/docs/CS/C++/Templates.md)
- [C 标准演进](/docs/CS/C/Standard.md)
- [Java 升级史](/docs/CS/Java/JDK/Upgrade.md)

## References

1. [cppreference: C++ compiler support](https://en.cppreference.com/w/cpp/compiler_support)
1. [ISO C++ Standard](https://isocpp.org/std)
