## Introduction

Rust 的"零成本抽象（zero-cost abstraction）"常被引用成"泛型不花钱"，这句话省略了主语：**泛型生成的机器码与你自己手写具体类型的版本等价，但机器码该有多少还是多少**。成本没有消失，只是从运行期搬到了另外三个地方——目标文件体积、编译时间、以及"每个下游 crate 都要重新生成一遍"的重复劳动。

本页用本机 `rustc` 实测把这三笔成本量化，并把 Rust 的编译模型和三种外来对照物讲清楚：C++ 模板（同样单态化，但没有约束、错误在实例化点才出现）、Java 泛型（类型擦除，运行期只有一份代码）、Go 1.18+ 泛型（既不是纯擦除也不是纯单态化，而是"模板 + 字典"）。一句话结论：Rust 泛型是**先按抽象类型做一次类型检查，再按具体类型无限次生成机器码**；它保证的是"不慢于手写"，从不保证"不膨胀"。

> [!NOTE]
> 实测环境：`rustc 1.98.1 (48a229cea 2026-09-01)`，target / host `aarch64-apple-darwin`，LLVM 22.1.8，8 逻辑核，一律 `-O`（等价 `opt-level = 3`）+ `--edition 2024`。C++ 侧用 Apple clang 16（`clang-1600.0.26.3`，`-std=c++20 -O2`），Go 侧 `go1.23.1 darwin/arm64`，Java 侧 OpenJDK 21.0.11。
> 本文所有体积与耗时数字都是**这一台机器上这一个版本的产物**，换 rustc 版本、换目标三元组、换优化级别都会变，不要当常量引用；但"泛型与手写等体积、元数据不随实例数线性增长"这类**比值关系**是编译器机制决定的，跨版本稳定。
> 当前 stable 已是 1.99.0（2026-10-01），本机为 1.98.1：只有 release notes 能给的版本归属会注明出处，不做"实测"声明。

## The Compilation Model

### Type Checking Ignores the Instantiation

泛型函数体在**定义处**就被完整类型检查一次，检查依据只有你写下的 trait bound——这一步与"谁调用它、用什么类型调用"无关。所以下面这行代码即使从未被实例化也报错（实测，`--emit=metadata` 不做 codegen）：

```rust
pub fn broken<T>(x: T) -> T { x + 1 }
```
```text
error[E0369]: cannot add `{integer}` to `T`
help: consider restricting type parameter `T` with trait `Add`
  | pub fn broken<T: std::ops::Add<i32, Output = T>>(x: T) -> T { x + 1 }
```

编译器直接给出补约束的建议，因为它在报错时**只知道 `T`**，不需要猜任何实例化。反过来，约束写全了但某个调用方不满足，错误就落在调用点：

```rust
use std::fmt::Display;
pub struct NoDisplay;
pub fn show<T: Display>(x: T) { println!("{x}"); }
pub fn go() { show(NoDisplay); }
```
```text
error[E0277]: `NoDisplay` doesn't implement `std::fmt::Display`
  = note: required by a bound in `show`
```

这两条合起来就是 Rust 与 [C++ 模板](/docs/CS/C++/Templates.md)最本质的差别：**Rust 把泛型体当成一个"约束即接口"的普通函数检查，C++ 把泛型体当成一段"要到实例化才懂"的文本**（clang 侧实测见后文专节）。

### Code Is Generated Where the Type Becomes Known

泛型函数本身不产生任何机器码；只有当某个 crate 用具体类型调用它时，rustc 才把该函数的 MIR 复制一份、把所有 `T` 换成具体类型、交给 LLVM 优化——这就是单态化（monomorphization）。它在编译管线中的位置见 [编译过程（rustc）](/docs/CS/Rust/compile.md)。

这一点可以精确测出来。构造两个库：一个只导出泛型 `cost<T>`（库内不调用它，所以没有任何实例化点），一个导出 14 份手写具体函数。实测 `--crate-type lib` 产出的 rlib：

| 库的内容 | rlib 内目标文件的 `.text` | rlib 文件体积 |
| :-- | --: | --: |
| 只有泛型 `cost<T: Scalar>` | 0 B | 44,632 B |
| 14 份手写 `cost_u8` … `cost_isize` | 22,008 B | 57,584 B |

再用一个消费方把 14 个类型全调用一遍：两个版本的最终可执行文件 `.text` **都是 255,564 B，都含 12 个 `cost` 函数**。

结论有两半：泛型代码不在 `.rlib` 里（库里只存类型检查产物），所以**下游实例几个类型就生成几份**；手写具体函数则相反——写一次，链一次。这决定了泛型"省库体积、费下游编译"的性格。

## Monomorphization Cost Is Measurable

