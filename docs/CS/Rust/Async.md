## Introduction

Rust 的 async 是一次**分工**：语言只负责语法和把 `async` 块编译成状态机，**调度、任务队列、定时器、epoll 全部在库里**。
std 到今天为止只提供 `Future` / `IntoFuture` / `Pin` / `Poll` / `Waker` 这几个类型，没有 runtime、没有 `spawn`、没有定时器；
`tokio`（1.53.2）就是那个补上调度器的库。理解这条分界线，下面几乎所有设计取舍都是它的推论：因为运行时是外部库，所以
future 可以**不跑在任何线程上**（惰性），所以 `spawn` 的约束是库自己写的（`'static + Send`），所以没有"语言级取消语义"
（取消就是 `drop`），所以 `Send` 泄漏进类型系统变成一类高频编译错误。

对照本库另外两台异步运行时：[netpoller](/docs/CS/Go/netpoller.md) 是**运行时自带栈**（goroutine 有独立栈，被 park 时整段保存），
[Asyncio](/docs/CS/Python/Asyncio.md) 是**单线程事件循环 + 只在 `await` 让出**。Rust 走的是第三条路：**无栈、定长结构体、
poll 驱动**，代价是 `Pin` 与 `Send` 这两门必修课。

本文实测环境：`rustc 1.98.1 (48a229cea 2026-09-01)`、`cargo 1.98.1`、目标 `aarch64-apple-darwin`、`tokio 1.53.2`
（features `rt-multi-thread,macros,time,sync`）。所有数字本机跑出；只有标注"自 1.99.0 起"的条目是本机跑不出的。

## What the Language Provides and What the Runtime Provides

| 能力 | 提供方 | 具体形态 |
| :--- | :--- | :--- |
| `async` / `await` 语法 | 语言 | `async fn` / `async {}` / `async move {}`（async/await 自 Rust 1.39.0, 2019-11-07 起 stable） |
| 状态机与 `Future` trait | 语言 + std | 编译器生成的匿名 `impl Future`，std 只有 trait 定义 |
| 固定内存位置的手段 | std | `Pin<P>`、`pin!`、`Box::pin`、`Unpin` |
| 唤醒机制 | std | `Waker` / `Context` / `Wake` trait |
| 调度器、任务队列、epoll/kqueue、定时器 | **库** | `tokio`、`smol`、`async-std`（后者官方已弃用，转 `smol`） |
| `spawn` / `JoinHandle` / `select!` / `JoinSet` | **库** | 约束（`'static + Send`）也是库自己定的 |
| `Stream`（异步迭代器） | **库** | `futures` 0.3.34；std 里没有 |

因为调度器在库侧，**同一个 `Future` 值可以被任何 executor 驱动**，也可以被手工 `poll`（本文的 mini runtime 就是这么跑的）；
这是 Rust 与 Go / Python 最根本的结构差别：那两者的协程与调度器是绑死的。

## A Future Does Not Run Until Someone Polls It

`async fn` 的调用**只是构造一个值**，函数体一行都不执行；`.await` 也不是"挂起当前线程"，而是"把当前状态机交给驱动方，
并在它返回 `Pending` 时把自己的 `Waker` 交出去"。实测（`rustc 1.98.1 -O`，aarch64）：

```rust
static ADD_RUNS: AtomicUsize = AtomicUsize::new(0);

async fn add(a: u32, b: u32) -> u32 {
    ADD_RUNS.fetch_add(1, Ordering::SeqCst);
    a + b
}

let f = add(1, 2);
// ADD_RUNS == 0  ← 函数体一次都没跑；构造完就 drop 掉，则一次都不会跑
// size_of_val(&f) == 12
```

驱动之后才是 2 次（`add(1,2)` 与 `add(3,4)` 各一次）。状态机是**定长结构体**，大小等于"所有分支上同时存活的局部变量之和"
（union 复用），实测三档：单 `await` 的 `add(1,2)` = **12 B**；两个顺序 `await` 的 `async {}` = **16 B**；
`await` 前后还留着一个 `[u8; 1024]` 局部变量的 `async {}` = **1056 B**。也就是说：**跨 `.await` 存活的局部变量决定 future 的体积**，
`.await` 之后再用的变量可以被复用同一块内存。这条是 Rust 的"堆栈"没有隐藏成本的原因，也是 `Box::pin` 大 future 值得测量的原因。

