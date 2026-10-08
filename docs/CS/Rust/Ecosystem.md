## Introduction

Rust 的语言特性只负责「能写出安全且快的代码」，真正决定工程效率的是 crates.io 上那套生态。它有一个和其他语言很不一样的定位：**crates.io 是 Cargo 唯一默认 registry**——`Cargo.toml` 里写一行 `serde = "1"`，查询的 registry、下载的源码包、写入 `Cargo.lock` 的版本号，全部由这一个源决定。没有 Maven 那种「先找 Central，找不到再找私服」的层次，也没有 Go 那种「按 import 路径直接去 VCS 拉」的分散模式。

这个中心化带来两个后果，贯穿全篇：

- **分发的是源码，不是二进制**。registry 上存的是 `.crate` 源码包，编译发生在你本机。所以「依赖树有多宽」直接等于「编译要多久」——这不是构建系统的实现细节，而是语言设计的直接后果：泛型要单态化（见 [compile.md](/docs/CS/Rust/compile.md)），每个 crate 都要在你机器上重新过一遍 codegen。
- **破坏性变更有双开关**。别的语言只有「版本号」一个旋钮，Rust 有 crate 级 edition + crate 级 `rust-version`（MSRV）两个正交旋钮，外加 semver 承诺。这让生态可以同时容纳 2015 edition 的老 crate 和 2024 edition 的新 crate，代价是选型时要多问一个问题。

本篇按职能分层讲**选型**：每层给出「为什么选它 / 什么时候不该选 / 代价是什么」，最后收在选型方法论与跨生态对照上。讲语言机制本身的地方都交叉引用出去——异步状态机与 `Pin` 见 [Async.md](/docs/CS/Rust/Async.md)，`Error` trait 本体见 [Error_Handling.md](/docs/CS/Rust/Error_Handling.md)，`Send` / `Sync` 与 std 同步原语见 [Concurrency.md](/docs/CS/Rust/Concurrency.md)，布局规则见 [Memory_Layout.md](/docs/CS/Rust/Memory_Layout.md)，跨语言 ABI 与绑定生成见 [Unsafe_FFI.md](/docs/CS/Rust/Unsafe_FFI.md)，版本/MSRV 机制见 [Edition_MSRV.md](/docs/CS/Rust/Edition_MSRV.md)。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，最新 edition 为 2024；本机实测工具链 `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1`，host `aarch64-apple-darwin`。下文所有 crate 版本与 `rust_version`（MSRV）字段均为 **2026-10-07 用 crates.io sparse index 实测**读取，命令形如：
>
> ```bash
> curl -s "https://index.crates.io/se/rd/serde" | tail -1
> ```
>
> 凡实测写到「实测」，凡取自文档或 release notes 写明出处，不谎称实测。

## crates.io as the Single Default Registry

一次 `cargo build` 的依赖链路是：读 `Cargo.toml` 的版本需求 → 向 `index.crates.io`（sparse index，HTTPS 上按 crate 名取一个 JSON-lines 文件）拉该 crate 的全量版本列表 → resolver 挑一组满足所有约束的版本 → 下载 `.crate` 源码包并校验校验和 → 写入 `Cargo.lock` → 本地编译。

两个容易被忽略的性质：

**索引是「一 crate 一文件」的纯文本**。整个版本历史（版本号、校验和、`rust_version`、feature 表、依赖表）都在那个文件里，一行一个版本。所以查 MSRV 不需要装任何工具，直接读索引最后一行即可。

**命名空间是扁平的、先到先得**。没有 Java 的 `groupId` 分层，也没有 Go 的「域名 + 路径」。一个名字被谁先注册就是谁的，这在治理层面意味着名字抢注要靠政策而非机制解决。

依赖树宽度是可以实测的。建一个只依赖 `axum` 与 `tokio`（`features = ["full"]`）的空二进制，实测：

```text
$ cargo tree
ax v0.1.0 (/private/tmp/rpc/ax)
├── axum v0.8.9
└── tokio v1.53.2
    ...
```

