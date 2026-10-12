## Introduction


需要注意：JVM 使用了两种非常相似的机制：
1. ParkEvent 用于 Java 层的 "monitor" 同步。
2. Parker 用于 JSR166-JUC 的 park-unpark。

> [!NOTE]
> 
> 未来我们希望考虑移除 Parker，转而使用 ParkEvent。
> 这两种机制之间存在大量重复。

## Parker
为 JSR166 提供的每线程阻塞支持。
相关理由参见 Java 层文档。本质上，`park` 类似于 `wait`，`unpark` 类似于 `notify`。

Parker 本质上属于其关联的 JavaThread，并且只有在 JavaThread 保证存活时才会被访问（例如操作当前线程，或线程受到 ThreadsListHandle 的保护。

Parker 类在共享代码中声明，并继承自平台相关的 os::PlatformParker 类，后者包含真正的实现机制（条件变量/事件等）。
park() 与 unpark() 的实现同样位于平台相关的 os_<os>.cpp 文件中。




```cpp
// share/runtime/park.hpp
class Parker : public os::PlatformParker {
 private:
  NONCOPYABLE(Parker);
 public:
  Parker() : PlatformParker() {}

  // For simplicity of interface with Java, all forms of park (indefinite,
  // relative, and absolute) are multiplexed into one call.
  void park(bool isAbsolute, jlong time);
  void unpark();
};
```

### PlatformParker


PlatformParker 为 Parker 类提供平台相关的基类。
它主要提供内部数据结构：mutex（互斥量）与 condvars（条件变量），随后被 OS 特定实现文件中定义的 Parker 方法直接使用。

Parker 与 PlatformParker 的组合所支持的功能，与上文的 PlatformEvent 之间存在大量重叠。
如果 Parker 能更像 ObjectMonitor，我们就能在两种场景都使用 PlatformEvent（当然需要一些 API 调整）。
但 Parker 的方法使用了破坏该层封装的快速路径（fastpath），因此将二者合并仍是一个未来的项目。

```cpp
// os/posix/os_posix.hpp
class PlatformParker {
  NONCOPYABLE(PlatformParker);
 protected:
  enum {
    REL_INDEX = 0,
    ABS_INDEX = 1
  };
  volatile int _counter;
  int _cur_index;  // which cond is in use: -1, 0, 1
  pthread_mutex_t _mutex[1];
  pthread_cond_t  _cond[2]; // one for relative times and one for absolute

 public:
  PlatformParker();
  ~PlatformParker();
};
```



#### Parker::park


Parker::park 在计数 > 0 时将其减一，否则执行条件变量等待。Unpark 将计数置为 1 并唤醒条件变量。
任何时刻最多只有一个线程在该条件变量上等待。若尝试 park 时观察到竞争，意味着有人在 unpark 你，因此无需等待。
伪唤醒是允许的，因此无需记录通知。

```cpp
void Parker::park(bool isAbsolute, jlong time) {

  // Optional fast-path check:
  // Return immediately if a permit is available.
  // We depend on Atomic::xchg() having full barrier semantics
  // since we are doing a lock-free update to _counter.
  if (Atomic::xchg(&_counter, 0) > 0) return;

  JavaThread *jt = JavaThread::current();

  // Optional optimization -- avoid state transitions if there's
  // an interrupt pending.
  if (jt->is_interrupted(false)) {
    return;
  }

  // Next, demultiplex/decode time arguments
  struct timespec absTime;
  if (time < 0 || (isAbsolute && time == 0)) { // don't wait at all
    return;
  }
  if (time > 0) {
    to_abstime(&absTime, time, isAbsolute, false);
  }

  // Enter safepoint region
  // Beware of deadlocks such as 6317397.
  // The per-thread Parker:: mutex is a classic leaf-lock.
  // In particular a thread must never block on the Threads_lock while
  // holding the Parker:: mutex.  If safepoints are pending both the
  // the ThreadBlockInVM() CTOR and DTOR may grab Threads_lock.
  ThreadBlockInVM tbivm(jt);

  // Can't access interrupt state now that we are _thread_blocked. If we've
  // been interrupted since we checked above then _counter will be > 0.

  // Don't wait if cannot get lock since interference arises from
  // unparking.
  if (pthread_mutex_trylock(_mutex) != 0) {
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

  OSThreadWaitState osts(jt->osthread(), false /* not Object.wait() */);

  assert(_cur_index == -1, "invariant");
  if (time == 0) {
    _cur_index = REL_INDEX; // arbitrary choice when not timed
    status = pthread_cond_wait(&_cond[_cur_index], _mutex);
    assert_status(status == 0 MACOS_ONLY(|| status == ETIMEDOUT),
                  status, "cond_wait");
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
}
```


