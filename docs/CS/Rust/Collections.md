## Introduction

`std::collections` 与 `std::iter` 是 Rust「零成本抽象」口号唯一能被机器码检验的地方：容器决定**内存布局与分配次数**，迭代器决定**循环能否被向量化**。两者又都被借用检查器重塑了一遍形态——因为「谁能改这块内存」在编译期就有答案，所以 Rust 不需要 C++ 那套迭代器失效规则，也不需要 Go map 的运行时写屏障。

本篇讲的是**选型与实现事实**，不是 API 手册：每个容器的复杂度保证是什么、文档**拒绝**保证什么（`Vec` 的增长因子是最著名的一条）、默认哈希函数为什么是 SipHash-1-3 而不是更快的整数哈希、迭代器链为什么和手写索引循环生成同一份汇编。智能指针与内部可变性见 [Smart Pointers](/docs/CS/Rust/Smart_Pointers.md)，`Send`/`Sync` 与并发容器见 [Concurrency](/docs/CS/Rust/Concurrency.md)，泛型单态化机制见 [Generics](/docs/CS/Rust/Generics.md)。

> [!NOTE]
> 本篇所有 `size_of` / 容量序列 / 计时数字均为**本机实测**：`rustc 1.98.1 (48a229cea 2026-09-01)`，目标三元组 `aarch64-apple-darwin`，`-O`（等同 `opt-level = 3`、`codegen-units = 16` 的手动近似）。凡涉及「规范保证」与「实现观察」的边界，会逐条标明。

## Container Overview

| 容器 | 布局（本机 `size_of`） | 复杂度保证 | 真实适用面 |
| :-- | :-- | :-- | :-- |
| `Vec<T>` | 24 字节（ptr/len/cap） | 随机访问 O(1)；`push` **摊还 O(1)**；任意位置 `insert`/`remove` O(n−index) | 默认选择。需要「一段连续 T 且会长大」时只有它能做 |
| `[T]` | 视图 16 字节（ptr/len） | 全部操作与 `Vec` 同阶，但**不能增删** | 函数参数与返回值的正确类型：`&[T]` / `&mut [T]`，同时接受数组和 `Vec` |
| `String` | 24 字节 | 同 `Vec<u8>`，但每次写入都保持 UTF-8 有效 | 拥有所有权的可变文本 |
| `str` | 视图 16 字节 | 只读；`&'static str` 来自字面量，零分配 | 常量、错误码、协议字段名；接口里的只读文本参数 |
| `Box<[T]>` | 16 字节 | 定长、无 capacity 字段 | 构建完成后不再增删的数组：省 8 字节头部与一次「容量>长度」的心智负担 |
| `HashMap<K,V>` | 48 字节（默认 `RandomState`）/ 32 字节（自带无状态 hasher） | 平均 O(1) 查找与插入，**最坏 O(n)** | 无序键值；默认 hasher 自带 HashDoS 防护 |
| `BTreeMap<K,V>` | 24 字节 | 最坏 O(log n)；`range` 为 O(log n + k) | 需要有序遍历、范围查询、**可复现的迭代顺序** |
| `HashSet<T>` | 48 字节 | 同 `HashMap` | 去重、集合运算（`union`/`difference` 直接是迭代器） |
| `VecDeque<T>` | 32 字节 | 两端 `push`/`pop` 摊还 O(1)；随机访问 O(1)；中间插入 O(n) | 队列、滑动窗口、需要 `make_contiguous` 再切片的 BFS |
| `BinaryHeap<T>` | 24 字节 | `push`/`pop` O(log n)，`peek` O(1)；**大顶堆** | Top-K、优先队列；要小顶堆得 `Reverse` 包一层 |
| `LinkedList<T>` | 24 字节（head/tail/len） | 两端与游标处插入 O(1)，**查找 O(n) 且无随机访问** | 近乎没有。std 文档自己就推荐用 `Vec`；唯一理由是要在稳定位置上 O(1) splice |
| `Cow<'a, T>` | `Cow<str>` 24 字节 | 读 O(1)；首次 `to_mut` 付一次 clone | 「多数时候不需要拥有，少数时候需要」的返回值 |

`OsString`（24 字节）与 `PathBuf`（24 字节）是「平台原生字符串」，**不保证 UTF-8**：Windows 上是 WTF-8 风格的宽字符序列，Unix 上是未校验的字节。这是 `Path` 能表达非法 UTF-8 文件名的原因，也是 `to_string_lossy()` 存在的理由。

## Vec Capacity Contract

### The Documented Promise and the Documented Refusal

std 文档在 `Vec` 的 "Capacity and reallocation" 一节里做了一件很少见的事：**明文拒绝规定增长策略**——"Vec does not guarantee any particular growth strategy when reallocating when full, nor when `reserve` is called"，紧接着给出唯一被保证的性质："Whatever strategy is used will of course guarantee **O(1) amortized `push`**"。