与另外两家"看起来都是异步"的语言对照，差别全在**惰性**这一点上：

| 语言 | 调用异步函数的瞬间 | 真正开始执行的时刻 |
| :--- | :--- | :--- |
| JavaScript | Promise **立即开跑**，`then` 只是接结果 | 同步部分已进入微任务队列 |
| Python | 只得到 coroutine 对象，不跑；但 `create_task()` 一调就排进循环 | 被 `Task.__step` 驱动时（见 Asyncio 的 `await` 上抛机制） |
| Rust | 只得到一个 `impl Future` 值，不跑 | 有人调用它的 `poll` 时——可能是 `block_on`，也可能是另一个 future 的 `poll` |

> [!WARNING]
> "调用了却没被 await / 没被 spawn"有两种命运，本机实测：直接丢弃返回值会报编译期
> `unused implementer of 'Future' that must be used`，并附一句 **"futures do nothing unless you `.await` or poll them"**
> （`Future` 带 `#[must_use]`）；但只要把值**绑到一个变量上**（`let f = foo();` 然后作用域结束），就**完全静默**——没有任何警告。
> 对照 JS：Promise 在创建瞬间已经跑了；对照 Python：忘 `await` 有运行期 "coroutine was never awaited" 警告。
> Rust 的静默来自类型系统——一个没人 poll 的 future 只是"一个被绑定后丢弃的值"，语法上无可指摘。

## poll, Waker and Context

`Future` 只有一个必需项：

```rust
pub trait Future {
    type Output;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output>;
}
```

把 `self` 写成 `&mut Self` 会直接被拒（本机实测）：

```text
error[E0053]: method `poll` has an incompatible type for trait
   |             ^^^^^^^^^ expected `Pin<&mut NoPin>`, found `&mut NoPin`
```

契约有三条，**违反第一条就是生产事故而不是编译错误**：

1. 返回 `Poll::Pending` 时，**必须保证将来某个时刻 `cx.waker()` 被调用**（或"已经被调用过"的状态可查）。漏 wake = 任务永久挂起。
2. 每次 `poll` 都要**用当前 `cx.waker()` 覆盖**上一轮的：waker 可能换人（future 被移进另一个任务）。
3. 返回 `Ready` 之后**不能再被 `poll`**。std 实现普遍 `panic!`（手写 `AddFut` 的第二次 `poll` 在本机确实 panic）。

漏 wake 的最小复现（本机实跑，`block_on` 换成自造 mini runtime + 超时）：

```rust
struct NeverReady;
impl Future for NeverReady {
    type Output = ();
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        *STASHED.lock().unwrap() = Some(cx.waker().clone()); // 存下来却没人调用 = 永久挂起
        Poll::Pending
    }
}
```

mini runtime 的 `run_until_idle(deadline)` 语义是 “队列在 deadline 内跑空返回 `true`，否则返回 `false”。实测：
`NeverReady` 让 `run_until_idle(150ms)` 返回 **false**、耗时 **150 ms**（任务停在队列外，没人唤醒）；把 `STASHED` 里那个 waker
手工 `wake()` 一次，任务被重新 `poll`（poll 计数 1 → 2），但因为它是 `NeverReady`，依旧 `Pending`——**唤醒只保证"再 poll 一次"，
不保证推进**。这就是挂死类 bug 的形态：现象是"卡住"，不是"报错"。

驱动方与 future 的骨架（本文所有 poll / wake 数字都出自这一份无外部依赖的 mini runtime，既不依赖 `futures` 也不依赖 tokio）：

```rust
struct Task {
    future: Mutex<Option<Pin<Box<dyn Future<Output = ()> + Send>>>>,
    queued: AtomicUsize,
    rt: Arc<Runtime>,
}

