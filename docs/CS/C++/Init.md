## Introduction

C++ 的初始化规则是公认最易踩坑的角落之一：同一句声明在不同语境下可能触发值初始化、拷贝初始化或直接初始化，产生截然不同的结果。`{}` 统一初始化（C++11）试图收敛混乱，但也带来新的歧义。

## Several Forms of Initialization

| 形式 | 语法 | 说明 |
|------|------|------|
| 默认初始化 | `T x;` | 内置类型**不初始化**（值不确定）；类类型调默认构造 |
| 值初始化 | `T x{};` / `new T()` | 内置类型零初始化；类类型调默认构造 |
| 直接初始化 | `T x(args);` | 调匹配构造 |
| 拷贝初始化 | `T x = y;` | 允许非 explicit 构造 / 转换 |
| 列表初始化 | `T x{a,b};` | 优先匹配 `initializer_list` 构造；**禁止窄化** |
| 聚合初始化 | `T x = {..};`（聚合类） | 按成员顺序填充，无构造参与 |

## Uniform Initialization `{}`

- C++11 起，`{}` 可用于几乎任何初始化，且对内置类型**拒绝窄化转换**（`int x{3.5};` 编译报错，而 `int x = 3.5;` 静默截断）。
- 歧义点：当类同时有 `initializer_list` 构造与普通构造时，`{}` 优先匹配 `initializer_list`，常导致意外（如 `std::vector<int> v{10, 20};` 是 2 个元素，而非 10 容量）。

## The Most Vexing Parse

```cpp
Widget w();        // ❌ 这声明了一个返回 Widget 的函数，不是对象！
Widget w{};        // ✅ 值初始化对象
Widget w(foo());   // ❌ 可能被解析为函数声明；用 {} 或额外括号化解
```

## Differences Between `=`, `()`, and `{}`

- `auto x = {1,2};` 推导为 `std::initializer_list<int>`，而非你以为的容器。
- `auto x{1};` 在 C++17 推导为 `int`（早期版本规则不同，注意版本）。
- `explicit` 构造函数禁止拷贝初始化（`=`）与隐式转换，但允许直接 / 列表初始化。

## Designated Initializers (C++20)

```cpp
struct Pt { int x, y; };
Pt p{.x = 1, .y = 2};   // 按设计器名赋值，成员须按声明序
```

## Links

- [C++](/docs/CS/C++/C++.md)
- [移动语义](/docs/CS/C++/Move.md)
- [标准库](/docs/CS/C++/STL.md)
- [未定义行为](/docs/CS/C++/UB.md)

## References

1. [cppreference: Initialization](https://en.cppreference.com/w/cpp/language/initialization)
