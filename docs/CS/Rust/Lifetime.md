## Introduction

生命周期（lifetime）不是运行时对象，也不是"引用能活多久"的度量。它是**借用关系的类型级名字**：编译器把"这个引用指向的那块数据"抽象成一个抽象区间 `'a`，写进类型里，于是"引用不能比它指向的东西活得久"这条规则变成了一次**类型检查**而不是运行时的空悬指针检测。理解这一点，很多反直觉的现象就顺了：`'a` 只出现在类型上、被推断出来、从不占用内存；`&'a str` 和 `&'b str` 是**不同类型**；结构体必须带生命周期参数而函数可以不写（省略规则）；`impl Trait` 的捕获规则本质上是在问"这个不透明类型对哪些 `'a` 参数化"。

本页只讲生命周期这一层：省略规则、显式标注的真实含义、`'static` 的双重语义、结构体与自引用、协变/逆变、HRTB、**edition 2024 的 RPIT 捕获规则反转**、以及生命周期与借用检查（NLL / Polonius）的分工。三条所有权规则、move/copy、`&mut` 的独占性本身在 [Ownership](/docs/CS/Rust/Ownership.md)，单态化在 [Generics](/docs/CS/Rust/Generics.md)，`dyn Trait` 的默认生命周期 bound 在 [Trait System](/docs/CS/Rust/Trait_System.md)，`Pin` / `Unpin` 在 [Async](/docs/CS/Rust/Async.md)。

本文全部代码与诊断在 `rustc 1.98.1 (48a229cea 2026-09-01)`、`aarch64-apple-darwin` 上实测；跨 edition 差异均给出两次真实运行结果。

## The Three Elision Rules

省略规则（elision rules）只决定**签名里没写的生命周期怎么补全**，按序应用，补不动就报错：

| 规则 | 内容 | 一句话记忆 |
| :--- | :--- | :--- |
| 1 | 每个省略的**输入**生命周期各自成为一个独立参数 | 输入各算各的 |
| 2 | 若输入位置**恰好只有一个**生命周期（省略或显式都算），它被赋给所有省略的**输出** | 一进一出才自动 |
| 3 | 若输入有多个生命周期但其中有 `&self` / `&mut self`，`self` 的生命周期赋给所有省略的输出 | 有 self 时 self 独赢 |

规则 1 的直接后果是"两个 `&str` 参数是两个不同区间"，编译器在诊断里会把它打印成 `'1` / `'2`（见下）。`'_` 这个占位写法自 1.31.0（2018-12-06）起可在 `impl` 头里使用——同一份实现从 `impl<'a> Reader for BufReader<'a> {}` 可改写成 `impl Reader for BufReader<'_> {}`，但**结构体字段里的生命周期仍然必须显式写**（1.31.0 的发布说明当时就补了一句 `Lifetimes are still required to be defined in structs.`）。

### Why the Third Rule Is the One People Get Wrong

三条里被记错的是第三条，而且错法有三种，每种都能被编译器当场抓住。

**错法一：以为"返回值会跟着某个参数走"。** 规则 3 的实际语义是 **`&self` 独占**省略的输出生命周期，其他参数不参与：

```rust
pub struct Ctx { pub data: String }
impl Ctx {
    pub fn pick(&self, other: &str) -> &str {
        if self.data.len() > other.len() { &self.data } else { other }
    }
}
```

`rustc --edition 2024` 的原文诊断（注意它给两个省略的输入生命周期起了 `'1`、`'2`，正是规则 1 的体现）：

```text
error: lifetime may not live long enough
 --> lib.rs:4:64
  |
3 |     pub fn pick(&self, other: &str) -> &str {
  |                 -             - let's call the lifetime of this reference `'1`
  |                 |
  |                 let's call the lifetime of this reference `'2`
4 |         if self.data.len() > other.len() { &self.data } else { other }
  |                                                                ^^^^^ method was supposed to return data with lifetime `'2` but it is returning data with lifetime `'1`
  |
help: consider introducing a named lifetime parameter and update trait if needed
  |
3 |     pub fn pick<'a>(&self, other: &'a str) -> &'a str {
  |                ++++                ++          ++
```

要返回 `other`，就必须显式写 `fn pick<'a>(&'a self, other: &'a str) -> &'a str` 或 `fn pick<'b>(&self, other: &'b str) -> &'b str`。省略规则不会替你做"取两个参数交集"这个决定，因为那正是需要程序员表达的地方。

