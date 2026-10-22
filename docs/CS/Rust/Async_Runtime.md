## Introduction

[Async](/docs/CS/Rust/Async.md) 讲清了那条分界线：语言只给了 `async` / `await` 语法、`Future` trait、`Poll` 与 `Waker`，
**调度、IO 就绪通知、定时器、`spawn`、取消全都不在语言里**。本文讲分界线右侧那一半——**运行时到底做了什么，
tokio 是怎么调度的，以及这套模型在你写下 `.await` 时向你收了哪些税**。

一句话概括：**语言给了"如何推进一个计算"（poll），运行时负责"何时推进谁"（调度 + 事件 + 时间）**。
后者的任何一条都不由标准库保证——这正是"忘记 `.await`""在 async 里 `std::thread::sleep`"
"`select!` 里读了一半被丢掉"这类 bug 全部编译通过、只在运行期发作的原因。

本文的实测数字沿用 [Async](/docs/CS/Rust/Async.md) 的那套环境（`rustc 1.98.1` + tokio 1.53.2 本机跑出），
而**版本事实**按本文写作时核实的结果写：

| 事实 | 核实值 | 来源 |
| :-- | :-- | :-- |
| Rust stable | **1.99.1**，2026-10-15 发布，patch release | releases.rs 1.99.1 |
| tokio 最新稳定 | **1.54.1**，2026-10-21 发布，MSRV **1.85**（1.54.0 发布后已 yank） | crates.io API |
| `worker_threads` 默认 | 系统可用核心数（`std::thread::available_parallelism`），可被 `TOKIO_WORKER_THREADS` 覆盖 | docs.rs Builder |
| `max_blocking_threads` 默认 | **512**，阻塞线程空闲 **10 秒** 后退出 | docs.rs Builder |

> [!WARNING]
> tokio 的 `io-uring` **不是默认路径**：它是 unstable feature（同族还有 `tracing` / `schedule-latency` / `taskdump`），
> 必须同时打开 feature 与 `--cfg tokio_unstable` 才编译，且仅 Linux 可用。把"tokio 支持 io_uring"当既成事实的人，
> 实际拿到的是 mio 的 readiness + poll 路径；真要 completion 模型看本文对比表里的 glommio / compio。

`Pin` 那一半（为什么 `poll` 的接收者必须是 `Pin<&mut Self>`、自引用状态机、`Unpin` 的误解）单独拆到了
[Pin](/docs/CS/Rust/Pin.md)；本文只在需要时引用，不重述。

## What a Runtime Does: Reactor, Executor, Timer

### The Language Stops at Future and Waker

先把"语言提供"和"运行时提供"逐条摆开，这张表是后面所有内容的索引：

| 能力 | 谁提供 | 形态 |
| :-- | :-- | :-- |
| `async` / `await` 语法、状态机生成 | 语言 | 编译器产出匿名 `impl Future` |
| `Future` / `Poll` / `Context` / `Waker` / `Pin` | std | 只有类型与 trait，**没有任何一个 executor** |
| 就绪通知（epoll / kqueue / IOCP / io_uring） | **运行时** | tokio 下是 `mio`（或 unstable 的 io-uring） |
| 任务队列与调度（谁下一步 poll） | **运行时** | 单线程本地队列 / 多线程 work-stealing |
| 定时器轮 | **运行时** | tokio 的 time driver，分级时间轮 |
| `spawn` / `JoinHandle` / `JoinSet` / `select!` | **运行时** | 约束 `'static + Send` 是库自己写的 |
| 阻塞线程池 | **运行时** | `spawn_blocking`，上限 512 |
| 取消 | **运行时 + 约定** | 语义就是 drop，[Async](/docs/CS/Rust/Async.md) 已论证 |

所以运行时最少由**三件独立的事**组成，缺一件就只能跑"不需要 IO、不需要时间、不需要并发"的 future。

### The Reactor: Turning OS Readiness Into Wakers

**反应器（reactor）**负责把"这个文件描述符可读了"翻译成"调用那个任务的 `Waker`"。
它自己不 poll 任何 future，只是维护一张 `fd → waker` 的表：

```rust
// 概念骨架，不是 tokio 源码；注释说明每一步的职责
struct Reactor {
    poll: mio::Poll,               // 封装 epoll / kqueue / IOCP
    registry: Slab<Registration>,  // token -> (fd, 感兴趣的方向, Waker)
}

impl Reactor {
    fn turn(&mut self, timeout: Option<Duration>) {
        // 阻塞在 OS 上等事件；这是整个 runtime 里唯一真的阻塞的地方
        for event in self.poll.poll(&mut events, timeout)? {
            // 事件到达 -> 取出对应 waker -> wake()（只是重新入队，不保证这次能推进）
        }
    }
}
```

