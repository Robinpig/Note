## Introduction

Metaspace 是 JVM 用来存放**类元数据**（class metadata）的内存区域。所谓类元数据，就是一个 Java 类在 JVM 进程内的运行时表示——凡是 JVM 为了"使用"这个类所需要的信息几乎都在里面，包括但不限于：

- **Klass 结构**：`java.lang.Class` 在 VM 内部的运行时表示，附带 vtable 与 itable；
- **方法元数据**：class 文件里 `method_info` 的运行时等价物（ConstMethod），含字节码、异常表、局部变量表、参数信息等；
- **运行时常量池**（constant pool）；
- **注解**；
- **方法计数器**：JIT 编译决策所依赖的插桩数据（MDO / MDA）。

Metaspace 的分配与**类加载**是耦合的：一个类被加载、其运行时表示被构造时，由它所属的 ClassLoader 从 Metaspace 中分配空间存放这些元数据。分配给某个类的 Metaspace **归属于它的 ClassLoader**，只有当这个 ClassLoader 本身被卸载时才会释放；而且"释放"也不等于"归还操作系统"——空间可能仍留在 JVM 进程内，等待被后续类加载复用。

在 Metaspace 出现之前，这份工作是**永久代（PermGen）**做的。PermGen 在物理上紧挨着堆，回收时复用老年代算法。它上面主要放三类数据：类的运行时内部表示、类静态变量（class statics）、interned strings。从 JDK 7 起，永久代被有计划地掏空，三次迁移各有明确动机，构成一条因果链：

1. **Symbols → native memory**。符号表条目由 class 文件常量池驻留而来、生命周期跟随类而非堆上对象，把它们搬出堆/永久代，就不必在每次 GC 中扫描与整理这块几乎只增不减的内存；
2. **Interned strings → Java Heap**。`String.intern()` 的结果本来就是对象，放进堆才能被普通 GC（含弱引用处理）正常回收，避免永久代里字符串无限堆积；
3. **class statics → Java Heap**。静态字段可能持有堆上对象引用，放进堆后引用关系不再跨代、跨区扫描，语义也终于和"它就是普通对象字段"一致。

这三块搬完之后，PermGen 里剩下的只有类元数据本身。于是 **JDK 8 彻底移除永久代**，由 Metaspace 取而代之：类元数据改从本地内存分配，上限默认只受机器可用内存约束，可用 `-XX:MaxMetaspaceSize` 显式封顶。JDK 21+ 的对象头与类空间问题（压缩类指针的退役）见下文 Version Baseline。

三个分工只需一句话：**Klass 与 oop 的二分**（`A.class` 是堆上的 `java.lang.Class` 实例，Klass 在 Metaspace）见 [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)；类加载的完整流程见 [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)；Symbols 的具体去向与驻留机制见 [SymbolTable](/docs/CS/Java/JDK/JVM/SymbolTable.md)。

## Version Baseline

> [!NOTE]
> 本篇以 **JDK 27 / HotSpot 主线源码**（jdk-27-ga）为准，三件最容易写错的事：
>
> 1. **`-XX:MetaspaceReclaimPolicy` 已 obsolete**。它在 `runtime/arguments.cpp:539` 的 obsolete 表中（`obsolete_in = JDK 21`），JDK 21 起不再是可配项，新文章不应再把它当调优开关推荐；回收策略已收敛为单一的自适应行为。
> 2. **`UseCompressedClassPointers` 在 JDK 25 deprecated、JDK 27 obsolete**（`runtime/arguments.cpp:544`），不再是可用开关；但 **compressed class space 本身仍在**（`CompressedClassSpaceSize` 依然有效，见 `runtime/globals.hpp:1385`），且 JDK 27 默认启用紧凑对象头后 narrowKlass 进入 markWord，对 Klass 的地址空间反而提出了更强约束（见 [Object_Header](/docs/CS/Java/JDK/JVM/Object_Header.md)）。
> 3. **chunk 分级制度换过代**。老文章里的四级 chunk（specialized / small / medium / humongous）是 JDK 8–11 的 ChunkManager 设计；当前源码里这些名字已完全不存在（在 `share/memory/metaspace/` 下 grep 无匹配），取而代之的是 16MB → 1K 的**十五级二分 chunk 树**与 RootChunkArea 管理（见下文）。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Class Space and Non-Class Space

Metaspace 在逻辑上分成两半：

