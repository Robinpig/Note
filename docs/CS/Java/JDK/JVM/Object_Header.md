## Introduction

HotSpot 里每一个 Java 对象在堆上都以一段固定的**对象头**开头，后面跟着实例字段，末尾再按对齐要求补
padding。对象头不是一个 C++ 结构体字段意义上的东西，而是被 `oopDesc` 覆写的堆内存前几个字：64 位虚
拟机上，它过去由 8 字节的 `markWord` 加上 4 字节的 `narrowKlass` 组成，共 12 字节，再补齐到对象对齐粒
度；从 JDK 24 引入、JDK 27 默认开启的**紧凑对象头**开始，klass 引用被塞进 `markWord` 的高位，整个头
压缩成一个 8 字节的机器字。

对象头要同时承担四件事：告诉 GC 对象的年龄与转发状态、告诉虚拟机锁的持有情况、缓存 `hashCode()` 的
identity hash、以及指向描述该对象类型的 `Klass`。这几件事挤在一个字里，所以每一位都被反复复用与重新
解释——理解了 `markWord` 的位布局，就理解了为什么 `MaxTenuringThreshold` 不能超过 15、为什么堆开得太
大要退回宽头、为什么 identity hash 会打乱 GC 的转发判断。

数组对象比实例对象多一个 `int` 类型的 `length` 字段，紧跟在对象头之后；这个字段在 C++ 里并不作为
`arrayOopDesc` 的成员声明，而是被排在声明字段之后或与 klass 共享的一段固定位置，靠
`arrayOopDesc::length_offset_in_bytes()` 计算偏移访问。

本篇只讲**对象头本身**与其衍生的**压缩指针机制**。类型系统的 `oop` / `Klass` 二分见
[Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)，`synchronized` 的完整加解锁流程见
[synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)，分配 fast path 见
[TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)，`Klass` 自身的地址空间管理见
[Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)。

## Version Baseline

> [!NOTE]
>
> 本篇基线为 **JDK 27**，以本机 `jdk-27-ga` 全量 HotSpot 源码为准。三个最容易写错的版本变化：
>
> - **紧凑对象头**：`UseCompactObjectHeaders` 在 JDK 27 已**默认为 true**（仅 64 位平台），履历为
>   JEP 450（24 引入，实验）→ JEP 519（25 转正）→ JEP 534（27 默认）。旧资料里"64 位对象头 = markWord +
>   narrowKlass 共 12 字节 / 补齐 16 字节"的说法在默认配置下已过时。
> - **偏向锁**：`UseBiasedLocking` 在 JDK 27 源码里**已彻底删除**，`runtime/arguments.cpp` 的 obsolete
>   表中已查不到该条目；不要再按 JDK 15 之前的"默认开启偏向锁"来理解对象头的 `lock` 位。
> - **`UseCompressedClassPointers`**：JDK 25 deprecated、**JDK 27 obsolete**（`arguments.cpp:544`），它不再
>   是可用开关，"关掉它省内存"的老建议在 JDK 27 上是无效 flag。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Object Layout on the Heap

一个实例对象在堆里的排布是：**对象头** → **实例字段** → **padding**。字段并非按 Java 源码里的书写顺序
摆放，而是由 `instanceKlass` 在链接期按类型与宽度重排（宽字段靠前以减少 padding），但重排算法本身不在
本篇展开。对象头本身分宽头与紧凑头两种布局：

| 布局 | 触发条件 | 对象头字节 | 构成 |
| :-- | :-- | :-- | :-- |
| 宽头 wide header | 32 位平台，或 64 位上 `UseCompactObjectHeaders=false` | `sizeof(markWord) + sizeof(narrowKlass)` = 8 + 4 = 12 字节，随字段一起按对齐补到 16 字节 | `markWord` 一个字 + `narrowKlass` 半个字（可能再带 4 字节 klass gap） |
| 紧凑头 compact header | 64 位平台且 `UseCompactObjectHeaders=true`（JDK 27 默认） | `sizeof(markWord)` = 8 字节 | 单个 `markWord`，klass 引用藏进高位 |

`oopDesc` 的两个成员恰好对应这两种布局：

