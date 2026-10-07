## Introduction

`unsafe` 常被说成"关掉安全检查的开关"，这个比喻是错的。它只给你五件事：**允许写下那五种编译器无法替你证明、但语义合法的操作**。借用检查、类型检查、生命周期、`static mut` 取引用禁令在 `unsafe` 块里**照旧工作**；被关掉的只是"编译器替你兜底"，同时**契约的责任过户给你**。所以 `unsafe` 代码的正确性不写在类型里，而写在文档前置条件里 —— 它是**契约边界**，不是免死金牌。`extern "C"` 是这条边界最锋利的一段：跨过去之后对端的 C 编译器根本不知道 Rust 的不变式存在，它只按 C 的 ABI 摆字节。本文先讲语言内边界（能力清单、UB 清单、provenance、`MaybeUninit`、`static mut`、edition 2024），再讲语言间边界（ABI、可穿越类型、所有权契约、回调、变参、工具链）。

未定义行为本身不重述 —— 本库已有 [C 的未定义行为](/docs/CS/C/UB.md)（"标准不施加要求 → 优化反噬"）与 [C++ 的未定义行为](/docs/CS/C++/UB.md)（"零成本换来的责任过户"）两篇口径，本文只做**对照**。布局与 niche 归 [内存布局](/docs/CS/Rust/Memory_Layout.md)；`Rc`/`Arc`/`Cell` 的安全 API 层归 [智能指针](/docs/CS/Rust/Smart_Pointers.md)；panic 与 `catch_unwind` 归 [错误处理](/docs/CS/Rust/Error_Handling.md)；数据竞争与 `Send`/`Sync` 归 [并发](/docs/CS/Rust/Concurrency.md)；符号 mangling 与链接归 [编译过程](/docs/CS/Rust/compile.md)；`no_std` 全景归 [No_Std](/docs/CS/Rust/No_Std.md)。本文版本归属与诊断文本以 **rustc 1.98.1 (48a229cea 2026-09-01)、`aarch64-apple-darwin`** 实测为准；标"自 1.99.0 起"的条目来自 release notes 史页，本机复现不出来 —— 同时给出它在 1.98.1 上的 E0658，两者互证。

## What an unsafe Block Actually Grants

`unsafe` 上下文（显式 `unsafe { }` 块，或 `unsafe fn` 的函数体）额外解锁的操作只有五类：

| 能力 | 典型写法 | 为什么编译器不能替你证明 |
| :--- | :--- | :--- |
| 解引用裸指针 | `*p`、`p.read()`、`slice::from_raw_parts` | 可能为空、悬垂、未对齐、越界 |
| 调用 `unsafe fn` | `libc_free(ptr)`、`extern` 块里的任何函数 | 前置条件写在文档，类型系统看不见 |
| 访问 / 修改 `static mut` | `unsafe { COUNTER += 1 }` | 线程间写写冲突与引用别名 |
| 实现 `unsafe trait` | `unsafe impl Send for W {}`、`GlobalAlloc` | trait 不变式不由方法签名保证 |
| 访问 `union` 字段 | `u.a` | 只有当前存活字段是合法位模式 |

```rust
#![allow(dead_code)]
static mut COUNTER: usize = 0;
union U { a: u32, b: f32 }
unsafe trait Marker {}
struct S(u32); unsafe impl Marker for S {}         // 能力 4
unsafe fn mark(x: &u32) -> u32 { *x }
fn five(p: *const u32, x: &u32) -> u32 {
    unsafe {
        let a = *p; let b = mark(x);               // 能力 1、2
        COUNTER += 1;                              // 能力 3
        let u = U { b: 1.0f32 };
        a + b + u.a                                // 能力 5
    }
}
```

这五类正是官方 UB 清单的全部入口（清单见 Reference 里的 Behavior considered undefined）。缺 `unsafe` 时的诊断 E0133 会**直接点名后果**：

