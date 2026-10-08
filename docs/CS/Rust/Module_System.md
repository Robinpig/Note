## Introduction

Rust 的模块系统之所以让人困惑，几乎从来不是因为语法难，而是因为三个**不在同一层**的概念被塞进了同一批词里：**crate** 是编译单元（rustc 一次运行产出的一份产物），**package** 是 Cargo 的打包与依赖单位（`Cargo.toml` 描述的一个可发布单元，可含一个 lib target 加多个 bin target），**module** 是 crate 内部的命名空间树。三者之间没有包含关系上的一一对应：一个 package 大概率只有一个 crate，但一个 package 可以有多个 crate（多个 bin target 各自是一个 crate），一个 crate 又可以有任意深的 module 树。把 "package" 当成 "crate" 的同义词、或把 "module" 当成 "文件" 的同义词，是后面所有困惑的源头。

于是模块系统真正要解决的只有一个问题：**在一个 crate 内部，用一个树形命名空间把名字组织起来，并精确控制每个名字在树的哪个范围内可见**。文件怎么摆只是这个命名空间树的物理映射，可见性才是设计上的本体。本篇的分量也按这个顺序分配：模块树与文件映射只是铺垫，**可见性**占全篇最重的一节——尤其要钉死一条最容易搞错的规则：**"私有"在 Rust 里的真实含义是"对当前模块及其所有后代可见"，而不是"只在定义它的那个模块内可见"**。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，最新 edition 为 2024。本篇所有标注"实测"的诊断与输出均在本机 `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1`（host `aarch64-apple-darwin`）上真实编译运行取得，原文照抄，只把路径前缀归一为 `src/lib.rs` / `tests/it.rs`。跨 edition 对照用 `rustc --edition <年份>` 逐版实测。标注"据文档"的条目指取自 Rust Reference / Edition Guide / release notes，未在 1.98.1 上复现。

边界：package / target / manifest 字段见 [Cargo](/docs/CS/Rust/Cargo.md)；edition 与 uniform paths 的版本归属见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)，本篇只引用不重写；宏系统本体（`macro_rules!` 语法、fragment specifier、过程宏）见 [Macros](/docs/CS/Rust/Macros.md)，本篇只讲宏与模块作用域相交的那一面。

## Three Layers: Crate, Package, Module

| 概念 | 谁定义 | 单位 | 边界在哪 | 一个典型误解 |
| :-- | :-- | :-- | :-- | :-- |
| **crate** | rustc | 编译单元，也是**可见性的最大边界** | `pub` 的对外可见性止于 crate；`pub(crate)` 正好覆盖整个 crate | "一个包就是一个 crate"——多个 bin target 时不是 |
| **package** | Cargo | `Cargo.toml` 描述的可发布单元 | 最多一个 lib target + 任意多个 bin target；还有 example / test / bench target | "package 和 module 是一回事"——完全不在一层 |
| **module** | rustc | crate 内的命名空间树节点 | `mod` 声明，可任意嵌套；文件只是它的物理映射 | "一个文件就是一个 module"——文件是映射，不是定义 |

三条推论值得单独拎出来：

- **`pub` 是"对 crate 外可见"，不是"对项目内可见"**。同一个 package 里的另一个 bin target 是另一个 crate，它看你这个 lib 时用的是和外部用户完全相同的视角——`pub(crate)` 的东西它一样看不见。这是"package ≠ crate"最直接的可观测后果。
- **crate 是可见性的天花板，也是孤儿规则（orphan rule）的作用域**。trait 与 impl 的相干性检查以 crate 为单位，跟 module 树无关（见 [Trait_System](/docs/CS/Rust/Trait_System.md)）。
- **module 树是纯逻辑结构**。`mod a { mod b {} }` 与拆成三个文件在语义上等价，编译器只认树，不认目录。

用一个最小 package 对照三者的物理位置：`[lib] name = "demo"` 是一个 crate，`[[bin]] name = "demo-cli"` 是**另一个 crate**——后者看前者时用的是和外部用户完全相同的视角，只有 `pub` 项可达。target 与 manifest 字段全貌见 [Cargo](/docs/CS/Rust/Cargo.md)。

