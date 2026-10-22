## Introduction

`extern "C"` 是 Rust 安全边界上最锋利的一段：跨过去之后，对端的编译器根本不知道 Rust 的不变式存在，它只按 C 的 ABI 摆字节。FFI 的全部工作因此可以概括成一句话 —— **把 Rust 侧的类型契约，翻译成对端语言能执行的形式**：谁分配、谁释放、谁能穿过、panic 谁接、布局由谁承诺。

语言内部的 `unsafe` 语义（UB 清单、provenance、别名模型）归 [Unsafe](/docs/CS/Rust/Unsafe.md)；两篇的枢纽是 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。本文只讲**语言之间**的那条线。

本文版本归属与诊断文本以 **rustc 1.98.1 (48a229cea 2026-09-01)、`aarch64-apple-darwin`** 实测为准；标"自 1.99.0 起"的条目来自 release notes 史页，同时给出它在 1.98.1 上的 E0658 互证。

## Choosing an extern ABI

| ABI | 语义 | 何时用 |
| :--- | :--- | :--- |
| `"Rust"`（默认） | 编译器私有的名字修饰与调用约定，未文档化 | 永不出 crate 边界；见 [编译过程](/docs/CS/Rust/compile.md) |
| `"C"` | 目标平台的 C 调用约定（本机即 AAPCS64 + Darwin 补丁） | 绝大多数 FFI；panic 穿越 = abort |
| `"system"` | "系统 API 用的约定"（Windows 32 位为 `stdcall`，其余等于 `"C"`） | Win32 API；变参声明 1.93.0 才放开 |
| `"C-unwind"` 等 `*-unwind` 家族 | 同 `"C"` 的字节布局，但允许异常穿过 | 对端 C++ 会抛，或 Rust 要向上游 unwind（1.71.0，2023-07-13） |
| 具名平台 ABI（`"sysv64"` / `"win64"` / `"aapcs"` / `"efiapi"`） | 写死某个约定 | 跨平台手写汇编 / 裸机 |

ABI 是**类型的一部分**，把 Rust 函数赋给 `extern "C"` 指针直接编译失败；写了对当前目标不存在的 ABI 同样是编译期错误（本机 `aarch64-apple-darwin`）：

```text
fn rust_fn() {} let p: extern "C" fn() = rust_fn;
error[E0308]: mismatched types  ... expected "C" fn, found "Rust" fn
error[E0570]: "sysv64" is not a supported ABI for the current target
```

unwind 的选择不是"要不要检查"，而是**谁负责终止**：`extern "C"` 声明的函数对 Rust 而言"不会 unwind"，这才是 `catch_unwind` 抓不到 C++ 异常的根本原因。1.71.0 引入 `*-unwind` 家族的意义即**同一套字节布局，两种异常传播假设**；本机实测 `extern "C-unwind"` 的定义与声明都可用，panic 能被正常接住（输出见 [Unsafe](/docs/CS/Rust/Unsafe.md)）。

## Which Types May Cross the Boundary

| 类别 | 依据 |
| :--- | :--- |
| 整数 / 浮点 / `std::ffi::{c_char, c_int, c_void, ...}` 别名 | 平台 C 类型的稳定包装；`char` ↔ C `uint32_t` 的 ABI 对应关系自 1.76.0 起被文档化 |
| `usize` ↔ C `size_t` | 同上；注意 `std::ffi::c_size_t` **仍 unstable**（1.98.1 实测 E0658，gate `c_size_t`，issue #88345），所以 `size_t` 位置就写 `usize` |
| 裸指针 / `NonNull<T>` / `Option<&T>` / `extern "C" fn(..)` | 单机器字；`Option` 走空指针 niche（`mem::size_of` 文档级保证），所以 `NULL` 恰好等于 `None` |
| `#[repr(C)]` 结构体、`#[repr(transparent)]` 新类型指针 | 布局与 ABI 显式冻结，见 [内存布局](/docs/CS/Rust/Memory_Layout.md) |

不该穿越的：`String` / `Vec<T>` / `HashMap`（Rust 私有布局）、任何 `Drop` 类型（谁析构说不清）、胖指针（`&[T]`、`&dyn Trait` 两个机器字的**顺序与语义**都不被 C 承认，必须自己拆成 `ptr + len`）、未标 `repr(C)` 的 `enum`（1.97.0 起更明确：不能对无布局保证的 enum 做假设）、`!`。这正是 Rust 与 C++ 的共识差异 —— C++ 靠 ABI 惯例把类对象传来传去，Rust 靠 `#[repr(C)]` 显式声明。