| 分区 | 放什么 | 形态 | 大小控制 |
| :-- | :-- | :-- | :-- |
| **Class Space** | 只放 `Klass*` 对象。Klass 是**定长**结构，后随变长的 vtable / itable 与极小的 OopMap | 一块**连续**的虚拟保留区（compressed class space），64 位平台默认 1G **reserve**（并非 commit） | `-XX:CompressedClassSpaceSize`，默认 `1*G`，range `1*M ~ 4*G`（`runtime/globals.hpp:1385`） |
| **Non-Class Space** | 方法元数据（ConstMethod / MDO）、常量池、注解等一切其他元数据 | 由多块不连续的内存组成，从本地内存分配 | 无独立上限，与 Class Space 共同受 `MaxMetaspaceSize` 约束 |

两分法的动机是压缩类指针：narrowKlass 只有 32 位，必须保证所有 Klass 落在一个可寻址的连续窗口内。**JDK 27 的一个关键版本事实**：紧凑对象头（JEP 534，默认开启）把 narrowKlass 直接塞进 markWord，因此 Klass 必须保持在有限地址窗口内，这一约束由 Object_Header.md 展开，此处不重复。

32 位平台没有 class space：`ClassLoaderMetaspace` 的注释明确写着"32-bit: A CLD owns just one MetaspaceArena"（`memory/classLoaderMetaspace.hpp:62-65`），`_class_space_arena` 在 32 位下为 null。老资料里"-XX:-UseCompressedClassPointers 时 Klass 也存 Non-Class Space"的说法在 JDK 27 已无从配置（见 Version Baseline 第 2 条）。

## Four-Layer Allocation Architecture

Metaspace 的实现是分层的：**最底层向 OS 大块 reserve、按需 commit；中间层把大块切成 metachunk 分发给各 ClassLoader；最上层由 arena 把 chunk 切给调用方**。以下按这四层展开。

```
Metaspace (全局)
 ├── VirtualSpaceList (class / non-class 各一条)
 │     └── VirtualSpaceNode   ~64MB reserve, 按 granule commit
 │           └── RootChunkArea  每个含 1 个 root chunk 或其碎片
 ├── ChunkManager             按 level 持有 FreeChunkList, 供给/回收 chunk
 ├── MetaspaceArena           每个 CLD 1~2 个, bump 分配
 │     ├── MetachunkList      retired ... + current chunk
 │     └── FreeBlocks         提前释放的块 (BinList32 + BlockTree)
```

### VirtualSpaceList and VirtualSpaceNode

底层内存以**节点**为单位向 OS 申请：`VirtualSpaceList` 是全局链表，节点是 `VirtualSpaceNode`。class 与非 class 空间各有一条 vslist（`memory/metaspace.cpp:205-210` 的 `get_ccl()` / `get_nccl()` 直接打印 "class vslist" / "non-class vslist"）。

节点的大小与对齐定义在 `memory/metaspace/metaspaceSettings.hpp`：

```cpp
// VirtualSpaceNode sizes
//  Must be a multiple of the root chunk size.
static const size_t _virtual_space_node_size_words =
    chunklevel::MAX_CHUNK_WORD_SIZE * NOT_LP64(1) LP64_ONLY(4); // 16MB (32-bit) / 64MB (64-bit)
```

即 64 位平台上一个节点 **reserve 64MB** 虚拟地址空间，而 reserve 对齐粒度是 root chunk 大小（16MB）。`VirtualSpaceNode` 的头文件注释（`memory/metaspace/virtualSpaceNode.hpp:47-84`）说明了两条彼此独立的切分逻辑：

- 地址空间按 **root chunk area** 切分，每个 area 容纳一个 root chunk 或其碎片，供 ChunkManager 取用；
- 同时按 **commit granule** 切分，用位图 `CommitMask` 记录每一格是否已 commit——**reserve 是一次性的虚拟地址占位，commit 才是真正占用物理内存，且以 granule 为粒度按需进行**；节点内全部空闲时可被 purge（uncommit / unmap 归还 OS）。

commit 前要过 `CommitLimiter` 这道闸门，它把"还能不能提交"的多重限制（GC 阈值、`MaxMetaspaceSize`）封装在一个接口里（virtualSpaceNode.hpp:64-66）。真正的 mmap 失败与地址空间耗尽则直接 `vm_exit_out_of_memory`，见后文 OOM 一节。

### ChunkManager and the Fifteen-Level Chunk Tree

