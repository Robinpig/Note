## Introduction

Rust 的析构（destructor）不是 C++ 那种"你在类里写一个 `~T()`，然后祈祷对象的所有者记得在正确的时机销毁它"。Rust 没有析构函数这个语法，却有比 C++ 更强的释放保证：**每个拥有资源的类型在编译期被绑定到一个确定的所有权终点，编译器保证资源一定在那个点被回收**。你几乎不需要写析构逻辑——`Drop` 是可选的，只有"除了递归 drop 字段之外还要做额外动作"（关文件、解锁、归还连接）时才需要实现它。

本篇讲清楚 RAII 的另一半：为什么"不写析构函数"也能保证释放；**释放顺序**（局部变量、临时量、结构体字段、元组各走各的规则，edition 2024 改变了 `if let` 与 tail expression 的临时量作用域）；`Drop::drop` / `std::mem::drop` / `mem::replace` / `Option::take` 四个"释放入口"；实现 `Drop` 的三条硬限制（dropck、不能重载、拿不到 `self` 所有权）；`ManuallyDrop` / `MaybeUninit` / `mem::forget` 与"泄漏即安全（leaking is memory-safe）"；panic 的 unwind 与析构、`extern "C"` 边界的特殊性；为什么对锁与文件句柄**不该依赖析构**而应显式 `close()`；`Box::leak` 与 1.99.0 的 FFI 新指引；与 C++ 析构、Go `defer`、Java try-with-resources / `Cleaner` 的精确对照。

所有权与移动的规则本身见 [Ownership](/docs/CS/Rust/Ownership.md)，本篇只谈"值生命周期的终点会触发什么"。

## Why no destructor yet release is guaranteed

C++ 的 RAII 依赖一个前提：**对象必须经过某个 `}` 被销毁**。但 C++ 对象可以泄漏（`new` 出来忘了 `delete`）、可以在栈上被越界写坏、可以在悬垂引用上被"用后即弃"。Rust 把"何时释放"从一个运行时问题降为编译期问题：

1. 每个值恰好有一个所有者（owner）。
2. 所有权要么传到新绑定（move，原绑定失效），要么停在某个作用域的末尾。
3. 在所有者离作用域、或所有权被移走的那一行，编译器**自动插入**对 `drop`（更准确说是 drop glue，见下节）的调用。

所以"资源一定被释放"不需要析构函数存在，只需要类型系统追踪所有权。`Drop` trait 只是让你在"编译器已经决定要释放"的那一刻**追加自定义动作**：

```rust
struct File { handle: u32 }
unsafe extern "C" { fn close(fd: i32) -> i32; }
impl Drop for File {
    fn drop(&mut self) { unsafe { close(self.handle as i32) }; }
}
```

如果你不写 `impl Drop`，编译器仍会在所有点插入 drop——只不过这个类型没有"额外动作"，或者根本没有需要释放的资源。

> [!NOTE]
> **drop glue 与 `Drop::drop` 不是一回事**。编译器为每个类型生成的释放代码叫 *drop glue*：它负责递归释放字段与数组元素；只有当类型（或其某个泛型实参）实现了 `Drop` 时，glue 才会额外调用你的 `Drop::drop`。也就是说 `impl Drop` 的函数体只是"字段释放前"的钩子，字段随后仍会被逐个 drop。

## Drop order

释放顺序是最容易记错的部分。三条主规则：

| 场景 | 顺序 |
| :--- | :--- |
| 同一作用域的局部变量 | **逆声明序**（最后声明的最先释放） |
| 结构体字段 | **声明顺序**（第一个字段最先释放）——与局部变量**相反** |
| 元组元素 | **从左到右** |
| 函数调用的参数临时量 | 进入被调函数体后，在调用结束时按 **逆序** 释放 |

下面的程序一次性验证前四条（`rustc 1.98.1`, `aarch64-apple-darwin`, `--edition 2024 -O` 实测，输出逐行照抄）：

