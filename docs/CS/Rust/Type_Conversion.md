## Introduction

Rust 没有隐式转换——`1u8 + 1` 不编译，`&String` 不自动变成 `&str`（等等，它其实会，见 deref coercion）。类型之间的一切移动都必须显式，但"显式"的选项有十几个：`as`、`From` / `Into`、`TryFrom` / `TryInto`、`AsRef` / `AsMut`、`Borrow` / `ToOwned`、`Deref`、`Cow`、`transmute`。选错不只是风格问题——`as` 静默截断、`transmute` 绕过一切检查、`Deref` 用错会让智能指针露出内部类型。

本篇按"代价从低到高"给这些转换排一张序，并回答两个高频问题：**`From`/`Into` 与 `AsRef` 到底怎么分工**，以及 **deref coercion 为什么是特例而不是常规**。错误类型的设计见 [Error_Handling](/docs/CS/Rust/Error_Handling.md)，所有权与移动见 [Ownership](/docs/CS/Rust/Ownership.md)。

## The Conversion Ladder

按"编译器替你保证了多少"从高到低排：

| 层 | 机制 | 保证 | 代价 |
| :--- | :--- | :--- | :--- |
| 1 | 子类型 / 生命周期 | 编译期完全证明 | 无 |
| 2 | `Deref` coercion | 编译期证明，隐式发生 | 一次解引用 |
| 3 | `From` / `Into` | 编译期选择实现，**显式调用** | 由实现决定 |
| 4 | `AsRef` / `AsMut` / `Borrow` | trait 显式调用，一对多可能 | 由实现决定 |
| 5 | `TryFrom` / `TryInto` | 同上 + 可能失败 | 检查 + `Result` |
| 6 | `as` | **几乎不检查** | 静默截断 / 位重解释 |
| 7 | `transmute` | 只查尺寸 | 零，但全是你的责任 |
| 8 | `ptr::read` / `write` + `unsafe` | 无 | 无，UB 风险 |

经验法则：**能从高层解决就别下底层**。`as` 与 `transmute` 是逃生门，不是工具箱。

## From and Into: The Infallible Pair

```rust
impl From<u32> for u64 { ... }   // 标准库已实现：u32 -> u64 不会失败
let x: u64 = 5u32.into();        // Into 由 From 自动获得（ blanket impl ）
let y = u64::from(5u32);         // 显式方向，错误信息更清晰
```

规则：**实现 `From` 就免费得到 `Into`**（标准库的 `impl<T, U> Into<U> for T where U: From<T>`）。所以"该实现哪个"的答案是 `From`——它是两个 trait 里唯一要写实现的，`Into` 只是个镜像。

分工约定（社区事实标准）：`From` 用于**不失败且可能不是零成本**的转换（`String -> Vec<u8>` 是移动、`&str -> String` 是分配）；`Into` 几乎从不显式实现，只作为泛型 bound 出现：`fn log(s: impl Into<String>)` 让调用方既能传 `&str` 又能传 `String`。

一个 blank impl 的后果：因为 `From<T> for T`（identity）存在，`impl Into<Foo>` 的 API 传 `Foo` 自身永远合法——这正是 `impl Into<String>` 好用的原因，也是它有时让类型推断犯难的原因（传 `"x"` 时要先 `&str -> String` 那步）。

## TryFrom and TryInto: The Fallible Pair

```rust
let big: u64 = 300;
let small = u8::try_from(big);       // Err(TryFromIntError)
let ok = u8::try_from(200u64)?;      // Ok(200)
```

与 `From`/`Into` 完全同构：实现 `TryFrom` 得 `TryInto`，泛型 bound 写 `TryInto`，显式调用写 `try_from`。错误类型必须实现 `Display` + `Error`，`?` 才能把它转成你的错误类型（[Error_Handling](/docs/CS/Rust/Error_Handling.md) 的 `From` 转换链）。

常见陷阱：**有符号 ↔ 无符号的 `try_from` 是值域检查，不是位重解释**——`i32::try_from(-1i32)` 到 `u32` 报错，而 `(-1i32) as u32` 静默变成 `4294967295`。要位模式相同就用 `as`（并注释为什么安全）。

## AsRef and AsMut: The Borrowing Pair

```rust
fn count(s: impl AsRef<str>) -> usize { s.as_ref().len() }
count("hi"); count(String::from("hi")); count(&Cow::from("hi"));
```

