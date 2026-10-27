## Introduction

闭包是 Rust 里唯一"编译器替你写结构体"的语法：一个 `|x| x + 1` 编译出来是一个匿名类型，捕获的变量是它的字段，函数体是它的方法。这个事实解释了大半闭包的反直觉行为——为什么闭包的大小取决于捕获什么、为什么 `move` 改变的是捕获方式而不是"搬东西"、为什么同一个闭包有时能调用两次有时不行、为什么把闭包传进泛型函数比传进 `dyn` 快。

所有权侧的 `move` 与 E0373 在 [Ownership](/docs/CS/Rust/Ownership.md)、trait 侧的 `Fn` 三兄弟与单态化在 [Trait_System](/docs/CS/Rust/Trait_System.md)、闭包与迭代器的配合在 [Iterator](/docs/CS/Rust/Iterator.md)，本篇讲闭包本身：捕获、三种 trait、返回闭包、以及它与函数指针的关系。

## A Closure Is an Anonymous Struct Plus One Method

```rust
let a = 1; let b = 2;
let f = |x: i32| x + a + b;
```

编译器生成的大致是：

```rust
struct __Closure<'env> { a: &'env i32, b: &'env i32 }
impl<'env> FnOnce<(i32,)> for __Closure<'env> {
    type Output = i32;
    extern "rust-call" fn call_once(self, args: (i32,)) -> i32 { args.0 + *self.a + *self.b }
}
impl<'env> FnMut<(i32,)> for __Closure<'env> {
    extern "rust-call" fn call_mut(&mut self, args: (i32,)) -> i32 { self.call_once((args.0,)) }
}
impl<'env> Fn<(i32,)> for __Closure<'env> {
    extern "rust-call" fn call(&self, args: (i32,)) -> i32 { self.call_once((args.0,)) }
}
```

三个推论直接从这张"展开图"读出来：

1. **闭包的大小 = 捕获字段的大小**，`size_of` 是编译期常量。一个不捕获的闭包是零大小；一个捕获 `[u8; 64]` 的闭包就是 64 字节——把它当 `dyn Fn` 装箱就是一次真实分配。
2. **调用语法 `f(x)` 走的是 trait 方法**，所以 `f(1, 2)` 与 `f((1, 2))` 在闭包上是同一件事：参数被打包成元组。
3. **三个 `Fn*` trait 是自动实现的**：编译器按捕获字段的用法挑最弱的那一个实现（见下节），这就是"闭包能调几次"的全部机制。

## Capture: By Reference, By Mutable Reference, By Value

Rust 2021 起闭包按**最小权限**捕获：编译器看函数体怎么用每个自由变量，只捕获必需的最低权限。

| 体内用法 | 捕获方式 | 后果 |
| :--- | :--- | :--- |
| 只读 `x` | `&x` | 闭包生命周期受 `x` 约束；原变量仍可用 |
| 写 `x = ...` / `x.push(..)` | `&mut x` | 闭包存在期间原变量不可用 |
| 消耗 `x`（`drop(x)`、`x.into_iter()`） | 按值（可能是移动） | 原变量失效 |
| 只读 `s.field` | **仅捕获 `s.field`**（disjoint capture） | `s.other` 不受影响 |

最后一行是 edition 2021 的 disjoint capture 改动：edition 2021 之前 `|| s.field` 会捕获整个 `s`（按引用），之后只捕 `&s.field`。这个改动的直接收益是"闭包只用结构体一个字段时，结构体其它字段仍可独立使用"；直接代价是某些代码在 2018 下能编、2021 下类型推断变了。

`move` 改变的是捕获**方式**而非捕获**清单**：加 `move` 后所有被捕获变量一律按值捕获。按值捕获对 `Copy` 类型就是复制，对非 `Copy` 就是移动——于是闭包自己成为所有者。`move || drop(s)` 之后 `s` 失效，且这个闭包必然只是 `FnOnce`（调用一次即被消耗，实测第二次调用报 E0382，附注 "closure cannot be invoked more than once because it moves the variable `s` out of its environment"）。

