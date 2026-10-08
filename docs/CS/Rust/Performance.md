## Introduction

「零成本抽象（zero-cost abstraction）」是 Rust 最容易被误读的一句话。它**不是**说抽象没有代价，而是说：抽象不向生成的机器码里塞入额外的运行时工作——迭代器链、闭包、泛型在优化之后和手写循环编译出的东西一样；代价被挪到了编译期，表现为编译时间与代码体积。

所以谈 Rust 性能必须分三笔账：**运行时**（抽象是否真的消失了）、**编译期**（单态化带来的时间与体积膨胀，见 [compile.md](/docs/CS/Rust/compile.md)）、以及**测量本身**（不测量就优化，在 Rust 里比在别的语言里更容易得出错误结论，因为 debug 与 release 的差距可以是一个数量级）。

本篇沿这条线组织：先论证「零成本」的机制与真实边界，再讲怎么测（这一节包含一个版本事实：stable 上的 `#[bench]` 已经没了），然后是分配与拷贝、内存布局的性能后果、锁与原子、编译 profile 调优、SIMD 在 stable 上的现状，最后给一份优化清单与跨语言对照。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**；本机实测工具链 `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1`，host `aarch64-apple-darwin`。所有标注「实测」的数字都来自本机真实运行（`rustc -O` 或 `cargo build --release`），**不同机器数值必然不同，可比的是相对关系**；凡取自 release notes / 文档的一律写明出处，不谎称实测。criterion 版本为 0.8.2（`rust_version` 实测 1.86）。

## What Zero-Cost Abstraction Actually Means

先做一个可以直接复现的实验：同一个函数写成迭代器链和手写下标循环两种形式，看 `-O`（等价于 release 的 `opt-level = 3`）生成的汇编。

```rust
#[no_mangle] pub fn sum_iter(v: &[i64]) -> i64 {
    v.iter().filter(|x| **x > 0).map(|x| x * 2).sum()
}
#[no_mangle] pub fn sum_loop(v: &[i64]) -> i64 {
    let mut s = 0i64;
    for i in 0..v.len() { let x = v[i]; if x > 0 { s += x * 2; } }
    s
}
```

```bash
rustc -O --emit asm --crate-type lib sum.rs -o sum.s
```

实测结果：**两个函数各生成 52 条指令，逐行完全相同**——唯一的差别是寄存器编号（`x9` / `x10` 互换）与基本块标签（`LBB0_*` 对 `LBB1_*`）。摘录两边主循环的第一段：

```asm
; sum_iter                          ; sum_loop
and     x9, x1, #0xffffffffffffff8  and     x9, x1, #0xffffffffffffff8
add     x8, x0, #32                 add     x8, x0, #32
movi.2d v0, #0000000000000000       movi.2d v0, #0000000000000000
ldp     q4, q5, [x8, #-32]          ldp     q4, q5, [x8, #-32]
ldp     q6, q7, [x8], #64           ldp     q6, q7, [x8], #64
cmgt.2d v16, v4, #0                 cmgt.2d v16, v4, #0
and.16b v4, v4, v16                 and.16b v4, v4, v16
add.2d  v4, v4, v4                  add.2d  v4, v4, v4
subs    x10, x10, #8                subs    x10, x10, #8
b.ne    LBB0_5                      b.ne    LBB1_5
```

这就是「零成本」的实证含义，而且这个例子还顺带证明了第二件事：**LLVM 把两种写法都自动向量化了**（NEON：`ldp` 一次取 4 个 `i64`、`cmgt.2d` 做比较生成掩码、`and.16b` 实现「负数置零」、`add.2d` 实现乘 2 累加）。手写循环并没有「更接近硬件」，因为它和迭代器链是同一段机器码——适配器为什么能被内联成一次指针比较、`size_hint` 又如何决定 `collect` 的预分配，都写在 [Iterator](/docs/CS/Rust/Iterator.md) 里。

但这句话有三个必须说清的边界：

- **它只在优化开启时成立**。同一个文件不加 `-O` 时，迭代器版本的指令数与手写版本不再一致（中间层 `Filter` / `Map` 的适配器还在）。**任何在 debug 构建下做的性能判断都是无效的**。
- **自动向量化不是承诺**。上例的向量化是 LLVM 的决定，不是语言的保证。循环里只要出现无法静态分析的边界、别名或浮点重排约束，向量化就会静默退化成标量。想要确定性的 SIMD，得自己写（见 SIMD 一节）。
- **代价付在编译期**。每个泛型实例单态化出一份代码（[compile.md](/docs/CS/Rust/compile.md)），`derive` 密集的类型（尤其 serde）会显著推高编译时间——这一点在 [Ecosystem.md](/docs/CS/Rust/Ecosystem.md) 里有实测数字。「零成本」应读作「运行时零成本」，不是「零成本」。