```c++
class oopDesc {
 private:
  volatile markWord _mark;
  narrowKlass _compressed_klass;
```

`header_size()` 按 flag 二选一返回头长（单位 HeapWord）：

```c++
  // Size of object header, aligned to platform wordSize
  static int header_size() {
    if (UseCompactObjectHeaders) {
      return sizeof(markWord) / HeapWordSize;
    } else {
      return sizeof(oopDesc)  / HeapWordSize;
    }
  }
```

非紧凑头且启用压缩 klass 指针时，`_compressed_klass`（4 字节）后面可能还留一段 **klass gap**，
`klass_gap_offset_in_bytes()` = `klass_offset_in_bytes() + sizeof(narrowKlass)`，让实例字段从对齐边界起；
是否存在由 `has_klass_gap()`（转调 `ObjLayout::oop_has_klass_gap()`）决定。

数组对象 `arrayOopDesc` 在头之后多放一个 32 位 `int` 的 `length`。它在 C++ 里不是成员变量：

```c++
  // The _length field is not declared in C++.  It is allocated after the
  // declared fields of the object or shares space with the klass word.
  static int length_offset_in_bytes() { ... }
```

因此数组的"头"被定义为 oop 头 + length 字段，`arrayOopDesc::header_size()` 取
`length_offset_in_bytes() + sizeof(int)`。这也是数组比同 klass 的实例对象天生多 4 字节的原因。

## markWord Bit Layouts

`oops/markWord.hpp` 文件头注释给出三种布局的权威定义，原样摘录（字段按最高位在前书写，实际编码按最低
位在前，`lock:2` 永远在 bit 0-1）：

```c++
// The markWord describes the header of an object.
//
// Bit-format of an object header (most significant first, big endian layout below):
//
//  32 bits:
//  --------
//             hash:25              age:4  self-fwd:1  lock:2
//
//  64 bits (without compact headers):
//  ----------------------------------
//  unused:22  hash:31  valhalla:4  age:4  self-fwd:1  lock:2
//
//  64 bits (with compact headers):
//  -------------------------------
//  klass:22   hash:31  valhalla:4  age:4  self-fwd:1  lock:2
```

### Field Widths and Shifts

各字段的位宽常量（`oops/markWord.hpp`）：

```c++
  static const int lock_bits                      = 2;
  static const int self_fwd_bits                  = 1;
  static const int age_bits                       = 4;
  static const int valhalla_reserved_bits         = LP64_ONLY(4) NOT_LP64(0);
  static const int max_hash_bits                  = BitsPerWord - age_bits - lock_bits - self_fwd_bits - valhalla_reserved_bits;
  static const int hash_bits                      = max_hash_bits > 31 ? 31 : max_hash_bits;
```

| 字段 | 位宽 | shift | 32 位 | 64 位宽头 | 64 位紧凑头 | 含义 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| `lock` | 2 | 0 | bit 0-1 | bit 0-1 | bit 0-1 | 锁状态 / GC 转发标记，见状态机 |
| `self-fwd` | 1 | 2 | bit 2 | bit 2 | bit 2 | 某些 GC 的原地转发标志 |
| `age` | 4 | 3 | bit 3-6 | bit 3-6 | bit 3-6 | 分代年龄，`max_age = 15` |
| `valhalla` | 4（LP64）/ 0（32 位） | 7 | 无 | bit 7-10 | bit 7-10 | 为 Valhalla 值类型预留 |
| `hash` | 25 / 31 | 11（LP64）| bit 7-31 | bit 11-41 | bit 11-41 | identity hash |
| `unused` / `klass` | 22 | 42 | — | `unused:22` 高位空闲 | `klass:22` 复用高位 | 紧凑头时装 narrowKlass |

`hash_bits` 由 `BitsPerWord − age − lock − self-fwd − valhalla` 推出：64 位下 = 64 − 4 − 2 − 1 − 4 = 53，被
`max_hash_bits > 31 ? 31 : max_hash_bits` 截到 **31**；32 位下 `valhalla_reserved_bits=0`，= 32 − 4 − 2 − 1
= 25。这解释了注释里 "largest value is 31 bits" 与 32 位布局的 `hash:25`。

