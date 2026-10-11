## Introduction

**Epsilon** 是一个 **no-op 垃圾收集器**：它只负责**分配内存**（以及按需把堆扩展出去），**不回收任何对象、不做压缩、不处理引用**。它的实现有意薄到"一眼看完"——整个 `share/gc/epsilon/` 目录只有一千来行 C++，`collect()` 的主体是一句日志。

Epsilon 的价值恰恰来自"它什么都不做"：它是**当前 JVM 里唯一能把 GC 开销压到理论下限的配置**，也是**测量"这个负载到底会吃掉多少内存"的最直接工具**（堆占用单调不减，泄漏无处可藏）。它的边界同样来自这一点：堆满即 `OutOfMemoryError`。

## Version Baseline

> [!NOTE]
> **JEP 编号是 `318`，不是 306**。实测 `https://openjdk.org/jeps/318` 的标题是 **`JEP 318: Epsilon: A No-Op Garbage Collector (Experimental)`**（JDK 11 引入实验版）；JEP 306 是 `Restore Always-Strict Floating-Point Semantics`，与 GC 无关。
>
> **开关是 `-XX:+UseEpsilonGC`，级别 `EXPERIMENTAL`**（`gc/shared/gc_globals.hpp:115`：`product(bool, UseEpsilonGC, false, EXPERIMENTAL, "Use the Epsilon (no-op) garbage collector")`）。因此每次都要 **`-XX:+UnlockExperimentalVMOptions`**，否则 JVM 直接拒绝启动。Epsilon 的**全部 8 个专属 flag 也都是 `EXPERIMENTAL`**（`gc/epsilon/epsilon_globals.hpp`）。另外它是**构建期可裁剪的**：`gc/shared/gcConfig.cpp:59,69` 用 `EPSILONGC_ONLY(...)` 注册 `IncludedGC(UseEpsilonGC, CollectedHeap::Epsilon, epsilonArguments, "epsilon gc")`，未编入该 GC 的构建里连 flag 都不存在。
>
> ⚠️ **早期文章里的 `EpsilonMaxHeapSize` / `EpsilonExpandHeap` / `EpsilonInitialWait` 在 `jdk-27-ga` 全树 grep 零命中，已不存在**。堆上限直接用 `-Xmx`，扩展策略由 `EpsilonMinHeapExpand` 单参数控制，没有"初始等待"这类选项。
>
> **Epsilon 不使用卡表，也不安装任何写屏障**（详见 [Card Table](/docs/CS/Java/JDK/JVM/GC/CardTable.md)）：`gc/epsilon` 目录 grep `CardTable` 零命中，`EpsilonBarrierSet` 是空实现。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Enabling Epsilon

```bash
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -Xmx512m -Xlog:gc -jar app.jar
```

`-Xms` 决定一开始提交多少、`-Xmx` 决定预留多少（也是"能漏多少"的上限）。GC 的选择机制在 `gc/shared/gcConfig.cpp`：`IncludedGCs[]` 表把 **flag ↔ `CollectedHeap::Name` ↔ `GCArguments` 实例 ↔ hs_err 里显示的名字**（Epsilon 那行是 `"epsilon gc"`）绑在一起。如果构建里没编入 Epsilon，`GCConfig::fail_if_non_included_gc_is_selected()` 会用 `NOT_EPSILONGC(FAIL_IF_SELECTED(UseEpsilonGC))` 直接 `vm_exit_during_initialization("Option -XX:+UseEpsilonGC not supported")`——**报的是"not supported"而不是"unknown option"**，这是判断"JVM 构建有没有带 Epsilon"的最快信号。另外同一文件里的 `select_gc_ergonomically()` 只要 `INCLUDE_G1GC` 成立就把 G1 设为默认，所以不带 `-XX:+UseEpsilonGC` 时 Epsilon 永远不会被选中。

## The Heap Object

`EpsilonHeap : public CollectedHeap` 的全部状态就是**一个虚拟空间 + 一个连续空间**，没有代、没有 region、没有记忆集：

