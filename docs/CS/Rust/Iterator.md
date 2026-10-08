## Introduction

`Iterator` 是 Rust 零成本抽象口号唯一能被机器码直接检验的地方：它用**一个必需方法**撑起了一百多个组合子，而那一个方法在 `--release` 下会被内联成「一次指针比较 + 自增」，与手写索引循环生成同一条指令。代价付在别处——付在**类型层面**（适配器是泛型结构体，链越长类型名越长、编译期工作量越大）和**心智层面**（惰性意味着「写了不等于跑了」）。

本篇沿这条主线组织：先拆 `Iterator` trait 本体的最小接口（这条解释了为什么自定义迭代器成本极低），再讲 `IntoIterator` 与三种迭代器的分工、`for` 循环的脱糖，然后是适配器全景与「惰性」这个核心属性，接着是消费者、三个标记 trait 各自承诺什么，之后用实测解释零成本与 `size_hint` 如何决定 `Vec` 预分配，最后是 `Peekable` / `by_ref` / 自定义迭代器 / `itertools` / `rayon`，以及一张常见坑清单。

> [!NOTE]
> 写作时最新 stable 为 **Rust 1.99.0（2026-10-01）**，本机实测工具链 `rustc 1.98.1 (48a229cea 2026-09-01)`（host `aarch64-apple-darwin`）。下文凡标「实测」的都给本机真实输出；凡标「据源码」的版本号取自本机 rust-src（`library/core/src/iter/traits/iterator.rs`，1.95.0 工具链）里的 `#[stable(feature = "..", since = "1.x.0")]` 属性——这是比文档页面更硬的版本判据；凡标「据文档」的来自 std docs / release notes。**API 的 stable 版本一律不凭记忆写。**

边界：容器侧的内存布局、分配次数与 `ExactSizeIterator` 的容量实测在 [Collections](/docs/CS/Rust/Collections.md)，本篇只讲迭代器语言机制；性能测量方法论（计时、火焰图、`criterion`）见 Performance 篇；并行执行与线程池语义见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

## The Trait Is One Required Method

`trait Iterator` 的必需部分只有两行：

```rust
pub trait Iterator {
    type Item;
    fn next(&mut self) -> Option<Self::Item>;
    // 其余一百多个方法全部有默认实现
}
```

（据源码，1.95.0 的声明是 `pub const trait Iterator`，`Item` 与 `next` 都标 `since = "1.0.0"`。）三点含义：

1. **`Item` 是关联类型而不是泛型参数**——一个类型只能有一种迭代元素，因此 `Iterator` 不能对同一个 `Self` 实现两次，调用侧也永远不需要 turbofish 指定元素类型（对比 `Add<Rhs>` 这类可以对多个 `Rhs` 实现的 trait）。
2. **`next` 拿 `&mut self`**——迭代器是**显式状态机**，`Option` 是它唯一的「结束了」信号。这一条同时解释了为什么 Rust 里不存在「迭代器失效」：`next` 独占借用迭代器，而迭代器又借用容器，借用检查器在编译期就挡住了「边遍历边改」。
3. **其余方法全是默认实现**，且绝大多数默认实现只依赖 `next`（少数会 override `size_hint` / `nth` / `fold` 等做特化）。所以实现一个自定义迭代器的成本就是写一个 `next`。

为什么默认实现这么便宜——看 `map` 的默认实现骨架（据源码简化）：

```rust
fn map<B, F>(self, f: F) -> Map<Self, F> where Self: Sized, F: FnMut(Self::Item) -> B {
    Map::new(self, f)
}
```

`Map` 只是把「内部迭代器 + 闭包」打包成一个结构体，它自己的 `next` 就是「调内部 `next`，`Some` 就套闭包，`None` 就传 `None`」。**适配器不持有数据，只持有状态与变换规则**——这是整个设计的支点，也是惰性与零成本两个性质共同的来源。