```rust
struct No(&'static str);
impl Drop for No { fn drop(&mut self){ println!("  drop {}", self.0); } }

#[derive(Default)]
struct Arg(&'static str);
impl Drop for Arg { fn drop(&mut self){ println!("  drop arg {}", self.0); } }
fn f(_a: Arg, _b: Arg) { println!("  (in f body)"); }

struct Pair { first: No, second: No }

fn main() {
    println!("[1] 局部变量：逆声明序");
    {
        let _a = No("a");
        let _b = No("b");
        let _c = No("c");
    }
    println!("[2] 函数参数临时量：进入函数体后、按逆序在调用结束时 drop");
    f(Arg("x"), Arg("y"));
    println!("[3] 结构体字段：按声明顺序（与局部变量相反！）");
    {
        let _p = Pair { first: No("first"), second: No("second") };
    }
    println!("[4] 元组：同样按从左到右的顺序");
    {
        let _t = (No("t0"), No("t1"));
    }
    println!("[5] mem::drop 只是普通函数，立即 move 进形参并 drop");
    {
        let v = No("via mem::drop");
        println!("  (before std::mem::drop)");
        std::mem::drop(v);
        println!("  (after std::mem::drop)");
    }
}
```

实际输出：

```text
[1] 局部变量：逆声明序
  drop c
  drop b
  drop a
[2] 函数参数临时量：进入函数体后、按逆序在调用结束时 drop
  (in f body)
  drop arg y
  drop arg x
[3] 结构体字段：按声明顺序（与局部变量相反！）
  drop first
  drop second
[4] 元组：同样按从左到右的顺序
  drop t0
  drop t1
[5] mem::drop 只是普通函数，立即 move 进形参并 drop
  (before std::mem::drop)
  drop via mem::drop
  (after std::mem::drop)
```

**为什么结构体字段是"声明顺序"而局部变量是"逆序"？** 局部变量在作用域内按声明先后逐个构造，编译器按构造栈的逆序插入 drop；而结构体字段作为整体被 drop 时，drop glue 按字段偏移从前往后处理。这导致一个真实陷阱——**若字段 A 的生命必须长于字段 B，A 必须声明在 B 后面**（A 后 drop；C++ 里恰好相反）。锁与守卫、分配器与被分配数据之间的顺序敏感，多半栽在这条上。

**移动后原绑定失效**：值被 move 到新所有者后，只有新所有者会 drop，原绑定不再拥有值（实测 `let y = x;` 之后只有一个 `drop x`）。

**部分移动后只 drop 未移动的字段**：结构体某字段被移走后，那个字段随新所有者释放，其余字段随原所有者释放，编译器追踪字段的"已移出"状态：

```rust
struct P(&'static str);
impl Drop for P { fn drop(&mut self){ println!("  drop {}", self.0); } }
struct Pair { a: P, b: P }
fn main() {
    let escaped: P;
    {
        let p = Pair { a: P("a"), b: P("b") };
        escaped = p.a;               // 字段 a 移出
        println!("  (inner block end: only b drops here)");
    }
    // 内部块结束：只 drop p.b（a 已移出）
    println!("  (escaped now dropped)");
    drop(escaped);                   // 之后才 drop a
}
// 输出：
//   (inner block end: only b drops here)
//   drop b
//   (escaped now dropped)
//   drop a
```

### Temporary scopes and the edition 2024 change

临时量（没有被 `let` 绑定的中间值）默认在**所在语句结束**时释放。`if let` 与块尾表达式（tail expression）是两处例外，而 **edition 2024 改变了这两处临时量的作用域**（`if_let_rescope` / `tail_expr_drop_order` 两个迁移 lint 就是为它们准备的）。

**`if let` 的 scrutinee 临时量**：edition 2021 里，`if let Some(x) = <expr>` 中 `<expr>` 产生的临时量活到整个 `if let ... else` 表达式结束（含 `else` 分支）；**edition 2024 把它缩短为"then 分支求值完、或控制流进入 `else` 之前"**。这正是经典死锁的成因——`RwLock` 读锁守卫（`RwLockReadGuard`）临时量若在 2021 里活过 `else`，而 `else` 又去 `write()`，就会死锁。

用一个打印 `Drop` 的"读锁守卫"复刻这个时序（同一份源码，两个 edition）：

```rust
struct Guard(&'static str);
impl Drop for Guard { fn drop(&mut self){ println!("  drop {}", self.0); } }
struct Rw;
impl Rw { fn read(&self) -> Guard { Guard("read-lock") } }
impl Guard { fn get(&self) -> Option<u8> { None } }   // 强制走 else 分支

fn main() {
    let rw = Rw;
    if let Some(_x) = rw.read().get() {
        println!("  then branch");
    } else {
        println!("  else branch: is read-lock STILL held here?");
    }
    println!("  end of if-let statement");
}
```

