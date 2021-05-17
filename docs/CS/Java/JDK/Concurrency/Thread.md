# Thread

## Lifetime

![Thread-Lifetime](../images/Thread-Lifetime.png)

#### Status

A thread can be in one of the following states:

| Status       | Description                                                  |
| ------------ | ------------------------------------------------------------ |
| NEW          | A thread that has not yet started is in this state.          |
| RUNNABLE     | A thread executing in the Java virtual machine is in this state. |
| BLOCKED      | A thread that is blocked waiting for a monitor lock is in this state. |
| WATING       | A thread that is waiting indefinitely for another thread to perform a particular action is in this state. |
| TIME_WAITING | A thread that is waiting for another thread to perform an action for up to a specified waiting time is in this state. |
| TERMINATED   | A thread that has exited is in this state.                   |

## Create

*How to create a Thread instance?*

***Just new a Thread instance.***

```java
/**
 * Allocates a new Thread object.
 */
public Thread() {
    init(null, null, "Thread-" + nextThreadNum(), 0);
}

/**
 * Allocates a new Thread object with Runnable taarget.
 */
public Thread(Runnable target) {
    init(null, target, "Thread-" + nextThreadNum(), 0);
}
```

### Example

1. create a thread extends Thread directly
2. use ThreadLocalExecutor
3. use CompletableFuture submit task
4. use FutureTask



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

### JVM_StartThread

JVM_StartThread:

1. `native_thread = new JavaThread(&thread_entry, sz)`
   1. `os::create_thread(this, thr_type, stack_sz)`
   2. ` while (state  == ALLOCATED), Monitor::wait(Mutex::_no_safepoint_check_flag)`
2. `Thread::start(native_thread)`
   1. `os::start_thread(thread)`
   2. `Monitor::notify`

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

//jvm.h
JNIEXPORT void JNICALL
JVM_StartThread(JNIEnv *env, jobject thread);
```



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
      // Allocate the C++ Thread structure and create the native thread.  The
      // stack size retrieved from java is 64-bit signed, but the constructor takes
      // size_t (an unsigned type), which may be 32 or 64-bit depending on the platform.
      //  - Avoid truncating on 32-bit platforms if size is greater than UINT_MAX.
      //  - Avoid passing negative values which would result in really large stacks.
      NOT_LP64(if (size > SIZE_MAX) size = SIZE_MAX;)
      size_t sz = size > 0 ? (size_t) size : 0;
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

  assert(native_thread != NULL, "Starting null thread?");

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



**JavaThread::run()**

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

  assert(JavaThread::current() == this, "sanity check");
  assert(!Thread::current()->owns_locks(), "sanity check");

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
  assert(JavaThread::current() == this, "sanity check");
  assert(this->threadObj() != NULL, "just checking");

  // Execute thread entry point unless this thread has a pending exception
  // or has been stopped before starting.
  // Note: Due to JVM_StopThread we can have pending exceptions already!
  if (!this->has_pending_exception() &&
      !java_lang_Thread::is_stillborn(this->threadObj())) {
    {
      ResourceMark rm(this);
      this->set_native_thread_name(this->get_thread_name());
    }
    HandleMark hm(this);
    this->entry_point()(this, this);//return _entry_point
  }

  DTRACE_THREAD_PROBE(stop, this);

  this->exit(false);
  this->smr_delete();
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

pthread_create in os_linux.cpp

```cpp
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

## Order

### join

Waits at most millis milliseconds for this thread to die. A timeout of 0 means to wait forever.
This implementation uses **a loop of this.wait** calls conditioned on this.isAlive. As a thread terminates the this.notifyAll method is invoked. It is recommended that applications not use wait, notify, or notifyAll on Thread instances.

```java
public final synchronized void join(long millis)
throws InterruptedException {
    long base = System.currentTimeMillis();
    long now = 0;

    if (millis < 0) {
        throw new IllegalArgumentException("timeout value is negative");
    }

    if (millis == 0) {
        while (isAlive()) {
            wait(0);
        }
    } else {
        while (isAlive()) {
            long delay = millis - now;
            if (delay <= 0) {
                break;
            }
            wait(delay);
            now = System.currentTimeMillis() - base;
        }
    }
}
```





### wait

Provider-Consumer

Wait-notify只是一个condition queue 仅使用于单生产/消费模型

