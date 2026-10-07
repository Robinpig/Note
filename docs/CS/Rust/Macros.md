## Introduction

Rust 的宏站在编译管线的**名称解析之前**：编译器先把源文件切成 token tree，反复调用展开器把宏调用换成语法片段，产出的**仍然是 AST 的一部分**，然后才交给名称解析、类型检查、借用检查（阶段划分见 [compile.md](/docs/CS/Rust/compile.md)）。这个位置同时决定了它的能力上限与全部痛苦来源：能拿到任意未解析的记号流、当前 cfg、环境变量，甚至编译期执行宿主代码的机会（过程宏）；拿不到类型信息、trait 求解结果、借用检查结果。代价就是错误定位到展开产物、`macro_rules!` 必须手写递归、过程宏必须独立 crate、IDE 必须重做一遍展开。

这与 C 预处理器是**两种不同的东西**，虽然中文都叫"宏"。[Preprocessor.md](/docs/CS/C/Preprocessor.md) 里 `#define SQR(x) x * x` 之所以咬人，是因为它不知道自己在操作表达式；Rust 的 `$e:expr` 会**拒绝**任何后续 token 无法安全接住的表达式，`MAX(i++, j++)` 的多重求值陷阱在结构上不存在（表达式被绑成一个 AST 节点，用几次由 transcriber 决定）。反过来，C 宏能只替换半条语句，而 Rust 的 `stmt` 片段连结尾分号都不包含。

> [!NOTE]
> 本文可编译断言全部在本机 `rustc 1.98.1` / 目标三元组 `aarch64-apple-darwin` 实测（`--edition 2024 --crate-type lib --emit=metadata`）；edition 差异按 2015/2018/2021/2024 各跑一遍。当前 stable 是 1.99.0，1.99.0 独有条目明确标注"未在本机实测"。

## Where Expansion Sits Relative to Name Resolution

"展开在名称解析之前"有两个可直接问编译器的后果。**其一，宏名按文本顺序解析，而宏生成的项按正常作用域解析：**

```rust
macro_rules! call_later { () => { later_fn() } }
pub fn a() -> u8 { call_later!() }   // 引用下面才定义的 later_fn：通过
pub fn later_fn() -> u8 { 5 }
pub const B: usize = late!();        // ERROR: cannot find macro `late` in this scope
macro_rules! late { () => { 1 } }
```

第二例的诊断带一句 `consider moving the definition of 'late' before this call` 和 `note: a macro with the same name exists, but it appears later`。`macro_rules!` 的名字走**文本作用域**（legacy textual scope），它生成的项走**模块作用域**（本就无序）——这条不对称是"把宏定义放文件末尾就报错"的根因。**其二，展开器既不做类型检查也不做名称解析**：过程宏的签名是 `TokenStream -> TokenStream`，看到的只是记号，这正是 `sqlx::query!` 必须自己连数据库、`#[derive(Clone)]` 会给泛型加错 bound 的原因。

| 维度 | C 预处理器 | Rust `macro_rules!` | Rust 过程宏 |
| :--- | :--- | :--- | :--- |
| 所处阶段 | 独立阶段，编译之前 | 名称解析之前，token tree → AST | 同左，但由外部已编译代码执行 |
| 操作单位 | pp-token，不懂语法 | token tree + **语法片段类型** | `TokenStream`，片段只是字符串 |
| 输出必须合法 | 否（可替换半条语句） | 是 | 是 |
| 卫生性 | 无 | 混合现场（mixed-site） | 有 `Span` 机制，显式选择 |
| 递归 | 不支持自引用 | 支持，手工递归 | 支持，且是图灵完备 Rust 代码 |
| 调试手段 | `cpp -E` / `gcc -fdirectives-only` | `cargo expand`（nightly） | 同左 + 打印 `TokenStream` |

## The Grammar of macro_rules

### Fragment Specifiers

匹配侧写 `$name:specifier`，转写侧只写 `$name`。全集（Reference 语法与编译器在 `missing_fragment_specifier` 报错时自己打印的那一行一致）：

| Specifier | 匹配什么 | 容易踩的点 |
| :--- | :--- | :--- |
| `expr` | 表达式 | edition 2024 起额外匹配 `const {..}` 与 `_`，见下节 |
| `expr_2021` | 表达式，但**排除** `const` 块与 `_` 表达式 | 只为一件事存在：向后兼容 |
| `ty` / `path` | 类型 / 类型路径 | 两者的 follow 集相同 |
| `pat` / `pat_param` | 模式 / 不含顶层 or-pattern 的模式 | `pat` 自 edition 2021 起含顶层 or-pattern |
| `block` / `stmt` | 块表达式 / 语句 | `block` 不含内部属性；`stmt` **不含结尾分号** |
| `ident` / `lifetime` | 标识符 / 生命周期记号 | `ident` 不接受 `_`、raw identifier、`$crate` |
| `literal` | 字面量 | 可选匹配前导 `-`，所以 `-1` 能过 |
| `item` / `meta` | 项 / 属性括号内的内容 | `meta` 常给 attribute 类宏传参 |
| `tt` | 单个 token tree | 递归宏的默认参数类型 |
| `vis` | 可见性限定符 | 可以匹配**空**，因此常放最前面 |

