## Introduction

`#![no_std]` 是 Rust 唯一一个「改变 crate 与外部世界连接方式」的 crate 级属性。它的常见误读是「禁用标准库」，但真实机制更精确：**它只是让编译器把隐式注入的 `extern crate std` 换成 `extern crate core`**。剩下的一切——`Vec` 找不到、`main` 不能写、必须自己写 `#[panic_handler]`——都是这一次换链的后果，而不是某个开关直接禁止了你用什么。

理解这一点之后，no_std 的全部难点收敛成三个可枚举的问题：**哪些能力随 `std` 一起消失**（`core` / `alloc` / `std` 三层的能力边界）、**消失的能力中哪些必须由 crate 作者自己补上**（panic 运行时、入口、全局分配器）、**怎么让同一个 crate 在两边都能用**（feature 双模）。嵌入式生态（embedded-hal、cortex-m、heapless、embassy、defmt、probe-rs）与 **BSP crate** 本质上是这三问的工程答案，而不是另一套语言。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，最新 edition 为 2024。本篇所有编译诊断与运行结果都在本机 `rustc 1.98.1 (48a229cea 2026-09-01)`（host `aarch64-apple-darwin`）上实跑，报错原文照抄；crate 版本取自 crates.io sparse index（`https://index.crates.io/...`）实测。**本机是 macOS 宿主，没有裸机目标、没有 nightly 工具链**（`rustup toolchain list` 只有 `stable` 与 `1.95.0`，`rustup target list --installed` 只有 `aarch64-apple-darwin`），因此链接脚本、中断向量表、`-Z build-std`、真实芯片上的 `_start` 等一律标注「未在裸机实测」或「据文档」，不谎称实测。

## What no_std Actually Changes

`#![no_std]` 的完整语义只有一句话：不向 crate 根部注入 `extern crate std;`（`std` 的隐式注入是 edition 2015 之后编译器的默认行为）。`core` 是**始终隐式注入**的，无论有没有 `#![no_std]`。所以它不是一个「减去」操作，而是一个「换成」操作：

实测：一个 `#![no_std]` lib，函数体里用 `Option`、`core::mem::size_of::<u64>()`、`unwrap_or`，`rustc --crate-type lib --edition 2021 a.rs` 退出码 0，零告警。`Iterator`、闭包、trait、`unsafe`、`core::arch` 亦全部照常可用——**`no_std` 削掉的是「依赖操作系统」的那部分能力，语言本身一点没少**。这是 Rust 与 C 裸机开发最大的分野：C 在 freestanding 下连 `memcpy` 都要自己提供（`compiler_builtins` 在 Rust 侧由编译器自动带），而 Rust 的 `core` 带着完整的类型系统与迭代器。

三层的依赖方向是**单向的**：`std` → `alloc` → `core`，反过来不成立。`std` 的源码里到处是 `use alloc::vec::Vec;`，`alloc` 里没有一行引用 `std`。这条单向性是可执行的——在 `#![no_std]` crate 里写 `std::time` 会直接炸：

```text
error[E0433]: cannot find module or crate `std` in this scope
 --> g.rs:3:5
  |
3 |     std::time::SystemTime::now().elapsed().unwrap().as_secs()
  |     ^^^ use of unresolved module or unlinked crate `std`
  |
  = help: you might be missing a crate named `std`
```

注意措辞是 **unlinked**，不是 forbidden。`std` 这个 crate 根本没有进链接集，所以 `std::` 路径在名字解析阶段就找不到。同理 `std::thread::spawn` 报的是同一条 E0433。

### Capability Boundary Table

| 能力 | `core` | `alloc` | `std` | 归属说明 |
| :-- | :-- | :-- | :-- | :-- |
| `Option` / `Result` / `Iterator` / 闭包 | ✓ | ✓ | ✓ | 语言 + `core` |
| `core::fmt::Display` / `Debug` / `write!` | ✓ | ✓ | ✓ | `core::fmt` 不含堆 |
| `Vec` / `String` / `format!` | ✗ | ✓ | ✓ | 实测：no_std 下 `Vec` 报 E0425、`format!` 报 "cannot find macro" |
| `Box` / `Rc` | ✗ | ✓ | ✓ | `Box` 在 `alloc`（实测 E0425），`Rc` 在 `alloc::rc` |
| `Arc` / `std::sync::Mutex` | ✗ | ✗ | ✓ | 需要线程概念 |
| `BTreeMap` / `VecDeque` / `LinkedList` / `BinaryHeap` | ✗ | ✓ | ✓ | `alloc::collections` |
| `HashMap` / `HashSet` | ✗ | ✗ | ✓ | 需要 `RandomState`（随机化的 hasher 来自 `std`）；`wasm32-unknown-unknown` 是特例，见 WASM 节 |
| 全局分配器契约 `GlobalAlloc` / `Layout` | ✓（trait 定义） | ✓ | ✓ | trait 在 `core::alloc`，**实现**由你给 |
| 原子 `AtomicUsize` / `Ordering` | ✓（target 支持时） | ✓ | ✓ | 单核 MCU 上 CAS 由 `critical-section` 或 `portable-atomic` 补 |
| `std::time::Instant` / `SystemTime` | ✗ | ✗ | ✓ | 需要 OS 时钟 |
| 文件 IO `std::fs` | ✗ | ✗ | ✓ | 需要 OS |
| 线程 `std::thread` / `thread_local!` | ✗ | ✗ | ✓ | 需要 OS 调度 |
| panic 运行时（unwind / 打印 / abort） | ✗ | ✗ | ✓ | `core` 只定义 `panic!` 宏与 `PanicInfo`，**不实现运行时** |
| 入口（调用 `main` 的运行时） | ✗ | ✗ | ✓ | `std` 提供 `lang_start`；no_std 要自己写入口 |