`repr(C)` 之外还有两级渐弱的承诺：`repr(transparent)` 保证新类型与其唯一非零字段布局一致（1.98.0 起对"平凡字段"的判定收紧，`repr(C)` 类型、私有字段类型、`#[non_exhaustive]` 类型不再算平凡）；`#[non_exhaustive]` 则让对端**无法穷尽构造**你的类型，是唯一能在不加字段时破坏"布局兼容"的手段 —— 加字段会改变布局，跨版本编译的两侧必然对不上，所以 FFI 边界的结构体要么冻结，要么留不透明。

## C-variadic Declarations and Definitions

C 变参在 Rust 里**声明与定义分两次稳定**，是最容易写错版本号的条目：

| 阶段 | 稳定版本 | 说明 |
| :--- | :--- | :--- |
| 声明（`extern "C" { fn printf(fmt: *const c_char, ...) -> c_int; }`） | **1.91.0** (2025-10-30) | release notes 原文："can be declared in `extern` blocks but not defined"，覆盖 `sysv64` / `win64` / `efiapi` / `aapcs` |
| 声明 for `"system"` ABI | **1.93.0** (2026-01-22) | 补上 Windows 那条路 |
| **定义**（`unsafe extern "C" fn f(n: i32, args: ...) -> i32`） | **1.99.0** (2026-10-01) | `...` 的类型是 `core::ffi::VaList`（与各目标 C 的 `va_list` ABI 兼容）；能读什么类型由 `VaArgSafe` trait 把关（`i32`/`f64`/裸指针可，`i8`/`f32` 因默认提升不可） |
| `#[unsafe(naked)]` + C 变参 | **1.99.0** | 让裸函数自己实现 `va_start` 类原语 |

本机 1.98.1 上"声明可、定义不可"，两份输出互证。为什么允许声明却不允许定义：声明只需承认**调用约定**（变参在多数 ABI 下靠 `al` / `x8` 之类寄存器记数），定义却要真的构造平台相关的 `va_list` 游标 —— 每个 ABI 一套，测试矩阵完全不同；这与 C 的处境一致，`va_start` 从来是实现提供的。

```text
error[E0658]: C-variadic functions are unstable  ... see issue #44930
error[E0658]: use of unstable library feature `c_variadic`: the `c_variadic` feature has not been properly tested on all supported platforms
```

## Opaque Handles and Layout Contracts

C 侧最常见的形状是不透明句柄：给你一个指针，只能经由函数用它。Rust 侧的要点是**类型导出、布局不导出**：

```rust
#![allow(dead_code)]
use std::cell::UnsafeCell;
use std::ffi::c_int;
use std::ptr::NonNull;
pub struct Context(UnsafeCell<Inner>);             // 字段私有 => 布局对外不可见
struct Inner { table: Vec<c_int> }                 // 内部仍是 Rust 类型，随便重排
#[unsafe(no_mangle)]
pub extern "C" fn context_first(ctx: *mut Context) -> *const c_int {
    let cell = match NonNull::new(ctx) {           // 空指针契约在这一处集中兑现
        None => return std::ptr::null(),
        Some(p) => unsafe { &p.as_ref().0 },
    };
    unsafe { (*cell.get()).table.as_ptr() }
}
```

三条纪律：句柄参数用 `*mut Context` 而**不是** `&mut Context`（引用意味着"非空 + 独占 + 生命周期由 Rust 定"，对端 C 三条都给不了，先 `NonNull::new` 再转）；`pub fn` 暴露私有类型会撞 `private_interfaces`（实测 `type 'Handle' is more private than the item 'handle_new'`），所以不透明类型要 `pub struct` 且字段私有；需要"新类型与指针 ABI 完全一致"时用 `#[repr(transparent)]` 包非空指针。

## Symbol Visibility and Mangling

默认的 `"Rust"` ABI 意味着**符号名与调用约定都不稳定**：`.rlib` / `.so` 不能跨编译器版本复用，更不能当稳定接口。要导出给 C 的符号必须两件事一起做：

```rust
#[unsafe(no_mangle)]                                 // edition 2024 起 unsafe attribute
pub extern "C" fn api_version() -> u32 { 3 }
```

