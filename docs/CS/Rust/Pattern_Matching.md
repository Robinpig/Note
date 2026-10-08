## Introduction

Rust 里有一处语法同时做两件事：**判定一个值是不是某个形状**，以及**把这个形状的组成部分取出来**。它就是模式（pattern）。这两件事在其他语言里通常是分开的——先用 `if` / `switch` 判定，再用下标或 getter 取值；Rust 把它们合并成一次动作，因此`match` 既能当控制流，也能当解构赋值。

合并带来一个必须回答的问题：**取出来的那个名字，拿走的是所有权还是借用？** 答案不写在模式里，而由「被匹配的东西（scrutinee）是值还是引用」和一套叫 **default binding modes** 的隐式规则共同决定。这也是 Rust 模式系统里唯一会让人写出「看起来能编、实际类型不对」的地方——`match &opt { Some(x) => ... }` 里的 `x` 是 `&T` 而不是 `T`，这个结论几乎每个 Rust 程序员都背过，但能说清机制的不多。本篇用实测把它拆到底。

于是本篇的组织：先钉住「模式不是表达式」这个前提（它决定了模式能出现在哪、以及为什么有些位置只接受不可反驳模式），再走一遍语法全景，然后花整节的篇幅讲 match ergonomics 与绑定模式，接着是所有权视角（move 还是 borrow）、穷尽性检查（含 `#[non_exhaustive]` 的反向用法）、守卫与 `if let` / `while let` / `let`-else 的版本差异，最后是 C++ / Java / Python 对照。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，本机实测工具链为 `rustc 1.98.1 (48a229cea 2026-09-01)`（host `aarch64-apple-darwin`），另有 pinned `1.95.0` 用于跨版本对照。下文凡标「实测」的都是本机 `rustc --edition 2024 --crate-type lib`（或双 edition 对照）的真实输出，诊断原文照抄、只把路径归一为文件名；凡标「据文档」的来自 Rust Reference / RFC / release notes，未在本机复现。**版本归属一律给判据，不凭记忆。**

边界：模式与所有权交互的规则本体在 [Ownership](/docs/CS/Rust/Ownership.md)，本篇只讲它在模式里的表现形态；`?` 与 `Result` 的匹配惯用法见 Error Handling 篇；「某语法属于哪个版本 / 是否分 edition」的三态辨析见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)，本篇只做交叉引用不重复论证。

## Patterns Are Not Expressions

模式是**语法范畴**，不是表达式。这一条不是术语洁癖，它有直接后果：表达式可以出现在任何期待值的地方，而模式只能出现在语言规定的六个位置——

| 位置 | 例子 | 是否允许 refutable |
| :-- | :-- | :-- |
| `match` 的 arm | `match x { Some(v) => .., None => .. }` | 是 |
| `if let` 的条件 | `if let Some(v) = x` | 是 |
| `while let` 的条件 | `while let Some(v) = it.next()` | 是 |
| `let`（含 `let`-else 的 `else` 之前） | `let (a, b) = t;` | **否** |
| 函数 / 闭包参数 | `fn f(Point { x, y }: Point)` | **否** |
| `for` 循环头 | `for (k, v) in map` | **否** |

分界线是「匹配失败时有没有退路」：`match` / `if let` / `while let` 都有「不匹配就走下一条」的语义，所以可接受会失败的模式；`let`、参数、`for` 没有退路——模式一旦不成立，程序无法继续，编译器直接拒绝。这个分类在 Reference 里的名字就是 **refutable**（可反驳）与 **irrefutable**（不可反驳）。

「匹配与绑定是同一次动作」这句话的另一半含义是：**模式里的标识符不是「声明变量」而是「把值搬进名字」**。`Some(v)` 里的 `v` 不是新变量，它是「若匹配成功，则 `Option` 内部那个 `T` 的所有权（或借用）现在归这个名字」。所以 `match` 里的一次匹配天然也是一次移动或一次借用——这正是后面「所有权视角」那一节的起点。

## The Grammar Surface

模式的语法家族不小，但成员之间边界很清楚：

