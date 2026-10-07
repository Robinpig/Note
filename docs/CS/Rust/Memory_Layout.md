## Introduction

这一篇回答一个问题：**关于一个值在内存里长什么样，Rust 编译器到底承诺了什么，哪些只是"当前实现恰好如此"**。这条边界在别的语言里往往没人追问（布局要么写死在 ABI 里，要么完全黑盒），而 Rust 把它做成了一组需要显式购买的契约：默认的 `repr(Rust)` 只承诺**保命所需的最小集合**（offset 被对齐整除、字段不重叠），字段顺序、tag 摆放、padding 大小统统不保证；想要保证，就要为 `repr(C)` / `repr(transparent)` / `#[non_exhaustive]` 这些标注付出表达力上的代价。

全文区分两种陈述，**混写就是这篇笔记最不能犯的错误**：

- **规范保证**：来自 Rust Reference / 版本兼容承诺，跨版本、跨 target 语义稳定。
- **实测值**：本机 `rustc 1.98.1 (48a229cea 2026-09-01)`、目标三元组 **aarch64-apple-darwin**、`-O`、edition 2021/2024 跑出；并用 pinned 的 `rustc 1.95.0` 做对照。同一个程序在 64 位 x86 上绝大多数数字相同，但**只有"指针宽度 = usize"这类规范条目才跨平台**。

边界：所有权与移动语义在 [Ownership](/docs/CS/Rust/Ownership.md)；`Box`/`Rc`/`Arc` 选型在 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)；`dyn` vtable 里有什么、如何分发在 [Trait_System](/docs/CS/Rust/Trait_System.md)；UB 全景、provenance 与 FFI 调用约定在 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)——本篇只取**布局视角**，不重复 UB 清单。通用内存分配（`malloc` 的对齐契约）见 [C Struct 与对齐](/docs/CS/C/Struct.md) 与 [malloc](/docs/CS/C/malloc.md)。

## The size_of, align_of, offset_of Trio

`std::mem::size_of::<T>()` / `align_of::<T>()` 是 `const fn`，可以在 `const` 上下文里做布局断言；`mem::offset_of!`（稳定自 **1.77.0**，2024-02-08）给出字段相对结构体开头的字节偏移。探测时**不要经引用取地址**——用 `offset_of!`、`&raw const`（1.82.0）或 `addr_of!`（1.51.0），它们不创建引用，因而在 packed / 未初始化场景安全，而 `&p.field` 一旦不对齐就是 UB。

基础类型的实测值（aarch64，与主流 64 位平台一致）：

```text
u8=1 u32=4 u64=8 f64=8 char=4 bool=1 usize=8 ()=0 [u8;0]=0
(u8,u8)=2 (u8,u32)=8 (u32,u8)=8 ((),u8,())=1 struct Z(u8,())=1
```

元组同样会被**重排**：`(u32, u8)` 是 8 字节而不是 5——与 C 结构体"按声明顺序 + 尾部补齐"的算式一致，但 Rust 连"按声明顺序"这半步都不承诺。

重排的真实证据（`repr(Rust)` vs `repr(C)`，同一组字段）：

```rust
use std::mem::{size_of, align_of, offset_of};

struct Reorder { a: u8, b: u32, c: u16 }
#[repr(C)]
struct ReorderC { a: u8, b: u32, c: u16 }

fn main() {
    // 实测 1.98.1 aarch64: Reorder  size=8  align=4  a=6 b=0 c=4
    //                  ReorderC size=12 align=4  a=0 b=4 c=8
    assert_eq!(size_of::<Reorder>(), 8);
    assert_eq!(offset_of!(Reorder, b), 0);   // b 被挪到了开头!
    assert_eq!(offset_of!(ReorderC, b), 4);  // repr(C) 才按声明顺序
}
```

