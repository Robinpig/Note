## Introduction

一门语言要在"不毁掉已有生态"的前提下继续演进，只有两条路：要么永不破坏（语言被冻死），要么给破坏性变化找一个足够细的开关粒度。Rust 的答案是后者，而且把开关拆成了**三个互相正交的轴**：编译器版本（1.x，6 周一个节拍）、crate 级的 edition（语言层的 opt-in 重定义）、crate 级的 `rust-version`（MSRV，库层的下限声明）。再加上稳定性承诺（Stability Document）与 Compatibility Notes 这条"受控破坏"通道，构成一套完整的演进机制。

本篇沿这条主线组织：先钉住三轴各自管什么（这是全篇的坐标系），再讲版本节拍、edition 本体与逐 edition 差异，然后用三态分类法拆掉"edition = feature gate = 稳定性"这个最常见的混淆，接着讲稳定性承诺的真实边界（破坏从哪里进来）、MSRV 实践与迁移机制，最后和 Python / Go / Java / C++ 对照——**"演进单位"这一列最能拉开差别**。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**。本篇所有编译行为差异都在本机 `rustc 1.98.1 (48a229cea 2026-09-01)`（host `aarch64-apple-darwin`）上跑了双 edition 对照实测，诊断原文照抄；跨版本对照用本机 pin 的 `+1.95.0` 工具链实测；1.99.0 独有事项按 release notes 记为"自 1.99.0 起"，不谎称实测。

## Three Orthogonal Axes

| 轴 | 在哪里声明 | 作用粒度 | 演进规则 |
| :-- | :-- | :-- | :-- |
| 编译器版本 1.x | `rustc --version`、rustup 通道 | 整个工具链 | 恰好 6 周一个 `.0`；稳定性承诺保证"曾经能编译的代码永远能编译" |
| edition | `Cargo.toml` 的 `package.edition` 或 `--edition` 参数 | 单个 crate | 只有 2015 / 2018 / 2021 / 2024；不显式迁移就不采纳任何破坏性变化 |
| `rust-version`（MSRV） | `Cargo.toml` 的 `package.rust-version` | 单个 crate | 自报"我最低的编译器版本"，供 Cargo 的 MSRV-aware resolver 与 CI 使用 |

三轴必须同时回答才能判断"这段代码能不能编"：edition 2024 要求编译器 ≥ 1.85.0，但 1.85.0 编译器照样能编 edition 2015 的 crate；反过来，一个 `rust-version = "1.75"` 的 crate 即使用最新编译器编，也**不能**使用 1.75 之后才 stable 的东西。两个 crate 级开关互相独立，也和编译器版本独立。

三轴在报错处的分工也不同：编译器版本不足时是 **Cargo** 拦你（`rust-version` 不满足就不开始编译，报错点名需要的版本与当前激活版本）；edition 不满足时是 **rustc** 逐条诊断拦你（见后文 `let chains are only allowed in Rust 2024 or later`）；而 MSRV 对**依赖的选择**起作用——`resolver = "3"` 下 Cargo 会挑 `rust-version` 与本机兼容的依赖版本组合，这是"三轴正交但互相引用"的唯一一处。

## Release Cadence and What a Version Number Carries

Rust 每 6 周（恰好 42 天）在周四发一个 `.0`。1.85.0 → 1.99.0 整段的实测节拍（以下版本与日期逐一取自官方 release notes 史页，且相邻 `.0` 的间隔都恰好 42 天，无一次例外）：

| 版本 | 日期 | | 版本 | 日期 | | 版本 | 日期 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 1.85.0 | 2025-02-20 | | 1.90.0 | 2025-09-18 | | 1.95.0 | 2026-04-16 |
| 1.86.0 | 2025-04-03 | | 1.91.0 | 2025-10-30 | | 1.96.0 | 2026-05-28 |
| 1.87.0 | 2025-05-15 | | 1.92.0 | 2025-12-11 | | 1.97.0 | 2026-07-09 |
| 1.88.0 | 2025-06-26 | | 1.93.0 | 2026-01-22 | | 1.98.0 | 2026-08-20 |
| 1.89.0 | 2025-08-07 | | 1.94.0 | 2026-03-05 | | **1.99.0** | **2026-10-01** |

