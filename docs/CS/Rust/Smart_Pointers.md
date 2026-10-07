## Introduction

智能指针（smart pointer）不是"会自己释放的裸指针"这么简单——它封装了三件事：**所有权语义**（谁能移动、谁能拷贝、拷贝意味着什么）、**元数据**（长度、vtable、强弱计数，决定指针本身多大、指向什么）与**析构职责**（何时调用 `drop_in_place`、何时归还内存）。C++ 把这些揉进 `shared_ptr` 一个类，Rust 把它们拆成一组正交的类型：`Box` / `Rc` / `Arc` / `Weak` 管所有权与计数，`Cell` / `RefCell` / `UnsafeCell` 管内部可变性，`Mutex` / `RwLock` 管跨线程，`Once` / `OnceLock` / `LazyLock` 管一次性初始化，`Deref` 让这一切对方法调用透明。选错类型的代价在 C++ 里通常是运行期泄漏或 data race，在 Rust 里多数被提前到编译期诊断——本篇的主线就是这张选型地图，以及每个节点"为什么必然如此、边界在哪"。

本篇只讲指针类型本身。析构顺序、dropck 与 `ManuallyDrop` 见 [Drop](/docs/CS/Rust/Drop.md)；`Send` / `Sync` 推理与并发选型见 [Concurrency](/docs/CS/Rust/Concurrency.md)；字段重排与 `repr` 保证见 [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)；裸指针与 provenance 见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)；分配器替换（`#[global_allocator]` + `mimalloc` / `tikv-jemallocator`）只在 `Box` 一节提一句，正文在 [Performance](/docs/CS/Rust/Performance.md)。

> [!NOTE]
> 本篇所有编译与运行断言实测于 `rustc 1.98.1 (48a229cea 2026-09-01)`、目标三元组 **aarch64-apple-darwin**、`--edition 2024`、`-O`；标注"自 1.99.0 起"的条目本机跑不出来，依据 1.99.0 发布说明与当前 stable 文档，单独声明。

## The Family at a Glance

`size_of` 为本机实测（元素取 `i32`，指针宽度 8 字节）：

| 类型 | 语义 | Clone 成本 | size 实测 | 线程共享 |
| :--- | :--- | :--- | :--- | :--- |
| `Box<i32>` | 单一所有权的堆值 | 移动 O(1)；`T: Clone` 时 Clone 是深拷贝堆内容 | 8 | 随 `T` |
| `Rc<i32>` | 引用计数共享 | 非原子 `++` | 8 | `!Send` `!Sync` |
| `Arc<i32>` | 原子计数共享 | `fetch_add` | 8 | `T: Send + Sync` 时 `Send + Sync` |
| `Weak<i32>` | 观察者，不延长寿命 | `++` 弱计数 | 8 | 同上 |
| `Cell<i32>` | 拷贝式内部可变 | — | 4（与 `T` 相同） | `!Sync` |
| `RefCell<i32>` | 动态借用检查 | — | 16（借用标志 `isize` + 值） | `!Sync` |
| `Mutex<i32>` | 跨线程独占访问 | — | 16（含中毒标志） | `T: Send` 时 `Sync` |
| `RwLock<i32>` | 多读单写 | — | 16 | `T: Send + Sync` 时 `Sync` |
| `OnceCell<i32>` | 单线程写一次 | — | 8（`Option` niche） | `!Sync` |
| `OnceLock<i32>` | 跨线程写一次 | — | 16 | `T: Send + Sync` 时 `Sync` |
| `LazyCell<i32, fn() -> i32>` | 单线程惰性 | — | 16 | `!Sync` |
| `LazyLock<i32, fn() -> i32>` | 线程安全惰性 | — | 16 | `T: Send + Sync` 时 `Sync` |

## Box: Heap Placement and Transfer

`Box<T>` 是最薄的智能指针：一个裸指针 + "我拥有并负责释放"的析构职责，没有计数、没有借用标志。它存在的理由有三个，每个都能问编译器要到证据。

**递归类型**。变长节点直接自嵌会把尺寸推成无穷，编译器拒绝：

```text
error[E0072]: recursive type `List` has infinite size
 --> /tmp/p_rec.rs:1:1
  |
1 | enum List { Cons(i32, List), Nil }
  | ^^^^^^^^^             ---- recursive without indirection
```