`cargo tree` 输出 121 行，去重后 55 个 crate（含根 crate）。也就是说，**两个直接依赖换来 50 多个需要本机编译的 crate**。这是「源码分发 + 单态化」这条设计路线的直接账单，选型时它是真实成本，不是抽象担忧。

## Async Runtimes

语言只提供 `Future` trait 与 `async` / `await` 语法，**调度器、反应器（reactor）、定时器全部由运行时提供**（[Async.md](/docs/CS/Rust/Async.md) 讲这个分工）。所以异步选型的第一件事是选运行时，而一旦选定，你的整个依赖树基本都被它钉死。

| crate | 版本（实测） | MSRV | 调度模型 | 什么时候选 |
| :-- | :-- | :-- | :-- | :-- |
| tokio | 1.53.2 | 1.71 | 多线程 work-stealing，可选 current-thread | 默认选项；需要生态兼容时 |
| smol | 2.0.2 | 1.63 | 极简 executor，可组合 | 想要小而可控的 executor |
| async-std | 1.13.2 | 1.63 | std 镜像 API | **不要选（已终止维护）** |
| glommio | 0.9.0 | 1.65 | thread-per-core + io_uring | Linux 高 IO、追求尾延迟 |
| monoio | 0.2.4 | 索引未声明 | thread-per-core + io_uring | Linux 高 IO、需要 tokio 兼容层 |

### Why tokio, and When Not To

选它的真正理由不是「它最快」，而是**生态默认绑它**：hyper 1.12.0、axum 0.8.9、reqwest 0.13.5、sqlx 0.9.0 的异步接口都在 tokio 的类型上定义。不选 tokio 就意味着你得靠兼容层（`tokio-compat`、`async-compat`）去桥，而桥本身就是风险面。

什么时候不该选：

- **no_std 或裸机**：tokio 依赖 std 与分配器。
- **只需要一个 executor**：`futures` 0.3.34 的 `LocalPool` / `block_on` 够用时，拉 tokio 是把整个 reactor + 线程池塞进依赖树。
- **thread-per-core  workload**：work-stealing 的跨核迁移在 CPU 亲和性敏感的场景是负担。

### async-std Is Discontinued, Not Merely Quiet

这一点必须写准。crates.io 上 async-std 1.13.2 的页面明写 **"Deprecated in favor of `smol`"**，正文写着 *"async-std has been discontinued; use smol instead"*，并附 **RUSTSEC-2025-0052（unmaintained）**公告。官方给出的迁移目标就是 smol，以及 `futures-lite` / `async-io` / `async-compat` 这套拆开的零件。

所以结论不是「谨慎使用」，而是**新项目不要引入**；存量项目用 `cargo audit` 会直接报这条公告。这也顺带说明一件事：在 Rust 生态里「维护状态」是可机检的（RUSTSEC + `cargo audit`），不需要靠印象判断。

### The io_uring Route: glommio and monoio

两者都是 thread-per-core + io_uring。monoio 的 crate 描述原文是 *"A thread per core runtime based on iouring"*。适用面很窄也很明确：Linux、内核支持 io_uring、工作负载以大量 IO 为主、且你愿意接受「一个线程一个核、任务不迁移」的模型。

**buffer 所有权模型不同，这是与 tokio 最本质的差别**，也是最容易踩的坑：

- tokio 是 **readiness + poll** 模型：`write_all(&buf)` 在返回 `Ready` 时，内核已经把 `buf` 的内容取走（或拷进内核缓冲），`buf` 立刻可以被复用或丢弃。
- io_uring 是 **completion** 模型：你提交一个 SQE 把 buffer 交给内核，**内核在 IO 完成之后才归还所有权**。所以运行时必须在整个操作期间持有这块 buffer，且不能让它被移动或释放。

具体到 API 形状，就是 monoio 用 `IoBuf` / `IoBufMut` 这类「所有权转移」的 buffer 抽象（`write()` 拿走 `T: IoBuf`，完成后通过返回的 future 把它还给你），glommio 有自己的缓冲与 DMA 文件抽象。这套约束和 `Async.md` 里讲的 `Pin`（自引用状态机不能被移动）是同一族问题：**异步操作的生命周期跨越了 await 点，所以编译器必须能证明被内核引用的那块内存在这段时间内稳定**。手写 `unsafe` 去绕过它，就是 UB。

