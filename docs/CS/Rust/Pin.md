## Introduction

[Async_Runtime](/docs/CS/Rust/Async_Runtime.md) 讲过那条分界线：语言只给了 `async` / `await` 语法、`Future` trait、`Poll` 与 `Waker`，调度、IO 就绪通知、定时器全在语言之外。但分界线语言这一侧还留着一个更难的问题——**为什么 `poll` 的接收者必须是 `Pin<&mut Self>`，而不是普普通通的 `&mut Self`**。本文回答这一半：自引用状态机、`Pin` 的承诺边界、`Unpin` 的误解，以及把 `Pin` 穿过结构体字段时唯一麻烦的操作（投影）。

一句话概括：**`async fn` 编译出来的状态机可能含有指向自己的指针，而"移动一个自引用值"是未定义行为；`Pin` 是把这个约束塞进类型系统的装置**。

> [!NOTE]
> 本页的事实基线是 `doc.rust-lang.org/std/pin/` 与 `std/marker/` 现行文档（Rust stable **1.99.1**，2026-10-15）。带版本号的结论均有官方来源，不按二手博客转述写。

## Why poll Takes a Pinned Receiver

先看问题本身。一个 `async` 块在编译期被降级成一个匿名结构体，`.await` 之间的局部变量是这个结构体的字段：

```rust
async fn example(buf: &[u8]) -> usize {
    let slice = &buf[..4];      // 字段：对 buf 的借用
    other_future.await;         // 第一次挂起点
    slice.len()                 // 挂起之后仍然使用 slice
}
```

第二次挂起恢复执行时，`slice` 必须仍然指向 `buf` 的有效位置。如果这个状态机在两次 `poll` 之间被**移动**了（比如从栈上搬进 `Box`、被 `Vec` 重新分配挤走、被 `mem::swap`），字段里那个指向旧地址的 `slice` 就成了悬垂指针——而编译器在生成状态机时**已经允许了这种自引用**，因为它假设"结构体不会在自己持有内部引用时搬家"。

这个假设对普通结构体不成立：Rust 的值默认是可移动的，`let a = b;`、函数传参、集合 `push` 都在悄悄移动。于是需要一个类型来把这个假设**变成可检查的承诺**：`Pin<&mut T>` 的意思不是"钉住内存"，而是"我保证这个值从此不会再移动，你可以安全地在里面存自引用"。

`Future::poll` 因此写成：

```rust
fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output>;
```

`self` 的类型本身就是文档：**任何 `poll` 你的代码都承诺了在本次 `Ready` 之前不动你**。执行器（tokio 的 task、`block_on` 的循环）负责先 pin 再 poll，语言和标准库负责让"移动一个已 pin 的值"在安全代码里不可能发生。

## What Pin Actually Guarantees

`Pin<P>` 的约束可以压成三条，逐条都有对应的安全边界：

1. **拿不到可移动的出口。** 对 `T: !Unpin`，`Pin<&mut T>` 不提供 `DerefMut`——安全代码无法从 `Pin<&mut T>` 变回 `&mut T`，因而无法 `mem::swap` / `mem::replace` / 整体搬走它。这是全部约束的实现方式：不是内存被钉住，而是**移动所需的 `&mut T` 被类型系统收回了**。
2. ** unsafe 移动必须连带着保证 drop。** `Pin::get_unchecked_mut` 与 `Pin::set`（后者要求 `T: Sized` 且调用方承担担保）允许在 `!Unpin` 时绕过约束，但契约是：要么保证不再移动后还使用旧内容，要么保证析构发生在 pin 的位置——因为 `!Unpin` 类型的 `Drop` 实现同样可能依赖"我没搬过家"。
3. **pin 不等于不可变。** `Pin<&T>` 可以读，`Pin<&mut T>` 在 `T: Unpin` 时照样 `DerefMut`；"被 pin 了所以不能改"是常见误读，`Pin` 管的是**位置**，不是**内容**。

配套的构造入口有三个安全度层级：`Pin::new(&mut x)` 仅接受 `T: Unpin`（对无自引用风险的类型，pin 不带来额外限制）；`Box::pin(x)` 在堆上钉住任意 `T`，返回 `Pin<Box<T>>`——移动 `Box` 本身不影响堆里那份数据，这是它天然满足承诺的原因；`pin!(x)` 宏（**1.68.0** 起稳定）把值钉在调用点的本地存储上，得到 `Pin<&mut T>`，借用的生命周期由借用检查器正常管辖，`pin!` 出来的值不可能比那个本地活得久。

## Unpin Is an Opt-Out, Not a Marker

`Unpin` 是**自动 trait**：编译器为几乎所有类型实现它，`PhantomPinned` 是标准库提供的退出手段——类型含有它就不自动实现 `Unpin`（`std::marker::PhantomPinned`，与 `std::pin` 同在 **1.33.0** 稳定）。

两处流行误读值得单独纠：