表格里最容易被误记的一行是 `HashMap`：它不在 `alloc`，因为 `RandomState` 依赖 `std` 的随机数源。这是「`alloc` = 有堆的 `core`」这个口诀唯一失效的地方——`alloc` 是「有堆且无需 OS」，不是「`std` 减去 OS」。

## Why Go no_std

六个动机，按「是否可替代」排序——前三个是硬约束，后三个是优化：

| 动机 | 典型场景 | 为什么必须 no_std |
| :-- | :-- | :-- |
| 裸机无 OS | Cortex-M 固件 | 目标根本没有 `std` 可链（`thumbv*` 无预编译 std），不 no_std 就编不出来 |
| 内核 / bootloader | 自己写 OS 内核、UEFI 应用 | `std` 假定自己之下有 OS syscall，而「OS」就是你 |
| WASM 特定目标 | `wasm32v1-none` | 该目标**不提供 std**，只有 `core` / `alloc`（据 rustc book） |
| 减小体积 | 固件 flash 只有几十 KB | 实测见下：空 `main` 从 464992 B 降到 16816 B |
| 避免 libc 依赖 | 静态分发、musl 之外的场景 | `std` 在 Unix 上走 libc，交叉链接 libc 是额外的供应链 |
| 避免 `std` 启动开销 | 硬实时、boot 阶段 | `std` 启动要建 `stdout` 缓冲、设 panic hook、读环境变量 |

体积这一条本机实测（`-O`，`aarch64-apple-darwin`）：

| 程序 | std | no_std（`-C panic=abort`） | 比值 |
| :-- | :-- | :-- | :-- |
| 空 `main() {}` | 464992 B（`__TEXT` 278528） | 16816 B（`__TEXT` 16384） | 27.7× |
| `Vec` + `format!` + 输出 | 469144 B | 57320 B | 8.2× |

必须诚实标注这个对照的边界：no_std 那一侧同时用了 `-C panic=abort`、自己写的 bump 分配器、裸 `write(2)` 而非 `println!`，所以差距里混了「没 unwind 表」「没 std 格式化器」「没 std IO 栈」三项，不能全算在 `no_std` 头上。但 27× 这个量级足以说明 `std` 不是零成本的可选项。

## What You Must Supply Yourself

`std` 替你做的四件事，no_std 下全都要自己补：**panic 运行时、unwind 人格函数、程序入口、全局分配器**。逐个看缺它时的真实报错。

### panic_handler

`core` 定义了 `panic!` 宏与 `core::panic::PanicInfo`，但**没有 panic 运行时**——没人负责打印、没人负责 abort、没人负责 unwind。`#[panic_handler]` 就是填这个位置的 lang item。注意 handler 收的是 `core::panic::PanicInfo`，不是 `std` 侧新名字 `PanicHookInfo`——实测写 `&core::panic::PanicHookInfo` 报 E0425 `cannot find type PanicHookInfo in module core::panic`，并提示 `similarly named struct PanicInfo defined here`。缺 handler 时（实测，no_std bin）：

```text
error: `#[panic_handler]` function required, but not found

error: aborting due to 1 previous error
```

它必须是 `fn(&core::panic::PanicInfo) -> !`，且整个依赖图里**只能有一个**（实测 `#[panic_handler] fn ph(_: &core::panic::PanicInfo) -> ! { loop {} }` 可编译）。

注意一个反直觉的事实：**lib crate 不需要 `panic_handler`**，只有最终链接成可执行文件（`--crate-type bin`）时才要求——它是链接期需求，不是类型检查期需求。所以写 no_std **库**不用碰它，写**固件 / 内核**才必须写。

### eh_personality

unwind 需要一个「人格函数」（personality routine）在栈展开时读 `.eh_frame`、找 cleanup landing pad。`std` 提供它；no_std 下要么 `panic = "abort"`（不需要展开），要么自己给。

实测拿到它的方式很戏剧性：在 macOS 宿主上写 no_std + `alloc` 的可执行文件，即使加了 `-C panic=abort`，链接器依然报：

```text
  = note: Undefined symbols for architecture arm64:
            "_rust_eh_personality", referenced from:
                .../lib/rustlib/aarch64-apple-darwin/lib/liballoc-3daa19367295a846.rlib[4](alloc-....rcgu.o)
          ld: symbol(s) not found for architecture arm64
```

这正是官方那条提示的实证（实测报错原文里就带）：

```text
error: unwinding panics are not supported without std
  |
  = help: using nightly cargo, use -Zbuild-std with panic="abort" to avoid unwinding
  = note: since the core library is usually precompiled with panic="unwind", rebuilding your crate with panic="abort" may not be enough to fix the problem
```

**`panic = "abort"` 只改你自己的 crate，不改预编译好的 `libcore` / `liballoc`**——后者是发行版用 `panic = "unwind"` 编的，内部引用 `rust_eh_personality`。要让 `liballoc` 也按 abort 编，只有重新编译标准库，也就是 `-Z build-std`（见后文）。实测的绕过办法是补一个空符号 `#[no_mangle] extern "C" fn rust_eh_personality() {}`，补上即链接通过——但这是**宿主 hack，不是裸机做法**。另外想用 `#[lang = "eh_personality"]` 直接挂上去在 stable 上被拒（实测 E0658 "lang items are subject to change"）：lang item 是编译器内部契约，`panic_handler` 是极少数被官方开成稳定 lang item 的例外。

