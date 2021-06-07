# FastThreadLocal



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

- FastThreadLocal 在具体的定位的过程中，只需要根据在构造方法里获取得到的具体下标就可以定位到具体的数组位置进行变量的存取，而在 jdk 原生的 ThreadLocal 中，具体位置的下标获取不仅需要计算 ThreadLocal 的 hash 值，并需要在 hashTable 上根据 key 定位的结果，一旦定位之后的结果上已经存在其他 ThreadLocal 的变量，那么则是通过线性探测法，在 hashTable 上寻找下一个位置进行，相比 FastThreadLocal 定位的过程要复杂的多。
- FastThreadLocal 由于采取数组的方式，当面对扩容的时候，只需要将原数组中的内容复制过去，并用 NULL 对象填满剩余位置即可，而在 ThreadLocal 中，由于 hashTable 的缘故，在扩容后还需要进行一轮 rehash，在这过程中，仍旧存在 hash 冲突的可能。
- 在 FastThreadLocal 中，遍历当前线程的所有本地变量，只需要将数组首位的集合即可，不需要遍历数组上的每一个位置。
- 在原生的 ThreadLocal 中，由于可能存在 ThreadLocal 被回收，但是当前线程仍旧存活的情况导致 ThreadLocal 对应的本地变量内存泄漏的问题，因此在 ThreadLocal 的每次操作后，都会进行启发式的内存泄漏检测，防止这样的问题产生，但也在每次操作后花费了额外的开销。而在 FastThreadLocal 的场景下，由于数组首位的 FastThreadLocal 集合中保持着所有 FastThreadLocal 对象的引用，因此当外部的 FastThreadLocal 的引用被置为 null，该 FastThreadLocal 对象仍旧保持着这个集合的引用，不会被回收掉，只需要在线程当前业务操作后，手动调用 FastThreadLocal 的 removeAll()方法，将会遍历数组首位集合，回收掉所有 FastThreadLocal 的变量，避免内存泄漏的产生，也减少了原生 ThreadLocal 的启发式检测开销。