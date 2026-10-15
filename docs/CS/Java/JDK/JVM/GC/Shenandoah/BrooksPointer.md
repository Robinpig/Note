## Introduction

Shenandoah 的 **Brooks Pointer**（也叫 forwarding pointer / indirection pointer）是它实现**并发重定位（concurrent compaction）**的核心机制——一个优雅且古老的思想：**在每个对象前加一个字（word），存储该对象的"当前位置"指针**。当对象被拷贝到新位置时，只需原子地更新这个前置指针，所有指向旧位置的 mutator 线程下次访问时自动被导向新位置。

这个机制与 ZGC 的 colored pointer 形成鲜明对比：

| 维度 | Brooks Pointer（Shenandoah） | Colored Pointer（ZGC） |
| --- | --- | --- |
| 存储位置 | **对象内存里**（前置一个 word） | **指针 bits 里**（64-bit 未使用位） |
| per-object 开销 | 是（1 word = 8 bytes） | 否 |
| per-pointer 开销 | 否 | 是（metadata bits 编码） |
| 读屏障复杂度 | 极低（LRB 1 条 movptr 指令） | 较高（shift + test + slow path） |
| 压缩指针支持 | ✅（32-bit LRB） | ❌（指针 metadata 占用了压缩指针需要的 bit） |
| 重定位修复 | **mutator 被动**：通过前置字自动转发 | **mutator 主动**：self-healing CAS 修复字段 |
| 设计起源 | Baker (1978) forwarding pointer | Pauseless GC (Azul, 2005) |

## Object Layout

Shenandoah 的对象布局是在所有其他 HotSpot GC 共享的基础布局上，**在对象正前方额外插入一个 8-byte word**：

```
    ┌──────────────────────┐ ─── 对象开始
    │  Brooks Pointer Word │  ← Shenandoah 特有，8 bytes
    ├──────────────────────┤
    │  Mark Word           │  ← HotSpot 通用（锁/GC 年龄/哈希）
    ├──────────────────────┤
    │  Klass Pointer       │
    ├──────────────────────┤
    │  Instance Fields     │
    └──────────────────────┘
```

这个 Brooks pointer word 的语义：

- **对象未被重定位**：`fwdptr == 对象自身地址 - 8`（指向自己，等价于 null forward）
- **对象已被重定位**：`fwdptr == 新位置的 Brooks pointer word 地址`（指向 to-region 副本的 Brooks pointer）

注意它存的是 **Brooks pointer word 的地址**，不是对象自身的地址——这样 LRB 只需要一条 `movptr(dst, Address(dst, -8))` 指令就能拿到 forwarding 目标的 Brooks pointer，然后再解引用一次就是对象自身地址。

### 为什么是前置字不是后置字

Baker 的原始方案是把 forwarding pointer 存在对象 header 里（利用 mark word 空闲位）。Shenandoah 选择前置字的原因是：

1. **不破坏 HotSpot 通用对象布局**：mark word、klass pointer、实例字段的偏移量全部不变
2. **LRB 极简化**：`addr - 8` 永远是 Brooks pointer word，不需要在对象内部再做偏移计算
3. **对压缩指针友好**：32-bit LRB 只需把地址左移一位（Brooks pointer word 总是对齐的）

## Speculative Copy CAS 协议

Shenandoah 的并发重定位不依赖 mutator 主动 self-healing，而是 GC 线程**先抢先拷贝对象，然后用 CAS 更新 Brooks pointer word**。协议步骤：

### 并发 GC 线程拷贝

> 以下为**简化伪代码**，非 OpenJDK 实际源码。核心意图是传达 speculative copy + CAS 协议。

```cpp
void ShenandoahEvacuator::copy_object(oop src) {
  // 1. 目标 Region 分配空间（CAS 竞争 bump-pointer）
  address dst_buf = _tlab->alloc(oop_size(src));
  oop dst = (oop)dst_buf;

  // 2. 拷贝对象内容（mark word、klass pointer、实例字段全部复制）
  Copy::aligned_disjoint_words((HeapWord*)src, (HeapWord*)dst, obj_size);

  // 3. CAS 更新 Brooks pointer：把 src 的 fwdptr 从指向自己，改成指向 dst 的 Brooks pointer word
  //    src 的 Brooks pointer word 在 src - 8 处
  address src_fwdptr = (address)src - 8;
  address dst_fwdptr = (address)dst - 8;
  address prev_fwdptr = Atomic::cmpxchg(src_fwdptr, dst_fwdptr, src_fwdptr);

  if (prev_fwdptr != src_fwdptr) {
    // CAS 失败：另一个线程（GC 或 mutator）已经抢先拷贝了 src
    // 回滚自己的推测副本（归还 TLAB 空间），直接使用 prev_fwdptr 指向的副本
    _tlab->undo_alloc(obj_size);
  }
  // CAS 成功：src 的 Brooks pointer 现在指向我们的副本
}
```

### 竞争情况

当多个线程同时尝试拷贝同一个 from-region 对象时：