`ChunkManager`（`memory/metaspace/chunkManager.hpp:72`）持有按 chunk 层级组织的空闲表 `FreeChunkListVector _chunks`（:82），负责把 root chunk 拆给 arena、再收回。当前版本的层级制度定义在 `memory/metaspace/chunklevel.hpp:42-114`：

```
// Each chunk has a level; the level corresponds to its position in the tree
// and describes its size.
// The largest chunks are called root chunks, ... and have level 0.
// size    level
// 16MB    0
// 8MB     1
// 4MB     2
// ...
// 4K      12
// 2K      13
// 1K      14
static const size_t MAX_CHUNK_BYTE_SIZE = 16 * M;   // :64
static const int    NUM_CHUNK_LEVELS    = 15;       // :65
```

| Level | 0 | 1 | 2 | 3 | 4 | … | 10 | 11 | 12 | 13 | 14 |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| 大小 | 16M | 8M | 4M | 2M | 1M | … | 16K | 8K | 4K | 2K | 1K |

分配时找"能装下请求尺寸的最高层级"（`level_fitting_word_size`，:95），拿不到就在树上**对半分裂**更高层级的 chunk——非 root chunk 必有兄弟节点（buddy，`memory/metaspace/metachunk.hpp:134` 注释），归还时可反向合并，这就是"chunk 树"。`metaspaceSettings.hpp:55-57` 还有一个优化开关 `_enlarge_chunks_in_place = true`：当前 chunk 装不下时优先**原地翻倍扩容**而非新取一块。老设计里按请求尺寸把 chunk 分成 specialized / small / medium / humongous 四级的词汇，在当前源码中已不存在。

Root chunk 的来源受 **RootChunkArea** 约束（`memory/metaspace/rootChunkArea.hpp`）：分配请求先按对齐与尺寸换算出所需的 root chunk area 数量（:198 `needed_root_chunks`），vslist 的节点正是按 area 网格化组织的。

新旧两代 chunk 管理制度的对照，读老文章时按此换算：

| 维度 | JDK 8–11 旧设计 | JDK 27 当前设计 |
| :-- | :-- | :-- |
| chunk 分类 | specialized / small / medium / humongous 四级 | 16MB → 1K 共 15 级二分树（`chunklevel.hpp:64-65`） |
| 空闲块组织 | 每级一条 free chunk 链表 | 每级一个 `FreeChunkList`，聚合为 `FreeChunkListVector`（`chunkManager.hpp:82`） |
| 大块元数据请求 | humongous 独立通道 | 无独立通道；装不下就分裂更高层级或原地扩（`_enlarge_chunks_in_place = true`，`metaspaceSettings.hpp:57`） |
| 地址载体 | vslist 节点内直接切 chunk | 节点内先网格化为 RootChunkArea，再供给 chunk |

### MetaspaceArena

Arena 是分层结构的顶端：`MetaspaceArena`（`memory/metaspace/metaspaceArena.hpp:78`）是"属于某个 CLD 的可增长 Metaspace 内存池"，其文件头注释给出了内部形态：

```
//  +---------------+
//  |     Arena     |
//  +---------------+
//            |
//            | _chunks                                               commit top
//            |                                                       v
//        +----------+      +----------+      +----------+      +----------+
//        | retired  | ---> | retired  | ---> | retired  | ---> | current  |
//        | chunk    |      | chunk    |      | chunk    |      | chunk    |
//        +----------+      +----------+      +----------+      +----------+
//                                                                  ^
//                                                                  used top
```

关键成员（:85-107）：`_chunk_manager`（取 chunk 的来源）、`_growth_policy`（`ArenaGrowthPolicy`，决定下一块 chunk 的层级，见 `next_chunk_level()` :123）、`MetachunkList _chunks`（表头即 current chunk）、`_fbl`（下节）。分配就是对 current chunk 的**指针碰撞（pointer bump）**；chunk 用旧了就 retire（`retire_current_chunk`），装不下就向 ChunkManager 要更大的（`allocate_new_chunk` :120）或原地扩（`attempt_enlarge_current_chunk` :129）。这种"整块生命周期同生共死"的模式与线程堆上分配用的 TLAB 同构（见 [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)），区别是 MetaspaceArena 的粒度是类元数据、生命周期跟随 ClassLoader。

### FreeBlocks with BinList32 and BlockTree