想"借而不搬"地把闭包送进线程，用 `thread::scope`（1.63.0）把线程关在作用域里，而不是对每个闭包加 `move`——scope 的保证是"线程在作用域结束前 join"，所以闭包借局部变量安全。

## The Three Fn Traits

| trait | 接收者 | 能调用 | 实现条件 |
| :--- | :--- | :--- | :--- |
| `FnOnce` | `self` | 一次 | 总能实现（每个闭包都是 `FnOnce`） |
| `FnMut` | `&mut self` | 多次（可变借用） | 体内不改捕获的所有权 |
| `Fn` | `&self` | 多次（共享借用） | 体内只读捕获 |

三者是**子 trait 关系**：`Fn: FnMut`、`FnMut: FnOnce`。所以要求 `Fn` 的 API 可以收 `FnMut` 的闭包（多一层 `&mut` 的成本），反过来不行。编译器按捕获字段的用法挑能实现的最高档：

```rust
let mut n = 0;
let mut inc = || { n += 1; };        // 写捕获 => FnMut（且是 FnOnce）
let greet = || println!("hi");       // 无捕获 => Fn
let consume = move || drop(vec![1]); // 移动捕获 => 仅 FnOnce
```

选 trait 的判据（写泛型 API 时天天遇到）：**能用 `Fn` 就别用 `FnMut`，能用 `FnMut` 就别用 `FnOnce`**——要求越弱，调用方能传的越多。`FnOnce` 是特例：它表达"这个调用会消耗调用者给的东西"，适合工厂与 one-shot 回调。

## Closures and Lifetimes

闭包的签名里没有生命周期，但它们全在：捕获的引用带进来，`Fn` 的返回值若借自捕获，闭包类型就带一个 HRTB 之外的隐式生命周期。三个常见形态：

1. **闭包借局部变量逃逸**：E0373 `closure may outlive the current function`——编译器直接给 `move` 建议，但 move 是"换捕获方式"而不是"延长生命周期"，若真需要 `'static`，就得 clone 或改结构。
2. **返回引用捕获的闭包**：`|| &x` 这种闭包的类型无法命名，不能返回。要返回"借用型"闭包只能靠 GAT / RPITIT（[Lifetime](/docs/CS/Rust/Lifetime.md) 的 RPIT 捕获规则），stable 上最常见的替代是返回拥有数据的闭包。
3. **`dyn Fn` 的默认生命周期**：`&dyn Fn()` 是 `&(dyn Fn() + '_)`， trait object 的生命周期推断规则与普通引用一致；显式 `Box<dyn Fn() + 'static>` 才是常见的存进结构体的形状。

## Returning Closures

"返回一个闭包"在 Rust 里比想象中麻烦，因为闭包类型无法书写。三种解法按优先级：

```rust
// 1) impl Trait：零成本，闭包类型对调用方透明（stable 长期可用）
fn adder(n: i32) -> impl Fn(i32) -> i32 { move |x| x + n }

// 2) 装箱：需要同一个类型装不同闭包时（如 Vec<Box<dyn Fn(i32) -> i32>>）
fn boxed_adder(n: i32) -> Box<dyn Fn(i32) -> i32> { Box::new(move |x| x + n) }

// 3) 函数指针：闭包不捕获时才能退化成 fn(...)，零大小、可直接比较
fn plain_adder(n: i32) -> fn(i32) -> i32 { move |x| x + n }   // ✗ move 捕获后退化不了
fn pure() -> fn(i32) -> i32 { |x| x * 2 }                     // ✓ 不捕获才能转 fn 指针
```

`impl Fn` 的陷阱是**返回值类型每次调用都不同**：`if cond { adder(1) } else { adder(2) }` 编不过，因为两个闭包是两个类型——这时只能 `Box<dyn Fn>`。`impl Trait` 在返回位置还隐式捕获问题：`-> impl Fn(i32) -> i32` 不自动 `+ 'static`，返回借了局部量的闭包仍会被 E0373 拦下。

## Closures as Arguments: Generic versus dyn

把闭包传进函数有两条路，性能与体积的取舍：

