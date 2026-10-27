## Introduction

`macro_rules!` 处理的是 **token 的形状**（重复、分隔、片段），过程宏处理的是 **token 的语义**——它是一段编译期执行的 Rust 程序，读入 token 流、解析成语法树、生成新的项。这条区别带来全部收益与全部代价：收益是它能做任何基于语法的代码生成（serde 的 derive、sqlx 的编译期 SQL 检查、tracing 的 span 注入），代价是它**永远看不到类型**，且必须在自己的 crate 里、以动态库的形式被编译器加载。

macro_rules 的语法、卫生性与内建宏归 [Macros](/docs/CS/Rust/Macros.md)，本篇只讲过程宏。实测环境为 `rustc 1.98.1` / `aarch64-apple-darwin`，版本事实按写作时核实的结果写。

## Three Kinds

| 形态 | 属性 | 输入 | 输出 | 典型用途 |
| :--- | :--- | :--- | :--- | :--- |
| function-like | `#[proc_macro]` | 括号内 `TokenStream` | 任意语法片段 | DSL、`macro_rules!` 做不了的拼接 |
| derive | `#[proc_macro_derive]` | 目标**项**的 token | **额外**生成项 | `Clone`、`serde::Serialize` |
| attribute | `#[proc_macro_attribute]` | 属性参数 + 被标注项 | **替换**被标注项 | `#[tokio::main]`、`#[derive_builder]` |

derive 只能"在旁边加东西"，attribute 宏可以整段重写目标项——这条区别决定了 `#[derive(Clone)]` 永远改不了字段。

## Why Procedural Macros Must Live in Their Own Crate

`[lib] proc-macro = true` 不是打包偏好，而是因果必需。四条本机实测诊断摆出整条链：`the #[proc_macro] attribute is only usable with crates of the proc-macro crate type`、`E0432: unresolved import 'proc_macro'`（普通 crate 链接不到该 crate）、`can't use a procedural macro from the same crate that defines it`、`` `proc-macro` crate types currently cannot export any items other than functions tagged with #[proc_macro], #[proc_macro_derive], or #[proc_macro_attribute] ``。

链条是：**展开器要调用你的代码，而调用意味着加载一个已编译的宿主平台动态库。** 你自己的 crate 此刻正在被编译、还没有可用产物，于是循环。所以过程宏必须是"在使用者之前编好的独立 crate"，且只能导出宏入口——内部逻辑得拆到另一个普通 crate，这正是很多宏库同时有 `foo` 与 `foo-derive` 两个包的原因。

这也正是与 C++ 的分水岭：C++ 的 `#include` 把声明与定义**文本地塞进同一个编译单元**，模板因此能在同一 TU 里惰性实例化、边解析边求值，顺手得到一门图灵完备的编译期语言（见 [C++ 模板](/docs/CS/C++/Templates.md)），代价是头文件依赖、ODR、编译时间和几百行的模板报错。Rust 反过来：编译期可执行代码被关进一个预先编好的沙箱 crate，边界干净、增量可控，但宏永远看不到类型。

## The de Facto Toolchain

手写 `TokenStream` 字符串拼接是可证明的坏主意：`format!("...").parse().unwrap()` 会丢掉全部原始 span（新 token 一律落在 call site），错误定位退化成"指到宏属性那一行"，还容易 panic。事实标准：

| crate | 角色 |
| :--- | :--- |
| `proc-macro2` | 可脱离编译器测试的 `TokenStream` 替身 + `Span::call_site()` / `Span::mixed_site()` 显式卫生控制 |
| `syn` | 把 token 解析成 Rust 语法树（`DeriveInput`、`Fields`、`Type`……） |
| `quote` | `quote! { }` 反引用插值生成 token，`#( ... )*` 对应重复 |
| `darling` | 解析 attribute 参数（`#[builder(default)]` 这类选项） |
| `paste` | 标识符拼接 |

版本现实要盯住：`syn` 的 1.x / 2.x / 3.x **大版本 API 不兼容**，依赖树锁了哪条线直接决定宏源码的写法；`darling` 0.20 到 0.24 之间也有 breaking。升级宏 crate 时第一个要查的就是这两行。

