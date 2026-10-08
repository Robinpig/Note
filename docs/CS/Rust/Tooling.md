## Introduction

Rust 的“工具链”不是一个大二进制，而是一组边界清楚、版本耦合程度不同的程序：rustup 选择并安装 toolchain，rustc 编译，Cargo 编排 package graph，rustfmt 做机械格式化，Clippy 做语义 lint，rustdoc 生成与测试文档，rust-analyzer 通过 LSP 服务编辑器，Miri 与 sanitizer 在运行时寻找未定义行为，nextest、Criterion 和 coverage 工具再补测试工程能力。

本篇以 **2026-10-08** 为时间点。本机实测默认工具链为 `rustc 1.98.1 (48a229cea 2026-09-01)`、`cargo 1.98.1`，host 为 `aarch64-apple-darwin`；最新 stable Rust 1.99.0 的事项只按官方 release notes 标“自 1.99.0 起”。版本轴、channel 与 MSRV 的定义见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)，这里只从安装、组件、编辑器集成、测试与 CI 的工具视角展开。

先记一条排障原则：`command -v` 找到 `~/.cargo/bin/<name>`，只证明 rustup proxy 或独立文件存在，不证明当前 toolchain 真包含该 component。必须再执行命令或用 `rustup which --toolchain ...` 验证。本机的 `rust-analyzer` 与 `cargo-miri` 正好展示了这个陷阱。

## Toolchain Inventory

本机实测核心版本：

```text
$ rustc --version --verbose
rustc 1.98.1 (48a229cea 2026-09-01)
host: aarch64-apple-darwin
release: 1.98.1
LLVM version: 22.1.8

$ cargo --version
cargo 1.98.1 (797e8a9bc 2026-08-05)

$ rustfmt --version
rustfmt 1.9.0-stable (48a229ceae 2026-09-01)

$ cargo clippy --version
clippy 0.1.98 (48a229ceae 2026-09-01)

$ cargo nextest --version
cargo-nextest 0.9.145 (00af4550e 2026-09-16)
```

“Rust 1.98.1 toolchain”是一套同步发布物，不要求每个工具显示相同版本格式：rustc 用 `1.98.1`，Clippy 用 `0.1.98`，rustfmt 有自己的 `1.9.0-stable`。第三方 `cargo-nextest` 完全独立发布，日期与版本也不跟 Rust release train。

本机 `rustup component list --installed` 的实测输出只有：

```text
cargo-aarch64-apple-darwin
clippy-aarch64-apple-darwin
rust-std-aarch64-apple-darwin
rustc-aarch64-apple-darwin
rustfmt-aarch64-apple-darwin
```

这份输出是判断“当前 toolchain 已装什么”的权威本地证据。`cargo --list` 虽然显示 `miri`，实际 `cargo miri --version` 报 component 对 stable 不可用；`rust-analyzer --version` 也报 `Unknown binary`。因此不能把 PATH 中的 shim 当成工具已经安装。

## Rustup as the Multiplexer

rustup 管理三种滚动 channel：`stable`、`beta`、`nightly`，也接受 `1.98.1`、`nightly-2026-09-01` 这类 pinned toolchain 名。滚动 channel 更新后指向新快照；带版本或日期的名称表达可复现选择。具体 release 兼容政策仍以 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md) 为准。

常用操作分成安装、选择、补组件、补 target：

```bash
rustup toolchain install stable
rustup toolchain install 1.95.0
rustup default stable
rustup override set 1.95.0
rustup component add rustfmt clippy
rustup target add wasm32-unknown-unknown
```

`rustc +1.95.0 --version` 中的 `+toolchain` 不是 rustc 参数，而是 rustup proxy 在启动真实命令前消费的选择器。本机实测：

```text
$ rustc +1.95.0 --version
rustc 1.95.0 (59807616e 2026-04-14)

$ cargo +1.95.0 --version
cargo 1.95.0 (f2d3ce0bd 2026-03-21)
```

rustup 选择 toolchain 时，命令行 `+toolchain` 优先级最高，其后才考虑 `RUSTUP_TOOLCHAIN`、目录 override、向父目录搜索到的 toolchain 文件与 default。临时比较编译器时用 `+1.95.0`，项目长期约束则提交：