```rust
fn apply_generic<F: Fn(i32) -> i32>(f: F, x: i32) -> i32 { f(x) }   // 单态化，零开销
fn apply_dyn(f: &dyn Fn(i32) -> i32, x: i32) -> i32 { f(x) }        // 虚调用，一份代码
```

- **泛型版**每个闭包类型一份机器码，编译时长与体积换速度；闭包在调用点内联后通常整体消失（[Iterator](/docs/CS/Rust/Iterator.md) 的惰性链就是这么免费下来的）。
- **`dyn` 版**一次间接调用，换来"不同类型闭包共用一份代码"与更小的二进制。判据与 [Trait_System](/docs/CS/Rust/Trait_System.md) 的静态/动态分发一致：热路径、调用点固定用泛型；要存进同质容器、或二进制体积敏感用 `dyn`。
- `fn` 指针是第三种：只收不捕获的闭包与裸函数，零大小、`Copy`、可以当 C 回调（[FFI](/docs/CS/Rust/FFI.md)）。`Option<fn(i32) -> i32>` 因此能走空指针 niche。

## Common Patterns

**1. 回调即策略。** 把"怎么做"参数化而不是继承：`sort_by(|a, b| a.len().cmp(&b.len()))`、`map_with` 一族。闭包让策略在调用点内联，比 `trait Strategy` 对象轻。

**2. 闭包捕获 self 的陷阱。** 方法返回闭包时 `|| self.field` 会捕获 `&self`，闭包类型因此借着对象——想存进结构体就得 `move` + clone，或用 `Rc<Self>`。

**3. 递归闭包。** 闭包不能直接递归（类型无限大），要递归必须拆函数或 `fn` 指针自引用（Y 组合子一类技巧，生产代码极少用）。

**4. 闭包与错误处理。** 返回 `Result` 的闭包可以直接喂 `?`：`let r: Result<_, _> = f();`，但闭包**体内**不能用 `?`——它不是 `fn`。需要提前返回就写成普通函数。

## Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | 以为 `move` 是"延长生命周期" | E0373 依旧 | `move` 只改捕获方式；要 `'static` 得 clone 或 `Rc` |
| 2 | 期望闭包能调用多次但它是 `FnOnce` | E0382 / "cannot be invoked more than once" | 不消耗捕获；或要求 `Fn` 的 API 在编译期就拦下 |
| 3 | 把大闭包塞进 `Box<dyn Fn>` | 一次堆分配 + 虚调用 | 先用泛型；确实要同质容器再装箱 |
| 4 | 闭包捕获整个结构体 | 其它字段被"锁住" | edition 2021 disjoint capture 已按字段捕；2018 下加 `let s = &s.field;` |
| 5 | 返回闭包时两个分支类型不同 | `if/else` 编不过 | 统一 `Box<dyn Fn>` 或提前返回 |
| 6 | 在闭包里 `?` | 编译错误 | 闭包不是 `fn`；拆普通函数 |
| 7 | `dyn Fn` 忘写 `+ Send` | `spawn` 报 not Send | 跨线程的闭包显式 `+ Send + 'static` |
| 8 | 期望 `FnMut` 闭包能并行调用 | 编译错误（`&mut self` 不可共享） | 改 `Fn`（内部用 `Mutex`/原子），或每线程一个 |

## Links

- [Ownership](/docs/CS/Rust/Ownership.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)
- [Iterator](/docs/CS/Rust/Iterator.md)
- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [FFI](/docs/CS/Rust/FFI.md)
- [智能指针](/docs/CS/Rust/Smart_Pointers.md)

## References

1. [The Rust Reference — Closure expressions](https://doc.rust-lang.org/reference/expressions/closure-expr.html)
2. [`std::ops::FnOnce`](https://doc.rust-lang.org/std/ops/trait.FnOnce.html)
3. [`std::ops::FnMut`](https://doc.rust-lang.org/std/ops/trait.FnMut.html)
4. [`std::ops::Fn`](https://doc.rust-lang.org/std/ops/trait.Fn.html)
5. [Edition Guide — Disjoint capture in closures](https://doc.rust-lang.org/edition-guide/rust-2021/disjoint-capture-in-closures.html)
6. [The Rustonomicon — Closures](https://doc.rust-lang.org/nomicon/closures.html)
