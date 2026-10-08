## Introduction

Cargo 同时扮演三个角色：它是把 crate graph 翻译成 rustc 调用序列的**构建器**，是解析版本、feature 与 lockfile 的**包管理器**，也是执行 `search` / `login` / `publish` / `yank` 的**注册表客户端**。把它只理解成“Rust 的 Make”会漏掉依赖求解；只理解成“Rust 的 npm”又会漏掉 target、profile、build script 与链接器编排。

本篇以 **Cargo 1.98.1（2026-08-05）本机实测**为行为基线，以 Rust/Cargo 1.99.0 官方文档补充后一版本变化。凡命令输出写“实测”，凡不能在本机 1.98.1 验证的变化写“自 X.Y.Z 起”。edition 与 MSRV 的定义及迁移见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)，rustc 前端到链接的阶段见 [Compile Pipeline](/docs/CS/Rust/compile.md)，这里不重复展开。

Cargo 的核心产物不是某个二进制，而是三样东西：由 manifest 声明的**约束**、resolver 生成并写入 `Cargo.lock` 的**具体依赖图**、按 profile 与 target 编排出的**构建单元图**。后续所有行为都可以放回这三层理解。

## Three Roles and Three Graphs

| 身份 | 输入 | 输出或副作用 | 代表命令 |
| :-- | :-- | :-- | :-- |
| 构建器 | package targets、profile、target triple | rustc / rustdoc / linker 调用与 `target/` 产物 | `build`、`check`、`test`、`doc`、`rustc` |
| 包管理器 | 版本需求、source、features、resolver policy | 解析图与 `Cargo.lock` | `add`、`remove`、`update`、`tree`、`metadata` |
| 注册表客户端 | registry 配置、token、package metadata | 查询、打包、上传、owner/yank 操作 | `search`、`info`、`package`、`publish`、`owner`、`yank` |

同一个 package 可以产生一个 library crate、多个 binary/example/test/bench crate；workspace 又把多个 package 放入同一解析与构建上下文。Cargo 先解析 package graph，再把每个 package 按 host/target、profile、feature set 等拆成 compilation units。因此“同一个依赖为何编译两次”通常不是 resolver 选了两个版本，而是它在 host build-dependency 与 target normal-dependency 上形成了两个构建单元。

`cargo metadata --format-version 1` 暴露 package graph 与 resolve graph，适合 IDE 和审计工具；`cargo tree -e features` 从人类视角显示 feature 来源。两者在 Cargo 1.98.1 都是内建命令，但前者不是稳定的 rustc 调用脚本接口。

## Manifest Anatomy

`Cargo.toml` 是 package manifest；workspace root 的同名文件还可以承担 workspace manifest。一个覆盖常用表的骨架如下：

```toml
[package]
name = "codec-cli"
version = "0.4.2"
edition = "2024"
rust-version = "1.85"
description = "A small codec front end"
license = "MIT OR Apache-2.0"
repository = "https://example.invalid/codec-cli"
readme = "README.md"
keywords = ["codec", "cli"]
categories = ["command-line-utilities"]
publish = false
build = "build.rs"
default-run = "codec"

[dependencies]
serde = { version = "1.0", features = ["derive"] }

[dev-dependencies]
proptest = "1"

[build-dependencies]
cc = "1"

[[bin]]
name = "codec"
path = "src/main.rs"
required-features = ["cli"]
```

Cargo 1.98.1 下，`name` 是本地 manifest 中唯一必填的 `[package]` 字段；发布到 registry 时还会受 registry 的 metadata 规则约束。`version` 表示本 package 的 SemVer，`edition` 选择 crate 语言语境，`rust-version` 自 1.56.0 起受 Cargo 尊重并声明 MSRV。

关键字段的职责必须分开：

| 字段 | 约束对象 | 常见误解 |
| :-- | :-- | :-- |
| `version` | 当前 package 的发布版本 | 不是依赖版本范围 |
| `edition` | 此 package 中所有 targets 的语言 edition | 不是工具链 pin |
| `rust-version` | 支持的最低 Rust 工具链 | 不会自动禁止源码使用更高版本 API，仍需 CI 验证 |
| `publish` | 是否/向哪些 registry 发布 | 不影响本地构建 |
| `build` | build script 路径或开关 | 不是普通 binary target |
| `links` | 声明唯一 native library 名并传递 metadata | 不是 linker 参数列表 |
| `include` / `exclude` | `cargo package` 收包边界 | 不是 rustc module 可见性 |