## The Module Tree

### Crate Root and `mod` Declarations

每个 crate 有且只有一个**crate 根**——lib target 是 `src/lib.rs`，bin target 是 `src/main.rs`。根本身是一个匿名 module，整个 module 树从它长出来。`mod x { ... }` 把内容写在原地，`mod x;` 只声明"存在一个名为 x 的子模块"、内容从文件加载；两者语义等价、可以混用。

### File Mapping

`mod` 到文件的映射规则是**纯约定的目录查找**，没有 manifest 参与（这与 Java 的 `package` 声明必须与目录一致不同——Rust 里目录不参与名字解析，只参与"去哪找文件"）：

| 声明位置 | 声明 | 查找路径（相对声明所在文件） |
| :-- | :-- | :-- |
| crate 根 `src/lib.rs` | `mod foo;` | `src/foo.rs`，或 `src/foo/mod.rs` |
| `src/foo.rs` 内部 | `mod bar;` | `src/foo/bar.rs`，或 `src/foo/bar/mod.rs` |
| 任意位置 | `#[path = "weird/place.rs"] mod foo;` | `weird/place.rs`（相对当前文件目录） |

`mod.rs` 是 edition 2018 之前唯一的写法（当时 `foo.rs` 里不能放 `foo` 的子模块），2018 之后 `foo.rs` + `foo/` 目录成为推荐形式，`mod.rs` 只是**仍然被接受的历史写法**，不是必须。实测两种都编得过（`src/foo/mod.rs` 单独存在时 `cargo build` 通过）。

两者同时存在则歧义，实测：

```text
error[E0761]: file for module `foo` found at both "src/foo.rs" and "src/foo/mod.rs"
 --> src/lib.rs:1:1
  |
1 | mod foo;
  | ^^^^^^^^
  |
  = help: delete or rename one of them to remove the ambiguity
```

`#[path]` 是逃生舱：它**覆盖**目录查找规则，让模块名与文件位置彻底解耦。实测 `#[path = "weird/place.rs"] mod foo;` 后面用 `foo::A` 访问 `src/weird/place.rs` 里的项，编译通过。它的合法用途很少（主要是把 `#[cfg]` 分平台的实现塞进不同文件），滥用会让读者无法从模块名推断文件位置。

## Paths

### Prefixes and Absolute vs Relative

| 前缀 | 含义 | 何时必须用 |
| :-- | :-- | :-- |
| `crate::` | 从**当前 crate 的根**出发，绝对 | 从任意深度跳回根的推荐写法 |
| `self::` | 从**当前模块**出发，相对 | 消除与外层同名项的歧义 |
| `super::` | 从**父模块**出发，相对 | 子模块访问父模块项（可叠加 `super::super::`） |
| `::name` | 从**外部 crate**（extern prelude）出发 | 2018 起用于显式区分外部 crate 名，避免与本地项撞名 |
| 无前缀 | 从当前模块作用域内的名字出发 | 普通表达式路径；`use` 里在 2018+ 也可用（见下） |

`::std::fmt::Display` 这种写法的关键作用不是"更绝对"，而是**消歧**：当本地有一个叫 `std` 的模块时，裸 `std::` 会解析到本地项，`::std::` 强制走外部 crate。实测 `::std::format!("{}", 2)` 正常编译。

### What Uniform Paths Actually Unified (edition 2018)

edition 2018 改的是 **`use` 声明里路径的解析起点**，这不是语法糖而是语义变化（详细归属见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)，此处只给实测判据）：

- **2015**：`use` 里的路径**永远是"从 crate 根出发的绝对路径"**，与 `use` 写在哪个模块无关。
- **2018 及以后**：`use` 里的路径**与其他任何路径一样解析**——可以以当前模块内的项开头，也可以用 `crate` / `self` / `super` / 外部 crate 名开头。

同一份源码跨 edition 实测，最干净的对照是"在模块 `a` 内 `use` 它自己的子模块 `inner`"：

```rust
pub mod a {
    pub mod inner { pub fn f() -> u32 { 1 } }
    use inner::f;          // 相对「当前模块 a」
    pub fn g() -> u32 { f() }
}
```

