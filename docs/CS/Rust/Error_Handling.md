## Introduction

Rust 没有异常。它的取舍是**把"失败"拆成两条互不相通的通道**：可恢复的失败进类型（`Option<T>` / `Result<T, E>`，编译器逼调用方分支），不可恢复的失败进控制流（`panic!`，展开栈并结束线程）。`?` 不是第三条通道，它只是"从类型里取值，取不到就换成外层错误类型回到调用方"的语法糖。

代价搬到哪里是理解一切的关键：**Java / Python 放在运行期**（抛出时抓栈、展开、匹配 `catch`），**Go 放在源码里**（每个调用点一次 `if err != nil`），**Rust 放在类型签名与编译期**（`Result` 是普通枚举，`?` 是一次 `From` 调用，展开栈只发生在"这是 bug"的路径上）。本篇讲 `?` 的真实展开与它至今未完成的扩展性、panic 作为 bug 通道的真实约束、错误类型三件套与 `thiserror` / `anyhow` 的分工、以及断言宏与 FFI 边界这些承重墙。析构顺序与 unwind 的交互见 [Drop](/docs/CS/Rust/Drop.md)，`unreachable_unchecked` 与 UB 边界见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)，`Result` 在 async 里的取消语义见 [Async](/docs/CS/Rust/Async.md)。

## Two Channels of Failure

### Option and Result Are Plain Enums

两者都是普通泛型枚举，`unwrap` / `map` / `and_then` 只是方法而非语言特性。它们值得单列，是因为 **niche 优化让"带错误信息的返回值"常常不比裸值贵**（`rustc 1.98.1`，`aarch64-apple-darwin`，`-O` 与 debug 结果一致；基线 `*const u8` 是 8 字节）：

| 类型 | size | align | 说明 |
| :-- | :-- | :-- | :-- |
| `Option<&u8>` | 8 | 8 | 全零位表示 `None`，与裸指针同宽 |
| `Result<&u8, Infallible>` | 8 | 8 | 不可能失败的 `Result` 不额外占位 |
| `io::Error` | 8 | 8 | 本身已是装箱枚举 |
| `Result<(), io::Error>` | 8 | 8 | 与 `io::Error` 同宽 |
| `Box<dyn Error>` | 16 | 8 | 胖指针：数据指针 + vtable 指针 |
| `Result<(), Box<dyn Error>>` | 16 | 8 | niche 落在指针上 |
| `Result<u8, u8>` | 2 | 1 | 没有可用 niche，老实加一个判别字节 |

两点必须记住。`Option<&T>` / `Option<Box<T>>` 与裸指针同宽是 **std `mem::size_of` 文档级保证**（文档明列 `*const T`、`&T`、`Box<T>`、`Option<&T>`、`Option<Box<T>>` 同大小）；但 **`Result` 的布局没有任何稳定保证**——1.97.0 的 Compatibility Notes 反过来明确"不要对枚举布局做假设"，某些枚举的编码确实变过。要冻结布局只能自己上 `#[repr(...)]`，机制见 [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)。

### Where the Boundary Sits

判据不是"人还能不能救"，而是**调用方有没有决策空间**：

| 情形 | 通道 | 理由 |
| :-- | :-- | :-- |
| 文件不存在、端口被占、数字解析失败 | `Result` | 调用方可换路径、重试、降级、报错给用户 |
| 下标越界、`unwrap()` 到 `None`、内部不变量被破坏 | `panic` | 说明这一层之前的代码写错了，换调用方也救不回来 |
| 栈溢出、展开途中再 panic、分配失败 | abort | 已无法保证还能执行任何 Rust 代码 |

`std` 自己就照这条线切：`Vec::get` 返回 `Option` 而 `v[i]` 越界 panic；`str::parse` 返回 `Result` 而 `String::from_utf8_unchecked` 返回 UB。选哪条通道就是选"错误由谁决定"。

## The Question Mark Operator

### It Is a Conversion Not an Early Return

`?` 展开后不是 `return`，而是**一次带类型转换的提前返回**。对 `Result` 而言稳定语义是 `FromResidual`，落到具体转换上就是 `From`（这两个错误类型甚至不需要实现 `Error`，`?` 只关心 `From`）：