**错法二：以为"给输入起个名字"就能救输出。** 规则 2 的条件是**输入位置恰好一个生命周期**，显式的也算，于是 `&'a str` + `&str` 是两个位置，规则 2 失效：

```rust
fn splity<'a>(a: &'a str, b: &str) -> &str { if a.len() > b.len() { a } else { b } }
```

```text
error[E0106]: missing lifetime specifier
  |
9 | fn splity<'a>(a: &'a str, b: &str) -> &str { ... }
  |                  -------     ----     ^ expected named lifetime parameter
  = help: this function's return type contains a borrowed value, but the signature does not say
          whether it is borrowed from `a` or `b`
```

**错法三：以为 `Self` 上有 `'a` 就等于输出能用 `'a`。** 结构体的生命周期参数和 `&self` 的寿命是两件事，规则 3 把省略的输出绑到 `&self` 而不是 `'a`：

```rust
pub struct Holder<'a> { pub r: &'a str }
impl<'a> Holder<'a> {
    pub fn via_self(&self) -> &str { self.r }      // 规则 3：返回的实际上是 &'_ self
    pub fn via_data(&self) -> &'a str { self.r }   // 显式：返回数据本身的寿命
}
pub fn ok<'h>(h: &'h Holder<'static>) -> &'static str { h.via_data() }
pub fn bad<'h>(h: &'h Holder<'static>) -> &'static str { h.via_self() }
```

`via_data` 通过，`via_self` 报 `error: lifetime may not live long enough ... returning this value requires that 'h must outlive 'static`。差别很实在：前者允许调用方在 `Holder` 销毁之后继续用返回的 `&'static str`，后者不行。规则只处理"省略"的地方，任何一处显式写出来它就不再介入。

> [!NOTE]
> 混用显式与省略写法现在会被 `mismatched_lifetime_syntaxes` 默认警告（1.89.0 起，取代 `elided_named_lifetimes`）。`fn v2<'a>(x: &'a str) -> &str` 触发原文：`warning: eliding a lifetime that's named elsewhere is confusing … = note: #[warn(mismatched_lifetime_syntaxes)] on by default`，建议 `consistently use 'a`。

## Explicit 'a Says At Least, Not Exactly

`fn longest<'a>(x: &'a str, y: &'a str) -> &'a str` 里的 `'a` 不表示"这两个引用活了 `'a` 那么久"，而是一个**下界承诺**：每个入参"至少活到 `'a`"，返回值"保证活到 `'a`"。所以调用点才拥有解释权——它挑一个 `'a`，编译器反过来要求所有入参都覆盖它，于是直觉上 `'a` 落在**所有实参寿命里最短的那个**上（精确说由推断器求解约束，"取最短"只是可靠直觉，不要当成算法定义）。两个关键推论：

- **可以缩短，不能拉长。** 因为 `&'a T` 对 `'a` 协变，`'a: 'b` 时 `&'a str` 能当 `&'b str` 用；反向必然错。实测 `pub fn to_shorter<'a: 'b, 'b>(x: &'a str) -> &'b str { x }` 通过。
- **参数之间要写约束，名字本身不蕴含大小关系。** `fn f<'a, 'b>(x: &'a str, y: &'b str)` 里 `'a` 与 `'b` 无任何关系；要表达包含关系得写 `<'a, 'b: 'a>` 或 `where 'a: 'b`（两者实测均通过，`where` 子句形式合法）。

顺带一条语法事实：`'r#own` 这类 **raw lifetime** 只在 edition 2021+ 能被解析（该语言特性自 1.83.0 起 stable）。同一份源码在 `--edition 2018` 下是**记号级**错误 `error: expected one of ',', ':', or '>', found '#'`，而不是类型错误——与 C-string 字面量的表现同构。

## 'static: Two Meanings in One Syntax

`'static` 在两个位置上说的是两件不同的事，混为一谈是它最常见错用来源。

**含义一：一个具体的生命周期值**——整个程序执行期间都有效。字面量、`static` 项属于这类。它是**最长**的那个区间，因为协变，`&'static T` 可以无代价地当作任何更短的 `&'a T` 用：`pub fn to_any<'a>(x: &'static str) -> &'a str { x }` 实测通过。

**含义二：一个类型 bound**——`T: 'static` 说的是"**这个类型内部不含任何非 `'static` 的引用**"，即它自己拥有全部数据，跟"是否被泄漏 / 是否永生"毫无关系。`String`、`Vec<u8>`、`i32` 都满足 `'static`，照样会被正常 drop。实测：