- **"`Unpin` 表示这个类型被 pin 了"——反了。** 它的真实含义是"**即使被 pin 也安全可移动**"。所以 `Unpin` 类型照样可以被 pin（`Box::pin(String::from("x"))` 完全合法），只是那个 pin 什么也不保证，因为移动它本来就不违反任何不变量。判断依据永远是 `T: Unpin` 还是 `T: !Unpin`，而不是"它现在处于什么状态"。
- **"要给自己的 future 标 `!Unpin` 才行"——通常不需要。** 由 `async` 块自动生成的状态机，编译器在发现跨 `.await` 的自引用时会自动让它 `!Unpin`；手写 `Future` 时才需要自己论证，而默认该问的问题是"我的字段里有没有可能在 `poll` 期间存下指向自己的引用"，有才需要 `PhantomPinned` 或结构性 `!Unpin`。

## Projection Is the Only Hard Part

单层类型好办，麻烦从"结构体里有结构体"开始。手写组合器时，外层 `poll` 拿到的 `Pin<&mut Outer>` 必须变成内层 `Pin<&mut Inner>`，这个动作叫**投影（projection）**，规则是结构性的：**哪些字段被标记为需要保持 pin，`Pin<&mut Outer>` 就只能投影出这些字段的 `Pin<&mut Inner>`**；其余字段照常给 `&mut`。理由很直接——如果内层 future 被移动而外层还持有指向它的自引用，承诺就被打破了。

标准库不自动做这件事，安全 API 只有两条路：

- `unsafe { outer.map_unchecked_mut(|o| &mut o.inner) }`：调用方担保"永远不会移动投影出来的这个字段"。担保是终身的，任何一处 `mem::replace` 都足以让整条链变成 UB，而且**编译器不会提醒你**。
- `pin-project` / `pin-project-lite` crate：用 `#[pin]` 属性字段声明结构，宏生成投影代码，把 unsafe 收敛到宏内部经审计的实现里。日常手写组合器应该默认走这条路，自己写 `map_unchecked_mut` 属于"知道宏在做什么之后的选择"，不是起点。

与投影绑定的还有析构顺序的隐含要求：`!Unpin` 的值必须在它被 pin 的位置析构。所以组合器的 `Drop` 不能把字段搬出来再 drop——析构就地在原处发生，这也是"投影出来的字段从此不能移动"在生命周期末端依然成立的原因。

## Where Pin Surfaces in Real Code

多数时候 `Pin` 不直接出现，但它解释了日常异步代码里的几个现象：

- **`Pin<Box<dyn Future<Output = T> + Send>>`** 是 trait 对象形式的 future（`BoxFuture`）。`Box` 提供了堆上的固定地址，因此 `dyn Future` 可以被反复 poll——类型签名里的 `Pin` 就是执行器与 future 之间的合同。
- **`spawn` 的边界**：`tokio::spawn` 要求 `Future + Send + 'static`，内部把 future 装箱并钉住再交给调度器；你写的 `async move` 块从被 spawn 那一刻起就再没搬过家。
- **`Stream` 与手写 `Future`**：`Stream::poll_next` 同样是 `self: Pin<&mut Self>`，理由与 `Future` 完全同构。
- **`.await` 不传染，pin 传染**：一个 `async fn` 内部 `.await` 另一个 future，编译器会把这个子 future 存进自己的状态机——父状态机被 pin，子 future 随之被结构性 pin。这正是为什么"父被 pin"能一路传递到嵌套的最深处。

> [!WARNING]
> 与 `Pin` 有关的 bug 几乎全是安全代码写不出来、`unsafe` 里静默作案的形态：投影字段被移动、`get_unchecked_mut` 之后 `mem::swap`、`Drop` 实现里搬动已 pin 的字段。共同特征是**编译通过、测试偶发、只在特定调度时序下崩**——看到这类症状，先查投影担保，而不是先疑执行器。

## Links

- [Async：语言层的 Future 与状态机](/docs/CS/Rust/Async.md)
- [Async Runtime：调度、reactor 与定时器](/docs/CS/Rust/Async_Runtime.md)
- [Concurrency：线程世界与 Send/Sync](/docs/CS/Rust/Concurrency.md)
- [Unsafe：unsafe 到底开放了什么](/docs/CS/Rust/Unsafe.md)
- [Memory Layout：值在字节层面的形状](/docs/CS/Rust/Memory_Layout.md)

## References

1. [std::pin — Rust Standard Library](https://doc.rust-lang.org/std/pin/)
2. [std::marker::PhantomPinned — Rust Standard Library](https://doc.rust-lang.org/std/marker/struct.PhantomPinned.html)
3. [Announcing Rust 1.68.0（`pin!` 稳定）](https://blog.rust-lang.org/2023/03/09/Rust-1.68.0/)
4. [Async Book — Pinning](https://rust-lang.github.io/async-book/04_pinning/01_chapter.html)
