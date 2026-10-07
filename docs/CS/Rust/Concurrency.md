## Introduction

Rust 对并发问题的表态是一句很强的话：**能编译过的 safe Rust 程序不会发生数据竞争**（freedom from data races）。它不是靠运行时检测，也不是靠"约定用锁"，而是把"这个值能不能被搬到另一个线程 / 能不能被另一个线程共享"这件事编码进类型系统，让不合法的线程访问在**编译期**就无法通过。

机制只有两条，配合起来却足以覆盖整个共享内存世界：

- **所有权 + 借用规则**给出"同一时刻要么一个 `&mut`、要么任意多个 `&`"，这正是"不会有两个访问同时以不兼容方式碰同一块内存"的形式化表达。
- **`Send` / `Sync` 两个 marker trait**把这条规则推广到线程边界：跨线程移动要求 `Send`，跨线程共享引用要求 `Sync`。`thread::spawn` 的签名要求闭包 `Send + 'static`，于是"把不该跨线程的东西搬过去"直接编译失败。

但这句话的边界必须同时说清，否则它会被读成"Rust 并发不会出错"——**类型系统证明的是"不存在并发的不兼容访问"，它对死锁、对 check-then-act 的逻辑竞态、对"锁保护了错误的不变式"一无所知**。本篇最重要的判断就在这一节：用 `Arc<Mutex<..>>` 完全可以写出编译器一声不响、运行时必然卡死或必然算错的程序。

> [!WARNING]
> 本篇只讲**线程世界**。`async` / `Future` / runtime / 单线程调度下的 `Send` 传染见 [Async](/docs/CS/Rust/Async.md)；`unsafe impl Send` 的责任条款与 UB 边界见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)；`Rc` / `Arc` / `RefCell` 本身的机制见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)；并发容器与锁 crate 的选型见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)。

## What Counts as a Data Race

本库对数据竞争的口径与 Go / Java / C++ 的内存模型一致，四要素缺一不可：

1. 两个访问指向**同一内存位置**；
2. 至少**一个是写**；
3. 二者**并发**（不被 happens-before 偏序所排序）；
4. 二者之间**没有任何同步关系**建立顺序。

第 3、4 条其实是同一件事的两种说法，写两条是因为"并发"在内存模型里是**派生概念**：没有 happens-before 边才叫并发。竞争一旦成立，后果不是"读到旧值"这么温和——在 Rust 与 C++ 里它是**未定义行为**，编译器有权假设它不会发生，于是可以把自旋循环里的加载整体提升到循环外、把两次读合并成一次、把 `Vec` 的长度缓存在寄存器里；硬件则允许撕裂与重排。Go 与 Java 把竞争降级为"值可以是任意的但程序仍然类型安全"（不会 out-of-thin-air），这是语言级内存模型给出的保护，不是免费的。

值得注意的是 Rust 的**规范性内存模型本身仍未定稿**：Reference 的 Memory model 一章开篇即自带警告"The memory model of Rust is incomplete and not fully decided"（2026-10 抓取）。这不削弱上面的保证——`Send`/`Sync` 的健全性不依赖内存模型细节，它依赖的是"竞争访问根本构造不出来"。恰恰因为抽象机规则还没写完，把安全线画在类型系统而不是"文档约定"上才显得划算。

### Why Concurrent Vec Mutation Is Undefined Behavior

`Vec` 是最好的入门案例：`push` 需要 `&mut self`，而 `&mut` 的唯一性由借用检查器保证。跨线程共享时你拿不到这个 `&mut`：

```rust
fn push_shared(v: &Vec<i32>) { v.push(1); }                      // E0596
fn push_arc(v: &std::sync::Arc<Vec<i32>>) {
    let mut c = v.clone();   // clone 只是复制 Arc 句柄，指向同一分配
    c.push(2);                                                   // E0596
}
```

`rustc 1.98.1` 的原文诊断分别是 `error[E0596]: cannot borrow \`*v\` as mutable, as it is behind a \`&\` reference` 和 `error[E0596]: cannot borrow data in an \`Arc\` as mutable`。第二条尤其值得记：**`Arc` 给的是共享所有权，不是可变性**；`mut` 加在句柄上只让句柄可变，改变不了 `Arc<T>` 解引用出 `&T` 的事实。

如果绕过去——比如 `unsafe` 里两个线程同时 `Vec::push`——后果是具体的：`push` 可能触发 realloc 换掉整块 buffer，另一个线程手里的旧指针当场悬垂；即使不 realloc，`len` 与 `ptr` 两个字段也会被并发写坏。这不是"结果不确定"，而是把分配器状态搞成非法值，因此 Rust 判定为 UB，且 `[u8]` 的 `len` 这类"只是读长度"的操作也在同一批访问里。正确写法只有两种：`Mutex<Vec<T>>`（锁内拿到真 `&mut`），或者把可变性搬到写侧（构造新 `Vec` 后发布新 `Arc`）。

## Send and Sync Encode the Same Rule Twice

- `T: Send`：**移动**所有权到另一个线程是安全的。
- `T: Sync`：**共享引用** `&T` 给另一个线程使用是安全的。