`Box` 在这里提供的是 indirection：指针宽度固定，堆上再套多少层都不影响 `size_of::<List>()`。

**trait object 装箱**。`dyn Trait` 没有静态尺寸，装箱后得到胖指针（`Box<dyn Trait>` 实测 16 字节，机制见 Fat Pointers and Metadata 一节）：

```rust
pub enum List { Cons(i32, Box<List>), Nil }

pub trait Shape { fn area(&self) -> f64; }
pub struct Square(pub f64);
impl Shape for Square { fn area(&self) -> f64 { self.0 * self.0 } }

pub fn build() -> Vec<Box<dyn Shape>> {
    let l = List::Cons(1, Box::new(List::Cons(2, Box::new(List::Nil))));
    let _ = &l;
    let b: Box<dyn Shape> = Box::new(Square(2.0));
    assert!(b.area() > 0.0);      // 方法经 vtable 分发，自动 deref
    vec![b, Box::new(Square(3.0))]
}
```

**`Box::leak` 与 FFI 所有权移交**。经典三段式是 `into_raw` 交出去、对面用完后 `from_raw` 收回来；`Box::leak` 则给出 `&'static mut T`：

```rust
pub fn leak_example() -> &'static mut str {
    let b: Box<str> = "hi".into();
    Box::leak(b)
}
pub fn ffi_handoff(v: u64) -> *mut u64 {
    Box::into_raw(Box::new(v))
}
pub unsafe fn reclaim(p: *mut u64) -> u64 {
    *unsafe { Box::from_raw(p) }
}
```

> [!WARNING]
> **1.99.0（2026-10-01）反转了 `Box::leak` 的推荐用法**。官方博客原文："we have updated the documentation on `Box::leak` to recommend against patterns that later deallocate that memory … Instead, `Box::into_raw` or `Box::into_non_null` should be preferred. This guidance also applies to other leak functions in the standard library."。动因是自定义分配器（`allocator_api`）即将稳定：leak 之后再 `from_raw` 释放，一旦分配器可变，配对的 dealloc 无法保证用的是同一个分配器。`Box::{into_non_null, from_non_null}` 与 `Vec::{into_parts, from_parts}` 同批于 1.99.0 稳定；本机 1.98.1 实测它仍报 `error[E0658]: use of unstable library feature \`box_vec_non_null\``（tracking issue #130364），只有旧行为可跑——"leak 出去就不打算收回"在 1.99.0 之前能用、之后应视为单向操作。

`Box<T>` 的分配走全局分配器。stable 上唯一的替换入口是 `#[global_allocator]`（`mimalloc`、`tikv-jemallocator` 等 crate 都基于它）；容器级 `Box<T, A>` 至今依赖 unstable 的 `allocator_api`。展开见 [Performance](/docs/CS/Rust/Performance.md)。

## Rc and Arc: Counting Semantics

`Rc`/`Arc` 在堆上放一个头部（strong 计数 + weak 计数）紧贴值本身，指针指向值；克隆只 `++` strong，丢弃只 `--`，strong 归零时析构值、等 weak 也归零时释放整块内存。计数语义可以直接打印验证：

```rust
use std::rc::Rc;
fn main() {
    let r = Rc::new(7);                       // strong=1
    let r2 = Rc::clone(&r);                   // strong=2
    assert_eq!(Rc::strong_count(&r2), 2);
    drop(r2);                                 // strong=1
    let w = Rc::downgrade(&r);                // weak=1
    assert_eq!(Rc::weak_count(&r), 1);
    drop(r);                                  // strong=0：值在此析构
    assert!(w.upgrade().is_none());           // 只剩弱引用，升级永远 None
}
```

实测输出（`rustc 1.98.1`，aarch64）：`strong after new 1` → `after clone 2` → `after drop 1` → `weak count 1` → `upgrade ... None`。`Weak` 的存在会让堆块在值死之后仍不释放——这正是"值死亡"与"内存归还"两个时刻被 weak 计数解耦的证据。

`Rc` 不能跨线程不是性能建议而是编译期事实，诊断值得原文记录：

```text
error[E0277]: `Rc<i32>` cannot be sent between threads safely
  = help: within `{closure@...}`, the trait `Send` is not implemented for `Rc<i32>`
  = note: required by a bound in `spawn`
```