```toml
# rust-toolchain.toml
[toolchain]
channel = "1.98.1"
profile = "minimal"
components = ["rustfmt", "clippy"]
targets = ["wasm32-unknown-unknown"]
```

`components` 是随 toolchain 分发的 host 工具，如 `rustfmt`、`clippy`、`rust-src`；`targets` 主要是为交叉目标安装的 `rust-std`。装了 target 不会自动安装 C linker、SDK 或 emulator。

本机 `rustup toolchain list` 实测只有两套；用户要求的 `ls ~/.rustup/toolchains/` 也实测只列出对应的两个目录：

```text
stable-aarch64-apple-darwin (active, default)
1.95.0-aarch64-apple-darwin
```

其中目录名分别为 `stable-aarch64-apple-darwin/` 与 `1.95.0-aarch64-apple-darwin/`。本机 `rustup target list --installed` 实测只有 `aarch64-apple-darwin`。1.95.0 额外装有 `rust-docs` 与 `rust-src`，stable 1.98.1 没有；component 是**逐 toolchain**安装的，不在两套工具链之间共享。

## Proxy and Shim Mechanics

本机 `~/.cargo/bin/rustc`、`cargo`、`rustfmt`、`cargo-fmt`、`cargo-clippy`、`cargo-miri`、`rust-analyzer`、`rust-gdb` 与 `rust-lldb` 都实测为 `-> rustup` 的符号链接。rustup 读取当前目录与选择器后，再转发到真实 toolchain 二进制：

```text
$ rustup which rustc
/Users/robin/.rustup/toolchains/stable-aarch64-apple-darwin/bin/rustc
```

这个设计让 `rustc +nightly`、目录 override 与 `rust-toolchain.toml` 对几乎所有一等工具保持一致。反面是“shim 总在、component 可缺”：

```text
$ rustup which rust-analyzer --toolchain stable-aarch64-apple-darwin
error: unknown binary 'rust-analyzer' in toolchain 'stable-aarch64-apple-darwin'

$ rustup which cargo-miri --toolchain stable-aarch64-apple-darwin
error: 'cargo-miri' is not installed for the toolchain 'stable-aarch64-apple-darwin'.
```

`cargo-nextest` 不同：本机该路径是独立的 23 MB 可执行文件，不是 rustup symlink。工具归属应看安装来源与真实文件，而不是只看命令前缀。

## Rust Analyzer

rust-analyzer 是独立运行的 **Language Server Protocol server**：编辑器是 LSP client，负责 UI；server 读取 Cargo metadata、源码与 cfg/feature 配置，维护增量语义数据库，提供 completion、go to definition、rename、references、inlay hints、diagnostics 与 assists。它不等于“每次按键运行一次 rustc”，因此响应快，但诊断也不必与 rustc 完全同构。

“独立二进制”描述的是进程与架构，**不意味着它不是 rustup component**。当前官方安装方式同时包括编辑器扩展自带/下载 release binary，以及 `rustup component add rust-analyzer`；本机 `rustup component list` 实测也列出 `rust-analyzer-aarch64-apple-darwin` 为可用项，只是未安装。把“独立 binary”与“可由 rustup 分发”写成互斥命题是错误的。

宏支持分两层：

| 宏类型 | rust-analyzer 的处理 | 失败模式 |
| :-- | :-- | :-- |
| `macro_rules!` / declarative macro | 在分析数据库中递归展开并映射 token | 递归深度、错误 token 或 cfg 不一致会使局部语义降级 |
| procedural macro | 通过单独 proc-macro server 加载并执行动态库 | build script 未完成、host/target 不匹配或宏 panic 会留下未展开区域 |

proc macro 本质是会执行的 host 代码，编辑器加载 workspace 时也可能触发构建与执行边界；在不受信任仓库中，不应把“只打开编辑器”视为纯文本阅读。排障先看 `rust-analyzer` 日志中的 workspace fetch/build-script/proc-macro 三段，而不是直接删除 IDE cache。

本机当前 PATH 中的 `rust-analyzer` 入口实际不可执行，因此本篇只把该状态称为“实测”；系统或编辑器是否另带未进入 PATH 的 server 不据此推断。LSP 与宏行为依据当前官方 manual，不伪称本机交互实测。