于是「`Vec` 容量翻倍」「`String` 按 1.5 倍增长」「小 Vec 有 64 字节下限」这类说法都**不是规范**。可靠的只有四条：

- `capacity()` 报告的值**完全准确**，可以据此判断是否会再分配；
- `vec![e1..en]`、`vec![x; n]`、`Vec::with_capacity(n)` 保证向分配器申请**恰好容纳 n 个元素**的空间（`Vec::with_capacity` 的这一条在 1.87.0 写死为文档保证）；
- `vec![x; n]` 对零值走分配器的清零页，文档原话是「通常比显式写零更高效」；
- 批量插入方法**可能在不必要的情况下重新分配**——文档明写 "Bulk insertion methods may reallocate, even when not necessary"。

> [!WARNING]
> 1.76.0 的 Compatibility Notes 是最后一条的最好警告："`Vec`'s allocation behavior was changed when collecting some iterators. **Allocation behavior is currently not specified**, nevertheless changes can be surprising." 也就是说，`collect` 之后的 `capacity()` 在版本之间是可以变的，任何依赖它的代码都属于「碰巧能跑」。

### Observed Growth on This Machine

```rust
fn growth_trace() {
    let mut v: Vec<i32> = Vec::new();
    let mut seen = 0usize;
    let mut log = Vec::new();
    for i in 0..100_000 {
        v.push(i);
        if v.capacity() != seen {
            seen = v.capacity();
            log.push(seen);
        }
    }
    println!("{:?} reallocs={}", &log[..14], log.len());
}
```

本机实测（`rustc 1.98.1`，`aarch64-apple-darwin`，`-O`）：

```text
Vec<i32>  : [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]  100k 次 push 共 16 次重分配
Vec<u8>   : [8, 16, 32, 64, 128, 256, 512]
Vec<i128> : [4, 8, 16, 32, 64, 128, 256, 512]
```

**这是观察，不是保证。** 形态上确实是 2 倍增长，但**起始容量随元素大小而变**：本机 `Vec<u8>` 从 8 起，`Vec<i32>` / `Vec<i128>` / 24 字节结构体都从 4 起（起始值由 `RawVec` 的最小分配块与元素大小共同决定，属实现细节，未逐个核实）。同一份代码换到别的 `rustc` 版本或别的元素布局都可能变——正因为文档不承诺，实现才敢改。

对照实验：`reserve`/`with_capacity` 之后 push **不会**再抬高容量。

```rust
fn exact_reserve() {
    let mut v: Vec<i32> = Vec::new();
    v.reserve(1000);
    v.push(1);
    assert_eq!(v.capacity(), 1000);
}
```

### Allocation Behavior of collect and extend

`collect` 会先看 `size_hint()` 的**上界**：精确长度的迭代器一次到位，猜不准的迭代器退化成 push 式增长。

```rust
fn collect_capacity() {
    let a: Vec<i32> = (0..1000).collect();
    let b: Vec<i32> = (0..1000).filter(|_| true).collect();
    let c: Vec<i32> = (0..1000).take(999).collect();
    let mut d: Vec<i32> = Vec::new();
    d.extend(0..1000);
    let mut e: Vec<i32> = Vec::with_capacity(4);
    e.extend(0..8);
    println!("{} {} {} {} {}", a.capacity(), b.capacity(), c.capacity(), d.capacity(), e.capacity());
}
```

本机输出 `1000 1024 999 1000 8`：`ExactSizeIterator` 恰好 1000，`Filter`（`size_hint` 下界 0、上界 1000）走到 1024，`take` 精确到 999，从 `with_capacity(4)` 出发批量塞 8 个元素得到 8（这次没「不必要地多分」，但文档允许它多分）。

结论只有一条工程性的：**知道规模就 `Vec::with_capacity(n)`**，把分配次数从「取决于实现」变成「取决于你」。1.99.0 另外补了一条**分配器层面**的合同：允许某些分配原地增长，但明确不允许原地缩小（"some allocations are allowed to grow in-place (but none are allowed to shrink)"）。它约束的是分配器实现而非容器接口，对使用者的含义是——重分配后指针是否变化更不可预判，而 `Vec` 早已规定「重分配会使全部引用失效」，所以这条并不放松任何借用规则。

## Slices and Adaptation

`[T]` 才是这套设施的中心：`Vec<T>` 通过 `Deref<Target = [T]>` 白送全部切片方法，所以「切片适配器」就是「`Vec` 的适配器」。`Deref`/`Index` 的机制细节见 [Trait System](/docs/CS/Rust/Trait_System.md)。