Cargo 按约定自动发现 `src/lib.rs`、`src/main.rs`、`src/bin/*.rs`、`examples/*.rs`、`tests/*.rs` 与 `benches/*.rs`。需要改名、改路径、关闭 harness 或挂 `required-features` 时，才显式写 `[lib]`、`[[bin]]`、`[[example]]`、`[[test]]`、`[[bench]]`。多个 `[[bin]]` 是 TOML array of tables，不是一个 `[bin]` 表。

`[package.metadata.*]` 与 `[workspace.metadata.*]` 对 Cargo 本身不透明解释，供第三方工具存配置；`[lints]` 是 Cargo 1.74.0 起稳定的 lint 配置入口。二者都不应拿来模拟 Cargo 已有的一等字段。

## Version Requirements

Cargo 的默认需求就是 caret：`serde = "1.0.188"` 等价于 `serde = "^1.0.188"`。它不是精确 pin；resolver 通常在允许范围内偏好最高版本，最终选择再由 lockfile 固定。

| 写法 | 展开范围 | 适合场景 |
| :-- | :-- | :-- |
| `1.2.3` / `^1.2.3` | `>=1.2.3, <2.0.0` | 默认选择，允许 SemVer-compatible 更新 |
| `^0.2.3` | `>=0.2.3, <0.3.0` | 0.x 中以最左非零段确定兼容边界 |
| `^0.0.3` | `>=0.0.3, <0.0.4` | 0.0.x 几乎精确到 patch 线 |
| `~1.2.3` | `>=1.2.3, <1.3.0` | 只接受同 minor 的 patch 更新 |
| `~1` | `>=1.0.0, <2.0.0` | 只写 major 时仍允许 minor 更新 |
| `1.2.*` | `>=1.2.0, <1.3.0` | 通配同一 minor；crates.io 拒绝裸 `*` |
| `>=1.2, <1.5` | 同时满足两个比较式 | 手工交集 |
| `=1.2.3` | 仅 `1.2.3` | 极少数必须精确耦合的场景 |

最大的陷阱是把 pre-1.0 一概理解成“任何 patch 都不兼容”。Cargo 的 caret 规则看**最左侧非零分量**：`^0.2.3` 明确是 `>=0.2.3, <0.3.0`，所以 `0.2.9` 可选而 `0.3.0` 不可选；只有 `^0.0.3` 才收窄到 `<0.0.4`。这套规则是 Cargo 对 SemVer 的工程化解释，不等于 SemVer 规范声称 0.x 有稳定 API。

逗号表示 AND 而不是 OR：`>=1.2, <1.5` 是交集。预发布版本默认不匹配普通需求；要从 `1.0.0-alpha` 起步必须显式写预发布标识。`+metadata` 不参与 Cargo 的版本选择。

## Dependency Kinds and Sources

三种 dependency kind 决定依赖在哪个构建阶段出现：

| 表 | 被谁使用 | 是否传播给下游 |
| :-- | :-- | :-- |
| `[dependencies]` | library/binary 的正常编译 | 是 |
| `[dev-dependencies]` | 当前 package 的 test/example/bench | 否 |
| `[build-dependencies]` | `build.rs`，为 host 编译 | 不进入目标程序的普通依赖图 |

目标条件可包住三种表：

```toml
[target.'cfg(unix)'.dependencies]
nix = "0.30"

[target.aarch64-unknown-linux-gnu.build-dependencies]
cc = "1"
```

当前官方规则不支持用 `cfg(feature = "...")` 驱动 `[target.*]` 依赖选择；feature 应放在 `[features]` 与 optional dependency 中，平台选择才交给 target table。

同一依赖可以来自 registry、Git 或本地路径：

```toml
[dependencies]
bytes = "1"
engine = { git = "https://example.invalid/engine.git", rev = "0123456" }
codec = { path = "../codec", version = "0.4" }
flate2 = { version = "1", default-features = false, features = ["zlib-rs"] }
telemetry = { version = "0.2", optional = true }
```