impl Wake for Task {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }
    fn wake_by_ref(self: &Arc<Self>) {
        if self.queued.swap(1, Ordering::SeqCst) == 0 {
            self.rt.queue.lock().unwrap().push_back(self.clone()); // 去重入队
        }
    }
}
// run_until_idle: 出队 → queued=0 → 持锁 poll → Ready 则把 future 置 None
```

### Lost Wakeup Meets a Lazy Timer

真实定时器一定是"另外的线程/系统调用在 future 之外完成事件"，于是有一个非常容易被写错的窗口。本机实现了一份 30 ms 定时器，
到期时刻在 `sleep_eager(dur)` **构造时**算出（而不是 poll 时），然后故意 `std::thread::sleep(80ms)` 不让任何人 poll：

```rust
let eager = sleep_eager(Duration::from_millis(30)); // 表已经开跑
std::thread::sleep(Duration::from_millis(80));      // 这段时间没人 poll 它
rt.spawn(eager);                                    // 注册 waker 时，事件早就过去了
```

| 写法 | 本机结果 |
| :--- | :--- |
| 到期时只 wake 已注册的 waker，不记录状态 | `idle = false`，**永久挂起**（事件先于注册发生，`wake` 打给了空气） |
| 到期时**额外把 id 写进 `fired` 集合**，`poll` 先查它 | `idle = true`，首次 poll 直接 `Ready`（elapsed 记到 0 ms） |
| 到期时刻在**首次 poll 时**才算（`async fn timer_sleep`） | `idle = true`，实测 37 ms 后完成 |

三条结论：**"判到期 + 存 waker"必须在一把锁里**；**事件比注册早到时必须留下可查的痕迹**；
**future 的构造不等于计时的开始**。这三条在 tokio 与 futures 的定时器实现里都是显式处理的，写自定义 future 时同样要处理。

## Pin Exists Because the State Machine Is Self-Referential

`async fn` 编译出的状态机会把"跨 `.await` 存活的局部变量"存进自身，还会**引用自己的字段**（`v` 与指向它的 `r` 在同一个结构体里）。
一旦这个值被移动，`r` 就指向旧地址——这是真实的悬垂。于是编译器要求 `poll` 的接收者是 `Pin<&mut Self>`：**承诺不把这个值再移动**。

本机实测最反直觉的一条：**编译器生成的 future 一律 `!Unpin`**，哪怕它根本没有自引用：

```rust
fn needs_unpin<T: Unpin>(_t: T) {}
async fn leaf() -> u32 { 1 } // 无借用、无 await，最干净的状态机
needs_unpin(leaf());
```

```text
error[E0277]: `{async fn body of leaf()}` cannot be unpinned
  = note: consider using the `pin!` macro
          consider using `Box::pin` if you need to access the pinned value outside of the current scope
```

所以不要指望"我这个 future 应该没自引用所以能 `Pin::new`"——编译器的答案对**所有** `async fn` / `async{}` 都是 `!Unpin`。
反过来，普通含 `PhantomPinned` 的类型报的是同族诊断（实测）：`the trait Unpin is not implemented for PhantomPinned`，
同一个 help 文案。

选择清单：

| 需求 | 写法 | 代价与陷阱 |
| :--- | :--- | :--- |
| 在 `async fn` 里 await 一个本地 future | `let f = foo(); f.await;` 直接 await 即可（本机实测通过） | 一旦要把 future 存在 `async fn` 之外再 await，就得先 `pin!` |
| 当前作用域内固定 | `let f = std::pin::pin!(foo());` | 离开作用域即失效，不能返回 |
| 需要逃逸 / 装箱进容器 / `dyn` | `Box::pin(foo())` → `Pin<Box<dyn Future<Output = T> + Send>>` | 一次堆分配；`Pin<Box<T>>` 与 `Box<T>` 同宽（本机实测 16 B，`Pin` 是零开销 newtype） |
| 已保证不移动、想要 `Pin` | `unsafe { Pin::new_unchecked(&mut f) }` | 见下 |
| 类型本身可以安全移动 | `Unpin` 是 auto trait，绝大多数普通类型自动满足，可直接 `Pin::new`；`futures::pin_mut!` 是 std `pin!` 的历史替身 | `!Unpin` 的对象只有 `pin!` / `Box::pin` / `unsafe` 三条路 |

`Pin::new_unchecked` 的安全不变式（"被 pin 的内存地址从此不再变化，且不能把 `&T` 交出去让人移动它"）**自 1.99.0 起被改动过**：
1.99.0 的 Compatibility Notes 原文是一条 *"The `Pin::new_unchecked` has had its safety invariants changed slightly"*。
本机是 1.98.1，跑不出改动前后的差异，**具体新措辞请以 1.99.0 的 std 文档为准**；能确定的是：这条改动被记在
"兼容性说明"里，意味着旧代码的 `unsafe` 前提可能要重审。相关的字段级固定 `#[pin]` / `pin_ergonomics` **至今 unstable**（Unstable Book 仍在列）。