类加载失败、字节码重写等原因会使已分配的块**提前释放**。这些块嵌在仍被 arena 使用的 chunk 里，不能交还 ChunkManager，只能由本 arena 自己复用——管理器就是 `FreeBlocks`（`memory/metaspace/freeBlocks.hpp:40-61` 注释）。它针对实际分布做了双结构拆分：约 90% 的释放块小于 16 words，用 **bin list**（按尺寸分桶的链表 `BinList32 _small_blocks`）承接；剩下少量大块（主要来自 retire chunk 的剩余空间）放进一棵二叉搜索树 `BlockTree _tree`：

```cpp
class FreeBlocks : public CHeapObj<mtMetaspace> {
  BinList32  _small_blocks;   // small to very small blocks
  BlockTree  _tree;           // only for blocks too large for _small_blocks
  STATIC_ASSERT(BinList32::MaxWordSize >= BlockTree::MinWordSize);
```

对外只有两个动作：`add_block` 归还、`remove_block(requested_word_size)` 取一块不小于请求尺寸的空间（可能偏大）。

## One Arena per ClassLoader

每个 ClassLoader 的 VM 侧表示是 `ClassLoaderData`（CLD），Metaspace 相关的成员只有两个（`classfile/classLoaderData.hpp:111-113`）：

```cpp
ClassLoaderMetaspace * volatile _metaspace;  // Meta-space where meta-data defined by the
Mutex* _metaspace_lock;  // Locks the metaspace for allocations and setup.
```

`ClassLoaderMetaspace`（CLMS，注意它已从 `memory/metaspace.hpp` 挪到独立文件 `memory/classLoaderMetaspace.hpp:67`）为 CLD 管理 arena，64 位下恰好两个：

```cpp
// Arena for allocations from non-class  metaspace
metaspace::MetaspaceArena* _non_class_space_arena;
// Arena for allocations from class space (null for 32-bit).
metaspace::MetaspaceArena* _class_space_arena;
```

对应的整体关系（源码头注释原图）：

```
// +------+       +----------------------+       +-------------------+
// | CLD  | --->  | ClassLoaderMetaspace | ----> | (non class) Arena |
// +------+       +----------------------+  |    +-------------------+     allocation top
//                                          |       |                        v
//                                          |       + chunk -- chunk ... -- chunk
//                                          |
//                                          |    +-------------------+
//                                          +--> | (class) Arena     |
//                                               +-------------------+
//                                                  |
//                                                  + chunk ... chunk
//                                                               ^
//                                                               alloc top
```

CLMS 对外的三个入口是 `allocate(word_size, mdType)`、`expand_and_allocate(...)`（GC 期间抬阈值后再分配，见下节）与 `deallocate(ptr, word_size)`——后者就是把块塞回 arena 的 `FreeBlocks`。因为同一 CLD 的分配可能来自多个线程，所有操作都在 `_metaspace_lock` 下进行（metaspaceArena.hpp:81-82 注释）。CLD 卸载时，其 CLMS 与全部 arena/chunk 被归还给 ChunkManager，条件合适时再 purge 回 OS。

## Metaspace GC Threshold

Metaspace 引发的 GC 有两种触发时机：

1. **常规分配时**：VM 持有一条阈值，committed 逼近它就先 GC 一轮，目的是卸载陈旧的 ClassLoader、复用它们的 Metaspace，然后才允许继续扩张。这条阈值随已 commit 量上下调整（实际只单调上移），防止 Metaspace 只增不减；
2. **Metaspace OOM 时**：committed 撞上 `MaxMetaspaceSize` 上限、或 compressed class space 耗尽，VM 会尝试用 GC 救急。如果 GC 真能卸载掉 ClassLoader 就皆大欢喜，否则即便 Java 堆还很空，进程也会陷入代价高昂的连续 full GC 循环——这是 Metaspace OOM 现场最典型的特征。

下面展开第 1 种。VM 维护**GC 阈值** `MetaspaceGC::_capacity_until_GC`（`memory/metaspace.cpp:266`）。两条规则：

- 阈值**只升不降**（`inc_capacity_until_GC` 拒绝任何下降，:330-334），但每次升的幅度与已回收量挂钩（`delta_capacity_until_GC`，:293-312，步长被 `MinMetaspaceExpansion` / `MaxMetaspaceExpansion` 夹住，见 `runtime/globals.hpp:1426`）；
- 新阈值不得超过 `MaxMetaspaceSize`（:341-344），超过即失败。

阈值随启动阶段变化，这正是理解 `MetaspaceSize` 的关键。消费方代码（`memory/metaspace.cpp:372-381`）：