同一个类型，`repr(Rust)` 把 4 字节的 `b` 放在偏移 0（编译器按对齐降序堆叠：b@0、c@4、a@6，尾部只浪费 1 字节 padding），`repr(C)` 忠实照抄 C 的布局（`a` 后填 3、尾部再填到 12）。**"Rust 不保证字段顺序"不是传言，是本机三行就能打出来的事实**——而 1.95.0 与 1.98.1 上这组偏移完全相同：重排算法同样是"当前实现"，它没变，但你不能依赖它不变。

Reference 对默认表示的**全部**保证只有这么几条（Type layout § The Rust representation），值得逐条背下——这就是"编译器给的"与"实现巧合"的分界线：

- 每个字段的 offset 能被该字段自身的对齐整除；
- 类型的对齐不小于任何字段的对齐；
- 结构体字段**互不重叠**：存在某个字段排序使区间不相交，但这个排序**不必是声明序**（全 ZST 字段可与别的字段同地址）；
- 全 ZST 的结构体、以及"唯一变体的内容全是 ZST"的枚举，本身保证零大小。

然后是一句原文：**"There are no other guarantees of data layout made by this representation."** ——这句话是整篇的锚点。

## repr Attribute: Trading Expressiveness for Guarantees

| 属性 | 保证什么 | 典型用途 | 主要陷阱 |
| :-- | :-- | :-- | :-- |
| `repr(C)` | 字段按声明顺序、padding 按 C ABI 规则；enum 布局对齐 C | FFI 结构体、手写二进制协议、需要 `transmute` 的场合 | 放弃重排优化，体积常常更大；零变体 enum 用 `repr(C)` 是**错误**（Reference 明文） |
| `repr(transparent)` | 与"唯一非平凡字段"同布局同 ABI | 新类型包装 `*const T` / `NonZeroUsize` 过 FFI；单变体 enum 包装 DST | 只允许任意个 size 0 + align 1 字段（如 `PhantomData`）**加至多一个**其他字段；1.98.0 收紧"平凡"判定（见下） |
| `repr(packed)` / `repr(packed(N))` | 字段对齐降为 1（或 N），无 padding | 网络头、寄存器镜像 | 字段引用直接编译失败（E0793）；取错地址方式=UB |
| `repr(align(N))` | 抬高对齐到 N | SIMD 缓冲、页对齐 | over-aligned 类型过 FFI / 普通分配器有额外义务（见下） |

`repr(packed)` 的 E0793 在 edition 2021 与 2024 下都是**硬错误**（本机实测），诊断值得整段记住：

```text
error[E0793]: reference to field of packed struct is unaligned
  = note: this struct is 1-byte aligned, but the type of this field may require higher alignment
  = note: creating a misaligned reference is undefined behavior (even if that reference is never dereferenced)
  = help: copy the field contents to a local variable, or replace the reference with a raw pointer
          and use `read_unaligned`/`write_unaligned`
```

关键词是 "even if never dereferenced"——**引用本身就携带对齐不变式**，造出来即违约。合规姿势只有两种：拷贝字段值，或 `&raw const` + `read_unaligned`（本机 1.98.1 + edition 2024 实测可编译运行）：

```rust
#[repr(packed)] struct P { a: u8, b: u32 }
fn main() {
    let p = P { a: 1, b: 0xdeadbeef };
    let v = unsafe { std::ptr::read_unaligned(&raw const p.b) };
    assert_eq!(v, 0xdeadbeef);
}
```

`ref` 模式绑定 packed 字段走的是同一条检查。实测 `#[repr(packed)] struct Packed { a: u8, b: u32, c: u16 }`：size=7、**align=1**、offset 0/1/5——C 语言 `#pragma pack` 的对应物，但 Rust 把"你由此造出的每个引用"的违规成本前移到了编译期。