| edition | 结果 |
| :-- | :-- |
| 2015 | `error[E0432]: unresolved import `inner``，help 提示改成 `use self::inner::f;` |
| 2018 / 2021 / 2024 | 编译通过 |

反方向的对照同样必要——在 `mod b` 里 `use` 根下的 `a`：

| edition | 结果 |
| :-- | :-- |
| 2015 | 编译通过（绝对路径，正好命中 `crate::a`） |
| 2018 / 2021 / 2024 | `error[E0432]: unresolved import `a``，note 指向 Edition Guide 的 path-clarity 章，help 提示改成 `use crate::a::f;` |

也就是说 2018 的"统一"是**让 `use` 与普通路径共享同一套解析规则**，而不是"让所有写法都能编"。代价正是上表第二行：2015 里能编的写法在 2018 后可能失效，`cargo fix --edition` 的主战场之一就是给这批 `use` 补 `crate::`。

### `pub(in path)` Uses a Different Rule Than `use`

一个容易踩的岔路：**可见性限制里的路径永远是 crate 绝对的，不受 edition 的 uniform paths 影响**。实测 `pub(in crate::a)` 在 2015 / 2018 / 2024 三个 edition 下全部编译通过；而写成相对形式在 2018+ 直接被拒：

```text
error: relative paths are not supported in visibilities in 2018 edition or later
 --> src/lib.rs:3:16
  |
3 |         pub(in a) fn semi() -> u32 { 1 }
  |                ^ help: try: `crate::a`
```

## Visibility

### What "Private" Really Means

这是全篇最需要钉死的一条。**Rust 里"私有"= 对声明它的模块及其所有后代模块可见**。三个方向都要实测才不会记反：

```rust
fn secret() -> u32 { 42 }          // 根里的私有项

pub mod a {
    pub fn f() -> u32 { super::secret() }        // 子模块访问父私有：可以
    pub mod deep {
        pub fn g() -> u32 { crate::secret() }    // 孙模块访问祖私有：可以
    }
}

pub mod b {
    use crate::secret;                            // 兄弟模块：可以
    pub fn h() -> u32 { secret() }
}
```

上面四个全部编译通过（实测）。注意最后一条最反直觉：`b` 与 `a` 是平级兄弟，`secret` 也不在 `b` 里——但因为 `secret` 声明在 crate 根，而**所有模块都是根的后代**，所以它对整个 crate 都可见。推论：**在 crate 根声明的私有项等价于 `pub(crate)`**（差别只在意图表达与 lint 提示）。

反向的对照更关键——**可见性是单向向下的，父不能访问子的私有项**：

```rust
pub mod a {
    fn inner() -> u32 { 1 }
    pub fn f() -> u32 { inner() }        // a 内部当然可以
}

pub fn from_root() -> u32 { a::inner() } // 根是 a 的祖先，不是后代
```

实测：

```text
error[E0603]: function `inner` is private
 --> src/lib.rs:6:32
  |
6 | pub fn from_root() -> u32 { a::inner() }
  |                                ^^^^^ private function
  |
note: the function `inner` is defined here
 --> src/lib.rs:2:5
  |
2 |     fn inner() -> u32 { 1 }
  |     ^^^^^^^^^^^^^^^^^
```

一句话记法：**可见性沿模块树向下流动，不向上流动**。这也是为什么 `#[cfg(test)] mod tests` 里写 `use super::*` 就能测私有项——`tests` 是被测模块的**子模块**（见 [Testing](/docs/CS/Rust/Testing.md)）。

### The Visibility Ladder

| 写法 | 可见范围 | 版本归属 |
| :-- | :-- | :-- |
| （不写） | 当前模块 + 其所有后代 | 1.0 |
| `pub(super)` | 父模块 + 父的所有后代 | `pub(restricted)` 自 **1.18.0（2017-06-08，RFC 1422）** 起 stable（据 release notes） |
| `pub(crate)` | 整个 crate | 同上 |
| `pub(in path)` | `path` 及其后代，`path` 必须是**祖先模块** | 同上 |
| `pub` | 无限制（对外可见） | 1.0 |

`pub(in path)` 的两条硬约束都有实测：

