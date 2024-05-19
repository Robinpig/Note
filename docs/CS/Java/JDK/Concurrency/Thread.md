## Introduction

One of the primary reasons to use threads is to improve performance. Using threads can improve resource utilization by letting applications more easily exploit available processing capacity, and can improve responsiveness by letting applications begin processing new tasks immediately while existing tasks are still running.

## Create

Threads are represented by the `Thread` class. The only way for a user to create a thread is to **create an object of this class**; 
each thread is associated with such an object. 
A thread will start when the `start()` method is invoked on the corresponding `Thread` object.

```java
// Allocates a new Thread object.
public Thread() {
    init(null, null, "Thread-" + nextThreadNum(), 0);
}

// Allocates a new Thread object with Runnable taarget.
public Thread(Runnable target) {
    init(null, target, "Thread-" + nextThreadNum(), 0);
}
```

### init
Threads are divided into two types: normal threads and daemon threads.

Normal threads and daemon threads differ only in what happens when they exit. When a thread exits, the JVM performs an inventory of running threads, and if the only threads that are left are daemon threads, it initiates an orderly shutdown. When the JVM halts, any remaining daemon threads are abandoned ‐ finally blocks are not executed, stacks are not unwound ‐ the JVM just exits.

*Daemon threads are not a good substitute for properly managing the lifecycle of services within an application.*
```java
private void init(ThreadGroup g, Runnable target, String name,
                  long stackSize) {
  init(g, target, name, stackSize, null, true);
}

private void init(ThreadGroup g, Runnable target, String name,
                  long stackSize, AccessControlContext acc,
                  boolean inheritThreadLocals) {
  if (name == null) {
    throw new NullPointerException("name cannot be null");
  }

  this.name = name;

  Thread parent = currentThread();
  SecurityManager security = System.getSecurityManager();
  if (g == null) {
    /* Determine if it's an applet or not */

    /* If there is a security manager, ask the security manager
               what to do. */
    if (security != null) {
      g = security.getThreadGroup();
    }

    /* If the security doesn't have a strong opinion of the matter
               use the parent thread group. */
    if (g == null) {
      g = parent.getThreadGroup();
    }
  }

  /* checkAccess regardless of whether or not threadgroup is
           explicitly passed in. */
  g.checkAccess();

  /*
         * Do we have the required permissions?
         */
  if (security != null) {
    if (isCCLOverridden(getClass())) {
      security.checkPermission(SUBCLASS_IMPLEMENTATION_PERMISSION);
    }
  }

  g.addUnstarted();

  this.group = g;
  this.daemon = parent.isDaemon();
  this.priority = parent.getPriority();
  if (security == null || isCCLOverridden(parent.getClass()))
    this.contextClassLoader = parent.getContextClassLoader();
  else
    this.contextClassLoader = parent.contextClassLoader;
  this.inheritedAccessControlContext =
    acc != null ? acc : AccessController.getContext();
  this.target = target;
  setPriority(priority);
  if (inheritThreadLocals && parent.inheritableThreadLocals != null)
    this.inheritableThreadLocals =
    ThreadLocal.createInheritedMap(parent.inheritableThreadLocals);
  /* Stash the specified stack size in case the VM cares */
  this.stackSize = stackSize;

  /* Set thread ID */
  tid = nextThreadID();
}
```



### Example

1. create a thread extends Thread directly
2. use [ThreadLocalExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md?id=ThreadPoolExecutor)
3. use [CompletableFuture](/docs/CS/Java/JDK/Concurrency/Future.md?id=CompletableFuture) submit task
4. use [FutureTask](/docs/CS/Java/JDK/Concurrency/Future.md?id=FutureTask)





## Lifetime

图源《Java并发编程的艺术》4.1.4节:

![Thread-Lifetime](../img/Thread-Lifetime.png)

#### State

A thread can be in one of the following states:

| State        | Description                                                  |
| ------------ | ------------------------------------------------------------ |
| NEW          | A thread that has not yet started is in this state.          |
| RUNNABLE     | A thread executing in the Java virtual machine is in this state. |
| BLOCKED      | A thread that is blocked waiting for a monitor lock is in this state. |
| WATING       | A thread that is waiting indefinitely for another thread to perform a particular action is in this state. |
| TIME_WAITING | A thread that is waiting for another thread to perform an action for up to a specified waiting time is in this state. |
| TERMINATED   | A thread that has exited is in this state.                   |



## Start

*Causes this thread to begin execution; the Java Virtual Machine calls the run method of this thread.*

*The result is that **two threads are running concurrently**: *

1. *the current thread (which returns from the call to the start method)*
2. *the other thread (which executes its run method).*

*It is never legal to start a thread more than once.*

```java
public synchronized void start() {
    /**
     * This method is not invoked for the main method thread or "system"
     * group threads created/set up by the VM. Any new functionality added
     * to this method in the future may have to also be added to the VM.
     * A zero status value corresponds to state "NEW".
     */
    if (threadStatus != 0)
        throw new IllegalThreadStateException();

    /* Notify the group that this thread is about to be started
     * so that it can be added to the group's list of threads
     * and the group's unstarted count can be decremented. */
    group.add(this);

    boolean started = false;
    try {
        start0();
        started = true;
    } finally {
        try {
            if (!started) {
                group.threadStartFailed(this);
            }
        } catch (Throwable ignore) {
            /* do nothing. If start0 threw a Throwable then
              it will be passed up the call stack */
        }
    }
}

private native void start0();
```

call [JVM_StartThread](/docs/CS/Java/JDK/Concurrency/Thread.md?id=JVM_StartThread)
```c
//Thread.c
static JNINativeMethod methods[] = {
    {"start0",           "()V",        (void *)&JVM_StartThread},
    {"stop0",            "(" OBJ ")V", (void *)&JVM_StopThread},
    {"isAlive",          "()Z",        (void *)&JVM_IsThreadAlive},
    {"suspend0",         "()V",        (void *)&JVM_SuspendThread},
    {"resume0",          "()V",        (void *)&JVM_ResumeThread},
    {"setPriority0",     "(I)V",       (void *)&JVM_SetThreadPriority},
    {"yield",            "()V",        (void *)&JVM_Yield},
    {"sleep",            "(J)V",       (void *)&JVM_Sleep},
    {"currentThread",    "()" THD,     (void *)&JVM_CurrentThread},
    {"countStackFrames", "()I",        (void *)&JVM_CountStackFrames},
    {"interrupt0",       "()V",        (void *)&JVM_Interrupt},
    {"isInterrupted",    "(Z)Z",       (void *)&JVM_IsInterrupted},
    {"holdsLock",        "(" OBJ ")Z", (void *)&JVM_HoldsLock},
    {"getThreads",        "()[" THD,   (void *)&JVM_GetAllThreads},
    {"dumpThreads",      "([" THD ")[[" STE, (void *)&JVM_DumpThreads},
    {"setNativeName",    "(" STR ")V", (void *)&JVM_SetNativeThreadName},
};
```


### JVM_StartThread

JVM_StartThread:

1. `native_thread = new JavaThread`
   1. `os::create_thread invoke pthread_create()`
   2. ` while (state  == ALLOCATED), Monitor::wait(Mutex::_no_safepoint_check_flag)`
   3. `after Monitor::notify, thread->call_run()`
