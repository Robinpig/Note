## Introduction

原子类型是 Rust 并发里**唯一一处把内存模型直接交到使用者手上**的地方。前面 [Concurrency](/docs/CS/Rust/Concurrency.md) 讲的是 `Send` / `Sync` 如何让"竞争构造不出来"、锁如何选择、channel 如何转移所有权；而 `std::sync::atomic` 这一层恰恰相反——它**允许**你在无锁的前提下构造并发访问，正确性由你自己用内存序论证，编译器只保证"操作是原子的"，不保证"顺序是你想要的"。

三条边界先摆清楚，它们决定了本页的写法：

- **原子不等于同步。** 一次 `Ordering::Relaxed` 的 `fetch_add` 结果一定正确（不丢失更新），但它**不与任何其他内存位置**建立 happens-before 边。计数正确与"发布的数据能被看到"是两件事。
- **Rust 的内存序菜单是 C++20 的子集。** `Ordering` 只有五档，没有 `Consume`；std 文档对每一档都标注了"Corresponds to `memory_order_*` in C++20"。所以它能表达的东西严格少于 C++，但语义与 C++ 对齐，不自建一套。
- **safe Rust 里原子类型不会让你写出数据竞争，但会让你写出逻辑竞态。** 用错内存序不产生 UB（除非你自己上 `unsafe`），它产生的是"编译时一声不响、运行时偶发读到旧值"。这正是它比 `unsafe` 更难排查的地方：`unsafe` 至少给了你一个该审查的标记，错误的 `Relaxed` 没有。

本页**不重述** `Send` / `Sync` 的派生规则、锁与无锁的选型、channel 语义——那些留在 [Concurrency](/docs/CS/Rust/Concurrency.md)；`Arc` / `Weak` 的计数机制本身见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)，本页只讲它的**顺序**为什么必须是这样；无锁内存回收（epoch）与并发容器见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)。

> [!NOTE]
> 本页的事实基线是 **Rust stable 1.99.1（2026-10-15）** 的官方文档；带"本机实测"字样的结论来自 `rustc 1.98.1` / `aarch64-apple-darwin`（Apple Silicon，弱内存序架构），换机器需重测。所有内存序语义均以 `doc.rust-lang.org/std/sync/atomic/` 现行文本为准，不按二手博客的转述写。

## Five Levels, Not Six

`std::sync::atomic::Ordering` **只有五档**：`Relaxed`、`Acquire`、`Release`、`AcqRel`、`SeqCst`。写"六档"通常是把 C++ 的 `memory_order_consume` 算进来了——Rust 从未提供 `Consume`（社区共识是它无法被安全实现，且没有编译器真正跟踪依赖链）。

该枚举是 `#[non_exhaustive]`：不带通配地穷举五档会报 `error[E0004]: non-exhaustive patterns: \`_\` not covered`（本机实测），所以 `match` 它必须留兜底分支。这不是形式主义——枚举保留未来加档的权利，你的代码必须能承受。

### What Each Ordering Buys You

"买到什么 / 没买到什么"是理解内存序唯一有用的问法。下表左两列是 std 文档的原文语义，右两列是工程含义：

| Ordering | std 文档语义 | 买到了什么 | **没买到**什么 |
| :--- | :--- | :--- | :--- |
| `Relaxed` | No ordering constraints, only atomic operations | 原子性 + 该变量自身的**修改顺序全序**（modification order）；计数器绝不丢更新 | 跨变量的 happens-before；读侧看到任何别的写；与相邻普通读写的顺序约束 |
| `Acquire` | 用于 load；若读到的值由某个 `Release`（或更强）写写入，则其后的所有操作被排在那个 store 之后 | 与配对的 `Release` 建立单向同步：**读侧能看到写侧之前的所有写** | 单独使用不构成"发布"；不影响别的线程什么时候看到**这次** load 之前的写 |
| `Release` | 用于 store；其前的所有操作被排在"任何以 `Acquire`（或更强）读到该值的 load"之前 | 把"我此前做的一切"发布出去 | 自己不等待任何东西；不保证读侧**真的**去读（需要配对的 `Acquire`） |
| `AcqRel` | 同时具备两者：load 侧按 `Acquire`，store 侧按 `Release` | 读改写（RMW）一次拿到双向语义 | 全局全序；`compare_exchange` 失败时实际只表现为 `Acquire` |
| `SeqCst` | 在 `Acquire`/`Release`/`AcqRel` 之上，额外保证所有线程看到**同一个** SeqCst 操作顺序 | 上述全部 + 单一全序（single total order），可用来推理多变量协议 | 便宜——它是唯一"不确定时总是对的"选择，代价见性能测试一节 |

三个最容易读错的点：

