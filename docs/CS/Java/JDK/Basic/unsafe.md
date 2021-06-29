# unsafe





### Direct Memory

[Direct Memory Management](/docs/CS/Java/JDK/Basic/Direct_Buffer.md)


### Memory Barrier

Fence like `volatile`

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
2. check pending interrupt, not clear interrupt
3. if has  pending interrupt or  `pthread_mutex_trylock` fail, return
4. check _counter again, `pthread_mutex_unlock` and return
5. Check time
   1. Time == 0, `pthread_cond_wait`
   2. Else `pthread_cond_timedwait`
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

1. `pthread_mutex_lock`
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



## Monitor



## Class

从Java 8开始，JDK使用invokedynamic及VM Anonymous Class结合来实现Java语言层面上的Lambda表达式。

- **invokedynamic**： invokedynamic是Java 7为了实现在JVM上运行动态语言而引入的一条新的虚拟机指令，它可以实现在运行期动态解析出调用点限定符所引用的方法，然后再执行该方法，invokedynamic指令的分派逻辑是由用户设定的引导方法决定。
- **VM Anonymous Class**：可以看做是一种模板机制，针对于程序动态生成很多结构相同、仅若干常量不同的类时，可以先创建包含常量占位符的模板类，而后通过Unsafe.defineAnonymousClass方法定义具体类时填充模板的占位符生成具体的匿名类。生成的匿名类不显式挂在任何ClassLoader下面，只要当该类没有存在的实例对象、且没有强引用来引用该类的Class对象时，该类就会被GC回收。故而VM Anonymous Class相比于Java语言层面的匿名内部类无需通过ClassClassLoader进行类加载且更易回收。

在Lambda表达式实现中，通过invokedynamic指令调用引导方法生成调用点，在此过程中，会通过ASM动态生成字节码，而后利用Unsafe的defineAnonymousClass方法定义实现相应的函数式接口的匿名类，然后再实例化此匿名类，并返回与此匿名类中函数式方法的方法句柄关联的调用点；而后可以通过此调用点实现调用相应Lambda表达式定义逻辑的功能。



BootstrapMethods



## Instance



## System Proterties





## Reference

1. [Java魔法类：Unsafe应用解析 - 美团技术团队](https://tech.meituan.com/2019/02/14/talk-about-java-magic-class-unsafe.html)