```java
/**
 * Causes the current thread to wait until either another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object, or a
 * specified amount of time has elapsed.
 * <p>
 * The current thread must own this object's monitor.
 * <p>
 * This method causes the current thread (call it <var>T</var>) to
 * place itself in the wait set for this object and then to relinquish
 * any and all synchronization claims on this object. Thread <var>T</var>
 * becomes disabled for thread scheduling purposes and lies dormant
 * until one of four things happens:
 * <ul>
 * <li>Some other thread invokes the {@code notify} method for this
 * object and thread <var>T</var> happens to be arbitrarily chosen as
 * the thread to be awakened.
 * <li>Some other thread invokes the {@code notifyAll} method for this
 * object.
 * <li>Some other thread {@linkplain Thread#interrupt() interrupts}
 * thread <var>T</var>.
 * <li>The specified amount of real time has elapsed, more or less.  If
 * {@code timeout} is zero, however, then real time is not taken into
 * consideration and the thread simply waits until notified.
 * </ul>
 * The thread <var>T</var> is then removed from the wait set for this
 * object and re-enabled for thread scheduling. It then competes in the
 * usual manner with other threads for the right to synchronize on the
 * object; once it has gained control of the object, all its
 * synchronization claims on the object are restored to the status quo
 * ante - that is, to the situation as of the time that the {@code wait}
 * method was invoked. Thread <var>T</var> then returns from the
 * invocation of the {@code wait} method. Thus, on return from the
 * {@code wait} method, the synchronization state of the object and of
 * thread {@code T} is exactly as it was when the {@code wait} method
 * was invoked.
 * <p>
 * A thread can also wake up without being notified, interrupted, or
 * timing out, a so-called <i>spurious wakeup</i>.  While this will rarely
 * occur in practice, applications must guard against it by testing for
 * the condition that should have caused the thread to be awakened, and
 * continuing to wait if the condition is not satisfied.  In other words,
 * waits should always occur in loops, like this one:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait(timeout);
 *         ... // Perform action appropriate to condition
 *     }
 * </pre>
 * (For more information on this topic, see Section 3.2.3 in Doug Lea's
 * "Concurrent Programming in Java (Second Edition)" (Addison-Wesley,
 * 2000), or Item 50 in Joshua Bloch's "Effective Java Programming
 * Language Guide" (Addison-Wesley, 2001).
 *
 * <p>If the current thread is {@linkplain java.lang.Thread#interrupt()
 * interrupted} by any thread before or while it is waiting, then an
 * {@code InterruptedException} is thrown.  This exception is not
 * thrown until the lock status of this object has been restored as
 * described above.
 *
 * <p>
 * Note that the {@code wait} method, as it places the current thread
 * into the wait set for this object, unlocks only this object; any
 * other objects on which the current thread may be synchronized remain
 * locked while the thread waits.
 */
public final native void wait(long timeout) throws InterruptedException;

/**
 * Causes the current thread to wait until another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object, or
 * some other thread interrupts the current thread, or a certain
 * amount of real time has elapsed.
 * <p>
 * This method is similar to the {@code wait} method of one
 * argument, but it allows finer control over the amount of time to
 * wait for a notification before giving up. The amount of real time,
 * measured in nanoseconds, is given by:
 * <blockquote>
 * <pre>
 * 1000000*timeout+nanos</pre></blockquote>
 * <p>
 * In all other respects, this method does the same thing as the
 * method {@link #wait(long)} of one argument. In particular,
 * {@code wait(0, 0)} means the same thing as {@code wait(0)}.
 * <p>
 * The current thread must own this object's monitor. The thread
 * releases ownership of this monitor and waits until either of the
 * following two conditions has occurred:
 * <ul>
 * <li>Another thread notifies threads waiting on this object's monitor
 *     to wake up either through a call to the {@code notify} method
 *     or the {@code notifyAll} method.
 * <li>The timeout period, specified by {@code timeout}
 *     milliseconds plus {@code nanos} nanoseconds arguments, has
 *     elapsed.
 * </ul>
 * <p>
 * The thread then waits until it can re-obtain ownership of the
 * monitor and resumes execution.
 * <p>
 * As in the one argument version, interrupts and spurious wakeups are
 * possible, and this method should always be used in a loop:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait(timeout, nanos);
 *         ... // Perform action appropriate to condition
 *     }
 */
public final void wait(long timeout, int nanos) throws InterruptedException {
    if (timeout < 0) {
        throw new IllegalArgumentException("timeout value is negative");
    }

    if (nanos < 0 || nanos > 999999) {
        throw new IllegalArgumentException(
                            "nanosecond timeout value out of range");
    }

    if (nanos > 0) {
        timeout++;
    }

    wait(timeout);
}

/**
 * Causes the current thread to wait until another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object.
 * In other words, this method behaves exactly as if it simply
 * performs the call {@code wait(0)}.
 * <p>
 * The current thread must own this object's monitor. The thread
 * releases ownership of this monitor and waits until another thread
 * notifies threads waiting on this object's monitor to wake up
 * either through a call to the {@code notify} method or the
 * {@code notifyAll} method. The thread then waits until it can
 * re-obtain ownership of the monitor and resumes execution.
 * <p>
 * As in the one argument version, interrupts and spurious wakeups are
 * possible, and this method should always be used in a loop:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait();
 *         ... // Perform action appropriate to condition
 *     }
 * </pre>
 * This method should only be called by a thread that is the owner
 * of this object's monitor. See the {@code notify} method for a
 * description of the ways in which a thread can become the owner of
 * a monitor.
 *
 * @throws  InterruptedException if any thread interrupted the
 *             current thread before or while the current thread
 *             was waiting for a notification.  The <i>interrupted
 *             status</i> of the current thread is cleared when
 *             this exception is thrown.
 */
public final void wait() throws InterruptedException {
    wait(0);
}
```


