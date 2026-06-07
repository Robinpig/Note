## Introduction

[ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md) 的一个特殊变体，当从 FastThreadLocalThread 访问时，能提供更高的访问性能。

在内部，**FastThreadLocal 使用数组中的常量索引**，而不是使用哈希码和哈希表来查找变量。
虽然看似微不足道，但它比使用哈希表具有轻微的性能优势，在频繁访问时非常有用。
要利用此线程局部变量，你的**线程必须是 FastThreadLocalThread 或其子类型**。
默认情况下，`DefaultThreadFactory` 创建的所有线程都是 FastThreadLocalThread，原因就在于此。
请注意，**快速路径仅在继承 FastThreadLocalThread 的线程上可用**，因为它需要一个特殊字段来存储必要的状态。
任何其他类型的线程访问都会回退到常规的 ThreadLocal。



## 使用 FastThreadLocal

**FastThreadLocal 不继承 ThreadLocal。**

```java
public class FastThreadLocal<V> {

    private static final int variablesToRemoveIndex = InternalThreadLocalMap.nextVariableIndex();
  
   private final int index;

    public FastThreadLocal() {
        index = InternalThreadLocalMap.nextVariableIndex();
    }
  ...
}
```



### set

```java
public final void set(V value) {
    if (value != InternalThreadLocalMap.UNSET) {
        InternalThreadLocalMap threadLocalMap = InternalThreadLocalMap.get();
        setKnownNotUnset(threadLocalMap, value);
    } else {
        remove();
    }
}

private void setKnownNotUnset(InternalThreadLocalMap threadLocalMap, V value) {
    if (threadLocalMap.setIndexedVariable(index, value)) {
        addToVariablesToRemove(threadLocalMap, this);
    }
}

// 当且仅当创建了新的线程局部变量时返回 true
public boolean setIndexedVariable(int index, Object value) {
    Object[] lookup = indexedVariables;
    if (index < lookup.length) {
        Object oldValue = lookup[index];
        lookup[index] = value;
        return oldValue == UNSET;
    } else {
        expandIndexedVariableTableAndSet(index, value);
        return true;
    }
}
```



#### expand

```java
private void expandIndexedVariableTableAndSet(int index, Object value) {
    Object[] oldArray = this.indexedVariables;
    int oldCapacity = oldArray.length;
    int newCapacity = index | index >>> 1;
    newCapacity |= newCapacity >>> 2;
    newCapacity |= newCapacity >>> 4;
    newCapacity |= newCapacity >>> 8;
    newCapacity |= newCapacity >>> 16;
    ++newCapacity;
    Object[] newArray = Arrays.copyOf(oldArray, newCapacity);
    Arrays.fill(newArray, oldCapacity, newArray.length, UNSET);
    newArray[index] = value;
    this.indexedVariables = newArray;
}
```



将 FastThreadLocal 的**强引用**添加到 InternalThreadLocalMap 的 indexedVariables[0] 中的 Set 中以便 remove

```java
@SuppressWarnings("unchecked")
    private static void addToVariablesToRemove(InternalThreadLocalMap threadLocalMap, FastThreadLocal<?> variable) {
        Object v = threadLocalMap.indexedVariable(variablesToRemoveIndex);
        Set<FastThreadLocal<?>> variablesToRemove;
        if (v == InternalThreadLocalMap.UNSET || v == null) {
            variablesToRemove = Collections.newSetFromMap(new IdentityHashMap<FastThreadLocal<?>, Boolean>());
            threadLocalMap.setIndexedVariable(variablesToRemoveIndex, variablesToRemove);
        } else {
            variablesToRemove = (Set<FastThreadLocal<?>>) v;
        }

        variablesToRemove.add(variable);
    }
```



```java
public class FastThreadLocalThread extends Thread {
    private InternalThreadLocalMap threadLocalMap;
}

public final class InternalThreadLocalMap extends UnpaddedInternalThreadLocalMap {
}
```



### get