顺带一个容易忽略的细节：`where Self: Sized` 出现在几乎所有消费者 / 适配器方法上。因为 `Iterator` 是 dyn-compatible 的（源码里那句 `fn _assert_is_dyn_compatible(_: &dyn Iterator<Item = ()>) {}` 就是在守这条），但返回具体适配器类型需要知道 `Self` 的大小，所以 `Box<dyn Iterator<Item = T>>` 上能用 `next` / `count` 这类「不返回新适配器」的方法，却**不能**调 `map` / `filter` 去继续接链——想接链得先 `Box<dyn Iterator>` 之外的具体类型。

## IntoIterator and the Three Iterators

`Iterator` 是「怎么走」，`IntoIterator` 是「谁能变成可走的东西」。标准容器几乎都给三种形态各实现一次：

| 入口 | `Item` | 容器命运 | 典型用途 |
| :-- | :-- | :-- | :-- |
| `v.iter()` / `&v` | `&T` | 完好 | 只读遍历；循环体内不能改容器 |
| `v.iter_mut()` / `&mut v` | `&mut T` | 完好 | 原地改 |
| `v.into_iter()` | `T` | **被消耗** | 转移所有权；`v` 之后不可用 |

`for` 循环脱糖成 `IntoIterator::into_iter()`，而不是 `.iter()`。这不是推论而是有实测诊断——把 `Vec<String>` 直接喂给 `for` 之后再读它：

```text
error[E0382]: borrow of moved value: `v`
 --> e1.rs:6:22
  |
2 |     let v = vec![String::from("a"), String::from("b")];
  |         - move occurs because `v` has type `Vec<String>`, which does not implement the `Copy` trait
3 |     for s in v {
  |              - `v` moved due to this implicit call to `.into_iter()`
...
6 |     println!("{:?}", v);
  |                      ^^^ value borrowed here after move
  |
note: `into_iter` takes ownership of the receiver `self`, which moves `v`
help: consider iterating over a slice of the `Vec<String>`'s content to avoid moving into the `for` loop
  |
3 |     for s in &v {
  |              +
```

`` `v` moved due to this implicit call to `.into_iter()` `` 这句诊断直接点名了脱糖目标；`note` 那一行进一步把原因归到 `into_iter` 的接收者是 `self`。所以 `for x in &v` 与 `for x in v` 的差别不是「写法糖」而是**选择了哪一个 `IntoIterator` 实现**：前者是 `&Vec<T>` 的（产出 `&T`），后者是 `Vec<T>` 的（产出 `T` 并吃掉容器）。规则本体见 [Ownership](/docs/CS/Rust/Ownership.md)。

数组是这条规则里唯一分 edition 的例外：`[T; N]` 的 `into_iter` 在 edition ≤ 2018 会 autoref 到切片、产出 `&T`，edition 2021 起改为按值产出 `T`（据 Edition Guide；该差异的实测判据见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)）。这是「同一个方法名在不同 edition 下解析到不同实现」的教科书案例。

## Adapter Landscape

适配器是「返回新迭代器的方法」，本身不做任何工作。按是否有状态分两类：

| 适配器 | 稳定版本（据源码） | 是否有状态 | 说明 |
| :-- | :-- | :-- | :-- |
| `map` | 1.0.0 | 否 | 逐元素变换；保留 `size_hint` 上界 |
| `filter` | 1.0.0 | 否 | 谓词过滤；**下界退化为 0** |
| `filter_map` | 1.0.0 | 否 | 变换 + 过滤合一，替代 `map` + `filter(Option::is_some)` + `unwrap` 三连 |
| `flat_map` | 1.0.0 | 否（但产出可变长） | 每个元素产出一个迭代器再展平；`size_hint` 上界变 `None` |
| `flatten` | 1.29.0 | 否 | 展平迭代器之迭代器 |
| `take(n)` / `skip(n)` | 1.0.0 | 计数 | `take` 是无限迭代器的唯一终止纪律 |
| `take_while` / `skip_while` | 1.0.0 | 一位 | 遇假即停 |
| `map_while` | 1.57.0 | 一位 | 「变换直到第一次失败」，比 `take_while` + `map` 更省一次闭包 |
| `zip` | 1.0.0 | 否 | 两个迭代器配对，取短者 |
| `enumerate` | 1.0.0 | 计数 | 附索引 |
| `chain` | 1.0.0 | 一位 | 首尾相接 |
| `rev` | 1.0.0 | 否 | 需要 `DoubleEndedIterator` |
| `inspect` | 1.0.0 | 否 | 每个元素上跑闭包做副作用，**不消费** |
| `cycle` | 1.0.0 | 需要 `Clone` | 无限循环 |
| `step_by` | 1.28.0 | 计数 | 按步长跳 |
| `scan` | 1.0.0 | **任意可变状态** | 见下 |
| `copied` / `cloned` | 1.36.0 / 1.0.0 | 否 | `Item = &T` → `T` |

