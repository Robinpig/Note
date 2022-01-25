## Introduction

This class provides thread-local variables. 
These variables differ from their normal counterparts in that each thread that accesses one (via its get or set method) has its own, independently initialized copy of the variable. 
**ThreadLocal instances are typically private static fields in classes that wish to associate state with a [thread](/docs/CS/Java/JDK/Concurrency/Thread.md) (e.g., a user ID or Transaction ID)**.

Each thread holds an implicit reference to its copy of a thread-local variable as long as the thread is alive and the ThreadLocal instance is accessible; 
**after a thread goes away, all of its copies of thread-local instances are subject to garbage collection (unless other references to these copies exist**).



## ThreadLocal

### Create ThreadLocal withInitial

```java
/**
 * Creates a thread local variable. The initial value of the variable is
 * determined by invoking the {@code get} method on the {@code Supplier}.
 */
public static <S> ThreadLocal<S> withInitial(Supplier<? extends S> supplier) {
    return new SuppliedThreadLocal<>(supplier);
}

/**
 * Creates a thread local variable.
 */
public ThreadLocal() {
}
```

### Set value in ThreadLocal

`ThreadLocalMap map=getMap(t)` actually get **ThreadLocal.ThreadLocalMap** of currentThread

`create ThreadLocalMap when set the first value`

```java
/**
 * Sets the current thread's copy of this thread-local variable
 * to the specified value.  Most subclasses will have no need to
 * override this method, relying solely on the {@link #initialValue}
 * method to set the values of thread-locals.
 */
public void set(T value) {
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);
    if (map != null)
        map.set(this, value);
    else
        createMap(t, value);
}

/** ThreadLocal values pertaining to this thread. This map is maintained
 * by the ThreadLocal class. 
 */
ThreadLocal.ThreadLocalMap threadLocals = null;

/**
 * InheritableThreadLocal values pertaining to this thread. This map is
 * maintained by the InheritableThreadLocal class.
 */
ThreadLocal.ThreadLocalMap inheritableThreadLocals = null;

```

### create ThreadLocalMap

**ThreadLocalMap**

Create ThreadLocalMap at **first set/get in ThreadLocal**.

ThreadLocalMap is a customized hash map suitable only for maintaining thread local values. No operations are exported outside of the ThreadLocal class. **The class is package private to allow declaration of fields in class Thread.** To help **deal with very large and long-lived usages, the hash table entries use WeakReferences for keys**. 

However, since **reference queues are not used, stale entries are guaranteed to be removed only when the table starts running out of space**.

```Java
static class ThreadLocalMap {
        static class Entry extends WeakReference<ThreadLocal<?>> {
            /** The value associated with this ThreadLocal. */
            Object value;

            Entry(ThreadLocal<?> k, Object v) {
                super(k);
                value = v;
            }
        }
   			/**
         * Construct a new map initially containing (firstKey, firstValue).
         * ThreadLocalMaps are constructed lazily, so we only create
         * one when we have at least one entry to put in it.
         */
        ThreadLocalMap(ThreadLocal<?> firstKey, Object firstValue) {
            table = new Entry[INITIAL_CAPACITY]; // INITIAL_CAPACITY = 16
            int i = firstKey.threadLocalHashCode & (INITIAL_CAPACITY - 1);
            table[i] = new Entry(firstKey, firstValue);
            size = 1;
            setThreshold(INITIAL_CAPACITY);
        }
}
```

**Entry**

The entries in this hash map **extend WeakReference**, using its **main ref field as the key (which is always a ThreadLocal object)**. Note that **null keys (i.e. entry.get() == null) mean that the key is no longer referenced, so the entry can be expunged from table**. Such entries are referred to as "**stale entries**" in the code that follows.

```java
static class Entry extends WeakReference<ThreadLocal<?>> {
    /** The value associated with this ThreadLocal. */
    Object value;

    Entry(ThreadLocal<?> k, Object v) {
        super(k);
        value = v;
    }
}
```

### hash

ThreadLocals rely on **per-thread linear-probe hash maps** attached to each thread (**Thread.threadLocals and inheritableThreadLocals**). The ThreadLocal objects act as keys, searched via threadLocalHashCode. This is a custom hash code (**useful only within ThreadLocalMaps**) that **eliminates collisions in the common case where consecutively constructed ThreadLocals are used by the same threads**, while remaining well-behaved in less common cases.

**HASH_INCREMENT = 0x61c88647**

The difference between successively generated hash codes - turns implicit sequential thread-local IDs into **near-optimally spread multiplicative hash values** for **power-of-two-sized tables**.

` 0x61c88647 = (long) ((1L << 31) * (Math.sqrt(5) - 1))`

```java
private final int threadLocalHashCode = nextHashCode();
// The next hash code to be given out. Updated atomically. Starts at zero.
private static AtomicInteger nextHashCode = new AtomicInteger();
private static final int HASH_INCREMENT = 0x61c88647;

private static int nextHashCode() {
    return nextHashCode.getAndAdd(HASH_INCREMENT);
}
```