两者的关系是精确的一条等值，不是类比：**`T: Sync` ⟺ `&T: Send`**。std 的 `Sync` 文档把这当作定义来写：因为 `&T` 是可复制的（人人都能再借一次），所以共享 `&T` 必须比"移动 `T`"更保守——要求即使多线程同时只读也不会破坏任何不变式，这正好是 `&T` 能安全移动的条件。

### Auto-Derivation Rules

两个 trait 都是 `#[automatically_derived]` 的 lang-item，规则可以背下来：

| 类型 | Send | Sync | 派生依据 |
| :--- | :--- | :--- | :--- |
| 结构体 | 所有字段都 `Send` | 所有字段都 `Sync` | 逐字段与（`PhantomData<*const ()>` 常被用来主动破坏它） |
| 枚举 | 所有变体的所有字段 | 同左 | 取全部变体的并 |
| `&T` | 需 `T: Sync` | 需 `T: Sync`（引用本身可自由共享） | 由 `&T: Send ⟺ T: Sync` 定义 |
| `&mut T` | 需 `T: Send` | 不满足（不可能有两个 `&mut`） | 唯一性 |
| `*const T` / `*mut T` | ❌ | ❌ | std 显式不实现，裸指针即"手工并发" |
| `UnsafeCell<T>` | 字段 `T: Send` 自动派生 | ❌ | std **从不**为 `UnsafeCell` 生成 `Sync` |
| `Cell<T>` / `RefCell<T>` | 取决于 `T: Send` | ❌ | 内部可变性建立在 `UnsafeCell` 上 |
| `Mutex<T>` | 需 `T: Send` | 需 `T: Send`（**不需要** `T: Sync`） | 锁自己负责同步 |
| `RwLock<T>` | 需 `T: Send` | 需 `T: Send + Sync` | 允许多个读者同时进入 |
| `Arc<T>` | 需 `T: Send + Sync` | 需 `T: Send + Sync` | 共享所有权 + 可同时解引用 |
| `Rc<T>` | ❌ | ❌ | 非原子引用计数，跨线程即计数撕裂 |
| `MutexGuard<'a, T>` | ❌ | 取决于 `T: Sync` | std 刻意不给 `Send`（见下） |
| `LocalKey<T>`（`thread_local!`） | ✅ | ✅ | 它是"键"不是"值"，与 `T` 无关 |

`MutexGuard` 为什么是 `!Send`：本篇只能给出实测事实（`error[E0277]: \`MutexGuard<'static, NS>\` cannot be sent between threads safely`）与 std 的设计意图——守卫的释放路径要动锁本身的状态（含中毒标记这类运行时信息），把它搬到另一个线程去 drop 会破坏"谁持有谁释放"的前提。具体到各平台的底层锁是否允许跨线程解锁，属实现细节，未在此核实。

`Cell<T>` 这一行要特别纠正一个流传很广的说法：**它不是"仅当 `T: Copy` 才 `Send`"**。实测 `Cell<String>`（`String` 是 `Send` 但 `!Copy`）满足 `Send`，而 `Cell<*const u8>` 报 `error[E0277]: \`*const u8\` cannot be sent between threads safely`——即 `Cell` 的 `Send` 完全走字段自动派生。让它无法跨线程共享的是另一件事：`Cell` / `RefCell` / `OnceCell` / `LazyCell` 的内部可变性都建立在 `UnsafeCell<T>` 之上，而 std **从不**为 `UnsafeCell<T>` 生成 `Sync`（实测 `Cell<u8>`、`RefCell<u8>`、`UnsafeCell<u8>` 三者全部报 `!Sync`，哪怕 `u8` 本身既 `Send` 又 `Sync`）。

### The Measured Diagnostics

把上述类型放进 `thread::spawn` / `thread::scope`，`rustc 1.98.1` 给的第一行诊断如下（这些是本篇最有价值的部分——报错文本直接告诉你该换什么）：

