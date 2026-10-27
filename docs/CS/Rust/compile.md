## Introduction

rustc 是 Rust 的官方编译器，用 Rust 自己写成（自举），后端基于 LLVM（另有 cranelift 快速调试后端、GCC 后端等实验方向）。理解编译过程，能解释"借用检查为什么在编译期完成"、"宏和泛型单态化在哪个阶段发生"以及"为什么 debug 构建慢、release 快"。日常开发通常不直接调用 rustc，而是通过 Cargo 驱动整个构建与依赖管理。

本篇按**从前端到链接器**的顺序走一遍管线，然后讲编译期真正花时间的四个大户（单态化、宏展开、增量、codegen-units）与对应的调节手段。版本归属：管线结构与旗标行为以 **rustc 1.99.1（2026-10-15）** 的文档为准；标"据 rustc-dev-guide"的条目是流程描述，非版本相关事实。

## The Pipeline

```
源代码 .rs
 ① 词法/语法分析 → TokenStream → AST
 ② 宏展开与名称解析（macro expansion / name resolution，两者交错进行）
 ③ HIR（High-level IR）：类型推断、trait 解析、方法选择的输入
 ④ THIR / MIR（Mid-level IR）：
     - 借用检查（NLL，基于控制流图的生命周期分析）
     - 常量求值、MIR inlining 等优化
 ⑤ LLVM IR：泛型单态化后生成 LLVM module
 ⑥ LLVM 优化 + 后端 codegen → 目标文件 .o
 ⑦ 链接器（lld / ld / mold）→ 可执行文件 / rlib / dylib / cdylib
```

关键阶段说明：

- **宏展开与名称解析交错**：`macro_rules!` 与过程宏产出的仍是 token / AST 片段，所以宏可以生成任意语法项，但 IDE 在展开前无法理解其结果；名称解析因此可能"解析一半遇到宏、展开再继续"。过程宏作为宿主 dylib 在这一步被调用，详见 [Proc_Macro](/docs/CS/Rust/Proc_Macro.md)。
- **HIR 与类型系统**：类型推断、trait 方法选择、生命周期推断的大部分工作在此完成，错误提示（E0308 类型不匹配）来自这一层。
- **借用检查运行在 MIR 上**：Rust 2018 后采用 NLL（Non-Lexical Lifetimes），借用存活范围由控制流图上的实际使用决定，而不是词法作用域，因此"作用域结束前已不再使用的引用"不再误报冲突；AST 上做不到这件事，因为"这条路径上还会用到吗"需要控制流图才能回答。
- **单态化（monomorphization）**：泛型 `Vec<T>` 对每个具体类型 T 生成一份专用机器码，性能等同手写具体类型，代价是编译时间与代码体积膨胀；MIR 阶段的 `-Zshare-generics`（默认开）会让部分实例共享一份代码，这是"膨胀可缓解但不可消除"的原因。
- **unsafe 不跳过借用检查**：unsafe 只开放少数额外能力（裸指针解引用、调用 unsafe fn 等），普通引用仍受完整检查，见 [Unsafe](/docs/CS/Rust/Unsafe.md)。

### NLL and What Comes After

NLL 解决的是"借用活到词法作用域末尾"这个过强近似，但它仍有已知局限——典型是**条件性返回引用**（`fn get(map: &Map, cond: bool) -> &Value` 里两个分支借不同键）与跨函数的生命周期流动问题。下一代 borrow check **Polonius** 用"位置敏感的数据流分析"取代"区域（region）推导"，能放过这些合法代码。

现状：Polonius 的**子集**（location-insensitive 版本）已在 nightly 以 `-Zpolonius` 提供，完整版仍在 rust-lang 仓库演进；**stable 上仍是 NLL**。写库时遇到"明明是合法代码却过不了借用检查"，先怀疑踩到 NLL 的已知局限， nightly + Polonius 是验证手段。

## Monomorphization: The Compile-Time Bill

零成本抽象的账单在编译期结算，四个事实决定了账的大小：