`AsRef<T>` 表达"我能被看成 `&T`"，特点是：

1. **一对多**：`String` 同时 `AsRef<str>`、`AsRef<[u8]>`、`AsRef<OsStr>`、`AsRef<Path>`。所以 `impl AsRef<str>` 的 API 传 `String` / `&str` / `Cow<str>` 都行，但**不**传 `&String` 之外的奇怪东西——推断只认这一个 bound。
2. **与 `Borrow` 的区别**：`Borrow<T>` 要求 `T` 上的 `Hash` / `Eq` 与 `&T` 一致（`BTreeMap::get` 用 `Q: Ord` 就是这机制），它是"等价借用"；`AsRef` 只是"能看成一个引用"，不承诺等价。查表用 `Borrow`，泛型收参用 `AsRef`。
3. **不要为每个类型都实现**：`AsRef` 的泛滥会让 `impl AsRef<str>` 的调用点推断困难。只实现"这个类型真的就是那个东西的视图"。

`AsMut` 是 `&mut` 版，但实际使用少得多——可变视图通常意味着所有权问题该用 `&mut T` 直接表达。

## Borrow and ToOwned: The Clone Spectrum

```rust
fn lookup<Q>(map: &HashMap<K, V>, key: &Q) -> Option<&V>
where K: Borrow<Q> + Eq, Q: Hash + ?Sized
```

`Borrow` 的契约比名字强：`borrow()` 返回的引用必须与原值在 `Hash`、`Eq` 上表现一致。这是 `HashMap::get(&str)` 能在 `HashMap<String, V>` 上工作的全部依据——`String: Borrow<str>`，且两者的哈希与相等逐字节一致。

`ToOwned` 是 `Clone` 的 ?Sized 版：`Clone` 要求 `Sized`，而 `ToOwned` 能从 `&str`（unsized）造出 `String`（owned）。`Cow<'a, B>` 则是两者的合体：`Cow::Borrowed(&B)` 或 `Cow::Owned(<B as ToOwned>::Owned)`，首次要改时才分配（[Collections](/docs/CS/Rust/Collections.md) 的 `Cow<str>` 一节有实测：`from_utf8_lossy` 输入合法时不分配）。

**`Cow` 是接口契约不是性能技巧**：签名 `-> Cow<'_, str>` 直接告诉调用方"多数路径不分配"。把它当返回值比当参数更常见。

## Deref Coercion: The One Implicit Conversion

Deref coercion 是 Rust 唯一的隐式引用转换：编译器在方法调用或函数参数处自动插入 `*` 链。`&String` 传给 `fn f(s: &str)` 能编，是因为 `String: Deref<Target = str>`。

三条纪律：

1. **它只发生在引用到引用**（`&String -> &str`、`&Vec<T> -> &[T]`），不发生在值上（`String` 不会变成 `str`）。
2. **它是方法解析的候选而非万能药**：`v.len()` 在 `Vec<T>` 与 `[T]` 都有 `len` 时，选的是 `Vec` 的——deref 是"本类型没有才下沉"，不是"优先用内层的"。
3. **智能指针滥用它的代价**：给新类型实现 `Deref` 到内部类型，会让新类型"继承"内部类型的全部方法，封装漏光。标准库自己只对 `Box` / `String` / `Vec` / `Rc` / `Arc` 这类真智能指针实现 `Deref`；自定义包装类型应该显式 `impl` 需要的几个方法，而不是 `Deref` 一放了之（[Smart_Pointers](/docs/CS/Rust/Smart_Pointers.md)）。

## as: The Lossy Cast

`as` 覆盖的场景比想象多，但**几乎不检查**：

| 转换 | 行为 |
| :--- | :--- |
| 整数 → 更小整数 | **截断**（`300u32 as u8 == 44`），无 warning |
| 整数 → 更大整数 | 符号扩展 / 零扩展（按源类型有符号性） |
| 浮点 → 整数 | 饱和到 0 / 向零取整后截断（Rust 的 `as` 是 saturating，与 C 的 UB 不同） |
| `bool` / `char` → 整数 | `true as u8 == 1`；`char as u32` 是码点 |
| 指针 → 整数 | 地址（**丢 provenance**，见 [Unsafe](/docs/CS/Rust/Unsafe.md)） |
| 引用 → 裸指针 | 保留 provenance（比 `as usize` 安全） |
| `*mut T` → `*mut U` | 无检查，对齐/尺寸责任在你 |