| 形式 | 写法 | 说明 |
| :-- | :-- | :-- |
| 字面量 | `1` / `"a"` / `true` | 按相等性匹配；`..=` 之外不能写范围表达式 |
| 标识符绑定 | `x` | irrefutable；匹配一切并把值交给 `x` |
| 通配符 | `_` | irrefutable；匹配一切且**不绑定**（不产生移动） |
| rest / 范围通配 | `..` | 用在 struct / tuple / slice 模式里吞掉剩余部分 |
| range 模式 | `0..=5` / `'a'..='z'` / `1..` | 半开用 `..`，闭区间用 `..=` |
| tuple 模式 | `(a, b)` / `(a, ..)` | 按元数匹配 |
| struct 模式 | `Point { x, y }` / `Point { x: 0, .. }` | 字段名可重绑，可用 `..` 省略 |
| tuple struct / enum 模式 | `Some(v)` / `Err(e)` | 最常见的解构形态 |
| slice 模式 | `[a, b, rest @ ..]` | 见下 |
| 引用模式 | `&x` / `&mut x` | 显式剥一层引用，同时重置绑定模式（见后） |
| `@` 绑定 | `n @ 1..=5` | 既判定子模式，又把整体绑给 `n` |
| or 模式 | `Ok(v) \| Err(v)` | 顶层 `|` 自 1.53.0 stable（据文档；本机 1.98.1 实测可用） |

slice 模式值得单独说，因为它是最晚补齐的一块：**定长 slice 模式**（`[a, b, c]`）随 1.26.0 stable（据 release notes），**subslice 模式**（`[first, .., last]`，即带 `..` 的可变长度写法）随 1.42.0 stable（据 release notes 与官方 "Recent and future pattern matching improvements" 一文）。本机实测 `[a, rest @ .., b]` 编译通过——`rest` 被绑成剩余切片：

```rust
pub fn f(v: &[u8]) -> u8 {
    match v {
        [a, rest @ .., b] => a + b + rest.len() as u8,
        [] => 0,
    }
}
```

注意这里还顺带暴露了一个穷尽性事实：上面这段代码实测报 `error[E0004]: non-exhaustive patterns: &[_] not covered`，因为 `[a, rest @ .., b]` 覆盖长度 ≥ 2、`[]` 覆盖长度 0，长度 1 落空。slice 模式的穷尽性检查是**按长度区间做区间运算**的，不是按「有没有 `_`」兜底。

`...`（三个点）这个历史 inclusive range 写法在 edition 2021 起已是硬错误，本机 2024 实测：

```text
error[E0783]: `...` range patterns are deprecated
 --> t4.rs:3:9
  |
3 |         0...5 => "low",
  |         ^---^
  |          |
  |          help: use `..=` for an inclusive range
```

`|` 在 or 模式里的含义是「两个分支绑定同一组名字」。实测 `match x { Ok(v) | Err(v) => v }`（`x: Result<u8, u8>`）编译通过——这是 `Result` 上「无论成败都要里面那个值」的唯一非 unwrap 写法，也是 or 模式最实用的场景。

## Refutable vs Irrefutable Is a Type-Level Distinction

把可反驳性当成「类型」看，会得到一个更可用的心智模型：**每个位置对模式的可反驳性有一个静态要求，违反就是编译错误**。实测把 refutable 模式放进 `let`：

```rust
pub fn i(x: Option<u8>) -> u8 {
    let Some(y) = x;
    y
}
```

```text
error[E0005]: refutable pattern in local binding
 --> t3.rs:2:9
  |
2 |     let Some(y) = x;
  |         ^^^^^^^ pattern `None` not covered
  |
  = note: `let` bindings require an "irrefutable pattern", like a `struct` or an `enum` with only one variant
  = note: for more information, visit https://doc.rust-lang.org/book/ch19-02-refutability.html
  = note: the matched value is of type `Option<u8>`
help: you might want to use `let...else` to handle the variant that isn't matched
  |
2 |     let Some(y) = x else { todo!() };
  |                     ++++++++++++++++
```

诊断里那句 `let...else` 的提示就是 1.65.0 加进来的那件事本身（据 release notes）：`let`-else 把「`let` 只接受 irrefutable」这条限制从「禁止」改成「你必须给出失败分支」。同理 `for (k, v) in map` 里的 `(k, v)` 和 `fn f(Point { x, y }: Point)` 里的 struct 模式都必须是 irrefutable——这也是为什么 `for` 循环头里永远看不到 `Some(..)`。

## Match Ergonomics and Default Binding Modes

这是全篇最有价值的一节。

问题的起点是这段代码：

```rust
pub fn f(opt: &Option<String>) {
    match opt {
        Some(x) => { let _: () = x; }
        None => {}
    }
}
```