关键性质：**reactor 唤醒的是"任务"，不是"那个具体的 future"**。一个任务里可能同时 `select!` 了三个 socket，
reactor 只知道"fd 7 可读了"，它把整个任务重新排进队列，由 executor poll 一遍让状态机自己判断是哪个分支就绪。
这就是为什么"虚假唤醒"在 Rust 异步里是**正常且必须容忍**的：`poll` 返回 `Pending` 完全合法，executor 只是白跑一趟。

顺带解释一个常见困惑：为什么 `TcpStream::read().await` 之前不需要先 poll 一次看是否就绪？
因为 readiness 模型是**先操作、后注册**：先真的调一次 `read(2)`，返回 `EWOULDBLOCK` 才把 fd 与 waker
注册进 reactor 并返回 `Pending`。这也意味着**"事件比注册早到"的窗口必须处理**——
[Async](/docs/CS/Rust/Async.md) 的 Lost Wakeup 一节用自造定时器复现过：只 wake 而不留可查状态，任务就永久挂起。

### The Executor: A Queue of Pollable Tasks

**执行器（executor）**是一个循环：从队列里取任务 → poll → 若 `Pending` 就放着等下次被唤醒。
它不与 OS 打交道（除了 reactor 那一处阻塞），也不知道"IO"这个概念。

```rust
// 多线程 runtime 每个 worker 线程上跑的循环，极度简化
loop {
    // 先在本地队列与全局注入队列里找活，都没有就去别的 worker 队尾偷（work-stealing）
    let task = self.next_local_task().or_else(|| self.steal_from_others())?;
    // 推进任务"一次"：poll 到 Pending 或 Ready 就交还控制权，不会一直 poll 到 Ready
    match task.poll_once() {
        Poll::Ready(()) => self.complete(task), // 任务结束，释放它的 future
        Poll::Pending   => {}                   // 什么都不做，等 waker 把它重新入队
    }
    // 每跑若干任务（tokio 的事件预算）回头去 reactor 那里收一次就绪事件
}
```

第 2 步的"**一次**"是理解调度模型的核心：**`poll` 返回时，任务就交还控制权了**。
要么 `Ready`（完了），要么 `Pending`（把 waker 交给了别人，等被叫醒）。
executor 永远不会在一个任务上死循环——除非那个任务自己不返回。

### The Timer: The Third Wheel

定时器在概念上和 reactor 完全同构，只是事件源从"fd 就绪"换成"时刻到达"：
注册 `(deadline, waker)`，时间到了就 `wake`。tokio 用分级时间轮实现，所以
`tokio::time::sleep` 的精度与代价与定时器数量基本无关。

它独立存在的意义在于：**只有启用 time driver，`sleep` / `timeout` / `interval` 才存在**——
只开 `rt` 的 runtime 里调 `tokio::time::sleep` 会在运行期 panic。
这是"运行时是库"的直接后果：能力是拼装出来的，不是默认全开。

三者拼起来的主循环只有三步，**且只有第二步会阻塞**：跑空任务队列 → 以"最近一个定时器的剩余时间"为超时
去 OS 上等事件 → 把到期的定时器与就绪的 fd 变成 `wake`，回到第一步。
阻塞的是 reactor 在等 OS，不是任务在等 IO——**这就是一个 worker 线程能跑几千个连接的原因**：
真正阻塞的系统调用只有这一处，而且带超时。

## tokio's Scheduling Model

### Two Flavors

tokio 提供两种运行时，`#[tokio::main]` 用 `flavor` 选择：

| 维度 | `current_thread` | `multi_thread` |
| :-- | :-- | :-- |
| worker 线程数 | 1（就是调用 `block_on` 的那个线程） | 默认 CPU 核心数，可 `worker_threads(n)` 或 `TOKIO_WORKER_THREADS` 覆盖 |
| 队列与负载均衡 | 单一本地队列 | 每 worker 一个本地队列 + 全局注入队列，**work-stealing**（本地空了从别人队尾偷） |
| 任务是否迁移 | 不迁移 | 会迁移，**任务与线程没有绑定关系** |
| `spawn` 是否要求 `Send` | **不要求**（可用 `spawn_local`） | 要求（future 可能被搬到别的线程） |
| `block_in_place` | **调用即 panic** | 可用 |
| IO / timer 驱动 | 只有 `Runtime::block_on` 能驱动 | 任意 worker 都能驱动 |
| 典型用途 | 单线程确定性测试、CLI | 服务端默认 |