**一、只能是祖先模块，不能是后代**：

```text
error[E0742]: visibilities can only be restricted to ancestor modules
 --> src/lib.rs:2:12
  |
2 |     pub(in crate::a::deep) fn only_deep() -> u32 { 1 }
  |            ^^^^^^^^^^^^^^
```

**二、路径必须写全**（见上一节的 `relative paths are not supported`）。

正确用法实测：`pub mod a { pub mod deep { pub(in crate::a) fn semi() -> u32 { 1 } ... } }` 之下，`a::f()` 访问 `deep::semi()` 编译通过（a 是祖先），而 crate 根与兄弟模块访问同一项都报 E0603。：前者把可见范围钉在 `a` 这棵子树上，根与兄弟模块都进不来。它是**在不拆 crate 的前提下做"库内部分层"**的唯一工具——比如让 `internal` 子树只能被 `api` 层调用。

### Field-level Visibility

可见性是**逐字段**判定的，跟结构体整体的可见性相互独立：`pub struct S { pub open: u32, closed: u32 }` 里 `closed` 只在当前模块及其后代里可读写。从外部 crate 构造它，实测：

```text
error[E0451]: field `closed` of struct `S` is private
 --> tests/it.rs:4:26
  |
4 |     let s = S { open: 1, closed: 2 };
  |                          ^^^^^^ private field
```

这条是"不变量封装"的落点：字段私有 + 构造器/访问器 `pub`，就能保证外部拿不到非法状态。注意 enum 的 variant 与 trait 的 item **没有**这种逐项可见性——variant 只能随 enum 整体可见（私有 enum 的 variant 不可再导出，这是 1.18 前后的旧坑）。

### When `pub` Buys Nothing

`pub` 只表示"愿意对外可见"，不表示"真的对外可达"。一个 `pub` 项放在私有模块里、又没有被 `pub use` 再导出，它对用户就是不可达的。三个相关机制实测如下。

**`unreachable_pub`**——提醒你写了无效 `pub`：

```text
error: unreachable `pub` item
 --> src/lib.rs:3:5
  |
3 |     pub fn unreachable() {}
  |     ---^^^^^^^^^^^^^^^^^
  |     |
  |     help: consider restricting its visibility: `pub(crate)`
  |
  = help: or consider exporting it for use by other crates
```

（上面是 `#![deny(unreachable_pub)]` 下的实测输出；默认级别是 allow-by-default，所以多数项目根本看不见它。）

**`private_interfaces`**——`pub` 函数签名里出现更私有的类型：

```text
error: type `Secret` is more private than the item `make`
 --> src/lib.rs:3:1
  |
3 | pub fn make() -> Secret { Secret }
  | ^^^^^^^^^^^^^^^^^^^^^^^ function `make` is reachable at visibility `pub`
  |
note: but type `Secret` is only usable at visibility `pub(crate)`
 --> src/lib.rs:2:1
  |
2 | struct Secret;
  | ^^^^^^^^^^^^^
```

这个函数对用户**可调用但返回值无法命名**，等于 API 里有个洞。正确做法是补 `pub type` 或把类型提到 `pub`。

**`pub use` 一个私有模块**——E0365，最常见的"我想导出但导不出去"：

```text
error[E0365]: `inner` is only public within the crate, and cannot be re-exported outside
 --> src/lib.rs:4:9
  |
4 | pub use inner as _inner_unused;
  |         ^^^^^^^^^^^^^^^^^^^^^^ re-export of crate public `inner`
  |
  = note: consider declaring type or module `inner` with `pub`
```

## `use` and Re-export

### What `use` Does Not Do

**`use` 只把名字引入当前作用域，不授予任何对外可见性。** 这不是细节而是模块系统的核心分工：`use` 管"我在这里怎么称呼它"，`pub` 管"它对谁可见"，两者正交。

实测最能说明问题的对照（`src/lib.rs` + `tests/it.rs`）：

```rust
mod inner {
    pub fn hidden() -> u32 { 1 }
    pub fn shown() -> u32 { 2 }
}
use inner::hidden;                 // 仅引入名字
pub use inner::shown;              // 再导出
pub fn go() -> u32 { hidden() }
```