```cpp
void MetaspaceGC::initialize() {
  // Set the high-water mark to MaxMetapaceSize during VM initializaton since
  // we can't do a GC during initialization.
  _capacity_until_GC = MaxMetaspaceSize;
}

void MetaspaceGC::post_initialize() {
  // Reset the high-water mark once the VM initialization is done.
  _capacity_until_GC = MAX2(MetaspaceUtils::committed_bytes(), MetaspaceSize);
}
```

也就是说：**`MetaspaceSize` 是"第一次 GC 阈值"，不是初始分配大小、也不是初始 commit 量**——flag 的官方描述就是这么写的："Initial threshold (in bytes) at which a garbage collection is done to reduce Metaspace usage"（`runtime/globals.hpp:1376-1378`，默认 LP64 `21*M`、32 位 `16*M`）。VM 初始化期间阈值干脆被抬到 `MaxMetaspaceSize`（因为此时不能 GC），启动完成后才落回 `max(已 commit 量, MetaspaceSize)`。Metaspace 实际 commit 的多少从来只由"真用了多少"决定，与 `MetaspaceSize` 无关。

相关参数一览（默认值均见 `runtime/globals.hpp`）：

| 参数 | 默认值 | 真实语义 |
| :-- | :-- | :-- |
| `MetaspaceSize` | 21 MB（64 位）/ 16 MB（32 位） | **首次 GC 阈值**，不是初始大小；只影响 GC 时机 |
| `MaxMetaspaceSize` | `max_uintx`（无限） | committed 总量硬上限，达到即 Metaspace OOM |
| `CompressedClassSpaceSize` | 1 GB（range 1M–4G） | class space 的**虚拟 reserve**，不占物理内存 |
| `MinMetaspaceExpansion` | 256 K | GC 阈值单次抬升下限 |
| `MaxMetaspaceFreeRatio` / `MinMetaspaceFreeRatio` | 70 / 40 | GC 后调整阈值的空闲率参数 |

## Metaspace OOM

三种成因，日志与后果各不相同——注意前两种是 **VM 直接退出**（native 层失败），只有第三种才是常见的 `OutOfMemoryError`：

| 成因 | 触发点 | 日志文案 | 后果 |
| :-- | :-- | :-- | :-- |
| **reserve 耗尽**：虚拟地址空间申请失败 | `VirtualSpaceList` 通过 `ReservedSpace` 建新节点（virtualSpaceNode.cpp:258） | `Failed to reserve memory for metaspace` | `vm_exit_out_of_memory`，VM 退出 |
| **commit 失败**：mmap 层拒绝提交 | `expand_and_commit_region_to_address` 中 `os::commit_memory` 返回 false（virtualSpaceNode.cpp:112-113） | `Failed to commit metaspace.` | `vm_exit_out_of_memory`，VM 退出 |
| **达到 `MaxMetaspaceSize` 或 CommitLimiter 拒绝** | 先查 limiter（virtualSpaceNode.cpp:106-108）、`MetaspaceGC::can_expand` 的 `committed + size > MaxMetaspaceSize`（metaspace.cpp:396-398）；GC 后仍失败进入 `Metaspace::report_metadata_oome` | `Metaspace (class\|data) allocation failed for size N`（metaspace.cpp:945，log tag `gc,metaspace,freelist,oom`）+ 抛 `java.lang.OutOfMemoryError: Metaspace`；若判定是 class space 溢出（:960-971），异常消息为 **`Compressed class space`** | 抛 OOME；`-XX:+HeapDumpOnOutOfMemoryError` 等挂钩照常生效 |

第三种成因的完整流程值得多看一眼（`memory/metaspace.cpp:938-990`）：OOM 时 VM 会以 info 级别顺手打印一份精简报告（`MetaspaceUtils::print_basic_report`），debug 级别还会 dump 出肇事 ClassLoader 的内容——排查时先 `-Xlog:metaspace,gc+metaspace` 打开日志，基本报告里 `in use capacity` 与 `max capacity` 的关系一目了然。

实践中 Metaspace OOM 几乎总是**动态生成类 + ClassLoader 泄漏**的组合：常见肇事者是 Orika 的 classMap、JSON 的 ASMSerializer、Groovy 动态编译，以及一切建立在反射、Javassist 字节码增强、CGLIB 动态代理、OSGi 自定义类加载器上的框架。对策除给 Metaspace 使用率加监控告警外，就是在 jcmd 报告里按 ClassLoader 维度找出数量异常的那一个（见下节）。

## Observability