```rust
pub fn needs_static<T: 'static>(t: T) -> T { t }
pub fn ok_owned() -> usize { needs_static(String::from("x")).len() }        // 通过
pub fn ok_dropped() -> usize { let s = needs_static(String::from("y")); s.len() }  // 通过，照样析构
pub fn err_borrowed<'a>(s: &'a str) -> usize { needs_static(s).len() }      // 报错
```

```text
error[E0521]: borrowed data escapes outside of function
 --> lib.rs:4:48
  |
4 | pub fn err_borrowed<'a>(s: &'a str) -> usize { needs_static(s).len() }
  |                     --  -                      ^^^^^^^^^^^^^^^
  |                     |   |                      |
  |                     |   |                      `s` escapes the function body here
  |                     |   |                      argument requires that `'a` must outlive `'static`
  |                     |   `s` is a reference that is only valid in the function body
  |                     lifetime `'a` defined here
```

`thread::spawn` 的 `'static` bound 是同一个约束，症状也是同一套（闭包捕获局部借用时），实测原文：

```text
error[E0373]: closure may outlive the current function, but it borrows `s`, which is owned by the current function
  |
8 |     let h = std::thread::spawn(|| println!("{}", s));
  |                                ^^                - `s` is borrowed here
  |                                |
  |                                may outlive borrowed value `s`
note: function requires argument type to outlive `'static`
```

| 转换方向 | 写法 | 代价 |
| :--- | :--- | :--- |
| `&'static str` → `String` | `s.to_owned()` | **堆分配 + 整块拷贝**，因为 `String` 要拥有 |
| `String` → `&str` | `&s` / `s.as_str()`（deref coercion） | **免费**，只是把 `{ptr, len}` 复制出来，寿命受 `s` 约束 |
| `String` → `&'static str` | 无法安全做到 | 只能 `Box::leak(s.into_boxed_str()) -> &'static mut str`（实测通过），代价是这块内存不再回收 |

所以"免费"只有 `String → &str` 这一边：deref coercion 不复制字节，而反向必然要有一块被拥有的缓冲。想拿到 `'static` 只能靠泄漏——注意 1.99.0（2026-10-01）改了 `Box::leak` 的文档口径：**不再推荐"先 leak、之后再把它 deallocate"的用法**，应优先 `Box::into_raw` / `Box::into_non_null`（这两个 API 同样在 1.99.0 stable）。泄漏只该出现在真正的 FFI 所有权移交处。

## Lifetimes in Structs and the Self-Referential Wall

引用放进结构体就必须带上它的生命周期参数，作为该结构的类型参数：

```rust
pub struct NeedsLife { pub r: &str }           // error[E0106]: missing lifetime specifier
pub struct Holder<'a> { pub r: &'a str, pub n: usize }
pub struct Pair<'a, 'b: 'a> { pub long: &'a str, pub short: &'b str }
```

`NeedsLife` 的诊断也是 E0106，但形态与函数不同：`= help: consider introducing a named lifetime parameter` 直接把建议写成 `struct NeedsLife<'a> { pub r: &'a str }`。E0106 在结构体上不可省，因为省略规则的三条全是关于函数签名的。字段间若要"短的能被长的借用"，得写 `'b: 'a`（实测通过）。

结构体的生命周期参数是**不可消灭的下界**：`Holder<'a>` 里存着 `&'a str`，那么 `Holder` 自己也不能活得比 `'a` 久，编译器会在移动/析构时守住这条线。这条线正是**自引用结构体在 Rust 里不可能**的原因：

```rust
pub struct SelfRef { pub s: String, pub r: &'static str }   // r 想指向 self.s
pub fn build() -> SelfRef {
    let mut o = SelfRef { s: String::from("hello"), r: "" };
    o.r = &o.s;
    o
}
```