```text
error[E0603]: function `hidden` is private
 --> tests/it.rs:5:20
  |                    ^^^^^^ private function
 --> src/lib.rs:5:5
  |     ^^^^^^^^^^^^^
```

外部 crate 里 `re::shown()` 与 `re::go()` 都能调，`re::hidden()` 报 E0603——而 note 指向的那一行正是 `use inner::hidden;`。**同一个 `use`，加不加 `pub` 决定了它是不是 API 的一部分。**

### `pub use` Is the Library Author's Main Tool

`pub use` 让**内部组织**与**对外 API**解耦：`inner` 模块怎么拆、怎么改名都不影响用户看到的路径。四个常见形态：提平（`pub use inner::shown;`）、改名（`pub use inner::shown as alias;`）、glob 再导出（`pub use crate::a::*;`，有风险见下）、嵌套加 `self`（`pub use std::io::{self, Read, Write};` 一次引入 `io` 与 `io::Read`）。`as` 重命名在 `use` 与 `pub use` 上都生效，主要用途是消名冲突和缩短路径。

### Glob Imports: The Trade-off

glob（`use foo::*`）在测试模块与 prelude 里很方便，在库代码里是负担：它让读者无法从文件头部判断一个名字来自哪里，而且**会静默引入未来的名字**（依赖升级加了一个同名项就可能撞上）。两个 glob 撞名的实测：

```text
error[E0659]: `X` is ambiguous
 --> src/lib.rs:9:33
  |
9 | pub fn read() -> u32 { use_one::X }
  |                                 ^ ambiguous name
  |
  = note: ambiguous because of multiple glob imports of a name in the same module
  = help: consider adding an explicit import of `X` to disambiguate
```

同一个源码还会附带 `warning: ambiguous glob re-exports ... = note: #[warn(ambiguous_glob_reexports)] on by default`。也就是说两个 `pub use ...::*` 撞名在定义处**只警告**，真正的 E0659 要等使用点才爆——所以库里别用 glob 再导出。

## `extern crate`

`extern crate foo;` 在 2018 之后**基本不再需要**：依赖已经在 extern prelude 里，直接用 `foo::` 即可。它仅存的用途是 `#[macro_use] extern crate foo;`（把旧式 `macro_rules!` 宏批量拉进 crate 根）和少数 sysroot 场景（`no_std` 下 `extern crate alloc;`，见 [No_Std](/docs/CS/Rust/No_Std.md)）。

edition 差异实测——同一句 `extern crate std;`：

| edition | 结果 |
| :-- | :-- |
| 2015 | `error[E0259]: the name `std` is defined multiple times`（根里已注入 `std`） |
| 2018 / 2024 | 编译通过，无警告（形同 no-op） |

一个有意思的对称：2015 里它**报错**，2018 后它**没用**。所以"新代码写不写 `extern crate`"的答案在 2018+ 是"不写"，而不是"写了更安全"。

## Conditional Compilation

条件编译是模块系统的近邻——它决定**哪些模块与项参与这次编译**：

```rust
#[cfg(feature = "serde")]           // 项/模块级：不满足则整个项不存在
mod serde_impl;

#[cfg_attr(feature = "serde", derive(Serialize))]   // 属性级：按条件挂属性
struct Config { /* ... */ }

pub fn probe() -> bool {
    cfg!(target_os = "macos")       // 表达式级：求值为 bool，两侧代码都要能编
}
```

三者的差别是**作用域层级**：`#[cfg]` 在编译前就把项删掉（未选中的分支连名字解析都不做，所以可以引用不存在的类型）；`cfg!` 只是求值的 `bool` 字面量，**两个分支都必须完整通过类型检查**。实测 `cfg!(target_os = "macos")` 在本机求值为 `true`，`cfg!(feature = "nope")` 为 `false`。

`#[cfg(test)]` 是同一机制的一个特例：它让测试模块在 `cargo build` 时**完全不存在**，只在 `cargo test` 编译时出现。这是一条单向门——它保证测试代码与测试依赖不进发布产物（feature 机制本体见 [Cargo](/docs/CS/Rust/Cargo.md)）。