2. `Thread::start(native_thread)`
   1. `os::start_thread(thread), set_state(RUNNABLE)`
   2. `pd_start_thread invoke Monitor::notify`


```cpp
//jvm.cpp
JVM_ENTRY(void, JVM_StartThread(JNIEnv* env, jobject jthread))
  JVMWrapper("JVM_StartThread");
  JavaThread *native_thread = NULL;

  // We cannot hold the Threads_lock when we throw an exception,
  // due to rank ordering issues. Example:  we might need to grab the
  // Heap_lock while we construct the exception.
  bool throw_illegal_thread_state = false;

  // We must release the Threads_lock before we can post a jvmti event
  // in Thread::start.
  {
    // Ensure that the C++ Thread and OSThread structures aren't freed before
    // we operate.
    MutexLocker mu(Threads_lock);

    // Since JDK 5 the java.lang.Thread threadStatus is used to prevent
    // re-starting an already started thread, so we should usually find
    // that the JavaThread is null. However for a JNI attached thread
    // there is a small window between the Thread object being created
    // (with its JavaThread set) and the update to its threadStatus, so we
    // have to check for this
    if (java_lang_Thread::thread(JNIHandles::resolve_non_null(jthread)) != NULL) {
      throw_illegal_thread_state = true;
    } else {
      // We could also check the stillborn flag to see if this thread was already stopped, but
      // for historical reasons we let the thread detect that itself when it starts running

      jlong size =
             java_lang_Thread::stackSize(JNIHandles::resolve_non_null(jthread));
```
Allocate the C++ Thread structure and create the native thread.  The
stack size retrieved from java is 64-bit signed, but the constructor takes
size_t (an unsigned type), which may be 32 or 64-bit depending on the platform.
 - Avoid truncating on 32-bit platforms if size is greater than UINT_MAX.
 - Avoid passing negative values which would result in really large stacks.
```
      NOT_LP64(if (size > SIZE_MAX) size = SIZE_MAX;)
      size_t sz = size > 0 ? (size_t) size : 0;
```
call [new JavaThread](/docs/CS/Java/JDK/Concurrency/Thread.md?id=JavaThreadJavaThread)
```cpp
      native_thread = new JavaThread(&thread_entry, sz);

      // At this point it may be possible that no osthread was created for the
      // JavaThread due to lack of memory. Check for this situation and throw
      // an exception if necessary. Eventually we may want to change this so
      // that we only grab the lock if the thread was created successfully -
      // then we can also do this check and throw the exception in the
      // JavaThread constructor.
      if (native_thread->osthread() != NULL) {
        // Note: the current thread is not being used within "prepare".
        native_thread->prepare(jthread);
      }
    }
  }

  if (throw_illegal_thread_state) {
    THROW(vmSymbols::java_lang_IllegalThreadStateException());
  }

  if (native_thread->osthread() == NULL) {
    // No one should hold a reference to the 'native_thread'.
    native_thread->smr_delete();
    if (JvmtiExport::should_post_resource_exhausted()) {
      JvmtiExport::post_resource_exhausted(
        JVMTI_RESOURCE_EXHAUSTED_OOM_ERROR | JVMTI_RESOURCE_EXHAUSTED_THREADS,
        os::native_thread_creation_failed_msg());
    }
    THROW_MSG(vmSymbols::java_lang_OutOfMemoryError(),
              os::native_thread_creation_failed_msg());
  }

  Thread::start(native_thread);
JVM_END
```



`thread_entry` for JavaCalls 

```cpp
// jvm.cpp
static void thread_entry(JavaThread* thread, TRAPS) {
  HandleMark hm(THREAD);
  Handle obj(THREAD, thread->threadObj());
  JavaValue result(T_VOID);
  JavaCalls::call_virtual(&result,
                          obj,
                          SystemDictionary::Thread_klass(),
                          // template(run_method_name, "run") 
                          vmSymbols::run_method_name(),
                          vmSymbols::void_method_signature(),
                          THREAD);
}
```



### JavaThread::JavaThread



```cpp
// thread.cpp
JavaThread::JavaThread(ThreadFunction entry_point, size_t stack_sz) :
                       Thread() {
  initialize();
  _jni_attach_state = _not_attaching_via_jni;
  set_entry_point(entry_point);
  // Create the native thread itself.
  // %note runtime_23
  os::ThreadType thr_type = os::java_thread;
  thr_type = entry_point == &compiler_thread_entry ? os::compiler_thread :
                                                     os::java_thread;
  os::create_thread(this, thr_type, stack_sz);
  // The _osthread may be NULL here because we ran out of memory (too many threads active).
  // We need to throw and OutOfMemoryError - however we cannot do this here because the caller
  // may hold a lock and all locks must be unlocked before throwing the exception (throwing
  // the exception consists of creating the exception object & initializing it, initialization
  // will leave the VM via a JavaCall and then all locks must be unlocked).
  //
  // The thread is still suspended when we reach here. Thread must be explicit started
  // by creator! Furthermore, the thread must also explicitly be added to the Threads list
  // by calling Threads:add. The reason why this is not done here, is because the thread
  // object must be fully initialized (take a look at JVM_Start)
}
```



### os::create_thread

todo PTHREAD_CREATE_DETACHED

