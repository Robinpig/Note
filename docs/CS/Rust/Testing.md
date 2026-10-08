## Introduction

Rust 把测试做成了**工具链内建的一等公民**：不需要选框架、不需要装 runner，`cargo new` 出来的项目立刻可以 `cargo test`。这套内建能力的边界也很清楚——`#[test]` 属性、`libtest` harness、以及三类测试（单元测试 / 集成测试 / 文档测试）全部随编译器分发；而**基准测试不在其中**，fixture、mock、参数化这些别的语言靠框架提供的东西也统统没有内建答案。

于是测试这篇的组织方式就是**沿着"内建边界"走**：先讲 harness 怎么收集和运行测试（这是所有行为差异的根源），再讲断言族与两种测试布局的分工——**单元测试与集成测试的差别不是目录位置，而是"是不是同一个 crate"**，这决定了能不能测私有项，是布局测试的第一原则。然后是本篇最重的一节：**基准测试的现状**。`#[bench]` 已于 1.88.0 在 stable 上硬错误化（本库 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md) 的 Compatibility Notes 已记录这条），本篇兑现它：实测 stable 上 `#[bench]` 报什么、`cargo bench` 还能不能跑、为什么生态普遍改用 criterion 0.8.2 加 `harness = false`。最后讲属性测试、覆盖率、cargo-nextest、Miri、依赖注入与跨语言对照。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**。本篇标注"实测"的输出均在本机 `rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1` / `cargo-nextest 0.9.145 (00af4550e 2026-09-16)`（host `aarch64-apple-darwin`）上真实运行取得，原文照抄。crate 版本取自 2026-10-07 的 crates.io sparse index 实测：`criterion 0.8.2`、`proptest 1.11.0`。标注"据文档"的条目取自 Rust Reference / Cargo Book / 工具官方文档，未在 1.98.1 上复现。

边界：profile 与 `debug-assertions` 开关见 [Cargo](/docs/CS/Rust/Cargo.md)；rustdoc 与 Miri 本体见 [Tooling](/docs/CS/Rust/Tooling.md)；`dyn` 与 `impl Trait` 的取舍见 [Trait_System](/docs/CS/Rust/Trait_System.md)；`#[cfg(test)] mod tests` 为什么能碰私有项见 [Module_System](/docs/CS/Rust/Module_System.md)。

## The Test Harness: How `cargo test` Works

`cargo test` 做三件事：**以 `--test` 编译每个测试目标** → **逐个运行产出的二进制** → **汇总退出码**。测试目标有四类：lib target 的单元测试、bin target 的单元测试、`tests/` 下每个文件的集成测试、以及 doc test。实测一个 lib + bin + 一个集成测试的 package，`cargo test` 依次跑四个段：

```text
     Running unittests src/lib.rs (target/debug/deps/ut-fccc9570b20d8df2)
     Running unittests src/main.rs (target/debug/deps/ut-09ae7913f0302ac6)
     Running tests/it.rs (target/debug/deps/it-05b6af0ef627c66f)
   Doc-tests ut
```

注意第二段：**bin target 也会被编译成测试二进制**，即使里面一个测试都没有（实测输出 `running 0 tests`）。这是很多人第一次看到 `cargo test` 输出时的困惑来源。

### libtest and Passing Arguments Through `--`

真正执行测试的是 `libtest`（Rust 自带的测试 runner，随 `test` crate 分发）。`cargo test` 自己只负责编译与调度，**`--` 之后的参数一律原样转交 harness**：

```bash
cargo test -- --test-threads=1     # 串行
cargo test -- --nocapture          # 不捕获 stdout/stderr
cargo test -- --ignored            # 只跑 #[ignore] 的
cargo test -- --list               # 只列出不运行
cargo test <filter>                # 按名字子串过滤（cargo 层参数，在 -- 之前）
```

实测 `cargo test -- --list` 的输出（每个目标一段）：

```text
tests::unit_can_see_private: test

1 test, 0 benchmarks
```

最后那行 `0 benchmarks` 是 harness 在告诉你 bench 计数——在 `#[bench]` 已成硬错误的 stable 上，这个数字永远是 0。