Git 源可选 `branch`、`tag` 或 `rev`，lockfile 固定解析到的 commit；`path + version` 常用于 workspace 内开发并保证发布后可改用 registry 中满足该版本的包。路径本身不上传，发布检查要求非 registry 依赖有可发布的版本落点。

`[patch.crates-io]` 在**整个依赖图**替换某个 source 中符合原版本需求的候选，典型用途是临时测试 fork；它不是无条件强制版本，patch package 的版本仍需落入消费者声明的 requirement。workspace 中只有 root manifest 的 `[patch]` 生效。

## Lockfile Policy

`Cargo.lock` 记录一次成功解析得到的精确 package id、source、checksum 与依赖关系，使不同机器和时间复用同一解析结果。它锁的是解析图，不锁编译器、系统链接库、环境变量或 build script 的外部输入，所以“有 lockfile”不等于完整可复现构建。

历史惯例是“应用提交、库不提交”：应用需要部署可复现性；库的下游只读取其 `Cargo.toml`，发布包携带的 lockfile 不约束消费者，省略库 lockfile 还能让 CI 经常碰到最新兼容依赖。现实规则已变得更务实：当前 `cargo new` 默认不再替你忽略 `Cargo.lock`，官方 FAQ 也改为“是否提交取决于 package 需要”。工具、workspace、MSRV 测试与可审计构建都能从提交 lockfile 获益；库仍必须另设任务验证无锁/最新依赖，因为提交自己的 lockfile不会替消费者锁版本。

常用更新粒度：

```bash
cargo update                       # 在 manifest 范围内重求整个 lockfile
cargo update -p serde              # 只主动更新指定 package
cargo update -p serde --precise 1.0.210
cargo build --locked               # lockfile 缺失或需变化就失败
cargo build --frozen               # 等价于同时禁止网络与 lockfile 变化
```

`cargo update -p` 仍可能连带调整为满足图约束所必需的相关节点；“只改一行”不是它的契约。yanked 版本通常不再新选，但已经锁住的版本可以继续使用，直到显式更新或安全策略拒绝它。

## Resolver Generations

resolver 有两项容易混淆的职责：选择 package **版本**，以及计算实际编译时的 **feature set**。`resolver = "3"` 不是完全不同的包管理器；它继承 v2 的 feature 行为，只把不兼容 `rust-version` 的默认策略改成 `fallback`。

| resolver | 默认来源 | feature 统一 | 版本选择中的 MSRV |
| :-- | :-- | :-- | :-- |
| v1 | 历史默认 | 同一 package/version 的 feature 几乎跨用途全局并集 | 默认不据此回退 |
| v2 | edition 2021 默认；1.51.0 起可显式选 | 隔离未激活 target；隔离 build/proc-macro 与 normal；dev 仅在实际构建时并入 | 默认 `allow` |
| v3 | edition 2024 默认；1.84.0 起稳定 | 与 v2 相同 | `incompatible-rust-versions = "fallback"` |

“v2 按依赖边完全分离”并不准确。普通依赖的同一 package/version 仍做 feature 并集；v2 只在三类边界避免不必要统一：未构建 target、host 上的 build-dependency/proc-macro 对 target normal dependency、以及当前未构建的 dev-dependency。执行 `cargo test` 或 `--all-targets` 后，相关 dev feature 仍会进入并集。

“v3 选择最旧兼容版本”也不准确。Cargo 的一般启发式仍是**偏好最高版本**；v3 在存在 `package.rust-version` 时，优先从 MSRV 兼容候选中选最高者。官方示例在多个兼容版本中选择较新的 `4.0.32`，明确不选更旧的 `4.0.0`。如果 requirement 内根本没有 MSRV 兼容候选，`fallback` 仍可能选一个不兼容版本并在之后报错，而不是保证求解成功。

resolver 是 workspace 全局选项，只认 root package 或虚拟 workspace 的 `[workspace].resolver`；依赖 crate 自己声明的 resolver 不支配顶层构建。自 1.79.0 起，`cargo add` 在未手写版本范围时也会读取当前 package 的 `rust-version`，优先添加兼容版本，并在不是最新版时告知用户。

## Feature Algebra

feature 是命名的条件编译能力集合。Cargo 对同一 package/version 汇总各路径请求的 feature；因此最重要的设计铁律是 **additive**：开启 feature 只能增加能力，不能关闭已有能力，也不应把既有 API 改成不兼容形态。