`klass_shift` 仅在紧凑头下有意义，等于 `hash_shift + hash_bits` = 11 + 31 = **42**，所以 klass 占 bit 42-63
（共 22 位，即高位看到的 `klass:22`）：

```c++
#ifdef _LP64
  // Used only with compact headers:
  // We store the (narrow) Klass* in the bits 43 to 64.
  static constexpr int klass_offset_in_bytes      = 4;
  static constexpr int klass_shift                = hash_shift + hash_bits;
  static constexpr int klass_bits                 = 22;
  static constexpr uintptr_t klass_mask           = right_n_bits(klass_bits);
#endif
```

`self-fwd` 摆在 bit 2 不是随意的：对象按 HeapWord 对齐，指针低位（含 bit 0-2）恒为 0，把 `self-fwd` 放在
bit 2 就能保证转发指针被正确判为"未自转发"，否则 `encode_pointer_as_mark()` 可能带上 `self-fwd`。

### age Width Bounds MaxTenuringThreshold

`age` 只有 4 位，最大年龄是 `max_age = age_mask = 0b1111 = 15`；`incr_age()` 到达上限后就地饱和：

```c++
  static const uint max_age                       = age_mask;
  markWord incr_age()      const { return age() == max_age ? markWord(_value) : set_age(age() + 1); }
```

晋升阈值 `MaxTenuringThreshold` 的合法区间被这个 4 位字段直接钉死（`gc/shared/gc_globals.hpp:488`），
`range` 上界正是 `markWord::max_age + 1`（默认 15）：

```c++
  product(uint, MaxTenuringThreshold,    15,                                \
          "Maximum value for tenuring threshold")                           \
          range(0, markWord::max_age + 1)                                   \
          constraint(MaxTenuringThresholdConstraintFunc,AfterErgo)          \
```

`gc/shared/ageTable.cpp:92` 还断言 `MaxTenuringThreshold should be 0 or markWord::max_age + 1`。**结论**：
4 位 `age` 字段是 `MaxTenuringThreshold` 不能超过 15（16 作为"直接晋升、不再计数"的哨兵值）的根因，这不是
可调参数而是位宽约束。

## lock Bits and the Object Monitor State Machine

`lock:2` 这两位既描述锁状态，也被 GC 借用来标记对象是否已被 mark / 转发。文件头注释给出全部编码：

```c++
//    [header          | 00]  locked             locked regular object header (fast-locking in use)
//    [header          | 01]  unlocked           regular object header
//    [header          | 10]  monitor            inflated lock (UseObjectMonitorTable == true)
//    [ptr             | 10]  monitor            inflated lock (UseObjectMonitorTable == false, header is swapped out)
//    [ptr             | 11]  marked             used to mark an object (header is swapped out)
```

对应常量：`locked_value = 0`、`unlocked_value = 1`、`monitor_value = 2`、`marked_value = 3`。

### Lock States

| lock 值 | 名称 | 含义 | 相关判定 |
| :-- | :-- | :-- | :-- |
| `01` | unlocked / neutral | 未加锁的普通对象头 | `is_unlocked()` / `is_neutral()` |
| `00` | locked | 轻量级 fast-locking，锁记录在栈上 `BasicLock`，头里不含指针 | `is_fast_locked()`，`set_fast_locked()` 清零 lock 位 |
| `10` | monitor | 膨胀后的重量级锁 | `has_monitor()` / `monitor()` |
| `11` | marked | GC 标记 / 转发，头被换出 | `is_marked()` |

`monitor`（值 2）有两种形态，取决于 `UseObjectMonitorTable`：为 true 时对象头保留 `[header | 10]`、
`ObjectMonitor` 存在独立哈希表里；为 false 时整个头被换成 `ObjectMonitor*` 指针，低位打 `10` 标签，解码
用异或取回（额外校验一位 tag）：

```c++
  ObjectMonitor* monitor() const {
    assert(has_monitor(), "check");
    assert(!UseObjectMonitorTable, "Locking with OM table does not use markWord for monitors");
    // Use xor instead of &~ to provide one extra tag-bit check.
    return (ObjectMonitor*) (value() ^ monitor_value);
  }
```