##### ObjectSynchronizer::wait

```cpp
// NOTE: must use heavy weight monitor to handle wait()
int ObjectSynchronizer::wait(Handle obj, jlong millis, TRAPS) {
  if (UseBiasedLocking) {
    BiasedLocking::revoke_and_rebias(obj, false, THREAD);
    assert(!obj->mark()->has_bias_pattern(), "biases should be revoked by now");
  }
  ObjectMonitor* monitor = ObjectSynchronizer::inflate(THREAD,
                                                       obj(),
                                                       inflate_cause_wait);
	//invoke ObjectMonitor::wait
  monitor->wait(millis, true, THREAD);

  return dtrace_waited_probe(monitor, obj, THREAD);
}
```



##### ObjectMonitor::wait

in objectMonitor.cpp

enter the wait queue

exit the monitor

```cpp
// Note: a subset of changes to ObjectMonitor::wait()
// will need to be replicated in complete_exit
void ObjectMonitor::wait(jlong millis, bool interruptible, TRAPS) {
  Thread * const Self = THREAD;
  assert(Self->is_Java_thread(), "Must be Java thread!");
  JavaThread *jt = (JavaThread *)THREAD;

  assert(InitDone, "Unexpectedly not initialized");

  // Throw IMSX or IEX.
  CHECK_OWNER();

  EventJavaMonitorWait event;

  // check for a pending interrupt
  if (interruptible && Thread::is_interrupted(Self, true) && !HAS_PENDING_EXCEPTION) {
    // post monitor waited event.  Note that this is past-tense, we are done waiting.
    if (JvmtiExport::should_post_monitor_waited()) {
      // Note: 'false' parameter is passed here because the
      // wait was not timed out due to thread interrupt.
      JvmtiExport::post_monitor_waited(jt, this, false);

      // In this short circuit of the monitor wait protocol, the
      // current thread never drops ownership of the monitor and
      // never gets added to the wait queue so the current thread
      // cannot be made the successor. This means that the
      // JVMTI_EVENT_MONITOR_WAITED event handler cannot accidentally
      // consume an unpark() meant for the ParkEvent associated with
      // this ObjectMonitor.
    }
    if (event.should_commit()) {
      post_monitor_wait_event(&event, this, 0, millis, false);
    }
    THROW(vmSymbols::java_lang_InterruptedException());
    return;
  }

  assert(Self->_Stalled == 0, "invariant");
  Self->_Stalled = intptr_t(this);
  jt->set_current_waiting_monitor(this);

  // create a node to be put into the queue
  // Critically, after we reset() the event but prior to park(), we must check
  // for a pending interrupt.
  ObjectWaiter node(Self);
  node.TState = ObjectWaiter::TS_WAIT;
  Self->_ParkEvent->reset();
  OrderAccess::fence();          // ST into Event; membar ; LD interrupted-flag

  // Enter the waiting queue, which is a circular doubly linked list in this case
  // but it could be a priority queue or any data structure.
  // _WaitSetLock protects the wait queue.  Normally the wait queue is accessed only
  // by the the owner of the monitor *except* in the case where park()
  // returns because of a timeout of interrupt.  Contention is exceptionally rare
  // so we use a simple spin-lock instead of a heavier-weight blocking lock.

  Thread::SpinAcquire(&_WaitSetLock, "WaitSet - add");
  AddWaiter(&node);
  Thread::SpinRelease(&_WaitSetLock);

  _Responsible = NULL;

  intptr_t save = _recursions; // record the old recursion count
  _waiters++;                  // increment the number of waiters
  _recursions = 0;             // set the recursion level to be 1
  exit(true, Self);                    // exit the monitor
  guarantee(_owner != Self, "invariant");

  // The thread is on the WaitSet list - now park() it.
  // On MP systems it's conceivable that a brief spin before we park
  // could be profitable.
  //
  // TODO-FIXME: change the following logic to a loop of the form
  //   while (!timeout && !interrupted && _notified == 0) park()

  int ret = OS_OK;
  int WasNotified = 0;
  { // State transition wrappers
    OSThread* osthread = Self->osthread();
    OSThreadWaitState osts(osthread, true);
    {
      ThreadBlockInVM tbivm(jt);
      // Thread is in thread_blocked state and oop access is unsafe.
      jt->set_suspend_equivalent();

      if (interruptible && (Thread::is_interrupted(THREAD, false) || HAS_PENDING_EXCEPTION)) {
        // Intentionally empty
      } else if (node._notified == 0) {
        if (millis <= 0) {
          Self->_ParkEvent->park();
        } else {
          ret = Self->_ParkEvent->park(millis);
        }
      }

      // were we externally suspended while we were waiting?
      if (ExitSuspendEquivalent (jt)) {
        // TODO-FIXME: add -- if succ == Self then succ = null.
        jt->java_suspend_self();
      }

    } // Exit thread safepoint: transition _thread_blocked -> _thread_in_vm

    // Node may be on the WaitSet, the EntryList (or cxq), or in transition
    // from the WaitSet to the EntryList.
    // See if we need to remove Node from the WaitSet.
    // We use double-checked locking to avoid grabbing _WaitSetLock
    // if the thread is not on the wait queue.
    //
    // Note that we don't need a fence before the fetch of TState.
    // In the worst case we'll fetch a old-stale value of TS_WAIT previously
    // written by the is thread. (perhaps the fetch might even be satisfied
    // by a look-aside into the processor's own store buffer, although given
    // the length of the code path between the prior ST and this load that's
    // highly unlikely).  If the following LD fetches a stale TS_WAIT value
    // then we'll acquire the lock and then re-fetch a fresh TState value.
    // That is, we fail toward safety.

    if (node.TState == ObjectWaiter::TS_WAIT) {
      Thread::SpinAcquire(&_WaitSetLock, "WaitSet - unlink");
      if (node.TState == ObjectWaiter::TS_WAIT) {
        DequeueSpecificWaiter(&node);       // unlink from WaitSet
        assert(node._notified == 0, "invariant");
        node.TState = ObjectWaiter::TS_RUN;
      }
      Thread::SpinRelease(&_WaitSetLock);
    }

    // The thread is now either on off-list (TS_RUN),
    // on the EntryList (TS_ENTER), or on the cxq (TS_CXQ).
    // The Node's TState variable is stable from the perspective of this thread.
    // No other threads will asynchronously modify TState.
    guarantee(node.TState != ObjectWaiter::TS_WAIT, "invariant");
    OrderAccess::loadload();
    if (_succ == Self) _succ = NULL;
    WasNotified = node._notified;

    // Reentry phase -- reacquire the monitor.
    // re-enter contended monitor after object.wait().
    // retain OBJECT_WAIT state until re-enter successfully completes
    // Thread state is thread_in_vm and oop access is again safe,
    // although the raw address of the object may have changed.
    // (Don't cache naked oops over safepoints, of course).

    // post monitor waited event. Note that this is past-tense, we are done waiting.
    if (JvmtiExport::should_post_monitor_waited()) {
      JvmtiExport::post_monitor_waited(jt, this, ret == OS_TIMEOUT);

      if (node._notified != 0 && _succ == Self) {
        // In this part of the monitor wait-notify-reenter protocol it
        // is possible (and normal) for another thread to do a fastpath
        // monitor enter-exit while this thread is still trying to get
        // to the reenter portion of the protocol.
        //
        // The ObjectMonitor was notified and the current thread is
        // the successor which also means that an unpark() has already
        // been done. The JVMTI_EVENT_MONITOR_WAITED event handler can
        // consume the unpark() that was done when the successor was
        // set because the same ParkEvent is shared between Java
        // monitors and JVM/TI RawMonitors (for now).
        //
        // We redo the unpark() to ensure forward progress, i.e., we
        // don't want all pending threads hanging (parked) with none
        // entering the unlocked monitor.
        node._event->unpark();
      }
    }

    if (event.should_commit()) {
      post_monitor_wait_event(&event, this, node._notifier_tid, millis, ret == OS_TIMEOUT);
    }

    OrderAccess::fence();

    assert(Self->_Stalled != 0, "invariant");
    Self->_Stalled = 0;

    assert(_owner != Self, "invariant");
    ObjectWaiter::TStates v = node.TState;
    if (v == ObjectWaiter::TS_RUN) {
      enter(Self);
    } else {
      guarantee(v == ObjectWaiter::TS_ENTER || v == ObjectWaiter::TS_CXQ, "invariant");
      ReenterI(Self, &node);
      node.wait_reenter_end(this);
    }

    // Self has reacquired the lock.
    // Lifecycle - the node representing Self must not appear on any queues.
    // Node is about to go out-of-scope, but even if it were immortal we wouldn't
    // want residual elements associated with this thread left on any lists.
    guarantee(node.TState == ObjectWaiter::TS_RUN, "invariant");
    assert(_owner == Self, "invariant");
    assert(_succ != Self, "invariant");
  } // OSThreadWaitState()

  jt->set_current_waiting_monitor(NULL);

  guarantee(_recursions == 0, "invariant");
  _recursions = save;     // restore the old recursion count
  _waiters--;             // decrement the number of waiters

  // Verify a few postconditions
  assert(_owner == Self, "invariant");
  assert(_succ != Self, "invariant");
  assert(((oop)(object()))->mark() == markOopDesc::encode(this), "invariant");

  // check if the notification happened
  if (!WasNotified) {
    // no, it could be timeout or Thread.interrupt() or both
    // check for interrupt event, otherwise it is timeout
    if (interruptible && Thread::is_interrupted(Self, true) && !HAS_PENDING_EXCEPTION) {
      THROW(vmSymbols::java_lang_InterruptedException());
    }
  }

  // NOTE: Spurious wake up will be consider as timeout.
  // Monitor notify has precedence over thread interrupt.
}
```



