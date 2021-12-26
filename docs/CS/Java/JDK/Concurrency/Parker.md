## Introduction




## Parker
Per-thread blocking support for JSR166. 
See the Java-level documentation for rationale. Basically, `park` acts like `wait`, `unpark` like `notify`.

Parkers are inherently part of their associated JavaThread and are only accessed when the JavaThread is guaranteed to be alive (e.g. by operating on the current thread, or by having the thread protected by a ThreadsListHandle.

Class Parker is declared in shared code and extends the platform-specific os::PlatformParker class, which contains the actual implementation mechanics (condvars/events etc). 
The implementation for park() and unpark()are also in the platform-specific os_<os>.cpp files.

**In the future we'll want to think about eliminating Parker and using ParkEvent instead.**  
There's considerable duplication between the two services.



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

JSR166 support

PlatformParker provides the platform dependent base class for the Parker class. 
It basically provides the internal data structures: - mutex and convars which are then used directly by the Parker methods defined in the OS specific implementation files.

There is significant overlap between the funcionality supported in the combination of Parker+PlatformParker and PlatformEvent (above). 
If Parker were more like ObjectMonitor we could use PlatformEvent in both (with some API updates of course). 
But Parker methods use fastpaths that break that level of encapsulation - so combining the two remains a future project.
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


// Parker::park decrements count if > 0, else does a condvar wait.  Unpark
// sets count to 1 and signals condvar.  Only one thread ever waits
// on the condvar. Contention seen when trying to park implies that someone
// is unparking you, so don't wait. And spurious returns are fine, so there
// is no need to track notifications.

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


ParkEvents are type-stable and immortal.

Lifecycle: Once a ParkEvent is associated with a thread that ParkEvent remains associated with the thread for the thread's entire lifetime - the relationship is stable. 
A thread will be associated at most one ParkEvent. 
When the thread expires, the ParkEvent moves to the EventFreeList.
New threads attempt to allocate from the EventFreeList before creating a new Event.
Type-stability frees us from worrying about stale Event or Thread references in the objectMonitor subsystem.
(A reference to ParkEvent is always valid, even though the event may no longer be associated with the desired or expected thread.
A key aspect of this design is that the callers of park, unpark, etc must tolerate stale references and spurious wakeups).

Only the "associated" thread can block (park) on the ParkEvent, although any other thread can `unpark` a reachable `parkevent`.
Park() is allowed to return spuriously.
In fact park-unpark a really just an optimization to avoid unbounded spinning and surrender the CPU to be a polite system citizen.
A degenerate albeit "impolite" park-unpark implementation could simply return.

See http://blogs.sun.com/dave for more details.

Eventually I'd like to eliminate Events and ObjectWaiters, both of which serve as thread proxies, and simply make the THREAD structure type-stable and persistent.
Currently, we unpark events associated with threads, but ideally we'd just unpark threads.

The base-class, PlatformEvent, is platform-specific while the ParkEvent is platform-independent.
PlatformEvent provides park(), unpark(), etc., and is abstract -- that is, a PlatformEvent should never be instantiated except as part of a ParkEvent.

Equivalently we could have defined a platform-independent base-class that exported Allocate(), Release(), etc.  
The platform-specific class would extend that base-class, adding park(), unpark(), etc.

A word of caution: The JVM uses 2 very similar constructs:
1. ParkEvent are used for Java-level "monitor" synchronization.
2. Parkers are used by JSR166-JUC park-unpark.

We'll want to eventually merge these redundant facilities and use ParkEvent.

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

Shared pthread_mutex/cond based PlatformEvent implementation.
Not currently usable by Solaris.


PlatformEvent

Assumption:
   Only one parker can exist on an event, which is why we allocate them per-thread. Multiple unparkers can coexist.

_event serves as a restricted-range semaphore.
  -1 : thread is blocked, i.e. there is a waiter
   0 : neutral: thread is running or ready,
       could have been signaled after a wait started
   1 : signaled - thread is running or ready

   Having three states allows for some detection of bad usage - see
   comments on unpark().

This is the platform-specific implementation underpinning
the ParkEvent class, which itself underpins Java-level monitor
operations. See park.hpp for details.
These event objects are type-stable and immortal - we never delete them.
Events are associated with a thread for the lifetime of the thread.
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