```cpp
class EpsilonHeap : public CollectedHeap {
  EpsilonMonitoringSupport* _monitoring_support;
  MemoryPool* _pool;
  GCMemoryManager _memory_manager;
  ContiguousSpace* _space;
  VirtualSpace _virtual_space;
  size_t _max_tlab_size;
  size_t _step_counter_update;
  size_t _step_heap_print;
  int64_t _decay_time_ns;
  Atomic<size_t> _last_counter_update;
  Atomic<size_t> _last_heap_print;
```

三个容量口径因此非常直白：

```cpp
  size_t max_capacity() const override { return _virtual_space.reserved_size();  }
  size_t capacity()     const override { return _virtual_space.committed_size(); }
  size_t used()         const override { return _space->used();                 }
```

`initialize()` 里最值得读的是"它把该做的都做了、但只有一遍"：

```cpp
jint EpsilonHeap::initialize() {
  size_t align = HeapAlignment;
  size_t init_byte_size = align_up(InitialHeapSize, align);
  size_t max_byte_size  = align_up(MaxHeapSize, align);

  // Initialize backing storage
  ReservedHeapSpace heap_rs = Universe::reserve_heap(max_byte_size, align);
  _virtual_space.initialize(heap_rs, init_byte_size);

  MemRegion committed_region((HeapWord*)_virtual_space.low(),          (HeapWord*)_virtual_space.high());

  initialize_reserved_region(heap_rs);

  _space = new ContiguousSpace();
  _space->initialize(committed_region, /* clear_space = */ true);

  // Precompute hot fields
  _max_tlab_size = MIN2(CollectedHeap::max_tlab_size(), align_object_size(EpsilonMaxTLABSize / HeapWordSize));
  _step_counter_update = MIN2<size_t>(max_byte_size / 16, EpsilonUpdateCountersStep);
  _step_heap_print = (EpsilonPrintHeapSteps == 0) ? SIZE_MAX : (max_byte_size / EpsilonPrintHeapSteps);
  _decay_time_ns = (int64_t) EpsilonTLABDecayTime * NANOSECS_PER_MILLISEC;

  // Enable monitoring
  _monitoring_support = new EpsilonMonitoringSupport(this);

  // Install barrier set
  BarrierSet::set_barrier_set(new EpsilonBarrierSet());

  // All done, print out the configuration
  EpsilonInitLogger::print();

  return JNI_OK;
}
```

`_step_counter_update` 取 `max_byte_size / 16` 与 `EpsilonUpdateCountersStep` 的**较小值**，即**步长最大只到堆的 1/16**——把 `EpsilonUpdateCountersStep` 调得再大，也不会让计数比"每用 1/16 堆刷一次"更稀疏；反之调小它确实能更频繁（直到 `min` 的另一侧）。这是"MXBean 看到的 used 会滞后一个步长"的根因。`EpsilonPrintHeapSteps = 0` 时 `_step_heap_print = SIZE_MAX`，等价于关闭分段打印。

## Allocation Path

真正的分配只有一条 bump-pointer 循环：`_space->par_allocate(size)` 失败就**在 `Heap_lock` 下扩展再重试**。

```cpp
HeapWord* EpsilonHeap::allocate_work(size_t size) {
  HeapWord* res = nullptr;
  while (true) {
    res = _space->par_allocate(size);
    if (res != nullptr) break;

    {
      MutexLocker ml(Heap_lock);
      res = _space->par_allocate(size);            // 可能别的线程已经扩展好了
      if (res != nullptr) break;

      size_t size_in_bytes = size * HeapWordSize;
      size_t uncommitted_space = max_capacity() - capacity();
      size_t unused_space = max_capacity() - used();
      size_t want_space = MAX2(size_in_bytes, EpsilonMinHeapExpand);

      if (want_space < uncommitted_space) {
        bool expand = _virtual_space.expand_by(want_space);       // 按整块扩展
      } else if (size_in_bytes < unused_space) {
        bool expand = _virtual_space.expand_by(uncommitted_space); // 把剩余全提交
      } else {
        return nullptr;                                            // 真的没空间了
      }

      _space->set_end((HeapWord *) _virtual_space.high());
    }
  }
  ...
}
```

