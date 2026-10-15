## Introduction

**load barrier（读屏障）** 是 ZGC 的 GC 屏障体系的基石，也是它区别于 CMS、G1、Shenandoah 等使用 write barrier（写屏障）的收集器的关键特征。

- **CMS / G1 / Shenandoah**：写屏障在引用**写入**时介入，把"旧值"或"字段位置"记录到队列/日志/RSet，后续 GC 从这些线索出发遍历对象图
- **ZGC**：load barrier 在引用**读取**时介入，检查 colored pointer 的 metadata bits，必要时在这一刻完成标记或重定位修复

这个设计选择让 ZGC 实现了 **完全并发的重定位**（concurrent relocation）——GC 线程可以随时移动对象，而不需要先通知所有持有该对象引用的 mutator 线程。旧指针依然有效，因为 load barrier 会在下次被读到时自动更新为新地址（**self-healing**）。

## Where Load Barriers Are Inserted

load barrier 由 JIT 编译器（C2）在每次**从堆对象字段加载引用类型**时自动注入。概念上类似 HotSpot 的 CompressedOops decode——compressed oops 的 decode 就是一种隐式的引用加载屏障，把压缩的 32-bit 偏移解成 64-bit 堆地址。

以 Java 代码为例：

```java
Person p = ...;
String name = p.name;  // ← 这里会被插入 load barrier
```

C2 生成的伪汇编大致是：

```asm
mov rax, [rdi + offset_name]   ; 原始 load（彩色指针）
; --- load barrier fast path ---
test rax, ZGC_METADATA_MASK    ; 检查是否有"坏颜色"或 relocation 标记
jz fast_path_done              ; 如果 metadata 位全零，直接使用
; --- slow path ---
call ZBarrier::load_oop_slow   ; 修复指针（self-heal）或触发标记
fast_path_done:
```

关键约束：load barrier **只在堆字段引用加载时插入**，不在栈上局部变量访问、CPU 寄存器访问中重复插入——因为栈和寄存器中的引用已经是 colorless 的（纯地址），不需要再检查 metadata。

## Fast Path / Slow Path

load barrier 和 store barrier 都遵循 ZGC 的统一 **fast path / slow path 分流**设计：

| 路径 | 频率 | 做什么 | 性能开销 |
| --- | --- | --- | --- |
| **Fast Path** | 绝大多数（>99%） | 检查 metadata bits，剥离后直接解引用 | 1–2 条指令（shift + test） |
| **Slow Path** | 极少数 | 执行 GC 工作（self-heal、标记、RSet 记录） | C++ 函数调用，可能触发 CAS 循环 |

fast path 的关键设计约束：**必须极快**，因为它每次堆引用加载都会执行。slow path 的关键设计约束：**必须幂等且一次性**，这样 slow path 执行完后会把 metadata bits 改成"已处理"状态，后续 fast path 看到就跳过。

ZGC 用一个技巧保证 slow path 的一次性：执行完后，把 colored pointer 的 metadata bits 更新为一个 fast path 识别的"正常"颜色，同时可能把指针的实际地址也更新了。下一次 mutator 加载同一个字段时，fast path 直接通过。

## Self-Healing 并发重定位

ZGC 的核心能力——**无需暂停即可并发移动对象**——完全依赖 load barrier 的 self-healing 机制。

### 问题场景

GC 线程正在并发 relocation（压缩）阶段，把 Region A 里的存活对象拷贝到 Region B。如果 mutator 线程此时读取一个 Region A 对象的引用，会发生什么？

**传统方案**（G1 / Shenandoah）：
- GC 线程提前更新所有 outgoing 引用（需要 RSet / forwarding pointer）
- 或者用 snapshot（SATB / Brooks pointer）保证 mutator 看到的总是有效视图

**ZGC 方案（self-healing）**：
1. GC 线程标记 Region A 的所有对象的 colored pointer 为"坏颜色"（relocation set 标记）
2. GC 线程把存活对象从 Region A 拷贝到 Region B，并记录 forwarding 表（old addr → new addr）
3. mutator 线程加载 Region A 里的某个对象引用时，load barrier fast path 检测到坏颜色
4. **load barrier slow path 执行 self-healing**：在 forwarding 表里查新地址，然后 CAS 原子把对象字段里的旧 colored pointer 替换成新地址 + 新颜色的 colored pointer
5. 如果 CAS 失败（另一个 mutator 或 GC 线程也在 self-heal 同一个字段），重试 CAS 循环
6. 修复完成，mutator 拿到新地址正常访问

### CAS 伪代码

```cpp
inline void ZBarrier::self_heal(volatile oop* p, uintptr_t addr, uintptr_t heal_addr) {
  assert(!fast_path(addr), "Invalid self heal — addr should have triggered slow path");
  assert(fast_path(heal_addr), "Invalid self heal — heal_addr should be valid");

  if (heal_addr == 0) {
    return;  // 对象已被回收
  }

  // CAS 循环：竞争修复同一个字段
  for (;;) {
    const uintptr_t prev_addr = Atomic::cmpxchg((volatile uintptr_t*)p, addr, heal_addr);
    if (prev_addr == addr) {
      // CAS 成功，我们修复了这个字段
      return;
    }
    // CAS 失败：另一个线程先修了
    addr = prev_addr;
    if (fast_path(addr)) {
      // 已经被别人修好
      return;
    }
    // 还是坏颜色，重试
  }
}
```