## Measurement: criterion, black_box, and the Fate of `#[bench]`

### `#[bench]` Is Gone on Stable

这是一条容易被旧资料误导的版本事实。release notes 1.88.0（2025-06-26）的 Language 一节原文：**"Fully de-stabilize the `#[bench]` attribute. Usage of `#[bench]` without `#![feature(custom_test_frameworks)]` already triggered a deny-by-default future-incompatibility lint since Rust 1.77, but will now become a hard error."**

本机 `rustc 1.98.1` 实测两条路径都堵死：

```text
// 不带 feature gate 写 #[bench]
error[E0658]: use of unstable library feature `test`: `bench` is a part of custom test frameworks which are unstable
error: functions used as benches must have signature `fn(&mut Bencher) -> impl Termination`

// 带 #![feature(test)]
error[E0554]: `#![feature]` may not be used on the stable release channel
```

注意措辞：1.88.0 之前它是 **deny-by-default 的 future-incompat lint**（自 1.77 起），1.88.0 起是**硬错误**。这条正好落在 [Edition_MSRV.md](/docs/CS/Rust/Edition_MSRV.md) 讲的 Compatibility Notes 通道上——语言演进的「受控破坏」是怎么落到普通代码身上的。

### `cargo bench` Itself Still Works

实测：stable 1.98.1 上 `cargo bench` 正常构建并运行 bench 目标。可用的姿势是 criterion + `harness = false`：

```toml
[dev-dependencies]
criterion = "0.8"

[[bench]]
name = "mybench"
harness = false
```

```rust
use criterion::{criterion_group, criterion_main, Criterion};
use std::hint::black_box;

fn fib(n: u64) -> u64 { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }

fn bench_fib(c: &mut Criterion) {
    c.bench_function("fib 20", |b| b.iter(|| fib(black_box(20))));
}
criterion_group!(benches, bench_fib);
criterion_main!(benches);
```

实测输出：

```text
Benchmarking fib 20: Collecting 100 samples in estimated 2.0406 s (86k iterations)
fib 20                  time:   [20.696 µs 21.839 µs 24.221 µs]
Found 7 outliers among 100 measurements (7.00%)
```

一个实测踩到的坑：`cargo bench -- <criterion 参数>` 会把参数同时喂给默认的 libtest 目标，实测报 `error: Unrecognized option: 'warm-up-time'`。正确写法是限定 bench 目标：`cargo bench --bench mybench -- --warm-up-time 1 --measurement-time 2`。另外 criterion 0.8.2 在没有 gnuplot 时会自行降级（实测输出 `Gnuplot not found, using plotters backend`）。

### Why `black_box` Is Mandatory

基准测试最大的系统性错误不是测错，而是**测了个空**：如果被测计算的结果没有被使用，LLVM 会判定它是死代码并整段删掉，你测到的就是 0 ns。

`std::hint::black_box` 是一个对优化器不透明的屏障：优化器必须假设它会对值做任何事，因此不能删除它上游的计算，也不能把它的常量传播下去。被测表达式要么整个包进 `black_box(...)`，要么让输入经过 `black_box`（如上例的 `fib(black_box(20))`），**两端至少要堵住一端**。

一个实测细节值得记住：**criterion 0.8.2 里的 `criterion::black_box` 已经被标记 deprecated**，实测警告原文是 ``use of deprecated function `criterion::black_box`: use `std::hint::black_box()` instead``。新代码一律用 `std::hint::black_box`。

### Profilers, Not Guesswork

`fib` 这种微基准只能回答「这两个写法哪个快」，回答不了「我的程序慢在哪」。宏观上要靠采样 profiler：Linux 上 `perf` + `cargo flamegraph`（flamegraph-rs），macOS 上 flamegraph-rs 走 xctrace；`samply` 用 Firefox Profiler 做前端，跨平台且能直接看源码行。这一层的输出是「哪个函数占了多少采样」，是优化顺序的唯一可靠依据。

## Symbol Names Changed in 1.97.0

这是一条**会打到所有按符号名工作的工具**的版本事实。release notes 1.97.0（2026-07-09）的 Compatibility Notes 原文：**"Rust will use the v0 symbol mangling scheme by default. This may cause some tools (such as debuggers or profilers, especially with old versions) to fail to demangle symbols emitted by Rust. It may also cause the formatting of text in backtraces to change."**

背景与三点后果：

- v0 scheme 自 **1.59** 起可通过 `-Csymbol-mangling-version=v0` 显式 opt-in，2025 年 11 月起在 nightly 默认，**1.97.0 起在 stable 默认**；旧的 Itanium ABI 方案要被移除。
- 动机：旧方案把泛型参数实例**哈希掉**，只留一个 hash；v0 保留泛型参数的具体值，且全链路一致（旧方案里并非所有部分都用 Itanium ABI，所以仍需要自定义 demangle）。
- 后果：backtrace 的**文本格式会变**；老版本 debugger / profiler 可能 demangle 失败；任何解析符号名的脚本（覆盖率、内存 profiling、手写的 `perf` 过滤规则）都要跟着改。

实测印证「旧方案只能在 nightly 上启用」这一条。在 stable 1.98.1 上试图切回 legacy：

```text
$ rustc -O -Csymbol-mangling-version=legacy --emit obj mg.rs
error: `-C symbol-mangling-version=legacy` requires `-Z unstable-options`