### Parallel by Default: Threads, Not Processes

libtest 默认**在一个进程里开 N 个线程**并行跑测试，N 默认等于可用 CPU 数。实测三个测试各打印 `std::process::id()`：

```text
=== cargo test -- --nocapture ===
test a pid=46335
test b pid=46335
test c pid=46335
```

**三个测试同一个 pid**——这是理解 Rust 测试行为的关键事实，也是一串现象的根源：测试之间共享进程状态（环境变量、`static`、全局 allocator），一个测试 panic 只是那个线程 unwind 不影响其他测试，但**一个测试里 `std::process::exit` 或段错误会带走整批**。要串行就 `--test-threads=1`。

`--nocapture` 的另一面：默认 harness 会**捕获**每个测试的 `println!` 输出，只在测试失败时才打印出来（失败摘要里那一段 `---- xxx stdout ----`）。所以"我的 println 不见了"不是 bug，是捕获在生效。

## Assertions

| 宏 | 语义 | 何时用 |
| :-- | :-- | :-- |
| `assert!(cond)` / `assert!(cond, "fmt {}", x)` | 失败即 panic | 通用 |
| `assert_eq!(a, b)` / `assert_ne!(a, b)` | 失败时打印两侧 `Debug` | 需要看到实际值时；要求两侧都实现 `Debug` 且可比较 |
| `debug_assert!` 系列 | **只在 debug profile 生效**，release 下被整体编译掉 | 内部不变量检查，热路径上的昂贵校验 |
| `#[should_panic(expected = "...")]` | 反向断言：必须 panic 且消息含子串 | 错误路径 |
| 返回 `Result` 的测试 | `Err` 即失败，用 `?` 传播 | 测试体里有大量可能失败的操作 |

`debug_assert!` 的差别必须实测才直观——同一份代码在 `check(0)` 上：

```text
--- debug ---
2

thread 'main' (28823201) panicked at src/main.rs:2:5:
x must be positive
--- release ---
2
```

release 下**静默通过**：`debug_assert!` 展开依赖 `cfg(debug_assertions)`，release profile 把它置为 false（profile 机制见 [Cargo](/docs/CS/Rust/Cargo.md)）。所以 `debug_assert!` 是"给开发者的断言"，**绝不能用来校验来自外部的输入**。

`#[should_panic(expected = ...)]` 的子串不匹配时，harness 会把两侧都打出来，实测：

```text
test tests::wrong_expectation - should panic ... FAILED

---- tests::wrong_expectation stdout ----
thread 'tests::wrong_expectation' (28817135) panicked at src/lib.rs:1:26:
explode: now
note: panic did not contain expected string
      panic message: "explode: now"
 expected substring: "wrong message"
```

注意测试名后面被追加了 `- should panic`。一个常见误用：不写 `expected` 的裸 `#[should_panic]` 只断言"发生了 panic"，任何 panic 都算通过，容易放过"因为别的原因崩了"的假阳性。

返回 `Result` 的测试用 `?` 写起来最顺，失败时打印的是 `Debug` 形式的错误，实测：

```text
---- tests::fails_via_result stdout ----
Error: "divide by zero"
```

`#[ignore = "原因"]` 会把原因带进输出（实测 `test tests::slow ... ignored, 需要网络`），用 `cargo test -- --ignored` 单独跑它们。

## Unit Tests vs Integration Tests

这是布局测试的第一原则，判据不是目录而是 **crate 边界**：

| | 单元测试 | 集成测试 |
| :-- | :-- | :-- |
| 位置 | 源码文件里的 `#[cfg(test)] mod tests` | `tests/` 目录下每个 `.rs` |
| crate 归属 | **与被测试代码同一个 crate** | **每个文件是独立的 crate** |
| 能否测私有项 | 能（它是被测模块的子模块） | 不能（只能调 `pub` API） |
| 编译时机 | `cargo build` 时被 `#[cfg(test)]` 整体删掉 | 只在 `cargo test` 时编译 |
| 用途 | 内部逻辑、边界条件、不变量 | 对外 API 的契约、端到端流程 |