`opt` 的类型是 `&Option<String>`，模式 `Some(x)` 里**没有写 `&`**，但代码能编。而且 `x` 的类型不是 `String`——本机实测：

```text
error[E0308]: mismatched types
 --> t1.rs:3:34
  |
3 |         Some(x) => { let _: () = x; }
  |                             --   ^ expected `()`, found `&String`
```

也就是说：**模式自动剥掉了 scrutinee 上的引用，同时把绑定降级成借用**。这套机制叫 **match ergonomics**（RFC 2005，随 1.26.0 stable，据 release notes "Pattern matching automatically applies dereferences"），实现方式是给模式匹配过程维护一个叫 **default binding mode（DBM）** 的状态量。

DBM 有三个取值，初始为 `move`：

| DBM | 含义 | 何时被设置 |
| :-- | :-- | :-- |
| `move` | 绑定按值（可能移动） | 初始状态；遇到显式 `&` / `&mut` 模式时重置回 `move` |
| `ref` | 绑定为 `&T` | 模式「跳过」了一层 `&T` 未被显式匹配 |
| `ref mut` | 绑定为 `&mut T` | 模式「跳过」了一层 `&mut T` 未被显式匹配 |

「跳过」是关键词：当模式在某处没有写 `&`，而 scrutinee 对应位置的类型是引用时，编译器就替你剥掉这一层，并把 DBM 从 `move` 降级到 `ref`（或 `ref mut`）。此后所有**不带显式绑定模式**的标识符绑定都按 DBM 取值。

本机实测的完整对照表（`rustc --edition 2024`，用 `let _: () = x;` 逼编译器报出 `x` 的真实类型）：

| scrutinee 类型 | 模式 | 实测 `x` 的类型 | 为什么 |
| :-- | :-- | :-- | :-- |
| `Option<String>` | `Some(x)` | `String` | DBM 全程 `move`，按值绑定（发生移动） |
| `&Option<String>` | `Some(x)` | `&String` | 跳过一层 `&` → DBM = `ref` |
| `&&Option<String>` | `Some(x)` | `&String` | 跳过两层 `&`，但 DBM **只降一次**到 `ref` |
| `&mut Option<String>` | `Some(x)` | `&mut String` | 跳过一层 `&mut` → DBM = `ref mut` |
| `&Option<String>` | `&Some(ref x)` | `&String` | 显式 `&` 剥掉外层后 DBM 仍是 `move`，靠显式 `ref` 取借用 |

第二行和第五行的对照说明了 `ref` / `ref mut` 的历史定位：**它们是显式绑定模式，用来在不写 `&` 模式的前提下指定借用方式**。match ergonomics 出现后，绝大多数 `ref` 都变成冗余——`match &opt { Some(ref s) => .. }` 里的 `ref` 与什么都不写等价。

第三行是最容易被忽略的一条：引用层数再多，DBM 也只降级一次，绑定类型是 `&T` 而不是 `&&T`。因为 DBM 是**三态枚举**而不是「引用计数」。

### What Rust 2024 Changed: RFC 3627

edition 2024 收紧了这套规则，出处是 **RFC 3627（match-ergonomics-2024）**，它建立在 RFC 2005 之上。三条限制（据 Edition Guide「Match ergonomics reservations」）：

1. 当 DBM 不是 `move` 时，在绑定上写 `mut` 是**错误**（≤ 2021 时 `mut` 会把 DBM 重置回 `move`）；
2. 当 DBM 不是 `move` 时，写 `ref` / `ref mut` 是错误（冗余的显式绑定模式被禁）；
3. 当 DBM 不是 `move` 时，写 `&` / `&mut` 引用模式是错误。

第 1 条的双 edition 实测最有说服力。同一份源码：

```rust
pub fn m(opt: &mut Option<String>) {
    match opt {
        Some(mut s) => { s.push_str("x"); }
        None => {}
    }
}
```

edition 2021 下是老规则（`mut` 把 DBM 重置为 `move`，于是试图从 `&mut` 后面移出一个 `String`）：

```text
error[E0507]: cannot move out of `opt` as enum variant `Some` which is behind a mutable reference
 --> t11.rs:2:11
  |
2 |     match opt {
  |           ^^^
3 |         Some(mut s) => { s.push_str("x"); }
  |              ----- data moved here because `s` has type `String`, which does not implement the `Copy` trait
help: consider borrowing the pattern binding
  |
3 |         Some(ref mut s) => { s.push_str("x"); }
  |              +++
```