$ rustc -O -Zunstable-options -Csymbol-mangling-version=legacy --emit obj mg.rs
error: the option `Z` is only accepted on the nightly compiler
```

也就是说：想靠「切回旧 mangling」绕过工具链不兼容，在 stable 上根本没有这个开关。版本归属的三轴（编译器版本 / edition / MSRV）与 Compatibility Notes 这条受控破坏通道，见 [Edition_MSRV.md](/docs/CS/Rust/Edition_MSRV.md)。

这条和本文前面的 profile 调优是耦合的：如果你既开了 `strip = true` 又在用老版本 profiler，符号这一层会同时被「剥离」和「改名」两次处理。分发 stripped 二进制时记得保留单独的符号文件。

## Allocation and Copying

### How Vec Grows

std 对增长策略的立场是**明文拒绝规定**（[Collections.md](/docs/CS/Rust/Collections.md) 引了原文：*"Vec does not guarantee any particular growth strategy"*），唯一承诺的是 **O(1) 摊还 push**。所以下面只能作为「本机观测」而不是规范：

```rust
// rustc 1.98.1，aarch64-apple-darwin 实测
Vec<u8>    capacity 变化：8 → 16 → 32
Vec<String> capacity 变化：4 → 8 → 16
Vec::<u8>::with_capacity(1).capacity() == 1
```

首次非零容量之所以不同，是因为 std 内部对「最小非零容量」按元素大小取了不同下限（1 字节元素取 8，较大的取 4），以避免极小的堆分配。这是实现细节，**不要写进断言**。

预分配的收益可以实测。2000 轮 × 65536 个 `u64`，两种写法（两轮运行结果一致）：

| 写法 | 耗时 |
| :-- | :-- |
| `Vec::with_capacity(n)` + `clear()` 复用 | 158.87 ms / 160.90 ms |
| 每轮 `Vec::new()` 从头增长 | 202.99 ms / 203.42 ms |

约 **1.27×**。量级不大（增长本身是摊还 O(1)），但它是免费的——知道最终容量时就该 `with_capacity`。

### What `clone` Actually Costs

`clone` 不是「复制一个值」这么便宜，它是**一次堆分配 + 一次 memcpy + 未来的一次释放**。实测：1 MiB `String` 克隆 200 次 = 4.87 ms，即每次约 **24 µs**（≈ 43 GB/s 的有效拷贝带宽，且还要算上分配器开销）。

热路径上的判断规则很朴素：看到一个 `clone()`，先问「能不能改成借用」。常见可改情形：

- 参数只需要读 → `&str` 而不是 `String`，`&[T]` 而不是 `Vec<T>`；
- 需要两者通吃 → `impl AsRef<str>`，代价是每个实参类型单态化出一份；
- 只有部分路径需要所有权 → `Cow<'_, str>`（[Collections.md](/docs/CS/Rust/Collections.md) 讲 `Cow` 语义），只有 `to_mut()` 那条路径才真的分配；
- 只读共享 → `Arc<T>`，但要记住 `Arc::clone` 是**原子自增**，实测 1000 万次无竞争 `Arc::clone` = 96.86 ms，约 **9.7 ns/次**。单线程下它比 `clone` 一块大内存便宜得多，多核下它就是争用点（见后文）。

## Memory Layout Consequences on Performance