```rust
#[derive(Debug)] struct Inner(&'static str);
#[derive(Debug)] struct Outer(&'static str);
impl From<Inner> for Outer { fn from(e: Inner) -> Self { Outer(e.0) } }
fn inner() -> Result<u8, Inner> { Err(Inner("bad")) }
fn with_q() -> Result<u8, Outer> { Ok(inner()?) }
fn desugared() -> Result<u8, Outer> { match inner() { Ok(v) => Ok(v), Err(e) => Err(From::from(e)) } }
```

删掉 `impl From<Inner> for Outer`，`with_q` 立刻编译不过而 `desugared` 改报 E0308——这正好证明 `?` 的隐藏内容就是 `From::from`。两个自定义错误类型 `A` / `B` 之间缺 `impl From<A> for B` 时的实测诊断：

```text
error[E0277]: `?` couldn't convert the error to `B`
10 | pub fn outer() -> Result<u8, B> { let x = inner()?; Ok(x) }
   |                   -------------           -------^ the trait `From<A>` is not implemented for `B`
   = note: the question mark operation (`?`) implicitly performs a conversion on the error value using the `From` trait
```

最后那行 note 是整件事的说明书：**`?` 只做一件事——把内层错误塞进外层错误类型；塞不进去是编译错误，不是运行期意外**。

### Why the Enclosing Return Type Must Match

`?` 能否出现，取决于**所在函数的返回类型是否接受这个 residual 类型**。三类典型误用的实测措辞各不相同，第三条甚至把修复方案写进了消息里：

```text
error[E0277]: the `?` operator can only be used in a function that returns `Result` or `Option` (or another type that implements `FromResidual`)
  | pub fn f(x: Option<u8>) -> i32 { let v = x?; v as i32 }

error[E0277]: the `?` operator can only be used on `Result`s, not `Option`s, in a function that returns `Result`
  | pub fn g(x: Option<u8>) -> Result<u8, String> { let v = x?; Ok(v) }
  | use `.ok_or(...)?` to provide an error compatible with `Result<u8, String>`

error[E0277]: the `?` operator can only be applied to values that implement `Try`
  | pub fn h(x: u8) -> Result<u8, String> { Ok(x?) }
  = help: the nightly-only, unstable trait `Try` is not implemented for `u8`
```

`Option` 与 `Result` 之间**不会自动跨通道**：`Option` 里没有错误信息可搬，所以在返回 `Result` 的函数里遇到 `Option` 必须你亲手补一个错误；反过来 `Result` 上的 `?` 在返回 `Option` 的函数里可用（错误被丢掉）：

```rust
pub fn q_on_option(o: Option<u8>) -> Option<u8> { Some(o?) }
pub fn q_in_result(o: Option<u8>) -> Result<u8, String> { let v = o.ok_or_else(|| "missing".to_string())?; Ok(v) }
pub fn collect_results(v: &[String]) -> Result<Vec<u32>, std::num::ParseIntError> { v.iter().map(|s| s.parse::<u32>()).collect() }
```

最后一个是 `?` 之外最常用的传播手法：`collect` 的目标类型是 `Result<Vec<_>, E>` 时任一元素失败即整体失败，它同样靠 `FromResidual`，因此在 stable 可用。判断"`?` 能不能用"的正确问法永远是：**所在函数的返回类型是否实现了接受这个 residual 的 `FromResidual`**，而 stable 上这个集合只有 `Option`、`Result` 和 `main` 的 `Termination`。

### Question Mark in main

`fn main()` 默认返回 `()`，用不了 `?`。自 **1.26.0 (2018-05-10)** 起 `main` 可返回 `Result<(), E>`（要求 `E: Debug`）；**1.58.0** 补上 `impl Termination for Result<Infallible, E>`，于是 `fn main() -> Result<Infallible, E>` 这种"只可能失败"的写法也合法。返回 `Err` 时 std 做的是**用 `Debug` 打印再返回退出码 1**（实测）：

```rust
use std::error::Error;
fn main() -> Result<(), Box<dyn Error>> { let _f = std::fs::File::open("nope-does-not-exist")?; Ok(()) }
```

```text
Error: Os { code: 2, kind: NotFound, message: "No such file or directory" }   # exit=1
```

打印的是 `Debug` 而非 `Display`——这就是为什么 `io::Error` 的 `Debug` 形态信息量比 `Display` 大，也是为什么真正的 CLI 不把 `main` 的 `Result` 当输出层（要自己 `eprintln!("{e:#}")`，见 anyhow 一节）。