```rust
fn slice_adapters() {
    let v = vec![1, 2, 3, 4, 5, 6];
    let _w = v.windows(3); // [1,2,3] [2,3,4] [3,4,5] [4,5,6]  重叠
    let _c = v.chunks(4); // [1,2,3,4] [5,6]                  最后一块可能短
    let _e = v.chunks_exact(4); // 只有 [1,2,3,4]
    let rem = v.chunks_exact(4).remainder(); // [5, 6]         零成本拿到落单部分
    let _s = "a,,bb,ccc".split(','); // "a" "" "bb" "ccc"      连续分隔符产生空串
    let _z = v.rchunks_exact(2);
}
```

三个容易写错的地方，都是本机跑出来的行为：

- `windows(0)` panic `"window size must be non-zero"`，`chunks(0)` panic `"chunk size must be non-zero"`——想表达「整个切片」应该用 `chunks_exact` 之外的方式或直接判断空。
- `chunks_exact` 的价值在于 `IntoIterator` 的 `Item = &[T]` **长度编译期已知为 k**，因此循环体里的 `chunk[0]`/`chunk[1]` 边界检查能被消掉；用 `chunks` 就享受不到。剩下的尾巴用 `remainder()` 单独处理。
- `split` 保留空片段，`split_terminator` 只吃掉**尾部**那一个，`splitn(k, _)` 的最后一段不再切分（`"a,b,c"` → `["a", "b,c"]`）。

### sort versus sort_unstable

| | `sort` | `sort_unstable` |
| :-- | :-- | :-- |
| 稳定性 | 保证（等值元素维持原序） | 不保证 |
| 复杂度 | O(n log n) 最坏 | O(n log n) 最坏 |
| 额外内存 | **会分配**：短片段不分配，中等片段分配 `len`，更大的封顶在 `len / 2` | 不分配（原地） |
| 当前算法 | 文档明写基于 **driftsort**（Orson Peters / Lukas Bergdoll），融合快排的平均表现与归并的最坏表现和游程检测 | 基于 **ipnsort**，快排平均 + 堆排最坏 |

`sort` 需要额外分配正是「稳定」的代价——归并式做法要临时空间，而 Rust 选择用 `alloc` 换确定性，而不是像 C++ 那样把 `stable_sort` 的分配失败留给运行时异常。要按键稳定排序又想省内存，就自己造索引：`sort_unstable_by_key` 配 `(key, index)` 元组，或先 `sort_unstable_by` 比较键再在键相等时比较原始下标。

> [!NOTE]
> 2024 年前后的资料会说 `sort` 是 Timsort、`sort_unstable` 是 pattern-defeating quicksort（pdqsort）。当前 stable（1.99.0 文档）已换成 driftsort / ipnsort，且首次给出了**辅助内存分配量与输入长度的关系**。这类「算法名字」属于文档级实现说明，会随版本变，别当规范记。

## The String Family

### A Selection Tree

```text
只读文本，长度已知且永久存在      → &'static str（字面量，零分配）
只读文本， borrowed from 别人     → &str（参数首选，别写 &String）
需要拼接 / 拥有 / 反复 push       → String
从字节流来，不确定是否 UTF-8      → Vec<u8>，需要时 from_utf8 / from_utf8_lossy
路径                                → &Path / PathBuf（不要求 UTF-8）
平台原生 argv / 环境变量          → &OsStr / OsString
0 次或 1 次分配皆可，取决于输入   → Cow<'a, str>
```

`Cow<str>` 不是「性能小技巧」，而是**接口契约**：`String::from_utf8_lossy(&[u8]) -> Cow<str>` 的签名直接说明「输入本来就是合法 UTF-8 时不分配」。本机验证：

```rust
fn cow_behavior() {
    let ok = String::from_utf8_lossy(b"hello");
    assert!(matches!(ok, std::borrow::Cow::Borrowed(_)));
    let bad = String::from_utf8_lossy(&[0x61, 0xff, 0x62]);
    assert!(matches!(bad, std::borrow::Cow::Owned(_)));
    let mut c = std::borrow::Cow::Borrowed("hi");
    c.to_mut().push('!'); // 这一刻才 clone，之后是 Owned
    assert_eq!(c, "hi!");
}
```

`String::from_utf8_lossy_owned(vec) -> String`（**Rust 1.99.0**）补上了最后一种情形：**拥有**输入的字节缓冲时，做有损转换不再需要「先拷成 `Cow`、再判断是否要拥有」。本机 `rustc 1.98.1` 上它仍被 feature gate 挡住：

```text
error[E0658]: use of unstable library feature `string_from_utf8_lossy_owned`
```

### UTF-8 Invariant and Why Byte Indices Panic