实测（`rustc 1.98.1`, `aarch64-apple-darwin`, `-O`）：

```text
===== if-let else  (edition 2021) =====
  else branch: is read-lock STILL held here?
  drop read-lock
  end of if-let statement
===== if-let else  (edition 2024) =====
  drop read-lock
  else branch: is read-lock STILL held here?
  end of if-let statement
```

2021 里 `read-lock` 在 `else` **之后**才 drop（守卫仍在持锁 → 若 `else` 去拿写锁即死锁）；2024 里在 `else` **之前**就 drop 了。

**块尾表达式（tail expression）的临时量**：edition 2024 让 tail 表达式产生的临时量**在块结束处、局部变量之前**就被 drop，而 2021 会把临时量作用域延伸到块外的下一个边界（语句末或函数体末）。两个方向都能出问题：

- 2021 报错、2024 通过的典型：`fn f() -> usize { let c = RefCell::new(".."); c.borrow().len() }`。2021 下 `c.borrow()` 的 `Ref` 临时量活到 `c` 之后，编译器判 `c` 在仍被借用时就要 drop——真实诊断：

  ```text
  error[E0597]: `c` does not live long enough
    = note: the temporary is part of an expression at the end of a block;
            consider forcing this temporary to be dropped sooner, before the block's local variables are dropped
  ```
  2024 下 tail 临时量先 drop，代码正常编译。
- 2021 通过、2024 报错的反向例子：`let x = { &String::from("1234") }.len();`。2024 下临时量 `String` 在块末就被 drop，`&String` 悬垂：`error[E0716]: temporary value dropped while borrowed`。修法是把块提成局部变量：`let s = { &String::from("1234") }; let x = s.len();`。

> [!WARNING]
> `if let` 的作用域改动是**单向收紧**（提前 drop，多数是修死锁 bug）；tail 表达式的作用域改动可能**双向**：既让 2021 的 E0597 消失，又可能让 2021 依赖"临时量活过块"的写法在 2024 编译不过。迁移 edition 2024 时跑 `cargo fix --edition` 会按 `if_let_rescope` / `tail_expr_drop_order` 给出改写建议，但 tail 表达式那侧官方明确说"不存在语义等价的自动重写"，需人工核对。edition 的取舍见 [Edition_MSRV](/docs/CS/Rust/Edition_MSRV.md)。

## Four Release Entry Points: Drop::drop / mem::drop / mem::replace / Option::take

初学最容易混的四件事，语义与"能不能手动调"完全不同：

| 名字 | 类别 | 能否手动调用 | 作用 |
| :--- | :--- | :--- | :--- |
| `Drop::drop(&mut self)` | trait 方法 | **永不可手动调用**（E0040） | 只是"释放前钩子"，由编译器在 drop glue 里调 |
| `std::mem::drop<T>(value)` | 普通函数 | 可以，且鼓励 | 把值 move 进形参，函数返回时立即 drop |
| `std::mem::replace(&mut place, new)` | 普通函数 | 可以 | 取走旧值、放入新值，返回旧值（旧值随后由你决定何时 drop） |
| `Option<T>::take(&mut self)` / `mem::take` | 方法 / 函数 | 可以 | 对 `Option`：置 `None` 并返回旧值；`mem::take` 用 `Default::default()` 替换并返回旧值 |

`std::mem::drop` 的实现就是"接收所有权然后什么都不做"，等价于让值立刻离开作用域——上文实测 `[5]` 段证明 drop 发生在 `std::mem::drop(v)` 那一行、早于其后的 `println`：**这就是"提前释放"的惯用法**，不需要写作用域块。

无论是 `x.drop()` 还是 `std::ops::Drop::drop(&mut x)` 都被拒（`error[E0040]: explicit use of destructor method`，编译器实测），因为析构逻辑由所有权系统统一调度，手动调用会破坏"恰好释放一次"的保证。想提前释放用 `std::mem::drop`。