`scan` 值得单说：它是「带累加器的 `map`」，签名 `scan(initial_state, |state, item| -> Option<B>)`，闭包返回 `None` 就提前结束。它与 `fold` 的关系是**同一对状态转移的两种投影**——`fold` 只要最终那个累加值，`scan` 要每一步的累加值序列。实测：

```text
scan: [1, 3, 6]        // [1,2,3].into_iter().scan(0, |acc, x| { *acc += x; Some(*acc) })
```

## Laziness Is the Point

`#[must_use = "iterators are lazy and do nothing unless consumed"]`（据源码，挂在 `Iterator` 上）。这条属性的字面意思就是本节标题：**适配器不消费就不执行**。实测把 `println!` 放进 `map` 的闭包，只构造不消费——输出里一个 `map ran` 都没有：

```text
built, nothing printed above except this line
```

而一旦有消费者（`count()`），闭包就逐元素执行：

```text
filter ran
filter ran
filter ran
filter ran
filter ran
count=3
```

`inspect` 是最容易在这里踩坑的适配器：它看起来像「在链上打个日志桩」，但它**只在上游被真正消费时**才触发。实测——构造一条带 `inspect` 的链、`drop` 掉，计数器仍然是 0；换成 `for_each` 消费后立刻变成 3：

```text
after building+drop, side=0
after for_each, side=3
```

判别式很简单：**数一下链尾有没有消费者**。`inspect` / `map` / `filter` 都不是消费者，`count` / `sum` / `collect` / `for_each` / `fold` / `any` / `find` 才是。想让副作用一定发生，就别用 `inspect`，用 `for_each`（或先 `collect` 再遍历）。

## Consumers

消费者是「吃掉迭代器产出非迭代器值」的方法，也是惰性链的驱动端：

| 消费者 | 稳定版本（据源码） | 说明 |
| :-- | :-- | :-- |
| `collect` | 1.0.0 | 靠 `FromIterator`；唯一需要类型标注的常用方法 |
| `fold` | 1.0.0 | 带初值的累加；最一般的消费者 |
| `try_fold` | **1.27.0** | 可短路的 `fold`；`Result` / `Option` / `ControlFlow` 版 |
| `reduce` | **1.51.0** | 无初值，用首元素当初值；空迭代返回 `None` |
| `sum` / `product` | 1.11.0 | 靠 `Sum` / `Product` trait（1.12.0） |
| `count` / `last` / `nth` | 1.0.0 | `nth` 会**消耗掉**跳过的元素 |
| `for_each` | 1.21.0 | 副作用版 `fold`；与 `inspect` 的关键差别是它自己就是消费者 |
| `partition` | 1.0.0 | 按谓词拆成两个集合 |
| `unzip` | 1.0.0 | `Item = (A, B)` → `(C, D)` |
| `any` / `all` / `find` / `position` | 1.0.0 | 短路查找系 |
| `find_map` | 1.30.0 | `find` + `map` 合一 |
| `is_sorted` | 1.82.0 | 免写 `windows(2).all(..)` |

`reduce` 与 `fold` 的差别只有一处，但很关键：空迭代时 `reduce` 返回 `None`（因为没有首元素可当初值），`fold` 返回你给的初值。实测：

```text
empty reduce: None
empty fold: 0
```

`collect` 是唯一必须写类型的常用消费者，因为它的返回类型是泛型参数 `B`。实测不标注就报错：