## The Runtime Is the Scheduler

`block_on` 与 `spawn` 都是库提供的。tokio 实测（`#[tokio::main(flavor = "current_thread")]`，即"单线程 + 协作"）：

| 写法 | 实测耗时 |
| :--- | :--- |
| `tokio::join!` 三个 `tokio::time::sleep(50ms)` | 61 ms（并发等待） |
| 同一个 current_thread runtime 里顺序 `await` 三次 | 175 ms |
| 3 个 task 各调 `std::thread::sleep(50ms)` | **177 ms**（阻塞把唯一 worker 独占，任务被迫串行） |
| 同样 3 个阻塞调用换 `spawn_blocking` | 60 ms |
| `multi_thread` worker 4，16 个 task | 落到 **2 个**不同 OS 线程 |
| 单个 task 连续 `yield_now()` 64 次 | 始终 **1 个**线程（本机未观察到迁移） |

两点读法：**"并发"来自 `join!` / `select!` / `spawn`，不来自 `await`**（顺序 `await` 就是串行）；
最后一行**不能当保证用**——task 不绑定线程，别在 async 代码里依赖 `thread_local!` 或"同一线程"假设；需要每任务上下文就用 `tokio::task_local!`。

`spawn` 的约束是库写的，报错也就长在库上（本机 `cargo check`，tokio 1.53.2）：

```text
error: future cannot be sent between threads safely
   = help: within `{async block@src/lib.rs:8:18: 8:28}`, the trait `Send` is not implemented for `Rc<u32>`
note: future is not `Send` as this value is used across an await
 9 |         let r = Rc::new(1u32);
   |             - has type `Rc<u32>` which is not `Send`
10 |         tokio::time::sleep(Duration::from_millis(1)).await;
   |                                                      ^^^^^ await occurs here, with `r` maybe used later
note: required by a bound in `tokio::spawn`
176 |         F: Future + Send + 'static,
```

诊断法：**先读"used across an await"指出的那一行**，它直接点名"哪个变量跨了 await 点"。三条出路，按优先级：
把该变量的生命周期收紧到 `await` 之前（`let x = ...; drop(x); fut.await`）；换成 `Arc`；或者干脆承认它是单线程的，
用 `LocalSet` + `spawn_local`（本机实测跑通了持 `Rc` 的 future，返回值 7）。`'static` 那一半则常表现为
`E0521: borrowed data escapes outside of function`——想 await 一个借用的东西，得先 clone 或改成结构化并发作用域。

阻塞调用毒害线程池的机理与 netpoller 那套是镜像问题：Go 遇到阻塞系统调用会把 P 交出去换别的 goroutine 跑（运行时兜底），
Rust 的 runtime **不知道**你在 `std::thread::sleep`，它只会傻等这次 `poll` 返回。两条出路各有代价：
`spawn_blocking` 把活儿丢进独立阻塞线程池（有 `max_blocking_threads` 上限，多一次线程切换与队列延迟）；
`block_in_place` 把当前 worker 的队列"整体搬到别的线程"，**且只在多线程 runtime 可用**——在 current_thread 上调用会 panic，
本机实测原文是 `can call blocking only when running on the multi-threaded runtime`。同族还有另一条只能在运行期撞到的 panic：
在 async 上下文里 drop 掉嵌套创建的 runtime（`block_on` 里再建一个 runtime）会得到
`Cannot drop a runtime in a context where blocking is not allowed`——**runtime 必须建在 async 世界之外**。

## Cancellation Safety in select! and JoinSet