`String`/`str` 的不变式是「字节序列必须是合法 UTF-8」，这个不变式由类型系统持有，所以**任何 API 都不需要再检查一遍编码**，代价是索引语义必须让步。

`"αβγ"` 是 6 字节 3 字符。对它做 `s[1]` 在本机得到的是**编译错误**，不是运行时 panic：

```text
error[E0277]: the type `str` cannot be indexed by `{integer}`
   = note: you can use `.chars().nth()` or `.bytes().nth()`
```

因为 `Index<usize>` 压根没为 `str` 实现——「第 i 个字符」和「第 i 个字节」二选一，选哪个都错，干脆不给。真正会 panic 的是**字节范围**（它编译得过）：

```rust
fn boundary_panic() {
    let s = String::from("αβγ");
    let _ = &s[0..1];
}
```

```text
end byte index 1 is not a char boundary; it is inside 'α' (bytes 0..2 of string)
```

正确的四条出口：`chars()` 拿 `char`、`char_indices()` 同时拿字节偏移与字符（`[(0, 'α'), (2, 'β'), (4, 'γ')]`）、`get(0..1)` 返回 `None` 而不是 panic（用于不可信输入）、`floor_char_boundary` 把任意下标吸附到最近的合法边界（本机 `rustc 1.98.1` 实测已在 stable 上可用，具体稳定版本未核实——旧资料里它是 nightly 方法）。

## HashMap Implementation Facts

### hashbrown and RandomState

`std::collections::HashMap` 自 **1.36.0（2019-07-04）** 起，实现整体换成 `hashbrown::HashMap`——也就是 Abseil **SwissTable** 的 Rust 移植：开放寻址 + 一组 SIMD 比较的控制字节（control bytes），查找时一次向量比较锁定候选槽位，元素本体连续存放。这与「每元素一个节点 + 桶链表」的教科书哈希表是两种内存形态，缓存行为差异远大于算法复杂度差异。

默认 hasher 是 `hash_map::RandomState`，算法是 **SipHash-1-3**（**1.11.0（2016-08-18）** 从 SipHash-2-4 换过来）。种子在进程启动时从操作系统的高质量随机源取，非阻塞。

> [!WARNING]
> 两个 SipHash-1-3 事实极易混淆：1.11.0 换的是 **`std::collections::HashMap` 的默认 hasher**；1.70.0 release notes 里 "Use SipHash-1-3 instead of SipHash2-4 for StableHasher" 说的是 **rustc 自己的内部哈希器**，与 `HashMap` 无关。另外 1.70.0 与 HashMap 的 hasher 变更没有任何关系，别把日期记串。

本机 `size_of` 顺带暴露了 `RandomState` 的存在：`HashMap<i32, i32>` 是 **48 字节**，而换成一个无种子的自定义 `BuildHasher` 后是 **32 字节**——那 16 字节正是两个 SipHash 密钥。

### Integer Keys and Swapping Hashers

整数键在默认 hasher 下慢，原因不是「SipHash 算得慢」这一句废话，而是：SipHash 的固定开销（初始化两个密钥、两轮压缩、处理长度域）在**键只有 4/8 字节**时摊销不掉，而它换来的抗碰撞强度对 `u32` 键这种「对手不能自由控制全部位」的场景常常过剩。换 `fxhash` / `ahash` / `rustc-hash` 能拿到 2~4 倍，**代价是 HashDoS 防护消失**：一旦键来自不可信输入，攻击者可以构造同桶键把 O(1) 打成 O(n)。

本机测法：`HashMap<i64, i64>`，键为 `i * 2654435761 % n` 打散后的整数，`with_capacity(n)` 预热分配，7 轮取最小值；对照组是手写 FxHash（`rotate_left(5) ^ k` 后乘常数）与 `BTreeMap`。

| n = 1_000_000 | 默认 SipHash-1-3 | FxHash 手写 | `BTreeMap` |
| :-- | :-- | :-- | :-- |
| 1M 次 insert | 0.0147 s | 0.0091 s（**1.6x**） | 0.1074 s |
| 1M 次 get（全命中） | 0.0227 s | 0.0065 s（**3.5x**） | 0.0996 s |
| n = 200_000 时 | 0.0025 / 0.0016 s | 0.0011 / 0.0004 s（**2.3x / 4.0x**） | 0.0179 / 0.0147 s |

局限必须一起读：单机单进程、系统分配器、`-O` 但 `codegen-units` 未收敛到 1、`get` 循环被内联且键序列在内存里预生成（对缓存友好，实际随机访问会更差）。**相对倍数可信，绝对秒数不可信**。

### Entry API Limits and Iteration Order