monoio 0.2.4 实测的 feature 表也说明了它的退路：`default = ["async-cancel", "bytes", "iouring", "legacy", "macros", "utils"]`，其中 `iouring` 依赖 `io-uring`、`legacy` 依赖 `mio`、`poll-io` 依赖 `tokio` + `mio`，另有 `tokio-compat` 走 tokio。也就是说它并非只有 io_uring 一条路，但 io_uring 才是它的设计中心。

## HTTP and Web: axum, tower, hyper

这一层是 Rust 生态里分层最清晰的一段，三层各自独立可用：

```text
hyper  1.12.0   HTTP/1.1 + HTTP/2 协议实现（连接管理、编解码）
  ↑
tower   0.5.3   Service / Layer 抽象：与协议无关的服务与中间件组合子
  ↑
axum    0.8.9   路由 + extractor：把 Service 的组合包装成人类可写的 API
```

### Service Is the Load-Bearing Abstraction

```rust
pub trait Service<Request> {
    type Response;
    type Error;
    type Future: Future<Output = Result<Self::Response, Self::Error>>;
    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>>;
    fn call(&mut self, req: Request) -> Self::Future;
}

pub trait Layer<S> {
    type Service;
    fn layer(&self, inner: S) -> Self::Service;
}
```

关键在两点：

- **`poll_ready` 把背压（backpressure）做进了 trait**。调用 `call` 之前必须先 poll 到 `Ready`，所以「限流」「并发上限」「熔断」这类中间件有统一的落点，不必每个框架各自发明。
- **`Layer<S> -> S` 让中间件是纯组合子**。`Layer` 不认识 HTTP，它只认识「包一个 Service 得到另一个 Service」。所以同一个 `Layer` 既能包 HTTP 服务，也能包 gRPC 服务或任何自定义请求类型。

代价也得说清楚：`call` 的返回类型是**关联类型** `Future`，所以中间件链的类型会层层嵌套，编译错误信息动辄几十行；而且因为 `Service` 的 `call` 不是 `async fn`，写中间件时要手写 future 状态机或靠 `BoxFuture`。这正是 async fn in trait 稳定度问题的外溢（[Async.md](/docs/CS/Rust/Async.md) 的 "Async in Traits Today" 一节讲语言侧）。

什么时候不该选 axum：如果你只需要一个 HTTP/1 客户端或服务端、不想引入 extractor 与 tower 那层抽象，直接用 hyper 1.12.0 加 `hyper::service::service_fn` 更轻。反过来，如果你完全不想要 tower 的类型嵌套，就得接受自己写中间件栈。

### Two TLS Backends

reqwest 0.13.5（MSRV 实测 1.85.0）是客户端事实标准，内部基于 hyper 与 tower-http 的解压缩 `Layer`。它有一个容易踩的默认：

```text
reqwest 0.13.5 default features（实测）: ["default-tls", "charset", "http2", "system-proxy"]
```

**默认 TLS 后端是系统库（native-tls），不是 rustls**。要 rustls 必须 `default-features = false` 再显式开 `rustls-tls`。这两条路线的差别是实质性的：

| | rustls 0.23.45 | native-tls / openssl |
| :-- | :-- | :-- |
| 实现语言 | 纯 Rust，无 C 依赖 | 绑定系统 OpenSSL / Security.framework / Schannel |
| 交叉编译 | 简单，不需要为目标平台准备 OpenSSL | 痛苦，常靠 `vendored` feature 源码编译 OpenSSL |
| 根证书来源 | 默认走 webpki-roots（内置）；要系统证书需 `rustls-native-certs` | 直接用系统证书库 |
| 合规 | 无 FIPS 认证路径 | 可用系统 FIPS 模块，合规场景常是硬要求 |
| 默认 crypto provider | 实测 default features 含 `aws_lc_rs`，即默认后端是 aws-lc-rs | 由系统库决定 |

