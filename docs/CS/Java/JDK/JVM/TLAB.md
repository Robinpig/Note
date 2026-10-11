## Introduction

堆上分配一个对象，本质上只是"把空闲指针往前推一段"（bump-the-pointer）。这个动作本身廉价到只有三条指令，但**空闲指针是全 JVM 共享的竞争资源**：如果每次 `new` 都要 CAS 或加锁去推进它，分配就成了所有线程的串行点——分配密集的负载里，锁竞争与 cache line 弹跳的开销会远大于对象初始化本身。

TLAB（Thread-Local Allocation Buffer）的思路是把这段竞争"批发变零售"：每个 Java 线程先从 Eden（或 GC 提供的某个分配区域）**整块批发**一段私有缓冲区，之后线程内的对象分配只在私有指针上做普通加法，无锁、无原子指令、可被 C2 内联成三四条机器指令。代价是引入了一组新问题，HotSpot 必须同时回答它们：

1. **半初始化对象的可解析性**。并发 GC 可能在一个对象刚 bump 出地址、header 尚未写入时扫到堆；TLAB 内"已划走但未用"的尾部空间在外部看来也不可解析。因此 HotSpot 约定：对象通过**最后 release 写 header/klass** 才变得可解析（`MemAllocator::finish`），TLAB 退化时**尾部必须写入 filler 对象**（`insert_filler`），GC 前还要 `ensure_parsability`。
2. **空间浪费**。线程私有就必然产生"每块用到一半就换掉"的内部碎片。HotSpot 用 refill waste limit、gc waste 统计与动态 sizing 把浪费压到可接受范围。
3. **大小估计**。TLAB 该开多大取决于线程分配速率，而分配速率是变化的，于是有了以 EMA 自适应的 resize 机制（`resize()` + `compute_size()`）。

堆的分代/区域布局本身属于 [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) 与各 GC 子树；对象头的位布局与写入口径属于 [对象头](/docs/CS/Java/JDK/JVM/Object_Header.md)。本篇只讲 TLAB 这条分配通道。

## Version Baseline

> [!NOTE]
> **版本口径**：TLAB 是 1999 年就存在的老机制，但 **JDK 27 的代码结构与大量旧资料（基于 JDK 17 及更早）已经对不上**，这是本篇最容易写错的点：
> - `MemAllocator::refill_contents()` 与 `ThreadLocalAllocBuffer::compute_desired_size()` **在 JDK 27 中已不存在**。refill 决策收拢在 `MemAllocator::mem_allocate_inside_tlab_slow()`（`gc/shared/memAllocator.cpp`），期望大小由 `initial_desired_size()` + GC 期的 `resize()` + refill 时的 `compute_size()` 三处共同决定。
> - `startup_initialization()` 里为 C2 预取预留空间的 `_reserve_for_allocation_prefetch` 静态字段已被删除，改为 `alignment_reserve()` 统一委托给 `CollectedHeap::lab_alignment_reserve()`（由 filler 对象大小推导，`gc/shared/collectedHeap.cpp:291-295`）。
> - `UseCompactObjectHeaders` 在 JDK 27 默认开启（仅 LP64），最小 dummy 对象只剩 1 个字头，恰好等于 `MinObjAlignment`，因此**默认配置下 `_lab_alignment_reserve == 0`**——"TLAB 尾部必须为 filler 预留对象头空间"这句老话在 JDK 27 默认配置下不再成立。
> - 字段改名：`_target_refills` → `_target_num_refills`、`_slow_allocations` → `_num_slow_allocations`，`_bytes_since_last_sample_point` 已移除。
> - fast path 汇编入口从 `MacroAssembler::fast_allocate*` 改名为 `MacroAssembler::tlab_allocate`，且真实实现在 `BarrierSetAssembler::tlab_allocate`（`gc/shared/` 下按 CPU 目录分发）。
>
> 各 flag 的默认值（`gc/shared/tlab_globals.hpp`，行号为 JDK 27）：`UseTLAB=true`:39、`ResizeTLAB=true`:42、`MinTLABSize=2K`:48、`TLABSize=0`:53、`TLABAllocationWeight=35`:65、`TLABWasteTargetPercent=1`:72、`TLABRefillWasteFraction=64`:78、`TLABWasteIncrement=4`:82。详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

当前 TLAB 不够分配时，如果剩余空间小于**最大浪费空间限制**（`_refill_waste_limit`），那么这个 TLAB 会被退回 Eden，重新申请一个新的。这个剩余空间就会成为孔隙。

如果不管这些孔隙，由于 TLAB 仅线程内知道哪些被分配了，在 GC 扫描发生时返回 Eden 区，如果不填充的话，外部并不知道哪一部分被使用哪一部分没有，需要做额外的检查，那么会影响 GC 扫描效率。所以 TLAB 回归 Eden 的时候，**会将剩余可用的空间用一个 dummy object 填充满**。如果填充**已经确认会被回收的对象**，也就是 dummy object，GC 会直接标记之后跳过这块内存，增加扫描效率。由于需要填充这个 dummy object，所以可能需要**预留出这个对象的对象头的空间**——这一步在 JDK 27 里由 `_allocation_end` 与 `hard_end()` 之间的 `alignment_reserve` 落实，其大小等于**最小 filler 对象**而不是"最大"，且在紧凑对象头下为 0（见 `initialize_tlab` 与 `TLAB Refill` 两节）。

## initialize_tlab

JVM 启动 [universe_init](/docs/CS/Java/JDK/JVM/start.md?id=universe_init) 时会初始化全局的 TLAB。入口在 `memory/universe.cpp:965`（由 `init` 于 `:898` 在堆初始化完成后调用）：

```cpp
// memory/universe.cpp:965
void Universe::initialize_tlab() {
  ThreadLocalAllocBuffer::set_max_size(Universe::heap()->max_tlab_size());
  PLAB::startup_initialization();
  if (UseTLAB) {
    ThreadLocalAllocBuffer::startup_initialization();
  }
}
```