```rust
fn entry_usage() {
    let mut counts: std::collections::HashMap<String, u32> = Default::default();
    for w in ["a", "b", "a"] {
        *counts.entry(w.to_string()).or_insert(0) += 1; // 只哈希一次
    }
    let _ = counts;
}
```

`HashMap::entry` 是**必须掌握的一次哈希原则**：`get` 后判断再 `insert` 会哈希两次并可能触发两次探测。但围绕它有两条经常被讲错的事实，本机验证如下：

```text
pub fn f(s: &mut HashSet<i32>) { s.entry(1).or_insert(1); }
error[E0658]: use of unstable library feature `hash_set_entry`

pub fn f(m: &mut HashMap<String, i32>) { m.raw_entry_mut(); }
error[E0599]: no method named `raw_entry_mut` found for mutable reference `&mut HashMap<String, i32>` in the current scope
```

- `HashSet::entry` **至今未稳定**（gate `hash_set_entry`）。想要「同值不重复插入但复用已有分配的键」这种语义，要么用 `HashMap<K, ()>`，要么上 `hashbrown`。
- **raw-entry API 不在 std**。既没有稳定方法，也没有可用的 feature gate，只有 `hashbrown` 提供稳定版。需要「拿已存在的 `String` 键做一次借用查询、避免为查询而 `to_owned()`」时，`std` 层面只能用 `HashMap<Box<str>, _>` 或换 crate。

迭代顺序**没有任何保证**：本机对同一个 map 增删若干元素后，前 6 个键从 `[126, 188, 193, 120, 152, 137]` 变成 `[6, 230, 265, 120, 359, 367]`。这不是「bug」而是刻意划的边界——1.63.0 的一条库变更标题就叫 "Put a bound on collection misbehavior"：不承诺、也不承诺不承诺，以便实现自由演化。要把顺序当输出的一部分，就用 `BTreeMap`，或显式 `keys().collect::<Vec<_>>(); sort()`。

顺带一条实测形状：`HashMap::new()` 的 `capacity()` 是 0（不分配），插入第一个元素后变成 **3**——与「一次分配一组桶、负载因子 7/8」的开放寻址形态一致。具体常量属于 `hashbrown` 实现细节，文档不承诺，别写进断言。

## BTreeMap versus HashMap

| 维度 | `BTreeMap` | `HashMap` |
| :-- | :-- | :-- |
| 查找 | O(log n)，最坏有保证 | 平均 O(1)，**最坏 O(n)** |
| 范围查询 | `range(a..b)` 一次拿到连续区间 | 只能全表扫描 |
| 有序遍历 | 天然、可复现 | 无 |
| 键的要求 | 只需 `Ord`（不需要 `Hash`） | 需要 `Hash + Eq` |
| 缓存 | B 树节点一次装多个键值，遍历接近顺序访问 | 控制字节 + 开放寻址，点查极快 |
| 分配峰值 | 每次可能分裂节点，粒度不可控 | 只随容量增长重分配，`with_capacity` 可精确预热 |
| 内存头部 | 24 字节 | 48 字节（默认 hasher） |
| 典型用途 | 区间索引、需要 `first_key_value`/`pop_first`、输出必须稳定 | 计数、去重、字典查找 |

`BTreeMap` 的另一条隐藏价值是**确定性**：需要把 map 序列化成可比对的文本（快照测试、配置指纹、增量计算的 key）时，它是 std 里唯一能直接 `for` 出稳定顺序的 map。上面那张计时表也说明别用它当「有序版的性能等价物」——1M 规模下它比默认 `HashMap` 慢 5~7 倍，比换 hasher 后的慢 10 倍以上。

## The Rest of the Toolbox

`VecDeque<T>`（32 字节，环形缓冲）是唯一能两头 O(1) 的序列。两个坑：中间 `insert` 仍是 O(n)；要传给接受 `&[T]` 的 API 得先 `make_contiguous()`（可能重排内部布局并返回 `&mut [T]`）。BFS 队列、滑动窗口统计该它上场，而 `Vec::remove(0)` 是 O(n) 的整体前移，用它当队列是经典性能事故。

`BinaryHeap<T>` 是 `Vec<T>` 上的堆，**大顶**；`peek` O(1)、`pop`/`push` O(log n)，`into_sorted_vec()` 一次性拿到升序 `Vec`。要小顶堆就 `Reverse` 包键，或反过来实现 `Ord`。Top-K 用 `BinaryHeap::pop` 保持长度为 K，比全排 O(n log n) 省成 O(n log K)。

`LinkedList<T>` 的诚实定位是「几乎别用」：每节点一次分配，指针追逐把缓存优势全丢，`size_of` 只有 24 字节头部骗不了人。std 文档自己就推荐 `Vec`。它仅剩的场景是需要 `Cursor`/`CursorMut` 在**已知位置** O(1) splice 且不允许元素移动（`Vec` 的移动会打断指针/索引的场合）——而这通常也该重新设计成索引 + arena。