两条读表纪律：

- **`.1` 补丁版从不承载特性**。这一区间的 1.93.1、1.94.1、1.96.1、1.97.1、1.98.1 全部是安全 / bug fix 发布，release notes 里连 `§ Language` 一节都没有。任何"某特性来自 1.9x.1"的说法都可以直接证伪。
- 版本号过 1.99 后顺延 1.100.0、1.101.0，没有字母方案；Cargo 版本恒为 rustc minor + 1（当前 nightly 的 cargo 是 0.102.0-nightly），这是交叉核对编号的一个捷径。

一个特性"属于哪个版本"指的就是 stable 化那一次的 `.0`。但**编译器版本只是三轴之一**——下面两节说明为什么光有版本归属还回答不了"能不能用"。

## What an Edition Is and What It Is Not

edition 是**crate 级的、opt-in 的语言层重定义**。官方定义："editions are opt-in, existing crates won't use the changes unless they explicitly migrate into the new edition." 要点：

- **不改变已有 crate**。发布 edition 2024 不会让任何存量 crate 的行为发生一丝变化；它是"新 crate 的默认语境"，而不是"升级补丁"。
- **edition 之间可以互相依赖**。依赖图里混用任意 edition 完全合法，同一个 workspace 的 member 各用各的 edition 也完全合法。edition 不是进程级 ABI，也不是语言"代际"，只是每个 crate 编译时的一套默认值。
- **迁移是机械动作**：`cargo fix --edition` 能把大部分差异（如 `dyn` 补全、`...` 模式改写、`#[unsafe(no_mangle)]` 包裹）自动改完，但语义敏感的部分（如 RPIT 生命周期捕获反转）仍需人工复核。edition bump 对库来说按惯例算 minor 版本。
- 升 edition 有编译器下限：edition 2018 于 1.31.0（2018-12-06）stable，edition 2021 于 1.56.0（2021-10-21）stable，edition 2024 于 1.85.0（2025-02-20）stable。

edition 与 `rust-version` 都只是 `Cargo.toml` 里的 crate 级声明，同一个 workspace 混用合法：

```toml
[package]                 # 保守的库，钉在旧语境
edition = "2015"
rust-version = "1.74"

[package]                 # 同一 workspace 里的新二进制，追最新
edition = "2024"
rust-version = "1.85.0"
```

`edition` 的隐式默认值至今仍是 2015（编译器源码里 `DEFAULT_EDITION = Edition2015`），新建项目才会被 `cargo new` 写入最新 stable edition；manifest 字段全貌见 [Cargo](/docs/CS/Rust/Cargo.md)。`cargo fix --edition` 的典型产出正是上表那几类改写：补 `dyn`、`0...5` 改 `0..=5`、`#[no_mangle]` 套 `unsafe(...)`——机械部分自动，语义部分（尤其 RPIT 捕获）留给人复核。

### No Edition 2027

三个独立证据钉死这一点。编译器源码（`rustc_span::edition`）：

```text
pub const EDITION_NAME_LIST: &str = "<2015|2018|2021|2024|future>";
LATEST_STABLE_EDITION = Edition::Edition2024
```

其中 `future` 是**永久 unstable 的占位 edition**——源码注释明说它允许"在分配到具体 edition 之前实现 edition 相关变化"，任何挂在它上面的特性本身仍必须在 feature gate 之后。本机实测（1.98.1）：

```text
error: argument for `--edition` must be one of: <2015|2018|2021|2024|future>. (instead was `2027`)
```

第三，Edition Guide 只有 2015/2018/2021/2024 四章，全部 release notes 史页中检索 "edition 2027" 零命中。另外**不要把"每三年一个 edition"当规则**——2015→2018→2021→2024 只是已发生的事实间距，机制本身是 per-crate opt-in，没有任何东西承诺下一个 edition 的时间。

## Edition 2018 and Its Boundaries

edition 2018 的真变化集中在名字与路径解析，判据以 Edition Guide 2018 章为准：