### Baker-Style Relocation

self-healing 的思想可以追溯到 Baker (1978) 的 **forwarding-pointer-on-object** 方案。Baker 建议把 forward 信息直接存在对象本身的 header 里，任何时候加载一个对象引用都先检查 forward。ZGC 把这个思想扩展到了 colored pointer 层面——forward 信息（relocation set membership）编码在指针 metadata 里，forwarding 表存在 GC 数据结构中。

### 与 G1 Evacuation 的对比

| 维度 | G1 Evacuation | ZGC Relocation |
| --- | --- | --- |
| 时机 | Young GC STW 阶段 | 并发，与 mutator 同时进行 |
| 引用更新 | STW 并行处理所有 incoming 引用 | Lazy，load barrier 按需修复 |
| 失败兜底 | Promotion → Full GC | 无需兜底，self-heal 总有效 |
| RSet 依赖 | 强依赖（跨 Region 引用扫描） | 不需要（单代内引用全靠 self-heal） |

## Non-Generational vs Generational 职责变化

| 职责 | Non-Generational Load Barrier | Generational Load Barrier |
| --- | --- | --- |
| 剥离 metadata bits | ✅ 不依赖 multi-mapping 隐式 | ✅ 显式 shift（低阶位布局，1 条指令） |
| Self-healing（relocation 更新） | ✅ 核心职责 | ✅ 保留 |
| **标记存活对象** | ✅ "应用在读 → 标记为活" | ❌ **移到 store barrier** |
| Colored ↔ Colorless 翻译 | 隐式（multi-mapping） | ✅ 显式，栈用 colorless |

分代 ZGC 把标记职责从 load barrier 移到 store barrier，是出于性能权衡：

- load barrier 比 store barrier 执行得更频繁（读多写少是普遍规律）
- fast path 上移走标记逻辑，让 load barrier 几乎可以被 JIT 完全消除（只剩一条 shift）
- store barrier 的 slow path 执行"act-once"语义（一个字段一个标记周期内只触发一次），总体开销可控

## Load Barrier vs Store Barrier 职责分工

分代 ZGC 中两类 barrier 的分工：

| Barrier | 插入位置 | Fast Path 做什么 | Slow Path 做什么 |
| --- | --- | --- | --- |
| **Load** | 堆引用**读** | Shift 剥离 metadata → 得到纯地址 | Self-healing（relocation 修复）、更新 metadata |
| **Store** | 堆引用**写** | 检查字段是否已登记过 → 彩色化新指针 | RSet 维护（old→young 记录）、SATB 标记（记录被覆盖的旧值） |

## Performance Characteristics

### Fast Path 开销

非分代 ZGC 的 load barrier fast path 几乎是零开销——multi-mapping 让正确地址直接可解引用，只需要一条 `test` 指令检查颜色是否"坏"。

分代 ZGC 因为取消了 multi-mapping，fast path 多了一条 shift（x64 上 1 条 `shr`），但低阶位布局让 shift 同时完成"检查是否需要处理"和"剥离 metadata"两个工作——**净增加 0 条指令**（把原本要分开做的 test + shift 合并）。

### Slow Path 频率

slow path 的触发频率是性能关键：

- 非分代 ZGC：标记阶段和 relocation 阶段 slow path 频率提升，因为 fast path 需要区分颜色
- 分代 ZGC：load barrier slow path 频率**大幅下降**——标记移到 store barrier 后，load barrier 的 slow path 只在 relocation 期间触发
- Relocation 阶段结束后，所有指针都被标记为"已 remap / 已 relocate"，此后 fast path 100% 通过

### 与 Shenandoah Load Reference Barrier 的对比

Shenandoah 也有 load reference barrier（叫 Brooks Pointer 间接指针 + SATB），但它的 barrier **每次加载都要检查 forwarding 指针**，而 ZGC 的 load barrier 在 relocation 完成后完全退化成纯地址解引用，**没有持续开销**。

## Links

- [ZGC 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [ZGC Colored Pointers（load barrier 解析的 metadata 来源）](/docs/CS/Java/JDK/JVM/GC/ZGC/ColoredPointers.md)
- [ZGC Generational（load/store barrier 分工与 fast/slow path）](/docs/CS/Java/JDK/JVM/GC/ZGC/Generational.md)
- [Shenandoah Barriers（LRB + SATB + 疏散写屏障）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)
- [Shenandoah Brooks Pointer（LRB 的底层机制）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)

## References

1. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — ACM TOSEM 2022，第 3.1 节 load barrier 核心算法
2. [The Z Garbage Collector](http://cr.openjdk.java.net/~pliden/slides/ZGC-Jfokus-2018.pdf) — Per Liden 在 Jfokus 2018 的演讲，load barrier 设计
3. [JEP 439: Generational ZGC](https://openjdk.org/jeps/439) — barrier 职责迁移的设计理由
4. [OpenJDK16 ZGC 源码分析](https://juejin.cn/post/7069620930418311176) — self-heal CAS 循环源码
5. [Baker: List Processing in Real Time on a Serial Computer](https://dl.acm.org/doi/10.1145/360625.360631) — 1978 年原始论文，forwarding pointer 方案
