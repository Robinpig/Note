## Introduction

Rust 的全部设计可以压成一句话：**把内存安全从运行时挪到编译期，并且不为这个保证付出运行时代价**。这句话藏着三个难点，Rust 的答案正好是三套机制——所有权与生命周期负责回答"这块内存什么时候还有效"，trait 与泛型负责"抽象在编译后被折叠成具体机器码"，`unsafe` 负责"编译器证明不了的部分必须显式标出来、责任随之转移"。三者不是并列的特性清单，而是同一个目标的三面：缺任何一面，另外两面都不成立。

代价同样清楚：既然保证发生在编译期，程序员要向编译器交代的东西就变多了。本子树绝大多数笔记其实是在替同一件事记账——**编译器到底要知道什么，才敢放行这段代码**。把这条线索拎起来，二十多篇笔记就不是散落的知识点，而是一条从类型系统延伸到工具链的完整链条。

写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，最新 edition 为 2024（1.85.0 起 stable）。

## Ownership Is a Type System Question

主线从内存开始。Rust 既没有分代回收也没有引用计数兜底，靠的是把"谁拥有这块内存"和"它能被用到什么时候"写进类型。 [Ownership](/docs/CS/Rust/Ownership.md) 讲这套规则的本体：值有唯一所有者，赋值默认移动，借用必须满足"一写或多读"。把它读懂之后，初学者最常撞到的报错会收敛成同一张脸——几乎所有 E0382 / E0502 都是这条规则在不同位置的表现。

紧接着要回答"这个借用活多久"。 [Lifetime](/docs/CS/Rust/Lifetime.md) 处理的正是这一层，而且必须纠一个流行误解：生命周期标注**不是**编译器给你的提示信息，恰恰相反，它是程序员向类型系统提交的声明——"这个引用的有效期至少覆盖到这里"，编译器拿它做约束求解。标注是输入，省略号的省略是编译器省你写字的善意，两者不是一回事。

有"消失"就得有"结束时做什么"。 [Drop](/docs/CS/Rust/Drop.md) 覆盖析构顺序、`std::mem::drop` 是函数而不是关键字（所以移动语义照样适用）这个常年被误解的点，以及 dropck 为什么要求析构 `Vec<T>` 时还得关心 `T` 此刻是否仍然可见。

所有权模型不够用的场景是常态，于是有四种代价各异的转义手段，由 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md) 逐个交代：`Box` 是上堆与递归类型的最小面，`Rc` 与 `Arc` 把所有权变成计数（后者是原子的），`RefCell` 把"一写或多读"的检查从编译期搬到运行期，`Weak` 则让所有权图允许有环——只有它允许成为有向有环图而前三者的组合必须构成树。

这些抽象最终要落地为字节， [Memory_Layout](/docs/CS/Rust/Memory_Layout.md) 给出确切答案：`Vec<T>` 是三个机器字，切片与 trait 对象是胖指针（数据和元数据并存），`Option<Box<T>>` 与裸指针等宽。它同时说明"零成本"从来不等于"零空间"。

## Abstraction That Disappears After Compilation

第二条主线是零成本抽象。这个词被滥用得很厉害，它的准确定义是：**没用到的不付代价，用到的手写也差不太多**。 [Trait_System](/docs/CS/Rust/Trait_System.md) 是地基——`impl Trait` 与 `dyn Trait` 的分野不是风格问题是实现策略问题（单态化 vs 虚表），对象安全规定的是哪些 trait 能被擦成运行时多态。 [Generics](/docs/CS/Rust/Generics.md) 接着讲单态化本身以及它的账单：每个具体类型一份专用代码，编译时长和二进制体积都要买单，这份账单也是 [compile](/docs/CS/Rust/compile.md) 里介绍的 HIR / MIR / LLVM IR 三段式流程为什么必要的原因——借用检查跑在 MIR 上而不是 AST 上，因为控制流图才回答得了"这条路径上还会用到吗"。

日常写得最多、误解得也最多的是 [Iterator](/docs/CS/Rust/Iterator.md) ：`map`-`filter`-`fold` 这条链在消费之前**什么都不做**，惰性不是优化技巧而是类型设计的结果，`size_hint` 决定了 `collect` 能预分配多少。对 `Option` 和 `Result` 的另一半由 [Pattern_Matching](/docs/CS/Rust/Pattern_Matching.md) 补上：匹配不是 switch 的加强版，它是"穷尽性成为编译错误"这块语言保证的实现方式；match ergonomics 决定 `Some(x)` 里的 `x` 到底是值还是引用，也就把模式这块直接楔回了所有权那条主线。错误值怎么一路传上来，则是 [Error_Handling](/docs/CS/Rust/Error_Handling.md) 的领域——`?` 展开后就是一次 `match` 加一次 `From`，没有什么神秘成分。

再往编译期推一层是 [Macros](/docs/CS/Rust/Macros.md) ：它生成的是语法项而非字符替换，因此和 C 那套纯文本预处理没有可比性（对照见 [C 预处理器](/docs/CS/C/Preprocessor.md)）。 [Collections](/docs/CS/Rust/Collections.md) 从容器侧看同一件事——三种遍历入口对应三种所有权姿势，而"迭代器失效"在这里是不可能发生的，因为借用检查器已经把边遍历边修改挡在编译期。

等这些抽象真要兑现成机器码， [Performance](/docs/CS/Rust/Performance.md) 接手：迭代器链与手写循环在 `--release` 下趋同的原因、`inline` 为什么只是提示、profile 里的 LTO 与 `codegen-units` 各自换来了什么。

## Two Worlds of Concurrency

