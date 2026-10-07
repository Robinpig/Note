## Introduction

Rust 没有 `interface` 关键字，也没有继承，但 `Iterator::next`、`println!("{}", x)`、`for x in v`、`a + b` 对任意类型都能用。承担这件事的单一语言设施就是 **trait**：它同时是三样东西 —— 一组可被实现者填满的**接口**、一条写在泛型参数上的**约束**、以及一套可以喂给别人的**扩展方法**（blanket impl）。同一份 `trait Shape { fn area(&self) -> f64; }` 在 `<T: Shape>` 里是编译期查表、在 `dyn Shape` 里是一次间接跳转，而这两种语义**共用同一份声明**，这是 Rust trait 系统与 Java interface、C++ 抽象基类、Go interface 最根本的差异：别处的接口天然是运行时的，Rust 的接口默认是编译期的，运行时分发要显式付一笔钱来换。

本篇讲这套机制本身的边界：三条分发路径在单态化 / vtable / 决定时机上各自是什么，`dyn` 为什么有一堆"不许"（dyn compatibility，旧称 object safety），vtable 到底长什么样并且怎么量出来，associated type 与泛型参数的选择判据，GAT 与 `async fn` in trait 的死结，auto trait 的传染规则，orphan rule 与 coherence 的真实约束，以及 sealed / newtype / visitor 这几个绕不开的设计模式。边界：`async fn` 与 `dyn` 的完整限制、`Future` 的 poll 语义在 [Async.md](/docs/CS/Rust/Async.md)；单态化的代码膨胀与编译时间实测在 [Generics.md](/docs/CS/Rust/Generics.md)；生命周期 bound、`use<..>` 精确捕获在 [Lifetime.md](/docs/CS/Rust/Lifetime.md)；`Deref` / `Index` / 智能指针选型在 [Smart_Pointers.md](/docs/CS/Rust/Smart_Pointers.md)；`Drop` 与 drop glue 在 [Drop.md](/docs/CS/Rust/Drop.md)；运算符重载与 `From` / `Into` / `TryFrom` 约定在 [Error_Handling.md](/docs/CS/Rust/Error_Handling.md) 与 [Collections.md](/docs/CS/Rust/Collections.md)。**本篇所有"编译器会不会接受 / 报错原文 / 字节数"的断言都在本机 `rustc 1.98.1 (48a229cea 2026-09-01)`、目标三元组 `aarch64-apple-darwin`、`--edition 2024` 上实测**，换版本需重测。

## Three Identities of One Declaration

| 身份 | 典型写法 | 谁来选实现 | 何时选完 | 反例场景 |
| :--- | :--- | :--- | :--- | :--- |
| 抽象接口 | `fn f(s: &dyn Shape)` | 运行时对象自己带 vtable | 运行期 | 需要异构集合、插件边界 |
| 泛型约束 | `fn f<T: Shape>(s: &T)` | 调用点的类型推断 | 编译期，每个 `T` 一份码 | 想让同一函数处理多种 `Shape` |
| 扩展方法 | `impl<T: Iterator> MyExt for T` | 编译器按 bound 找 | 编译期（本质是第 2 行的入口） | 只想给某个具体类型加方法 |

第三种身份最容易被忽略，也最能解释"为什么 Rust 不需要扩展语法"：给 `Iterator` 加一条自己的方法只要一个 blanket impl，而方法用 `where Self: Sized` 兜住就不会破坏这个 trait 的 dyn 可用性：

```rust
trait Second: Iterator {
    fn second(&mut self) -> Option<Self::Item>
    where Self: Sized,
    { self.next(); self.next() }
}
impl<T: Iterator + ?Sized> Second for T {}
fn main() {
    let v = vec![10, 20, 30];
    println!("second = {:?}", v.iter().copied().second()); // 实测：second = Some(20)
}
```

代价是名字空间是全局共享的：两个 trait 给同一个类型带进同名方法，方法解析立刻歧义（实测 `d.go()` → **E0034: multiple applicable items in scope**，并逐条列出 "candidate #1 is defined in an impl of the trait `Fly`"）。这就是 std 里 `Iterator::count` 之类名字不能被随便 blanket 出去的原因，也是社区惯例把扩展方法收进独立 trait 的由来。

对照其他语言：**Java** 的 `interface` 是名义子类型且只有运行时形态（`invokeinterface`，方法表按接口偏移查）；**C++** 的抽象基类靠对象头一个 vptr，非虚函数根本不进表（见 [ObjectModel](/docs/CS/C++/ObjectModel.md)、[RTTI](/docs/CS/C++/RTTI.md)）；**Go** 的 interface 值是一张 `(itab*, data*)` 两字段胖指针，`itab` 把某个接口方法与某个具体类型的实现一次性绑定成函数指针表，而"这个类型满足这个接口"由编译器在赋值点当场证明（见 [Reflection](/docs/CS/Go/Reflection.md)）。Rust 的独特之处是：这三家的"接口"在 Rust 里全被 `trait` 一词吃掉，而其中只有 `dyn` 那一支需要付出与 Go/C++ 同级的运行时成本。语言级速览见 [Languages](/docs/CS/Languages.md)。