`as` 唯一比 `transmute` 强的地方：**尺寸不同的截断是确定行为**，且浮点饱和是确定行为。凡"可能失败"的（`u64 -> u32`）就该走 `try_from`；凡"位模式不变"的（`f32 -> u32`）就该走 `to_bits`（比 `transmute` 语义清晰）；凡"不变量要人担保"的才考虑 `as` + 注释。

## transmute: The Last Resort

`transmute` 的唯一合法用途是"两个类型位模式相同、且你论证了目标类型的不变式成立"。标准库的替代品覆盖了绝大多数场景，先用它们：

| 需求 | 用 | 而不是 |
| :--- | :--- | :--- |
| 浮点位模式 | `f32::to_bits` / `from_bits` | `transmute` |
| 字节 ↔ 整数 | `to_ne_bytes` / `from_ne_bytes`（还有 `to_le` / `to_be`） | `transmute` |
| 延长/缩短生命周期 | `transmute`（**确实没有安全替代**） | 重新设计 |
| 未初始化内存 | `MaybeUninit`（[Unsafe](/docs/CS/Rust/Unsafe.md)） | `transmute` + zeroed |

尺寸检查在编译期（`transmute` 不同尺寸直接 E0512），**语义检查完全没有**：`transmute` 出一个 `bool` 而位模式是 `2`，就是立即 UB（[Unsafe](/docs/CS/Rust/Unsafe.md) 的 UB 清单）。

## Choosing the Right Mechanism

| 我要 | 用 |
| :--- | :--- |
| `u32` 变 `u64`，不失败 | `From` / `Into` |
| `u64` 变 `u32`，可能失败 | `TryFrom` |
| API 同时收 `&str` 和 `String` | `impl AsRef<str>` 或 `impl Into<String>` |
| `HashMap<String, V>` 上用 `&str` 查 | `Borrow`（标准库已实现，你不用写） |
| 返回值多数情况不分配 | `Cow<'_, str>` |
| `&String` 传给要 `&str` 的函数 | Deref coercion（自动） |
| 截断是故意的 | `as` + 注释 |
| 位模式转换 | `to_bits` / `from_bytes` 家族 |
| 延长生命周期 | `transmute` + 最强注释 |

## Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | 用 `as` 做可能失败的转换 | 静默截断 | `try_from` |
| 2 | 给新类型 `Deref` 到内部 | 封装全漏，方法意外出现 | 显式 impl 需要的方法 |
| 3 | 实现 `Into` 而不是 `From` | 白写一半， blanket impl 冲突 | 只实现 `From` |
| 4 | `Borrow` 与 `AsRef` 混用 | `HashMap::get` 行为不符预期 | 查表用 `Borrow`，收参用 `AsRef` |
| 5 | `transmute` 浮点转整数 | 可读性差、可能踩无效值 | `to_bits` / `from_bits` |
| 6 | `impl Into<String>` 推断困难 | `"x"` 编不过或类型不明 | 调用点显式 `.to_string()` / `.into()` |
| 7 | 指针 `as usize` 再转回 | 丢 provenance（[Unsafe](/docs/CS/Rust/Unsafe.md)） | `with_exposed_provenance` |
| 8 | 忘了 `char as u32` 是码点 | 与 UTF-8 字节混淆 | 要字节用 `encode_utf8` |

## Links

- [Ownership](/docs/CS/Rust/Ownership.md)
- [Error_Handling](/docs/CS/Rust/Error_Handling.md)
- [智能指针](/docs/CS/Rust/Smart_Pointers.md)
- [集合类型](/docs/CS/Rust/Collections.md)
- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [Trait_System](/docs/CS/Rust/Trait_System.md)

## References

1. [`std::convert` module docs](https://doc.rust-lang.org/std/convert/index.html)
2. [`std::borrow` module docs](https://doc.rust-lang.org/std/borrow/index.html)
3. [`std::ops::Deref`](https://doc.rust-lang.org/std/ops/trait.Deref.html)
4. [`std::mem::transmute`](https://doc.rust-lang.org/std/mem/fn.transmute.html)
5. [The Rustonomicon — Transmutes](https://doc.rust-lang.org/nomicon/transmutes.html)
6. [Type conversions in The Rust Reference](https://doc.rust-lang.org/reference/expressions/operator-expr.html#type-cast-expressions)