edition 2024 下多出一条专属诊断，直接点名 RFC 3627 的规则 1：

```text
error: cannot mutably bind by value within an implicitly-borrowing pattern
 --> t11.rs:3:14
  |
3 |         Some(mut s) => { s.push_str("x"); }
  |              ^^^ `mut` binding modifier not allowed when implicitly borrowing
  |
  = note: for more information, see <https://doc.rust-lang.org/reference/patterns.html#binding-modes>
note: matching on a reference type with a non-reference pattern implicitly borrows the contents
 --> t11.rs:3:9
  |
3 |         Some(mut s) => { s.push_str("x"); }
  |         ^^^^^^^^^^^ this non-reference pattern matches on a reference type `&mut _`
help: match on the reference with a reference pattern to avoid implicitly borrowing
  |
3 |         &mut Some(mut s) => { s.push_str("x"); }
  |         ++++
```

（`mut s` 后面跟着的 E0507 在 2024 下依然存在，所以 2024 下是两条错误。）诊断给出的修法就是「把前缀写全」：`&mut Some(mut s)`。这条规则的存在理由写在 Edition Guide 里——「可修改性不该影响绑定的类型」，2024 先把这个反直觉行为禁掉，为将来重新定义留出空间。这也是「edition 是 opt-in 的语言层重定义」的又一例证：同一个模式在 2021 和 2024 下语义不同，迁移由 `rust_2024_incompatible_pat` lint 与 `cargo fix --edition` 接管。

## Patterns and Ownership

把前面两节合起来，`match` 到底是 move 还是 borrow 只有一个判据：**绑定时的 DBM**。DBM = `move` 且类型非 `Copy` 就移动，DBM = `ref` / `ref mut` 就借用。而 DBM 又被 scrutinee 是不是引用、模式有没有写 `&` 决定。

按值匹配一个非 `Copy` 值会移动它，之后原名字被判定为「部分移动」——实测：

```rust
pub fn g(opt: Option<String>) {
    match opt {
        Some(s) => println!("{}", s),
        None => {}
    }
    println!("{:?}", opt);
}
```

```text
error[E0382]: borrow of partially moved value: `opt`
 --> t2.rs:6:22
  |
3 |         Some(s) => println!("{}", s),
  |              - value partially moved here
...
6 |     println!("{:?}", opt);
  |                      ^^^ value borrowed here after partial move
  |
  = note: partial move occurs because value has type `String`, which does not implement the `Copy` trait
help: borrow this binding in the pattern to avoid moving the value
  |
3 |         Some(ref s) => println!("{}", s),
  |              +++
```

注意措辞是 **partially** moved 而不是 moved：`Option` 这个整体没有被移走，被移走的只是 `Some` 分支里的那个 `String`。编译器是按分支、按字段做移动记账的（MIR 上的数据流分析），所以 `match` 之后 `opt` 处于「部分已移动」状态——既不能整体读，也不能整体 drop，但可以重新赋值让名字复活。规则本体见 [Ownership](/docs/CS/Rust/Ownership.md)。

诊断给的修法 `Some(ref s)` 就是显式绑定模式的经典用途：把「按值匹配」改成「按引用匹配」。在 match ergonomics 之后，更常见的写法是干脆把 scrutinee 写成引用（`match &opt`），让 DBM 自动降级。

`for` 循环是同一件事的另一个入口——它脱糖成 `IntoIterator::into_iter()`，而 `Vec` 的 `into_iter` 吃 `self`。实测：

```rust
pub fn f() {
    let v = vec![String::from("a"), String::from("b")];
    for s in v {
        println!("{}", s);
    }
    println!("{:?}", v);
}
```

```text
error[E0382]: borrow of moved value: `v`
 --> e1.rs:6:22
  |
2 |     let v = vec![String::from("a"), String::from("b")];
  |         - move occurs because `v` has type `Vec<String>`, which does not implement the `Copy` trait
3 |     for s in v {
  |              - `v` moved due to this implicit call to `.into_iter()`
...
6 |     println!("{:?}", v);
  |                      ^^^ value borrowed here after move
  |
note: `into_iter` takes ownership of the receiver `self`, which moves `v`
help: consider iterating over a slice of the `Vec<String>`'s content to avoid moving into the `for` loop
  |
3 |     for s in &v {
  |              +
```

