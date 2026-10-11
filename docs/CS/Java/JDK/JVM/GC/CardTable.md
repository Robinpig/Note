## Introduction

**Card Table（卡表）** 是分代 / 分区式 GC 实现 **remembered set（记忆集）** 的粗筛结构。它解决的问题是：老年代对象持有指向年轻代（或收集集内 region）的引用时，回收年轻代**不能漏掉**这些引用；但每次回收都完整扫描老年代，代价不可接受。

卡表的思路是**用空间换时间 + 用粒度换性能**：把堆按固定字节数切成「卡」，在每次**写引用**时把**被写的那个字段所在的卡**标脏（card marking），回收时只扫描标脏的卡，把卡内的对象当作潜在的根来源。

本篇讲的是 `share/gc/shared/cardTable.hpp` 这条**共享基础设施**：卡表的数据布局、写屏障如何落到指令、哪些收集器在扫它、以及 G1 的卡表与 RSet 的分工。

## Version Baseline

> [!NOTE]
> **卡大小由 `GCCardSizeInBytes` 决定，不是编译期常量**。`gc/shared/gc_globals.hpp:525` 定义 `product(uint, GCCardSizeInBytes, 512, ...)`，`range(128, NOT_LP64(512) LP64_ONLY(1024))`，并挂 `constraint(GCCardSizeInBytesConstraintFunc, AtParse)`——**越界或不是 2 的幂在解析命令行阶段就报错**。运行时值被缓存进 `CardTable::_card_size` / `_card_shift` / `_card_size_in_words` 三个 `static uint`。
>
> ⚠️ **JDK 8 时代的符号在本树已全部消失**（对 `jdk-27-ga` 全 `share/` 树 grep 零命中）：类名 `CardTableModRefBS`、常量 `CARD_SIZE` / `CARD_SIZE_LOG2`、字段 `_guard_index` / `_last_valid_index`、以及 RemSet API `younger_refs_in_space_iterate`。旧资料里按这些名字写的段落需要整体改写：现代入口是 `CardTable::card_size()` / `card_shift()` / `last_valid_index()`，扫描侧改由 `CardTableRS::scan_old_to_young_refs`（Serial）、`PSCardTable::scavenge_contents_parallel`（Parallel）、`G1RemSet::refine_card_concurrently`（G1）承担。
>
> **使用卡表的收集器**：Serial（`gc/serial/cardTableRS.{hpp,cpp}`）、Parallel（`gc/parallel/psCardTable.{hpp,cpp}`）、G1（`gc/g1/g1CardTable.{hpp,cpp}`）、Shenandoah（`gc/shenandoah/shenandoahCardTable.{hpp,cpp}`）。**ZGC 与 Epsilon 完全不使用卡表**：对 `gc/z`、`gc/epsilon` 两目录 grep `CardTable` 零命中，Epsilon 安装的是空的 `EpsilonBarrierSet`（详见 [Epsilon](/docs/CS/Java/JDK/JVM/GC/Epsilon.md)）。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Card Size and Address Mapping

`CardTable` 只做一件事：**堆地址 ↔ 卡表字节** 的双向映射。

### Card Values With Inverted Semantics

```cpp
  // We use 0x00 (zero) to represent Dirty and 0xFF to represent Clean because
  // this choice reduces the barrier code by one instruction on architectures with
  // a constant-zero register. On such architectures, the Dirty value (0x00) is
  // directly accessible through the zero register, eliminating the need to load
  // the value explicitly and thereby saving one instruction
  //
  // E.g. see
  //  Urs Hölzle. A fast write barrier for generational garbage collectors.
  //  In Eliot Moss, Paul R. Wilson, and Benjamin Zorn, editors, OOPSLA/ECOOP '93
  //  Workshop on Garbage Collection in Object-Oriented Systems, October 1993
  //
  enum CardValues {
    clean_card                  = (CardValue)-1,

    dirty_card                  =  0,
    CT_MR_BS_last_reserved      =  1
  };

  // a word's worth (row) of clean card values
  static const intptr_t clean_card_row = (intptr_t)(-1);
```

三个要点：