`Box<[T]>` 值得单列：构建期用 `Vec`，定型后 `into_boxed_slice()` 交出容量。省掉的那 8 字节在结构体里嵌 N 个数组时是实打实的，同时把「还能 `push`」这个错误可能性从类型上抹掉——这是 Rust 式的「用类型收窄表达不变式」。代价是 `into_boxed_slice` 若容量大于长度会**重新分配一次**。

## Iterators Are a State Machine

`Iterator` 只有一个必需方法：`fn next(&mut self) -> Option<Self::Item>`。这就是全部抽象——**迭代器是显式状态机，Option 是它唯一的「结束了」信号**。因此 `for` 循环、`while let Some(x) = it.next()`、以及「在循环里换迭代器」这三件事是同一件事的三种写法；也因此「迭代器失效」在 Rust 里不可能发生：状态机持有 `&mut self`，借用检查器直接把「边遍历边改容器」挡在编译期。

三个进入方式对应三种所有权语义：

| 写法 | `Item` | 容器之后 | 本机可观察差异 |
| :-- | :-- | :-- | :-- |
| `v.iter()` / `&v` | `&T` | 完好 | 循环体内不能再 `v.push(..)`（共享借用与可变借用冲突） |
| `v.iter_mut()` | `&mut T` | 完好 | 可原地改 |
| `v.into_iter()` | `T` | **消耗** | `v` 之后不可用；数组按值迭代只在 edition 2021+ |
| `v.drain(range)` | `T` | 变短，**容量保留** | 本机 `drain(..1)` 后 `capacity()` 仍是 3 |
| `v.extract_if(range, pred)` | `T` | 剔除命中元素 | 惰性：不 `collect` 也会在其 Drop 时完成删除 |

edition 那条差异本机实测（`let a = [1, 2, 3]; a.into_iter()`）：写成 `*...next().unwrap()`（期待 `&i32`）在 **2015/2018 编译通过**、在 2021/2024 报 `error[E0614]: type {integer} cannot be dereferenced`；反过来写成期待 `i32` 时在 2015/2018 报 `error[E0308]: mismatched types`、在 2021/2024 通过。机制与代价见 [Edition and MSRV](/docs/CS/Rust/Edition_MSRV.md)。

`extract_if`（`Vec`/`LinkedList` 于 **1.87.0** 稳定；本机 `HashMap`/`BTreeMap` 版本上也可用，属未逐个核实的稳定 API）取代了过去「`retain` + 一个外部 `Vec` 收集被删项」的两趟写法：`retain` 只告诉你留不留，`extract_if` 把被拿走的值交给你。

```rust
fn extract() {
    let mut v = vec![1, 2, 3];
    let taken: Vec<i32> = v.extract_if(.., |x| *x % 2 == 0).collect();
    assert_eq!((taken.as_slice(), v.as_slice()), ([2].as_slice(), [1, 3].as_slice()));
}
```

### Laziness size_hint peekable fuse

组合子**不产生任何循环**，只是把状态包进新结构体：`Zip`、`Flatten`、`FilterMap`、`Inspect`、`Map` 全部是「一个 `next()` 里推进内部状态机」。`inspect` 用于在链里插一段观测（本机 `.inspect(|_| {})` 与不插得到同一结果），`flatten` 把「一串迭代器」压平（`Vec<Vec<i32>> → Vec<i32>`），`filter_map` 是「过滤 + 解包 Option」的二合一，比 `filter(..).map(..)` 少一次 `Option` 往返。

`size_hint() -> (lower, Option<upper>)` 是迭代器唯一影响**分配**的接口，`Vec` 的 `reserve` 与 `collect` 全靠它。本机实测：`(0..10).filter(|x| x % 2 == 0).size_hint()` 是 `(0, Some(10))`（下界只能保守到 0），`take(3)` 是 `(3, Some(3))`，`chain(0..10, 0..10)` 是 `(20, Some(20))`。这条链的直接后果：`filter` 之后 `collect` 往往拿不到精确长度，退化成 push 式增长——想要精确分配就 `Vec::with_capacity(已知上界)` 再 `extend`。

`ExactSizeIterator` 是「长度编译期已知」的类型层标记，`Peekable`（`peek` 借用队首且不消费，本机 `peek` 后 `collect` 仍得到 `[1, 2, 3]`）与 `Fuse`（`next()` 返回过一次 `None` 之后**永远**返回 `None`）。`Fuse` 存在的理由是：`Iterator` 文档规定 `next()` 返回 `None` 之后再调用的行为**不作约定**，而很多组合子（尤其是自己实现 `Iterator` 时）必须在结束点重复判定；`fuse()` 用 1 字节把这个义务变成运行时保证。`FusedIterator` 则是类型层的对应声明。