[Async](/docs/CS/Rust/Async.md) 实测的那组数字值得重读一遍：`current_thread` 里三个 `sleep(50ms)`
用 `join!` 是 61 ms、顺序 `await` 是 175 ms、换成 `std::thread::sleep` 是 177 ms、换 `spawn_blocking` 回到 60 ms。
**并发不来自 `await`，来自 `join!` / `select!` / `spawn`**——顺序 `.await` 就是串行，这一点在两种 flavor 下都成立。

### Work Stealing and the Task-Thread Relationship

`multi_thread` 下每个 worker 有自己的本地队列（可无锁 push/pop），另有全局注入队列
（从 runtime 外部 `Handle::spawn` 进来的任务先落这里）。取活顺序：本地队列 → 全局注入队列 → 偷别人的，
偷的时候从**队尾**取以减少竞争。

由此得到一条必须记住的结论，**也是 [Async](/docs/CS/Rust/Async.md) 那条"不要当保证用"背后的机制**：
**任务与 OS 线程之间没有绑定关系**，同一个任务的两轮 `poll` 可能在不同线程上执行；
本机实测"单个 task 连续 `yield_now()` 64 次始终落在 1 个线程"只是**没有发生迁移**，不是不会迁移。

因此以下写法全部是错误假设：

| 错误假设 | 后果 |
| :-- | :-- |
| 用 `std::thread_local!` 存 per-task 上下文 | 任务迁移后读到别的线程的那份，或读到空的 |
| 依赖"同一个连接总在同一个线程上"做无锁缓存 | 迁移后缓存失效，或产生逻辑竞态 |
| 用线程 ID 做分片 / 哈希 | 分片随迁移抖动 |
| 认为 `Cell` / `Rc` 在 spawn 的任务里安全 | 编译期就被 `Send` 拦下（见下节） |

per-task 上下文要用 `tokio::task_local!`；per-worker 的 CPU 亲和性敏感场景应改用 thread-per-core 运行时（见对比表）。

### Tasks Are Not Preempted

**这是协作式调度最硬的一条约束**：tokio 的任务**不可被抢占**。
一个任务一旦被 poll，就会一直执行到它返回 `Pending` 或 `Ready`；在这期间它**独占那个 worker 线程**。

推论直接而严厉：

```rust
// 反例：这个任务会让分到同一个 worker 上的所有其它任务一起饿死
tokio::spawn(async {
    loop {
        do_some_work();          // 没有 .await，没有让出点
        // 即便 do_some_work() 每次只花 100 µs，worker 也永远不会回头看队列
    }
});
```

| 症状 | 根因 |
| :-- | :-- |
| 一个 CPU 密集任务把整池吞吐打到接近单核 | 该任务没有让出点，占住 worker；其它任务在队列里等 |
| `multi_thread` 下延迟突然出现长尾 | 某个任务在一个 `poll` 里干了太多活 |
| `current_thread` 下整个程序"卡住" | 唯一 worker 被一个不返回的 `poll` 占住 |

正确的处理不是"多开几个 worker 线程"（那只是把饥饿摊薄），而是：

1. **CPU 密集的活离开 async 世界**：`spawn_blocking` 或 `rayon`。
2. **长循环里手动让出**：`tokio::task::yield_now().await`，或在每 N 次迭代后 `sleep(Duration::ZERO)`。
3. **按核数而不是按连接数设并发度**：并发单位在这里是"任务"，几百个任务抢 8 个 worker 是常态。

> [!NOTE]
> `yield_now()` 的语义是"把自己重新排进队列尾部然后返回 `Pending`"，**不是**让出给某个具体任务。
> 每轮工作都很短时，它的入队/出队开销可能超过收益。

### What block_in_place Actually Does

`block_in_place` 常被误读成"允许阻塞的魔法"，它做的只有一件事：
**在阻塞之前，把当前 worker 的其余任务连同驱动职责移交给另一个 worker 线程，然后在本线程上阻塞**。

```rust
// 这里可以安全地调用同步阻塞 API，本 worker 的其它任务已被移交
let s = tokio::task::block_in_place(|| std::fs::read_to_string("big.txt"));
```

代价与限制（tokio 官方文档逐条写明）：

- **只在 `multi_thread` 可用**，在 `current_thread` 上调用直接 panic（本机实测原文
  `can call blocking only when running on the multi-threaded runtime`）。