```toml
[dependencies]
serde = { version = "1", optional = true }
rgb = { version = "0.8", optional = true }

[features]
default = ["std"]
std = []
serialization = ["dep:serde", "rgb?/serde"]
image = ["dep:rgb"]
```

- `optional = true` 默认生成同名隐式 feature。
- `dep:serde` 显式引用 optional dependency，并抑制 `serde` 这个隐式公开 feature；该 namespaced syntax 自 1.60.0 起稳定。
- `rgb/serde` 会在开启 dependency feature 时顺带启用 optional `rgb`。
- `rgb?/serde` 是 weak dependency feature：只有 `rgb` 已被别处启用时才打开它的 `serde` feature，不负责启用 `rgb`；`?/` 同样自 1.60.0 起稳定。
- `default-features = false` 只表达当前依赖声明不请求默认集合；图中另一条边请求默认 feature 时，并集仍会把它打开。

反例是 `no_std = []`、`fast = []` 与 `safe = []` 互相关闭代码：当两个下游同时启用时，统一后的组合没有明确语义。正确方向通常是默认能力最小化，以 `std`、`simd`、`serde` 这类正向 feature 增加实现，并用 `compile_error!` 只处理确实互斥且不可重构的组合。

feature 也是 public contract。删除 feature、删除 optional dependency、把现有 public API 移到 feature 后面，通常都是 SemVer-incompatible；增加 feature 通常兼容，但仍需验证 `--all-features` 与 `--no-default-features`。

## Workspace Semantics

workspace 把 packages 作为一个操作单元，核心共享项是 root、`Cargo.lock` 与默认位于 root 的 `target/`。共享 target 避免同配置重复编译；统一 lockfile 让整个仓库看到同一解析快照，但也意味着低 MSRV member 可能影响其他 member 的依赖选择。

```toml
[workspace]
members = ["crates/*", "tools/xtask"]
exclude = ["crates/experimental"]
default-members = ["crates/app"]
resolver = "3"

[workspace.package]
edition = "2024"
rust-version = "1.85"
license = "MIT OR Apache-2.0"

[workspace.dependencies]
serde = { version = "1", default-features = true, features = ["derive"] }
```

member 显式选择继承：

```toml
[package]
name = "app"
version = "0.1.0"
edition.workspace = true
rust-version.workspace = true
license.workspace = true

[dependencies]
serde = { workspace = true, features = ["rc"] }
```

`workspace.package` 与 `workspace.dependencies` 继承自 1.64.0 起稳定。workspace dependency 不能标成 `optional`；member 增加的 `features` 与 root 定义做并集。自 1.99.0 起，edition ≥ 2024 的 member 可以用 `default-features = false` 覆写继承依赖的 root 设置；在 1.99.0 之前或旧 edition 中，这种局部覆写可能被忽略或拒绝，因此本机 1.98.1 不宣称实测该新语义。

`default-members` 只决定在 workspace root 且没有 `-p` / `--workspace` 时默认操作谁：有 root package 时默认是 root package；virtual workspace 未配置时默认全部 members。`cargo build --workspace` 明确选择全部，`--exclude` 必须配合全 workspace 选择。

只有 root manifest 的 `[profile.*]`、`[patch]` 与 `[replace]` 生效。member 内写这些表会被忽略；这是 workspace “统一构建政策”而非简单目录聚合的直接证据。

## Profiles and Code Generation

四个内建 profile 的继承关系在 Cargo 1.98.1 如下：

| profile | 触发命令 | 继承 | 关键默认值 |
| :-- | :-- | :-- | :-- |
| `dev` | `build` / `run` / `check` | 无 | `opt-level=0`、`debug=true`、`incremental=true`、`codegen-units=256` |
| `test` | `test` | `dev` | 继承开发期可调试性 |
| `release` | `build --release` | 无 | `opt-level=3`、`debug=false`、`incremental=false`、`codegen-units=16` |
| `bench` | `bench` | `release` | 继承优化构建 |

共同默认包括 `strip="none"`、`lto=false`、`panic="unwind"`；dev 的 `debug-assertions` / `overflow-checks` 为 true，release 为 false。这里的 `lto=false` 不是任何情形都绝对“零 LTO”：当 codegen units 大于 1 且启用优化时，rustc 可做 local thin LTO；`lto="off"` 才明确关闭。