### expr Becomes expr_2021 in Edition 2024

`expr` 的语义跟着 edition 走，`expr_2021` 是钉死不变的逃生舱（自 **1.83.0** 起在**所有 edition** 可用）。Reference 的定义很窄：`expr_2021` = 表达式，但**排除**顶层 `UnderscoreExpression` 与 `ConstBlockExpression`；edition 2024 起 `expr` 允许它们（内联 `const {..}` 是 1.79.0 稳定的，`_` 表达式是 1.59.0 的）。为什么非要等一个 edition：新语法进 `expr` 会**改变已有宏的匹配结果**，这是可编译验证的差分：

```rust
macro_rules! which {
    ($e:expr)       => { 1u8 };
    (const $e:expr) => { 1u32 };
}
const _: u8 = which!(const { 1 + 1 });   // 2021: E0308（命中第二条） 2024: 通过（命中第一条）
macro_rules! dash { ($e:expr) => { 1u8 }; ($t:tt) => { 1u32 }; }
const _: u8 = dash!(_);                  // 同样的 edition 分叉
```

四个 edition 各跑一遍：`2015/2018/2021` 报两条 `E0308: mismatched types`（诊断标注"在这个宏调用中"），`2024` 全绿；把 `expr` 换成 `expr_2021` 后即使在 2024 也保持旧行为。迁移靠 lint `edition_2024_expr_fragment_specifier`（属 `rust-2024-compatibility` 组），`cargo fix --edition` 会批量把 `expr` 改写成 `expr_2021`——但**新宏多数应保留 `expr`**，只需检查有没有别的规则因此被抢走匹配。同族的历史改动是 `pat` / `pat_param`（or-pattern），且 ⚠️ 决定语义的是 **`macro_rules!` 定义所在 crate 的 edition**，不是调用点。另有一条已硬化：`($name)` 这种**漏写片段说明符**的规则自 1.89.0 起在所有 edition 都是硬错误 `error: missing fragment specifier`，`cargo fix --edition` 不会帮你——它本来就是死代码。

### Repetition Operators and Separators

`$( ... ) op` 的 `op` 三选一：`*` 任意多个、`+` 至少一个、`?` 零或一个。分隔符是任意"非分隔符、非计数符"的单 token，实践中 `,` 与 `;` 最常见。三条限制的措辞直接来自本机诊断：``the `?` macro repetition operator does not take a separator``（`($($i:ident),?)` 非法）；`($($i:ident),*) => { $i }` 在调用时报 ``variable `i` is still repeating at this depth``；`($($i:ident),*) => { $(a)* }` 报 ``attempted to repeat an expression containing no syntax variables matched as repeating at this depth``。

也就是说：转写侧的重复必须与匹配侧**数量、类型、嵌套顺序一致**（配 `$($i);*` 合法，配 `$($i)+` 与裸 `$i` 都不合法），且每层重复至少含一个 metavariable 才能确定重复次数——这条"必须含 metavariable"正是累加器要写成 `$($acc:tt)*` 而不是裸 `$(...)*` 的原因；同层多个 metavariable 还必须绑定相同数量。

### Follow Set and the No-Lookahead Rule

匹配器是**逐 token 决定、不回溯、不前瞻**的自动机，本质是 LL(1) 的限制。其一，片段类型规定了它能被什么 token 直接跟随——因为 `expr` 若允许跟 `{`，`m!(if c { 1 } { 2 })` 就有两种合法切分。本机实测的 follow 集：

| 片段 | 允许的直接跟随 |
| :--- | :--- |
| `expr` / `expr_2021` | `=>` `,` `;` |
| `pat` | `=>` `,` `=` `if` `if let` `in` |
| `ty` / `path` | `{` `[` `=>` `,` `>` `=` `:` `;` `|` `as` `where` |
| `vis` | `,`、一个 ident 或一个类型 |
| `tt` `ident` `lifetime` `block` `stmt` `item` `meta` `literal` | 实测接 `+` `;` `=` 都不报错，基本不受限 |