三个分支对应三种语义：**正常时按 `max(请求, EpsilonMinHeapExpand)` 批量提交**（默认至少 128 MB 一步，避免频繁 `mmap`）；**接近 `Xmx` 时一次性提交剩余全部**；**只有当"已用 + 本次请求 ≥ 上限"才返回 `nullptr`**。

注意 `mem_allocate` 就是它的转发，慢路径没有额外逻辑：

```cpp
HeapWord* EpsilonHeap::mem_allocate(size_t size) { return allocate_work(size); }
HeapWord* EpsilonHeap::allocate_loaded_archive_space(size_t size) { return allocate_work(size); }
```

后一条配合 `can_load_archived_objects() { return true; }` 说明：**Epsilon 与 CDS / AOT 归档对象是兼容的**，归档里的对象可以正常落到这个连续空间。

分配成功后还有两个"按步长触发"的动作——刷 perf 计数、以及每 `_step_heap_print` 打一次堆/元空间水位：

```cpp
  size_t last_counter = _last_counter_update.load_relaxed();
  if ((used - last_counter >= _step_counter_update) &&
      _last_counter_update.compare_set(last_counter, used)) {
    if (_monitoring_support->is_ready()) {
      _monitoring_support->update_counters();
    }
  }
```

用 `compare_set` 而不是加锁，保证**多线程同时越界时只有一个线程去打印**——这是"分配热路径不能有任何锁"的具体落实。

## Barriers and Card Table Are Absent

`EpsilonBarrierSet` 的全部实现就是"空"：

```cpp
// No interaction with application is required for Epsilon, and therefore
// the barrier set is empty.
class EpsilonBarrierSet: public BarrierSet {
public:
  EpsilonBarrierSet();
  virtual void print_on(outputStream *st) const {}
  virtual void on_thread_create(Thread* thread);
  virtual void on_thread_destroy(Thread* thread);

  template <DecoratorSet decorators, typename BarrierSetT = EpsilonBarrierSet>
  class AccessBarrier: public BarrierSet::AccessBarrier<decorators, BarrierSetT> {};
};
```

```cpp
EpsilonBarrierSet::EpsilonBarrierSet() : BarrierSet(
          make_barrier_set_assembler<BarrierSetAssembler>(),
          make_barrier_set_c1<BarrierSetC1>(),
          make_barrier_set_c2<BarrierSetC2>(),
          nullptr /* barrier_set_nmethod */,
          nullptr /* barrier_set_stack_chunk */,
          BarrierSet::FakeRtti(BarrierSet::EpsilonBarrierSet)) {}
```

拆开看这意味着什么：

| 缺席的东西 | 后果 |
| :-- | :-- |
| 卡表 | 省下 `heap / GCCardSizeInBytes` 字节的常驻内存；也没有 `store_check` 指令 |
| 后屏障（card marking） | `putfield` / `aastore` 编译成**裸 store**，JIT 代码更小 |
| 前屏障（SATB 等） | 不存在并发标记，自然不需要记录旧值 |
| nmethod barrier / stack chunk barrier | 传的是 `nullptr`；`requires_barriers(stackChunkOop)` 直接 `return false`——**结构化并发的栈块无需任何屏障** |
| `BarrierSetAssembler` 特化 | 用基类，即解释器与 C1/C2 都走默认的"无屏障"代码路径 |
| GC 线程 | `void gc_threads_do(ThreadClosure* tc) const override {}` ——**不向 VM 注册任何 GC 线程**（枚举结果为空，hs_err 与线程遍历里都看不到它们） |

同一层"什么都不做"的实现还散落在 `EpsilonHeap.hpp` 里，它们共同界定了 Epsilon 能做什么诊断：

```cpp
  // Object pinning support: every object is implicitly pinned
  void pin_object(JavaThread* thread, oop obj) override { }
  void unpin_object(JavaThread* thread, oop obj) override { }

  // No support for block parsing.
  HeapWord* block_start(const void* addr) const { return nullptr;  }
  bool block_is_obj(const HeapWord* addr) const { return false; }

  // No nmethod handling
  void register_nmethod(nmethod* nm) override {}
  ...
  // No heap verification
  void prepare_for_verify() override {}
  void verify(VerifyOption option) override {}
```