```rust
fn private_helper() -> u32 { 7 }        // 私有
pub fn public_api() -> u32 { private_helper() * 2 }

#[cfg(test)]
mod tests {
    use super::*;                       // 子模块 -> 能碰私有项
    #[test]
    fn unit_can_see_private() { assert_eq!(private_helper(), 7); }
}
```

`use super::*` 之所以让私有项变得可测，原理在 [Module_System](/docs/CS/Rust/Module_System.md) 那条"私有 = 对当前模块及其后代可见"`tests` 是 `lib.rs` 根模块的子模块，因此根里的私有项对它全部可见。**Rust 不需要反射、不需要把测试放进同一个包、不需要改可见性就能测私有代码**，这在别的语言里通常要靠测试专用的可见性后门。

反过来，`tests/it.rs` 是独立 crate，`ut::private_helper()` 实测：

```text
error[E0603]: function `private_helper` is private
 --> tests/it.rs:6:20
  |
6 |     assert_eq!(ut::private_helper(), 7);
  |                    ^^^^^^^^^^^^^^ private function
  |
note: the function `private_helper` is defined here
 --> src/lib.rs:1:1
```

由此得到一条实用判据：**`tests/` 里写不出来的测试，说明你的 API 表面不够**，要么补 `pub`，要么把它降级成单元测试；不要把集成测试硬写成单元测试来绕过——那会让你失去"用户视角"的检验。

`tests/` 下的每个文件独立编译成独立二进制，所以**共享的 fixture 要放进 `tests/common/mod.rs`**（`common/` 子目录不会被当成独立测试目标）或用 `mod common;` 引入，否则每个文件各编一份。

## Doc Tests

`cargo test --doc` 把文档里的代码块当测试跑。它和 rustdoc 是同一套东西：rustdoc 在渲染时把 ```` ``` ```` 块交给同一个编译器编译并运行（rustdoc 本体见 [Tooling](/docs/CS/Rust/Tooling.md)）。

四种标注实测（同一份 `src/lib.rs` 上的 `cargo test --doc`）：

| 标注 | 行为 | 实测输出 |
| :-- | :-- | :-- |
| 无（```` ``` ````） | 编译并运行 | `test src/lib.rs - add (line 3) ... ok` |
| `no_run` | 只编译，不运行 | 计入 passed（可执行文件不存在、需要副作用 API 时用） |
| `should_panic` | 编译运行，必须 panic | `test src/lib.rs - add (line 15) - should panic ... ok` |
| `ignore` | 完全不编译 | 单独一段 `test src/lib.rs - add (line 21) ... ignored` |

两个值得记住的细节：

- **doctest 的名字是 `文件 - 项名 (行号)`**，而不是函数名。所以按名字过滤时用 `cargo test --doc add` 而不是 `test_add`。
- 输出末尾有 `all doctests ran in 0.80s; merged doctests compilation took 0.35s`——rustdoc 会把同一 crate 的所有 doctest **合并编译**以摊掉编译开销，这也是 doctest 数量多时仍然可接受的原因。

doctest 的隐性成本是它只覆盖 **lib target** 的公开文档。实测：把 doctest 写进 `src/main.rs` 的文档注释，`cargo test --doc` 的 `Doc-tests ut` 段里是 `running 0 tests`；想补也补不上——`cargo test --doc --bins` 报 `error: can't mix --doc with other target selecting options`。所以"文档里的例子跑不通"这条反馈只对 lib 的公开 API 有效，bin 与私有项上的文档注释没有测试保护。

## Benchmarking After `#[bench]` Was Removed

### Measured: What `#[bench]` Does on Stable

`#[bench]` 与 `test` crate 一直绑在 nightly 的 custom test frameworks 上，1.88.0 起在 stable 上成为硬错误（版本归属与"stable 化可以撤销"这条推论见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)）。实测 stable 1.98.1，裸 `#[bench]`：