### std::ops::Try Is Still Unstable

大量教程写"`?` 可扩展到你自己的类型，实现 `std::ops::Try` 即可"。**这句话到今天仍不成立。**

```rust
use std::convert::Infallible;
use std::ops::FromResidual;
pub struct My;
impl FromResidual<Result<Infallible, u8>> for My { fn from_residual(_r: Result<Infallible, u8>) -> Self { My } }
```

```text
error[E0658]: use of unstable library feature `try_trait_v2`
  = note: see issue #84277 <https://github.com/rust-lang/rust/issues/84277> for more information
```

`Try` / `FromResidual` / `Branch` 整套都在 `try_trait_v2`（含 `_residual`、`_yeet`）之下，stable 只允许内置类型用。结论：**`?` 的语义是闭集，可组合性靠 `From` 而不是靠自定义 `Try`**。漏到 stable 的只有半边——`std::ops::ControlFlow<B, C>` 是 `Try::branch` 的返回类型，本身可用（`is_break` / `is_continue` 自 **1.95.0** 稳定），能表达"`?` 版的循环提前退出"：

```rust
use std::ops::ControlFlow;
fn scan() -> ControlFlow<&'static str> { let mut sum = 0u8; [1u8, 2, 3, 4].iter().try_for_each(|x| { sum += x; if sum > 4 { ControlFlow::Break("overflow-ish") } else { ControlFlow::Continue(()) } }) }
```

但让它真正顶替 `Result` 的那批方法（`try_bind`、`into_result`）在 1.98.1 上取不到，所以 `ControlFlow` 目前只是 `try_trait_v2` 的预留地基，不是第三种错误通道。

## unwrap expect and panic

### What a panic Costs

`panic!` 默认**展开栈**（unwind）：逆着栈帧跑析构，再把控制权交给最近的 `catch_unwind` 或线程边界。**`panic = "abort"` 不是 release 的默认值**——Cargo 文档列出的内建 profile（含 `[profile.release]`）默认全是 `panic = 'unwind'`，只有显式 `panic = "abort"` / `-C panic=abort` 才换成直接终止。两者差别实测（源码是 `let r = catch_unwind(|| panic!("caught?")); println!("err = {}", r.is_err());`）：

```text
$ rustc --edition 2024 app.rs && ./app            # 默认 unwind
thread 'main' panicked at app.rs:2:41: caught?
err = true
$ rustc --edition 2024 -C panic=abort app.rs && ./app
thread 'main' panicked at app.rs:2:41: caught?    # println 那行永远没跑到, exit=134
```

`abort` 构建下 `catch_unwind` 照样编译通过、照样接不住——它**静默失效**，没有任何编译期提示，只是进程没了。这是嵌入式与体积敏感场景必须知道的坑（换来的是省掉 landing pad 体积）。`Result` 一侧没有这些：它是值，代价只是判别字节上的一次分支，所以"用 panic 当控制流"既写不成惯用法、也确实贵。

`unwrap` / `expect` 的消息是排障现场第一手材料，格式很固定（实测原文）：`called `Option::unwrap()` on a `None` value`、`called `Result::unwrap()` on an `Err` value: Kind(NotFound)`、`expect("load config")` 打印 `load config`、`Err(42u8).expect("bad")` 打印 `bad: 42`。即 `unwrap` 用固定模板 + 内层错误的 `Debug`，`expect(msg)` 用 `msg`（必要时 `msg: {err:?}`）。**`unwrap()` 能带出 `Err` 里的信息，但只带 `Debug`**——这又一次要求错误类型把信息放进字段而不是放进 `Display` 文案。

### catch_unwind Is Not try and catch

`std::panic::catch_unwind(F)` 的约束写在类型上：`F: FnOnce() -> R + UnwindSafe`。它的用途极窄——隔离一段你认为可能炸掉但不该带走整个进程的代码（解释器、插件宿主、线程池边界），**不是异常处理**。编译期会拦"跨 unwind 边界的可变借用"，std 把理由说得很直白（实测，源码是 `catch_unwind(|| { c.set(1); })` 配 `c: &Cell<i32>`、`catch_unwind(|| { *m += 1; })` 配 `m: &mut i32`）：