> [!IMPORTANT]
> **`mem::take` 不取代 `mem::replace`**——两者都长期 stable，用途不同：`mem::replace(&mut x, y)` 要你提供具体的新值，`mem::take(&mut x)` 要求 `T: Default`、用默认值占位返回旧值。`T` 没有合适 `Default` 时只能用 `replace` 或 `Option` + `take`。`mem::swap(&mut a, &mut b)` 交换两值、各自随后正常 drop，同样是普通 safe fn。版本（本机 `rustc 1.98.1` 交叉验证 + release notes）：`mem::replace` 自始 stable，**自 1.83.0（2024-11-28）起在 const 上下文可用**；`mem::take` 于 **1.40.0（2019-12-19）** stable，但**在 1.98.1 上仍不是 const fn**（实测 `error[E0658]: cannot call conditionally-const function std::mem::take in constants`，只在 `T:~const Default` 时条件 const）——const 里"替换取旧值"目前用 `mem::replace`。

## Three Restrictions on Implementing Drop

### dropck: Why Drop with Lifetimes May Be Rejected

普通借用检查保证"引用不比其指向的数据活得久"。但 `Drop` 引入例外：一个持有 `&'a u32` 的结构体，在 `drop` 时它的 `Drop::drop` **可能去读那个 `u32`**。若届时 `u32` 已被释放，就是悬垂读。于是编译器对**实现了 `Drop` 且带生命周期参数**的类型启用更严的规则——**dropck（drop check）**：它额外要求所有引用参数在被 drop 的类型生命周期内保持有效。

经典反例（结构体带生命周期又实现 `Drop`，且被 drop 时引用的值已失效）会被拒，诊断形如：

```text
error[E0597]: `y` does not live long enough
   |
   |         x = Foo { data: None, x: &y };
   |                                  ^^ borrowed value does not live long enough
   |     }
   |     - `y` dropped here while still borrowed
   = note: values in a scope are dropped in the opposite order they are defined
```

关键在 `data: Option<Rc<String>>` 这类字段让 `Drop` 有理由"在析构时访问借用数据"，编译器不再信任"析构不碰 `'a`"，只能按最保守的 dropck 报错。`#[may_dangle]` 属性允许你标注"该生命周期参数在析构里不会真被解引用"以放宽 dropck，但**至今不稳定**（实测 `error[E0658]: may_dangle has unstable semantics and may be removed in the future`；`note: see issue #34761`）。`std` 里 `HashMap`、`Vec` 之类能实现 `Drop` 而不触发 dropck，正是因为它们的 impl 用了 `#[may_dangle]`（nightly 特性，稳定代码用不了）。日常写带 `'a` 的 `Drop` 若被 E0597 卡住，多数解法是**别实现 `Drop`**、或把生命周期从带 `Drop` 的类型里拆出去。

### Drop Cannot Be Overloaded: A Type Can Implement It Only Once

`Drop` 是"每类型至多一个析构"，重复实现直接 E0119：

```text
error[E0119]: conflicting implementations of trait `Drop` for type `S`
```

没有函数签名参与决议，也没有"部分类型条件实现"的空间——这与 Copy/Clone 的"一个类型只能有一份 Clone 语义"一致。想表达"不同条件下做不同清理"，只能在唯一的 `drop` 体内用运行时状态判断。

### &mut self Cannot Take Ownership, So It Cannot Re-move Itself

`Drop::drop` 的签名是 `fn drop(&mut self)`，拿到的永远是**可变借用**而非 `self` 所有权。原因很直接：drop glue 正在这块内存上运行，把 `self` move 走会让编译器无法完成剩下的字段释放，等于"释放到一半对象被搬走"。因此想在 `drop` 里消费自身必然被拒：

```rust
struct S;
impl S { fn eat(self){} }
impl Drop for S { fn drop(&mut self){ self.eat(); } }   // 想 move 出 self
```

```text
error[E0507]: cannot move out of `*self` which is behind a mutable reference
```

同理不能在 `Drop::drop` 里 `mem::forget(self)` 或把 `self` 塞进别的容器"复活"——`&mut self` 结构上就挡住了 move-out。要"在析构里转移部分资源"，只能借 `&mut` 的字段逐个操作（常配合 `ManuallyDrop` / `Option::take`）。

## Manual Release Management: ManuallyDrop / MaybeUninit / mem::forget

有时需要**阻止**编译器自动 drop：把所有权交给 `unsafe` 代码或 FFI 对端手动释放。