### Entry Point

`std` 的入口链条是：`_start`（C 运行时）→ `lang_start` → `main`。no_std 下这条链条整条消失。直接写 `fn main` 实测被拒：

```text
error: using `fn main` requires the standard library
  |
  = help: use `#![no_main]` to bypass the Rust generated entrypoint and declare a platform specific entrypoint yourself, usually with `#[no_mangle]`
```

于是要 `#![no_main]` + 自己导出平台要求的入口符号。真裸机上通常是 `Reset` 或 `_start`（名字由链接脚本和启动文件约定）；在 macOS 宿主上试 `_start` 会得到（实测）：

```text
  = note: Undefined symbols for architecture arm64:
            "_main", referenced from:
                <initial-undefines>
            "dyld_stub_binder", referenced from:
                <initial-undefines>
```

两个信息：① macOS 的动态链接器入口约定是 `_main` 不是 `_start`；② `-nodefaultlibs`（no_std 编译自动带上）导致 `libSystem` 不被默认链接，`dyld_stub_binder` 无人提供。这两条恰好说明**入口是 ABI 约定而非语言特性**——同一个 no_std crate 换目标就要换入口代码，这正是 BSP crate 存在的理由之一。

顺带一个版本事实（实测）：自定义入口的旧写法 `#![feature(start)]` 已被移除，报 E0557 `feature has been removed`，note 写 `removed in 1.86.0`、`not portable enough and never RFC'd`。

### global_allocator

用 `alloc` 才需要。`#[global_allocator]` 填的是 `core::alloc::GlobalAlloc` 这个契约槽位。实测：no_std **lib** 用 `alloc` 不报任何错，**bin** 才报——

```text
error: no global memory allocator found but one is required; link to std or add `#[global_allocator]` to a static item that implements the GlobalAlloc trait

error: `#[panic_handler]` function required, but not found

error: unwinding panics are not supported without std

error[E0601]: `main` function not found in crate `e`
```

四条同时出现，正好覆盖本节四件套。定义方式就是 `unsafe impl GlobalAlloc for Bump` 加 `#[global_allocator] static A: Bump = Bump;`（实测可编译、可运行）。两个槽位都只允许一份，重复定义实测报 `error: cannot define multiple global allocators`，并指回前一个定义处。

分配器返回 `null` 时 `alloc` 会走 `handle_alloc_error`，而它默认就是一次 panic——实测让 `alloc` 恒返回 `null` 后 `Vec::push` 直接触发我自己的 `panic_handler`（打印 `PANIC` 后 `exit(3)`，退出码 3）。**所以「no_std 没有 panic 运行时」这话要加半句：你自己提供的那个 handler 就是运行时**，它同时承接 panic 与 OOM。

把四件套补齐后，实测在 macOS 宿主上真的跑起来了一个 no_std + `alloc` 程序（bump 分配器 + 裸 `write(2)`）：

```text
sum=140 len=8 size_of_Vec=24
```

`size_of::<Vec<u32>>() == 24` 与 [内存布局](/docs/CS/Rust/Memory_Layout.md) 之外的常识一致（ptr + len + cap，64 位），说明 `alloc::vec::Vec` 就是 `std` 里那个 `Vec`，`std` 只是 re-export。

## Panic Strategy: abort versus unwind

`panic` 策略是 `Cargo.toml` 的 `[profile.*] panic` 或 `rustc -C panic=`，与 no_std **正交但强耦合**：

| | `panic = "unwind"` | `panic = "abort"` |
| :-- | :-- | :-- |
| 语义 | 沿栈展开，跑 `Drop`，可被 `catch_unwind` 捕获 | 直接 `abort`，不跑 `Drop` |
| 需要 eh_personality | 是 | 否（但预编译库仍可能引用，见上） |
| no_std 可用 | 否（实测 "unwinding panics are not supported without std"） | 是 |
| 二进制体积 | 大（`.eh_frame` + landing pad） | 小 |

`std` 下 `catch_unwind` 能工作正是因为 unwind；no_std 下没有 unwind，也就没有 `catch_unwind`——错误必须靠返回值传播，没有「抛出异常」这条路。这直接决定了下一节的写法。

一个易混点：`core::panic!` 与 `std` 的 panic 是**同一个宏的两个面**。`panic!` 在 `core` 里就存在（实测 no_std lib 里 `panic!("too big")` 与 `core::panic!("always")` 都编译通过），它做的是构造 `PanicInfo` 然后调用 panic 运行时。no_std 下这个运行时是你的 `#[panic_handler]`；`std` 下是 `std::panicking` 里那一套（打印 backtrace、跑 hook、unwind 或 abort）。**宏与格式化逻辑共用，运行时分离**——`defmt` 就是利用这一点把格式化整个换掉的（见生态节）。

## Writing a Dual-Mode Crate

绝大多数库不应该在 std / no_std 之间二选一，而应该双模。标准写法（实测 `cargo build` 与 `cargo build --no-default-features` 均通过）：

```toml
[features]
default = ["std"]
std = []
```