1. **`Relaxed` 不是"无所谓"**，它是"只对这一个变量保证"。两个 `Relaxed` 操作之间永远只建立**同一变量的修改顺序**，不建立跨变量的 happens-before。
2. **`Acquire` 和 `Release` 必须成对**才有意义。单边写 `Acquire` 而不存在任何 `Release` 写，什么都不会发生。
3. **`SeqCst` 是默认值也是安全值**。所有不确定该用哪一档的场合都用 `SeqCst`，先让它正确；只有在 profiling 证明这一行是瓶颈、且你能论证为何不需要跨变量同步时，才降档。

### Rust Ordering vs C++ std::memory_order

这是本页的核心对照。Rust 的五档与 C++20 的六个常量一一对应，`Consume` 是唯一的差集：

| Rust `Ordering` | C++20 `std::memory_order` | 可用于 | 语义是否等价 |
| :--- | :--- | :--- | :--- |
| `Relaxed` | `memory_order_relaxed` | load / store / RMW | ✅ 等价 |
| `Acquire` | `memory_order_acquire` | 仅能 load 的操作 | ✅ 等价 |
| `Release` | `memory_order_release` | 仅能 store 的操作 | ✅ 等价 |
| `AcqRel` | `memory_order_acq_rel` | 仅读改写（RMW） | ✅ 等价 |
| `SeqCst` | `memory_order_seq_cst` | load / store / RMW | ✅ 等价 |
| ——（无） | `memory_order_consume` | 仅 load | ❌ Rust 不提供 |

关于 `consume` 的补充（这是"C++ 更丰富"这个印象的真实含量）：它从 **C++17 起被标准"暂时不鼓励使用"，到 C++26 正式弃用**，并且 C++26 规定 release-consume 排序与 release-acquire 排序**效果相同**；在此之前也没有任何已知生产编译器真正跟踪依赖链，实现一律把它提升（lift）为 acquire。**也就是说这一档在实践中从来没有兑现过它的理论收益**——Rust 不提供它不是能力缺失，而是拒绝收录一个已知无法实现的档位。

因此"Rust 原子序弱于 C++"这句话只有在**可表达性**上成立；在**可实现性**上两者等价。

### Which Ordering Is Legal on Which Operation

内存序不是随便填的，std 对每一档限定了它能用在什么操作上，越界直接 panic（这是运行时 panic，不是编译错误）：

| 操作 | 允许的 Ordering | 违反时的后果 |
| :--- | :--- | :--- |
| `load(order)` | `Relaxed` `Acquire` `SeqCst` | `panic`：*Panics if `order` is `Release` or `AcqRel`* |
| `store(order)` | `Relaxed` `Release` `SeqCst` | `panic`：*Panics if `order` is `Acquire` or `AcqRel`* |
| RMW（`fetch_add` / `swap` / `fetch_max`…） | 全部五档 | 无 panic，但见下方的降级提示 |
| `compare_exchange(success, failure)` | success 任意；**failure 只能是 `SeqCst` / `Acquire` / `Relaxed`** | 文档明示限制；`Release`/`AcqRel` 作为 failure 不合法 |
| `fence(order)` | `Acquire` `Release` `AcqRel` `SeqCst` | `panic`：*Panics if `order` is `Relaxed`* |

RMW 上的**降级**是这里最容易踩的一处，std 每一档都写了 Notice：把 `Release` 用在"同时 load 又 store"的操作上，**load 部分退化成 `Relaxed`**；把 `Acquire` 用在 RMW 上，**store 部分退化成 `Relaxed`**。所以 `fetch_add(1, Release)` 不是"发布语义的加法"，它是一个 `Relaxed` 读 + `Release` 写的混合体。想要完整的双向，就写 `AcqRel`。

例外只有一条：`compare_and_swap` / `compare_exchange` 用 `AcqRel` 时，如果比较失败根本没发生写，那这次操作实际只有 `Acquire` 语义——文档同样写明"`AcqRel` will never perform `Relaxed` accesses"，即它不会比 `Acquire` 更弱，只是可能没用满。

## Publish-Subscribe Needs Acquire and Release

发布-订阅（一个线程写数据后置标志，另一个线程见标志后读数据）是唯一必须自己论证内存序的常见模式：

```rust
static DATA: AtomicUsize = AtomicUsize::new(0);
static FLAG: AtomicBool = AtomicBool::new(false);

// 错误：两处都 Relaxed，FLAG 与 DATA 之间没有任何同步边
fn producer_relaxed() { DATA.store(42, Ordering::Relaxed); FLAG.store(true, Ordering::Relaxed); }
fn consumer_relaxed() {
    while !FLAG.load(Ordering::Relaxed) { std::hint::spin_loop(); }
    let x = DATA.load(Ordering::Relaxed);   // 可能读到 0，也可能被编译器整个提出循环
}

// 正确：FLAG 上用 Release/Acquire 建立同步边；DATA 本身 Relaxed 就够
fn producer() { DATA.store(42, Ordering::Relaxed); FLAG.store(true, Ordering::Release); }
fn consumer() {
    while !FLAG.load(Ordering::Acquire) { std::hint::spin_loop(); }
    let x = DATA.load(Ordering::Relaxed);   // 同步已由 flag 建立，这里加序是白付钱
}
```