同方向的 `!Sync` 用一行边界即可复现：`fn requires_sync<T: Sync>() {}` 配上 `requires_sync::<RefCell<i32>>()` → "cannot be shared between threads safely"。`Arc` 则对 `T: Send + Sync` 自动 `Send + Sync`，推理规则见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

`Rc` vs `Arc` 的成本差就是非原子 `++` 与原子 `fetch_add` 的差。本机单线程微基准（clone + drop 一个 `Rc/Arc<u64>` 于 2000 万次循环，`-O`，取三轮）：

| 操作 | 实测 |
| :--- | :--- |
| `Rc::clone` + drop | 4.15 – 4.19 ns/op |
| `Arc::clone` + drop | 9.85 – 10.81 ns/op |
| `Cell<usize>` 自增 | 0.38 – 0.42 ns/op |
| `AtomicUsize::fetch_add` Relaxed | 2.17 – 2.23 ns/op |
| `AtomicUsize::fetch_add` SeqCst | 7.03 – 7.21 ns/op |

> [!WARNING]
> 这组数字的局限必须一起读：**单线程、无竞争、计数器常年驻留 L1、循环极热**，是原子操作的最好情况；真实程序里 `Arc` 头部被多个核共享时，瓶颈变成缓存行弹跳，差距远大于 2 倍，而 `Rc` 根本没有资格参赛。aarch64 的独占指令对与 x86 的 `lock xadd` 行为也不同。换机器换场景必须重测（`#[bench]` 自 1.88.0 起是硬错误，得用 `criterion`/`divan` 或手写计时循环）。数量级结论只取一条：单线程共享所有权下 `Arc` 大约贵 2~3 倍。

多持有者时想要 `&mut T`，`Rc::get_mut` / `Arc::get_mut` 只在 strong==1 且 weak==0 时返回 `Some`：

```rust
use std::rc::Rc;
fn main() {
    let mut r = Rc::new(5);
    let first = Rc::get_mut(&mut r).map(|v| { *v += 1; *v });   // Some(6)
    let _r2 = Rc::clone(&r);
    let second = Rc::get_mut(&mut r);                            // None：还有别的持有者
    assert!(second.is_none() && first == Some(6));
}
```

## Weak and Circular References

引用计数的死穴是环：`A` 持有 `B`、`B` 持有 `A`，外部句柄全部 drop 之后计数仍互撑不归零，析构永远不跑。用 `Rc<RefCell<...>>` 搭一个最小环并埋析构计数器：

```rust
use std::cell::RefCell;
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
static DROPS: AtomicUsize = AtomicUsize::new(0);
struct Node { name: String, peer: RefCell<Option<Rc<Node>>> }
impl Drop for Node { fn drop(&mut self) { DROPS.fetch_add(1, Ordering::Relaxed); } }

fn main() {
    let a = Rc::new(Node { name: "a".into(), peer: RefCell::new(None) });
    let b = Rc::new(Node { name: "b".into(), peer: RefCell::new(None) });
    *a.peer.borrow_mut() = Some(Rc::clone(&b));
    *b.peer.borrow_mut() = Some(Rc::clone(&a));
    println!("a strong={} b strong={}", Rc::strong_count(&a), Rc::strong_count(&b));
    drop(a); drop(b);
    assert_eq!(DROPS.load(Ordering::Relaxed), 0);   // 析构一次都没跑
}
```

本机实测输出：环内 `a strong=2 b strong=2`；外部 drop 之后**析构函数跑了 0 次**——两个节点泄漏，且没有任何编译期或运行期警告。修法是把回边降级为 `Weak`（所有权边与观察边分开，所有权图必须是 DAG）：

```rust
use std::cell::RefCell;
use std::rc::{Rc, Weak};
use std::sync::atomic::{AtomicUsize, Ordering};
static DROPS: AtomicUsize = AtomicUsize::new(0);
struct Node {
    name: String,
    peer: RefCell<Option<Rc<Node>>>,      // 所有权边：a -> b
    back: RefCell<Option<Weak<Node>>>,    // 观察边：b -.weak.-> a
}
impl Drop for Node { fn drop(&mut self) { DROPS.fetch_add(1, Ordering::Relaxed); } }

fn main() {
    let a = Rc::new(Node { name: "a".into(), peer: RefCell::new(None), back: RefCell::new(None) });
    let b = Rc::new(Node { name: "b".into(), peer: RefCell::new(None), back: RefCell::new(None) });
    *a.peer.borrow_mut() = Some(Rc::clone(&b));
    *b.back.borrow_mut() = Some(Rc::downgrade(&a));
    println!("a strong={} a weak={} b strong={}",
        Rc::strong_count(&a), Rc::weak_count(&a), Rc::strong_count(&b));
    drop(a); drop(b);
    assert_eq!(DROPS.load(Ordering::Relaxed), 2);   // 两个都析构了
}
```