- `#[unsafe(no_mangle)]` 关掉名字修饰（edition 2024 起必须显式写 `unsafe`，1.82.0 的收紧）；自 1.99.0 起**泛型项不能再 `no_mangle`**，因为单态化会造出多个同名符号。
- `#[export_name = "..."]` 在需要精确控制符号名时替代它；`#[link_section = "..."]` 把函数/变量放进指定节（裸机入口、启动元数据）。
- 符号还受 `-C visibility` 与链接器脚本影响：默认可见性对动态库是"导出"，对静态库是"隐藏"；跨 `.so` 边界的 Rust 类型仍走 C ABI 的那部分保证。
- 反向的入口是 `unsafe extern "C" { ... }` 声明块：函数默认 `safe`（调用仍需 `unsafe` 块，因为契约在文档），`static` 与 `static mut` 的声明仍允许（见 [Unsafe](/docs/CS/Rust/Unsafe.md)）。

链接层面的完整账（`cargo:rustc-link-lib`、`cargo:rustc-link-search`、`#[link]` 属性、符号解析顺序）归 [编译过程](/docs/CS/Rust/compile.md) 与 [Cargo](/docs/CS/Rust/Cargo.md)。

## Three Ownership Contracts Across the Edge

| 契约 | Rust 侧写法 | C 侧义务 | 失败模式 |
| :--- | :--- | :--- | :--- |
| **借用** | `*const T` / `*mut T` | 调用返回前用完，不保存、不释放 | 悬垂读 |
| **移交** | 构造函数返回 `Box::into_raw`；配套 `*_free` 做 `Box::from_raw` | 恰好释放一次，且只能用配套函数 | 泄漏 / double free |
| **回调归还** | C 把指针交回 Rust 的 `extern "C" fn`，Rust 侧 `Box::from_raw` 收回 | 回调返回后不得再用该指针 | use-after-free |

移交型的标准形状（本机实际跑过：`handle_free(handle_new(7))` 打印 `Handle 7 dropped`）：

```rust
#![allow(dead_code)]
#[derive(Default)]
struct Handle(usize);
impl Drop for Handle { fn drop(&mut self) { println!("Handle {} dropped", self.0); } }
#[unsafe(no_mangle)]
pub extern "C" fn handle_new(seed: usize) -> *mut Handle {
    Box::into_raw(Box::new(Handle(seed)))           // 交出所有权，Rust 不再析构
}
#[unsafe(no_mangle)]
pub extern "C" fn handle_free(h: *mut Handle) {
    if !h.is_null() { unsafe { drop(Box::from_raw(h)); } }   // 重新拥有 => Drop 由 Rust 跑
}
```

`Box::from_raw` 的三个前置条件：这块内存当初由 `Box::new` 产生、布局完全一致、没有任何其他指针还在用它。少一条就是 UB，而编译器**什么都不会说**。**1.99.0 反转了 `Box::leak` 的推荐用法**，是本主题最新的口径变化：过去"把所有权交给 FFI"常写成 `Box::leak` 拿 `'static` 引用再取指针，现在官方文档改为**不推荐之后再回收这块内存**，理由是自定义分配器（`allocator_api`）即将稳定，而 `leak` 丢掉了分配器信息、之后可能落回错误的分配器。正解是 `Box::into_raw`（需要非空时配 `Box::into_non_null`）；同批稳定的还有 `Box::from_non_null` 与 `Vec::into_parts` / `Vec::from_parts`。1.98.1 上它们共享一个 gate（实测细节：`Vec::into_parts` 返回 `(NonNull<T>, len, cap)` 三元组）：

```text
error[E0658]: use of unstable library feature `box_vec_non_null`  ... see issue #130364
```

要"给出去所有权但不让 Rust 析构"，用 `ManuallyDrop` + 显式 `ptr::drop_in_place`（语义同上但少了"这块内存属于 Box"的隐含前提）；`mem::forget` 会连内存一起留下，差别归 [Drop](/docs/CS/Rust/Drop.md)。最后一颗雷是**跨分配器**：C 的 `malloc` 内存必须用 C 的 `free` 释放，`Box::from_raw` 走的是 Rust 全局分配器（默认系统分配器，`#[global_allocator]` 可换）—— 见 [malloc](/docs/CS/C/malloc.md) 与 [内存管理](/docs/CS/memory/memory.md)。

## Callbacks and User Data

