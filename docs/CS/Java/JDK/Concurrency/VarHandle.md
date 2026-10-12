## Introduction

[VarHandle](/docs/CS/Java/JDK/Concurrency/VarHandle.md) 是 `java.lang.invoke` 下的一个**动态强类型的变量引用**：它像一根类型安全的「指针」，指向某个实例字段、静态字段、数组元素或堆外数据结构的分量，并支持在一组**访问模式（access mode）**下读写——从无排序约束的 plain 访问，到 volatile 语义，再到 CAS 与 get-and-add。它随 **JDK 9（JEP 193: Variable Handles）** 引入，设计目标是给 `java.util.concurrent.atomic` 与 `sun.misc.Unsafe` 的底层操作一个**标准、安全、可移植**的统一入口。

JEP 193 的动机很直白：在 VarHandle 之前，想对「自己类的单个字段」做原子/有序操作只有三条路，每条都有硬伤——

- 包一个 [AtomicInteger](/docs/CS/Java/JDK/Concurrency/Atomic.md)：多一层间接与额外并发状态；
- 用 [FieldUpdater](/docs/CS/Java/JDK/Concurrency/Atomic.md)：基于反射，开销常常大于操作本身；
- 直接上 [Unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)：无类型检查、不可移植、不受支持，却因为能落到 intrinsic 而被大量使用。

JEP 193 为此定了四个目标：**Safety**（不可能把 JVM 搞进损坏的内存状态，字段只能写入可转型的值、数组下标不能越界）、**Integrity**（与 `getfield`/`putfield` 同样的访问规则，`final` 字段不可写）、**Performance**（与 Unsafe 等价操作的生成码几乎一致）、**Usability**（比 Unsafe 好用的 API）。

> [!NOTE]
>
> 本文事实以 **JDK 25（jdk-25+36）** 源码核实：`java.lang.invoke.VarHandle`、`java.lang.invoke.MethodHandles`、`java.util.concurrent.atomic.AtomicInteger`、`java.util.concurrent.Exchanger`。

## Coordinate Types and Signature Polymorphism

一个 VarHandle 由两部分刻画出它能访问的全部变量：

- **varType** `T`：被访问变量的类型；
- **coordinateTypes** `CT1, ..., CTn`：定位变量所需的**坐标表达式**类型——实例字段的坐标是接收者，数组元素的坐标是「数组 + 下标」，静态字段没有坐标。

```java
String[] sa = ...;
VarHandle avh = MethodHandles.arrayElementVarHandle(String[].class);
// 坐标类型是 String[] 和 int，变量类型是 String
boolean r = avh.compareAndSet(sa, 10, "expected", "new");
```

每个访问模式对应一个**签名多态（signature polymorphic）**方法。它们在源里看起来能收任意参数、返回任意类型，但编译成 `invokevirtual` 时，编译器必须把实际参数类型记进**符号类型描述符**，且**不做方法调用转换**——参数按自身未转换的类型压栈。这与 `invokedynamic` 的 MethodHandle 调用是两套机制，也意味着这些方法不能通过反射调用。

常用工厂方法（均为 `@since 9`）：

| 工厂 | 坐标类型 | 说明 |
| --- | --- | --- |
| `Lookup.findVarHandle(Class, String, Class)` | 接收者类型 | 实例字段；`NoSuchFieldException` / `IllegalAccessException` |
| `Lookup.findStaticVarHandle(Class, String, Class)` | 无 | 静态字段 |
| `MethodHandles.arrayElementVarHandle(Class)` | 数组 + `int` | 任意数组的元素（`AtomicIntegerArray` 即用它） |
| `MethodHandles.byteArrayViewVarHandle` / `byteBufferViewVarHandle` | `byte[]` / `ByteBuffer` + `int` | 把字节数据视图化成其它基础类型的数组 |

## Access Modes

访问模式同时决定**原子性**与**顺序性**，是一条逐级增强的阶梯：

| 层级 | 读 | 写 | 语义 |
| --- | --- | --- | --- |
| plain | `get` | `set` | 仅对引用与 ≤32 位原语保证 bitwise 原子；**不施加任何跨线程可观察的顺序约束** |
| opaque | `getOpaque` | `setOpaque` | bitwise 原子，且对**同一变量**的访问相干有序（coherently ordered） |
| acquire / release | `getAcquire` | `setRelease` | 在 opaque 之上：acquire 读及其后的访问，不会重排到匹配的 release 写及其之前的访问之前 |
| volatile | `getVolatile` | `setVolatile` | 在 acquire/release 之上：所有 volatile 操作彼此**全序** |

按功能分组，访问模式方法还有（每组都有 `Plain / Acquire / Release / Volatile` 的排序变体）：

- **原子更新**：`compareAndSet`、`weakCompareAndSet` / `weakCompareAndSetPlain` / `weakCompareAndSetAcquire` / `weakCompareAndSetRelease`、`compareAndExchange` / `compareAndExchangeAcquire` / `compareAndExchangeRelease`、`getAndSet` 及 Acquire/Release 变体；
- **数值原子更新**：`getAndAdd` 及 Acquire/Release 变体；
- **位运算原子更新**：`getAndBitwiseOr` / `getAndBitwiseAnd` / `getAndBitwiseXor` 及 Acquire/Release 变体。

三条容易踩的规则：