```rust
#![cfg_attr(not(feature = "std"), no_std)]
#![allow(unused)]

extern crate alloc; // std 模式下也无害：alloc 已被 std 拉进来

#[cfg(feature = "std")]
pub fn describe() -> String { format!("std mode: {}", std::env::consts::OS) }

#[cfg(not(feature = "std"))]
pub fn describe() -> alloc::string::String { alloc::format!("no_std mode") }
```

三个必须记住的点：

1. **`#![cfg_attr(not(feature = "std"), no_std)]` 而不是 `#![no_std]`**。前者让属性本身受 feature 控制，后者是无条件的。
2. **`extern crate alloc;` 必须显式写**。`alloc` 不像 `core` / `std` 那样被隐式注入——它只是一个普通 crate，要不要链由你决定。这是 `Vec` 在 no_std 下报 E0425 的直接原因（名字解析压根没进作用域）。
3. **feature 是加法且跨 crate 并集**。`std` 这种「能力型 feature」尤其危险：依赖图里任何一个 crate 打开它，你就被打开了。实测 `cargo tree -f "{p} {f}"`：

```console
$ cargo tree -p outer -f "{p} {f}"     # outer 用 default-features = false
outer v0.1.0
└── inner v0.1.0

$ cargo tree -p outer -f "{p} {f}"     # outer 用默认依赖
outer v0.1.0
└── inner v0.1.0  default,std
```

第二行那个 `default,std` 就是事故现场。所以 no_std 侧的依赖一律写 `default-features = false`，并且**在每个 feature 上做一次 `cargo build --no-default-features`**。

一个反直觉的实测结论，值得单独强调：**在宿主目标上，一个 `#![no_std]` crate 依赖 std-only crate 照样能编译通过**。实测 `#![no_std]` lib 依赖 `rand = "0.8"`（它拉进 `libc`、`getrandom` 等），`cargo build` 直接成功。原因是 `std` 这个 crate 对 `aarch64-apple-darwin` 是存在的，依赖里的 `use std::...` 合法——**「我的 crate 是 no_std」约束的只是我自己的源码，不含依赖**。真正的崩溃发生在交叉编译到没有 `std` 的目标时（`thumbv7em-none-eabihf` 之类）：那时依赖里的 `std` 无库可链，才报一堆 E0433 / 链接错误。

这个区分很重要：**排查 std 泄漏不能靠在宿主上编译，必须 `cargo build --target <裸机triple>`，或用 `cargo tree -f "{p} {f}"` 静态看 feature。** 本机没有安装裸机 target，交叉编译那条为据文档，`cargo tree` 部分已实测。

## Error Handling Without std

[错误处理](/docs/CS/Rust/Error_Handling.md) 的结论在 no_std 下退化的地方很窄，但很要命：

| `std` 侧的惯用法 | no_std 下 | 替代 |
| :-- | :-- | :-- |
| `core::fmt::Display` / `Debug` | ✓ 照常 | 无 |
| `thiserror` 派生 | ✓（它只依赖 `core::fmt`） | 无 |
| `Box<dyn Error>` | ✗ | 需要 `alloc`：`alloc::boxed::Box<dyn core::error::Error>` |
| `std::io::Error` | ✗ | 自己定义错误枚举，或 `embedded-io` 的 `ErrorKind` |
| `anyhow` | ✗（依赖 `std::error::Error` 的 `downcast`） | 无直接等价物 |
| `?` 运算符 / `From` 转换 | ✓ 照常 | 无 |

实测：`core::error::Error` 这个 trait 本身在 `core` 里（`Error` 已被移入 core，no_std 可用），但 `Box` 不在——所以

```text
error[E0425]: cannot find type `Box` in this scope
 --> n.rs:7:34
  |
7 | pub fn boxed_err() -> Result<(), Box<dyn core::error::Error>> { Ok(()) }
  |                                  ^^^ not found in scope
```

要么 `extern crate alloc;` 后写 `alloc::boxed::Box`，要么干脆别用动态错误类型——嵌入式里更常见的选择是**自己的错误枚举 + `#[derive(Debug)]` + `Display`**，因为（a）没有堆，（b）`dyn` 的 vtable 占 flash，（c）错误种类在编译期已知。

顺带一句：`core::fmt::Display` 与 `write!` 完全可用（实测在 no_std lib 里手写 `impl fmt::Display` 编译通过），但 `core::fmt` **没有 `std::io::Write` 那样的 sink**，输出到哪里（UART / RTT / semihosting）由你决定，这正是 `defmt` 与 `embedded-io` 各自切入的位置。

## The Embedded Ecosystem

版本号均取自 crates.io sparse index 实测（2026-10-08），MSRV 取自索引里的 `rust_version` 字段：

| crate | 版本 | MSRV | 在栈里的位置 |
| :-- | :-- | :-- | :-- |
| embedded-hal | 1.0.0 | 1.60 | **HAL trait 层**：定义 `OutputPin` / `SpiBus` / `DelayNs` 等 trait |
| cortex-m | 0.7.9 | 1.85 | Cortex-M 内核外设（NVIC、SysTick、`asm::wfi`）+ `critical-section` 实现 |
| critical-section | 1.2.0 | — | 「临界区」的统一抽象槽位 |
| nb | 1.1.0 | 1.60 | 非阻塞 API 的 `Result<T, WouldBlock>` 约定 |
| heapless | 0.9.3 | 1.87 | 无堆集合：`Vec<T, N>` / `Deque` / `String<N>` / `spsc::Queue` |
| embassy-executor | 0.10.0 | — | 异步执行器（无 OS 线程、可无堆） |
| defmt | 1.1.1 | — | 把格式化搬到宿主端的日志框架 |
| probe-rs | 0.32.0 | 1.89 | 宿主侧调试 / 烧录工具链（替代 OpenOCD） |
| postcard | 1.1.3 | — | 面向 no_std 的紧凑序列化（COBS + serde） |
| wasm-bindgen | 0.2.129 | 1.81 | WASM 互操作（宿主侧代码生成） |
| libc | 0.2.190 | 1.65 | FFI 声明；**可 no_std**（只是声明，不调用 OS） |
| zerocopy | 0.8.61 | 1.56.0 | 零拷贝字节 ↔ 结构体转换 |