```
Rc<u8>          error[E0277]: `Rc<u8>` cannot be sent between threads safely
                 = help: the trait `Send` is not implemented for `Rc<u8>`
RefCell<u8>     error[E0277]: `RefCell<u8>` cannot be shared between threads safely
Cell<u8>         = help: the trait `Sync` is not implemented for `Cell<u8>`
                 = note: if you want to do aliasing and mutation between multiple threads,
                          use `std::sync::RwLock` or `std::sync::atomic::AtomicU8` instead
MutexGuard      error[E0277]: `MutexGuard<'static, NS>` cannot be sent between threads safely
```

`= note:` 那一句是编译器主动给出的替代方案，这是 Rust 报错设计上少见的"教学型诊断"：它知道你想要的是"别名 + 可变"，并直接点名 `RwLock` 或原子类型。

### The Instructive Asymmetries

三条不对称最能说明这套规则不是机械的字段遍历：

- **`Mutex<T>: Sync` 不要求 `T: Sync`。** 这是整套设计的精髓：锁存在的意义就是把一个 `!Sync` 的东西变成可共享的。实测 `struct NS(Cell<u8>)`（`Send + !Sync`）满足 `Mutex<NS>: Sync`，但不满足 `RwLock<NS>: Sync`，也不满足 `Arc<NS>: Send`。
- **`RwLock` 比 `Mutex` 多一个 `Sync` 约束。** 因为读守卫可以同时给多个线程，此时 `&T` 真的在多线程里并存，`T: Sync` 不可省。
- **`Arc<T>` 同时要求 `T: Send + Sync`。** 共享所有权意味着既可能"移动到其他线程"也可能"多线程同时读"，两条路都得堵。

### dyn Trait + Send Is a Type-Level Constraint

写 `Box<dyn Worker + Send>` 是合法的，也是该写的（否则 `Send` 在擦除时就丢了）。但要清楚它的实现方式：auto trait 约束**纯在类型层**，运行期不做任何核验，也**不会多出第二张 vtable**——同一 `dyn Trait + Send` 值在实测中拿到的是同一个 vtable 地址（这条已在本库 [Trait_System](/docs/CS/Rust/Trait_System.md) 里做过实测订正）。真正产生"次表"的是 `trait C: A + B` 这类复合 supertrait 的上转。另：`dyn A + B`（两个非 auto trait）根本不被接受，报 E0225。也就是说 `+ Send` 是"给借用检查器看的元数据"，而不是"给运行时看的开关"。

## What the Borrow Checker Does Not Prove

保证的陈述形式是"不存在竞争访问"，而不是"程序行为正确"。以下三类缺陷都能干净通过类型检查，且都在本机实跑复现。

### AB-BA Deadlock

```rust
let a = Arc::new(Mutex::new(0u32));
let b = Arc::new(Mutex::new(0u32));
let gate = Arc::new(Barrier::new(2));          // 保证两线程都持有第一把锁
let (tx, rx) = mpsc::channel();

let (a1, b1, g1, t1) = (a.clone(), b.clone(), gate.clone(), tx.clone());
thread::spawn(move || { let _x = a1.lock().unwrap(); g1.wait(); let _y = b1.lock().unwrap(); t1.send(1).unwrap(); });
let (a2, b2, g2, t2) = (a.clone(), b.clone(), gate.clone(), tx);
thread::spawn(move || { let _y = b2.lock().unwrap(); g2.wait(); let _x = a2.lock().unwrap(); t2.send(2).unwrap(); });
```

`rustc` 对这份程序**没有任何警告或错误**；用 `recv_timeout` 可控地观察（不要让主线程无限等），实跑输出：

```
no progress within 300ms -> AB-BA deadlock; rustc emitted no warning for this program
a locked by stuck thread? true
b locked by stuck thread? true
```

类型系统看到的两组 `MutexGuard` 各自都满足 `!Send`、生命周期都合法——它证明的是"不会有两个守卫同时指向同一把锁"，而**死锁恰恰需要"两个守卫同时持有、各自等待对方"**。加锁顺序是全局协议，不是局部类型性质，任何类型系统都表达不了它。唯一的实用缓解是把加锁顺序写进不变式文档、或用一个"总按同一顺序拿锁"的辅助函数。

### Reentrancy and Guard Temporary Lifetime

第二条更隐蔽，也更常发生在手写代码里。std 的 `Mutex` **不可重入**：

```rust
let g = m.lock().unwrap();
println!("second lock on same thread would block? {}", m.try_lock().is_err());  // true
```

实跑 `true`——同一线程第二次 `lock()` 会永远阻塞自己。而真实的死锁往往来自**守卫临时量的生命周期**：`println!("{}", (m.lock().unwrap(), m.lock().unwrap()))` 这类"同一条语句里两次取锁"的写法完全合法，因为第一个 `MutexGuard` 临时量要到整条语句结束才释放，第二次取锁必然卡住。写这篇笔记时我就用 `m.lock().is_err()` 与 `m.lock().unwrap_or_else(..)` 塞进同一个 `println!` 而把自己挂死过一次——这正是"类型正确、行为死锁"的标准样本。规则：守卫要么 `drop` 掉再取下一次，要么用 `Mutex::guard` 风格的显式作用域。

### Check-Then-Act Across Two Locks

TOCTOU（time-of-check to time-of-use）是逻辑竞态的最小形态：**每一次加锁都是安全的，但"检查"与"行动"不在同一个临界区里**。

```rust
fn racy(bal: &Arc<Mutex<i32>>) {
    let have = *bal.lock().unwrap();                       // 1) 检查，guard 在本语句末释放
    thread::sleep(Duration::from_millis(1));
    if have >= 60 { *bal.lock().unwrap() -= 60; }          // 2) 行动，用的是过期的 have
}
fn safe(bal: &Arc<Mutex<i32>>) {
    let mut g = bal.lock().unwrap();                       // 同一个临界区
    if *g >= 60 { *g -= 60; }
}
```

余额 100、两个线程各提 60 的场景，本机 5 次运行**每次都稳定输出** `racy=-20  safe=40`。透支是确定的，而编译器一个警告都没有。原因：`Mutex` 保护的是"这块内存同时只有一个访问者"，它无法知道 `have` 这个本地拷贝与被保护的不变式之间的关系。**不变式跨语句的时间一致性不在类型系统表达力之内**，这是"数据竞争"与"竞态条件"这两个词必须严格区分的原因——Rust 消灭的是前者。

### No Stable Race Detector

死锁与逻辑竞态之外，还有一个常被忽略的事实：**Rust 没有 stable 的数据竞争检测器**。类型系统已经覆盖了绝大多数 safe 代码，因此竞争只会从 `unsafe`、`unsafe impl Send/Sync`、有缺陷的 crate 泄漏出来，而检测工具（ThreadSanitizer）至今仍挂在 nightly 上：

```
$ rustc -Zsanitizer=thread x.rs
error: the option `Z` is only accepted on the nightly compiler
```

（`rustc 1.98.1` 实测；用法见 Unstable Book 的 Sanitizer 一节。）这意味着 Rust 的"发现竞争"责任几乎全部前置到设计期，而不是像 Go 那样可以在测试期用 `-race` 兜底。Go 的 race detector 见 [RaceDetector](/docs/CS/Go/Concurrency/RaceDetector.md)。

## Atomic Ordering

### Five Levels, Not Six

`std::sync::atomic::Ordering` **只有五档**：`Relaxed`、`Acquire`、`Release`、`AcqRel`、`SeqCst`。写"六档"通常是把 C++ 的 `memory_order_consume` 算进来了——Rust 从未提供 `Consume`（社区共识是它无法被安全实现）。std 文档在每一档下明确标注"Corresponds to memory_order_xxx in C++20"，也就是说 Rust 的原子序是 C++20 菜单的一个**去掉 consume 的子集**。

另外该枚举是 `#[non_exhaustive]`：不带通配地穷举五档会报 `error[E0004]: non-exhaustive patterns: \`_\` not covered`（实测），所以 `match` 它必须留兜底分支。