#### Parker::unpark
```cpp

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


## ParkEvent


ParkEvent 是类型稳定（type-stable）且不可销毁（immortal）的。

生命周期：
一旦某个 ParkEvent 与某线程关联，它在整个线程生命周期内都保持关联——这种关系是稳定的。
**一个线程最多关联一个 ParkEvent。**
线程退出后，该 ParkEvent 会进入 EventFreeList。
新线程在创建新事件前会先尝试从 EventFreeList 中分配。
类型稳定性使我们从不必担心 objectMonitor 子系统中出现失效的 Event 或 Thread 引用。
（对 ParkEvent 的引用始终有效，即便该事件可能已不再与期望的线程关联。
这一设计的关键在于，park、unpark 等的调用方必须容忍失效引用与伪唤醒。）

只有「关联」的线程才能在 ParkEvent 上阻塞（park），但任何其他线程都可以 `unpark` 一个可达的 `parkevent`。
**Park() 允许伪唤醒返回。**
事实上，park-unpark 本质上只是一种避免无限自旋、主动让出 CPU 的礼貌性优化。
一个退化但「不礼貌」的 park-unpark 实现甚至可以直接返回。

最终我希望移除 Events 与 ObjectWaiters（二者都充当线程代理），直接让 THREAD 结构具备类型稳定且持久的特性。
目前我们 unpark 与线程关联的事件，但理想情况下应该直接 unpark 线程。

基类 PlatformEvent 是平台相关的，而 ParkEvent 是平台无关的。
PlatformEvent 提供 park()、unpark() 等，且是抽象的——也就是说，PlatformEvent 除作为 ParkEvent 的一部分外不应被单独实例化。

等价地，我们也可以定义一个导出 Allocate()、Release() 等的平台无关基类，
再由平台相关的类继承它并补充 park()、unpark() 等。


```cpp
// share/runtime/park.hpp
class ParkEvent : public os::PlatformEvent {
  private:
    ParkEvent * FreeNext ;

    // Current association
    Thread * AssociatedWith ;

  public:
    // MCS-CLH list linkage and Native Mutex/Monitor
    ParkEvent * volatile ListNext ;
    volatile int TState ;
    volatile int Notified ;             // for native monitor construct

  private:
    static ParkEvent * volatile FreeList ;
    static volatile int ListLock ;

    // It's prudent to mark the dtor as "private"
    // ensuring that it's not visible outside the package.
    // Unfortunately gcc warns about such usage, so
    // we revert to the less desirable "protected" visibility.
    // The other compilers accept private dtors.

  protected:        // Ensure dtor is never invoked
    ~ParkEvent() { guarantee (0, "invariant") ; }

    ParkEvent() : PlatformEvent() {
       AssociatedWith = NULL ;
       FreeNext       = NULL ;
       ListNext       = NULL ;
       TState         = 0 ;
       Notified       = 0 ;
    }

    // We use placement-new to force ParkEvent instances to be
    // aligned on 256-byte address boundaries.  This ensures that the least
    // significant byte of a ParkEvent address is always 0.

    void * operator new (size_t sz) throw();
    void operator delete (void * a) ;

  public:
    static ParkEvent * Allocate (Thread * t) ;
    static void Release (ParkEvent * e) ;
} ;
```

### PlatformEvent

基于共享 pthread_mutex/cond 的 PlatformEvent 实现。
目前 Solaris 尚不可用。

前提假设：
   一个事件上只能存在一个 parker，这正是我们按线程分配的原因。多个 unparker 可以共存。

_event 充当一个有限值域的信号量（semaphore）。
  -1 : 线程已阻塞，即存在等待者
   0 : 中性：线程正在运行或就绪，
       可能在等待开始后已被唤醒
   1 : 已唤醒——线程正在运行或就绪

   三个状态可用于检测部分误用——详见
   unpark() 上的注释。

这是支撑 ParkEvent 类的平台相关实现，而 ParkEvent 类本身又支撑着 [Java-level monitor](/docs/CS/Java/JDK/Concurrency/synchronized.md) 操作。详见 `park.hpp`。
事件在线程的整个生命周期内都与该线程关联。
```cpp