```java
public static InternalThreadLocalMap get() {
    Thread thread = Thread.currentThread();
    if (thread instanceof FastThreadLocalThread) {
        return fastGet((FastThreadLocalThread) thread);
    } else {
        return slowGet();
    }
}

private static InternalThreadLocalMap fastGet(FastThreadLocalThread thread) {
    InternalThreadLocalMap threadLocalMap = thread.threadLocalMap();
    if (threadLocalMap == null) {
        thread.setThreadLocalMap(threadLocalMap = new InternalThreadLocalMap());
    }
    return threadLocalMap;
}

// InternalThreadLocalMap's SuperClass
class UnpaddedInternalThreadLocalMap {

    static final ThreadLocal<InternalThreadLocalMap> slowThreadLocalMap = new ThreadLocal<InternalThreadLocalMap>();
}

private static InternalThreadLocalMap slowGet() {
    ThreadLocal<InternalThreadLocalMap> slowThreadLocalMap = UnpaddedInternalThreadLocalMap.slowThreadLocalMap;
    InternalThreadLocalMap ret = slowThreadLocalMap.get();
    if (ret == null) {
        ret = new InternalThreadLocalMap();
        slowThreadLocalMap.set(ret);
    }
    return ret;
}
```



### size

```java
static final AtomicInteger nextIndex = new AtomicInteger();

/** Used by {@link FastThreadLocal} */
Object[] indexedVariables;

// Core thread-locals
int futureListenerStackDepth;
int localChannelReaderStackDepth;
Map<Class<?>, Boolean> handlerSharableCache;
IntegerHolder counterHashCode;
ThreadLocalRandom random;
Map<Class<?>, TypeParameterMatcher> typeParameterMatcherGetCache;
Map<Class<?>, Map<String, TypeParameterMatcher>> typeParameterMatcherFindCache;

// String-related thread-locals
StringBuilder stringBuilder;
Map<Charset, CharsetEncoder> charsetEncoderCache;
Map<Charset, CharsetDecoder> charsetDecoderCache;

// ArrayList-related thread-locals
ArrayList<Object> arrayList;

public int size() {
    int count = 0;

    if (futureListenerStackDepth != 0) {
        count ++;
    }
    if (localChannelReaderStackDepth != 0) {
        count ++;
    }
    if (handlerSharableCache != null) {
        count ++;
    }
    if (counterHashCode != null) {
        count ++;
    }
    if (random != null) {
        count ++;
    }
    if (typeParameterMatcherGetCache != null) {
        count ++;
    }
    if (typeParameterMatcherFindCache != null) {
        count ++;
    }
    if (stringBuilder != null) {
        count ++;
    }
    if (charsetEncoderCache != null) {
        count ++;
    }
    if (charsetDecoderCache != null) {
        count ++;
    }
    if (arrayList != null) {
        count ++;
    }

    for (Object o: indexedVariables) {
        if (o != UNSET) {
            count ++;
        }
    }

    // 我们应该从计数中减 1，因为 'indexedVariables' 中的第一个元素由 'FastThreadLocal' 保留，
    // 用于保存要在 'FastThreadLocal.removeAll()' 时移除的 'FastThreadLocal' 列表。
    return count - 1;
}
```



### 缓存行填充

```java
// Cache line padding (must be public)
// 启用 CompressedOops 时，此类的实例应至少占用 128 字节。
public long rp1, rp2, rp3, rp4, rp5, rp6, rp7, rp8, rp9;
```





## ThreadLocal vs FastThreadLocal

| Type | ThreadLocal | FastThreadLocal |
| --- | --- | --- |
| 定位方式 | 数组索引 | hash 与线性探测 |
| 扩容 | 仅复制 | 复制并 rehash |
| 遍历 | 遍历所有元素 | 获取 head Set 获取所有 FastThreadLocal |
| 存储 | ThreadLocalMap 中的 WeakReference key | InternalThreadLocalMap，值可能存储在 ThreadLocalMap 或 FastThreadLocal 的字段中，实际值存储在 InternalThreadLocalMap 中 |
| remove | 只需在任务完成后移除 | 存在内存泄漏问题，set/get 时会清理过期值 |
| 特殊值 | - | InternalThreadLocalMap 中所有 FastThreadLocal 的强引用 Set |


## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