第二段里 `DATA.load` 用 `Relaxed` 是**正确的**，这一点常被误解为偷懒：`Acquire` load 的语义是"**其后**的所有操作排在那个 `Release` store 之后"，它覆盖的是整个后续区间，不需要每个变量自己再带一次序。反过来说，把 `DATA` 也升级成 `Acquire` 不会更正确，只会多付一次屏障。

> [!WARNING]
> 第一段代码能编译、能通过 review、能在 x86 上永远正常工作，并且**在 aarch64 上也可以一直"看起来正常"**。这正是内存序 bug 的形态：它不是必现错误，而是一个在弱内存序机器上偶发、且与编译器优化级别耦合的窗口。我没有在本机给出"Relaxed 版实际读到 0"的复现——单次采样触发不了这个窗口，把"没跑出来"写成"没问题"和把"理论上可以"写成"实测复现"是同一种错误。

### The Failure Ordering Is Also Part of the Contract

`compare_exchange` 有**两个**顺序参数，第二个（failure）描述的不是"失败时我要多强的同步"，而是"这次失败的**读**是什么序"：

```rust
// 典型：成功要发布（AcqRel 或 Release），失败只需要重新读一次值（Acquire 或 Relaxed）
let mut cur = self.state.load(Ordering::Relaxed);
loop {
    let next = compute(cur);
    match self.state.compare_exchange_weak(cur, next, Ordering::AcqRel, Ordering::Acquire) {
        Ok(_) => break,              // 成功：写入已被发布，且能看到之前的状态
        Err(observed) => cur = observed,   // 失败：拿到新的当前值继续试
    }
}
```

failure 只能是 `SeqCst` / `Acquire` / `Relaxed` 三者之一。多数 CAS 循环里失败路径只是"拿新值重试"，用 `Relaxed` 足矣；只有当失败路径本身也要读被保护的数据时，才需要 `Acquire`。

## Fences

### fence vs Operation-Embedded Ordering

`fence(order)` 是**不带数据**的屏障，它与"操作自带的顺序"能互相配对，std 文档明确列出三种同步方式（外加常规的操作-操作同步，共四种）：

| 模式 | 线程 1 | 线程 2 | 建立的边 |
| :--- | :--- | :--- | :--- |
| atomic → atomic（常规） | `m.store(3, Release)` | `m.load(Acquire) == 3` | X → Y |
| **atomic → fence** | `m.store(3, Release)` | `m.load(Relaxed) == 3` 后接 `fence(Acquire)` | X → B |
| **fence → atomic** | `fence(Release)` 后接 `m.store(3, Relaxed)` | `m.load(Acquire) == 3` | A → Y |
| **fence → fence** | `fence(Release)` 后接 `m.store(3, Relaxed)` | `m.load(Relaxed) == 3` 后接 `fence(Acquire)` | A → B |

关键差异有三条：

- **fence 不绑定变量。** 操作自带的顺序只对"那个原子变量"生效；`fence` 是线程内的一条横线，它与**任何**原子操作都能配对。这是它能做"一次性把多个变量的发布收口"的原因。
- **`fence` 是"事后补序"。** 上面的 atomic→fence 模式允许你先用 `Relaxed` 读、确认值之后再补一次 `Acquire`，从而获得与 `Acquire` load 等价的同步，但把屏障挪到了分支内部——在"绝大多数迭代都不满足条件"的自旋里这是净收益。
- **`fence` 不能救非原子访问。** std 的 "Mandatory Atomic" 一节说得很直白：*Fences cannot be used to establish synchronization between non-atomic accesses in different threads*。屏障建立的是 happens-before，而 happens-before 的两端必须至少有一端是原子操作或 fence；两个普通读写之间放一个 fence 什么也同步不了。

`fence` 接受 `Acquire` / `Release` / `AcqRel` / `SeqCst`，传 `Relaxed` 会 panic。

### compiler_fence Is Not a Substitute

`compiler_fence` 的文档定性是 *An atomic fence for synchronization within a single thread*——它只约束编译器重排，**不生成硬件内存屏障**，因此**不能**用来做线程间同步。它的正当用途是信号处理器、以及和 MMIO 相关的单线程顺序场景。把它当成"便宜版的 `fence`"是典型的错误，而且这类错误在 x86 上永远不会暴露。

### Read-Only Memory Can Fault

一条几乎没人提但真的会咬人的事实：std 明确警告，**在只读内存上做 `compare_exchange`，即使注定失败（概念上是只读操作），仍然可能段错误**——因为底层可能用 compare-exchange 指令实现 `load`，而写只读页会 fault。所以"把 `static` 放进只读段然后用原子读它"这条路是走不通的；反过来，需要在只读内存上建立 acquire 语义时，正确写法是 `Relaxed` load + `fence(Acquire)`（正是上一节的 atomic→fence 模式）。

## Read-Modify-Write and the CAS Loop

### compare_exchange_weak and Spurious Failure