## Macros Meet the Module System

`macro_rules!` 宏不遵守项的作用域规则，它用的是**文本作用域**（textual scope）：从定义处开始，向下覆盖同一个"文件展开序列"的剩余部分，包括之后声明的子模块。它**不会**自动进入兄弟模块，也**不会**随模块边界消失。

实测：在 `mod defs` 里定义、在 crate 根之后使用：

```text
error: cannot find macro `greet` in this scope
 --> src/lib.rs:6:27
  |
6 | pub fn outside() -> u32 { greet!() }
  |                           ^^^^^
  |
  = help: have you added the `#[macro_use]` on the module/import?
help: consider importing this macro through its public re-export
  |
1 + use crate::defs::greet;
  |
```

三条出路，各自对应不同场景：

1. **`#[macro_use] mod defs;`**（或 `#[macro_use] extern crate foo;`）——把该模块内的宏提到 crate 根的文本作用域，之后全 crate 可见。实测编译通过。这是旧式库的惯例，也是 `extern crate` 至今仍需存在的唯一理由。
2. **`pub(crate) use greet;`**（macro 2.0 式的 `use`）——实测上面 help 里正是这么建议的；需要宏是 `pub` 可见的。
3. **`#[macro_export]`**——把宏提到 **crate 根**，供外部 crate 用 `your_crate::mac!()` 调用。

`#[macro_export]` 的关键副作用必须记住：**宏被提到 crate 根，不再留在定义它的模块路径上**。实测：

```text
error[E0433]: cannot find `m` in `defs`
 --> src/lib.rs:6:34
  |
6 | pub fn g() -> u32 { crate::defs::m!() }
  |                                  ^ could not find `m` in `defs`
```

同一份代码里 `crate::m!()` 编译通过，外部 crate 里 `mc::m!()` 也通过（实测 integration test 通过）。也就是说 `#[macro_export]` 之后，宏的"地址"是 `crate::m` 而不是 `crate::defs::m`——**它打破了模块树的一一对应**，这是宏系统与模块系统唯一真正冲突的地方。宏本体见 [Macros](/docs/CS/Rust/Macros.md)。

## Pitfalls

| 坑 | 现象 | 怎么避 |
| :-- | :-- | :-- |
| `#[path]` 滥用 | 模块名与文件位置失去对应关系，读者找不到定义 | 只在 `#[cfg]` 分平台实现时用 |
| 两个 glob 撞名 | 定义处只 warn（`ambiguous_glob_reexports`），使用点才 E0659 | 库代码不用 glob 再导出 |
| `pub` 在私有模块里 | 写了很多 `pub` 但用户一个都调不到 | 开 `unreachable_pub`，或用 `cargo doc` 对照 |
| `pub` 签名里漏类型可见性 | `private_interfaces` 报 "more private than" | 返回值/参数类型与函数同步可见性 |
| 拆模块导致可见性回退 | 把函数移到子模块后，原来能调的地方报 E0603 | 记住可见性只向下：搬进子模块 = 对父不可见 |
| 父想读子的私有项 | E0603 "is private" | 加 `pub(super)` / `pub(crate)`，或把使用点也搬进子模块 |
| 循环 `use` | `use crate::a;` 写在 `a` 内部（自引用）或互相 `use` 循环 | `use` 不产生依赖环，删掉多余的自引用即可 |
| `mod.rs` 与 `foo.rs` 并存 | E0761 "found at both" | 2018+ 统一用 `foo.rs` + `foo/` |
| 2015 的 `use` 搬到 2018 | E0432 "unresolved import" | `cargo fix --edition` 补 `crate::` |

最后一条是**唯一一条与 edition 强相关**的坑，也是最容易被误判成"编译器坏了"的：代码没动、编译器升级后 `use` 突然失效，原因往往是路径解析起点变了，而不是名字没了。

## Cross-language Comparison