```text
error[E0283]: type annotations needed
 --> e7.rs:3:9
  |
3 |     let r = it.collect();
  |         ^      ------- type must be known at this point
  |
  = note: the type must implement `FromIterator<u8>`
note: required by a bound in `collect`
help: consider giving `r` an explicit type, where the type for type parameter `B` is specified
  |
3 |     let r: Vec<_> = it.collect();
  |          ++++++++
```

注意诊断建议的是 `Vec<_>` 而不是 `Vec<u8>`：`collect::<Vec<_>>()` 这种「只指定容器、让元素类型继续推断」的写法就叫 **turbofish 的部分标注**，它是 `collect` 的惯用法。`collect` 之所以能产出 `Vec` / `String` / `HashMap` / `Result<Vec<_>, _>` 等任意目标，靠的是 `FromIterator` trait——而且这个 trait 的实现可以是**会失败的**：`impl FromIterator<Result<A, E>> for Result<V, E>` 让 `iter.collect::<Result<Vec<_>, _>>()` 在第一个 `Err` 处短路，从而把「一堆 `Result` 聚成一个 `Result`」写成一行。这一条与错误处理篇的 `?` 惯用法直接相邻。

## Building Iterators From Nothing

链的起点不只有容器。`std::iter` 提供一组自由函数用来「凭空造迭代器」，写解析器、状态机、测试数据的时候比先建 `Vec` 再 `into_iter()` 干净得多：

| 构造器 | 稳定版本（据源码） | 产出 | 备注 |
| :-- | :-- | :-- | :-- |
| `iter::once(x)` | 1.2.0 | 恰好一个元素 | 最常见的「把一个值接进链里」 |
| `iter::once_with(f)` | 1.43.0 | 闭包返回值恰好一次 | 惰性版 `once`，值贵就不白算 |
| `iter::repeat(x)` | 1.0.0 | 无限重复，需 `Clone` | **无限**，必须 `take` |
| `iter::repeat_with(f)` | 1.28.0 | 无限调用闭包 | 无限 |
| `iter::repeat_n(x, n)` | 1.82.0 | 恰好 `n` 个 | 有限版，1.82.0 才补上 |
| `iter::from_fn(f)` | 1.34.0 | 直到闭包返回 `None` | 通用「把状态机写成闭包」 |
| `iter::successors(seed, f)` | 1.34.0 | `seed` 之后反复套 `f` | 斐波那契、链表遍历、树下降的惯用写法 |

实测（`rustc --edition 2024 -O`）：

```text
once+repeat_n: [1, 2, 2, 2]
successors: [1, 2, 4, 8, 16]
from_fn: [1, 2, 3]
repeat_with+take: [7, 7, 7]
```

`successors` 与 `from_fn` 的差别是一个很有用的判据：**`successors` 的闭包接收上一个产出**（有依赖，序列是递推的），**`from_fn` 的闭包不接收任何输入**（无依赖，状态只能靠闭包自己捕获的变量）。所以「下一项由上一项决定」用 `successors`，「每轮从外部状态取一个」用 `from_fn` + `move` 闭包。两者都是惰性的，不消费就不调用闭包——上面那三条实测之所以有输出，是因为链尾都有 `collect`。

## The Three Marker Traits

三个特殊 trait 都是在「`Iterator` 没承诺的东西」之上加承诺，且都是**空 trait 或只加少数方法**——它们存在的意义是让泛型代码能按能力分派：

| trait | 稳定版本（据源码） | 承诺 | 为什么需要 |
| :-- | :-- | :-- | :-- |
| `ExactSizeIterator` | 1.0.0 | `len()` 精确且 `size_hint` 上下界相等 | `Vec` 预分配、`chunks_exact` 的长度已知、`rev` 的正确性都依赖它 |
| `DoubleEndedIterator` | 1.0.0 | 支持 `next_back()` / `rfold` / `rfind` | `.rev()` 与双向算法的前提 |
| `FusedIterator` | **1.26.0** | `next()` 返回过一次 `None` 之后**永远**返回 `None` | `Iterator` 的文档**不保证**终止后行为；`fuse()` 把它变成运行时保证，`FusedIterator` 是类型层声明 |