```text
error[E0658]: use of unstable library feature `test`: `bench` is a part of custom test frameworks which are unstable
 --> src/lib.rs:1:3
  |
1 | #[bench]
  |   ^^^^^
  |
  = note: see issue #50297 <https://github.com/rust-lang/rust/issues/50297> for more information
```

想用 `#![feature(test)]` 绕也绕不过去，实测：

```text
error[E0554]: `#![feature]` may not be used on the stable release channel
 --> src/lib.rs:1:1
  |
1 | #![feature(test)]
  | ^^^^^^^^^^^^^^^^^
```

也就是说 **stable 上写 bench 的两条路都被堵死**：属性本身 E0658，开 feature gate 则是 E0554（`#[bench]` 在 nightly 上仍然可用，配 `#![feature(test)]` + `extern crate test;`）。

### Measured: `cargo bench` Itself Still Works

子命令没有被移除。实测一个只有 `#[test]` 的 lib，`cargo bench`：

```text
    Finished `bench` profile [optimized] target(s) in 0.11s
     Running unittests src/lib.rs (target/release/deps/benchdemo-501e6e96115e4a6d)

running 1 test
test tests::t_add ... ignored

test result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out
```

三条实测事实：

1. `cargo bench` 仍然编译并运行，用的是 **`bench` profile**（optimized + debuginfo），与 `cargo test` 的 `test` profile 不同；
2. 它把 `#[test]` 全部标记为 **ignored**——harness 被 `--bench` 切成"只跑 bench"模式，而 bench 数为 0；
3. 它**不跑 doc test**（输出里没有 `Doc-tests` 段，而 `cargo test` 有）。

结论：`cargo bench` 现在只是"跑第三方 bench 二进制的入口"，内建的计时机已经不存在了。

### criterion 0.8.2 与 `harness = false`

生态的标准答案是 criterion（实测最新 `0.8.2`）。它自带的 `main` 与 libtest 生成的 `main` 互斥，所以 manifest 里必须关掉内建 harness：

```toml
[dev-dependencies]
criterion = "0.8.2"

[[bench]]
name = "my_bench"
harness = false          # 关键：让 cargo 不要注入 libtest 的 main
```

```rust
use criterion::{criterion_group, criterion_main, Criterion};
use cri::fib;

fn bench_fib(c: &mut Criterion) {
    c.bench_function("fib 20", |b| b.iter(|| fib(std::hint::black_box(20))));
}

criterion_group!(benches, bench_fib);
criterion_main!(benches);
```

`cargo bench` 实测输出（节选）：

```text
Benchmarking fib 20: Collecting 100 samples in estimated 5.0836 s (237k iterations)
Benchmarking fib 20: Analyzing
fib 20                  time:   [20.568 µs 21.106 µs 21.931 µs]
                        change: [+1.5016% +5.9479% +11.969%] (p = 0.01 < 0.05)
                        Performance has regressed.
Found 13 outliers among 100 measurements (13.00%)
```

对比内建 `#[bench]`（本质是固定迭代次数求平均），criterion 多出来的正是手写 bench 不会做的部分：**warmup**、**统计采样**、**与上一次运行的回归检验**（`change:` 行带 p 值）、**离群点报告**、可选的 HTML/图表输出（本机无 gnuplot 时实测回落 `Gnuplot not found, using plotters backend`）。

**`harness = false` 漏写的后果是静默的**，这是最值得记住的一条实测：去掉 `harness = false` 后 `cargo bench` 既不报错也不跑 criterion，只输出