布局规则（`repr`、niche 优化、DST、padding）见 [Memory_Layout.md](/docs/CS/Rust/Memory_Layout.md)，本节只讲**性能后果**。

### False Sharing Is the Biggest Single Item

两个线程各自对一个 `AtomicU64` 做 2000 万次 `fetch_add(Relaxed)`，实测：

| 布局 | 耗时 |
| :-- | :-- |
| 两个 `AtomicU64` 相邻（`[AtomicU64; 2]`） | 252.87 ms |
| 各包一层 `#[repr(align(64))]`（实测 `size_of` 从 8 变 64） | 54.42 ms |

**4.6×**。这两个原子变量在逻辑上毫无关系，没有任何数据竞争，纯粹因为它们落在同一条 cache line 上，就导致每次写入都要让对方的 cache line 失效。这是 Rust 里最典型的「代码完全正确但慢得离谱」——借用检查器管不到 cache line，它只保证没有数据竞争。

对策是强制分开：`#[repr(align(64))]` 或手动填 padding。判据是「这个字段会被多个线程高频写吗」。

### AoS versus SoA Depends on Access Patterns

- **AoS（`Vec<Struct>`）**：一次遍历要读多个字段时，同一个对象的字段在同一条 cache line 上，局部性好；但只用一个字段时，其余字段白白占了 cache line。
- **SoA（每个字段一个 `Vec`）**：只扫一个字段时每个 cache line 全是有效数据（也更容易被自动向量化）；但要同时用多字段就得维护多条流的同步。

没有普适答案，取决于热循环访问几个字段。判断依据是 profiler 给出的 cache miss，不是风格偏好。

### The Hidden Cost of Padding

`size_of::<T>()` 通常大于各字段之和，因为对齐会插入 padding。字段顺序不当会白白多出一截——`Memory_Layout.md` 给出规则，这里的性能含义是：**每多一条 padding，每个元素就多占几字节，一个大 `Vec` 的总内存与 cache 占用就按比例膨胀**。按对齐降序排列字段是零成本的优化。

## Locks and Atomics

std 原语与 `Ordering` 的语义见 [Concurrency.md](/docs/CS/Rust/Concurrency.md)，本节只讲代价量级。

实测无竞争的 `std::sync::Mutex` lock/unlock 100 万次 = 8.82 ms，约 **8.8 ns/次**。这个数字的意义在于：锁在无竞争时不是「慢」的代名词，真正的成本都在**竞争**上（内核 futex 等待、上下文切换、cache line 乒乓）。

`parking_lot 0.12.5` 与 std 锁的实质差别（选型细节见 [Ecosystem.md](/docs/CS/Rust/Ecosystem.md)）是：没有 poisoning 语义（`lock()` 直接返回 guard 而非 `Result`）、表示更紧凑、提供可升级读锁 `upgradable_read`、以及不同的公平性策略。换之前先确认你不需要 poisoning——std 那个 `Err(PoisonError)` 在「持有锁时 panic 了」的场景是有用的信号。

`Arc` 的争用是另一类典型问题。引用计数是共享的单个原子变量，多核高频 `clone` / `drop` 会把它变成热点，其症状和 false sharing 完全一样（同一个 cache line 被反复抢）。对策有三条，按侵入性递增：

1. **读多写少**：用快照——写者整体替换一个 `Arc<Config>`，读者 `Arc::clone` 一次后长期使用，而不是每次访问都 clone。
2. **高频计数**：分片。每线程一个计数器，读时求和（`dashmap` 的分片思路同样适用）。
3. **降级 Relaxed**：只在计数本身不参与同步顺序时（[Concurrency.md](/docs/CS/Rust/Concurrency.md) 讲 `Ordering` 的语义边界）。

## Build Profile Tuning

同一份代码（200 万次循环的小二进制），**冷构建**（`rm -rf target` 后 `cargo build --release`）实测：

| profile 配置 | 冷构建 real | 产物体积 |
| :-- | :-- | :-- |
| release 默认（`lto = "off"`, `codegen-units = 16`） | 3.25 s | 434,016 B |
| `lto = "thin"` + `codegen-units = 16` + `panic = "abort"` + `strip = true` | 4.76 s | 339,184 B |
| `lto = "fat"` + `codegen-units = 1` + `panic = "abort"` + `strip = true` | 5.38 s | 302,480 B |

几个读表要点：

