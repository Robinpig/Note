## Introduction

原子操作和内存屏障是一切锁的基石：spinlock 靠 `cmpxchg` 抢锁，RCU 靠 `smp_store_release` 发布指针，seqlock 靠序号与屏障配对。理解同步机制，必须先理解"编译器与 CPU 都会重排你的代码"。

重排有两个来源：

1. **编译器重排**：在单线程语义不变的前提下，编译器可自由移动读写指令；
2. **CPU 重排**：乱序执行、store buffer 延迟写回等。不同架构的内存模型不同——**x86 是强序模型**（TSO，只允许 store 之后的 load 被提前），**ARM/PowerPC 是弱序模型**（load/load、load/store 都可能重排），后者的乱序收益更大，但也要求更谨慎的屏障。

## Atomic Operations

整型原子操作接口（`include/linux/atomic.h`）：

```c
atomic_t v = ATOMIC_INIT(0);

atomic_inc(&v);                  /* 加 1 */
atomic_dec_and_test(&v);         /* 减 1 并判断是否为 0：引用计数释放的经典写法 */
atomic_add(3, &v);
atomic_cmpxchg(&v, old, new);    /* 比较并交换，返回旧值 */
atomic_xchg(&v, new);
atomic_fetch_or(mask, &v);
```

指针与位操作：`cmpxchg()`（通用，任意宽度）、`xchg()`、`test_and_set_bit()`、`set_bit()`/`clear_bit()`。

需要注意的取舍：

- **`atomic_t` 是"无记忆"的**：它只保证单次操作原子，不保证与其他内存访问的先后顺序，也不提供任何互斥；
- **引用计数优先用 `refcount_t` / `kref`**：`refcount_t` 会检测"从 0 再增"（use-after-free 的典型症状）与溢出；`kref` 在此之上封装了"引用归零时调用 release 回调"的对象生命周期模式；
- **32 位平台上的 64 位原子**：`atomic64_t` 可能退化为加锁实现（`CONFIG_GENERIC_ATOMIC64`），性能要留心。

## Compile-Time Barriers and Single Access

```c
barrier();                       /* 仅阻止编译器重排，不生成指令 */
READ_ONCE(x);  WRITE_ONCE(x, v); /* 保证访问是单次的（不被拆开/合并/缓存到寄存器） */
```

`READ_ONCE`/`WRITE_ONCE` 解决的是 C 语言层面的问题：编译器可能把循环里的读取提升为寄存器缓存（导致永远读不到其他 CPU 的写入），也可能把一次访问拆成多次。内核文档将其称为 **KCSAN 关注的"标记式访问"**——用它们标记那些有意不加锁的并发访问点。

## SMP Memory Barriers

```c
smp_mb();    /* 全屏障：之前的读写全部先于之后的读写 */
smp_rmb();   /* 读屏障 */
smp_wmb();   /* 写屏障 */
smp_load_acquire(&p);          /* 获取语义：之后的访问不会提前到它前面 */
smp_store_release(&p, v);      /* 释放语义：之前的访问不会推迟到它后面 */
```

`acquire`/`release` 是使用成本最低的一对语义，恰好对应"发布-订阅"模式：

```c
/* 写侧：先初始化对象，再发布指针 */
obj->data = 42;
smp_store_release(&global_ptr, obj);

/* 读侧：先取指针，再访问对象内容 */
struct obj *p = smp_load_acquire(&global_ptr);
if (p)
        use(p->data);            /* 保证看到 42 */
```

在 x86 上，`store_release`/`load_acquire` 几乎不需要额外指令（强序），而 ARM 上会生成 `stlr`/`ldar`——这就是"同一份内核代码在不同架构上开销不同"的原因。

`dma_wmb()`/`dma_rmb()` 用于与设备 DMA 交互（不保证与 CPU 缓存的交互顺序）；带 `virt_` 前缀的版本用于虚拟化场景。

## Common Misconceptions

- 用 `atomic_t` 保护**多个**变量的一致性——原子性只覆盖单个变量，复合不变量仍需要锁；
- 以为 `barrier()` 能解决多核可见性——它只约束编译器，`smp_mb()` 才是硬件屏障；
- 在无锁代码里漏掉 `READ_ONCE`，让编译器把循环读取优化成死循环；
- 在 32 位平台用 `atomic64_t` 做高频计数。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