C 的回调没有词法作用域，所以 Rust 闭包**不可能**直接当回调（捕获的上下文没有地方放）。可穿越的只有 `extern "C" fn`，上下文靠 user data 指针带：

```rust
#![allow(dead_code)]
use std::ffi::c_int;
extern "C" fn print_cb(i: usize, v: c_int) { println!("cb[{i}] = {v}"); }
#[unsafe(no_mangle)]
pub extern "C" fn each(arr: *const c_int, len: usize, mut cb: Option<extern "C" fn(usize, c_int)>) {
    if arr.is_null() || cb.is_none() { return; }    // NULL 回调 = None
    for i in 0..len {
        let v = unsafe { *arr.add(i) };
        if let Some(f) = cb.as_mut() { f(i, v); }
    }
}
pub fn demo(d: &[c_int]) { each(d.as_ptr(), d.len(), Some(print_cb)); }
```

契约要点：user data 是 `*mut c_void`，Rust 侧收回时 `&*(ud as *const T)`（要求它仍被 C 拥有）与 `Box::from_raw`（要求 Rust 收回所有权）对"谁让它活着"的要求不同；回调若被 C **跨线程**调用，捕获类型的 `Send`/`Sync` 论证落回你自己头上（[并发](/docs/CS/Rust/Concurrency.md)）；回调里 panic 走 `extern "C"` 的 abort 路径，除非两侧都声明 `*-unwind`。

## Naked Functions and no_std Entrypoints

`no_std` 目标上 `unsafe` 的密度陡增：没有 `std` 就没人替你写 `#[panic_handler]`、全局分配器与启动代码（最小形状见下面第二块）。需要完全控制序言 / 结语时用 naked 函数（**1.88.0**，2025-06-26 稳定 `naked_functions`；属性必须写 `#[unsafe(naked)]`，体内只能 `core::arch::naked_asm!` —— 实测三条边界：裸 `#[naked]` 在 edition 2024 报 `unsafe attribute used without unsafe`；体内用 `asm!` 报 `error[E0787]: the 'asm!' macro is not allowed in naked functions`，诊断直接提示换 `naked_asm!`；naked + C 变参自 1.99.0 起可用）：

```rust
#![allow(dead_code)]
use core::arch::naked_asm;
#[unsafe(naked)]
pub unsafe extern "C" fn twice(_x: u32) -> u32 {
    naked_asm!("add w0, w0, w0", "ret");            // aarch64-apple-darwin
}
```

```rust
#![no_std]
#![allow(dead_code)]
#[panic_handler]
fn ph(_: &core::panic::PanicInfo) -> ! { loop {} }
#[unsafe(no_mangle)]
pub extern "C" fn entry(x: u32) -> u32 { x.wrapping_mul(2) }
```

`no_std` 全景（异常处理、`alloc`、BSP crate）见 [No_Std](/docs/CS/Rust/No_Std.md)；内联汇编语法与链接阶段见 [编译过程](/docs/CS/Rust/compile.md) 与 [ELF](/docs/CS/Compiler/ELF.md)。

## Tooling: bindgen, cxx, corrosion, miri

工具的目标只有一个：**把 `unsafe` 压到边界上，让人审契约而不是审代码**。

| 工具 | 层次 | 定位 | 现状（2026-10 查证） |
| :--- | :--- | :--- | :--- |
| `bindgen` | C → Rust | 读头文件生成 `extern` 声明与 `repr(C)` 结构 | 0.73.2 (2026-09-08) |
| `cbindgen` | Rust → C | 从 Rust 源码生成 C 头文件 | 0.29.4 (2026-06-09) |
| `cxx` | C++ ↔ Rust | 双向代码生成，类型两侧同时可见 | 1.0.202 (2026-09-12) |
| `corrosion` | 构建系统 | CMake 集成 Rust crate；**不是 crates.io crate**，同名 crate 是无关项目 | GitHub 活跃 |
| `wasm-bindgen` | Rust ↔ JS | 浏览器里的"FFI"，不走 C ABI（`extern "C"` 在 wasm32 目标 1.89.0 起才是标准 ABI） | 0.2.129 (2026-09-25) |
| `miri` | 校验 | 解释执行，查别名 / provenance / 越界 / 泄漏 / 无效值 | **只能装在 nightly** |
| `cargo-fuzz` / `cargo-vet` | 供应链 | 前者给 `unsafe` 边界喂随机输入，后者审计依赖里谁放了 `unsafe` | 长期在用 |