诊断里那句 `` `v` moved due to this implicit call to `.into_iter()` `` 值得抄下来——它把「`for` 循环吃进整个集合」这件事直接归因到了 `IntoIterator` 的方法签名上。循环头里的 `s` 本身也是模式（`for` 只接受 irrefutable），所以 `for (k, v) in map`、`for Point { x, y } in pts` 这类解构同样是「匹配 + 绑定」一次完成，同样遵守上面那套 move / borrow 判据。

## Exhaustiveness and the Cost of `_`

穷尽性检查是**语言保证**而非 lint：`match` 必须覆盖 scrutinee 类型的所有可能值，否则是硬错误。实测漏一个变体：

```text
error[E0004]: non-exhaustive patterns: `E::C` not covered
 --> t12.rs:3:11
  |
3 |     match e {
  |           ^ pattern `E::C` not covered
  |
note: `E` defined here
 --> t12.rs:1:10
  |
1 | pub enum E { A, B, C }
  |          ^         - not covered
  = note: the matched value is of type `E`
help: ensure that all possible cases are being handled by adding a match arm with a wildcard pattern or an explicit pattern as shown
```

它之所以能做成语言保证，是因为**枚举的变体集合在编译期封闭**：`enum` 的取值域是定义时就写死的有限集，编译器可以按变体做集合差。这也是 Rust 的 `match` 与 `switch` 类语法最本质的差别——后者处理的是开放值域，只能靠 `default` 兜底。

于是 `_` 的取舍就很清楚了：写 `_` 等于**放弃未来新增变体时的编译告警**。库作者给自己加一个新变体，你的 `match` 依然编译通过，但走的是 `_` 那条分支——语义静默改变。所以判别式是：

- 自己的 `enum`、且希望新增变体时挨个 review：写全变体，不写 `_`；
- 别人的 `enum`（尤其跨 crate）：写 `_`，因为你无法控制对方加变体；
- 值域开放（整数、字符串、`&str`）：必须写 `_`，否则 E0004。

`#[non_exhaustive]` 是这件事的反向工具：**库作者用它主动剥夺下游的穷尽匹配权**，从而保留「将来加变体不算破坏性变更」的权利。它的生效范围是**跨 crate**——这一条有实测支撑：在**同一个 crate 内**对 `#[non_exhaustive] enum` 做穷尽匹配，本机实测**编译通过**（属性不影响本 crate）；跨 crate 时才报错：

```text
error[E0004]: non-exhaustive patterns: `_` not covered
 --> nemain.rs:4:11
  |
4 |     match k {
  |           ^ pattern `_` not covered
  |
note: `Kind` defined here
 --> nelib.rs:2:1
  |
2 | pub enum Kind { A, B }
  | ^^^^^^^^^^^^^
  = note: the matched value is of type `Kind`
  = note: `Kind` is marked as non-exhaustive, so a wildcard `_` is necessary to match exhaustively
help: ensure that all possible cases are being handled by adding a match arm with a wildcard pattern or an explicit pattern as shown
  |
6 ~         Kind::B => 2,
7 ~         _ => todo!(),
  |
```

注意最后那句 `= note:` 的措辞——它要求的是 `_`，而**不是**「把新变体列出来」。因为 `#[non_exhaustive]` 的语义就是「你列不全，别列」。同样的属性也能加在 struct / variant 上，效果是禁止下游用 struct 字面量构造、禁止穷尽 struct 模式（本机实测：同 crate 内 `let S { a } = s;` 仍编译通过，判据同上）。

## Guards, if let, while let, and let-else

**match guard** 是 arm 上的 `if` 条件：`Some(x) if x > 0 => ..`。守卫在模式匹配成功**之后**求值，失败就继续试下一条 arm。守卫里的绑定是借用语义（守卫不能夺走所有权），这是它被限制的直接原因。

`if let` / `while let` 是「只关心一个分支」的语法糖，代价是**放弃穷尽性检查**——它们没有 E0004。`while let Some(v) = it.next()` 之所以是最常见的迭代器循环写法，正是因为循环终止条件天然就是「模式不再成立」。

`let`-else（1.65.0 stable，据 release notes）把「`let` 只接受 irrefutable」改成「失败就走 `else` 块」：

```rust
pub fn f(x: Option<u8>) -> u8 {
    let Some(v) = x else { return 0 };
    v
}
```