`set_max_size` 取自当前 GC 的 `max_tlab_size()`：通用上限是"一个 `int[Integer.MAX_VALUE]` 能填满的尺寸"（`gc/shared/collectedHeap.cpp:419`），G1 收紧为 humongous 阈值，ZGC 收紧为 256 KiB（见 `TLAB Differences Between GCs`）。随后是每 VM 一次的启动初始化（`gc/shared/threadLocalAllocBuffer.cpp:246`）：

```cpp
void ThreadLocalAllocBuffer::startup_initialization() {
  ThreadLocalAllocStats::initialize();

  // Assuming each thread's active tlab is, on average,
  // 1/2 full at a GC
  _target_num_refills = 100 / (2 * TLABWasteTargetPercent);
  // We need to set the initial target number of refills to 2 to avoid a GC which causes VM
  // abort during VM initialization.
  _target_num_refills = MAX2(_target_num_refills, 2U);

  // During jvm startup, the main thread is initialized
  // before the heap is initialized.  So reinitialize it now.
  guarantee(Thread::current()->is_Java_thread(), "tlab initialization thread not Java thread");
  Thread::current()->tlab().initialize();
}
```

`_target_num_refills` 的含义：假定每次 GC 时线程的活跃 TLAB 平均用到一半，允许的浪费占比是 `TLABWasteTargetPercent`（默认 1%），于是两次 GC 之间的期望 refill 次数为 `100 / (2 * 1) = 50`。这个数字后面在 `initial_desired_size()` 和 `compute_size()` 里反复使用。

注意 JDK 27 的这个函数里**已经没有了**老版本那段著名的 `#ifdef COMPILER2` 预取预留计算（`_reserve_for_allocation_prefetch = (AllocatePrefetchDistance + ...) / HeapWordSize`）。预取越界的安全空间不再单独预留，`alignment_reserve()` 统一问 `CollectedHeap::lab_alignment_reserve()`（`:461`）：

```cpp
// gc/shared/threadLocalAllocBuffer.cpp:461
size_t ThreadLocalAllocBuffer::end_reserve() {
  return CollectedHeap::lab_alignment_reserve();
}
```

而 `lab_alignment_reserve` 在堆构造时算出（`gc/shared/collectedHeap.cpp:291-295`）：

```cpp
  // If the minimum object size is greater than MinObjAlignment, we can
  // end up with a shard at the end of the buffer that's smaller than
  // the smallest object.  We can't allow that because the buffer must
  // look like it's full of objects when we retire it, so we make
  // sure we have enough space for a filler int array object.
  size_t min_size = min_dummy_object_size();
  _lab_alignment_reserve = min_size > (size_t)MinObjAlignment ? align_object_size(min_size) : 0;
```

`min_dummy_object_size()` 就是 `oopDesc::header_size()`（`gc/shared/collectedHeap.hpp:318-320`）。所以：宽对象头（2 字）下 reserve 是 2 字；**JDK 27 默认紧凑头（1 字）= `MinObjAlignment`，reserve 为 0**；`ObjectAlignmentInBytes=16` 时又反转为 0/1 字的差别。这个值就是 `_allocation_end` 与 `hard_end()` 之间的缝隙。

每个 [JavaThread::run](/docs/CS/Java/JDK/Concurrency/Thread.md?id=javathreadrun) 启动时会先给线程挂上空 TLAB 描述符（`runtime/thread.cpp:150`）：

```cpp
void Thread::initialize_tlab() {
  if (UseTLAB) {
    tlab().initialize();
  }
}
```

```cpp
// gc/shared/threadLocalAllocBuffer.cpp:234
void ThreadLocalAllocBuffer::initialize() {
  initialize(nullptr,                    // start
             nullptr,                    // top
             nullptr);                   // end

  set_desired_size(initial_desired_size());

  set_refill_waste_limit(initial_refill_waste_limit());

  reset_statistics();
}
```

三参版 `initialize()`（`:223`）把五个指针全部摆正，注意 `_pf_top` 与 `_allocation_end` 都在这里归位：

```cpp
void ThreadLocalAllocBuffer::initialize(HeapWord* start,
                                        HeapWord* top,
                                        HeapWord* end) {
  set_start(start);
  set_top(top);
  set_pf_top(top);
  set_end(end);
  set_allocation_end(end);
  invariants();
}
```

## Data Layout

`ThreadLocalAllocBuffer` 是挂在 `JavaThread` 里的一个描述符（`CHeapObj<mtThread>`），本体不在堆内；堆内那段缓冲区只由这几个指针界定。类头的注释直接点出了 `_end` 的双重身份（`gc/shared/threadLocalAllocBuffer.hpp:35`）：

```cpp
// ThreadLocalAllocBuffer is a descriptor for thread-local storage used by
// mutator threads for local/private allocation. As a TLAB is thread-private,
// there is no concurrent/parallel access to its memory or its members,
// other than by estimated_used_bytes().
//
// Heap sampling is performed via the end and allocation_end
// fields.
// allocation_end contains the real end of the tlab allocation,
// whereas end can be set to an arbitrary spot in the tlab to
// trip the return and sample the allocation.
class ThreadLocalAllocBuffer: public CHeapObj<mtThread> {
  friend class VMStructs;
private:
  HeapWord* _start;                              // address of TLAB
  HeapWord* _top;                                // address after last allocation
  HeapWord* _pf_top;                             // allocation prefetch watermark
  HeapWord* _end;                                // allocation end (can be the sampling end point or _allocation_end)
  HeapWord* _allocation_end;                     // end for allocations (actual TLAB end, excluding alignment_reserve)

  size_t    _desired_size;                       // desired size   (including alignment_reserve)

  // If too many slow allocations (outside TLAB) happen, we increase
  // _refill_waste_limit. This reduces outside-TLAB allocations at
  // the expense of wasting more memory, i.e., the TLAB is discarded sooner.
  size_t    _refill_waste_limit;                 // hold onto tlab if free() is larger than this
  uint64_t  _allocated_before_last_gc;           // total bytes allocated up until the last gc

  static size_t   _max_size;                     // maximum size of any TLAB
  static unsigned _target_num_refills;           // expected number of refills between GCs

  unsigned  _num_refills;
  // TLAB retirement is invoked in two main contexts:
  // 1. TLAB refill:
  //    The current TLAB is insufficient to satisfy a pending allocation
  //    request, triggering a refill. The remaining space in the current
  //    TLAB is treated as waste and tracked in _refill_waste.
  // 2. Before GC:
  //    Invoked at the start of a GC cycle to ensure heap parsability.
  //    The unused space in the current TLAB is treated as waste and
  //    tracked in _gc_waste.
  unsigned  _refill_waste;
  unsigned  _gc_waste;
  unsigned  _num_slow_allocations;

  // Allocated size for filling TLAB in HeapWords
  size_t    _allocated_size;

  // Fraction of eden allocated by this thread, used for sizing its TLAB.
  AdaptiveWeightedAverage _allocation_fraction;
```