| 设置 | 作用 | 取舍 |
| :-- | :-- | :-- |
| `opt-level` | `0..3`、`s`、`z` | 编译时间、运行速度、体积并非单调关系 |
| `debug` | 调试信息级别 | 可为 release 保留 line tables |
| `lto` | 跨 codegen unit/crate 优化 | `fat` 更全面；`thin` 更快且常接近其收益 |
| `codegen-units` | 并行 codegen 分片数 | 多则编译快，跨单元优化空间少 |
| `panic` | `unwind` 或 `abort` | test/bench/build script/proc macro 忽略该设置 |
| `strip` | `none` / `debuginfo` / `symbols` | 减体积但降低诊断与调试能力 |
| `incremental` | 保存增量缓存 | 主要改善本地重编译，增加磁盘状态 |
| `debug-assertions` | 控制 `cfg(debug_assertions)` | 影响 `debug_assert!` 与条件代码 |
| `overflow-checks` | 整数溢出运行时检查 | 与 `debug-assertions` 是两个独立开关 |

自定义 profile 自 1.57.0 起稳定，必须写 `inherits`：

```toml
[profile.production]
inherits = "release"
lto = "thin"
codegen-units = 1
debug = "line-tables-only"
strip = "none"

[profile.dev.package."*"]
opt-level = 1
```

profile override 可针对 dependency 或 build dependency；不能在 override 中改 `panic`、`lto`、`rpath`。泛型代码通常在使用方 monomorphize，所以“只提高依赖 opt-level”未必优化最终实例，实际效果必须 benchmark。

## Build Scripts

存在 `build.rs` 时，Cargo 先把它编译为 host 程序，再执行并读取 stdout 中的指令；脚本生成物必须写入 Cargo 提供的 `OUT_DIR`，源码可用 `include!(concat!(env!("OUT_DIR"), "/bindings.rs"))` 纳入生成代码。

```rust
fn main() {
    println!("cargo::rerun-if-changed=wrapper.h");
    println!("cargo::rerun-if-env-changed=CC");
    println!("cargo::rustc-link-search=native=/opt/vendor/lib");
    println!("cargo::rustc-link-lib=static=vendor");
    println!("cargo::rustc-env=BUILD_FLAVOR=portable");
}
```

`cargo::KEY=VALUE` 双冒号语法自 1.77.0 起可用；若 package 的 MSRV 低于 1.77，应继续输出兼容旧 Cargo 的 `cargo:KEY=VALUE`。两者表达同类指令，不是“双冒号更强”；差异首先是解析语法与 MSRV。

`rerun-if-changed=PATH` 把重跑条件收窄到文件/目录；一个都不发时，Cargo 默认扫描 package 内文件变化。`rerun-if-env-changed=VAR` 追踪 Cargo 进程环境，不应用于 Cargo 自己设置且每次运行可见的变量。

原生链接常用 `rustc-link-search` 与 `rustc-link-lib`。指令输出顺序可能传递到 rustc 再传到 linker，因此静态库存在顺序依赖时，`println!` 顺序也是构建语义。调试脚本时看 `target/<profile>/build/<pkg>/output`，普通构建不会把全部 stdout 直接展示。

build script 是受信任的 host 可执行代码，不是声明式沙箱：拉入依赖就等于允许其 build script 在构建机权限下运行。它也解释了交叉编译的双世界——脚本为 host 编译并运行，最终 crate 才为 target 编译。

## Command Surface

本机 `cargo 1.98.1` 执行 `cargo --list` 的原始项目如下，只去除了终端 ANSI 颜色：