一处需要点名的索引事实：**`critical-section` 索引里存在 1.3.0，但它已被 yanked，最新可用版本就是 1.2.0**。只看「最大值」的自动化工具会在这里踩坑。

### embedded-hal: Why a Trait Layer

HAL 的意义不是「省事」，而是**把「驱动」与「芯片」两件事解耦**：驱动 crate（比如一个 SSD1306 OLED 驱动）只依赖 `embedded_hal::i2c::I2c` 这个 trait，不依赖 STM32 也不依赖 nRF；芯片厂提供的 HAL crate（如 `stm32f4xx-hal`）为具体芯片实现这些 trait。于是 `驱动 × 芯片` 的组合数从乘积变成和。

1.0.0 相对 0.2.x 的关键改动是**把错误类型拆成独立的 `ErrorType` trait**。实测：给 `struct Pin` 直接 `impl OutputPin`（两个方法返回 `Result<(), core::convert::Infallible>`）而不写 `ErrorType`，得到

```text
error[E0277]: the trait bound `Pin: embedded_hal::digital::ErrorType` is not satisfied
  --> src/lib.rs:5:5
   |
 5 |     fn set_low(&mut self) -> Result<(), core::convert::Infallible> { Ok(...
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ unsatisfied trait bound
help: the trait `embedded_hal::digital::ErrorType` is not implemented for `Pin`
```

补上 `impl ErrorType for Pin { type Error = core::convert::Infallible; }` 后编译通过（与 `nb 1.1.0`、`critical-section 1.2.0`、`postcard 1.1.3` 同处一个 `#![no_std]` crate 里一次编过）。0.2.x 用 `void::Void` 表达「不会失败」，1.0.0 换成 `core::convert::Infallible`——**这是 no_std 友好化的一部分**：不再需要外部 `void` crate。

### heapless: Collections Without a Heap

与 [集合类型](/docs/CS/Rust/Collections.md) 的对照点很直接：`heapless::Vec<T, N>` 的容量 `N` 是**类型参数**，存储内联在结构体里，因此 `size_of::<Vec<u8, 8>>()` 是编译期常量、无间接层、无重分配。代价是 `push` 可能返回 `Err`（容量满），而不是悄悄扩容。实测在 `#![no_std]` crate 里写 `let mut v: Vec<u8, 8> = Vec::new(); v.push(1).unwrap();`，`cargo build` 通过，依赖树只有 `heapless → byteorder / hash32 / stable_deref_trait`，**没有一个拉回 std**——这是「依赖树干净」的正面样本。

### embassy-executor: Async Without an OS

与 [异步](/docs/CS/Rust/Async.md) 的交叉点最容易写错：嵌入式 async **不需要 OS 线程，也不需要堆**。`async fn` 编译出的状态机是**存在栈上（或 `static` 里）的结构体**，`Waker` 由硬件中断触发（而不是线程池唤醒）。`embassy-executor` 做的是一个单栈、协作式的任务轮询器：任务 `await` 某个外设时让出，中断来了把对应 `Waker` 标为就绪，执行器再轮询。没有抢占、没有每任务独立栈、无 `Arc` 也能跑。这是 Rust `async` 设计成「零分配状态机 + 外部 executor」而非「内置运行时」的直接收益——Go / JavaScript 那种带运行时 goroutine / 事件循环的模型在这里塞不进去。

### critical-section: A Slot for Critical Sections

单核 MCU 上「关中断」没有统一指令（Cortex-M 用 `PRIMASK`，RISC-V 用 `mie`），而 `alloc` / `embassy` 这类通用 crate 又需要它。`critical-section` 的做法与 `GlobalAlloc` 完全同构：**定义契约，由平台 crate 在链接期填一个实现**。用户代码写 `critical_section::with(|cs| { ... })`，具体是关中断还是别的手段由 `cortex-m` 或 `riscv` 的实现决定。这是 no_std 生态里反复出现的设计模式——**用 lang-item 式的契约槽替代运行时多态**（`GlobalAlloc`、`panic_handler`、`critical_section`、`defmt::Logger` 四处同构）。

### defmt: Moving Formatting to the Host

`format!("x = {}", x)` 在固件里的代价是：格式化代码 + 格式字符串 + `Display` 实现全部进 flash，可能几十 KB。`defmt` 的做法是**固件侧只发一个「 interned 字符串索引 + 参数字节流」**，真正的格式化由宿主上的 `defmt-decoder` 结合 ELF 里的符号表完成（所以 `defmt` 要求链接脚本额外放一个 `.defmt` 段，并需要 ELF 文件参与解码——与 [ELF](/docs/CS/Compiler/ELF.md) 的知识在这里接上）。

