## Introduction

C++11 引入的**右值引用（rvalue reference）**与**移动语义**是语言自模板之后最大的一次工程性升级：它让「资源所有权的廉价转移」成为可能，使返回大对象、向容器插入元素、智能指针传递不再被迫深拷贝。

## 值类别（value categories）

表达式按值类别分三类，注意它描述的是**表达式**，不是变量：

- **lvalue**：有身份、可取地址（变量名、返回左值引用的函数调用、`*p`）。
- **prvalue（纯右值）**：临时对象、字面量、返回非引用的值——即将被销毁的「值」。
- **xvalue（将亡值）**：既有身份又即将被移动的资源（如 `std::move(x)` 的结果、`static_cast<T&&>(x)`）。

glvalue = lvalue + xvalue；rvalue = prvalue + xvalue。

## 右值引用与 std::move

`T&&` 绑定到右值；`std::move` 只是把左值**强制转换**为右值引用，**本身不移动任何东西**——真正的动作发生在接收方的移动构造 / 移动赋值里。

```cpp
std::vector<int> a = make_big();
std::vector<int> b = std::move(a);   // a 的内部指针被「偷走」，a 进入有效但未指定状态（通常为空）
```

## 移动构造与 Rule of Five

- 资源管理类通常需显式定义：析构、拷贝构造、拷贝赋值、移动构造、移动赋值（**Rule of Five**）。
- 移动操作应标记为 `noexcept`：标准库容器在扩容 / `std::vector` rehash 时，只有移动构造 `noexcept` 才会真正移动，否则退回拷贝（保证强异常安全）。

## 完美转发（perfect forwarding）

引用折叠规则：`T& &&` → `T&`，`T&& &&` → `T&&`。`std::forward<T>(x)` 据此把参数**原样**转发（左值仍左值、右值仍右值），是实现泛型工厂 / 包装器的关键。

```cpp
template<class T, class... Args>
std::unique_ptr<T> make_unique(Args&&... args) {
    return std::unique_ptr<T>(new T(std::forward<Args>(args)...));
}
```

## 拷贝消除（copy elision）

- **RVO / NRVO**：返回局部对象时编译器可省略拷贝 / 移动（C++17 起对 prvalue 返回值**强制**省略，连移动构造都不调用）。
- 因此「返回大对象」在现代 C++ 已几乎零成本，不必为它写 `std::move`（反而可能阻止 RVO）。

## Links

- [C++](/docs/CS/C++/C++.md)
- [智能指针](/docs/CS/C++/SmartPtr.md)
- [初始化](/docs/CS/C++/Init.md)
- [Rust 所有权](/docs/CS/Rust/Rust.md)

## References

1. [cppreference: Value categories](https://en.cppreference.com/w/cpp/language/value_category)
1. [cppreference: std::move](https://en.cppreference.com/w/cpp/utility/move)