## Three Dispatch Paths

| 维度 | `<T: Trait>` 泛型 | `impl Trait` 参数位（APIT） | `impl Trait` 返回位（RPIT） | `dyn Trait` |
| :--- | :--- | :--- | :--- | :--- |
| 类型类别 | 通用（universal） | 通用，等价匿名 `T` | 存在（existential） | 动态 |
| 实现者何时确定 | 调用点推断 | 调用点推断 | 函数体内部 | 运行期随对象 |
| 分发方式 | 直接调用（可内联） | 直接调用（可内联） | 直接调用 | vtable 间接跳转 |
| 是否按类型复制函数体 | 是 | 是 | 否（无泛型入参，本体只编一份） | 否 |
| 异构集合 | 需 `Vec<Box<dyn Trait>>` | 同左 | 返回值只能是一种 | 天然支持 |
| trait 需 dyn compatible | 否 | 否 | 否 | **是** |
| 能被内联 / 特化到具体类型 | 是 | 是 | 是 | 否（跨 vtable 边界） |

单态化的"每个类型一份码"是可以在产物里数出来的。`#[inline(never)]` 挡住内联后，同一个泛型函数在 4 个类型上实例化出 4 个符号，而 `dyn` 版本只有 1 个（符号名是 v0 mangling，**自 Rust 1.97.0 起为默认**）：

```text
# rustc 1.98.1 -O --crate-type lib --emit asm，截自 .s 文件标签
__RINvCs41ryptVWyam_7m3_mono10sum_statichEB2_:   # 实例化 1
__RINvCs41ryptVWyam_7m3_mono10sum_staticmEB2_:   # 实例化 2
__RINvCs41ryptVWyam_7m3_mono10sum_statictEB2_:   # 实例化 3
__RINvCs41ryptVWyam_7m3_mono10sum_staticyEB2_:   # 实例化 4
__RNvCs41ryptVWyam_7m3_mono7sum_dyn:             # 非泛型，只此一个
```

四个泛型符号只差一个类型编码字母，对应 `u8` / `u16` / `u32` / `u64` 四次实例化；`sum_dyn` 因为不泛型只有本体。多写几个泛型参数是乘性膨胀，编译时间与体积的实测见 [Generics.md](/docs/CS/Rust/Generics.md)。

### APIT and RPIT Are Not the Same Feature

参数位的 `impl Trait` **只是匿名泛型参数**，因此它天生表达不了"两个实参同类型"：

```rust
use std::fmt::Debug;
fn pair(_a: impl Debug, _b: impl Debug) {}     // 两个互相独立的匿名类型
fn pair_same<T: Debug>(_a: T, _b: T) {}         // 想要同型必须回到 <T>
fn main() { pair("a", 1u8); pair_same(1u8, 2u8); }  // 两者均通过
```

返回位的 `impl Trait` 是**存在类型**：类型由实现方选定且**不可命名**，于是三条后果都能被编译器当场问出来。

第一，所有 `return` 分支必须是同一个隐藏类型，`if/else` 两支不同类型直接 E0308，并且 help 会明确劝你装箱：

```rust
fn iter(flag: bool) -> impl Iterator<Item = i32> {
    if flag { [1, 2].into_iter() } else { 0..3 }
}
```

```text
# rustc 1.98.1 实测
error[E0308]: `if` and `else` have incompatible types
  = note: expected struct `std::array::IntoIter<{integer}, 2>`
             found struct `std::ops::Range<{integer}>`
help: you could change the return type to be a boxed trait object
1 + fn iter(flag: bool) -> Box<dyn Iterator<Item = i32>> {
```

第二，隐藏类型不可命名 → 不能存进结构体字段，也不能在两个函数之间传递具体形状（要给返回类型起名字就得用 TAIT，至今 unstable，见下文）。第三，**递归不可能**：递归调用自己的返回类型里含它自己，只能装箱。

```rust
fn f(n: u32) -> impl Iterator<Item = u32> {
    if n == 0 { std::iter::empty() } else { std::iter::once(n).chain(f(n - 1)) }
}
```

```text
# rustc 1.98.1 实测
error[E0308]: `if` and `else` have incompatible types
  = note: expected struct `std::iter::Empty<_>`
             found struct `std::iter::Chain<std::iter::Once<u32>, impl Iterator<Item = u32>>`
help: if you change the return type to expect trait objects, box the returned expressions
```