`FusedIterator` 那一行是三者里最反直觉的：`Iterator` 只说「`None` 之后再调 `next` 的行为不作约定」，`chain` / `zip` 这类组合子在结束点必须重复判定，于是 `fuse()` 用一点状态把这个义务变成运行时保证。

哪些适配器保留哪些标记，可以编译期实测（用三个 `fn assert_*<I: Trait>(_: &I) {}` 逐个试）。本机实测结论：

| 适配器 | `ExactSizeIterator` | `DoubleEndedIterator` | `FusedIterator` |
| :-- | :-- | :-- | :-- |
| `v.iter()` | ✅ | ✅ | ✅ |
| `.map(..)` | ✅ | ✅ | ✅ |
| `.enumerate()` / `.take(n)` / `.zip(..)` / `.copied()` / `.rev()` | ✅ | 视上游 | — |
| `.filter(..)` | ❌（下界退化为 0） | 视上游 | ✅ |
| `.scan(..)` | ❌ | 视上游 | ❌ |
| `.fuse()` | — | — | ✅ |

`.filter()` 丢掉 `ExactSizeIterator` 是这表里最重要的一个「❌」，它直接导致下一节的容量差异。

## Zero Cost, and Why size_hint Decides Allocation

零成本的第一个证据是汇编。把同一段计算写成迭代器链和索引循环，`--edition 2021 -O --emit asm`：

```rust
#[no_mangle]
pub fn sum_iter(xs: &[i64]) -> i64 { xs.iter().map(|x| x * 2).filter(|x| *x > 0).sum() }
#[no_mangle]
pub fn sum_loop(xs: &[i64]) -> i64 { /* for i in 0..xs.len() { .. } */ }
```

本机实测：两个函数体**各 60 行**，把标签编号归一化后**只有 6 行不同，且全部是寄存器分配 / 指令顺序差异**（`mov x9/x8` 的顺序、`sub` 与 `add` 的先后、尾循环用 `x9` 还是 `x10`），语义等价。两者主体都是 4 宽 NEON：`ldp q4, q5` / `add.2d` / `cmgt.2d` / `and.16b` / `add.2d` 加一次 4 路展开，尾部一个标量循环。**没有边界检查、没有闭包调用、没有中间集合**。

能成立的原因是单态化 + 内联：适配器是已知大小的泛型结构体，`next()` 被内联成指针比较与自增之后，剩下的就是 LLVM 熟悉的计数循环形态，边界检查在指针步进被证明落在 `[ptr, ptr+len)` 内时消掉。

第二个证据在分配侧。`collect` 用 `size_hint().0`（下界）做预分配，于是**适配器丢不丢 `size_hint` 直接决定 `Vec` 的容量**。本机实测：

| 表达式 | `size_hint` | 实测 `capacity()` / `len()` |
| :-- | :-- | :-- |
| `v.iter().copied().collect()` | `(5, Some(5))` | **5 / 5** |
| `v.iter().copied().map(..).collect()` | `(5, Some(5))` | **5 / 5** |
| `v.iter().copied().filter(..).collect()` | `(0, Some(5))` | **8 / 2** |
| `(0..100u8).filter(..).collect()` | `(0, Some(100))` | **8 / 4** |

前两行精确、`filter` 两行明显超分——因为 `filter` 的下界是 0，`collect` 无从预分配，只能按 `Vec` 的翻倍增长一路走到 8。同一组 `size_hint` 实测：

```text
slice iter hint: (5, Some(5))      filter hint: (0, Some(5))       map hint: (5, Some(5))
take(2) hint: (2, Some(2))         step_by hint: (3, Some(3))      chain hint: (10, Some(10))
flat_map hint: (0, None)           scan hint: (0, Some(5))         zip hint: (5, Some(5))
```

⚠️ 但**不要把 `capacity()` 当契约**。1.76.0 的 Compatibility Notes 明说 "`Vec`'s allocation behavior was changed when collecting some iterators. **Allocation behavior is currently not specified**"——上表是本机 1.98.1 的观察值，不是跨版本承诺（同判据见 [Collections](/docs/CS/Rust/Collections.md)）。这条同时是「行为对你 load-bearing 就去引用文档」的一个活例。

