## Introduction

`FastThreadLocal` 是 Netty 对 [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md) 的替代品，**它并不继承 `ThreadLocal`**（`public class FastThreadLocal<V>`，源码：`common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:47`），只是 API 长得像。

JDK 的 `ThreadLocal` 把变量存在线程的 `ThreadLocalMap` 里，这是一个用开放寻址法解决冲突的哈希表：每次 `get()` 都要算哈希、探测、可能触发 rehash。Netty 的做法是把这层哈希彻底去掉——**每个 `FastThreadLocal` 实例在构造时领到一个全局唯一的 `int index`，之后线程上的所有变量都放在一个 `Object[]` 里，用 `indexedVariables[index]` 直接寻址**。这一步从「哈希探测」退化成「数组下标」，是它名字里 Fast 的来源。

按下面顺序读：先看 Index Allocation 搞清 index 从哪来，再看 InternalThreadLocalMap 的数组结构与扩容，然后看 Variables To Remove 与 `removeAll()` 这套批量清理机制（这是它在线程池场景下不泄漏的关键），最后看 FastThreadLocalThread 为什么是快路径的前提。

## Index Allocation

index 由 `InternalThreadLocalMap` 的一个静态 `AtomicInteger` 全局单调分配，因此不同线程上同一个 `FastThreadLocal` 的下标是一致的，数组可以按同一个 layout 复用。

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:44
private static final AtomicInteger nextIndex = new AtomicInteger();
// Internal use only.
public static final int VARIABLES_TO_REMOVE_INDEX = nextVariableIndex();
```

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:149
public static int nextVariableIndex() {
    int index = nextIndex.getAndIncrement();
    if (index >= ARRAY_LIST_CAPACITY_MAX_SIZE || index < 0) {
        nextIndex.set(ARRAY_LIST_CAPACITY_MAX_SIZE);
        throw new IllegalStateException("too many thread-local indexed variables");
    }
    return index;
}
```

`VARIABLES_TO_REMOVE_INDEX` 在静态初始化时就抢到了 **0 号槽**，这个槽不放业务变量，而是放「本线程上已设置过的所有 `FastThreadLocal` 的强引用集合」，专门给 `removeAll()` 用（`InternalThreadLocalMap.java:46`）。上限 `ARRAY_LIST_CAPACITY_MAX_SIZE = Integer.MAX_VALUE - 8`（`InternalThreadLocalMap.java:51`），用完即抛 `IllegalStateException`——所以 `FastThreadLocal` 不能动态无限创建。

每个实例在构造时取号，`index` 是 `final`：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:126
private final int index;

public FastThreadLocal() {
    index = InternalThreadLocalMap.nextVariableIndex();
}
```

> [!NOTE]
>
> 这个常量早期叫 `variablesToRemoveIndex`（小写开头），自 **4.1.85.Final** 起改为 `InternalThreadLocalMap.VARIABLES_TO_REMOVE_INDEX` 这个 `public static final` 常量，并被 `FastThreadLocal` 静态导入（`FastThreadLocal.java:26`、`:61`、`:100`）。同一次改动（提交 `4573c91220`，fix `InternalThreadLocalMap.size()`）还重写了 `size()`，见 [size](#size)。

## InternalThreadLocalMap

`InternalThreadLocalMap` 是真正存数据的地方，核心就是一个 `Object[]`，初始长度 32 且全部预填 `UNSET` 哨兵对象（而不是 `null`）——因为「没设置」和「设置了 null」必须能区分。

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:54
private static final int INDEXED_VARIABLE_TABLE_INITIAL_SIZE = 32;

// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:61
/** Internal use only. */
public static final Object UNSET = new Object();

// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:166
private static Object[] newIndexedVariableTable() {
    Object[] array = new Object[INDEXED_VARIABLE_TABLE_INITIAL_SIZE];
    Arrays.fill(array, UNSET);
    return array;
}
```

读取就是一次数组下标，**越界不抛异常而是返回 `UNSET`**，把「数组还没扩到这么大」和「该槽位没设值」统一成同一个结果：

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:317
public Object indexedVariable(int index) {
    Object[] lookup = indexedVariables;
    return index < lookup.length? lookup[index] : UNSET;
}
```

### set

4.2 的写入路径比 4.1 多了一层：`set(V)` 直接委托给 `getAndSet(V)`，`set(V)` 不再自己判断 `value != UNSET`。

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:194
public final void set(V value) {
    getAndSet(value);
}

// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:208
public V getAndSet(V value) {
    if (value != InternalThreadLocalMap.UNSET) {
        InternalThreadLocalMap threadLocalMap = InternalThreadLocalMap.get();
        return setKnownNotUnset(threadLocalMap, value);
    }
    return removeAndGet(InternalThreadLocalMap.getIfSet());
}
```

