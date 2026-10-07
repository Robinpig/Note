## Introduction

rustc 是 Rust 的官方编译器，基于 LLVM 后端（另有 cranelift 快速调试后端、GCC 后端等实验方向）。理解编译过程，能解释"借用检查为什么在编译期完成"、"宏和泛型单态化在哪个阶段发生"以及"为什么 debug 构建慢、release 快"。日常开发通常不直接调用 rustc，而是通过 Cargo 驱动整个构建与依赖管理。

## Compilation Process

```
源代码 .rs
 ① 词法/语法分析 → Token → AST
 ② 宏展开与名称解析（macro expansion / name resolution）
 ③ HIR（High-level IR）：类型推断、trait 解析、借用检查的早期分析
 ④ MIR（Mid-level IR）：
     - 借用检查（NLL，基于控制流图的生命周期分析）
     - 常量求值、优化（MIR inlining 等）
 ⑤ LLVM IR：泛型单态化后的代码生成到 LLVM
 ⑥ LLVM 优化 + 后端 codegen → 目标文件 .o
 ⑦ 链接器（ld/lld）→ 可执行文件 / .rlib / .so
```

关键阶段说明：

- **宏展开在名称解析之前**：`macro_rules!` 与过程宏（derive）产出的仍是 AST 片段，所以宏可以生成任意语法项，但 IDE 在展开前无法理解其结果；
- **HIR 与类型系统**：类型推断、trait 方法选择、生命周期推断的大部分工作在此完成，错误提示（E0308 类型不匹配）来自这一层；
- **借用检查运行在 MIR 上**：Rust 2018 后采用 NLL（Non-Lexical Lifetimes），借用存活范围由控制流图上的实际使用决定，而不是词法作用域，因此"作用域结束前已不再使用的引用"不再误报冲突；
- **单态化（monomorphization）**：泛型 `Vec<T>` 对每个具体类型 T 生成一份专用机器码，性能等同手写具体类型，代价是编译时间与代码体积膨胀；
- **unsafe 不跳过借用检查**：unsafe 只开放少数额外能力（裸指针解引用、调用 unsafe fn 等），普通引用仍受完整检查。

## Cargo and Workspaces

Cargo 是官方构建系统与包管理器：`cargo build/check/test/run`、crates.io 依赖、feature flags、workspace 多 crate 构建。`cargo check` 只做到类型检查不做 codegen，是开发循环中最快的反馈方式。

| profile | opt-level | 用途 |
|---------|-----------|------|
| dev（默认） | 0 | 编译快、运行慢，调试信息完整 |
| release | 3 + LTO 可选 | 全量 LLVM 优化，编译慢但运行快 |

## Comparison with Compilers of Other Languages

- 与 Go 相比：Go 直接生成机器码、编译极快、泛型用 GC 而不是所有权；rustc 借 LLVM 获得成熟优化但编译更慢；
- 与 C++ 相比：两者共用 LLVM/链接器后端，区别在前端——Rust 把内存安全做成编译期类型系统规则（ownership/borrow/lifetime），C++ 靠开发者约定与运行时工具（ASan/Valgrind）事后发现；
- 与 Java 相比：Rust 是 AOT 编译为原生码、无 GC、无运行时虚拟机；Java 编译为字节码由 JVM JIT（参见 [JVM 栈结构](/docs/CS/Java/JDK/JVM/Stack.md) 的运行时视角对照）。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Programming（编译与解释）](/docs/CS/SE/Programming.md)

## References

1. [The rustc book - Guide to Rustc Development](https://rustc-dev-guide.rust-lang.org/)
2. [Rust Reference](https://doc.rust-lang.org/reference/)