两个错误同时出现，而且互相解释：`error[E0597]: 'o.s' does not live long enough … assignment requires that 'o.s is borrowed for 'static` 与 `error[E0505]: cannot move out of 'o' because it is borrowed`。也就是说，字段类型只能写成某个具体区间（`'static` 或另一个参数 `'a`），而那个区间一旦要求"指向自己"，赋值与移动就同时被封死。**这不是实现限制，是类型表达的边界**：借用关系必须由*外部*提供的生命周期参数命名，而 `self` 的地址在移动后失效，于是没有一个参数能描述它。想要自引用只有三条路：返回 `String` / `Rc`、把数据搬到固定地址（`Box` + 裸指针 + `unsafe` 自己维护不变式）、或者用 `Pin` 把"不许移动"写进类型——`Pin` 的机制与 `Unpin` 契约见 [Async](/docs/CS/Rust/Async.md)，本页不展开。async/await 生成的 future 是真实的自引用结构，所以它必然带 `Pin`，这两件事是同一个问题。

## Variance and PhantomData

生命周期参数参与子类型（subtyping）时，容器的"方向"叫协变（covariant，`'a: 'b` 时 `C<'a> <: C<'b>`）、逆变（contravariant，方向相反）、不变（invariant，两个方向都不允许）。规则不必背表，只需记住**成员位置决定方向**：出现在只读位置（`&`、返回类型）协变；出现在**可以写入**的位置（`&mut`、`Cell<T>`、`Mutex<T>`）不变；出现在函数指针的**参数**位置逆变。

实测（`'a: 'b` 前提下，每一行单独编译）：

```rust
use std::cell::Cell;
pub fn cov_ref<'a: 'b, 'b>(x: &'a u8) -> &'b u8 { x }                    // OK  协变
pub fn cov_vec<'a: 'b, 'b>(x: Vec<&'a str>) -> Vec<&'b str> { x }        // OK  协变
pub fn inv_cell<'a: 'b, 'b>(x: Cell<&'a str>) -> Cell<&'b str> { x }     // ERR 不变
pub fn contra_ok<'a: 'b, 'b>(x: fn(&'b str)) -> fn(&'a str) { x }        // OK  fn(&T) 逆变
pub fn contra_bad<'a: 'b, 'b>(x: fn(&'a str)) -> fn(&'b str) { x }       // ERR
```

`inv_cell` 的诊断是这节最该记的一段，因为它**直接点名不变性**（不是只说"寿命不够"）：

```text
error: lifetime may not live long enough
  = note: requirement occurs because of the type `Cell<&str>`, which makes the generic argument `&str` invariant
  = note: the struct `Cell<T>` is invariant over the parameter `T`
  = help: see <https://doc.rust-lang.org/nomicon/subtyping.html> for more information about variance
```

**`fn(T)` 与 `fn(&T)` 的坑就在这里**：函数指针的参数位置是逆变的，所以"看起来更宽松"的方向反而不通。上面 `contra_bad` 与 `inv_cell` 的报错正文一模一样（`function was supposed to return data with lifetime 'a but it is returning data with lifetime 'b`），但成因不同：一个是"逆变要求反方向"，一个是"不变要求相等"。三个实用结论，全部实测：`fn(fn(&'a str))` 逆变两次等于协变（通过）；同时占参数与返回值两个位置的 `fn(&'a str) -> &'a str` **两个方向都不通过**，即对 `'a` 不变；`Mutex<T>` 与 `Cell<T>` 一样会打印 `the struct 'std::sync::Mutex<T>' is invariant over the parameter 'T'`。一旦类型不变，把它的参数写短一点也通融不了，此时**只能改结构，不能改 bound**。

`PhantomData<T>` 的真实用途有三类，都不是"占位"这种玄学说法：

```rust
use std::cell::Cell;
use std::marker::PhantomData;
pub struct Owns<T> { _p: PhantomData<T> }               // 表现得像拥有一个 T
pub struct NotOwns<T> { _p: PhantomData<fn() -> T> }    // 只"用到" T，不拥有
pub struct PtrLike<T> { _p: PhantomData<*const T> }     // 传染 !Send / !Sync
pub struct Inv<T> { _p: PhantomData<Cell<T>> }          // 强制不变
pub fn assert_send<T: Send>() {}
pub fn cov_ok<'a: 'b, 'b>(x: NotOwns<&'a str>) -> NotOwns<&'b str> { x }      // OK
pub fn inv_via_pd<'a: 'b, 'b>(x: Inv<&'a str>) -> Inv<&'b str> { x }          // ERR
pub fn no_send() { assert_send::<PtrLike<u8>>(); }                             // ERR
```