### Experiment Design

同一个函数体、三种写法对比（`--crate-type lib --emit=obj`，`-O`）：

- **泛型**：一个 `#[inline(never)] fn cost<T: Scalar>(a: T, b: T, n: u32) -> T`（函数体就是下面那段），再加 14 个 `#[unsafe(no_mangle)] extern "C"` 包装函数，把它实例化到 14 个类型（`u8 u16 u32 u64 u128 i8 i16 i32 i64 i128 f32 f64 usize isize`）。实测跑了两份斜率：一份用下面这个短函数体，一份把 `while` 里的语句重复到 60 条。
- **手写**：把同一个函数体复制 14 遍，`cost_u8` / `cost_f64` …，包装函数完全相同。1067 行源码。
- **擦除**：见下一节。

`Scalar` 只是把运算符收进约束的 trait；`#[inline(never)]` 阻止 LLVM 把函数体吸进包装函数，否则量的就不是函数体本身：

```rust
use std::ops::{Add, Mul, Sub};

pub trait Scalar:
    Copy + Add<Output = Self> + Mul<Output = Self> + Sub<Output = Self> + PartialOrd + Default
{}
impl<T> Scalar for T where
    T: Copy + Add<Output = T> + Mul<Output = T> + Sub<Output = T> + PartialOrd + Default
{}

#[inline(never)]
pub fn cost<T: Scalar>(a: T, b: T, n: u32) -> T {
    let mut acc = T::default();
    let mut x = a;
    let mut k = b + b;
    let mut i = 0u32;
    while i < n {
        let t = x * b + k;
        if t > x { x = t - b; acc = acc + x; k = k + k; } else { x = t + b; k = b + b; }
        i += 1;
    }
    acc + x
}

pub fn use_three() -> u128 {
    cost(1u8, 2u8, 3) as u128 + cost(1f64, 2.0, 3) as u128 + cost(1u64, 2u64, 3) as u128
}
```

体积用 `size -m xxx.o | grep __text`（Mach-O 段大小），符号与逐函数长度用 `nm -n` + `objdump -d`，耗时用 Python `perf_counter` 包住 `rustc` 取 5~7 次中位数。

### Code Size

| 实例化数 N（长函数体，循环 60 条语句） | `.text` 泛型 | `.text` 手写 | `.rmeta` 泛型 | `.rmeta` 手写 |
| --: | --: | --: | --: | --: |
| 1 | 1,580 B | 1,580 B | 3,618 B | 3,522 B |
| 14 | 22,232 B | 22,232 B | 5,473 B | 8,573 B |

上面那段短函数体按 N 逐个扫一遍，膨胀的线性形状更清楚（`.text` 一列同时是泛型与手写的值，**每一行都相等**；每个实例只有百来字节）：

| N | 1 | 2 | 4 | 8 | 14 |
| :-- | --: | --: | --: | --: | --: |
| `.text` (B) | 104 | 208 | 368 | 808 | 1224 |
| `.rmeta` 泛型 (B) | 3,568 | 3,902 | 4,155 | 4,659 | 5,422 |
| `.rmeta` 手写 (B) | 3,472 | 3,959 | 4,518 | 5,635 | 7,737 |

三件事同时成立，这就是"零成本"的准确形状：

1. **泛型 = 手写**：每个类型的函数体逐个对齐（`u8` 1,548 B / 387 条指令，`u32` 1,472 B / 368 条，`u128` 3,396 B / 849 条，`f64` 1,568 B / 392 条，两边完全一致）。不是"近似"，是同一个数量。
2. **膨胀是真的**：小函数体表里 14 个类型 = 1,224 B，摊下来约 87 B/类型，与函数体大小成正比；换成 60 行的函数体就是 22,232 B。泛型不会替你省掉这份代码，因为对机器码而言**从来就是 N 份**。
3. **省的是元数据不是机器码**：`.rmeta`（类型检查产物）在泛型版里从 3,618 B 只涨到 5,473 B（函数体只存一份），手写版从 3,522 B 涨到 8,573 B（14 份 body 都要存）。N=14 时元数据差 1.57 倍，源码行数差 8.1 倍（1,067 行对 131 行）。

### Compile Time

中位数（ms），同一台机器同一份源码：

| 版本 | `--emit=metadata`（只做类型检查） | `--emit=obj`（含 LLVM codegen） |
| :-- | --: | --: |
| 泛型 N=1 | 39.6 | 132.2 |
| 手写 N=1 | 37.6 | 108.9 |
| 泛型 N=14 | **40.6** | **1167.9** |
| 手写 N=14 | **91.3** | **955.6** |