```text
error[E0133]: use of mutable static is unsafe and requires unsafe function or block
  = note: mutable statics can be mutated by multiple threads: aliasing violations or data races will cause undefined behavior
```

## What unsafe Does Not Turn Off

把借用冲突写进 `unsafe` 块，编译器照报 —— 这是"unsafe 不关闭借用检查"这个误解最省事的反例。同类"以为关掉了其实没关"的三处也全部实测：普通引用的不变式照旧（`&T` 仍必须非空、对齐、生命周期内不被并发改写，`unsafe` 只是允许你**伪造**它，而一旦伪造出来，全库都按它合法来推理，这正是 `&raw const` 存在的理由）；`transmute` 的尺寸检查在编译期，不是"运行时可能出错"而是根本不生成代码；`union` 不许有非 `Copy` 字段，因为编译器无法替你插入析构。

```text
fn alias(x: &mut u32) { unsafe { let a = &*x; let b = &mut *x; *b += *a; } }
error[E0502]: cannot borrow `*x` as mutable because it is also borrowed as immutable

fn t(x: u32) -> u64 { unsafe { std::mem::transmute(x) } }
error[E0512]: cannot transmute between types of different sizes, or dependently-sized types

union Bad { s: String }
error[E0740]: field must implement `Copy` or be wrapped in `ManuallyDrop<...>` to be used in a union
```

结论：`unsafe` 的作用面精确等于那五类操作，其余语义一概不变。真正的代价是**推理负担** —— 块内的错误编译器不报，只在 miri 或线上崩溃时暴露。

## The Rust UB List, Compared with C and C++

Rust 的 UB 条目与 C/C++ 高度同源，差别在**分布**：C 的每一行都可能在 UB，Rust 的 safe 代码原则上不可能（前提是所有经手的 `unsafe` 守约）。

| Rust UB 条目 | 与 [C/UB](/docs/CS/C/UB.md) 的关系 | 与 [C++/UB](/docs/CS/C++/UB.md) 的关系 | safe 层能否触发 |
| :--- | :--- | :--- | :--- |
| 引用别名违反（`&T` 与 `&mut T` 同时活跃） | C 的 strict aliasing 在"类型"层，Rust 收到"权限"层 | 同 C，仅 `std::launder` 等补丁 | 否 |
| `&mut` 区间重叠 | 对应 C 的 `restrict` 手工声明 | 无对应保证 | 否 |
| 无效值违反类型不变式（`bool`≠0/1、`char` 越界、`&T` 为空、枚举 tag 越界、`NaN` 逃进 `Ord`）、`transmute` 不变式不符 | C 无"类型不变式"概念，位模式一律合法 | 部分 enum 有底层约束，仍弱得多；`std::bit_cast` 有同等尺寸检查 | 否 |
| 越界读写、悬垂解引用、读未初始化 | C 里"值不确定"，多数平台能用 | 同 C，另加迭代器失效 | 否（索引 panic；未初始化须 `MaybeUninit`） |
| 数据竞争 | C11 / C++11 内存模型同源 | 同 | 否（`Send`/`Sync` 挡在编译期） |
| `panic` 穿越 `extern "C"` | 不适用 | 同构于 `noexcept` 里抛异常 → `terminate` | **是**，safe API 能踩到的少数之一 |
| 指针丢失 provenance | C 只写成实现定义 | 同 C | 否，但 `unsafe` 里极易写出 |

未初始化这一条 Rust 明确加强过 —— release notes 1.65.0（2022-11-03）原文："**Uninitialized integers, floats, and raw pointers are now considered immediate UB.** Usage of `MaybeUninit` is the correct way to work with uninitialized memory." "immediate" 意为**读到即错、不必用到那个值**：C 里读未初始化通常只是垃圾值，Rust 里它是让 miri 报错、让优化合法删除分支的 UB。

编译器还替你钉死了别名类的 UB（`invalid_reference_casting` 自 clippy 提升于 1.72.0，1.73.0 起 deny-by-default），但只认最直白的形态 —— 绕一层（存进 `Vec`、经过 `transmute`）它就看不见，是安全网不是证明：

