## Introduction

Rust 要在**没有 GC、也没有手动 `free`** 的前提下管住内存。两条传统路都被堵死后，剩下的唯一解就是所有权（ownership）：编译器在编译期给每个值指派唯一的所有者，在所有者的生命周期终点静态插入析构调用，再用借用（borrowing）规则保证「任一时刻，一个值要么只有一个写者、要么只有多个读者」。

于是问题从「运行时谁来回收」变成「编译期能否证明析构点正确」。答案是能，但代价不是零：代价付在**签名的表达力**（`&str` 还是 `String`、要不要 `move`）、**编译期的分析工作**（借用检查跑在 MIR 上，做控制流图上的数据流分析），以及**被误拒的合法程序**（NLL 已放宽过一次，Polonius 仍在 nightly 上补剩下的缝隙）。

本篇讲机制层：三条规则各防哪类事故、move 与 `Copy` / `Clone` 的分工、按值传参与部分移动、借用规则为什么等价于「无数据竞争」、借用检查运行在哪里（MIR / NLL / 析构点 / 临时值作用域）、`'static` 与闭包捕获，最后是错误码的真实诊断与跨语言对照。下文所有诊断都是 `rustc 1.98.1` 单文件编译的真实输出，只把路径前缀按 cargo 惯例归一为 `src/main.rs` / `src/lib.rs`。

边界：生命周期**标注语法**、variance、HRTB、RPIT 捕获规则见 [Lifetime](/docs/CS/Rust/Lifetime.md)；`Box` / `Rc` / `Arc` / `RefCell` 见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)；析构顺序与 dropck 见 [Drop](/docs/CS/Rust/Drop.md)；`Send` / `Sync` 见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

## The Three Rules and the Accident Each One Prevents

《The Rust Programming Language》第 4 章的三条规则：每个值有一个所有者（owner）；同一时刻只能有一个所有者；所有者离开作用域时值被丢弃（dropped）。三条单独看都很朴素，合起来正好覆盖 C/C++ 的三类经典事故——关键是第三条，它把「何时释放」变成编译器可推导的静态事实，前两条保证这个释放点前后没有别人再碰这块内存。

| 规则 | 直接防住的事故 | 事故定义 | 触发时的报错 |
| :-- | :-- | :-- | :-- |
| 只有一个所有者 | double free | 同一块堆内存被释放两次 | E0382 |
| 转移后原名字失效 | use-after-free | 读已释放（或已被复用）的内存 | E0382 / E0597 |
| 所有者离开作用域才丢弃 | 悬垂引用逃逸 | 引用比被引用者活得更久 | E0597 / E0716 |
| 一写或多读（借用规则推论） | 数据竞争 | 同址、至少一写、无同步顺序 | E0499 / E0502，跨界再加 `Send` / `Sync` |

用编译器确认第一条不是修辞——把 `drop` 走两次：

```rust
fn main() {
    let mut v: Vec<String> = Vec::new();
    v.push(String::from("a"));
    drop(v);
    drop(v);
}
```

```text
error[E0382]: use of moved value: `v`
 --> src/main.rs:5:10
  |
2 |     let mut v: Vec<String> = Vec::new();
  |         ----- move occurs because `v` has type `Vec<String>`, which does not implement the `Copy` trait
3 |     v.push(String::from("a"));
4 |     drop(v);
  |          - value moved here
5 |     drop(v);
  |          ^ value used here after move
```

注意措辞：编译器没在说「禁止重复释放」，它说的是「`v` 已经被移走」。double free 之所以不可能，是因为 `drop(v)` 是一次**移动**，移动之后那个名字在编译期就不存在了——保护不来自运行时的「是否已释放」标志，而来自名字的失效。这就是「无 GC 也无 free」的真实机制：**析构点被编码进变量的生命期，运行时零簿记**。

## Move, Copy, and Clone

赋值 / 传参 / 返回默认是**移动**：复制值的字节，同时把源名字标记为失效。`String` 与 `Vec` 的栈上部分只有 24 字节（ptr + len + cap），移动的就是这 24 字节，堆缓冲原封不动：

```rust
fn main() {
    let a: Vec<u8> = vec![1, 2, 3];
    let p0 = a.as_ptr();
    let b = a;                                  // move：只复制那 24 字节
    println!("ptr equal after move: {}", std::ptr::eq(p0, b.as_ptr()));
    let c = b.clone();                          // clone：新分配一块堆缓冲
    println!("ptr equal after clone: {}", std::ptr::eq(b.as_ptr(), c.as_ptr()));
}
```

