## Introduction

`unsafe` 与 FFI 常被当成两个话题，其实是同一条边界的内外两面，分开谈必然两头落空。**向内看**，`unsafe` 是"编译器证明不了、但语义合法的操作由人担保"——它解锁的只有五种能力，其余检查照旧，变的只是责任落在谁身上。**向外看**，FFI 把这份担保**用 C ABI 重述给另一个语言**：Rust 的不变式出不了进程内存图，对端只认字节布局、调用约定与释放责任，所以契约必须翻译成"谁分配、谁释放、谁能穿过、panic 谁接"四句可审计的话。

拆成两篇之后，分工是这样：

- [Unsafe](/docs/CS/Rust/Unsafe.md) 讲语言内部：`unsafe` 块到底开放什么、Rust 的 UB 清单与 C/C++ 的逐条对照、指针 provenance 与两种别名模型（Stacked / Tree Borrows）、`MaybeUninit` 的"绕过不变式"契约、`static mut` 的退场、edition 2024 对 unsafe 生态的一次性收紧，以及写 unsafe 的六条纪律与十类失败模式。
- [FFI](/docs/CS/Rust/FFI.md) 讲语言之间：ABI 谱系（`"C"` / `"system"` / `"C-unwind"` 与平台具名 ABI）、哪些类型能跨边界、C 变参声明与定义的分次稳定、不透明句柄的布局契约、三种所有权契约（借用 / 移交 / 回调归还）、bindgen 与 cxx 各自翻译什么，以及 Python / Node / Java / 浏览器各宿主的封装差异。

两条主线在几个点上是同一件事：**provenance 既是别名模型的输入，也是 FFI 里"地址能不能带出国界"的判据**；**`Box::into_raw` / `from_raw` 既是 unsafe 的指针运算，也是跨边界所有权移交的标准形状**；**panic 穿越边界的 abort 语义既定义在 `extern "C"` 的 ABI 里，也决定回调里能写什么**。所以本文不再重复任何一面的细节，只留三个跨两篇才能看清的判断：

**第一，`unsafe` 的正确性只能由契约承载。** 编译器能报的那部分（借用冲突、尺寸不符、`static_mut_refs`）在 [Unsafe](/docs/CS/Rust/Unsafe.md) 全部列出；报不了的那部分（"这块内存必须由配套的 `_free` 释放""这个 `&mut` 区间与另一个区间不重叠"）只能写进文档与测试。miri 能机器验证别名与未初始化，但它 nightly-only、只跑 Rust 代码、且检查的是提案级模型——是最便宜的一层网，不是地板。

**第二，FFI 的安全不取决于用了哪个工具。** bindgen 忠实转录 C 的头文件并生成布局测试，cxx 把双向翻译收敛到一套类型词汇表，但它们都翻译不了契约：错误码到 `Result` 的映射、空指针的集中处理、生命周期边界，永远手写。工具让边界变窄，不让人变轻松。

**第三，版本轴必须三问同时回答。** 本文的版本归属与诊断文本以 rustc 1.98.1（2026-09-01）实测为准；标"自 1.99.0 起"的条目来自 release notes 史页（如 C 变参定义、`Box::leak` 的推荐用法反转），并同时给出 1.98.1 上的 E0658 互证。判断某段 unsafe 代码能不能编，编译器版本、edition、MSRV 三轴见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)。

顺带一个口径提醒：未定义行为的概念本身不在这里重述，本库已有 [C 的未定义行为](/docs/CS/C/UB.md) 与 [C++ 的未定义行为](/docs/CS/C++/UB.md) 两篇，本文只做对照。

## Links

- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [FFI](/docs/CS/Rust/FFI.md)
- [内存布局](/docs/CS/Rust/Memory_Layout.md)
- [智能指针](/docs/CS/Rust/Smart_Pointers.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)
- [Edition 与 MSRV](/docs/CS/Rust/Edition_MSRV.md)

## References

1. [Behavior Considered Undefined (Rust Reference)](https://doc.rust-lang.org/reference/behavior-considered-undefined.html)
2. [The Rustonomicon](https://doc.rust-lang.org/nomicon/)
3. [FFI chapter of the Rustonomicon](https://doc.rust-lang.org/nomicon/ffi.html)
4. [Unsafe Code Guidelines Working Group](https://github.com/rust-lang/unsafe-code-guidelines)
5. [bindgen User Guide](https://rust-lang.github.io/rust-bindgen/)
6. [Rust Release Notes](https://doc.rust-lang.org/stable/releases.html)