```text
     Running benches/my_bench.rs (target/release/deps/my_bench-612c65b24f02c227)

running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

绿字通过、零基准——CI 上这种配置能静默躺好几个月。

另外实测 criterion 0.8.2 里 `criterion::black_box` 已废弃，编译器建议改 `std::hint::black_box()`：

```text
warning: use of deprecated function `criterion::black_box`: use `std::hint::black_box()` instead
```

## Property-based Testing

手写样例测试是"我举几个例子证明它对"，属性测试是"我描述它应该满足的性质，让生成器去找反例"。proptest（实测最新 `1.11.0`）是 Rust 生态的主流选择：

```rust
pub fn reverse_twice(v: &[i32]) -> Vec<i32> { v.iter().rev().rev().cloned().collect() }

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn double_reverse_is_identity(v in prop::collection::vec(any::<i32>(), 0..100)) {
            prop_assert_eq!(reverse_twice(&v), v);
        }
    }
}
```

`proptest!` 宏把生成策略（`v in ...`）与断言包成一个正常的 `#[test]`，**libtest 与 cargo-nextest 都能照常收集它**（实测 `cargo test` 输出 `test tests::double_reverse_is_identity ... ok`）。这一点很重要：属性测试不是另一套 runner，只是另一个测试体。

它与手写样例的差别在失败时才显出来。把一个错的性质（`v.len() < 5`）跑挂，实测：

```text
proptest: Saving this and future failures in /private/tmp/pt/proptest-regressions/lib.txt
cc 8cdc6bdae1376a7942a4baa07f13c7ffbe41d09db3a26e0e583e866505553bd9

thread 'tests::bad_property' (28809272) panicked at src/lib.rs:8:5:
Test failed: len was 5 at src/lib.rs:11.
minimal failing input: v = [
    0, 0, 0, 0, 0,
]
	successes: 0
```

两个机制：**收缩（shrinking）**把反例自动缩到最小（这里从随机长度缩成 5 个 0），报告的是一个可读的最小复现；**回归持久化**把失败种子写进 `proptest-regressions/` 并带一行 `cc <hash>`，下次运行先重跑这批种子。所以属性测试的随机性是"有记忆的随机"——这个目录必须提交进版本库，否则回归保护就没了。

## Coverage

覆盖率**不是** `cargo test` 的内建选项，它是 rustc 的 codegen 选项：

```bash
RUSTFLAGS="-C instrument-coverage" cargo test     # 1.60.0（2022-04-07）起 stable（据 release notes）
```

实测跑完后当前目录出现若干 `.profraw`（**每个测试二进制一个**，实测三个：`default_1609955556728086024_0_48615.profraw` 等）。`.profraw` 只是原始计数，要变成报告还得合并（`llvm-profdata merge`）再渲染（`llvm-cov show/report`），这两个工具来自 **`llvm-tools` 组件，不是默认安装**。本机实测：

```text
$ rustup component list --installed
cargo / clippy / rust-std / rustc / rustfmt        # 没有 llvm-tools
$ cargo llvm-cov --version
error: no such command: `llvm-cov`
```

所以完整流程通常是 `rustup component add llvm-tools`，或者直接用第三方 `cargo llvm-cov`（`cargo install cargo-llvm-cov`）把三步合成一条命令。**`cargo llvm-cov` 是第三方工具，不是 Cargo 内建子命令**（同类的认知陷阱见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md) 里 `cargo msrv` 那条）。

## cargo-nextest

nextest 是 Rust 的第三方测试 runner（本机实测 `cargo-nextest 0.9.145`）。它与 libtest 最本质的差别是**进程模型**：libtest 一个进程多线程（上文实测三个测试同 pid），nextest **每个测试一个进程**。实测同一份源码：

```text
=== cargo nextest run --no-capture ===
test a pid=46370
        PASS [   0.007s] (1/3) pp tests::a
test b pid=46371
        PASS [   0.007s] (2/3) pp tests::b
test c pid=46372
        PASS [   0.008s] (3/3) pp tests::c
     Summary [   0.022s] 3 tests run: 3 passed, 0 skipped
```

**三个不同的 pid**。由此带来 libtest 给不了的性质：一个测试崩溃/自杀不会影响其他测试（nextest 把它记为 FAIL 而不是丢掉整批）、测试之间无法共享进程状态（顺带消灭了一整类"测试顺序依赖"的 flaky）、以及可以按测试粒度设置超时与重试（`--retries`）。

常用命令：`cargo nextest run` / `cargo nextest list`（实测输出形如 `pt tests::bad_property`）/ `cargo nextest run --no-capture` / `cargo nextest run -E 'test(foo)'`。注意 nextest 用 `--no-capture`，不是 libtest 的 `--nocapture`——它没有 `--` 转发这一层，参数都是自己的。