```text
fn g(x: &u32) -> &mut u32 { unsafe { &mut *(x as *const u32 as *mut u32) } }
error: casting `&T` to `&mut T` is undefined behavior, even if the reference is unused, consider instead using an `UnsafeCell`
  = note: `#[deny(invalid_reference_casting)]` on by default
```

`panic` 穿越 C 边界则是**规定的 abort**而非 UB，可以放心跑（两个函数只差 ABI 名字，下面是实际 stderr 与退出码）：

```rust
extern "C" fn c_abi() { panic!("boom across C boundary"); }
extern "C-unwind" fn cu_abi() { panic!("boom across C-unwind boundary"); }
pub fn demo() {
    println!("C-unwind caught = {}", std::panic::catch_unwind(|| cu_abi()).is_err());
    c_abi();
}
```

```text
C-unwind caught = true
thread 'main' panicked at panicking.rs:225:5: panic in a function that cannot unwind
thread caused non-unwinding panic. aborting.        exit=134
```

与 `noexcept` 的关键差别：`extern "C"` 里 panic 时**先跑 drop glue 再 abort**（1.84.0 起明确），RAII 不在边界上失效。unwind 语义归 [错误处理](/docs/CS/Rust/Error_Handling.md) 与 [Drop](/docs/CS/Rust/Drop.md)。

## Pointer Provenance

Rust 的指针不只是地址：**地址决定访问哪个字节，provenance（来源）决定你有没有权限访问**。它是 C 的 strict aliasing 推到极致后的产物 —— 编译器要靠"这次访问派生自哪个对象"判断能否重排、合并、缓存。

### Why Integer Round-Trips Are Lossy

`ptr → usize → ptr` 会丢信息，因为 `usize` 只承载地址。1.91.0（2025-10-30）加了 warn-by-default 的 `integer_to_ptr_transmutes` lint，实测输出连出路一起给：

```text
fn f(x: usize) -> *const u8 { unsafe { std::mem::transmute(x) } }
warning: transmuting an integer to a pointer creates a pointer without provenance
  = note: this is dangerous because dereferencing the resulting pointer is undefined behavior
  = help: if you truly mean to create a pointer without provenance, use `std::ptr::without_provenance_mut`