### probe-rs: The Host-Side Toolchain

`probe-rs` 用 Rust 重写了调试探针协议（SWD / JTAG），替代 OpenOCD + GDB 的组合，并原生支持 `defmt` 的 RTT 解码与 `cargo embed` / `cargo flash` 工作流。它是**宿主侧的 std 程序**，不是固件的一部分——这个区分很重要：no_std 只约束跑在芯片上的那一半。

### BSP Crate: The Board Layer

栈的层次从上到下是：`应用` → `驱动 crate`（按 embedded-hal trait 写）→ `HAL crate`（芯片厂 / 社区，实现 trait + 提供 `Peripherals` 单例）→ `PAC crate`（外设寄存器映射，通常由 `svd2rust` 从厂商 SVD 生成）→ **BSP crate（板级支持包）**。

BSP crate 存在的理由与本文前几节一一对应：

1. **它固化入口与链接脚本**。链接脚本（`memory.x`，声明 FLASH / RAM 的 Origin 与 Length）、启动代码、`.vector_table` 段位置都是板级的，不是芯片级也不是应用级。`cortex-m-rt` 提供 `#[entry]` 宏与默认链接脚本骨架，BSP 负责给出本板的 `memory.x`——这正是上一节「入口是 ABI 约定」的落地。
2. **它完成契约槽的填充**：`#[panic_handler]`、`#[global_allocator]`（如果要用 `alloc-*` 类分配器）、`critical-section` 实现、`defmt` 的 `#[defmt::global_logger]`。这些全图只能有一份，天然属于「最后一个链接者」。
3. **它把引脚编号绑定成名字**。同一颗 STM32 在不同板子上接的 LED 引脚不同，BSP 提供 `Led` / `Button` / `Uart` 这类已配置好的类型，应用不再关心 `PA5` 还是 `PB7`。
4. **它固化时钟配置**。系统时钟树（PLL、分频、flash latency）是板级决策（取决于焊的晶振频率）。

典型命名：`stm32f4xx-hal` 是 HAL，`stm32f4-discovery` 是 BSP；`rp2040-hal` 是 HAL，`rp-pico` / `pimoroni-pico-explorer` 是 BSP。**BSP 就是「把本文前四节要求你自供的四件套 + 板级硬件事实打包好」的那一层**——这也是为什么写固件时几乎总是从 BSP 开始，而不是从 `#![no_std]` 开始。

## MMIO and volatile

与 [unsafe 与 FFI](/docs/CS/Rust/Unsafe_FFI.md) 的交叉点：MMIO 是 `unsafe` 最正当的用途之一，而且**必须 volatile**。理由不是「内存可能被别的线程改」而是「编译器有权把看起来冗余的读写删掉」。实测（`rustc -O --emit asm`，`aarch64-apple-darwin`）：

```rust
#[no_mangle] pub unsafe fn plain(p: *mut u32)       { core::ptr::write(p, 1); core::ptr::write(p, 2); }
#[no_mangle] pub unsafe fn vol(p: *mut u32)         { core::ptr::write_volatile(p, 1); core::ptr::write_volatile(p, 2); }
#[no_mangle] pub unsafe fn read_twice(p: *const u32) -> u32     { core::ptr::read(p) + core::ptr::read(p) }
#[no_mangle] pub unsafe fn read_twice_vol(p: *const u32) -> u32 { core::ptr::read_volatile(p) + core::ptr::read_volatile(p) }
```

```asm
_plain:                _vol:                    _read_twice:          _read_twice_vol:
    mov  w8, #2            mov  w8, #1              ldr  w8, [x0]         ldr  w8, [x0]
    str  w8, [x0]          str  w8, [x0]            lsl  w0, w8, #1       ldr  w9, [x0]
    ret                    mov  w8, #2              ret                   add  w0, w9, w8
                           str  w8, [x0]                                  ret
                           ret
```

三条结论，全是实测：

- `plain` 只剩 `mov w8, #2; str` —— 第一次写 `1` 被当作 dead store 消掉。若 `p` 是「写 1 再写 2 才生效」的寄存器，语义直接错。
- `read_twice` 只剩一次 `ldr` 加 `lsl #1`（乘 2）—— 编译器假设两次读同一地址结果相同。若 `p` 是「读一次清一次」的数据寄存器，第二次值永远读不到。
- `vol` / `read_twice_vol` 各自保留全部两次访问。

所以规则是：**凡是地址指向硬件寄存器（而非普通 RAM），读写一律 `read_volatile` / `write_volatile`**，PAC crate 生成的寄存器访问已经这么做了，手写 `*(0x4000_0000 as *mut u32) = 1;` 是错的。反过来，对普通内存滥用 volatile 会阻止优化且**不提供任何原子性或同步语义**（这一点与 Java 的 `volatile` 同名不同义，见 [并发](/docs/CS/Rust/Concurrency.md)）。

## WebAssembly Targets

WASM 是最容易写错的一节，因为「WASM」不是一个目标。据 rustc book 的 platform support 页面（**未在本机实测，本机未安装任何 wasm target**）：