| 变化 | 内容 | 备注 |
| :-- | :-- | :-- |
| 模块与路径 | `crate::` / `::` 前缀、uniform paths、`mod x;` 直接对应 `x.rs` | 影响最深的一项，`cargo fix --edition` 的主战场 |
| 新关键字 | `async`、`await`、`try` 被保留为（未来的）关键字 | 当时异步语法还没落地，先圈地 |
| 匿名 trait object 进入废弃期 | `&Trait` 建议写 `&dyn Trait` | `dyn` **语法本身** stable 于 1.27.0（2018-06-21）；2018 只 warn，强制要到 2021 |

edition 2018 之所以全压在名字解析上，是因为 1.0 到 2018 之间生态增长暴露的问题几乎都出自这里：`extern crate` 样板、路径相对/绝对语义不一致（同一写法在 crate 根和子模块含义不同）、宏作用域靠目录树隐式决定。把命名与解析一次修完，后续 edition 才有余力去做语义层的事。而 edition 2018 是"一次性大清理"：此后没有任何 edition 再动路径系统。

## Edition 2021

edition 2021 没有单一主题，是一组"当年已经是 warn、现在转正"的变化加 prelude 扩充。逐条给出判据与本机双 edition 实测（同一份源码，分别以 `--edition 2021` / 旧 edition 用 `rustc --emit=metadata --crate-type lib` 编译）：

| 变化 | 实测对照 |
| :-- | :-- |
| prelude 加入 `TryFrom` / `TryInto` / `FromIterator` | `x: u32` 上调 `x.try_into()`：edition 2018 报 `error[E0599]: no method named try_into found for type u32 in the current scope`；2021 编译通过。"必须 `use std::convert::TryInto`"从此只适用于 ≤ 2018 |
| 数组 `into_iter` 变为按值迭代 | `v.into_iter().collect::<Vec<u8>>()`（`v: [u8; 3]`）：2018 报 `error[E0277]: a value of type Vec<u8> cannot be built from an iterator over elements of type &u8`（autoref 到切片）；2021 编译通过 |
| `bare_trait_objects` 从 warn 升 hard error | `fn f(_x: &Marker)`：2015 只 warn（诊断里明写 "this is accepted in the current edition (Rust 2015) but is a hard error in Rust 2021!"）；2021 报 `error[E0782]: expected a type, found a trait` |
| `...` inclusive 模式从 warn 升 hard error | `match x { 0...5 => ... }`：2015 warn；2021 报 `error[E0783]: ... range patterns are deprecated` |
| disjoint closure capture | 闭包按字段捕获而非按整个环境捕获，只影响借用冲突面，无可观测的诊断差异 |
| `edition = "2021"` 隐含 `resolver = "2"` | resolver v2 本身 1.51.0 起可手动选；2021 起自动生效（feature 解析按依赖边而非全局并集）——操作细节见 [Cargo](/docs/CS/Rust/Cargo.md) |
| C-string 字面量归在 2021 章 | `c"hi"`：2018 直接是记号级错误，编译器还会提示 `c-string literals require Rust 2021 or later`；2021 编译通过。⚠️ 它所依赖的 `CStr` API 其实 1.77.0 就 stable 了——Edition Guide 故意按**词法生效点**归档，这正是"API 版本 ≠ edition 生效点"的教科书案例 |

## Edition 2024

edition 2024（1.85.0，2025-02-20 stable）的主题是**把 unsafe 的边界在语言层收紧**，外加借用与临时量生命周期的一批语义修正。逐条列真变化，每条给"是否本机实测"：

