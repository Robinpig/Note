## Introduction

`&T` 意味着不可变共享——这是借用检查的基石，也是内部可变性要绕过的唯一规则。Rust 的答案不是"关掉检查"，而是**把检查从编译期搬到运行期、或者把可变性藏进一个原语里**：`Cell` 系让值"进出"而不产生引用，`RefCell` 把一写多读的规则推迟到运行时 panic，`Mutex` / 原子把它升级成跨线程版本。本篇以 `UnsafeCell` 为根，把这四种形态放进同一张图，并回答那个真正的问题：**什么场景该用哪一种**。

各类型作为智能指针的定位在 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)（本篇只引用不重述其 API 表），内存序侧在 [Atomics](/docs/CS/Rust/Atomics.md)，别名模型（Stacked / Tree Borrows）与 unsafe 边界在 [Unsafe](/docs/CS/Rust/Unsafe.md)。

## UnsafeCell Is the Root

`UnsafeCell<T>` 是标准库里唯一允许"通过 `&T` 获得 `&mut T`"的类型，其它一切内部可变性最终都经由它：

```rust
pub struct UnsafeCell<T> { value: T }
impl<T> UnsafeCell<T> {
    pub fn get(&self) -> *mut T { &self.value as *const T as *mut T }  // 唯一入口
}
```

它的规则只有一条，但这条规则是**编译器与你的契约**：`UnsafeCell` 内部的值可以在有 `&UnsafeCell<T>` 的情况下被修改，**但你必须保证同一时刻不存在引用冲突**（两个 `&mut` 或一个 `&mut` 与若干 `&`）。编译器因为 `get()` 返回裸指针而放行；正确性全靠调用方论证——这正是 [Unsafe](/docs/CS/Rust/Unsafe.md) 里"契约边界"的定义。

`UnsafeCell` 本身不 `Sync`：跨线程共享它要求你自己证明互斥（`unsafe impl Sync`，见下）。它也影响布局与优化：含 `UnsafeCell` 的字段编译器不会做跨访问的优化假设，这是 [内存布局](/docs/CS/Rust/Memory_Layout.md) 里"布局的代价"的一例。

## The Four Implementations

| 类型 | 检查时机 | 跨线程 | 失败方式 | 产生引用？ |
| :--- | :--- | :--- | :--- | :--- |
| `Cell<T>` | 编译期（`T: Copy`） | 否 | 编译错误 | 否（值进出） |
| `RefCell<T>` | **运行期** | 否 | **panic** | 是 |
| `Mutex<T>` | 运行期（阻塞） | 是 | 阻塞 / 中毒 | 是 |
| 原子类型 | 硬件 | 是 | 无（CAS 重试） | 否（值进出） |

### Cell: The Copy Route

`Cell<T>` 的 `size_of` 实测与 `T` 相同（`Cell<i32>` = 4 字节，零包装成本）。`get` / `set` 要求 `T: Copy`，否则编译器拦下（实测 `error[E0599]` + `String: Copy` 未满足）。非 `Copy` 类型走 `take()`（取走并留 `Default::default()`）/ `replace()` / `into_inner()`——值整体进出、任何时刻不存在悬出的引用，所以 `Cell` 全程不需要借用标志，也不需要 `unsafe`。

**适用**：单线程、`Copy` 或可"整体替换"的小状态（计数器、`Option<SmallEnum>`、标记位）。性能四兄弟里最好——`get` 通常就是一条 load。

### RefCell: The Dynamic Borrow Check

`RefCell<T>` 在头部放一个 `isize` 借用标志：正数记共享借用数，`-1` 表示独占借用。`borrow` / `borrow_mut` 检查标志，违反 aliasing 规则时**当场 panic**：

```rust
use std::cell::RefCell;
fn main() {
    let c = RefCell::new(5);
    let _r1 = c.borrow();               // 共享借用 +1
    let _r = c.borrow_mut();            // panic: RefCell already borrowed
}
```

非 panic 版本是 `try_borrow` / `try_borrow_mut`，返回 `Result<Ref<T>, BorrowError>`（Display 同为 "RefCell already borrowed"）。`Ref` / `RefMut` 是 RAII guard：drop 时把标志复位——**所以 guard 的临时变量生命周期是经典坑**（`c.borrow().field` 在语句结束就放锁，`if c.borrow().is_empty() { c.borrow_mut().push(1) }` 看起来安全实则两次借用不重叠，反而 `let x = c.borrow(); ...` 持有太久才会 panic）。