实测输出 `a strong=1 a weak=1 b strong=2`，随后 `DROPS == 2`：`a` 的外部句柄一 drop 计数即归零，其析构释放对 `b` 的所有权边，`b` 跟着归零。这就是 C++ 里 `shared_ptr` 环用 `weak_ptr` 破的同一件事，口径对照见 [C++ 智能指针](/docs/CS/C++/SmartPtr.md)。

> [!NOTE]
> 埋计数用的 `impl Drop` 还会带来一个构造期坑：带 `Drop` 的类型**不能用函数式更新语法** `..Default::default()`，实测报 `error[E0509]: cannot move out of type \`Node\`, which implements the \`Drop\` trait`——析构职责要求你不能把字段挪走，上面的例子因此逐字段构造。

## Internal Mutability

`&T` 意味着不可变共享，想"隔着 `&` 改值"就是内部可变性（interior mutability）。Rust 给两条正交路线：**拷贝式**（值进出，不产生引用）与**动态借用检查**（产生引用，把冲突检测推到运行期）。

### Cell: the Copy Route

`Cell<T>` 的 `size_of` 实测与 `T` 相同（`Cell<i32>` = 4 字节，零包装成本）。`get`/`set` 要求 `T: Copy`，否则编译器拦下：

```text
error[E0599]: the method `get` exists for reference `&Cell<String>`, but its trait bounds were not satisfied
  = note: the following trait bounds were not satisfied:
          `String: Copy`
```

非 `Copy` 类型走 `take()`（取走并留 `Default::default()`）/ `replace()` / `into_inner()`——值整体进出、任何时刻不存在悬出的引用，所以 `Cell` 全程不需要借用标志。

### RefCell: the Dynamic Borrow Check Route

`RefCell<T>` 在头部放一个 `isize` 借用标志：正数记共享借用数，`-1` 表示独占借用。`borrow`/`borrow_mut` 检查标志，违反 aliasing 规则时**当场 panic**：

```rust
use std::cell::RefCell;
fn main() {
    let c = RefCell::new(5);
    let _r1 = c.borrow();               // 共享借用 +1
    let _r = c.borrow_mut();            // panic: RefCell already borrowed
}
```

实测 panic 消息（`try_borrow_mut` 则返回 `Err(BorrowMutError)`，Display 同为 "RefCell already borrowed"）：

```text
thread 'main' panicked at /tmp/p_sp4.rs:5:15:
RefCell already borrowed
```

这行要点破了：**panic 不是"运行期检查的优雅降级"，而是把本该在编译期成立的 aliasing 约束搬到运行期、并在违反的瞬间放弃整个程序**。选 `RefCell` 等于承诺"借用冲突在我的程序里属于不可恢复错误"；如果冲突是可预期的业务状态，那说明数据模型该改（拆字段、换消息通道），而不是换 API。它的正面用途是明确的：`Rc<RefCell<T>>` 给共享所有权补上唯一的可变入口——图、树、观察者列表、上面破环例子，全靠这一组合。

### OnceCell and LazyCell

介于两条路线之间的是"写一次"家族：`OnceCell`（1.70.0）/ `OnceLock`（1.70.0）的 `get_or_init` 只初始化一次，`size_of::<OnceCell<i32>>()` 实测 8 字节（`Option<T>` 靠 niche 优化，与 `T` 几乎同宽）；`LazyCell`/`LazyLock`（1.80.0）= `OnceCell` + 初始化闭包。`size_of` 实测：`LazyCell<i32, fn() -> i32>` 16 字节。

### UnsafeCell: the Only Primitive

