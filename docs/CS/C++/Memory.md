## Introduction

C++ 的内存管理位于「手动 `malloc`」与「带 GC 的语言」之间：它把**分配**与**构造**拆成两个正交步骤，并提供了可替换的分配器抽象。理解 `new` / `delete` 的真实动作，是写好 [智能指针](/docs/CS/C++/SmartPtr.md)、避免泄漏与 UB 的前提。

## The Two Phases of new-expression

`T* p = new T(args);` 实际发生：

1. 调用 `operator new(size)` 分配**原始、未构造**的内存（底层通常走 `malloc`）；
2. 在该内存上调用 `T` 的构造函数。

`delete p;` 反之：先调析构函数，再调 `operator delete`。**只 `free` 不析构、或只析构不 `free` 都是 UB**。

## placement new and Custom operator new

- **placement new** `new (buf) T` 在已分配内存上构造对象，不分配——用于内存池、定制布局（如 [muduo](/docs/CS/C++/muduo.md) 的对象池、ring buffer）。
- 可重载全局 / 类级 `operator new` / `operator delete`，实现专属分配策略（如高频小对象用池化分配器）。

## Allocator Model (allocator)

- `std::allocator`（经典接口：`allocate` / `deallocate` / `construct` / `destroy`）让容器与内存来源解耦。
- C++17 起 `std::pmr`（**P**olymorphic **M**emory **R**esource）：`std::pmr::memory_resource` + `std::pmr::polymorphic_allocator`，运行时切换内存池（monotonic_buffer / pool / 默认 `new_delete_resource`），`std::pmr::vector` 即使用它的容器。
- 自定义分配器需满足可拷贝、相等性语义（`a1 == a2` 表示可释放对方分配的内存）。

```cpp
std::pmr::monotonic_buffer_resource pool;
std::pmr::vector<int> v{&pool};   // 该 vector 从 pool 取内存，析构后整体回收
```

## new[] / delete[]

数组版本 `new T[n]` 在分配区额外记录元素个数（供 `delete[]` 知道调多少次析构）；`new[]` 必须与 `delete[]` 配对，否则 UB。实践中**优先用 `std::vector` / 容器**替代裸数组。

## Relationship with C / Smart Pointers

- 比 [C 的 malloc](/docs/CS/C/malloc.md) 多了构造 / 析构环节、类型安全（不需 `(T*)` 强转），但错误使用同样是 UB。
- 现代 C++ 的答案是 [智能指针](/docs/CS/C++/SmartPtr.md) 与容器，把 `new` / `delete` 藏进 RAII。

## Links

- [C++](/docs/CS/C++/C++.md)
- [智能指针](/docs/CS/C++/SmartPtr.md)
- [未定义行为](/docs/CS/C++/UB.md)
- [C 的 malloc](/docs/CS/C/malloc.md)
- [并发与内存模型](/docs/CS/C++/Concurrency.md)

## References

1. [cppreference: new-expression](https://en.cppreference.com/w/cpp/language/new)
1. [cppreference: std::pmr](https://en.cppreference.com/w/cpp/memory)