- **脏是 0、干净是 `0xFF`**——语义与直觉相反。原因是 AArch64 / RISC-V / SPARC 有**常量零寄存器**，标脏就是 `strb zr, [addr]` 一条指令，无需先把立即数装进寄存器。这也是 `clean_card_row = -1` 存在的原因：一整「机器字」全干净时该字等于 `0xFF..FF`，可以一次比较跳过 8 张卡。
- `CardValue` 是 `uint8_t`，且有 `STATIC_ASSERT(sizeof(CardValue) == 1)`，注释明确写着"所有代码生成器都假设卡表项是一字节"。
- `CT_MR_BS_last_reserved = 1` 只是保留值，G1 在同名低位上另做了扩展颜色（见后文）。

对外读接口是三个静态量与两个访问器：

```cpp
  static uint card_shift() { return _card_shift; }
  static uint card_size() { return _card_size; }
  static uint card_size_in_words() { return _card_size_in_words; }

  static constexpr CardValue clean_card_val()          { return clean_card; }
  static constexpr CardValue dirty_card_val()          { return dirty_card; }
  static constexpr intptr_t clean_card_row_val()       { return clean_card_row; }
```

### byte_for and the Shift

```cpp
  // Mapping from address to card marking array entry
  CardValue* byte_for(const void* p) const {
    assert(_whole_heap.contains(p), /* ... */);
    CardValue* result = &_byte_map_base[uintptr_t(p) >> _card_shift];
    assert(result >= _byte_map && result < _byte_map + _byte_map_size,
           "out of bounds accessor for card marking array");
    return result;
  }
```

配套的方向与粒度函数：`byte_after`（常用于循环上界）、`index_for`、`byte_for_index(card_index)`、以及**反向映射** `addr_for(CardValue*)`——注意它的实现刻意不用 `pointer_delta()`，因为 `_byte_map_base` 可能"负"到 `_byte_map` 之前，指针差值会触发断言：

```cpp
    // As _byte_map_base may be "negative" (the card table has been allocated before
    // the heap in memory), do not use pointer_delta() to avoid the assertion failure.
    size_t delta = p - _byte_map_base;
    HeapWord* result = (HeapWord*) (delta << _card_shift);
```

粒度对齐判断用 `static bool is_card_aligned(HeapWord* p)`（内部就是 `is_aligned(p, card_size())`）。

### The Virtual Base byte_map_base

堆不从地址 0 开始，但为了让「地址 >> card_shift」直接当数组下标，需要一个**虚拟基址**（`cardTable.cpp:92-97`）：

```cpp
  // The assembler store_check code will do an unsigned shift of the oop,
  // then add it to _byte_map_base, i.e.
  //
  //   _byte_map = _byte_map_base + (uintptr_t(low_bound) >> card_shift)
  _byte_map = (CardValue*) rs.base();
  _byte_map_base = _byte_map - (uintptr_t(low_bound) >> _card_shift);
```

于是 `_byte_map_base` 指向真实数组**之前**的某个地址，只用于加法、不可解引用。这样屏障侧永远只需要 `shr` + `add`（甚至合并成一次带位移的寻址），不必再减堆起点。

### Covered Regions and Lazy Commit

卡表**一次预留、按代增量提交**：

```cpp
  // Some barrier sets create tables whose elements correspond to parts of
  // the heap; the CardTableBarrierSet is an example.  Such barrier sets will
  // normally reserve space for such tables, and commit parts of the table
  // "covering" parts of the heap that are committed. At most one covered
  // region per generation is needed.
  static constexpr int max_covered_regions = 2;

  // The covered regions should be in address order.
  MemRegion _covered[max_covered_regions];
```

`initialize()` 用 `MemoryReserver::reserve(_byte_map_size, rs_align, _page_size, mtGC)` 预留整表，失败直接 `vm_exit_during_initialization("Could not reserve enough space for the card marking array")`；`resize_covered_region()` 才真正 `os::commit_memory_or_exit` / `os::uncommit_memory`，并且**扩展时 `memset(delta.start(), clean_card, ...)`**——新提交的分页必须先涂成"干净"，否则 `0x00` 会被当成脏卡。该函数开头 `assert(UseSerialGC || UseParallelGC, "only these two collectors")`，即**只有 Serial / Parallel 走这条按代提交路径**；G1 改为按 region 提交（`G1CardTable::initialize(G1RegionToSpaceMapper*)` + `G1CardTableChangedListener::on_commit`）。

