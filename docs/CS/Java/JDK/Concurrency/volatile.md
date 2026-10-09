## Introduction

`volatile` 是 Java 内存模型（JMM）里最轻量的同步手段。它不涉及上下文切换、不阻塞线程、不需要加锁，
但也正因为轻，它能提供的保证非常**窄**——只有「可见性」和「有序性」，**没有互斥性**。
绝大多数关于 volatile 的误解都源于把它当成「轻量的锁」。

一句话概括契约：

> 对一个 volatile 变量的写，**happens-before** 后续对它的读。

这条单一规则经 JSR-133 补齐（原始 JMM 里 volatile 与非 volatile 变量的访问可以自由重排，等于没有语义）。
它精确地给出两件事：写线程的修改对读线程可见；且编译器与处理器不得把写之后的操作重排到写之前、把读之前的操作重排到读之后。
但它**不含**任何「两个线程同时更新会怎样」的保证——那需要原子类或锁。

## Two Guarantees, Not Three

JMM 里与 volatile 相关的三条性质要分清，前两条由 volatile 提供，第三条不由它提供：

| 性质 | 含义 | volatile 是否提供 |
| --- | --- | --- |
| **可见性（visibility）** | 一个线程的写，其他线程能看到 | ✅ |
| **有序性（ordering）** | 编译器/CPU 不跨越 volatile 读写重排 | ✅ |
| **原子性（atomicity）** | 复合操作不可被分割 | ❌ **不提供** |

最直接的反例是 `count++`。它在字节码层面是「读-改-写」三条指令的组合：

```java
volatile int count = 0;
count++;    // 等价于 count = count + 1，volatile 拦不住这一步的交错
```

两个线程同时执行 `count++`，即使变量是 volatile，最终结果也可能是 1 而不是 2——两个线程可能读到同一个初值 0，
各自写回 1，后者覆盖前者。要让复合操作原子化，只能靠 `synchronized`（隐含互斥）或
[Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md) 里的 CAS（`AtomicInteger.incrementAndGet`）。

顺带一个更隐蔽的推论：**`volatile` 变量的读写本身是原子的，但仅限「单次读/单次写」**。
这正是 `volatile int` 可以用来做跨线程的原子标志位（flag toggling）而 `volatile long` 也能这么用的原因——
JMM 规定 32 位以下的单次读写天然原子，`long`/`double` 的单次读写在 **64 位 JVM 上也保证原子**（JLS 17.7，非 volatile 的 long/double 写可能被拆成两次 32 位写）。

## The Safe Pattern

`volatile` 适合的场景有一个共同的形状：**某个状态的变化由一个线程写入，其它线程只读；写方不依赖读方**。
这正是原书列出的三个使用前提——写入不依赖当前值（或只有一个线程会写）、变量不与其他状态变量构成不变式、访问它时不需要加锁。

```java
private volatile boolean running = true;

public void shutdown() { running = false; }        // 只写
public boolean isRunning() { return running; }     // 只读
```

反例是把 volatile 用来保护不变式。下面的代码即使给 `base` 加 volatile 也是错的，
因为「读 base → 算 sum → 写 sum」不是原子操作，另一个线程可以在任意两步之间插进来，读到不一致的组合：

```java
private volatile int base = 0;      // 加 volatile 也救不了
private int sum = base + offset;   // 别的线程可能观察到 base 已更新、sum 未更新
```

要保护这种复合不变式，必须用锁把**整段**临界区包起来，或者用 `AtomicInteger` 之类的原子类把复合操作收敛成单条 CAS。
判断标准很简单：**如果你需要「读到的一定是配套的另一个变量的最新值」，就需要锁，而不是 volatile。**

## Double-Checked Locking

这是 volatile 最著名的用武之地，也是它最著名的坑。双检锁要解决的是「并发初始化昂贵对象时不要重复构造」：

```java
private volatile Singleton instance;    // volatile 绝不能省

public Singleton getInstance() {
    if (instance == null) {                       // 第一次检查：无锁快速路径
        synchronized (this) {
            if (instance == null) {               // 第二次检查：持锁复查
                instance = new Singleton();
            }
        }
    }
    return instance;
}
```

**为什么 volatile 不能省**——这是 Java 内存模型里最著名的结论（有专门论文《The "Double-Checked Locking is Broken" Declaration》）。
`new Singleton()` 不是一步完成的，它大致是三步：① 分配内存；② 调用构造器初始化对象；③ 把内存地址赋给变量 `instance`。
JMM 允许 ① 和 ② 之间、② 和 ③ 之间与后续读发生重排（**as-if-serial 只保证单线程内不改变语义，不禁止跨线程观察中间态**）。
于是可能出现：线程 B 在线程 A 执行完 ①、还没执行 ③ 时读到了 `instance != null`（非 null 但对象字段全是默认值 0/null），
直接返回一个**半构造**的对象——后续所有访问都可能读到 null 或 0。