`else` 块必须以发散表达式收尾（`return` / `break` / `panic!`），因为 `v` 必须在 `else` 之后仍然有效可用——这条约束是 `let`-else 与普通 `match` 的关键差别。

版本差异这块最容易写错，逐个给判据（三态辨析的机制见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)，此处只结论）：

| 语法 | stable 版本 | 是否分 edition | 判据 |
| :-- | :-- | :-- | :-- |
| or 模式顶层 `\|` | 1.53.0 | 不分 edition | 据 release notes；本机 1.98.1 双 edition 实测均可用 |
| `let`-else | 1.65.0 | 不分 edition | 据 release notes；本机 1.98.1 实测可用 |
| match ergonomics（DBM） | 1.26.0 | 不分 edition（原始规则） | 据 1.26.0 release notes "Pattern matching automatically applies dereferences" |
| `mut` / `ref` / `&` 在隐含借用模式下的限制 | 随 edition 2024（1.85.0） | **仅 2024** | RFC 3627；本机双 edition 实测（见上） |
| `let` 链（`if let .. && ..`） | 1.88.0 | **仅 2024** | 本机实测：`--edition 2021` 报 `error: let chains are only allowed in Rust 2024 or later`；2024 通过 |
| match arm 上的 `if let` 守卫 | 1.95.0 | **不分 edition** | 本机实测：`Some(inner) if let Some(v) = inner => v` 在 1.98.1 的 2021 与 2024 下**双双编译通过**；另用 pinned `+1.95.0 --edition 2021` 实测亦通过 |

最后两行是同一屏的对照，也是最容易搞混的一对：`let` 链是 edition 独占，`if let` 守卫是版本独占。本机同时复现了两者——

```text
$ rustc +1.95.0 --edition 2021 --crate-type lib ifletguard.rs   # 编译通过（if let 守卫自 1.95.0）
$ rustc +1.95.0 --edition 2021 --crate-type lib letchain.rs     # error: let chains are only allowed in Rust 2024 or later
```

## Error Codes You Will Actually Hit

| 码 | 首行（本机实测措辞） | 根因 | 修法 |
| :-- | :-- | :-- | :-- |
| E0004 | non-exhaustive patterns: `E::C` not covered | 变体 / 值域未覆盖；或对跨 crate 的 `#[non_exhaustive]` 类型没写 `_` | 补齐 arm，或按场景写 `_` |
| E0005 | refutable pattern in local binding | 把可反驳模式放进 `let` / 参数 / `for` | 改 `match`，或改 `let`-else |
| E0308 | mismatched types（常表现为 `expected (), found &String`） | 绑定模式与预期不符：按引用匹配却当成按值用 | 加 `*` 解引用，或改 scrutinee 的引用层数 |
| E0382 | borrow of partially moved value: `opt` | 按值匹配移走了非 `Copy` 字段 | 改 `match &opt`，或 `Some(ref s)` |
| E0507 | cannot move out of `opt` .. which is behind a mutable reference | `mut` / 按值绑定试图从引用后移出 | 2024 下先消掉非法 `mut`；否则改 `ref mut` / `&mut` 模式 |
| E0783 | `...` range patterns are deprecated | 用了三点的历史 inclusive range | 改 `..=` |
| —（无码） | cannot mutably bind by value within an implicitly-borrowing pattern | 2024 的 RFC 3627 规则 1 | 把前缀写全：`&mut Some(mut s)` |

## Cross-language Comparison

模式匹配在四门语言里的形态差别，最能拉开的是「穷尽性是否由语言保证」和「匹配与绑定是否同一次动作」这两列：

| 维度 | Rust | C++ | Java | Python |
| :-- | :-- | :-- | :-- | :-- |
| 语法载体 | `match` 表达式 + 所有 `let` / 参数位置 | `switch`（仅常量）；结构化绑定（C++17）；`std::visit` + overload set（C++17） | `switch` 表达式 / 语句，**自 Java 21 起支持模式**（JEP 441） | `match` 语句，**自 Python 3.10 起**（PEP 634） |
| 结构化解构 | 语言级（struct / enum / tuple / slice） | 结构化绑定只覆盖固定成员，无「判定 + 解构」合一 | 类型模式 + record 模式（JEP 440，Java 21） | 序列 / 映射 / 类模式，可嵌套 |
| 穷尽性 | **语言保证**（E0004 硬错误） | `std::visit` 漏分支是编译错误；`switch` 无 | 模式 `switch` 覆盖检查是编译错误；`default` 可绕过 | 无（无匹配则是 no-op） |
| 绑定即所有权 | 是（DBM 决定 move / borrow） | 否（引用 / 值拷贝由声明决定） | 否（引用语义） | 否（对象引用） |
| 守卫 | arm 上的 `if`，1.95.0 起可直接写 `if let` | `std::visit` 里靠 `if`；提案里有 `if` 子句 | `when` 子句（guarded pattern） | case 后的 `if` 子句 |
| 未来方向 | `let` 链（仅 2024）、`if let` 守卫（1.95.0） | **语言级模式匹配尚未进标准**：P2688R6（2026-09-22）未获 EWG 共识，目标 C++29；今天只有 `std::visit` + 结构化绑定 | Java 24 起 primitive type pattern 为预览特性 | 稳定，无后续扩展 |