```text
Installed Commands:
    add                  Add dependencies to a Cargo.toml manifest file
    b                    alias: build
    bench                Execute all benchmarks of a local package
    build                Compile a local package and all of its dependencies
    c                    alias: check
    check                Check a local package and all of its dependencies for errors
    clean                Remove artifacts that cargo has generated in the past
    clippy               Checks a package to catch common mistakes and improve your Rust code.
    config               Inspect configuration values
    d                    alias: doc
    doc                  Build a package's documentation
    fetch                Fetch dependencies of a package from the network
    fix                  Automatically fix lint warnings reported by rustc
    fmt                  Formats all bin and lib files of the current crate using rustfmt.
    generate-lockfile    Generate the lockfile for a package
    git-checkout         REMOVED: This command has been removed
    help                 Displays help for a cargo command
    info                 Display information about a package
    init                 Create a new Cargo package in an existing directory
    install              Install a Rust binary
    locate-project       Print a JSON representation of a Cargo.toml file's location
    login                Log in to a registry.
    logout               Remove an API token from the registry locally
    metadata             Output the resolved dependencies of a package, the concrete used versions including overrides, in machine-readable format
    miri
    new                  Create a new cargo package at <path>
    nextest
    owner                Manage the owners of a crate on the registry
    package              Assemble the local package into a distributable tarball
    pkgid                Print a fully qualified package specification
    publish              Upload a package to the registry
    r                    alias: run
    read-manifest        DEPRECATED: Print a JSON representation of a Cargo.toml file.
    remove               Remove dependencies from a Cargo.toml manifest file
    report               Generate and display various kinds of reports
    rm                   alias: remove
    run                  Run a binary or example of the local package
    rustc                Compile a package, and pass extra options to the compiler
    rustdoc              Build a package's documentation, using specified custom flags.
    search               Search packages in the registry. Default registry is crates.io
    t                    alias: test
    test                 Execute all unit and integration tests and build examples of a local package
    tree                 Display a tree visualization of a dependency graph
    uninstall            Remove a Rust binary
    update               Update dependencies as recorded in the local lock file
    vendor               Vendor all dependencies for a project locally
    verify-project       DEPRECATED: Check correctness of crate manifest.
    version              Show version information
    yank                 Remove a pushed crate from the index
```

标题 `Installed Commands` 容易误导：它合并 Cargo 内建命令、alias 与 PATH 上名为 `cargo-*` 的外部程序，并不承诺每一项都能运行。本机分类如下：

| 类别 | 实测项目 | 结论 |
| :-- | :-- | :-- |
| Cargo 内建 | `build`、`check`、`test`、`tree`、`vendor` 等 | 随 Cargo 1.98.1 提供 |
| rustup 官方组件前端 | `cargo-fmt`、`cargo-clippy` | `~/.cargo/bin/` 中是指向 `rustup` 的 shim，组件已安装，可运行 |
| rustup shim 但组件缺失 | `cargo-miri` | 被 `--list` 发现，但执行报 stable 上 Miri component 不可用 |
| 独立第三方扩展 | `cargo-nextest` | `~/.cargo/bin/cargo-nextest` 是真实独立文件，实测版本 0.9.145 |

本机逐个执行确认 `cargo msrv`、`cargo audit`、`cargo deny`、`cargo outdated`、`cargo llvm-cov`、`cargo flamegraph` 都报 `no such command`。它们无论是否安装都**不是 Cargo 内建子命令**；`cargo --list` 只说明当前环境可发现什么，不能当“Cargo 官方功能全集”。

## Cross Compilation

`rustc --print target-list` 列出编译器认识的 built-in target triple；`rustup target add <triple>` 安装该工具链的预编译 `rust-std`，`cargo build --target <triple>` 则切换目标并把产物放入独立 target 子目录。安装标准库不等于安装系统 linker、C runtime 或目标平台 SDK。

```toml
# .cargo/config.toml
[target.aarch64-unknown-linux-gnu]
linker = "aarch64-linux-gnu-gcc"
runner = "qemu-aarch64"

[build]
target = "aarch64-unknown-linux-gnu"
```

本机 1.98.1 实测 host 与唯一已装 target 都是 `aarch64-apple-darwin`，所以这里只验证了命令面，没有谎称完成异平台链接。自 1.95.0 起，stable rustc 不再接受 JSON custom target specification；built-in triple 不受影响。该去稳定化为未来 `build-std` 设计清路，但 `-Z build-std` 到 1.99.0 仍属于 nightly 能力，不能写成 1.95 已稳定。

交叉构建时区分 host 与 target：proc macro、build script 在 host 运行；普通依赖和最终产物面向 target。许多 OpenSSL/系统库失败不是 Rust target 未安装，而是 build script 找不到 target 对应 headers、pkg-config 数据或 linker。

## Vendoring and Offline Builds

