## Introduction

模板是 C++ 泛型与零成本抽象的核心机制：函数和类可以参数化类型 / 非类型 / 模板参数，在**实例化点**由编译器生成具体代码。它既是 STL 的基石，也是现代元编程的工具。

## Basic Form

```cpp
template<class T>
T max(T a, T b) { return a < b ? b : a; }   // 模板参数推导：max(1,2) => T=int
```

- 类模板参数通常不能推导（C++17 起类模板构造可部分推导），函数模板可全推导。
- 非类型模板参数（NTTP）：整型、指针、引用，以及 C++20 起的浮点与类类型字面量。

## Instantiation and Code Bloat

- **隐式实例化**：首次以某组实参使用时生成代码；**显式实例化** `template class Vector<int>;` 可在 .cpp 中集中生成以缩短编译时间（分离编译技巧）。
- 每套实参生成一份独立机器码，**过度特化导致二进制体积膨胀**（code bloat）——这是模板的隐性成本，与 Java 类型擦除、Go 单态化形成对照。

## SFINAE and Type Traits

「**替换失败不是错误**」：模板实参替换若产生非法类型，只将该重载从重载集移除，不报错。据此可用 `std::enable_if` + `<type_traits>` 做编译期分支。

```cpp
template<class T, std::enable_if_t<std::is_integral_v<T>, int> = 0>
void f(T) { /* 仅整型可调用 */ }
```

## Variadic Templates and Fold Expressions

```cpp
template<class... Ts>
auto sum(Ts... ts) { return (ts + ... + 0); }   // C++17 折叠表达式
```

## Concepts（C++20）

Concepts 把「模板实参必须满足的约束」显式写成类型级谓词，彻底取代 SFINAE 的晦涩写法，错误信息也大幅改善：

```cpp
template<std::integral T>
T gcd(T a, T b) { while (b) { T t = b; b = a % b; a = t; } return a; }
```

## CRTP: Static Polymorphism

奇异递归模板模式：派生类作为基类模板参数，`Base<Der>` 可在编译期向下转型调用派生实现，实现「静态虚函数」（无 vtable 开销）。常见于 `std::enable_shared_from_this`、Eigen 表达式模板。

## Links

- [C++](/docs/CS/C++/C++.md)
- [对象模型](/docs/CS/C++/ObjectModel.md)
- [C++ 标准演进](/docs/CS/C++/Standard.md)

## References

1. [cppreference: Templates](https://en.cppreference.com/w/cpp/language/templates)
1. [cppreference: Constraints and concepts](https://en.cppreference.com/w/cpp/language/constraints)