选型判据因此很清晰：调用点要挑类型 → 参数位；只想藏住具体类型且**只有一种** → 返回位（比 `Box<dyn>` 省一次装箱和一次跳转，也不要求 dyn compatible）；返回值形状真的会随输入变 → `Box<dyn Trait>`。RPIT 的生命周期捕获在 edition 2024 改成"隐式捕获所有在作用域内的参数"，`use<..>` 写法（free RPIT 自 Rust 1.82.0、trait 内自 1.87.0）一律以 [Lifetime.md](/docs/CS/Rust/Lifetime.md) 为准。

## Dyn Compatibility Rules

术语：Reference 与编译器诊断现在统一写 **dyn compatible**（下文表格里的诊断原句均为本机抄录），并明确注记 "This concept was formerly known as object safety"（本机 1.95.0 与 1.98.1 的 E0038 输出都已是新词）。旧教程里的 "object safe / 对象安全" 是同一件事。

规则的成因只有一句：**能不能用一张固定的表把所有入口表达出来**。`dyn Trait` 的调用要变成 `(*(vtable.at(slot)))(&data, args)`，于是任何"槽位类型取决于具体实现者"的特性都违和。

| 禁止项 | 为什么（vtable 视角） | 实测错误码与诊断原句 |
| :--- | :--- | :--- |
| `Sized` 是 supertrait（`trait T: Sized`） | 对象本身 `!Sized`，与上界矛盾 | E0038 "...because it requires `Self: Sized`" |
| 关联常量 | 常量是**值**，不是可调用入口，表里没有它的槽 | E0038 "...because it contains associated const `N`" |
| 带泛型参数的方法 | 每个 `T` 一份机器码，槽位数随类型变化 | E0038 "...because method `read_as` has generic type parameters" |
| 方法签名里出现 `Self`（返回类型或除接收者外的参数） | `Self` 要到运行期才知道 | E0038 "...because method `clone_it` references the `Self` type in its return type" |
| 无 `self` 的关联函数 | 没有接收者就没法从胖指针拿到表 | E0038 "...because associated function `make` has no `self` parameter" |
| `async fn` | 脱糖后返回隐藏 Future 类型 | E0038 "...because method `fetch` is `async`" |
| 返回位 `impl Trait`（RPITIT） | 同上，隐藏类型不可命名 | E0038 "...because method `nums` references an `impl Trait` type in its return type" |
| 泛型关联类型（GAT） | 表里要写死的类型带了个没人能填的寿命参数 | E0038 "...because it contains generic associated type `Fut`" |
| 嵌套接收者 `self: Rc<Vec<Self>>` 等 | 拆不出唯一的对象指针 | 见 Reference 的 dyn-incompatible 例 |

泛型方法那例的实测输出如下。顺带一个容易困惑的点：`fn make() -> Self`（无接收者）被诊断成"没有 `self` 参数"而不是"`Self` 出现在返回类型" —— 一条 trait 同时犯多条规则时，编译器只报它先命中的那条：

```text
error[E0038]: the trait `Readable` is not dyn compatible
4 | fn use_obj(_: &dyn Readable) {}
  |                ^^^^^^^^^^^^ `Readable` is not dyn compatible
note: for a trait to be dyn compatible it needs to allow building a vtable
      for more information, visit <https://doc.rust-lang.org/reference/items/traits.html#dyn-compatibility>
1 | trait Readable {
  |       -------- this trait is not dyn compatible...
2 |     fn read_as<T>(&self, n: usize) -> T;
  |        ^^^^^^^ ...because method `read_as` has generic type parameters
  = help: consider moving `read_as` to another trait
```

最常被拿来试的例子是 `&dyn Clone`，它报的是另一句 —— "not dyn compatible because it requires `Self: Sized`"，因为 std 里 `pub trait Clone: Sized`，命中的是表格第一行。

三条逃生口，实测都可用：

```rust
trait MaybeSized {
    fn obj_ok(&self) -> u32;
    fn gated(self) -> u32
    where
        Self: Sized;              // 显式声明"这条不参与 dyn"
}
struct X(u32);
impl MaybeSized for X {
    fn obj_ok(&self) -> u32 { self.0 }
    fn gated(self) -> u32 { self.0 }
}
fn use_obj(o: &dyn MaybeSized) -> u32 { o.obj_ok() }
fn main() { let x = X(5); println!("dyn = {}, sized = {}", use_obj(&x), x.gated()); } // 实测：5, 5
```

1. `where Self: Sized`：方法被排除出 vtable，trait 仍然 dyn compatible（下面的槽位实测能看到它确实不在表里）。2. **`self` 值接收者隐含同一个上界**：`fn into_inner(self)` 不会让 trait 变不可用，`&dyn Consuming` 编译通过，但**调用点**才会炸：`error[E0161]: cannot move a value of type `dyn Consuming`` + `E0507`。这条经常被记反成"by-value 方法破坏 dyn 兼容性"。3. 把 `Self` 换成关联类型，并在对象类型里写死方向：`dyn Out<Item = u32>` 合法，`dyn Out` 则报 **E0191: the value of the associated type `Item` in `Out` must be specified**。