`repr(align(N))` 实测 `#[repr(align(16))] struct OverAligned { x: u8 }` 为 size=16、align=16；`#[repr(C, align(16))] struct Both { x: u8, y: u32 }` 为 size=16、align=16（声明序 + 抬高对齐可叠加）。为什么 over-aligned 会影响 FFI：C 侧 `malloc` 只保证 `max_align_t` 对齐（多数平台 16，见 [C Struct 与对齐](/docs/CS/C/Struct.md)），`Vec<OverAligned>` 在 Rust 里按 `Layout` 分配没问题，但把这样的类型交给 C 的 `malloc`/栈传参，对齐契约就没人接了；跨语言边界要么降到 `max_align` 以内，要么两侧同时换用对齐分配接口。

### repr(transparent)'s "Trivial Field" Tightening in 1.98.0

`#[repr(transparent)]` 要求"至多一个非平凡字段"。1.98.0 (2026-08-20) 的 Compatibility Notes（PR 155299）原文：**`repr(C)` types, types with private fields, and `#[non_exhaustive]` types are no longer considered "trivial"**。本机做了 1.95.0 → 1.98.1 的 A/B：

```rust
#[repr(C)] struct Marker;                      // C 语言里没有零大小结构体
#[repr(transparent)] struct W(Marker, u8);
```

- 1.95.0：warning —— "`zero-sized fields in repr(transparent) cannot contain repr(C) types` … 将被移除，未来版本成为硬错误"（跟踪 issue #78586）。
- 1.98.1：硬错误 —— `error[E0690]: transparent struct needs at most one non-trivial field, but has 2`，子诊断 "`Marker` is a `#[repr(C)]` type, so it is not guaranteed to be zero-sized on all targets"。

根因很妙：`Marker` 在 Rust 里是 0 字节，但 `#[repr(C)]` 声称自己与 C 同布局，而 **C 保证任何结构体非零大小**——跨 target 时它未必能忽略。`PhantomData`（size 0 且 align 1）依然是合法陪衬，两个版本的编译器都接受 `#[repr(transparent)] struct W(PhantomData<u8>, *const u8)`。

## Enum Layout and Niche Optimization

布局算法（实现细节，非规范条文）对每个 enum 在两条路里选一条：**tag + union 载荷**，或者**挤进某个字段类型里"不可能出现的位模式"（niche）**。niche 不是魔法，原料是类型的**合法性不变式（validity invariant）**——这半边倒是写在规范里（Reference § Behavior considered undefined："producing an invalid value is immediate UB"，其中明确：引用与 `Box<T>` 必须对齐且非 null、fn pointer 必须非 null、`bool` 只能是 0/1、`char` 不得落在 0xD800..=0xDFFF 也不得超过 `char::MAX`）。于是 `&T`/`Box<T>`/`NonNull<T>`/`fn()` 天然贡献一个空闲值 null，`NonZeroXxx` 排除 0，`bool` 有 254 个空闲模式，`char` 有上百万个。

实测 `size_of` 表（rustc 1.98.1，aarch64-apple-darwin）：

| 类型 | size | 解释 |
| :-- | :-- | :-- |
| `&u8` / `Option<&u8>` | 8 / 8 | null 编码 None，**免费** |
| `Box<u8>` / `Option<Box<u8>>` | 8 / 8 | 同上 |
| `fn()` / `Option<fn()>` | 8 / 8 | 同上——与裸指针同宽 |
| `Option<NonNull<u8>>` / `Option<NonZeroU8>` | 8 / 1 | 同上 |
| `bool` / `Option<bool>` | 1 / 1 | 2..=255 全是空闲模式 |
| `char` / `Option<char>` | 4 / 4 | 非法标量值做 tag |
| `u8` / `Option<u8>` | 1 / **2** | u8 无非法值 → 加一字节 tag |
| `(u8,u8)` / `Option<(u8,u8)>` | 2 / **3** | 元组同样无 niche |
| `Option<Option<&u8>>` | **16** | niche 只有 null 一个，已被内层用掉 → 外层另付一整字 |
| `&[u8]` / `Option<&[u8]>` / `Option<&str>` | 16 / 16 / 16 | 胖指针 niche 落在**数据字**，metadata 字照留 |
| `Box<dyn Shape>` / `Option<Box<dyn Shape>>` | 16 / 16 | 同上 |
| `ManuallyDrop<Option<Box<u8>>>` | 8 | niche 穿过 trivial 包装 |
| `Option<MaybeUninit<u8>>` | **2** | MaybeUninit 任何位模式都合法 → **消灭 niche** |
| `Empty`（零变体 enum） | 0 | 没有任何值，也不占空间 |