### Why for Loops and Iterators Emit the Same Code

```rust
fn zero_cost() {
    let v: Vec<i64> = (0..20_000_000i64).collect();
    let mut s = 0i64;
    for i in 0..v.len() {
        s += v[i] * v[i];
    }
    let t: i64 = v.iter().map(|x| x * x).sum();
    let _ = (s, t);
}
```

本机 `-O` 计时（3 轮取最小）：索引循环 0.0064 s、`iter().map().sum()` 0.0064 s、`for x in &v` 0.0063 s——**同一条机器码的三次执行**。

把 `--emit=asm` 打开更直接：把三个 `pub fn`（`idx_f32` / `iter_f32` / `idx_i32` / `iter_i32`）写进一个 lib crate，`-O` 下**只生成 2 个函数体**——同形函数被 LLVM 合并成同一个符号；生成的函数里是 4 宽 NEON（`fmul.4s`、`ldr q`）加 4 路展开，`i64` 版则是 4 路 `madd` 展开（该目标没有 64×64 定宽 SIMD 乘法，所以「向量化」退化成「充分展开」，这本身也是 `sum-of-squares` 用 `i64` 时值得注意的一点）。

为什么能成立：`Range<usize>` / `slice::Iter` 在单态化后是**已知大小的结构体**，`next()` 会被内联成一次指针比较与自增，剩下的就是 LLVM 熟悉的计数循环形态；边界检查在指针步进被证明落在 `[ptr, ptr+len)` 内时消掉。机制（单态化、`#[inline]` 策略、`iter` 与 `into_iter` 的同源性）在 [Generics](/docs/CS/Rust/Generics.md) 与 [compile](/docs/CS/Rust/compile.md)。

> [!TIP]
> 反过来，把迭代器链 `collect` 成 `Vec` 再用索引循环走一遍是**纯亏**：多一次分配、多一遍内存。clippy 的 `needless_collect` 就是钉这个的。判断标准很简单——如果 `collect` 之后你只做「顺序访问 / `sum` / `iter().any`」，那就去掉 `collect`；只有一种情况必须 `collect`：**迭代过程中还要修改被迭代的容器**（借用检查器会拦住你），或者需要 `len()`/多次遍历。

## Performance Traps

本机能量化的几条：

| 陷阱 | 为什么慢 | 出路（含实测） |
| :-- | :-- | :-- |
| 不知道规模就一路 `push` | 每轮增长可能重分配 + memcpy；100k 次 push 实测 16 次重分配 | `Vec::with_capacity(n)` / `reserve(n)`，之后容量不再被抬高 |
| `s = format!("{s}{x}")` 循环拼接 | 每轮**整体拷贝**已累积的内容，O(n²) | 实测 n=200k：`format!` 11.65 s vs `with_capacity + write!` 0.0033 s（约 **3500x**） |
| 拼接前不预热容量 | `String` 与 `Vec<u8>` 一样按增长策略重分配 | `String::with_capacity(n * 平均长度)`，再 `write!`/`push_str` |
| `v.remove(0)` 当队列 | 每次整体前移，实测 `[1,2,3,4,5]` 删头剩 4 个但容量仍是 5 | `VecDeque`，或反向 `pop()`；批删用 `retain`/`extract_if` |
| 函数签名收 `&String` / `&Vec<T>` | 白增一层间接，还拒绝接受 `&str` / `&[T]` | 一律 `&str` / `&[T]`，靠 `Deref` 自动兼容 |
| 小容器内嵌进结构体 | 每个 `Vec` 固定 24 字节头部 + 一次堆分配 | 外部 `smallvec::SmallVec` / `tinyvec`（非 std；泛型参数写错反而更慢，需实测） |
| 定型后仍留 `Vec` 的 capacity | 8 字节头部 + 「未使用但已占用」的容量 | `into_boxed_slice()`（注意可能触发一次重分配） |
| 整数键默认 hasher | SipHash-1-3 的固定开销见上文 | 键可信时换 `rustc-hash`/`ahash`（实测 1.6~4.0x），**键不可信时不换** |
| `filter(..).collect()` 期待精确分配 | `size_hint` 下界为 0 | `with_capacity(上界)` + `extend` |

字符串拼接那行值得单独强调：`write!` 到 `String` 需要 `use std::fmt::Write`，而它和 `push_str` 的差别在本机只有 2 倍（0.0033 s vs 0.0069 s），远小于「循环里用 `format!`」那 3 个数量级。也就是说，**先消灭 O(n²)，再考虑省常数**。分配器层面的进一步优化（换全局分配器）见 [Performance](/docs/CS/Rust/Performance.md)。