## The Shape of a vtable

`dyn Trait` 是 `!Sized`（`size_of::<dyn Trait>()` → E0277 "the size for values of type `dyn Trait` cannot be known at compilation time"），所以它只能出现在指针后面。胖指针的大小与"有几个方法"无关，恒为两个字：

| 类型 | 实测大小 | 类型 | 实测大小 |
| :--- | :--- | :--- | :--- |
| `&S`（`S` 为 Sized 结构体）、`*const S`、`fn()` | 8 | `&dyn Shape` / `&mut dyn Shape` / `Box<dyn Shape>` | 16 |
| `&[i32]` / `&str` | 16 | `&(dyn Shape + Send + Sync)`、`Option<&dyn Shape>` | 16 |

第二个字指向 vtable。当前实现里它的槽位顺序可以用裸读观察到：`[drop_in_place, size, align, 方法指针...]`。`size`/`align` 槽的存在有稳定 API 佐证 —— 对 `&dyn C` 调 `size_of_val` / `align_of_val` 能拿回 16 / 8，这正是具体类型 `S` 的值，说明这些信息确实存在对象里而不是编译期。

```text
# 以下观察值来自 rustc 1.98.1 -O / aarch64-apple-darwin：先用 transmute_copy 取出胖指针，
# 再裸读该地址。vtable 布局不是稳定 ABI，换编译器版本或优化级别都可能不同。
vtable: dynA=0x...090  dynB=0x...040  dynC=0x...060  dynA+Send=0x...090  dynA+Send+Sync=0x...090
size_of_val(&dynC)=16  align_of_val=8 （S 实际 16 / 8）
dynA 表:  [0x00] drop_in_place <非零>  [0x08] 0x10  [0x10] 0x8  [0x18] <S as A>::a
D2 表（两个方法，其中一个默认实现且未被覆写）: [0x18]=100d05a14 [0x20]=100d05a1c —— 默认实现自己占一槽
dynM3 表（m1 m2 m3 可分发 + by_value(self) + gated(where Self: Sized)）: 只有三个方法槽，两个不可分发方法都不在表里
dynC 表（trait C: A + B）: [0x18] <S as A>::a  [0x20] <S as B>::b  [0x28] = dynB 表地址
upcast dynC -> dynA 得到 dynC 自己那张表；upcast dynC -> dynB 得到 dynB 独立对象那张表
S::drop 打印（证明第 0 槽确实是 drop_in_place，Box<dyn C> 释放时走的正是它）
```

四个直接可写的结论：

- **默认实现也占一个槽**，未被覆写时表里放的是编译器为该类型生成的默认实现副本地址，`dyn` 调用它照样是一次真实跳转 —— 接口越宽，表越长，"反正有默认实现"省不掉运行时代价；而 `where Self: Sized` 与 `self` 值接收者的方法**不占槽**。
- **`Send` / `Sync` 这类 auto trait 不产生第二张表**：`dyn A`、`dyn A + Send`、`dyn A + Send + Sync` 拿到的是同一个 vtable 地址，它们没有方法槽位可放，约束只存在于类型系统里。这也意味着 `dyn Trait + Send` 的 `Send` 是**编译期的承诺**，运行时不会二次核验 —— 想骗过它只能靠 `unsafe impl`。
- `dyn A + B`（两个非 auto trait 拼一个对象类型）**根本不被接受**：**E0225 only auto traits can be used as additional traits in a trait object**，help 直接建议 "consider creating a new trait with all of these as supertraits"。所谓"多张表"只出现在这种**复合 supertrait** 形态里。
- 胖指针的第二个字无法在 stable 手工构造或拆解：`std::ptr::metadata` → `E0658 use of unstable library feature 'ptr_metadata'`（tracking issue #81513）。自己造 `dyn` 只能靠 coercion。

上面 `dynC` 那行实测最能说明"表"与"上转"的关系：主表把 `A`、`B` 的方法按层次摊平在一起，再额外放一个指向 `dyn B` 表的指针。也就是说，转到**主 trait**（声明里第一个非 auto trait）是免费的 —— 表前缀本来就兼容；转到**次 trait** 要沿着表里那个额外槽位跳一次。对照 C++：虚表每类一张、非虚函数不入表、`dynamic_cast` 依赖可选的 RTTI 附加表，见 [C++/ObjectModel.md](/docs/CS/C++/ObjectModel.md) 与 [C++/RTTI.md](/docs/CS/C++/RTTI.md)；Go 的 `itab` 则是"某个接口 × 某个类型"一张表，表里既有方法地址也带 `inter`/`_type` 反查信息，见 [Go/Reflection.md](/docs/CS/Go/Reflection.md)。

## Trait Upcasting

`dyn Sub → dyn Super` 曾经是手写 `unsafe` 或额外方法的禁区，现在分两步放开：