分配粒度也值得注意：`_byte_map_size` 会 `align_up(num_bytes, MAX2(_page_size, os::vm_allocation_granularity()))`，因此**小堆上的卡表实际占用会明显大于理论值**。

## Memory Cost of the Card Table

一字节管一张卡，公式直白：

```text
卡表字节数 ≈ ceil(堆大小 / 卡大小) 向上对齐到 max(页大小, 分配粒度)
```

| 堆大小 | 卡大小 512 B | 卡大小 1024 B |
| :-- | :-- | :-- |
| 1 GB | 2 MiB | 1 MiB |
| 8 GB | 16 MiB | 8 MiB |
| 64 GB | 128 MiB | 64 MiB |
| 1 TB | 2 GiB | 1 GiB |

几点推论：

- **卡大小翻倍 → 卡表减半，但每张卡覆盖的堆翻倍**，扫描时的"误报"也翻倍；这正是 `GCCardSizeInBytes` 上界在 32 位平台压到 512（`NOT_LP64(512)`）的动机之一——小堆不需要大卡。
- 堆边界必须落在卡边界上：构造函数 `assert` 了 `_whole_heap` 的 start / end 都按 `_card_size` 对齐，因此 `CardTable::ct_max_alignment_constraint()` 返回 `GCCardSizeInBytes * os::vm_page_size()`，供上层决定堆对齐。
- **Shenandoah 的卡表是双份**（读表 + 写表，见下节），内存代价直接 ×2。
- G1 每 region 的卡数由 `G1HeapRegion::CardsPerRegion` / `LogCardsPerRegion` 给出，`G1ClearCardTableTask::worker_cost()` 就用 `num_regions << G1HeapRegion::LogCardsPerRegion` 估算清理工作量。

## Precise and Imprecise Card Marking

> [!WARNING]
> **卡表标的是"被写的那个字段所在的卡"，也就是持有引用的那个对象（源），而不是被写进去的目标对象。** 常见的直觉错误是"把 B 所属的卡标脏"——实际代码是 `byte_for(field)`，`field` 是**目的地址**（对象 A 的字段地址）。回收时扫脏卡的语义因此是"这张卡里的对象可能持有向下的引用，把 A 的字段逐个看一遍"。

`cardTableBarrierSet.hpp:39-45` 的注释给出了精度规则：

```cpp
// As it currently stands, this barrier is *imprecise*: when a ref field in
// an object "o" is modified, the card table entry for the card containing
// the head of "o" is dirtied, not necessarily the card containing the
// modified field itself.  For object arrays, however, the barrier *is*
// precise; only the card containing the modified element is dirtied.
```

即：**普通对象字段 → 标"对象头所在卡"（imprecise）；对象数组元素 / 未知引用 → 标"元素所在卡"（precise）**。这个区分在代码生成侧统一由一个布尔量决定：

```cpp
  bool is_array = (decorators & IS_ARRAY) != 0;
  bool on_anonymous = (decorators & ON_UNKNOWN_OOP_REF) != 0;
  bool precise = is_array || on_anonymous;
```

扫描侧必须配合这个语义。Serial 的实现把这条规则写成了显式注释：非 objArray 只要对象头那张卡脏，就认为对象**跨越的所有卡**（除最后一张）都脏，因为整个对象都会被扫一遍；而 objArray 是精确标记的，不允许跳到对象末尾（`CardTableRS::find_first_clean_card`）。

## Write Barrier in the Runtime Path

运行时（解释器 + 非内联 C1/C2 路径）通过 `AccessBarrier` 挂钩。核心只有三行：

```cpp
template <DecoratorSet decorators, typename T>
inline void CardTableBarrierSet::write_ref_field_post(T* field) {
  volatile CardValue* byte = card_table()->byte_for(field);
  *byte = CardTable::dirty_card_val();
}
```