两条必须知道的边界（均为实测）：**nextest 不跑 doc test**——上文那个有 2 个 doctest 的 crate，`cargo nextest run` 输出 `Starting 0 tests across 1 binary` 直到 `error: no tests to run`；所以 CI 里通常两条都跑：`cargo nextest run` + `cargo test --doc`。"为什么更快"据 nextest 官方文档：每个测试一个进程让它可以**按测试粒度并行调度**（libtest 只能在一个进程内按线程并行，遇到有全局状态的测试就得整体串行），加上更紧凑的输出与跳过失败后停止的开销。这不是本篇实测，按文档记录。

## Miri

Miri 是 UB 解释器，能在 `cargo miri test` 下把测试跑在解释器里、检出越界访问与 aliasing 违规（本体见 [Tooling](/docs/CS/Rust/Tooling.md)）。它**只在 nightly 上分发**，本机 stable 实测：

```text
error: the 'miri' component which provides the command 'cargo-miri' is not available for the 'stable-aarch64-apple-darwin' toolchain
```

所以 `cargo miri test` 是 CI 里的**额外一档 nightly job**，而不是日常 `cargo test` 的替代品：它慢一个数量级，但能抓到 `unsafe` 代码里编译器静态证明不了的问题（见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)）。

## Mocking and Dependency Injection

Rust **没有内建 mock 框架**，也没有内建的"替换函数实现"机制（没有像 Java 那样的字节码织入或动态代理）。原因很直接：Rust 的调用大多是静态派发，编译期就定死了调谁。唯一的出路是**把依赖变成参数**，也就是依赖注入，两种形态对比：

```rust
pub trait Clock { fn now(&self) -> u64; }
pub struct Fixed(u64);
impl Clock for Fixed { fn now(&self) -> u64 { self.0 } }

// 泛型注入：单态化，零虚表开销，但具体类型写进了调用方签名
pub fn is_expired_generic<C: Clock>(c: &C, t: u64) -> bool { c.now() > t }

// trait object 注入：运行时多态，一个函数体，测试里随便换实现
pub fn is_expired_dyn(c: &dyn Clock, t: u64) -> bool { c.now() > t }
```

两种都实测编译并跑通。选择依据就是 [Trait_System](/docs/CS/Rust/Trait_System.md) 里 `impl Trait` / 泛型 与 `dyn` 的取舍：泛型保留静态派发与单态化优化，代价是每个具体类型都要重新编译一份、且类型参数会传染到签名；`dyn` 只编一份、可以在运行时替换，代价是虚表间接调用与要求 object safety。

由此推出 Rust 测试布局的一条硬约束：**"能不能 mock"是在设计函数签名时决定的，不是在写测试时决定的**。想测一个直接调用 `Utc::now()` / `std::fs::read()` 的函数，你改不了测试，只能改签名。这也是 Rust 项目里"把 IO 边界提到参数上"这一习惯的来源。

需要替换整个 crate（比如 HTTP 客户端）时，常见做法是 `#[cfg(test)]` 下换实现、或用 `cfg` 在 dev-dependency 里换一个 fake crate——都不是语言机制，是约定。

## CI: Minimal Form

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - run: cargo test --all-features          # 单元 + 集成 + doc test
      - run: cargo test --doc                   # nextest 用户需要单独补这一条
      - run: cargo clippy -- -D warnings
      - run: cargo fmt -- --check