**jcmd**。命令名定义在各 dcmd 类的 `static const char* name()` 里，**Metaspace 这一族仍是 `VM.` 前缀**——JDK 27 并没有发生过"`VM.` 迁到 `GC.`"这件事，`GC.` 前缀只属于本来就管堆的命令（`GC.heap_info`、`GC.run` 等，见 `services/diagnosticCommand.hpp`）。

```bash
jcmd <pid> VM.metaspace                     # 命令名 memory/metaspace/metaspaceDCmd.hpp:46-48
jcmd <pid> VM.metaspace show-loaders        # 按 ClassLoader 展开
jcmd <pid> VM.classloaders                  # 类加载器层级树 classLoaderHierarchyDCmd.hpp:40
jcmd <pid> VM.classloader_stats             # 加载器统计 classLoaderStats.hpp:43
```

`VM.metaspace` 共 8 个参数（`metaspaceDCmd.hpp:55` 的 `num_arguments()`），在 `metaspaceDCmd.cpp:39-49` 逐个定义：
`basic`（不需 safepoint 的简版）、`show-loaders`、`by-spacetype`、`by-chunktype`、`vslist`、`chunkfreelist`、
`scale`（1/KB/MB/GB 或默认的 `dynamic`）、`show-classes`。

> [!WARNING]
> 这三个命令名的**定义位置在 `.hpp` 的 `name()`，不在 `.cpp`**。`metaspaceDCmd.cpp:39-49` 那一串
> `basic` / `show-loaders` / `by-spacetype` / `by-chunktype` / `vslist` 是**参数字符串**，不是命令名——
> 把它们当成命令名会得出"`GC.metaspace_dump` 存在"这类根本不存在的结论（全树 grep `metaspace_dump` 零命中）。

`VM.metaspace` 的输出由 `metaspaceReporter.cpp` 生成，字段与源码术语一一对应（:96-119）：`capacity reserved`（reserve 总量）、`capacity at next GC`（当前 GC 阈值）、`capacity at limit`（`MaxMetaspaceSize`）、`capacity committed`（真实物理占用，"This is the amount of memory the metaspace occupies at this moment"）、`capacity used committed`（其中真正被元数据占用的）。`VM.classloaders` 每行还带 chunk 层级直方图，如 `chunkusage=108K@3;216K@4;928K@6`（`@` 后即 chunk level）。

**NMT**。`jcmd <pid> VM.native_memory summary` 下与 Metaspace 相关的标签定义在 `nmt/memTag.hpp`（⚠️ NMT 源码在本树已移入 `share/nmt/`，不在旧的 `memory/` 下）。区别在于统计口径：

| NMT 标签 | 代码常量 | 覆盖内容 |
| :-- | :-- | :-- |
| `Metaspace` | `mtMetaspace`（:57） | Metaspace 本体；其管理类如 ChunkManager / FreeBlocks 是 `CHeapObj<mtMetaspace>` |
| `Class` | `mtClass`（:32） | class space 相关；Metaspace 的关键管理结构 `VirtualSpaceNode` / `ClassLoaderMetaspace` / `MetaspaceArena` 全是 `CHeapObj<mtClass>`，会记到这个标签下 |
| `Arena Chunk` | `mtChunk`（:47） | 承载 arena 内容的 chunk 辅助结构 |
| `Symbol` | `mtSymbol`（:44） | 符号表等，见 [SymbolTable](/docs/CS/Java/JDK/JVM/SymbolTable.md) |
| `Shared class space` | `mtClassShared`（:46） | CDS 映射的共享类区 |

所以看 NMT 时只盯 `Metaspace` 一行会**漏算 class space 与配套结构**，"Metaspace 看起来不大、native 却涨了很多"的情形常要连着 `Class` / `Arena Chunk` 一起看。

**日志与收尾统计**。运行时行为用 `-Xlog` 的 `gc+metaspace` / `metaspace` tag 观察（如 `GC threshold increased: %zu->%zu`，classLoaderMetaspace.cpp:151）；退出时打印汇总用 `-XX:+PrintMetaspaceStatisticsAtExit`（diagnostic，`runtime/globals.hpp:1397`）。

## Links

- [Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [GC](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [Serviceability](/docs/CS/Java/JDK/JVM/Serviceability.md)

## References

- [JEP 122: Remove the Permanent Generation](https://openjdk.org/jeps/122)
- [JDK-8251158: Implementation of JEP 387: Elastic Metaspace](https://bugs.openjdk.org/browse/JDK-8251158)
- [The java Command](https://docs.oracle.com/en/java/javase/27/docs/specs/man/java.html)
