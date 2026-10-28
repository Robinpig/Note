## Introduction

WASM 是最容易写错的一节，因为「WASM」不是一个目标。Rust 编译到 WebAssembly 有两条**互不相同**的路径，混淆它们是绝大多数 wasm 文章出错的根源：一条面向浏览器，宿主是 JS 引擎；一条面向服务器，宿主是 WASI 运行时。选错的直接后果不是"跑不起来"，而是"为什么连个文件都读不了""为什么 `std::thread` 不存在"这类定位困难的困惑——因为两个目标提供的根本不是同一个世界。

本篇先给目标谱系（Rust 侧的 wasm triple 已在五个以上，它们在「有没有 std、宿主要求什么 syscall、输出 core module 还是 component」上完全不同），再讲 `wasm-bindgen` 这个**不走 C ABI** 的互操作层，最后是体积优化与选型。

与 no_std 的关系（[No_Std](/docs/CS/Rust/No_Std.md) 只引用不重述）：**只有 `wasm32v1-none` 是必须 no_std 的**，其余目标都有 std，只是 OS 类 API 是失败桩或走 WASI syscall。自定义 target JSON 与 `-Z build-std` 的关系也见 [No_Std](/docs/CS/Rust/No_Std.md)。

> [!NOTE]
> 本机未安装任何 wasm target，本篇目标能力描述**全部据 rustc book 的 platform support 页面与 [wasi.dev](http://wasi.dev/) 等官方来源**，未在本机实测（2026-10 核实）。不写具体运行时版本号——这个生态的版本节拍太快，写下来即过期。

## The Target Spectrum

| 目标 | std | 宿主模型 | 输出 | 典型用途 |
| :--- | :--- | :--- | :--- | :--- |
| `wasm32-unknown-unknown` | ✓（大量 API 不可用） | 无 WASI，宿主是 JS 引擎 | core module | 浏览器，配 wasm-bindgen |
| `wasm32-wasip1` | ✓ | WASI preview 1 syscall | core module | WASI 运行时（Wasmtime、wasmtime-cli） |
| `wasm32-wasip1-threads` | ✓ | WASIp1 + 线程 | core module | 需要线程的 WASI 场景 |
| `wasm32-wasip2` | ✓（原文 "supports std fully"） | Component Model（WASI 0.2） | **component** | Wasmtime、组件化部署 |
| `wasm32-wasip3` | ✓（std 仍面向 0.2） | WASI 0.3，原生异步 | component | **Tier 3、仅 nightly**；`wasip3` crate 提供 0.3 绑定 |
| `wasm32v1-none` | **✗（只有 `core` + `alloc`）** | 无：不 import 任何宿主函数 | core module | 最小 wasm、无宿主环境 |

三条关键区分，别混：

1. **`wasm32-unknown-unknown` 不是 no_std**。它链的是真 `std`，只是 `std` 里依赖 OS 的部分被做成「返回错误的桩」——rustc book 原文：「`println!` does nothing, `std::fs` always return errors, `std::thread::spawn` will panic」。所以你能用 `String` / `Vec`，甚至 `HashMap`（该目标的 `RandomState` 不随机化，是被文档点名的特例）。no_std 在这里是**可选**的体积优化。
2. **`wasm32v1-none` 才是「必须 no_std」的那个**。原文明确「does not support std, only core and alloc」，理由也直白：既然什么都不 import，任何用 OS 设施的 std 部分到最后都得做成失败桩，而 `unknown-unknown` 上那套桩的体验「was deemed not something worth repeating」。
3. **`wasip1` / `wasip2` 有完整 std**，因为它们假定宿主提供 WASI syscall。要写 WASI CLI 程序（`wasmtime foo.wasm`）用这两个，不要用 `unknown-unknown`。

选哪条只看一个问题：**谁来提供系统能力**。浏览器里答案是"通过 JS 绑定按能力逐个导入"；服务器上答案是"WASI 按 capability 授权"。前者的边界是 `wasm-bindgen`，后者的边界是 WIT 接口。

Tier 等级的含义（rustc book 的 platform support 分级）决定了你能对 CI 里的 nightly 报错有多敏感：tier 1/2 目标保证每次发布都能编过，更低 tier 的目标可能阶段性损坏。wasm 目标长期在 tier 2，属于「能用于生产但 nightly 兼容性要自己盯」；`wasip3` 目前是 tier 3 且只存在于 nightly。

## Why wasm-bindgen Exists

这是本篇最重要的一节：**为什么不能直接导出 Rust 类型**，也就是为什么浏览器这条路不走 C ABI。

答案在 wasm 的数字类型系统。core wasm 只有 `i32` / `i64` / `f32` / `f64` 四种数字类型，函数签名只能由这四种组成。Rust 的 `String`、`Vec`、结构体、trait 对象，在 wasm 线性内存里是**一段字节 + 一个地址**，而 JS 侧的值活在 JS 引擎自己的堆里。`extern "C"` 那套「共享 ABI」在 wasm 上不成立：C ABI 描述的是**标量与指针的布局**，而 JS 互操作要传递的是对象、字符串、闭包和 Promise——这些东西没有 C 布局可言。

所以浏览器里的 FFI 必须有人做翻译，`wasm-bindgen` 就是这个翻译层。它实际做三件事：

1. **Rust 侧**：提供 `#[wasm_bindgen]` 属性宏，把 `#[wasm_bindgen] pub fn f(s: String) -> JsValue` 编译成「把 Rust 值写进线性内存 / 从内存读回来」的垫片，函数签名换成 wasm 数字类型。
2. **生成 JS 胶水**：构建时生成一段 JS/TS 代码，里面为每个导出函数生成 wrapper，调用时分配内存、写参数、调 wasm、读回结果、释放。**所以它生成的 wasm 不是「自包含的可执行」，而是与这段 JS 配套使用的。**
3. **描述表**：它生成一份 `__wbindgen_*` 符号的描述（导出函数签名、需要的 externref 表、要生成的 JS wrapper 清单），JS 侧的 loader 据此初始化。

结论：**浏览器场景下，跨边界传的是 JS 值，不是 C ABI 的字节**。这也解释了为什么 Rust 侧给 JS 传结构体时，`#[wasm_bindgen]` 要求你显式标注每个字段的 JS 名字（serde 的 `Serialize` + `serde-wasm-bindgen` 是另一条路，但序列化成本在边界上）。

`web-sys` / `js-sys` 是这条路上的另一半：`web-sys` 是浏览器 API（DOM、fetch、WebGL）的 Rust 绑定，`js-sys` 是 JS 内建对象（`Object`、`Array`、`Promise`）的绑定，两者都由 wasm-bindgen 的 CLI 从 WebIDL 生成。

Component Model 的 *canonical ABI* 把同一思想标准化了：WIT 类型到核心 wasm 类型的转换规则是规范的一部分，不再依赖 bindgen 的私有约定。实践上两处的纪律一致：**跨边界的函数签名越简单越好**。传 `&[u8]` 与回调是可分析的，传复杂的 `Rc<RefCell<...>>` 图则会在胶水里生成大量拷贝与提升代码——这与 C FFI 那条「布局承诺、分配器对上」的清单是两类不同的纪律。

## std on wasm32-unknown-unknown

`unknown-unknown` 有 std，但缺的不是「API 不存在」而是「API 存在但返回失败」：

| std API | 该目标上的行为 | 替代 |
| :--- | :--- | :--- |
| `println!` / `stdout` | 什么都不做 | `console.log`（`web-sys` / `wasm-bindgen`） |
| `std::fs` | 永远返回错误 | 无（浏览器无文件系统）；WASI 目标才可用 |
| `std::thread::spawn` | panic | 无；`wasm-bindgen-rayon` 只在特定宿主可用 |
| `std::time::Instant` / `SystemTime` | std 有实现，但时钟值来自**宿主注入的导入函数**（wasm-bindgen 环境下由 JS 胶水提供）；裸宿主下没有时钟，精度与单调性由宿主决定 | `js-sys::Date` 或让宿主注入 |
| `std::net` | 不存在 | `fetch`（`web-sys`）/ WebSocket |
| `HashMap` | 可用但**不随机化** | 不要依赖 `RandomState` 的随机性做安全假设 |

**没有线程**是最大的架构约束：wasm 的线程提案（shared memory + atomics）只在 `wasm32-wasip1-threads` 与开了 `+atomics,+bulk-memory` 特性的 nightly 实验里推进过；浏览器侧的 `SharedArrayBuffer` 还额外要求 COOP/COEP 响应头，这是同源策略的要求，与 Rust 无关。写 wasm 应用时先假设单线程，把并发交给 JS 侧的 Worker + 多个 wasm 实例（每实例独立线性内存，通信靠 `postMessage`）。SIMD 有 `simd128` 目标特性可用，但要用 `std::arch::wasm32` 的内部函数显式写。

工程上有几条几乎固定的纪律：

1. **panic 策略用 `abort`**。wasm 没有 unwind 的廉价实现（该目标默认就是 `-Cpanic=abort`），需要可读报错时挂 `console_error_panic_hook`。
2. **发布构建必过 `wasm-opt`**（binaryen）。同一份代码过与不过，体积差常在 30% 以上；`wasm-pack build --release` 默认会跑。
3. **`LTO` + `opt-level = "z"` 或 `"s"`**。wasm 的下载与实例化成本让体积就是性能。

产物如何被页面加载由打包侧决定：`wasm-pack` 产出 npm 包，`trunk` 直接管 `index.html` 与资源，任选其一。

## Async in the Browser

wasm 上的 async 与桌面端是同一个 `Future`，但**驱动它的不是线程池而是浏览器事件循环**：

- `wasm-bindgen-futures` 提供 `spawn_local`（把 future 交给 `queueMicrotask` 之类的机制推进）与 `JsFuture`（把 JS Promise 包成 Rust Future）。
- 没有 `Send` 要求问题：单线程意味着 `spawn_local` 不需要 `Send`，这也是 [Async_Runtime](/docs/CS/Rust/Async_Runtime.md) 里 `LocalSet` 机制在浏览器侧的天然形态。
- **阻塞是致命的**：wasm 与 JS 共享同一个线程，Rust 侧任何长时间计算（不只是阻塞 IO，也包括纯 CPU 的紧循环）都会冻结页面。`spawn_blocking` 在 wasm 上没有意义，正确解法是把大计算拆成可让出的步骤或丢给 Worker。

## Size Optimization

wasm 的体积直接决定下载与实例化时间，优化链路的每一步都能量测：

| 手段 | 原理 | 注意 |
| :--- | :--- | :--- |
| `opt-level = "z"` / `"s"` | LLVM 面向体积优化 | 与 `debug-assertions` 互斥才有明显效果 |
| `lto = true` / `"fat"` | 跨 crate 内联与死代码消除 | 编译时长代价 |
| `panic = "abort"` | 去掉 unwind 表与 formatting 路径 | wasm 上 abort 即 `unreachable` |
| `codegen-units = 1` | 给 LTO 最大空间 | 编译明显变慢 |
| `debug = false` / `strip = "symbols"` | 去调试信息与符号 | dwarf 段常占 30%+ 体积 |
| `wasm-opt`（binaryen） | wasm 级死代码消除、合并、重排 | `wasm-pack` 默认跑 |
| `wasm-snip` | 把未使用的导出/函数替换为 `unreachable` | 常与 wasm-opt 组合 |

经验量级（社区常见数据，非本机实测）：一个 hello-world 从默认 profile 到全链路优化后可以从数百 KB 降到几十 KB。顺序上先保证 `panic=abort` + `strip`（收益最大且无损语义），再上 `lto=fat` + `opt-level=z`，最后才是 binaryen 那两级。

## WASI and the Component Model

WASI 把「文件 / 网络 / 时钟」变成**宿主提供的 capability 导入**，wasm 模块声明要哪些导入、宿主决定给哪些。三个时代：

- **WASI preview 1**（`wasm32-wasip1`）：POSIX 风格的 syscall 集（`fd_read`、`path_open`……），与 C 程序的心智模型接近，输出 core module。文件访问靠 **preopen**：宿主显式把某个目录授权给实例，没有 ambient authority。问题是接口是数字编号而非类型，跨语言互操作靠猜。Wasmtime、wasmtime-cli、WasmEdge 都跑它。
- **WASI 0.2 / Component Model**（`wasm32-wasip2`）：用 **WIT**（WebAssembly Interface Types）描述接口，单元从 *module* 变成 *component*，跨语言链接按 WIT 类型检查，能力按 *world* 声明（如 `wasi:cli/command`、`wasi:http/proxy`）。"组件只能做它的 world 导入允许的事"从设计上取代了 preopen 式授权。工具链是 `cargo component`。
- **WASI 0.3**（`wasm32-wasip3`）：引入原生异步（`stream` / `future` / 订阅），Rust 侧目标是 **tier 3 且仅 nightly**，`wasip3` crate 提供绑定并且可以从稳定的 `wasip2` 目标上使用——但上游建议 crate 与目标对齐，且 `wasip2` 上的 std 仍是 0.2。**务实选择仍是 0.2**：0.3 的生态覆盖还没铺开。

Component Model 的意义是「组合的正确性」：preview 1 的世界里两个 wasm 模块互访只能靠共享内存约定，component 的世界里接口是带类型的、由 runtime 校验的。对 Rust 使用者的直接影响：**写 component 时你的 API 面要用 WIT 描述，而不是 `extern "C"`**。存量 core module 升级成组件的路径是 `wasm-tools component new` 加 0.1→0.2 适配器，这是 C/C++ 与多数工具链当前的现实路线。

运行时分三层：`wasmtime` 是参考实现；Fermyon Spin 面向 HTTP 组件；wasmCloud 把组件当分布式 actor 编排。三者的共同卖点不是吞吐而是**启动时间与隔离粒度**——毫秒级冷启动、按组件授权，这正是"serverless / 边缘"场景选它的理由。

## Embedding wasm Runtimes

反方向——把 wasm 运行时嵌进 Rust 程序——是另一类需求（插件系统、沙箱执行、serverless 函数运行时）。主流选择：

| runtime | 定位 | 备注 |
| :--- | :--- | :--- |
| `wasmtime` | Bytecode Alliance 的参考实现 | JIT（Cranelift），WASI 支持最全 |
| `wasmi` | 纯解释器 | 无 JIT 依赖，适合受限环境与确定性执行 |
| `wws`（wasmedge） | 云原生场景 | AOT 编译加速 |
| `wasmer` | 与 wasmtime 并列的成熟实现 | 多后端（Cranelift / LLVM / Singlepass） |

嵌入时最常遇到的三件事：**fuel / epoch 限制**（防止恶意模块死循环）、**内存限制**（`Store` 级别的 memory cap）、以及 **WASI capability 白名单**（只给文件系统的一个子目录，用 `preview1` 的 `--dir` 或 component 的 capability 声明控制）。

## What Wasm Does Not Buy

- **它不是"接近原生的速度"**：计算密集循环仍显著慢于同架构原生代码，差距来自边界检查、缺少部分原生优化等。赢的是一次编译处处运行与**启动时间**。
- **它不是新的安全边界本身**：沙箱强度取决于宿主的实现与权限配置，Rust 的内存安全保证只覆盖 guest 内部。
- **调试与可观测性是短板**：panic 信息、source map、profiling 都依赖工具链成熟度，出问题时的第一现场常比原生稀薄。

选型判据因此很窄：**分发与启动成本主导**（边缘函数、插件、前端重计算）时选 wasm；**吞吐与延迟主导**时不选。

## WASM Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | 用 `extern "C"` 导给 JS | JS 侧看到的是裸数字/指针，没有包装 | 用 `#[wasm_bindgen]`；`extern "C"` 在 wasm32 自 1.89.0 起才成为标准 ABI |
| 2 | 选了 `unknown-unknown` 却想要文件 | `std::fs` 永远失败 | 换 `wasip1` / `wasip2` |
| 3 | 选了 `wasip1` 却想跑在浏览器 | 找不到 WASI 导入 | 浏览器必须 `unknown-unknown` + wasm-bindgen |
| 4 | 主线程跑大计算 | 页面冻结 | 拆步骤让出，或 Worker + 多实例 |
| 5 | 依赖 `std::time::Instant` | 时钟来自宿主导入，裸宿主下没有时钟 | `js-sys::Date` 或宿主注入 |
| 6 | 忘了 `strip` / `panic=abort` | 体积数倍于预期 | 先做零语义损失的优化 |
| 7 | 依赖 `RandomState` 随机性 | 哈希值可预测 | 该目标不随机化，安全相关哈希自己实现 |
| 8 | 把 wasm 当「跨平台二进制」分发 | 换了宿主全废 | wasm 的 ABI 是宿主相关的（JS vs WASI vs 嵌入式 runtime） |

## Links

- [Embedded](/docs/CS/Rust/Embedded.md)
- [FFI](/docs/CS/Rust/FFI.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)
- [性能优化](/docs/CS/Rust/Performance.md)
- [Tooling：rustup 与工具链](/docs/CS/Rust/Tooling.md)
- [Cargo：manifest 与构建图](/docs/CS/Rust/Cargo.md)

## References

1. [The rustc book — Platform Support](https://doc.rust-lang.org/rustc/platform-support.html)
2. [The rustc book — wasm32-unknown-unknown](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html)
3. [The rustc book — wasm32-wasip1](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip1.html)
4. [The rustc book — wasm32-wasip2](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip2.html)
5. [The rustc book — wasm32v1-none](https://doc.rust-lang.org/rustc/platform-support/wasm32v1-none.html)
6. [The wasm-bindgen Guide](https://rustwasm.github.io/docs/wasm-bindgen/)
7. [WASI — Languages and Targets](http://wasi.dev/languages)
8. [rustc target spec: wasm32-wasip2](https://doc.rust-lang.org/beta/nightly-rustc/src/rustc_target/spec/targets/wasm32_wasip2.rs.html)
9. [The Rust and WebAssembly Book](https://rustwasm.github.io/docs/book/)
10. [Component Model Documentation](https://component-model.bytecodealliance.org/)