| 字段 | 含义 | 关键读者 |
| :-- | :-- | :-- |
| `_start` | TLAB 首地址 | 统计 `used_bytes`，`Thread::retire_tlab` |
| `_top` | bump 指针，最后一次分配之后的地址 | **fast path 唯一读写热点** |
| `_pf_top` | 预取水位线 watermark | 仅 C2 `AllocatePrefetchStyle==2`（`opto/macro.cpp:1910`） |
| `_end` | fast path 检查的"表观终点" | 可能是 `_allocation_end`，也可能被 JVMTI 采样提前拉低 |
| `_allocation_end` | 真实分配终点 | `hard_end() = _allocation_end + alignment_reserve` |
| `_desired_size` | 期望大小（含 reserve） | `compute_size` / `resize` / `initial_refill_waste_limit` |
| `_refill_waste_limit` | 剩余多少就不肯扔掉 TLAB | 慢路径判据（`memAllocator.cpp:275`） |
| `_num_refills` `_refill_waste` `_gc_waste` `_num_slow_allocations` `_allocated_size` | 统计组 | trace/debug 日志与 `ThreadLocalAllocStats` |
| `_allocated_before_last_gc` | 上次 GC 前累计分配字节 | `accumulate_and_reset_statistics` 算本轮速率 |
| `_allocation_fraction` | 本线程占 Eden 比例 EMA | `resize()` 的唯一输入 |

### _end vs _allocation_end

一次 refill 成功后（`fill()`，`threadLocalAllocBuffer.cpp:204`）：

```cpp
  initialize(start, top, start + new_size - alignment_reserve());
```

即 `_end == _allocation_end == 缓冲区尾 - alignment_reserve`。`alignment_reserve` 那截**永远不给对象用**，它是留给"万一尾部剩下不足一个对象"时能塞进最小 filler 的保险（宽头时代是 2 字；紧凑头为 0）。`remaining()`（`:70`）算的是 `hard_end() - top`，`free()` 算的是 `end - top`——refill 浪费记账用前者（真正扔回堆的字节），"还要不要留用这块 TLAB"的判断用后者。

`_end` 与 `_allocation_end` 分开是为了 **JVMTI 堆采样**：`MemAllocator::Allocation::notify_allocation_jvmti_sampler()`（`memAllocator.cpp:192-195`）把下一个采样点写进 `_end`：

```cpp
  // Set a new sampling point in the TLAB if it fits in the current TLAB
  const size_t words_until_sample = heap_sampler.bytes_until_sample(tlab.top()) / HeapWordSize;
  if (words_until_sample <= tlab.free()) {
    tlab.set_sampling_point(tlab.top() + words_until_sample);
  }
```

于是 fast path 撞到采样点时会"假装 TLAB 满了"走慢路径，在慢路径里完成采样，再 `set_back_allocation_end()`（`:290`，把 `_end` 恢复为 `_allocation_end`）重试。真终点 `_allocation_end` 因此必须独立保存，否则被拉低的 `_end` 会把整块 TLAB 截断。

### _pf_top Prefetch Watermark

`_pf_top` 只在一种组合下有读者：C2 且 `-XX:AllocatePrefetchStyle=2`（水位线式预取）。`PhaseMacroExpand::prefetch_allocation`（`opto/macro.cpp:1910` 起）生成的逻辑是：每次分配 bump 出新 `_top` 后与 `_pf_top` 比较，越过了才从 `_pf_top + AllocatePrefetchDistance` 处发起一串 `prefetch` 并把水位线推到那里；未越过则一条预取指令都不发。相比"每次分配都发预取"的 style 1，它用一次额外分支换掉了大部分预取指令的发射成本。`vmStructs.cpp:334` 为 SA 工具保留了该字段可见性，`thread.hpp:587` 提供 `tlab_pf_top_offset()` 给代码生成。

## Fast Path

同一条 TLAB bump 存在三份实现，语义一致：**取 `_top` → 加 size → 与 `_end` 比较 → 写回 `_top`**。

### C++ Implementation

解释器 runtime、JDK 内部直接分配等走 `ThreadLocalAllocBuffer::allocate`（`threadLocalAllocBuffer.inline.hpp:38`）：

```cpp
inline HeapWord* ThreadLocalAllocBuffer::allocate(size_t size) {
  invariants();
  HeapWord* obj = top();
  if (pointer_delta(end(), obj) >= size) {
    // Successful thread-local allocation.

    // This addition is safe because we know that top is
    // at least size below end, so the add can't wrap.
    set_top(obj + size);

    invariants();
    return obj;
  }
  return nullptr;
}
```

`size` 单位是 HeapWord，`end` 是"表观终点"。返回的内存**不清零**（注释明说 "The memory is NOT initialized to zero"，见 hpp `:141`），清零由分配器在 `initialize`/`mem_clear` 里做，或由 `ZeroTLAB` 整块做。

### Assembler Implementation

解释器 `new` 字节码（`cpu/x86/templateTable_x86.cpp` `TemplateTable::_new`，`:3573` 处调用）、C1（`c1_MacroAssembler_x86.cpp`，初始化对象前先 `tlab_allocate`）、C2（`opto/macro.cpp:1358` `expand_allocate_common`）最终都落到同一处后端实现——注意**老资料里的 `fast_allocate` 在 JDK 27 已改名为 `tlab_allocate`，且转发给 BarrierSetAssembler**（`cpu/x86/macroAssembler_x86.cpp:3534`）：