### Set in ThreadLocalMap

We don't use a fast path as with get() because it is at  least as common to use set() to create new entries as it is to replace existing ones, in which case, a fast path would fail more often than not.

```java
private void set(ThreadLocal<?> key, Object value) {
    Entry[] tab = table;
    int len = tab.length;
    int i = key.threadLocalHashCode & (len-1);

  	// non-null entry
    for (Entry e = tab[i];
         e != null;
         e = tab[i = nextIndex(i, len)]) {
        ThreadLocal<?> k = e.get();
				// same key
        if (k == key) {
            e.value = value;
            return;
        }
				// null key
        if (k == null) {
            replaceStaleEntry(key, value, i);
            return;
        }
    }
		// null entry
    tab[i] = new Entry(key, value);
    int sz = ++size;
    if (!cleanSomeSlots(i, sz) && sz >= threshold)
        rehash();
}
```



### replaceStaleEntry

Replace a stale entry encountered during a set operation with an entry for the specified key. The value passed in the value parameter is stored in the entry, whether or not an entry already exists for the specified key. As a side effect, this method expunges all stale entries in the "run" containing the stale entry. (**A run is a sequence of entries between two null slots**.)

1. Back up to find prior stale entry util the null entry
2. From staleSlot to check the key of  entry util the null entry
   1. if find key, swap and expunge
   2. If key not found, put new entry in stale slot
      1. If we didn't find stale entry on backward scan, the first stale entry seen while scanning for key is the first still present in the run.
      2. If there are any other stale entries in run, expunge them

```java
private void replaceStaleEntry(ThreadLocal<?> key, Object value,
                               int staleSlot) {
    Entry[] tab = table;
    int len = tab.length;
    Entry e;

   /**
    *  Back up to check for prior stale entry in current run. 
    * We clean out whole runs at a time to avoid continual incremental rehashing due 
    * to garbage collector freeing  up refs in bunches (i.e., whenever the collector runs).
    */
    int slotToExpunge = staleSlot;
    for (int i = prevIndex(staleSlot, len);
         (e = tab[i]) != null;
         i = prevIndex(i, len))
        if (e.get() == null)
            slotToExpunge = i;

    // Find either the key or trailing null slot of run, whichever
    // occurs first
    for (int i = nextIndex(staleSlot, len);
         (e = tab[i]) != null;
         i = nextIndex(i, len)) {
        ThreadLocal<?> k = e.get();

        // If we find key, then we need to swap it with the stale entry to maintain 
      	// hash table order.
        // The newly stale slot, or any other stale slot
        // encountered above it, can then be sent to expungeStaleEntry
        // to remove or rehash all of the other entries in run.
        if (k == key) {
            e.value = value;

            tab[i] = tab[staleSlot];
            tab[staleSlot] = e;

            // Start expunge at preceding stale entry if it exists
            if (slotToExpunge == staleSlot)
                slotToExpunge = i;
            cleanSomeSlots(expungeStaleEntry(slotToExpunge), len);
            return;
        }

        // If we didn't find stale entry on backward scan, the
        // first stale entry seen while scanning for key is the
        // first still present in the run.
        if (k == null && slotToExpunge == staleSlot)
            slotToExpunge = i;
    }

    // If key not found, put new entry in stale slot
    tab[staleSlot].value = null;
    tab[staleSlot] = new Entry(key, value);

    // If there are any other stale entries in run, expunge them
    if (slotToExpunge != staleSlot)
        cleanSomeSlots(expungeStaleEntry(slotToExpunge), len);
}
```



### cleanSomeSlots

**Heuristically scan some cells looking for stale entries.**

This is invoked when either a new element is **added**, or another stale one has been **expunged**.

It **performs a logarithmic number of scans**, as a balance between no scanning (fast but retains garbage) and a number of scans proportional to number of elements, that would find all garbage but **would cause some insertions to take O(n) time**.

```java
private boolean cleanSomeSlots(int i, int n) {
    boolean removed = false;
    Entry[] tab = table;
    int len = tab.length;
    do {
        i = nextIndex(i, len);
        Entry e = tab[i];
        if (e != null && e.get() == null) {
            n = len;
            removed = true;
            i = expungeStaleEntry(i);
        }
    } while ( (n >>>= 1) != 0);
    return removed;
}
```





### expungeStaleEntry

1. Expunge a stale entry by **rehashing any possibly colliding entries lying between staleSlot and the next null slot**.
2. This also **expunges any other stale entries encountered before the trailing null**.

**See Knuth, Section 6.4 -- todo**

```java
private int expungeStaleEntry(int staleSlot) {
    Entry[] tab = table;
    int len = tab.length;

    // expunge entry at staleSlot
    tab[staleSlot].value = null;
    tab[staleSlot] = null;
    size--;

    // Rehash until we encounter null
    Entry e;
    int i;
    for (i = nextIndex(staleSlot, len);
         (e = tab[i]) != null;
         i = nextIndex(i, len)) {
        ThreadLocal<?> k = e.get();
        if (k == null) {
            e.value = null;
            tab[i] = null;
            size--;
        } else { //rehash
            int h = k.threadLocalHashCode & (len - 1);
            if (h != i) {
                tab[i] = null;
                // Unlike Knuth 6.4 Algorithm R, we must scan until
                // null because multiple entries could have been stale.
                while (tab[h] != null)
                    h = nextIndex(h, len);
                tab[h] = e;
            }
        }
    }
    return i;
}
```