违反时的诊断毫不含糊：``error: `$e:expr` is followed by `$p:pat`, which is not allowed for `expr` fragments`` + ``= note: allowed there are: `=>`, `,` or `;``。其二，**能在 token 层面消歧也不算数**：`macro_rules! ambiguity { ($($i:ident)* $j:ident) => {}; }` 遇到 `ambiguity!(error);` 报 `error: local ambiguity when calling macro 'ambiguity': multiple parsing options: built-in NTs ident ('i') or ident ('j')`——哪怕往后看一个 token 就能确定切分，展开器也不看。工程结论：同一层不要放两个能匹配同类 token 的重复；把 `tt` 放最后，或用嵌套组 `[$(...)*]` 显式包列表。另一条常被误会的规则：**第一个匹配成功的规则被采用后不再回退**，即使它的转写随后报错——通用规则必须写在特化规则之后，而 `($($t:tt)*)` 这类万能捕获一旦放前面就永久吃掉后面的规则。

其三与上一条同源：把匹配到的片段转发给另一个 `macro_rules!` 时，下游看到的不是原始 token 而是不透明的 AST 节点。`macro_rules! fwd { ($l:expr) => { bar!($l); } }` 配上 `macro_rules! bar { (3) => {} }`，`fwd!(3)` 报 ``no rules expected `expr` metavariable``，note 直接给出规则：``captured metavariables except for `:tt`, `:ident` and `:lifetime` cannot be compared to other tokens``。这一条几乎解释了 `macro_rules!` 的整个递归风格：**凡可能还要继续拆解的东西，一开始就用 `tt` 收**，别贪心写 `:expr`。

## Mixed-Site Hygiene

Reference 的原话：声明宏是 **mixed-site hygiene**——**循环标签、块标签、局部变量在宏的定义现场解析，其余符号在调用现场解析**。四组实测：

```rust
macro_rules! decl { () => { let x = 1; }; }
fn outer() { decl!(); let _y = x; }        // E0425: cannot find value `x`
macro_rules! brk { () => { break 'outer }; }
fn loop_it() { 'outer: loop { brk!(); } }  // E0426: use of undeclared label `'outer`
macro_rules! brk2 { ($l:lifetime) => { break $l }; }
fn loop_ok() { 'outer: loop { brk2!('outer); } }  // 通过：标签作为片段传进来
macro_rules! def_fn { () => { fn helper() -> u8 { 1 } } }
def_fn!();
pub fn at_module() -> u8 { helper() }      // 通过：项符号按调用现场解析
```

所以「宏里的 `let x` 不污染调用点」是真的，但「宏里的东西外面都看不见」是**假的**：宏在模块作用域生成的 `fn`/`struct`/`const` 完全能在外面引用（`mk!(Foo)` 之后 `Foo` 可用同理——插值 ident 属于"其余符号"）。推理时把 hygiene 当成**只对局部变量和标签生效**，才不会写出看似安全实则依赖它的代码。另一点：`m!(define)` 与 `m!(refer)` 两次调用**不共享**同一个 `x`，每次展开的局部现场都是新的。

### No Token Pasting, and paste

声明宏**没有** C 的 `##`：`macro_rules! glue { ($n:ident) => { struct Foo$n; } }` 调 `glue!(Bar)` 报 `error: expected 'where', '{', '(' or ';' after struct name, found 'Bar'`。这就是 `paste` crate 的全部理由（本机离线实测通过）：

```rust
use paste::paste;
macro_rules! accessor {
    ($name:ident) => { paste! { pub fn [<get_ $name>]() -> u8 { 1 } } };
}
accessor!(count);
pub fn use_it() -> u8 { get_count() }   // 通过
```

> [!WARNING]
> `paste` 破坏的正是上面那套规则：拼出来的名字与普通声明的名字同现场。用它生成"本该被外部引用"的项没问题，但别指望它能绕开局部变量的 hygiene。

### The crate Metavariable

`#[macro_export]` 把宏导出到 crate 根，但展开发生在**使用方现场**，直接写裸名字会找不到：provider crate 里 `pub const CONST: u8 = 1;` 配 `#[macro_export] macro_rules! good { () => { $crate::CONST } }` 能被 `prov::good!()` 正常使用，而把 `$crate::` 去掉写成 `bad!` 就报 `E0425: cannot find value 'CONST' in this scope`（本机用两个 `rustc` 编译单元实测）。`$crate` 是"引用**定义宏的那个 crate**"的唯一手段；宏体内部用到本 crate 路径、或要防使用方遮蔽 `std` 时都得走它（或写成 `::core::assert!` 这种完全限定形式）。

## Recursion Idioms

`macro_rules!` 没有循环、没有累加变量、没有 `if`，只有"匹配 + 自己再调自己"。**tt muncher** 每次吃一个 token，把子问题放在展开产物的**左侧**：

```rust
macro_rules! count {
    () => { 0usize };
    ($t:tt $($rest:tt)*) => { count!($($rest)*) + 1 };
}
const N: usize = count!(a b c d e);   // 运行输出 5
```

参数用 `$t:tt` 而非 `$t:ident`，因为 `tt` 是唯一"什么都能装且可继续拆"的片段；缺点是产物形如 `count!(...) + 1 + 1 + ...`，递归深度与表达式长度同时增长。**push-down accumulation** 则把已算好的部分**塞回参数的累加器**，让递归保持尾部形态，最后一步一次生成结果：

```rust
macro_rules! pushdown {
    { [$($acc:tt)*] } => { [$($acc)*] };
    { [$($acc:tt)*] $head:tt $($tail:tt)* } => { pushdown!{ [$($acc)* $head] $($tail)* } };
}
macro_rules! from_list { ($($t:tt)*) => { pushdown!{ [] $($t)* } } }
const ARR: [i32; 3] = from_list!(1, 2, 3);
```

`from_list!` 这个入口是必需的：把"入口规则"和"递归规则"分开写，比在同一宏里既匹配 `[]` 开头又匹配裸列表省事得多，也避开了前一节的 local ambiguity。muncher 与 accumulation 是几乎所有复杂声明宏（包括 `vec!` 这类分支构造）的骨架。展开器另有递归上限，且报错指向**宏定义**而不是调用点（`error: recursion limit reached while expanding 'count!'`）：本机 400 个 token 的 `count!` 稳定触发，加 `#![recursion_limit = "1200"]` 后输出 400；别写成 `-C recursion-limit=10000`，那不是 codegen 选项（实测 `error: unknown codegen option: recursion-limit`）。上限也在提醒：递归宏的深度是真实编译期成本。

## The Built-in Macro Set

内置宏不全是"标准库里的普通宏"：`asm!`、`cfg_select!`、`compile_error!`、`include!` 家族由编译器特殊支持（要读写文件系统、或在 AST 里插东西）。下表全部在本机编译通过（`write!` 对 `String` 需 `use std::fmt::Write`）：

| 类别 | 宏 |
| :--- | :--- |
| 格式化与输出 | `println!` `print!` `eprintln!` `eprint!` `write!` `writeln!` `format!` `format_args!` `dbg!` |
| 断言 | `assert!` `assert_eq!` `assert_ne!` `debug_assert!`；`const _: () = assert!(..)` 可当 const 上下文静态检查 |
| 表达式构造 | `vec!`（`vec![x; n]` / `vec![a, b]`）、`matches!`（把 `match` 的一个分支压成 `bool`，如 `matches!(v, 1 \| 2)`） |
| 字面量与编译期取值 | `concat!` `stringify!` `env!` `option_env!` `include_str!` `include_bytes!` `include!` `file!` `line!` `column!` `module_path!` |
| 条件与诊断 | `cfg!` `cfg_select!` `compile_error!` `panic!` `todo!` `unreachable!` `unimplemented!` |
| 指针 | `addr_of!` `addr_of_mut!`（1.82.0 起推荐写法是 `&raw const` / `&raw mut`） |
| 内联汇编 | `core::arch::asm!` `global_asm!` `naked_asm!` |

实测行为：`concat!("a", 1, true, 'c')` 得 `"a1truec"`（非字符串参数也被 stringify）；`stringify!({ let x = 1; x })` 得 `"{ let x = 1; x }"`（保留原文、不求值）；`option_env!("NOPE_NOT_SET")` 得 `None`，而 `env!` 找不到变量时直接终止编译（`error: environment variable ... not defined at compile time`）——这就是两者的全部区别；`include_str!` 的路径相对**当前源文件**解析。

### Case Study: Compile-Time Format Checking in println

`println!` / `format!` 是内置宏：展开期就把格式串解析成片段描述符，再为每个实参生成带 trait bound 的取值。于是四类错误全在编译期，本机诊断分别是 `multiple unused formatting arguments`（实参多了）、`2 positional arguments in format string, but there is 1 argument`、`unknown format trait 'd'`、`invalid format string: expected '}' but string was terminated`。caret 指回**格式串本身**并附 `help: format specifiers use curly braces, consider adding 2 format specifiers`，而不是指到展开出来的临时变量——这是编译器对该宏**特例化**的结果，普通 `macro_rules!` 拿不到这种定位质量。同族的语言级整理还有 edition 2021 的 `panic!` 宏一致性改造。

### Case Study: Build-Time Database Access in sqlx

`sqlx::query!` 是过程宏：展开时真的连数据库、把 SQL 交给服务端解析、按推断出的列类型生成结构体字段——纯粹靠"展开在类型系统之前，因此可以自带一套外部校验"这条管线位置，换来"SQL 写错或列改名就编译失败"。代价同样直接：编译依赖外部可变状态、构建不再自包含（因此官方提供 `cargo sqlx prepare` 生成离线 `.sqlx` 缓存）；每个 `query!` 是一次网络往返，几十个就能明显拖慢 `cargo check`；展开产物里的错误定位远差于 `println!`。同一取舍适用于 `include!` 家族（读文件系统 → `rerun-if-changed` 那类构建依赖问题，见 [Cargo.md](/docs/CS/Rust/Cargo.md)）。判断标准一句话：**凡是"编译期读外部世界"的宏，都在用构建可复现性和编译时间换运行期安全。** 生态侧宏库全景（`serde` / `thiserror` / `tokio::main`）见 [Ecosystem.md](/docs/CS/Rust/Ecosystem.md)，`sqlx` 目前在 0.9 线上。

### cfg_select and the cfg_match Myth

`cfg_select!` 自 **1.95.0（2026-04-16）** 稳定，是"多分支版 `cfg!`"，例如 `cfg_select! { target_arch = "aarch64" => 10, target_arch = "x86_64" => 20, _ => 30 }`（分支体也可以是 `{ ... }` 包住若干项声明）。三条实测边界：旧名 **`cfg_match!` 在 stable 上不存在**（`error: cannot find macro 'cfg_match' in this scope`——它在 nightly 存在过并改名，2024–2025 年大量资料仍写 `cfg_match!`，照抄必错）；分支上不能加属性（``error: attributes are not allowed on `cfg_select` branches``）；无分支命中且缺 `_` 时是 `error: none of the predicates in this 'cfg_select' evaluated to true`，被前面同条件遮住的分支触发 `unreachable_cfg_select_predicates` 警告（本机 1.98.1 已默认开启）。`cfg_select!` 只解决"表达式/常量层面选一个值"；`cfg` 属性、feature 与构建系统那层的条件编译见 [Cargo.md](/docs/CS/Rust/Cargo.md)，两处不重复叙述。

### asm global_asm and naked_asm

三者都在 `core::arch::` 下，`naked_asm!` 只配 `#[unsafe(naked)]` 函数（裸 `#[naked]` 在 edition 2024 报 "unsafe attribute used without unsafe"）。两个实测到的坑：**`--emit=metadata` 不校验汇编串**——往 `global_asm!` 里塞一句彻底非法的汇编，`--emit=metadata` 干净通过，`--emit=obj` 才报 `error: unexpected token in argument list` + `note: instantiated into assembly here --> <inline asm>:1:9`，也就是说 `cargo check` **发现不了**内联汇编语法错误；以及 naked 函数里用 `asm!` 是 `E0787: the 'asm!' macro is not allowed in naked functions`，诊断直接建议改 `naked_asm!`。unsafe 语义与 ABI 部分见 [Unsafe_FFI.md](/docs/CS/Rust/Unsafe_FFI.md)。

## Procedural Macros

### Three Kinds

| 形态 | 属性 | 输入 | 输出 | 典型用途 |
| :--- | :--- | :--- | :--- | :--- |
| function-like | `#[proc_macro]` | 括号内 `TokenStream` | 任意语法片段 | DSL、`macro_rules!` 做不了的拼接 |
| derive | `#[proc_macro_derive]` | 目标**项**的 token | **额外**生成项 | `Clone`、`serde::Serialize` |
| attribute | `#[proc_macro_attribute]` | 属性参数 + 被标注项 | **替换**被标注项 | `#[tokio::main]`、`#[derive_builder]` |

derive 只能"在旁边加东西"，attribute 宏可以整段重写目标项——这条区别决定了 `#[derive(Clone)]` 永远改不了字段。

### Why Procedural Macros Must Live in Their Own Crate

`[lib] proc-macro = true` 不是打包偏好，而是因果必需。四条本机实测诊断摆出整条链：``the `#[proc_macro]` attribute is only usable with crates of the `proc-macro` crate type``、`E0432: unresolved import 'proc_macro'`（普通 crate 链接不到该 crate）、`can't use a procedural macro from the same crate that defines it`、`` `proc-macro` crate types currently cannot export any items other than functions tagged with `#[proc_macro]`, `#[proc_macro_derive]`, or `#[proc_macro_attribute]` ``。

链条是：**展开器要调用你的代码，而调用意味着加载一个已编译的宿主平台动态库。** 你自己的 crate 此刻正在被编译、还没有可用产物，于是循环。所以过程宏必须是"在使用者之前编好的独立 crate"，且只能导出宏入口——内部逻辑得拆到另一个普通 crate，这正是很多宏库同时有 `foo` 与 `foo-derive` 两个包的原因。这也正是与 C++ 的分水岭：C++ 的 `#include` 把声明与定义**文本地塞进同一个编译单元**，模板因此能在同一 TU 里惰性实例化、边解析边求值，顺手得到一门图灵完备的编译期语言（见 [Templates.md](/docs/CS/C++/Templates.md)），代价是头文件依赖、ODR、编译时间和几百行的模板报错。Rust 反过来：编译期可执行代码被关进一个预先编好的沙箱 crate，边界干净、增量可控，但宏永远看不到类型。

### The de Facto Toolchain

手写 `TokenStream` 字符串拼接是可证明的坏主意：`format!("...").parse().unwrap()` 会丢掉全部原始 span（新 token 一律落在 call site），错误定位退化成"指到宏属性那一行"，还容易 panic。事实标准：

| crate | 角色 |
| :--- | :--- |
| `proc-macro2` | 可脱离编译器测试的 `TokenStream` 替身 + `Span::call_site()` / `Span::mixed_site()` 显式卫生控制 |
| `syn` | 把 token 解析成 Rust 语法树（`DeriveInput`、`Fields`、`Type`……） |
| `quote` | `quote! { }` 反引用插值生成 token，`#( ... )*` 对应重复 |
| `darling` | 解析 attribute 参数（`#[builder(default)]` 这类选项） |
| `paste` | 标识符拼接 |

本机 `index.crates.io` 不可达（curl 超时），但本地 registry 缓存足够 `--offline` 构建，解析到 `syn 2.0.119` / `quote 1.0.47` / `proc-macro2 1.0.107` / `paste 1.0.15`（缓存里同时有 `syn 1.0.109` 与 `syn 3.0.6`：大版本 API 不兼容，动手前先确认依赖树锁了哪条线；`darling` 缓存有 0.20 至 0.24）。下面这个 derive 在本机真实编译，使用方 `Cfg::builder().host(s).port(1).build()` 也通过，是可以直接抄的最小骨架：

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
            #(fn #idents(mut self, v: #tys) -> Self { self.#idents = Some(v); self })*
            fn build(self) -> Result<#name, String> {
                Ok(#name { #(#idents: self.#idents.ok_or_else(|| stringify!(#idents).to_string())? ),* })
            }
        }
    };
    out.into()
}
```

`format_ident!` 就是"受控的 `##`"；`#(#idents: Option<#tys>),*` 把几个平行 Vec 同步展开成逗号列表。`syn` 只负责解析、`quote` 只负责生成、互不越界，是这套工具能用少数原语覆盖绝大多数宏的原因。

