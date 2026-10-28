## Introduction

`Pin` 是 Rust 里最被误解的机制，误解的根源在名字：它听起来像"禁止移动的运行时机制"，实际是**一个包装指针 + 一句编译期承诺**——"被指的值从此不再移动"。为什么需要这句承诺？因为 `async fn` 编译出的状态机**可能引用自己的字段**：`v` 与指向它的 `r` 在同一个结构体里，一旦值被移动，`r` 就指向旧地址，这是真实的悬垂。

同一事实的另一半写在 `Future::poll` 的签名上：

```rust
fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output>;
```

`self` 的类型本身就是文档——**任何 poll 你的代码都承诺了在本次 `Ready` 之前不动你**。执行器（tokio 的 task、`block_on` 的循环）负责先 pin 再 poll，语言和标准库负责让"移动一个已 pin 的值"在安全代码里不可能发生。

语言侧的 `Future` / `poll` / `Waker` 归 [Async](/docs/CS/Rust/Async.md)，调度与运行时归 [Async_Runtime](/docs/CS/Rust/Async_Runtime.md)；本篇只讲 `Pin` 本身。

> [!NOTE]
> 本页事实以 `doc.rust-lang.org/std/pin/` 与 `std/marker/` 现行文档为准（2026-10 核实）。文中标「实测」的结论跑在 `rustc 1.98.1` / `aarch64-apple-darwin`，换版本需重测；带版本号的语义变化以所用版本的 std 文档为最终口径。

## What Pin Actually Is

`Pin<P>` 的定义简单到几乎什么都没有：

```rust
pub struct Pin<P> { pointer: P }
impl<P: Deref> Pin<P> { /* 只暴露不移动的 API */ }
```

它是一个 newtype，包住一个指针（`&mut T`、`Box<T>`、`Rc<T>` 都行），**零运行时开销**（实测 `Pin<Box<T>>` 与 `Box<T>` 同宽，16 B）。它的全部作用在类型层面：把"可以移动"的 `&mut T` / `Box<T>` 换成"承诺不移动"的 `Pin<&mut T>` / `Pin<Box<T>>`。

于是 API 表面出现一道分界线：

| 方法 | 可用条件 | 语义 |
| :--- | :--- | :--- |
| `Pin::new(ptr)` | `T: Unpin` | 安全——因为 `T` 本来就能移动，pin 不 pin 无差别 |
| `Pin::new_unchecked(ptr)` | 无 | unsafe——调用方承诺"这个地址从此不变" |
| `Pin::get_mut(pin)` | `T: Unpin` | 取回 `&mut T`，同样只在能移动时有意义 |
| `unsafe { Pin::get_unchecked_mut(pin) }` | 无 | 绕过承诺，义务在你 |
| `pin.as_ref()` / `pin.as_mut()` | 无 | 拿回 `Pin<&T>` / `Pin<&mut T>`，保留承诺 |

约束本身可以压成三条，逐条都有对应的安全边界：

1. **拿不到可移动的出口。** 对 `T: !Unpin`，`Pin<&mut T>` 不提供 `DerefMut`——安全代码无法从 `Pin<&mut T>` 变回 `&mut T`，因而无法 `mem::swap` / `mem::replace` / 整体搬走。约束的实现方式是**收回移动所需的 `&mut T`**，而不是把内存钉住。
2. **unsafe 绕过必须连带着保证 drop。** `get_unchecked_mut` / `map_unchecked_mut` 允许在 `!Unpin` 时绕过，但契约是：要么保证之后不再移动还使用旧内容，要么保证析构发生在 pin 的位置——`!Unpin` 类型的 `Drop` 实现同样可能依赖"我没搬过家"。
3. **pin 不等于不可变。** `Pin<&T>` 可以读，`Pin<&mut T>` 在 `T: Unpin` 时照样 `DerefMut`；"被 pin 了所以不能改"是常见误读，`Pin` 管的是**位置**，不是**内容**。

## Unpin: The Trait That Makes Pin Free for Most Types

`Unpin` 是 auto trait，**几乎所有普通类型都自动实现它**——`u32`、`String`、`Vec<T>`、你自己的普通 struct，全都 `Unpin`。`!Unpin` 只有两个来源：编译器生成的 future，和显式 `PhantomPinned`（与 `std::pin` 同在 1.33.0 稳定）。

两处流行误读值得单独纠：