栈上的轻量级锁记录 `BasicLock` 在 JDK 27 里已不持有 "displaced header" 字段，而是缓存膨胀后使用的
`ObjectMonitor*`（`runtime/basicLock.hpp`）：

```c++
class BasicLock {
 private:
  // Used as a cache of the ObjectMonitor* used when locking. Must either
  // be nullptr or the ObjectMonitor* used when locking.
  ObjectMonitor* volatile _monitor;
```

`runtime/basicLock.cpp` 的 `move_to()` 注释保留了"this 轻量锁膨胀"的语义：displaced header 原本
unlocked/neutral，OSR 时把 `BasicLock` 从解释器帧搬到编译帧，靠 inflated fast-path 避免每次都真膨胀。
完整 fast_lock / inflated fast-path 汇编属 `synchronized` 范畴，见
[synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)。`ObjectMonitor::_metadata`（`runtime/objectMonitor.hpp`）
同样区分两态：用 OM 表时存 `_object` 的 hashCode，不用 OM 表时存换出的 displaced header。

### lock Bits Reused by GC

GC 标记-复制阶段借用同一批低位：`set_marked()` 把 lock 位置为 `marked_value`（3），转发指针编进 markWord
高位。`is_forwarded()` 对 `0b011`（普通转发）与 `0b1xx`（self-forwarded）都返回真（判定式即
`lock | self-fwd` 组成的位段 `>= marked_value`）。GC 是否保留原头由 `must_be_preserved()` 决定：

```c++
  // Should this header be preserved during GC?
  bool must_be_preserved() const {
    return !is_unlocked() || !has_no_hash();
  }
```

锁状态或 hash 一旦被转发指针覆盖就丢了信息，这正是紧凑头下 identity hash 与转发指针抢位的根源。

### Biased Locking Removed

> [!WARNING]
>
> JDK 27 源码里 `UseBiasedLocking` **已不存在**：在 `runtime/arguments.cpp` 的 deprecated / obsolete 表中
> `grep -rn UseBiasedLocking` **零命中**（`grep -rn BiasedLocking share/runtime/` 只匹配到无关的
> register coloring / JFR 里的 "biased" 字样）。因此 `lock:2` 状态机里**没有 biased 这一档**——旧资料的
> `[threadId | epoch | 1 | 01]` 偏向布局、"偏向 → 轻量 → 重量"三段式在本版都不成立。今天只剩
> `01 unlocked → 00 fast-locked → 10 monitor`，膨胀直接进重量级监视器。历史：偏向锁在 JDK 15
> deprecated 并默认禁用（JEP 374），JDK 18 obsolete（JDK-8256425），此后从源码彻底删除。

## Compressed Oops

32 位引用压缩（`UseCompressedOops`）让 64 位 VM 里的引用只用 32 位存储，靠全局的 **base** 与 **shift**
编解码。`narrowOop` 底层是 `uint32_t`，`oops/compressedOops.hpp` 用四档枚举描述模式：

```c++
  enum Mode {
    UnscaledNarrowOop  = 0,
    ZeroBasedNarrowOop = 1,
    DisjointBaseNarrowOop = 2,
    HeapBasedNarrowOop = 3
  };
```

| 模式 | 条件 | 解码 |
| :-- | :-- | :-- |
| UnscaledNarrowOop | `NarrowOopHeapBaseMin + heap_size < 4Gb`，无需编码 | 直接当指针用 |
| ZeroBasedNarrowOop | base = 0、仅 shift | `(uint64_t)v << shift` |
| DisjointBaseNarrowOop | base 32G 对齐且 base > 0，base 位与 oop 位不相交 | `(v << shift) \| base` |
| HeapBasedNarrowOop | base ≠ 0 且位相交 | `base + (v << shift)` |