`cargo fetch --locked` 先把 lockfile 指定的源填入本地 cache；`--offline` 禁止网络但允许在本地已有数据范围内重新解析，`--locked` 禁止改 lockfile，`--frozen` 同时施加两者。离线不等于 vendor：cache 位于 Cargo home，vendor 则把 source tree 放进项目可携带目录。

```bash
mkdir -p .cargo
cargo vendor --locked vendor > .cargo/config.toml
cargo build --frozen
```

生成配置通过 source replacement 把 crates.io 替换到 `vendor/`。vendored source 应视为只读镜像；要修改依赖，应使用 `[patch]` 指向显式 fork/path，而不是直接改 vendor 后忘记来源。真正可复现还要 pin 工具链、系统依赖和 linker，lockfile + vendor 只解决 Rust package source 这一层。

## Ecosystem Comparison

| 维度 | Cargo | CMake | Maven | Go modules | npm |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 主定位 | 构建器 + 包管理器 + registry client | 构建系统生成器，不自带统一 registry | JVM 构建与依赖管理 | 语言内置模块依赖 | JS 包管理与脚本运行 |
| 锁定 | 单 workspace `Cargo.lock` 精确解析图 | 无统一 lockfile 语义 | POM 通常声明范围，常靠 dependencyManagement 固定 | `go.mod` 选版本，`go.sum` 校验内容 | `package-lock.json` / 同类文件锁安装树 |
| 默认 registry | crates.io，可配 alternate registry | 无 | Maven Central + repositories | module proxy，可直连 VCS | npm registry，可切换 |
| 条件能力 | additive Cargo features，按图统一 | cache options/compile definitions，无包级统一规则 | profiles/optional deps，不等价于 feature union | build tags，不是依赖 feature 协商 | optional/peer deps 与 scripts，无同构 feature algebra |
| 构建配置 | profile、target、build.rs 一体化 | toolchain file、generator、target 属性 | lifecycle/plugin | `go build` flags 与 tags | scripts 调外部 bundler/compiler |

Cargo 的取舍是“一套工具覆盖默认路径”，代价是 resolver、feature union、host/target 双图与 build script 供应链权限都进入同一个模型。排障时先问失败发生在版本解析、feature 选择还是某个构建单元，通常比盯着最后一条 linker error 更快。

## Operational Checklist

1. 用 `cargo metadata` 确认 workspace/package 边界，用 `cargo tree -e features -i <crate>` 追 feature 来源。
2. 应用和工具提交 `Cargo.lock`；库即使提交，也另测最新依赖与声明 MSRV。
3. 更新单包优先 `cargo update -p`，需要重现时配 `--precise`，CI 用 `--locked` 或 `--frozen`。
4. feature 保持 additive，同时测 default、`--no-default-features` 与 `--all-features`。
5. workspace 把 resolver、profile、patch 放 root；自 1.64.0 起用继承减少漂移。
6. `build.rs` 只写 `OUT_DIR`，声明精确 rerun 条件；MSRV < 1.77 时保留旧 `cargo:` 语法。
7. 交叉编译同时准备 Rust target、系统 linker/SDK 与 native dependency 搜索路径。
8. 不从 `cargo --list` 推断命令归属；先判断内建、rustup component 还是 `cargo-*` 扩展。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [Macros](/docs/CS/Rust/Macros.md)
- [Programming](/docs/CS/SE/Programming.md)

## References

- [The Cargo Book](https://doc.rust-lang.org/cargo/)
- [The Manifest Format](https://doc.rust-lang.org/cargo/reference/manifest.html)
- [Specifying Dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html)
- [Dependency Resolution](https://doc.rust-lang.org/cargo/reference/resolver.html)
- [Features](https://doc.rust-lang.org/cargo/reference/features.html)
- [Workspaces](https://doc.rust-lang.org/cargo/reference/workspaces.html)
- [Profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)
- [Build Scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html)
- [Overriding Dependencies](https://doc.rust-lang.org/cargo/reference/overriding-dependencies.html)
- [Cargo FAQ](https://doc.rust-lang.org/cargo/faq.html)
- [Cargo Changelog](https://doc.rust-lang.org/nightly/cargo/CHANGELOG.html)
- [Announcing Rust 1.95.0](https://blog.rust-lang.org/2026/04/16/Rust-1.95.0/)
- [Announcing Rust 1.99.0](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/)
