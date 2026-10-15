## Heap

G1的堆空间管理与JVM之前常用的串行、并行、CMS等垃圾回收算法有很大的区别。串行、并行、CMS中，堆空间是连续的，或者粗粒度的划分为新生代（eden / survivor）、老年代、永久代
随着计算机硬件的发展，服务器堆内存越来越大，旧时代的垃圾回收算法处理大堆时，性能较差且停顿（STW）时间不可控。
G1将堆拆分成一系列的分区（Heap Region），这样垃圾回收算法在大部分场景下仅需处理一部分HR，而不是整个老年代。极大的提升了收集效率，并使得JVM可以精细控制STW的时间

### Region

G1 将堆划分为一系列大小相等的 Heap Region，每个 region 是一段连续的虚拟内存范围，如图 1 所示。Region 是 G1 内存分配与内存回收的基本单位。任一时刻，region 要么空闲（浅灰色），要么被分配到某个分代——年轻代或老年代。当应用发起内存分配请求时，内存管理器从 free list 拿出空闲 region，分配到对应分代，再把这块空间交给应用自行分配。

<div style="text-align: center;">

![zHeap Layout](../img/G1-Heap-Layout.png)

</div>

<p style="text-align: center;">
图 1：G1 垃圾回收器堆布局
</p>

我们对 heap region 类型的值进行编码，以便快速确定所属分代。
标签分为两部分：

- major type（young, old, humongous） ：高 N-1 位
- minor type（eden / survivor, starts / cont hum 等） ：低 1 位

如果未来需要增加 minor type 的数量，就需要增加后者的位数，相应减少前者的位数。

G1的分区类型大概可以分为5类：
* 可用分区 FHR
* 新生代分区 YHR，细分为eden分区和survivor分区
* 大对象分区 HHR，细分为大对象头分区和大对象连续分区，当对象size超过region_size一半时，即被认为是大对象
* 老年代分区 OHR
* 归档分区 AHR，细分为开放归档分区和关闭归档分区，区别在于是否允许引用堆外对象

```cpp
//
// 00000 0 [ 0] Free
//
// 00001 0 [ 2] Young Mask
// 00001 0 [ 2] Eden
// 00001 1 [ 3] Survivor
//
// 00010 0 [ 4] Humongous Mask
// 00010 0 [ 4] Starts Humongous
// 00010 1 [ 5] Continues Humongous
//
// 00100 0 [ 8] Old Mask
// 00100 0 [ 8] Old
//
```

### Region Lifecycle State Machine

Region 不是静态分配的——它在不同角色之间动态流转。从 free list 到最终归还，一个 region 可能经历下面的状态序列：

```
                    alloc_region()     GC cycle end
  Free ──────────────────────→ Eden ──────────────→ Survivor
  ↑                                                │
  │                                                │ GC cycle end
  │                          promotion             ↓
  │                                          Old ────────→ Free (evacuation)
  │                                            │
  │  humongous allocation                      │ Cleanup phase
  ↓                                            ↓
  Free ──→ Starts Humongous ──→ Continues Humongous ──→ Free
  ↑
  │  archive time
  └──────── Archive (Open/Closed)
```

**关键转换点**：

| 转换 | 触发者 | 机制 |
| :--- | :--- | :--- |
| Free → Eden | TLAB 分配时 Eden 用尽 | `HeapRegionManager::allocate_young_region()` 从 young free list 取 |
| Eden → Survivor | YGC 结束 | evacuation pause 内把 survivor 复制进新 region，旧 eden 清空归 Free |
| Survivor → Old | 对象晋升 / Survivor 过老 | `copy_to_survivor_space` 中 age ≥ MaxTenuringThreshold 时对象进 old region（不是 region 本身转）；evacuation failure 时整个 survivor region 晋升 |
| Old → Free | Mixed GC / Full GC | evacuation / compaction 清空存活对象后，region 加入 free list |
| Free → Humongous | 分配 > 0.5 × region_size 的对象 | 连续 Free regions 合并为 Starts + N 个 Continues |
| Humongous → Free | Cleanup 阶段检测到没人引用 | `HeapRegion::set_humongous_is_live()` 未被置位 |
| Free → Archive | CDS 归档时 | `G1ArchiveAllocator` 保留只读 region |

**注意**：Region 状态转换与 region 类型编码（line 97-111 的 bit flag）是独立的——编码决定"当前是什么"，生命周期决定"怎么变"。