### What derive Can and Cannot Do

- **不能给被 derive 的类型加字段。** derive 的输出是"另发的项"，原类型定义不动一行；要改字段只能用 attribute 宏重写整个项，或用 function-like 宏生成字段列表。
- **不能实现 `Drop`。** 实测 `#[derive(Drop)]` → ``error: cannot find derive macro `Drop` in this scope`` + `= note: 'Drop' is in scope, but it is only a trait, without a derive macro`。析构必须手写，理由见 [Drop.md](/docs/CS/Rust/Drop.md)。
- **不能声明未登记的辅助属性。** 上例没写 `attributes(builder)`，于是使用方的 `#[builder(default)]` 报 `error: cannot find attribute 'builder' in this scope`。
- **会给泛型加机械的 bound**，这是最著名的陷阱：

```rust
#[derive(Clone)]
pub struct Handle<T> { inner: std::rc::Rc<T> }
pub struct NotClone;
pub fn needs_clone<H: Clone>(_h: H) {}
pub fn probe(h: Handle<NotClone>) { needs_clone(h); }   // E0277
```

`Rc<T>` 对**任何** `T` 都是 `Clone`，但 derive 生成的是 `impl<T: Clone> Clone for Handle<T>`。真实诊断替你把解法写出来了：``= help: consider manually implementing `Clone` to avoid undesired bounds``。解法是手写 `impl<T> Clone for Handle<T> { fn clone(&self) -> Self { Self { inner: self.inner.clone() } } }`（本机通过）。同一机制解释了 `#[derive(Default)]` 对 `PhantomData<T>` 加 `T: Default` 的问题：derive 只看类型参数是否**出现**，不看字段是否真的需要它。机制细节在 [Trait_System.md](/docs/CS/Rust/Trait_System.md) 与 [Generics.md](/docs/CS/Rust/Generics.md)。