```cpp
//os_linux.cpp
bool os::create_thread(Thread* thread, ThreadType thr_type,
                       size_t req_stack_size) {
  assert(thread->osthread() == NULL, "caller responsible");

  // Allocate the OSThread object
  OSThread* osthread = new OSThread(NULL, NULL);
  if (osthread == NULL) {
    return false;
  }

  // set the correct thread state
  osthread->set_thread_type(thr_type);

  // Initial state is ALLOCATED but not INITIALIZED
  osthread->set_state(ALLOCATED);

  thread->set_osthread(osthread);

  // init thread attributes
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

  // Calculate stack size if it's not specified by caller.
  size_t stack_size = os::Posix::get_initial_stack_size(thr_type, req_stack_size);
  // In the Linux NPTL pthread implementation the guard size mechanism
  // is not implemented properly. The posix standard requires adding
  // the size of the guard pages to the stack size, instead Linux
  // takes the space out of 'stacksize'. Thus we adapt the requested
  // stack_size by the size of the guard pages to mimick proper
  // behaviour. However, be careful not to end up with a size
  // of zero due to overflow. Don't add the guard page in that case.
  size_t guard_size = os::Linux::default_guard_size(thr_type);
  if (stack_size <= SIZE_MAX - guard_size) {
    stack_size += guard_size;
  }
  assert(is_aligned(stack_size, os::vm_page_size()), "stack_size not aligned");

  int status = pthread_attr_setstacksize(&attr, stack_size);
  assert_status(status == 0, status, "pthread_attr_setstacksize");

  // Configure glibc guard page.
  pthread_attr_setguardsize(&attr, os::Linux::default_guard_size(thr_type));

  ThreadState state;

  {
    pthread_t tid;
    //
    int ret = pthread_create(&tid, &attr, (void* (*)(void*)) thread_native_entry, thread);

    char buf[64];
    if (ret == 0) {
      log_info(os, thread)("Thread started (pthread id: " UINTX_FORMAT ", attributes: %s). ",
        (uintx) tid, os::Posix::describe_pthread_attr(buf, sizeof(buf), &attr));
    } else {
      log_warning(os, thread)("Failed to start thread - pthread_create failed (%s) for attributes: %s.",
        os::errno_name(ret), os::Posix::describe_pthread_attr(buf, sizeof(buf), &attr));
    }

    pthread_attr_destroy(&attr);

    if (ret != 0) {
      // Need to clean up stuff we've allocated so far
      thread->set_osthread(NULL);
      delete osthread;
      return false;
    }

    // Store pthread info into the OSThread
    osthread->set_pthread_id(tid);

    // Wait until child thread is either initialized or aborted
    {
      Monitor* sync_with_child = osthread->startThread_lock();
      MutexLockerEx ml(sync_with_child, Mutex::_no_safepoint_check_flag);
      while ((state = osthread->get_state()) == ALLOCATED) {
        sync_with_child->wait(Mutex::_no_safepoint_check_flag);
      }
    }
  }

  // Aborted due to thread limit being reached
  if (state == ZOMBIE) {
    thread->set_osthread(NULL);
    delete osthread;
    return false;
  }

  // The thread is returned suspended (in state INITIALIZED),
  // and is started higher up in the call chain
  assert(state == INITIALIZED, "race condition");
  return true;
}

// Thread start routine for all newly created threads
static void *thread_native_entry(Thread *thread) {

  thread->record_stack_base_and_size();

  // Try to randomize the cache line index of hot stack frames.
  // This helps when threads of the same stack traces evict each other's
  // cache lines. The threads can be either from the same JVM instance, or
  // from different JVM instances. The benefit is especially true for
  // processors with hyperthreading technology.
  static int counter = 0;
  int pid = os::current_process_id();
  alloca(((pid ^ counter++) & 7) * 128);

  thread->initialize_thread_current();

  OSThread* osthread = thread->osthread();
  Monitor* sync = osthread->startThread_lock();

  osthread->set_thread_id(os::current_thread_id());

  log_info(os, thread)("Thread is alive (tid: " UINTX_FORMAT ", pthread id: " UINTX_FORMAT ").",
    os::current_thread_id(), (uintx) pthread_self());

  if (UseNUMA) {
    int lgrp_id = os::numa_get_group_id();
    if (lgrp_id != -1) {
      thread->set_lgrp_id(lgrp_id);
    }
  }
  // initialize signal mask for this thread
  os::Linux::hotspot_sigmask(thread);

  // initialize floating point control register
  os::Linux::init_thread_fpu_state();

  // handshaking with parent thread
  {
    MutexLockerEx ml(sync, Mutex::_no_safepoint_check_flag);

    // notify parent thread
    osthread->set_state(INITIALIZED);
    sync->notify_all();

    // wait until os::start_thread()
    while (osthread->get_state() == INITIALIZED) {
      sync->wait(Mutex::_no_safepoint_check_flag);
    }
  }

  // call one more level start routine
  thread->call_run();

  // Note: at this point the thread object may already have deleted itself.
  // Prevent dereferencing it from here on out.
  thread = NULL;

  log_info(os, thread)("Thread finished (tid: " UINTX_FORMAT ", pthread id: " UINTX_FORMAT ").",
    os::current_thread_id(), (uintx) pthread_self());

  return 0;
}
```

### Thread::start

`Set RUNNABLE before os::start_thread(thread)`


```cpp
// thread.cpp
void Thread::start(Thread* thread) {
  // Start is different from resume in that its safety is guaranteed by context or
  // being called from a Java method synchronized on the Thread object.
  if (!DisableStartThread) {
    if (thread->is_Java_thread()) {
      // Initialize the thread state to RUNNABLE before starting this thread.
      // Can not set it after the thread started because we do not know the
      // exact thread state at that time. It could be in MONITOR_WAIT or
      // in SLEEPING or some other state.
      java_lang_Thread::set_thread_status(((JavaThread*)thread)->threadObj(),
                                          java_lang_Thread::RUNNABLE);
    }
    os::start_thread(thread);
  }
}


// The INITIALIZED state is distinguished from the SUSPENDED state because the
// conditions in which a thread is first started are different from those in which
// a suspension is resumed.  These differences make it hard for us to apply the
// tougher checks when starting threads that we want to do when resuming them.
// However, when start_thread is called as a result of Thread.start, on a Java
// thread, the operation is synchronized on the Java Thread object.  So there
// cannot be a race to start the thread and hence for the thread to exit while
// we are working on it.  Non-Java threads that start Java threads either have
// to do so in a context in which races are impossible, or should do appropriate
// locking.

//os.cpp
void os::start_thread(Thread* thread) {
  // guard suspend/resume
  MutexLockerEx ml(thread->SR_lock(), Mutex::_no_safepoint_check_flag);
  OSThread* osthread = thread->osthread();
  osthread->set_state(RUNNABLE);
  pd_start_thread(thread);
}

// os_linux.cpp
void os::pd_start_thread(Thread* thread) {
  OSThread * osthread = thread->osthread();
  assert(osthread->get_state() != INITIALIZED, "just checking");
  Monitor* sync_with_child = osthread->startThread_lock();
  MutexLockerEx ml(sync_with_child, Mutex::_no_safepoint_check_flag);
  sync_with_child->notify();
}
```



### Monitor::notify


```cpp
// mutex.cpp
bool Monitor::notify() {
  assert(_owner == Thread::current(), "invariant");
  assert(ILocked(), "invariant");
  if (_WaitSet == NULL) return true;

  // Transfer one thread from the WaitSet to the EntryList or cxq.
  // Currently we just unlink the head of the WaitSet and prepend to the cxq.
  // And of course we could just unlink it and unpark it, too, but
  // in that case it'd likely impale itself on the reentry.
  Thread::muxAcquire(_WaitLock, "notify:WaitLock");
  ParkEvent * nfy = _WaitSet;
  if (nfy != NULL) {                  // DCL idiom
    _WaitSet = nfy->ListNext;
    assert(nfy->Notified == 0, "invariant");
    // push nfy onto the cxq
    for (;;) {
      const intptr_t v = _LockWord.FullWord;
      assert((v & 0xFF) == _LBIT, "invariant");
      nfy->ListNext = (ParkEvent *)(v & ~_LBIT);
      if (Atomic::cmpxchg(intptr_t(nfy)|_LBIT, &_LockWord.FullWord, v) == v) break;
      // interference - _LockWord changed -- just retry
    }
    // Note that setting Notified before pushing nfy onto the cxq is
    // also legal and safe, but the safety properties are much more
    // subtle, so for the sake of code stewardship ...
    OrderAccess::fence();
    nfy->Notified = 1;
  }
  Thread::muxRelease(_WaitLock);
  assert(ILocked(), "invariant");
  return true;
}
```



### JavaThread::run