- 类型检查阶段泛型便宜 **2.25 倍**（40.6 vs 91.3 ms）：从 N=1 到 N=14，泛型版几乎不动（+1.0 ms），手写版跟着源码行数长（+53.7 ms）。这与 `.rmeta` 的结论同源——**函数体只被类型检查一次**。
- codegen 阶段泛型反而**慢 22%**（1167.9 vs 955.6 ms）。这不是意外：两边最终都要把 14 个函数交给 LLVM，而泛型版多做了一遍"复制 MIR + 逐实例替换类型参数 + 实例缓存查找"。所以"零成本抽象"在编译期是**负收益**的，代价随实例数增长。
- 这个差距不是并行度造成的：显式指定 `-C codegen-units=1 / 8 / 16`，泛型版分别测得 1163.8 / 1191.1 / 1163.6 ms，手写版 950.9 / 954.7 / 961.4 ms，比例不变。

### Runtime

同一份二进制里交替计时（20,000 次调用 × 内层 2,000 次迭代，结果相等）：

| 类型 | 泛型实例 | 手写副本 |
| :-- | --: | --: |
| `u32` | 3264 / 3277 / 3280 ms | 3268 / 3448 / 3620 ms |
| `f64` | 7163 / 7339 / 7467 ms | 7116 / 7154 / 7444 ms |

差异在噪声内，而且**必须**在噪声内：两边的指令条数逐函数完全相等，只是寄存器分配不同（`u8` 版 387 条指令里有 90 条是操作数顺序 / 寄存器编号的差别）。这就是"零成本"的字面兑现方式：**不是生成了更快的代码，而是生成的代码本来就该长这样**。

## Contrast With C++ Templates

本机 Apple clang 16（`-std=c++20 -O2`）实测把这个差别钉死：`template <class T> T broken(T x) { return x + 1; }` **只要不实例化就干净编译通过**（退出码 0，因为 `x + 1` 是依赖名，编译期不查）；一旦强制实例化 `template std::vector<int> broken(std::vector<int>);`，同一行代码立刻报 `invalid operands to binary expression` 并连带 61 行诊断，绝大部分是标准库里逐个 `operator+` 重载的 `candidate template ignored`。给模板换成 C++20 约束 `template <std::integral T>` 后，诊断缩到 13 行且第一句就指向"约束不满足"——**这一步 Rust 从第一天就是默认行为**。体积上两者同构：14 个类型的模板版（26 行源码）与手写 14 份（169 行源码）编译后 `.text` 都是 1,780 B，14 个函数地址完全一致，所以"按类型生成代码 = 按类型膨胀"是共性，不是 Rust 的特点；两边机制层面的完整对照见 [C++ 模板与泛型](/docs/CS/C++/Templates.md)。

## What rustc Reuses and What It Does Not

C++ 世界里对付这种膨胀的经典手段叫 **parameter sharing**：把"与模板参数无关的部分"提到一个以 `void*` / 基类指针为参数的公共函数里，让所有实例共享一份。Rust 里对应的机制只有三条，边界要划清：

1. **只实测到"完全相同的函数才合并"**。14 个实例化只占 12 个不同的函数地址（同一目标文件里就已经重叠）：`cost::<usize>` 与 `cost::<u64>` 地址相同，`cost::<isize>` 与 `cost::<i64>` 地址相同——因为 `usize`/`u64` 在本目标上就是同一个 LLVM 类型。符号仍然有 14 个，只是同一份代码。同理，56 个逐字相同的包装函数会被优化器折叠成 14 个。
2. **稳定版没有"按布局共享代码"的开关**。`-C share-generics` 在本机 rustc 1.98.1 上直接报 `error: unknown codegen option: share-generics`；它也不在 Cargo 的 profile 文档里。凡是把 `share-generics` 当稳定可调项来写的文章都对不上当前工具链，别照抄。
3. **真正可控的手段是"把类型无关的部分写成非泛型函数"**，也就是手写版的 parameter sharing：一个 `fn shared(...)` 里做所有与 `T` 无关的工作，泛型函数只留一个薄薄的、可以随意被复制的壳。判断标准很机械：**函数体里每一行按 `T` 特化后仍然相同的代码，都是本可以共享而 rustc 不会替你去共享的代码**。

vtable 与 `dyn` 的机制、对象安全规则在 [Trait 系统](/docs/CS/Rust/Trait_System.md)；`Box<dyn _>` 的内存布局在 [内存布局](/docs/CS/Rust/Memory_Layout.md)。

## Erasing the Type to Buy Back Size

把 `F: Fn(u64) -> u64` 换成 `&dyn Fn(u64) -> u64`，代码复制立刻停止：类型不再是编译期参数，而是一份运行期 vtable。同一个驱动函数（40 条混淆运算的循环体）配 8 个不同闭包，实测本 crate 自己的代码：