## Peekable and by_ref

**`Peekable`** 解决「需要看一眼下一个元素再决定」的算法。它缓存一个元素，`peek()` 借用队首但不消费。典型例子是游程编码（run-length），实测输出 `[(1, 3), (2, 2), (3, 1)]`：

```rust
let mut p = data.iter().peekable();
while let Some(&cur) = p.next() {
    let mut n = 1;
    while p.peek() == Some(&&cur) { p.next(); n += 1; }
    out.push((cur, n));
}
```

`Peekable` 的方法稳定版本（据源码）：`peek` 1.0.0、`next_if` / `next_if_eq` 1.51.0、`peek_mut` 1.53.0、`next_if_map` / `next_if_map_mut` 1.94.0。`next_if` 系列存在的意义是把上面那个内层 `while` 压成一行（`while p.next_if(|&x| x == cur).is_some() { n += 1; }`）。

**`by_ref()`** 解决另一件事：适配器默认**拿走 `self`**，所以 `it.take(1).collect()` 之后 `it` 就没了。`by_ref()` 借出 `&mut it`（而 `&mut I` 本身实现 `Iterator`，据源码 `impl<I: Iterator + ?Sized> Iterator for &mut I`，1.0.0），从而可以「消费一部分、留着剩下的」。实测：

```text
by_ref: [1] then [2, 3]
```

## Writing Your Own Iterator

真实的最小实现只写 `next`，但**再加两行收益极大**——`size_hint` 决定下游能否精确预分配，`IntoIterator` 让这个类型能直接进 `for`。实测可编的完整骨架：

```rust
pub struct Counter { cur: u8, max: u8 }

impl Iterator for Counter {
    type Item = u8;
    fn next(&mut self) -> Option<u8> {
        if self.cur >= self.max { return None; }
        self.cur += 1;
        Some(self.cur - 1)
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = (self.max - self.cur) as usize;
        (n, Some(n))
    }
}
impl ExactSizeIterator for Counter {}

pub struct Range8 { max: u8 }
impl IntoIterator for Range8 {
    type Item = u8;
    type IntoIter = Counter;
    fn into_iter(self) -> Counter { Counter::new(self.max) }
}
```

三点设计要点：

- **`impl Iterator for Counter` 与 `impl IntoIterator for Range8` 是对称的两半**。前者说「这个类型怎么走」，后者说「这个类型能被 `for` 消费」。标准库里 `Vec` 自己实现 `IntoIterator`（产出 `T`）、`&Vec` 也实现（产出 `&T`），就是靠 receiver 类型不同来选。
- **`size_hint` 不写也不算错**，默认值是 `(0, None)`，代价是下游 `collect` 无法预分配——正是上一节 `filter` 那一行的情形。写了且写对，下游的 `Vec` 就一次分配到位。
- **只有当你确实能保证时才 `impl ExactSizeIterator`**。它是 `unsafe` -free 但语义很强的承诺（`len()` 必须精确），说谎会让依赖它的代码（如某些 `rev` / 分块逻辑）越界。

实现自定义迭代器时，`FusedIterator` 只有在「`None` 之后确实永远 `None`」时才实现；`scan` 那种能中途恢复的类型就不该实现它（与前面的实测表一致）。

## itertools: What std Deliberately Left Out

`itertools` 0.15.0（2026-06-16 发布，MSRV 1.63.0，据 crates.io）的定位是「std 故意不收的东西」。判断 std 收不收的标准大致是：是否有广泛共识、是否需要额外依赖、放进 std 后能否永久维护。`itertools` 补的主要是三类：

- **多迭代器组合**：`merge` / `merge_join_by` / `kmerge`（有序归并）、`izip!`（多 zip）、`multiunzip`；
- **分组与去重**：`group_by` / `chunk_by` / `dedup` / `unique` / `counts` / `into_group_map`；
- **排列组合与窗口**：`permutations` / `combinations` / `tuple_windows` / `circular_tuple_windows`。