help: use `std::ptr::with_exposed_provenance` instead to use a previously exposed provenance
```

出路是把"暴露"写成**显式动作**：`expose_provenance()` 让地址可被整数携带（对端 C 也能持有），`with_exposed_provenance()` 再按暴露过的 provenance 重建指针；穿过 C 数组、句柄表、共享内存都合规。注意这是**演化中的模型**：miri 实现的 Stacked Borrows / Tree Borrows 都是提案性质，"miri 通过"不等于"语言规范背书"。

### The Stable Provenance API

| API | 稳定版本 | 用途 |
| :--- | :--- | :--- |
| `ptr::from_ref` / `from_mut` / `addr_eq` | 1.76.0 (2024-02-08) | 由引用造裸指针并**保留 provenance**，取代 `&x as *const _` |
| `ptr::without_provenance` / `_mut`；`ptr::with_exposed_provenance` / `_mut`；`ptr::dangling` / `dangling_mut` | 1.84.0 (2025-01-09) | 造无 provenance 指针（MMIO、哨兵）；从暴露整数复原；零大小类型的合法悬垂指针 |
| `<*const T>::addr` / `with_addr` / `map_addr` / `expose_provenance` | 1.84.0 (2025-01-09) | 换地址但**沿用原 provenance**，指针算术的正规写法 |
| `NonNull::{from_ref, from_mut, without_provenance, with_exposed_provenance, expose_provenance}` | 1.89.0 (2025-08-07) | 同族动作的 `NonNull` 版；地址类型是 `NonZero<usize>`（刻意不收 0） |

```rust
#![allow(dead_code)]
use std::num::NonZero;
use std::ptr::{addr_eq, dangling, from_mut, from_ref, with_exposed_provenance, without_provenance, NonNull};
fn f(x: &u32, m: &mut u32) -> usize {
    let p = from_ref(x);
    let e = p.expose_provenance();                     // usize，可穿越 FFI / 存进表
    let r = with_exposed_provenance::<u32>(e);         // 复原并重新认领 provenance
    let n: usize = NonNull::from_ref(x).expose_provenance().into();
    let q = NonNull::<u32>::with_exposed_provenance(NonZero::new(n).unwrap());
    std::hint::black_box((from_mut(m), q, without_provenance::<u32>(0x1000), dangling::<u32>()));
    if addr_eq(p, r) { 0 } else { e }
}
```

### Raw References and addr_of

`&raw const` / `&raw mut`（RFC 2582，**1.82.0**）是取裸引用的首选：它**不创建引用**，因此绕开"取引用即承诺一整套不变式"。三次增量要记住：1.82.0 起 `addr_of!` 与 `&raw` 对**所有 static 项**（含 `static mut`）都安全；1.84.0 起 `&raw const *ptr` 安全；1.92.0 起 safe 代码里可 `&raw const/mut` 取 `union` 字段。

```rust
#![allow(dead_code)]
use std::ptr::addr_of;
struct P { a: u32, b: u16 }
union U { x: u32, y: f32 }
static mut S: u32 = 0;
fn f(p: &P, u: &U) -> usize {
    addr_of!(p.a) as usize + &raw const p.b as usize + &raw const S as usize + &raw const (*u).y as usize
}
fn m(p: &mut P) { let q = &raw mut p.a; unsafe { *q = 1 } }
```

为什么不用 `&p.a as *const _`：若字段被 `UnsafeCell` 包住、或正处于另一个活跃 `&mut` 的管辖下，**创建引用这一步本身**就是 UB，哪怕你立刻转成裸指针、从不解引用。第三件工具是 `UnsafeCell::raw_get`（1.56.0）；1.99.0 进一步保证"`UnsafeCell` 的内容可以不经过 `get` 访问"，并据此调整了 `invalid_reference_casting`。

### Raw Pointer Metadata Is Still Unstable

裸指针版 DST 元数据 API **至今没稳定**（`ptr_metadata`，issue #81513，1.98.1 实测 E0658），所以**别在 FFI 里写"用 `ptr::from_raw_parts` 从 C 的 `ptr + len` 组装 `*const [T]`"**。stable 只有两条路：立刻 `slice::from_raw_parts` 成 `&[T]`（引用版是 stable 的），或把胖指针拆成两个字段传、布局含义自己定义（见 [内存布局](/docs/CS/Rust/Memory_Layout.md)）。同族但**已于 1.99.0 稳定**的是"从裸指针问布局"三件套 `mem::size_of_val_raw`、`mem::align_of_val_raw`、`alloc::Layout::for_value_raw`（1.82.0 先放开 `size_of_val_raw` 长度为 0 的情形）；1.98.1 上三者共享一个 gate，正好交叉验证版本号：

```text
error[E0658]: use of unstable library feature `layout_for_ptr`  ... see issue #69835
```

## Building Values Without Writing Them

`MaybeUninit<T>` 的理由只有一条：**类型的不变式在写入之前不成立**。它"与 `T` 同大小同对齐、内容任意"，对泛型参数不承担不变式（布局归 [内存布局](/docs/CS/Rust/Memory_Layout.md)）：

```rust
#![allow(dead_code)]
use std::mem::MaybeUninit;
fn single() -> u32 {
    let mut x: MaybeUninit<u32> = MaybeUninit::uninit();
    x.write(3);                                     // 1.85.0
    unsafe { x.assume_init() }                      // 前置条件：已写入合法值
}
fn array_ok() -> [MaybeUninit<u8>; 4] {             // 元素本身就是 MaybeUninit，故 uninit 数组合法
    unsafe { MaybeUninit::<[MaybeUninit<u8>; 4]>::uninit().assume_init() }
}
fn take_from_c(producer: impl Fn(*mut u8, usize) -> usize) -> Vec<u8> {
    let mut v: Vec<u8> = Vec::with_capacity(64);
    let buf: &mut [MaybeUninit<u8>] = v.spare_capacity_mut();
    let n = producer(buf.as_mut_ptr().cast(), buf.len());
    unsafe { v.set_len(n) };    // 前置条件：前 n 字节已被写满，n <= capacity
    v
}
```

切片版的 `assume_init_ref` / `assume_init_drop` 于 1.93.0 稳定，`Box<MaybeUninit<T>>::write` 于 1.87.0。三个易错点：不要再给 `MaybeUninit<T>` 包一层 `Cell`/`UnsafeCell`；`assume_init()` 是消费式的，之后不得再用该 `MaybeUninit`；`ptr::write` / `copy_nonoverlapping` 解决"绕过 `Drop`"，`MaybeUninit` 解决"绕过不变式"，两件事不要混。`split_at_spare_mut` 仍 unstable（`vec_split_at_spare`）。

## static mut Is Being Retired

`static mut` 的问题不是"要写 `unsafe`"，而是**它的类型是全局可变状态，而 Rust 的别名模型不允许"随时可以造引用"**。两种引用各踩一条 UB（edition 2024，实测）：

```text
error: creating a shared reference to mutable static
  = note: `#[deny(static_mut_refs)]` (part of `#[deny(rust_2024_compatibility)]`) on by default