### HeapRegionManager: Core Data Structures

所有 region 的分配、回收、迭代都经过 `HeapRegionManager`。它维护三个关键结构：

#### 两层索引表

```
G1HeapRegionTable _regions  (全堆 region 的二级索引)
  ├── _regions[chunk_index]        (一级：chunk 指针)
  │     └── chunk->_base
  │           └── chunk->_regions[local_index]  (二级：HeapRegion* 数组)
  │
  └── 堆地址 → region 的映射：
      region_index = (addr - heap_bottom) / region_size
      chunk_idx = region_index >> _log2_region_size
      local_idx = region_index & _region_size_mask
      return _regions[chunk_idx]->_regions[local_idx]
```

为什么两级？G1 heap 最大可以到 32TB（`max_jint × HeapWordSize`），直接用一个巨大数组会导致 TLB miss。分 chunk 可以按需按需分配二级数组（`G1HeapRegionTable::initialize` 惰性初始化）。

#### Free List 管理

`HeapRegionManager` 维护三个并行的 free region 列表：

```
young_free_list    // Eden/Survivor 分配用（G1EdenRegions / G1SurvivorRegions 会从这里取）
old_free_list      // Mixed GC / Full GC 疏散目标
humongous_free_list // humongous 对象分配时需要连续 region，这里单独维护
```

**合并机制**：free list 中的 region 如果物理相邻，`HeapRegionManager::allocate_*_region()` 可以返回连续的一组——这就是 humongous 对象能够被分配的原因。`HeapRegionManager::get_sequence()` 会扫描 free list 找到一段连续 region。

#### Region 迭代器

G1 的很多遍历（evacuation、marking、compaction）需要并行遍历所有 region。`HeapRegionManager::heap_region_par_iterate_from_worker_offset()` 用 **linear scan + claimed bit** 实现多线程安全迭代：

```
每个 worker 从自己的 offset 开始
  → 检查 HeapRegion::_claimed 位（CAS 竞争）
  → claim 成功则处理这个 region
  → 否则跳过（其他 worker 已 claim）
  → 继续线性推进直到遍历完
```

这避免了显式的工作窃取队列——region 数组本身就是天然的"工作队列"。

#### Retirement：动态调整 young gen 大小

G1 有个冷门但重要的机制——**retired regions**。当 heap 需要缩小时（`MinHeapFreeRatio` 触发），G1 不能直接把 region 归还给 OS（因为可能有存活对象），而是先 retire：

```
HeapRegion::retire()
  → 标记 _retired = true
  → 从所有 free list 移除
  → 不再参与任何分配或 GC
```

Retired regions 最终在 Full GC 后被实际释放（如果 compaction 把所有存活对象搬走了），或者在下一次 heap resize 时被重新激活。

年轻代包含 eden region（红色）和 survivor region（红色带"S"标记）。
这些 region 与其他收集器中对应的连续空间功能相同，区别在于 G1 中这些 region 在内存中通常以非连续方式布局。
老年代由 old region（浅蓝色）组成。老年代 region 可能是大对象 region（浅蓝色带"H"标记），用于存放跨越多个 region 的对象。

heap region 内的分配通过递增已分配空间和未分配空间之间的边界 top 来实现。
始终有一个 region 作为当前分配 region，从中分配存储。
由于我们主要面向多处理器场景，mutator 线程仅通过线程本地分配缓冲区（TLAB）直接在 heap region 中分配，使用比较并交换（CAS）操作。
然后它们在这些缓冲区中私下分配对象，以最小化分配竞争。
当当前分配 region 被填满时，会选择新的分配 region。空 region 组织成链表，使得 region 分配成为常数时间操作。
较大对象可以直接在当前分配 region 中分配，在 TLAB 之外。
但尺寸超过 heap region 大小 3/4 的对象被称为大对象（humongous）。



HR的大小影响分配和回收的效率，HR过大则回收消费的时间长，HR过小则导致对象内存分配较慢且内存利用率较低。
HR大小上下限定义在heapRegionBounds中，最小1MB，最大32MB。HR的size必须是2的幂次，即仅可为1MB、2MB、4MB、8MB、16MB、32MB。
JVM参数-XX:G1HeapRegionSize可以指定HR size
计算HR size的逻辑主要在setup_heap_region_size函数中