| 写法 | 本 crate `.text` 中相关函数 | 结构 |
| :-- | --: | :-- |
| 泛型 `fn driver<F: Fn(u64) -> u64>(...)` | 11,476 B / 17 个函数 | `driver` 8 份 × 1,160 B（闭包体已内联进去）+ `map_sum` 8 份 × 144 B |
| `fn driver_dyn(f: &dyn Fn(u64) -> u64, ...)` | 3,040 B / 19 个函数 | `driver_dyn` 1 份 1,168 B + 8 个闭包 20 B + 8 个 `FnOnce::call_once` 转发壳 20 B |

体积差 **3.8 倍**，但代价不是免费的，而且形态很反直觉——**取决于被擦除的调用在热路径上出现的频率**（`Instant` 单进程交替计时，量级参考）：

| 场景 | 泛型 | `&dyn Fn` |
| :-- | --: | --: |
| 每元素一次调用（200 万元素 × 8） | 0.165 ~ 0.169 ns/元素 | 0.937 ~ 0.972 ns/元素（**约 5.7 倍**） |
| 每次调用做 30,000 轮大循环（8 次调用一组） | 18.1 ~ 20.2 ms | 18.1 ~ 19.0 ms（**看不出差别**） |

第二个场景是"擦除几乎白拿"：每轮 40 条运算只摊一次虚调用，差距直接落进噪声。第一个场景是"擦除不可接受"：0.17 纳秒的工作里塞一次取 vtable + 间接跳转（多出约 0.77 纳秒），还把内联与常量传播全切断。所以判断标准不是"泛型慢、dyn 快"这种口号，而是**每个被擦除的调用点平均承担多少计算量**。表里那 8 个 20 B 的 `FnOnce::call_once` 转发壳也是擦除的固定成本：闭包要适配到 trait，就得为每个具体闭包类型生成一个 shim（对象安全与 vtable 规则见 [Trait 系统](/docs/CS/Rust/Trait_System.md)，`Rc`/`Arc` 与 `Box<dyn>` 的选型见 [智能指针](/docs/CS/Rust/Smart_Pointers.md)）。

> [!WARNING]
> 擦除**不必然**缩小产物。本机一个驱动体更小的对照实验里，泛型 2,140 B 对擦除 1,848 B 只差 14%——因为擦除版仍要为每个闭包留一份函数体加一个 `call_once` 转发壳。判断口径只能是"量自己 crate 的代码"，不能套"擦除一定省体积"。

## Trait Bound Syntax

### Bounds Are Set Unions

约束是集合，`+` 求交，多个 `impl` 约束同时成立才可选中。类型参数一多就得换 `where`，两个位置可以混用：

```rust
use std::fmt::Display;
pub fn pick<A, B, C>(a: A, mut b: B, c: C) -> String
where
    A: Display,
    B: Iterator<Item = A>,
    C: for<'x> Fn(&'x A) -> bool,
{
    match b.find(|x| c(x)) { Some(x) => format!("{x}"), None => format!("{a}") }
}
```

`where` 只是排版，不改变单态化身份：实例的键仍是"类型实参 + 生命周期 + const 实参"的完整元组。

### The Implicit Sized Bound and Its Escape Hatch

每个泛型类型参数都**隐含** `Sized`，这不是文档习惯而是语言规则；要接受 `str` / `[T]` / `dyn Trait` 必须显式撤掉：

```rust
use std::fmt::Display;
pub fn a<T: Display>(x: &T) { let _ = x.to_string(); }
pub fn call_a() { a("literal str"); }
```
```text
error[E0277]: the size for values of type `str` cannot be known at compilation time
note: required by an implicit `Sized` bound in `a`
```

写成 `T: Display + ?Sized` 就通过（实测），而且 `T` 仍可以是 `Sized` 的——`?Sized` 是"放宽"，不是"要求不定长"。两种写法都实测合法：`<T: Display + ?Sized>` 与 `where T: ?Sized`；反向的 `where T: Sized` 也能写，只是冗余。

### impl Trait in Two Positions

`impl Trait` 在参数位置和返回位置是**两件不同的事**，都在 1.26.0（2018-05-10）进入 stable：

| 位置 | 语义 | 谁选类型 | 代码生成 |
| :-- | :-- | :-- | :-- |
| `fn f(x: impl Display)`（APIT） | 语法糖，等价于 `fn f<T: Display>(x: T)` | **调用方** | 单态化，每个实参一份机器码 |
| `fn f() -> impl Iterator<Item = u8>`（RPIT） | 存在类型（opaque），藏住具体类型 | **实现方** | 函数体一份；泛型参数仍按实例复制 |