`write_ref_field_pre` 在卡表屏障里是**空实现**——卡表只记"这里脏了"，不需要旧值，这与 G1 的 SATB 前屏障形成对照。

`AccessBarrier` 覆盖了四类写：`oop_store_in_heap`、`oop_atomic_cmpxchg_in_heap`、`oop_atomic_xchg_in_heap`、`oop_arraycopy_in_heap`、`clone_in_heap`。两个细节值得记：

- **cmpxchg 只在成功时标脏**（`if (result == compare_value)`），避免失败路径白写卡表。
- 带 checkcast 的数组拷贝在**类型检查失败时会先对已拷贝的前缀 `write_ref_array(dst_raw, pd)` 再返回 ArrayCopyFailure**——部分拷贝也必须留下脏卡，否则引用丢失。
- `write_ref_array(HeapWord* start, size_t count)` 会保守地把首尾对齐到 `HeapWord`（压缩 oops 下元素可能非对齐），因此**一次 arraycopy 可能多标半张卡**。

`ReduceInitialCardMarks` 允许编译代码跳过"刚分配对象的初始化写"的标脏，代价由慢路径分配出口补偿：

```cpp
void CardTableBarrierSet::on_slowpath_allocation_exit(JavaThread* thread, oop new_obj) {
#ifdef COMPILER2
  if (!ReduceInitialCardMarks) {
    return;
  }
  if (new_obj->is_typeArray() || card_table()->is_in_young(new_obj)) {
    // Arrays of non-references don't need a post-barrier.
  } else {
    MemRegion mr(cast_from_oop<HeapWord*>(new_obj), new_obj->size());
    // Do the card mark
    write_region(mr);
  }
#endif // COMPILER2
}
```

即：**快路径 TLAB 分配的新对象在 Eden，卡表天然不需要；慢路径可能直接分配到老年代，所以在这里整段补标**。G1 的注释同样写在这个函数上方，指出它的后屏障是"入队脏卡"而非直接标老年代卡。

## Code Generation for the Store Check

### Constant Card Table Base for Serial and Parallel

```cpp
  CardValue* card_table_base_const() const {
    assert(UseSerialGC || UseParallelGC, "Only these GCs have constant card table base");
    return card_table()->byte_map_base();
  }
```

这条断言解释了一个容易看漏的分歧：**Serial / Parallel 把 `_byte_map_base` 当立即数直接编进指令**；G1 / Shenandoah 则在运行时取（G1 从线程本地 `G1ThreadLocalData::card_table_base_offset()` 读），AOT 代码走 `AOTRuntimeConstants::card_table_base_address()` 间接加载。

### x86 Instruction Sequence

```cpp
void CardTableBarrierSetAssembler::store_check(MacroAssembler* masm, Register obj, Register rscratch) {
  __ shrptr(obj, CardTable::card_shift());
  intptr_t byte_map_base = (intptr_t)ctbs->card_table_base_const();
  if (__ is_simm32(byte_map_base)) {
    card_addr = Address(noreg, obj, Address::times_1, byte_map_base);
  } else {
    AddressLiteral cardtable((address)byte_map_base, relocInfo::none);
    card_addr = __ as_Address(ArrayAddress(cardtable, index), rscratch);
  }
  int dirty = CardTable::dirty_card_val();
  if (UseCondCardMark) {
    __ cmpb(card_addr, dirty);
    __ jccb(Assembler::equal, L_already_dirty);
    __ movb(card_addr, dirty);
  } else {
    __ movb(card_addr, dirty);
  }
}
```

理想情况下整个屏障就是 **`shr` + `movb [obj + disp], 0` 两条指令**（`is_simm32` 成立时）。若 `byte_map_base` 超出 32 位位移，退回 `AddressLiteral` + 重定位项，多一条装载。

`oop_store_at` 决定给哪个地址做 store check：