上面所有内部可变性——`Cell`、`RefCell`、`OnceCell`、`Mutex`、`RwLock`——都建立在 `UnsafeCell<T>` 之上，它是语言层面**唯一**能合法地把 `&T` 变成 `&mut T` 的机制：编译器对包在 `UnsafeCell` 里的字段停止"共享不可变"假设，把 aliasing 纪律的责任转交给封装者。`Cell` 靠"不产生引用"守住规则，`RefCell` 靠运行期标志守住，`Mutex` 靠锁守住——守的都是同一条编译期本来替你保证的不变量。自 1.99.0 起 std 文档额外保证"可以不经过 `get()` 访问 `UnsafeCell` 的内容"（`invalid_reference_casting` lint 随之调整）；直接手写 `UnsafeCell` 的纪律见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Mutex and RwLock: Cross-Thread Counterparts

`Mutex`/`RwLock` 与 `RefCell` 的分工只有一条轴：**线程**。单线程内的"运行时可变借用"用 `RefCell`（无系统调用、冲突即 panic、`!Sync` 出不了线程）；跨线程共享才需要锁。`RwLock` 与 `RefCell` 的行为几乎同构（多读单写 + 冲突检测），区别在冲突时**等待**而非 panic。锁序、饥饿与 `Mutex` vs `RwLock` 选型见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

### Poisoning

`Rc`/`Arc` + `RefCell` 世界里 panic 即终止，没有跨线程残局；`Mutex` 有：持锁线程 panic 时可能把数据留在半改状态，std 的处理是给锁打"毒"标记——后续 `lock()` 仍返回数据，但以 `Err(PoisonError)` 强迫你显式表态。实测（工作线程 push 完成后 panic）：

```rust
use std::sync::{Arc, Mutex};
fn main() {
    let m = Arc::new(Mutex::new(vec![1, 2, 3]));
    {
        let m2 = Arc::clone(&m);
        let h = std::thread::spawn(move || {
            let mut g = m2.lock().unwrap();
            g.push(4);
            panic!("boom while holding the lock");
        });
        let _ = h.join();
    }
    assert!(m.is_poisoned());
    let r = m.lock();
    assert!(r.is_err());                       // 数据其实完好，也要你表态
    let mut g = r.unwrap_or_else(|e| e.into_inner());
    m.clear_poison();                          // 1.77.0 起可清毒
    g.push(5);
    drop(g);
    assert_eq!(&*m.lock().unwrap(), &[1, 2, 3, 4, 5]);
}
```

要点有二：其一，毒化只表示"上一个持有者死在锁里"，**不表示数据一定坏**——`into_inner()` 取守卫是合法的，但必须显式写出来；其二，`clear_poison`（1.77.0）存在说明毒化是可选的卫生机制而非安全边界——真正兜底的是 panic 不跨锁传播这条线：`MutexGuard` 还实现了 `!Send`（实测 `error[E0277]: \`MutexGuard<'_, i32>\` cannot be sent between threads safely`），守卫不能被带进别的线程去解锁。

顺带一个实测陷阱：同一条表达式里两次 `m.lock()`（比如 `println!("{}", m.lock().is_ok() && *m.lock().unwrap() > 0)`）会**死锁**——两个 `MutexGuard` 临时值都活到整条语句结束，第二个 `lock()` 在等第一个释放。锁内表达式要分句。

### Why Handing Out &mut T Is the Key Design

`Mutex<T>` 的 `lock()` 返回守卫，守卫 `Deref`/`DerefMut` 到 `&T`/`&mut T`——看起来违反直觉：里面根本没检查 `T: Sync`，怎么敢给 `&mut`？关键在于**`&mut` 的唯一性正是锁要买的东西**：编译器保证同一时刻只有"当前持有守卫的这段代码"能构造出指向数据的引用，锁负责把这条保证扩展到跨线程场景。因此 `Mutex<T>` 只要求 `T: Send`（数据可以被搬进临界区独占访问），不要求 `T: Sync`——`Mutex<RefCell<i32>>` 合法（实测通过 `requires_sync::<Mutex<RefCell<i32>>>()`），`Mutex` 替 `RefCell` 补了它没有的跨线程互斥。对照 C++：`std::mutex` 与数据是两个互不相干的对象，忘记加锁编译器不管；Rust 把数据**焊在锁里**，不加锁连字段都摸不到。这条设计是"封装析构职责"之外的第二种智能指针范式——包装器同时是访问控制。

## One-Shot Initialization and Lazy Statics