APIT 就是匿名类型参数，实测得到独立实例：`fn a(x: impl Display)` 被 `u32`、`f64`、`char` 调用后，目标文件里出现 `a::<u32>`、`a::<f64>` 与第三个函数——**别把 `impl Trait` 参数误当成"一种类型打天下"**。

RPIT 反过来：调用方看不到具体类型，因此也**不能**依赖它。它的两个边界都实测过：

- 只能出现在函数/方法的参数与返回位置。`let x: impl Sized = f();` → `error[E0562]: impl Trait is not allowed in the type of variable bindings`（see issue #63065）。
- 不能出现在类型别名里。`pub type A = impl Iterator<Item = u8>;` → `error[E0658]: impl Trait in type aliases is unstable`（see issue #63063），即 `type_alias_impl_trait` 至今 nightly。

edition 之间的一个真实差异也落在 RPIT 上（RFC 3498）。同一行代码，四个 edition 分别编译：

```rust
pub fn make<'a>(s: &'a str) -> impl Sized { s }
```

| 写法 | 2015 / 2018 / 2021 | 2024 |
| :-- | :-- | :-- |
| `-> impl Sized` | `error[E0700]: hidden type for impl Sized captures lifetime that does not appear in bounds` | 通过 |
| `-> impl Sized + use<'a>` | 通过 | 通过 |

2024 起所有在作用域内的泛型参数（含生命周期）被隐式捕获，所以旧 edition 的报错在新 edition 消失；而精确捕获 `+ use<..>`（RFC 3617，1.82.0 / 2024-10-17 起 stable）**在所有 edition 都可写**——它是跨 edition 的通用逃生舱，不是 2024 专属。细节与生命周期含义见 [Lifetime](/docs/CS/Rust/Lifetime.md)。trait 里的 `impl Trait`（RPITIT）自 1.75.0（2023-12-28）stable。

## Const Generics

最小常量泛型（`min_const_generics`）自 **1.51.0（2021-03-25）** stable，官方 release notes 的措辞是"Only values of primitive integers, `bool`, or `char` types are currently permitted"。这个限制今天仍然是硬边界，实测三条诊断：

```rust
pub fn f<const N: f64>() {}      // error: `f64` is forbidden as the type of a const generic parameter
pub struct K(pub u8);
pub fn g<const N: K>() {}        // error: `K` is forbidden as the type of a const generic parameter
                                 //   = note: the only supported types are integers, `bool`, and `char`
pub struct P<const A: usize>([u8; A]);
pub fn h<const N: usize>() -> P<{ N + 1 }> { unimplemented!() }
// error: generic parameters may not be used in const operations
//   = help: const parameters may only be used as standalone arguments here, i.e. `N`
```

**表达式不行**（`N + 1` 直接拒收），这就是 generic const expressions 的位置；`const N: f64` 也不是"暂时不稳定"，而是当前 stable 语言里根本不存在的类型域。仍停留在 nightly 的相关 gate（名字与 tracking issue 都取自 nightly Unstable Book，2026-10-07 抓取，逐条 200）：

| feature gate | tracking issue | 覆盖什么 |
| :-- | :-- | :-- |
| `generic_const_exprs` | rust-lang/rust#76560 | 上面 `P<{ N + 1 }>` 那种依赖其它参数的常量表达式 |
| `adt_const_params` | rust-lang/rust#95174 | 用结构体 / 枚举当常量参数（配 `ConstParamTy`） |
| `unsized_const_params` | rust-lang/rust#95174 | 不定长类型作常量参数 |
| `min_generic_const_args` | rust-lang/rust#132980 | 让常量实参本身可以是一个泛型常量参数 |
| `generic_const_args` | rust-lang/rust#151972 | 同方向的更宽泛化（两者语义分工本页未逐项核实） |

已经落地的一条：**显式推断常量实参 `_`** 自 1.89.0（2025-08-07）stable（release notes 原文 "Stabilize explicitly inferred const arguments (`feature(generic_arg_infer)`)"），本机 1.98.1 与 pin 的 1.95.0 工具链都实测通过：

```rust
pub fn takes<const N: usize>(_x: [u8; N]) {}
pub fn infer() {
    let _: [u8; _] = [0u8; 4];   // 数组长度从实参推出来
    takes::<_>([0u8; 6]);        // turbofish 里用 `_` 让常量参数参与推断
}
```

const 参数**参与实例身份**，所以它是第二个膨胀维度：`fn fill<const N: usize>(...)` 用 `N = 4 / 8 / 16 / 64` 各调用一次，目标文件里出现 4 个不同函数、`.text` 合计 9,896 B（`N = 64` 那份最大，因为定长循环按 `N` 展开了）。这解释了为什么 `Vec<[u8; N]>` 在 N 变化频繁时会一份一份长出来。