语义表（"同步"指的是两个线程之间建立 happens-before 边，不是"保证顺序"这种模糊说法）：

| Ordering | 与相邻操作的顺序 | 与别的线程建立同步 | 典型用途 |
| :--- | :--- | :--- | :--- |
| `Relaxed` | 无（只保证原子性与单变量修改顺序全序） | **不建立** | 计数器、统计、引用计数增减 |
| `Acquire` | 其后的读写不得上提越过它 | 与一个 `Release` 配对 | load 端读锁、消费标志 |
| `Release` | 其前的读写下不得下沉越过它 | 被某个 `Acquire` 看到 | store 端发布数据 |
| `AcqRel` | 两侧都要 | 双向 | `fetch_add` / CAS 等读改写 |
| `SeqCst` | `AcqRel` + 所有 SeqCst 操作构成**单一全序** | 全局一致 | 不确定时的默认；多变量协议 |

只有 `Release`/`Acquire`/`AcqRel`/`SeqCst` 的**读**能看到某个 `Release` 写之前的所有副作用；`Relaxed` 之间永远只建立"同一变量的修改顺序"，不建立跨变量的 happens-before。

### Publish-Subscribe Needs Acquire and Release

```rust
static DATA: AtomicUsize = AtomicUsize::new(0);
static FLAG: AtomicBool = AtomicBool::new(false);

fn producer_relaxed() { DATA.store(42, Ordering::Relaxed); FLAG.store(true, Ordering::Relaxed); }
fn consumer_relaxed() {
    while !FLAG.load(Ordering::Relaxed) { std::hint::spin_loop(); }
    let x = DATA.load(Ordering::Relaxed);   // 可能读到 0，也可能被编译器整个提出循环
}

fn producer() { DATA.store(42, Ordering::Relaxed); FLAG.store(true, Ordering::Release); }
fn consumer() {
    while !FLAG.load(Ordering::Acquire) { std::hint::spin_loop(); }
    let x = DATA.load(Ordering::Relaxed);   // 这里 DATA 用 Relaxed 就够了：发布已被 flag 的同步覆盖
}
```

两段都能编译——**这正是本篇的论点**：`Relaxed` 版本不是类型错误，抽象机层面它允许 `FLAG` 先到 `true` 而 `DATA` 仍是旧值。第二个版本的 `DATA.load` 用 `Relaxed` 是正确的（同步关系已经由 flag 上的 `Release`/`Acquire` 建立，额外加序只是白付钱）。我没有在本机给出"Relaxed 版实际读到 0"的复现：单次采样触发不了弱内存序窗口，把"没跑出来"写成"没问题"和把"理论上可以"写成"实测复现"是同一种错误。

### A Micro-Benchmark With Its Caveats

本机 `rustc 1.98.1 -O`、`aarch64-apple-darwin`（Apple Silicon，弱内存序）、每场景连跑多轮取区间，工具只有 `std::time::Instant` + `std::hint::black_box`——**没有 criterion 的预热与统计置信，也没有排除频率漂移**，所以下面的数字只用于判断"量级差异在不在"，不要当性能结论。

- **单线程、无争用的 store：`Relaxed` 与 `SeqCst` 差异淹没在噪声里**（2M 次 store，两者各轮耗时区间互相覆盖）。所以在 aarch64 上"把 SeqCst 改成 Relaxed 提速"这个常见建议，对无争用的单变量写基本是空操作——`stlr` 在无争用缓存行上很便宜。
- **读改写指令本身才是成本**：无争用 2M 次下 `swap(SeqCst)` ≈ 11–14 ms、`compare_exchange` ≈ 30–38 ms，而 `store` ≈ 0.7–1.2 ms。差 1–2 个数量级的不是内存序，是"独占缓存行"。
- **争用下才看得到序的差别**：4 线程争同一行、各 500k 次 `fetch_add`，3 轮结果 `Relaxed` ≈ 39–42 ms，`AcqRel` ≈ 74–91 ms，`SeqCst` ≈ 74–80 ms。即 **Relaxed 约为后两者的 1/2，而 `AcqRel` 与 `SeqCst` 在本机测不出稳定差异**（全局全序的额外代价在这里体现不出来，两者都是带屏障的 RMW）。