- **体积上 fat LTO 最狠**（−30%），代价是构建时间 +66%。thin LTO 拿到 −22%，时间 +46%。
- **`panic = "abort"` 与 `strip = true` 的体积收益被算进了后两行**，所以不要把这 30% 全记在 LTO 头上。
- 这是**单 crate 的玩具程序**。真实项目依赖越多，LTO 的绝对时间代价越大，而收益（跨 crate 内联消除）也越大。

各开关的取舍：

| 开关 | 作用 | 代价 / 陷阱 |
| :-- | :-- | :-- |
| `opt-level` | `0`（dev 默认）到 `3`（release 默认）；`"s"` / `"z"` 面向体积 | 低于 3 时本文开头那个「迭代器 = 手写循环」的等价性**不成立** |
| `lto` | `"off"` / `"thin"` / `"fat"` | fat 全量跨 crate 优化，最慢最小；thin 折中且可并行 |
| `codegen-units` | release 默认 16 | `1` 让 LLVM 一次看到整个 crate，优化更好但放弃并行 codegen |
| `panic = "abort"` | 去掉 unwind 表与 landing pad | **`catch_unwind` 失效**，`Drop` 不再在 unwind 时运行（见 [Error_Handling.md](/docs/CS/Rust/Error_Handling.md)） |
| `strip = true` | 移除符号 | profiler 与 backtrace 需要符号，务必保留单独符号文件；与 1.97 的 v0 mangling 叠加时尤其注意 |
| `debug = false` | release 默认已是 `false` | 需要线上定位时改用 `debug = 1` + `split-debuginfo` |
| `-C target-cpu=native` | 按本机 CPU 启用指令集 | stable 可用（实测通过）；**产物不可在其他 CPU 上跑**，只适合本机运行或已知硬件 |

`target-cpu=native` 有一个实测踩到的调用约束：`cargo rustc` 必须限定单个 target，否则报错：

```text
error: extra arguments to `rustc` can only be passed to one target, consider filtering
the package by passing, e.g., `--lib` or `--bin NAME` to specify a single target
```

另一个常被问的选择是换分配器（jemalloc / mimalloc）。它不属于 profile 开关，而是换 `#[global_allocator]`；收益取决于分配模式（大量小对象、多线程分配时最明显），同样需要实测而不是照抄。

## SIMD on Stable

`std::simd` **仍在 nightly**，feature gate 名是 **`portable_simd`**（tracking issue #86656）。本机只装了 stable 1.98.1 与 1.95.0，**没有 nightly，无法实测**，故按 unstable book 与官方文档记为 nightly-only：任何用到它的 crate 都必须 nightly 编译，且 API 仍会随 nightly 变动。

stable 上只有两条路：

1. **LLVM 自动向量化**。零工作量，但不保证——本文开头那两个 `sum` 函数就是它生效的例子；反过来，一旦循环里出现浮点重排约束、别名不确定或边界无法静态分析，它就会静默退化。判断有没有生效，只能看 asm（`cargo rustc --release --lib -- --emit asm`）。
2. **`std::arch` intrinsics + `#[target_feature]`**。显式、确定，代价是平台绑定。自 **1.87.0** 起（release notes 1.87.0 的 Platform Support 一节），**大多数不接收指针参数的 `std::arch` intrinsic 可以在带 `#[target_feature]` 标注的安全函数中直接调用**；加载 / 存储类 intrinsic（涉及裸指针）仍然是 `unsafe`。运行时分发靠 `is_x86_feature_detected!`，注意分发本身有函数调用边界的开销，粒度太小的函数反而不划算。

对比之下，`std::simd` 的价值是**可移植**：同一份 `Simd<T, N>` 代码在所有 LLVM 支持的目标上都能编（没有对应指令时退化成标量）。要不要为它上 nightly，取决于你的部署目标是否单一。

## A Checklist

按收益与风险排序，前三条是「先做」：

1. **先测量**。criterion 0.8.2 + `std::hint::black_box`，或采样 profiler 找热点。不做这步，后面全是猜测。
2. **确认你在测 release**。`opt-level` 低于 3 时抽象不会消失（见第一节）。
3. **消除不必要的分配与 `clone`**：`with_capacity`、`Cow`、`&str` 参数、借用替代克隆。
4. **检查热路径的意外装箱**：`Box<dyn Trait>` 在热循环里是间接跳转 + 可能的分配；能静态分发就静态分发（[Trait_System](/docs/CS/Rust/Trait_System.md) 与 [Generics](/docs/CS/Rust/Generics.md) 讲单态化与 dyn 的取舍）。
5. **检查布局**：热字段是否相邻、跨线程写的字段是否隔开了 cache line、大 `Vec` 是否因 padding 膨胀、热循环是否该改 SoA。
6. **减少原子争用**：快照、分片计数、必要时降级 `Ordering`。
7. **最后才动 profile**：`lto` / `codegen-units` / `panic = "abort"` / `strip` / `target-cpu`，按前面的实测表权衡时间与体积。
8. **把结论固化成基准**：优化之后补一个 criterion 基准，防止回归。