- **"`Unpin` 表示这个类型被 pin 了"——反了。** 它的真实含义是"**即使被 pin 也安全可移动**"。所以 `Unpin` 类型照样能被 pin（`Box::pin(String::from("x"))` 完全合法），只是那个 pin 什么也不保证。判断依据永远是 `T: Unpin` 还是 `T: !Unpin`，而不是"它现在处于什么状态"。
- **"我的 future 没有跨 await 借用，所以应该 `Unpin`"——不成立。** 本机实测：

```rust
fn needs_unpin<T: Unpin>(_t: T) {}
async fn leaf() -> u32 { 1 } // 无借用、无 await，最干净的状态机
needs_unpin(leaf());
```

```text
error[E0277]: `{async fn body of leaf()}` cannot be unpinned
  = note: consider using the `pin!` macro
          consider using `Box::pin` if you need to access the pinned value outside of the current scope
```

编译器对**所有** `async fn` / `async {}` 的产物都回答 `!Unpin`（async 降级出的协程是不可移动的），这不是保守判断而是设计：状态机是否自引用由编译器内部决定，把 `Unpin` 实现权留给编译器，才能保证未来改变状态机布局时不破坏用户代码。所以不要指望"我这个 future 应该没自引用所以能 `Pin::new`"。手写 `Future` 时才需要自己论证，该问的问题是"我的字段里有没有可能在 `poll` 期间存下指向自己的引用"，有才需要 `PhantomPinned` 或结构性 `!Unpin`。

反过来，普通类型显式拒绝移动靠 `PhantomPinned`，报的是同族诊断（实测）：`the trait Unpin is not implemented for PhantomPinned`，同一个 help 文案。

**推论：对一个 `Unpin` 类型写 `Pin<&mut T>` 毫无意义**——`get_mut` 随时能取回可变引用，承诺没有约束力。`Pin` 的全部力量只作用在 `!Unpin` 上，这正是它容易被过度讨论的原因。

## Why Self-Reference Forces the Promise

自引用不是理论构造。`async` 块里的这段代码：

```rust
async fn demo() -> usize {
    let v = vec![1, 2, 3];
    let r = &v;              // r 指向 v
    some_io().await;         // 跨 await：v 与 r 都必须存活
    r.len()                  // 编译出的状态机里，r 指向同一结构体的另一个字段
}
```

编译产物大致是：

```rust
struct DemoFuture {
    v: Vec<usize>,           // 字段 1
    r: Option<&Vec<usize>>,  // 字段 2，指向字段 1
    state: State,            // await 点位置
}
```

`r` 的地址是构造时算出来的。如果 `DemoFuture` 之后被 `mem::swap` 或移动赋值搬走，`r` 仍指向**旧地址**——那里的 `v` 已经不存在（或已是别的值）。Rust 的借用检查管不了这个，因为移动不经过任何指针运算；唯一堵住它的办法是**在类型上宣布"这个值被造出来之后不许再移动"**——这就是 `Pin`。

## The Three Ways to Pin a Future

选择清单（全部本机实测）：

| 需求 | 写法 | 代价与陷阱 |
| :--- | :--- | :--- |
| 在 `async fn` 里 await 一个本地 future | `let f = foo(); f.await;` 直接 await | 一旦要把 future 存在 `async fn` 之外再 await，就得先 `pin!` |
| 当前作用域内固定 | `let f = std::pin::pin!(foo());` | 离开作用域即失效，不能返回；`pin!` 自 1.68.0 稳定 |
| 需要逃逸 / 装箱进容器 / `dyn` | `Box::pin(foo())` → `Pin<Box<dyn Future<Output = T> + Send>>` | 一次堆分配；移动 `Box` 本身不影响堆里那份数据，这是它天然满足承诺的原因 |
| 已保证不移动、想要 `Pin` | `unsafe { Pin::new_unchecked(&mut f) }` | 见安全不变式 |
| 类型本身可以安全移动 | `Unpin` 自动满足，直接 `Pin::new` | `futures::pin_mut!` 是 std `pin!` 的历史替身 |

`pin!` 的语义值得单独说：它把 future 钉在**当前栈帧**上，所以钉完之后的变量不能再移动、不能返回、不能存进结构体。它的实现就是一个 `unsafe` 块加一句"我保证不再移动它"——std 用 `ManuallyDrop` 式的技巧让 shadow 变量遮蔽原名，后续代码碰不到未 pin 的版本。

## The Safety Invariants