每个 region 都关联一个记忆集（remembered set），它指示所有可能包含指向该 region 内（存活）对象指针的位置。
维护这些记忆集要求 mutator 线程在进行可能产生跨 region 指针的指针修改时通知收集器。
这个通知使用卡表（card table）：堆中每 512 字节的 card 映射到卡表中的一个一字节条目。
每个线程都关联一个记忆集日志（remembered set log），即当前缓冲区或修改过的 card 序列。
此外，还有一个全局的已填充 RS 缓冲区集合。

记忆集本身是 card 的集合（用哈希表表示）。
实际上，由于并行性，每个 region 关联多个这样的哈希表组成的数组，每个并行 GC 线程一个，以允许这些线程无干扰地更新记忆集。
记忆集的逻辑内容是各组成哈希表所代表集合的并集。
记忆集写屏障在指针写入之后执行。
如果代码执行指针写入 x.f = y，且寄存器 rX 和 rY 分别包含对象指针值 x 和 y，那么屏障的伪代码如下：

```
1| rTmp := rX XOR rY
2| rTmp := rTmp >> LogOfHeapRegionSize
3| // Below is a conditional move instr
4| rTmp := (rY == NULL) then 0 else rTmp
5| if (rTmp == 0) goto filtered
6| call rs_enqueue(rX)
7| filtered:
```

这个屏障使用了 Stefanovi´c 等人简要提到的过滤技术。
如果写入创建的是同一 heap region 内对象之间的指针（这是常见情况），则无需记录在记忆集中。
第 1、2 行的异或和移位操作意味着如果 x 和 y 在同一 heap region 内，rTmp 在第 2 行之后为零。
第 4 行添加了对 null 指针存储的过滤。
如果存储通过了这些过滤检查，则它创建了跨 region 指针。
rs enqueue 例程读取对象头 rX 的卡表条目。
如果该条目已经是脏的，则不做任何处理。
这减少了对同一 card 多次存储的工作量——这种情况常见于初始化写入。
如果卡表条目不是脏的，则将其标脏，并将指向 card 的指针入队到线程的记忆集日志中。
如果这次入队填满了线程的当前日志缓冲区（默认存放 256 个元素），则该缓冲区放入全局已填充缓冲区集合中，并分配新的空缓冲区。

并发记忆集线程等待（在条件变量上）已填充 RS 缓冲区集合的大小达到可配置的启动阈值（默认 5 个缓冲区）。
记忆集线程将已填充缓冲区作为队列处理，直到队列长度降至启动阈值的 1/4。
对于每个缓冲区，它处理每个卡表指针条目。
有些 card 是热点：它们包含被频繁写入的位置。
为了避免重复处理热点 card，我们尝试识别最热的 card，并将其处理推迟到下一次疏散停顿。
我们通过第二个卡表来实现这一点，它记录自上次疏散停顿以来 card 被标脏的次数（在此停顿期间，此表与卡表本身一样被清空）。
处理 card 时我们递增其在此表中的计数。
如果计数超过热度阈值（默认 4），则 card 被加入称为热队列（hot queue）的环形缓冲区中（默认大小 1 K）。
该队列在每次疏散停顿开始时像日志缓冲区一样处理，因此在结束时为空。
如果环形缓冲区已满，则另一端的 card 会被驱逐并处理。

因此，并发记忆集线程在以下情况下处理 card：card 尚未达到热度阈值，或 card 从热队列中被驱逐。
处理 card 时，线程首先将相应的卡表条目重置为干净值，以便对 card 上对象的任何并发修改都会重新标脏并入队 card。
然后它检查其修改可能已经标脏该 card 的所有对象的指针字段，寻找包含对象所在 heap region 之外的指针。
如果找到这样的指针，则将 card 插入被引用 region 的记忆集中。

我们仅使用单个并发记忆集线程，以在有空闲处理器时引入并行性。
但如果此线程不足以处理变更速率，则已填充 RS 缓冲区集合会变得过大。
我们限制此集合的大小；尝试添加更多缓冲区的 mutator 线程会自行执行记忆集处理。

-XX:ParallelGCThreads

默认 2048 个 Region

可使用 -XX:+G1HeapRegionSize 指定，但建议使用默认值

Young 默认 堆大小的 5%，建议不超过 60%

-XX:G1NewSizePercent -XX:G1MaxNewSizePercent

Eden : survivor1: survivor2 = 8: 1: 1 保持不变

大对象 超过半个 region 大小