Rust 没有"取消异常"。`select!` / `tokio::time::timeout` / `JoinHandle::abort` 的取消动作**就是 drop 那个 future**，
于是"future 在 `poll` 里做过什么不可回滚的副作用"变成了一类真实 bug——**只有 Rust 需要担心这件事**，
因为有栈的运行时（Go / Loom）取消时要么整个栈丢掉、要么函数自己返回。

本机在 tokio 上做了对照实验：两个 `Arc<Mutex<VecDeque<u32>>>`，初始各 2 条消息，`select!` 里让一个 5 ms 定时器先赢（即另一支被 drop）：

| 分支 future 的写法 | `select!` 取消后队列剩余 | 说明 |
| :--- | :--- | :--- |
| 第 1 次 `poll` 就 `pop_front()` 存进自身，第 2 次 `poll` 才处理 | **1**（消息丢了） | 取货与处理之间有可取消点 |
| 只在"数据真的到了"的那次 `poll` 里 `pop_front()`，之前一直 `Pending` | **2**（一条没动） | 不可回滚的动作放在"确定能完成"的那一步 |

同一次实验还测到 `select!` 对未就绪分支的 `poll` 次数 = **1**。纪律：**不要把 `pop` / `ack` / 计数 / 写缓冲放在一个还可能有后续
`.await` 的 `poll` 里**；要么整体可回滚，要么一步到位。写库级组合子时还要逐个文档化"我这个 future 是不是取消安全的"——
tokio 的文档为常用 await 方法逐条写了 Cancel safety 小节，判断依据始终是同一个：那次 `poll` 会不会消费掉外部状态。
`biased;` 只影响 `poll` 顺序（避免饥饿），**不改变取消语义**。

`JoinSet` 的取值顺序是**完成顺序**而非 spawn 顺序（本机 3 个 20/15/10 ms 的任务，返回 `[2, 1, 0]`）。
另外两条常被误用的语义：`JoinHandle` 被 drop **不取消**已 `spawn` 的任务（它脱离 await 继续跑，这是"孤儿任务"的来源）；
`await JoinHandle` 时任务 panic 表现为 `JoinError`，**不会**沿调用栈传播成 panic——错误处理口径见
[Error_Handling](/docs/CS/Rust/Error_Handling.md)。

锁的 async 版本与"持锁跨 `.await`"：

| 对象 | 跨 `await` 持有 | 实测/后果 |
| :--- | :--- | :--- |
| `std::sync::MutexGuard` | 在 `tokio::spawn` 的 future 里 → **编译不过** | 诊断同上：`the trait Send is not implemented for std::sync::MutexGuard<'_, u32>`，且"used across an await"点名 `g` |
| `std::sync::Mutex`（极短临界区，不跨 await） | 允许 | 只是别让 `lock()` 本身抢占到 worker |
| `tokio::sync::Mutex` | 语法合法 | 实测 `*g += 1` 正常；但持锁 `await` 会把并行段串行化，并引入死锁面 |
| `tokio::sync::RwLock` 读守卫 | 同上 | 与 `Mutex` 同族，写者独占；读并发是它的存在理由 |
| `select!` 分支里持有守卫 | 分支被 drop 时守卫一起释放 | 不会泄漏锁，但"取数据 + 写数据"被拆成两次加锁，逻辑可能不原子 |

## Async in Traits Today