```text
error[E0277]: the type `UnsafeCell<i32>` may contain interior mutability and a reference may not be safely
transferable across a catch_unwind boundary
  = help: within `Cell<i32>`, the trait `RefUnwindSafe` is not implemented for `UnsafeCell<i32>`
  = note: required for `&Cell<i32>` to implement `UnwindSafe`

error[E0277]: the type `&mut i32` may not be safely transferred across an unwind boundary
```

`RefUnwindSafe` 表示"这个类型内部没有在就地改的东西"，`UnwindSafe` 表示"拿它的引用跨边界是安全的"。于是 `&mut T` 一律不满足（它承诺独占，而 panic 会让承诺停在半路），`Cell` / `UnsafeCell` 一律不满足（内部可变性 + 半途而废 = 可能观测到撕裂状态）。反过来 `Mutex<i32>` 实测可以直接进 `catch_unwind`——**因为 std 用 poisoning 把"数据可能不一致"编码进了运行期状态**，锁机制承担了 `UnwindSafe` 承担不了的那部分（见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)）。

绕开只有 `AssertUnwindSafe`：`catch_unwind(AssertUnwindSafe(|| { c.set(1); }))`（实测可编译；1.96.0 起还有 `From<T> for AssertUnwindSafe`，能 `.into()` 少写一层嵌套）。它不改变任何事实，只是把判断责任从类型系统挪回你手上——这也是关于 `UnwindSafe` 长期争议的实质：它真正能表达的只有"捕获后我不去读可能被就地改过的东西"，而"panic 之后这个数据结构还能不能用"是逻辑问题，其自动推导规则既不严格也不宽松。实践结论很朴素：**要么捕获后立刻丢弃全部状态，要么大方写 `AssertUnwindSafe` 并接受它是免责声明**，别把它当 C++ 的 `noexcept` 或 Java 的类型化异常层次。

**它也不保证抓得住。** 其一是**展开途中再 panic**（最常见是析构里 panic），`catch_unwind` 在场也救不了（实测）：

```text
thread 'main' panicked at app.rs:5:58: first panic
thread 'main' panicked at app.rs:2:43: second panic inside drop
thread 'main' panicked at .../library/core/src/panicking.rs:233:5: panic in a destructor during cleanup
thread caused non-unwinding panic. aborting.        # exit=134
```

其二是 `-C panic=abort`（静默失效，见上一节）；其三是**外来异常**（C++ 抛过来的等），1.48.0 起会被 `catch_unwind` 捕获但紧接着 abort，std 明确写了"该行为不保证、仍算 UB"。析构与展开的完整机制见 [Drop](/docs/CS/Rust/Drop.md)。

## Designing an Error Type

### Display Debug and Error

三件套的分工不是风格问题，而是**给谁读**：`Debug` 给机器和日志（结构可枚举），`Display` 给最终用户（一句话），`Error` 给链（`source()`）。`Error` 的超边界是 `Debug + Display`，只 derive `Debug` 就写 `impl Error` 实测报 `E0277: E doesn't implement std::fmt::Display`（note 指向 `library/core/src/error.rs`）。`io::Error` 是最好的示范——同一个值两种读法（实测）：`Display` 给 `denied`，`Debug` 给 `Custom { kind: PermissionDenied, error: "denied" }`，判别走 `kind()`。**把信息只写进 `Display` 字符串，等于让调用方去 parse 你自己的文案。**

### Walking the source Chain

`Error::source()` 是链的唯一稳定入口，**默认实现返回 `None`，不 override 就没有链**（实测）。链要**手动走**，因为 std 到今天还没有迭代器版本的链：`e.sources().count()` 实测报 `E0658: use of unstable library feature error_iter`（issue #58520），一些旧书里的 `std::error::SourceError` 在 stable 上更是不存在（实测 `E0425: cannot find type SourceError in module std::error`）：

```rust
use std::error::Error;
use std::fmt;
#[derive(Debug)] struct Parse { got: String }
impl fmt::Display for Parse { fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "cannot parse `{}`", self.got) } }
impl Error for Parse {}
#[derive(Debug)] struct Wrap { ctx: String, src: Parse }
impl fmt::Display for Wrap { fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "{}", self.ctx) } }
impl Error for Wrap { fn source(&self) -> Option<&(dyn Error + 'static)> { Some(&self.src) } }
fn walk(e: &dyn Error) { let (mut cur, mut i) = (Some(e), 0); while let Some(x) = cur { println!("{i}: {x}"); cur = x.source(); i += 1; } }
```