对象**永不移动**，所以"钉住对象"是空操作（对追踪对象身份、把地址当线索来对齐日志非常友好）；但反过来说，**块解析（block starting）不支持、堆校验是空函数**，依赖这些能力的工具在 Epsilon 上拿不到数据。堆遍历仍可用 `object_iterate`（转发 `_space->object_iterate(cl)`）。

## Garbage Collection That Does Not Happen

`collect()` 是整个收集器最反直觉的一段——**它并非完全忽略所有 GC 请求**：

```cpp
void EpsilonHeap::collect(GCCause::Cause cause) {
  switch (cause) {
    case GCCause::_metadata_GC_threshold:
    case GCCause::_metadata_GC_clear_soft_refs:
      // Receiving these causes means the VM itself entered the safepoint for metadata collection.
      // While Epsilon does not do GC, it has to perform sizing adjustments, otherwise we would
      // re-enter the safepoint again very soon.

      assert(SafepointSynchronize::is_at_safepoint(), "Expected at safepoint");
      log_info(gc)("GC request for \"%s\" is handled", GCCause::to_string(cause));
      MetaspaceGC::compute_new_size();
      print_metaspace_info();
      break;
    default:
      log_info(gc)("GC request for \"%s\" is ignored", GCCause::to_string(cause));
  }
  _monitoring_support->update_counters();
}

void EpsilonHeap::do_full_collection(bool clear_all_soft_refs) {
  collect(gc_cause());
}
```

三条结论：

1. **`System.gc()`、`GC.request`、内存压力触发的普通 GC 全部被忽略**，只在 `-Xlog:gc` 里留一行 `GC request for "System.gc()" is ignored`。
2. **元空间相关的两种 cause 会被"处理"**——但不是回收，而是调 `MetaspaceGC::compute_new_size()` 重新调整元空间大小。注释解释得很清楚：VM 已经为了元空间收集进了安全点，Epsilon 必须顺手做尺寸调整，否则很快又会重新进入安全点。
3. 无论哪种情况都会 `_monitoring_support->update_counters()` 刷一次监控数据。

"仍然有安全点"这一事实直接决定了下面那条自动调整：Epsilon 只去掉**GC 引起**的安全点，去不掉反优化、类重定义、thread dump 等**非 GC 安全点**。

## Out of Memory Behavior

Epsilon **自己不抛异常**：`allocate_work` 在没空间时返回 `nullptr`，`OutOfMemoryError` 由 HotSpot 通用的分配失败路径抛出（与其他收集器同一条路）。

真正 Epsilon 特有的行为在参数初始化里：

```cpp
void EpsilonArguments::initialize() {
  GCArguments::initialize();

  assert(UseEpsilonGC, "Sanity");

  // Forcefully exit when OOME is detected. Nothing we can do at that point.
  if (FLAG_IS_DEFAULT(ExitOnOutOfMemoryError)) {
    FLAG_SET_DEFAULT(ExitOnOutOfMemoryError, true);
  }
  ...
}
```

也就是说：**默认情况下第一次 OOME 就会让进程退出**，因为"堆满了我们无能为力"。判断条件用的是 `FLAG_IS_DEFAULT`——**你显式写 `-XX:-ExitOnOutOfMemoryError` 就会被尊重**，此时行为回到常规的"抛 OOME 给应用处理"。

配套可用的通用 flag（定义在 `runtime/globals.hpp`）：

- `product(ccstrlist, OnOutOfMemoryError, "", "Run user-defined commands on first java.lang.OutOfMemoryError thrown from JVM")`（`:549`）——挂 dump / 告警脚本；
- `product(bool, HeapDumpOnOutOfMemoryError, false, MANAGEABLE, ...)`（`:566`）。

其余由 Epsilon 主动让路的调整：