0.15.0 的 breaking 变化（据 CHANGELOG）：`Position` 从 enum 改为 struct；`all_equal_value` 的错误类型规范化；新增 `*_with_hasher` 系列与 `strip_prefix` / `strip_prefix_by`；`array_combinations` 去掉 `Clone` bound 并**弃用** `tuple_combinations`，新增 `[circular_]array_windows` 并**弃用** `tuple_windows`；`collect_vec` 加 `#[must_use]`。

那条「弃用 `tuple_combinations`、改推 `array_combinations`」的走向值得记：它和 std 里 `array_chunks` 的思路一致——**用 const 泛型数组替代「为每种元数各写一遍」的 tuple 版本**，把指数级的 API 面缩成一个。反向印证是：std 的 `Iterator::array_chunks` 与 `next_chunk` **至今 nightly-only**（本机 1.98.1 实测 E0658：

```text
error[E0658]: use of unstable library feature `iter_array_chunks`
  = note: see issue #100450 <https://github.com/rust-lang/rust/issues/100450> for more information
error[E0658]: use of unstable library feature `iter_next_chunk`
  = note: see issue #98326 <https://github.com/rust-lang/rust/issues/98326> for more information
```

），所以「按块取 N 个」这件事在 stable 上要么自己写、要么用 `itertools` 的 `next_array` / `collect_array`（0.14.0 起）。**任何声称 `array_chunks` / `next_chunk` 已 stable 的说法都是错的**。

## Parallel Iteration with rayon

`rayon` 1.12.0（2026-04-14 发布，MSRV 1.80.0，据 crates.io）的 API 设计核心是**与 std 迭代器同形**：`ParallelIterator` 的方法名与 `Iterator` 一一对应（`map` / `filter` / `fold` / `reduce` / `sum` / `collect` …），迁移成本通常只有把 `iter()` 改成 `par_iter()` 一处。三条设计约束让这个同形得以成立（据 rayon 文档与 FAQ）：

1. **数据无竞争由类型系统保证**：`ParallelIterator` 的闭包要求 `Send` + `Sync` 相关约束，因此 Rust 的借用规则直接推出「并行迭代不会数据竞争」，不需要运行时检测；
2. **`IndexedParallelIterator` 对应 std 的 `ExactSizeIterator`**：长度已知才能把区间对半切分，这是 work-stealing 调度器分任务的前提；
3. **`fold` + `reduce` 是并行的原生形态**：因为它们不要求顺序，`rayon` 能把它们拆成「各线程局部折叠、最后归并」；而 `for_each` 在并行下**不保证顺序**，需要顺序就得用 `for_each_with` 或改回串行。

`par_bridge` 是把任意串行 `Iterator` 接到并行链上的逃生舱，代价是它需要加锁、且吞吐通常不如原生并行迭代器——判断标准很简单：数据源本身能随机访问（`Vec` / 切片 / `Range`）就用 `par_iter` / `par_chunks`，只能顺序产出（流式读文件、自定义生成器）才考虑 `par_bridge`。线程池与 work-stealing 的执行语义见 [Concurrency](/docs/CS/Rust/Concurrency.md)；依赖选型的生态视角见 Ecosystem 篇。

## Common Pitfalls