```cpp
  bool needs_post_barrier = val != noreg && in_heap;
  if (needs_post_barrier) {
    if (!precise || (dst.index() == noreg && dst.disp() == 0)) {
      store_check(masm, dst.base(), tmp2);        // 对象头，imprecise
    } else {
      __ lea(tmp1, dst);                          // 元素真实地址，precise
      store_check(masm, tmp1, tmp2);
    }
  }
```

注意 `val != noreg`——**装载（load）不产生屏障**。

### AArch64 Instruction Sequence

```cpp
  __ lsr(obj, obj, CardTable::card_shift());
  assert(CardTable::dirty_card_val() == 0, "must be");
  __ load_byte_map_base(tmp1);
  if (UseCondCardMark) {
    __ ldrb(tmp2,  Address(obj, tmp1));
    __ cbz(tmp2, L_already_dirty);
    __ strb(zr, Address(obj, tmp1));
  } else {
    __ strb(zr, Address(obj, tmp1));
  }
```

`strb zr` 正是把"脏 = 0"这一颠倒语义兑现成一条指令的地方：源码里甚至有 `static_assert` / `assert` 保证脏值是 0，否则这条指令就不成立。批量标脏（arraycopy 后屏障）也同样是 `strb zr, [start, count]` 的循环，x86 侧对应 `movb(Address(addr, count, Address::times_1), 0)`。

### C1 and C2

- **C1**：`gc/shared/c1/cardTableBarrierSetC1.cpp` 的 `store_at_resolved` / `atomic_cmpxchg_at_resolved` / `atomic_xchg_at_resolved` 先 `pre_barrier`（空）→ 原生 store → `post_barrier`。`post_barrier` 手工发射 `unsigned_shift_right(addr, CardTable::card_shift())` + `LIR_Address(tmp, card_table_base, T_BYTE)` + `move(dirty, card_addr)`；`UseCondCardMark` 时插入比较分支。`resolve_address` 还被重写，以便 precise 场景把地址解析进寄存器。
- **C2**：`gc/shared/c2/cardTableBarrierSetC2.cpp::post_barrier` 是等价的数据流版本，另外做两种**屏障消除**：
  - 写常量 `null` 直接返回（`t == TypePtr::NULL_PTR || t == Type::TOP`）；
  - `use_ReduceInitialCardMarks() && obj == kit->just_allocated_object(...)` 时跳过刚分配对象的初始化写。

  还有 `tightly_coupled_alloc`（`C2_TIGHTLY_COUPLED_ALLOC`）在 `store_at_resolved` 入口就把屏障整体旁路。宏展开阶段另有一个钩子 `CardTableBarrierSetC2::eliminate_gc_barrier`，把可证明冗余的卡表 store 直接替换成它的 memory input（`macro->replace_node(mem, mem->in(MemNode::Memory))`）；`UseCondCardMark` 时对应的 `LoadB` 会被替换成常量 0 从而折叠掉分支。

一般写屏障的概念与分类见 [c1](/docs/CS/Java/JDK/JVM/c1.md) 与 [JIT](/docs/CS/Java/JDK/JVM/JIT.md)，本篇只讲卡表这一种。

### UseCondCardMark

`product(bool, UseCondCardMark, false, "Check for already marked card before updating card table")`（`gc/shared/gc_globals.hpp:408`）。C2 里的注释把用途说得很清楚：

```cpp
  // The classic GC reference write barrier is typically implemented
  // as a store into the global card mark table.  Unfortunately
  // unconditional stores can result in false sharing and excessive
  // coherence traffic as well as false transactional aborts.
```

即：多线程写**落在同一缓存行的相邻卡**时，无条件 store 会引发缓存行争用（以及事务性代码的伪冲突中止）。打开后变成"先读、已脏就跳过"，读多了但写少了。**默认关闭**，只有在写引用极密集且 profiler 显示屏障缓存争用时才值得试。

## Who Scans Dirty Cards

### Serial

Serial 用 `CardTableRS : public CardTable`（注意它在 **`gc/serial/`** 而非 `gc/shared/`），注释写着"This RemSet uses a card table both as shared data structure for a mod ref barrier set and for the rem set information"——**卡表就是记忆集本身**。