| 事项 | 状态 | 出处 |
| :--- | :--- | :--- |
| `async fn` in trait（AFIT）+ RPITIT | stable 于 **1.75.0（2023-12-28）** | release notes；本机编译通过 |
| AFIT 的 future **不自动是 `Send`** | 实测 | `E0277: impl Future<Output = String> cannot be sent between threads safely`，编译器直接建议改写成 `fn f(&self) -> impl Future<Output = T> + Send` |
| 精确捕获 `use<..>` | free RPIT 于 **1.82.0**，trait 上于 **1.87.0（2025-05-15）** | 规则细节见 [Lifetime](/docs/CS/Rust/Lifetime.md) |
| `async fn` in **`dyn` trait** | **仍 unstable**，gate `async_fn_in_dyn_trait`，tracking issue **#133119**（标题已核实） | 本机实测报的是 `E0038: the trait Store is not dyn compatible ... because method get is async` |
| `#[async_trait]`（把 `async fn` 展开成 `-> Pin<Box<dyn Future + Send + '_>>`） | 外部 crate，**没过时** | 本机 1.98.1 + edition 2024 `cargo check` 通过，且 `&dyn AsyncApi` 可调用 |
| `trait_variant::make`（同一 trait 生成 `+ Send` 变体） | 外部 proc-macro crate（**不是语言特性，无版本可引**） | 本机编译通过 |
| async closures 与 `AsyncFn` / `AsyncFnMut` / `AsyncFnOnce` | async closures stable 于 **1.85.0（2025-02-20）**；`AsyncFn*` 本机可直接用作 bound | release notes + 本机编译通过 |
| `IntoFuture` 与 `.await` 自定义类型 | stable（`.await` 走 `IntoFuture`） | 本机：只实现 `IntoFuture` 的 `Awaitable.await` 编译通过 |
| `Future` / `IntoFuture` 进 prelude | **edition 2024** | 本机同一份源码：`--edition 2021` 报 `E0405: cannot find trait Future in this scope`，`--edition 2024` 通过 |
| `Stream` / `Sink` / 组合子 | **不在 std**，在 `futures` 0.3.34 | std 里既没有 `Stream` 也没有 `for await`；异步迭代仍要 `futures` 的 `StreamExt::next()` 配 `while let` 手写 |
| `gen` 块 / `async gen` / `yield` | **仍 unstable** | 本机：`E0658: gen blocks are experimental`（issue **#117078**）、`E0658: yield syntax is experimental`（issue **#43122**）；`gen` 关键字仅在 edition 2024 被保留 |
| `async` 块在 `const fn` 里 | **仍 unstable**（`const_async_blocks`） | 本机：`E0658: 'async' blocks are not allowed in constant functions`，issue **#85368** |

需要 `dyn` 的动态分发时，今天（1.98/1.99）的三条路依然要选一条：**`#[async_trait]` 装箱**（最省事、代价是每次调用一次堆分配）、
**手写 `-> impl Future + Send` 的 RPITIT + 具体类型泛型**（零成本但不能 `dyn`）、
**枚举/静态分发**。对象安全本身的限制见 [Trait_System](/docs/CS/Rust/Trait_System.md)，
指针与 `Pin` 之外的固定性问题见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)。

## Four Async Designs Side by Side

| 维度 | Rust + tokio | Go | Python asyncio | Java Loom |
| :--- | :--- | :--- | :--- | :--- |
| 谁产生状态机 | rustc（`async` → 匿名结构体） | 无（有栈协程，不需要状态机） | 编译器把 `yield` 帧化成 generator 帧 | 编译器不变，JVM 提供 `Continuation` |
| 谁调度 | **库**（tokio 等，可选） | Go runtime（语言自带） | 标准库 event loop（单线程） | JVM（ForkJoin 载体线程池） |
| 挂起时保存什么 | future 结构体里的字段（**无栈**） | 整段 goroutine 栈（可增长堆栈） | coroutine 帧 | continuation 的栈帧（堆上） |
| 让出时机 | 只在 `.await`（返回 `Pending`） | 系统调用 / channel / 显式点 + 信号式抢占 | 只在 `await` | 阻塞 API 内部自动让出 |
| 抢占 | 无，纯协作 | **有**（Go 1.14 起异步抢占） | 无 | 载体线程有抢占，任务本身协作 |
| 并发单位与栈 | `Task` = 一个 future，几十字节，可无分配 | goroutine，初始栈约 2 KB 后增长 | Task + coroutine 对象 | 虚拟线程，栈在堆上 |
| 取消 | `drop` future（需库配合，如 `abort`） | `context.Context` 显式传播 | 抛 `CancelledError` 进挂起点 | `Thread.interrupt()` |
| 阻塞调用的后果 | 独占 worker，整池吞吐塌方 → 需 `spawn_blocking` | runtime 自动 handoff，P 转给别人 | 整个循环停摆（见 Asyncio） | 载体线程被 pin（synchronized / native 帧） |
| 类型系统承担的成本 | `Pin` / `Unpin` / `Send` 泄漏到签名上 | 无（代价在运行期与栈内存） | 无（代价是运行时警告与调试） | 无（代价是 pinning 与调试可见性） |
| 能否吃满多核 | 能（多线程 runtime，无全局锁） | 能 | 不能（GIL，见 [GIL](/docs/CS/Python/GIL.md)） | 能 |