**`Option<&T>` 与裸指针同宽**的答案就是这张表的前四行：不存 tag，0x0 位模式专职表示 None。**什么时候 niche 用不上**：类型没有多余位模式（u8/`(u8,u8)`）、niche 名额已被占用（嵌套 Option）、或类型被声明为"任意位模式皆合法"（`MaybeUninit`）。

`Result<T, E>` 常常不是 `max(size_of::<T>(), size_of::<E>())`，因为两个变体都带数据时 tag 未必塞得下。实测：

| 类型 | size | 备注 |
| :-- | :-- | :-- |
| `Result<u8,u8>` | 2 | tag 占位 + 两变体共享 1 字节载荷 |
| `Result<(),u8>` | 2 | `()` 无空间可放 tag，独立 tag 字节 |
| `Result<u8,Box<u8>>` | **16** | 不是 8：Box 的 niche 只有 null 一个值，装不下"另一个变体还要带 1 字节数据"的需求 → tag+union 对齐到 8 |
| `Result<Vec<u8>,u8>` | **24** | = `Vec` 本身：1.65.0 起多数据变体也能做 niche 填充（见下） |
| `Result<u8,NonZeroU8>` | 2 | |
| `enum E2 { A(u64), B(u64,u64), C(u8) }` | 24 | tag + 16 字节载荷 + 对齐 |
| `enum NE1 { A(Box<u8>), B(()) }` | **8** | 免费——tag 挤进指针的 null 位模式 |
| `enum Tag { A(u8,u8), B(u8,u8), C }` | 3 | |

`NE1`/`Result<Vec,u8>` 这类"两个变体都带数据但仍是免费的"得益于 1.65.0 的编译期变更（release notes Compiler 节，PR 98051："Use niche-filling optimization even when multiple variants have data"）：niche 的空闲位模式不仅用来选变体，还能顺带编码对应变体的部分载荷。

**但以上全部是"当前算法的输出"，不是承诺。** 1.97.0 (2026-07-09) Compatibility Notes 白纸黑字（PR 155473）：

> The encoding of certain `enum`s have changed. This is not a breaking change, as it only applies to `enum`s without layout guarantees, but is noted here as we've seen people impacted from having made assumptions about the layout algorithm.

本机把 6 种形状枚举的 `size_of` 在 1.95.0 与 1.98.1 之间逐项 diff，**没有任何一个数字变化**——这恰好印证了警告的性质：变的是 tag 具体放哪、debuginfo 如何呈现这类"你本就不该看"的细节。跨进程共享裸内存、把无 `#[repr]` 枚举 `transmute` 成整数、靠字节级快照做回归测试，都是踩在这块冰面上。

> [!WARNING]
> 关于 niche 的三条易错口径：
> 1. `Option<&T>`/`Option<Box<T>>` 与裸指针同宽是**写在 std 文档里的**（`mem::size_of` 页：`*const T`/`&T`/`Box<T>`/`Option<&T>`/`Option<Box<T>>` 同大小，T 为 Sized 时都等于 `usize`）；但 `Option<fn()>`、`Option<&[u8]>` 这类延伸只是本机实测，而 `Result<Vec<u8>,u8>` 这种"多变体 niche 填充"更是 1.65.0 起的算法红利，**不是承诺**。
> 2. niche 的"名额"极其稀缺：一个可空指针只贡献一个空闲值，所以 `Option<Option<&T>>` 要付第二份空间（实测 16）。
> 3. `MaybeUninit` 会**吃掉**内层的 niche：实测 `MaybeUninit<&u8>` = 8，但 `Option<MaybeUninit<&u8>>` = 16，而不是免费维持 8。

