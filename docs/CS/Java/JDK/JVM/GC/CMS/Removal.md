## Introduction

CMS（Concurrent Mark Sweep）是 HotSpot 家族中**首个把并发引入生产**的收集器，也是**第一个被整体移除**的收集器（JDK 14，JEP 363）。从 JDK 5（2004）引入到 JDK 14（2020）移除，CMS 服务了 Java 生态整整 16 年，为低延迟应用建立了"大部分 GC 工作并发、仅两次 STW"的设计范式。

但 CMS 的设计是**过渡性的**——它的并发标记（增量更新）和标记-清除本质上无法解决**浮动垃圾 → CMF → Full GC**的问题链。G1（Region 化）、Shenandoah（并发重定位）、ZGC（着色指针+读屏障）分别从不同方向突破了 CMS 的限制。

### JEP 时间线

| JEP | Release | 动作 |
| --- | --- | --- |
| **JEP 140** | JDK 5 | 首次引入 CMS（实验性，`-XX:+UseConcMarkSweepGC`） |
| — | JDK 1.4.2 | CMS 被标记为"可用于生产" |
| **JEP 189** | JDK 12 | Shenandoah 实验性（`-XX:+UseShenandoahGC`） |
| **JEP 274** | JDK 12 | ZGC 实验性（`-XX:+UseZGC`） |
| **JEP 291** | JDK 9 | **弃用 CMS**：`-XX:+UseConcMarkSweepGC` 开始打印弃用警告 |
| **JEP 363** | **JDK 14** | **移除 CMS**：`gc/cms` 源码目录整体删除，命令行选项被忽略（回退到默认收集器） |
| **JEP 377** | JDK 15 | ZGC 转正 |
| **JEP 379** | JDK 15 | Shenandoah 转正 |

CMS 的移除与 ZGC/Shenandoah 转正几乎在同一年完成——这不是巧合。

## 四个结构性缺陷

CMS 的问题不是"实现 bug"，而是**架构设计缺陷**。G1/ZGC/Shenandoah 的继任都是在架构层面解决了这些缺陷。

### 缺陷 1：标记-清除不压缩

- **表现**：老年代碎片化——长期运行后即使总空闲足够，也无法分配大对象（没有连续空闲块）
- **触发**：大对象分配失败时，CMS 会触发一次 **Full GC mark-compact**（等价 CMF 路径）
- **根因**：增量更新 + 标记-清除 = CMS **无法做并发重定位**（参见 [Incremental Update](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md)）
- **继任者怎么解**：
  - **G1**：Region 化 + STW evacuation（young/mixed GC 期间搬运存活对象），消除碎片化
  - **Shenandoah**：**并发重定位**（speculative copy + Brooks pointer），evacuation 与 mutator 并发
  - **ZGC**：**并发重定位**（self-healing + colored pointer），relocation 与 mutator 并发

### 缺陷 2：浮动垃圾 + CMF

- **表现**：增量更新不取消标记 → 标记期间变成不可达的对象不会被取消标记 → 这些浮动垃圾**占据真实内存直到下一周期**
- **后果**：如果浮动垃圾太多、CMS 没在老年代填满前完成 sweep → **CMF** → 退化成 Full GC mark-compact
- **根因**：增量更新的 correctness 语义决定了浮动垃圾必然存在
- **继任者怎么解**：
  - **G1**：SATB 快照保证**快照可达性** → 标记期间变成不可达的对象不需要取消标记，SATB 语义天然保证"只标记快照中的可达对象"
  - **Shenandoah/ZGC**：SATB + 并发重定位 → 即使有浮动垃圾（实际也很少），evacuation/relocation 阶段**顺手搬掉**
  - **所有现役收集器**：**没有 CMF 这种退化机制**——最差也是 Shenandoah Degenerated GC（STW 并发 evacuation）或 ZGC Emergency Collection，不放弃自身逻辑

### 缺陷 3：CPU 占用高

- **表现**：CMS 并发阶段持续占用 **1 ~ ceil(N/4)** 个处理器（N = CPU 核数）
- **根因**：CMS 必须全程维持并发标记线程——增量更新写屏障 + SATB marker queue 是持续写入的
- **与 G1 对比**：G1 也有并发标记线程，但 mixed GC 可以在标记完成后停止；CMS 的并发标记-清除**贯穿整个老年代占用周期**
- **继任者怎么解**：
  - **G1**：young GC 不并发标记（只有 Full GC 和 mixed GC 才需要），减少并发阶段时长
  - **Shenandoah**：并发重定位与 mutator 并发，读屏障（LRB）极低开销，写屏障也被优化到 fast path 极快
  - **ZGC**：load barrier fast path 1-2 条指令，store barrier（分代模式）act-once 语义——mutator 开销在所有现役收集器中最低