### notify

*如果是通过notify来唤起的线程，那先进入wait的线程会先被唤起来 * 如果是通过nootifyAll唤起的线程，默认情况是最后进入的会先被唤起来，即LIFO的策略*
```java
/**
 * Wakes up a single thread that is waiting on this object's
 * monitor. If any threads are waiting on this object, one of them
 * is chosen to be awakened. The choice is arbitrary and occurs at
 * the discretion of the implementation. A thread waits on an object's
 * monitor by calling one of the {@code wait} methods.
 * <p>
 * The awakened thread will not be able to proceed until the current
 * thread relinquishes the lock on this object. The awakened thread will
 * compete in the usual manner with any other threads that might be
 * actively competing to synchronize on this object; for example, the
 * awakened thread enjoys no reliable privilege or disadvantage in being
 * the next thread to lock this object.
 * <p>
 * This method should only be called by a thread that is the owner
 * of this object's monitor. A thread becomes the owner of the
 * object's monitor in one of three ways:
 * <ul>
 * <li>By executing a synchronized instance method of that object.
 * <li>By executing the body of a {@code synchronized} statement
 *     that synchronizes on the object.
 * <li>For objects of type {@code Class,} by executing a
 *     synchronized static method of that class.
 * </ul>
 * <p>
 * Only one thread at a time can own an object's monitor.
 */
public final native void notify();

/**
 * Wakes up all threads that are waiting on this object's monitor. A
 * thread waits on an object's monitor by calling one of the
 * {@code wait} methods.
 * <p>
 * The awakened threads will not be able to proceed until the current
 * thread relinquishes the lock on this object. The awakened threads
 * will compete in the usual manner with any other threads that might
 * be actively competing to synchronize on this object; for example,
 * the awakened threads enjoy no reliable privilege or disadvantage in
 * being the next thread to lock this object.
 */
public final native void notifyAll();

```