## Rustfmt

rustfmt 是确定性的源码格式化器，`cargo fmt` 是 cargo-fmt 对整个 package/workspace target 的包装。CI 常用：

```bash
cargo fmt --all -- --check
```

`--check` 只比较、不写文件；本机 `rustfmt 1.9.0-stable` 实测可运行。项目配置可放 `rustfmt.toml` 或 `.rustfmt.toml`，从目标文件目录向父目录查找；常见稳定项包括：

```toml
edition = "2024"
max_width = 100
use_small_heuristics = "Default"
newline_style = "Unix"
```

rustfmt 解析语法时必须知道 edition。经 `cargo fmt` 调用时可从 Cargo target 获得 edition；直接调用 `rustfmt` 时则应由 `--edition` 或配置明确，避免把新版语法放进旧默认语境。

配置文档将每项标为 Stable 或 Unstable。stable rustfmt 只有 stable 项生效；nightly-only 项需要 nightly toolchain，并非“写进配置就偷偷启用”。本机把 `imports_granularity = "Crate"` 放进 `rustfmt.toml` 后运行 stable `cargo fmt -- --check`，实测退出码仍为 0，但明确输出：

```text
Warning: can't set `imports_granularity = Crate`, unstable features are only available in nightly channel.
```

所以 CI 不能只看格式命令成功，还应看是否误用了被 stable 忽略的配置。若团队决定使用 nightly 格式化，必须 pin nightly 日期，否则格式输出可能随 nightly 漂移。

## Clippy

Clippy 与对应 rustc 同步发布并通过 `rustup component add clippy` 安装。本机实测 `clippy 0.1.98` 可运行；最小命令是 `cargo clippy`，完整 workspace 检查常加 `--workspace --all-targets --all-features`。

主要 lint groups 的当前默认策略：

| group | 默认 | 意图 |
| :-- | :-- | :-- |
| `correctness` | deny | 高置信度错误或无效代码 |
| `suspicious` | warn | 可疑但未必错误的写法 |
| `style` | warn | 惯用表达与可读性 |
| `complexity` | warn | 不必要的复杂实现 |
| `perf` | warn | 高置信度性能坏味道 |
| `pedantic` | allow | 更主观、更严格，允许一定 false positive |
| `nursery` | allow | 尚在孵化、稳定性或误报率未达默认组标准 |
| `restriction` | allow | 禁止某类语言能力；不应整组开启，内部 lint 甚至可能互相冲突 |

`clippy::all` 汇总默认质量组，但不包含 `pedantic`、`nursery` 与 `restriction`。项目可以逐项设级别：

```toml
[lints.clippy]
all = { level = "warn", priority = -1 }
pedantic = { level = "warn", priority = -1 }
module_name_repetitions = "allow"
unwrap_used = "deny"
```

CI 经典写法仍是：

```bash
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

`--` 后参数交给 clippy-driver/rustc。自 Cargo 1.97.0 起，官方更推荐 `CARGO_BUILD_WARNINGS=deny cargo clippy` 或 `[build] warnings = "deny"`，因为反复切换 `-D warnings` 会改变编译参数并使 cache 失效；但旧写法在本机 1.98.1 仍有效。

MSRV 会改变建议是否合法。`clippy.toml` 可写 `msrv = "1.70"`，其默认值取 `Cargo.toml` 的 `package.rust-version`，未提供时才按当前编译器。`#![clippy::msrv = "1.70"]` 是更细粒度 attribute，但官方文档要求 `custom_inner_attributes`，因此它仍需 nightly；stable 项目优先用 manifest 与 `clippy.toml`。Clippy 可能抑制某条 lint，或改给旧 API 的兼容建议，但它不能替代在真实 MSRV 工具链上编译。

## Rustdoc

rustdoc 随标准 Rust distribution 提供；`cargo doc` 为当前 package 与依赖构造 rustdoc 调用，默认输出到 `target/doc`。常用边界：

```bash
cargo doc --workspace --no-deps
cargo rustdoc -- --document-private-items
RUSTDOCFLAGS="-D rustdoc::broken_intra_doc_links" cargo doc --no-deps
```