```

三档 toolchain 矩阵（`rust-version` / stable / nightly）与它们各自抓什么，见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)。一条容易漏的：`cargo test` 默认**不开 feature**，所以 CI 上至少要有一档 `--all-features`，否则 feature 门后的代码常年不被测试。

## Cross-language Comparison

| | Rust | [Go](/docs/CS/Go/Testing.md) | [JUnit](/docs/CS/Java/JUnit.md) | [Python](/docs/CS/Python/Python.md) |
| :-- | :-- | :-- | :-- | :-- |
| 谁提供 runner | 编译器自带 `libtest` + `cargo test` | 标准库 `testing` + `go test` | 外部库 JUnit 5（Maven/Gradle 拉） | 外部 pytest（内建只有 `unittest`） |
| 测试放哪 | 同文件 `#[cfg(test)] mod tests` 或 `tests/` | 同包 `_test.go` 文件 | 独立 `src/test/java` 源码树 | 独立 `tests/` 目录或 `test_*.py` |
| 能否测私有 | **能**（测试模块是子模块） | 能（同 package 的测试文件可访问未导出标识符） | 靠包级可见或反射 | 能（无强制私有） |
| 并行模型 | 默认多线程同进程（nextest 改为每测试一进程） | 默认包级并行，包内串行（`-parallel`） | 由 JUnit 5 / 构建插件配置 | pytest-xdist 插件，进程级 |
| 断言 | 宏，`assert_eq!` 打印 `Debug` | 手写 `if got != want { t.Errorf(...) }` | `Assertions.assertEquals` 静态方法 | 裸 `assert`（重写断言以获得报错细节） |
| 基准测试 | **无内建**（`#[bench]` 已移除，用 criterion） | 内建 `testing.B` + `go test -bench` | 需 JMH（JVM 预热问题） | `pytest-benchmark` |
| 属性测试 | proptest（第三方） | `testing/quick`（标准库） | jqwik（第三方） | Hypothesis（第三方） |
| 覆盖率 | `-C instrument-coverage` + `llvm-tools`（第三方封装） | **内建** `go test -cover` | JaCoCo 等（字节码插桩） | `coverage.py` / `pytest-cov` |

最显眼的一列是**基准测试**：Go 把 bench 做成标准库一等公民（`func BenchmarkX(b *testing.B)` 直接跑），Rust 的内建 bench 则被整个撤掉——这正好是 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md) 里"stable 化可以撤销"的兑现。代价是 Rust 项目必须自己选第三方方案，收益是 criterion 这类工具的统计能力远强于当年的内建 `#[bench]`。

第二处结构性差别是**可见性**：Rust 靠"测试模块是子模块"拿到私有访问权（语言机制），Go 靠"测试文件在同一个 package"（约定），Java 靠包级可见性或反射（外部机制）。三者都能做到，但 Rust 这条是唯一**不需要为测试放宽任何可见性声明**的。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Languages](/docs/CS/Languages.md)
- [Concurrency](/docs/CS/Rust/Concurrency.md)

## References

- [The Rust Programming Language — Writing Tests](https://doc.rust-lang.org/book/ch11-00-writing-tests.html)
- [Rust By Example — Unit testing / Documentation testing](https://doc.rust-lang.org/rust-by-example/testing/unit_testing.html)
- [Rust Reference — The `test` attribute](https://doc.rust-lang.org/reference/attributes/testing.html)
- [The Cargo Book — cargo test](https://doc.rust-lang.org/cargo/commands/cargo-test.html)
- [The Cargo Book — cargo bench](https://doc.rust-lang.org/cargo/commands/cargo-bench.html)
- [The Cargo Book — Benchmark targets / harness](https://doc.rust-lang.org/cargo/reference/cargo-targets.html#benchmarks)
- [The Cargo Book — Profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)
- [rustdoc — Documentation tests](https://doc.rust-lang.org/rustdoc/write-documentation/documentation-tests.html)
- [rustc Book — Codegen options: instrument-coverage](https://doc.rust-lang.org/rustc/codegen-options/index.html#instrument-coverage)
- [rustc Book — Source-based Code Coverage](https://doc.rust-lang.org/rustc/instrument-coverage.html)
- [Criterion.rs — User Guide](https://bheisler.github.io/criterion.rs/book/index.html)
- [proptest — Book](https://proptest-rs.github.io/proptest/intro.html)
- [cargo-nextest — Documentation](https://nexte.st/book/how-it-works.html)
- [Miri — README](https://github.com/rust-lang/miri)
- [Rust release notes — Compatibility Notes index](https://doc.rust-lang.org/stable/releases.html)