调用链在 scavenge 末尾：`DefNewGeneration::collect` → `TenuredGeneration::scan_old_to_young_refs()` → `CardTableRS::scan_old_to_young_refs(tg, space()->top())`，后者用 `OldGenScanClosure`（定义在 `gc/serial/serialHeap.inline.hpp`）逐卡扫描。

真正的循环在 `non_clean_card_iterate`，两个游标函数决定它的成本：

- `find_first_dirty_card`：**一次比较一个机器字**，用 `clean_card_row_val()` 快速跳过 8 张全干净的卡（源码注释"Implemented word-iteration to skip long consecutive clean cards"）。这正是"脏 = 0 / 干净 = 0xFF"设计的第二重收益。
- `find_first_clean_card`：处理 imprecise 标记导致的"整对象跨卡"情况。

清理时机是**边扫边清**：`clear_cards(MIN2(dirty_l, clear_limit_card), MIN2(dirty_r, clear_limit_card))`，且刻意不清最后一张卡（`clear_limit_card`），因为**未对齐的尾卡可能已经含有新晋升对象的 old→young 引用**。

### Parallel

Parallel 的 `PSCardTable : public CardTable`（`gc/parallel/psCardTable.hpp`）多了**条带化（striping）**与**影子表**：

```cpp
class PSCardTable: public CardTable {
  friend class PSStripeShadowCardTable;
  static constexpr size_t num_cards_in_stripe = 128;
  Atomic<int> _preprocessing_active_workers;
```

流程是 `pre_scavenge(active_workers)` → `preprocess_card_table_parallel(...)`（把 imprecise 对象延伸出的脏标记"复制"到条带首卡）→ `scavenge_contents_parallel(...)` 按条带 `[start, end)` 并行扫描。`PSStripeShadowCardTable` 用来减少多线程在相邻条带边界的伪共享。

### Shenandoah

`ShenandoahCardTable : public CardTable` 维护**两份卡表**，这是它与其它三者最大的结构差异：

```cpp
  // We maintain two copies of the card table to facilitate concurrent remembered set
  // scanning and concurrent clearing of stale remembered set information.  During the
  // init_mark safepoint, we copy the contents of _write_byte_map to _read_byte_map and
  // clear _write_byte_map.
  CardValue* _read_byte_map;
  CardValue* _write_byte_map;
  CardValue* _read_byte_map_base;
  CardValue* _write_byte_map_base;
```

并发扫描读 `_read_byte_map`，mutator 屏障写 `_write_byte_map`，避免"扫描与清理并发"丢引用；`swap_read_and_write_tables()` 做切换。注释还留下一句工程权衡：目前**卡表地址被内联进屏障指令**，因此换表需要复制而非指针交换。另有 `#define ShenandoahMinCardSizeInBytes 128`。

### G1

G1 也继承 `CardTable`，但**卡表不是它的记忆集，只是"哪里可能有跨区域引用"的粗筛**；真正的持久结构是每 region 的 RSet。见下一节。

## G1 Card Table Versus Remembered Sets

### Card Values During Evacuation

`G1CardTable` 在共享的 `dirty/clean` 之上加了三种颜色（`gc/g1/g1CardTable.hpp:53-95` 的注释是本树对这套机制最完整的说明）：

```cpp
    g1_dirty_card = dirty_card,          // 0x0
    g1_card_already_scanned = 0x1,
    g1_to_cset_card = 0x2,
    g1_from_remset_card = 0x4
```

| 值 | 含义 | 谁产生 |
| :-- | :-- | :-- |
| `0xFF` | clean | 提交 / 清理 |
| `0x00` | dirty，待扫 | mutator 后屏障 |
| `0x01` | 本轮已扫，不再扫（仅 GC 期间） | 扫描 / 疏散 |
| `0x02` | 引用指向 collection set | 精炼阶段，可免再精炼 |
| `0x04` | 来自 remembered set 的脏卡 | 精炼阶段，用于估算脏卡产生率 |