两个变体的差别只有一句：*Unlike `compare_exchange`, this function is allowed to spuriously fail even when the comparison succeeds, which can result in more efficient code on some platforms*。

"伪失败"指的是**值明明相等也可能返回 `Err`**。原因不是随机器（虽然常被这么比喻），而是弱 CAS 允许映射到那些在争用、中断、或 LL/SC 序列被打断时会失败的指令上，从而省掉编译器自己插入的重试循环。因此规则只有一条：

> **`compare_exchange_weak` 必须写在循环里。** 它在循环里比 `compare_exchange` 更快（编译器不必再包一层重试）；它不在循环里就是 bug。

```rust
// 正确的弱 CAS 形态：失败值就是新的当前值，直接继续
let mut cur = shared.load(Ordering::Relaxed);
loop {
    match shared.compare_exchange_weak(cur, cur + 1, Ordering::AcqRel, Ordering::Relaxed) {
        Ok(prev) => break prev,
        Err(observed) => { cur = observed; std::hint::spin_loop(); }
    }
}
```

### try_update and update

"读出来 → 算新值 → 条件性写回"这个形状 std 给了现成的名字，但**命名在 1.99.0 换过**，这是本页最需要记住的 API 事实之一：

| 方法 | 状态 | 语义 |
| :--- | :--- | :--- |
| `fetch_update(set_order, fetch_order, f)` | **自 1.99.0 起 deprecated**，提示 *renamed to `try_update` for consistency*，建议替换为 `try_update` | 就是 `try_update` 的别名 |
| `try_update(set_order, fetch_order, f)` | 1.95.0 稳定 | `f` 返回 `Option<T>`；`Some` 则写回并继续重试，`None` 则放弃，返回 `Result<T, T>` |
| `update(set_order, fetch_order, f)` | 1.95.0 稳定 | `f` 返回 `T`（总是写回），返回旧值 |

三者的实现都是 CAS 循环（std 源码里就是 `compare_exchange_weak` 套 `while let`），std 文档专门加了一节 "Considerations" 提醒：*This method is not magic; it is not provided by the hardware, and does not act like a critical section or mutex*——它不是原子版的"锁住算一下"，期间别的线程可以任意改动这个值，你的闭包可能被调用多次（只要它一直返回 `Some`）。

### fetch_max and fetch_min

`fetch_max` / `fetch_min`（1.45.0 稳定）是**真正由硬件或 CAS 循环提供**的复合操作，文档注明 *All ordering modes are possible*（不像 load/store 那样受限）。它们的价值不是"少写几行"，而是把一个"读-比较-写"的序列变成**一次不可分割的操作**，从而消除这一小段上的竞态。同样的思路适用于 `fetch_add` / `fetch_sub` / `fetch_or` / `fetch_and` / `fetch_xor`。

但要看清边界：`fetch_max` 只保证"这一次取最大值"是原子的，它**不保证**你随后基于返回值做的判断仍然成立（返回旧值的那一刻，值可能又变了）。这就是 std 反复提醒的 **ABA 问题**——尤其当这个原子整数被当作**索引**使用时：值相同不代表它指向的还是同一个对象。

## A Micro-Benchmark With Its Caveats

本机 `rustc 1.98.1 -O`、`aarch64-apple-darwin`、每场景连跑多轮取区间，工具只有 `std::time::Instant` + `std::hint::black_box`——**没有 criterion 的预热与统计置信，也没有排除频率漂移**，所以下面的数字只用于判断"量级差异在不在"，不要当性能结论。

- **单线程、无争用的 store：`Relaxed` 与 `SeqCst` 差异淹没在噪声里**（2M 次 store，两者各轮耗时区间互相覆盖）。所以在 aarch64 上"把 SeqCst 改成 Relaxed 提速"这个常见建议，对无争用的单变量写基本是空操作。
- **读改写指令本身才是成本**：无争用 2M 次下 `swap(SeqCst)` ≈ 11–14 ms、`compare_exchange` ≈ 30–38 ms，而 `store` ≈ 0.7–1.2 ms。差 1–2 个数量级的不是内存序，是"独占缓存行"。
- **争用下才看得到序的差别**：4 线程争同一行、各 500k 次 `fetch_add`，3 轮结果 `Relaxed` ≈ 39–42 ms，`AcqRel` ≈ 74–91 ms，`SeqCst` ≈ 74–80 ms。即 **Relaxed 约为后两者的 1/2，而 `AcqRel` 与 `SeqCst` 测不出稳定差异**。

判据由此变得很简单：`Relaxed` 的收益只在**高争用的读改写**上才可观，且必须先证明你不需要跨变量的同步关系；否则选 `AcqRel` 基本是免费的。换句话说，**内存序调优的入口是"争用"，不是"少写几个字母"**。

## Which Atomic Types Exist Where

### The Stable Set

