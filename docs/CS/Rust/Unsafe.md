## Introduction

`unsafe` 常被说成"关掉安全检查的开关"，这个比喻是错的。它只给你五件事：**允许写下那五种编译器无法替你证明、但语义合法的操作**。借用检查、类型检查、生命周期、`static mut` 取引用禁令在 `unsafe` 块里**照旧工作**；被关掉的只是"编译器替你兜底"，同时**契约的责任过户给你**。所以 `unsafe` 代码的正确性不写在类型里，而写在文档的前置条件里 —— 它是**契约边界**，不是免死金牌。

这条边界只向内。跨出语言的部分（ABI、可穿越类型、回调、bindgen）归 [FFI](/docs/CS/Rust/FFI.md)，两篇的枢纽是 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。本文只回答一个问题：**`unsafe` 到底解锁了什么，解锁之后你欠下了什么**。

未定义行为本身不重述 —— 本库已有 [C 的未定义行为](/docs/CS/C/UB.md)（"标准不施加要求 → 优化反噬"）与 [C++ 的未定义行为](/docs/CS/C++/UB.md)（"零成本换来的责任过户"）两篇口径，本文只做**对照**。布局与 niche 归 [内存布局](/docs/CS/Rust/Memory_Layout.md)；`Rc`/`Arc`/`Cell` 的安全 API 层归 [智能指针](/docs/CS/Rust/Smart_Pointers.md)；数据竞争与 `Send`/`Sync` 归 [并发](/docs/CS/Rust/Concurrency.md)；`no_std` 全景归 [No_Std](/docs/CS/Rust/No_Std.md)。本文版本归属与诊断文本以 **rustc 1.98.1 (48a229cea 2026-09-01)、`aarch64-apple-darwin`** 实测为准；标"自 1.99.0 起"的条目来自 release notes 史页，本机复现不出来 —— 同时给出它在 1.98.1 上的 E0658，两者互证。

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

这五类正是官方 UB 清单的全部入口（清单见 References 里的 Behavior considered undefined）。缺 `unsafe` 时的诊断 E0133 会**直接点名后果**：

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

## Two Alias Models and Where They Come From

"引用别名违反"是 Rust UB 清单里最难自查的一条，因为**"违规"的判定标准本身还没有定案**。编译器实现按两个提案演进，两者在 miri 里实现、在论文与讨论里成形，但都不是语言规范：

| 模型 | 出处 | 核心规则 | 争议点 |
| :--- | :--- | :--- | :--- |
| **Stacked Borrows** | O'Hearn / langs-team 讨论，2019 起 | 引用入栈出栈；通过栈中间接访问即令其上条目失效；`Raw` 指针保留整栈 | 对某些"借道"写法过严，如把 `&mut` 存入结构体字段再分别使用 |
| **Tree Borrows** | langs-team 后续提案，2023 起 | 权限在"位置树"上传递；读权限可沿树向下传递，写权限必须独占子树 | 是否最终取代 SB 仍未定；miri 两个模型都在测 |

三件事要说清：

1. **miri 报错 ≠ 你写错了语言**，但**miri 报错几乎总意味着你的代码在某个正式模型下不成立**，修掉通常更安全。
2. 两个模型在少数代码上结论相反，所以"miri 默认跑哪个"会影响结果 —— miri 的 `-Zmiri-tree-borrows` 用来切换。
3. 日常 safe 代码碰不到这层模型；只有 `&raw`、`ptr::offset`、`UnsafeCell` 三件套开始频繁出现时，它才成为必须理解的背景。

Miri 的能力边界（写 unsafe 的人必须记住）：它只跑 **Rust** 代码，`extern "C"` 声明的外部函数不会真执行（要么手写桩，要么当黑盒）；它检查的别名模型是**某个具体提案**，通过不等于未来编译器一定认可。安装与 nightly 限定见 [工具链](/docs/CS/Rust/Tooling.md)。

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
| 性能敏感、愿意手写契约 | `struct G(UnsafeCell<T>)` + `unsafe impl Sync` | 长期 stable |
| 只为省掉 `unsafe impl Sync` 样板 | `SyncUnsafeCell` | **仍 nightly** |

最后一行是本主题最大的以讹传讹点：`SyncUnsafeCell` 常被写成"1.81.0 起稳定"，1.98.1 实测它**没有** stable，而且它在 `std::cell` 不在 `std::sync`。于是 stable 的写法是自己承担那个不变式 —— 这恰好印证"`unsafe` 是契约边界"：

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