**适用**：单线程、需要"隔着 `&` 改"、且改的触发点编译器看不见（典型：图 / 树结构里 `&self` 方法要改子节点；缓存；`Rc<RefCell<T>>` 共享可变）。

### Mutex: The Cross-Thread Counterpart

`Mutex<T>` 把同一机制升级到跨线程：`lock()` 返回 `LockResult<MutexGuard<T>>`，guard 析构时解锁。三条与 `RefCell` 的关键差异：

1. **失败方式是阻塞而非 panic**。`RefCell` 的标志在单线程内被同步代码维护，违规一定是 bug；`Mutex` 的竞争在别的线程，阻塞是正常语义。
2. **中毒（poisoning）**：持锁线程 panic 后，锁标记为 poisoned，后续 `lock()` 返回 `Err(PoisonError)`——因为你不能假设被 panic 打断的临界区留下了什么。要忽略中毒用 `unwrap_or_else(|e| e.into_inner())`，但那是显式决定"我知道数据可能不一致"。
3. **async 里的 guard 不能跨 `.await`**。`std::sync::MutexGuard` 不是 `Send`（跨 await 会导致锁跨线程持有），这是 [Async_Runtime](/docs/CS/Rust/Async_Runtime.md) 的典型事故；跨 await 要 `tokio::sync::Mutex`（异步锁，语义与阻塞锁不同）。

`RwLock` 是同一家族的读者写者版：多读单写，`read` guard 共享、`write` guard 独占。选型判据：读远多于写且临界区短用 `RwLock`，否则 `Mutex` 通常更快（读写锁的标志本身就是一次原子 RMW，见 [Atomics](/docs/CS/Rust/Atomics.md)）。

### Atomics: Interior Mutability Without References

原子类型是内部可变性的第四种形态，但路线完全不同：**值进出、不产生引用**，与 `Cell` 同构而非与 `RefCell` 同构。`AtomicUsize::load()` 像 `Cell::get()`（取副本），`store()` 像 `set()`。差别在跨线程：原子把可见性顺序（[Atomics](/docs/CS/Rust/Atomics.md) 的五档）也管了，而 `Cell` 连 `Sync` 都不实现。

一个容易忽略的推论：**`Cell<T>` 不实现 `Sync`，所以 `Cell` 永远不能跨线程共享**——想跨线程就升级到原子类型或 `Mutex`。`static` 上要用 `Cell` 只能 `thread_local!`。

## OnceCell, LazyLock, and Friends

"一次性初始化"是内部可变性的特例场景，标准库给了专用件：

| 类型 | 版本 | 线程 | 语义 |
| :--- | :--- | :--- | :--- |
| `OnceCell<T>` | 1.70.0 | 单线程 | `get_or_init` 保证只初始化一次；`set` 重复返回 `Err` |
| `LazyLock<T>` | 1.80.0 | 单线程 | 首次访问时初始化，`Deref` 到 `T` |
| `OnceLock<T>` | 1.70.0 | **跨线程** | `OnceCell` 的 `Sync` 版 |
| `LazyLock` 的跨线程版 | 1.80.0 | **跨线程** | `static` 延迟初始化的标准答案 |
| `OnceBox<T>` | 仍 unstable | 跨线程 | 省一次 `Option` 判空，未稳定 |

`static` 延迟初始化因此有了标准形状：`static CONFIG: LazyLock<Config> = LazyLock::new(|| Config::load());`——线程安全、无 `once_cell` 依赖、初始化只跑一次。要处理"初始化可能失败"用 `OnceLock<Result<T, E>>` 或 `get_or_try_init`。

## The Sync Question: Who Decides Thread Safety

`Cell` / `RefCell` **不实现 `Sync`**（`!Sync` 是 auto trait 的负向结论：含 `UnsafeCell` 且无同步机制）。所以 `Rc<RefCell<T>>` 天然单线程，`Arc<RefCell<T>>` 甚至编不过（`RefCell<T>` 不是 `Sync`，`Arc` 要求 `T: Send + Sync`）。跨线程共享可变的正确组合是：

| 场景 | 用 |
| :--- | :--- |
| 简单计数器 / 标志 | 原子类型 |
| 复合结构跨线程改 | `Arc<Mutex<T>>` |
| 读多写少 | `Arc<RwLock<T>>` |
| 一次性初始化 | `OnceLock` / `LazyLock` |
| 自定义无锁结构 | `UnsafeCell` + `unsafe impl Sync`（**论证落你头上**） |