error: creating a mutable reference to mutable static
  = note: mutable references to mutable statics are dangerous; it's undefined behavior if any other pointer to the static is used
```

时间线：`static_mut_refs` lint 于 **1.77.0**（2024-03-21）加入并 warn，同一份代码 edition 2021 是 `warning`、edition 2024 是 `deny`。但**不取引用的读写仍合法** —— 上文 `five()` 里的 `COUNTER += 1` 在 2024 下编译通过；编译器只钉死"引用"这一种用法，因为只有它直接违反别名模型。替代方案分层：

| 需求 | 用 | 版本 |
| :--- | :--- | :--- |
| 只读一次性初始化 | `OnceLock<T>` + `get_or_init`，或 `LazyLock` | 1.70.0 / 1.80.0 |
| 整型计数器 / 标志 | `AtomicUsize` 等原子类型 | 长期 stable |
| 需要堆分配的可变全局 | `Mutex<T>` / `RwLock<T>`；单线程用 `thread_local!` + `Cell` | 长期 stable |
| 性能敏感、愿意手写契约 | `struct G(UnsafeCell<T>)` + `unsafe impl Sync` | 长期 stable || 只为省掉 `unsafe impl Sync` 样板 | `SyncUnsafeCell` | **仍 nightly** |

最后一行是本主题最大的以讹传讹点：`SyncUnsafeCell` 常被写成"1.81.0 起 stable"，1.98.1 实测它**没有** stable，而且它在 `std::cell` 不在 `std::sync`。于是 stable 的写法是自己承担那个不变式 —— 这恰好印证"`unsafe` 是契约边界"：

```text
error[E0432]: unresolved import `std::sync::SyncUnsafeCell`
error[E0658]: use of unstable library feature `sync_unsafe_cell`  ... see issue #95439
```

```rust
#![allow(dead_code)]
use std::cell::UnsafeCell;
struct Global(UnsafeCell<u64>);
unsafe impl Sync for Global {}                      // 声明：我已保证跨线程互斥
static G: Global = Global(UnsafeCell::new(0));
fn bump() { unsafe { *G.0.get() += 1 } }
```

`extern` 块里声明的 `static mut` 是另一码事 —— 那是**对端 C 的全局量**，Rust 无从决定谁会写它，所以 1.98.1 仍允许声明（连同变参声明，见下文 C-variadic 一节）：

```rust
#![allow(dead_code)]
use std::ffi::{c_char, c_int};
unsafe extern "C" { static errno: c_int; static mut big_buf: [u8; 8];
                   fn printf(fmt: *const c_char, ...) -> c_int; }