一句话总结这三家的分工：**Go 用运行时把复杂度吃进自己、把简单留给语法**；**Python 把让出点写在语法里、调度留给标准库**；
**Rust 反过来——语法只给糖，运行时外包给库，代价由类型系统（`Pin` + `Send`）替所有调用方预付**。
Loom 的虚拟线程机制细节见 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)，
Go 的 fd 就绪路径见 [netpoller](/docs/CS/Go/netpoller.md)，调度器与抢占见 [runtime](/docs/CS/Go/runtime.md)，
epoll 层见 [Netpoll](/docs/CS/Framework/Netpoll.md)。

## When This Design Hurts

| 症状 | 根因 | 处理方向 |
| :--- | :--- | :--- |
| 程序"卡住"但没有任何报错 | 漏 `wake`，或 future 构造后没人 poll | 给驱动方加超时（本文 mini runtime 的 `run_until_idle(deadline)` 就是这个用途）；检查 `poll` 返回 `Pending` 的每条路径 |
| `future is not Send` 满天飞 | 有栈的运行时没有这个概念，`Send` 是 Rust 独有的编译期税 | 收紧变量生命周期 / `Arc` / `LocalSet`；多线程 runtime 才要求 `Send` |
| 异步代码里混进同步 SDK | 每次阻塞都独占一个 worker | 先补齐异步客户端；否则 `spawn_blocking` 并给它设上限 |
| CPU 密集任务用 async 不涨吞吐 | 没有让出点，任务只会排队 | 走 `rayon` 数据并行或普通线程池，并发度按核数而不是按连接数 |
| 一个 trait 既要 `dyn` 又要 async | `async_fn_in_dyn_trait` 仍未稳定 | `#[async_trait]` 装箱，或把 async 方法拆到单独的 trait 上用泛型 |

Web 框架与生态选型（axum / actix-web / hyper / tower 的取舍）不在本文，见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)；
线程与 `Send` / `Sync` 的世界见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

## Links

- [Concurrency](/docs/CS/Rust/Concurrency.md)
- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [netpoller](/docs/CS/Go/netpoller.md)
- [Asyncio](/docs/CS/Python/Asyncio.md)

## References

- [std::future::Future](https://doc.rust-lang.org/std/future/trait.Future.html)
- [std::task::Wake](https://doc.rust-lang.org/std/task/trait.Wake.html)
- [std::task::Context](https://doc.rust-lang.org/std/task/struct.Context.html)
- [std::pin::Pin](https://doc.rust-lang.org/std/pin/struct.Pin.html)
- [std prelude and edition differences](https://doc.rust-lang.org/std/prelude/index.html)
- [Rust 2024 prelude](https://doc.rust-lang.org/edition-guide/rust-2024/prelude.html)
- [Release notes history](https://doc.rust-lang.org/stable/releases.html)
- [Unstable Book: async_fn_in_dyn_trait](https://doc.rust-lang.org/unstable-book/language-features/async-fn-in-dyn-trait.html)
- [Tracking Issue for async_fn_in_dyn_trait #133119](https://github.com/rust-lang/rust/issues/133119)
- [Tracking Issue for gen_blocks #117078](https://github.com/rust-lang/rust/issues/117078)
- [The rustc book: traits and dyn compatibility](https://doc.rust-lang.org/reference/items/traits.html)
- [tokio::select! macro](https://docs.rs/tokio/latest/tokio/macro.select.html)
- [tokio runtime overview](https://docs.rs/tokio/latest/tokio/index.html)
- [tokio::task::LocalSet](https://docs.rs/tokio/latest/tokio/task/struct.LocalSet.html)
- [async-trait crate](https://docs.rs/async-trait/latest/async_trait/)
- [trait-variant crate](https://docs.rs/trait-variant/latest/trait_variant/)
- [The Rust Async Book](https://rust-lang.github.io/async-book/01_getting_started/01_chapter.html)