**`mem::forget` 是 safe 函数**——这是 Rust "泄漏即安全（leaking is memory-safe）"的体现：泄漏一块内存**不构成 UB**，最坏是资源耗尽，所以它不需要 `unsafe`。`forget(v)` 拿走 `v` 的所有权然后什么都不做，跳过 drop。`ManuallyDrop<T>` 是"带 `Drop` 类型的外壳，但不自动 drop 内值"的包装，比 `forget` 更结构化：`size_of` 与 `T` 完全一致（实测 `aarch64-apple-darwin`, `rustc 1.98.1`：`ManuallyDrop<String>` 与 `String` 都是 24 字节），因为它就是 `#[repr(transparent)]` 的 newtype，手动释放用 `ManuallyDrop::into_inner`。`MaybeUninit<T>` 则处理"尚未初始化、可能根本没有值可 drop"的内存，`assume_init` 之前不会 drop 内部（也就没有"drop 未初始化内存"的 UB）：

```rust
use std::mem::{ManuallyDrop, MaybeUninit};
fn main() {
    std::mem::forget(vec![1, 2, 3]);                          // 安全，但堆缓冲泄漏
    let md = ManuallyDrop::new(String::from("abc"));          // 离作用域不 drop 内值
    let s: String = unsafe { ManuallyDrop::into_inner(md) };  // 取回所有权再正常 drop
    let mut x = MaybeUninit::<String>::uninit();
    x.write(String::from("hi"));                              // 现在里面才有有效值
    let _ = unsafe { x.assume_init() };
    drop(s);
}
```

> [!WARNING]
> "泄漏即安全"**不等于**"泄漏无所谓"。对持有非内存资源的类型（文件句柄、socket、锁），`forget` 会永久占住内核资源——`File`/`TcpStream` 的 `Drop` 被跳过，fd 不会关；跨线程的 `Mutex` 被 `forget` 更糟：锁永远解不开。因此 `forget` 只该用在纯内存资源且确要转移给 unsafe 的场景。

三者是手写容器（如 `Vec` 底层）与 FFI 所有权转移的地基；内部可变性与其关系见 [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)。

## panic unwind and Destruction

默认 `panic = "unwind"`：panic 沿栈展开时，**每个栈帧上的局部值都正常跑析构**。这让 `Drop` 成为异常安全（scope guard）的落地方式——即使函数中途 panic，锁会释放、文件会关闭：

```rust
struct G(&'static str);
impl Drop for G { fn drop(&mut self){ println!("  cleanup {}", self.0); } }
fn boom() { let _g = G("ran"); panic!("kaboom"); }
fn main(){
    let _top = G("top");
    let r = std::panic::catch_unwind(|| { let _h = G("handler"); boom(); });
    println!("  caught = {}", r.is_err());
}
```

实测（`--edition 2024 -O`，stderr 上的 panic 文本已略）：

```text
  cleanup ran
  cleanup handler
  caught = true
  cleanup top
```

`boom` 里的 `G("ran")` 与 `main` 里闭包捕获的 `G("handler")` 都因展开而 drop；被 `catch_unwind` 拦下后，`main` 自己的 `G("top")` 也照常释放。这正是 RAII 的价值：**panic 不破坏释放契约**。错误处理策略（`Result` / `?` / `catch_unwind` 的取舍）见 [Error_Handling](/docs/CS/Rust/Error_Handling.md)，`no_std` / `panic = "abort"`（此时展开被禁用、析构**不会**运行）见 [No_Std](/docs/CS/Rust/No_Std.md) 与 [Cargo](/docs/CS/Rust/Cargo.md)。

### extern C Boundary: unwind Triggers abort, but drop glue Runs First

Rust panic 不能跨过 FFI 边界继续展开——那会让非 Rust 栈帧处于 UB。Rust 的做法是在 `extern "C"`（非 `-unwind`）函数里把 panic 转成 `abort`。**自 Rust 1.84.0（2025-01-09）起，在 abort 之前会先执行 `extern "C"` 函数内的 drop glue**，保证栈上的 Rust 资源在进程终止前被清理（此前这一条行为不保证）。实测 `extern "C"` 里 panic：

```rust
struct G(&'static str);
impl Drop for G { fn drop(&mut self){ println!("  drop glue {}", self.0); } }
extern "C" fn c() { let _g = G("in extern C"); panic!("unwind through C"); }
fn main(){ c(); }
```

真实输出（节选，`rustc 1.98.1`）：