### Failure Modes of Attribute Macros

**一、错误定位在展开产物上。** 一个把项复制两遍的 attribute 宏，本机报 `E0428: the name 'solo' is defined multiple times`，caret 只落在 `#[duplicate]` 那一行，并附 `= note: this error originates in the attribute macro 'duplicate' (in Nightly builds, run with -Z macro-backtrace for more info)`。诊断能告诉你是哪个宏造成的，但给不出展开后的行号；要看完整展开链得开 `-Z macro-backtrace`，那是 nightly 专属。

**二、宏内部 panic 只剩一条几乎无信息的错误。** 上面那个 `Builder` derive 用在 `enum` 上会走 `panic!` 分支，本机报 `error: proc-macro derive panicked` + `= help: message: Builder 只能 derive 到 struct`，caret 只落在 `#[derive(Builder)]` 的属性名上。panic 穿越展开器时丢了文件行号与上下文。`proc_macro_error`（以及后续 `unwind` 方向的工作）解决的就是这件事：**用 `abort!` 输出正常诊断而不是 panic**；更朴素的写法是把 `syn::Error` 转成 `to_compile_error()` 返回。写宏时应把"用户输入不合法"和"宏自己有 bug"分成两条路径。

**三、span 是卫生性的载体。** `Span::call_site()` 生成的 token 属于调用点（会被调用方局部变量遮蔽、错误落在调用点），`Span::mixed_site()` 则按声明宏规则处理局部符号。手搓 `String` + `parse()` 把所有 token 变成 call-site span，副作用三合一：错误定位差、IDE 跳转失效、`rustfmt` 无从格式化。