一次性初始化有三个粒度：`Once`（手工 gate，配 `call_once`，`LazyLock` 的底层）、`OnceLock<T>`（1.70.0，单值写一次，`get_or_init` 线程安全、`set` 失败返回 `Err`）、`OnceCell<T>`（1.70.0，`!Sync` 单线程版）。惰性求值再进一格：`LazyLock<T, F>`（1.80.0）= `static` 友好的 `OnceLock` + 初始化函数，`LazyCell` 是其单线程版。

```rust
use std::sync::{Once, OnceLock};
fn main() {
    let o = OnceLock::new();
    for _ in 0..100 { o.get_or_init(|| 42); }   // 闭包只跑一次
    assert!(o.set(7).is_err());                 // 已初始化，set 失败
    let once = Once::new();
    let mut n = 0u8;
    once.call_once(|| n = 1);
    once.call_once(|| n = 2);
    assert_eq!(n, 1);
}
```

`LazyLock` 的正确姿势是 `static`，并且**需要手写 `fn()` 指针类型参数**（闭包类型无法出现在 `static` 签名里）：

```rust
use std::sync::LazyLock;
static S: LazyLock<u8, fn() -> u8> = LazyLock::new(|| 1);
fn main() { assert_eq!(*S, 1); }
```

实测（1.95.0 与 1.98.1 均编译并运行通过）：`LazyLock::new` 是 `const fn`——当前 stable 文档标注 "Stable since 1.80.0, const since 1.80.0"，`static` 初始化合法；`Mutex::new`/`OnceLock::new` 同理，`LazyLock::get/get_mut/force_mut` 则晚至 1.94.0 才稳定。但要避开一个语义陷阱：**别用 `const` 而不是 `static`**。`const` 项在每个使用点复制一份，惰性语义直接失效——`const X: LazyCell<u8, fn() -> u8>` 被读两次，初始化闭包实测跑了 **2 次**（`static` 才是 1 次）。

生态 crate 现状排序（std 能力已覆盖绝大多数场景）：

| 排序 | 选择 | 理由 |
| :--- | :--- | :--- |
| 1 | `std::sync::LazyLock`（1.80.0） | 线程安全惰性全局的默认答案 |
| 2 | `std::sync::OnceLock`（1.70.0） | 需要 `set` / 显式控制初始化时机时 |
| 3 | `once_cell`（1.21.4） | 仅当需要超出 std 的 API：`get_or_try_init`、`try_insert`（std 对应 gate `once_cell_try` 等仍 unstable） |
| 4 | `lazy_static`（1.5.1） | 未弃用，但 1.80.0 之后已无存在理由（宏入口 + 无法 const 构造） |

## Deref and Coercion

智能指针能"透明地当 `&T` 用"，靠的是 `Deref`/`DerefMut` 驱动的**解引用强制转换**（deref coercion）：在期望 `&T` 的位置给 `&P`（`P: Deref<Target = T>`），编译器自动插 `deref()`；转换可级联。实测 `&Rc<String>` 直接传给 `fn takes(s: &str)` 成立（`&Rc<String>` → `&String` → `&str` 两步级联）：

```rust
use std::rc::Rc;
fn takes(s: &str) -> usize { s.len() }
fn main() {
    let rc = Rc::new(String::from("hello"));
    assert_eq!(takes(&rc), 5);            // &Rc<String> -> &String -> &str
    let b = Box::new(String::from("x"));
    assert_eq!(takes(&b), 1);             // &Box<String> 同理
}
```

方法调用同理：`rc.chars()`、`b.area()` 都是接收者自动 deref 后进固有方法或 vtable。

边界与纪律：

- **`deref` 是隐式插入的公共 API**。std 文档原话："This trait's method should never unexpectedly fail. Deref coercion means the compiler will often insert calls to `Deref::deref` implicitly."——所以 `deref` 不允许失败、必须廉价、必须与 `*` 语义一致；不满足"逻辑上的解引用"关系（比如只是"能借出内部值"）时，文档明确建议实现 `AsRef`/`Borrow` 而不是 `Deref`（"It may be desirable to implement either or both of these, whether in addition to or rather than deref traits"）。这就是所谓"被劝退成 `as_ref`"的第一层含义：`as_ref` 是显式方法，可按类型选择转换目标；`deref` 一旦被编译器盯上就全局生效，退不回去。
- 第二层是 clippy。显式手写 `x.deref()` 会触发 `clippy::explicit_deref_methods`（restriction 组，默认关闭；本机开启后实测输出）：

