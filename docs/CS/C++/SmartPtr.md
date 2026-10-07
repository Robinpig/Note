## Introduction

C++ 没有 GC，资源靠 **RAII**（构造获取、析构释放）管理。智能指针是 RAII 在堆对象上的标准实现：把 `new` / `delete` 配对封装进对象生命周期，使异常安全与多返回路径下的资源释放变得自动。

## std::unique_ptr：独占所有权

- 独占语义，**不可拷贝、可移动**；大小通常等于一个裸指针。
- 支持自定义删除器（deleter 作为类型参数或运行时对象）、数组特化 `unique_ptr<T[]>`。
- 表达「这是个对象、且只有我拥有它」的语义，是默认首选。

```cpp
auto p = std::make_unique<Widget>(arg);   // 优先 make_unique：异常安全、无裸 new
std::vector<std::unique_ptr<Base>> items; // 多态对象容器
```

## std::shared_ptr：共享所有权

- 引用计数；每次拷贝 `use_count++`，析构 `use_count--`，归零时释放对象。
- 计数与弱引用计数存放于**控制块（control block）**：
  - `std::make_shared<T>` 将对象内存与控制块**一次分配**（更省、更省 cache），但对象与控制块同生命周期（即便有 `weak_ptr` 长期持有，对象内存也延迟释放）。
  - `shared_ptr<T>(new T)` 则两次分配。
- **线程安全**：控制块的引用计数增减是原子的；但**被指向的对象本身不是线程安全的**，多线程读写仍需额外同步。
- `enable_shared_from_this`：在成员函数内安全产出指向自身的 `shared_ptr`，避免从 `this` 裸造第二个控制块。

## std::weak_ptr：打破循环

- 不增加引用计数，用于观察 `shared_ptr` 而不延长其生命周期。
- 用前须 `lock()` 提升为 `shared_ptr`（可能为空），典型场景：缓存、观察者、父子关系中「父持有子、子弱引用父」。

```cpp
std::weak_ptr<Cache> w = cache;
if (auto s = w.lock()) s->use();   // 提升失败 => s 为空，避免访问已销毁对象
```

## 常见陷阱

- **循环引用**导致内存泄漏：`A↔B` 都用 `shared_ptr` 互指，计数永远不为 0——一端改 `weak_ptr`。
- **按值传 `shared_ptr`** 会无谓增减计数；只读观察应传 `const shared_ptr<T>&` 或 `const T&`。
- **`this` 直接构造 `shared_ptr`** 会创建独立控制块，造成双重释放——用 `shared_from_this()`。

## 与 C / Rust 的对照

- C 用 `malloc` / `free` 手动管理（见 [C 的 malloc](/docs/CS/C/malloc.md)），无 RAII 保护。
- Rust 把所有权 / 借用在编译期强制（见 [Rust](/docs/CS/Rust/Rust.md)），连 `shared_ptr` 这类运行期计数结构都不需要。

## Links

- [C++](/docs/CS/C++/C++.md)
- [移动语义](/docs/CS/C++/Move.md)
- [内存与 new/delete](/docs/CS/C++/Memory.md)
- [未定义行为](/docs/CS/C++/UB.md)
- [C 的 malloc](/docs/CS/C/malloc.md)

## References

1. [cppreference: memory (smart pointers)](https://en.cppreference.com/w/cpp/memory)
1. [cppreference: RAII](https://en.cppreference.com/w/cpp/language/raii)