可预测停顿 

-XX:MaxGCPauseMillis=value

### Heap Sizing

G1 在调整 Java 堆大小时遵循标准规则，使用 `-XX:InitialHeapSize` 作为 Java 堆最小大小，`-XX:MaxHeapSize` 作为 Java 堆最大大小，
`-XX:MinHeapFreeRatio` 用于确定调整后的最小空闲内存百分比，`-XX:MaxHeapFreeRatio` 用于确定调整后的最大空闲内存百分比。
G1 收集器仅在 Remark 和 Full GC 停顿期间根据这些选项考虑调整 Java 堆大小。
此过程可能向操作系统释放内存或从操作系统分配内存。

> [!NOTE]
> **JDK 27 默认值变化（[JDK-8238686](https://bugs.openjdk.org/browse/JDK-8238686)）**：G1 将 `-XX:MinHeapFreeRatio` 和 `-XX:MaxHeapFreeRatio` 的默认值分别从 **40 / 70** 改为 **0 / 100**。改动后这两个参数默认不再影响 G1 堆伸缩逻辑，只有用户显式设置时才生效。旧默认值在 Full GC 后可能触发不必要的堆扩展或收缩，新默认让 G1 更纯粹地按容量目标（`-Xms` / `-Xmx`）运行。

堆扩展在回收停顿内发生，而内存释放在停顿结束后与应用并发执行。

#### Young-Only Phase Generation Sizing

G1 始终在正常 young collection 结束时为下一个 mutator 阶段确定年轻代大小。
这样，G1 可以基于对实际停顿时间的长期观察，满足通过 -XX:MaxGCPauseTimeMillis 和 -XX:GCPauseIntervalMillis 设定的停顿时间目标。
此计算会考虑相似大小的年轻代需要多长时间完成疏散。
这包括回收期间需要复制多少对象、以及这些对象之间相互关联的紧密程度等信息。

-XX:GCPauseIntervalMillis 和 -XX:MaxGCPauseTimeMillis 选项定义了最小 mutator 利用率（MMU）。
G1 会尝试在每个可能的 -XX:GCPauseIntervalMillis 时间范围内，垃圾回收停顿总计最多使用 -XX:MaxGCPauseTimeMillis 毫秒。

如果没有其他约束，G1 会在 -XX:G1NewSizePercent 和 -XX:G1MaxNewSizePercent 确定的值之间自适应调整年轻代大小以满足停顿时间。
关于如何修复长时间停顿的更多信息，请参见 Garbage-First Garbage Collector Tuning。

另外，也可以使用 -XX:NewSize 配合 -XX:MaxNewSize 分别设置年轻代的最小和最大大小。

> [!NOTE]
>
> 仅指定这后两个选项之一会将年轻代大小固定为 -XX:NewSize 和 -XX:MaxNewSize 分别传入的确切值。这会禁用停顿时间控制。

#### Space-Reclamation Phase Generation Sizing

在空间回收阶段，G1 试图在单次垃圾回收停顿中最大化老年代回收的空间量。年轻代大小通常设置为允许的最小值，通常由 -XX:G1NewSizePercent 确定，但也会考虑 MMU 规范。

在此阶段的每次 mixed collection 开始时，G1 从 collection set 候选中选择一组 region 加入 collection set。这组额外的老年代 region 由三部分组成：

- 一组最小的老年代 region，确保疏散进度。
  这组老年代 region 的数量由 collection set 候选中的 region 数量除以 Space-Reclamation 阶段的长度（由 -XX:G1MixedGCCountTarget 确定）来决定。
- 如果 G1 预测在完成最小集合回收后还有剩余时间，则从 collection set 候选中添加额外的老年代 region。
  老年代 region 会被不断添加，直到预计剩余时间的 80% 会被用完。
- 一组可选的 collection set region，在另外两部分完成疏散且本停顿中还有剩余时间时，G1 增量式地疏散这些 region。

前两组 region 在初始回收遍历中被回收，可选 collection set 中的额外 region 会被安排到剩余的停顿时间内。
这种方法确保了空间回收进度，同时提高了保持停顿时间的概率，并最小化了可选 collection set 管理带来的开销。

当 collection set 候选 region 集合中不再有 region 时，Space-Reclamation 阶段结束。

#### Periodic Garbage Collections

如果由于应用长时间不活跃而没有进行垃圾回收，VM 可能长时间持有大量闲置内存，这些内存本可用于其他地方。
为避免这种情况，可以使用 -XX:G1PeriodicGCInterval 选项强制 G1 定期执行垃圾回收。
此选项确定 G1 考虑执行垃圾回收的最小间隔（毫秒）。
如果自从上次垃圾回收停顿以来已过了这段时间且没有正在进行的并发周期，G1 会触发额外的垃圾回收，可能产生以下效果：

在 Young-Only 阶段：G1 通过 Concurrent Start 停顿启动并发标记，或者如果指定了 -XX:-G1PeriodicGCInvokesConcurrent，则触发 Full GC。
在 Space Reclamation 阶段：G1 继续空间回收阶段，触发与当前进度相适应的垃圾回收停顿类型。
-XX:G1PeriodicGCSystemLoadThreshold 选项可用于细化是否触发垃圾回收：如果 JVM 宿主系统（例如容器）上 getloadavg() 调用返回的一分钟平均系统负载值高于此值，则不会运行定期垃圾回收。

#### Determining Initiating Heap Occupancy

启动堆占用百分比（Initiating Heap Occupancy Percent，IHOP）是触发 Concurrent Start 回收的阈值，它定义为老年代大小的百分比。

G1 默认通过观察标记需要多长时间以及标记周期内老年代通常分配多少内存来自动确定最优 IHOP。
此功能称为自适应 IHOP（Adaptive IHOP）。
如果此功能启用，那么只要没有足够的观测数据来准确预测 IHOP 阈值，-XX:InitiatingHeapOccupancyPercent 选项就会将初始值确定为当前老年代大小的百分比。
使用选项 -XX:-G1UseAdaptiveIHOP 关闭 G1 的此行为。在这种情况下，-XX:InitiatingHeapOccupancyPercent 的值始终决定此阈值。

在内部，自适应 IHOP 会尝试设置 IHOP，使得空间回收阶段的第一次 mixed garbage collection 在老年代占用达到当前最大老年代大小减去 -XX:G1HeapReservePercent 作为额外缓冲时开始。

#### Behavior in Very Tight Heap Situations

当应用保持存活的内存过多导致疏散无法找到足够的目标空间时，就会发生疏散失败（evacuation failure）。
疏散失败意味着 G1 试图完成当前的垃圾回收：保持已经移动到新位置的对象不动，不复制尚未移动的对象，只调整对象之间的引用。
疏散失败可能会带来一些额外开销，但通常应该与其他 young collection 一样快。
在发生疏散失败的这次垃圾回收之后，G1 会正常恢复应用执行，不采取任何其他措施。
G1 假设疏散失败发生在垃圾回收接近尾声时；也就是说，大多数对象已经移动完毕，应用有足够的空间继续运行，直到标记完成并开始空间回收。

如果此假设不成立，G1 最终会安排一次 Full GC。这种回收执行整个堆的原地压缩（in-place compaction），可能会非常慢。

G1 试图通过调度预防性 young collection（Preventive young collections）来避免 young collection 期间的疏散失败。
其假设是：不发生疏散失败的额外常规 young collection 可能通过回收大对象 region 来在老年代释放足够的内存，从而完全避免此类垃圾回收的开销。
预防性 young collection 可以使用 -XX:-UsePreventiveGC 选项关闭。

```cpp

  // Minimum region size; we won't go lower than that.
  // We might want to decrease this in the future, to deal with small
  // heaps a bit more efficiently.
  static const size_t MIN_REGION_SIZE = 1024 * 1024;

  // Maximum region size determined ergonomically.
  static const size_t MAX_ERGONOMICS_SIZE = 32 * 1024 * 1024;
  // Maximum region size; we don't go higher than that. There's a good
  // reason for having an upper bound. We don't want regions to get too
  // large, otherwise cleanup's effectiveness would decrease as there
  // will be fewer opportunities to find totally empty regions after
  // marking.
  static const size_t MAX_REGION_SIZE = 512 * 1024 * 1024;

  // The automatic region size calculation will try to have around this
  // many regions in the heap.
  static const size_t TARGET_REGION_NUMBER = 2048;

void HeapRegion::setup_heap_region_size(size_t max_heap_size) {
  size_t region_size = G1HeapRegionSize;
  // G1HeapRegionSize = 0 means decide ergonomically.
  if (region_size == 0) {
    region_size = clamp(max_heap_size / HeapRegionBounds::target_number(),
                        HeapRegionBounds::min_size(),
                        HeapRegionBounds::max_ergonomics_size());
  }

  // Make sure region size is a power of 2. Rounding up since this
  // is beneficial in most cases.
  region_size = round_up_power_of_2(region_size);
```

现在确保我们不会超出或低于限制。

1MB ~ 32MB

```cpp
  region_size = clamp(region_size, HeapRegionBounds::min_size(), HeapRegionBounds::max_size());

  // Calculate the log for the region size.
  int region_size_log = log2i_exact(region_size);

  // Now, set up the globals.
  guarantee(LogOfHRGrainBytes == 0, "we should only set it once");
  LogOfHRGrainBytes = region_size_log;

  guarantee(GrainBytes == 0, "we should only set it once");
  GrainBytes = region_size;

  guarantee(GrainWords == 0, "we should only set it once");
  GrainWords = GrainBytes >> LogHeapWordSize;

  guarantee(CardsPerRegion == 0, "we should only set it once");
  CardsPerRegion = GrainBytes >> G1CardTable::card_shift();

  LogCardsPerRegion = log2i(CardsPerRegion);

  if (G1HeapRegionSize != GrainBytes) {
    FLAG_SET_ERGO(G1HeapRegionSize, GrainBytes);
  }
}
```

### young size

- -XX:NewSize and -XX:MaxNewSize override -XX:NewRatio

```cpp

G1YoungGenSizer::G1YoungGenSizer() : _sizer_kind(SizerDefaults),
  _use_adaptive_sizing(true), _min_desired_young_length(0), _max_desired_young_length(0) {

  if (FLAG_IS_CMDLINE(NewRatio)) {
    if (FLAG_IS_CMDLINE(NewSize) || FLAG_IS_CMDLINE(MaxNewSize)) {
      log_warning(gc, ergo)("-XX:NewSize and -XX:MaxNewSize override -XX:NewRatio");
    } else {
      _sizer_kind = SizerNewRatio;
      _use_adaptive_sizing = false;
      return;
    }
  }

  if (NewSize > MaxNewSize) {
    if (FLAG_IS_CMDLINE(MaxNewSize)) {
      log_warning(gc, ergo)("NewSize (" SIZE_FORMAT "k) is greater than the MaxNewSize (" SIZE_FORMAT "k). "
                            "A new max generation size of " SIZE_FORMAT "k will be used.",
                            NewSize/K, MaxNewSize/K, NewSize/K);
    }
    FLAG_SET_ERGO(MaxNewSize, NewSize);
  }

  if (FLAG_IS_CMDLINE(NewSize)) {
    _min_desired_young_length = MAX2((uint) (NewSize / HeapRegion::GrainBytes),
                                     1U);
    if (FLAG_IS_CMDLINE(MaxNewSize)) {
      _max_desired_young_length =
                             MAX2((uint) (MaxNewSize / HeapRegion::GrainBytes),
                                  1U);
      _sizer_kind = SizerMaxAndNewSize;
      _use_adaptive_sizing = _min_desired_young_length != _max_desired_young_length;
    } else {
      _sizer_kind = SizerNewSizeOnly;
    }
  } else if (FLAG_IS_CMDLINE(MaxNewSize)) {
    _max_desired_young_length =
                             MAX2((uint) (MaxNewSize / HeapRegion::GrainBytes),
                                  1U);
    _sizer_kind = SizerMaxNewSizeOnly;
  }
}
```

### Humongous Objects

大对象是指大于或等于半个 region 大小的对象。
当前 region 大小通过 ergonomics 确定，如 G1 GC 的 Ergonomic Defaults 部分所述，除非通过 -XX:G1HeapRegionSize 选项设置。

这些大对象有时以特殊方式处理：

- 每个大对象都作为老年代中一串连续 region 分配。
  对象本身的起始位置始终位于该序列中第一个 region 的起始处。
  该序列中最后一个 region 的任何剩余空间在整个对象被回收之前都无法用于分配。
- 通常，大对象只能在标记结束的 Cleanup 停顿期间回收，或者如果它们变得不可达，则在 Full GC 期间回收。
  但对于大对象的 **eager reclamation** 有特殊规定：G1 会在任何 GC 停顿中机会性地回收那些不被很多对象引用的大对象。
  - **JDK 26 前（pre-[JDK-8048180](https://bugs.openjdk.org/browse/JDK-8048180)）**：仅基本类型数组（`bool`、各种整型、浮点型）可以被 eager reclaim——扫描这类对象的引用关系成本极低，GC pause 内就能判定它们是否真的不可达。
  - **JDK 26+**：含引用的 humongous 对象也能被 eager reclaim。实现上，GC pause 中会扫描这些对象的字段，沿引用向外追溯，只要确认它们不被任何 young gen region 或 survivor region 引用即可回收，无需等完整的并发标记周期结束。
  这个 eager reclaim 行为默认启用，可用 `-XX:G1EagerReclaimHumongousObjects` 控制。
- 分配大对象可能导致垃圾回收停顿过早发生。
  G1 在每次大对象分配时检查 IHOP 阈值，如果当前占用超过该阈值，可能会立即触发一次初始标记 young collection。
- 大对象永远不会被移动，即使在 Full GC 期间也不会。
  这可能因 region 空间碎片化而导致过早发生缓慢的 Full GC 或意外的内存溢出条件，即使有很多剩余空闲空间。

## Garbage Collection Cycle

从高层来看，G1 收集器在两个阶段之间交替。
young-only 阶段包含垃圾回收，会逐渐用老年代对象填满当前可用内存。
space-reclamation 阶段是 G1 除了处理年轻代之外，还增量式回收老年代空间的阶段。
然后周期以 young-only 阶段重新开始。

<div style="text-align: center;">

![Garbage Collection Cycle](../img/G1-GC-Cycle.png)

</div>

<p style="text-align: center;">
图 2：垃圾回收周期 
</p>

下列列表详细描述了 G1 垃圾回收周期的各个阶段、它们的停顿以及阶段之间的转换：

1. Young-only 阶段：此阶段以几次 Normal young collection 开始，将对象晋升到老年代。
   当老年代占用达到某个阈值——IHOP 阈值时，young-only 阶段和 space-reclamation 阶段之间的转换开始。
   此时，G1 会安排一次 Concurrent Start young collection 而不是 Normal young collection。

   - Concurrent Start：这种回收除了执行 Normal young collection 之外，还启动标记过程。
     并发标记确定所有当前可达（存活）的老年代 region 中的对象，以便后续的 space-reclamation 阶段保留它们。
     标记尚未完全完成时，可能会发生 Normal young collection。
     标记以两个特殊的 Stop-The-World（STW）停顿结束：Remark 和 Cleanup。
     <br>
     Concurrent Start 停顿可能还会确定不需要继续进行标记：在这种情况下，会发生短暂的并发标记撤销阶段，Young Only 阶段继续。
     这种情况下不会发生 Remark 和 Cleanup 停顿。
   - Remark：此停顿完成标记本身，执行引用处理和类卸载，回收完全空的 region，并清理内部数据结构。
     在 Remark 和 Cleanup 之间，G1 计算后续能够并发回收选中老年代 region 空闲空间所需的信息，这将在 Cleanup 停顿中最终确定。
   - Cleanup：此停顿确定是否真的会进入 space-reclamation 阶段。
     如果进入 space-reclamation 阶段，young-only 阶段以一次 Prepare Mixed young collection 结束。
2. Space-reclamation 阶段：此阶段由多次 young collection 组成，这些 collection 除了年轻代 region 之外，还疏散老年代 region 集合中的存活对象。
   这些回收也称为 Mixed collection。当 G1 确定继续疏散更多老年代 region 不会产生足够值得的空闲空间时，space-reclamation 阶段结束。

空间回收之后，回收周期以另一个 young-only 阶段重新开始。
作为兜底，如果应用在收集存活信息期间内存耗尽，G1 会像其他收集器一样执行一次原地 STW 全堆压缩（Full GC）。
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Predictions（停顿预测）](/docs/CS/Java/JDK/JVM/GC/G1/Predictions.md)
- [G1 RSet（记忆集与 Refinement）](/docs/CS/Java/JDK/JVM/GC/G1/RSet.md)
- [GC 全景](/docs/CS/Java/JDK/JVM/GC/GC.md)

## References

- [HotSpot HeapRegionManager Source (openjdk.org)](https://github.com/openjdk/jdk/tree/master/src/hotspot/share/gc/g1)
- [G1 Heap Sizing Policy — OpenJDK Wiki](https://wiki.openjdk.org/display/JDKUpdates/G1+Garbage+Collector)