| 变化 | 判据与实测 |
| :-- | :-- |
| RPIT 生命周期捕获反转（RFC 3498） | 2024 起，未写 `use<..>` 的 `impl Trait` 返回值**隐式捕获所有在作用域内的生命周期参数**；≤ 2021 只捕获类型参数提及的生命周期。⚠️ 常见以讹传讹是"2024 才开始捕获所有泛型参数"——**类型参数在所有 edition 里一直被捕获**，反转的只是生命周期参数。逃生舱 `+ use<'a, T>` 自 1.82.0 起**在全部 edition** 可用（旧 `Captures<'a>` 技巧可整体替换）。捕获机制本体见 [Lifetime](/docs/CS/Rust/Lifetime.md)，本篇只管归属与迁移 |
| `let` 链（`if let ... && ...`） | 1.88.0（2025-06-26）stable 但**仅 edition 2024**。实测：`if let Some(y) = x && y > 0` 在 2021 报 `error: let chains are only allowed in Rust 2024 or later`，2024 通过；且 2021 下链内模式允许 irrefutable（1.95.0 起不再 lint） |
| `gen` 保留为关键字（RFC 3513） | 实测：`let gen = 1;` 在 2024 报 `error: expected identifier, found reserved keyword gen`，2021 通过。注意这只**保留**了关键字 |
| unsafe attributes | `no_mangle` / `export_name` / `link_section` 三个属性在 2024 必须写 `#[unsafe(...)]`。实测：裸 `#[no_mangle]` 在 2024 报 `error: unsafe attribute used without unsafe`，在 2021 通过；`#[unsafe(no_mangle)]` 在 2024 通过。属性机制本身 1.82.0 起在**所有 edition** 可用。⚠️ `#[global_allocator]` **不是** unsafe attribute |
| `unsafe extern` 块强制 | 实测：裸 `extern "C" { pub fn q(); }` 在 2024 报 `error: extern blocks must be unsafe`，2021 通过。`unsafe extern` 语法 1.82.0 起存在。完整语义见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md) |
| `unsafe_op_in_unsafe_fn` 变 warn | 过去 unsafe fn 体内自动是 unsafe 上下文且无人报警；2024 起不写显式 `unsafe { }` 块会 warn |
| 禁止对 `static mut` 取引用 | `static_mut_refs` lint 1.77.0 引入，2024 升为 error；正确姿势是 `&raw`（1.82.0） |
| 临时量生命周期三处修正 | `if let` 条件的临时量、尾表达式临时量的析构时点变化；never type fallback 改变。都是"旧代码行为悄悄不同"类，仅当显式迁移进 2024 才会发生 |
| 宏 fragment specifier `expr` → `expr_2021` | 2024 里 `expr` 变成"2021 前语义冻结版"，新代码要用 `expr_2021`（该 specifier 1.83.0 起全 edition 可用） |
| prelude 加入 `Future` / `IntoFuture` | 无需 `use std::future::Future` 即可写 async 相关 bound |
| `std::env::set_var` / `remove_var` 变 unsafe fn | 实测：2021 下 `std::env::set_var("A", "B");` 编译通过；2024 下报 `error[E0133]: call to unsafe function set_var is unsafe and requires unsafe block`。迁移铺垫从 1.80.0 开始（失去 `Fn` trait 实现、不能转安全函数指针） |
| 隐含 `resolver = "3"` | 见下节 MSRV 实践。1.99.0 起还允许 edition ≥ 2024 的 workspace member 覆写继承依赖的 `default-features` |

## Three Shapes of Edition-Boundary Diagnostics

把上面所有实测诊断按"编译器在哪个阶段拒绝"归类，会得到三种形态——认识形态本身就是一半的排错能力：

1. **记号级（lexer/parser）**：旧 edition 里根本不存在这个 token。`gen` 报 `expected identifier, found reserved keyword`；`c"hi"` 在 2018 报 `expected one of ... found "hi"` 并附带提示 `c-string literals require Rust 2021 or later`。这类错误**没有错误码**，也几乎无法靠加 import 解决——只能升 edition 或改写写法。
2. **lint 抬升预告型**：旧 edition 接受但 warn，且诊断原文里直接写明后果——`trait objects without an explicit dyn are deprecated` 后面跟着 "this is accepted in the current edition (Rust 2015) but is a hard error in Rust 2021!"。这类"未来不兼容"信息可以 `cargo report future-incompatibilities` 汇总查看，改对了在旧 edition 也零成本。
3. **显式 edition gate**：特性已 stable，但作用域限定新 edition。`let` 链的 `error: let chains are only allowed in Rust 2024 or later`、`error: extern blocks must be unsafe`、`error: unsafe attribute used without unsafe` 都是这一类；E0133（`set_var` 变 unsafe fn）则介于 2、3 之间——它本质是 std API 签名按 edition 切换。