判据由此变得很简单：`Relaxed` 的收益只在**高争用的读改写**上才可观，且必须先证明你不需要跨变量的同步关系；否则选 `AcqRel` 是免费的。

### Reference Counts Are an Ordering Problem too

`Arc` 是全库最常被"白嫖"内存序的地方，它内部那两个计数都是原子量（计数机制本身见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)，这里只讲并发侧为什么必须是原子的）：

- **递减到 0 的那一次必须"看到"其他所有线程的写**：`Arc::drop` 走的是 `Release` 递减 + 最后一个持有者 `Acquire` 读回，否则析构函数会在还没看到他人写入的状态上运行。这是 `Arc<T>` 只要求 `T: Send + Sync` 却能安全析构的全部依据。
- **强计数与弱计数必须是两个量**：`Weak::upgrade` 不能"先读强计数非零、再抬升"——中间有任何一次 `drop` 都会让它复活一个正在析构的对象。唯一安全形态是把"弱计数递增 + 强计数检查 + 强计数抬升"压进一次 CAS 序列，这也是 `Weak` 存在的意义。
- `Weak::upgrade` **不是选举**。实测 4 个线程同时 `upgrade` 同一个仍然活着的 `Weak`，返回 `Some` 的次数是 **4**（`hits = 4`）；`Arc::strong_count` / `weak_count` 打印出 `strong=1 weak=1`。用"我 `upgrade` 成功了"来判定"我是唯一 owner"是错的，需要唯一性得再叠一层 CAS 或锁。
- 最后一个 `Arc` 掉完后 `upgrade` 返回 `None`（实测 `true`），而不是 panic——`Weak` 的并发语义是"可能失败的所有权尝试"。

### Which Atomic Types Exist on Stable

稳定的类型族是 `AtomicBool`、`AtomicPtr` 与 8 / 16 / 32 / 64 / `size` 各宽度的有符号无符号整数。`AtomicI128` / `AtomicU128` **仍不稳定**，实测报 `error[E0658]: use of unstable library feature \`integer_atomics\``。

一个容易踩的分裂：`cfg!(target_has_atomic = "128")` 在本机是 **`true`**（与 `= "64"`、`= "ptr"` 一样为真），但类型仍不存在。**硬件与 ABI 支持 128 位原子操作 ≠ stable std 暴露了它**。用 `#[cfg(target_has_atomic = "…")]` 做可选路径是对的，但别据此假定 `AtomicU128` 可写。

### loom for Permutation Checking

无锁结构的正确性靠人脑推理内存序几乎必错，本库的默认工具是 **`loom`**（当前 `0.7.2`，crates.io 最后更新 **2024-04-23**）。它不是运行时监测器，而是把 `loom::sync::atomic::*` 换掉 std 原子类型后，**穷举线程交错（permutation）+ 内存序可能取值**，把"某条弱序路径会失败"变成断言失败。测试写法是把 `#[test]` 放进 `loom::model!` 或直接跑 loom 版测试、release 版跑普通测试。

⚠️ `loom` 自 2024 年以来没有新版本，**不要把它描述成活跃开发中**；它仍是这类工具的参考实现，但状态是"成熟且基本不动"。相关：无锁并发容器的 epoch 回收见 `crossbeam-epoch`（`0.9.21`，2026-09-05）。

## Channels Transfer Ownership Rather than Sharing Access

`std::sync::mpsc` 的"多生产者单消费者"名号是字面意思，也是它全部的规则：

```rust
let (tx, rx) = mpsc::channel::<usize>();
let (t1, t2) = (tx.clone(), tx.clone());
drop(tx);
// 两个线程各持有自己的 Sender
let sum: usize = rx.iter().sum();          // 45
```

- `Sender<T>` 可以 `clone`（这就是"多生产者"），且 `Send + Sync`——所以 `&Sender` 也能跨线程共享；
- `Receiver<T>` 是 `Send` 但 **`!Sync`**，实测 `error[E0277]: \`Receiver<u8>\` cannot be shared between threads safely`（这正是 mpsc 而非 mpmc 的体现）。
- **channel 天然不产生数据竞争**：发送即转移所有权，接收方拿到的是唯一持有者，而"转移"这件事本身就是 happens-before 边。这是 CSP 路线（Go）与共享内存路线（Rust std）的分水岭——但 Rust 的 channel 不禁止你发送 `Arc<Mutex<T>>`，那样共享内存问题会原样跟过来。

断连语义四种，实跑输出（`rustc 1.98.1`）：

| 场景 | 结果 |
| :--- | :--- |
| `recv` 且队列里有值 | `Ok(v)` |
| `recv` 且所有 `Sender` 已 drop、队列已空 | `Err(RecvError)` |
| `send` 时 `Receiver` 已 drop | `Err(SendError { .. })`（**值被退回**，可复用） |
| `try_recv`，无 sender 且队列空 | `Err(Empty)`（注意：先消费残留值） |
| `sync_channel(n)` 满时 `try_send` | `Err(TrySendError::Full(..))`；`send` 则**阻塞** |