所以「rustls 更好」是错的，正确说法是：**rustls 解决依赖与交叉编译问题，系统 TLS 解决合规与证书信任链问题**。要合规就别硬换 rustls。

## Serialization

serde 1.0.229（MSRV 实测 1.56）是事实标准，它的设计是一个三层拆分：`serde` 定义 trait 与数据模型，`serde_derive` 提供 derive 宏，格式由独立 crate 实现（`serde_json` 1.0.151、`postcard` 1.1.3、`bincode` 3.0.0 等）。这个拆分是一个 crate 能被全生态复用的前提——换个格式不用改数据模型。

### The Compile-Time Cost of derive (Measured)

derive 不是「零成本」：它为每个字段生成写死的 `Serialize` / `Deserialize` 实现，序列化一个 struct 就会单态化出一份代码（[compile.md](/docs/CS/Rust/compile.md) 讲单态化机制）。实测：60 个四字段 struct（`String` / `i64` / `Vec<f64>` / `Option<u32>`），同一 crate 的增量编译时间：

| 变体 | 增量编译（3 次，`/usr/bin/time -p` 的 real） |
| :-- | :-- |
| 无 derive | 0.07s / 0.06s / 0.07s |
| 双向 derive（`Serialize` + `Deserialize`） | 0.23s / 0.29s（首次全量 5.96s 含 serde 自身编译） |

即约 **3~4 倍**，每个 struct 约 3 ms。这不是「serde 慢」，而是**把类型级信息在编译期展开成代码**这件事本身的成本，任何 derive 密集的宏都一样。缓解手段是把 derive 集中在少数 crate、避免把 derive 类型散布在被大量 crate 依赖的底层模块里。

### Picking a Wire Format

| 格式 | 版本（实测） | 特点 | 什么时候选 |
| :-- | :-- | :-- | :-- |
| serde_json | 1.0.151 | 文本、人类可读、体积大、解析慢 | 配置、对外 API、调试 |
| bincode | 3.0.0（MSRV 1.85.0） | 紧凑二进制、定长编码 | 受信两端、同构 Rust 系统 |
| postcard | 1.1.3 | `no_std` 友好、varint、无 schema | 嵌入式、带宽受限链路 |
| rkyv | 0.8.18 | 零拷贝反序列化 | 大对象、只读访问、启动延迟敏感 |

### rkyv and zerocopy Solve Different Problems

两者都号称「零拷贝」，但做的事不同，混用会出错：

- **rkyv** 是「换个类型读」：它定义了一套归档布局，`Archived<T>` 与 `T` 是**不同的类型**，反序列化只做校验（默认 `bytecheck`）并把指针指向归档内存，不构造 Rust 值。代价是你操作的是 `Archived<T>` 这套镜像 API。
- **zerocopy** 是「同一类型直接读」：它把「这个 Rust 类型可以安全地按字节解释」变成 derive 出来的契约，`T` 还是那个 `T`，只是允许从 `&[u8]` 直接得到 `&T`。

选型判据：**你能接受读写 `Archived<T>` 吗**？能就 rkyv（还有归档格式稳定与版本演进问题要考虑）；不能，只是想省掉一次 `transmute`，就 zerocopy。

## Error Handling: thiserror versus anyhow

库与应用在这里分道扬镳，判据只有一条：**错误是否是你 API 契约的一部分**。

| | thiserror 2.0.21 | anyhow 1.0.104 |
| :-- | :-- | :-- |
| 定位 | 库：定义具体错误类型 | 应用：擦除错误类型 |
| 生成物 | 每个变体的 `Display`、`source()`、`From` | 无（你手写 `anyhow!` / `?`） |
| 调用方能否 `match` | 能，变体是公开的 | 不能，只能 `downcast_ref::<T>()` |
| 代价 | derive 编译时间（同上节） | `Error` 是胖指针 + 一次堆分配；丢失结构化信息 |

一个库如果返回 `anyhow::Error`，调用方就**无法**在编译期知道它可能失败的原因，只能 downcast——等于把编译期契约降级成运行时约定。反过来，一个应用如果用 thiserror 定义几十个错误枚举，往往是在为不会有人 match 的错误付建模成本。