`aarch64-apple-darwin` 上实测输出 `true` 与 `false`。所以 move 与 clone 的差别不在语义而在**是否重新分配**；`Copy` 类型的复制之所以能隐式发生，是因为它的位模式本身就是完整值（无堆指针、无句柄、无引用计数）。

`Copy` 是标记 trait，但它是 `Clone` 的**子 trait**（`pub trait Copy: Clone`）。手写 `pub struct S(pub i32); impl Copy for S {}` 而漏掉 `Clone`，实测得到 E0277 "the trait bound `S: Clone` is not satisfied"，并带一行 "note: required by a bound in `Copy`" 指向 `library/core/src/marker.rs`。为什么必须这样：`Copy` 声明「按位复制就是完整的克隆」，`Clone` 声明「这个类型的克隆有确定的实现」。若允许一个类型 `Copy` 却不 `Clone`，泛型代码里的 `x.clone()` 与「`x` 被隐式复制」就会走两套逻辑——前者可以被自定义成深拷贝、做规范化、注册副作用，后者永远是 memcpy。把 `Copy` 挂成 `Clone` 的子 trait 等于强制两者是同一件事：手写 `Copy` 的类型其 `Clone` 实现通常就写成 `fn clone(&self) -> Self { *self }`（实测这样的实现可编译）。

反过来 `Copy` 与 `Drop` 互斥，`impl Drop for D` 之后再 `impl Copy for D {}` 实测报 E0184：

```text
error[E0184]: the trait `Copy` cannot be implemented for this type; the type has a destructor
 --> src/lib.rs:3:15
  |
3 | impl Copy for D {}
  |               ^ `Copy` not allowed on types with destructors
  |
note: destructor declared here
 --> src/lib.rs:2:19
```

道理同源：`Copy` 意味着「复制完源名字仍有效、可以随便丢弃」，`Drop` 意味着「丢弃有副作用」，同时成立就等于允许「复制一次、析构两次」。

| 机制 | 语义 | 触发方式 | 典型类型 |
| :-- | :-- | :-- | :-- |
| move | 转移唯一所有权，源失效 | 默认：赋值、传参、返回、`for` | `String`、`Vec<T>`、`Box<T>`、闭包 |
| `Copy` | 按位复制，源仍有效 | 隐式 | 整数、`bool`、`char`、`&T`、`[T; N]`（`T: Copy`）、POD 结构体 |
| `Clone` | 显式克隆，可能分配 | 必须写 `.clone()` | 几乎所有类型（`derive` 逐字段要求 `Clone`） |

> [!NOTE]
> `#[derive(Clone, Copy)]` 生成**带条件的实现**（`impl<T: Copy> Copy for Pair<T>`）。实测对 `fn dup<T>(p: Pair<T>) -> (Pair<T>, Pair<T>) { (p, p) }` 报 E0382 并提示 "consider restricting type parameter `T` with trait `Copy`"。约束写法见 [Generics](/docs/CS/Rust/Generics.md)。

## Moves at Function Boundaries

按值传参就是索取所有权，按值返回就是交出所有权；调用方若还想用那个名字，就得付一次 `clone`。这条形状最常被撞上，而编译器给的也不是 `clone`，是「把参数改成借用」——它在告诉你正确的修法在签名上：

```rust
fn main() {
    let s = String::from("hello");
    print_owned(s);
    println!("{}", s);
}
fn print_owned(v: String) { println!("{}", v); }
```

```text
error[E0382]: borrow of moved value: `s`
 --> src/main.rs:4:20
  |
2 |     let s = String::from("hello");
  |         - move occurs because `s` has type `String`, which does not implement the `Copy` trait
3 |     print_owned(s);
  |                 - value moved here
4 |     println!("{}", s);
  |                    ^ value borrowed here after move
  |
note: consider changing this parameter type in function `print_owned` to borrow instead if owning the value isn't necessary
 --> src/main.rs:6:19
  |
6 | fn print_owned(v: String) { println!("{}", v); }
  |    -----------    ^^^^^^ this parameter takes ownership of the value
```