稳定的类型族是 `AtomicBool`、`AtomicPtr`，以及 8 / 16 / 32 / 64 / `size` 各宽度的有符号与无符号整数（`AtomicI8`…`AtomicIsize`、`AtomicU8`…`AtomicUsize`）。`AtomicI128` / `AtomicU128` **仍不稳定**：实测报 `error[E0658]: use of unstable library feature \`integer_atomics\``，其跟踪 issue 是 **rust-lang/rust#99069**（Unstable Book 的 `integer_atomics` 条目）。

一个容易踩的分裂，实测：`cfg!(target_has_atomic = "128")` 在本机是 **`true`**（与 `= "64"`、`= "ptr"` 一样为真），但类型仍不存在。**硬件与 ABI 支持 128 位原子操作 ≠ stable std 暴露了它**。用 `#[cfg(target_has_atomic = "…")]` 做可选路径是对的，但别据此假定 `AtomicU128` 可写。

### Portability Is Not Uniform

std 的 Portability 一节给了明确清单，值得逐条记住：

| 平台 | 限制 |
| :--- | :--- |
| PowerPC / MIPS（32 位指针） | **没有** `AtomicU64` / `AtomicI64` |
| Legacy ARM（ARMv4T / ARMv5TE） | 裸机目标**整个 `atomic` 模块被禁用**；Linux 目标靠内核辅助（有性能损失）；ARMv6K 起硬件才支持 CAS |
| ARMv6-M / ARMv8-M baseline（`thumbv6m-*`、`thumbv8m.base-*`） | **只有 load / store**，没有 CAS——`swap` / `fetch_add` / `compare_exchange` 都不可用 |
| ARMv7-M / ARMv8-M mainline | 完整 CAS 支持 |
| 其它 | `AtomicUsize` / `AtomicIsize` 通常最可移植，但也不是所有平台都有；std 要求目标必须有 `AtomicBool` 与指针宽度原子 |

另一个常被忽略的承诺：**所有可用的原子类型都保证 lock-free（内部不会拿全局锁），但不保证 wait-free**——`fetch_or` 这类操作可能由 CAS 循环实现。此外某些平台会用更宽的指令模拟较窄的原子类型（例如用 4 字节指令实现 `AtomicI8`），文档说明这不影响正确性。

### When you Need More: portable-atomic

`portable-atomic` 的存在理由就是上面这张表：它提供 `AtomicI128` / `AtomicU128`、`AtomicF32` / `AtomicF64`，给 std 完全没有原子的目标（RISC-V 无 A 扩展、MSP430、AVR）补 load/store，给 `thumbv6m` 这类补 CAS，并把 `fetch_max` / `fetch_min` / `try_update` 这些"需要较新编译器"的 API 下放到很老的 Rust 上。128 位原子在 x86_64 / aarch64 / riscv64 走原生指令（Rust 1.59+），其余平台回退到基于锁的 fallback。

选择判据很简单：**能用 std 就用 std**；只有当你要么需要 128 位 / 浮点原子，要么目标是 std 原子不完整的嵌入式平台时，才引入它。它是一个真实依赖，不是零成本抽象。

## Reference Counts Are an Ordering Problem too

`Arc` 是全库最常被"白嫖"内存序的地方。计数机制本身见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)，这里只讲并发侧**为什么必须是这个顺序**。

### Why Arc::drop Needs Release and Acquire

std（以及 Rustonomicon 复述的那段注释）的实现形态是：

```rust
fn drop(&mut self) {
    let inner = unsafe { self.ptr.as_ref() };
    // 递减用 Release：把"我此前对数据的所有使用"发布出去
    if inner.rc.fetch_sub(1, Ordering::Release) != 1 { return; }
    // 只有最后一个持有者才走到这里：再补一条 Acquire，把别人的写同步进来
    atomic::fence(Ordering::Acquire);
    unsafe { drop_slow(); }
}
```

两条顺序各司其职，缺一不可：

- **`Release` 递减**：保证"本线程对数据的所有访问"排在计数递减之前。别的线程一旦看到计数变化，就能看到这些访问。
- **`Acquire` fence**：保证"别人的访问"排在销毁之前。这一条最容易被忽略，理由也最实际——`Arc` 的内容通常不可变，但**它可以是 `Arc<Mutex<T>>`**：`Mutex` 在被析构时并**不会**被加锁，因此无法依赖它自己的同步逻辑把线程 A 的写入交给在线程 B 上运行的析构函数。Boost 文档的那句话正是这个意思：*"It is important to enforce any possible access to the object in one thread to happen before deleting the object in a different thread."*

为什么不用一步 `AcqRel` 的 `fetch_sub`：因为**绝大多数** `drop` 都不是最后一个持有者，而 `AcqRel` 会让每一次递减都付 acquire 的代价，只为那唯一一次需要的场合。"Release 递减 + 条件性 Acquire fence"把一个稀有路径的成本挪出了热路径。

### Weak::upgrade Is a CAS Loop, Not a Check

`Weak::upgrade` 不能写成"先读强计数非零、再抬升"——中间有任何一次 `drop` 都会让它复活一个正在析构的对象。std 的实现是把"读 + 判零 + 抬升"压进一次 CAS 循环：

