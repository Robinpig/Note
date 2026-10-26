## Introduction

Rust 编译到 WebAssembly 有两条**互不相同**的路径，混淆它们是绝大多数 wasm 文章出错的根源：一条面向浏览器，宿主是 JS 引擎；一条面向服务器，宿主是 WASI 运行时。选错的直接后果不是"跑不起来"，而是"为什么连个文件都读不了""为什么 `std::thread` 不存在"这类定位困难的困惑——因为两个目标提供的根本不是同一个世界。

本页把这两条路径各自的地形讲清：目标三元组、宿主提供什么、Rust 侧少了什么、以及为什么浏览器这条路**不走 C ABI**（[Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md) 的 FFI 对照表把这一行指向了本页）。

> [!NOTE]
> 本页版本事实按 **2026-10** 核实：wasm 目标分层与 WASI 里程碑状态以 [wasi.dev](http://wasi.dev/) 与 rustc 目标规格（`rustc_target/spec/targets/wasm32_wasip2.rs`，tier 2）为准；不写具体运行时版本号——这个生态的版本节拍太快，写下来即过期。

## Two Targets, Two Worlds

| 目标三元组 | 宿主 | std 可用性 | 典型用途 |
| :--- | :--- | :--- | :--- |
| `wasm32-unknown-unknown` | 浏览器 JS 引擎（或 Node） | 部分：无线程、网络、文件系统、时钟粒度受限 | 前端重计算、插件、Office/Canvas 处理 |
| `wasm32-wasip1` | WASI Preview 1 运行时（wasmtime 等） | 较完整：文件（preopen）、时钟、环境变量、随机数；**无异步** | 命令行工具、边缘函数 |
| `wasm32-wasip2` | WASI 0.2 组件运行时 | 完整，但标准库仍面向 WASI 0.2 | 组件化服务、多语言互操作 |
| `wasm32-wasip3` | WASI 0.3 运行时 | **Tier 3，仅 nightly**；`wasip3` crate 提供 0.3 绑定 | 原生异步（stream/future）组件 |

判断用哪条只看一个问题：**谁来提供系统能力**。浏览器里答案是"通过 JS 绑定按能力逐个导入"；服务器上答案是"WASI 按 capability 授权"。前者的边界是 `wasm-bindgen`，后者的边界是 WIT 接口。

## The Browser Side: unknown-unknown

这个目标的 `unknown` 是双重的：未知 OS、未知 环境。你的代码运行在一个沙箱里，能碰的东西只有：

- **线性内存**（可增长）与 JS 互操作；
- **导入的 JS 函数**——`web-sys` 把所有 Web API 绑成 Rust 调用，`js-sys` 覆盖 ES 内置对象；
- **受限的时钟**（`Instant` 可用但精度受限）与 `console` 输出。

因此以下能力**不存在**，不是"要额外配置"：`std::thread`、`std::net`、文件系统、进程。多线程要另走一路：`SharedArrayBuffer` + `wasm-bindgen-rayon`，且页面必须带 `COOP` / `COEP` 响应头才拿得到 `SharedArrayBuffer`——这是浏览器同源策略的要求，与 Rust 无关。SIMD 有 `simd128` 目标特性可用，但要用 `std::arch::wasm32` 的内部函数显式写。

工程上有几条几乎固定的纪律：

1. **panic 策略用 `abort`**。wasm 没有 unwind 的廉价实现，`panic = "abort"` 能显著缩小产物；需要可读报错时挂 `console_error_panic_hook`。
2. **发布构建必过 `wasm-opt`**（binaryen）。同一份代码过与不过，体积差常在 30% 以上；`wasm-pack build --release` 默认会跑。
3. **`LTO` + `opt-level = "z"` 或 `"s"`**。wasm 的下载与实例化成本让体积就是性能。

产物如何被页面加载由打包侧决定：`wasm-pack` 产出 npm 包，`trunk` 直接管 `index.html` 与资源，任选其一。

## The Server Side: WASI and the Component Model

WASI 的历史分两章，分界线是 **Preview 2（WASI 0.2）**：

- **Preview 1** 是一套 POSIX 风格的 syscall 式导入（`fd_read`、`path_open`……）。文件访问靠 **preopen**：宿主显式把某个目录授权给实例，没有 ambient authority。问题是没有异步、接口是数字编号而非类型，跨语言互操作靠猜。
- **Preview 2 起重建在 Component Model 之上**：单元从 *module* 变成 *component*，导入导出用 **WIT**（WebAssembly Interface Types）描述成带类型的接口，跨语言链接按 WIT 类型检查，能力按 *world* 声明（如 `wasi:cli/command`、`wasi:http/proxy`）。"组件只能做它的 world 导入允许的事"从设计上取代了 preopen 式授权。
- **Preview 3（WASI 0.3）** 引入原生异步（`stream` / `future` / 订阅），Rust 侧 `wasm32-wasip3` 是 **Tier 3 nightly-only**，`wasip3` crate 提供绑定且可以从稳定的 `wasip2` 目标上使用——但上游建议 crate 与目标对齐，且 `wasip2` 上的 std 仍是 0.2。**务实选择仍是 0.2**：0.3 的生态覆盖还没铺开。

存量 core module 升级成组件的路径是 `wasm-tools component new` 加 0.1→0.2 适配器，这是 C/C++ 与多数工具链当前的现实路线。运行时分三层：`wasmtime` 是参考实现；Fermyon Spin 面向 HTTP 组件；wasmCloud 把组件当分布式 actor 编排。三者的共同卖点不是吞吐而是**启动时间与隔离粒度**——毫秒级冷启动、按组件授权，这正是"serverless / 边缘"场景选它的理由。

## Why the Browser Path Does Not Use the C ABI

[Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md) 的对照表里，浏览器一行写的是"不走 C ABI，传的是 JS 值"。原因是 C ABI 描述的是**标量与指针的布局**，而 JS 互操作要传递的是对象、字符串、闭包和 Promise——这些东西没有 C 布局可言。`wasm-bindgen` 的做法是生成胶水代码，在 JS 值与线性内存表示之间双向转换，类型信息来自 Rust 侧签名（`extern "C"` 之外的 `#[wasm_bindgen]` 属性）。Component Model 的 *canonical ABI* 把同一思想标准化了：WIT 类型到核心 wasm 类型的转换规则是规范的一部分，不再依赖 bindgen 的私有约定。

实践上这意味着：**跨进浏览器边界的函数签名越简单越好**。传 `&[u8]` 与回调是可分析的，传复杂的 `Rc<RefCell<...>>` 图则会在胶水里生成大量拷贝与提升代码——这与 C FFI 那条"布局承诺、分配器对上"的清单是两类不同的纪律。

## What Wasm Does Not Buy

- **它不是"接近原生的速度"**：计算密集循环仍显著慢于同架构原生代码，JIT 后的差距来自边界检查、64 位运算模拟（wasm32 无原生 i64 之外的类型优势）与缺少部分原生优化。赢的是一次编译处处运行与**启动时间**。
- **它不是新的安全边界本身**：沙箱强度取决于宿主的实现与权限配置，Rust 的内存安全保证只覆盖 guest 内部。
- **调试与可观测性是短板**：panic 信息、source map、profiling 都依赖工具链成熟度，出问题时的第一现场常比原生稀薄。

选型判据因此很窄：**分发与启动成本主导**（边缘函数、插件、前端重计算）时选 wasm；**吞吐与延迟主导**时不选。

## Links

- [Unsafe FFI：unsafe 到底开放了什么](/docs/CS/Rust/Unsafe_FFI.md)
- [No Std：没有标准库的场景](/docs/CS/Rust/No_Std.md)
- [Tooling：rustup 与工具链](/docs/CS/Rust/Tooling.md)
- [Cargo：manifest 与构建图](/docs/CS/Rust/Cargo.md)
- [编译过程（rustc）](/docs/CS/Rust/compile.md)

## References

1. [WASI — Languages and Targets](http://wasi.dev/languages)
2. [rustc target spec: wasm32-wasip2](https://doc.rust-lang.org/beta/nightly-rustc/src/rustc_target/spec/targets/wasm32_wasip2.rs.html)
3. [The wasm-bindgen Guide](https://rustwasm.github.io/docs/wasm-bindgen/)
4. [The Rust and WebAssembly Book](https://rustwasm.github.io/docs/book/)
5. [Component Model Documentation](https://component-model.bytecodealliance.org/)