**四、编译期与交互成本。** 过程宏是宿主 dylib：改宏 crate 会让所有使用者重编，展开时反复做 `TokenStream` 转换与解析是真实开销——`cargo check` 变慢、IDE 卡顿的常见根因就在这里。测量与缓解见 [Tooling.md](/docs/CS/Rust/Tooling.md)。

## Expansion and Tooling

看展开结果只有编译器自己的产物可信：`cargo +nightly rustc -- -Zunpretty=expanded`（展开到 stdout）或包装工具 `cargo expand`。本机如实说明：**stable 上跑不出来**——`rustc -Zunpretty=expanded` 报 `error: the option Z is only accepted on the nightly compiler`，旧式 `--pretty=expanded` 直接 `error: Unrecognized option: 'pretty'`；本机只有 stable 1.98.1 与一个 pin 的 1.95.0，没有 nightly，`cargo --list` 里也没有 `expand`。因此本文所有展开结论都来自诊断文本与 Reference 描述，而非展开产物。

与 rust-analyzer 的边界值得单列：它**自己重新实现了一遍展开与解析**，不共享 rustc 的展开器。三条实践后果：`macro_rules!` 的**文本作用域顺序**在 IDE 里同样成立，把宏定义移到文件末尾会让 analyzer 立刻在使用点标红；过程宏要**加载编译好的宏 crate dylib**，所以第一次打开工程（或宏 crate 刚改过）时，derive 生成的 `impl` 与 attribute 宏重写的函数体会短暂"不存在"，表现为幻影 `no method`，等宏 crate 构建完并刷新展开缓存才消失；展开缓存不会自动感知外部状态变化，`sqlx` 那类 build-time 宏在 IDE 里尤其容易给出旧结果。本库不把配置键名写成事实（本机 `rust-analyzer` 二进制里没能验证到具体键，写出来就是潜在以讹传讹），只记行为差异，具体开关以本机 `rust-analyzer` 文档为准。C 侧的对照物是 `cpp -E`，见 [Preprocessor.md](/docs/CS/C/Preprocessor.md)。