值得强调的推论：**第 1 类的存在证明 edition 是词法/语法层开关；第 3 类的存在证明 edition ≠ feature gate**——`let` 链在 1.88 之后的编译器上以 `--edition 2021` 照样被拒（本机 1.95.0 与 1.98.1 双版本实测同一条错误），它不是 nightly 独占，而是 edition 独占。

## A Feature Needs Three Addresses

edition、feature gate、稳定性是**三套互不推导的坐标**。任何语法或 API 的可用性要填三个空：stable 于 vN / nightly only（附 gate 名）/ 从未存在；是否分 edition；是否仍是原语义。本篇用到的例子恰好构成全部象限：

| 对象 | stable 版本 | edition 限制 | 三态辨析 |
| :-- | :-- | :-- | :-- |
| `let` 链 | 1.88.0 | **仅 2024** | "1.88 起随便用"❌，2021 报上面那条实测错误 |
| `if let` 守卫（match arm） | 1.95.0 | **不分 edition** | 实测同一份 `Some(inner) if let Some(v) = inner => ...` 在 `+1.95.0 --edition 2021` 编译通过——与 `let` 链同屏对照，2024 时代的文章不知道这条 |
| `+ use<..>` 精确捕获 | 1.82.0 | 不分 edition | 它是跨 edition 的**逃生舱**，不是 2024 专属；2024 只是让它从"可选"变成"必要" |
| `gen` | — | 2024 保留关键字 | 关键字保留 ≠ 特性存在：`gen` 块**至今 nightly only**（gate `gen_blocks`，issue #117078） |
| `c"..."` 字面量 | API 1.77.0 | 词法 2021+ | 上面 2021 表已述 |
| `#[bench]` | 曾有 → 无 | — | 1.88.0 彻底去稳定化，stable 上是**硬错误**：stable 化可以撤销 |
| never type `!` / never patterns | 从未 stable | 不分 edition | nightly only，gate 名 `never_type` / `never_patterns`（stable 触发 E0658）；但对无 inhabited 值的类型写空 `match x {}` 一直是 stable——同一语法面里 stable 与 unstable 并存 |

两个方向的误读都要防：拿"已 stable"推"所有 edition 可用"（`let` 链），或拿"某 edition 强制"推"该机制只存在于该 edition"（unsafe attributes 机制 1.82 就全 edition 可用，2024 只是**强制点**）。

## The Stability Promise and Its Edges

稳定性承诺的内容：stable 工具链**永不拒绝编译曾经能编译的代码**；`std` / `core` 公开 API 只废弃不删除；语义静默漂移被制度性禁止。但它的边界同样有制度：**每个 release notes 的 `Compatibility Notes` 一节就是官方预留的"受控破坏"入口**——soundness 修复、被误 stable 的东西去稳定化、文档从未承诺过的行为收紧，都从这里进来。判断"某特性今天还生不生效"，要读消费方与 Compatibility Notes，**存在 ≠ 还生效**。下表是 1.88–1.99 区间的真实破坏样本（全部取自 release notes）：

| 版本 | Compatibility / 破坏内容 | 为什么值得记 |
| :-- | :-- | :-- |
| 1.88.0 / 1.89.0 | `#[bench]` 从 deny-by-default future-incompat（1.77 起）到**硬错误**（1.88）；`dangerous_implicit_autorefs` lint warn（1.88）→ deny（1.89） | 两步走：先硬错误，或 lint 两级抬升，就是 future-incompat 的标准生命周期 |
| 1.95.0 | JSON target spec 被**去稳定化**，需 `-Z unstable-options`（为 build-std 让路） | 连"曾经 stable 的命令行输入格式"都能收回 |
| 1.97.0 | **v0 symbol mangling 成为默认**（旧版 debugger / profiler 可能失配）；无布局保证的枚举**编码变化** | 直接改变 backtrace 与性能剖析的文本，所有依赖符号名或旧布局假设的工具链全部受累 |
| 1.98.0 | `repr(transparent)` 对 "trivial field" 收紧（`repr(C)` 类型、私有字段、`#[non_exhaustive]` 不再算 trivial）；derive `Ord` 时 `derive(PartialOrd)` 走快速路径（暴露 `PartialOrd` / `Ord` 不一致的旧代码）；structural-match 相等性漏洞收紧 | 三条全是"你的代码合法但依赖了未承诺行为"类 |
| 1.99.0 | `no_mangle_generic_items` 变**硬错误**；`std::i32::MAX` 一类旧式整型模块**完全废弃**（改 `i32::MAX`）；`Box::leak` 文档指引**反转**（推荐 `Box::into_raw` / `Box::into_non_null`，leak 后释放视为反模式）；`CI` 环境变量存在时默认**关闭增量编译**；`Pin::new_unchecked` 安全不变式**变化** | "存在 ≠ 生效"的活标本：`std::i32` 模块还在，但引用它已进废弃终态；`Box::leak` 函数签名未动，推荐用法却掉头 |