统一解码式（`oops/compressedOops.inline.hpp`）就是 `base + (v << shift)`；`_base` / `_shift` 是
`CompressedOops` 的两个静态量。`compressedOops.cpp::initialize()` 按堆上界选 base 与 shift：堆落在
`UnscaledOopHeapMax`（4 GB）之上才 `set_shift`，落在 `OopEncodingHeapMax`（32 GB）之内才 `set_base(nullptr)`，
否则用 `heap_space.compressed_oop_base()` 带一个非零 base。两处判断都带 `|| AOTCompatibleOopCompression` 或
`&& !AOTCompatibleOopCompression`，即 AOT 模式强制偏移 base 与 shift。

### Heap Base Alignment Since JDK 15

base 是否被强制，取决于 `memoryReserver.cpp::reserve_compressed_oops_heap()`。关键机制名是**"heap base is
not enforced"**——非 AOT 情况下让 base 保持 null、把堆尽量塞进低 32G 区间（尝试 unscaled / zerobased 落点），
只有落不进去才用带 base 的 HeapBasedNarrowOop。这解除了 JDK 15 之前"非零 heap base 必须对齐 32GB"的要求：

```c++
  uintptr_t aligned_heap_base_min_address = align_up(MAX2(HeapBaseMinAddress, alignment), alignment);
  if (!AOTCompatibleOopCompression) { // heap base is not enforced
    unscaled  = (heap_end_address <= UnscaledOopHeapMax);
    zerobased = (heap_end_address <= OopEncodingHeapMax);
  }
```

`AOTCompatibleOopCompression` 是 `runtime/globals.hpp:127` 的 **DIAGNOSTIC** flag（默认 false）：一旦为真就
强制走 HeapBasedNarrowOop（`initialize()` 两处判断都带 `|| AOTCompatibleOopCompression`），让 AOT 代码不受
运行时堆落点影响。这也反证常规路径下堆 base 不必再对齐到 32GB。

### ObjectAlignmentInBytes and Compressible Heap Limit

可压缩堆上界 `OopEncodingHeapMax` 直接由对象对齐粒度算出（`runtime/arguments.cpp:1432-1436`）：

```c++
  LogMinObjAlignmentInBytes  = exact_log2(ObjectAlignmentInBytes);
  // Oop encoding heap max
  OopEncodingHeapMax = (uint64_t(max_juint) + 1) << LogMinObjAlignmentInBytes;
```

`max_juint + 1 = 2^32`（32 位 narrowOop 能表示的偏移个数），再左移 `LogMinObjAlignmentInBytes`。`narrowOop`
存的是"以对齐粒度为单位的偏移"，所以可寻址范围 = `2^32 × ObjectAlignmentInBytes`：

| ObjectAlignmentInBytes | Log2 | OopEncodingHeapMax | 推导 |
| :-- | :-- | :-- | :-- |
| 8（默认） | 3 | 2^32 × 8 = 2^35 = **32 GiB** | 32 位偏移 × 每 8 字节一格 |
| 16 | 4 | 2^32 × 16 = 2^36 = **64 GiB** | 同上，格子翻倍 |

`runtime/globals.hpp:134` 声明 `ObjectAlignmentInBytes` 默认 8、`range(8, 256)`。对齐从 8 提到 16，可压缩堆
上限从 32 GiB 翻到 64 GiB，代价是所有对象占用更多 padding。**这就是压缩指针 32GB 天花板的来源**：
不是拍脑袋的数字，而是 `2^32` 个对齐格子的自然结果。

## Compact Object Headers JEP 534

紧凑对象头把 `narrowKlass`（22 位）塞进 `markWord` 高位（bit 42-63），使 64 位对象头从"markWord +
narrowKlass = 12/16 字节"缩到单字 8 字节。三个真实代价都不体现在 flag 名里。

### Enabled by Default

`runtime/globals.hpp:131` 把它定为默认 true（仅 64 位），32 位下 `const bool … = false`：

```c++
  product(bool, UseCompactObjectHeaders, true,                              \
          "Use compact 64-bit object headers in 64-bit VM")                 \
```

### Cost One Heap Size Ceiling and Auto-Disable

Full GC 的转发指针复用对象头低位，紧凑头下 klass 占了高位，可转发的位数只剩 `NumLowBitsNarrow − Shift`
（`gc/shared/fullGCForwarding.hpp:45`）：