```cpp
// thread.cpp
// The first routine called by a new Java thread
void JavaThread::run() {
  // initialize thread-local alloc buffer related fields
  this->initialize_tlab();

  // used to test validity of stack trace backs
  this->record_base_of_stack_pointer();

  this->create_stack_guard_pages();

  this->cache_global_variables();

  // Thread is now sufficient initialized to be handled by the safepoint code as being
  // in the VM. Change thread state from _thread_new to _thread_in_vm
  ThreadStateTransition::transition_and_fence(this, _thread_new, _thread_in_vm);

  DTRACE_THREAD_PROBE(start, this);

  // This operation might block. We call that after all safepoint checks for a new thread has
  // been completed.
  this->set_active_handles(JNIHandleBlock::allocate_block());

  if (JvmtiExport::should_post_thread_life()) {
    JvmtiExport::post_thread_start(this);

  }

  // We call another function to do the rest so we are sure that the stack addresses used
  // from there will be lower than the stack base just computed
  thread_main_inner();

  // Note, thread is no longer valid at this point!
}

void JavaThread::thread_main_inner() {
```
Execute thread entry point unless this thread has a pending exception
or has been stopped before starting.
Note: Due to `JVM_StopThread` we can have pending exceptions already!
```cpp
  if (!this->has_pending_exception() &&
      !java_lang_Thread::is_stillborn(this->threadObj())) {
    {
      ResourceMark rm(this);
      //set native thread name
      this->set_native_thread_name(this->get_thread_name());
    }
    HandleMark hm(this);
```
execute entry_point -> run_method_name(`Thread.run()`)
```cpp
    this->entry_point()(this, this);
  }

  this->exit(false);
  this->smr_delete();
}
```



## Wait Sets and Notification

Every object, in addition to having an associated monitor, has an associated *wait set*. A wait set is a set of threads.

When an object is first created, its wait set is empty. Elementary actions that add threads to and remove threads from wait sets are atomic.

Wait sets are manipulated solely through the methods `Object``.``wait`, `Object``.``notify`, and `Object``.``notifyAll`.