1. **声明"我拥有它"**：影响 drop 检查（`unsafe` 里自己管理内存时的标准写法）与 `T: 'a` 约束的成立。上面 `Owns<T>` 与 `NotOwns<T>` 的协变方向都是协变，但 `PhantomData<Cell<T>>` 会让整个结构对 `T` 变不变（实测诊断 ``= note: the struct `Inv<T>` is invariant over the parameter `T` ``）——这就是**手动控制 variance** 的正规旋钮。
2. **参数没在字段里用到会直接拒绝编译**：`pub struct Bad<T> { v: u32 }` → ``error[E0392]: type parameter `T` is never used``，help 明确写了 `using a marker such as `PhantomData``。
3. **传染自动 trait**：`PtrLike<T>` 因为 `*const T` 而 `!Send`/`!Sync`（实测两条 E0277，第二条为 ``error[E0277]: `*const u8` cannot be shared between threads safely``，均附 `note: required because it appears within the type 'PhantomData<*const u8>'`）。手写 `Rc` 类容器时，这是让"裸指针语义"体现在类型层的唯一手段。

## Higher-Ranked Trait Bounds

有时**没有任何一个具体生命周期能填进去**：回调必须对"调用时才决定"的任意寿命都成立。`for<'a>` 就是把生命周期量词写进 bound：

```rust
pub fn general(f: impl for<'b> Fn(&'b str)) { let local = String::from("x"); f(&local); }
pub fn early<'a>(f: impl Fn(&'a str)) { let local = String::from("x"); f(&local); }   // ERR
```

`early` 报 `error[E0597]: 'local' does not live long enough … argument requires that 'local is borrowed for 'a`，因为 `&'a str` 的 `'a` 是**早期绑定**（early bound）——在调用点就被定死，而 `general` 里量词在闭包内部，每次调用重新选。

日常中你其实一直在用它，只是看不见：trait object / `impl Trait` 里**省略的输入生命周期会自动成为高阶的**。实测 `pub fn boxed() -> Box<dyn for<'a> Fn(&'a str) -> &'a str> { Box::new(|s| s) }` 与写成 `Box<dyn Fn(&str) -> &str>` 的两个版本都通过；把参数类型写错时报的正是 `error[E0631] … note: expected function signature 'for<'a> fn(&'a str) -> _'`——诊断文本自己承认了 `for<'a>` 的存在。

绕不开的三处：**① 存回调的字段**——`Box<dyn Fn(&str)>` 里省略的 `&str` 是高阶的，所以它对"调用时才决定的寿命"仍然可用；一旦写成 `Box<dyn Fn(&'static str)>`，同一个函数体 `let l = String::new(); f(&l)` 就报 `error[E0597]: 'l' does not live long enough … argument requires that 'l is borrowed for 'static`（两个版本实测，只差那个 `'static`）。**② trait 方法的引用参数**——`fn set(&mut self, s: &str)` 与显式 `fn visit<'a>(&self, s: &'a str)` 都能编译（实测），但前者是 late-bound 的高阶量、后者是方法级泛型参数，在对象安全与 `dyn` 可用性上待遇不同（细节见 [Trait System](/docs/CS/Rust/Trait_System.md)）；**③ 闭包**——恰恰是**唯一不能自己写 `for<'a>` 的地方**：`let f = for<'a> |x: &'a str| x.len();` 实测 `error[E0658]: 'for<...>' binders for closures are experimental`，`note: see issue #97362 <https://github.com/rust-lang/rust/issues/97362>`，附带 `error: implicit types in closure signatures are forbidden when 'for<...>' is present`。所以闭包只能靠上下文推断出高阶签名，推不出来就要回头改函数侧 bound 或改成 `fn` 项。与 `async` 的纠缠（`AsyncFn*` 系列、future 捕获的寿命）见 [Async](/docs/CS/Rust/Async.md)。

## RPIT Lifetime Capture and the Edition 2024 Inversion

`-> impl Trait` 返回的是一个**不透明类型**（opaque type），它到底对哪些生命周期参数化，叫**捕获（capture）**。这件事在 edition 2024 被整体翻转（RFC 3498），是生命周期话题里近两年代价最大的一处行为变化，而且**改的是默认值而不是语法**——旧代码能编、新代码也能编，但语义不同。

| | edition 2015 / 2018 / 2021 | edition 2024 |
| :--- | :--- | :--- |
| 捕获哪些**生命周期** | 只捕获出现在 `impl Trait` bound 文本里的那些 | **所有在作用域内的泛型参数**（含全部生命周期） |
| 捕获哪些**类型参数** | 一直是全部（实测：`use<>` 会报 "type parameter is implicitly captured"） | 全部 |
| 典型后果 | 隐藏类型引用了未声明的寿命 → E0700 | 不引用也被捕获 → 借用被无谓延长 |
| 逃生舱 | `Captures<'a>` 技巧 / `+ '_` | `+ use<..>`（1.82.0 起**全 edition 可用**） |