判脏规则被压缩成**一位**：`LSB = 1 → clean`，`LSB = 0 → non-clean`。源码解释 `g1_to_cset_card` 是"粘性"的——精炼线程遇到它就直接搬到普通卡表而不再重新精炼，因为"已经找到的有趣引用多半仍然是有趣引用"；`g1_from_remset_card` 则用于把 mutator 产生的脏卡与 RSet 带来的脏卡分开，让**脏卡产生率预测更准**，从而更好地做精炼线程的水位控制。

### From Dirty Card to RSet

后屏障在 G1 里多做一步**同 region 过滤**（`cpu/x86/gc/g1/g1BarrierSetAssembler_x86.cpp:315-338`）：

```cpp
    __ movptr(tmp1, store_addr);                          // tmp1 := store address
    __ xorptr(tmp1, new_val);                             // tmp1 := store address ^ new value
    __ shrptr(tmp1, G1HeapRegion::LogOfHRGrainBytes);     // 同 region？
    __ jccb(Assembler::equal, L_done);
    ...
    __ shrptr(tmp1, CardTable::card_shift());
    Address card_table_addr(thread, in_bytes(G1ThreadLocalData::card_table_base_offset()));
    __ addptr(tmp1, card_table_addr);
    if (UseCondCardMark) { /* 只清卡时才写 */ }
    __ movb(Address(tmp1, 0), G1CardTable::dirty_card_val());
```

源对象与目标对象落在**同一个 heap region** 时屏障整段跳过——这是 GC 总览里提到的"两指令屏障"思想的实现（先做便宜的本地性过滤，再决定要不要标脏）。C++ 侧的对应实现：

```cpp
template <DecoratorSet decorators, typename T>
inline void G1BarrierSet::write_ref_field_post(T* field) {
  CardTable* local_card_table = card_table();      // 只读一次，防止编译器重装载到错误的表
  CardValue* byte = local_card_table->byte_for(field);
  if (*byte == G1CardTable::clean_card_val()) {
    *byte = G1CardTable::dirty_card_val();
  }
}
```

> [!IMPORTANT]
> **JDK 27 的 G1 已经没有 mutator 侧的 dirty card queue**。`G1BarrierSet::write_ref_field_post` 只写卡表，不再入队；`DirtyCardQueue` / `DirtyCardQueueSet` 在本树 grep 零命中，`G1BarrierSetRuntime` 只剩 SATB 相关的 `write_ref_field_pre_entry` 与 arraycopy 入口。脏卡的消费方式改成了**并发清扫卡表**：`G1ConcurrentRefineSweepTask` 用 `G1CardTableClaimTable` 抢占 region 块，再调用 `G1RemSet::refine_card_concurrently(card_ptr, worker_id)` 把脏卡里的跨区域引用写进目标 region 的 RSet。

一句话概括分工：**卡表是"粗筛 + 变更日志"（每 512 B 一字节，全局一张，可随意丢失），RSet 是"持久化的反向索引"（每 region 一份，记住"谁引用了我"）**。回收某 region 时，G1 只需要读它的 RSet 就能拿到根，不必扫整个堆；而 RSet 的正确性由卡表 + 并发精炼保证。

cleanup 阶段的专属动作是把已回收 region 的卡表整段清空：

```cpp
          G1HeapRegion* r = _g1h->region_at(_regions->at(i));
          // The card table contains "dirty" card marks. Clear unconditionally.
          //
          // Humongous reclaim candidates are not in the dirty set. This is fine because
          // we clean their card and refinement tables when we reclaim separately.
          r->clear_card_table();
```

这是一个 STW 子任务 `G1ClearCardTableTask`（阶段名 `G1GCPhaseTimes::ClearCardTable`），按 `num_cards_per_worker = M`（一百万张卡）为每个 worker 切块。

## Degradation Scenarios

卡表最实用的结论是**它在什么情况下会失去"只扫脏卡"的优势**：