```cpp
void MacroAssembler::tlab_allocate(Register obj,
                                   Register var_size_in_bytes,
                                   int con_size_in_bytes,
                                   Register t1,
                                   Register t2,
                                   Label& slow_case) {
  BarrierSetAssembler* bs = BarrierSet::barrier_set()->barrier_set_assembler();
  bs->tlab_allocate(this, obj, var_size_in_bytes, con_size_in_bytes, t1, t2, slow_case);
}
```

`BarrierSetAssembler::tlab_allocate` 的默认实现（x86，`cpu/x86/gc/shared/barrierSetAssembler_x86.cpp:265`）就是全库 TLAB fast path 的真身：

```asm
  // obj = tlab._top
  movptr  obj, Address(r15_thread, JavaThread::tlab_top_offset())
  // end = obj + size (size 可为常量或寄存器)
  lea     end, Address(obj, con_size_in_bytes)
  // if end > tlab._end goto slow_case
  cmpptr  end, Address(r15_thread, JavaThread::tlab_end_offset())
  jcc     Assembler::above, slow_case
  // tlab._top = end   (bump)
  movptr  Address(r15_thread, JavaThread::tlab_top_offset()), end
```

aarch64（`cpu/aarch64/gc/shared/barrierSetAssembler_aarch64.cpp:239`）逐条对应：`ldr obj,[rthread,#tlab_top]` → `lea end,obj+size` → `ldr rscratch1,[rthread,#tlab_end]` → `cmp end,rscratch1` → `br HI, slow_case` → `str end,[rthread,#tlab_top]`。**G1 / ZGC / Shenandoah 都不覆盖这条 fast path**（在 `cpu/*/gc/` 下 grep 不到 `tlab_allocate` 的 override），线程私有所以无需任何 barrier；差异全部体现在 refill 慢路径。

`obj` 拿到的是"裸内存"，接下来的顺序以解释器 `_new`（x86）为准：

1. `tlab_allocate` bump 出对象地址（上面四条指令）；
2. 若 `ZeroTLAB` 则直接跳到写头（整块 TLAB 已在 refill 时清零）；
3. 否则循环把对象最后一个 8 字节写 0（配合最小重写技巧，`templateTable_x86.cpp:3595` 起）；
4. **最后写 header**：紧凑头下装载 `Klass::prototype_header` 单字 release 写入 mark 槽；非紧凑下写 `markWord::prototype()`、清 klass gap、`store_klass`。header（或其中 klass 位段）的可见时刻就是对象对并发 GC 可解析的时刻——这正是 Introduction 里第 1 个问题的答案。位布局与写入口径见 [对象头](/docs/CS/Java/JDK/JVM/Object_Header.md)。

### C2 IR Form and Prefetching

C2 不走 MacroAssembler 而是直接在理想图里展开（`gc/shared/c2/barrierSetC2.cpp` `BarrierSetC2::obj_allocate`，`:760-813`）：`LoadP tlab_top` → `AddP new_top` → `CmpP new_top, tlab_end` → `Bool ge` → `If` 分支 → **`prefetch_allocation`** → `StoreP tlab_top`。注意 C2 用 `>=` 判满，汇编用 `above`（`>`），语义等价（`_top` 永远不超过 `_end`）。预取指令插在 bump 与 store 之间，`prefetch_lines = 数组用 AllocatePrefetchLines / 实例用 AllocateInstancePrefetchLines`（`opto/macro.cpp:1491`）。

## Allocation Prefetch

对象一旦被分配，很快就会被写/读；顺序 bump 天然适合硬件预取，但 HotSpot 还允许软件预取，把"下一块大概率要用的内存"提前拉进 cache。全部由一组 `AllocatePrefetch*` flag 控制（定义在 `runtime/globals.hpp:1200-1230`，**注意不在 gc 的 globals 里**）：

| flag | 默认 | 含义 |
| :-- | :-- | :-- |
| `AllocatePrefetchStyle` | 1 | `0`=不预取；`1`=每次分配发一条预取；`2`=用 `_pf_top` 水位线门控；`3`=每条 cache line 一条 |
| `AllocatePrefetchDistance` | -1 | 预取超前分配指针的字节数，-1 表示平台自算 |
| `AllocatePrefetchLines` | 3 | 数组分配时超前预取的行数 |
| `AllocateInstancePrefetchLines` | 1 | 实例分配时超前预取的行数 |
| `AllocatePrefetchStepSize` | 16 | 相邻两条预取指令的地址步进 |
| `AllocatePrefetchInstr` | 0 | 预取指令选择（x86: 0=`prefetchnta` 等） |

语义逐条对应 `PhaseMacroExpand::prefetch_allocation`（`opto/macro.cpp:1905`）的三个分支：

- **style 2**（`:1910`）：比较新 `_top` 与 `_pf_top`，越过水位线才发 `lines` 条 `prefetch(new_pf_wmt + i*step)`，并把 `_pf_top` 推为 `_pf_top + distance`。分支预测良好（注释给的概率是"万分之一"量级），稳态下几乎不发预取指令。x86 上 Core 系 CPU 的水位线 distance 用 384（`vm_version_x86.cpp:3199`）。
- **style 3**（`:1993`）：把地址对齐到 cache line，每 line 一条——为 SPARC BIS 指令那类硬件设计，`startup_initialization` 老代码里"为 C2 预取多留 2 行"的注释解释了当年 `_reserve_for_allocation_prefetch` 的由来。
- **style > 0 的其余情况（即 1）**（`:2030`）：无条件对 `new_top + i*step` 发 `lines` 条。

平台默认值修正发生在 `VM_Version::initialize`：

- x86：`AllocatePrefetchStepSize` 提为 cache line（`vm_version_x86.cpp:1751`）；AMD Family 15h 默认 `Style=0`、`Instr=3`（`PREFETCHW`，`:1516-1525`）；`Distance` 按 CPU 家族取 192/256/384/512（`allocate_prefetch_distance`，`:3173`）；`Distance=0` 会反向废掉 Style（`:1754-1759`）。
- aarch64：`Distance = min(512, 3*dcache_line)` 并强制 8 的倍数（`vm_version_aarch64.cpp:123-127,145-147`）；Style 保持全局默认 1。
- riscv / ppc / s390 在各自 `vm_version_*.cpp` 里微调。