`volatile` 的作用是给「② 写字段」和「③ 赋引用」之间插入 StoreStore 屏障，禁止 ③ 提前到 ② 之前。
于是 B 要么看到 null（继续走加锁路径），要么看到一个**完全构造好**的对象，二者必居其一。

顺带一提，Java 5 之后其实有更省心的写法——**静态初始化 holder 惯用法**，靠类初始化的 JVM 保证替代手工屏障：

```java
private static class Holder {
    static final Singleton INSTANCE = new Singleton();
}
public static Singleton getInstance() { return Holder.INSTANCE; }
```

但它要求单例是 `static` 的，双检锁可用于实例字段，所以两者并不互相替代。

## Volatile Reference Trap

还有一个高频错误：只给引用类型的字段加 volatile，就以为它指向的对象「深度不可变」了。实际上 `volatile` 只保证
**引用本身**的写入有序可见，完全不保证**被引用对象的内部状态**是否可见：

```java
class Config {
    int timeoutMs;                    // 没有 volatile！
    boolean enabled;
}
private volatile Config config;       // 只保证 config 这个引用的替换是可见的
```

线程 B 通过 `config.enabled` 读到的是**写线程当时的快照**，之后写线程改 `config.timeoutMs` 可能永远不被 B 看到。
**结论：volatile 字段必须引用不可变对象**，被引用对象的所有可变状态都要自己保证可见性。

## Ordering and Barriers

从语义到实现的翻译是：**JMM 要求在每个 volatile 写之后、或每个 volatile 读之前插入 StoreLoad 屏障**。
注意 JMM 采取的是保守策略而非最小屏障集合。JEP-133 之后 HotSpot 的做法是统一收敛为写后插 StoreLoad：

```cpp
CASE(_putstatic):
        {
          // ...
          if (cache->is_volatile()) {
            // ...
            OrderAccess::storeload();
          } else {
            // ...
          }
        }
```

选「写后」而非「读前」是出于实际收益的权衡：volatile 的常见用法是**一个写线程对多个读线程**。
读线程数量远多于写线程时，把屏障放在写之后（每个写线程付一次成本），比放在读之前（每个读线程各付一次）划算得多。
这体现了 JMM 实现上的一贯取舍：**先保证正确性，再追求执行效率**。

在 x86 上，四种屏障的代价极不对称：

```cpp
// x86
inline void OrderAccess::loadload()   { compiler_barrier(); }
inline void OrderAccess::storestore() { compiler_barrier(); }
inline void OrderAccess::loadstore()  { compiler_barrier(); }
inline void OrderAccess::storeload()  { fence();            }
```

x86 是强内存序架构，硬件层面只有 StoreLoad（写后读）需要显式屏障，前三种只需阻止编译器重排（编译器屏障）。
所以 JMM 的要求落到 x86 上只剩一个 `storeload()`，而它必须用带 `lock` 前缀的指令实现：

```cpp
inline void OrderAccess::fence() {
  // always use locked addl since mfence is sometimes expensive
#ifdef AMD64
  __asm__ volatile ("lock; addl $0,0(%%rsp)" : : : "cc", "memory");
#else
  __asm__ volatile ("lock; addl $0,0(%%esp)" : : : "cc", "memory");
#endif
  compiler_barrier();
}
```

用 `lock; addl $0,0(%rsp)` 而不是 `mfence` 是因为 AMD 架构上 `mfence` 开销明显更高，而空操作的 `lock addl` 同样能触发
「原子操作 + 全内存屏障」双重效果。`lock` 前缀本身提供两个能力：

- 使被修饰的指令成为**原子的**，执行期间锁住所涉及的 cache line，其它核不能存取其中缓存的对应 cache line；
- 同时提供**内存屏障**效果。

这条 x86 强序性的推论解释了 volatile 在 x86 上比在 ARM 上便宜得多：在 x86 上，`volatile int` 的读几乎零成本（只多一个编译器屏障），
只有写要付 `lock` 前缀的代价；而在 ARM 这类弱序架构上，每种屏障都需要对应硬件指令。

## Links

- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)

## References

1. [The "Double-Checked Locking is Broken" Declaration](https://www.cs.umd.edu/~pugh/java/memoryModel/DoubleCheckedLocking.html)
2. [关于汇编：在 x86 上，哪个更好的写障碍是：lock + addl 或 xchgl？](https://www.codenong.com/4232660/)
3. [汇编指令的 LOCK 指令前缀](https://dslztx.github.io/blog/2019/06/08/%E6%B1%87%E7%BC%96%E6%8C%87%E4%BB%A4%E7%9A%84LOCK%E6%8C%87%E4%BB%A4%E5%89%8D%E7%BC%80/)
4. [JLS SE 25, §17.4 Memory Model](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html)
5. [JSR-133: Java Memory Model and Thread Specification Revision](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr133.pdf)