`for` 循环是同一机制的隐藏版本：它脱糖成 `into_iter()`，因此默认**吃进**整个集合。实测 `for s in v { ... }` 之后再读 `v` 报 E0382，诊断里那句 "`v` moved due to this implicit call to `.into_iter()`" 正是借用检查在 MIR 上工作的自白——源码里没写的调用，它照单全收；给出的 help 是 `for s in &v`。`into_iter` / `iter` / `iter_mut` 三种遍历的取舍见 [Collections](/docs/CS/Rust/Collections.md)。

于是 API 形状是一个必须提前做的决定：`fn f(s: &str)` 只借、`fn f(s: String)` 索取，二者不兼容且不能事后改；`impl AsRef<str>` / `impl Into<String>` / `Cow<_>` 是同一取舍的不同赌注（实测 `takes_str(&owned_string)` 靠 deref coercion 可行，而 `takes_owned(owned)` 会移动、逼出 `.clone()`）。

## Partial Moves and Field-Level Ownership

所有权**按字段记账**，不按变量名。非 `Copy` 字段被移走后，结构体其余部分仍可用，但整个值不可用：

```rust
struct Point { x: String, y: String }
fn whole(_p: Point) {}
fn main() {
    let p = Point { x: String::from("a"), y: String::from("b") };
    let a = p.x;
    whole(p);
    println!("{}", a);
}
```

```text
error[E0382]: use of partially moved value: `p`
 --> src/main.rs:6:11
  |
5 |     let a = p.x;
  |             --- value partially moved here
6 |     whole(p);
  |           ^ value used here after partial move
  |
  = note: partial move occurs because `p.x` has type `String`, which does not implement the `Copy` trait
```

把 `p.x` 重新赋值，`whole(p)` 就恢复可用（实测通过）——记账对象是「每个字段是否持有值」。字段级记账同时解释了另外三条边界：定长数组禁止部分移动（实测 E0508 "cannot move out of type `[String; 2]`, a non-copy array"，下标可以是运行期的，无法逐要素记账，只能整体禁止）；`Vec` 索引禁止移出（实测 E0507 "cannot move out of index of `Vec<String>`"，移走一个元素会在缓冲区留下一个「无值」槽位，破坏 `Vec` 不变式）；实现 `Drop` 的类型禁止部分移动（实测 E0509 "cannot move out of type `Guarded`, which implements the `Drop` trait"，析构函数可能读到那个字段，dropck 见 [Drop](/docs/CS/Rust/Drop.md)）。

要从容器里合法取走元素，只能走**在同一步里改变容器不变式**的接口：`Vec::pop` / `remove` / `swap_remove` / `drain`、`Option::take`、`std::mem::replace`。它们需要 `&mut self` 正是这个原因。同理，`fn f(r: &String) -> String { *r }` 报 E0507 "cannot move out of `*r` which is behind a shared reference"——借来的值给不出去。

## Borrowing: One Writer or Many Readers

`&T` 是共享借用，`&mut T` 是独占借用。规则两句：`&mut T` 不能与任何其他借用同时存在；`&T` 之间可以共存。

「这条规则和数据竞争无关」的直觉是错的——它就是为数据竞争写的。数据竞争要四个条件同时成立：同一地址、至少一个写、无同步顺序、不同线程。其中「同址 + 至少一写」可以静态排除：只要写权限唯一且可追踪，就不可能有两个访问者对同一地址交错访问。`&mut T` 是独占写令牌（既不能与另一个 `&mut` 共存，也不能与任何 `&T` 共存），`&T` 只能读，于是前三项在类型层被压掉；第四项由 `Send` / `Sync` 与生命周期接手（见 [Concurrency](/docs/CS/Rust/Concurrency.md)）。Rust 的并发安全因此不是「线程库做得好」，而是 `aliasing XOR mutation` 这条局部规则的外推。

```rust
fn main() {
    let mut v = vec![1, 2, 3];
    let r = &v;
    v.push(4);
    println!("{:?}", r);
}
```

```text
error[E0502]: cannot borrow `v` as mutable because it is also borrowed as immutable
 --> src/main.rs:4:5
  |
3 |     let r = &v;
  |             -- immutable borrow occurs here
4 |     v.push(4);
  |     ^^^^^^^^^ mutable borrow occurs here
5 |     println!("{:?}", r);
  |                      - immutable borrow later used here
```

两个易被忽略的推论：