```cpp
  if (EpsilonMaxTLABSize < MinTLABSize) {
    log_warning(gc)("EpsilonMaxTLABSize < MinTLABSize, adjusting it to %zu", MinTLABSize);
    EpsilonMaxTLABSize = MinTLABSize;
  }

  if (!EpsilonElasticTLAB && EpsilonElasticTLABDecay) {
    log_warning(gc)("Disabling EpsilonElasticTLABDecay because EpsilonElasticTLAB is disabled");
    FLAG_SET_DEFAULT(EpsilonElasticTLABDecay, false);
  }

#ifdef COMPILER2
  // Enable loop strip mining: there are still non-GC safepoints, no need to make it worse
  if (FLAG_IS_DEFAULT(UseCountedLoopSafepoints)) {
    FLAG_SET_DEFAULT(UseCountedLoopSafepoints, true);
    if (FLAG_IS_DEFAULT(LoopStripMiningIter)) {
      FLAG_SET_DEFAULT(LoopStripMiningIter, 1000);
    }
  }
#endif
```

三个要点：**`EpsilonMaxTLABSize` 会被抬到不低于全局 `MinTLABSize`**；**关掉弹性 TLAB 时衰减也自动失效**（否则无意义）；**C2 下默认打开计数循环安全点 + 每 1000 次迭代切一段**——因为长跑的紧循环仍要为反优化 / dump 等安全点留出可打断点。堆对齐与大小页也在这里定义：`conservative_max_heap_alignment()` 返回 `UseLargePages ? os::large_page_size() : os::vm_page_size()`，`initialize_alignments()` 把 `SpaceAlignment` / `HeapAlignment` 设为 `MAX2(os::vm_allocation_granularity(), page_size)`。

## TLAB and the Elastic Policy

Epsilon 的性能几乎全部来自 TLAB（线程本地分配缓冲），而它的特色是**弹性 TLAB**：线程按需把 TLAB 尺寸**逐步放大**，长时间不分配则**退回 0**。

```cpp
HeapWord* EpsilonHeap::allocate_new_tlab(size_t min_size,
                                         size_t requested_size,
                                         size_t* actual_size) {
  Thread* thread = Thread::current();
  bool fits = true;
  size_t size = requested_size;
  size_t ergo_tlab = requested_size;
  int64_t time = 0;

  if (EpsilonElasticTLAB) {
    ergo_tlab = EpsilonThreadLocalData::ergo_tlab_size(thread);

    if (EpsilonElasticTLABDecay) {
      int64_t last_time = EpsilonThreadLocalData::last_tlab_time(thread);
      time = (int64_t) os::javaTimeNanos();
      // If the thread had not allocated recently, retract the ergonomic size.
      if (last_time != 0 && (time - last_time > _decay_time_ns)) {
        ergo_tlab = 0;
        EpsilonThreadLocalData::set_ergo_tlab_size(thread, 0);
      }
    }

    fits = (requested_size <= ergo_tlab);
    if (!fits) {
      size = (size_t) (ergo_tlab * EpsilonTLABElasticity);
    }
  }

  size = clamp(size, min_size, _max_tlab_size);
  size = align_up(size, MinObjAlignment);
  ...
  HeapWord* res = allocate_work(size);
  if (res != nullptr) {
    *actual_size = size;
    if (EpsilonElasticTLABDecay) {
      EpsilonThreadLocalData::set_last_tlab_time(thread, time);
    }
    if (EpsilonElasticTLAB && !fits) {
      EpsilonThreadLocalData::set_ergo_tlab_size(thread, size);   // 记住新的尺寸
    }
  } else {
    if (EpsilonElasticTLAB) {
      EpsilonThreadLocalData::set_ergo_tlab_size(thread, 0);      // 失败则重来
    }
  }
  return res;
}
```

放大是**乘法而不是加倍**：`EpsilonTLABElasticity = 1.1`，即每次不满足就涨 10%，`0 → 0` 时靠 `clamp(size, min_size, ...)` 兜底到 `min_size`。线程态只有两个字段，挂在 `Thread::gc_data<T>()` 上（`EpsilonThreadLocalData`），由 barrier set 的 `on_thread_create` / `on_thread_destroy` 构造与析构：

```cpp
class EpsilonThreadLocalData {
  size_t _ergo_tlab_size;
  int64_t _last_tlab_time;
```

代价与收益的取舍写在 flag 描述里：更大 TLAB 更快但每线程浪费更多（未用完的 TLAB 空间永远拿不回来，因为不回收）；`EpsilonTLABElasticity` 调高提升性能、调低省内存。`-Xlog:gc=trace` 会打印决策过程：`TLAB size for "<thread>" (Requested: ..K, Min: ..K, Max: ..K, Ergo: ..K) -> ..K`。TLAB 的通用机制见 [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)。