这些预取访问的是 `_end` 之后的"未来"地址，因此 fast path 的 bump 必须保证越界访问落在同一个已 commit 的堆区域内——这解释了为什么预取参数改动会连带影响 `alignment_reserve` 的历史演进（见 `initialize_tlab` 一节）。

## TLAB Refill

`MemAllocator::mem_allocate`（`gc/shared/memAllocator.cpp:326`）把三条路径串起来，这也是"慢路径"的权威枚举点：

```cpp
HeapWord* MemAllocator::mem_allocate(Allocation& allocation) const {
  if (UseTLAB) {
    // Try allocating from an existing TLAB.
    HeapWord* mem = mem_allocate_inside_tlab_fast();
    if (mem != nullptr) {
      return mem;
    }
  }

  // Allocation of an oop can always invoke a safepoint.
  DEBUG_ONLY(allocation._thread->check_for_valid_safepoint_state());

  if (UseTLAB) {
    // Try refilling the TLAB and allocating the object in it.
    HeapWord* mem = mem_allocate_inside_tlab_slow(allocation);
    if (mem != nullptr) {
      return mem;
    }
  }

  return mem_allocate_outside_tlab(allocation);
}
```

`mem_allocate_inside_tlab_slow`（`:252`）是 refill 决策的全部：

```cpp
  if (JvmtiExport::should_post_sampled_object_alloc()) {
    // ...把被采样点拉低的 _end 恢复，重试一次 fast path
    tlab.set_back_allocation_end();
    mem = tlab.allocate(_word_size);
    if (mem != nullptr) return mem;
  }

  // Retain tlab and allocate object in shared space if
  // the amount free in the tlab is too large to discard.
  if (tlab.free() > tlab.refill_waste_limit()) {
    tlab.record_slow_allocation(_word_size);
    return nullptr;                       // -> 走 outside-tlab
  }

  // Discard tlab and allocate a new one.
  tlab.record_refill_waste();             // 剩余额度计入 _refill_waste
  _thread->retire_tlab();                 // 写 filler + 清指针

  // To minimize fragmentation, the last TLAB may be smaller than the rest.
  size_t new_tlab_size = tlab.compute_size(_word_size);
  if (new_tlab_size == 0) return nullptr; // 空间凑不齐 -> outside-tlab

  size_t min_tlab_size = ThreadLocalAllocBuffer::compute_min_size(_word_size);
  mem = Universe::heap()->allocate_new_tlab(min_tlab_size, new_tlab_size, &allocation._allocated_tlab_size);
  if (mem == nullptr) return nullptr;

  // ...and clear or zap just allocated TLAB, if needed.
  if (ZeroTLAB) {
    Copy::zero_to_words(mem, allocation._allocated_tlab_size);
  } else if (ZapTLAB) {
    size_t hdr_size = oopDesc::header_size();
    Copy::fill_to_words(mem + hdr_size, allocation._allocated_tlab_size - hdr_size, badHeapWordVal);
  }

  _thread->fill_tlab(mem, _word_size, allocation._allocated_tlab_size);
  return mem;
```

要点逐条：

1. **保 TLAB 还是扔 TLAB**：剩余 `free()` 大于 `_refill_waste_limit` 就**留着这块 TLAB**，本次对象去 shared 空间分配，同时 `record_slow_allocation()`（`threadLocalAllocBuffer.inline.hpp:90`）把上限抬高 `TLABWasteIncrement`（默认 4 字）——"老在外面分配说明这块留着也没用，下次果断扔"。`initial_refill_waste_limit = desired_size / TLABRefillWasteFraction`（默认 1/64，`cpp:62`）。
2. `record_refill_waste()` 把 `remaining()`（按 `hard_end` 算）累加进 `_refill_waste`，然后 `_thread->retire_tlab()`。
3. `compute_size()` 决定新 TLAB 要多大（见 Dynamic Sizing），拿 `CollectedHeap::unsafe_max_tlab_alloc()` 封顶——"下次 GC 前还能安全 bump 的总量"。
4. 真正的划内存委托给当前 GC 的 `allocate_new_tlab(min, requested, actual)`，**允许返回比 requested 小、比 min 大的实际值**。
5. `fill_tlab → fill()`（`threadLocalAllocBuffer.cpp:196`）：`_num_refills++`、`_allocated_size += new_size`、以 `start + new_size - alignment_reserve` 为 `_end` 摆正指针，并**重置 `_refill_waste_limit`**（`:220`，注释 "Reset amount of internal fragmentation"）。

JFR 的两个分配事件也在这里挂账：`notify_allocation_jfr_sampler()`（`memAllocator.cpp:203`）区分 `ObjectAllocationInNewTLAB`（伴随 refill）与 `ObjectAllocationOutsideTLAB`，实现细节见 [JFR](/docs/CS/Java/Tools/JFR.md)。

### Retire and Filler

`Thread::retire_tlab`（`runtime/thread.cpp:156`）先给"已分配字节数"总账（`incr_allocated_bytes(tlab().used_bytes())`）和 JVMTI 采样器收尾，再进 `ThreadLocalAllocBuffer::retire`（`threadLocalAllocBuffer.cpp:145`）：

```cpp
void ThreadLocalAllocBuffer::retire(ThreadLocalAllocStats* stats) {
  if (stats != nullptr) {
    accumulate_and_reset_statistics(stats);
  }

  if (end() != nullptr) {
    invariants();
    insert_filler();
    initialize(nullptr, nullptr, nullptr);
  }
}

void ThreadLocalAllocBuffer::insert_filler() {
  assert(end() != nullptr, "Must not be retired");
  if (top() < hard_end()) {
    Universe::heap()->fill_with_dummy_object(top(), hard_end(), true);
  }
}
```

这就是 dummy object 叙述的源码对应物：填充范围是 `[top, hard_end)`——注意是 `hard_end` 而不是 `end`，`alignment_reserve` 那截也在 filler 覆盖之内；`zap=true` 表示 debug 构建下填充 `badHeapWordVal`。另有一条更轻的路径 `make_parsable()`（`:138`）：GC 前只写 filler 但不退役 TLAB（`ensure_parsability(retire_tlabs=false)` 时走它，`collectedHeap.cpp:524-542`），`ZeroTLAB` 开着时例外地强制完整 retire。