`Error` trait 本体、`?` 的展开、`From` 转换礼节、panic 与 `catch_unwind` 见 [Error_Handling.md](/docs/CS/Rust/Error_Handling.md)，本篇只讲这两个库的选型与代价。

## Concurrency and Parallelism

std 提供 `Mutex` / `RwLock` / `Condvar` / channel / `Atomic*`（[Concurrency.md](/docs/CS/Rust/Concurrency.md) 讲这些原语与 `Send` / `Sync`），生态补齐 std 没做的部分：

| crate | 版本（实测） | 补什么 | 什么时候不该选 |
| :-- | :-- | :-- | :-- |
| crossbeam | 0.8.5（MSRV 1.61） | scope 线程、MPMC channel、epoch 内存回收、`AtomicCell` | 只需要 std channel 时 |
| rayon | 1.12.0 | 数据并行：`par_iter`、分治、`join` | **IO 并发不要用** |
| parking_lot | 0.12.5 | 更小更快的锁、无 poisoning、可升级读锁 | 需要 poisoning 语义时 |
| dashmap | 6.2.1 | 分片并发 map，`&self` 即可写 | 需要迭代一致性快照时 |

**rayon 的边界最容易搞错**：它是数据并行库，工作窃取线程池的线程数默认等于 CPU 核数，任务是 CPU 密集的分块计算。拿它跑 IO 会把线程池占满、阻塞后续计算——IO 并发该用异步运行时，不是 rayon。而 `par_iter` 通常只需改一处的理由，是 `ParallelIterator` 与 std 的 `Iterator` 方法名一一对应；这套同形设计的三条约束与 `par_bridge` 的代价见 [Iterator](/docs/CS/Rust/Iterator.md)。

**parking_lot 与 std 锁的实质差别**不是「更快」这么笼统，而是三点：std 的 `Mutex` 有 poisoning（持有锁的线程 panic 后锁被标记，后续 `lock()` 返回 `Err`），parking_lot 没有这个语义，因此 `lock()` 直接返回 guard 而非 `Result`；parking_lot 的表示更紧凑（无竞争路径就是一个原子字）；它的 `RwLock` 提供 `upgradable_read`，std 没有。

**dashmap 的代价**：分片意味着你拿不到全表的一致性快照，`iter()` 看到的是各分片在不同时刻的状态；而且分片数固定后，热点 key 仍会退化成单点竞争。

## Observability: tracing and log

`log` 0.4.34 是**门面（facade）**：五个宏加一个 `Log` trait，由具体 logger 实现（env_logger 等）接收。它没有 span 概念，一条日志就是一个扁平记录。

`tracing` 0.1.44 补的是**因果结构**：span 有进入/退出与父子关系，事件带结构化字段，由 `Subscriber` 决定怎么渲染。这是分布式追踪与异步程序（一个 future 跨多个 await 点）真正需要的东西——异步代码里「当前调用栈」这个概念本身就不成立，靠 span 才能把因果关系说清楚。

两者**可以共存**，不需要二选一：`tracing` 的 `log` feature 让它把自身事件转发给 `log`（相当于给老的 logger 加一层），反向桥接由 `tracing-log` 0.2.0 提供。所以存量代码用 `log`、新代码用 `tracing` 是可行路径。

代价：`tracing` 的宏展开与字段构造在极热路径上有开销，靠静态级别过滤（`target` + `max_level` 或手写 `if tracing::enabled!(...)`）规避。

## Zero-Cost Byte Handling

**zerocopy 0.8.61**（MSRV 实测 1.56.0）把「这个类型可以按任意字节解释」从注释变成**编译器可检查的契约**：

```rust
#[derive(FromBytes, AsBytes, Unaligned)]
#[repr(C)]
struct Header { magic: u32, len: u32 }
```

derive 会检查 repr、padding、字段类型是否都满足位模式合法性。它的意义是**替代手写 `transmute`**：手写的那份 unsafe 依赖「我记得保持两边布局一致」，而 derive 出来的那份把这个不变量交给编译器。注意 `FromBytes` 要求**所有**位模式都是合法值，有 padding 或有非法枚举值的类型只能 derive `TryFromBytes`（运行时校验）。布局规则本身见 [Memory_Layout.md](/docs/CS/Rust/Memory_Layout.md)。