`sync_channel` 是"有界 + 背压"，`channel` 是无界（内存换吞吐，生产者永不被阻塞）。

std 这一族的边界很清楚，全部实测过：

- **没有 mpmc**：`std::sync::mpmc::channel()` → `error[E0658]: use of unstable library feature \`mpmc_channel\``。
- **没有队列长度查询**：`Receiver::len` / `is_empty` → E0599。
- **没有跨句柄判等**：`Sender::same_channel` → E0599。
- **没有 `select!`**：多路复用要么自己开线程，要么换 crate。

生态位因此是：**`crossbeam-channel`（`0.5.17`，2026-09-05）** 补 mpmc、`select!`、长度、`same_channel`，是线程世界的默认；`tokio::sync::{mpsc, oneshot, broadcast}` 属于异步世界，其 `send` 是 `async fn`、语义与阻塞版不同，见 [Async](/docs/CS/Rust/Async.md)。选型速览：

| 需求 | 选 | 理由 |
| :--- | :--- | :--- |
| 一次性把值交给一个消费者 | `mpsc::channel` | 无锁开销的最小方案 |
| 需要背压 / 限制内存 | `mpsc::sync_channel(n)` | 有界即背压 |
| 多消费者抢同一队列 / `select!` | `crossbeam-channel` | std 无 mpmc |
| 少量值 + 高频读 | `Arc<Mutex<..>>` 或原子 | channel 每次都是搬运与分配 |
| 异步任务间 | `tokio::sync` | 阻塞 `recv` 会卡住执行器线程 |

## Threads, Scoped Threads, and Thread Locals

### JoinHandle

`thread::spawn` 返回 `JoinHandle<T>`；`join` 返回 `Result<T, Box<dyn Any + Send>>`——panic 被降级成值，不自动传播，你必须主动 `join` 才知道子线程炸了：

```rust
let h = thread::spawn(|| -> u32 { panic!("child"); });
assert!(matches!(h.join(), Err(_)));
let msg = h.join().unwrap_err().downcast_ref::<&str>();   // Some("child")
```

实跑确认 `downcast_ref::<&str>() == Some("child")`（`panic!` 的字符串字面量载荷是 `&str`，`String` 载荷则要用 `String` 去 downcast）。三条硬事实：**drop `JoinHandle` 就是 detach**（没有 cancel API，Rust 不提供强制终止线程的能力）；线程栈溢出是 abort 而非可捕获 panic；子线程不 join 就随 `main` 返回被整体销毁（进程退出只等主线程）。

### thread::scope Replaces 'static With a Lifetime

`thread::scope`（Rust **1.63.0**，2022-08-11 稳定）是这套规则里最漂亮的一处：它不做 `Arc` 打包，而是用生命周期换掉 `'static` 约束。

```rust
let mut data = vec![1i32; 8];
let (a, b) = data.split_at_mut(4);
std::thread::scope(|sc| {
    let h1 = sc.spawn(|| a.iter().sum::<i32>());   // 直接借用 &mut [i32]
    let h2 = sc.spawn(|| b.iter().sum::<i32>());
    let _ = (h1.join().unwrap(), h2.join().unwrap());
});                                                 // 隐式 join，作用域结束保证不悬垂
```

两个线程拿到的是**互不相交的 `&mut` 切片**，能编译过就意味着不存在重叠访问——这是"所有权把数据竞争变成类型错误"的最纯粹示例，全程没有锁、没有 `Arc`、没有 `unsafe`。而同一作用域里想要 `&data` 与 `&mut data` 并存时，报的是普通借用错误：`error[E0502]: cannot borrow \`data\` as mutable because it is also borrowed as immutable`。

反过来，`scope` 并不能豁免 `Sync`：把 `&Cell<u8>` 或 `&RefCell<u8>` 借进闭包仍然得到 E0277（`required for \`&Cell<u8>\` to implement \`Send\``）。**scoped API 放宽的是生命周期，不是可共享性**，这两件事常被混为一谈。`ScopedJoinHandle<'scope, T>` 的 `'scope` 就是它的护栏——它保证句柄活不过 `scope` 调用。

### thread_local and LocalKey

`thread_local!` 生成的是一个 `LocalKey<T>` 静态量，值存在线程本地存储里：

```rust
thread_local! {
    static EVENTS: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
}
fn tls_len_push() -> usize {
    EVENTS.with(|e| { e.borrow_mut().push(7); e.borrow().len() })
}
```

三个线程加主线程各调一次，实跑 `per-thread TLS lengths = [1, 1, 1], main = 1`：每份状态天然线程私有。

关键的一条实测结论：**`LocalKey<T>` 对任意 `T`（哪怕 `T = Rc<u8>`）都同时满足 `Send` 和 `Sync`**——因为它是"键"而不是"值"，跨线程传一个键仍然只会访问到调用者自己那份数据。`with` 闭包拿到的是 `&T`，而 `T` 本身可以完全不是 `Send`/`Sync`。这解释了为什么 `RefCell` 在 TLS 里是标准搭配：TLS 是"把单线程类型安全地放进多线程程序"的正道，而不是绕过 `Send`/`Sync` 的后门——一旦你把 `with` 里的引用带出闭包，借用检查立刻拦住。