filler 到底是什么对象？`CollectedHeap::fill_with_dummy_object`（`:520`）默认转发 `fill_with_object`，最终由 `fill_with_object_impl`（`:478`）二选一：

```cpp
  if (words >= filler_array_min_size()) {
    fill_with_array(start, words, zap);          // int[]，klass = Universe::fillerArrayKlass
  } else if (words > 0) {
    assert(words == min_fill_size(), "unaligned size");
    ObjAllocator allocator(CollectedHeap::filler_object_klass(), words);
    allocator.initialize(start);                 // jdk.internal.vm.FillerObject
  }
```

即**大块孔隙填一个 `int[]`，不足一个数组头的碎缝用专门的最小 filler 类 `jdk.internal.vm.FillerObject`**（`classfile/vmSymbols.hpp:104`；`vmClasses.cpp:210` 在初始化时替换掉兜底的 `java_lang_Object`）。`is_filler_object()` 认这两种 klass（`collectedHeap.inline.hpp:55`）。"GC 直接跳过"的说法对应的就是：filler 是活的假对象，任何遍历都会把它当一个完整对象整块跨过，孔隙不会被误读成半初始化对象；而 TLAB 上限之所以是"最大 `int[]` 的大小"（`max_tlab_size`，`collectedHeap.cpp:419`），正因为再大就填不出**一个**filler 了。

GC 侧还会各自加工：G1 覆写 `fill_with_dummy_object` 在填 old region 前同步 BOT（`gc/g1/g1HeapRegion.cpp:771-777`）；Serial/Parallel/G1 的 safepoint 都会经过 `CollectedHeap::ensure_parsability`（如 `gc/shared/gcVMOperations.cpp:188`，堆验证/heap dump 前也会调）。safepoint 机制本身见 [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)。

线程退出同样会 retire（`runtime/javaThread.cpp:828`、失败 attach 清理 `:892`），保证不留不可解析尾。

## Dynamic Sizing

期望大小不是常数，三层机制叠出来：

### Default Flag Values

| flag | 默认 | 作用 | 定义 |
| :-- | :-- | :-- | :-- |
| `UseTLAB` | true | 总开关 | `gc/shared/tlab_globals.hpp:39` |
| `ResizeTLAB` | true | 允许 GC 期 resize | `:42` |
| `MinTLABSize` | 2K 字节 | 下限（换算成字后再加 reserve） | `:48` |
| `TLABSize` | 0 | 非 0 则钉死初始 desired size，禁 ergo 初值 | `:53` |
| `TLABAllocationWeight` | 35 | 各 EMA 权重 | `:65` |
| `TLABWasteTargetPercent` | 1 | GC 时可容忍的 Eden 浪费百分比，决定 `_target_num_refills` | `:72` |
| `TLABRefillWasteFraction` | 64 | refill waste 上限 = desired/64 | `:78` |
| `TLABWasteIncrement` | 4 字 | 每次 outside 分配抬高的 waste 上限 | `:82` |

### initial_desired_size at Thread Birth

`threadLocalAllocBuffer.cpp:265`。`TLABSize > 0` 时直接采用；否则：

```cpp
    const size_t predicted_total_requested_size = (size_t)(ThreadLocalAllocStats::total_requested_size_fraction_avg() * Universe::heap()->tlab_capacity());
    const uint num_threads = ThreadLocalAllocStats::num_allocating_threads_avg();
    const size_t per_thread_requested_size = predicted_total_requested_size / num_threads;
    const size_t tlab_size = per_thread_requested_size / _target_num_refills;
```

两个 EMA 预测量都在 `ThreadLocalAllocStats::initialize()` 里以 `TLABAllocationWeight` 加权、并给了冷启动样本（分配线程数=1，需求占比=10%，`:324-331`）。直觉：`predicted_total_requested_size / num_threads` ≈ 本线程到下次 GC 前总共要分配多少（**目标分配速率 × GC 间隔**），除以期望 refill 次数 50，就是每次 refill 该拿多大。

### resize after Each GC

`CollectedHeap::resize_all_tlabs()`（`collectedHeap.cpp:544`）遍历所有线程调 `ThreadLocalAllocBuffer::resize()`（`threadLocalAllocBuffer.cpp:161`）：

```cpp
  size_t alloc = (size_t)(alloc_fraction * capacity_in_words);
  size_t new_size = alloc / _target_num_refills;
  new_size = clamp(new_size, min_size(), max_size());
  size_t aligned_new_size = align_object_size(new_size);
  ...
  set_desired_size(aligned_new_size);
  set_refill_waste_limit(initial_refill_waste_limit());
```

`_allocation_fraction` 的样本在 `accumulate_and_reset_statistics`（`:78`）里喂：`(本轮分配字节 - 上轮基线) / tlab_capacity`，且只有当 Eden 确实用过半才采样（避免小 GC 污染估计）。调用点按 GC 各异：通用实现挂在 Serial/Parallel/G1 Full 的收尾（`serialHeap.cpp:788`、`psScavenge.cpp:458` 等），G1 young 在 post-evacuate 阶段逐线程 resize（`gc/g1/g1YoungGCPostEvacuateTasks.cpp:906`），ZGC 挂在 per-thread retire（见下节）。

### compute_size Boost at Refill

`threadLocalAllocBuffer.inline.hpp:54`：

```cpp
  size_t scaled_desired_size = desired_size();
  if (ResizeTLAB) {
    // Extra boost if too many refills; 16X at most.
    if (_num_refills > _target_num_refills) {
      const uint excess = _num_refills - _target_num_refills;
      const uint steps = MIN2(excess / 8, 4U);
      ...
        scaled_desired_size <<= steps;
    }
  }
  size_t new_tlab_size = MIN3(available_size, scaled_desired_size + align_object_size(obj_size), max_size());
```