- **Rust 1.78.0 (2024-05-02)**：只允许 `dyn Trait → dyn Trait + Auto`，且那个 auto trait 必须是 `Trait` 自己声明的 supertrait。
- **Rust 1.86.0 (2025-04-03)**：放开到一般 supertrait（实测 `Box<dyn C> → Box<dyn A>` 与 `Box<dyn C> → Box<dyn B>` 都通过，1.95.0 与 1.98.1 行为一致）。

```rust
trait A { fn a(&self) -> u32; }
trait B { fn b(&self) -> u32; }
trait C: A + B {}
struct S;
impl A for S { fn a(&self) -> u32 { 1 } }
impl B for S { fn b(&self) -> u32 { 2 } }
impl C for S {}
trait Logged: Send { fn msg(&self) -> String; }
fn up_principal(x: Box<dyn C>) -> Box<dyn A> { x }             // 1.86.0：主 trait
fn up_second(x: Box<dyn C>) -> Box<dyn B> { x }                 // 1.86.0：次 trait
fn up_auto(x: Box<dyn Logged>) -> Box<dyn Logged + Send> { x }   // 1.78.0：追加已声明的 auto trait
fn main() { println!("{}", up_principal(Box::new(S)).a()); }
```

反过来不行：给一个既有对象类型**追加**一个它没声明过的 auto trait 仍然失败 —— `Box<dyn C + Sync> → Box<dyn C + Send + Sync>` 报 E0308 "expected trait `C + Send + Sync`, found trait `C + Sync`"。控制"多个 supertrait 时以哪个为上转入口"的 `#[upcastable]` 属性也还没有 stable 形态：本机写 `#[upcastable]` 得到 `error: cannot find attribute \`upcastable\` in this scope`（feature gate `multiple_supertrait_upcastable`）。

## Associated Type or Generic Parameter

判据只有一条：**这个类型参数相对于实现者是一个还是多个？**

```rust
trait Convert { type Target; fn convert(self) -> Self::Target; }
trait ConvertG<T> { fn convert(self) -> T; }
struct Src(u32);
impl Convert for Src { type Target = u32; fn convert(self) -> u32 { self.0 } }
impl ConvertG<u32> for Src { fn convert(self) -> u32 { self.0 } }
impl ConvertG<String> for Src { fn convert(self) -> String { self.0.to_string() } }
// impl Convert for Src { type Target = i64; .. }   // 打开即 E0119 conflicting implementations
fn main() { println!("{} {}", Convert::convert(Src(1)), ConvertG::<String>::convert(Src(2))); }
```

- 关联类型 ⇒ 每个实现者**恰好一个**结果类型，所以类型推断可以唯一反推（"我拿到 `Self::Target`，就知道是哪个 impl"）；再写第二个 impl 就是实测到的 **E0119**。
- 泛型参数 ⇒ 一个类型可实现多次，但编译器**无法从使用点反推**，所有调用都得写成 `ConvertG::<String>::convert(..)` 或由期望类型供给。
- 需要"关系"而不是"输出"时用泛型参数：`impl Add<u32> for Seconds`、`impl From<u32> for MyInt`（约定见 [Error_Handling.md](/docs/CS/Rust/Error_Handling.md)）。两种形态都能上 `dyn`，只要把参数写死：`dyn Convert<Target = u32>` 与 `dyn ConvertG<u32>` 都是合法的对象类型（本机实测），方法若是 `&self` 接收者还能照常分发（`&dyn ConvertG<u32>` 上调 `get()` 返回 7）；被禁止的一直是**方法自己带类型参数**（上文表格第 3 行的 E0038），而不是 trait 带参数。
- 泛型关联类型（GAT）是第三条路：既能表达"随输入寿命变化"又保持名义唯一，见下节。

想把 `impl Trait` 从函数签名搬到 `type T = impl Iterator<Item = u32>;` 是**至今不行**的：**E0658 "`impl Trait` in type aliases is unstable"**（tracking issue #63063，feature gate `type_alias_impl_trait`）；`impl Trait` 出现在关联类型位置同样是 E0658，同一编号 —— TAIT 与 `impl_trait_in_assoc_type` 是同一批未完成的地基，也正是 RPITIT 能存在的原因。

## GAT and the Price of async fn in Traits

GAT（generic associated types，Rust 1.65.0 (2022-11-03)）解决的是"关联类型自己还需要参数"。最典型的是**借用型迭代器**：`Iterator::Item` 与 `Self` 同寿，无法表达"每次 next 借出一个引用 self 内部缓冲区的 `&str`"。