```c++
  static const int NumLowBitsNarrow = LP64_ONLY(markWord::klass_shift) NOT_LP64(0 /*unused*/);
  static const int Shift            = markWord::lock_bits + markWord::lock_shift;
```

推导：`NumLowBitsNarrow = markWord::klass_shift = 42`、`Shift = 2 + 0 = 2`，可用转发位 = `42 − 2 = 40`，堆
上限 = `right_n_bits(40) × HeapWordSize` = `(2^40 − 1) × 8 字节` ≈ **2^43 字节 = 8 TiB（8192 GiB）**。头文件
注释也点明 "we have 40 bits to encode forwarding pointers. This is enough to address 8TB of heap"。超过这个
上限时不报错，而是 warning 加**运行时自动关闭紧凑头**（`gc/shared/fullGCForwarding.cpp:32-45`）：

```c++
void FullGCForwarding::initialize_flags(size_t max_heap_size) {
#ifdef _LP64
  size_t max_narrow_heap_size = right_n_bits(NumLowBitsNarrow - Shift);
  if (UseCompactObjectHeaders && max_heap_size > max_narrow_heap_size * HeapWordSize) {
    warning("Compact object headers require a java heap size smaller than %zu"
            "%s (given: %zu%s). Disabling compact object headers.", ...);
    FLAG_SET_ERGO(UseCompactObjectHeaders, false);
  }
#endif
}
```

即最大堆超过约 8 TiB 时紧凑头自动降级回宽头；这个数字正是 `2^(klass_shift − lock_bits) × 8 字节`，与
`klass_shift = 42` 直接挂钩。

### Cost Two Incompatibility with UseObjectMonitorTable

`Arguments::set_compact_headers_flags()`（`runtime/arguments.cpp:3462-3465`）强制打开 OM 表——紧凑头里没有
多余空间放 `ObjectMonitor*`，重量级锁必须依赖独立 OM 表：

```c++
void Arguments::set_compact_headers_flags() {
#ifdef _LP64
  if (UseCompactObjectHeaders && !UseObjectMonitorTable) {
    if (FLAG_IS_CMDLINE(UseObjectMonitorTable)) {
      warning("-UseObjectMonitorTable is incompatible with +UseCompactObjectHeaders; ignoring -UseObjectMonitorTable");
    }
    FLAG_SET_DEFAULT(UseObjectMonitorTable, true);
  }
#endif
}
```

也就是说紧凑头下**关不掉** `-UseObjectMonitorTable`：命令行显式关会被忽略并 warning，回到 lock 状态机里
`monitor` 的 `[header | 10]` 形态。

### Cost Three Identity Hash Contends with klass

宽头下 `unused:22` 高位本就空闲，identity hash 占满 `hash:31`，klass 另有独立字段。紧凑头把 klass 挤进
bit 42-63 后，整个字刚好 64 位用满，`hash` 与 `klass` 谁都不能溢出。`copy_set_hash()` 只清
`hash_mask_in_place` 再写回，绝不误动 klass 段：

```c++
  markWord copy_set_hash(intptr_t hash) const {
    uintptr_t tmp = value() & (~hash_mask_in_place);
    tmp |= ((hash & hash_mask) << hash_shift);
    return markWord(tmp);
  }
```

klass 的初值由 `Klass::_prototype_header` 决定——每个 klass 有一个"原型头"（`oops/klass.hpp:159`，
`prototype_header()` / `set_prototype_header()`），新对象分配时从它拷入 markWord。紧凑头要求所有 klass 的
prototype header 已把 narrowKlass 编进高位；一旦头被 identity hash 或转发指针占用，就得靠
`must_be_preserved()` 保护原头，否则 GC 无法回收 klass 位。**identity hash 计算会破坏紧凑头下的转发编码，
是它最大的隐性代价**，也是 JEP 534 强调"对 hash 敏感的应用需实测"的原因。