| 语言 | 命名空间单位 | 命名空间与文件的关系 | 可见性层级 | 私有 = 什么 | 引入机制 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **Rust** | module（可嵌套的树） | 目录只决定"去哪找文件"，**不参与名字解析**；`#[path]` 可彻底解耦 | 项级 + **模块树祖先/后代**，`pub(crate)` / `pub(super)` / `pub(in path)` | **对当前模块及其所有后代可见**（向下不向上） | `use`（编译期名字绑定，不影响可见性） |
| Java | package（扁平，无嵌套） | 目录必须与 `package` 声明一致 | 项级 `public` / `protected` / package-private / `private`，**无"对子包可见"** | 仅对同一个**顶层类**（含嵌套类）可见；同 package 不算私有 | `import`（编译期，不影响可见性）（见 [Java](/docs/CS/Java/Java.md)） |
| C++ | namespace（可嵌套） + TU | 头文件是**文本包含**，`#include` 把声明复制进 TU；目录与命名空间毫无关系 | 类成员三级 + namespace 只有"存在与否"；`friend` 可例外授予 | 仅对类自身及其 `friend` 可见 | `#include`（预处理期文本复制）+ `using`（见 [C++](/docs/CS/C++/C++.md)） |
| Python | package / module | 目录 + `__init__.py` 决定 package；`import` 在**运行时**执行模块代码 | 只有约定级（`_name` 下划线），**无强制私有** | 约定私有，外部仍可访问 | `import` / `from ... import`（运行时，有副作用、可动态改）（见 [Python](/docs/CS/Python/Python.md)） |
| Go | package（扁平） | 目录 = package，一个目录一个 package | 只有**首字母大小写**两级：导出 / 包内可见 | 小写标识符对**整个 package**（同一目录下所有文件）可见 | `import`（编译期，路径即 import path）（见 [Go](/docs/CS/Go/Go.md)） |

**"私有 = 对后代可见"这一列是 Rust 在这张表里最显眼的一行**。Java 的 `private` 是"对这个顶层类"，Go 的小写是"对整个 package"（package 是扁平的，所以等价于 crate 级），C++ 靠 `friend` 逐个点名；只有 Rust 把可见性做成了**沿树向下流动**的关系。这带来两个别的语言没有的性质：测试模块作为子模块天然能测私有项（不需要反射、不需要同包技巧），以及 `pub(in path)` 能在不拆包的前提下切出"库内部的可见性层"。

另一处差别同样结构性：C++ 与 Python 的"引入"分别是**文本复制**与**运行时执行**，都会产生可观测副作用（宏污染、import 时执行代码）；Rust 与 Java / Go 的引入是纯名字绑定，只影响"这里怎么称呼它"，因此**没有任何引入能让一个项变得更可见**——这条在上文 `use` 一节已由 E0603 实测钉死。

## Links

- [compile](/docs/CS/Rust/compile.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [Languages](/docs/CS/Languages.md)

## References

- [Rust Reference — Crates and source files](https://doc.rust-lang.org/reference/crates-and-source-files.html)
- [Rust Reference — Items: Modules](https://doc.rust-lang.org/reference/items/modules.html)
- [Rust Reference — Paths](https://doc.rust-lang.org/reference/paths.html)
- [Rust Reference — Visibility and Privacy](https://doc.rust-lang.org/reference/visibility-and-privacy.html)
- [Rust Reference — Use declarations](https://doc.rust-lang.org/reference/items/use-declarations.html)
- [Rust Reference — Conditional compilation](https://doc.rust-lang.org/reference/conditional-compilation.html)
- [Rust Reference — Macros By Example: Scoping, Exporting, and Importing](https://doc.rust-lang.org/reference/macros-by-example.html)
- [Rust Edition Guide — Rust 2018: Path clarity](https://doc.rust-lang.org/edition-guide/rust-2018/module-system/path-clarity.html)
- [Rust Edition Guide — Rust 2018: Module system](https://doc.rust-lang.org/edition-guide/rust-2018/module-system/index.html)
- [The Cargo Book — Defining a package / targets](https://doc.rust-lang.org/cargo/reference/cargo-targets.html)
- [The Cargo Book — Features](https://doc.rust-lang.org/cargo/reference/features.html)
- [Rust 1.18.0 release notes — Stabilize pub(restricted), RFC 1422](https://github.com/rust-lang/rust/blob/master/RELEASES.md#version-1180-2017-06-08)