三点使用上的提醒：

- **C++ 不要写「C++26 有模式匹配」**。P2688 在 2025-02 Hagenberg 会议的 EWG 投票结果是 "Not consensus"，C++26 已完成技术工作且不含该特性，提案现在指向 C++29；截至写作时没有任何 shipping 编译器可用。当前唯一可用的近似是 `std::variant` + `std::visit` + overload set（C++17），它能给出穷尽性检查，但**不能**在匹配的同时解构，也不能按值匹配。
- **Java 的模式匹配是分批改出来的**：`instanceof` 类型模式在 Java 16（JEP 394）转正，`switch` 模式匹配在 Java 21（JEP 441）转正，同版本的 record 模式是 JEP 440。写「Java 支持 switch 模式匹配」而不带版本号会被误读成更早的版本。
- **Python 的 `match` 与 Rust 的 `match` 只是同名**。PEP 634 的语义是「按 case 顺序试，失败就下一个，全不匹配则整个块是 no-op」，没有穷尽性概念；而且序列模式**不匹配迭代器、也不匹配字符串**（据 PEP 634），这两条限制在写解析器时最容易踩。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Collections](/docs/CS/Rust/Collections.md)
- [Error_Handling](/docs/CS/Rust/Error_Handling.md)
- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [Macros](/docs/CS/Rust/Macros.md)
- [Languages](/docs/CS/Languages.md)

## References

- [The Rust Reference - Patterns](https://doc.rust-lang.org/reference/patterns.html)
- [The Rust Reference - Binding modes](https://doc.rust-lang.org/reference/patterns.html#binding-modes)
- [The Rust Reference - Match expressions](https://doc.rust-lang.org/reference/expressions/match-expr.html)
- [The Rust Reference - The non_exhaustive attribute](https://doc.rust-lang.org/reference/attributes/type-system.html#the-non_exhaustive-attribute)
- [RFC 2005 - Match Ergonomics](https://rust-lang.github.io/rfcs/2005-match-ergonomics.html)
- [RFC 3627 - Match Ergonomics 2024](https://rust-lang.github.io/rfcs/3627-match-ergonomics-2024.html)
- [Edition Guide - Match ergonomics reservations](https://doc.rust-lang.org/edition-guide/rust-2024/match-ergonomics.html)
- [The Rust Programming Language - Patterns and Matching](https://doc.rust-lang.org/book/ch18-00-patterns.html)
- [Rust 1.26.0 release notes - match ergonomics and fixed slice patterns](https://blog.rust-lang.org/2018/05/10/Rust-1.26.html)
- [Rust 1.42.0 release notes - subslice patterns](https://blog.rust-lang.org/2020/03/12/Rust-1.42.html)
- [Rust 1.53.0 release notes - or-patterns](https://blog.rust-lang.org/2021/06/17/Rust-1.53.0.html)
- [Rust 1.65.0 release notes - let-else](https://blog.rust-lang.org/2022/11/03/Rust-1.65.0.html)
- [Inside Rust - Recent and future pattern matching improvements](https://blog.rust-lang.org/inside-rust/2020/03/04/recent-future-pattern-matching-improvements/)
- [JEP 441 - Pattern Matching for switch](https://openjdk.org/jeps/441)
- [JEP 440 - Record Patterns](https://openjdk.org/jeps/440)
- [PEP 634 - Structural Pattern Matching: Specification](https://peps.python.org/pep-0634/)
- [P2688R6 - Pattern Matching: match Expression](https://open-std.org/jtc1/sc22/wg21/docs/papers/2026/p2688r6.html)