### The Base Case

同一份源码，只有 edition 不同（实测）：

```rust
pub fn chars(s: &str) -> impl Iterator<Item = char> { s.chars() }
```

```text
# rustc --edition 2021 --emit=metadata --crate-type lib
error[E0700]: hidden type for `impl Iterator<Item = char>` captures lifetime that does not appear in bounds
 --> lib.rs:1:55
  |
1 | pub fn chars(s: &str) -> impl Iterator<Item = char> { s.chars() }
  |                 ----     --------------------------   ^^^^^^^^^
  |                 |        |
  |                 |        opaque type defined here
  |                 hidden type `Chars<'_>` captures the anonymous lifetime defined here
  |
help: add a `use<...>` bound to explicitly capture `'_`
  |
1 | pub fn chars(s: &str) -> impl Iterator<Item = char> + use<'_> { s.chars() }
  |                                                     +++++++++

# rustc --edition 2024 --emit=metadata --crate-type lib
（无输出，编译通过）
```

`edition 2015 / 2018` 的 E0700 输出与 2021 逐字相同，连 help 里推荐的 `use<'_>` 也一样（因为 1.82.0 之后这个语法在所有 edition 都存在）。

### The Pre-2024 Workarounds

旧 edition 里"想让 RPIT 捕获 `'a`"有两个历史技巧，两者实测在 2018/2021/2024 **都能编译**（前者在新 edition 已成冗余，后者顺带过度约束）：

```rust
pub trait Captures<'a> {}                                   // 技巧 1：造一个提到 'a 的 marker trait
impl<'a, T: ?Sized> Captures<'a> for T {}
pub fn a<'a>(s: &'a str) -> impl Iterator<Item = char> + Captures<'a> { s.chars() }

pub fn b(s: &str) -> impl Iterator<Item = char> + '_ { s.chars() }   // 技巧 2：outlives bound 让 'a 出现在 bound 里
```

`Captures<'a>` 的全部作用就是"把 `'a` 写进 bound 文本"，好让旧规则认为它该被捕获——技巧本身是规则的一个后门，读旧代码时最容易误以为 `Captures` 有运行时含义（它没有，是空 trait）。

### Precise Capturing with use

`+ use<'a>`（RFC 3617，Rust 1.82.0，2024-10-17）把默认值问题变成显式声明，且**与 edition 无关**：

```rust
pub fn c<'a>(s: &'a str) -> impl Iterator<Item = char> + use<'a> { s.chars() }
pub fn d(s: &str) -> impl Iterator<Item = char> + use<'_> { s.chars() }
pub fn e<T: Default>(_t: T) -> impl Default + use<T> { T::default() }
```

`use<>`（空列表）表示"什么都不捕获"，只有**当作用域内没有类型参数**时才合法，否则报 ``error: `impl Trait` must mention all type parameters in scope in `use<...>` ``，并附 `note: currently, all type parameters are required to be mentioned in the precise captures list`（实测）。

### What the New Default Breaks

新默认的价值是 E0700 那一类不再需要样板；代价是**过度捕获**：隐藏类型明明不引用 `'a`，不透明类型仍然被参数化，于是借用被无谓延长。同一份代码：

```rust
pub fn bogus<'a>(_x: &'a str) -> impl std::fmt::Debug { 1u8 }
pub fn use_it() -> String {
    let local = String::from("x");
    let v = bogus(&local);
    drop(local);
    format!("{:?}", v)
}
```

```text
# rustc --edition 2021   → 通过
# rustc --edition 2024   →
error[E0505]: cannot move out of `local` because it is borrowed
 --> lib.rs:5:10
  |
3 |     let local = String::from("x");
  |         ----- binding `local` declared here
4 |     let v = bogus(&local);
  |                   ------ borrow of `local` occurs here
5 |     drop(local);
  |          ^^^^^ move out of `local` occurs here
6 |     format!("{:?}", v)
  |                     - borrow later used here
  |
note: this call may capture more lifetimes than intended, because Rust 2024 has adjusted the `impl Trait` lifetime capture rules
 --> lib.rs:4:13
  |
4 |     let v = bogus(&local);
  |             ^^^^^^^^^^^^^
help: use the precise capturing `use<...>` syntax to make the captures explicit
  |
1 | pub fn bogus<'a>(_x: &'a str) -> impl std::fmt::Debug + use<> { 1u8 }
  |                                                       +++++++
```