| 目标 | std | 能力 | 典型用途 |
| :-- | :-- | :-- | :-- |
| `wasm32-unknown-unknown` | ✓（但大量 API 不可用） | 原文：「`println!` does nothing, `std::fs` always return errors, `std::thread::spawn` will panic」；`core` 与 `alloc` 完整支持；**额外支持 `std` 的 `HashMap`**（但不随机化） | 浏览器 / JS 宿主，配 wasm-bindgen |
| `wasm32-wasip1` | ✓（基于 WASIp1 syscalls） | 导入 `wasi_snapshot_preview1`，可与 C/C++ 互操作，输出 core wasm module | Wasmtime / wasmtime-cli 等 WASI 运行时 |
| `wasm32-wasip1-threads` | ✓ | WASIp1 + 线程 | 需要线程的 WASI 场景 |
| `wasm32-wasip2` | ✓（原文 "supports std fully"） | 基于 Component Model 的 WASI 0.2，输出 **component** 而非 core module | Wasmtime 17+ |
| `wasm32v1-none` | **✗（只有 `core` + `alloc`）** | 不 import 任何宿主函数、不开任何 post-1.0 proposal | 最小 wasm、无宿主环境 |

关键区分，别混：

- **`wasm32-unknown-unknown` 不是 no_std**。它链的是真 `std`，只是 `std` 里依赖 OS 的部分被做成「返回错误的桩」。所以你能用 `String` / `Vec` / `HashMap`，但 `std::fs` 一定失败。这里 `no_std` 是一个**可选**的体积优化，不是必需。
- **`wasm32v1-none` 才是「必须 no_std」的那个**。原文明确「does not support std, only core and alloc」，理由也写得很直白：既然什么都不 import，任何用 OS 设施的 std 部分到最后都得做成失败桩，`unknown-unknown` 上那套桩的体验「was deemed not something worth repeating」。
- **`wasip1` / `wasip2` 有完整 std**，因为它们假定宿主提供 WASI syscall。要写 WASI CLI 程序（比如 `wasmtime foo.wasm`）用这两个，不要用 `unknown-unknown`。

`wasm-bindgen 0.2.129` 属于 `unknown-unknown` 那条路：它生成 JS 胶水代码，让 Rust 侧能直接调 DOM API。它本身是宿主侧的 std 工具链 + 过程宏，不是固件 crate。

## build-std and Custom Targets

为什么需要 `-Z build-std=core,alloc`：rustup 为每个 tier-1/2 目标分发**预编译好的** `libstd` / `libcore` / `liballoc`。裸机目标（`thumbv7em-none-eabihf` 等）没有预编译 std，因为它们没有 OS；而你自己写的 crate 如果 `panic = "abort"`，与预编译的 `panic = "unwind"` 版本不匹配——就是前文那个 `_rust_eh_personality` 未定义的实测错误。所以必须在**本地用指定 profile 重新编译标准库源码**，这就是 `-Z build-std`。

三个约束（**均为据文档，本机无 nightly，未实测**）：

1. `-Z build-std` 仍是 **nightly-only** 的 `-Z` flag，需要一个 nightly 工具链 + `rust-src` component。
2. 它必须与 `-Z build-std-features` / `panic = "abort"` 等 profile 设置配合使用，才能编出「不含 unwind 引用」的 `libcore` / `liballoc`。
3. 自定义目标（`-Z build-std` 的常见搭档）需要 target spec。这里与 [Edition 与 MSRV](/docs/CS/Rust/Edition_MSRV.md) 的记录接上：**1.95.0 起 JSON target spec 被去稳定化**，需要 `-Z unstable-options` 才能用，官方理由是「为 build-std 让路」。也就是说这两件事是同一个改造的两半：把「自定义目标」从 stable 命令行接口收回，好让 build-std 那套（JSON spec 是其输入格式）能自由演进。这是本文唯一一处「stable 上本来能用的东西被收回」的实例，与 Edition_MSRV 里那张「受控破坏」表是同一现象。

## Comparison with C and C++ Bare Metal

| 维度 | C / C++ `-nostdlib` freestanding | Rust no_std |
| :-- | :-- | :-- |
| 谁提供 `memcpy` / 软浮点运算 | 你要（`libgcc` / `compiler_builtins`） | **编译器自动带** `compiler_builtins`（实测链接命令行里可见 `libcompiler_builtins-*.rlib`） |
| 入口 | `_start`，自己写汇编或 C | `#[no_mangle] fn _start` / `cortex-m-rt` 的 `#[entry]` |
| 启动代码（`.data` 拷贝、`.bss` 清零） | 自己写 crt0 | `cortex-m-rt` 等启动 crate 做，**但仍是板级代码** |
| 链接脚本 | `-T linker.ld` | 同样需要（`memory.x` + `-C link-arg=-Tlink.x`） |
| 编译期能提供的保证 | 基本没有（UB 靠人） | **完整保留**：所有权、借用、类型系统、迭代器全在 `core` 里 |
| 堆 | 自己写 `sbrk` 或 `_malloc_r` | 实现 `GlobalAlloc` trait（有签名约束与安全契约） |
| 没有 libc 时 | 许多库直接不可用 | `libc` crate 只是**声明**，no_std 下照样能链（实测 MSRV 1.65） |
| 泛型 / 编译期抽象 | 宏或 C++ 模板 | trait + 泛型，**零运行时成本**，这是 HAL trait 层成立的前提 |

一句话概括差别：**C 裸机开发的难点是「运行时设施全缺」，Rust no_std 的难点是「运行时设施全缺但类型系统还在」**——后者既是负担（要补四件套）也是优势（HAL trait、状态机 async、无堆集合这些抽象在 C 里做不出来）。

## Pitfall Checklist