## Flag Reference

`gc/epsilon/epsilon_globals.hpp` 的全部 8 个 flag，**级别清一色 `EXPERIMENTAL`**：

| Flag | 类型 | 默认值 | range | 作用 |
| :-- | :-- | :-- | :-- | :-- |
| `EpsilonPrintHeapSteps` | `size_t` | `20` | `0 ~ max_intx` | 把堆水位分成几步打印，`0` 关闭 |
| `EpsilonUpdateCountersStep` | `size_t` | `1 * M` | `1 ~ max_intx` | 每分配多少字节刷一次堆计数；调大更快但计数更粗，步长上限是堆的 1/16 |
| `EpsilonMaxTLABSize` | `size_t` | `4 * M` | `1 ~ max_intx` | TLAB 上限（字节），并与 `CollectedHeap::max_tlab_size()` 取小 |
| `EpsilonElasticTLAB` | `bool` | `true` | — | 是否按线程行为弹性放大 TLAB |
| `EpsilonElasticTLABDecay` | `bool` | `true` | — | 长时间不分配则收缩回 0（依赖上一项为 true） |
| `EpsilonTLABElasticity` | `double` | `1.1` | `1.0 ~ DBL_MAX` | 下一档 TLAB = 当前 × 该系数 |
| `EpsilonTLABDecayTime` | `size_t` | `1000` | `1 ~ max_intx` | 衰减判定的空闲时长，**单位毫秒** |
| `EpsilonMinHeapExpand` | `size_t` | `128 * M` | `1 ~ max_intx` | 每次堆扩展的最小步长（字节） |

外加 `gc/shared/gc_globals.hpp:115` 的 `UseEpsilonGC`（`bool` / `false` / `EXPERIMENTAL`），以及直接复用的通用堆参数 `-Xms` / `-Xmx` / `UseLargePages` / `MinTLABSize` / `UseTLAB`。

## What Epsilon Is Good For

| 场景 | 为什么合适 | 关键参数 |
| :-- | :-- | :-- |
| 一次性短命进程（CLI、构建插件、初始化脚本） | 进程在堆填满前就退出，GC 纯属浪费；且**不创建 GC 线程** | `-Xmx` 给足 + 默认即可 |
| 微基准与性能实验 | 隔离掉 GC 因素，测出"分配 + JIT + 应用逻辑"的下界，用来归因 GC 开销 | `EpsilonUpdateCountersStep` 调大减少干扰 |
| 内存泄漏复现与定量测量 | 占用单调增长、无压缩、无搬迁，**水位曲线就是泄漏曲线** | `EpsilonPrintHeapSteps`、`-Xlog:gc` |
| 验证"某条路径真的在分配" | 任何多余分配都会直接推高水位甚至 OOME，无法被 GC 悄悄擦掉 | 配合 `-Xlog:gc=trace` 看 TLAB 决策 |
| 对象身份调试 | 地址稳定（`pin_object` 空实现，永不移动） | — |
| 追求极致吞吐与最小代码体积 | 无写屏障 → 裸 store、无卡表内存 | — |

## What Epsilon Is Not For

| 场景 | 为什么不行 |
| :-- | :-- |
| 任何长期运行的服务 | 堆只增不减，必然 OOME（且默认直接退出进程） |
| 需要 `SoftReference` / `WeakHashMap` 语义正确性的负载 | 可达性变化只由分配决定，不回收意味着这些引用不会被清理，堆压力反而更高 |
| 依赖 Cleaner / finalizer 释放**非堆**资源 | 这些回调由回收时的引用处理驱动，Epsilon 不触发；非堆资源照样泄漏 |
| 需要 Full GC 兜底或 `-XX:+VerifyBeforeGC` 之类的堆校验 | `verify()` / `prepare_for_verify()` 是空函数 |
| 生产环境的"性能优化手段" | EXPERIMENTAL 级别本身就是免责声明；收益远小于风险 |

## Monitoring and Diagnostics

Epsilon 把监控做得比"什么都不做"这个印象充分得多，因为它必须让自己可被观测：