## File Inclusion Without a Preprocessor

Rust 没有 `#include`，三件不同的东西分别接管：`include!("frag.rs")` 把另一个文件的**语法片段**并入当前 AST（实测可在模块作用域 include 一份 `pub const` 片段再 `use` 它），它是 AST 级并入而非文本粘贴，因此也**不会**在被包含文件里"再跑一遍预处理器"；`include_str!` / `include_bytes!` 完全不解析，产出 `&'static str` / `&'static [u8; N]`，把内容当数据；`#[path = "sib.rs"] mod aliased;` 只改模块对应的文件位置、不改任何语义（实测通过）。

把 attribute 宏用到 `mod` 声明上的 **outlined modules**（`#[my_macro] mod foo;`，让宏的展开结果里再出现嵌套模块）自 **1.99.0** 才稳定。本机 1.98.1 上 `mod foo;` 仍在展开前就去找文件，报 `error[E0583]: file not found for module 'foo'`——这个"先找文件再展开"的顺序本身就是 1.99 之前做不到这件事的原因。模块目录与 `OUT_DIR` 那类生成代码的构建侧写法见 [Cargo.md](/docs/CS/Rust/Cargo.md)。

## Why No Turing-Complete Compile-Time Programming

C++ 的模板在类型层面是图灵完备的（实例化即求值），于是大量本该运行期做的事被搬进模板。Rust 没有对应设计，是两个决定合起来的结果：（1）**宏只是 AST 变换**——`TokenStream -> TokenStream` 确实是图灵完备的 Rust 代码，但它的输出必须是语法片段而不是值，且拿不到类型，因此无法参与类型计算，"编译期计算"被拆到两处而不是像 C++ 那样用一门语言同时干两件事；（2）**值层交给 const eval，类型层交给 trait 求解**——`const fn` 与内联 `const { }`（1.79.0 稳定，1.87.0 起 `vec!` / `assert_eq!` 的参数里可直接写 `const {…}`，也正是 edition 2024 的 `expr` 才匹配它）承担值层面求值，trait bound 求解承担类型层面推导，边界与代价见 [Generics.md](/docs/CS/Rust/Generics.md)、[Trait_System.md](/docs/CS/Rust/Trait_System.md) 与 [compile.md](/docs/CS/Rust/compile.md)。