- **同一个任务内的并发分支仍然被挂起**：`join!` 里的另一个分支不会推进。要避免这个就改用 `spawn_blocking`。
- **其中的代码不可被取消**：关闭 executor 时会无限等待它跑完；`shutdown_timeout` 只是不再等，任务照样继续跑。
- 它是**唯一**被文档允许"内部再 `block_on` 回到 async 上下文"的位置。

## Blocking and CPU-Bound Work

### spawn_blocking and the Blocking Pool

Rust 的 runtime **不知道**你在 `std::thread::sleep` 或调同步 SDK，它只看到"这次 `poll` 还没返回"，
于是按不可抢占的性质——**整个 worker 线程连同它队列上的所有任务一起停摆**。
这与 Go 的 netpoller 是镜像问题：Go 遇到阻塞系统调用会把 P 交出去换别的 goroutine 跑（运行时兜底），
见 [netpoller](/docs/CS/Go/netpoller.md)；Rust 没有这个兜底，**责任在调用方**。

`spawn_blocking` 把闭包丢进一个**独立的阻塞线程池**（不是 worker 线程池），任务变成"等一个线程返回"，
worker 立刻回去跑别的：

```rust
// 把同步阻塞调用隔离出去；这里可以随便阻塞：同步 DB 驱动、CPU 密集计算、fs 调用
let data = tokio::task::spawn_blocking(move || std::fs::read_to_string(path)).await??;
```

池的参数：`max_blocking_threads` 默认 **512**，空闲 **10 秒** 后线程退出（`thread_keep_alive` 可改）。
它和 worker 池是**两个池**，因此：

| 现象 | 解释 |
| :-- | :-- |
| `spawn_blocking` 之后吞吐反而下降 | 阻塞池被打满（512 是真实上限），任务在它自己的队列里排队 |
| 阻塞池打满时 async 侧仍然流畅 | 两个池互不影响，这正是隔离的价值 |
| 大量小任务走 `spawn_blocking` 变慢 | 每次都有线程切换 + 队列延迟，粒度太细不划算 |

### Why CPU-Bound Work Should Not Live in async

CPU 密集的代码即使**不阻塞**（纯计算），放进 async 也拿不到收益，只有成本：

1. 它没有 IO，reactor 帮不上忙，并发度上限就是 worker 数；
2. 它天然缺少让出点，一个 `poll` 里算完 → 触发上一节的饥饿；
3. 状态机体积随跨 `.await` 的局部变量增长（[Async](/docs/CS/Rust/Async.md) 实测带 `[u8; 1024]` 那个例子 = 1056 B），
   大缓冲区等于给每个任务都背上一份。

正确去处：`rayon` 的数据并行或普通线程池，并发度按**核数**而不是按连接数。
要留在 async 里也行，但必须自己插让出点，且那是在模拟抢占、不是在获得并行。

### block_on Inside async Context

`Handle::block_on` 的文档把 panic 条件写得很直白：**从异步上下文里调用它就 panic**
（包括 `Runtime::block_on` 内部、`Handle::block_on` 内部、`#[tokio::main]` 标注的函数里）。
它做的是"在当前线程上把这个 future 跑到完"，于是：

- 当前 worker 被占住 → 该任务 await 的东西若依赖同池上的另一个任务，**死锁**；
- 在 `current_thread` 上它**驱动不了 IO 与 timer**，除非另有线程在同 runtime 上 `Runtime::block_on`。

唯一被认可的"从 async 回到 async"姿势是 `block_in_place` + `Handle::block_on` 组合（上一节），
同样只在 `multi_thread` 可用。

同族还有一条运行期 panic：**在 async 上下文里 drop 掉嵌套创建的 runtime** 会得到
`Cannot drop a runtime in a context where blocking is not allowed`（本机实测）。
结论是**runtime 必须建在 async 世界之外**；确实要在里头收尾就用 `shutdown_background()`
（它会留下仍在跑的 `spawn_blocking` 任务，即潜在资源泄漏）。

> [!WARNING]
> 三条同族的运行期 panic 建议一起记：`block_in_place` 在 `current_thread` 上、
> `Handle::block_on` 在 async 上下文里、runtime 在 async 上下文里被 drop。
> 它们的共同根因是同一个：**运行时需要一个"可以被阻塞"的线程，而 async 上下文里的线程恰恰不能被阻塞**。

## Send Contagion and the Single-Threaded Escape Hatch

`multi_thread` 的 `spawn` 要求 `F: Future + Send + 'static`。因为任务会跨线程迁移，
于是**任何跨 `.await` 存活的局部变量都必须是 `Send`**——这就是 `Send` 传染。
[Async](/docs/CS/Rust/Async.md) 给过那条实测诊断，读法是**先读 "used across an await" 指的那一行**，
它直接点名哪个变量跨了 await 点。