`extern` 块里声明的 `static mut` 是另一码事 —— 那是**对端 C 的全局量**，Rust 无从决定谁会写它，所以 1.98.1 仍允许声明（连同变参声明，归 [FFI](/docs/CS/Rust/FFI.md)）：

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

## Writing Discipline for unsafe Code

Unsafe Code Guidelines 项目长期没有"完成态"，但几条纪律已经被社区与官方文档反复确认，逐条对应到上面的机制：

1. **把 unsafe 块压到最小**。`unsafe fn` 的调用方也欠一份契约，所以 unsafe 块越窄、前置条件越好写；最理想的形状是 safe 外壳 + 窄 unsafe 内核，`handle_free` 那种"空指针检查在 safe 侧、`Box::from_raw` 在 unsafe 侧"的切分。
2. **契约写进 `# Safety` 文档段**。编译器看不见契约，所以契约的位置只有两处：文档段与测试。写不出三行"调用方必须保证"的函数，通常说明抽象不对。
3. **能 safe 就不要 unsafe**。上表 `static mut` 那节是范本：`OnceLock` / 原子 / `Mutex` / `UnsafeCell + unsafe impl Sync` 是四个代价递增的台阶，先确认前三个真的不能用。
4. **不变量跨 panic 也要成立**。`unsafe` 代码在 panic 前改变内部状态（如 `set_len` 与真实写入不同步）会留下未定义状态，drop 路径要单独审。
5. **用工具补上编译器缺位**：miri 查别名与未初始化（nightly），`clippy` 的 `invalid_reference_casting` 系列查最直白的形态，`cargo-fuzz` 给边界喂输入，`cargo-vet` 审计依赖里谁引入了 `unsafe`。
6. **别把 miri 通过当安全证明**：它跑的是提案级模型、不跑外部 C 函数、也不覆盖所有目标。它是成本最低的那一层网，不是地板。

## Common Failure Modes Checklist

写 unsafe 时最常犯的十类错误，按出现频率排列：

| # | 错误 | 症状 | 对应机制 |
| :--- | :--- | :--- | :--- |
| 1 | `&x as *const _ as *mut _` 写回引用 | miri 报 alias 错、release 下逻辑错乱 | 引用构造即承诺；用 `&raw mut` / `addr_of!` |
| 2 | `transmute` 整数造指针 | `integer_to_ptr_transmutes` warning；解引用 UB | provenance 丢失；用 `with_exposed_provenance` |
| 3 | `set_len` 早于真实写入 | 读到未初始化 = immediate UB | `MaybeUninit` + 先写后 `set_len` |
| 4 | `Box::from_raw` 非配套指针 | double free / 跨分配器释放 | 三种所有权契约见 [FFI](/docs/CS/Rust/FFI.md) |
| 5 | `static mut` 取引用 | edition 2024 deny | `OnceLock` / 原子 / `Mutex` |
| 6 | 手写 `unsafe impl Sync` 而无同步 | 偶发数据竞争，tsan 抓不到 Rust 层 | `Send`/`Sync` 见 [并发](/docs/CS/Rust/Concurrency.md) |
| 7 | `asm!` 的 clobber 列表不全 | 寄存器值被悄悄改掉 | 内联汇编语法与寄存器类别 |
| 8 | `union` 读到非存活字段 | 位模式解释成非法值 | 引用类型不能 union |
| 9 | 在 `Drop` 里再触发同一释放 | 重入释放 | `mem::forget` / `ManuallyDrop`，归 [Drop](/docs/CS/Rust/Drop.md) |
| 10 | 依赖 nightly 当作 stable | E0658 | 版本轴归 [Edition 与 MSRV](/docs/CS/Rust/Edition_MSRV.md) |

## Links

- [FFI](/docs/CS/Rust/FFI.md)
- [智能指针](/docs/CS/Rust/Smart_Pointers.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [错误处理](/docs/CS/Rust/Error_Handling.md)
- [工具链](/docs/CS/Rust/Tooling.md)
- [未定义行为（C）](/docs/CS/C/UB.md)

## References

1. [Behavior Considered Undefined (Rust Reference)](https://doc.rust-lang.org/reference/behavior-considered-undefined.html)
2. [Raw pointers module docs (provenance)](https://doc.rust-lang.org/std/ptr/index.html)
3. [The Rustonomicon](https://doc.rust-lang.org/nomicon/)
4. [Unsafe Code Guidelines Working Group (rust-lang/unsafe-code-guidelines)](https://github.com/rust-lang/unsafe-code-guidelines)
5. [Edition Guide: references to mutable statics](https://doc.rust-lang.org/edition-guide/rust-2024/static-mut-references.html)
6. [Rust Release Notes](https://doc.rust-lang.org/stable/releases.html)