### wait
**The current thread must own [this object's monitor](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=ObjectMonitor).** use `CHECK_OWNER`.

> [!NOTE]
> 
> Use `wait` in a while loop avoid **spurious wakeups**.

Causes the current thread to wait until:
- either another thread invokes the `Object::notify` or the `Object::notifyAll` for this object
- or a specified amount of time has elapsed.
- or if any thread interrupted the current thread. **The interrupted status of the current thread is cleared when this exception is thrown.**

Each thread must determine an order over the events that could cause it to be removed from a wait set. 
That order does not have to be consistent with other orderings, but the thread must behave as though those events occurred in that order.

For example, if a thread t is in the wait set for m, and then both an interrupt of t and a notification of m occur, there must be an order over these events. 
If the interrupt is deemed to have occurred first, then t will eventually return from wait by throwing InterruptedException, 
and some other thread in the wait set for m (if any exist at the time of the notification) must receive the notification. 
If the notification is deemed to have occurred first, then t will eventually return normally from wait with an interrupt still pending.


```java
public final native void wait(long timeout) throws InterruptedException;

public final void wait(long timeout, int nanos) throws InterruptedException {
    wait(timeout);
}

public final void wait() throws InterruptedException {
    wait(0);
}
```


#### join

Waits at most millis milliseconds for this thread to die. A timeout of 0 means to wait forever.
This implementation uses **a loop of this.wait** calls conditioned on this.isAlive.
As a thread terminates the this.notifyAll method is invoked.
**It is recommended that applications not use wait, notify, or notifyAll on Thread instances.**


Actually call [wait](/docs/CS/Java/JDK/Concurrency/Thread.md?id=wait)
```java
public final synchronized void join(long millis) throws InterruptedException {
    ...
    while (isAlive()) {
        wait(0);
    }
}
```



#### ObjectSynchronizer::wait

must get monitor by [ObjectSynchronizer::inflate](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=inflate)

```cpp
// NOTE: must use heavy weight monitor to handle wait()
int ObjectSynchronizer::wait(Handle obj, jlong millis, TRAPS) {
  if (UseBiasedLocking) {
    BiasedLocking::revoke_and_rebias(obj, false, THREAD);
  }
  ObjectMonitor* monitor = ObjectSynchronizer::inflate(THREAD,
                                                       obj(),
                                                       inflate_cause_wait);
	//invoke ObjectMonitor::wait
  monitor->wait(millis, true, THREAD);

  return dtrace_waited_probe(monitor, obj, THREAD);
}
```

#### ObjectMonitor::wait

1. check for a pending interrupt and ClearInterrupted, THROW(vmSymbols::java_lang_InterruptedException())
2. CHECK_OWNER
3. **AddWaiter**, enter the wait queue
4. exit monitor
5. **`Park`** Self
6. ReenterI  or enter when unPark by other Thread

```cpp
//objectMonitor.cpp
// Note: a subset of changes to ObjectMonitor::wait()
// will need to be replicated in complete_exit
void ObjectMonitor::wait(jlong millis, bool interruptible, TRAPS) {
  Thread * const Self = THREAD;
  JavaThread *jt = (JavaThread *)THREAD;

  // Throw IMSX or IEX.
  CHECK_OWNER();

  EventJavaMonitorWait event;

  // check for a pending interrupt and ClearInterrupted
  if (interruptible && Thread::is_interrupted(Self, true) && !HAS_PENDING_EXCEPTION) {
    THROW(vmSymbols::java_lang_InterruptedException());
    return;
  }

	// AddWaiter
  Thread::SpinAcquire(&_WaitSetLock, "WaitSet - add");
  AddWaiter(&node);
  Thread::SpinRelease(&_WaitSetLock);

  _Responsible = NULL;

  intptr_t save = _recursions; // record the old recursion count
  _waiters++;                  // increment the number of waiters
  _recursions = 0;             // set the recursion level to be 1
  exit(true, Self);                    // exit the monitor
  guarantee(_owner != Self, "invariant");

  // TODO-FIXME: change the following logic to a loop of the form
  //   while (!timeout && !interrupted && _notified == 0) park()
        if (millis <= 0) {
          Self->_ParkEvent->park();
        } else {
          ret = Self->_ParkEvent->park(millis);
        }
	// Exit thread safepoint: transition _thread_blocked -> _thread_in_vm

    

    if (node.TState == ObjectWaiter::TS_WAIT) {
      Thread::SpinAcquire(&_WaitSetLock, "WaitSet - unlink");
      if (node.TState == ObjectWaiter::TS_WAIT) {
        DequeueSpecificWaiter(&node);       // unlink from WaitSet
        node.TState = ObjectWaiter::TS_RUN;
      }
      Thread::SpinRelease(&_WaitSetLock);
    }

    // post monitor waited event. Note that this is past-tense, we are done waiting.
    if (JvmtiExport::should_post_monitor_waited()) {
      JvmtiExport::post_monitor_waited(jt, this, ret == OS_TIMEOUT);

      if (node._notified != 0 && _succ == Self) {
        node._event->unpark();
      }
    }
		
  	// enter or reenter 
    ObjectWaiter::TStates v = node.TState;
    if (v == ObjectWaiter::TS_RUN) {
      enter(Self);
    } else {
      guarantee(v == ObjectWaiter::TS_ENTER || v == ObjectWaiter::TS_CXQ, "invariant");
      ReenterI(Self, &node);
      node.wait_reenter_end(this);
    }
  	// OSThreadWaitState()

  jt->set_current_waiting_monitor(NULL);

  guarantee(_recursions == 0, "invariant");
  _recursions = save;     // restore the old recursion count
  _waiters--;             // decrement the number of waiters

  // check if the notification happened
  if (!WasNotified) {
    // no, it could be timeout or Thread.interrupt() or both
    // check for interrupt event, otherwise it is timeout
    if (interruptible && Thread::is_interrupted(Self, true) && !HAS_PENDING_EXCEPTION) {
      THROW(vmSymbols::java_lang_InterruptedException());
    }
  }
}
```



### Notification

wake up thread when exit the sync block

|       | notify | notifyAll |
| ----- | ------ | --------- |
| order | FIFO   | LIFO      |

notifyAll foreach from tail -> head



```java
public final native void notify();

public final native void notifyAll();

```

**TODO**: *Consider: If the lock is cool (cxq == null && succ == null) and we're on an MP system then instead of transferring a thread from the WaitSet to the EntryList we might just dequeue a thread from the WaitSet and directly unpark() it.*

*Consider: a not-uncommon synchronization bug is to use `notify()` when `notifyAll()` is more appropriate, potentially resulting in stranded threads; 
this is one example of a lost wakeup. A useful diagnostic option is to force all notify() operations to behave as notifyAll().*

*Note: We can also detect many such problems with a "minimum wait". 
When the "minimum wait" is set to a small non-zero timeout value and the program does not hang whereas it did absent "minimum wait", that suggests a lost wakeup bug.*


dequeue from the WaitSet to the EntryList or _cxq

```cpp
void ObjectMonitor::notify(TRAPS) {
  CHECK_OWNER();
  if (_WaitSet == NULL) {
    return;
  }
  DTRACE_MONITOR_PROBE(notify, this, object(), THREAD);
  INotify(THREAD);
  OM_PERFDATA_OP(Notifications, inc(1));
}

void ObjectMonitor::INotify(Thread * Self) {
  Thread::SpinAcquire(&_WaitSetLock, "WaitSet - notify");
  ObjectWaiter * iterator = DequeueWaiter();
  if (iterator != NULL) {
    guarantee(iterator->TState == ObjectWaiter::TS_WAIT, "invariant");
    guarantee(iterator->_notified == 0, "invariant");
    // Disposition - what might we do with iterator ?
    // a.  add it directly to the EntryList - either tail (policy == 1)
    //     or head (policy == 0).
    // b.  push it onto the front of the _cxq (policy == 2).
    // For now we use (b).

    iterator->TState = ObjectWaiter::TS_ENTER;

    iterator->_notified = 1;
    iterator->_notifier_tid = JFR_THREAD_ID(Self);

    ObjectWaiter * list = _EntryList;
    if (list != NULL) {
      assert(list->_prev == NULL, "invariant");
      assert(list->TState == ObjectWaiter::TS_ENTER, "invariant");
      assert(list != iterator, "invariant");
    }

    // prepend to cxq
    if (list == NULL) {
      iterator->_next = iterator->_prev = NULL;
      _EntryList = iterator;
    } else {
      iterator->TState = ObjectWaiter::TS_CXQ;
      for (;;) {
        ObjectWaiter * front = _cxq;
        iterator->_next = front;
        if (Atomic::cmpxchg(iterator, &_cxq, front) == front) {
          break;
        }
      }
    }
```
_WaitSetLock protects the wait queue, not the EntryList.  
We could move the add-to-EntryList operation, above, outside the critical section protected by _WaitSetLock.  In practice that's not useful.  
With the exception of  wait() timeouts and interrupts the monitor owner is the only thread that grabs _WaitSetLock.  
There's almost no contention on _WaitSetLock so it's not profitable to reduce the length of the critical section.

```cpp
    iterator->wait_reenter_begin(this);
  }
  Thread::SpinRelease(&_WaitSetLock);
}
```



*_WaitSetLock protects the wait queue, not the EntryList.  We could move the add-to-EntryList operation, above, outside the critical section protected by _WaitSetLock.  
In practice that's not useful.  With the exception of  wait() timeouts and interrupts the monitor owner is the only thread that grabs _WaitSetLock.  
**There's almost no contention on _WaitSetLock** so it's not profitable to reduce the length of the critical section.*

**notifyAll** when JavaThread exit

```cpp
void JavaThread::exit(bool destroy_vm, ExitType exit_type) {
	//...
  ensure_join(this);
  //...
}
static void ensure_join(JavaThread* thread) {
    Handle threadObj(thread, thread->threadObj());

    ObjectLocker lock(threadObj, thread);

    thread->clear_pending_exception();

    java_lang_Thread::set_thread_status(threadObj(),        java_lang_Thread::TERMINATED);
    java_lang_Thread::set_thread(threadObj(), NULL);
    //notify_all
    lock.notify_all(thread);
    thread->clear_pending_exception();
}
```



#### ObjectMonitor::exit

```cpp
void ObjectMonitor::exit(bool not_suspended, TRAPS) {
  Thread * const Self = THREAD;
  if (THREAD != _owner) {
    if (THREAD->is_lock_owned((address) _owner)) {
      // Transmute _owner from a BasicLock pointer to a Thread address.
      // We don't need to hold _mutex for this transition.
      // Non-null to Non-null is safe as long as all readers can
      // tolerate either flavor.
      assert(_recursions == 0, "invariant");
      _owner = THREAD;
      _recursions = 0;
    } else {
      // Apparent unbalanced locking ...
      // Naively we'd like to throw IllegalMonitorStateException.
      // As a practical matter we can neither allocate nor throw an
      // exception as ::exit() can be called from leaf routines.
      // see x86_32.ad Fast_Unlock() and the I1 and I2 properties.
      // Upon deeper reflection, however, in a properly run JVM the only
      // way we should encounter this situation is in the presence of
      // unbalanced JNI locking. TODO: CheckJNICalls.
      // See also: CR4414101
      assert(false, "Non-balanced monitor enter/exit! Likely JNI locking");
      return;
    }
  }

  if (_recursions != 0) {
    _recursions--;        // this is simple recursive enter
    return;
  }

  // Invariant: after setting Responsible=null an thread must execute
  // a MEMBAR or other serializing instruction before fetching EntryList|cxq.
  _Responsible = NULL;

#if INCLUDE_JFR
  // get the owner's thread id for the MonitorEnter event
  // if it is enabled and the thread isn't suspended
  if (not_suspended && EventJavaMonitorEnter::is_enabled()) {
    _previous_owner_tid = JFR_THREAD_ID(Self);
  }
#endif

  for (;;) {
    assert(THREAD == _owner, "invariant");

    // release semantics: prior loads and stores from within the critical section
    // must not float (reorder) past the following store that drops the lock.
    // On SPARC that requires MEMBAR #loadstore|#storestore.
    // But of course in TSO #loadstore|#storestore is not required.
    OrderAccess::release_store(&_owner, (void*)NULL);   // drop the lock
    OrderAccess::storeload();                        // See if we need to wake a successor
    if ((intptr_t(_EntryList)|intptr_t(_cxq)) == 0 || _succ != NULL) {
      return;
    }
    // Other threads are blocked trying to acquire the lock.

    // Normally the exiting thread is responsible for ensuring succession,
    // but if other successors are ready or other entering threads are spinning
    // then this thread can simply store NULL into _owner and exit without
    // waking a successor.  The existence of spinners or ready successors
    // guarantees proper succession (liveness).  Responsibility passes to the
    // ready or running successors.  The exiting thread delegates the duty.
    // More precisely, if a successor already exists this thread is absolved
    // of the responsibility of waking (unparking) one.
    //
    // The _succ variable is critical to reducing futile wakeup frequency.
    // _succ identifies the "heir presumptive" thread that has been made
    // ready (unparked) but that has not yet run.  We need only one such
    // successor thread to guarantee progress.
    // See http://www.usenix.org/events/jvm01/full_papers/dice/dice.pdf
    // section 3.3 "Futile Wakeup Throttling" for details.
    //
    // Note that spinners in Enter() also set _succ non-null.
    // In the current implementation spinners opportunistically set
    // _succ so that exiting threads might avoid waking a successor.
    // Another less appealing alternative would be for the exiting thread
    // to drop the lock and then spin briefly to see if a spinner managed
    // to acquire the lock.  If so, the exiting thread could exit
    // immediately without waking a successor, otherwise the exiting
    // thread would need to dequeue and wake a successor.
    // (Note that we'd need to make the post-drop spin short, but no
    // shorter than the worst-case round-trip cache-line migration time.
    // The dropped lock needs to become visible to the spinner, and then
    // the acquisition of the lock by the spinner must become visible to
    // the exiting thread).

    // It appears that an heir-presumptive (successor) must be made ready.
    // Only the current lock owner can manipulate the EntryList or
    // drain _cxq, so we need to reacquire the lock.  If we fail
    // to reacquire the lock the responsibility for ensuring succession
    // falls to the new owner.
    //
    if (!Atomic::replace_if_null(THREAD, &_owner)) {
      return;
    }

    guarantee(_owner == THREAD, "invariant");

    ObjectWaiter * w = NULL;

    w = _EntryList;
    if (w != NULL) {
      // I'd like to write: guarantee (w->_thread != Self).
      // But in practice an exiting thread may find itself on the EntryList.
      // Let's say thread T1 calls O.wait().  Wait() enqueues T1 on O's waitset and
      // then calls exit().  Exit release the lock by setting O._owner to NULL.
      // Let's say T1 then stalls.  T2 acquires O and calls O.notify().  The
      // notify() operation moves T1 from O's waitset to O's EntryList. T2 then
      // release the lock "O".  T2 resumes immediately after the ST of null into
      // _owner, above.  T2 notices that the EntryList is populated, so it
      // reacquires the lock and then finds itself on the EntryList.
      // Given all that, we have to tolerate the circumstance where "w" is
      // associated with Self.
      assert(w->TState == ObjectWaiter::TS_ENTER, "invariant");
      ExitEpilog(Self, w);
      return;
    }

    // If we find that both _cxq and EntryList are null then just
    // re-run the exit protocol from the top.
    w = _cxq;
    if (w == NULL) continue;

    // Drain _cxq into EntryList - bulk transfer.
    // First, detach _cxq.
    // The following loop is tantamount to: w = swap(&cxq, NULL)
    for (;;) {
      assert(w != NULL, "Invariant");
      ObjectWaiter * u = Atomic::cmpxchg((ObjectWaiter*)NULL, &_cxq, w);
      if (u == w) break;
      w = u;
    }

    assert(w != NULL, "invariant");
    assert(_EntryList == NULL, "invariant");

    // Convert the LIFO SLL anchored by _cxq into a DLL.
    // The list reorganization step operates in O(LENGTH(w)) time.
    // It's critical that this step operate quickly as
    // "Self" still holds the outer-lock, restricting parallelism
    // and effectively lengthening the critical section.
    // Invariant: s chases t chases u.
    // TODO-FIXME: consider changing EntryList from a DLL to a CDLL so
    // we have faster access to the tail.

    _EntryList = w;
    ObjectWaiter * q = NULL;
    ObjectWaiter * p;
    for (p = w; p != NULL; p = p->_next) {
      guarantee(p->TState == ObjectWaiter::TS_CXQ, "Invariant");
      p->TState = ObjectWaiter::TS_ENTER;
      p->_prev = q;
      q = p;
    }

    // In 1-0 mode we need: ST EntryList; MEMBAR #storestore; ST _owner = NULL
    // The MEMBAR is satisfied by the release_store() operation in ExitEpilog().

    // See if we can abdicate to a spinner instead of waking a thread.
    // A primary goal of the implementation is to reduce the
    // context-switch rate.
    if (_succ != NULL) continue;

    w = _EntryList;
    if (w != NULL) {
      guarantee(w->TState == ObjectWaiter::TS_ENTER, "invariant");
      ExitEpilog(Self, w);
      return;
    }
  }
}
```

#### ObjectMonitor::ExitEpilog

Exit protocol:

1. ST _succ = wakee
2. membar #loadstore|#storestore;
3. ST _owner = NULL
4. unpark(wakee)

```cpp
void ObjectMonitor::ExitEpilog(Thread * Self, ObjectWaiter * Wakee) {
  ParkEvent * Trigger = Wakee->_event;

  // Hygiene -- once we've set _owner = NULL we can't safely dereference Wakee again.
  // The thread associated with Wakee may have grabbed the lock and "Wakee" may be
  // out-of-scope (non-extant).
  Wakee  = NULL;

  // Drop the lock
  OrderAccess::release_store(&_owner, (void*)NULL);
  OrderAccess::fence();                               // ST _owner vs LD in unpark()

  DTRACE_MONITOR_PROBE(contended__exit, this, object(), Self);
  Trigger->unpark();

  // Maintain stats and report events to JVMTI
  OM_PERFDATA_OP(Parks, inc());
}
```







### Interruptions

*The `interrupt` method interrupts **this thread**.*
Unless the current thread is interrupting itself, which is always permitted, the checkAccess method of this thread is invoked, which may cause a SecurityException to be thrown.
The interruption is that it doesn’t actually interrupt a running thread — it just requests that the thread interrupt itself at the next convenient opportunity.
1. If this thread is blocked in an invocation of the wait(), wait(long), or wait(long, int) methods of the Object class, or of the join(), join(long), join(long, int), sleep(long), or sleep(long, int), methods of this class, then its interrupt status will be cleared and it will receive an InterruptedException.

2. If this thread is blocked in an I/O operation upon an InterruptibleChannel then the channel will be closed, the thread's interrupt status will be set, and the thread will receive a java.nio.channels.ClosedByInterruptException.
   If this thread is blocked in a java.nio.channels.Selector then the thread's interrupt status will be set and it will return immediately from the selection operation, possibly with a non-zero value, just as if the selector's wakeup method were invoked.

3. If none of the previous conditions hold then this thread's interrupt status will be set.

4. Interrupting a thread that is not alive need not have any effect.

Threads may block for several reasons: waiting to wake up from a Thread.sleep(), waiting to acquire a lock, waiting for I/O completion, or waiting for the result of a computation in another thread, among others.

The InterruptedException is usually thrown by all blocking methods so that it can be handled and the corrective action can be performed. There are several methods in Java that throw InterruptedException. These include Thread.sleep(), Thread.join(), the wait() method of the Object class, and put() and take() methods of BlockingQueue, to name a few.



*The `interrupted` method Tests whether the **current thread** has been interrupted and clear interrupted status.*
*The `isInterrupted` method tests whether **this thread** has been interrupted. A thread interruption ignored because a thread was not alive at the time of the interrupt will be reflected by this method returning false.*

```java
public void interrupt() {
    if (this != Thread.currentThread())
        checkAccess();

    synchronized (blockerLock) {
        Interruptible b = blocker;
        if (b != null) {
            interrupt0();           // Just to set the interrupt flag
            b.interrupt(this);
            return;
        }
    }
    interrupt0();
}

public static boolean interrupted() {
    return currentThread().isInterrupted(true);
}

public boolean isInterrupted() {
    return isInterrupted(false);
}

private native boolean isInterrupted(boolean ClearInterrupted);
```

```cpp
// share/runtime/thread.cpp
void JavaThread::interrupt() {
  // All callers should have 'this' thread protected by a
  // ThreadsListHandle so that it cannot terminate and deallocate
  // itself.

  // For Thread.sleep
  _SleepEvent->unpark();

  // For JSR166 LockSupport.park
  parker()->unpark();

  // For ObjectMonitor and JvmtiRawMonitor
  _ParkEvent->unpark();
}
```

#### JVM_Interrupt

1. `OSThread::set_interrupted(true)`
2. `ParkEvent::unpark`

```c
//Thread.c
{"interrupt0",       "()V",        (void *)&JVM_Interrupt},
```

```cpp
//jvm.cpp
JVM_ENTRY(void, JVM_Interrupt(JNIEnv* env, jobject jthread))
  JVMWrapper("JVM_Interrupt");

  ThreadsListHandle tlh(thread);
  JavaThread* receiver = NULL;
  bool is_alive = tlh.cv_internal_thread_to_JavaThread(jthread, &receiver, NULL);
  if (is_alive) {
    // jthread refers to a live JavaThread.
    Thread::interrupt(receiver);
  }
JVM_END

//thread.cpp
void Thread::interrupt(Thread* thread) {
  os::interrupt(thread);
}

// os.posix.cpp
void os::interrupt(Thread* thread) {
  OSThread* osthread = thread->osthread();

  if (!osthread->interrupted()) {
    osthread->set_interrupted(true);
    // More than one thread can get here with the same value of osthread,
    // resulting in multiple notifications.  We do, however, want the store
    // to interrupted() to be visible to other threads before we execute unpark().
    OrderAccess::fence();
    ParkEvent * const slp = thread->_SleepEvent ;
    if (slp != NULL) slp->unpark() ;
  }

  // For JSR166. Unpark even if interrupt status already was set
  if (thread->is_Java_thread())
    ((JavaThread*)thread)->parker()->unpark();

  ParkEvent * ev = thread->_ParkEvent ;
  if (ev != NULL) ev->unpark() ;
}
```



### Interactions of Waits, Notification, and Interruption
> From JLS:
> 
> If a thread is both notified and interrupted while waiting, it may either:
> - return normally from wait, while still having a pending interrupt (in other words, a call to `Thread.interrupted` would return true)
> - return from wait by throwing an `InterruptedException`
> The thread may not reset its interrupt status and return normally from the call to `wait`.
> 
> Similarly, **notifications cannot be lost due to interrupts**. 
> Assume that a set *s* of threads is in the wait set of an object *m*, and another thread performs a `notify` on *m*. Then either:
> 
> - at least one thread in *s* must return normally from `wait`, or
> - all of the threads in *s* must exit `wait` by throwing `InterruptedException`
> 
> **Note that if a thread is both interrupted and woken via `notify`, and that thread returns from `wait` by throwing an `InterruptedException`, then some other thread in the wait set must be notified.**

Such as two threads wait for lock, may thread1 be notified and `Thread.interrupted` return true while the other thread still waiting

```java
synchronized (lock) {
    thread1.interrupt();
  	// Thread.yield(); 
    lock.notify();
}
```



## Sleep and Yield


`Thread.sleep()` causes the currently executing thread to sleep (temporarily cease execution) for the specified duration, 
subject to the precision and accuracy of system timers and schedulers. The thread **does not lose ownership of any monitors**, 
and resumption of execution will depend on scheduling and the availability of processors on which to execute the thread.

**It is important to note that neither Thread.sleep nor Thread.yield have any synchronization semantics.** 
In particular, the compiler does not have to flush writes cached in registers out to shared memory before a call to sleep or yield, 
nor does the compiler have to reload values cached in registers after a call to sleep or yield. 

> For example, in the following (broken) code fragment, assume that this.done is a non-volatile boolean field:

```java
        while (!this.done)
        Thread.sleep(1000);
```
> The compiler is free to read the field this.done just once, and reuse the cached value in each execution of the loop.
> This would mean that the loop would never terminate, even if another thread changed the value of this.done.



|              | wait      | yield       | sleep       |
| ------------ | --------- | ----------- | ----------- |
| From         | Object    | Thread      | Thread      |
| Lock         | Dependent | Independent | Independent |
| Interruption | Throws    |             | Throws      |


### sleep
if millis = 0, `os::naked_yield()` like [Thread#yield()](/docs/CS/Java/JDK/Concurrency/Thread.md?id=yield)
```cpp

```c
//Thread.c
static JNINativeMethod methods[] = {
    {"sleep",            "(J)V",       (void *)&JVM_Sleep},
    ...
};

// jvm.cpp
JVM_ENTRY(void, JVM_Sleep(JNIEnv* env, jclass threadClass, jlong millis))
  JVMWrapper("JVM_Sleep");

  if (millis < 0) {
    THROW_MSG(vmSymbols::java_lang_IllegalArgumentException(), "timeout value is negative");
  }

  if (Thread::is_interrupted (THREAD, true) && !HAS_PENDING_EXCEPTION) {
    THROW_MSG(vmSymbols::java_lang_InterruptedException(), "sleep interrupted");
  }

  // Save current thread state and restore it at the end of this block.
  // And set new thread state to SLEEPING.
  JavaThreadSleepState jtss(thread);

  HOTSPOT_THREAD_SLEEP_BEGIN(millis);
  EventThreadSleep event;

  if (millis == 0) {
    os::naked_yield();
  } else {
    ThreadState old_state = thread->osthread()->get_state();
    thread->osthread()->set_state(SLEEPING);
    if (os::sleep(thread, millis, true) == OS_INTRPT) {
      // An asynchronous exception (e.g., ThreadDeathException) could have been thrown on
      // us while we were sleeping. We do not overwrite those.
      if (!HAS_PENDING_EXCEPTION) {
        if (event.should_commit()) {
          post_thread_sleep_event(&event, millis);
        }
        HOTSPOT_THREAD_SLEEP_END(1);

        // TODO-FIXME: THROW_MSG returns which means we will not call set_state()
        // to properly restore the thread state.  That's likely wrong.
        THROW_MSG(vmSymbols::java_lang_InterruptedException(), "sleep interrupted");
      }
    }
    thread->osthread()->set_state(old_state);
  }
  if (event.should_commit()) {
    post_thread_sleep_event(&event, millis);
  }
  HOTSPOT_THREAD_SLEEP_END(0);
JVM_END
```

#### os::sleep
1. `OSThread::set_interrupted(true)`
2. `ParkEvent::park`

When `ParkEvent::unpark` by [interrupt()](/docs/CS/Java/JDK/Concurrency/Thread.md?id=JVM_Interrupt), use `OSThread::set_interrupted(true)` at next iteration.

```cpp
// os_posix.cpp
int os::sleep(Thread* thread, jlong millis, bool interruptible) {

  ParkEvent * const slp = thread->_SleepEvent ;
  slp->reset() ;
  OrderAccess::fence() ;

  if (interruptible) {
    jlong prevtime = javaTimeNanos();

    for (;;) {
      // check for a pending interrupt and ClearInterrupted
      if (os::is_interrupted(thread, true)) { 
        return OS_INTRPT;
      }

      jlong newtime = javaTimeNanos();

      if (newtime - prevtime < 0) {
        // time moving backwards, should only happen if no monotonic clock
        // not a guarantee() because JVM should not abort on kernel/glibc bugs
        assert(!os::supports_monotonic_clock(), "unexpected time moving backwards detected in os::sleep(interruptible)");
      } else {
        millis -= (newtime - prevtime) / NANOSECS_PER_MILLISEC;
      }

      if (millis <= 0) {
        return OS_OK;
      }

      prevtime = newtime;

      {
        assert(thread->is_Java_thread(), "sanity check");
        JavaThread *jt = (JavaThread *) thread;
        ThreadBlockInVM tbivm(jt);
        OSThreadWaitState osts(jt->osthread(), false /* not Object.wait() */);

        jt->set_suspend_equivalent();
        // cleared by handle_special_suspend_equivalent_condition() or
        // java_suspend_self() via check_and_wait_while_suspended()

        slp->park(millis);

        // were we externally suspended while we were waiting?
        jt->check_and_wait_while_suspended();
      }
    }
  } else {
    OSThreadWaitState osts(thread->osthread(), false /* not Object.wait() */);
    jlong prevtime = javaTimeNanos();

    for (;;) {
      // It'd be nice to avoid the back-to-back javaTimeNanos() calls on
      // the 1st iteration ...
      jlong newtime = javaTimeNanos();

      if (newtime - prevtime < 0) {
        // time moving backwards, should only happen if no monotonic clock
        // not a guarantee() because JVM should not abort on kernel/glibc bugs
        assert(!os::supports_monotonic_clock(), "unexpected time moving backwards detected on os::sleep(!interruptible)");
      } else {
        millis -= (newtime - prevtime) / NANOSECS_PER_MILLISEC;
      }

      if (millis <= 0) break ;

      prevtime = newtime;
      slp->park(millis);
    }
    return OS_OK ;
  }
}
```

### yield
call os::naked_yield()
```c
//Thread.c
static JNINativeMethod methods[] = {
    {"yield",            "()V",        (void *)&JVM_Yield},
    ...
};

// jvm.cpp
JVM_ENTRY(void, JVM_Yield(JNIEnv *env, jclass threadClass))
  if (os::dont_yield()) return;
  HOTSPOT_THREAD_YIELD();
  os::naked_yield();
JVM_END
```

Linux CFS scheduler (since 2.6.23) does not guarantee sched_yield(2) will actually give up the CPU. Since skip buddy (v2.6.28):
- Sets the yielding task as skip buddy for current CPU's run queue.
- Picks next from run queue, if empty, picks a skip buddy (can be the yielding task).
- Clears skip buddies for this run queue (yielding task no longer a skip buddy).
  An alternative is calling os::naked_short_nanosleep with a small number to avoid
  getting re-scheduled immediately.

```cpp
// os_linux.cpp
void os::naked_yield() {
  sched_yield();
}
```


## Timing
The TimeUnit class provides multiple granularities (including nanoseconds) for specifying and controlling time-out based operations.
Most classes in the package contain operations based on time-outs in addition to indefinite waits.
In all cases that time-outs are used, the time-out specifies the minimum time that the method should wait before indicating that it timed-out.
Implementations make a "best effort" to detect time-outs as soon as possible after they occur.
However, an indefinite amount of time may elapse between a time-out being detected and a thread actually executing again after that time-out.
All methods that accept timeout parameters treat values less than or equal to zero to mean not to wait at all.
To wait "forever", you can use a value of Long.MAX_VALUE.


A TimeUnit represents time durations at a given unit of granularity and provides utility methods to convert across units, and to perform timing and delay operations in these units. 
A TimeUnit does not maintain time information, but only helps organize and use time representations that may be maintained separately across various contexts.

A TimeUnit is mainly used to inform time-based methods how a given timing parameter should be interpreted.

Note however, that there is no guarantee that a particular timeout implementation will be able to notice the passage of time at the same granularity as the given TimeUnit.



**Convenience Methods:**

| Method         | Convenience Method in TimeUnit |
| -------------- | ------------------------------ |
| *Object.wait*  | *timedWait*                    |
| *Thread.join*  | *timedJoin*                    |
| *Thread.sleep* | *sleep*                        |

```java
/**
 * Performs a timed {@link Object#wait(long, int) Object.wait}
 * using this time unit.
 */
public void timedWait(Object obj, long timeout)
        throws InterruptedException {
    if (timeout > 0) {
        long ms = toMillis(timeout);
        int ns = excessNanos(timeout, ms);
        obj.wait(ms, ns);
    }
}

/**
 * Performs a timed {@link Thread#join(long, int) Thread.join}
 * using this time unit.
 */
public void timedJoin(Thread thread, long timeout)
        throws InterruptedException {
    if (timeout > 0) {
        long ms = toMillis(timeout);
        int ns = excessNanos(timeout, ms);
        thread.join(ms, ns);
    }
}

/**
 * Performs a {@link Thread#sleep(long, int) Thread.sleep} using
 * this time unit.
 */
public void sleep(long timeout) throws InterruptedException {
    if (timeout > 0) {
        long ms = toMillis(timeout);
        int ns = excessNanos(timeout, ms);
        Thread.sleep(ms, ns);
    }
}
```

## Thread Affinity


See [OpenHFT Java Thread Affinity library](https://github.com/OpenHFT/Java-Thread-Affinity)

## Fiber

See [Loom](/docs/CS/Java/JDK/Loom.md).

Preemptive Threads-Scheduling

Virtual Thread

## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [JVM Thread](/docs/CS/Java/JDK/JVM/Thread.md)


## References

1. [JLS - Threads and Locks](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html)
2. [The JSR-133 Cookbook for Compiler Writers - Doug Lea](http://gee.cs.oswego.edu/dl/jmm/cookbook.html)
3. [JSR 133 (Java Memory Model) FAQ - Jeremy Manson and Brian Goetz, February 2004](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr-133-faq.html)
4. [Understanding Threads and Locks](https://docs.oracle.com/cd/E13150_01/jrockit_jvm/jrockit/geninfo/diagnos/thread_basics.html)