| 场景 | 退化机理 | 后果与对策 |
| :-- | :-- | :--- |
| 大量老年代对象持续写年轻代引用 | 脏卡数量逼近"老年代卡总数"，扫描成本趋向"整代扫描" | 提高年轻代大小 / 减少长期对象持有短命引用；G1 侧表现为脏卡产生率升高 → 精炼线程与堆外内存占用上升 |
| 大对象数组批量写 | `write_ref_array` 逐卡 `strb`/`movb` 循环，长度按卡数计 | arraycopy 后屏障本身就是 O(跨越卡数)；超大数组拷贝考虑分片 |
| 多线程写同一卡（同一缓存行） | 无条件 store 造成伪共享与一致性流量 | `-XX:+UseCondCardMark`（先读后写） |
| Serial 疏散失败后年轻代未清空 | `maintain_old_to_young_invariant` **保守地把整个老年代已用区间标脏**（`dirty_MemRegion(used_mr)`），因为无法确定哪张卡持有 old→young 指针 | 下一次 scavenge 退化为整代扫描；由 `SerialHeap` 的全 GC 路径调用（`serialFullGC.cpp:775`） |
| G1 region 内引用泛滥 | 同 region 写被 `LogOfHRGrainBytes` 过滤掉，**不产生脏卡** | 这是 G1 的优势；但若对象分布退化（如巨型数组跨 region），过滤失效 |
| 卡表内存本身 | `heap / card_size` 字节常驻，Shenandoah 还要 ×2 | 大堆可考虑增大 `GCCardSizeInBytes`（64 位上限 1024），代价是扫描精度下降 |

最后一条是最常见的取舍：**卡越大，卡表越省内存、屏障争用越低，但每张脏卡要扫的堆越多**。

## Comparison With Alternative Schemes

| 方案 | 取舍 |
| :-- | :-- |
| 每对象一个标记位（精确） | 需要对象表或对象头额外位，开销大；数组元素与栈上槽位无处安放 |
| **卡表**，512 B 粒度 | 覆盖任意内存（含数组、栈上镜像的堆内部分），常数小；代价是卡内误判 |
| 页粒度位图 | 内存更省，但一页常 4 KB，误判率远高于卡 |
| 持久反向索引，RSet | 扫描成本与堆大小无关，但维护成本高、内存随引用关系增长（G1 每 region 一份） |
| 着色指针 + 读屏障 | 完全不需要卡表（ZGC），但要求堆内元数据与地址位借用 |

卡表能在**不依赖对象头**的前提下覆盖数组元素引用，这是它在分代 GC 中长期存在的原因。

## Observation and Tuning

```bash
# 卡大小：initialize_card_size 打印 "CardTable entry size: 512"（gc+init 域）
java -Xlog:gc+init=info -version

# 卡表地址区间与 _byte_map_base（gc,barrier trace）
java -Xlog:gc+barrier=trace -XX:+UseSerialGC -version

# 当前进程的堆与代信息（dcmd 名在 diagnosticCommand.hpp:244）
jcmd <pid> GC.heap_info

# 确认 flag 是否被改动
java -XX:+PrintFlagsFinal -version | grep -E 'GCCardSizeInBytes|UseCondCardMark'
```

`CardTable::print_on()`（`cardTable.cpp:259`）的格式串是 `"<desc> table byte_map: [start, end) _byte_map_base: <base>"`，默认描述词就是 `"Card"`；`CardTableBarrierSet::print_on()` 只是把 `st` 转发给它。想看实际地址区间，最省事的仍是 `-Xlog:gc+barrier=trace`。

`CardTable::initialize()` 里的三条 `log_trace(gc, barrier)` 会打印 `&_byte_map[0]`、`_byte_map[last_valid_index()]`、`_byte_map_base`，是理解"虚拟基址在真实数组之前"的最直接证据。

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [G1](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [Serial](/docs/CS/Java/JDK/JVM/GC/Serial.md)
- [Parallel](/docs/CS/Java/JDK/JVM/GC/Parallel.md)
- [Shenandoah](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)

## References

- [JEP 214: Remove GC Combinations Deprecated in JDK 8](https://openjdk.org/jeps/214)
- [JEP 379: Shenandoah: A Low-Pause-Time Garbage Collector (Production)](https://openjdk.org/jeps/379)
- [JEP 523: Make G1 the Default Garbage Collector in All Environments](https://openjdk.org/jeps/523)