不变式的核心（各版本措辞略有出入，精神一致）：**被 pin 的内存地址从此不再变化，且不能把 `&T` 交出去让人能移动它**。三条常见违反：

1. pin 住一个值之后又把它 `mem::swap` 走（哪怕交换目标也是 `!Unpin`）——两个地址都变。
2. 从 `Pin<&mut T>` 造出 `&T` 传给一个会 `mem::take` 它的函数——`take` 在原地留下 `Default`，地址没变但**内容被替换**，对自引用结构同样致命。
3. 给 pin 住的字段做结构体投影时投影错了字段。

`Pin::new_unchecked` 的不变式在 1.99.0 有过一次调整，这是本主题最新的口径变化：1.99.0 的 Compatibility Notes 原文是一条 *"The `Pin::new_unchecked` has had its safety invariants changed slightly"*。本机是 1.98.1，跑不出改动前后的差异，**具体新措辞以 1.99.0 的 std 文档为准**；能确定的是：这条改动被记在"兼容性说明"里，意味着旧代码的 `unsafe` 前提可能要重审。动手写 `new_unchecked` 前先读一遍你所用版本的 `std::pin` 文档。

## Structural Pinning: The Hard Part

单个值 pin 住是简单的；**结构体的部分字段要 pin、部分不 pin**时，问题升级为"投影"：给 `Pin<&mut Outer>` 造出 `Pin<&mut Inner>`。手写投影几乎必然错，因为你要论证的恰恰是"投影不破坏原承诺"。规则是结构性的：**哪些字段被标记为需要保持 pin，`Pin<&mut Outer>` 就只能投影出这些字段的 `Pin<&mut Inner>`**；其余字段照常给 `&mut`。

安全 API 只有两条路：

- `unsafe { outer.map_unchecked_mut(|o| &mut o.inner) }`：调用方担保"永远不会移动投影出来的这个字段"。担保是终身的，任何一处 `mem::replace` 都足以让整条链变成 UB，而且**编译器不会提醒你**。
- `pin-project`（或更小的 `pin-project-lite`）：用 `#[pin]` 属性声明结构，宏生成投影代码，把 unsafe 收敛到宏内部经审计的实现里。

```rust
use pin_project::pin_project;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::future::Future;

#[pin_project]
pub struct Wrapper<F: Future> {
    #[pin]
    inner: F,            // 这个字段参与 pin 投影
    name: String,        // 这个字段随时可取回 &mut
}

impl<F: Future> Future for Wrapper<F> {
    type Output = F::Output;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        // this.inner 是 Pin<&mut F>，this.name 是 &mut String
        this.inner.poll(cx)
    }
}
```

`#[pin]` 标记的字段投影后是 `Pin<&mut F>`，未标记的是普通 `&mut`。`pin-project-lite` 用宏展开生成同样逻辑但不带 token 级错误报告，体积更小。**自己手写投影的判据**：字段是 `#[repr(transparent)]` 新类型、且你能写出为什么投影不移动——否则用 crate。日常手写组合器应该默认走 crate 这条路，自己写 `map_unchecked_mut` 属于"知道宏在做什么之后的选择"，不是起点。

## Drop and Pinning

一个容易被跳过的问题：**pin 住的值被 drop 时怎么办**。`Pin<&mut T>` 不阻止 drop（drop 是原地调用 `Drop::drop`，地址不变），所以普通情况没有问题。真正的边界是 `Pin<Box<T>>` 释放堆内存时——地址"消失"而非"改变"，这是允许的。

对 `!Unpin` 类型手写 `Drop` 时有一条纪律：**drop 里不得再移动任何字段**（`mem::replace` 之类），理由与上面第 2 条相同。规范写法是把 `drop` 当成隐式接收 `self: Pin<&mut Self>`：

```rust
impl Drop for Type {
    fn drop(&mut self) {
        // 值被 drop 之后不再使用，因此 new_unchecked 成立
        inner_drop(unsafe { Pin::new_unchecked(self) });
        fn inner_drop(this: Pin<&mut Type>) {
            // 真正的析构代码
        }
    }
}
```

与投影绑定的还有析构顺序的隐含要求：`!Unpin` 的值必须在它被 pin 的位置析构。组合器的 `Drop` 不能把字段搬出来再 drop——析构就地在原处发生，这也是"投影出来的字段从此不能移动"在生命周期末端依然成立的原因。

## Where Pin Surfaces in Real Code

多数时候 `Pin` 不直接出现，但它解释了日常异步代码里的几个现象：

