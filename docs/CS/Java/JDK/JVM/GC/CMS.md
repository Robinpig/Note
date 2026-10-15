## Introduction

> [!WARNING]
>
> **CMS 已被移除，本篇仅作历史与源码阅读材料。**
>
> - **JEP 291**（Release **9**）弃用 CMS：`-XX:+UseConcMarkSweepGC` 开始打印弃用警告。
> - **JEP 363**（Release **14**）**移除** CMS：HotSpot 源码树中整个 `gc/cms` 目录被删除。此后在命令行传 `-XX:+UseConcMarkSweepGC` 只会得到警告然后**回退到默认收集器继续运行**——不是报错退出，容易被忽略。
>
> 迁移路径：G1 是官方指定继任者，低延迟大堆可选 ZGC 或 Shenandoah。本文描述的并发模式失败、浮动垃圾、i-cms 等机制在现役收集器中已无对应实现。

CMS（Concurrent Mark Sweep）是 HotSpot 家族中**首个把并发引入生产**的收集器（JDK 5），也是**第一个被整体移除**的收集器（JDK 14，JEP 363）。它面向"偏好更短 GC 暂停、且能承受 GC 与应用并发共享处理器资源"的应用——典型受益者是大老年代、多处理器服务端。

CMS 通过**单独的 GC 线程与应用线程并发地追踪可达对象**来降低 major 收集的暂停。CMS 只负责老年代（Old GC）；年轻代回收由 ParNew（并行）以 STW 方式完成。每个 major 周期有 **两次 STW 暂停**（Initial Mark + Remark）和 **两次并发阶段**（Concurrent Mark + Concurrent Sweep）。

### Collector Evolution 演进位置

在 HotSpot 收集器家族中，CMS 是 Serial → Parallel → **CMS → G1 → ZGC/Shenandoah** 这条演进链中的关键中间态：

| 收集器 | 核心特征 | 缺陷 |
| --- | --- | --- |
| Serial | 单线程 STW | 暂停时间随堆增长 |
| Parallel | 多线程 STW，换吞吐量 | 同左 |
| **CMS**（过渡） | **并发标记-清除**，换低延迟，但留结构性缺陷 | 碎片 + 浮动垃圾 + CMF |
| G1 | Region 化 + STW evacuation | 仍是 STW 疏散 |
| Shenandoah / ZGC | **并发重定位**，暂停与堆解耦 | 维护成本较高 |

CMS 设计是过渡性的——增量更新 + 标记-清除天生无法解决浮动垃圾 → CMF 的缺陷链。

### GC Cycle 四阶段

CMS 的 major 周期（老年代）：

```
Initial Mark（STW，暂停短）
    ├─ 扫描 GC Roots（young→old 晋升对象 + Roots）
    │
    ▼
Concurrent Mark（并发）
    ├─ 用**增量更新**追踪整个老年代对象图
    ├─ CMS 独有：Concurrent Precleaning（Remark 前处理最脏的卡）
    │
    ▼
Remark（STW，暂停最长）
    ├─ 重扫脏卡 + 重新扫 Roots 补漏 + flush 内部队列
    │
    ▼
Concurrent Sweep（并发）
    └─ 回收所有未标记为可达的老年代对象 → 分段空闲链表
```

每个周期两次 STW。CMS 尝试把 Remark 暂停安排在两次 young GC 之间的**大致中点**，避免叠加暂停。Initial Mark 通常远短于 Remark，不做调度。

### Key Design Choice：Incremental Update

CMS 用**增量更新（incremental update）**做并发标记——与 G1/Shenandoah/ZGC 的 SATB（Snapshot-At-The-Beginning）是 HotSpot 并发标记的两大流派。差异贯穿 CMS 的整个缺陷链：

| 维度 | CMS 增量更新 | G1/Shenandoah/ZGC SATB |
| --- | --- | --- |
| 写屏障记录方向 | **新值**（`x.f = y` 后把 `y` 入标记队列） | **旧值**（`x.f = y` 前把旧值入 SATB 队列） |
| 浮动垃圾 | **会产生**（标记期间变不可达的对象不取消标记） | **不会**（快照保证） |
| 并发重定位兼容 | **不兼容**（引用变更追踪不完整） | **兼容**（快照不变性 + load/store barrier） |
| 详细分析 | [CMS Incremental Update](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md) | [G1 Concurrent Marking](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md) |

## Knowledge Map

CMS 已拆分为 3 篇独立笔记，覆盖 CMS 独有的三个核心概念。阅读顺序建议：**IncrementalUpdate → ConcurrentModeFailure → Removal**。