1. **只有一个 CAS 成功**，成为"权威副本"
2. 失败的 GC 线程回滚自己的推测副本，用 CAS 返回值（另一线程的副本）继续
3. 失败的 mutator 线程（正在写 from-region 对象）同样回滚自己的副本，改用另一个线程的副本执行写入

这个 CAS 协议是 Shenandoah 避免 STW 重定位的关键——**全程不需要暂停 mutator**，失败方回滚成本极低（只是归还 TLAB bump pointer）。

## Load Reference Barrier (LRB)

LRB 是 Shenandoah 唯一在读路径上的屏障，核心就是那条 movptr 指令：

```cpp
void ShenandoahBarrierSet::compile_resolve_oop() {
  __ movptr(dst, Address(dst, -8));  // dst - 8 == Brooks pointer word
}
```

**干了什么？** 从"可能是 Brooks pointer word 地址"变成"Brooks pointer word 内容本身"。整个过程是：

1. Java 线程读到一个堆对象引用 `ref`
2. LRB 执行 `ref = *(ref - 8)`，拿到 Brooks pointer word 里存的地址
3. 如果对象没被重定位，Brooks pointer 指向自己，`ref` 不变
4. 如果对象被重定位了，Brooks pointer 指向 to-region 副本的 Brooks pointer word，后续访问自动导向新位置

### Fast Path vs Slow Path

非分代 Shenandoah 的 LRB 实际上**没有显式 slow path 检查**——Brooks pointer word 要么指向自己（fast path 直接通过），要么指向新位置（LRB 自动转发）。这让 LRB fast path 比 ZGC load barrier fast path **更简单**——后者还需要一条 shift + test 检查 metadata bits。

### 与 ZGC Load Barrier 对比

| 维度 | Shenandoah LRB | ZGC Load Barrier |
| --- | --- | --- |
| Fast path 指令 | **1 条 movptr** | 1–2 条（shift + test，shift 同时剥离 metadata） |
| Slow path 频率 | 几乎零（只需解引用 Brooks pointer） | relocation 期间较高（self-healing CAS） |
| Mutator 做 GC 工作 | 很少（拷贝失败时回滚） | 较多（self-healing CAS 循环） |
| Relocation 完成后开销 | 几乎零（fwdptr 指向自身 → LRB 退化为恒等 mov） | 几乎零（metadata bits 全零 → fast path 直通） |

## 演进：Extra Word → Mark Word 编码

额外 word 带来了 per-object 8 bytes 开销。随着 LRB 优化和 GC 算法成熟，OpenJDK 社区找到了消除这部分开销的方法：**把 forwarding pointer 编码进对象的 mark word 里**（2020 年 JDK 实现，RFR JDK-8224584）。

### 编码原理

HotSpot mark word 的最低两位（bits 0-1）表示对象的锁状态：

| Bit 0 | Bit 1 | 状态 |
| --- | --- | --- |
| 00 | 00 | 未锁定 |
| 01 | 00 | 轻量级锁定 |
| 10 | 00 | 重量级锁定（monitor） |
| 11 | 00 | GC forwarded（Shenandoah 专用） |

当 Shenandoah 需要转发对象时，把 mark word 的最低两位置为 `0b11`（这是一个合法锁状态不会出现的组合），剩余 62 bits 存储 forwarding pointer。LRB 检测到 `0b11` 就知道需要走 forwarding 路径。

### 收益

- 消除了 per-object 8 bytes 额外开销
- 对象布局回归 HotSpot 通用格式
- LRB 只需检查 bits 0-1 是否为 `0b11`

### 代价

- mark word 的 GC 年龄 / 哈希等信息在 forwarded 期间**丢失**，需要额外备份
- forwarded 对象必须先"unforward"才能被 HotSpot 的 mark word 逻辑正确处理

分代 Shenandoah（JEP 404）仍然使用 mark word encoding——extra word 方案已经过时。

## References

1. [Shenandoah Proposal PDF (OpenJDK)](https://mail.openjdk.org/pipermail/hotspot-gc-dev/attachments/20160513/cde124dd/ShenandoahProposal.pdf) — Brooks 指针原始设计
2. [PPPJ 2016: Shenandoah: An open-source concurrent compacting GC](https://tech-notes.accel.dk/programming/java/java12/docs/PPPJ2016.pdf) — Baker 风格并发拷贝
3. [Shipilev: Shenandoah GC September 2017](https://shipilev.net/talks/vmm-Sep2017-shenandoah.pdf) — speculative copy 协议
4. [RFR JDK-8224584: Eliminate forwarding pointer word](https://mail.openjdk.org/archives/list/shenandoah-dev@openjdk.org/thread/ZMS7UZTPHHAWLNK35N6JT4WODB7YDORC/) — mark word 编码演进
5. [Baker: List Processing in Real Time on a Serial Computer](https://dl.acm.org/doi/10.1145/360625.360631) — 1978 原始 forwarding pointer 方案

## Links

- [Shenandoah 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [Shenandoah Barriers（LRB + SATB 写屏障）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)
- [Shenandoah Evacuation（speculative copy 全流程）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Evacuation.md)
- [ZGC Colored Pointers（对比：metadata bits vs per-object extra word）](/docs/CS/Java/JDK/JVM/GC/ZGC/ColoredPointers.md)
