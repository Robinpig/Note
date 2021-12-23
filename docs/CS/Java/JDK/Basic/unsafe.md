## Introduction

A collection of methods for performing low-level, unsafe operations. Although the class and all methods are public, use of this class is limited because only trusted code can obtain instances of it. 

**Note:** It is the responsibility of the caller to make sure arguments are checked before methods of this class are called. While some rudimentary checks are performed on the input, the checks are best effort and when performance is an overriding priority, as when methods of this class are optimized by the runtime compiler, some or all checks (if any) may be elided. Hence, the caller must not rely on the checks and corresponding exceptions!


## Memory

### Direct Memory

[Direct Memory Management](/docs/CS/Java/JDK/Basic/Direct_Buffer.md)




## Memory Barrier


Fence like `volatile` 

see [JEP 171: Fence Intrinsics](https://openjdk.java.net/jeps/171)

```java
    //Ensures lack of reordering of loads before the fence with loads or stores after the fence.
    public native void loadFence();

    //Ensures lack of reordering of stores before the fence with loads or stores after the fence.
    public native void storeFence();

    //Ensures lack of reordering of loads or stores before the fence with loads or stores after the fence.
    public native void fullFence();
```
used in StampedLock

## Parker

Parker based on `futex`

`_counter` only will be 0 or 1

### park

```cpp
// unsafe.cpp
UNSAFE_ENTRY(void, Unsafe_Park(JNIEnv *env, jobject unsafe, jboolean isAbsolute, jlong time)) {
  HOTSPOT_THREAD_PARK_BEGIN((uintptr_t) thread->parker(), (int) isAbsolute, time);
  EventThreadPark event;

  JavaThreadParkedState jtps(thread, time != 0);
  thread->parker()->park(isAbsolute != 0, time);
  if (event.should_commit()) {
    const oop obj = thread->current_park_blocker();
    if (time == 0) {
      post_thread_park_event(&event, obj, min_jlong, min_jlong);
    } else {
      if (isAbsolute != 0) {
        post_thread_park_event(&event, obj, min_jlong, time);
      } else {
        post_thread_park_event(&event, obj, time, min_jlong);
      }
    }
  }
  HOTSPOT_THREAD_PARK_END((uintptr_t) thread->parker());
} UNSAFE_END
```



```cpp
// park.hpp
class Parker : public os::PlatformParker {
private:
  volatile int _counter ;
  Parker * FreeNext ;
  JavaThread * AssociatedWith ; // Current association

public:
  Parker() : PlatformParker() {
    _counter       = 0 ;
    FreeNext       = NULL ;
    AssociatedWith = NULL ;
  }
protected:
  ~Parker() { ShouldNotReachHere(); }
public:
  // For simplicity of interface with Java, all forms of park (indefinite,
  // relative, and absolute) are multiplexed into one call.
  void park(bool isAbsolute, jlong time);
  void unpark();

  // Lifecycle operators
  static Parker * Allocate (JavaThread * t) ;
  static void Release (Parker * e) ;
private:
  static Parker * volatile FreeList ;
  static volatile int ListLock ;

};
```



os_posix.cpp

1. Check if prevoius `_counter` is > 0, return fast
2. check pending interrupt, **not clear interrupt**
3. if has  pending interrupt or  **`pthread_mutex_trylock`** fail, return
4. check _counter again, **`pthread_mutex_unlock`** and return
5. Check time
   1. Time == 0, **`pthread_cond_wait`**
   2. Else **`pthread_cond_timedwait`**
6. set _counter = 0, release mutex lock, `pthread_mutex_unlock` 
7. If externally suspended while waiting, re-suspend

```cpp
// Parker::park decrements count if > 0, else does a condvar wait.  Unpark
// sets count to 1 and signals condvar.  Only one thread ever waits
// on the condvar. Contention seen when trying to park implies that someone
// is unparking you, so don't wait. And spurious returns are fine, so there
// is no need to track notifications.

void Parker::park(bool isAbsolute, jlong time) {

  // Optional fast-path check:
  // Return immediately if a permit is available.
  // We depend on Atomic::xchg() having full barrier semantics
  // since we are doing a lock-free update to _counter.
  if (Atomic::xchg(0, &_counter) > 0) return;

  // ... ignore assert

  // Optional optimization -- avoid state transitions if there's an interrupt pending.
  if (Thread::is_interrupted(thread, false)) {
    return;
  }

  // Next, demultiplex/decode time arguments
  struct timespec absTime;
  if (time < 0 || (isAbsolute && time == 0)) { // don't wait at all
    return;
  }
  if (time > 0) {
    to_abstime(&absTime, time, isAbsolute);
  }

  // Enter safepoint region
  // Beware of deadlocks such as 6317397.
  // The per-thread Parker:: mutex is a classic leaf-lock.
  // In particular a thread must never block on the Threads_lock while
  // holding the Parker:: mutex.  If safepoints are pending both the
  // the ThreadBlockInVM() CTOR and DTOR may grab Threads_lock.
  ThreadBlockInVM tbivm(jt);

  // Don't wait if cannot get lock since interference arises from
  // unparking. Also re-check interrupt before trying wait.
  if (Thread::is_interrupted(thread, false) ||
      pthread_mutex_trylock(_mutex) != 0) {
    return;
  }

  int status;
  if (_counter > 0)  { // no wait needed
    _counter = 0;
    status = pthread_mutex_unlock(_mutex);
    assert_status(status == 0, status, "invariant");
    // Paranoia to ensure our locked and lock-free paths interact
    // correctly with each other and Java-level accesses.
    OrderAccess::fence();
    return;
  }

  OSThreadWaitState osts(thread->osthread(), false /* not Object.wait() */);
  jt->set_suspend_equivalent();
  // cleared by handle_special_suspend_equivalent_condition() or java_suspend_self()

  assert(_cur_index == -1, "invariant");
  if (time == 0) {
    _cur_index = REL_INDEX; // arbitrary choice when not timed
    status = pthread_cond_wait(&_cond[_cur_index], _mutex);
    assert_status(status == 0, status, "cond_timedwait");
  }
  else {
    _cur_index = isAbsolute ? ABS_INDEX : REL_INDEX;
    status = pthread_cond_timedwait(&_cond[_cur_index], _mutex, &absTime);
    assert_status(status == 0 || status == ETIMEDOUT,
                  status, "cond_timedwait");
  }
  _cur_index = -1;

  _counter = 0;
  status = pthread_mutex_unlock(_mutex);
  assert_status(status == 0, status, "invariant");
  // Paranoia to ensure our locked and lock-free paths interact
  // correctly with each other and Java-level accesses.
  OrderAccess::fence();

  // If externally suspended while waiting, re-suspend
  if (jt->handle_special_suspend_equivalent_condition()) {
    jt->java_suspend_self();
  }
}
```



### unpark

1. **`pthread_mutex_lock`**
2. Get prevoius `_counter` and  set _counter = 1,get  `_cur_index`
3. `pthread_mutex_unlock`
4. `pthread_cond_signal` when previous `_counter` < 1 && `_cur_index` != -1

```cpp
// os_posix.cpp
void Parker::unpark() {
  int status = pthread_mutex_lock(_mutex);
  assert_status(status == 0, status, "invariant");
  const int s = _counter;
  _counter = 1;
  // must capture correct index before unlocking
  int index = _cur_index;
  status = pthread_mutex_unlock(_mutex);
  assert_status(status == 0, status, "invariant");

  // Note that we signal() *after* dropping the lock for "immortal" Events.
  // This is safe and avoids a common class of futile wakeups.  In rare
  // circumstances this can cause a thread to return prematurely from
  // cond_{timed}wait() but the spurious wakeup is benign and the victim
  // will simply re-test the condition and re-park itself.
  // This provides particular benefit if the underlying platform does not
  // provide wait morphing.

  if (s < 1 && index != -1) {
    // thread is definitely parked
    status = pthread_cond_signal(&_cond[index]);
    assert_status(status == 0, status, "invariant");
  }
}
```



serial

getOffset 



putLong

### write object
performance
put > putOrder > putVolatile


allocateInstance not invoke constructor

## CAS

In [computer science](https://en.wikipedia.org/wiki/Computer_science), **compare-and-swap** (**CAS**) is an [atomic](https://en.wikipedia.org/wiki/Atomic_(computer_science)) [instruction](https://en.wikipedia.org/wiki/Instruction_(computer_science)) used in [multithreading](https://en.wikipedia.org/wiki/Thread_(computer_science)#Multithreading) to achieve [synchronization](https://en.wikipedia.org/wiki/Synchronization_(computer_science)). It compares the contents of a memory location with a given value and, only if they are the same, modifies the contents of that memory location to a new given value. This is done as a single atomic operation. The atomicity guarantees that the new value is calculated based on up-to-date information; if the value had been updated by another thread in the meantime, the write would fail. The result of the operation must indicate whether it performed the substitution; this can be done either with a simple [boolean](https://en.wikipedia.org/wiki/Boolean_logic) response (this variant is often called **compare-and-set**), or by returning the value read from the memory location (*not* the value written to it).



### Overview

This operation is used to implement [synchronization primitives](https://en.wikipedia.org/wiki/Synchronization_(computer_science)#Thread_or_process_synchronization) like [semaphores](https://en.wikipedia.org/wiki/Semaphore_(programming)) and [mutexes](https://en.wikipedia.org/wiki/Mutex),[[1\]](https://en.wikipedia.org/wiki/Compare-and-swap#cite_note-plan9-1) as well as more sophisticated [lock-free and wait-free algorithms](https://en.wikipedia.org/wiki/Lock-free_and_wait-free_algorithms). [Maurice Herlihy](https://en.wikipedia.org/wiki/Maurice_Herlihy) (1991) proved that CAS can implement more of these algorithms than [atomic](https://en.wikipedia.org/wiki/Atomic_operation) read, write, or [fetch-and-add](https://en.wikipedia.org/wiki/Fetch-and-add), and assuming a fairly large[*[clarification needed](https://en.wikipedia.org/wiki/Wikipedia:Please_clarify)*] amount of memory, that it can implement all of them.[[2\]](https://en.wikipedia.org/wiki/Compare-and-swap#cite_note-herlihy91-2) CAS is equivalent to [load-link/store-conditional](https://en.wikipedia.org/wiki/Load-link/store-conditional), in the sense that a constant number of invocations of either primitive can be used to implement the other one in a [wait-free](https://en.wikipedia.org/wiki/Wait-free) manner.[[3\]](https://en.wikipedia.org/wiki/Compare-and-swap#cite_note-3)

Algorithms built around CAS typically read some key memory location and remember the old value. Based on that old value, they compute some new value. Then they try to swap in the new value using CAS, where the comparison checks for the location still being equal to the old value. If CAS indicates that the attempt has failed, it has to be repeated from the beginning: the location is re-read, a new value is re-computed and the CAS is tried again. Instead of immediately retrying after a CAS operation fails, researchers have found that total system performance can be improved in multiprocessor systems—where many threads constantly update some particular shared variable—if threads that see their CAS fail use [exponential backoff](https://en.wikipedia.org/wiki/Exponential_backoff)—in other words, wait a little before retrying the CAS.[[4\]](https://en.wikipedia.org/wiki/Compare-and-swap#cite_note-dice-4)



```cpp
// unsafe.cpp
UNSAFE_ENTRY(jboolean, Unsafe_CompareAndSetInt(JNIEnv *env, jobject unsafe, jobject obj, jlong offset, jint e, jint x)) {
  oop p = JNIHandles::resolve(obj);
  if (p == NULL) {
    volatile jint* addr = (volatile jint*)index_oop_from_field_offset_long(p, offset);
    return RawAccess<>::atomic_cmpxchg(x, addr, e) == e;
  } else {
    assert_field_offset_sane(p, offset);
    return HeapAccess<>::atomic_cmpxchg_at(x, p, (ptrdiff_t)offset, e) == e;
  }
} UNSAFE_END
```



```hpp
// atomic.hpp
// Handle cmpxchg for integral and enum types.
//
// All the involved types must be identical.
template<typename T>
struct Atomic::CmpxchgImpl<
  T, T, T,
  typename EnableIf<IsIntegral<T>::value || IsRegisteredEnum<T>::value>::type>
{
  T operator()(T exchange_value, T volatile* dest, T compare_value,
               atomic_memory_order order) const {
    // Forward to the platform handler for the size of T.
    return PlatformCmpxchg<sizeof(T)>()(exchange_value,
                                        dest,
                                        compare_value,
                                        order);
  }
};

// Handle cmpxchg for pointer types.
//
// The destination's type and the compare_value type must be the same,
// ignoring cv-qualifiers; we don't care about the cv-qualifiers of
// the compare_value.
//
// The exchange_value must be implicitly convertible to the
// destination's type; it must be type-correct to store the
// exchange_value in the destination.
template<typename T, typename D, typename U>
struct Atomic::CmpxchgImpl<
  T*, D*, U*,
  typename EnableIf<Atomic::IsPointerConvertible<T*, D*>::value &&
                    IsSame<typename RemoveCV<D>::type,
                           typename RemoveCV<U>::type>::value>::type>
{
  D* operator()(T* exchange_value, D* volatile* dest, U* compare_value,
               atomic_memory_order order) const {
    // Allow derived to base conversion, and adding cv-qualifiers.
    D* new_value = exchange_value;
    // Don't care what the CV qualifiers for compare_value are,
    // but we need to match D* when calling platform support.
    D* old_value = const_cast<D*>(compare_value);
    return PlatformCmpxchg<sizeof(D*)>()(new_value, dest, old_value, order);
  }
};

// Handle cmpxchg for types that have a translator.
//
// All the involved types must be identical.
//
// This translates the original call into a call on the decayed
// arguments, and returns the recovered result of that translated
// call.
template<typename T>
struct Atomic::CmpxchgImpl<
  T, T, T,
  typename EnableIf<PrimitiveConversions::Translate<T>::value>::type>
{
  T operator()(T exchange_value, T volatile* dest, T compare_value,
               atomic_memory_order order) const {
    typedef PrimitiveConversions::Translate<T> Translator;
    typedef typename Translator::Decayed Decayed;
    STATIC_ASSERT(sizeof(T) == sizeof(Decayed));
    return Translator::recover(
      cmpxchg(Translator::decay(exchange_value),
              reinterpret_cast<Decayed volatile*>(dest),
              Translator::decay(compare_value),
              order));
  }
};
```



Implement by os

```cpp
// atomic_linux_x86.hpp
inline T Atomic::PlatformCmpxchg<8>::operator()(T exchange_value,
                                                T volatile* dest,
                                                T compare_value,
                                                atomic_memory_order /* order */) const {
  STATIC_ASSERT(8 == sizeof(T));
  __asm__ __volatile__ ("lock cmpxchgq %1,(%3)"
                        : "=a" (exchange_value)
                        : "r" (exchange_value), "a" (compare_value), "r" (dest)
                        : "cc", "memory");
  return exchange_value;
}
```





### ABA problem

In [multithreaded](https://en.wikipedia.org/wiki/Thread_(computer_science)) [computing](https://en.wikipedia.org/wiki/Computer_science), the **ABA problem** occurs during synchronization, when a location is read twice, has the same value for both reads, and "value is the same" is used to indicate "nothing has changed". However, another thread can execute between the two reads and change the value, do other work, then change the value back, thus fooling the first thread into thinking "nothing has changed" even though the second thread did work that violates that assumption.



Some CAS-based algorithms are affected by and must handle the problem of a [false positive](https://en.wikipedia.org/wiki/Type_I_error#False_negative_vs._false_positive) match, or the [ABA problem](https://en.wikipedia.org/wiki/ABA_problem). It is possible that between the time the old value is read and the time CAS is attempted, some other processors or threads change the memory location two or more times such that it acquires a bit pattern which matches the old value. The problem arises if this new bit pattern, which looks exactly like the old value, has a different meaning: for instance, it could be a recycled address, or a wrapped version counter.

A general solution to this is to use a double-length CAS (DCAS). E.g. on a 32-bit system, a 64-bit CAS can be used. The second half is used to hold a counter. The compare part of the operation compares the previously read value of the pointer *and* the counter, with the current pointer and counter. If they match, the swap occurs - the new value is written - but the new value has an incremented counter. This means that if ABA has occurred, although the pointer value will be the same, the counter is exceedingly unlikely to be the same (for a 32-bit value, a multiple of 232 operations would have to have occurred, causing the counter to wrap and at that moment, the pointer value would have to also by chance be the same).

An alternative form of this (useful on CPUs which lack DCAS) is to use an index into a freelist, rather than a full pointer, e.g. with a 32-bit CAS, use a 16-bit index and a 16-bit counter. However, the reduced counter lengths begin to make ABA possible at modern CPU speeds.

One simple technique which helps alleviate this problem is to store an ABA counter in each data structure element, rather than using a single ABA counter for the whole data structure.

A more complicated but more effective solution is to implement safe memory reclamation (SMR). This is in effect lock-free garbage collection. The advantage of using SMR is the assurance a given pointer will exist only once at any one time in the data structure, thus the ABA problem is completely solved. (Without SMR, something like a freelist will be in use, to ensure that all data elements can be accessed safely (no memory access violations) even when they are no longer present in the data structure. With SMR, only elements actually currently in the data structure will be accessed).



### Implementations

- [AIX compare_and_swap Kernel Service](http://pic.dhe.ibm.com/infocenter/aix/v7r1/topic/com.ibm.aix.kerneltechref/doc/ktechrf1/compare_and_swap.htm)
- Java package [java.util.concurrent.atomic]() implements `compareAndSet` in various classes
- .NET Class methods [Interlocked::CompareExchange](https://msdn.microsoft.com/en-us/library/system.threading.interlocked.aspx)
- Windows API [InterlockedCompareExchange](https://msdn.microsoft.com/en-us/library/windows/desktop/ms683560.aspx)

## Monitor



## Class



在Lambda表达式实现中，通过invokedynamic指令调用引导方法生成调用点，在此过程中，会通过ASM动态生成字节码，而后利用Unsafe的defineAnonymousClass方法定义实现相应的函数式接口的匿名类，然后再实例化此匿名类，并返回与此匿名类中函数式方法的方法句柄关联的调用点；而后可以通过此调用点实现调用相应Lambda表达式定义逻辑的功能。



BootstrapMethods

### defineAnonymousClass

Defines a class but does not make it known to the class loader or system dictionary.
For each CP entry, the corresponding CP patch must either be null or have the a format that matches its tag:

- Integer, Long, Float, Double: the corresponding wrapper object type from java.lang
- Utf8: a string (must have suitable syntax if used as signature or name)
- Class: any java.lang.Class object
- String: any object (not just a java.lang.String)
- InterfaceMethodRef: (NYI) a method handle to invoke on that call site's arguments



**Deprecated since 15**
Use the `MethodHandles.Lookup.defineHiddenClass(byte[], boolean, MethodHandles.Lookup.ClassOption...)` method.

```java
public Class<?> defineAnonymousClass(Class<?> hostClass, byte[] data, Object[] cpPatches) {
    if (hostClass == null || data == null) {
        throw new NullPointerException();
    }
    if (hostClass.isArray() || hostClass.isPrimitive()) {
        throw new IllegalArgumentException();
    }

    return defineAnonymousClass0(hostClass, data, cpPatches);
}
```

Method Handle like Function Pointer in C/C++ 

## Instance



## System Proterties





## Reference

1. [Java魔法类：Unsafe应用解析 - 美团技术团队](https://tech.meituan.com/2019/02/14/talk-about-java-magic-class-unsafe.html)