```text
thread 'main' panicked at cfn.rs:3:48: unwind through C
  drop glue in extern C
thread 'main' panicked at library/core/src/panicking.rs:225:5:
panic in a function that cannot unwind
...
thread caused non-unwinding panic. aborting.
--- rc=134 ---
```

关键顺序：先打印 `drop glue in extern C`（析构跑了），再 "panic in a function that cannot unwind" 并 `abort`（rc=134 即 SIGABRT）。想让 panic 正常跨越边界被上层（哪怕是非 Rust 但支持展开的调用方）捕获，用 **`extern "C-unwind"`** ABI（自 1.71.0 stable）——实测其中 panic 能被 `catch_unwind` 捕获、`drop glue in C-unwind` 正常打印。`extern` 声明与 ABI 细节见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Drop, Locks, and File Handles: Why Explicit close Is Recommended

把"释放资源"寄托在析构上，在两种类型上会翻车：**有顺序依赖的锁**与**有缓冲区语义的文件/流**。

**死锁**：上一节 `if let` 读锁的例子就是析构时机导致的死锁——局部守卫在 `}` 前一直持锁，若同作用域后续去拿写锁就自锁。锁的正确用法是把 `MutexGuard` 的生命周期缩到最小作用域，而不是指望它在"看起来该结束的地方"被 drop。多个守卫共存时，**释放顺序 = 逆声明序 / 字段声明序**，稍一疏忽就与获取顺序相反造成死锁。

**忘记 flush**：`File` / `BufWriter` 的 `Drop` 会尝试关句柄，但对 `BufWriter` 而言 drop 时的 flush **错误会被吞掉**（析构返回不了 `Result`）——你可能写完就以为成功，实际数据没落盘。标准库自己的文档就建议 `BufWriter` 显式 `flush()`。

```rust
use std::io::{BufWriter, Write};
fn write_it() -> std::io::Result<()> {
    let file = std::fs::File::create("out.txt")?;
    let mut w = BufWriter::new(file);
    w.write_all(b"data")?;
    w.flush()?;      // 显式：错误此刻可见
    w.into_inner()?; // 再取回 File，其 close 错误也能被 Result 捕获
    Ok(())
}
```

> [!TIP]
> 因此 Rust 生态的通行建议与 C++ 的 RAII-only 风格相反：**对可能失败的资源释放（close/flush/shutdown），提供显式方法返回 `Result`，`Drop` 只做"尽力而为"的兜底**。`Drop` 里不能返回错误、不该 panic（panic 时再 panic 会 abort）。把 `close()` 做成幂等、让 `Drop` 也调用它一次作为最后防线，是两全的做法。锁的选型与死锁分析见 [Concurrency](/docs/CS/Rust/Concurrency.md)。

## `Box::leak` and Giving Ownership to FFI

`Box::leak(b)` 把 `Box<T>` 变成 `&'static mut T`，内存被有意"泄漏"出去——交给需要长期持有的场景（全局单例、给 C 层一个不透明指针）。传统上会把这块内存当 `*mut` 传出去，将来用 `Box::from_raw` 收回。但**自 Rust 1.99.0（2026-10-01）起，官方文档反转了这一推荐**：`Box::leak` 后将来再 `Box::from_raw` deallocate 的模式被明确劝退，尤其因为自定义分配器（`allocator_api`）即将稳定——leak 出来的内存在别的分配器下用 `from_raw` 收回会踩坑。官方给出的替代是 **`Box::into_raw` / `Box::into_non_null`**（`into_non_null` 随 1.99.0 一起稳定，1.98.1 上仍 unstable，实测报 `use of unstable library feature box_vec_non_null`）。

也就是说：把 `Box` 的所有权交给 FFI 对端、且**预期它归还**时，用 `into_raw`/`into_non_null`（配合 `from_raw`/`from_non_null`）成对使用；只有真"一次性泄漏、永不归还"才用 `leak`。这条与本篇的释放契约直接相关：`into_raw` 把"何时 drop 由你手动决定"合法化，而 `leak` 是把 drop 永久取消。FFI 所有权转移的完整规约见 [Unsafe_FFI](/docs/CS/Rust/Unsafe_FFI.md)。

## Cross-language comparison