```

## Edition 2024 Tightening of unsafe

edition 2024 随 **1.85.0**（2025-02-20）稳定，一次性收紧了 unsafe 生态。下表**每项都在 1.98.1 上按 edition 2021 / 2024 各编一遍**：

| 收紧项 | 机制稳定版本 | edition 2024 表现（实测诊断首行） |
| :--- | :--- | :--- |
| `unsafe extern` 块强制 | 1.82.0（RFC 3484） | `error: extern blocks must be unsafe`（2021 下无警告） |
| unsafe attribute 显式标注 | 1.82.0 | `error: unsafe attribute used without unsafe`；需包的是 `no_mangle` / `export_name` / `link_section` / `naked` |
| `unsafe_op_in_unsafe_fn` 转 warn | 1.82.0 | `warning[E0133]: dereference of raw pointer is unsafe and requires unsafe block` |
| 禁止对 `static mut` 取引用 | lint 1.77.0 | `error: creating a shared reference to mutable static` |
| `env::set_var` / `remove_var` 变 unsafe fn | 过渡始于 1.80.0 | `error[E0133]: call to unsafe function 'set_var' is unsafe and requires unsafe block`（≤2021 仍可安全调用） |
| `no_mangle` 的泛型项 | 1.99.0 起硬错误 | 1.98.1 仍是 `warning: functions generic over types or consts must be mangled` |

`unsafe_op_in_unsafe_fn` 最有教育意义，诊断把 `unsafe fn` 的语义讲清了：`note: an unsafe function restricts its caller, but its body is safe by default`。即 `unsafe fn` 修饰的是**调用方的义务**，"函数体自动是 unsafe 上下文"纯属历史包袱；edition 2024 纠正它，等于强制你在原地写清"这里我依赖哪条前置条件"。**两个反面清单**：`#[global_allocator]` **不是** unsafe attribute（`#[unsafe(global_allocator)]` 报 ``` `global_allocator` is not an unsafe attribute ```），照旧直接写；`#[unsafe(opaque)]` / `#[opaque]` **这个属性不存在**，不透明句柄靠的是"类型导出、布局不导出"。

## Choosing an extern ABI

| ABI | 语义 | 何时用 |
| :--- | :--- | :--- |
| `"Rust"`（默认） | 编译器私有的名字修饰与调用约定，未文档化 | 永不出 crate 边界；见 [compile](/docs/CS/Rust/compile.md) |
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

unwind 的选择不是"要不要检查"，而是**谁负责终止**：`extern "C"` 声明的函数对 Rust 而言"不会 unwind"，这才是 `catch_unwind` 抓不到 C++ 异常的根本原因。1.71.0 引入 `*-unwind` 家族的意义即**同一套字节布局，两种异常传播假设**；本机实测 `extern "C-unwind"` 的定义与声明都可用，panic 能被正常接住（见上文输出）。

## Which Types May Cross the Boundary

| 类别 | 依据 |
| :--- | :--- |
| 整数 / 浮点 / `std::ffi::{c_char, c_int, c_void, ...}` 别名 | 平台 C 类型的稳定包装；`char` ↔ C `uint32_t` 的 ABI 对应关系自 1.76.0 起被文档化 |
| `usize` ↔ C `size_t` | 同上；注意 `std::ffi::c_size_t` **仍 unstable**（1.98.1 实测 E0658，gate `c_size_t`，issue #88345），所以 `size_t` 位置就写 `usize` |
| 裸指针 / `NonNull<T>` / `Option<&T>` / `extern "C" fn(..)` | 单机器字；`Option` 走空指针 niche（`mem::size_of` 文档级保证），所以 `NULL` 恰好等于 `None` |
| `#[repr(C)]` 结构体、`#[repr(transparent)]` 新类型指针 | 布局与 ABI 显式冻结，见 [内存布局](/docs/CS/Rust/Memory_Layout.md) |