泛型与 FFI 的接口不兼容也在这里暴露：给泛型函数挂 `#[unsafe(no_mangle)]` 在本机是警告 `functions generic over types or consts must be mangled`（lint `no_mangle_generic_items`），因为"未单态化的泛型没有唯一符号"；按 release notes 自 1.99.0 起该 lint 升为 hard error（本机 1.98.1 尚未生效，不声明实测）。

`const fn` 里的泛型约束是另一条时间线：`const fn` 支持泛型 trait bound 与 `impl Trait` 参数/返回自 1.61.0（2022-05-19）；常量求值本身发生在 MIR 解释器阶段，见 [编译过程](/docs/CS/Rust/compile.md)。

## Inlining and Optimization Settings

单态化和内联是**两层不同的复制**，混淆它们会得出错误结论：

- 单态化按**类型实参元组**复制：`cost::<u32>` 是一个实例，无论它被调用 1 次还是 100 次。
- 内联按**调用点**复制：`#[inline(always)]` 会把已经单态化出来的函数体再按每个调用点铺一遍。

实测（14 个类型 × 4 个各不相同的调用点 = 56 个调用点，`opt-level = 3`）：

| 属性 | `.text` | `--emit=obj` 耗时 |
| :-- | --: | --: |
| `#[inline(never)]` | 23,220 B | 1,189 ms |
| 不写（默认启发式） | 23,220 B | 1,181 ms |
| `#[inline(always)]` | **100,372 B** | **4,586 ms** |

即：默认策略下 LLVM 判断这个 1.5 KB 的函数不值得内联，体积与 `inline(never)` 相同；强制 always 后体积 4.3 倍、编译时间 3.9 倍。**"泛型导致膨胀"在很多真实案例里其实是"泛型 + 强制内联导致膨胀"**，先把 `#[inline(always)]` 拿出来量一遍再怪泛型。

优化级别同理：`opt-level = 0` 121,872 B → `= 3` 22,232 B → `= z` 19,024 B（同一 N=14 泛型库）。`codegen-units` 在本例只影响并行度，不影响产物（见上文表格）。这些开关的**配置写法**（profile 继承、`lto` 的四个合法值、`-C linker-plugin-lto`、PGO）不在本页，见 [Cargo 构建配置](/docs/CS/Rust/Cargo.md) 与 [性能与调优](/docs/CS/Rust/Performance.md)；符号名如何被单态化实参影响见 v0 mangling（自 1.97.0，2026-07-09 起是默认方案，实测符号形如 `__RINvCsgroNwgXTkPB_6mono144costdEB2_`，`nm | c++filt` 可还原成 `mono14::cost::<f64>`）。

## Auto Traits under Generics

`Send` / `Sync` / `Unpin` 这类 auto trait 是**结构性**推导的：一个泛型类型是否 `Send`，取决于它的字段类型是否 `Send`，不需要你写 `impl`。实测三种情况：

```rust
use std::marker::PhantomData;
use std::rc::Rc;
pub struct W<T>(pub PhantomData<T>);
pub fn assert_send<T: Send>() {}
pub fn ok() { assert_send::<W<u8>>(); }        // 通过
pub fn bad() { assert_send::<W<Rc<u8>>>(); }   // E0277: `Rc<u8>` cannot be sent between threads safely
                                               // note: required because it appears within the type `PhantomData<Rc<u8>>`
```

关键在于这条推导对 `PhantomData<T>` 也算数：`PhantomData<T>` 的 `Send`/`Sync` 性跟着 `T` 走（`*const T` 作参数就整体 `!Send`，实测同样报 E0277）。

反过来，**擦除会切断自动推导**，这是并发代码里最常见的一个坑：`dyn Trait` 不会自己继承 auto trait，必须手写：