三条出路，按优先级：

| 出路 | 做法 | 代价 |
| :-- | :-- | :-- |
| 收紧生命周期 | `let x = ...; drop(x); fut.await;` | 最干净，零成本 |
| 换 `Arc` | `Rc` → `Arc`、`RefCell` → `Mutex`/`RwLock` | 原子操作成本；`Arc` 的语义细节见 [Concurrency](/docs/CS/Rust/Concurrency.md) |
| 承认它是单线程的 | `LocalSet` + `spawn_local`，或 `LocalRuntime` | 任务被钉在当前线程，不能利用多核；且不能与 work-stealing 混用 |

具体选型：

| 机制 | 适用 | 说明 |
| :-- | :-- | :-- |
| `LocalSet` + `spawn_local` | 在 `current_thread` 或 `multi_thread` 里跑一小批 `!Send` 任务 | 经典方案；`LocalSet` 自己要被 await（`run_until` / `await`）才推进 |
| `LocalRuntime` | 整体就是单线程、且大量用 `!Send` | 不需要 `LocalSet` 包裹即可 `spawn_local`；**不能在线程间移动、不能被不同线程驱动**，且与 `LocalSet` 不兼容 |
| `spawn_local` | 单个 `!Send` 任务 | 必须在 `LocalSet` / `LocalRuntime` 上下文里调，否则 panic |

注意一个容易踩的不对称：`LocalRuntime` 的 `Handle` 是 `Send` 的、可以被搬到别的线程，
但**用它在别的线程上只能 `spawn`（要求 `Send`），不能 `spawn_local`**——单线程的承诺只在创建它的那个线程上成立。

## Structured Concurrency, JoinHandle and Task Leaks

### Dropping a JoinHandle Detaches, It Does Not Cancel

这是 Rust 异步里最容易被误解的一条，与 `JoinSet` 恰好相反：

| 对象 | drop 的语义 |
| :-- | :-- |
| `JoinHandle` | **只是 detach**：任务脱离 await 继续在后台跑完，谁也不等它，返回值被丢弃 |
| `JoinSet` | **立即 abort 集合里所有任务**（`Drop` 实现写的；想让它继续跑先调 `detach_all()`） |

于是"我 spawn 了但没 await"天然产生**孤儿任务**：它继续消耗 worker 时间、继续持有资源，
而它的返回值（包括 `Err`）被静默丢弃。这是"任务泄漏"的主要形态——不是内存泄漏，是**生命周期失控**。

结构化并发的做法是让一组任务的生命周期有明确的边界：

```rust
let mut set = tokio::task::JoinSet::new();
for id in ids { set.spawn(fetch(id)); }        // 同返回类型的任务集合
while let Some(res) = set.join_next().await {  // 按完成顺序返回
    match res {
        Ok(v)  => handle(v),
        Err(e) => { set.abort_all(); break; }  // JoinError：任务 panic 或被 abort
    }
}
// 走到这里 set 被 drop -> 剩余任务被 abort，不会漏在后台
```

`join_next` 的返回顺序是**完成顺序**而非 spawn 顺序（`JoinSet` 文档原话 "the tasks will be returned
in the order they complete"，`join_all` 同样），本机 3 个 20/15/10 ms 的任务实测返回 `[2, 1, 0]`。
它本身是**取消安全**的：文档明确保在 `select!` 分支里被丢弃也**不会**有任务从集合里被移除。

### Panic Propagation

`await JoinHandle` 时任务 panic 表现为 `JoinError`，**不会**传播成 panic；
`JoinSet::join_all` 相反——任一任务 `JoinError` 会让它 **panic** 并取消剩余任务。
口径见 [Error_Handling](/docs/CS/Rust/Error_Handling.md)。

## Cancellation Safety

### Cancellation Is Drop

Rust 没有"取消异常"。`select!` 里输掉的分支、`tokio::time::timeout` 到期的 future、
`JoinHandle::abort()`，三者的取消动作**都是 drop 那个 future**。
于是"这次 `poll` 里做过什么不可回滚的副作用"变成了一类真实 bug——**只有 Rust 需要担心这件事**，
因为有栈的运行时（Go / Loom）取消时要么整个栈丢掉、要么函数自己返回。
判断标准只有一条：**那次 `poll` 会不会消费掉外部状态**。会，就取消不安全。

### Where It Bites

[Async](/docs/CS/Rust/Async.md) 的对照实验给出了最小复现：两个队列初始各 2 条消息，
`select!` 里让 5 ms 定时器先赢，于是另一支被 drop：