不该穿越的：`String` / `Vec<T>` / `HashMap`（Rust 私有布局）、任何 `Drop` 类型（谁析构说不清）、胖指针（`&[T]`、`&dyn Trait` 两个机器字的**顺序与语义**都不被 C 承认，必须自己拆成 `ptr + len`）、未标 `repr(C)` 的 `enum`（1.97.0 起更明确：不能对无布局保证的 enum 做假设）、`!`。这正是 Rust 与 C++ 的共识差异 —— C++ 靠 ABI 惯例把类对象传来传去，Rust 靠 `#[repr(C)]` 显式声明。

## C-variadic Declarations and Definitions

C 变参在 Rust 里**声明与定义分两次稳定**，是最容易写错版本号的条目：

| 阶段 | 稳定版本 | 说明 |
| :--- | :--- | :--- |
| 声明（`extern "C" { fn printf(fmt: *const c_char, ...) -> c_int; }`） | **1.91.0** (2025-10-30) | release notes 原文："can be declared in `extern` blocks but not defined"，覆盖 `sysv64` / `win64` / `efiapi` / `aapcs` |
| 声明 for `"system"` ABI | **1.93.0** (2026-01-22) | 补上 Windows 那条路 |
| **定义**（`unsafe extern "C" fn f(n: i32, args: ...) -> i32`） | **1.99.0** (2026-10-01) | `...` 的类型是 `core::ffi::VaList`（与各目标 C 的 `va_list` ABI 兼容）；能读什么类型由 `VaArgSafe` trait 把关（`i32`/`f64`/裸指针可，`i8`/`f32` 因默认提升不可） |
| `#[unsafe(naked)]` + C 变参 | **1.99.0** | 让裸函数自己实现 `va_start` 类原语 |

本机 1.98.1 上"声明可（见上文 `printf` 块）、定义不可"，两份输出互证。为什么允许声明却不允许定义：声明只需承认**调用约定**（变参在多数 ABI 下靠 `al` / `x8` 之类寄存器记数），定义却要真的构造平台相关的 `va_list` 游标 —— 每个 ABI 一套，测试矩阵完全不同；这与 C 的处境一致，`va_start` 从来是实现提供的。

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

三条纪律：句柄参数用 `*mut Context` 而**不是** `&mut Context`（引用意味着"非空 + 独占 + 生命周期由 Rust 定"，对端 C 三条都给不了，先 `NonNull::new` 再转）；`pub fn` 暴露私有类型会撞 `private_interfaces`（实测 `type 'Handle' is more private than the item 'handle_new'`），所以不透明类型要 `pub struct` 且字段私有；需要"新类型与指针 ABI 完全一致"时用 `#[repr(transparent)]` 包非空指针，1.98.0 起它对"平凡字段"的判定收紧（`repr(C)` 类型、私有字段类型、`#[non_exhaustive]` 类型不再算平凡，细节归 [内存布局](/docs/CS/Rust/Memory_Layout.md)）。

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

```text
$ rustup component add miri
error: component 'miri' for target 'aarch64-apple-darwin' is unavailable for download for channel 'stable-aarch64-apple-darwin'
```

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

## Links

- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [智能指针](/docs/CS/Rust/Smart_Pointers.md)
- [未定义行为（C）](/docs/CS/C/UB.md)
- [未定义行为（C++）](/docs/CS/C++/UB.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

1. [Behavior Considered Undefined (Rust Reference)](https://doc.rust-lang.org/reference/behavior-considered-undefined.html)
2. [Raw pointers module docs (provenance)](https://doc.rust-lang.org/std/ptr/index.html)
3. [FFI chapter of the Rustonomicon](https://doc.rust-lang.org/nomicon/ffi.html)
4. [Edition Guide: references to mutable statics](https://doc.rust-lang.org/edition-guide/rust-2024/static-mut-references.html)
5. [Rust Release Notes](https://doc.rust-lang.org/stable/releases.html)
6. [Miri](https://github.com/rust-lang/miri)