```rust
trait LendingIterator {
    type Item<'a> where Self: 'a;
    fn next(&mut self) -> Option<Self::Item<'_>>;
}
struct Lines { buf: String, pos: usize }
impl LendingIterator for Lines {
    type Item<'a> = &'a str where Self: 'a;
    fn next(&mut self) -> Option<&str> {
        if self.pos >= self.buf.len() { return None; }
        let end = self.buf[self.pos..].find('\n').map_or(self.buf.len(), |i| self.pos + i + 1);
        let s = &self.buf[self.pos..end];
        self.pos = end;
        Some(s.trim_end())
    }
}
fn main() {
    let mut l = Lines { buf: "a bb\nccc dd\nee".to_string(), pos: 0 };
    let mut n = 0;
    loop { match l.next() { Some(line) => n += line.split_whitespace().count(), None => break } }
    println!("words = {n}"); // 实测输出 words = 5（edition 2021 同样通过）
}
```

每一轮取到的 `&str` 借用了 `self`，用完才能进下一轮 —— 这就是 "lending" 的含义；没有 GAT 时唯一的写法是每轮返回 `Vec<String>`，即每行一次堆分配。`async fn` in trait 的命运和 GAT 绑在一起也正因为如此：它自 Rust 1.75.0 (2023-12-28) 起与 RPITIT 互为糖衣，而 RPITIT 脱糖出来就是**带生命周期参数的关联类型**：

```rust
use std::future::Future;
trait Fetch {
    type Fut<'a>: Future<Output = u32> + 'a where Self: 'a;
    fn fetch(&self) -> Self::Fut<'_>;
}
fn obj(_: &dyn Fetch) {}   // error[E0038]: ...because it contains generic associated type `Fut`
```

同一条链解释了为什么 `#[async_trait]` 没过时：`async fn`（E0038 "...because method `fetch` is `async`"）、手写 RPITIT（"...because method `fetch` references an `impl Trait` type in its return type"，加 `+ 'static` 也一样）、以及上面的 GAT 版本，三种写法在 `dyn` 前全部撞墙；`async fn` **in `dyn` trait 至今 unstable**（feature gate `async_fn_in_dyn_trait`，本机 `#![feature(...)]` 得到 E0554 加 "the feature `async_fn_in_dyn_trait` is incomplete"，tracking issue #133119）。stable 上唯一能同时拿到"trait 里的异步方法"和"dyn 分发"的路子仍是装箱，把隐藏类型换成一个可写进表的对象类型（`#[async_trait]` 展开出来的就是它）：

```rust
use std::future::Future;
use std::pin::Pin;
trait Async: Send {
    fn fetch(&self) -> Pin<Box<dyn Future<Output = u32> + Send + '_>>;
}
struct F(u32);
impl Async for F {
    fn fetch(&self) -> Pin<Box<dyn Future<Output = u32> + Send + '_>> {
        let v = self.0;
        Box::pin(async move { v })
    }
}
fn call(o: &(dyn Async + Send + Sync)) -> Pin<Box<dyn Future<Output = u32> + Send + '_>> { o.fetch() }
fn main() { let f = F(5); let _ = call(&f); }  // &dyn Async 合法，装箱即绕开隐藏类型
```

代价一眼可见：每次调用一次装箱 + 表里多一条 `dyn Future` 的间接层，而且返回的 future 借用了 `self` —— 把签名里的 `'_` 换成 `'static` 当场得到 `error: lifetime may not live long enough`（本机实测）。`Pin`、`Send` 与 poll 语义的细节全部在 [Async.md](/docs/CS/Rust/Async.md)，本篇只记"为什么必须是装箱才能上 dyn"。

## Auto Traits

`Send` / `Sync` / `Unpin` / `UnwindSafe`（另有 `RefUnwindSafe`、`Sized` 的特殊地位）是 **auto trait**：不由人声明实现，编译器按结构递归推导，并且**只能加不能减** —— 想反悔必须在 `unsafe impl` 里自己承担后果。

| 写法 | 实测结果（1.98.1） |
| :--- | :--- |
| `struct WithRc { r: Rc<u8> }` → `assert_send::<WithRc>()` | E0277 "`Rc<u8>` cannot be sent between threads safely" + "required because it appears within the type `WithRc`" |
| `Wrap<Rc<u8>>` | 同上，逐层传染 |
| `assert_sync::<RefCell<u8>>()` | E0277 "`RefCell<u8>` cannot be shared between threads safely" |
| `struct WithRaw { p: PhantomData<*const u8> }` | `Send` 由 `unsafe impl Send` 手工恢复，`Sync` 仍 E0277（"`*const u8` cannot be shared ... appears within `WithRaw`"） |
| `assert_send::<&dyn P>()` | E0277，help 指出 "the trait `Sync` is not implemented for `dyn P`; required for `&dyn P` to implement `Send`" |
| `assert_send::<&(dyn P + Send)>()` | 仍 E0277（`&T: Send` 要的是 `T: Sync`，加 `Send` 没用） |
| `assert_send::<&(dyn P + Send + Sync)>()` / `Box<dyn P + Send + Sync>` | 通过 |
| `assert_unpin::<dyn P>()` | E0277 "`dyn P` cannot be unpinned" |

三条最容易记错的规则：