**`&T` 是 `Copy` 的，即使 `T` 不是；`&mut T` 不是。** 复制引用只复制地址，不新增别名权限，所以 `fn ref_is_copy(b: &Big) { needs_copy(b) }` 编译通过，而把 `Big`（无 `Copy`）换成 `&mut Big` 就得到 E0277——编译器顺手把这条不对称写进了 note：

```text
error[E0277]: the trait bound `&mut Big: Copy` is not satisfied
  --> src/lib.rs:10:78
   |
10 | pub fn mut_ref_is_not_copy(b: &mut Big) -> (&mut Big, &mut Big) { needs_copy(b) }
   |                                                                   ---------- ^ the trait `Copy` is not implemented for `&mut Big`
   |
   = note: `Copy` is implemented for `&Big`, but not for `&mut Big`
```

`&mut T` 不是 `Copy`，它是线性使用的令牌——「独占写可被静态证明」的技术支点正是这条不对称。

**再借用（reborrow）让令牌移交很省。** 把 `&mut v` 传给 `fn f(x: &mut Vec<i32>)` 时编译器自动插入 `&mut *v`，原借用只在调用期间冻结、之后恢复；手写 `let r = &mut *v;` 与 `let read = &*v;` 都实测可编译。但两个同时活跃、之后还要用的 `&mut` 立刻撞墙：

```text
error[E0499]: cannot borrow `*v` as mutable more than once at a time
 --> src/lib.rs:4:13
  |
2 |     let r = &mut *v;
  |             ------- first mutable borrow occurs here
3 |     r.push(1);
4 |     let s = &mut *v;
  |             ^^^^^^^ second mutable borrow occurs here
5 |     s.push(2);
6 |     println!("{}", r.len());
  |                    - first borrow later used here
```

`Cell` / `RefCell` 是这条规则的受控后门：它们在 `&self` 上提供内部可变性，代价是把「一写或多读」从编译期搬到运行期计数器（实测 `RefCell` 在已有活跃 `borrow` 时再 `borrow_mut` 会 panic：`RefCell already borrowed`）。机制见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)，本篇不展开。

## Where the Borrow Checker Runs

借用检查不在 AST / HIR 上做，而在 **MIR** 上做——rustc-dev-guide 的 borrow-check 章原话是 "The borrow checker operates on the MIR. An older implementation operated on the HIR"。原因有两层：MIR 已经脱糖（`a = b + c + d` 拆成带临时变量的多条语句、`for` 拆成 `into_iter` 调用、每个析构点是一条独立的 `drop(lvalue)`），且 MIR 是**控制流图**，于是能做真正的数据流分析。下面三小节是这套架构能被观测到的三个后果。

### NLL Tracks Liveness, Not Curly Braces

早期的词法作用域检查把借用区域绑在 `let` 所在的块上；NLL（non-lexical lifetimes，RFC 2094）把区域改成**从 CFG 上算出的活跃区间**：借用活到最后一次使用为止。最直接的实验是同一个函数删掉一行：

```rust
pub fn illegal(v: &mut Vec<i32>) -> usize {
    let head = v.first();
    if head == Some(&1) {
        v.push(2);
    }
    println!("{:?}", head);
    v.len()
}
```

```text
error[E0502]: cannot borrow `*v` as mutable because it is also borrowed as immutable
 --> src/lib.rs:4:9
  |
2 |     let head = v.first();
  |                - immutable borrow occurs here
3 |     if head == Some(&1) {
4 |         v.push(2);
  |         ^^^^^^^^^ mutable borrow occurs here
5 |     }
6 |     println!("{:?}", head);
  |                      ---- immutable borrow later used here
```

把第 6 行那个 `println!` 删掉（其余一字不动）就**实测编译通过**。同一行 `v.push(2)` 合法与否只取决于 `head` 之后是否还被读——词法作用域模型解释不了这个，只有「区域 = 活跃区间」能解释。分支上的移动同理：`if c { let t = s; t.len() } else { s.len() }` 实测通过（两条路径各移动一次），而 `if c { let _t = s; } s.len()` 得到 E0382——编译器沿 CFG 合并路径，而不是「作用域里出现过 move 就一律作废」。

`println!` 也常被误认为「借用持续到块尾」。它只在语句期间借走格式化参数，所以 `let r = &v; println!("{r:?}"); v.push(4);`（`r` 之后不再使用）实测合法。

### Destruction and Move Are the Real Use Sites