> [!WARNING]
>
> `UseCompressedClassPointers` 在 JDK 25 deprecated、**JDK 27 已 obsolete**（`runtime/arguments.cpp:544`，
> obsolete 表条目 `deprecated=25, obsolete=27`）：
>
> ```c++
> #ifdef _LP64
>   { "UseCompressedClassPointers",   JDK_Version::jdk(25),  JDK_Version::jdk(27), JDK_Version::undefined() },
> #endif
> ```
>
> 旧资料里"关掉 `-UseCompressedClassPointers` 能省内存 / 换宽 klass 指针"的说法在 JDK 27 上是**无效
> flag**（用了会直接被拒），不要再据此设计对象头内存模型。

## narrowKlass Encoding

`Klass*` 在 oop 里的存储形态随头布局而变，两套几何由 `oops/compressedKlass.hpp` 分开定义：

```c++
  // Narrow klass pointer bits for an unshifted narrow Klass pointer.
  static constexpr int narrow_klass_pointer_bits_noncoh = 32;
  static constexpr int narrow_klass_pointer_bits_coh = 22;
  // The maximum shift values we can use depending on UseCompactObjectHeaders
  static constexpr int max_shift_noncoh = 3;
  static constexpr int max_shift_coh = 10;
```

### Wide Header Layout

非紧凑（non-coh）时，`narrowKlass _compressed_klass` 是 oop 里紧挨 `markWord` 的独立 32 位字段
（`narrow_klass_pointer_bits_noncoh = 32`），编解码同 `base + (nk << shift)` 套路，`shift` 最大
`max_shift_noncoh = 3`（Klass 至少 8 字节对齐），可寻址 Klass Range = `2^32 × 2^3 = 32 GiB`——对应
`compressedKlass.hpp` 文件头注释里 "shift=3 ... Encoding Range: [0 .. 0x8_0000_0000) (32 GB)"。

### Compact Header klass in markWord High Bits

紧凑头（coh）时 klass 只有 **22 位**（`narrow_klass_pointer_bits_coh = 22`），被 `markWord` bit 42-63 容纳；
为覆盖足够的 Klass 地址空间，允许 shift 提高到 `max_shift_coh = 10`（Klass 至少 `2^10 = 1024` 字节对齐）。
可寻址范围 = `2^22 × 2^10 = 2^32 = 4 GiB`——这正是紧凑头对 **Metaspace 里 Klass 地址空间**的硬约束：类元
数据必须落在能被"22 位 × 10 位 shift"编码的连续 Klass Range 内，超出就得靠 CDS 压缩或提高对齐。
`narrowKlass` 的 base/shift 由 `CompressedKlassPointers::initialize()` 在启动时确定（Klass Range 必须被
Encoding Range 包含），细节见 [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)。

| 维度 | 非紧凑头 non-coh | 紧凑头 coh |
| :-- | :-- | :-- |
| narrowKlass 位宽 | 32 位 | 22 位（`klass_bits`） |
| 最大 shift | `max_shift_noncoh = 3` | `max_shift_coh = 10` |
| klass 存放位置 | oop 内独立 `_compressed_klass` 字段 | `markWord` bit 42-63 |
| Klass 可寻址范围 | 约 32 GiB | 约 4 GiB（需对齐与落点配合） |

`klass_shift = 42` 这个数字在本篇出现三次——它既是紧凑头里 klass 段的起始位，又是 `FullGCForwarding` 推
8 TiB 堆上限的 `NumLowBitsNarrow`，是理解"为什么紧凑头会牺牲转发位"的枢纽。

## Links

- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)
- [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)
- [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)

## References

- [JEP 534: Compact Object Headers by Default](https://openjdk.org/jeps/534)
- [JEP 519: Compact Object Headers](https://openjdk.org/jeps/519)
- [JEP 450: Compact Object Headers (Experimental)](https://openjdk.org/jeps/450)
- [JEP 374: Deprecate and Disable Biased Locking](https://openjdk.org/jeps/374)
- [JEP 142: Reduce Cache Contention on Specified Fields](https://openjdk.org/jeps/142)
- [JDK-8256425 Obsolete Biased Locking in JDK 18](https://bugs.openjdk.org/browse/JDK-8256425)
- [The Java Virtual Machine Specification: Instances, Methods](https://docs.oracle.com/javase/specs/jvms/se21/html/jvms-2.html)