每一步之间都要重新测量。**第 2 条和第 3 条的收益通常远大于第 7 条**——profile 调优是最后几个百分点，算法与分配是数量级。

## Cross-Language Comparison

| 维度 | Rust | C / C++ | Go | Java |
| :-- | :-- | :-- | :-- | :-- |
| 理论性能上限 | 与 C 同级（同为 LLVM 后端、无 GC） | 基准 | 略低（GC + 逃逸分析不完全） | JIT 可达甚至超过 AOT（按运行时 profile 重优化） |
| 运行时停顿 | **无 GC 停顿** | 无（除非分配器抖动） | GC 停顿（通常亚毫秒级） | GC 停顿，取决于收集器 |
| 运行时自适应 | **无 JIT**，不按运行时 profile 重新优化 | 无 | 无 | 有（热点探测、去优化与重优化） |
| 抽象的运行时代价 | 单态化 → 运行时零成本，编译期付账 | 模板同理；运行时多态走 vtable | 接口调用是动态分发 | 虚方法 + JIT 内联（可撤销） |
| 内存占用 | 无 per-object header、无 GC headroom | 最低 | GC 需要 headroom | JVM 元空间 + GC headroom |
| 典型失分点 | 误用 `clone`、意外 `Box`、伪共享 | UB 与手误 | 逃逸分析失败导致堆分配 | 预热期、GC、装箱 |
| 性能可预测性 | 高（无运行时重编译） | 高 | 中 | **低**（同一段代码在不同 profile 下表现不同） |

这张表里最有信息量的是**运行时自适应**那一行。Rust 与 C/C++ 的可预测性来自「AOT 定死」，Java 的峰值性能来自「JIT 按实际执行路径重排」——两者是相反的设计赌注：前者牺牲了对运行时信息的利用，后者牺牲了可预测性与启动延迟。Go 夹在中间：AOT 编译，但有 GC 与运行时调度。

「Rust 比 C 快」和「Rust 比 Java 快」都不是有意义的命题。真实差异不来自语言，而来自**抽象被怎么用**：一段误用 `clone` 与 `Box` 的 Rust 代码会输给写得干净的 Java 代码，而一段避免了伪共享的 Rust 代码和等价的 C 代码是同一段机器码（这正是第一节那个实验的结论）。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Drop](/docs/CS/Rust/Drop.md)
- [Ownership](/docs/CS/Rust/Ownership.md)

## References

- [Rust Release Notes（1.88.0 / 1.97.0 条目）](https://doc.rust-lang.org/stable/releases.html)
- [Announcing Rust 1.97.0 — Symbol mangling v0 enabled by default](https://blog.rust-lang.org/releases/1.97.0/)
- [The rustc book — Symbol Mangling](https://doc.rust-lang.org/rustc/symbol-mangling/index.html)
- [The Cargo Book — Profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)
- [The Cargo Book — Build Scripts / rustc flags via `cargo rustc`](https://doc.rust-lang.org/cargo/commands/cargo-rustc.html)
- [std::hint::black_box](https://doc.rust-lang.org/std/hint/fn.black_box.html)
- [std::simd（nightly，gate `portable_simd`）](https://doc.rust-lang.org/std/simd/index.html)
- [The Unstable Book — portable_simd](https://doc.rust-lang.org/unstable-book/library-features/portable-simd.html)
- [rust-lang/rust#86656 — portable_simd tracking issue](https://github.com/rust-lang/rust/issues/86656)
- [std::arch](https://doc.rust-lang.org/std/arch/index.html)
- [criterion 0.8.2 documentation](https://docs.rs/criterion/0.8.2/criterion/)
- [flamegraph-rs / cargo flamegraph](https://github.com/flamegraph-rs/flamegraph)
- [samply — sampling profiler with Firefox Profiler UI](https://github.com/mstange/samply)
- [parking_lot 0.12.5 documentation](https://docs.rs/parking_lot/0.12.5/parking_lot/)
- [std::sync::atomic](https://doc.rust-lang.org/std/sync/atomic/index.html)