`setKnownNotUnset` 用的是 `getAndSetIndexedVariable`（而不是 4.1 的 `setIndexedVariable`），靠「旧值是不是 `UNSET`」判断这是不是一个**新**变量，只有新变量才需要登记到待清理集合：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:230
private V setKnownNotUnset(InternalThreadLocalMap threadLocalMap, V value) {
    V old = (V) threadLocalMap.getAndSetIndexedVariable(index, value);
    if (old == UNSET) {
        addToVariablesToRemove(threadLocalMap, this);
        return null;
    }
    return old;
}
```

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:325
/**
 * @return {@code true} if and only if a new thread-local variable has been created
 */
public boolean setIndexedVariable(int index, Object value) {
    return getAndSetIndexedVariable(index, value) == UNSET;
}

// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:332
public Object getAndSetIndexedVariable(int index, Object value) {
    Object[] lookup = indexedVariables;
    if (index < lookup.length) {
        Object oldValue = lookup[index];
        lookup[index] = value;
        return oldValue;
    }
    expandIndexedVariableTableAndSet(index, value);
    return UNSET;
}
```

### expand

数组不够长时扩容。做法是把 index 用位移或操作「向上取整到 2 的幂」，`Arrays.copyOf` 后把新增区间填 `UNSET`。注意这里是**纯复制，没有 rehash**——这正是它比 `ThreadLocalMap` 便宜的地方，因为槽位与 index 是一一对应的，扩容不改变已有元素的下标。

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:343
private void expandIndexedVariableTableAndSet(int index, Object value) {
    Object[] oldArray = indexedVariables;
    final int oldCapacity = oldArray.length;
    int newCapacity;
    if (index < ARRAY_LIST_CAPACITY_EXPAND_THRESHOLD) {
        newCapacity = index;
        newCapacity |= newCapacity >>>  1;
        newCapacity |= newCapacity >>>  2;
        newCapacity |= newCapacity >>>  4;
        newCapacity |= newCapacity >>>  8;
        newCapacity |= newCapacity >>> 16;
        newCapacity ++;
    } else {
        newCapacity = ARRAY_LIST_CAPACITY_MAX_SIZE;
    }

    Object[] newArray = Arrays.copyOf(oldArray, newCapacity);
    Arrays.fill(newArray, oldCapacity, newArray.length, UNSET);
    newArray[index] = value;
    indexedVariables = newArray;
}
```

`ARRAY_LIST_CAPACITY_EXPAND_THRESHOLD = 1 << 30`（`InternalThreadLocalMap.java:49`）：超过 2^30 就不再做位扩散，直接一步顶到 `Integer.MAX_VALUE - 8`，避免位移溢出。

### get

`InternalThreadLocalMap.get()` 是快慢两条路的分支点：线程是 `FastThreadLocalThread` 就读它自己的字段，否则退化成 JDK `ThreadLocal`。

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:110
public static InternalThreadLocalMap get() {
    Thread thread = Thread.currentThread();
    if (thread instanceof FastThreadLocalThread) {
        return fastGet((FastThreadLocalThread) thread);
    } else {
        return slowGet();
    }
}

// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:119
private static InternalThreadLocalMap fastGet(FastThreadLocalThread thread) {
    InternalThreadLocalMap threadLocalMap = thread.threadLocalMap();
    if (threadLocalMap == null) {
        thread.setThreadLocalMap(threadLocalMap = new InternalThreadLocalMap());
    }
    return threadLocalMap;
}

// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:127
private static InternalThreadLocalMap slowGet() {
    InternalThreadLocalMap ret = slowThreadLocalMap.get();
    if (ret == null) {
        ret = new InternalThreadLocalMap();
        slowThreadLocalMap.set(ret);
    }
    return ret;
}
```

慢路径的 `slowThreadLocalMap` 定义在 `InternalThreadLocalMap` 自身（源码：`InternalThreadLocalMap.java:42-43`），不再依赖父类；`UnpaddedInternalThreadLocalMap` 因此变成了**空类并标记 `@Deprecated`**（源码：`common/src/main/java/io/netty/util/internal/UnpaddedInternalThreadLocalMap.java:18-23`），注释写明「4.1 不能删是为了兼容性，未来会移除」。

顺带说明：`DefaultThreadFactory` 产出的线程确实是 `FastThreadLocalThread`（`common/src/main/java/io/netty/util/concurrent/DefaultThreadFactory.java:121`），所以 Netty 自己的 EventLoop 线程天然走快路径。

### size