1. **`&T: Send` 当且仅当 `T: Sync`**。所以"能跨线程发送的共享引用"要写 `&(dyn Trait + Send + Sync)`，只加 `Send` 是最常见的无效修法。
2. **`dyn Trait` 默认既不是 `Send` 也不是 `Sync`**，除非把上界写进 trait 声明（`trait Logged: Send`）—— 因为对象的 `Send`-ness 取决于运行期塞进去的那个类型，编译器无法推导。这也解释了上一节实测的"auto trait 不进 vtable"：约束纯粹在类型系统层，运行时不核验。
3. `Unpin` 的自动推导以"所有字段 `Unpin`"为条件，`dyn Trait` 不满足；`unsafe impl Send for Handle { p: *const u8 }` 这类写法把责任从编译器转到你身上 —— 你必须保证跨线程访问确实安全，而 `Send` 里没有任何一行检查会替你把关（这是 `unsafe` 契约的一部分，见 [Unsafe_FFI.md](/docs/CS/Rust/Unsafe_FFI.md)）。`UnwindSafe` 只在 `catch_unwind` 附近有存在感，日常靠 `std::panic::AssertUnwindSafe` 显式放弃。

并发侧的语义与 `Send`/`Sync` 的关系、以及"为什么 Go/C++ 没有这套编译期推导"的对照，记在 [Concurrency.md](/docs/CS/Rust/Concurrency.md)。

## Orphan Rule, Coherence, and the New Solver

orphan rule 保证一个 `(trait, 类型)` 组合至多一个 impl，否则跨 crate 的两份实现会同时被合法选中。实测边界：

```text
error[E0117]: only traits defined in the current crate can be implemented for types defined outside of the crate
3 | impl Display for Vec<u32> {
  | ^^^^^^^^^^^^^^^^^--------
  |                  |
  |                  `Vec` is not defined in the current crate
  = note: impl doesn't have any local type before any uncovered type parameters
  = note: for more information see https://doc.rust-lang.org/reference/items/implementations.html#orphan-rules
  = note: define and implement a trait or type instead
```

`impl Display for Vec<My>` 同样被拒 —— 本地类型藏在 `Vec` 里不算数。合法的两条路是：**本地 trait**（`trait Inch { .. } impl Inch for f64` 永远合法）与 **newtype**（`struct Kilometers(f64); impl Display for Kilometers`）。反过来，**本地类型实现外部 trait**（`impl Display for My`）也合法，这正是 std 那些 trait 能被全生态实现的原因。

coherence 是同一枚硬币的另一面：blanket impl 与具体 impl 会重叠。

```text
error[E0119]: conflicting implementations of trait `Summary` for type `My`
3 | impl<T: Display> Summary for T { .. }   // first implementation here
6 | impl Summary for My { .. }              // conflicting implementation for `My`
```

重叠判定看的是**当前已存在的 impl 集合**：本机对照过，把 `impl Display for My` 删掉，上面两条 impl 立刻同时合法；补上它，第二条马上变 E0119。所以库作者写 blanket impl 就等于把"所有满足该 bound 的类型"全部占住，这也是 specialization（`specialization` / `min_specialization`，仍 unstable）想解决却还没解决的问题。

新求解器的进度必须说准：next-generation trait solver **自 Rust 1.84.0 (2025-01-09) 起用于 coherence**（修掉多个 soundness 问题），此后**只在 2026-08-21 起于 nightly 全面启用** —— 它**不是 stable 的默认行为**，别把 nightly 上的新诊断当成 stable 现状。

## Trait Design Patterns

- **sealed trait** —— 想彻底关死一个 trait 的实现入口，给它加一个私有模块里的 supertrait：

  ```rust
  mod priv_api {
      pub trait Sealed {}
      impl Sealed for u32 {}
  }
  pub trait Node: priv_api::Sealed { fn name(&self) -> String; }
  impl Node for u32 { fn name(&self) -> String { format!("num {self}") } }
  ```

  下游 crate 实现 `Node` 时先撞 E0277（"the trait bound `Foreign: Sealed` is not satisfied"），想直接实现 `Sealed` 则撞 E0603（"module `priv_api` is private"，附注 "trait `Sealed` is not publicly re-exported"）—— 两条均为本机跨 crate 实测。代价是 trait 变不可扩展，只在确实需要枚举全部实现者时用。

- **newtype** —— orphan rule 与 blanket-impl 冲突的共同解，还能顺带做单位区分（`Kilometers` vs `Miles`）。`#[repr(transparent)]` 保证与内部字段同布局，需要 `Deref` 代理时看 [Smart_Pointers.md](/docs/CS/Rust/Smart_Pointers.md)。

- **extension / blanket** —— 上面 `Second for T: Iterator` 那一类，标准库自己用得极多（`Iterator` 组合子大半是 `where Self: Sized`）。