```text
0: reading config
1: cannot parse `tru`
```

需要链就自己 while-let，或者用 anyhow 的 `chain()`。

### Box<dyn Error> Has Real Limits

它的用处是"我不关心错误的具体类型，只要能打印、能追链"。`?` 能直接把它当外层错误，是因为 std 为 `Box<dyn Error>` 及 `+ Send` / `+ Send + Sync` 两个变体提供了针对 `E: Error + 'static` 的 blanket `From`（实测无需自己写 impl）：

```rust
use std::error::Error;
pub fn via_box(x: Result<u8, std::num::ParseIntError>) -> Result<u8, Box<dyn Error>> { Ok(x?) }
```

限制有三条：它是胖指针（实测 `size_of::<Box<dyn Error>>() == 16`，`Result<(), Box<dyn Error>>` 也是 16）；擦除类型就丢了判别（`downcast_ref::<T>()` 是 `dyn Error` 的方法，在 concrete 类型上写会报 `E0599: no method named downcast_ref found for struct Wrap`，而且只能取回最外层那个类型——实测 `e.downcast_ref::<Parse>()` 在 `Wrap` 上返回 `None`，必须 `e.source().and_then(|s| s.downcast_ref::<Parse>())`）；它不 `Send`，跨线程即炸：

```text
error[E0277]: `dyn std::error::Error` cannot be sent between threads safely
  = help: the trait `Send` is not implemented for `dyn std::error::Error`
```

并发边界上的错误类型要写成 `Box<dyn Error + Send + Sync>`，代价是内层错误也必须满足这两个 auto trait。

### Error::provide Is Still Unstable

"错误对象携带任意类型化上下文"（像 anyhow 的 `downcast` 直达任意层）同样没稳定：给一个已实现 `Debug + Display` 的类型 `E` 写 `fn provide<'a>(&'a self, _req: &mut std::error::Request<'a>) {}`，实测报 `E0658: use of unstable library feature error_generic_member_access`（issue #99301）。`Error::provide` 与 `std::error::Request` 全在这个 gate 下，所以**"错误链 + 类型化成员提取"今天仍是生态解决的事，不是 std 解决的事**。

### thiserror for Libraries anyhow for Binaries

`thiserror`（当前 **2.x**）只替你写三件套里的机械部分：`Display`、`Error`、`From`。本机 `thiserror 2.0.20` + `anyhow 1.0.103` 离线编译实测：

```rust
use std::error::Error;
use std::path::PathBuf;
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("reading {path}")]
    Read { path: PathBuf, #[source] src: std::io::Error },
    #[error("bad number")]
    Parse(#[from] std::num::ParseIntError),
}
pub fn parse(input: &str) -> Result<u32, ConfigError> { Ok(input.trim().parse()?) }
pub fn load(path: PathBuf) -> Result<u32, ConfigError> {
    let s = std::fs::read_to_string(&path).map_err(|e| ConfigError::Read { path, src: e })?;
    parse(&s)
}
pub fn to_anyhow(path: PathBuf) -> anyhow::Result<u32> { Ok(load(path)?) }
pub fn box_send(e: anyhow::Error) -> Box<dyn Error + Send + Sync> { Box::from(e) }
```

生成的东西完全对得上前面的模型：`#[error("...")]` 是 `Display`，`#[from]` 是 `impl From<...>`（于是 `parse()?` 直接可用），`#[source]` 是 `source()` override。运行期 `Display` 给 `bad number`、`Debug` 给 `Parse(ParseIntError { kind: InvalidDigit })`、`Error::source()` 给 `Some("invalid digit found in string")`。

`anyhow`（当前 **1.0.x**）反过来：一个不透明的 `anyhow::Error`，靠 `context()` 往上叠话，靠 `{:#}` 一次打全链。它是应用层的 `Result` 别名（`anyhow::Result<T>` = `Result<T, anyhow::Error>`），另有 `bail!` / `ensure!`：

```rust
pub fn demo() {
    let e = parse("12x").map_err(|er| anyhow::Error::new(er).context("loading /etc/app.conf")).unwrap_err();
    println!("{e:#}");                                   // 全链一次打完
    println!("{}", e.root_cause());
    for (i, c) in e.chain().enumerate() { println!("chain[{i}] = {c}"); }
    println!("{:?}", e.downcast_ref::<ConfigError>());
}
```