当前实现的 `size()` 不再遍历整个 `indexedVariables` 数组，而是**直接读 0 号槽那个 Set 的 size**，把「数非空槽」变成 O(1)（前面那批 `xx != null` 计数是 Netty 自己复用的几个内部 thread-local）。这是自 **4.1.85.Final** 起的修复——早期版本靠遍历数组再 `count - 1` 减掉 0 号槽，在槽位被复用时会算错：

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:203
Object v = indexedVariable(VARIABLES_TO_REMOVE_INDEX);
if (v != null && v != InternalThreadLocalMap.UNSET) {
    @SuppressWarnings("unchecked")
    Set<FastThreadLocal<?>> variablesToRemove = (Set<FastThreadLocal<?>>) v;
    count += variablesToRemove.size();
}

return count;
```

## Variables To Remove

这是 `FastThreadLocal` 与普通 `ThreadLocal` 差异最大的一块设计。0 号槽存的是一个 **identity 语义的 Set**，里面是「本线程上已经写过值的每个 `FastThreadLocal` 的强引用」：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:98
private static void addToVariablesToRemove(InternalThreadLocalMap threadLocalMap, FastThreadLocal<?> variable) {
    Object v = threadLocalMap.indexedVariable(VARIABLES_TO_REMOVE_INDEX);
    Set<FastThreadLocal<?>> variablesToRemove;
    if (v == InternalThreadLocalMap.UNSET || v == null) {
        variablesToRemove = Collections.newSetFromMap(new IdentityHashMap<FastThreadLocal<?>, Boolean>());
        threadLocalMap.setIndexedVariable(VARIABLES_TO_REMOVE_INDEX, variablesToRemove);
    } else {
        variablesToRemove = (Set<FastThreadLocal<?>>) v;
    }

    variablesToRemove.add(variable);
}
```

用 `IdentityHashMap` 是因为 `FastThreadLocal` 通常不重写 `equals()` / `hashCode()`，按对象身份去重才对。有加就有删，`removeAndGet()` 里会同步摘掉（`FastThreadLocal.java:112-124`）。

### removeAll

有了这个 Set，「把线程上所有 `FastThreadLocal` 清干净」就变成一次遍历，而 JDK `ThreadLocal` 没有等价能力（只能找到你手里握着引用的那几个）：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocal.java:54
public static void removeAll() {
    InternalThreadLocalMap threadLocalMap = InternalThreadLocalMap.getIfSet();
    if (threadLocalMap == null) {
        return;
    }

    try {
        Object v = threadLocalMap.indexedVariable(VARIABLES_TO_REMOVE_INDEX);
        if (v != null && v != InternalThreadLocalMap.UNSET) {
            @SuppressWarnings("unchecked")
            Set<FastThreadLocal<?>> variablesToRemove = (Set<FastThreadLocal<?>>) v;
            FastThreadLocal<?>[] variablesToRemoveArray =
                    variablesToRemove.toArray(new FastThreadLocal[0]);
            for (FastThreadLocal<?> tlv: variablesToRemoveArray) {
                tlv.remove(threadLocalMap);
            }
        }
    } finally {
        InternalThreadLocalMap.remove();
    }
}
```

先拷贝成数组再遍历，避免 `remove` 过程中修改 Set 触发 `ConcurrentModificationException`；最后 `InternalThreadLocalMap.remove()` 把 map 本身从线程上摘掉（`InternalThreadLocalMap.java:136-143`）。每个 `tlv.remove()` 会走 `removeAndGet()`，触发用户可覆盖的 `onRemoval(V)` 钩子（`FastThreadLocal.java:277-293`、`:307`）。

它的调用点全都落在「线程即将不再属于我」的时刻：

| 调用点 | 源码位置 | 场景 |
| --- | --- | --- |
| `FastThreadLocalRunnable.run()` 的 `finally` | `common/src/main/java/io/netty/util/concurrent/FastThreadLocalRunnable.java:28-34` | 任务跑完即清理，配合线程池复用 |
| `FastThreadLocalThread.runWithFastThreadLocal()` 的 `finally` | `common/src/main/java/io/netty/util/concurrent/FastThreadLocalThread.java:176-181` | 4.2.2 起新增，虚拟线程等非继承场景 |
| `SingleThreadEventExecutor` 终止 / 线程归还 | `common/src/main/java/io/netty/util/concurrent/SingleThreadEventExecutor.java:1305`、`:1322` | EventLoop 关闭，见 issue #6596 |

也就是说：池化线程被复用时，上一轮任务留下的 `FastThreadLocal` 值不会「串味」到下一轮，也不会因为线程长期存活而累积成事实泄漏。`FastThreadLocalRunnable` 只在 `FastThreadLocalThread` 带 `Runnable` 的构造里包一层（此时 `cleanupFastThreadLocals = true`，`FastThreadLocalThread.java:47-50`）。

## FastThreadLocalThread

快路径的前提是线程上有一个**普通字段**存 map，不必走 `Thread.currentThread().threadLocals` 的哈希表：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/FastThreadLocalThread.java:41
private InternalThreadLocalMap threadLocalMap;
```