承诺的豁免情形同样是成文的，大致三类：**soundness 修复**（利用编译器漏洞的代码允许被拒——1.95.0 就把 stable 上被意外放行的 `mut ref` 模式重新 gate 回 unstable）；**从未真正 stable 的东西**（`#[bench]` 从 deny-by-default 到 1.88 宣告硬错误，前后铺垫了 11 个版本）；**文档从未承诺的行为**（1.97 的枚举布局、1.98 的 `repr(transparent)` 细节都属于"没保证过，所以不算破坏"）。反过来，`std` 公开 API 的废弃项**永不删除**——上面表里 `std::i32` 的案例说明"完全废弃"改变的是推荐与告警强度，不是可用性。读 Compatibility Notes 的正确姿势：它不是承诺失效的漏洞，而是**唯一合法的破坏通道**，每 6 周固定审阅一次，beta 通道提前彩排。

还有一条单向性推论要记住：这份承诺约束的是**编译器**，不豁免你对未记录行为的依赖。"某个写法一直如此"在稳定性体系里不构成任何权利——1.98.0 的 `derive(PartialOrd)` 快速路径改变时，受害的全是依赖"从未写进文档的 derive 展开顺序"的代码。行为对你 load-bearing，就去引用文档，而不是引用观察。

## The Migration Pipeline

破坏不是突然落下的，Rust 有一条制度化的四拍流水线：

1. **`#[deprecated]`**（带 `since` / `note`）：API 层的第一拍，编译产生 warn，项永不移除。
2. **future-incompat lint**：对"今天合法、将来不合法"的写法先 warn（如 `static_mut_refs`、`deny(by future-incompat)` 的 `#[bench]`），`cargo build` 结束时提示运行 `cargo report future-incompatibilities` 查看完整清单。
3. **lint 抬升**：warn → deny（如 `dangerous_implicit_autorefs` 的 1.88 → 1.89 两步）。
4. **硬错误**（如 1.88 的 `#[bench]`）。

跨 edition 的机械迁移走 `cargo fix --edition`；它和 future-incompat 报告共同构成"生态怎么被推着走"的答案——**编译器替每个 crate 记账，而不是替所有人同时改代码**。两个入口的用法：

```bash
cargo fix --edition          # 在旧 edition 上预先采纳新 edition 的机械改写
cargo report future-incompatibilities --id 1   # 查看 build 结尾提示的那份报告
```

这条流水线的节奏在本篇例子里可以直接对表：`static_mut_refs` 1.77.0（2024-03-21）引入 warn，到 edition 2024（1.85.0）把同一件事变成 error，警告窗口拉了约一年；`dangerous_implicit_autorefs` 则是 warn（1.88.0）→ deny（1.89.0）的两版本快车道。**窗口长度本身就是沟通的一部分**：越 load-bearing 的行为铺垫越久，越接近"从未承诺"的东西收得越快。

## MSRV in Practice

MSRV（minimum supported Rust version）是第三个轴，也是**唯一由 crate 作者自己声明**的轴：

| 机制 | 版本归属 | 内容 |
| :-- | :-- | :-- |
| `package.rust-version` | 1.56.0（2021-10-21，与 edition 2021 同一次发布） | manifest 字段；用更高编译器编它会直接报错 |
| MSRV-aware resolver 配置 + `resolver = "3"` | 1.84.0（2025-01-09） | 解析依赖时优先挑 `rust-version` 兼容的**最旧可用**版本组合，而不是无脑最新；edition 2024 隐含 `resolver = "3"` |
| `cargo add` 的 MSRV 感知 | 1.79.0（2024-06-13） | 往 manifest 加依赖时按当前 MSRV 挑版本号 |