miri 是唯一能**机器验证**别名与 provenance 的工具，但 stable 装不上（实测原文）。两个能力边界要说清：miri 只跑 **Rust** 代码，`extern "C"` 声明的外部函数不会真执行（要么手写桩，要么当黑盒）；它检查的别名模型是**某个具体提案**（Stacked Borrows），通过不等于未来编译器一定认可。`build.rs` + `bindgen` 的构建期契约见 [Cargo](/docs/CS/Rust/Cargo.md) 与 [工具链](/docs/CS/Rust/Tooling.md)；任务清单里提到的 `tibc`（宣称做 ABI-safe 的 Rust↔C 异步 FFI）本机在 crates.io 与 GitHub 仓库搜索里**均无命中**，版本与维护状态未能核实，故不列入推荐。

### bindgen Details

`bindgen` 的默认输出不是"可放心调用的 Rust 代码"，而是一份**忠实转录**：C 的每个函数、每个字段、每个宏常量都变成 Rust 项，类型能推则推、不能推就 `c_void` 占位。几个日常开关要知道：

- `--allowlist-function` / `--allowlist-type` / `--blocklist-item`：按符号白/黑名单裁剪输出，是控制体积与编译时长的主要手段。
- `--no-derive-debug` / `--no-partialeq`：别让生成码替你 derive 一堆东西（`repr(C)` 类型 derive `PartialEq` 是安全的，derive `Hash` 可能按指针走）。
- `--rustified-enum`：把 C 枚举转成 Rust `enum`（**只在确认 tag 值域有限且不增时才安全**，否则留 `repr(C)` 常量）。
- `bindgen::Builder::generate_cstr_literals`、`--generate-cstr` 一类的开关控制 `&[u8; N]` 与 `&CStr` 的取舍；回调参数默认转成 `Option<extern "C" fn>`。
- 布局稳定性靠 `tests/layout.rs`：bindgen 会生成编译期 `static_assert` 风格的尺寸/偏移测试，C 头文件改了就编译失败 —— 这是它最有价值的部分。

### cxx Details

`cxx` 解决的是 bindgen 的反方向问题：**双向**。C++ 侧定义一个 `#[cxx::bridge]` 生成的模块，两侧用同一套类型（`SharedPtr<T>`、`UniquePtr<T>`、`String`、`Vec<T>`、`rust::String` 等）互相调用，所有权由生成的桥接代码保证。代价是**双方都必须用 cxx 的类型词汇表**：不能直接把任意 C++ 类对象传过去，只能传它认识的少数类型加不透明句柄。它的真正价值在 C++ 项目里**渐进引入 Rust**：先桥一个模块，再逐步蚕食。对纯 C 项目，bindgen + 手写薄封装通常更轻。

### What to Hand-Write Anyway

工具能替你翻译签名，但翻译不了**契约**。无论用不用 bindgen/cxx，这几处永远手写：错误码到 `Result` 的映射、空指针与哨兵值的集中处理、生命周期边界的注释（`# Safety` 段）、以及"这个指针借多久"的注释。工具让边界变窄，不让人变轻松。

## Comparison with C and C++ Discipline

| 问题域 | C | C++ | Rust |
| :--- | :--- | :--- | :--- |
| 释放内存 | 手动 `free`，漏 / 重 / 悬垂全靠自律 | RAII + 智能指针，仍有裸 `new`/`delete` | 所有权 + `Drop`；手动只在 `unsafe` 里 |
| 越界 | 语言不检查，靠 ASan / Valgrind 事后抓 | 同 C，`.at()` 只换成异常 | safe 层索引 panic；`unsafe` 的 `p.add(n)` 无从检查 |
| 类型双关 | `memcpy` 或 `union`（严格别名例外） | `std::memcpy` / `std::bit_cast` | `transmute`（尺寸编译期核对）/ `MaybeUninit` / `&raw` |
| 未初始化读 | 垃圾值，通常"能跑" | 同 C | **immediate UB**（1.65.0），必须 `MaybeUninit` |
| 别名前提 | `restrict` 手工声明 | `const` 只是局部约定 | 借用检查强制；`unsafe` 里靠 lint + miri 兜一部分 |
| 异常穿越边界 | 不适用 | `noexcept` 里抛 → `terminate` | `extern "C"` 里 panic → abort（drop glue 先跑）；要 unwind 用 `"C-unwind"` |
| 事后诊断 | ASan / UBSan / Valgrind | 同 + MSVC `/fsanitize=address` | miri（nightly）+ 地址消毒器（`-Zsanitizer`，unstable） |
| 契约放在哪 | 注释与约定 | 头文件 + 约定 | `unsafe fn` 签名 + 文档 Safety 段 + 编译器能报的那部分 |