刻意不给第三门语言的理由很实际：trait 求解本身已有完备性与性能边界（正是 orphan rules、next-gen solver 一路在收拾的战场），再叠一门图灵完备的类型级语言，诊断长度与编译时间都会失控。C++20 用 concepts 收敛模板、用 `consteval` 给编译期函数一个正式入口，走的其实是"退回 Rust 早已划好的那条线"。edition 与语言版本的分层策略见 [Edition_MSRV.md](/docs/CS/Rust/Edition_MSRV.md)。

## Cross-Language Comparison

| 方案 | 介入阶段 | 单位 | 懂语法 | 卫生性 | 能读类型 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| C 预处理器 | 编译前独立阶段 | pp-token / 文本 | 否 | 无 | 否 | 可替换半条语句；无自引用递归 |
| C++ 模板 | 编译期实例化 | 类型 + NTTP | 是 | 无 | **是** | 类型层图灵完备，价值与代价同源 |
| Rust `macro_rules!` | 名称解析前展开 | AST 片段 / token tree | 是（片段类型） | 混合现场 | 否 | 不能拼标识符；递归手写 |
| Rust 过程宏 | 同左，由已编译代码执行 | `TokenStream` | 宏自己决定 | 由 `Span` 控制 | 否 | 必须独立 crate |
| Go `go:generate` | 编译**之前**，外部命令 | 整个文件（工具自定义） | 由工具决定 | 无此概念 | 由工具决定 | 语言层根本没有宏，见 [Go.md](/docs/CS/Go/Go.md) |
| Java 注解处理器 | javac 编译中，生成**新源文件** | 元素模型 `Element` | 是 | 部分（不能改宿主类） | **是** | 只能新增；Lombok 靠侵入 javac 内部，属非标准 |
| Lisp / Scheme 宏 | 读之后、求值之前 | 同像 s-expression | 是（宏系统即语言子集） | 有专章（hygiene 概念的出处） | 否 | Rust 的卫生性讨论直接继承自这里 |

Java 那行值得多说一句：它是几家里最接近"过程宏能读到类型"的——注解处理器拿到编译器给出的 `Element` 模型，看得见类、方法、签名；代价是**只能新增文件、不能修改被标注的类**。所以 JavaPoet 风格的生态全是"生成旁支"，而 Rust 的 attribute 宏可以整段替换目标项。两条路线的取舍差异在这里最清楚。语言层面的横向速览另见 [Languages.md](/docs/CS/Languages.md)。

## Links

- [compile.md](/docs/CS/Rust/compile.md)
- [Cargo.md](/docs/CS/Rust/Cargo.md)
- [Trait_System.md](/docs/CS/Rust/Trait_System.md)
- [Preprocessor.md](/docs/CS/C/Preprocessor.md)
- [Ecosystem.md](/docs/CS/Rust/Ecosystem.md)
- [Rust.md](/docs/CS/Rust/Rust.md)

## References

- [Rust Reference: Macros By Example](https://doc.rust-lang.org/reference/macros-by-example.html)
- [Rust Reference: Procedural Macros](https://doc.rust-lang.org/reference/procedural-macros.html)
- [Rust Reference: Tokens](https://doc.rust-lang.org/reference/tokens.html)
- [Rust Edition Guide: Macro Fragment Specifiers](https://doc.rust-lang.org/edition-guide/rust-2024/macro-fragment-specifiers.html)
- [Rust Edition Guide: Missing Macro Fragment Specifiers](https://doc.rust-lang.org/edition-guide/rust-2024/missing-macro-fragment-specifiers.html)
- [The Rust Programming Language: Macros](https://doc.rust-lang.org/book/ch19-06-macros.html)
- [std documentation: macro cfg_select](https://doc.rust-lang.org/std/macro.cfg_select.html)
- [Unstable Book: -Z macro-backtrace](https://doc.rust-lang.org/unstable-book/compiler-flags/macro-backtrace.html)
- [syn crate documentation](https://docs.rs/syn/latest/syn/)