⚠️ **`cargo msrv` 不是内建子命令**。本机 `cargo --list` 实测：`add` / `remove` / `fix` / `report` / `config` / `info` 都在列，`msrv` 不在（`grep -c msrv` 为 0）。Cargo 的内建 MSRV 机器就是上面三行；工具圈里那个 `cargo msrv` 是第三方 `cargo-msrv` crate。

**库与二进制的 MSRV 策略不同**。库对外承诺的是区间，常见两种形态：**backward compat**（发布后 N 个月内不抬 MSRV，semver-minor 里允许抬一次）与 **forward compat**（只承诺最低版本，随时可抬；如 rustls 自己的口径是 "Rustls requires Rust 1.71 or later"）。二进制没有对外承诺，MSRV 只约束 CI。无论哪种，`rust-version` 声明的是"我保证在 ≥ 这个版本能编"，而**不是**"我用过这个版本测试"——前者是承诺，后者要靠 CI 兑现。

由此推出 CI 矩阵同时测三档的理由：

- **声明的最低版本**：稳定性承诺保证老编译器不拒绝新代码，所以这一档挂了一定是**代码或依赖**的问题，反馈环最短；
- **stable**：用户实际会用的编译器，也是 `rust-version` 应长期钉住的那一档；
- **nightly**（allow-failure）：提前一个节拍看见 future-incompat lint 与 Compatibility Notes 级别的破坏（例如 1.97 的 v0 mangling、1.99 的 `no_mangle` 泛型项硬错误），给自己留出迁移窗口而不是被动挨打。

最小落地形态：CI 矩阵里三行 toolchain（`1.74` / `stable` / `nightly`），本地抽查只需 rustup 的 `+` 选择器——`cargo +1.74 test` 一句（前提是 `rustup toolchain install 1.74`）。想自动二分"当前代码真正的最低可编版本"，用第三方 `cargo-msrv`：它逐版本装 toolchain 试编——这个实现方式恰好解释了为什么它做不成 Cargo 内建子命令（内建机器只需要 resolver 与 manifest 字段，不需要猜）。

> [!TIP]
> 定 MSRV 的实用锚点不是"我的开发机版本"，而是**用户拿编译器的渠道**：发行版打包的 rustc 常落后 stable 一到两年，面向系统包用户就按发行版现值定；面向 crates.io 开发者的库惯例是滚动窗口（rustls 自报 "requires Rust 1.71 or later"，即 1.71.0 / 2023-07-13 的兼容面）。窗口越大兼容性越好，但你在 Compatibility Notes 里被破坏波及的暴露时间也越短——这是一个商业权衡，不是技术下限。

## rustup Channels and Toolchain Selection

rustup 的通道模型：`stable` / `beta` / `nightly` 三个滚动通道，加上 `1.95.0` 这种**pinned toolchain**（钉死某个发布版本，6 周节拍不影响它）。本机实测 `ls ~/.rustup/toolchains/` 即有 `1.95.0-aarch64-apple-darwin` 与 `stable-aarch64-apple-darwin` 并存。

跨版本对照用 `+` 语法，工具链选择器放在子命令之后：

```text
$ rustc +1.95.0 --edition 2021 --emit=metadata --crate-type lib ifletguard.rs   # 编译通过（if let 守卫自 1.95.0）
$ rustc +1.95.0 --edition 2021 --emit=metadata --crate-type lib letchain.rs     # error: let chains are only allowed in Rust 2024 or later
$ rustc +1.95.0 --edition 2024 --emit=metadata --crate-type lib letchain.rs     # 编译通过
```

（`~/.cargo/bin/rustc` 就是 rustc 的 rustup shim；nightly 还可以用日期选择器 `nightly-2026-10-01`。）项目级固定用仓库根的 `rust-toolchain.toml`（`[toolchain] channel = "..."`），它覆盖默认通道、按目录生效。beta 通道的价值在前面说过：Compatibility Notes 里的破坏先在 beta 排练 6 周，`rustup default beta` 就是给自己装预警机。

## Cross-language Comparison