### Incremental Update

**CMS 独有的并发标记正确性策略：增量更新 vs SATB、write barrier 原理、浮动垃圾来源。**

- 增量更新原理：记录**新值**（黑对象 → 白对象），与 SATB（记录旧值，快照保证）对比
- 双色标记、Concurrent Mark 全流程（Initial → Mark → Remark → Sweep）
- Remark STW 三数据源（脏卡重扫 + Roots 补漏 + CMS 内部队列 flush）
- **为什么增量更新不兼容并发重定位**（直接导致 CMS 无法做 evacuation）
- 浮动垃圾详解：数量估计、与 CMS 标记-清除的耦合

👉 [**跳转 → CMS/IncrementalUpdate.md**](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md)

### Concurrent Mode Failure

**CMS 独有的退化机制：CMF 触发条件、Full GC fallback 路径、与 G1 Evacuation Failure 的本质差异。**

- CMF 触发检测点：老年代分配失败 + CMS 周期正在进行 + 非 STW 阶段
- Fallback 路径：**完全放弃 CMS** → `Serial Old` mark-compact（暂停随堆大小增长）
- Initiating Occupancy 阈值（默认 92%）+ SafetyFactor（1.1）经验公式
- CMF vs Concurrent Mode Interruption（外部强制中断）
- **与 G1 Evacuation Failure 对比**（G1 就地晋升，不放弃自身逻辑）
- **与 Shenandoah/ZGC 退化对比**（Degenerated GC / Emergency Collection 都不放弃自身逻辑）

👉 [**跳转 → CMS/ConcurrentModeFailure.md**](/docs/CS/Java/JDK/JVM/GC/CMS/ConcurrentModeFailure.md)

### Removal

**JEP 291/363 时间线、四大结构性缺陷、继任者 G1/ZGC/Shenandoah 各自解决了什么。**

- JDK 5（2004）引入 → JDK 9 弃用（JEP 291）→ JDK 14 移除（JEP 363）
- **四大缺陷深度展开**：不压缩 → 碎片 + 大对象 OOM；浮动垃圾 → CMF；CPU 占用高；与 ParNew 紧耦合 + 维护成本
- JEP 363 的移除范围：编译时删除 `gc/cms/`、运行时选项忽略回退默认
- 迁移路径：CMS → G1（一般场景）/ ZGC 或 Shenandoah（低延迟 + 大堆）

👉 [**跳转 → CMS/Removal.md**](/docs/CS/Java/JDK/JVM/GC/CMS/Removal.md)

## Pros, Cons and Fitness

| 维度 | 说明 |
| --- | --- |
| 主要优势 | 相对更短的 major 暂停（标记/清除并发）；HotSpot 首个并发收集器，建立"两次 STW + 两次并发"设计范式 |
| 主要缺点 | 内存碎片、浮动垃圾、CMF 退化为 Full GC、CPU 占用高、无法并发重定位 |
| 最佳场景 | **仅限历史参考**；JDK 14 之前、堆中等、对延迟敏感、多处理器服务 |
| 关键限制 | JDK 14 起彻底移除（JEP 363），不可再用；必须配合 ParNew（`UseParNewGC`），不支持替代新生代收集器 |
| 新生代搭档 | 必须配合 ParNew（JDK 8 + CMS 的标准用法：`-XX:+UseConcMarkSweepGC` 隐含 `-XX:+UseParNewGC`） |

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [CMS Incremental Update（增量更新 + SATB 对比 + 浮动垃圾）](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md)
- [CMS Concurrent Mode Failure（CMF 退化机制）](/docs/CS/Java/JDK/JVM/GC/CMS/ConcurrentModeFailure.md)
- [CMS Removal（JEP 291/363 + 四大缺陷）](/docs/CS/Java/JDK/JVM/GC/CMS/Removal.md)
- [G1 Garbage Collector（CMS 继任者）](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [ZGC（并发重定位解决了 CMS 的碎片问题）](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [Shenandoah（并发重定位 + Brooks pointer）](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)

## References

1. [Concurrent Mark Sweep (CMS) Collector](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html) — Oracle Java 8 官方文档
2. [JEP 291: Deprecate CMS](https://openjdk.org/jeps/291)
3. [JEP 363: Remove CMS](https://openjdk.org/jeps/363)
4. [Pirinen: Incremental Update Marking](https://dl.acm.org/doi/10.1145/3061659.3061667) — 增量更新正确性论文
5. [Wilson: Garbage Collection Considered Harmful](https://dl.acm.org/doi/10.1145/60974.60978) — 写屏障方向对并发标记的影响