1. **每个具体类型一份代码**：`fn f<T>(x: T)` 被 `u32` / `String` / `Vec<u8>` 调用三次，机器码有三份；嵌套泛型是指数级的（`Vec<Vec<u32>>` 不是简单地两份）。
2. **跨 crate 不共享**：单态化发生在**最终** crate，所以库 crate 交付的是泛型的 MIR/LLVM IR，每个下游都各自实例化一遍。这也是"改一行调用方代码为什么会引起大范围重编"的根源之一。
3. **`impl Trait` 与泛型同价**：`impl Trait` 参数位置等价于泛型（单态化），返回位置等价于匿名具体类型——都不是 `dyn` 的动态分发，见 [Trait_System](/docs/CS/Rust/Trait_System.md)。
4. **`dyn Trait` 是唯一的省钱选项**：一份虚表分发代码替所有实现者买单，代价是间接调用与内联屏障。二进制体积敏感时，热路径保留泛型、冷路径考虑 `dyn`。

## Incremental Compilation

增量编译把"上次编过的部分"缓存成查询结果（rustc 内部是 query 系统：从 `crate_metadata` 到 `optimized_mir` 的每条查询带缓存），下次只重算受影响的查询。默认行为：

- **dev profile 默认开启**，release 默认关闭（release 的跨 crate 优化会削弱缓存命中）。
- 缓存放 `target/debug/incremental/`，改一行通常只重编当前 crate。
- 增量与某些优化不兼容（最明显的是 LTO 全量模式），表现为"开 LTO 时增量自动失效"。

`cargo check` 是更轻的反馈：走到类型检查为止，不生成机器码、不链接。**开发循环的标准姿势是 `cargo check` + `cargo build` 只在要运行时做**；配 `cargo-watch` 或 IDE 的保存即检就是查这条路径。

## Codegen Units, LTO, and Profiles

LLVM 侧的并行度与优化深度由 profile 与 codegen-units 决定：

| 维度 | dev | release |
| :--- | :--- | :--- |
| opt-level | 0 | 3 |
| codegen-units | 16（并行多，优化差） | 1（单线程，优化全） |
| LTO | off | `false` / `thin` / `fat` 可选 |
| debuginfo | 完整 | 可裁 |
| panic | unwind | 可选 abort |

- **codegen-units**：把 crate 切成多个编译单元并行 codegen。数量越多编译越快、优化越差（跨单元的调用看不见对方）。release 设 1 是拿编译时长换运行时性能。
- **LTO**：`thin`（LLVM 的模块间轻量优化）是性价比之选；`fat` 把所有 IR 合成一个 module 做全量优化，编译最慢、可能挤出最后百分之几性能。跨 crate 的泛型实例化此时才可能被合并。
- **`-C embed-bitcode` 与 `linker-plugin-lto`**：前者让 rlib 携带 LLVM bitcode（fat LTO 的前提），后者把 LTO 下沉到链接器插件，介于 thin 与 fat 之间。

**PGO**（`-C profile-generate` / `-C profile-use`）是更激进的交换：先跑一遍真实负载收集 profile，再喂回编译器做分支预测与内联决策——对热路径固定的服务端程序通常有可观收益，代价是两轮构建与 profile 数据管理。`cargo build --timings` 与 `cargo llvm-lines` 是定位"编译时间花在哪 / 泛型膨胀有多大"的两个常用工具。

## Linking: From Object to Artifact

rustc 的产物形态由 `--crate-type` 决定：

| 类型 | 内容 | 用途 |
| :--- | :--- | :--- |
| `bin` | 可执行文件 | 最终产品 |
| `rlib` | Rust 静态库 + 元数据 | **默认的库产物**，只能被 rustc 用 |
| `dylib` | Rust 动态库 | 被其它 Rust 程序动态链接 |
| `cdylib` | **C ABI** 动态库 | 给 C / Python / Node 用，无 Rust 元数据 |
| `staticlib` | C ABI 静态库 | 链进别人的最终二进制 |

三个与链接相关的常见问题：

1. **符号 mangling**：`"Rust"` ABI 的符号名带哈希与泛型参数，跨版本不稳定；`#[unsafe(no_mangle)]` 关掉它（edition 2024 起 unsafe attribute，见 [Unsafe](/docs/CS/Rust/Unsafe.md)），导出给 C 用。
2. **链接器选择**：默认用系统的 `cc` / `ld`；可用 `-C linker-flavor` / `linker=` 换 `lld` 或 `mold`——大项目换 mold 的链接加速常常是数量级的，且不改语义。
3. **`-C prefer-dynamic` 与 split-debuginfo**：前者让依赖链动态链接 std（二进制小、运行时依赖 libstd.so），后者把调试信息拆出去（Linux 上 `.dwp` / `.dwo`）——两者都影响产物分发形态。

