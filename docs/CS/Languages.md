## Introduction

本页做**编程语言的横向对比**：先一张特性速览表（编译方式、类型系统、内存管理、并发模型、运行时），再逐门语言讲它的适用场景与不宜场景。目的是回答"这件事该用什么语言"，而不是教某门语言的语法。

本页是全站的语言对比入口：先给语言入口列表，再做特性对比，最后逐门语言讲适用场景。各门语言笔记的详细链接见页尾 Links。

## 语言入口列表

各语言笔记的入口，以及编译方式、内存管理与函数调用约定。

| Programming Language                      | Compile Type | Memory Management | Func Call |
|-------------------------------------------|--------------|-------------------|-----------|
| [C](/docs/CS/C/C.md)                      |              |                   | Register  |
| [C++](/docs/CS/C++/C++.md)                |              |                   |           |
| [Golang](/docs/CS/Go/Go.md)               |              | GC                | Stack     |
| [Java](/docs/CS/Java/JDK/JDK.md)          |              | GC                | Stack     |
| [Python](/docs/CS/Python/Python.md)       |              | GC                |           |
| [Rust](/docs/CS/Rust/Rust.md)             |              |                   |           |
| [Scala](/docs/CS/Scala/Scala.md)          |              |                   |           |
| [TypeScript](/docs/CS/TypeScript/TypeScript.md) | 转译为 JS 后由 JIT 执行 | GC                | Stack     |
| [Flutter](/docs/CS/Flutter.md)            |              |                   |           |
| [Assembly](/docs/CS/assembly/assembly.md) |              |                   |           |

不同语言的函数调用耗时有较大差异。

## 特性速览

| 语言 | 编译 / 执行 | 类型系统 | 内存管理 | 并发模型 | 运行时 |
|------|------------|---------|---------|---------|--------|
| [C](/docs/CS/C/C.md) | 编译到机器码 | 静态、弱、名义 | 手动 `malloc`/`free` | OS 线程 / pthread | libc，几乎裸机 |
| [C++](/docs/CS/C++/C++.md) | 编译到机器码 | 静态、强、名义 | RAII + 智能指针，手动为主 | `std::thread`、协程（C++20） | libc++ / libstdc++ |
| [Java](/docs/CS/Java/JDK/JDK.md) | 源码 → 字节码 → JVM 解释 + JIT | 静态、强、名义 | GC（G1/ZGC/Shenandoah） | OS 线程；Java 21+ 虚拟线程 | JVM |
| [Golang](/docs/CS/Go/Go.md) | 编译到机器码（自带编译器） | 静态、强、结构化接口 | 并发三色标记 GC | goroutine + channel，M:N 调度 | Go runtime（含调度器） |
| [Rust](/docs/CS/Rust/Rust.md) | 编译到机器码（LLVM 后端） | 静态、强、所有权 + 借用检查 | 编译期决定，无 GC | `std::thread`、async/await，无数据竞争 | 无运行时（可 `no_std`） |
| [Python](/docs/CS/Python/Python.md) | 源码 → 字节码 → 解释器执行 | 动态、强（duck typing） | 引用计数 + 分代 GC | 线程受 GIL 限制；靠多进程 / async | CPython 解释器 |
| [TypeScript](/docs/CS/TypeScript/TypeScript.md) | 转译为 JS → JIT | 渐进可选静态、结构化、unsound | GC（宿主负责） | 单线程事件循环 + worker | JS 引擎（V8 等） |
| [Scala](/docs/CS/Scala/Scala.md) | 源码 → 字节码 → JVM | 静态、强，含类型推断与高阶类型 | JVM GC | Future / Akka / 协程库 | JVM |

三个容易看漏的列：

- **类型系统的"强/弱"和"静态/动态"是两回事**。Python 是动态但强类型（`"1" + 1` 直接报错），JavaScript/TS 的类型层反而是刻意不健全（unsound）的——见 [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)。
- **内存管理一列决定了性能曲线的形状**：手动管理换来可预测的延迟，GC 换来开发效率但带来停顿与内存放大，Rust 把成本挪到编译期，代价是学习曲线与编译时间。
- **并发模型一列决定了能扛多少连接**：OS 线程约 1:1 且栈开销大（MB 级），goroutine 与虚拟线程是 M:N 且栈可增长（KB 级）。这与 [C10k 问题](/docs/CS/CN/C10k.md)是一件事的两个时代版本。

## C

贴近硬件、没有隐藏成本，是操作系统、嵌入式、数据库存储引擎、高性能库的事实标准。[Linux 内核](/docs/CS/OS/Linux/Linux.md)就是它最大的工程样本。

- **适合**：操作系统与驱动、嵌入式与实时、ABI 稳定的库（被其他语言 FFI 调用）、对延迟有硬要求的场景。
- **不宜**：需要快速迭代的业务应用、字符串/集合密集的逻辑、缺乏静态分析基建的团队。内存安全全靠人，一个 use-after-free 就是线上事故。

## C++

在 C 之上叠加 RAII、模板与 STL，做到了"零成本抽象"——抽象不用的不付费、用到的与手写等价。代价是语言复杂度极高，编译慢，错误信息长。