`getIfSet()` 只读不建，这也是 `removeAll()`、 `getIfExists()`、`isSet()` 用它的原因——避免为了「查一下」而白白创建 map（`InternalThreadLocalMap.java:102-108`）。

> [!NOTE]
>
> **4.2 新增（4.2.2.Final，提交 `6c8e8500f0`）了虚拟线程等「无法继承 `FastThreadLocalThread`」场景的兜底**：`FastThreadLocalThread.runWithFastThreadLocal(Runnable)`（`FastThreadLocalThread.java:163-182`）把当前线程 id 记进一个不可变的 `FallbackThreadSet`（位图 + `LongLongHashMap`，`:201-255`），此后 `currentThreadHasFastThreadLocal()` 返回 `true`，Netty 的 Recycler / allocator 会像对待真 `FastThreadLocalThread` 一样启用优化，退出时同样调用 `FastThreadLocal.removeAll()`。文档注释明确说「目前这个兜底底层仍是普通 `ThreadLocal`，未来若语义可保、性能够好会换成 scoped values」（`:158-159`）。
>
> 另外 `FastThreadLocalThread` 提供 `permitBlockingCalls()`，默认返回 `false`（`:194-196`）——EventLoop 线程用它表达「禁止阻塞调用」。

## Cache Line

`InternalThreadLocalMap` 尾部有一组 padding 字段，目的是让实例在开启压缩指针时也占满 128 字节，避免与相邻对象落在同一缓存行造成伪共享：

```java
// 源码：common/src/main/java/io/netty/util/internal/InternalThreadLocalMap.java:83
/** @deprecated These padding fields will be removed in the future. */
public long rp1, rp2, rp3, rp4, rp5, rp6, rp7, rp8;
```

两个容易记错的细节：是 **8 个 `long`（`rp1`~`rp8`）不是 9 个**；并且当前版本已给这段加了 `@deprecated`，注释说未来会移除——`@Contended` 普及之后这种手写 padding 的必要性在下降。

## ThreadLocal vs FastThreadLocal

| 维度 | JDK `ThreadLocal` | Netty `FastThreadLocal` |
| --- | --- | --- |
| 定位方式 | `ThreadLocalMap` 开放寻址哈希探测，需算 hash、线性探测 | `Object[]` 按 `index` 直接寻址，O(1) 无探测 |
| 扩容 | 容量过半就 rehash，元素位置全部重排 | `Arrays.copyOf` 纯复制，下标不变、不 rehash |
| key 引用强度 | `ThreadLocalMap.Entry` 弱引用 key，value 强引用 → 易出现 `null` key 的脏 value，靠 `get`/`set` 顺带 `expungeStaleEntry` 清理 | 0 号槽强引用持有所有 `FastThreadLocal`，无 stale entry 问题，但 `FastThreadLocal` 实例本身被线程持有 |
| 批量清理 | 无等价能力，只能逐个 `remove()` | `removeAll()` 一次遍历全清（`FastThreadLocal.java:54`） |
| null 值 | 用 `null` 表示未初始化 | 用 `UNSET` 哨兵区分「未设置」与「设为 null」（`InternalThreadLocalMap.java:61`） |
| 非配套线程 | 天然可用 | 退化为 `slowThreadLocalMap`（`InternalThreadLocalMap.java:127`），拿不到性能收益 |
| 移除钩子 | 只有 `ThreadLocal.remove()`，无回调 | 可覆盖 `onRemoval(V)`（`FastThreadLocal.java:307`） |

一句话取舍：`FastThreadLocal` 用「全局 index + 每个线程一个数组」换掉了哈希，代价是**必须配合 `FastThreadLocalThread`** 且 index 不可无限增长，收益是热路径上少了哈希探测、以及线程池场景下有可靠的批量清理。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [Memory Pool](/docs/CS/Framework/Netty/memory.md)
- [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)

## References

1. [FastThreadLocal (Netty API Reference 4.2)](https://netty.io/4.2/api/io/netty/util/concurrent/FastThreadLocal.html)
2. [ThreadLocals and FastThreadLocals in Netty — Netty.io Wiki](https://netty.io/wiki/thread-local.html)
3. [A faster ThreadLocal — Netty news](https://netty.io/news/2012/05/11/a-faster-threadlocal.html)