| 分支 future 的写法 | 取消后队列剩余 |
| :-- | :-- |
| 第 1 次 `poll` 就 `pop_front()` 存进自身，第 2 次 `poll` 才处理 | **1**（消息丢了） |
| 只在"数据真的到了"的那次 `poll` 里 `pop_front()`，之前一直 `Pending` | **2**（一条没动） |

同次实验还测到 `select!` 对未就绪分支的 `poll` 次数 = **1**——**被丢弃的分支只被 poll 了一次**，
而这唯一的一次足以让它把消息吃掉。

`biased;` 只改变 `poll` 顺序（避免饥饿），**不改变取消语义**。别指望用它修取消 bug。

### A Catalog of Cancel-Unsafe Futures

| Future / 方法 | 是否取消安全 | 原因 |
| :-- | :-- | :-- |
| `AsyncReadExt::read(&mut buf)` / `read_exact` | **不安全** | 可能已读进 `buf` 一部分才返回 `Pending`；被取消后这部分数据丢失、`buf` 状态不明 |
| `AsyncWriteExt::write_all` | **不安全** | 可能已经写出一部分；被取消后连接处于半写状态 |
| `tokio::time::sleep` | 安全 | 无外部副作用，drop 只是不醒了 |
| `tokio::sync::mpsc` / `oneshot` 的 `recv` | 安全 | 文档明确保证消息不会丢 |
| `JoinSet::join_next` | 安全 | 取消不会移除集合中的任务 |
| `tokio::fs` 系列 | 基本安全 | 底层走 `spawn_blocking`，取消后操作照常跑完（也就意味着**它其实不响应取消**） |
| `block_in_place` 里的代码 | **不可取消** | 文档明确：关 executor 时会无限等它跑完 |

> [!NOTE]
> tokio 的文档为常用 await 方法逐条写了 Cancel safety 小节，写库级组合子时应当照做。
> 实用的自检：把这个 future 的 `poll` 想象成"可能随时在任意一行被剪断"，
> 看被剪断后外部世界是否处于一个你自己定义得出来的状态。

### How to Write a Cancel-Safe Future

纪律只有两句：**不要把 `pop` / `ack` / 计数 / 写缓冲放在一个还可能有后续 `.await` 的 `poll` 里**；
**要么整体可回滚，要么一步到位**。取消安全的写法是"判断"与"消费"之间没有让出点：

```rust
impl Future for RecvOne {
    type Output = u32;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<u32> {
        match self.queue.lock().unwrap().pop_front() {
            // 拿到与返回是原子的，不存在"取了但没交出去"的窗口
            Some(v) => Poll::Ready(v),
            // 没数据就只登记 waker，这一步没有任何副作用，取消它是无损的
            None => { self.register(cx.waker()); Poll::Pending }
        }
    }
}
```

## Runtime Comparison

选型前先读 [Ecosystem](/docs/CS/Rust/Ecosystem.md) 的 Async Runtimes 一节（crate 版本与依赖成本），
本文只补**调度模型与 IO 驱动**这一层。

| 运行时 | 版本（核实） | 调度模型 | IO 驱动 | 任务与线程 | 适用场景 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **tokio** | 1.54.1（2026-10-21，MSRV 1.85） | `current_thread` 或 `multi_thread` **work-stealing** | readiness + poll（`mio`）；**io-uring 是 unstable feature**，需 `--cfg tokio_unstable` | 任务不绑线程，会迁移 | 默认选项；hyper / axum / tonic / reqwest / sqlx 都长在它的类型上 |
| **smol** | 2.0.2（约两年前，MSRV 1.63） | 极简 executor，可组合（`async-executor` + `async-io`） | `async-io`：单 reactor 线程 + readiness | 单线程或多 worker | 想要小而可控；**async-std 官方指定的迁移目标** |
| **async-std** | 1.13.2 | std 镜像 API，自带 executor + 线程池 | readiness | — | **不要选**：crates.io 明写 "Deprecated in favor of `smol`"，附 RUSTSEC-2025-0052（unmaintained） |
| **glommio** | 0.9.0（两年多前，MSRV 1.65） | **thread-per-core**，任务不迁移 | **io_uring**（completion） | 一个核一个线程 | Linux、高 IO、追求尾延迟、CPU 亲和性敏感 |
| **compio** | 0.19.2（2026-08-18）；0.20.0-beta.1 为预发布 | completion-based（自述 "Completion based async runtime"） | Windows IOCP / Linux io_uring | — | 要 completion 模型又想跨 Windows/Linux；**未声明 MSRV** |
| **embassy** | embassy-executor 0.10.0 | 嵌入式 executor，`no_std` | 硬件中断 / 外设驱动提供 waker | 单线程（裸机） | 裸机与嵌入式；`no_std` 侧的唯一现实选择 |