`const { ... }` 初始化器（避免每次运行期判空）是 stable 的常规写法，实测编译通过。

### Windows TLS Destructors Moved to FLS

一条纯兼容性注意：Rust **1.98.0**（2026-08-20）的 Compatibility Notes 记录，**Windows 上 TLS 析构函数改用 Fiber Local Storage（FLS）实现**。受影响的是"线程退出时 `thread_local!` 值的析构时机/是否被调用"这类边角行为（旧的 `TlsAlloc` + DLL_THREAD_DETACH 路径在动态加载/卸载、`DllMain` 上下文里本就有坑）。除此之外，1.95.0 的 release notes 还专门补充了 `thread::scope` 的 join 与 TLS 析构交互的**文档**（仅文档，非行为变更）。写"某平台上 TLS 析构一定会/一定不会跑"之前需要重测——这类结论带平台前提。

## Data Parallelism Without Hand-Writing Threads

**rayon**（`1.12.0`，2026-04-14）是这块的事实默认，它把上面 `split_at_mut` + `thread::scope` 的手工活缩成一个方法名：`par_iter()`。调度器是全局线程池（默认规模按逻辑 CPU 数）+ 每线程工作窃取队列（work stealing），所以"分成几份、谁干哪份、负载不均怎么补"都不用你管。

rayon 值得放在这篇里，是因为它是 `Send`/`Sync` 设计最直接的受益者：`ParallelIterator` 的约束本质是"**闭包可共享可搬运 + 被遍历的数据可共享**"，即 `&F: Send`、`Data: Sync` 一类的 bound。于是 `par_iter` 能并行**只读**变换而无需任何锁，而 `par_iter_mut` 的可行性来自"每个闭包拿到互不相交的 `&mut` 分片"——**借用检查器在这里给出的证明，正是 rayon 无需自己做线程安全论证的前提**。这也解释了那条实战判据：

- 元素类型是 `Cell` / `RefCell` / 含裸指针 → 不满足 `Sync` → 根本进不了 `par_iter`。不是 rayon 保守，而是"边并行边改内部可变性"确实没有定义。
- 想并行写同一块状态，正确形状不是"加锁的 `par_iter`"（锁会把并行度压回 1），而是**返回局部值再合并**：`par_iter().map(...).fold(...).reduce(...)`。
- `fold` + `reduce` 的合并顺序不固定，所以依赖运算顺序的东西（浮点累加、拼接顺序）结果可能与串行版本不同——这是"没有数据竞争但仍有不确定性"的另一类，和本篇前面的竞态完全无关，属于归约语义。

本机没有 rayon 可编译，故不给它的代码示例；用 std 手写一个同构的最小版本（实测编译通过，与 `split_at_mut` 的例子只差在分片数量）：

```rust
let data: Vec<i64> = (0..1000).collect();
let parts: Vec<_> = data.chunks(250).collect::<Vec<_>>();
let mut sums = Vec::new();
std::thread::scope(|sc| {
    let handles: Vec<_> = parts.iter().map(|p| sc.spawn(|| p.iter().sum::<i64>())).collect();
    for h in handles { sums.push(h.join().unwrap()); }
});
let total: i64 = sums.iter().sum();
```

这段代码同时说明 rayon 帮你省掉的是什么：分片、句柄收集、以及"分区后各线程仍只碰自己的 `&[T]`"这件事的显式表达。

## Choosing Between Mutex, RwLock, and Lock-Free

判据不是"读多就 `RwLock`"这么简单，`RwLock` 的读路径本身要做引用计数增减，收益经常没到：

| 维度 | `Mutex<T>` | `RwLock<T>` | 原子 / 无锁 |
| :--- | :--- | :--- | :--- |
| 读者并发 | 串行 | 并行 | 并行 |
| `T` 需要的约束 | `Send`（才 `Sync`） | `Send + Sync` | 类型自带 |
| 适合 | 写多、临界区长、不变式跨多字段 | 读临界区**长**且读远多于写 | 单字/小结构、可 CAS 表达 |
| 陷阱 | 写者长时间持锁 → 全线阻塞 | 读者短暂高频时反而比 `Mutex` 慢 | 逻辑竞态与 ABA 全归你 |
| panic 后果 | 中毒，后续 `lock()` 返回 `Err` | 同左 | 无中毒概念（无锁可毒） |

三条常被误用的经验：

1. **读远多于写时，优先考虑"发布新值"而不是 `RwLock`**：写侧构造完整新对象、`Arc` 换指针，读侧一次 `load` 拷贝 `Arc`。这样读路径没有锁也没有引用计数争用（代价是写侧的复制）。
2. **`Mutex` 的粒度按不变式划，不按字段划**：一把锁保护一组必须同时成立的值。多把细锁正是 AB-BA 死锁的温床——细粒度的收益要能覆盖顺序协议的成本。
3. **`try_lock` 是诊断工具，不是并发方案**：它能在运行时确认"锁被谁卡住"（本篇的死锁复现就靠它），但用轮询 `try_lock` 代替阻塞等待通常是设计缺陷。