| # | 坑 | 现象 | 排查 / 解法 |
| :-- | :-- | :-- | :-- |
| 1 | `Vec` / `String` 不在作用域 | E0425 / E0433 `cannot find type Vec in this scope` | `extern crate alloc;` + `use alloc::vec::Vec;` |
| 2 | `format!` 不在作用域 | `error: cannot find macro format in this scope` | `use alloc::format;` |
| 3 | `Box<dyn Error>` 不在作用域 | E0425 | 用 `alloc::boxed::Box`，或改自定义错误枚举 |
| 4 | 忘了 `#[panic_handler]` | `error: #[panic_handler] function required, but not found` | 只在可执行 crate 需要；lib 不用管 |
| 5 | 用了 `alloc` 但没给分配器 | `no global memory allocator found but one is required` | 加 `#[global_allocator]`（仅 bin 报；lib 链接前不报） |
| 6 | 两个分配器 / 两个 panic handler | `cannot define multiple global allocators` | 全依赖图只能一份，放到 BSP 层 |
| 7 | `panic = "abort"` 但仍缺 `_rust_eh_personality` | 链接期 Undefined symbol（实测来自 `liballoc`） | 真解是 `-Z build-std`；宿主 hack 是补空符号 |
| 8 | 写了 `fn main` | `error: using fn main requires the standard library` | `#![no_main]` + `#[no_mangle]` 入口 |
| 9 | 依赖树里某个 crate 拉回 std | 宿主上**编译照样通过**；交叉到裸机才炸 | `cargo tree -f "{p} {f}"` 查 `default,std`；依赖写 `default-features = false`；**用 `cargo build --target <裸机triple>` 验证** |
| 10 | 自定义入口的旧写法 | E0557 `feature has been removed ... removed in 1.86.0` | `#![feature(start)]` 已移除，改用 `#[no_mangle]` 入口 |
| 11 | 手写寄存器读写 | 值不对 / 访问被优化掉（实测 dead store 消除） | 一律 `core::ptr::read_volatile` / `write_volatile` |
| 12 | 无 FPU 的 MCU 上用浮点 | 链接到不存在的硬件浮点指令 | 据文档：确认 target 的 ABI（`eabi` vs `eabihf`）与 softfloat 支持；**未在裸机实测** |
| 13 | 以为 `HashMap` 在 `alloc` | 找不到 | 它在 `std`（`RandomState` 依赖 std） |
| 14 | 以为 `wasm32-unknown-unknown` 必须 no_std | 白费功夫 | 它有 std，只是 fs/net 是失败桩；必须 no_std 的是 `wasm32v1-none` |
| 15 | 用已 yanked 的版本 | 构建失败或解析到旧版 | 例：`critical-section` 1.3.0 已 yanked，最新可用为 1.2.0 |

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Languages](/docs/CS/Languages.md)
- [ELF](/docs/CS/Compiler/ELF.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)

## References

- [The Rust Standard Library — `core`](https://doc.rust-lang.org/core/index.html)
- [The Rust Standard Library — `alloc`](https://doc.rust-lang.org/alloc/index.html)
- [The Rust Standard Library — `std`](https://doc.rust-lang.org/std/index.html)
- [The Rustonomicon — Panic Handler and Lang Items](https://doc.rust-lang.org/nomicon/panic-handler.html)
- [`core::alloc::GlobalAlloc`](https://doc.rust-lang.org/core/alloc/trait.GlobalAlloc.html)
- [`core::ptr::read_volatile`](https://doc.rust-lang.org/core/ptr/fn.read_volatile.html)
- [The rustc book — Platform Support](https://doc.rust-lang.org/rustc/platform-support.html)
- [The rustc book — `wasm32-unknown-unknown`](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html)
- [The rustc book — `wasm32-wasip1`](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip1.html)
- [The rustc book — `wasm32-wasip2`](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip2.html)
- [The rustc book — `wasm32v1-none`](https://doc.rust-lang.org/rustc/platform-support/wasm32v1-none.html)
- [The rustc book — Custom Targets (target spec JSON)](https://doc.rust-lang.org/rustc/targets/custom.html)
- [The Cargo Book — Unstable Features (`build-std`)](https://doc.rust-lang.org/cargo/reference/unstable.html)
- [The Cargo Book — Profiles (`panic`)](https://doc.rust-lang.org/cargo/reference/profiles.html)
- [The Embedded Rust Book — A no_std Rust Environment](https://docs.rust-embedded.org/book/intro/no-std.html)
- [The Embedonomicon — The smallest no_std program](https://docs.rust-embedded.org/embedonomicon/smallest-no-std.html)
- [docs.rs — embedded-hal 1.0.0](https://docs.rs/embedded-hal/1.0.0/embedded_hal/)
- [docs.rs — heapless 0.9.3](https://docs.rs/heapless/0.9.3/heapless/)
- [docs.rs — cortex-m 0.7.9](https://docs.rs/cortex-m/0.7.9/cortex_m/)
- [docs.rs — critical-section 1.2.0](https://docs.rs/critical-section/1.2.0/critical_section/)
- [docs.rs — embassy-executor 0.10.0](https://docs.rs/embassy-executor/0.10.0/embassy_executor/)
- [docs.rs — defmt 1.1.1](https://docs.rs/defmt/1.1.1/defmt/)
- [defmt — the deferred formatter](https://defmt.ferrous-systems.com/)
- [probe-rs](https://probe.rs/)
- [docs.rs — postcard 1.1.3](https://docs.rs/postcard/1.1.3/postcard/)