需要可控 tag 时用**原始表示**：`#[repr(u8)]`/`#[repr(C)]` 字段-less 枚举有文档化布局（discriminant 宽度固定），实测 `#[repr(C)] enum CEnum { A, B = 300 }` = 4 字节、`#[repr(u8)] enum U8Enum { A(u32), B }` = 8 字节。注意 Reference 同时保证：**为 ZST 内容的单变体 enum 本身零大小**，这条是规范，不是巧合。

## DST and Fat Pointers: Two Machine Words on the Stack

`sized` 类型大小编译期已知，可以整体躺在栈上；`str`、`[T]`、`dyn Trait` 是 DST（动态大小类型），**值形式不能放进栈变量、也不能放进非末位字段**，只能借指针出现。对 DST 直接问大小是编译错误（本机实测原文）：

```text
error[E0277]: the size for values of type `dyn Shape` cannot be known at compilation time
  = help: the trait `Sized` is not implemented for `dyn Shape`
```

把 `str` 放在结构体**中间**得到同一族 E0277（"`the size for values of type `str` cannot be known at compilation time`"，实测 1.98.1）；但放在**最后一位**是合法的——`struct Bad { s: str }` 能通过类型检查，因为此时 `Bad` 自己也被传染成 DST。这正是 C 的 flexible array member（`struct { size_t len; char data[]; }`）在 Rust 里的对应形态：**类型能定义、能拿引用，但无法在 stable 上构造**——构造需要手工造胖指针，而那是 `ptr_metadata` gate 后的 API（1.98.1 实测 E0658）。stable 上让指针"变胖"只有一条路：隐式 unsize coercion（`&array as &[T]`、`boxed_array.into()`）。

DST 指针是**胖的**：薄指针只有地址，胖指针 = 地址 + metadata——切片存长度，trait 对象存 **vtable 指针**（vtable 里有什么、动态分发怎么走，见 [Trait_System](/docs/CS/Rust/Trait_System.md)）。Reference 保证 DST 指针的 size/align **不小于**同种薄指针，并用 Note 承认"目前全部是 2×usize"——**注意那个 "you should not rely on this"**。

`&dyn` 是两个机器字的实测证据分两层。第一层是宽度（1.98.1，aarch64）：

```text
&u8=8  &str=16  &[u8]=16  &mut[u8]=16  &dyn Shape=16  Box<dyn Shape>=16
String=24  Vec<u8>=24  Rc<u8>=8  Arc<u8>=8  Box<[u8;4]>=8  Box<[u8]>=16
```

`Box<[u8;4]>`（8 字节，Sized 元素）到 `Box<[u8]>`（16 字节）的 unsize 转换就是 metadata 从无到有的过程。第二层是**两个字的角色**——1.87.0 起裸指针的 `Debug` 会打印 metadata（stable API，本机实测输出）：

```rust
let sl: &[u8] = b"hello";
println!("{:?}", sl as *const [u8]);
// Pointer { addr: 0x100a57fc0, metadata: 5 }
let s: &dyn Shape = &Circle(2.0);
println!("{:?}", s as *const dyn Shape);
// Pointer { addr: 0x16f3deaf8, metadata: DynMetadata(0x10a64040) }
```

切片的 metadata 就是长度 5，trait 对象的 metadata 是一个 vtable 地址——两字结构直接可见。手工拆分/重组 metadata 的 `ptr::metadata` / `ptr::from_raw_parts`（DST 版）到 1.98 仍在 `ptr_metadata` gate 后（E0658），stable 上构造胖指针只能靠隐式 coercion（`&concrete as &dyn Trait`、`boxed_array.into()`）。