- **适合**：游戏引擎、交易系统、浏览器（Chromium/V8）、数据库、需要性能又要抽象的中间件。
- **不宜**：团队没有 C++ 经验时的新业务；构建与依赖管理（CMake + vcpkg/Conan）的心智负担明显高于现代语言。

## Java

JVM 提供了跨平台的内存管理、JIT 与成熟的可观测性，生态是企业级中间件最厚的一层（Spring、Netty、Kafka、Flink、Hadoop）。[虚拟线程](/docs/CS/Java/JDK/Loom.md)让同步阻塞写法重新可用，一个请求一个线程不再需要线程池复用。

- **适合**：企业后端、大数据与流处理、需要长期维护和大量现成组件的系统。
- **不宜**：极短生命周期的脚本、内存极度受限的环境、要求毫秒级冷启动的 Serverless（JIT 预热 + 类加载是硬成本）。面向对象的基础概念见 [OOP](/docs/CS/Java/OOP.md)。

## Go

语言刻意做小，把复杂度留给运行时：goroutine + channel 让高并发写法变成默认姿势，编译快、部署是单个静态二进制。GC 是[并发三色标记](/docs/CS/Go/GC.md)，调度器是 [GMP 模型](/docs/CS/Go/GMM.md)。

- **适合**：云原生基础设施与微服务、网关与代理、CLI 工具、需要高并发但不想碰线程细节的后端——[Docker](/docs/CS/Container/Docker/Docker.md)、[Kubernetes](/docs/CS/Container/k8s/K8s.md)、[etcd](/docs/CS/Framework/etcd/etcd.md) 都是它写的。
- **不宜**：需要复杂泛型抽象或丰富表达力的领域（泛型到 1.18 才落地且能力有限）、对 GC 停顿零容忍的实时场景。

## Rust

用所有权与借用检查把内存安全和数据竞争挪到编译期，因此不需要 GC 也能保证安全，延迟表现可预测。代价是学习曲线陡峭、编译时间长。

- **适合**：系统编程的新增代码（重写 CLI、数据库引擎、浏览器组件）、对内存安全与延迟同时有要求的场景、WASM。
- **不宜**：需要当天出活的业务迭代、团队无 Rust 经验且没有资深成员兜底时。

## Python

表达力与生态（科学计算、数据处理、AI）是它的全部优势，性能是它的全部劣势。CPython 的 GIL 让多线程无法利用多核，因此并发靠多进程或 async；3.13 起提供 free-threaded 构建（PEP 703），但生态尚未普遍受益。

- **适合**：数据分析与机器学习、胶水脚本与自动化、原型验证、教学。
- **不宜**：CPU 密集的服务主体（通常把热路径用 C/Rust 写扩展，Python 做编排）。

## TypeScript / JavaScript

同一套语言的两端：TS 是[类型层](/docs/CS/TypeScript/TypeSystem.md)，运行时语义完全来自 JS。它是唯一能同时覆盖浏览器、服务端、桌面（Electron）、移动（React Native）的选择，[Node.js](/docs/CS/front-end/Nodejs.md) 让它在服务端站稳。

- **适合**：前端与全栈、IO 密集的 BFF 与网关、需要跨平台复用代码的团队、工具链与构建脚本。
- **不宜**：CPU 密集计算（事件循环会被阻塞）、需要严格数值语义（只有一种 number）的场景。
- 注意它[是不是一门独立语言](/docs/CS/TypeScript/TypeScript.md)的边界：语法与类型系统自有，运行时语义与目标平台全部借用 JS。

## Scala

同时吃 JVM 生态与函数式表达力：类型推断、模式匹配、高阶类型、不可变集合。代价是编译慢、学习曲线陡、写法差异极大（有人当"更好的 Java"，有人当 Haskell 用）。

- **适合**：数据管道与流处理（Spark/Flink 的原生语言）、需要强表达力且已有 JVM 基建的团队。
- **不宜**：团队流动大的项目——代码风格方差过大是真实的维护风险。

## 选型的几个判断

| 判断 | 说明 |
|------|------|
| 先定运行时，再定语言 | 要求 JVM 生态就别选 Go；要求浏览器就逃不开 JS/TS；要求裸机就只剩 C/C++/Rust |
| 并发模型比性能数字重要 | 一个 goroutine 撑十万连接和十万 OS 线程，是两个数量级的资源差异 |
| GC 不是原罪，停顿才是 | 明确能接受多少 ms 的 P99 停顿，再决定要不要上 Rust 或手动管理 |
| 生态决定交付速度 | 语言特性再好，缺库就得自己造；招人难度同理 |
| 别用类型系统当架构 | TS 的 unsound、Java 的数组协变都说明：类型检查兜不住所有设计错误 |

## Links

- [Tests](/docs/CS/Go/Go.md)
- [Scala](/docs/CS/Scala/Scala.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [Python](/docs/CS/Python/Python.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)

## References

- [TIOBE Index](https://www.tiobe.com/tiobe-index/)
- [Stack Overflow Developer Survey](https://survey.stackoverflow.co/)
- [The Computer Language Benchmarks Game](https://benchmarksgame.org/)