这条 note 是官方给的直接信号：**"这行以前能编，现在因为捕获规则不能编"**。迁移时把它加回 `use<>` 即可，且 `use<>` 在 2021 下也通过（实测），所以可以先在旧 edition 上补 `use<>`、再切 2024，两步都不破坏编译。

### RPITIT

trait 方法里返回 RPIT（RPITIT，Rust 1.75.0 stable）从一开始就是"捕获全部在作用域内的参数"，**没有** edition 差异（实测同一份 RPITIT 代码在 2021 与 2024 下都通过，无 E0700）；1.87.0（2025-05-15）才把 `use<..>` 允许写在这里（`precise_capturing_in_traits`）。两个实测坑：`use<..>` 列表里**生命周期必须排在类型参数之前**（`error: lifetime parameter 'a must be listed before non-lifetime parameters`），且 trait 声明处必须提到 `Self`，而 impl 处 `Self` 是别名不能提（``error[E0799]: `Self` can't be captured in `use<...>` precise captures list, since it is an alias``）。可编译的对照写法：

```rust
pub trait Mapper {
    fn chars<'a>(&self, s: &'a str) -> impl Iterator<Item = char> + use<'a, Self>;
}
pub struct M;
impl Mapper for M {
    fn chars<'a>(&self, s: &'a str) -> impl Iterator<Item = char> + use<'a> { s.chars() }
}
```

trait 侧写了 `use<..>` 而 impl 侧什么都不写会报 `error: return type captures more lifetimes than trait definition`——两侧都要标注。`dyn` 兼容性（对象安全）与 `dyn Trait` 的默认 `+ 'static` bound 见 [Trait System](/docs/CS/Rust/Trait_System.md)。

## How the Borrow Checker Consumes Lifetimes

生命周期是**类型**，借用检查是**算法**，两者不能混为一谈：`'a` 上的约束只是被解出来的结果，真正决定"这次借用行不行"的是控制流图（CFG）。非词法生命周期（NLL，non-lexical lifetimes）之后，一个引用的活跃区间等于**它在 CFG 上被最后使用的那些程序点集合**，而不再是"到所在作用域右花括号为止"：

```rust
pub fn dead_before(v: &mut Vec<i32>) -> i32 {
    let r = &v[0];
    let x = *r;          // r 的最后一次使用在这里，借贷到此结束
    v.push(x);           // OK
    x
}
pub fn live_after(v: &mut Vec<i32>) -> i32 {
    let r = &v[0];
    v.push(1);           // error[E0502]：r 仍然活跃
    let x = *r;
    x
}
```

`live_after` 的诊断特意把两端点标出来：`immutable borrow occurs here` … `immutable borrow later used here`——**判据是"later used"，不是"later scope"**。同理，分支也是分开看的：`if let Some(value) = map.get_mut(&key) { … } else { map.insert(…) }` 这类结构在 1.98.1 上实测通过，它正是"看借贷是否仍然活跃、而不是看花括号在哪里结束"的典型判例。换句话说，**生命周期参数名（`'a`）只是给约束起名，实际区间由程序点上的使用情况算出来**；理解了这点，`&'a str` 与 `&'static str` 之间的"至少活这么久"就不会被读成"活刚刚好这么久"。

剩下的空隙是**路径不相交**（disjointness）：`let (a, b) = (&mut v[0], &mut v[1]);` 实测 `error[E0499]: cannot borrow '*v' as mutable more than once at a time`，并附 `help: use '.split_at_mut(position)' to obtain two mutable non-overlapping sub-slices`——借用检查不把 `v[0]` 与 `v[1]` 看成两个不重叠的区间。这正是下一版借用检查（官方博客称 "the next iteration of the borrow checker"，即 Polonius 那条线）瞄准的方向；**它目前只在 nightly**，本地 flag 是 `-Z polonius`，unstable book 对该 flag 的自述是 `This feature has no tracking issue, and is therefore likely internal to the compiler, not being intended for general use.`；官方在 2026-08-04 发过一篇标题为 "Enabling the next iteration of the borrow checker on nightly" 的 alpha 启用公告（⚠️ 本机抓取该 permalink 返回 404，只见于博客索引，故此处只记标题与日期、不引用正文，也没有放进 References）。结论纪律：把它当"nightly 上可试的方向"，**不要写成"某个 stable 版本起 NLL 会被替换"**。跨 edition 的迁移与 MSRV 取舍见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)。