```rust
loop {
    let n = inner.strong.load(Relaxed);   // 0 是永久状态，所以 Relaxed 就够
    if n == 0 { return None; }            // 已死，永远不会复活
    if n > MAX_REFCOUNT { abort(); }
    // 用 CAS 而不是 fetch_add：计数一旦到 0 就绝不允许再变正
    let old = inner.strong.compare_and_swap(n, n + 1, Relaxed);
    if old == n { return Some(/* 新的 Arc */); }
}
```

两点值得单独记住：**`Relaxed` 读在这里是合法的**（因为 0 是永久状态，读到"旧的非零值"会被随后的 CAS 证伪）；以及 **CAS 而非 `fetch_add` 是必需的**，否则会把 0 抬成正数。

另外一条实测结论：`Weak::upgrade` **不是选举**。4 个线程同时 `upgrade` 同一个仍然活着的 `Weak`，返回 `Some` 的次数是 **4**。用"我 upgrade 成功了"来判定"我是唯一 owner"是错的，需要唯一性得再叠一层 CAS 或锁。最后一个 `Arc` 掉完后 `upgrade` 返回 `None`（实测），而不是 panic——`Weak` 的并发语义是"可能失败的所有权尝试"。

### AtomicPtr

`AtomicPtr<T>` 是裸指针上的原子，也是所有"手写无锁结构"的起点。它的顺序问题与引用计数同构：

- **发布**一个指针用 `Release` store，**获取**用 `Acquire` load；指针指向的数据的可见性由这一对保证，数据本身的读写仍可以是普通访问。
- 它是 `*mut T`，因此**没有生命周期**，编译器不帮你证明指向的东西还活着。用 `AtomicPtr` 就意味着你自己承担回收（通常叠 epoch / hazard pointer，见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)）。
- `AtomicPtr` 的 `fetch_*` 系列（指针算术）长期不稳定，`portable-atomic` 提供等价物。

## False Sharing and Cache Lines

内存序之外，无锁代码第二个真实的性能来源是**缓存行争用**，而它与内存序完全正交：`Relaxed` 的 `fetch_add` 在高争用下仍然慢，因为慢的是**缓存行在核间来回失效**，不是屏障指令。

std 的文档给出了这一现象的官方说法：*Updating an atomic value invalidates the whole cache line it belongs to, which makes the next access to the same cache line slower for other CPU cores*。两个逻辑上无关、但物理上落在同一缓存行的原子计数器，会互相拖慢——这就是**伪共享（false sharing）**。

两种处理手段：

```rust
// 1) 语言自带：手工对齐到 128 字节（保守值，覆盖 Intel 的空间预取会成对拉 64B 行的行为）
#[repr(align(128))]
struct PaddedCounter(AtomicU64);

// 2) 生态做法：crossbeam-utils 的 CachePadded，自动按架构选 N
use crossbeam_utils::CachePadded;
struct Queue<T> {
    head: CachePadded<AtomicUsize>,   // 生产者侧
    tail: CachePadded<AtomicUsize>,   // 消费者侧：不再互相失效
    buffer: *mut T,
}
```

`crossbeam_utils::CachePadded` 的取值（按 docs.rs 现行文本）：x86-64 / aarch64 / powerpc64 上 **N = 128**；arm / mips / mips64 / sparc / hexagon 上 **N = 32**；m68k 上 **N = 16**；s390x 上 **N = 256**；其余 **N = 64**。文档同时声明 *N is just a reasonable guess and is not guaranteed to match the actual cache line length*——x86-64 取 128 是因为 Intel 的空间预取器会成对拉取 64 字节行，所以悲观地按 128 算。自 **crossbeam-utils 0.8.22** 起它是 `#[repr(C)]`，并保证 `CachePadded<T>` 的地址与内部 `T` 相同（因此可以直接解引用，不需要额外偏移）。

> [!NOTE]
> 对齐只在**真的存在多核写争用**时才划算。给一个只被单线程碰的计数器加 128 字节填充，是在用内存换一个不存在的收益；而给 `head` / `tail` 这类"两边各自高频写"的字段做填充，收益通常是数倍。

## A Worked Example: Spinlock, and Why Seqlock Is Harder

### A Spinlock

std 的 `fence` 文档自带一个完整的自旋锁，它的价值在于**示范了 fence 如何替代操作自带顺序**：

```rust
use std::sync::atomic::{AtomicBool, Ordering, fence};

pub struct Spinlock { flag: AtomicBool }

impl Spinlock {
    pub fn new() -> Spinlock { Spinlock { flag: AtomicBool::new(false) } }

    pub fn lock(&self) {
        // 抢锁：反复弱 CAS，失败就自旋；这里用 Relaxed 即可，同步由下面的 fence 负责
        while self.flag
            .compare_exchange_weak(false, true, Ordering::Relaxed, Ordering::Relaxed)
            .is_err()
        { std::hint::spin_loop(); }        // 提示 CPU 正在忙等，别乱推测执行
        // 与 unlock 里的 Release store 配对：临界区之前的写必须在此之后可见
        fence(Ordering::Acquire);
    }

    pub fn unlock(&self) {
        self.flag.store(false, Ordering::Release);   // 把临界区内的写发布出去
    }
}
```