**TODO**: *Consider: If the lock is cool (cxq == null && succ == null) and we're on an MP system then instead of transferring a thread from the WaitSet to the EntryList we might just dequeue a thread from the WaitSet and directly unpark() it.*

*Consider: a not-uncommon synchronization bug is to use notify() when notifyAll() is more appropriate, potentially resulting in stranded threads; this is one example of a lost wakeup. A useful diagnostic option is to force all notify() operations to behave as notifyAll().*

*Note: We can also detect many such problems with a "minimum wait". When the "minimum wait" is set to a small non-zero timeout value and the program does not hang whereas it did absent "minimum wait", that suggests a lost wakeup bug.*



dequeue from the WaitSet to the EntryList


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

    // _WaitSetLock protects the wait queue, not the EntryList.  We could
    // move the add-to-EntryList operation, above, outside the critical section
    // protected by _WaitSetLock.  In practice that's not useful.  With the
    // exception of  wait() timeouts and interrupts the monitor owner
    // is the only thread that grabs _WaitSetLock.  There's almost no contention
    // on _WaitSetLock so it's not profitable to reduce the length of the
    // critical section.

    iterator->wait_reenter_begin(this);
  }
  Thread::SpinRelease(&_WaitSetLock);
}
```



*_WaitSetLock protects the wait queue, not the EntryList.  We could move the add-to-EntryList operation, above, outside the critical section protected by _WaitSetLock.  In practice that's not useful.  With the exception of  wait() timeouts and interrupts the monitor owner is the only thread that grabs _WaitSetLock.  **There's almost no contention on _WaitSetLock** so it's not profitable to reduce the length of the critical section.*


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


### Sleep

#### yield 跟 sleep 

1. yield 跟 sleep 都能暂停当前线程，都不会释放锁资源，sleep 可以指定具体休眠的时间，而 yield 则依赖 CPU 的时间片划分
2. sleep方法给其他线程运行机会时不考虑线程的优先级，因此会给低优先级的线程以运行的机会。yield方法只会给相同优先级或更高优先级的线程以运行的机会
3. 调用 sleep 方法使线程进入等待状态，等待休眠时间达到，而调用我们的 yield方法，线程会进入就绪状态，也就是sleep需要等待设置的时间后才会进行就绪状态，而yield会立即进入就绪状态
4. sleep方法声明会抛出 InterruptedException，而 yield 方法没有声明任何异常
5. yield 不能被中断，而 sleep 则可以接受中断。
6. sleep方法比yield方法具有更好的移植性(跟操作系统CPU调度相关)

#### wait 跟 sleep 

1. wait来自Object，sleep 来自 Thread
2. wait 释放锁，sleep 不释放
3. wait 必须在同步代码块中，sleep 可以任意使用
4. wait 不需要捕获异常，sleep 需捕获异常







### TimeUnit

*A TimeUnit represents time durations at a given unit of granularity and provides utility methods to convert across units, and to perform timing and delay operations in these units. A TimeUnit does not maintain time information, but only helps organize and use time representations that may be maintained separately across various contexts.*
*A TimeUnit is mainly used to inform time-based methods how a given timing parameter should be interpreted.*
*Note however, that there is no guarantee that a particular timeout implementation will be able to notice the passage of time at the same granularity as the given TimeUnit.*



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




### Interrupt

*The `interrupt` method interrupts **this thread**.*
Unless the current thread is interrupting itself, which is always permitted, the checkAccess method of this thread is invoked, which may cause a SecurityException to be thrown.

1. If this thread is blocked in an invocation of the wait(), wait(long), or wait(long, int) methods of the Object class, or of the join(), join(long), join(long, int), sleep(long), or sleep(long, int), methods of this class, then its interrupt status will be cleared and it will receive an InterruptedException.

2. If this thread is blocked in an I/O operation upon an InterruptibleChannel then the channel will be closed, the thread's interrupt status will be set, and the thread will receive a java.nio.channels.ClosedByInterruptException.
   If this thread is blocked in a java.nio.channels.Selector then the thread's interrupt status will be set and it will return immediately from the selection operation, possibly with a non-zero value, just as if the selector's wakeup method were invoked.

3. If none of the previous conditions hold then this thread's interrupt status will be set.

4. Interrupting a thread that is not alive need not have any effect.

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

## Lock

### Dead Lock



产生死锁必须满足四个条件：

1. 互斥条件：该资源任意⼀个时刻只由⼀个线程占⽤。
2. 请求与保持条件：⼀个进程因请求资源⽽阻塞时，对已获得的资源保持不放。
3. 不剥夺条件:线程已获得的资源在末使⽤完之前不能被其他线程强⾏剥夺，只有⾃⼰使⽤完毕后才释放资源。
4. 循环等待条件:若⼲进程之间形成⼀种头尾相接的循环等待资源关系。






### Live Lock

## JMM