最后一行是全部差别的根源：C/C++ 的 UB 治理在**运行期与工具期**（ASan 抓一次是一次的样本），Rust 的治理在**编译期与契约期** —— safe 层把 UB 挡在外面，`unsafe` 把契约写进签名，FFI 再把契约翻译成对端语言能执行的形式：谁分配、谁释放、谁能穿过、panic 谁接。于是"这段 `unsafe` 安全吗"从来不是编译器能答的问题，而是"你对端的调用约定、生命周期与释放责任，能否写成三行可被审计的句子"。

## Beyond C: Other Language Targets

`extern "C"` 是 Rust 事实上的通用 FFI 层，但各宿主语言会再包一层自己的约定：

| 对端 | 常用方案 | 边界形态 |
| :--- | :--- | :--- |
| C / C++ | `bindgen` / `cxx` / 手写 `extern` 块 | C ABI，本文主体 |
| Python | `PyO3`、`maturin` | CPython 对象 + GIL 约定；返回类型走 PyObject 转换 |
| Node.js | `napi-rs`、`neon`（历史） | N-API 值，跨 V8 版本稳定 |
| Ruby | `magnus`、`rutie`（历史） | CPython 式对象 + GC 句柄 |
| Java | `jni` crate、`jni-rs` | JNI 局部/全局引用，`JNIEnv` 线程绑定 |
| .NET | 原生互操作 `[DllImport]` | 反向：C# 调 Rust 导出 |
| 浏览器 | `wasm-bindgen` | **不走 C ABI**，传的是 JS 值，见 [WASM](/docs/CS/Rust/WASM.md) |

共同模式：**每层封装都在替你做"把宿主语言的自动管理翻译成 C ABI 能表达的东西"**，代价是每个边界都有自己的借用与生命周期规则（GIL、JNI 局部引用表、N-API 句柄作用域）。选封装层的判据与普通依赖一致：MSRV、维护活跃度、边界规则的文档质量 —— 方法论见 [生态选型](/docs/CS/Rust/Ecosystem.md)。

## A Checklist for the C-ABI Edge

把上面各节压成一份过边界前的检查清单：

1. **ABI 写明了吗** —— 每个跨边界函数都是 `extern "C"` 或显式平台 ABI，没有裸 `extern`。
2. **布局承诺了吗** —— 结构体 `#[repr(C)]`，不透明类型字段私有，跨版本变更走新增函数而非改结构。
3. **指针契约是三条中的哪条** —— 借用 / 移交 / 回调归还，写进 `# Safety` 段，并对空指针集中处理。
4. **分配器对上了吗** —— Rust 分配的内存用 `Box::from_raw` 类回收，C 分配的用 C 的 free，不混用。
5. **panic 想好去哪了吗** —— 默认 abort；要穿越用 `*-unwind`，且两侧一致。
6. **回调有 user data 吗** —— 闭包不能过边界；`Send`/`Sync` 论证自己写。
7. **符号稳定吗** —— `#[unsafe(no_mangle)]` 而非默认 mangling；泛型项不能导出。
8. **工具跑过吗** —— bindgen 布局测试在 CI 里，miri 跑 safe+unsafe 混合代码，fuzz 给边界喂输入。

## Links

- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)
- [Cargo](/docs/CS/Rust/Cargo.md)
- [WASM](/docs/CS/Rust/WASM.md)
- [未定义行为（C）](/docs/CS/C/UB.md)

## References

1. [FFI chapter of the Rustonomicon](https://doc.rust-lang.org/nomicon/ffi.html)
2. [The Rust Reference — External blocks](https://doc.rust-lang.org/reference/items/external-blocks.html)
3. [The Rust Reference — ABI, calling conventions and attributes](https://doc.rust-lang.org/reference/abi.html)
4. [bindgen User Guide](https://rust-lang.github.io/rust-bindgen/)
5. [cxx Book](https://cxx.rs/)
6. [Rust Release Notes](https://doc.rust-lang.org/stable/releases.html)