注意 `lock` 的 CAS 用的是 `Relaxed`——这一步不需要同步，它只需要"独占地把 false 换成 true"；同步语义由紧随其后的一次 `fence(Acquire)` 提供，而这次 fence **只在抢到锁时执行一次**，不在每次自旋失败时重复。这正是前面"事后的 fence 可以放进分支"那条结论的用处。

### Why a True Seqlock Is Not Available in Safe Rust

seqlock 的经典形态是：写者递增序号 → 改数据 → 递增序号；读者读序号 → 读数据 → 再读序号，若两次序号相同且为偶数则数据有效。**在 C 里这是可行的，在 Rust 里它不是"unsafe"，它就是 UB**：读者与写者并发访问同一块数据是**数据竞争**，而 Rust 的竞争即 UB，编译器有权假设它不会发生，于是可以缓存、重排、甚至把读提到循环外。用 `UnsafeCell` 绕过借用检查并不能改变这一点——改变内存可见性的是内存序，不是 `UnsafeCell`。

所以在 Rust 里应当用**结构上无竞争的等价物**替代，而不是复刻 seqlock 的读侧。最常用的是双缓冲发布（写者写非活跃槽、用 `Release` 翻转索引；读者 `Acquire` 读索引后读对应槽）：

```rust
static INDEX: AtomicU8 = AtomicU8::new(0);
static SLOTS: [AtomicU64; 2] = [AtomicU64::new(0), AtomicU64::new(0)];

fn publish(v: u64) {
    let i = INDEX.load(Ordering::Relaxed) as usize;
    SLOTS[1 - i].store(v, Ordering::Relaxed);   // 先写非活跃槽，读者看不到
    INDEX.store((1 - i) as u8, Ordering::Release); // 一次原子翻转完成发布
}
fn read() -> u64 {
    let i = INDEX.load(Ordering::Acquire) as usize;
    SLOTS[i].load(Ordering::Relaxed)            // 同步已由 INDEX 建立
}
```

这个形状保留了 seqlock 的全部优点（读侧无锁、无写阻塞、不会读到撕裂值），代价是**载荷必须是能一次原子写入的字**（否则要把载荷放进 `Arc` 并做 Arc swap，见 [Concurrency](/docs/CS/Rust/Concurrency.md) 里"发布新值而不是用 RwLock"那条判据），并且它放弃了 seqlock 的"读侧可以无限重试直到读到一致快照"这一条——读侧读到的是**某一次**发布的完整值，而不是"读到一半就重来"。

换句话说：**Rust 里"用无锁数据结构"通常意味着把不变式编码进结构（槽、版本号、索引），而不是编码进读侧的重试协议。**

## loom for Permutation Checking

无锁结构的正确性靠人脑推理内存序几乎必错，本库的默认工具是 **`loom`（`0.7.2`，crates.io 最后更新 **2024-04-23**，MIT，MSRV 1.65）**。

它不是运行时监测器，而是**模型检查器**：把 `loom::sync::atomic::*`、`loom::sync::Mutex`、`loom::thread` 换掉 std 的对应物之后，`loom::model` 会**反复运行同一个闭包**，穷举（在状态约简前提下）线程交错与内存序的可能取值，把"存在一条弱序路径会让断言失败"变成一次真实的断言失败。

```rust
use loom::sync::Arc;
use loom::sync::atomic::AtomicUsize;
use loom::sync::atomic::Ordering::{Acquire, Release, Relaxed};
use loom::thread;

#[test]
#[should_panic]
fn buggy_concurrent_inc() {
    loom::model(|| {
        let num = Arc::new(AtomicUsize::new(0));
        let ths: Vec<_> = (0..2).map(|_| {
            let num = num.clone();
            thread::spawn(move || {
                let curr = num.load(Acquire);
                num.store(curr + 1, Release);   // 读改写不是原子的：会丢更新
            })
        }).collect();
        for th in ths { th.join().unwrap(); }
        assert_eq!(2, num.load(Relaxed));
    });
}
```

运行方式是把 loom 放在 `--cfg loom` 的 target 依赖里，然后 `RUSTFLAGS="--cfg loom" cargo test --release`。

### What loom Can and Cannot Prove

这一点必须写清楚，否则会把"loom 跑过"误当成"已证明正确"。官方 README 的 "Unsupported features" 一节只列了两条，但两条都是实质性的：