每个析构在 MIR 上是一条 `drop(lvalue)`，因此**把析构提前到某条语句**（`std::mem::drop(v)` 本质是移动）就在那个位置制造了一个使用点：之后还要用借用就冲突。实测报 E0505：

```text
error[E0505]: cannot move out of `v` because it is borrowed
 --> src/main.rs:5:20
  |
3 |     let r = &v;
  |             -- borrow of `v` occurs here
4 |     println!("{}", std::hint::black_box(r.len()));
5 |     std::mem::drop(v);
  |                    ^ move out of `v` occurs here
6 |     println!("{}", std::hint::black_box(r.len()));
  |                                         - borrow later used here
```

反过来要提醒一句，很多旧文章写错的正是这里：**隐式的块尾析构并不会把借用拖到块尾**。实测一个实现了 `Drop` 的 `struct WithDrop(String)`，`let r = &w;` 用完之后照样可以 `w.0.push('!')`——借用仍按活跃性结束，编译器不会因为「这个类型有析构函数」就把它的共享借用延长到作用域末尾（对 `Vec<String>` 这类有 drop glue 的类型同样成立）。所谓 drop liveness 只在借用真的横跨了析构点时才咬人。

而**手动调用析构方法被禁止**，用的是独立错误码 E0040（`struct Guard; impl Drop for Guard { fn drop(&mut self) {} }`，然后 `let mut g = Guard; Drop::drop(&mut g);`）：

```text
error[E0040]: explicit use of destructor method
 --> src/main.rs:5:5
  |
5 |     Drop::drop(&mut g);
  |     ^^^^^^^^^^ explicit destructor calls not allowed
  |
help: consider using `drop` function
  |
5 -     Drop::drop(&mut g);
5 +     drop(g);
```

这条禁令正是本篇主线的反面：`Drop::drop(&mut g)` 让析构提前发生，而 `g` 这个名字仍然有效、离开作用域时还会再析构一次——同一个值析构两遍，正是所有权模型承诺消灭的那类事故，而它偏偏绕过了「名字失效」这道防线（名字没被移走）。所以 rustc 直接把方法本身封掉。要提前结束借用就用嵌套作用域；要放弃析构就用 `ManuallyDrop` / `mem::forget`。

### The Lifetime of Temporaries Is the Real Boundary of a Borrow

借用一个临时值时，临时值的销毁时刻决定借用能否成立。实测 `let r: &str = format!("{x}").as_str();` 之后再用 `r` 得到 E0716 "temporary value dropped while borrowed"，诊断同时标出 "temporary value is freed at the end of this statement" 与 "consider using a `let` binding to create a longer lived value"。

Rust 2024 edition（1.85.0，2025-02-20）改了两处临时值作用域，都落在这条边界上（Edition Guide 的 "if let temporary scope" 与 "Tail expression temporary scope"）。同一份源码跨 edition 的实测差异：

```rust
use std::cell::RefCell;
fn main() {
    let c = RefCell::new(vec![1, 2, 3]);
    if let Some(x) = c.borrow().iter().find(|&&i| i == 9).copied() {
        println!("{x}");
    } else {
        println!("else branch, len = {}", c.borrow().len());
    }
}
```

`--edition 2021` 报 E0597，诊断把因果写得很直白："a temporary with access to the borrow is created here ... and the borrow might be used here, when that temporary is dropped and runs the destructor for type `Ref<'_, Vec<i32>>`"；`--edition 2024` 编译通过并打印 `else branch, len = 3`。块尾表达式同理：`fn f() -> usize { let c = RefCell::new(".."); c.borrow().len() }` 在 2021 报 E0597、在 2024 通过。这两条都不是「编译器变聪明了」，而是**析构点被重新安排**，借用检查如实反映出来。

### Polonius Is the Next Step, Still on nightly

NLL 对「区域在循环里是否重叠」偏保守。经典形状是边遍历边 `remove`：`for (name, value) in &mut *m { if *value == to { m.remove(name); } }`（`m: &mut HashMap<String, u32>`）。实测 `rustc 1.98.1` 报 E0499，"first borrow later used here" 指向整个 `for` 头。现实写法要么先收集键再改，要么用 `extract_if`（`Vec` / `LinkedList` 上的 `extract_if` 稳定于 1.87.0）。Polonius 用按位置区分的 loan 判定来接受这类代码，但至今 nightly-only（Unstable Book 的 compiler flag `polonius`；官方 2026-08-04 才把它以 alpha 形式开到 nightly），stable 上任何 `-Z` 都被拒：`error: the option `Z` is only accepted on the nightly compiler`。