跨平台交叉编译由 `--target <triple>` 驱动：换 sysroot、换链接器、换 `std` 预编译件；没有预编译 std 的目标要 `-Z build-std`，见 [No_Std](/docs/CS/Rust/No_Std.md)。目标三元组与 tier 等级见 [WASM](/docs/CS/Rust/WASM.md) 的 wasm 谱系。

## cargo check versus cargo build versus rustc

| 命令 | 走到哪 | 用途 |
| :--- | :--- | :--- |
| `cargo check` | HIR/MIR 类型检查，无 codegen 无链接 | 最快反馈 |
| `cargo build` | 全管线 + 链接 | 得到可运行产物 |
| `cargo clippy` | check + 额外 lint（也是 rustc 驱动） | 静态分析 |
| `cargo doc` | rustdoc，独立的文档管线 | 文档 |
| `cargo rustc` | 直接把参数透传给 rustc | `-Zunpretty=expanded` 一类 |
| `rustc --explain E0382` | 错误码长文本 | 诊断的权威解释 |

`cargo` 与 `rustc` 的分工：**rustc 编一个 crate，Cargo 决定编哪些 crate、以什么顺序、带什么 feature、传给 rustc 什么旗标**。manifest 语义与依赖解析见 [Cargo](/docs/CS/Rust/Cargo.md)，feature 与 resolver 的行为差异也归它。

## Comparison with Compilers of Other Languages

- 与 Go 相比：Go 直接生成机器码、编译极快、泛型用 GC 而不是所有权；rustc 借 LLVM 获得成熟优化但编译更慢——慢的大头正是单态化 + 宏展开 + MIR 上的借用检查这三件 Go 没有的事；
- 与 C++ 相比：两者共用 LLVM/链接器后端，区别在前端——Rust 把内存安全做成编译期类型系统规则（ownership/borrow/lifetime），C++ 靠开发者约定与运行时工具（ASan/Valgrind）事后发现；模板的实例化模型与 Rust 泛型对比见 [Templates](/docs/CS/C++/Templates.md) 与 [Generics](/docs/CS/Rust/Generics.md)；
- 与 Java 相比：Rust 是 AOT 编译为原生码、无 GC、无运行时虚拟机；Java 编译为字节码由 JVM JIT（参见 [JVM 栈结构](/docs/CS/Java/JDK/JVM/Stack.md) 的运行时视角对照）；
- 与 Python 相比：CPython 的字节码是运行期解释的，编译期只做语法检查，Rust 的全部决策（所有权、单态化、布局）都在编译期定完。

## A Compile-Time Tuning Checklist

编译慢的时候按这个顺序查：

1. `cargo build --timings` 看时间花在哪个 crate——多半是宏重的依赖（serde / tokio / prost / bindgen 一族）或泛型大户。
2. 开发循环换 `cargo check`；确认 dev profile 的增量开着（默认开，别在 CI 缓存里清掉）。
3. codegen-units 在 dev 已经默认 16；release 只在真要性能时收敛到 1。
4. LTO 先用 `thin`；`fat` 只对最终发布产物开。
5. 泛型膨胀用 `cargo llvm-lines` 看实例化排行，热路径外的泛型考虑 `dyn`。
6. 换 `lld` / `mold` 链接器；换完先跑全量测试。
7. 真要压榨运行时：PGO 两轮构建。
8. nightly 需求（`-Zbuild-std` / Polonius / 新 lint）单独隔离到 CI 或本地，别污染团队的 stable 工具链。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Cargo](/docs/CS/Rust/Cargo.md)
- [Proc_Macro](/docs/CS/Rust/Proc_Macro.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [No_Std](/docs/CS/Rust/No_Std.md)
- [Programming（编译与解释）](/docs/CS/SE/Programming.md)

## References

1. [The rustc book — Guide to Rustc Development](https://rustc-dev-guide.rust-lang.org/)
2. [rustc-dev-guide — Lexing and Parsing](https://rustc-dev-guide.rust-lang.org/parsing.html)
3. [rustc-dev-guide — The MIR (Mid-level IR)](https://rustc-dev-guide.rust-lang.org/mir/index.html)
4. [rustc-dev-guide — Incremental compilation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html)
5. [Rust Reference](https://doc.rust-lang.org/reference/)
6. [The Cargo Book — Profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)