栈/堆的划分由此一目了然：`Vec<u8>` 在栈上是 24 字节（ptr+len+cap，全部 Sized），堆上只存 `[u8]` 本体，**不存** len/cap；`String` 同理（24）；`Rc<T>`/`Arc<T>` 栈上只有一个薄指针（8），计数器和值在同一个堆块里（块头布局是实现细节，选型见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)，分配走系统 `malloc` 的历史与机制见 [C malloc](/docs/CS/C/malloc.md)）。ZST 让"栈上 footprint 可以为零"（`((), u8, ())` 实测 1 字节）。**局部变量在栈帧内的相互位置没有任何保证**——Reference 只管类型内部布局，帧内调度归编译器。

## non_exhaustive as a Layout Contract

`#[non_exhaustive]` 不改**当前**机器码布局（它只影响下游 crate 的名字可见性），但它是**跨版本**维度的布局信号："这个 enum 还会长出新变体、这个 struct 还会长出新字段"——于是它的 `size_of`、tag 宽度、字段偏移全部处于**作者保留变更权**之下。这与 1.97.0 的编码变更警告是同一课的两面：前者是作者显式声明"别冻结我"，后者是编译器示范"冻结实现细节的下场"。

跨 crate 使用（本机 1.98.1 实测，lib 编译 rlib 后下游引用）：

| 标注位置 | 下游后果 |
| :-- | :-- |
| `#[non_exhaustive] enum` | 穷举 match 编译失败：`E0004: non-exhaustive patterns: _ not covered`——必须留 wildcard 臂 |
| `#[non_exhaustive] struct` | 结构体字面量构造失败 `E0639`；模式不带 `..` 失败 `E0638: .. required` |
| `#[non_exhaustive]` 元组变体 | 变体对下游整体不可命名（构造与模式都报 `E0603: tuple variant is private`），只能被 wildcard 命中 |
| `#[non_exhaustive]` 用在**字段**上 | 已弃用的误用：warning "`#[non_exhaustive]` can be applied to data types and enum variants"，将来升硬错误 |

对 `repr(C)` 而言这意味着：**给 FFI/序列化用的结构体绝不要加 `#[non_exhaustive]`**——你声明了 C 布局，又声明字段集可变，两者在别的发行版上必然打架。反过来，`repr(transparent)` 的"平凡字段"名单在 1.98.0 把 `#[non_exhaustive]` 类型踢出去，正是这条契约在布局层的投影。

## MaybeUninit and Uninitialized Memory

**读未初始化内存不是"读到垃圾值"，是立即 UB**——即使类型允许所有位模式。1.65.0 (2022-11-03) § Language 的表述（release notes 原文）："Uninitialized integers, floats, and raw pointers are now considered immediate UB. Usage of `MaybeUninit` is the correct way to work with uninitialized memory." 在此之前，读未初始化的 int 属于"可能以后才算错"；1.65 起它是编译器可以随时假定"有值"的即时错误。布局视角的推论：优化器可以按需把未初始化字节**替换成任意常量**，所以"先读出来再判断"的防御代码根本没有存在的语义。

`MaybeUninit<T>` 是布局完全透明的一块"T 大小的存储"：实测 `size_of`/`align_of` 与 `T` 相同（`MaybeUninit<u32>` = 4/4，`MaybeUninit<[u8;3]>` = 3），它**不排除任何位模式**——副作用是前面表里的 `Option<MaybeUninit<u8>>` = 2（niche 被消灭）。1.92.0 (2026-05-28) 的 release notes 条目 "Document MaybeUninit representation and validity" 把这份表示契约正式写进文档。

运行期误用会被 lint 逮住（本机实测，u8 这种"全位模式合法"的类型同样警告）：

```text
warning: the type `u8` does not permit being left uninitialized
  = note: integers must be initialized
  = note: `#[warn(invalid_value)]` on by default