## 'static and move Closures

`'static` 有两个方向相反的用法，混起来就看不懂报错。作为**引用类型**，`&'static T` 表示这个引用永远有效（字符串字面量正是它）；作为**约束**，`T: 'static` 表示 `T` 内部不含任何非 `'static` 的引用，即「它拥有自己的全部数据」。

```rust
fn takes_static<T: 'static>(_t: T) {}
fn main() {
    let s: &'static str = "literal";
    takes_static(String::from("owned"));
    takes_static(s);
    let local = 5u8;
    takes_static(&local);
}
```

前三行实测通过（`String` 与被泄漏不了的 `&'static str` 都满足约束），最后一行报 E0597：

```text
error[E0597]: `local` does not live long enough
 --> src/main.rs:7:18
  |
6 |     let local = 5u8;
  |         ----- binding `local` declared here
7 |     takes_static(&local);
  |     -------------^^^^^^-
  |     |            |
  |     |            borrowed value does not live long enough
  |     argument requires that `local` is borrowed for `'static`
8 | }
  | - `local` dropped here while still borrowed
```

`T: 'static` 是零成本的约束：它不要求泄漏，只要求不借别人的东西，于是 `String`、`Vec`、`i32` 与所有不含引用的具体类型都满足。真正制造 `'static` 值的方式是把所有权交给堆并放弃析构（`Box::leak` 返回 `&'static mut T`，实测可用；`mem::forget` 同族）。注意 1.99.0 起官方文档已改为**不推荐**「`Box::leak` 之后再 `Box::from_raw` 回收」这种玩法，改用 `Box::into_raw` / `Box::into_non_null` 表达移交（`into_non_null` 在本机 1.98.1 仍 unstable，实测 E0658 "use of unstable library feature `box_vec_non_null`"）。

把值交给别的线程是这条约束最常撞墙的地方。`thread::spawn` 要求闭包 `FnOnce() + Send + 'static`，「借本地变量」直接失败，而编译器给的修法正是 `move`：

```text
error[E0373]: closure may outlive the current function, but it borrows `v`, which is owned by the current function
 --> src/main.rs:3:24
  |
3 |     std::thread::spawn(|| { println!("{:?}", v); });
  |                        ^^                    - `v` is borrowed here
  |                        may outlive borrowed value `v`
  |
note: function requires argument type to outlive `'static`
help: to force the closure to take ownership of `v` (and any other referenced variables), use the `move` keyword
  |
3 |     std::thread::spawn(move || { println!("{:?}", v); });
  |                        ++++