`--document-private-items` 让内部 API 进入产物，适合应用与内部 crate 审查，不应误解为改变 Rust visibility。`rustdoc::broken_intra_doc_links` 检查 `[Vec]`、[`Self::method`] 这类 intra-doc link，CI 设 deny 可防重构后链接静默断裂。

doc test 是测试的一类，不只是文档渲染副作用。`cargo test --doc` 让 rustdoc 抽取 fenced Rust blocks，补必要 wrapper 后编译并运行；`compile_fail`、`no_run`、`should_panic`、`ignore` 控制预期。自 edition 2024 起，兼容 doctest 可合并编译以提速，但每个 doctest 仍独立运行；依赖具体源码行号的例子可标 `standalone_crate`。

`cargo doc` 生成文档，`cargo test --doc` 验证示例，两者不能互相替代。第三方 test runner 也未必接管 doctest，因此 CI 应显式保留这一层。

## Miri

Miri 是解释 MIR 的 Undefined Behavior detector，不是性能 profiler，也不是形式证明器。典型流程需要 nightly：

```bash
rustup +nightly component add miri
cargo +nightly miri setup
cargo +nightly miri test
```

本机没有 nightly toolchain；stable 的 `cargo-miri` 只是 rustup shim，实测运行失败。因此本篇没有声称执行过 Miri test。

当前官方 Miri 可检查：

| 类别 | 例子 | 边界 |
| :-- | :-- | :-- |
| 空间/生命期 UB | 越界、use-after-free | 只覆盖实际执行路径 |
| 初始化与有效性 | 未初始化读、无效 `bool`/enum discriminant | 不等价于所有 Rust 规范性质 |
| 对齐与 intrinsic 前置条件 | 未对齐引用、重叠 `copy_nonoverlapping` | 依赖 Miri 已实现的规则 |
| aliasing | Stacked Borrows，或可选 Tree Borrows | 模型仍属 experimental |
| 并发 UB | data race、部分 weak-memory 效应 | 只运行众多调度中的一条，可换 seed 但不穷举 |
| 资源 | 不可达 allocation 的 leak | leak 报告不等同所有资源泄漏 |

必须纠正一个常见错误：**Miri 能检测数据竞争**，因为 Rust/C/C++ 内存模型中的 data race 本身就是 UB。它的限制是动态执行覆盖不完所有交错，而不是“不查 data race”。ThreadSanitizer 也是动态 race detector，适合原生速度与更真实系统环境；loom 通过替换同步原语系统探索受控并发状态。三者覆盖与成本不同，不是简单归属切割。并发模型本身见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