最后一行是唯一需要手写 unsafe 的路，也是 [Unsafe](/docs/CS/Rust/Unsafe.md) 里 `struct Global(UnsafeCell<T>)` 那个例子的场景：你向编译器声明"我已保证互斥"，编译器不再过问。这个声明写错就是数据竞争，而数据竞争在 Rust 里是 UB 不是竞态——`loom`（[Atomics](/docs/CS/Rust/Atomics.md)）是少数能帮你验证的工具。

## Verification: Miri and the Alias Models

内部可变性是"引用规则被显式绕开"的机制，所以也是 miri 最有价值的场景之一：miri 在 Stacked / Tree Borrows 别名模型下解释执行，能抓出 `Cell::get` 返回指针被长期持有、`RefCell` guard 通过 `Ref::clone` 泄漏出的 `&T` 在 `borrow_mut` 后仍被使用一类错误。装 miri 要 nightly（[工具链](/docs/CS/Rust/Tooling.md)），别名模型的现状见 [Unsafe](/docs/CS/Rust/Unsafe.md)。

运行期可用的轻量替代：`RefCell` 的借用标志在 debug 构建总是开着，`RUSTFLAGS="-Z debug-assertions"` 一类的设置不影响它；真正的问题是**release 下 panic 消息仍在**（`RefCell` 的运行期检查不进 `debug_assertions` 门控），所以"release 没崩"不代表没有借用冲突，只代表这次没触发。

## Selection Checklist

按这个顺序问自己，第一个"是"就是答案：

1. **跨线程吗？** → 原子（简单值）/ `Mutex`（复合）/ `RwLock`（读多写少）/ `OnceLock`（一次性）。
2. **要产生引用吗？** → 要：`RefCell`（单线程）；不要（值进出）：`Cell`（`Copy`）/ `take-replace`（非 `Copy`）。
3. **"一次性初始化"吗？** → `OnceLock` / `LazyLock`，别手写 `OnceCell` + `Option`。
4. **上面都不合适、且你能写出不变式吗？** → `UnsafeCell` + `unsafe impl Sync`，并配 loom 与 miri。
5. **还是不合适？** → 大概率是设计问题：`&mut self` 能被借用检查证明的场合，比任何运行期检查都便宜。

## Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | `RefCell` guard 持有太久 | `already borrowed` panic | 缩小 guard 作用域；`let x = c.borrow();` 别横跨整个函数 |
| 2 | `RefCell` guard 临时变量早退 | 锁提前放掉，后续读到不一致状态 | 显式 `let g = ...;` 绑定 |
| 3 | `Arc<RefCell<T>>` | `RefCell<T>: Sync` 不满足，编译错误 | `Arc<Mutex<T>>` |
| 4 | `std::sync::Mutex` guard 跨 await | not Send / 锁跨线程 | `tokio::sync::Mutex` 或缩临界区 |
| 5 | 忽略锁中毒 | `PoisonError` 到处传播 | 决定"忽略中毒"就 `unwrap_or_else(\|e\| e.into_inner())` |
| 6 | `Cell` 用在 static 上 | 无法跨线程 / 编译错误 | `thread_local!` 或原子 |
| 7 | 手写 `unsafe impl Sync` 无同步 | 偶发数据竞争（UB） | 先回到 1–3 步；真要用就 loom + miri |
| 8 | `Cell::get` 的指针长期持有 | miri alias 报错 | `get` 出的值当副本用，别存 |

## Links

- [智能指针](/docs/CS/Rust/Smart_Pointers.md)
- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [Atomics](/docs/CS/Rust/Atomics.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [Async_Runtime](/docs/CS/Rust/Async_Runtime.md)
- [工具链](/docs/CS/Rust/Tooling.md)

## References

1. [`std::cell` module docs](https://doc.rust-lang.org/std/cell/index.html)
2. [`std::cell::UnsafeCell`](https://doc.rust-lang.org/std/cell/struct.UnsafeCell.html)
3. [`std::cell::RefCell`](https://doc.rust-lang.org/std/cell/struct.RefCell.html)
4. [`std::sync::OnceLock`](https://doc.rust-lang.org/std/sync/struct.OnceLock.html)
5. [`std::sync::LazyLock`](https://doc.rust-lang.org/std/sync/struct.LazyLock.html)
6. [The Rustonomicon — Interior Mutability](https://doc.rust-lang.org/nomicon/unchecked-uninit.html)