1. **访问模式覆盖声明站点的排序**。字段声明了 `volatile`，但用 `get`（plain）访问，就按 plain 语义走——混合访问（mixed access）在 JMM 下可能给出意外结果。
2. **`get`/`set` 的原子性有平台例外**：32 位平台上对 `long`/`double` 的 plain 访问不保证原子（这正是 JMM 里「非原子 64 位操作」的由来，见 [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)）；除工厂方法另有说明外，其余读写模式对引用和所有原语都提供原子访问。
3. **弱 CAS 允许伪失败**。`weakCompareAndSet*` 可能无缘无故返回 `false`（典型原因是内存竞争），且 `weakCompareAndSetPlain` **不建立任何 happens-before**——只适合统计计数器这类与其它排序无关的场景；需要排序保证用 `weakCompareAndSet`（volatile 语义）。

引用 `final` 字段的 VarHandle 只支持读模式，写/原子更新模式调用时抛 `UnsupportedOperationException`（JEP 193 的 Integrity 目标）。

## Memory Fences

除了访问模式，VarHandle 还提供一组**静态 fence 方法**做细粒度内存排序控制——JEP 193 明确把它定位为 Unsafe 那套非标准 fence 操作的标准替代：

| 方法 | 保证 | C11 对应 |
| --- | --- | --- |
| `fullFence()` | fence 前的 load/store 不与 fence 后的 load/store 重排 | `atomic_thread_fence(memory_order_seq_cst)` |
| `acquireFence()` | fence 前的 load 不与 fence 后的 load/store 重排 | `atomic_thread_fence(memory_order_acquire)` |
| `releaseFence()` | fence 前的 load/store 不与 fence 后的 store 重排 | `atomic_thread_fence(memory_order_release)` |
| `loadLoadFence()` | fence 前的 load 不与 fence 后的 load 重排 | LoadLoad barrier |
| `storeStoreFence()` | fence 前的 store 不与 fence 后的 store 重排 | StoreStore barrier |

源码里 `acquireFence`/`releaseFence` 分别落到 `UNSAFE.loadFence()` / `UNSAFE.storeFence()`，`fullFence` 落到 `UNSAFE.fullFence()`——API 是标准的，实现仍借道 Unsafe。

在 x86-TSO 上，load-acquire / store-release **不需要任何屏障指令**（硬件模型已保证），真正的开销只有 `fullFence` 对应的 `lock` 前缀指令或 `mfence`。这也是 [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md) 中「无竞争的同步几乎免费」的硬件依据。

## Examples

**原子计数器**——一行 `getAndAdd` 替代 `AtomicLong` 包装，排序由访问模式全权决定：

```java
public class Counter {
    private static final VarHandle COUNT;
    static {
        try {
            COUNT = MethodHandles.lookup().findVarHandle(Counter.class, "count", long.class);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }
    private long count;            // 注意：不需要声明 volatile

    public long next() {
        return (long) COUNT.getAndAdd(1L);
    }
}
```

**发布 / 订阅**——release 写与 acquire 读配对，数据发布无需锁：

```java
// 发布方：先写数据，再 release 写标志位
data = payload;
READY.setRelease(this, 1L);

// 订阅方：acquire 读标志位，成功后必见 data
if ((long) READY.getAcquire(this) == 1L) {
    use(data);                    // 不会看到旧的 data
}
```

** fence 的粗粒度用法**——JDK 内部在 `VarHandle.updateVarForm` 里就是这样用 `UNSAFE.fullFence()` 保证 VarForm 切换对所有线程可见。

## VarHandle in the JDK: Facts vs Myths

一个流行说法是「JDK 9 之后并发包内部都改用 VarHandle 了」。核对 JDK 25 源码后，**这个说法只对了一半**：

| 类 | JDK 25 实际实现 | 依据 |
| --- | --- | --- |
| `AtomicIntegerArray` / `AtomicLongArray` / `AtomicReferenceArray` | **VarHandle**（`MethodHandles.arrayElementVarHandle`） | 源码 `private static final VarHandle AA` |
| `CompletableFuture` | **VarHandle**（`RESULT` / `STACK` / `NEXT` 三个，经 `MhUtil.findVarHandle` 获取） | `CompletableFuture.java:3029-3036` |
| `Exchanger` | **VarHandle**（`BOUND` / `MATCH` / `ENTRY` 三个） | `Exchanger.java:530-532` |
| `AtomicInteger` / `ThreadLocalRandom` / `Striped64` | **仍是 `jdk.internal.misc.Unsafe`** | `AtomicInteger.java:58-61` 注释原文 |

`AtomicInteger` 源码里的注释把原因说得很清楚：

```java
/*
 * This class intended to be implemented using VarHandles, but there
 * are unresolved cyclic startup dependencies.
 */
private static final Unsafe U = Unsafe.getUnsafe();
```

即：**不是不想用，是启动期循环依赖（`java.lang.invoke` 初始化早于 `java.util.concurrent.atomic`）还没解**。所以「VarHandle 已全面取代 Unsafe」在 JDK 25 仍不成立——评价「现在实际用什么」要读字段声明，不是读 API 表面。

另有一个 API 表面对齐的细节：`AtomicInteger.lazySet` 的语义在 JDK 25 源码里标注为 `VarHandle#setRelease`，实现是 `U.putIntRelease(...)`——早期文档里「lazySet 是 lazy 的写」这种直觉描述，与 release 语义的规格表述并不等价，写内存序推理时以后者为准。

## Links

- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)
- [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [JEP 193: Variable Handles](https://openjdk.org/jeps/193)
2. [VarHandle (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/VarHandle.html)
3. [MethodHandles (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/MethodHandles.html)
4. [JDK-8046183: JEP 193: Variable Handles](https://bugs.openjdk.org/browse/JDK-8046183)