### 缺陷 4：维护成本 + ParNew 紧耦合

- **表现**：CMS 代码路径复杂（`gc/cms/` 目录约 20 KLOC），与 ParNew（新生代收集器）**紧耦合**——CMS 直接调用 ParNew 的 live bits、young→old 引用扫描、tenuring 等
- **根因**：CMS 是 HotSpot 中**第一个并发收集器**，没有现代 GC 框架（CollectedHeap、GC 接口、统一 barrier set）——很多基础设施是为 CMS 定制的
- **继任者怎么解**：
  - **G1**：与 Parallel GC 共享新生代框架（ParNew 退役后），现代 GC 接口
  - **Shenandoah/ZGC**：从头设计在现代 GC 框架上，不依赖任何历史遗留
  - **最终结果**：CMS 源码树中 `gc/cms/` 目录整个删除（JEP 363 描述），JDK 源码中再无 CMS 代码

## 为什么是 JDK 14 移除，不是更早

JEP 291（JDK 9）弃用 CMS，JEP 363（JDK 14）才移除——中间隔了 5 年。原因：

1. **大量生产系统依赖 CMS**：迁移成本高，社区需要缓冲时间
2. **G1 在 JDK 9 转正**（替代 Parallel 成为默认收集器），但 G1 有自己的学习曲线
3. **ZGC/Shenandoah 从 JDK 11/12 开始实验，JDK 15 转正**——在 CMS 移除后真正提供同等或更好的低延迟能力
4. **没有社区维护者**：JEP 291 描述"没有可信的贡献者接手 CMS 维护"

## 迁移路径

CMS 移除后的官方推荐：

| 场景 | 替代方案 |
| --- | --- |
| 一般服务端应用（中堆） | **G1**（Region 化、可预测暂停、官方默认） |
| 低延迟 + 大堆（TB 级） | **ZGC** 或 **Shenandoah**（并发重定位、暂停与堆解耦） |
| 需要 CMS 的增量模式（i-cms） | JDK 8 或更早版本（i-cms 早在 Java 8 就已弃用） |

典型迁移命令行：

```shell
# CMS（JDK 8 及更早）
java -XX:+UseConcMarkSweepGC

# 迁移到 G1（JDK 9+ 默认）
java -XX:+UseG1GC

# 迁移到 Shenandoah
java -XX:+UseShenandoahGC

# 迁移到 ZGC
java -XX:+UseZGC
```

## JEP 363 的移除范围

JEP 363（JDK 14）移除的内容：

1. **编译时**：CMS 源码树 `src/hotspot/share/gc/cms/` 整个删除
2. **编译时**：CMS 专属选项（`-XX:+UseConcMarkSweepGC`、`-XX:+CMSIncrementalMode`、`-XX:+UseCMSCompactAtFullCollection` 等）从 VM 移除
3. **编译时**：CMS 专属统计、日志、诊断（`-XX:+PrintGCDetails` 中的 `CMS-*` 输出）移除
4. **运行时**：命令行传 CMS 选项打印弃用警告 + `support was removed in <version>` + **回退到默认收集器**（不是报错退出）

⚠️ 回退到默认收集器容易被忽略——JDK 14 上跑着的 CMS 应用，把 `-XX:+UseConcMarkSweepGC` 去掉就是 G1，加回去只是打印警告然后继续 G1。

## References

1. [JEP 291: Deprecate CMS](https://openjdk.org/jeps/291) — 弃用 CMS 的设计动机
2. [JEP 363: Remove CMS](https://openjdk.org/jeps/363) — 移除 CMS 的具体范围
3. [JEP 377: ZGC Production](https://openjdk.org/jeps/377) — ZGC 转正时间线
4. [JEP 379: Shenandoah Production](https://openjdk.org/jeps/379) — Shenandoah 转正时间线
5. [CMS Documentation (Java 8)](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html) — 官方文档，现已归档

## Links

- [CMS 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/CMS.md)
- [CMS Incremental Update（架构根源问题）](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md)
- [CMS Concurrent Mode Failure（浮动垃圾 → CMF → Full GC）](/docs/CS/Java/JDK/JVM/GC/CMS/ConcurrentModeFailure.md)
- [G1 Garbage Collector（CMS 的继任者）](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [ZGC（并发重定位解决了 CMS 的碎片问题）](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [Shenandoah（并发重定位 + Brooks pointer）](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
