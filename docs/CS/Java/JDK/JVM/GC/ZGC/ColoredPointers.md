## Introduction

ZGC 的一个核心设计原则是 **将 colored object pointers（着色对象指针，即 colored oops）与 load barrier（读屏障）结合使用**——这是 ZGC 区别于所有其他 HotSpot GC 算法的根本特征。CMS 和 G1 标记的是对象本身，写屏障记录被覆盖的引用；ZGC 直接在对象指针里编码 GC 状态元数据，读屏障在每次引用加载时解析这些元数据。

着色指针方案带来了三个关键能力：

1. **并发重定位**：在 relocation 阶段，指向被回收/复用 Region 的指针可以"原地保留"，load barrier 在应用真正使用时才修正地址。这避免了写屏障必须跟踪所有 outgoing 引用的开销。
2. **无需 Full GC 专用 mark-compact**：由于地址自愈机制，ZGC 的常规回收周期就包含压缩，不需要像 G1 那样在 evacuation failure 时升级到 Full GC。
3. **通用元数据容器**：只要元数据能塞进 64-bit 指针的未使用位，load barrier 就能基于它执行任意动作。这为未来的异构内存追踪（把冷对象重定位到冷存储）等特性奠定了基础。

## Basic Concepts

所有存储在 Java 堆对象字段中的引用都是 **64-bit colored pointer**，其格式为：

```
63    ...    N          N-1    ...    0
┌──────────────────────┬────────────────┐
│  Address Bits        │  Metadata Bits │  ← Generational ZGC（元数据在低阶位）
└──────────────────────┴────────────────┘

63    ...    M          M-1    ...    0
┌──────────────────────┬────────────────┐
│  Metadata Bits       │  Address Bits  │  ← Non-Generational ZGC（元数据在高阶位）
└──────────────────────┴────────────────┘
```

- **Address Bits**：对象的虚拟地址，决定了支持的最大堆大小
- **Metadata Bits**：GC 编码的状态信息（GC 阶段、对象颜色、relocation 状态、代属等）

metadata bits 的数量和含义**随 GC 周期动态变化**——ZGC 在不同阶段（marking / remapping / relocation）为元数据位赋予不同语义。

### Colorless vs Colored Pointer

一个容易混淆的点：

- **堆对象字段中的引用** → colored pointer，带完整 metadata bits
- **JVM 栈 / CPU 寄存器中的引用** → colorless pointer，纯地址、**没有 metadata**

load barrier 和 store barrier 负责在 colored ↔ colorless 之间翻译。这也是为什么 colored pointer layout 可以设计得很奇特——栈和寄存器永远不直接持有 colored pointer，barrier 的翻译成本就是唯一约束。

## Non-Generational ZGC Layout

非分代 ZGC（JDK 11–22）把 metadata bits 放在**高阶位**（地址位在下半部分），并依赖 **multi-mapped memory（多视图映射）** 来压低 load barrier 的开销。

### Multi-Mapped Memory

Linux / x86_64 上，ZGC 把**同一段物理内存**同时 `mmap` 到**三个不同的虚拟地址范围**，每个视图有不同的访问权限：

| View | 用途 | 访问权限 |
| --- | --- | --- |
| Marked0 | GC 阶段 0 的标记视图 | READ + WRITE |
| Marked1 | GC 阶段 1 的标记视图 | READ + WRITE |
| Remapped | Relocation / Remapping 阶段 | READ ONLY（或按需） |

metadata bits 编码选择哪个视图：如果一个对象被标记在 Marked0，它的 colored pointer 的 metadata bits 就指向 Marked0 视图的虚拟地址区间。这样 load barrier 不需要显式检查"这个对象是否已被标记"，**虚拟地址空间本身就是标记状态的指示**——直接解引用，OS 会自动路由到正确的视图。

### 颜色状态机

非分代 ZGC 的 colored pointer 颜色状态（简化版）：