```

const 上下文则是硬错误：`const U: u8 = unsafe { MaybeUninit::<u8>::uninit().assume_init() };` 报 `error[E0080]: reading memory at alloc12[0x0..0x1], but memory is uninitialized at [0x0..0x1], and this operation requires initialized memory`。`assume_init` 的"调用前置条件=每个字节都已写入"、以及 `Box<MaybeUninit<T>>::write`（1.87.0）这类部分初始化工具的完整安全契约属于 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md) 的范畴。

## UnsafeCell and the Layout Cost of Interior Mutability

| 类型 | size（u8 内嵌，实测） | 布局成本 |
| :-- | :-- | :-- |
| `UnsafeCell<u8>` | 1 | 零开销：与 `u8` 同布局（`repr(transparent)` 语义），运行时不携带任何标记 |
| `Cell<u8>` | 1 | 同上——读写整体拷贝，无借用记账 |
| `RefCell<u8>` | **16** | 借用计数器（当前实现为一个 `isize` 宽的状态字）+ 载荷 + padding；`RefCell<Vec<u8>>` = 32 |

内部可变性的**空间账单**取决于运行时检查放在哪里：`Cell`/`UnsafeCell` 不检查所以不加一个字节；`RefCell` 把"借用状态"塞进同一个对象头，16 − 1 = 15 字节的差额就是那本账。`&RefCell<T>` 在布局上仍是一个薄指针（8 字节）——可变性藏在指向的内存里，这正是它与 `&mut` 的分工。为什么 `Cell` 必须整体换值而不能给字段引用：`&mut`/`&` 的 aliasing 规则（"至多一个可变引用 XOR 任意多共享引用"）不因 `UnsafeCell` 而暂停，只是把违约检测推迟到运行时或取消；违约即 UB，完整清单在 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。顺带一条版本事实：1.99.0 起 std 明文保证 **`UnsafeCell` 的内容可以不经过 `get()` 访问**（REL § Libraries），`invalid_reference_casting` lint 随之调整。所有 `&mut` 指向的内存底层都是 `UnsafeCell`（编译器隐式插入），因此"引用布局 = 指向 `UnsafeCell` 的裸指针布局"。

## Cross-Language Comparison

| 维度 | C | C++ | Java (HotSpot) | Rust |
| :-- | :-- | :-- | :-- | :-- |
| 字段顺序 | 声明序，ABI 锁定 | 同一 access 段声明序（标准允许段间重排，主流实现不排） | 由 JVM 决定，完全黑盒 | 默认**不保证**；`repr(C)` 才锁定 |
| 默认布局保证 | 有（语言级 ABI） | 接近有 | 无 | 近乎无（只有 soundness 四条） |
| 收紧/放开工具 | `#pragma pack`、`_Alignas` | `[[gnu::packed]]`、`alignas`、`[[no_unique_address]]` | 无 | `#[repr(C/transparent/packed/align(N))]` |
| 位域 | `:3` 位域，成员**不可取地址**，跨编译器布局实现定义 | 同 C + 访问控制切分 | 无对应物 | **没有语言级位域**，位级打包只能手写移位+掩码（与 C 位域的通用建议一致，见 [Struct.md](/docs/CS/C/Struct.md)） |
| 空类型优化 | 空 struct 至少 1 字节 | 空基类大小 1，**EBO** 让派生类免费 | 不适用（对象必有 header） | ZST 天生 0 字节，`()`/`PhantomData`/空字段 struct 均不占空间 |
| 虚表指针在哪 | 不适用 | **vptr 嵌在对象头部**（多继承多个），数据与调度混在一起 | mark word + klass 指针在对象头 | vtable **不进对象**，存在胖指针的第二字里——`Circle` 自己永远是纯数据 |
| 对象头 | 无 | 多态类 1×指针宽（vptr） | mark word 8 + klass 4（压缩指针）= 12 字节起，补齐到 8 的倍数 | 无：`T` 就是 `T`，堆块簿记在 `Vec`/`Rc` 等容器的分配层 |
| 布局探测 | `sizeof`/`offsetof` | 同 C + `std::hardware_destructive_interference_size` 等 | 只能靠 JOL 工具库 | `size_of`/`align_of`/`offset_of!`/`&raw`/裸指针 `Debug`（1.87.0） |