### A Minimal derive

下面这个 derive 在本机真实编译，使用方 `Cfg::builder().host(s).port(1).build()` 也通过，是可以直接抄的最小骨架：

```rust
use proc_macro::TokenStream;
use quote::{format_ident, quote};
use syn::{parse_macro_input, Data, DeriveInput, Fields};

#[proc_macro_derive(Builder)]
pub fn derive_builder(input: TokenStream) -> TokenStream {
    let input = parse_macro_input!(input as DeriveInput);
    let Data::Struct(s) = &input.data else { panic!("Builder 只能 derive 到 struct") };
    let Fields::Named(n) = &s.fields else { panic!("Builder 只支持具名字段的 struct") };
    let name = &input.ident;
    let builder = format_ident!("{}Builder", name);
    let idents: Vec<_> = n.named.iter().map(|f| f.ident.as_ref().unwrap()).collect();
    let tys: Vec<_> = n.named.iter().map(|f| &f.ty).collect();
    let out = quote! {
        struct #builder { #(#idents: Option<#tys>),* }
        impl #name { fn builder() -> #builder { #builder { #(#idents: None),* } } }
        impl #builder {
            #(#idents(mut self, v: #tys) -> Self { self.#idents = Some(v); self })*
            fn build(self) -> Result<#name, String> {
                Ok(#name { #(#idents: self.#idents.ok_or_else(|| stringify!(#idents).to_string())? ),* })
            }
        }
    };
    out.into()
}
```

`format_ident!` 就是"受控的 `##`"；`#(#idents: Option<#tys>),*` 把几个平行 Vec 同步展开成逗号列表。`syn` 只负责解析、`quote` 只负责生成、互不越界，是这套工具能用少数原语覆盖绝大多数宏的原因。

## What derive Can and Cannot Do

- **不能给被 derive 的类型加字段。** derive 的输出是"另发的项"，原类型定义不动一行；要改字段只能用 attribute 宏重写整个项，或用 function-like 宏生成字段列表。
- **不能实现 `Drop`。** 实测 `#[derive(Drop)]` → `error: cannot find derive macro Drop in this scope` + `= note: 'Drop' is in scope, but it is only a trait, without a derive macro`。析构必须手写，理由见 [Drop](/docs/CS/Rust/Drop.md)。
- **不能声明未登记的辅助属性。** 上例没写 `attributes(builder)`，于是使用方的 `#[builder(default)]` 报 `error: cannot find attribute 'builder' in this scope`。辅助属性必须在 `#[proc_macro_derive(Builder, attributes(builder))]` 里登记，这是 derive 与使用方之间的显式契约。
- **会给泛型加机械的 bound**，这是最著名的陷阱：

```rust
#[derive(Clone)]
pub struct Handle<T> { inner: std::rc::Rc<T> }
pub struct NotClone;
pub fn needs_clone<H: Clone>(_h: H) {}
pub fn probe(h: Handle<NotClone>) { needs_clone(h); }   // E0277
```

`Rc<T>` 对**任何** `T` 都是 `Clone`，但 derive 生成的是 `impl<T: Clone> Clone for Handle<T>`。真实诊断替你把解法写出来了：`= help: consider manually implementing Clone to avoid undesired bounds`。解法是手写 `impl<T> Clone for Handle<T> { fn clone(&self) -> Self { Self { inner: self.inner.clone() } } }`。同一机制解释了 `#[derive(Default)]` 对 `PhantomData<T>` 加 `T: Default` 的问题：derive 只看类型参数是否**出现**，不看字段是否真的需要它。机制细节在 [Trait_System](/docs/CS/Rust/Trait_System.md) 与 [Generics](/docs/CS/Rust/Generics.md)。

## Spans and Error Reporting

span 是卫生性与诊断质量的共同载体，`proc_macro2` 提供两档显式控制：

- `Span::call_site()`：生成的 token 属于**调用点**。它会被调用方局部变量遮蔽（这是卫生性的一半），错误落在调用点（这是诊断的一半）。
- `Span::mixed_site()`：按声明宏规则处理局部符号——生成的**标识符**不参与调用方遮蔽，其它 token 仍按 call_site。

