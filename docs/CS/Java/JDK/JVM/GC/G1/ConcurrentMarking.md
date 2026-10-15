## Concurrent Marking

G1 标记使用一种称为 Snapshot-At-The-Beginning（SATB）的算法。
它在 Initial Mark 停顿之时对堆做一次虚拟快照——在标记开始时存活的所有对象在标记的剩余过程中都被视为存活。
这意味着在标记期间变为垃圾（不可达）的对象，出于空间回收的目的仍被视为存活（有一些例外）。
与其他收集器相比，这可能导致额外内存被错误保留。但 SATB 在 Remark 停顿期间可能提供更好的延迟。
在这次标记中被过于保守地视为存活的对象，会在下次标记期间被回收。

### Marking Data Structures

我们维护两个标记 bitmap，分别标记为 previous 和 next。
previous marking bitmap 是上次标记已完成的 bitmap。
next marking bitmap 可能正在构建中。
随着标记完成，两个物理 bitmap 会交换逻辑角色。
每个 bitmap 中，每个可能是对象起始地址的位置对应一位。
默认 8 字节对象对齐的情况下，这意味着每 64 个 heap bits 对应 1 个 bitmap 位。
我们使用 mark stack 来保存（部分）灰色对象（已标记但尚未递归扫描的对象）。

### Initial Marking Pause/Concurrent Marking

标记周期的第一阶段清空 next marking bitmap。此操作并发执行。
接下来，initial marking pause 停止所有 mutator 线程，标记所有从 roots 直接可达的对象（在分代模式下，initial marking 实际上附带在一次 full young evacuation pause 上执行）。
每个 heap region 包含两个 top at mark start（TAMS）变量，一个用于 previous marking，一个用于 next。
我们将它们分别称为 previous 和 next TAMS 变量。
这些变量用于识别标记阶段期间分配的对象。
这些位于 TAMS 值之上的对象，相对于 TAMS 变量对应的标记被视为隐式标记，但分配不会因标记 bitmap 更新而减慢。
initial marking pause 遍历堆中的所有 region，将每个 region 中 top 的当前值复制到该 region 的 next TAMS 中。
图 2 中的步骤 A 和 D 说明了这一点。
图中的步骤 B 和 E 表明，并发标记期间分配的对象位于 next TAMS 值之上，因此被视为存活。
（bitmap 在物理上覆盖整个堆，但仅显示与它们相关的 region 部分。）

现在 mutator 线程重新启动，标记的并发阶段开始。
此阶段与并发标记阶段非常相似：一个 "finger" 指针遍历 marked bits。
位于 finger 之上的对象是隐式灰色的；finger 之下的灰色对象用 mark stack 表示。

mutator 在收集器追踪指针图时可能正在更新它。
这种变更可能会在 "快照" 对象图中移除指针，违反 SATB 标记所基于的保证。
因此，SATB 标记要求 mutator 线程在覆盖指针字段之前记录其值。
下面展示了将 rY 中的值写入 rX 地址对象中偏移量 FieldOffset 的字段时，标记写屏障的伪代码。
其操作说明如下。

```
1| rTmp := load(rThread + MarkingInProgressOffset)
2| if (!rTmp) goto filtered
3| rTmp := load(rX + FieldOffset)
4| if (rTmp == null) goto filtered
5| call satb_enqueue(rTmp)
6| filtered:
```

实际的指针存储 [rX, FieldOffset] := rY 会紧随其后。
屏障的前两行在标记未进行时跳过剩余部分；对于许多程序，这会过滤掉大部分动态执行的屏障。
第 3、4 行加载对象字段中的值，并检查其是否为 null。只需记录非 null 值。
在许多程序中，大部分指针写入是对之前为 null 的字段的初始化写入，因此这种进一步过滤非常有效。
satb enqueue 操作将指针值添加到线程的当前 marking buffer 中。
与 remembered set buffer 类似，如果入队填满了 buffer，则将其添加到全局已完成 marking buffer 集合中。
并发标记线程定期检查此集合的大小，中断堆遍历以处理已填充的 buffer。