中毒（poisoning）与 `clear_poison`（Rust **1.77.0**，2024-03-21）的机制细节在 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)；本篇只给实测结论：子线程持锁 panic 后，`join()` 报 panic、后续 `lock()` 返回 `Err`，但**数据仍在**（`unwrap_or_else(|e| e.into_inner())` 可取出，实跑得 `data preserved through poison = 1`），`clear_poison()` 之后锁恢复正常。也就是说中毒是**运行时状态**，类型系统不会因为一把锁可能中毒而改变它的类型——这又是一处"类型保证到不了的地方"。

再往下一层，`Mutex`/`RwLock` 在这些平台上的等待队列最终落在 futex 上（无争用时只是一次原子 CAS，争用时才进内核），内核侧机制见 [futex](/docs/CS/OS/Linux/Lock/futex.md)，各锁的内核实现与选型见 `OS/Linux/Lock/`。

## Cross-Language Comparison

同一件事（"忘了同步"）在四套体系里的责任人完全不同：

| | Rust | Go | Java | C++ |
| :--- | :--- | :--- | :--- | :--- |
| 竞争的定义 | 同一位置 + 至少一写 + 无 happens-before（口径一致） | 同左，`go/ref/mem` | 同左，JLS 17.4 | 同左，`[intro.races]` |
| 谁发现竞争 | **编译器**：`!Send`/`!Sync` 使构造失败 | **运行时**：`-race` 建 happens-before 图，需覆盖到该路径 | 工具链：TSan / JCStress；JMM 只在 `volatile`/`final`/锁上给保证 | **没有人**：靠审查 + `-fsanitize=thread` |
| 竞争的后果 | safe 代码里构造不出；`unsafe` 里是 UB | 值任意但类型安全 | 值任意但类型安全，不 out-of-thin-air | UB |
| 内存序暴露面 | 5 档 `Ordering`（无 `Consume`） | 无显式序菜单，只有 happens-before 规则 | 无显式序菜单（`volatile`/锁/final 规则） | 6 档 `std::memory_order`（含 `consume`） |
| 代价支付阶段 | **设计期**（类型怎么定义、哪里用内部可变性） | **测试期**（`-race` 跑到了才算数） | **审查期**（正确发布构造的知识） | **事故期** |
| 死锁 / 逻辑竞态 | 都不管 | 都不管（`-race` 不报死锁） | 都不管 | 都不管 |
| 默认并发模型 | 共享内存 + `Send`/`Sync` 护栏 | CSP，channel 传值 | 共享内存 + `java.util.concurrent` | 什么都给你，什么都自己负责 |

一句总结：**Go 用"不共享"消解竞争，Java 用"规定竞争的后果"驯化竞争，C++ 用"给你内存序菜单"让你自己处理竞争，Rust 用"让竞争写不出来"前置竞争。** 但四行里最后一行是共同的：死锁、TOCTOU、错误的不变式划分，四种语言都得靠运行时与人的设计解决。对照可读 [Go 内存模型](/docs/CS/Go/Concurrency/MemoryModel.md)、[Java JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)、[C++ 并发](/docs/CS/C++/Concurrency.md)。

## Boundaries of This Guarantee

逃逸口只有四个，每个都有明确归属：

- **`unsafe impl Send` / `Sync`**：向编译器担保"我保证安全"，担保错误时整套保证同时失效 → [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。
- **`unsafe` 块内的裸指针跨线程**（自己转 `*mut T`）：借用检查在 `unsafe` 里不工作 → [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。
- **异步边界上的 `Send` 传染**：`MutexGuard` 跨 `.await` 之类 → [Async](/docs/CS/Rust/Async.md)。
- **依赖 crate 内部的 unsoundness**：类型正确不代表实现正确，Rust 的历史上修过好几次"本该 `!Send` 却自动派生成 `Send`"的 bug。

而本篇反复出现的那句"编译器不报"，是这套设计诚实的一部分：**Rust 把一类难检测的错误变成不可能，代价是把剩下几类错误全部交给你。**

## Links

- [Async](/docs/CS/Rust/Async.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)
- [Go Concurrency Memory Model](/docs/CS/Go/Concurrency/MemoryModel.md)
- [Java JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

1. [The Rust Reference — Memory model](https://doc.rust-lang.org/reference/memory-model.html)
2. [std::sync::atomic::Ordering](https://doc.rust-lang.org/std/sync/atomic/enum.Ordering.html)
3. [std::marker::Sync](https://doc.rust-lang.org/std/marker/trait.Sync.html)
4. [The Rustonomicon — Atomics](https://doc.rust-lang.org/nomicon/atomics.html)
5. [std::thread::scope](https://doc.rust-lang.org/std/thread/fn.scope.html)
6. [std::sync::mpsc](https://doc.rust-lang.org/std/sync/mpsc/index.html)
7. [The Unstable Book — Sanitizers](https://doc.rust-lang.org/unstable-book/compiler-flags/sanitizer.html)
8. [loom 0.7.2 documentation](https://docs.rs/loom/0.7.2/loom/)
9. [rayon 1.12.0 documentation](https://docs.rs/rayon/1.12.0/rayon/)
10. [cppreference — memory_order](https://en.cppreference.com/w/cpp/atomic/memory_order)