| 坑 | 实测症状 | 根因 | 修法 |
| :-- | :-- | :-- | :-- |
| 适配器链的借用与后续修改冲突 | `error[E0502]: cannot borrow v as mutable because it is also borrowed as immutable` | 链里的 `v.iter()` 持有共享借用，而适配器**未被消费时借用仍活着** | 先 `collect()` 结束借用，或把修改挪到消费之后 |
| `collect` 类型推断失败 | `error[E0283]: type annotations needed` + `= note: the type must implement FromIterator<u8>` | `collect` 的返回类型是不可能被推断出的泛型参数 `B` | `collect::<Vec<_>>()` 或 `let r: Vec<_> = ..` |
| 无限迭代器没有 `take` | 编译通过、运行时不终止 | `cycle` / `repeat` / `iter::successors` 永不返回 `None` | 一律 `.take(n)` 收口，或用 `find` / `any` 这类短路消费者 |
| 以为 `inspect` 跑了副作用 | 计数器实测为 0 | 惰性：没有消费者，闭包根本没被调用 | 改用 `for_each`，或补一个真正的消费者 |
| 用 `reduce` 却期待空输入有值 | 实测 `empty reduce: None` | `reduce` 无初值，空迭代只能返回 `None` | 需要默认值就改 `fold` |
| 用 `nth` 之后以为元素还在 | `nth(3)=Some(3)` 之后 `next()` 得到 `Some(4)` | `nth` 消耗掉跳过的元素 | 需要跳过但不消耗就先 `skip(n).next()`（同样消耗；真正不消耗要 `Peekable` 或克隆迭代器） |
| 对 `dyn Iterator` 继续接适配器 | `the method map exists but its trait bounds were not satisfied`（`where Self: Sized` 不满足） | 适配器方法要求 `Self: Sized` | 只在 trait object 上用 `next` / `count` 等；接链要用具体类型 |

第一条值得再强调一次：**借用冲突不是「链写长了」造成的，是「链没有被消费」造成的**。实测把 `let it = v.iter().map(..)` 之后立刻 `v.push(4)`，编译器报 E0502 并明确指出 `it.collect()` 那一行才是借用的最后一次使用——这正是 NLL「借用绑在活跃性上、不绑在花括号上」的直接体现（机制见 [Ownership](/docs/CS/Rust/Ownership.md)）。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [Generics](/docs/CS/Rust/Generics.md)
- [Async](/docs/CS/Rust/Async.md)
- [compile](/docs/CS/Rust/compile.md)
- [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)

## References

- [std::iter - module documentation](https://doc.rust-lang.org/std/iter/index.html)
- [std::iter::Iterator](https://doc.rust-lang.org/std/iter/trait.Iterator.html)
- [std::iter::IntoIterator](https://doc.rust-lang.org/std/iter/trait.IntoIterator.html)
- [std::iter::FromIterator](https://doc.rust-lang.org/std/iter/trait.FromIterator.html)
- [std::iter::ExactSizeIterator](https://doc.rust-lang.org/std/iter/trait.ExactSizeIterator.html)
- [std::iter::DoubleEndedIterator](https://doc.rust-lang.org/std/iter/trait.DoubleEndedIterator.html)
- [std::iter::FusedIterator](https://doc.rust-lang.org/std/iter/trait.FusedIterator.html)
- [std::iter::Peekable](https://doc.rust-lang.org/std/iter/struct.Peekable.html)
- [core::iter::traits::iterator - source (stability attributes)](https://doc.rust-lang.org/stable/src/core/iter/traits/iterator.rs.html)
- [The Rust Programming Language - Processing a Series of Items with Iterators](https://doc.rust-lang.org/book/ch13-02-iterators.html)
- [The Rust Reference - Iterator loops](https://doc.rust-lang.org/reference/expressions/loop-expr.html#iterator-loops)
- [Rust 1.26.0 release notes - FusedIterator](https://blog.rust-lang.org/2018/05/10/Rust-1.26.html)
- [Rust 1.27.0 release notes - try_fold / try_for_each](https://blog.rust-lang.org/2018/06/21/Rust-1.27.html)
- [Rust 1.51.0 release notes - reduce](https://blog.rust-lang.org/2021/03/25/Rust-1.51.0.html)
- [Rust Releases - Version History and Compatibility Notes](https://doc.rust-lang.org/stable/releases.html)
- [itertools 0.15.0 documentation](https://docs.rs/itertools/0.15.0/itertools/)
- [itertools CHANGELOG](https://github.com/rust-itertools/itertools/blob/master/CHANGELOG.md)
- [rayon 1.12.0 documentation](https://docs.rs/rayon/1.12.0/rayon/)
- [rayon::iter::ParallelIterator](https://docs.rs/rayon/1.12.0/rayon/iter/trait.ParallelIterator.html)
- [rayon FAQ](https://github.com/rayon-rs/rayon/blob/master/FAQ.md)