| | loom 的能力 |
| :--- | :--- |
| ✅ 能 | 在 **C11 内存模型**下穷举线程交错与操作顺序的可能组合；用状态约简（state reduction）避免组合爆炸；把弱序路径变成断言失败；支持 `fence(SeqCst)` |
| ❌ 不能 | **`SeqCst` 的原子操作被当作 `AcqRel` 处理** → 会漏掉某些真实执行，产生**假警报**（不完整，not complete），见 loom issue #180 |
| ❌ 不能 | **不探索 load buffering** 行为 → 存在某些 C11 允许的执行 loom 搜不到，**loom 说没 bug 不代表没 bug**（不健全，not sound） |
| ❌ 不能 | 验证 ABA、饥饿、公平性、性能；也不验证与 `unsafe` 内存回收相关的安全性 |
| ❌ 不能 | 覆盖真实编译器的优化（它模拟的是模型，不是 LLVM 的代码生成） |

即：**loom 通过 = 在这些交错下没找到反例；loom 失败 = 一定有 bug。** 它是一个很好的"证伪"工具，不是一个"证明"工具。另外它自 2024 年以来没有新版本，**不要把它描述成活跃开发中**；它仍是这类工具的参考实现，但状态是"成熟且基本不动"。

## Common Mistakes

踩坑清单，按"是否会静默出错"排序：

1. **把 `Relaxed` 当成"无所谓"。** 它是"只对这一个变量保证"。任何跨变量的可见性需求都不能靠它；一旦某个 `Relaxed` 的读要与别处的写配对，它就必须是 `Acquire`。
2. **对同一个原子混用不同顺序。** 同步关系是**读与写的配对**，不是变量的属性。一个变量上写用 `Release`、读用 `Relaxed`，等于没发布——两者必须成对。更隐蔽的形态是：同一个变量的读在代码里散落三处，其中两处写了 `Acquire`，第三处为了"优化"写成 `Relaxed`。
3. **把内存序当成锁的替代品。** 原子保证的是"这一次操作不可分割"，不保证"这一组不变式同时成立"。跨多个字段的不变式、`Arc<Mutex<T>>` 就能解决的事、以及任何需要"读-判断-写"三步的协议，用原子手写几乎必错。Rust 里原子最正当的用途是**计数器、标志、状态机的一位、以及指针的发布**。
4. **在非循环里用 `compare_exchange_weak`。** 它会伪失败；不在循环里就是偶发 bug（见前文）。
5. **给 RMW 传 `Acquire` 或 `Release` 以为拿到了双向语义。** 实际上另一侧退化成 `Relaxed`。要双向就写 `AcqRel`。
6. **把 `fence(SeqCst)` 当成"更强的全能屏障"，或把 `compiler_fence` 当成 `fence`。** 前者只是"同时具备 acquire/release 且参与全局全序"，后者根本不做线程间同步。
7. **用 `cfg!(target_has_atomic = "128")` 推断 `AtomicU128` 可用。** 硬件支持与 std 暴露是两件事（实测前者为 true、后者仍 E0658）。
8. **在自旋循环里忘记 `std::hint::spin_loop()`。** 它不改变正确性，但会显著影响忙等时的功耗与对同核超线程的干扰（`atomic::spin_loop_hint` 已废弃，现在用 `hint::spin_loop`）。
9. **给所有原子都加缓存行填充。** 填充只在多核写争用下才有收益，盲目加会把数据结构吹大并破坏局部性。
10. **把"loom 跑过"当证明。** 它既不完整也不健全（见上一节），尤其是 `SeqCst` 与 load buffering 两条。

## Links

- [Async](/docs/CS/Rust/Async.md)
- [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)
- [Performance](/docs/CS/Rust/Performance.md)
- [Ecosystem](/docs/CS/Rust/Ecosystem.md)
- [C++ Concurrency](/docs/CS/C++/Concurrency.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [std::sync::atomic::Ordering](https://doc.rust-lang.org/std/sync/atomic/enum.Ordering.html)
- [std::sync::atomic — Portability and memory model](https://doc.rust-lang.org/std/sync/atomic/index.html)
- [std::sync::atomic::fence](https://doc.rust-lang.org/std/sync/atomic/fn.fence.html)
- [std::sync::atomic::compiler_fence](https://doc.rust-lang.org/std/sync/atomic/fn.compiler_fence.html)
- [std::sync::atomic::AtomicUsize](https://doc.rust-lang.org/std/sync/atomic/type.AtomicUsize.html)
- [The Rustonomicon — Atomics](https://doc.rust-lang.org/nomicon/atomics.html)
- [The Rustonomicon — Arc: Dropping](https://doc.rust-lang.org/nomicon/arc-mutex/arc-drop.html)
- [The Unstable Book — integer_atomics](https://doc.rust-lang.org/unstable-book/library-features/integer-atomics.html)
- [cppreference — std::memory_order](https://en.cppreference.com/w/cpp/atomic/memory_order)
- [loom 0.7.2 documentation](https://docs.rs/loom/0.7.2/loom/)
- [tokio-rs/loom — README](https://github.com/tokio-rs/loom)
- [crossbeam_utils::CachePadded](https://docs.rs/crossbeam-utils/latest/struct.CachePadded.html)
- [portable-atomic](https://crates.io/crates/portable-atomic)
- [Rust 1.99.1 release notes](https://releases.rs/docs/1.99.1/)