```text
loading /etc/app.conf: bad number: invalid digit found in string
root_cause = invalid digit found in string    chain[0..2] = loading /etc/app.conf / bad number / invalid digit found in string
downcast = Some(Parse(ParseIntError { kind: InvalidDigit }))
```

两条容易踩空的实测事实。**`#[from]` 不允许变体里还有别的字段**，报的是 thiserror 自己的话而不是类型错：`error: deriving From requires no fields other than source and backtrace`，且派生失败会紧接着让 `parse()?` 报 `E0271: type mismatch resolving <u32 as FromStr>::Err == ConfigError`；要上下文就 `#[source]` + 手写 `From`，或者像 `Read` 那样把上下文放进 `Display` 模板。**`anyhow::Error` 不实现 `std::error::Error`**：`Box::new(e) as Box<dyn Error>` 实测 `E0277: the trait bound anyhow::Error: std::error::Error is not satisfied`——它故意做成这样（透明表示 + 避免自我嵌套），只提供了专门的 `From<anyhow::Error> for Box<dyn Error + Send + Sync>`，所以 anyhow 只能站在链的**最外层**，不能当内层 source。

### Why the Two Roles Diverge

| 维度 | 库作者（thiserror） | 二进制作者（anyhow） |
| :-- | :-- | :-- |
| 调用方是谁 | 别人，且需要 `match` 你的错误做决策 | 自己，最终只要一行日志或一个退出码 |
| 错误类型是否公开 API | 是，改动即破坏 | 否，随便演进 |
| 判别方式 | 枚举变体 + `#[from]` 生成的 `From` | `downcast_ref::<T>()` / `chain()` |
| `Display` 里放什么 | 该变体的一句话（不含链） | `{:#}` 一次打全链 |
| 额外成本 | 无（零装箱） | 每层 context 一次装箱与类型擦除 |
| 混用后果 | 库内部依赖 `anyhow` 是常见反模式：把决策权外包给调用方 | 在 `main` / CLI / 服务入口收口是正解 |

`to_anyhow` 那一行是这套分工的接缝：anyhow 有针对 `E: Error + Send + Sync + 'static` 的 blanket `From`，所以库的 `ConfigError` 进 `anyhow::Result` 时不需要 `map_err`——`?` 自己就完成了升级。

## Termination and Exit Codes

`main` 的返回值不受 `Result` 限制：**1.61.0 (2022-05-19)** 稳定了 `std::process::Termination` 与 `std::process::ExitCode`，任何实现 `Termination` 的类型都能当 `main` 的返回类型（stable 实测，运行后 `echo $?` 得 `73`）：

```rust
use std::process::ExitCode;
pub struct Fail(u8);
impl std::process::Termination for Fail { fn report(self) -> ExitCode { ExitCode::from(self.0) } }
fn main() -> Fail { Fail(70 + std::hint::black_box(3)) }
```

这条通道与 `std::process::exit` 的分工：`ExitCode` 走 `main` **正常返回**的路径（析构照跑、输出照刷），`exit` 直接终止进程、绕过这一层。CLI 要精确控制退出码（区分"用法错误 2"与"运行失败 1"）就用前者，别在深层代码里 `exit`。

## From TryFrom and the Conversion Etiquette

`?` 靠 `From` 转换错误，因此 **`From` 就是错误传播的公开 API**：两条推论——给每个可能出现在 `?` 右侧的内层错误写 `From`；同一个外层错误不要为两个源类型写会冲突的 `From`。可能失败的转换走 `TryFrom` / `TryInto`（`From` / `Into` 的失败版对偶，`TryFrom` 还要求你选一个携带上下文的 `Error` 类型），注意 **prelude 的 edition 差异**：`TryFrom`、`TryInto`、`FromIterator` 自 **edition 2021** 才进 prelude，2015 / 2018 不 `use` 就报 `E0599: no associated function or constant named try_from found for type u8`，并附 `help: trait TryFrom ... perhaps you want to import it`（实测）。

零成本的"不可能失败"要写进类型而不是注释，那就是空枚举 `Infallible`。但**`Result<_, Infallible>` 上的 `?` 在 stable 上行不通**——std 没有 `impl From<Infallible> for E`（实测 `E0277: the trait From<Infallible> is not implemented for String`）。正确写法是在类型层面消灭它（空枚举无构造方式，`Err` 分支可穷尽）：