> [!WARNING]
> 版本与"最后发布"要分开看：glommio 0.9.0 与 smol 2.0.2 都**两年以上未发新版**，但性质不同——
> smol 是 async-std 官方指定的迁移目标；glommio 停在 0.9 意味着 thread-per-core 这条路上**没有活跃的维护**。
> 选它们之前按 [Ecosystem](/docs/CS/Rust/Ecosystem.md) 那套可机检的办法（`cargo audit` + 最后发布时间）再验一次。

三种 IO 模型决定了它们长什么样：**readiness + poll**（用户持有 buffer，返回 `Ready` 时 buffer 立刻可复用——
tokio 默认路径与 smol）、**completion / io_uring**（**内核持有 buffer 到操作完成**，运行时必须全程持有且不能移动它——
glommio、compio）、**中断驱动**（ISR 置位、executor 轮询标志——embassy）。
completion 那条约束与 [Pin](/docs/CS/Rust/Pin.md) 是同一族问题：**异步操作的生命周期跨越了 await 点，
编译器必须能证明被内核引用的那块内存在这段时间内稳定**。

## Observability

异步程序的调试难点在于"栈"不是栈：任务的调用链被拆成了状态机字段，panic 栈里看不到"谁在等谁"。
三层手段：

| 手段 | 打开方式 | 给什么 |
| :-- | :-- | :-- |
| `tracing` + `#[instrument]` | 普通依赖 | 每个请求的 span，跨 await 点的因果链 |
| `tokio-console` | feature `tracing` + `--cfg tokio_unstable`；console 0.1.14（2025-10-30） | 实时看每个任务的 poll 次数、busy / idle 时长、被谁阻塞 |
| `task::Builder` + `Handle::dump` | `--cfg tokio_unstable` + `rt`+`tracing`（Builder）/ `taskdump`（dump，Linux only） | 给任务命名；`dump` 打印每个任务的完整 async 栈 |

`#[tracing::instrument]` 给每个 `async fn` 套一个跨 await 存活的 span，于是能看出"这个请求卡在哪一次 await 上"。
`task::Builder` 是**不稳定 API**（文档原话："The public API of this type may break in 1.x releases"），
需要 `tokio_unstable` + `rt` + `tracing` 同时成立，目前唯一选项是 `.name()`：
`tokio::task::Builder::new().name("db-writer").spawn(writer_loop())?;`

命名之后 `tokio-console` 与 `Handle::dump` 的输出才可读。`Handle::dump` 本身很贵（要暂停所有 worker
并重 poll 每个任务），且**若某个 worker 阻塞超过 250 ms 它可能永不返回**，因此必须套 `timeout`。

## The Bridge to the Thread World

async 世界与线程世界之间的桥只有几座，每座都有明确代价：

| 桥 | 方向 | 说明 |
| :-- | :-- | :-- |
| `spawn_blocking` | async → 线程 | 把同步阻塞代码隔离进阻塞池；上限 512 |
| `block_in_place` | async → 线程（就地） | 只在 `multi_thread`；先把本 worker 的任务移交出去 |
| `Handle::block_on` | 线程 → async | **在 async 上下文里调用会 panic**；在 `current_thread` 上驱动不了 IO / timer |
| `Handle::spawn` | 线程 → async | 从 runtime 外往里投任务；任务落全局注入队列 |
| `Handle::enter` / `EnterGuard` | 线程 → async 上下文 | 让"必须在 runtime 上下文里构造"的类型（`Sleep`、`TcpStream`）可用；也让 `Handle::current()` 不 panic |
| `tokio::sync` 的 `oneshot` / `mpsc` / `watch` | 双向 | `.await` 版本不会占住线程 |

一个必须记住的不对称：**`std::thread::spawn` 出来的线程不在 runtime 上下文里**，
在那里调 `Handle::current()` 会 panic，必须先 `let _guard = handle.enter();`。

至于"`std::sync::Mutex` 的 guard 为什么不能跨 `.await`"：**[Concurrency](/docs/CS/Rust/Concurrency.md)
已完整论证（`Send` / `Sync` 与 guard 的线程亲和性），本文只引用不重述**。后果是：
在 `tokio::spawn` 的 future 里持 `std::sync::MutexGuard` 跨 await **编译不过**；
换 `tokio::sync::Mutex` 语法上合法但会把并行段串行化，并引入死锁面。