## Cross-Language Comparison

五个真正影响写代码的维度：

| 维度 | Rust `HashMap` | C++ `unordered_map` | Go `map` | Java `HashMap` |
| :-- | :-- | :-- | :-- | :-- |
| 哈希种子 | 每进程随机（`RandomState`），SipHash-1-3 | 默认 `std::hash` **无随机化**；实现私有 | 每 map 一个随机 `hash0`，**故意不可复现** | `String.hashCode` 纯确定性；无种子（历史 `HashSip` 已移除） |
| 内存布局 | SwissTable 开放寻址：控制字节数组 + 元素数组，**元素原地存放** | **链地址**：节点式分配，桶数组 + 每元素一个节点（libstdc++/libc++ 均如此） | `hmap` + 每桶 8 个键值对 + `tophash` 摘要字节；溢出桶；元素不可取地址 | 桶数组 + 链表；链表长度到阈值且表够长时**树化**成红黑树 |
| 迭代顺序保证 | 无（且不承诺「不变」） | 无；但同实现同输入下通常稳定，重哈希会打散 | **显式随机化**（起始桶与桶内偏移随机），语言层面就防止你依赖顺序 | 无；`LinkedHashMap` 才给插入/访问序 |
| 越界检查 | `v[i]` panic（消息含类型与 trait 名），`get(i)` 返 `Option`；循环里检查常能被消掉 | `operator[]` **不检查（UB）**，`.at()` 抛异常 | 越界 panic（运行时检查，无法关） | 越界抛 `ArrayIndexOutOfBoundsException`（JIT 做范围检查消除） |
| 增长策略 | **规范不保证**；只保证摊还 O(1)（本机观察 2 倍） | 标准**不规定**；由 `max_load_factor` 与实现共同决定，主流 2x | 翻倍或缩表，**渐进式 rehash**（一次操作搬一点） | 桶数翻倍，负载因子默认 0.75 |

对照读法：Rust 与 C++ 同为「静态类型 + 零成本抽象」，但 `HashMap` 与 `unordered_map` 的性能差异主要来自**节点式 vs 原地式**这两套布局，而不是哈希函数；Go 走的是另一条路——map 是运行时数据结构，因此能在语言层面把迭代顺序随机化当作**契约工具**（逼你别依赖顺序），这是 Rust 和 C++ 都不做也不该做的设计，因为它们没有运行时可插进去；Java 的树化是在「哈希碰撞退化成 O(n)」和「常见情况别为红黑树付常数」之间的折中，而 Rust 的答复是把这件事推给 hasher：默认 SipHash-1-3 让碰撞构造在经济上不可行，而不是在表结构上兜底。

C 侧没有这两件东西（见 [C Array String](/docs/CS/C/Array_String.md)：手动 `malloc` + 手动长度 + 手动终止符），C++ 侧的容器与迭代器体系见 [STL](/docs/CS/C++/STL.md)：它的迭代器失效规则正是 Rust 借用检查器要替编译器解决的问题的另一面——`erase` 返回下一个有效迭代器这类惯例，在 Rust 里被类型系统写成了「你根本拿不到失效的迭代器」。语言层的横向速览见 [Languages](/docs/CS/Languages.md)。

## Links

- [Generics](/docs/CS/Rust/Generics.md)
- [Smart Pointers](/docs/CS/Rust/Smart_Pointers.md)
- [Performance](/docs/CS/Rust/Performance.md)
- [STL](/docs/CS/C++/STL.md)
- [C 数组与字符串](/docs/CS/C/Array_String.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

- [std::collections — Rust API docs](https://doc.rust-lang.org/std/collections/index.html)
- [Vec in std — Capacity and reallocation](https://doc.rust-lang.org/std/vec/struct.Vec.html)
- [HashMap in std::collections](https://doc.rust-lang.org/std/collections/struct.HashMap.html)
- [RandomState in std::collections::hash_map](https://doc.rust-lang.org/std/collections/hash_map/struct.RandomState.html)
- [Slice primitives — sort and sort_unstable](https://doc.rust-lang.org/std/primitive.slice.html)
- [Iterator trait](https://doc.rust-lang.org/std/iter/trait.Iterator.html)
- [Cow in std::borrow](https://doc.rust-lang.org/std/borrow/enum.Cow.html)
- [IntoIterator for arrays — Edition Guide 2021](https://doc.rust-lang.org/edition-guide/rust-2021/IntoIterator-for-arrays.html)
- [hashbrown — Rust implementation of Swiss Tables](https://rust-lang.github.io/hashbrown/)
- [Swiss Tables — Abseil design note](https://abseil.io/about/design/swisstables)
- [cppreference: std::unordered_map](https://en.cppreference.com/w/cpp/container/unordered_map)