- **visitor** —— 需要"异构节点 + 每个访问者处理全部节点"的双分派时，`&dyn Visitor` 是唯一能编译的形状（类型层无法表达这种互相递归的集合）：

  ```rust
  trait Expr { fn eval(&self, v: &dyn Visitor) -> f64; }
  trait Visitor { fn num(&self, n: f64) -> f64; fn add(&self, l: &dyn Expr, r: &dyn Expr) -> f64; }
  struct Num(f64);
  struct Add(Box<dyn Expr>, Box<dyn Expr>);
  impl Expr for Num { fn eval(&self, v: &dyn Visitor) -> f64 { v.num(self.0) } }
  impl Expr for Add { fn eval(&self, v: &dyn Visitor) -> f64 { v.add(&*self.0, &*self.1) } }
  struct LogAll;
  impl Visitor for LogAll {
      fn num(&self, n: f64) -> f64 { println!("  num {n}"); n }
      fn add(&self, l: &dyn Expr, r: &dyn Expr) -> f64 {
          let (a, b) = (l.eval(self), r.eval(self));
          println!("  add {a} + {b}");
          a + b
      }
  }
  fn main() {
      let e: Box<dyn Expr> = Box::new(Add(Box::new(Num(1.0)), Box::new(Add(Box::new(Num(2.0)), Box::new(Num(3.0))))));
      println!("= {}", e.eval(&LogAll));
  }
  ```

  实测输出 `num 1 / num 2 / num 3 / add 2 + 3 / add 1 + 5 / = 6` —— 两跳 `&dyn` 之间没有任何静态类型能追到递归终点。

- **`dyn Any` 兜底** —— trait 层次没法提前枚举时才用 `Box<dyn Any>` + `downcast_ref`（实测 `"u32 7" / "String hi" / unknown true`），代价是把分发推迟到运行期且丢掉了类型检查。它是 Rust 里唯一像样的运行时类型识别，`type_id` 本身也只是 vtable 上的一个方法。

## Diagnostics That Do Not Recommend

trait bound 不满足时，编译器会顺着所有 impl 找"最接近的候选"，blanket impl 会把这条建议带到沟里。Rust 1.85.0 (2025-02-20) 稳定的 `#[diagnostic::do_not_recommend]` 就是把某个 impl 从这条推荐链上摘掉。同一个程序，只删这一行属性：

```rust
trait Parse {}
impl Parse for String {}
#[diagnostic::do_not_recommend]
impl<T: Parse> Parse for Box<T> {}
fn takes(_: impl Parse) {}
fn main() { takes(Box::new(1u8)); }
```

```text
# 带属性时（rustc 1.98.1 实测）
error[E0277]: the trait bound `Box<u8>: Parse` is not satisfied
  |                   ^^^^^^^^^^^^^ the trait `Parse` is not implemented for `Box<u8>`
help: the trait `Parse` is implemented for `String`

# 去掉属性后：怪罪对象变成了内层类型，并且把那条泛型 impl 摆出来当"你可以实现它"
error[E0277]: the trait bound `u8: Parse` is not satisfied
help: the following other types implement trait `Parse`
3 | impl<T: Parse> Parse for Box<T> {}
note: required for `Box<u8>` to implement `Parse`
```

差别是实质性的：没属性时编译器顺着重叠的 blanket impl 一路推到 `u8`，给出的建议通常不是用户想做的事；有属性后它直接说 `Box<u8>` 不满足并把那条 impl 从推荐链上摘掉。写公开 trait 的 blanket impl 时，把 `do_not_recommend` 当成默认搭配；要自定义消息文本用 `#[diagnostic::on_unimplemented]`。

## Links

- [Generics](/docs/CS/Rust/Generics.md)
- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [ObjectModel](/docs/CS/C++/ObjectModel.md)
- [RTTI](/docs/CS/C++/RTTI.md)
- [Reflection](/docs/CS/Go/Reflection.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [The Rust Reference — Dyn compatibility](https://doc.rust-lang.org/reference/items/traits.html#dyn-compatibility)
- [The Rust Reference — Orphan rules](https://doc.rust-lang.org/reference/items/implementations.html#orphan-rules)
- [The Rust Reference — Auto traits](https://doc.rust-lang.org/reference/special-types-and-traits.html#auto-traits)
- [The Nomicon — Exotic sizes](https://doc.rust-lang.org/nomicon/exotic-sizes.html)
- [Rust Release Notes](https://doc.rust-lang.org/stable/releases.html)
- [rust-lang/rust#133119 — Tracking issue for `async_fn_in_dyn_trait`](https://github.com/rust-lang/rust/issues/133119)
- [rust-lang/rust#63063 — Tracking issue for `type_alias_impl_trait`](https://github.com/rust-lang/rust/issues/63063)
- [rust-lang/rust#81513 — Tracking issue for pointer metadata APIs](https://github.com/rust-lang/rust/issues/81513)
- [async-trait on docs.rs](https://docs.rs/async-trait/latest/async_trait/)