> [Use single mark bitmap in G1](https://bugs.openjdk.org/browse/JDK-8210708)

### Concurrent Marking Finger Algorithm: `do_marking_step` Deep Dive

上文只提了"finger 指针遍历 marked bits"一句话，这里展开 G1 并发标记的**核心循环**。G1 的并发标记不是简单的 DFS——它同时用 **bitmap（finger 扫描）** 和 **mark stack（栈式 DFS）** 两种机制表示灰度对象，并与 SATB 队列、TAMS 隐式标记、YGC evacuation 并发交互。

#### 为什么需要两种灰度表示

在三色标记中，"灰对象" 是关键——自身已标记但子引用还没扫完。G1 选择了两种表示方式：

| 灰度表示 | 存储形式 | 优点 | 缺点 |
| :--- | :--- | :--- | :--- |
| **below-finger gray** | mark stack（`G1CMTask` 内部的 oop 栈） | 精确、快速处理 | 栈容量有限，GC worker 线程间需要窃取 |
| **above-finger gray** | marking bitmap（finger 指针之后的所有 marked bits） | bitmap 可无限扩展 | 遍历 bitmap 找对象需要解析标记位 |

finger 把 bitmap 切成两半：**finger 之前的已标记对象要么全黑（子引用已扫完）要么在 mark stack 中等待继续处理；finger 之后的所有 marked 对象都是灰的（等待被扫）**。

#### 核心循环：`G1CMTask::do_marking_step`

这是 G1 并发标记线程（`G1CMConcurrentMarkingTask`）每个 worker 的核心方法，在一个设定的时间片（`G1ConcMarkStepDurationMillis`，默认 10ms）内尽可能多标记：

```cpp
// src/hotspot/share/gc/g1/g1CMTask.cpp（简化核心循环）
void G1CMTask::do_marking_step(double target_time_ms,
                                bool do_termination, bool is_serial) {
  Ticks start = Ticks::now();
  double time_limit_ms = 10.0;  // G1ConcMarkStepDurationMillis
  // 1. 先 drain SATB 队列（mutator 写屏障记录的旧引用）
  //    这保证了 SATB 正确性：所有被覆盖的旧引用都被补扫
  drain_satb_buffers();
  
  // 2. 主循环：交替处理 mark stack 和 bitmap
  while (elapsed_time_ms < time_limit_ms) {
    // 2a. 优先处理 mark stack 中的对象
    if (!_mark_stack.is_empty()) {
      oop obj = _mark_stack.pop();
      // 递归扫描 obj 的子引用
      obj->oop_iterate(_mark_closure);
      // 如果 obj 有子引用不在 bitmap 的 above-finger 区，
      // push 到 _mark_stack 等待下次迭代
    }
    
    // 2b. mark stack 空了 → 用 finger 扫描 bitmap
    if (!_marking_finger.move_to_next_marked_bit()) {
      // bitmap 扫完了 → 标记 terminator 让所有 worker 同步
      _has_aborted = false;
      return;  // 结束这次 step
    }
    // 找到了一个 marked bit → 对应的对象是 above-finger gray
    oop obj = _marking_finger.current_obj();
    // 把它 push 到 mark stack，下次迭代时递归处理
    _mark_stack.push(obj);
  }
  
  // 3. 时间片用完 → 检查 SATB 队列大小，决定要不要中断
  if (_satb_overflow) {
    // SATB 队列积压太多，先 drain SATB 再继续
    drain_satb_buffers();
  }
}
```

#### SATB 队列 drain 的两种触发方式

SATB 队列中的内容来自 mutator 线程的写屏障——每次引用字段被覆盖前，旧值被 enqueue 到线程本地的 SATB buffer。SATB buffer 满了就进全局 `G1SATBMarkQueueSet`。

drain 时机：

```
方式 1：do_marking_step 开头立即 drain
  → 保证 SATB 正确性优先

方式 2：SATB 队列 overflow 时中断 mark loop
  → SATB 队列积压过多会让 Remark pause 变长
  → G1 定期检查 _satb_overflow 标志
```

drain 的逻辑很直接——把 SATB buffer 中的每个对象当作灰度对象处理（标记它的子引用），相当于把 SATB 写屏障记录的"旧值"补扫一遍。

#### TAMS 的隐式标记：新分配对象自动存活

在 Initial Mark 暂停中，G1 把每个 region 的 `top` 保存到 `next_tams`。**TAMS 以上的对象（marking 开始后新分配的）自动视为活对象，不需要在 marking bitmap 中置位**。

机制：

```cpp
// Initial Mark 暂停中
for (HeapRegion* hr : all_regions) {
  hr->save_prev_top_to_next_tams();  // next_tams = hr->top()
}
// mutator 继续运行，新分配的对象都在 next_tams 之上
// GC worker 标记时：
if (obj_address >= hr->next_tams()) {
  // 隐式标记，跳过 bitmap 置位
  // 但仍然要扫描它的子引用（子引用可能在 TAMS 以下）
}
```

TAMS 的好处：**新分配对象的标记是零成本的**——写屏障不会因为新对象的出现而额外置位。代价是新对象的所有子引用都会被保守地扫描一遍（因为子引用可能指向 TAMS 以下的旧对象）。

#### Evacuation 与 Marking 的并发交互

标记进行期间可能触发 Young GC / Mixed GC（evacuation pause），这会改变堆的状态。关键点：

1. **Evacuation 不处理 "next marking" 的 bitmap**：evacuation 期间标记线程仍然在跑。evacuation 移动对象时，只调整当前 evacuation 所需的引用关系，不碰并发标记线程正在扫描的对象。

2. **TAMS 在 evacuation 后会增加**：如果 evacuation 把更多对象搬到某个 region 并分配到了新地址，region 的 `top` 会升高。evacuation pause 结束后，**新的 top 会被复制到 next_tams**，这样新搬来的对象也算"隐式标记"。

3. **Marking Stack 被当作额外的 GC Root**：evacuation pause 开始时，GC worker 线程先 join 标记的 terminator（让标记线程暂停），然后把所有 worker 的 mark stack 里的对象当作 CSet 的根——这些对象可能已经在 CSet 里，evacuation 时需要正确处理它们的转发指针。

4. **Concurrent Mark 终止条件**：标记完成需要同时满足三个条件：

```
do_marking_step 中检查：
  !_marking_finger.has_more_marked_bits()  // bitmap 扫完了
  && _marking_stack.is_empty()             // mark stack 空了
  && !_satb_queue.has_unprocessed_entries()  // SATB 队列 drain 完了
```

三个条件同时满足后，标记线程设置 `has_aborted() = false`，触发 Remark pause。

#### Concurrent Marking 的完整阶段

从 `phase_clear_cld_claimed_marks` 到 `phase_cleanup`，并发标记周期的 7 个阶段：

```
G1ConcurrentMarkThread::concurrent_mark_cycle_do()
  │
  ├── phase_clear_cld_claimed_marks()     // 1. 清理上次标记残留
  │   └── SystemDictionary::unlink()
  │
  ├── phase_scan_root_regions()            // 2. 扫描 root regions（survivor + archive）
  │   └── G1CMRootRegionScanTask (并行)
  │   // ⚠️ 必须在所有 evacuation 之前完成，YGC 会 wait
  │
  ├── phase_mark_loop()                    // 3. 主循环：do_marking_step
  │   └── G1CMConcurrentMarkingTask (并行)
  │       └── do_marking_step(10ms, ...)  // 上面展开的核心逻辑
  │
  ├── phase_rebuild_remembered_sets()     // 4. 重建 RSet（Remark 与 Cleanup 之间）
  │   └── G1UpdateRemSetTask (并行)
  │
  ├── phase_delay_to_keep_mmu_before_cleanup() // 5. MMU 节流
  │   // 如果 GC 时间占比太高，等 mutator 先跑一会儿
  │
  ├── phase_cleanup()                      // 6. STW pause：选择 CSet 候选
  │   └── VM_G1Concurrent → CMCleanup
  │
  └── phase_clear_bitmap_for_next_mark()   // 7. 为下次标记清空 next bitmap
      // （实际上是交换 previous/next 的角色）
```

注意 **阶段 2（scan_root_regions）必须在阶段 3（mark_loop）之前**。YGC pause 开始时会调用 `wait_for_root_region_scanning()`——如果 root region 扫描还没结束，YGC 必须等标记线程扫完。这是 correctness 的硬约束：root region 是 survivor regions，YGC 的 evacuate 会处理这些对象，但如果标记线程还没扫完它们，YGC 可能会把标记中途的对象搬到新位置而没通知标记线程。

### Final Marking Pause

标记阶段在以下条件下完成：并发标记遍历了所有已标记对象，完全清空了 mark stack，并且所有记录的更新都已处理完毕。
前一个条件容易检测；后一个较难，因为 mutator 线程 "拥有" log buffers 直到它们被填满。
STW final marking pause 的目的是在所有 mutator 线程停止时可靠地达到此终止条件。
它非常简单：任何未处理的已完成 log buffers 如上所述处理，部分完成的每线程 buffer 以相同方式处理。
此过程并行执行，以防有许多 mutator 线程且它们的 marking log buffer 部分填充，导致长停顿时间或并行扩展问题。

### Live Data Counting and Cleanup

并发标记还会统计每个 heap region 中已标记数据的数量。
最初，这作为标记过程的一部分来完成。
但移动存活对象的 evacuation pause 也必须更新每个 region 的存活数据计数。
当 evacuation pause 并行执行，且多个线程将对象疏散到同一 region 时，一致更新此计数可能成为并行争用的来源。
虽然有多种技术可以缓解此扩展问题，但即使只有单线程，更新计数也占 evacuation pause 成本的很大比例。因此，我们决定并发执行所有存活数据统计。
final marking 完成后，GC 线程重新检查每个 region，统计与标记关联的 TAMS 值之下的已标记数据字节数。
这有点像 sweeping 阶段，但注意我们通过检查 marking bitmap 来查找存活对象，而不是遍历垃圾对象。

标记期间发生的 evacuation pause 可能会增加某些 heap region 的 next TAMS 值。
因此，需要最终的 STW cleanup pause 来可靠地完成此计数过程。
此 cleanup 阶段还以其他几种方式完成标记。
就在这时，next 和 previous bitmap 交换角色：新完成的 bitmap 变成 previous bitmap，旧的可供下次标记使用。
此外，由于标记完成，每个 region 的 next TAMS 字段中的值被复制到 previous TAMS 字段，如图 2 中的步骤 C 和 F 所示。
存活对象查询依赖于 previous marking bitmap 和 previous TAMS，因此新完成的标记信息现在将用于确定对象存活状态。
在图 2 中，浅灰色表示已知为垃圾的对象。
步骤 D 和 E 展示了已完成标记的结果如何在新标记进行中使用。

最后，cleanup 阶段按预期 GC 效率对 heap region 排序。
此指标将通过回收 region 可回收的垃圾量除以回收该 region 的成本。
此成本基于多种因素估算，包括疏散存活数据的估计成本和遍历 region 记忆集的成本。
排序结果是 region 纳入 collection set 的初始优先级排序。
成本估算可能随时间变化，因此此估算只是初始的。

完全没有存活数据的 region 在此阶段立即回收。
对于某些程序，这种方法可以回收相当大比例的总垃圾。

### Evacuation Pauses and Marking

首先，evacuation pause 永远不会疏散在最后一次完成的标记中已被证明为垃圾的对象。
由于对象是垃圾的，它显然不会被 roots 引用，但可能被其他垃圾对象引用。
collection set 内的引用仅在引用对象被发现为存活时才被追踪。
collection set 之外的引用由记忆集识别；如果记忆集识别出的对象已被证明为垃圾，则它们会被忽略。
其次，当我们在 evacuation pause 中疏散对象时，我们需要确保它相对于 previous 和 next 标记都被正确标记（如需要）。
事实证明这非常微妙且棘手。
不幸的是，由于篇幅限制，我们无法在此给出这种交互的所有细节。

我们允许在标记线程的 mark stack 非空时发生 evacuation pause：如果不这样做，标记可能会无限延迟所需的 evacuation pause。
mark stack 条目可能引用 collection set 中的对象。
由于这些对象在当前标记中被标记，它们相对于 previous 标记显然是存活的，并且可能被 evacuation pause 疏散。
为了确保 mark stack 条目被正确更新，我们将 mark stack 视为根来源。
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Mixed GC（依赖标记结果的 CSet 候选选择）](/docs/CS/Java/JDK/JVM/GC/G1/MixedGC.md)
- [G1 Evacuation（与 evacuation 并发交互）](/docs/CS/Java/JDK/JVM/GC/G1/Evacuation.md)
- [G1 Predictions（IHOP 自适应决定何时启动标记）](/docs/CS/Java/JDK/JVM/GC/G1/Predictions.md)

## References

- [G1ConcurrentMark Source (openjdk.org)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/g1/g1ConcurrentMark.cpp)
- [SATB Paper — Yu-Ting Chen](https://www.researchgate.net/publication/2528287_Snapshot-at-the-Beginning_Mark-Sweep-Garbage_Collection)