## Error Code Field Guide

| 诊断 | 真实触发点 | 首行原文 |
| :--- | :--- | :--- |
| E0106 | 函数输出省略但输入位置 ≠ 1 且无 `&self`；或结构体字段写 `&str` | `missing lifetime specifier` + `does not say whether it is borrowed from `x` or `y`` |
| E0700 | 旧 edition 的 RPIT 隐藏类型引用了未出现在 bound 里的生命周期 | ``hidden type for `impl Iterator<Item = char>` captures lifetime that does not appear in bounds`` |
| E0597 | 值在其借用结束前被 drop（含自引用尝试） | `` `local` does not live long enough`` … `borrowed value does not live long enough` |
| E0505 | 借用仍然活跃时移走/借用其来源（含 2024 过度捕获） | ``cannot move out of `local` because it is borrowed`` |
| E0502 / E0499 | 同一处已借为可变又借为不可变 / 两次可变 | ``cannot borrow `*v` as mutable because it is also borrowed as immutable`` / ``cannot borrow `*v` as mutable more than once at a time`` |
| E0716 | 临时值在本语句结束即析构却被继续借用 | `temporary value dropped while borrowed` + `consider using a `let` binding to create a longer lived value` |
| E0521 / E0373 | 违反 `T: 'static` bound；闭包捕获局部被送去 `'static` 上下文 | `borrowed data escapes outside of function` / `closure may outlive the current function` |
| E0515 | 返回指向函数自身拥有的参数的引用 | ``cannot return reference to function parameter `s` `` + `returns a reference to data owned by the current function` |
| E0631 | 实参函数签名与 `for<'a> fn(...)` 期望不符 | ``expected function signature `for<'a> fn(&'a str) -> _` `` |
| E0495 已停用 | **已停用**。1.98.1 的 `rustc --explain E0495` 首行明写 `Note: this error code is no longer emitted by the compiler` | 旧教程里的 E0495 场景今天报的是无编号的 `lifetime may not live long enough` + `consider adding the following bound: 'a: 'b` |

E0495 这一行值得单独强调：错误索引里保留着它的完整解释页与 `fn transmute_lifetime<'a, 'b, T>` 示例，但拿原示例在 1.98.1（以及 1.95.0、edition 2015）上跑，得到的都是"lifetime may not live long enough"而非 E0495。**"错误码页面存在" ≠ "这个码还会被发出"**，这与本库内核笔记里"sysctl 存在 ≠ 仍生效"是同一类判据。

E0716 单独一提，因为它的修法几乎总是那一句：`let s: &str = format!("{}", 42).as_str();` 里 `format!` 的 `String` 是本语句的临时值，`s` 下一行还在用就必然报错；把它 `let tmp = format!(…); let s: &str = &tmp;` 就变成一次普通的作用域问题。

## Links

- [Ownership](/docs/CS/Rust/Ownership.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [Trait System](/docs/CS/Rust/Trait_System.md)
- [Async](/docs/CS/Rust/Async.md)
- [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [Validating References with Lifetimes — The Rust Book](https://doc.rust-lang.org/book/ch10-03-lifetime-syntax.html)
- [Lifetimes — The Rustonomicon](https://doc.rust-lang.org/nomicon/lifetimes.html)
- [Subtyping and Variance — The Rustonomicon](https://doc.rust-lang.org/nomicon/subtyping.html)
- [Return-Position Impl Trait Capturing Lifetimes — Edition Guide (Rust 2024)](https://doc.rust-lang.org/edition-guide/rust-2024/rpit-lifetime-capture.html)
- [RFC 3498: Lifetime Capture Rules 2024](https://github.com/rust-lang/rfcs/pull/3498)
- [RFC 3617: Precise capturing](https://github.com/rust-lang/rfcs/pull/3617)
- [E0495 — Error codes index](https://doc.rust-lang.org/error_codes/E0495.html)
- [E0716 — Error codes index](https://doc.rust-lang.org/error_codes/E0716.html)
- [polonius — Unstable Book](https://doc.rust-lang.org/unstable-book/compiler-flags/polonius.html)