```
           并发标记开始                 并发标记结束          Remapping / Relocation 完成
对象地址 ──────────────► Marked0 ──────────────► Remapped ──────────────► Remapped（纯地址视图）
```

- **Unmarked → Marked0**：在 Pause Mark Start 中通过根扫描设置
- **Marked0 → Marked0 / Marked1**：并发标记线程推进时在两个颜色之间翻转（标记阶段用两个颜色位并行追踪不同标记 wavefront）
- **Marked → Remapped**：对象已被 remap 或 relocate，地址视图切换到 Remapped view
- **Remapped**：final 状态，load barrier 看到就直接返回，不再做任何处理

### 为什么 Multi-Mapping 有价值

load barrier 的 fast path 快到什么程度？**什么都不做**——如果虚拟地址落在正确的视图区间内，CPU 直接解引用就是正确结果。只有当对象需要处理时（颜色错了、指向要 relocate 的 region），slow path 才会介入。

### 代价

`ps` 等工具报告的堆内存是实际使用量的 ~3 倍（三个虚拟地址区间重叠同一段物理内存），容易让运维误判堆占。JEP 439 取消了 multi-mapping，消除了这个问题。

## Generational ZGC Layout (JEP 439)

分代 ZGC（JDK 21 引入，JDK 23 默认）对 colored pointer 做了两项根本性修改：**元数据移到低阶位** + **取消 multi-mapping**。

### Low-Order Metadata Bits

把 metadata bits 放在低阶位有几个好处：

1. **单条 shift 指令完成 fast path 检查**：在 x64 上，一个右移指令（`shr`）可以同时完成"检查是否需要处理"和"剥离元数据得到纯地址"。非分代布局需要 mask + shift 两条指令。
2. **支持更多 metadata bits**：取消了 multi-mapping 对 metadata 必须落在堆虚拟地址范围高位的约束，多出了可用 bit 位，可以编码代属信息、双代独立标记状态等。
3. **最大堆可超越 16 TB**：地址位不再受限于 44 位（低阶位设计下，地址位可以扩展到完整 64 - metadata bits）。

### 显式 Barrier 取代 Multi-Mapping

分代 ZGC 不再依赖虚拟地址视图来隐式表达颜色状态，而是让 **load/store barrier 显式检查 metadata bits**。这个变化的直接收益：

- `ps`、`top`、`smem` 等工具报告的堆内存不再是虚高的 3 倍
- 代码路径更可移植（multi-mapping 依赖 OS 支持，Solaris/SPARC 是硬件支持，Linux 纯软件）
- 更多 CPU 架构上 ZGC 的行为一致

但代价是 load barrier fast path 多了一条指令。JEP 439 用一系列优化弥补了这个损失（fused store barrier、barrier patching、store barrier buffer 等，详见 [Generational ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC/Generational.md)）。

## Metadata Bits Encoding

### Non-Generational ZGC (multi-mapping 隐式编码)

非分代 ZGC 的 metadata bits 与 multi-mapping 三个视图一一对应。以 x86_64 为例：

- Marked0 视图虚拟地址区间：`[M0_BASE, M0_BASE + HEAP_SIZE)`
- Marked1 视图虚拟地址区间：`[M1_BASE, M1_BASE + HEAP_SIZE)`
- Remapped 视图虚拟地址区间：`[R_BASE, R_BASE + HEAP_SIZE)`

metadata bits 的"值"实际上就是**虚拟地址落在哪个视图区间**。load barrier fast path 只需检查指针的高阶位，就能判断它属于哪个视图：

```cpp
// 伪代码
if ((addr & VIEW_MASK) == M0_BASE) { /* Marked0 */ }
if ((addr & VIEW_MASK) == M1_BASE) { /* Marked1 */ }
if ((addr & VIEW_MASK) == R_BASE)  { /* Remapped */ }
```

实际上由于 multi-mapping 让三个视图的**地址低 N 位（offset）完全相同**，fast path 的检查简化成：**指针是否落在 remapped 视图的地址区间内**？是 → 已经修复；否 → 还需要处理（slow path）。