| 维度 | Rust `Drop` | C++ 析构 | Go `defer` | Java |
| :--- | :--- | :--- | :--- | :--- |
| 释放时机决定方 | 编译器（所有权终点） | 程序员（对象作用域）+ GC 不管栈对象 | 程序员显式注册 | GC / try-with-resources |
| 无自定义析构仍释放内存？ | 是（drop glue 递归字段） | 否（栈对象走作用域，堆 `new` 会泄漏） | 内存靠 GC | 靠 GC |
| 同作用域内顺序 | 局部逆声明序 | 局部逆声明序 | LIFO（后进先出） | 无关 |
| 成员/字段顺序 | 声明顺序（`struct` 字段先 drop） | 逆成员声明序（析构体先跑，成员后销毁） | 无成员析构概念 | 无确定性 |
| 虚析构 | 不需要（非虚，`Drop` 静态派发） | **基类析构须 `virtual`**，否则 UB | — | `finalize`/`Cleaner` 非虚 |
| 能否重载 / 多份 | 否（E0119） | 否（每类唯一析构） | 每次可 defer 多条 | — |
| `drop`/析构里抛异常 | 展开时析构正常跑；析构内再 panic → abort | 析构隐式 `noexcept`（C++11 起）；抛出即 `terminate` | `defer` 中 panic 可被 recover | `close()` 抛 `IOException` 需处理 |
| 手动提前释放 | `mem::drop`（普通 fn） | 无安全等价（栈对象不能提前销毁） | `defer` 只能在函数末，除非包一层 | 无（GC 决定） |
| `std::move` / take 语义 | move 后原绑定失效，仅新所有者 drop | `std::move` 不移动、仅转换；源处于"有效未指定"态 | 无关 | 无关 |
| 泄漏是否安全 | 安全（`mem::forget`） | 堆对象泄漏即 UB 之外的资源损失 | GC 兜底内存，但 `defer` 未跑会漏非内存资源 | GC 兜底内存 |
| finalizer / Cleaner | 无（无 GC 兜底） | 无 | 无（`runtime.SetFinalizer` 仅内存对象） | `finalize` **已废弃（Java 9）**，改用 `java.lang.ref.Cleaner` |

几点值得单独钉牢：

- **C++ 成员销毁是逆声明序，Rust 结构体字段是正声明序**（见实测 [3]）——从 C++ 迁来时最反直觉的一条。且 **C++ rule of 0/3/5** 在 Rust 里塌缩为 rule of 0：所有权 + move 消灭了"浅拷贝 double-free"，`Clone` 显式而非隐式，`Drop` 只在追加清理时写。对照 [Move](/docs/CS/C++/Move.md) 与 [Init](/docs/CS/C++/Init.md)。
- **Go `defer` 的参数在注册时求值**、函数体在返回时才执行，栈是 LIFO——与 Rust "值在所有者作用域末 drop"是不同心智模型（详见 [Defer](/docs/CS/Go/Defer.md)）。**Java 的 `try-with-resources`** 最接近 Rust `Drop`（确定性 close + 异常抑制），但靠程序员记得用该语法；`Cleaner` 取代了被废弃的 `finalize`（Java 9），因为 finalizer 不保证运行、可能与对象复活打架——这正是 Rust 从不提供"GC 兜底析构"的原因。

## Links

- [Ownership](/docs/CS/Rust/Ownership.md)
- [Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Error_Handling](/docs/CS/Rust/Error_Handling.md)
- [初始化（C++ RAII 的构造面）](/docs/CS/C++/Init.md)
- [defer（Go 的确定性清理）](/docs/CS/Go/Defer.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [Destructors — Rust Reference](https://doc.rust-lang.org/reference/destructors.html)
- [Drop trait — std](https://doc.rust-lang.org/std/ops/trait.Drop.html)
- [std::mem::drop — std](https://doc.rust-lang.org/std/mem/fn.drop.html)
- [ManuallyDrop — std](https://doc.rust-lang.org/std/mem/struct.ManuallyDrop.html)
- [MaybeUninit — std](https://doc.rust-lang.org/std/mem/union.MaybeUninit.html)
- [Dropck — the Rustonomicon](https://doc.rust-lang.org/nomicon/dropck.html)
- [if let temporary scope — Edition Guide 2024](https://doc.rust-lang.org/edition-guide/rust-2024/temporary-if-let-scope.html)
- [Tail expression temporary scope — Edition Guide 2024](https://doc.rust-lang.org/edition-guide/rust-2024/temporary-tail-expr-scope.html)
- [Rust 1.99.0 release announcement](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/)
