

## Introduction

*A special variant of [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md) that yields higher access performance when accessed from a FastThreadLocalThread.*
*Internally, a **FastThreadLocal uses a constant index in an array**, instead of using hash code and hash table, to look for a variable. Although seemingly very subtle, it yields slight performance advantage over using a hash table, and it is useful when accessed frequently.*
*To take advantage of this thread-local variable, your **thread must be a FastThreadLocalThread or its subtype**. By default, all threads created by `DefaultThreadFactory` are FastThreadLocalThread due to this reason.*
*Note that **the fast path is only possible on threads that extend FastThreadLocalThread, because it requires a special field to store the necessary state**. An access by any other kind of thread falls back to a regular ThreadLocal.*



## Use FastThreadLocal

**FastThreadLocal don not extens ThreadLocal.**

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

// true if and only if a new thread-local variable has been created
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



add **StrongReference** of FastThreadLocal to *a Set in indexedVariables[0]* of InternalThreadLocalMap remove

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

    // We should subtract 1 from the count because the first element in 'indexedVariables' is reserved
    // by 'FastThreadLocal' to keep the list of 'FastThreadLocal's to remove on 'FastThreadLocal.removeAll()'.
    return count - 1;
}
```



### Cache Line

```java
// Cache line padding (must be public)
// With CompressedOops enabled, an instance of this class should occupy at least 128 bytes.
public long rp1, rp2, rp3, rp4, rp5, rp6, rp7, rp8, rp9;
```





## ThreadLocal vs FastThreadLocal

| Type | ThreadLocal | FastThreadLocal |
| --- | --- | --- |
| Location | array index | hash & liner |
| resize | just copy | copy & rehash |
| Iteration | iterate all elements | get head Set and get all FastThreadLocal |
| Storage | weakReference key in ThreadLocalMap | InternalThreadLocalMap may value in ThreadLocalMap or  field in FastThreadLocal, storage value in InternalThreadLocalMap |
| remove | only need to remove after task done | exist memory leaky & expunge stale value when set/get |
| Special value | - | a strong reference set of all fastThreadLocals in InternalThreadLocalMap |