```rust
use std::convert::Infallible;
pub fn infallible_match(x: Result<u8, Infallible>) -> Result<u8, String> { Ok(match x { Ok(v) => v, Err(e) => match e {} }) }
```

顺带区分两件常被混谈的事：`match x {}` 匹配空枚举是 stable；`!` 作为**类型**（never type）至今 unstable（`never_type`，`fn f(x: !)` 实测报 `E0658: the ! type is experimental`）。

## The Assertion Ladder

断言宏是错误处理里被忽略的一层：它们全走 panic，区别只在**什么构建下还存在**、**失败时说什么**、**能不能挪到编译期**。

| 宏 | 何时生效 | 失败消息（实测） | 用途层次 |
| :-- | :-- | :-- | :-- |
| `debug_assert!` / `debug_assert_eq!` | 仅 `debug_assertions`（dev 默认开，release 默认关） | `assertion failed: <表达式原文>` | 内部不变量、代价敏感的边界检查 |
| `assert!` / `assert_eq!` / `assert_ne!` | 永远 | `assertion failed: <cond>`；比较版另起两行打印 left / right | 参数前置条件、公开不变量 |
| `assert_matches!` | 永远（**1.96.0** 稳定，同批的 `debug_assert_matches!` 仅 debug） | 打印值与模式 | 枚举形态检查 |
| `unreachable!` | 永远 | `internal error: entered unreachable code: <msg>` | 编译器可证但你想留话的分支 |
| `todo!` | 永远 | `not yet implemented: <msg>` | 占位，不是错误处理 |
| `unimplemented!` | 永远 | `not implemented: <msg>` | 特性或平台缺口 |
| `compile_error!` | 编译期 | 你写的消息，指向宏调用处 | 把语义错误前移到编译期 |

`debug_assert!` 的层次差别比"多一行检查"尖锐：**整个表达式连同副作用一起消失**。同一个 `debug_assert!({ bump(); v < 1 })` 在 debug 构建下报 `app.rs:5:5: assertion failed: { checks.set(checks.get() + 1); v < 1 }`，在 `-O` 下计数器一次都没加过（实测 `conditions evaluated = 1 (debug_assertions = false)`，那 1 次来自 `assert!`）。写在 `debug_assert!` 里的计数器、缓存填充、日志副作用，release 下**一次都不会跑**——把它当廉价保险到处塞，就会得到只在 debug 复现的行为。

`compile_error!` 是这条梯子的顶点，把错误从"运行期 panic / 返回 Err"推到"编译失败"，常与 `cfg` 或 const 求值配合（实测 `pub const fn pick(n: u8) -> u8 { if n > 4 { compile_error!("only up to 4"); } n }`）：