```text
warning: explicit `deref` method call
  = help: try: `&**r`
```

意思是：`deref()` 本来就不该被点名调用——要引用写 `&*` / `&**`，要转换写 `as_ref`/`as_deref`。点名调用把"实现过 `Deref`"锁进调用点，trait 的实现细节泄漏成了公共表达式。
- 守卫类 `Deref`（`Ref`/`MutexGuard`）把引用的生命周期绑在守卫自身上，"作用域即窗口"就是这条 impl 的表达。
- `Deref` 不能表达"可能失败/昂贵的解引用"——那是显式方法（`Weak::upgrade`）的地盘；通用的 `Try` 式解引用（`deref` 返回 `Result`）至今没有稳定机制（`try_trait_v2` unstable）。

## Fat Pointers and Metadata

`dyn Trait` 与 `[T]` 没有静态尺寸，指向它们的指针携带**元数据**（metadata）凑成胖指针。本机实测（`rustc 1.98.1`，aarch64）：

| 类型 | size | 元数据 |
| :--- | :--- | :--- |
| `Box<i32>` / `Rc<i32>` / `Arc<i32>` | 8 | 无 |
| `&dyn Animal` / `Box<dyn Animal>` / `Rc<dyn Animal>` | 16 | vtable 指针 |
| `Rc<str>` / `*const [u8]` | 16 | 长度 |

`Rc<dyn Trait>` 实测也是 16 字节，说明元数据与计数头可以叠加：指针字仍只一份，宽度翻倍是因为**第二字要装 vtable**。堆头布局（strong/weak 计数紧贴值）与 vtable 内容（drop glue + size/align + 方法指针，字段顺序无任何保证）见 [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)。裸指针的胖指针化 API——`std::ptr::metadata` / `from_raw_parts` 重构 `dyn`——本机实测仍 unstable：`error[E0658]: use of unstable library feature \`ptr_metadata\``；1.99.0 稳定的只是 `size_of_val_raw` / `Layout::for_value_raw` 这条"从裸指针取尺寸"的旁路。

## Comparison with C++, Go, Java

| 问题 | Rust | C++ | Go | Java |
| :--- | :--- | :--- | :--- | :--- |
| 独占所有权堆值 | `Box<T>` | `std::unique_ptr<T>`（+删除器） | GC 托管堆对象 | GC 托管堆对象 |
| 共享所有权 | `Rc<T>`（单线程）/ `Arc<T>`（跨线程） | `std::shared_ptr<T>`（计数**总是**原子，单线程也付） | 无对应——靠 GC | 无对应——靠 GC |
| 观察者/破环 | `Weak<T>` + `upgrade() -> Option` | `std::weak_ptr<T>` + `lock()`（可能空） | 不需要（环可被收集器回收） | `WeakReference<T>` + `get()` 可能返回 `null` |
| 成员内取 self 的共享句柄 | 自存 `Weak<Self>`（或 `Rc::new_cyclic`） | `enable_shared_from_this` | 不需要 | 不需要 |
| 计数头与对象分配 | 一次分配（头紧贴值） | `make_shared` 一次；`shared_ptr(new T)` 两次 | — | — |
| 循环引用 | 计数模型下环即泄漏（已实测），设计期用 `Weak` 破环 | 同左，同靠 `weak_ptr` | tri-color + 混写屏障的并发标记回收，天然免疫 | GC 原生处理 |
| 误用防护 | `Rc` 跨线程 = 编译错误 E0277 | `shared_ptr` 计数线程安全但对象不安全，误用无提示 | 无此问题 | `WeakHashMap` 键随时可能被回收、条目自动失效；`PhantomReference` + `ReferenceQueue` 只做死后的登记清理 |