**bytes 1.12.1** 解决的是另一半问题：`Bytes` 是引用计数的字节切片，`split_to` / `split_off` 是 O(1) 且不拷贝。协议解析时反复 `copy_from_slice` 是常见的隐性开销来源，用 `Bytes` 可以把「把首部切掉、把剩下的交给下一层」变成无拷贝操作。

顺带一条生态现状：同类的 `bytemuck` 仍在服役，但零拷贝契约的生态重心已经移向 zerocopy（它把「安全」做成了 derive 出来的 trait，而不是一堆 `unsafe fn` 的约定）。

## Data Structures

| crate | 版本（实测） | 提供什么 | 代价 |
| :-- | :-- | :-- | :-- |
| indexmap | 2.14.2 | 保持插入序的 map / set | 多一份索引数组的内存；`swap_remove` O(1) 但打乱顺序，`shift_remove` 保序但 O(n) |
| itertools | 0.15.0 | 迭代器适配器补充：`chunk_by`、`group_by`、`merge_join_by`、`izip!` | 适配器链变长后类型名变长 |
| smallvec | 1.16.2（最新稳定版；`2.0.0-beta.2` 是预发布） | 小向量栈上内联，避免小容量场景的堆分配 | 按值传递时拷贝整个内联数组 |

`indexmap` 常被误当成「有序的 HashMap」：它保持的是**插入序**，不是按键排序（后者是 `BTreeMap`）。std 容器的容量契约与陷阱见 [Collections.md](/docs/CS/Rust/Collections.md)。

## Databases: sqlx and the Cost of Compile-Time Checking

sqlx 0.9.0 的核心卖点是**编译期查询校验**：`query!()` 宏在编译期连上数据库，把 SQL 发给它取回 schema，校验 SQL 合法性并推出返回列的具体 Rust 类型；SQL 写错是**编译错误**，不是运行时 panic。

代价有两条，都值得单独讲：

1. **编译期必须能访问数据库**。CI 要么提供数据库实例，要么先 `cargo sqlx prepare` 生成 `.sqlx` 离线目录并把它提交进仓库。这意味着构建不再是纯粹的「源码进、二进制出」。
2. **MSRV 被推得很高**：实测 sqlx 0.9.0 的 `rust-version` 是 **1.94.0**。作为对照，tokio 1.53.2 是 1.71，serde 1.0.229 是 1.56，zerocopy 0.8.61 是 1.56.0。

第 2 条是一个很干净的**代价样本**：编译期能力越强，越依赖新编译器的特性与过程宏接口，MSRV 就越高。而这会经由 `resolver = "3"` 的 MSRV-aware resolver 反向约束你的整个依赖图——你的项目一旦依赖 sqlx，你自己的 `rust-version` 下限就被抬到 1.94.0。版本三轴如何互相引用，见 [Edition_MSRV.md](/docs/CS/Rust/Edition_MSRV.md)。

## FFI and Bindings

| crate | 版本（实测） | MSRV | 用途 |
| :-- | :-- | :-- | :-- |
| pyo3 | 0.29.3 | 1.83 | 用 Rust 写 Python 扩展模块（原生 ABI，非 CPython C API 手写） |
| wasm-bindgen | 0.2.129 | — | Rust ↔ JS 的高层绑定，生成 JS 胶水代码 |

这条链路和 `bindgen` / `cxx` 的共同点是：**把「手工维持两边的布局、调用约定与所有权契约一致」变成生成代码**（[Unsafe_FFI.md](/docs/CS/Rust/Unsafe_FFI.md) 讲这些契约本身）。选绑定生成器而非手写 FFI 的理由和选 zerocopy 而非手写 `transmute` 是同一个理由——把不变量从「我记得」移到「工具保证」。

## Choosing a Dependency: A Checklist

选型不是「看 star 数」，下面是可机检的七项：