```text
error: only up to 4
2 |     if n > 4 { compile_error!("only up to 4"); }
  |                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

## Panics at the FFI Boundary

`extern "C"` 函数不允许 unwind（C 的 ABI 没有 unwind 表，且历史约定跨 FFI 抛异常是 UB）。Rust 的做法是**在边界上把 panic 换成 abort**，但先正常跑完析构（实测，`Guard` 的 `Drop` 打印一行）：

```text
thread 'main' panicked at app.rs:3:43: panic across C boundary
drop glue ran
thread 'main' panicked at .../library/core/src/panicking.rs:225:5: panic in a function that cannot unwind
thread caused non-unwinding panic. aborting.        # exit=134
```

顺序很关键：**drop glue 先跑完，然后 abort**。所以边界上的资源释放靠析构是可靠的，但进程必死——C 侧一行 `setjmp` 也救不回来。想让 panic 穿过边界必须双方共同同意：`extern "C-unwind"`（**1.71.0 (2023-07-13)** 稳定）及 `extern "system-unwind"` 等变体。推论到工程：导出给 C 的函数应返回错误码，或让 C 传指针回来收错误；跨语言边界不要指望携带 Rust 的 `Result`。UB 侧的完整边界见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Errors in Logs and Traces

`Result` 与 `panic` 都不负责"事后看得见"：`Display` / `{:#}` 只是**呈现层**，把它接进结构化日志与 span 属生态层的事（`tracing` 的 span 与事件字段常直接收 `&dyn Error` 或 `anyhow::Error`），选型与用法见 [Ecosystem](/docs/CS/Rust/Ecosystem.md)。

## Cross-language Comparison

| 维度 | Rust | Go | Java | Python |
| :-- | :-- | :-- | :-- | :-- |
| 失败进哪里 | 类型（`Result`）+ 控制流（panic 只留给 bug） | 类型（返回值里的 `error`） | 两者（checked / unchecked 分裂） | 控制流（异常） |
| 编译器是否强制处理 | 是，`?` / `match` 才写得通（不消费 `Result` 只警告） | 是，不写 `if err != nil` 就是丢值 | checked exception 必须 catch 或 `throws` | 否，签名完全不体现 |
| 跨层传播与错误链 | `?` 附带一次 `From`；链靠 `source()` 手动走或 anyhow `chain()` | `fmt.Errorf("%w")` 建链，`errors.Is` / `As` 判定 | `throw` + `throws`；链靠 `getCause()` | `raise`；链靠 `__cause__` / `__context__` |
| 多路失败聚合 | 自己攒 `Vec<Error>`（std 无 ExceptionGroup 等价物） | `errors.Join`（Go 1.20） | `Suppressed` 异常 | `ExceptionGroup` + `except*`（3.11） |
| 栈信息在哪 | 只在 panic 路径上，`Result` 不带栈 | 不带栈（社区最大痛点） | 构造即 `fillInStackTrace`，昂贵 | traceback 完整保留 |
| **谁承担控制流成本** | **写代码的人**：类型签名与 `From` impl；运行期零展开 | **每个调用点的读者**：一次分支，代码冗长 | **抛的一方**：抓栈 + 展开 | **抛的一方**：解释器展开；捕获方要靠层级约定沟通 |
| 崩溃的进程语义 | 默认展开到线程边界，线程死进程活；`abort` 则全死 | `panic` 默认打死进程，`recover` 只在 defer 里有效 | 未捕获的 `Error` 打死线程 | 顶层未捕获即 traceback 退出 |

分歧其实是同一件事：**把错误放进类型系统，还是放进控制流**。Rust 是唯一把"错误转换本身"做成类型系统成员的语言（`?` = `From`），所以样板最少而签名信息量最大；代价是 `Error` 侧的可组合性至今没在 std 闭环（`Try`、`sources()`、`provide` 全在 nightly），链条靠 `thiserror` / `anyhow` 补齐。顺带纠正一处常见说法：Rust 的 panic **载荷确实能跨线程**——stable 上 `join()` 的 `Err` 分支类型就是 `Box<dyn Any + Send>`（实测可 `downcast_ref::<&str>()` 拿回 `"worker died 7"`），但 `std::thread::JoinError` 这个包装类型在 1.98.1 上仍不存在，载荷的类型化没有任何保证。对照实现见 [Go 的 error 与包装链](/docs/CS/Go/Errors.md)、[Python 异常链与 ExceptionGroup](/docs/CS/Python/Exceptions.md)、[Java Throwable 层级](/docs/CS/Java/JDK/Basic/Throwable.md)、[Go panic/recover](/docs/CS/Go/Panic.md)。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Ownership](/docs/CS/Rust/Ownership.md)
- [Drop](/docs/CS/Rust/Drop.md)
- [Ecosystem](/docs/CS/Rust/Ecosystem.md)
- [Errors](/docs/CS/Go/Errors.md)
- [Exceptions](/docs/CS/Python/Exceptions.md)

## References

- [std::error::Error](https://doc.rust-lang.org/std/error/trait.Error.html)
- [std::ops::Try](https://doc.rust-lang.org/std/ops/trait.Try.html)
- [rust-lang/rust#84277 — Try trait v2 tracking issue](https://github.com/rust-lang/rust/issues/84277)
- [rust-lang/rust#99301 — error_generic_member_access tracking issue](https://github.com/rust-lang/rust/issues/99301)
- [rust-lang/rust#58520 — Error::sources tracking issue](https://github.com/rust-lang/rust/issues/58520)
- [std::panic::catch_unwind](https://doc.rust-lang.org/std/panic/fn.catch_unwind.html)
- [std::process::Termination](https://doc.rust-lang.org/std/process/trait.Termination.html)
- [Cargo Profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)
- [Edition Guide — Rust 2021 prelude](https://doc.rust-lang.org/edition-guide/rust-2021/prelude.html)
- [thiserror 2.x](https://docs.rs/thiserror/latest/thiserror/)
- [anyhow 1.0.x](https://docs.rs/anyhow/latest/anyhow/)