## Selection and Pitfalls

### Choosing

1. **默认 tokio + `multi_thread`**。理由是生态绑它，不是它最快。
2. **只在 Linux、工作负载以大量 IO 为主、能接受"一个核一个线程、任务不迁移"** 才考虑 thread-per-core（glommio / compio）。
3. **只需要一个 executor**（没有 IO、没有定时器）时，`futures` 的 `LocalPool` / `block_on` 就够。
4. **裸机 / `no_std`**：embassy。**不要引入 async-std**。

### Pitfall Checklist

| # | 坑 | 表现 | 处理 |
| :-- | :-- | :-- | :-- |
| 1 | async 里调同步阻塞 API | 整池吞吐塌方 | `spawn_blocking` 并给它设上限；长远看补异步客户端 |
| 2 | CPU 密集任务放进 async | 不涨吞吐，长尾 | `rayon` / 线程池，并发度按核数 |
| 3 | 任务里没有让出点 | 同 worker 上其它任务饿死 | 插 `yield_now()`，或移出 async 世界 |
| 4 | 依赖任务与线程的绑定 | 迁移后行为异常 | `tokio::task_local!`；或换 thread-per-core |
| 5 | 在 async 上下文 `block_on` / drop runtime；`block_in_place` 用于 `current_thread` | 运行期 panic | runtime 建在 async 之外，收尾用 `shutdown_background()`；单线程 runtime 改用 `spawn_blocking` |
| 6 | `worker_threads` 设得比核数大很多 | 上下文切换变多、缓存局部性变差 | 默认 = 核数；确要调先用 `RuntimeMetrics` 量 |
| 7 | 丢掉 `JoinHandle` 以为取消了任务 | 孤儿任务继续跑，返回值（含 `Err`）被静默丢弃 | 用 `JoinSet` 收口；或显式 `abort()` |
| 8 | 把 `JoinSet` 当"后台跑完"用 | drop 时全部被 abort | 先 `detach_all()` |
| 9 | `select!` 里读一半被取消 | 数据丢失 | 见取消安全一节；不可回滚的动作放在"确定能完成"的那次 poll |
| 10 | `Send` 传染满屏报错 | `future is not Send` | 先读 "used across an await" 那一行；收紧生命周期 / `Arc` / `LocalSet` |
| 11 | 任务 panic 没被发现 | `JoinError` 被丢弃 | 每个 `JoinHandle` 都要 await 并处理 `JoinError` |
| 12 | 以为开了 tokio 就有 io_uring | 实际走 mio 的 readiness 路径 | 要 completion 模型换运行时；开 unstable feature 就得接受它可能在 1.x 内 break |
| 13 | 阻塞池被打满 | `spawn_blocking` 自己排队（上限 512） | 给阻塞调用设并发上限；粒度太细反而更慢 |

## Links

- [Ecosystem](/docs/CS/Rust/Ecosystem.md)
- [Error_Handling](/docs/CS/Rust/Error_Handling.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [tokio crate documentation](https://docs.rs/tokio/latest/tokio/index.html)
- [tokio::runtime::Builder](https://docs.rs/tokio/latest/tokio/runtime/struct.Builder.html)
- [tokio::runtime::Handle](https://docs.rs/tokio/latest/tokio/runtime/struct.Handle.html)
- [tokio::runtime::LocalRuntime](https://docs.rs/tokio/latest/tokio/runtime/struct.LocalRuntime.html)
- [tokio::task::block_in_place](https://docs.rs/tokio/latest/tokio/task/fn.block_in_place.html)
- [tokio::task::JoinSet](https://docs.rs/tokio/latest/tokio/task/struct.JoinSet.html)
- [tokio::task::Builder](https://docs.rs/tokio/latest/tokio/task/struct.Builder.html)
- [smol on crates.io](https://crates.io/crates/smol)
- [async-std on crates.io（含 RUSTSEC-2025-0052 unmaintained 公告）](https://crates.io/crates/async-std)
- [RUSTSEC-2025-0052: async-std has been discontinued](https://rustsec.org/advisories/RUSTSEC-2025-0052.html)
- [glommio on crates.io](https://crates.io/crates/glommio)
- [compio on crates.io](https://crates.io/crates/compio)
- [embassy-executor on crates.io](https://crates.io/crates/embassy-executor)
- [Rust 1.99.1 release notes](https://releases.rs/docs/1.99.1/)
- [The Rust Async Book](https://rust-lang.github.io/async-book/01_getting_started/01_chapter.html)