同样面对"语言要演进、生态不能碎"，五种语言的解法差异集中在**演进单位**一列——单位越细，破坏性变化越容易采纳：

| 语言 | 演进单位 | 切换机制 | 旧代码的命运 | 生态代价落点 |
| :-- | :-- | :-- | :-- | :-- |
| Rust | **per-crate** edition | `Cargo.toml` 的 `edition = "2024"` | 永远能编；不动就不变 | 几乎为零：依赖图里混 edition 合法 |
| C++ | per-标准（约每 3 年一版，C++11/14/17/20/23） | 编译器 flag `-std=c++23`，粒度是**整个 TU** | 编译器基本不拒绝旧标准代码 | 同一程序里不同依赖被编成不同标准时没有协调机制，flag 归构建系统管（见 [Standard](/docs/CS/C++/Standard.md)） |
| Java | per-release 语言级别 | `javac --release 21`（同时锁语言 + API 签名视图） | 字节码向后兼容，老 class 永远能跑；但语言演进走 JEP 就地改，删除内部 API 靠强封装 | 语言几乎不破坏，破坏转嫁给生态工具链与 `sun.misc` 类依赖（见 [Java](/docs/CS/Java/Java.md)） |
| Go | **无演进单位**（语言只有一个） | 没有开关，也没有 edition | Go 1 兼容性承诺：程序一旦合法永远合法；新语法（如 1.18 泛型）被约束为不与旧代码冲突 | 语言演进速度被"不能占用旧语法空间"反向锁死（见 [Go](/docs/CS/Go/Go.md)） |
| Python | per-interpreter 大版本 + **per-file** 特性开关 | `from __future__ import annotations` 这类 import 换特性 | 跨大版本**不保证**源码兼容（`print` 语句、除法语义都碎过） | 兼容层全压在运行时库与 `typing_extensions` backport 上（见 [Typing](/docs/CS/Python/Typing.md)） |

Rust 选 per-crate 的原因就是依赖图：一个程序由上千个不同作者的 crate 组成，任何"全局切换"（C++ 的 flag、Python 的解释器版本）都会把迁移决策强加给生态最慢的一环，而"永不破坏"（Go）又把语言冻进既有语法空间。edition 把决策权下放到每个 `Cargo.toml`，代价只是 `cargo fix --edition` 的机械劳动；Python 的 future import 看似相同（per-file 开关），但它只覆盖单个特性且解释器版本仍是全局轴——所以 Python 生态的兼容负担落在库的多版本兼容代码上，而 Rust 落在编译器的 edition 记账上。

## Links

- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [Cargo](/docs/CS/Rust/Cargo.md)
- [compile](/docs/CS/Rust/compile.md)
- [Languages](/docs/CS/Languages.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [Tooling](/docs/CS/Rust/Tooling.md)

## References

- [Editions — The Rust Edition Guide](https://doc.rust-lang.org/edition-guide/editions/index.html)
- [Rust 2018 — Edition Guide](https://doc.rust-lang.org/edition-guide/rust-2018/index.html)
- [Rust 2021 — Edition Guide](https://doc.rust-lang.org/edition-guide/rust-2021/index.html)
- [Rust 2024 — Edition Guide](https://doc.rust-lang.org/edition-guide/rust-2024/index.html)
- [Rust 2024 Cargo Resolver — Edition Guide](https://doc.rust-lang.org/edition-guide/rust-2024/cargo-resolver.html)
- [Rust Releases — Version History and Compatibility Notes](https://doc.rust-lang.org/stable/releases.html)
- [rustc_span::edition — EDITION_NAME_LIST source](https://doc.rust-lang.org/beta/nightly-rustc/src/rustc_span/edition.rs.html)
- [The Cargo Book — Version Resolution](https://doc.rust-lang.org/cargo/reference/resolver.html)
- [The Cargo Book — Manifest Schema](https://doc.rust-lang.org/cargo/reference/manifest.html)
- [cargo fix](https://doc.rust-lang.org/cargo/commands/cargo-fix.html)
- [cargo report](https://doc.rust-lang.org/cargo/commands/cargo-report.html)
- [rustup — Toolchains](https://rust-lang.github.io/rustup/concepts/toolchains.html)