1. **MSRV**：读索引的 `rust_version` 字段，不要看 README 里写的。
   ```bash
   curl -s "https://index.crates.io/se/rd/serde" | tail -1
   ```
2. **维护活跃度**：最后一次发布时间 + issue/PR 响应 + **是否有 RUSTSEC 公告**。`cargo audit` 直接给出答案；async-std 就是这条的反面样本。
3. **依赖树宽度**：`cargo tree`（前面实测：两个直接依赖 → 121 行 / 55 个 crate）。也看 `cargo tree -d` 找重复版本。
4. **unsafe 代码比例**：`cargo geiger` 统计 `unsafe` 块/函数的行数占比。零拷贝、io_uring、FFI 类 crate 天然高，这本身不是问题，但要知道自己吃进了多大的审计面。
5. **License 与来源**：`cargo deny` 按策略拒绝不合规 license、yanked 版本、多来源同名 crate。这几项与 `cargo audit` / `cargo geiger` 都属于工具链侧能力，见 [Tooling.md](/docs/CS/Rust/Tooling.md)。
6. **版本语义陷阱**：见下。
7. **API 稳定性**：1.x 之前的 crate（如 monoio 0.2.4）接口可能随 minor 变。

### In 0.x, a Minor Bump Is Breaking

这是 Rust 生态最常见、代价也最高的一条坑。Cargo 的 caret 需求（`serde = "1"` 等价于 `^1`）**不是**简单地「锁住第一段」，而是「锁住最左侧的非零段」：

| 写法 | 实际等价范围 | 含义 |
| :-- | :-- | :-- |
| `^1.2.3` | `>=1.2.3, <2.0.0` | 1.x 内 minor 可自动升 |
| `^0.2.3` | `>=0.2.3, <0.3.0` | **0.x 里 minor 就是 major**，0.2→0.3 不会自动跨 |
| `^0.0.3` | `>=0.0.3, <0.0.4` | 连 patch 都锁死 |

后果有两层：

- **升级是手动的**。`monoio = "0.2"` 永远拿不到 0.3，作者把 0.2 升到 0.3 是 breaking change，但版本号看起来只是「minor」。用户必须自己改 `Cargo.toml`。
- **同一 crate 的两个不兼容版本会同时出现在依赖树里**。A 依赖 `rkyv 0.7`、B 依赖 `rkyv 0.8`，Cargo 会同时编两份，且 `rkyv::Archived<T>` 在两个版本里是**不同的类型**，两个库之间传这个值会类型不匹配。`cargo tree -d` 是发现这类重复的第一工具。

对比：Go 用语义导入版本（`/v2` 写进 import 路径），把「不兼容」编码进命名空间，于是两个大版本可以共存且类型清晰区分；Maven 用「nearest wins」直接选一个版本（可能选到不兼容的那个）；Rust 会诚实地编两份，把冲突暴露成类型错误。三种策略各有代价，但 Rust 这条的**具体代价是编译时间与二进制体积**。

## Cross-Ecosystem Comparison

| 维度 | Rust / crates.io | Python / PyPI | Java / Maven | Go modules |
| :-- | :-- | :-- | :-- | :-- |
| registry 中心化 | 唯一默认 registry（可用配置替换源） | PyPI 事实默认，多源并存 | Maven Central 事实默认，企业常自建私服 | **无中心 registry**，按 import 路径直接从 VCS 拉，官方只提供代理与校验 |
| 分发物 | **源码**（`.crate`），本机编译 | sdist 源码 + 预编译 wheel | 预编译 jar | 源码，本机编译 |
| lockfile | `Cargo.lock`：二进制项目提交，库默认不提交 | 无官方 lockfile（靠 pip-tools / uv 等各自实现） | 无（靠版本固定 + BOM） | `go.mod` 记版本 + `go.sum` 记校验和 |
| 版本选择 | 选满足约束的最新版；`resolver = "3"` 带 MSRV 感知 | 无解算保证，常靠虚拟环境隔离 | 最近优先，冲突时 nearest wins | **MVS（最小版本选择）**，倾向选旧 |
| 破坏性变更约定 | semver + crate 级 edition 双开关 | 无强制约定 | 无强制约定 | 语义导入版本（`/v2` 路径） |
| 命名空间 | 扁平、先到先得 | 扁平、先到先得 | `groupId` 分层 | 域名 / 仓库路径即命名空间 |
| 供应链治理 | `cargo audit` + RUSTSEC；`cargo deny` 管 license 与来源 | pip-audit / Safety | OWASP dependency-check | `govulncheck` |