```

`move` 做的不是「搬走什么」，而是**改变捕获方式**：默认按最小权限捕获（体内怎么用就怎么捕：只读用 `&`、要改用 `&mut`、要消耗就按值），加 `move` 则一律按值。按值捕获可能就是移动，于是闭包自己成为唯一所有者——`move || drop(s)` 之后 `s` 失效，且这个闭包成了 `FnOnce`，调用一次即被消耗（实测第二次调用报 E0382，附注 "closure cannot be invoked more than once because it moves the variable `s` out of its environment"）。想借而不搬，用 `thread::scope`（1.63.0）把线程关在作用域里。

Rust 2021 起闭包捕获做了字段级细化（disjoint capture），粒度与非 `Copy` 字段的局部借用一致：`let print = || println!("{}", c.port); c.host = String::from("x"); print();` 实测在 `--edition 2015` / `2018` 报 E0506 "cannot assign to `c.host` because it is borrowed"，在 `--edition 2021` / `2024` 通过——因为闭包只捕了 `c.port`。`Fn` / `FnMut` / `FnOnce` 三档与 `impl Trait` 返回闭包的写法见 [Trait_System](/docs/CS/Rust/Trait_System.md)。

## What the Compiler Decides, and Where the Cost Lands

所有权对目标码的额外要求几乎为零，值得用数字说清。`rustc 1.98.1` / `aarch64-apple-darwin` 实测（`--edition 2024 -O` 直接运行打印）：

| 类型 | size_of | align_of | 数据在哪 |
| :-- | :-- | :-- | :-- |
| `u8` / `i64` | 1 / 8 | 1 / 8 | 值即全部，栈上或内联进父结构 |
| `(u8, u64)` | 16 | 8 | 栈（对齐填充吃掉 7 字节） |
| `String` / `Vec<u8>` | 24 | 8 | 栈上胖指针 + 堆缓冲 |
| `&[u8]` | 16 | 8 | 胖引用（ptr + len），不拥有 |
| `Box<u8>` / `Rc<u8>` / `Arc<u8>` | 8 | 8 | 8 字节指针，拥有语义写在类型里 |
| `Option<&u8>` / `Option<Box<u8>>` | 8 | 8 | 无额外 tag，空指针 niche |
| `&dyn Debug` | 16 | 8 | ptr + vtable |

编译期决定：值的大小与对齐、栈还是堆（由**类型**决定，不是逃逸分析）、每条 CFG 边上的析构时刻、每个借用的起止点。运行期剩下：这些决策落地后的普通指令。对照 Go 最清楚——Go 的逃逸分析**替程序员决定** `x := 42; return &x` 里 `x` 放哪（`go build -gcflags=-m` 实测打印 `moved to heap: x`），Rust 由类型明说（`Box::new(42)` 才是堆），不引入隐式分配决策。布局细节见 [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)。

那代价付在哪？四类，全在**写代码时**而不在运行时：签名必须提前回答要不要所有权（上一节的 `&str` / `String` 取舍）；数据结构必须能被静态记账（自引用结构、图、双向链表、共享可变状态都不自然，得换成 arena 索引、`Rc<RefCell<_>>` 或 `unsafe`）；合法程序会被误拒（NLL 与 2024 的临时值作用域改动方向都是**放宽**，本身就说明原判定过保守，Polonius 还在补）；以及编译期开销（CFG 上的数据流分析加上泛型单态化，管线见 [compile](/docs/CS/Rust/compile.md)）。

## Cross-Language Comparison

| 维度 | Rust | C++ | Go | Java |
| :-- | :-- | :-- | :-- | :-- |
| 变量存什么 | 值本体，引用是带规则的视图 | 值本体，引用 / 指针是视图 | 值本体；slice / map 是带隐藏指针的头部 | 只有对象引用，无值语义 |
| 赋值 / 传参 | move（源失效）；`Copy` 类型按位复制 | 按值拷贝；`std::move` 才转移 | 整份值拷贝（slice / map 只拷头部） | 拷引用，永不拷对象 |
| 移动后原值 | 编译期失效，读它 E0382 | 有效但未指定，照常可读可重赋值 | 无「移动」概念 | 不适用 |
| 释放由谁决定 | 编译期插桩的析构点 | 作用域结束 / `delete` | GC | GC |
| 深拷贝 | 显式 `.clone()` | 拷贝构造 / Rule of Five | 手写（无内建深拷贝） | 浅 `clone()` + `Cloneable` |
| 别名 + 可变 | `aliasing XOR mutation`，编译期 | 无约束，靠约定与 ASan / UBSan | 无约束，靠 `-race` 运行期检测 | 无约束，靠 JMM + 同步 |
| 栈 / 堆归属 | 类型明说（`Box` / `Vec`） | 类型明说（`new`） | 逃逸分析决定 | 对象一律堆上 |
| 违反的代价 | 编译失败 | 运行期 UB（double free / UAF） | 运行期 race 或内存滞留 | 运行期 race 或对象永生 |
| 成本主要付在 | 表达力与编译期 | 正确性纪律（工具 + 人） | 运行期 GC 与 race 检测 | 运行期 GC 与堆占用 |

对照 [C++ 的移动语义](/docs/CS/C++/Move.md) 时最容易记错的是强度差：C++11 的「移动后有效但未指定」与 Rust 的「移动后不可用」不是一个量级的承诺。实测 `clang++ -std=c++17`：moved-from 的 `std::string` 把堆缓冲直接交给目标（`data()` 指针相同、`size()` 变 0），随后 `a = "reassigned"` 合法且良定义；Rust 里同样的复用必须靠重新赋值把名字「复活」，或者改设计。另两处实测对照：Go 里 `for _, x := range s` 改 `x` 不影响切片元素（值拷贝），但 `a := s; a[0].n = 7` 会改到 `s`（头部拷贝、底层数组共享）——「共享还是复制」取决于类型；Java 里赋值只拷引用（实测 `List<Integer> y = x; y.set(0, 99);` 之后 `x` 就是 `[99, 2, 3]`）。GC 一侧见 [memory/GC](/docs/CS/memory/GC.md) 与 [Go GC](/docs/CS/Go/GC.md)，横向速览见 [Languages](/docs/CS/Languages.md)。

## Error Codes You Will Actually Hit

| 码 | 首行（本机实测措辞） | 根因 | 修法 |
| :-- | :-- | :-- | :-- |
| E0382 | borrow of moved value: `s` / use of partially moved value: `p` | 名字已交出所有权 | 改传 `&T`、`.clone()`、`Option::take()`，或重新赋值让名字复活 |
| E0499 | cannot borrow `*v` as mutable more than once at a time | 两个 `&mut` 同时活跃 | 收窄借用范围、先收集再改、`mem::replace` |
| E0502 | cannot borrow `v` as mutable because it is also borrowed as immutable | `&T` 与 `&mut T` 的活跃区间重叠 | 让只读借用更早结束（NLL 只认最后一次使用） |
| E0505 | cannot move out of `v` because it is borrowed | 移动 / 析构点落在借用区间内 | 把使用挪到移动之前，或先 `clone` 引用侧 |
| E0506 | cannot assign to `c.host` because it is borrowed | 赋值要先析构旧值，与借用冲突 | 结束借用后再赋值；2021+ 的 disjoint capture 常自动解决 |
| E0507 | cannot move out of `*r` which is behind a shared reference | 借来的值给不出去 | 签名改 `&mut` 或按值，或 `clone` |
| E0508 | cannot move out of type `[String; 2]`, a non-copy array | 下标可运行期化，无法逐要素记账 | 换元组 / `Vec` + `remove` / `Option` 包裹 |
| E0597 | `x` does not live long enough | 引用比被引用者活得久 | 缩短引用存活区、把值放到更长生命周期的绑定上、改拥有型 |
| E0716 | temporary value dropped while borrowed | 临时值在语句末析构 | 用 `let` 绑定延长生命，或靠 2024 的新临时值作用域 |
| E0040 | explicit use of destructor method | 手动调 `Drop::drop` | 用 `drop`（移动）或嵌套作用域；确需手动则 `ManuallyDrop` |

E0502 那一段的读法值得自己跑一遍：`rustc --edition 2024 --crate-type lib` 下对 `v.first()` 那个函数增删一行 `println!`，你会亲眼看到「借用不绑在花括号上，而绑在活跃性上」。

## Links

- [Rust](/docs/CS/Rust/Rust.md)
- [Lifetime](/docs/CS/Rust/Lifetime.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Drop](/docs/CS/Rust/Drop.md)
- [Memory_Layout](/docs/CS/Rust/Memory_Layout.md)
- [Move](/docs/CS/C++/Move.md)

## References

- [The Rust Programming Language - What Is Ownership](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html)
- [The Rust Programming Language - References and Borrowing](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)
- [RFC 2094 - Non-lexical lifetimes](https://rust-lang.github.io/rfcs/2094-nll.html)
- [rustc-dev-guide - The borrow checker](https://rustc-dev-guide.rust-lang.org/borrow-check.html)
- [rustc-dev-guide - MIR](https://rustc-dev-guide.rust-lang.org/mir/index.html)
- [Unstable Book - -Zpolonius](https://doc.rust-lang.org/unstable-book/compiler-flags/polonius.html)
- [The Rust Reference - Destructors](https://doc.rust-lang.org/reference/destructors.html)
- [The Rustonomicon - Ownership and Lifetimes](https://doc.rust-lang.org/nomicon/ownership.html)
- [Edition Guide - if let temporary scope](https://doc.rust-lang.org/edition-guide/rust-2024/temporary-if-let-scope.html)
- [Edition Guide - Tail expression temporary scope](https://doc.rust-lang.org/edition-guide/rust-2024/temporary-tail-expr-scope.html)
- [Edition Guide - Disjoint capture in closures](https://doc.rust-lang.org/edition-guide/rust-2021/disjoint-capture-in-closures.html)
- [std::marker::Copy](https://doc.rust-lang.org/std/marker/trait.Copy.html)
- [std::clone::Clone](https://doc.rust-lang.org/std/clone/trait.Clone.html)
- [Rust Release Notes](https://doc.rust-lang.org/1.99.0/releases.html)
