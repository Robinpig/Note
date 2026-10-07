## Introduction

**Card Table（卡表）**是分代式 GC 用来实现 **remembered set（记忆集）** 的经典数据结构。它解决的问题是：老年代对象持有对年轻代对象的引用时，回收年轻代**不能漏掉**这些对象；但若每次都扫描整个老年代找引用，代价不可接受。

卡表的思路是**用空间换时间**：把堆按固定大小切成「卡」，在每次**写引用**时，只把「目标地址所在的卡」标脏（card marking）；回收年轻代时只需扫描被标脏的卡。

## Version Baseline

> [!NOTE]
> **版本口径**：卡大小由全局参数 `GCCardSizeInBytes` 决定，**默认 512 字节**，取值范围 `128` ~ `MaxGCCardSizeInBytes`（**32 位平台 512 / 64 位平台 1024**），超出范围会在**解析命令行时**报错。
>
> 卡表是**基于卡的收集器**（G1 / Parallel / Serial / Shenandoah）共用的基础设施（OpenJDK 主干 `src/hotspot/share/gc/shared/cardTable.cpp`）。**ZGC 与 Epsilon 不使用它**——前者有自己的多阶段着色指针/负载屏障方案，后者根本没有屏障（JEP 318）。
>
> 参见 [GC 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Core Mechanism

### 1. Determining Card Size

`card_shift` 是卡大小的以 2 为底的对数，这样地址到卡号的换算就变成一次**右移**：

```cpp
void CardTable::initialize_card_size() {
  assert(UseG1GC || UseParallelGC || UseSerialGC || UseShenandoahGC,
         "Initialize card size should only be called by card based collectors.");

  _card_size = GCCardSizeInBytes;          // 默认 512
  _card_shift = log2i_exact(_card_size);   // 512 → 9
  _card_size_in_words = _card_size / sizeof(HeapWord);

  log_info_p(gc, init)("CardTable entry size: " UINT32_FORMAT,  _card_size);
}
```

> [!TIP]
> **为什么是 512 字节？** 这是精度与开销的折中。卡越小，扫描越精确但卡表越大、写屏障的脏卡率越高；卡越大则反之。512 字节在两者间取了平衡，且正好是 2 的幂，使移位替代除法。

### 2. Address → Card Number

核心是 `byte_for()`：给定任意堆内地址，右移 `_card_shift` 即可直接算出对应卡表项的位置——**无需查表、无需除法**：

```cpp
// Mapping from address to card marking array entry
CardValue* byte_for(const void* p) const {
  assert(_whole_heap.contains(p),
         "Attempt to access p = " PTR_FORMAT " out of bounds of "
         " card marking array's _whole_heap = [" PTR_FORMAT "," PTR_FORMAT ")",
         p2i(p), p2i(_whole_heap.start()), p2i(_whole_heap.end()));
  CardValue* result = &_byte_map_base[uintptr_t(p) >> _card_shift];
  assert(result >= _byte_map && result < _byte_map + _byte_map_size,
         "out of bounds accessor for card marking array");
  return result;
}
```

### 3. Offset Tricks of `_byte_map_base`

这里有个容易看懵的设计。堆并非从地址 0 开始，但为了让数组下标与地址**线性对应**，需要一个「反推出来的虚拟基址」：

```cpp
//   _byte_map = _byte_map_base + (uintptr_t(low_bound) >> card_shift)
_byte_map_base = _byte_map - (uintptr_t(low_bound) >> _card_shift);
```

```cpp
CardValue* byte_map_base() const { return _byte_map_base; }
```

于是对任意地址 `p`，下标 `p >> card_shift` 天然包含了堆的低地址偏移，**不需要再减去堆起点**。代价是 `_byte_map_base` 指向实际卡表数组**之前**的某个地址——它只是用来做加法的基准，不是可解引用的指针。

### 4. Class Structure

```cpp
class CardTable: public CHeapObj<mtGC> {
protected:
  // The declaration order of these const fields is important; see the
  // constructor before changing.
  const MemRegion _whole_heap;       // the region covered by the card table
  size_t          _guard_index;      // index of very last element in the card
                                     // table; it is set to a guard value
                                     // (last_card) and should never be modified
  size_t          _last_valid_index; // index of the last valid element
  const size_t    _page_size;        // page size used when mapping _byte_map
  size_t          _byte_map_size;    // in bytes
  CardValue*      _byte_map;         // the card marking array
  CardValue*      _byte_map_base;

}
```

字段设计的两个细节：

- **声明顺序即初始化顺序**，注释明确警告改动会破坏构造函数——因为这些字段之间存在依赖（`_page_size` 要先算，才能定 `_byte_map_size`）；
- `_guard_index` 是**哨兵（sentinel）元素**，卡表最后一项固定为 `last_card` 值，让**越界检查不需要额外的比较分支**。

## Write Barrier: Who Marks Dirty

卡表本身只是数据结构，**标记动作发生在写屏障里**。当应用线程执行「把一个引用写进某个对象」时，编译器插桩（interceptor 与 JIT 都会生成）会调用屏障代码：

```text
对象 A 的字段被写入指向对象 B 的引用
        ↓
写屏障检查：这是一次「跨代写」或「指针移动」吗？
        ↓
是 → 把 B 所属的卡标脏（byte_for(B) 置位）
```

> [!WARNING]
> **卡表是「卡粒度」的近似**：把一张卡标脏，意味着**这张卡内的所有对象都可能被引用了**，而不只是实际被写的那一个。所以卡越大，扫描时需要处理的无效引用越多。GC 总览里提到的 **Two-Instruction 屏障**（用两条指令完成过滤）是另一种优化思路，用来减少进入屏障代码的开销。

相关机制见 [GC 总览的 Generation 一节](/docs/CS/Java/JDK/JVM/GC/GC.md?id=generation)，G1 的具体用法见 [G1 Roots](/docs/CS/Java/JDK/JVM/GC/G1.md?id=roots)。

## Why Not Use bitmap or Other Schemes

| 方案 | 取舍 |
| :-- | :-- |
| **每对象一个标记位**（精确） | 对象头/对象表开销大，且**无对象头的栈上引用、数组元素**无法记录 |
| **卡表**（512B 粒度） | 空间小、覆盖所有内存（含栈上槽位、数组），代价是卡内误判 |
| **位图 + 页表** | 内存最大 |
| **ZGC 的着色指针 / 负载屏障** | 彻底不写屏障（靠读屏障 + 元数据），但需分代无关的堆布局 |

卡表能在**不依赖对象头**的前提下覆盖「数组内引用」与「栈上引用」这两类无处安放引用的场景，这是它在分代 GC 中长期存在的原因。

## Observation and Tuning

```bash
# 打印卡大小与卡表范围（需要 -Xlog 支持）
java -Xlog:gc+init=info -Xlog:gc+barrier=trace -version

# 观察写屏障活动
java -Xlog:gc+barrier=debug -version
```

G1 的并发标记阶段可以打印写屏障统计（`gc+barrier` 域），用于判断屏障开销是否偏高。

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [G1](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)
- [Epsilon](/docs/CS/Java/JDK/JVM/GC/Epsilon.md)