### rehash

1. expungeStaleEntries and decrement size
2. if size >= threshold - threshold / 4, double the capacity of the table

```java
private void rehash() {
    expungeStaleEntries();
    // Use lower threshold for doubling to avoid hysteresis
    if (size >= threshold - threshold / 4)
        resize();
}

/**
 * Expunge all stale entries in the table.
 */
private void expungeStaleEntries() {
    Entry[] tab = table;
    int len = tab.length;
    for (int j = 0; j < len; j++) {
        Entry e = tab[j];
        if (e != null && e.get() == null)
            expungeStaleEntry(j);
    }
}

/**
 * Double the capacity of the table.
 */
private void resize() {
    Entry[] oldTab = table;
    int oldLen = oldTab.length;
    int newLen = oldLen * 2;
    Entry[] newTab = new Entry[newLen];
    int count = 0;

    for (int j = 0; j < oldLen; ++j) {
        Entry e = oldTab[j];
        if (e != null) {
            ThreadLocal<?> k = e.get();
            if (k == null) {
                e.value = null; // Help the GC
            } else {
                int h = k.threadLocalHashCode & (newLen - 1);
                while (newTab[h] != null)
                    h = nextIndex(h, newLen);
                newTab[h] = e;
                count++;
            }
        }
    }

    setThreshold(newLen);
    size = count;
    table = newTab;
}
```





### Get in ThreadLocal

Returns the value in the current thread's copy of this thread-local variable. If the variable has no value for the current thread, it is first initialized to the value returned by an invocation of the initialValue method.

```java
public T get() {
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);
    if (map != null) {
        ThreadLocalMap.Entry e = map.getEntry(this);
        if (e != null) {
            @SuppressWarnings("unchecked")
            T result = (T)e.value;
            return result;
        }
    }
    return setInitialValue();
}

/**
 * Variant of set() to establish initialValue. Used instead
 * of set() in case user has overridden the set() method.
 */
private T setInitialValue() {
    T value = initialValue();
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);
    if (map != null)
        map.set(this, value);
    else
        createMap(t, value);
    return value;
}

/**
 * Get the entry associated with key.  This method
 * itself handles only the fast path: a direct hit of existing
 * key. It otherwise relays to getEntryAfterMiss.  This is
 * designed to maximize performance for direct hits, in part
 * by making this method readily inlinable.
 */
private Entry getEntry(ThreadLocal<?> key) {
    int i = key.threadLocalHashCode & (table.length - 1);
    Entry e = table[i];
    if (e != null && e.get() == key)
        return e;
    else
        return getEntryAfterMiss(key, i, e);
}

/**
 * Version of getEntry method for use when key is not found in
 * its direct hash slot.
 */
private Entry getEntryAfterMiss(ThreadLocal<?> key, int i, Entry e) {
    Entry[] tab = table;
    int len = tab.length;

    while (e != null) {
        ThreadLocal<?> k = e.get();
        if (k == key)
            return e;
        if (k == null)
            expungeStaleEntry(i);
        else
            i = nextIndex(i, len);
        e = tab[i];
    }
    return null;
}
```



### remove in ThreadLocal

Removes the current thread's value for this thread-local variable.

If this thread-local variable is subsequently read by the current thread, its value will be reinitialized by invoking its initialValue method, unless its value is set by the current thread in the interim. **This may result in multiple invocations of the initialValue method in the current thread**.

**Invoke remove method if no longer used.** 

```java
     public void remove() {
         ThreadLocalMap m = getMap(Thread.currentThread());
         if (m != null)
             m.remove(this);
     }

     private void remove(ThreadLocal<?> key) {
            Entry[] tab = table;
            int len = tab.length;
            int i = key.threadLocalHashCode & (len-1);
            for (Entry e = tab[i];
                 e != null;
                 e = tab[i = nextIndex(i, len)]) {
                if (e.get() == key) {
                    e.clear();
                    expungeStaleEntry(i);
                    return;
                }
            }
        }
```





## InheritableThreadLocal

### create in init of Thread

```java
if (inheritThreadLocals && parent.inheritableThreadLocals != null)
    this.inheritableThreadLocals =
        ThreadLocal.createInheritedMap(parent.inheritableThreadLocals);
```



**TransmittableThreadLocal**



## Optimize ThreadLocal



1. [FastThreadLocal in Netty](/docs/CS/Java/Netty/FastThreadLocal.md)



## Practice

1. session/token for use
3. TraceId for trace request

## Links

- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)
- [ThreadLocalRandom](/docs/CS/Java/JDK/Concurrency/ThreadLocalRandom.md)