（C 侧口径与 [Struct.md](/docs/CS/C/Struct.md) 一致，C++ 与 [ObjectModel.md](/docs/CS/C++/ObjectModel.md) 一致，Java 对象头与 [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) 口径一致。）最值得对照的是虚表位置：C++ 把 vptr 焊进对象，Rust 把 vtable 指针放进 `&dyn`——代价是 trait 对象永远"指针翻倍"，红利是**具体类型的对象零开销**且可以被 `Vec<T>` 之类以值形式紧凑存放；Java 则是第三条路：header + GC 间接，人人平等地付钱。

## Practice: What to Do When You Need to Freeze Layout

1. **先问要不要冻结**。只有跨进程裸内存、mmap 文件头、与 C 结构体对接才需要；纯 Rust 内部结构体重排是白赚的优化。
2. **冻结用 `repr(C)`，包装用 `repr(transparent)`**，然后用 const 断言把期望焊死在代码里——布局回归在 CI **编译期**失败，而不是运行时爆炸：

```rust
use std::mem::{size_of, offset_of};
#[repr(C)]
struct Header { magic: u32, len: u16, flags: u8 }
const _: () = assert!(size_of::<Header>() == 8);      // 7 向上取整到对齐 4 的倍数
const _: () = assert!(offset_of!(Header, len) == 4);  // 声明序 = 偏移序（repr(C) 保证）
fn main() {}
```

字段偏移只问 `offset_of!`，别用 `&field as *const _ as usize - base`——后者造了引用，在 packed 或半初始化对象上可能已经违约。
3. **字节级转译交给 `zerocopy`（0.8.x，crates.io 现值 0.8.61，2026-10-07）**：`FromBytes`/`IntoBytes`/`Unaligned`/`TryFromBytes` derive 把"这个类型可以按任意字节解释"变成可检查的契约，替代手写 `transmute`；它要求的 `repr(C)`/`repr(transparent)` + `assert_impl_all!` 纪律正是本节推荐的姿势。`bytemuck` 仍在服役但生态重心已移向 zerocopy（选型脉络见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)）。
4. **别给无 `repr` 的枚举做二进制序列化、内存快照、跨语言共享**。要用 tag 的协议用 `#[repr(u8)]` 字段-less 枚举或手写常量，把"布局"变成你自己的 API。
5. 性能侧的 padding/缓存行话题在 [Performance](/docs/CS/Rust/Performance.md)；`Vec`/`String` 堆块里具体存什么在 [Collections](/docs/CS/Rust/Collections.md)。

## Links

- [Smart Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Unsafe 与 FFI](/docs/CS/Rust/Unsafe_FFI.md)
- [Trait System](/docs/CS/Rust/Trait_System.md)
- [C 结构体布局](/docs/CS/C/Struct.md)
- [C++ 对象模型](/docs/CS/C++/ObjectModel.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [The Rust Reference: Type Layout](https://doc.rust-lang.org/reference/type-layout.html)
- [The Rust Reference: repr attribute](https://doc.rust-lang.org/reference/attributes/type_system.html)
- [std::mem::offset_of!](https://doc.rust-lang.org/std/mem/macro.offset_of.html)
- [std::mem::MaybeUninit](https://doc.rust-lang.org/std/mem/union.MaybeUninit.html)
- [Rust Release Notes (1.65.0 / 1.97.0 / 1.98.0 条目)](https://doc.rust-lang.org/stable/releases.html)
- [zerocopy (GitHub)](https://github.com/google/zerocopy)