```cpp
void EpsilonHeap::initialize_serviceability() {
  _pool = new EpsilonMemoryPool(this);
  _memory_manager.add_pool(_pool);
}
```

即 **一个 `GCMemoryManager`（构造参数就是 `"Epsilon Heap"`）+ 一个内存池**，`memory_managers()` / `memory_pools()` 各自只返回这一项——这解释了 JMX 里看到的 `MemoryMXBean` 只有单个堆池、没有代池。

perf 计数由 `EpsilonMonitoringSupport` 建立：`EpsilonGenerationCounters("Heap", 1, 1, 0, max_capacity, capacity)` 与 `EpsilonSpaceCounters("Heap", 0, ...)`，在 `UsePerfData` 打开时注册 `capacity` / `used` / `maxCapacity` / `initCapacity`，`update_counters()` 顺带调 `MemoryService::track_memory_usage()` 与 `MetaspaceCounters::update_performance_counters()`。注意 `update_counters()` 开头 `assert(is_ready(), "Must be ready")`，而 `_ready` 要到 `post_initialize()` 里 `mark_ready()` 才置位——所以热路径上先判 `is_ready()` 再刷。

堆水位的打印格式（`log_info(gc)`）：

```cpp
    log_info(gc)("Heap: %zu%s reserved, %zu%s (%.2f%%) committed, "
                 "%zu%s (%.2f%%) used", ...);
```

元空间对应 `log_info(gc, metaspace)("Metaspace: ...")`，用 `MetaspaceUtils::get_combined_statistics()` 取 reserved / committed / used。`print_tracing_info()`（异步日志与崩溃诊断会用到）则一次性打印两者。`jcmd <pid> GC.heap_info` 走的是 `print_heap_on()`，输出 `Epsilon Heap` + 虚拟空间 + 分配空间三段。

常用观测命令：

```bash
# 每一步的堆水位（默认 20 步）
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -Xmx1g -Xlog:gc=info -jar app.jar

# TLAB 决策过程
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -Xlog:gc=trace -version

# 关掉分段打印（该 flag 是 size_t，用 0 关闭，不是 -XX:- 形式）
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -XX:EpsilonPrintHeapSteps=0 -jar app.jar

# 关闭"OOME 即退出"，让应用自己捕获
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -XX:-ExitOnOutOfMemoryError ...
```

> [!WARNING]
> `EpsilonPrintHeapSteps` 是 `size_t` 而非布尔开关，**关闭写法是 `-XX:EpsilonPrintHeapSteps=0`**，`-XX:-EpsilonPrintHeapSteps` 会被当作非法布尔语法。所有 Epsilon 专属 flag 都必须先 `-XX:+UnlockExperimentalVMOptions`。

## Pitfalls

- **默认 OOME 即退出**：这是最容易被忽略的行为改变，脚本若依赖捕获 `OutOfMemoryError` 后降级运行，必须显式 `-XX:-ExitOnOutOfMemoryError`。
- **计数是"步长触发"的**：`used` 在 MXBean / perf 上最多滞后一个步长（默认 `EpsilonUpdateCountersStep` = 1 MB，且步长不会超过堆的 1/16）；精确测量要用 `EpsilonPrintHeapSteps` 的分段日志，而不是轮询 JMX。
- **扩展只增不减**：`allocate_work` 里只有 `expand_by`，没有任何 uncommit 路径，committed 单调上升。
- **仍需要安全点**：`UseCountedLoopSafepoints` 被默认打开，说明 Epsilon 不是"没有停顿"，只是没有 GC 停顿。
- **诊断能力有缺口**：无块解析、无堆校验、无 nmethod 注册，部分依赖它们的工具拿不到数据。
- **`EpsilonMinHeapExpand` 默认 128 MB**：小堆（如 `-Xmx64m`）下第一步就会把剩余全部提交，看似"瞬间吃满 RSS"，这是设计使然而非异常。

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [Card Table](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)
- [JMH](/docs/CS/Java/JDK/JVM/JMH.md)

## References

- [JEP 318: Epsilon: A No-Op Garbage Collector (Experimental)](https://openjdk.org/jeps/318)
- [JDK 11](https://openjdk.org/projects/jdk/11/)