### Generational ZGC (显式编码)

取消 multi-mapping 后，metadata bits 的含义完全变成显式位标记：

| Bit 位置（低阶） | 含义 |
| --- | --- |
| Bit 0 | **Color bit 0**：标记阶段 wavefront |
| Bit 1 | **Color bit 1**：标记阶段 wavefront（两位组合支持 4 种颜色状态） |
| Bit 2 | **Remapped flag**：对象已 remap / relocate，地址正确 |
| Bit 3 | **Old-gen flag**：对象属于 old generation |
| Bit 4 | **Young-gen flag**：对象属于 young generation（或可简化为 ~old-gen） |
| Bit 5+ | 保留给 future features（异构内存、堆访问追踪等） |

分代 ZGC 用**两个独立的 marking color（young / old 各一套）**，让两代可以独立回收。在同一次 major GC 中，young gen 和 old gen 的标记阶段完全解耦。

## Address Bits and Heap Size

address bits 的数量直接决定了 ZGC 支持的最大堆大小：

| 布局 | Address Bits | 理论最大堆 | 实测上限 |
| --- | --- | --- | --- |
| Non-Generational（x86_64） | ~42–44 | 4–16 TB | ~16 TB |
| Generational（x86_64） | ~44+ | 16 TB+ | 更大 |

metadata bits 数量随 GC 阶段和代属变化，通常占 8–20 位区间。由于现代 Linux x86_64 默认只给用户空间 47 位虚拟地址（128 TB），address bits 永远不会成为瓶颈。

## Why No CompressedOops

ZGC 不能与 CompressedOops（压缩普通对象指针）同时启用，原因很直接：

- CompressedOops 把 64-bit 堆对象引用压缩成 32-bit 偏移量，利用了"堆对齐到 8 bytes，所以最低 3 位恒为 0"的规律来塞入额外信息
- ZGC 的 colored pointer **已经利用了这些位来编码 GC 元数据**，两者的 bit 用途完全冲突
- 另外 CompressedOops 支持的最大堆是 **32 GB**，而 ZGC 的核心卖点是 **TB 级堆**——即使没有 bit 冲突，32 GB 也太小

这意味着使用 ZGC 的应用进程内存（Java 堆 + 元空间 + 直接内存）天然会比使用 G1/Parallel/CompressedOops 时更大。

## Links

- [ZGC 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [ZGC Load Barrier（self-healing 依赖 colored pointer）](/docs/CS/Java/JDK/JVM/GC/ZGC/LoadBarrier.md)
- [Shenandoah Brooks Pointer（对比：per-object extra word vs pointer metadata bits）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)
- [ZGC Generational（元数据 bit 布局变更）](/docs/CS/Java/JDK/JVM/GC/ZGC/Generational.md)

## References

1. [The Pauseless GC Algorithm](https://www.usenix.org/legacy/events/vee05/full_papers/p46-click.pdf) — ZGC 与 Azul Pauseless GC 的设计渊源
2. [Deep Dive into ZGC: A Modern Garbage Collector in OpenJDK](https://dl.acm.org/doi/pdf/10.1145/3538532) — ACM TOSEM 2022，详细的 ZGC 高层设计
3. [ZGC The Next Generation Low-Latency Garbage Collector](http://cr.openjdk.java.net/~pliden/slides/ZGC-OracleDevLive-2020.pdf) — Per Liden 在 OracleDevLive 的演讲
4. [OpenJDK16 ZGC 详细源码分析](https://heapdump.cn/article/3473288) — multi-mapping 源码级分析
5. [JEP 439: Generational ZGC](https://openjdk.org/jeps/439) — 分代 ZGC 对 colored pointer 布局的变更
6. [ZGC Wiki: Pointer Metadata using Multi-Mapped Memory](https://wiki.openjdk.org/display/zgc/Pointer+Metadata+using+Multi-Mapped+memory)