```rust
pub struct H { pub f: Box<dyn Fn()> }
pub fn assert_send<T: Send>() {}
pub fn bad() { assert_send::<H>(); }
```
```text
error[E0277]: `(dyn Fn() + 'static)` cannot be sent between threads safely
note: required because it appears within the type `Box<(dyn Fn() + 'static)>`
```

改成 `Box<dyn Fn() + Send>` 才成立。RPIT 同理：隐藏类型里的 auto trait 会"漏"给调用方，但返回类型里没写的就不会被承诺。泛型函数自身几乎不需要操心这点——只有当你把 `T` 送进线程或共享状态，才要写 `T: Send`：

```rust
use std::rc::Rc;
pub fn hidden() -> impl Sized { Rc::new(1u8) }
pub fn needs_send<T: Send>(_t: T) {}
pub fn bad() { needs_send(hidden()); }
// error[E0277]: `Rc<u8>` cannot be sent between threads safely
//     ---------- within this `impl Sized`   （诊断直接指向 RPIT 的隐藏类型）
```

`Send`/`Sync` 的完整语义与线程边界见 [并发](/docs/CS/Rust/Concurrency.md)。

## PhantomData and Variance

`PhantomData<T>` 声明一个"逻辑上拥有但物理上不存在"的 `T`，它没有运行时体积（见 [内存布局](/docs/CS/Rust/Memory_Layout.md)），却同时影响三件编译期事：自动推导的 `Send`/`Sync`（上一节）、所有权与生命周期的使用标记、以及**变型（variance）**。

变型决定 `Wrapper<&'long T>` 能否当成 `Wrapper<&'short T>` 用。默认按参数出现的位置推导，而 `PhantomData` 是唯一能手工指定它的手段：

```rust
use std::marker::PhantomData;
pub struct Inv<T>(PhantomData<fn(T) -> T>);   // 不变；换成 PhantomData<fn(T)> 就是逆变
pub fn inv_bad<'a, 'b: 'a>(x: Inv<&'b str>) -> Inv<&'a str> { x }   // 报错
```
```text
error: lifetime may not live long enough
  = note: requirement occurs because of the type `Inv<&str>`, which makes the generic argument `&str` invariant
  = note: the struct `Inv<T>` is invariant over the parameter `T`
```

同一份代码放进 `Cov<T>(PhantomData<T>)`（协变）就通过。`Vec<T>`、`Option<T>` 因为内部真的持有 `T` 而协变；任何带内部可变性的容器（`Cell<T>`、`UnsafeCell<T>`，实测同样给出 "invariant" 提示）必须不变，否则就是类型漏洞。选哪个 `PhantomData` 形状（`fn(T)->T` / `fn(T)` / `fn() -> T`）等价于在声明"我打算怎么用这个 T"。生命周期的完整变型规则与 `'static` 边界见 [Lifetime](/docs/CS/Rust/Lifetime.md)。

## Contrast With Java and Go

四种语言对"同一个函数体服务多个类型"的处理，逐条对照（每一列都在本机编译器上验证过）：

| 维度 | Rust 泛型 | C++ 模板 | Java 泛型 | Go 1.18+ 泛型 |
| :-- | :-- | :-- | :-- | :-- |
| 编译期检查依据 | trait bound，定义处一次通过 | 无约束（C++20 concepts 可选），要实例化才知道 | 类型参数 + 上界，擦除前检查 | constraint（本质是接口），定义处检查 |
| 产物形态 | 每个类型实参元组一份机器码 | 每个实参一份机器码 | **一份**擦除后的方法 | 每个实例化一份代码 **+** 每个类型参数一份字典 |
| 运行期是否知道 `T` | 否，生成的机器码里不留任何 `T` 的元数据 | 否（除非显式要求 `typeid`） | 否（只剩反射可见的 `Signature` 属性） | **是**，字典里带 rtype / GC 形状 |
| 值类型是否装箱 | 不装箱，布局按 `T` 定 | 不装箱 | 必装箱（`List<Integer>` 存引用） | 不装箱，但走字典间接 |
| 膨胀位置 | `.text` 与编译时间 | `.text` 与编译时间 | 无膨胀（代价是装箱与检查 cast） | `.text` + 字典数据 |
| 本机实测 | 14 实例 = 22,232 B `.text`，与手写 14 份逐字节等量 | 26 行模板 = 1,780 B，169 行手写 = 1,780 B，函数地址完全一致 | 一个 `max` 方法，调用点插 `checkcast` | 7 个 `go.shape` 函数体 + 7 个 `..dict.` 字典（各 64 B，`func() int` 520 B） |

**为什么 Java 的 `List<T>` 运行时不知道 `T`，而 Rust 的每个实例化都是不同机器码？** 因为两者要解决的是不同问题。

Java 的泛型（1.5 起）是**类型检查期的附加层**：`javac` 用它验证用法，然后擦掉，字节码里只留下界类型，连 `new T[10]` 都不允许（`error: generic array creation`）。本机 `javap -c` 实测，`class Gen<T extends Comparable<T>> { T max(T a, T b) }` 编译后的方法签名是 `max(Ljava/lang/Comparable;Ljava/lang/Comparable;)Ljava/lang/Comparable;`——**一个方法服务所有 `T`**；调用点看到的是 `invokevirtual max:(Comparable...)Comparable` 紧跟一条 `checkcast java/lang/String`，`Gen<Integer>` 与 `Gen<String>` 是同一个 `Class` 对象（`new ArrayList<Integer>().getClass()` 打印 `class java.util.ArrayList`）。既然运行期只有一份方法、一个 `Class`，`T` 就不可能留下任何信息，于是 `o instanceof T` → `error: Object cannot be safely cast to T`，`new T()` → `error: unexpected type`，`new T[10]` → `error: generic array creation`，`(T[]) new Object[3]` 只有 `warning: [unchecked] unchecked cast`。协变返回还额外需要一座桥：`StrNode` 里除了 `public String get()` 还多出一个 `public Object get()`，标志位是 `ACC_PUBLIC, ACC_BRIDGE, ACC_SYNTHETIC`——这个编译器伪造的方法就是"桥接方法（bridge method）"。