三条结构性差异值得点名：其一，C++ 的 `shared_ptr` 把"共享所有权"与"线程安全计数"绑死——单线程也付原子指令（对照上面 2~3 倍的实测差距），Rust 用 `Rc`/`Arc` 两个类型把这个取舍显式化；其二，Java 的 `WeakHashMap`/`PhantomReference` 服务的是"对象生命周期之外还有资源要收尾"（如 direct buffer 的 cleaner），Rust 的 `Drop` 是确定性的，不需要这类钩子；其三，Go 与 Java 的循环引用根本不是问题，因为可达性分析天然免疫计数盲区——这是计数式方案（Rust/C++）换确定性释放付出的固定税。GC 侧机制展开见 [垃圾回收](/docs/CS/memory/GC.md)，`shared_ptr` 细节见 [C++ 智能指针](/docs/CS/C++/SmartPtr.md)。

## Custom Smart Pointers

自定义智能指针 = `Deref`（透明访问）+ `Drop`（析构职责）两个 impl，所有权语义靠 move 检查免费获得。最小可运行骨架（实测编译运行，堆分配借 `Box::into_raw` 移交）：

```rust
use std::ops::{Deref, DerefMut};
struct MyBox<T> { raw: *mut T }
impl<T> MyBox<T> {
    fn new(v: T) -> Self { MyBox { raw: Box::into_raw(Box::new(v)) } }
}
impl<T> Deref for MyBox<T> {
    type Target = T;
    fn deref(&self) -> &T { unsafe { &*self.raw } }
}
impl<T> DerefMut for MyBox<T> {
    fn deref_mut(&mut self) -> &mut T { unsafe { &mut *self.raw } }
}
impl<T> Drop for MyBox<T> {
    fn drop(&mut self) { unsafe { drop(Box::from_raw(self.raw)) } }
}
fn main() {
    let mut m = MyBox::new(1u8);
    *m += 1;
    assert_eq!(*m, 2);
}
```

读这段代码的正确姿势是看它的 `unsafe` 集中在哪：`deref` 把裸指针变引用、`drop` 把所有权还给 `Box`——两处都依赖"`raw` 始终指向自己独占的分配"这条编译器看不见的不变量。两个连带后果：`*mut T` 字段使 `MyBox` 默认 `!Send + !Sync`，若语义确实可跨线程需要手写不安全 impl；字段的析构次序与 dropck 的边界见 [Drop](/docs/CS/Rust/Drop.md)。写真正的自定义分配器/句柄型指针前，先读 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Selection Checklist

| 场景 | 选择 |
| :--- | :--- |
| 只有一个拥有者，要上堆 / 递归 / 多态装箱 | `Box<T>` |
| 多拥有者，确认单线程 | `Rc<T>` |
| 多拥有者，跨线程 | `Arc<T>`（同步原语选择见 Concurrency） |
| 回边、缓存、观察者、破环 | `Weak<T>`（所有权图必须是 DAG） |
| 共享只读 + 某处需要可变（单线程） | `Rc<RefCell<T>>` |
| 只改一个 `Copy` 小字段（计数器、标志位） | `Cell<T>` |
| 共享可变，跨线程 | `Arc<Mutex<T>>` 或 `Arc<RwLock<T>>` |
| 全局/静态惰性初始化，线程安全 | `static LazyLock` |
| 全局惰性，单线程或线程局部 | `LazyCell` / `thread_local!` |
| 写一次、之后只读，要 `set` 控制 | `OnceLock<T>`（单线程版 `OnceCell<T>`） |
| 所有权交给 C、之后接回 | `Box::into_raw` →（对面）→ `Box::from_raw`；leak 视为单向 |

## Links

- [Drop 与析构](/docs/CS/Rust/Drop.md)
- [并发与同步](/docs/CS/Rust/Concurrency.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [C++ 智能指针](/docs/CS/C++/SmartPtr.md)
- [垃圾回收](/docs/CS/memory/GC.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [std::boxed — Box](https://doc.rust-lang.org/std/boxed/struct.Box.html)
- [std::rc — Rc](https://doc.rust-lang.org/std/rc/struct.Rc.html)
- [std::rc — Weak](https://doc.rust-lang.org/std/rc/struct.Weak.html)
- [std::sync — Mutex](https://doc.rust-lang.org/std/sync/struct.Mutex.html)
- [std::cell — UnsafeCell](https://doc.rust-lang.org/std/cell/struct.UnsafeCell.html)
- [std::ops — Deref](https://doc.rust-lang.org/std/ops/trait.Deref.html)
- [std::sync — LazyLock](https://doc.rust-lang.org/std/sync/struct.LazyLock.html)
- [Rust 1.99.0 Release Announcement](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/)