最能拉开差别的是**分发物**这一行：Rust 与 Go 分发源码，所以依赖树宽度等于编译成本，且跨平台交叉编译天然可行；Python 与 Java 分发二进制，安装快但平台适配是打包者的责任。以及**破坏性变更约定**这一行：只有 Rust 和 Go 有机制级的答案，Python 与 Java 靠社区默契。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Performance](/docs/CS/Rust/Performance.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [Macros](/docs/CS/Rust/Macros.md)

## References

- [crates.io — Rust Package Registry](https://crates.io/)
- [The Cargo Book — Registries](https://doc.rust-lang.org/cargo/reference/registries.html)
- [The Cargo Book — Registry Index (sparse)](https://doc.rust-lang.org/cargo/reference/registry-index.html)
- [The Cargo Book — Specifying Dependencies (caret requirements)](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html)
- [The Cargo Book — Dependency Resolution / MSRV-aware resolver](https://doc.rust-lang.org/cargo/reference/resolver.html)
- [The Cargo Book — Publishing / yanked crates](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [RustSec Advisory Database](https://rustsec.org/)
- [cargo-audit](https://github.com/rustsec/rustsec/tree/main/cargo-audit)
- [cargo-deny](https://github.com/EmbarkStudios/cargo-deny)
- [cargo-geiger](https://github.com/geiger-rs/cargo-geiger)
- [tokio 1.53.2 documentation](https://docs.rs/tokio/1.53.2/tokio/)
- [tower 0.5.3 documentation](https://docs.rs/tower/0.5.3/tower/)
- [hyper 1.12.0 documentation](https://docs.rs/hyper/1.12.0/hyper/)
- [axum 0.8.9 documentation](https://docs.rs/axum/0.8.9/axum/)
- [reqwest 0.13.5 documentation](https://docs.rs/reqwest/0.13.5/reqwest/)
- [rustls](https://docs.rs/rustls/latest/rustls/)
- [serde 1.0.229 documentation](https://docs.rs/serde/1.0.229/serde/)
- [rkyv 0.8.18 documentation](https://docs.rs/rkyv/0.8.18/rkyv/)
- [zerocopy 0.8.61 documentation](https://docs.rs/zerocopy/0.8.61/zerocopy/)
- [bytes 1.12.1 documentation](https://docs.rs/bytes/1.12.1/bytes/)
- [thiserror 2.0.21 documentation](https://docs.rs/thiserror/2.0.21/thiserror/)
- [anyhow 1.0.104 documentation](https://docs.rs/anyhow/1.0.104/anyhow/)
- [parking_lot 0.12.5 documentation](https://docs.rs/parking_lot/0.12.5/parking_lot/)
- [rayon 1.12.0 documentation](https://docs.rs/rayon/1.12.0/rayon/)
- [dashmap 6.2.1 documentation](https://docs.rs/dashmap/6.2.1/dashmap/)
- [tracing 0.1.44 documentation](https://docs.rs/tracing/0.1.44/tracing/)
- [indexmap 2.14.2 documentation](https://docs.rs/indexmap/2.14.2/indexmap/)
- [sqlx 0.9.0 documentation](https://docs.rs/sqlx/0.9.0/sqlx/)
- [pyo3 0.29.3 documentation](https://docs.rs/pyo3/0.29.3/pyo3/)
- [monoio 0.2.4 documentation](https://docs.rs/monoio/0.2.4/monoio/)
- [glommio 0.9.0 documentation](https://docs.rs/glommio/0.9.0/glommio/)
- [async-std on crates.io（含 unmaintained 公告 RUSTSEC-2025-0052）](https://crates.io/crates/async-std)