- **`Pin<Box<dyn Future<Output = T> + Send>>`** 是 trait 对象形式的 future（`BoxFuture`）。`Box` 提供堆上的固定地址，因此 `dyn Future` 可以被反复 poll——类型签名里的 `Pin` 就是执行器与 future 之间的合同。
- **`spawn` 的边界**：`tokio::spawn` 要求 `Future + Send + 'static`，内部把 future 装箱并钉住再交给调度器；你写的 `async move` 块从被 spawn 那一刻起就再没搬过家。
- **`.await` 不传染，pin 传染**：一个 `async fn` 内部 `.await` 另一个 future，编译器会把这个子 future 存进自己的状态机——父状态机被 pin，子 future 随之被结构性 pin。这正是"父被 pin"能一路传递到嵌套最深处的原因。
- **`Stream` 与手写 `Future`**：`poll_next` 同样是 `self: Pin<&mut Self>`，理由与 `Future` 完全同构。
- **lending iterator / GAT**："返回借用自身元素的迭代器"与 pin 的自引用问题同源，`next(&mut self) -> Item<'_>` 形态是同一道题的另一种问法。trait 侧的展开见 [Trait_System](/docs/CS/Rust/Trait_System.md)。
- **自引用结构体的安全未来**：把"编译期检查自引用"做进类型系统的工作（`self-cell`、`ouroboros` 一类 crate 各用各的技巧）仍在演进，没有统一答案。日常需求先用这些 crate，别手写。

> [!WARNING]
> 与 `Pin` 有关的 bug 几乎全是安全代码写不出来、`unsafe` 里静默作案的形态：投影字段被移动、`get_unchecked_mut` 之后 `mem::swap`、`Drop` 实现里搬动已 pin 的字段。共同特征是**编译通过、测试偶发、只在特定调度时序下崩**——看到这类症状先查投影担保，而不是先疑执行器。

## Common Misuses

| # | 误用 | 为什么错 |
| :--- | :--- | :--- |
| 1 | 把 `Pin` 当"运行时禁止移动" | 它是编译期承诺 + 类型门禁；`get_unchecked_mut` 照样能拿到可变引用 |
| 2 | 对 `Unpin` 类型用 `Pin` | 毫无约束力，`Pin::get_mut` 随时破解 |
| 3 | 以为自己的 future 没自引用就能 `Pin::new` | 编译器生成的 future 一律 `!Unpin`（实测） |
| 4 | pin 之后 `mem::swap` / `mem::take` 字段 | 违反不变式；`take` 对自引用结构是内容替换，同样致命 |
| 5 | 手写结构体投影 | 投影错的字段 = 悬垂；用 `pin-project` |
| 6 | 把 `pin!` 的值返回或存进结构体 | 它钉在栈帧上，离开作用域即失效 |
| 7 | 在 `!Unpin` 类型的 `Drop` 里移动字段 | drop 只能原地进行 |
| 8 | 拿旧文章的 `new_unchecked` 措辞当现行语义 | 1.99.0 改过不变式，以所用版本文档为准 |

## Links

- [Drop](/docs/CS/Rust/Drop.md)
- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [Proc_Macro](/docs/CS/Rust/Proc_Macro.md)
- [Concurrency](/docs/CS/Rust/Concurrency.md)
- [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)
- [Edition 与 MSRV](/docs/CS/Rust/Edition_MSRV.md)

## References

1. [`std::pin` module docs](https://doc.rust-lang.org/std/pin/index.html)
2. [`std::pin::pin!`](https://doc.rust-lang.org/std/pin/macro.pin.html)
3. [`std::marker::PhantomPinned`](https://doc.rust-lang.org/std/marker/struct.PhantomPinned.html)
4. [The Rustonomicon — Pinning](https://doc.rust-lang.org/nomicon/pin.html)
5. [pin-project docs](https://docs.rs/pin-project/latest/pin_project/)
6. [Rust 1.99.0 release notes — Compatibility Notes](https://releases.rs/docs/1.99.0/)
7. [Announcing Rust 1.68.0（`pin!` 稳定）](https://blog.rust-lang.org/2023/03/09/Rust-1.68.0/)
8. [Async Book — Pinning](https://rust-lang.github.io/async-book/04_pinning/01_chapter.html)
9. [The Rust Programming Language — Traits for Async](https://doc.rust-lang.org/book/ch17-05-traits-for-async.html)