// os/posix/os_posix.hpp
class PlatformEvent : public CHeapObj<mtSynchronizer> {
 private:
  double cachePad[4];        // Increase odds that _mutex is sole occupant of cache line
  volatile int _event;       // Event count/permit: -1, 0 or 1
  volatile int _nParked;     // Indicates if associated thread is blocked: 0 or 1
  pthread_mutex_t _mutex[1]; // Native mutex for locking
  pthread_cond_t  _cond[1];  // Native condition variable for blocking
  double postPad[2];

 protected:       // TODO-FIXME: make dtor private
  ~PlatformEvent() { guarantee(false, "invariant"); } // immortal so can't delete

 public:
  PlatformEvent();
  void park();
  int  park(jlong millis);
  void unpark();

  // Use caution with reset() and fired() -- they may require MEMBARs
  void reset() { _event = 0; }
  int  fired() { return _event; }
};
```


#### PlatformEvent::park

```cpp

int os::PlatformEvent::park(jlong millis) {
  // Transitions for _event:
  //   -1 => -1 : illegal
  //    1 =>  0 : pass - return immediately
  //    0 => -1 : block; then set _event to 0 before returning

  // Invariant: Only the thread associated with the Event/PlatformEvent
  // may call park().
  assert(_nParked == 0, "invariant");

  int v;
  // atomically decrement _event
  for (;;) {
    v = _event;
    if (Atomic::cmpxchg(&_event, v, v - 1) == v) break;
  }
  guarantee(v >= 0, "invariant");

  if (v == 0) { // Do this the hard way by blocking ...
    struct timespec abst;
    to_abstime(&abst, millis_to_nanos_bounded(millis), false, false);

    int ret = OS_TIMEOUT;
    int status = pthread_mutex_lock(_mutex);
    assert_status(status == 0, status, "mutex_lock");
    guarantee(_nParked == 0, "invariant");
    ++_nParked;

    while (_event < 0) {
      status = pthread_cond_timedwait(_cond, _mutex, &abst);
      assert_status(status == 0 || status == ETIMEDOUT,
                    status, "cond_timedwait");
      // OS-level "spurious wakeups" are ignored
      if (status == ETIMEDOUT) break;
    }
    --_nParked;

    if (_event >= 0) {
      ret = OS_OK;
    }

    _event = 0;
    status = pthread_mutex_unlock(_mutex);
    assert_status(status == 0, status, "mutex_unlock");
    // Paranoia to ensure our locked and lock-free paths interact
    // correctly with each other.
    OrderAccess::fence();
    return ret;
  }
  return OS_OK;
}
```

#### PlatformEvent::unpark

```cpp

void os::PlatformEvent::unpark() {
  // Transitions for _event:
  //    0 => 1 : just return
  //    1 => 1 : just return
  //   -1 => either 0 or 1; must signal target thread
  //         That is, we can safely transition _event from -1 to either
  //         0 or 1.
  // See also: "Semaphores in Plan 9" by Mullender & Cox
  //
  // Note: Forcing a transition from "-1" to "1" on an unpark() means
  // that it will take two back-to-back park() calls for the owning
  // thread to block. This has the benefit of forcing a spurious return
  // from the first park() call after an unpark() call which will help
  // shake out uses of park() and unpark() without checking state conditions
  // properly. This spurious return doesn't manifest itself in any user code
  // but only in the correctly written condition checking loops of ObjectMonitor,
  // Mutex/Monitor, and JavaThread::sleep

  if (Atomic::xchg(&_event, 1) >= 0) return;

  int status = pthread_mutex_lock(_mutex);
  assert_status(status == 0, status, "mutex_lock");
  int anyWaiters = _nParked;
  assert(anyWaiters == 0 || anyWaiters == 1, "invariant");
  status = pthread_mutex_unlock(_mutex);
  assert_status(status == 0, status, "mutex_unlock");

  // Note that we signal() *after* dropping the lock for "immortal" Events.
  // This is safe and avoids a common class of futile wakeups.  In rare
  // circumstances this can cause a thread to return prematurely from
  // cond_{timed}wait() but the spurious wakeup is benign and the victim
  // will simply re-test the condition and re-park itself.
  // This provides particular benefit if the underlying platform does not
  // provide wait morphing.

  if (anyWaiters != 0) {
    status = pthread_cond_signal(_cond);
    assert_status(status == 0, status, "cond_signal");
  }
}
```


## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)