desired 只反映"上一轮 GC 的平均"，追不上突变；所以本轮 refill 次数每超 8 次档位，就把期望尺寸翻倍，最多 16 倍。`available_size = unsafe_max_tlab_alloc()/HeapWordSize` 是硬顶（下次 GC 前最多还能安全 bump 的总量），`compute_min_size(obj_size)`（`:84`，`max(aligned_obj + reserve, MinTLABSize)`）是地板，凑不齐地板就返回 0、这单走 outside。

### EMA and TLABAllocationWeight

HotSpot 内像 `exp_avg()` 这种预测函数都采用 EMA（Exponential Moving Average，指数加权移动平均），`gcUtil.hpp:102`：

```cpp
  static inline float exp_avg(float avg, float sample, unsigned int weight) {
    return (100.0F - (float)weight) * avg / 100.0F + (float)weight * sample / 100.0F;
  }
```

权重越高，最近样本对预测影响越大。`TLABAllocationWeight=35` 意味着每次 GC 的新观测占 35%——线程数是动态起落的，resize 要基于历史平均分配线程数推测未来规模，权重太小会被单次毛刺带偏，太大则跟不上负载换挡。冷启动阶段另有保护：`compute_adaptive_average`（`gcUtil.cpp:29-45`）在样本数不足 `100/weight` 前先用 `1/count` 平滑。这个 weight 同时作用于三处 EMA：`_num_allocating_threads_avg`、`_total_requested_size_fraction`（均 `cpp:325-329`）与每线程 `_allocation_fraction`（构造函数 `cpp:57`）。

## Slow Paths

`memAllocator.hpp` 没有枚举（JDK 27 里三个路径就是三个受保护成员函数，`:45-53`）：

| 函数 | 触发条件 | 后果 |
| :-- | :-- | :-- |
| `mem_allocate_inside_tlab_fast` | 无条件先试 | `_top` 够用即成功；不够用返回 null |
| `mem_allocate_inside_tlab_slow` | fast 失败，且 `UseTLAB` | 见上一节：采样恢复 / 留 TLAB / refill |
| `mem_allocate_outside_tlab` | 无 TLAB、留 TLAB 弃单、或 refill 凑不出空间 | `Universe::heap()->mem_allocate()`，**这条路径才允许触发 GC** |

补充三条容易漏掉的细分：

1. **`UseTLAB=false`**：C2 在 `expand_allocate_common`（`opto/macro.cpp:1398`）直接废掉 fast path，全部对象走 `mem_allocate_outside_tlab`，每次分配都要在堆级分配器上竞争（G1 仍走 CAS `par_allocate`，Serial/Parallel 走 HeapLock）。
2. **JVMTI 采样点**：`_end` 被人为拉低造成的"假满"，在 slow 入口先 `set_back_allocation_end()` + 重试解决（`memAllocator.cpp:256-271`），不算真正的 refill。
3. **大对象**：`compute_size` 保证 `min_size(obj)` 装得下才 refill，否则这单直接 outside；在 G1 中超过 humongous 阈值的请求根本不会以 TLAB 形式分配（`assert(!is_humongous(requested_size))`）。

三条失败出口（留 TLAB / compute_size 为 0 / allocate_new_tlab 为 null）都汇入 `mem_allocate_outside_tlab`，其中 `_thread->incr_allocated_bytes` 与 `heap_sampler().inc_outside_tlab_bytes` 补齐账本（`memAllocator.cpp:234-246`）。

## TLAB Differences Between GCs

`allocate_new_tlab` 是唯一由各 GC 覆写的插槽，差异集中在此：

| GC | refill 来源 | GC 触发 | retire/resize 时机 | TLAB 尺寸上限 |
| :-- | :-- | :-- | :-- | :-- |
| Serial / Parallel | 分代 Eden，堆锁保护 | 可以同步 GC | 通用 `ensure_parsability` + `resize_all_tlabs` | 通用最大 `int[]` |
| G1 | 当前 region CAS，装不下就换 region | **refill 不触发 GC** | safepoint 统一 retire；young 后逐线程 resize | humongous 阈值 |
| ZGC | 共享页原子 CAS 划出一段 | 从不（分配只 stall，由 pacer 驱动） | 线程栈水位线到 gc 阶段时 retire+resize | 256 KiB |
| Shenandoah | `allocate_memory(req)`，可返回小值 | 从不直接触发 | `ensure_parsability` 是空操作；Full/Degenerated 才全局 retire | PLAB 通用上限 |
| Epsilon | 独占 bump | 从不 | 通用 | 4 MiB（`EpsilonMaxTLABSize`） |