手搓 `String` + `parse()` 把所有 token 变成 call-site span，副作用三合一：错误定位差、IDE 跳转失效、`rustfmt` 无从格式化。

错误路径要分两条：**用户输入不合法**应该产出 `syn::Error` 并 `to_compile_error()` 转成带 span 的诊断；**宏自己有 bug** 才 panic。前者的标准封装是 `proc_macro_error`，它提供 `abort!` / `emit!` 系列，把错误渲染成正常诊断而不是 `error: proc-macro derive panicked` 加一条 `= help: message: ...`。

## Failure Modes of Attribute Macros

**一、错误定位在展开产物上。** 一个把项复制两遍的 attribute 宏，本机报 `E0428: the name 'solo' is defined multiple times`，caret 只落在 `#[duplicate]` 那一行，并附 `= note: this error originates in the attribute macro 'duplicate' (in Nightly builds, run with -Z macro-backtrace for more info)`。诊断能告诉你是哪个宏造成的，但给不出展开后的行号；要看完整展开链得开 `-Z macro-backtrace`，那是 nightly 专属。

**二、宏内部 panic 只剩一条几乎无信息的错误。** 上面那个 `Builder` derive 用在 `enum` 上会走 `panic!` 分支，本机报 `error: proc-macro derive panicked` + `= help: message: Builder 只能 derive 到 struct`，caret 只落在 `#[derive(Builder)]` 的属性名上。panic 穿越展开器时丢了文件行号与上下文。`proc_macro_error`（以及后续 `unwind` 方向的工作）解决的就是这件事：**用 `abort!` 输出正常诊断而不是 panic**；更朴素的写法是把 `syn::Error` 转成 `to_compile_error()` 返回。写宏时应把"用户输入不合法"和"宏自己有 bug"分成两条路径。

**三、与 `cfg` 和 feature 的交互。** 过程宏展开发生在 `cfg` 求值**之前**，所以宏生成的代码里写的 `#[cfg(...)]` 会被正常求值，但宏**自己**的代码看不到调用方的 cfg 环境。这意味着"derive 在某个 feature 下少生成一个字段"这类需求只能通过辅助属性显式传参，没有反射可用。

**四、编译期与交互成本。** 过程宏是宿主 dylib：改宏 crate 会让所有使用者重编，展开时反复做 `TokenStream` 转换与解析是真实开销——`cargo check` 变慢、IDE 卡顿的常见根因就在这里。测量与缓解见 [工具链](/docs/CS/Rust/Tooling.md)。

## Hygiene: What You Get and What You Do Not

macro_rules 的混合站点卫生（局部变量不泄漏、也不被调用方遮蔽）在过程宏里**不存在**，你只有 span 这一种原始工具：

- 生成的标识符默认是 call-site span，能被调用方的同名项遮蔽——所以宏里要引用标准库时写 `$crate` 式的全路径（proc-macro2 提供 `proc_macro_crate` crate 帮你确定路径），绝不要写裸的 `std::`。
- 反过来，宏生成的**新类型名**要与调用方可能存在的名字区分，`format_ident!("{}Builder", name)` 比拼接字符串更安全，但仍可能与调用方的 `FooBuilder` 撞车——这是过程宏无法根治的问题，只能靠命名约定（`__Foo` 前缀之类）缓解。
- 与 C 预处理器的对照（文本替换、无卫生、无语义）见 [Macros](/docs/CS/Rust/Macros.md) 与 [C 预处理器](/docs/CS/C/Preprocessor.md)。

## Expansion and Tooling

看展开结果只有编译器自己的产物可信：`cargo +nightly rustc -- -Zunpretty=expanded`（展开到 stdout）或包装工具 `cargo expand`。

本机如实说明：**stable 上跑不出来**——`rustc -Zunpretty=expanded` 报 `error: the option Z is only accepted on the nightly compiler`，旧式 `--pretty=expanded` 直接 `error: Unrecognized option: 'pretty'`。因此所有展开结论都应来自诊断文本与文档描述，而非展开产物；要真看展开，本地装一个 nightly 是写宏的基本投入。