Rust 的方向恰好相反：**泛型是 codegen 的输入，不是 codegen 之后被抹掉的注释**。`Vec<u8>` 与 `Vec<String>` 的元素大小、对齐、是否 `Drop`、`Send`/`Sync` 推导全都不同，这些差异必须在编译期钉死（不然所有权与布局无法成立），所以实现方式是"为每种组合真的生成一个函数"，代价是膨胀、收益是运行期零信息、零间接。

Go 站在中间：它既没有 Rust 的编译期所有权约束，也不接受 Java 的装箱，于是走"共享模板 + 传字典"。本机 `go1.23.1` 编译一个接受 `func(T) T` 回调的泛型函数 `Transform`，配 7 种实参，符号表里同时出现按 shape 生成的函数体（`main.Transform[go.shape.int]`、`main.Transform[go.shape.string]` …共 1,664 B）和**每种实参一个运行期字典**（`main..dict.Transform[int]` 等，各 64 B；`func() int` 的字典 520 B，因为要带 GC 程序）。但字典并没有替它省掉复制：7 份函数体合计 1,664 B，与手写 7 份的 1,616 B 基本等量，整个可执行文件只差 832 B（1,930,850 vs 1,930,018）。**也就是说 Go 的产物形状其实最接近 Rust——一样按类型铺代码——只是额外多一份字典换来运行期类型信息**；代价是热循环里每个涉及 `T` 的操作都要过一遍字典。

## When Zero Cost Holds

| 成本项 | 泛型的实际表现 | 依据 |
| :-- | :-- | :-- |
| 运行时间 | 与手写具体类型**没有差别**（指令条数逐函数相同） | 本机 `u32`/`f64` 交替计时 |
| 机器码体积 | 与手写具体类型**完全相同**，即"膨胀全额存在" | 22,232 B = 22,232 B |
| 类型检查 / 元数据 / 源码 | 函数体只算一次、只存一份、只写一遍 | 40.6 ms vs 91.3 ms；`.rmeta` 5,473 B vs 8,573 B；131 行 vs 1067 行 |
| codegen 时间 | 反而**更贵**（约 22%） | 1,167.9 ms vs 955.6 ms |
| 下游 crate | 每个实例化点重新生成一遍 | rlib 里 `.text` 为 0 B |

所以准确说法是：**Rust 泛型把"抽象的表达成本"降到手写水平，把"机器码成本"原封不动留给你，并且额外收一笔编译期与下游重复生成的税**。想控体积就去共享代码（非泛型外壳或 `dyn`），想控编译时间就减少实例化数量或给热库预先生成有限几个实例——这两种手段的取舍全在"每个调用点承担多少计算量"这一个问题上。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Trait 系统](/docs/CS/Rust/Trait_System.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)
- [性能与调优](/docs/CS/Rust/Performance.md)
- [C++ 模板与泛型](/docs/CS/C++/Templates.md)

## References

- [The Rust Reference — Generics](https://doc.rust-lang.org/reference/items/generics.html)
- [The Rust Book — Generic Data Types / Monomorphization](https://doc.rust-lang.org/book/ch10-01-syntax.html)
- [rustc-dev-guide — Monomorphization](https://rustc-dev-guide.rust-lang.org/backend/monomorph.html)
- [Rust Release Notes（1.51.0 min_const_generics / 1.89.0 generic_arg_infer）](https://doc.rust-lang.org/stable/releases.html)
- [The Rust Nomicon — Variance](https://doc.rust-lang.org/nomicon/subtyping.html)
- [Unstable Book — generic_const_exprs](https://doc.rust-lang.org/unstable-book/language-features/generic-const-exprs.html)
- [cppreference — Function templates](https://en.cppreference.com/w/cpp/language/function_template)
- [The Java Language Specification, Java SE 21 Edition — Chapter 4（类型擦除）](https://docs.oracle.com/javase/specs/jls/se21/html/jls-4.html)
- [Go 1.18 Release Notes — Generics](https://go.dev/doc/go1.18)