并发是本库拆得最清楚的一处，因为它天然分两个世界，而混谈这两个世界是绝大多数异步文章出错的根源。 [Concurrency](/docs/CS/Rust/Concurrency.md) 是线程世界：操作系统线程、`Send` / `Sync` 作为"无数据竞争"的类型化表达、`Mutex` 与原子操作。关键点在于 `Send` / `Sync` 是 auto trait，编译器替你推导，而你自己手写 `unsafe impl` 就等于把整套担保接过肩膀。

 [Async](/docs/CS/Rust/Async.md) 是另一个世界：`Future` 是状态机而不是绿色线程，谁来推进它由运行时决定，由此衍生出 `Pin` 的自引用问题和跨 `.await` 的 `Send` 传染问题。两个世界之间有桥（`spawn_blocking`、`block_on`），但语义不通用——比如 `std::sync::Mutex` 的 guard 跨 `.await` 是典型事故。差别不在语法而在调度主体。

## Where Safety Ends

第三条主线是边界。 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md) 讲清 `unsafe` 到底开放了什么：解引用裸指针、调用 unsafe 函数、访问可变静态、实现 unsafe trait、访问 union 字段，仅此五项。它不是"关闭检查"而是"此处由人担保"——普通引用在经过 `unsafe` 块时照样受借用检查管辖。FFI 侧的 ABI 选择、`MaybeUninit` 的部分初始化契约、回调里 panic 的走向也都在这里。

再往外一步是连 `std` 都不存在的场景， [No_Std](/docs/CS/Rust/No_Std.md) 处理：`core` / `alloc` / `std` 三层能力边界、`#[panic_handler]` 与 `#[global_allocator]` 为什么必须由你自己提供、裸机上的 MMIO 为什么非用 volatile 读写不可。

## Building Real Projects

工程侧的展开顺序几乎是固定的。先弄清 [Cargo](/docs/CS/Rust/Cargo.md) ：manifest 表达的其实是三层东西——约束、`Cargo.lock` 里那张具体依赖图、以及被打散成多个编译单元的构建图；版本需求里的 caret 语义、feature 只能是加法的铁律、resolver 三代的行为差异都是日常会撞到的。它之上是 [Module_System](/docs/CS/Rust/Module_System.md) 那套容易混淆的三层概念（crate 是编译单元、package 是 Cargo 概念、module 是命名空间树），其中"私有"的真实含义是**对当前模块及其后代可见**，这一条解释了很多反直觉现象。

交付流程由两篇分担： [Testing](/docs/CS/Rust/Testing.md) 处理单元测试、 `tests/` 下的集成测试与文档测试三种不同编译单元的区别，`#[bench]` 被硬错误化之后基准该怎么搭； [Tooling](/docs/CS/Rust/Tooling.md) 处理 rustup 通道模型、rust-analyzer、rustfmt、clippy、rustdoc 与 Miri 各自守的是哪一段。最后往上接到真实世界—— [Ecosystem](/docs/CS/Rust/Ecosystem.md) 按职能分层给出 crate 选型，核心方法论是看 MSRV、看依赖树宽度、看维护活跃度，并且牢记 0.x 版本的 minor 就是破坏性变更。

## How It Evolves Without Breaking

最后一串中所有的"从哪个版本起"都要落到 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md) 那套三轴坐标系上：编译器版本每六周一个节拍，edition 是单个 crate 可选进的语言层重定义，`rust-version` 是自己声明的兼容下限。判断某段代码能不能编，三个轴必须同时回答。它也记载了"稳定承诺"的真实边界——每个 release 的 Compatibility Notes 就是官方预留的受控破坏通道，所以"某个写法存在"从来不等于"它现在的语义还是原来那个"。

## Where Rust Sits Among Languages

放在横向坐标里，Rust 的定位由它放弃的东西定义。对 [C 与 C++](/docs/CS/C++/C++.md) 而言，它把内存安全从"约定 + 事后工具"变成编译期类型义务，代价是编译器对每个借用的生存期都要问一句；对 Java 这种依靠 [垃圾回收](/docs/CS/memory/GC.md) 的语言，它换掉了运行时的停顿与管理帧，收不到那份"先跑起来再说"的便利；对 [Go](/docs/CS/Go/Go.md) 那种 library 自带调度器的方案，它没有运行时却要把并发的两个世界分开管；对 [Python](/docs/CS/Python/Python.md) 这类动态语言，它把几乎所有决策前移到了编译期。二进制产物如何拼接则由 [ELF](/docs/CS/Compiler/ELF.md) 那篇负责，而内存分配与线程无论怎样抽象，最终仍然是 [Linux 内核](/docs/CS/OS/Linux/Linux.md) 提供的那几个系统调用——没有 GC 的意思是这件事你躲不掉。横向速查另见 [编程语言横向对比](/docs/CS/Languages.md)。

## Links

- [编译原理（Programming）](/docs/CS/SE/Programming.md)
- [C](/docs/CS/C/C.md)
- [软件工程](/docs/CS/SE/Engineering.md)

## References

- [The Rust Programming Language（the Book）](https://doc.rust-lang.org/book/)
- [The Rust Reference](https://doc.rust-lang.org/reference/)
- [The Rustonomicon（Dark Arts of Advanced and Unsafe Rust）](https://doc.rust-lang.org/nomicon/)
- [The Cargo Book](https://doc.rust-lang.org/cargo/)
- [The rustc Dev Guide](https://rustc-dev-guide.rust-lang.org/)
- [The Rust Edition Guide](https://doc.rust-lang.org/edition-guide/editions/index.html)
- [Rust Releases — Version History and Compatibility Notes](https://doc.rust-lang.org/stable/releases.html)
- [Rust Blog](https://blog.rust-lang.org/)
- [crates.io](https://crates.io/)