## Case Studies: What This Buys in Practice

三个被广泛使用的宏，各代表一种"没有过程宏就做不了"的模式：

- **`serde_derive`**：读取类型定义，为每种目标格式生成 `Serialize` / `Deserialize` 实现。关键点是**零拷贝反序列化**（`&str` 字段直接借用输入缓冲）——这要求 derive 生成的代码对每个字段选择"借用还是拷贝"，是类型系统 + 代码生成合作的范本。详见 [Serde](/docs/CS/Rust/Serde.md)。
- **`thiserror`**：把一个错误枚举的 doc 注释与 `#[from]` 属性编译成 `Display` + `Error` 实现。它只依赖 `core::fmt`，所以 no_std 可用（[No_Std](/docs/CS/Rust/No_Std.md)）。
- **`sqlx`**：编译期连接真实数据库执行查询，把结果的列类型**检查**进你的 Rust 代码。这是过程宏能做到的最激进的事：编译期 IO。代价是构建期要有数据库可达，与 `bindgen` 在 build.rs 里读头文件是同一类契约。

## Choosing Between macro_rules and Procedural Macros

| 判据 | `macro_rules!` | 过程宏 |
| :--- | :--- | :--- |
| 需要读**语法结构**（字段列表、类型） | 做不到 | 可以 |
| 需要卫生的局部变量 | 有 | 要自己用 span 处理 |
| 可以和使用者在同一 crate | 是 | **否**（必须独立 crate） |
| 编译期开销 | 低 | 高（dylib + 解析） |
| 错误信息质量 | 中（follow set 限制） | 可做到很好（span 控制），也可很差 |
| 调试手段 | 诊断文本 | `cargo expand`（nightly） |

默认答案：能用 `macro_rules!` 解决的重复就用它；只有需要"理解结构再生成"时才上过程宏。

## Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | 宏与使用者同 crate | `can't use a procedural macro from the same crate that defines it` | 拆 `foo` / `foo-derive` |
| 2 | 生成裸 `std::` 路径 | 用户 crate 里 `std` 被遮蔽时报错 | `$crate` 或 `proc_macro_crate` |
| 3 | derive 给泛型加机械 bound | `E0277` 卡住不需要 bound 的类型 | 手写 impl（诊断会提示） |
| 4 | `#[derive]` 到 enum / union | `error: proc-macro derive panicked` | `syn::Error` + `to_compile_error()` |
| 5 | 忘了登记辅助属性 | `cannot find attribute 'builder' in this scope` | `attributes(builder)` 登记 |
| 6 | `String` + `parse()` 造 token | 错误定位退化、IDE 失效 | `proc-macro2` + `quote` |
| 7 | `compare_exchange_weak` 式一次性 CAS 思维写宏 | 以为展开总成功 | 展开**可能 panic**，所有输入都要处理 |
| 8 | 同步 syn 大版本 | 依赖树锁 1.x，源码按 2.x 写 | 升级前查 `cargo tree` |
| 9 | 忘了 macro 不感知 cfg | "按 feature 少生成字段"失效 | 辅助属性显式传参 |
| 10 | 在 CI 里跑 `cargo expand` | nightly-only 失败 | 本地 nightly 或放弃展开验证 |

## Links

- [Macros](/docs/CS/Rust/Macros.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [Serde](/docs/CS/Rust/Serde.md)
- [工具链](/docs/CS/Rust/Tooling.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)

## References

1. [The Rust Reference — Procedural macros](https://doc.rust-lang.org/reference/procedural-macros.html)
2. [proc-macro2 docs](https://docs.rs/proc-macro2/latest/proc_macro2/)
3. [syn docs](https://docs.rs/syn/latest/syn/)
4. [quote docs](https://docs.rs/quote/latest/quote/)
5. [proc-macro-error](https://docs.rs/proc-macro-error/latest/proc_macro_error/)
6. [cargo-expand](https://github.com/dtolnay/cargo-expand)