Miri 隔离程序并为一部分系统 API 提供 shim，多数平台专有 API、networking 与 FFI 并不完整。调用未建模 FFI 时可能直接不支持；即使通过外部 shared object 实验性放行，Miri 也无法检查外部代码内部。unsafe/FFI 语义边界见 [Unsafe and FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Tests and Benchmarks

内建 `cargo test` 编译 unit tests、integration tests 与 doc tests，并使用 libtest harness 处理过滤、`#[ignore]`、并行线程和输出捕获。它是稳定基线；需要真实外部资源的测试仍应显式隔离，不能因默认并行执行而共享未同步状态。

cargo-nextest 是第三方 Cargo extension，不随 Cargo/rustup 发布。本机实测独立二进制版本为 `0.9.145`。它为每个测试提供更强的进程隔离、并发调度、重试、分区与慢测试策略，适合大型 suite；当前工作流仍应单独运行 doctest，因为 nextest 不把 rustdoc doctest 当普通 test binary 接管。

```bash
cargo nextest run --workspace --all-features
cargo test --workspace --doc
```

benchmark 有三层事实：

1. `cargo bench` 命令本身在 stable 存在，选择优化的 `bench` profile。
2. 标准库 `test::Bencher` 与 `#[bench]` 不是 stable benchmark API；自 Rust 1.88.0 起，历史 soft-unstable 使用被硬错误拒绝。
3. Criterion.rs 是第三方 stable-compatible harness；当前 `cargo search criterion --limit 1` 本机联网实测返回 `criterion = "0.8.2"`。

本机 1.98.1 临时 crate 实测 `cargo bench` 成功，默认 unit test harness 把普通 `#[test]` 标成 ignored，结果为 `0 measured`；加入 `extern crate test` 与 `#[bench]` 后实测报四处 E0658，包括：

```text
error[E0658]: use of unstable library feature `test`: `bench` is a part of custom test frameworks which are unstable
```

Criterion 的 stable 接法是关闭内建 harness：

```toml
[dev-dependencies]
criterion = "0.8.2"

[[bench]]
name = "throughput"
harness = false
```

因此“`cargo bench` 在 stable 不能运行”是错的；准确说法是命令与 custom `harness = false` 稳定，而内建 `#[bench]` API 不稳定且自 1.88.0 起成为 hard error。

## Profiling, Coverage, and Debugging

工具要按观测层次选择：

| 目标 | 工具 | 归属与当前边界 |
| :-- | :-- | :-- |
| CPU sample profile | Linux `perf`、`cargo flamegraph`、samply | `perf` 是 OS 工具；后两者是第三方，不是 Cargo 内建 |
| source-based coverage | rustc `-C instrument-coverage` + LLVM tools | 编译器插桩是 Rust 能力，报告还需 `llvm-tools`/`llvm-profdata`/`llvm-cov` |
| Cargo coverage workflow | `cargo llvm-cov` | 第三方 wrapper，不是 Cargo 内建 |
| source debugger | `rust-gdb` / `rust-lldb` | rustup proxy 选择工具链脚本，再调用系统 debugger |
| UB execution | Miri | nightly、解释执行、覆盖已走路径 |
| native data race | ThreadSanitizer | nightly `-Zsanitizer=thread`，需完整插桩并受 target 限制 |

本机实测 `perf`、`cargo flamegraph`、`samply` 与 `cargo llvm-cov` 都不可用；不能把文档中的候选工具写成本机已装。`rust-gdb --version` 实测进入 GNU gdb 15.2，`rust-lldb --version` 实测进入 Apple LLDB 1600.0.36.3。

release profiling 通常保留 line tables：

```toml
[profile.profiling]
inherits = "release"
debug = "line-tables-only"
strip = "none"
```

采样 profiler 看“时间在哪里”，coverage 看“哪些路径执行过”，Miri/sanitizer 看“执行路径是否违规”，debugger 看“某一时刻状态”。四种证据不能互相替代；特别是 100% line coverage 既不证明无 UB，也不证明无 race。

## Supply Chain Tools

`cargo tree` 是 Cargo 1.98.1 内建命令：`-d` 找重复版本，`-i crate` 反查依赖者，`-e features` 显示 feature 来源。它描述解析结果，不查询漏洞数据库，也不执行许可证/来源政策。

`cargo audit`（RustSec advisory）、`cargo deny`（advisory/license/ban/source policy）都是第三方扩展。本机逐个实测均报 `no such command`，同样未安装的还有 `cargo msrv`、`cargo outdated` 与 `cargo llvm-cov`。是否出现在某篇工具清单与是否属于 Cargo 内建是两个问题。

供应链最小闭环通常是：提交 lockfile；用 `cargo fetch --locked` 固定解析；用 `cargo tree` 检视图；再按项目政策安装并 pin audit/deny 的版本。build script 与 proc macro 会在 host 执行代码，审计不能只看最终 binary 的 runtime dependencies。

## Minimal CI

一个不依赖 nightly 的最小质量门可以写成：

```yaml
steps:
  - run: rustup component add rustfmt clippy
  - run: cargo fmt --all -- --check
  - run: cargo check --workspace --all-targets --all-features --locked
  - run: cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
  - run: cargo test --workspace --all-features --locked
  - run: RUSTDOCFLAGS="-D rustdoc::broken_intra_doc_links" cargo doc --workspace --no-deps --locked
```

对 library 再加真实 MSRV job；只写 `rust-version` 不会证明源码和所有 feature 组合可在该版本编译。对使用 nextest 的项目，仍保留 `cargo test --doc`。Miri、sanitizer、coverage 与 supply-chain audit 成本和平台约束更强，应作为独立 job，不要让“最小 CI”假装覆盖了所有动态性质。

CI 里的 toolchain 与第三方扩展都应 pin：前者用 action/container 或 `rust-toolchain.toml`，后者记录安装版本。滚动 `stable` 适合前向兼容 job，但可复现发布需要精确 toolchain；二者可并列而不是二选一。

## Toolchain Comparison

| 维度 | Rust | Go | Java | Python |
| :-- | :-- | :-- | :-- | :-- |
| 版本管理 | rustup toolchain/channel/component/target | 官方发行版，常配第三方版本管理器 | JDK distribution + SDK 管理器 | interpreter/venv，常配 pyenv/uv |
| 构建与依赖 | Cargo 一体化 | `go` command + modules | Maven/Gradle | pip/uv/Poetry 等多套组合 |
| 编辑器语义 | rust-analyzer LSP | gopls LSP | JDT LS/IDE index | Pylance/Pyright/Jedi |
| 格式化 | rustfmt 官方组件 | gofmt 官方内建 | 常由 IDE/Spotless/google-java-format | Black/Ruff 等第三方 |
| 静态检查 | rustc lints + Clippy | go vet/staticcheck | javac + Error Prone/SpotBugs | Ruff/Pylint/mypy/Pyright |
| 文档测试 | rustdoc 原生抽取执行 | example tests | Javadoc 本身不执行示例 | doctest 可执行交互示例 |
| UB/内存模型检查 | Miri + sanitizers | race detector 原生集成度高 | managed runtime + profiler | managed runtime + type/lint tools |

Rust 的特色不是每项工具都独有，而是 toolchain pin、compiler、formatter、lint、docs 与 Cargo metadata 共享同一版本坐标。第三方扩展仍独立发布，所以“`cargo foo`”这个命令形状不能证明 `foo` 属于官方工具链。

## Diagnostic Checklist

1. 先记录 `rustc --version --verbose`、`cargo --version` 与 `rustup show active-toolchain`。
2. 对 component 同时查 `rustup component list --installed` 与 `rustup which`，不要只查 PATH。
3. 对 `cargo-*` 扩展执行 `cargo <name> --version`，再判断它是 rustup shim 还是独立文件。
4. 编辑器行为异常时区分 LSP client、rust-analyzer server、Cargo build script 与 proc-macro server。
5. formatter 配置按 Stable/Unstable 分类；stable 命令成功也要留意 ignored-option warning。
6. Clippy 以 manifest MSRV 为默认建议边界，但 CI 仍要用真实 MSRV toolchain 编译。
7. test、doctest、nextest、benchmark 分开列任务；不要假设一个 runner 全部覆盖。
8. Miri 能查执行到的 data race，但不穷举调度；与 TSan、loom 按覆盖模型互补。
9. profiler、coverage、debugger、UB detector 回答不同问题，报告中必须标明证据类型。

## Links

- [Cargo](/docs/CS/Rust/Cargo.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [Error Handling](/docs/CS/Rust/Error_Handling.md)
- [Macros](/docs/CS/Rust/Macros.md)

## References

- [The rustup book](https://rust-lang.github.io/rustup/)
- [rust-analyzer User Manual](https://rust-analyzer.github.io/book/)
- [rustfmt Configurations](https://rust-lang.github.io/rustfmt/)
- [Clippy Documentation](https://doc.rust-lang.org/clippy/)
- [Configuring Clippy](https://doc.rust-lang.org/clippy/configuration.html)
- [The rustdoc book](https://doc.rust-lang.org/rustdoc/)
- [Documentation Tests](https://doc.rust-lang.org/rustdoc/write-documentation/documentation-tests.html)
- [Miri](https://github.com/rust-lang/rust/tree/master/src/tools/miri)
- [Rust Compiler Sanitizers](https://doc.rust-lang.org/beta/unstable-book/compiler-flags/sanitizer.html)
- [cargo-nextest](https://nexte.st/)
- [Criterion.rs](https://bheisler.github.io/criterion.rs/book/)
- [cargo-llvm-cov](https://github.com/taiki-e/cargo-llvm-cov)
- [RustSec cargo-audit](https://github.com/rustsec/rustsec/tree/main/cargo-audit)
- [cargo-deny](https://embarkstudios.github.io/cargo-deny/)