- **G1**：`G1CollectedHeap::allocate_new_tlab`（`gc/g1/g1CollectedHeap.cpp:429`）注释写明"不允许借 refill 之机做 GC"（否则会吞掉 `UseGCOverheadLimit` 的 OOME 判定），直接 `attempt_allocation(..., allow_gc=false)`。分配区域按 NUMA 节点各一个 `MutatorAllocRegion`（`g1Allocator.cpp:51`），TLAB 用 `par_allocate(min, desired)` 对 region top 做 CAS（`g1AllocRegion.inline.hpp:51-65`），因此 **TLAB 从不跨 region**；region 用尽换新的时会 `retire(true)`，`fill_up_remaining_space`（`g1AllocRegion.cpp:52-100`）以"整块一次性 CAS 抢下剩余空间"对抗仍在本 region 上竞争的线程，抢赢才写 dummy 并 `set_pre_dummy_top`。`max_tlab_size` = humongous 阈值（`:2304`），`unsafe_max_tlab_alloc` 是"当前 alloc region 的剩余额度且不低于 MinTLABSize"（`g1Allocator.cpp:191-199`）。详见 [G1](/docs/CS/Java/JDK/JVM/GC/G1.md)。
- **ZGC**：`ZCollectedHeap::allocate_new_tlab` → `ZHeap::alloc_tlab` → `ZObjectAllocator::alloc`（`zCollectedHeap.cpp:137`、`zHeap.inline.hpp:92`）——TLAB 与"outside 分配"用的是同一套共享页原子分配器：small 对象走 **per-CPU 共享页**、medium 走共享 medium 页（`zObjectAllocator.hpp:23-52`）。`max_tlab_size() == ZObjectSizeLimitSmall == ZPageSizeSmall/8`，即 2 MiB 小页的 1/8 = **256 KiB**（`zGlobals.hpp:35-55`、`zHeap.cpp:144`）。`unsafe_max_tlab_alloc` 读 eden 分配器剩余额度，剩余额度不足 MinTLABSize 时故意报"最大"（反正下次 refill 会逼分配器换页，`zHeap.cpp:148-161`）。`mem_allocate`（outside）返回 null 只会 `out_of_memory()`，**分配路径上不存在同步 GC**，跟不上节奏靠 allocation stall 与 pacer。TLAB 的 retire 不靠全局 safepoint 而是**栈水位线**：`ZStackWatermark::start_processing_impl` 在该线程 GC 栈扫完且处于 mark 阶段时 `ZThreadLocalAllocBuffer::retire`（`zStackWatermark.cpp:193-197`），后者 retire 完顺手 `resize()`（`zThreadLocalAllocBuffer.cpp:65-73`）。Eden 小页的占用按页做 TLAB accounting（`zHeap.cpp:232-247`）。详见 [ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC.md)。
- **Shenandoah**：`allocate_new_tlab` 把请求包成 `ShenandoahAllocRequest::for_tlab` 交给统一入口 `allocate_memory`（`shenandoahHeap.cpp:911-921`），受 pacer/分配缓冲影响，**返回尺寸可以远小于请求**。最有辨识度的一点：`ShenandoahHeap::ensure_parsability` 是**空实现**（`:1798-1800`，注释解释其对象遍历走 bitmap + barrier，不需要线性可解析堆），全局 TLAB retire 只在 Full GC（`shenandoahFullGC.cpp:226`）与 Degenerated GC（`shenandoahDegeneratedGC.cpp:379`）里显式 `tlabs_retire()`；正常周期中 resize 发生在 per-thread 栈水位线推进时（`shenandoahStackWatermark.cpp:124`）。GC 侧还有对称的 GCLAB（晋升缓冲，`PLAB`），与 TLAB 是两套但共用 filler/dummy 机制。详见 [Shenandoah](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)。
- **Epsilon**：`_max_tlab_size = MIN2(通用上限, EpsilonMaxTLABSize=4M)`（`gc/epsilon/epsilonHeap.cpp:57`，flag 在 `epsilon_globals.hpp:53`）。真正值得读的是它的 **elastic TLAB** 策略（`EpsilonElasticTLAB` 默认 true，`allocate_new_tlab` 全体 `:181-246`）：每线程记一个 `ergo_tlab_size`，请求超过它就按 `EpsilonTLABElasticity`（默认 1.1）放大再分配，久不分配（超过 `EpsilonTLABDecayTime`，默认 1000 ms）则衰减归零——用"惰性增长 + 定时衰减"替代 resize-at-GC，因为无 GC 可挂。详见 [Epsilon](/docs/CS/Java/JDK/JVM/GC/Epsilon.md)。
- 附带一句：`tlab_globals.hpp` 里紧挨着的 `YoungPLABSize=4096` / `OldPLABSize=1024`（`:57,:61`）属于 **PLAB**——GC 线程晋升时的本地缓冲，机制同构但生命周期在 GC 内部，不在本篇范围。

## Observability

- **统一日志**：TLAB 的全部内部日志都打在 `gc,tlab` tag 上（tag 定义 `logging/logTag.hpp:211`），三档真实输出（均在 `threadLocalAllocBuffer.cpp`）：
  - `-Xlog:gc+tlab=trace`：逐线程三行——`TLAB fill`（`:209`，refill 时刻的容量与 refill 计数）、`TLAB GC`（`:112`，desired / 本轮分配 / slow allocs / waste 百分比 / gc 与 refill waste 字节）、`TLAB resize`（`:178`，alloc-fraction 与尺寸变化）。
  - `-Xlog:gc+tlab=debug`：全局汇总 `TLAB totals`（`:438`，线程数、refills、slow allocs、两类 waste 的总量与最大值）。
  - 分配失败/慢路径的 GC 侧输出在 `gc,alloc` tag（G1 `g1CollectedHeap.cpp:491`、Shenandoah `:984`）。
- **Perf 计数器**：`-XX:+UsePerfData` 时发布 `sun.gc.tlab.*` 十个变量：`allocThreads` / `fills` / `maxFills` / `alloc` / `gcWaste` / `maxGcWaste` / `refillWaste` / `maxRefillWaste` / `slowAlloc` / `maxSlowAlloc`（`threadLocalAllocBuffer.cpp:333-342`）。
- **JFR**：`jdk.ObjectAllocationInNewTLAB` 与 `jdk.ObjectAllocationOutsideTLAB` 两个事件对应 `memAllocator.cpp:203-214` 的挂账点（`AllocTracer::send_allocation_*`，`gc/shared/allocTracer.cpp:35,45`）。字段与采样开销的分析见 [JFR](/docs/CS/Java/Tools/JFR.md)，此处不重复。
- **判断"TLAB 是否在起作用"的经验信号**：`gc+tlab=debug` 里 `slow allocs` 高且 `refill waste` 占比大 → 分配尺寸方差大，考虑调 `TLABRefillWasteFraction` / `TLABWasteIncrement`；waste 占比逼近 `TLABWasteTargetPercent` → desired size 与分配速率不匹配。关闭 `UseTLAB` 后 Eden 分配退化到堆级竞争（`slowAlloc` 变成所有分配），一般只有排查内存占用（TLAB 尾浪费）时才关。
- `estimated_used_bytes()`（`:465`）是给外部工具（SA / dump）读的近似值，注释明确警告其对并发访问不做精确保证。

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)
- [c1](/docs/CS/Java/JDK/JVM/c1.md)
- [Object](/docs/CS/Java/JDK/Basic/Object.md)

## References

- [JEP 450: Compact Object Headers (Experimental)](https://openjdk.org/jeps/450)
- [JEP 534: Compact Object Headers by Default](https://openjdk.org/jeps/534)
- [JEP 439: Generational ZGC](https://openjdk.org/jeps/439)
- [JEP 318: Epsilon: A No-Op Garbage Collector (Experimental)](https://openjdk.org/jeps/318)
