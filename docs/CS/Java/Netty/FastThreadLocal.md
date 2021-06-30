

## Introduction

*A special variant of [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md) that yields higher access performance when accessed from a FastThreadLocalThread.*
*Internally, a **FastThreadLocal uses a constant index in an array**, instead of using hash code and hash table, to look for a variable. Although seemingly very subtle, it yields slight performance advantage over using a hash table, and it is useful when accessed frequently.*
*To take advantage of this thread-local variable, your **thread must be a FastThreadLocalThread or its subtype**. By default, all threads created by `DefaultThreadFactory` are FastThreadLocalThread due to this reason.*
*Note that **the fast path is only possible on threads that extend FastThreadLocalThread, because it requires a special field to store the necessary state**. An access by any other kind of thread falls back to a regular ThreadLocal.*





```java
public class FastThreadLocal<V> {

    private static final int variablesToRemoveIndex = InternalThreadLocalMap.nextVariableIndex();
  
   private final int index;

    public FastThreadLocal() {
        index = InternalThreadLocalMap.nextVariableIndex();
    }

```



set

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


```java
public final class InternalThreadLocalMap extends UnpaddedInternalThreadLocalMap {
}
```



get()

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



## ThreadLocal vs FastThreadLocal

| Type | ThreadLocal | FastThreadLocal |
| --- | --- | --- |
| Location | array index | hash & liner |
| resize | just copy | copy & rehash |
| Iteration | get head collection | iterate all array |
| remove | only need to remove after task done | exist memory leaky & expunge stale value when set/get |
