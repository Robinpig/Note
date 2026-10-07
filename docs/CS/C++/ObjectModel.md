## Introduction

C++ 的对象模型决定了「一个对象在内存里长什么样」，以及虚函数、`dynamic_cast`、`typeid` 是如何找到正确实现的。理解它是读懂 RAII、智能指针、RTTI，以及和 C / Rust / Go 对象布局差异的前提。

## Data Member Layout

- 同一 **access specifier** 下的非静态数据成员按声明顺序在对象内递增排列；不同 access 段之间的相对顺序标准未强制，但主流编译器（GCC / Clang / MSVC）实际仍按声明顺序排布。
- 编译器按各成员对齐要求插入填充（padding），对象大小 ≥ 各成员大小之和；空类大小不为 0（通常占位 1 字节）。
- **空基类优化（EBO）**：空基类不占用派生类空间（少数情况除外），`boost::noncopyable`、`std::allocator` 等据此瘦身。

```cpp
struct A { char c; int i; };   // sizeof(A)==8：c 后填 3 字节对齐 i
struct Empty {};               // sizeof(Empty)==1
struct B : Empty { int x; };   // sizeof(B)==4（EBO 生效，Empty 不占空间）
```

## Virtual Function Table (vtable / vptr)

带虚函数的类（多态类）由编译器插入一个隐藏的 **vptr**（通常位于对象起始处，offset 0），指向该类型的 **vtable**：

- vtable 存放虚函数指针、指向 `std::type_info` 的指针（支撑 `typeid` / `dynamic_cast`），以及多继承 / 虚继承所需的调整信息（thunk / virtual base offset）。
- **单继承**：派生类 vtable 复用基类布局，被重写的虚函数槽位就地替换为派生实现，新增虚函数追加在末尾。
- **多继承**：派生类含多个 vptr（每个有虚函数的基类一个），调用第二个基类虚函数时需要 this 指针调整（thunk）。
- **虚继承**：共享虚基类的偏移在 vtable 中记录，避免菱形继承下基类子对象重复。

> 具体布局遵循 **Itanium C++ ABI**（Linux / macOS 上 GCC、Clang 遵守）；MSVC 的细节略有差异，但 vptr + vtable 的通用模型一致。

## Virtual Dispatch and Its Cost

```cpp
struct Base { virtual void f(); virtual ~Base(); };
struct Der : Base { void f() override; };
Base* p = new Der;
p->f();          // 通过 p 的 vptr 找到 Der::f，一次额外间接寻址
```

- 虚调用 = 一次指针间接 + 可能的 cache miss，**无法被内联 / 去虚化**（除非编译器能静态确定类型）。
- **析构函数应为 virtual**：通过基类指针 delete 派生对象时，非虚析构只调基类析构，导致派生部分泄漏（UB）。

## Relationship with RTTI

`dynamic_cast` 与 `typeid` 都读取 vtable 内嵌的 `std::type_info`（见 [RTTI](/docs/CS/C++/RTTI.md)）。只有多态类才有可用 RTTI；非多态类型 `dynamic_cast` 在编译期即被拒。

## Links

- [C++](/docs/CS/C++/C++.md)
- [RTTI](/docs/CS/C++/RTTI.md)
- [C 结构体布局](/docs/CS/C/Struct.md)

## References

1. [Itanium C++ ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi.html)
1. [cppreference: Object model](https://en.cppreference.com/w/cpp/language/object)
