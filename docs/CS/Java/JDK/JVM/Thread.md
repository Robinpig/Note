## Introduction

All Thread subclasses must be either JavaThread or NonJavaThread.

Class hierarchy
```c
// - Thread
//   - JavaThread
//     - various subclasses eg CompilerThread, ServiceThread
//   - NonJavaThread
//     - NamedThread
//       - VMThread
//       - ConcurrentGCThread
//       - WorkerThread
//     - WatcherThread
//     - JfrThreadSampler
//     - LogAsyncWriter
```

```c
class ThreadShadow: public CHeapObj<mtThread> {
  friend class VMStructs;
  friend class JVMCIVMStructs;

 protected:
  oop  _pending_exception;                       // Thread has gc actions.
  const char* _exception_file;                   // file information for exception (debugging only)
  int         _exception_line;                   // line information for exception (debugging only)
  friend void check_ThreadShadow();              // checks _pending_exception offset

  // The following virtual exists only to force creation of a vtable.
  // We need ThreadShadow to have a vtable, even in product builds,
  // so that its layout will start at an offset of zero relative to Thread.
  // Some C++ compilers are so "clever" that they put the ThreadShadow
  // base class at offset 4 in Thread (after Thread's vtable), if they
  // notice that Thread has a vtable but ThreadShadow does not.
  virtual void unused_initial_virtual() { }

 public:
  oop  pending_exception() const                 { return _pending_exception; }
  bool has_pending_exception() const             { return _pending_exception != nullptr; }
  const char* exception_file() const             { return _exception_file; }
  int  exception_line() const                    { return _exception_line; }

  // Code generation support
  static ByteSize pending_exception_offset()     { return byte_offset_of(ThreadShadow, _pending_exception); }

  // use THROW whenever possible!
  void set_pending_exception(oop exception, const char* file, int line);

  // use CLEAR_PENDING_EXCEPTION whenever possible!
  void clear_pending_exception();

  // use CLEAR_PENDING_NONASYNC_EXCEPTION to clear probable nonasync exception.
  void clear_pending_nonasync_exception();

  ThreadShadow() : _pending_exception(nullptr),
                   _exception_file(nullptr), _exception_line(0) {}
};
```


线程对象持有
```c
class Thread: public ThreadShadow {
public:
  ParkEvent * volatile _ParkEvent;            // for Object monitors, JVMTI raw monitors,
                                              // and ObjectSynchronizer::read_stable_mark
  
  // Termination indicator used by the signal handler.
  // _ParkEvent is just a convenient field we can null out after setting the JavaThread termination state
  // (which can't itself be read from the signal handler if a signal hits during the Thread destructor).
  bool has_terminated()                       { return Atomic::load(&_ParkEvent) == nullptr; };
};
```


Thread execution sequence and actions:
```
All threads:
 - thread_native_entry  // per-OS native entry point
   - stack initialization
   - other OS-level initialization (signal masks etc)
   - handshake with creating thread (if not started suspended)
   - this->call_run()  // common shared entry point
     - shared common initialization
     - this->pre_run()  // virtual per-thread-type initialization
     - this->run()      // virtual per-thread-type "main" logic
     - shared common tear-down
     - this->post_run()  // virtual per-thread-type tear-down
     - // 'this' no longer referenceable
   - OS-level tear-down (minimal)
   - final logging

For JavaThread:
  - this->run()  // virtual but not normally overridden
    - this->thread_main_inner()  // extra call level to ensure correct stack calculations
      - this->entry_point()  // set differently for each kind of JavaThread
```


| **线程**                | **说明**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Attach Listener         | 负责接收到外部的命令，而对该命令进行执行的并且吧结果返回给发送者。通常我们会用一些命令去要求jvm给我们一些反馈信息<br /> 如：java -version、jmap、jstack等等。如果该线程在jvm启动的时候没有初始化，那么，则会在用户第一次执行jvm命令时，得到启动。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Signal Dispatcher       | Attach Listener线程接收外部jvm命令，会交给signal dispather线程去进行分发到各个不同的模块处理命令，并且返回处理结果。signal dispather线程也是在第一次接收外部jvm命令时，进行初始化工作。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| CompilerThread0         | 用来调用JITing，实时编译装卸class。通常，jvm会启动多个线程来处理这部分工作，线程名称后面的数字也会累加，例如：CompilerThread1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| DestroyJavaVM           | 执行main()的线程在main执行完后调用JNI中的jni_DestroyJavaVM()方法唤起DestroyJavaVM线程。  JVM在Jboss服务器启动之后，就会唤起DestroyJavaVM线程，处于等待状态，等待其它线程（java线程和native线程）退出时通知它卸载JVM。线程退出时，都会判断自己当前是否是整个JVM中最后一个非deamon线程，如果是，则通知DestroyJavaVM线程卸载JVM。ps：扩展一下：1.如果线程退出时判断自己不为最后一个非deamon线程，那么调用thread->exit(false)，并在其中抛出thread_end事件，jvm不退出。2.如果线程退出时判断自己为最后一个非deamon线程，那么调用before_exit()方法，抛出两个事件： 事件1：thread_end线程结束事件、事件2：VM的death事件。然后调用thread->exit(true)方法，接下来把线程从active list卸下，删除线程等等一系列工作执行完成后，则通知正在等待的DestroyJavaVM线程执行卸载JVM操作。 |
| Finalizer               | 这个线程也是在main线程之后创建的，其优先级为10，主要用于在垃圾收集前，调用对象的finalize()方法；关于Finalizer线程的几点：1)只有当开始一轮垃圾收集时，才会开始调用finalize()方法；因此并不是所有对象的finalize()方法都会被执行；2)该线程也是daemon线程，因此如果虚拟机中没有其他非daemon线程，不管该线程有没有执行完finalize()方法，JVM也会退出；3) JVM在垃圾收集时会将失去引用的对象包装成Finalizer对象（Reference的实现），并放入ReferenceQueue，由Finalizer线程来处理；最后将该Finalizer对象的引用置为null，由垃圾收集器来回收；4) JVM为什么要单独用一个线程来执行finalize()方法呢？如果JVM的垃圾收集线程自己来做，很有可能由于在finalize()方法中误操作导致GC线程停止或不可控，这对GC线程来说是一种灾难；                                                          |
| Gang worker#0           | JVM用于做新生代垃圾回收（monir gc）的一个线程。#号后面是线程编号，例如：Gang worker#1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| GC Daemon               | GC Daemon线程是JVM为RMI提供远程分布式GC使用的，GC Daemon线程里面会主动调用System.gc()方法，对服务器进行Full GC。<br /> 其初衷是当RMI服务器返回一个对象到其客户机（远程方法的调用方）时，其跟踪远程对象在客户机中的使用。当再没有更多的对客户机上远程对象的引用时，或者如果引用的“租借”过期并且没有更新，服务器将垃圾回收远程对象。<br />不过，我们现在jvm启动参数都加上了-XX:+DisableExplicitGC配置，所以，这个线程只有打酱油的份了。                                                                                                                                                                                                                                                                                                                              |
| Low MemoryDetector      | 这个线程是负责对可使用内存进行检测，如果发现可用内存低，分配新的内存空间。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| process reaper          | 该线程负责去执行一个OS命令行的操作。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Reference Handler       | JVM在创建main线程后就创建Reference Handler线程，其优先级最高，为10，它主要用于处理引用对象本身（软引用、弱引用、虚引用）的垃圾回收问题。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| taskObjectTimerFactory  | 顾名思义，该线程就是用来执行任务的。当我们把一个任务交给Timer对象，并且告诉它执行时间，周期时间后，Timer就会将该任务放入任务列队，并且通知taskObjectTimerFactory线程去处理任务，taskObjectTimerFactory线程会将状态为取消的任务从任务列队中移除，如果任务是非重复执行类型的，则在执行完该任务后，将它从任务列队中移除，如果该任务是需要重复执行的，则计算出它下一次执行的时间点。                                                                                                                                                                                                                                                                                                                                                                                     |
| VM Periodic Task Thread | 该线程是JVM周期性任务调度的线程，它由WatcherThread创建，是一个单例对象。该线程在JVM内使用得比较频繁，比如：定期的内存监控、JVM运行状况监控，还有我们经常需要去执行一些jstat这类命令查看gc的情况，如下：jstat -gcutil 23483 250 7 这个命令告诉jvm在控制台打印PID为：23483的gc情况，间隔250毫秒打印一次，一共打印7次。                                                                                                                                                                                                                                                                                                                                                                                                                                                 |





VM Thread                                         | 这个线程就比较牛b了，是jvm里面的线程母体，根据hotspot源码（vmThread.hpp）里面的注释，它是一个单例的对象（最原始的线程）会产生或触发所有其他的线程，这个单个的VM线程是会被其他线程所使用来做一些VM操作（如，清扫垃圾等）。在 VMThread的结构体里有一个VMOperationQueue列队，所有的VM线程操作(vm_operation)都会被保存到这个列队当中，VMThread本身就是一个线程，它的线程负责执行一个自轮询的loop函数(具体可以参考：VMThread.cpp里面的void VMThread::loop())，该loop函数从VMOperationQueue列队中按照优先级取出当前需要执行的操作对象(VM_Operation)，并且调用VM_Operation->evaluate函数去执行该操作类型本身的业务逻辑。ps：VM操作类型被定义在vm_operations.hpp文件内，列举几个：ThreadStop、ThreadDump、PrintThreads、GenCollectFull、GenCollectFullConcurrent、CMS_Initial_Mark、CMS_Final_Remark…..有兴趣的同学，可以自己去查看源文件。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

## JavaThread

See [java.lang.Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)

```cpp
// thread.hpp
class JavaThread: public Thread {
 private:
  bool           _on_thread_list;                // Is set when this JavaThread is added to the Threads list
  OopHandle      _threadObj;                     // The Java level thread object

}

// share/classfile/javaclasses.cpp
JavaThread* java_lang_Thread::thread(oop java_thread) {
  return (JavaThread*)java_thread->address_field(_eetop_offset);
}
```

## vmOperations

Operations in the VM that can be requested by Java threads, but which must be executed, in serial fashion by a specific thread known as the VM thread.
These operations are often synchronous, in that the requester will block until the VM thread has completed the operation.
Many of these operations also require that the VM be brought to a safepoint before the operation can be performed - a garbage collection request is a simple example.

A list of common operations is below.

```cpp
// vmOperations.hpp
class VM_Operation: public CHeapObj<mtInternal> {
 public:
  enum Mode {
    _safepoint,       // blocking,        safepoint, vm_op C-heap allocated
    _no_safepoint,    // blocking,     no safepoint, vm_op C-Heap allocated
    _concurrent,      // non-blocking, no safepoint, vm_op C-Heap allocated
    _async_safepoint  // non-blocking,    safepoint, vm_op C-Heap allocated
  };

  enum VMOp_Type {
    VM_OPS_DO(VM_OP_ENUM)
    VMOp_Terminating
  };

 private:
  Thread*         _calling_thread;
  ThreadPriority  _priority;
  long            _timestamp;
  VM_Operation*   _next;
  VM_Operation*   _prev;

  // The VM operation name array
  static const char* _names[];
  
}
```



### attach

create_vm 时候会初始化

默认情况下JVM启动的时候并不会立即启动Attach Listener线程。在客户端发送SIGQUIT信号时会启动Attach Listener线程



```cpp
jint Threads::create_vm(JavaVMInitArgs* args, bool* canTryAgain) {
    // ...
    // Signal Dispatcher needs to be started before VMInit event is posted
    os::initialize_jdk_signal_support(CHECK_JNI_ERR);

    // Start Attach Listener if +StartAttachListener or it can‘t be started lazily
    if (!DisableAttachMechanism) {
        AttachListener::vm_start();
        if (StartAttachListener || AttachListener::init_at_startup()) {
            AttachListener::init();
        }
    }
    // ...
}

```


void os::initialize_jdk_signal_support(TRAPS) {
    if (!ReduceSignalUsage) {
        // Setup JavaThread for processing signals
        const char* name = ”Signal Dispatcher“;
        Handle thread_oop = JavaThread::create_system_thread_object(name, CHECK);

        JavaThread* thread = new JavaThread(&signal_thread_entry);
        JavaThread::vm_exit_on_osthread_failure(thread);

        JavaThread::start_internal_daemon(THREAD, thread, thread_oop, NearMaxPriority);
    }
}


Signal Dispatcher线程启动后会通过os::signal_wait()等待操作系统信号量。当收到操作系统信号量，且信号量为SIGBREAK时会触发初始化Attach Listener


static void signal_thread_entry(JavaThread* thread, TRAPS) {
  os::set_priority(thread, NearMaxPriority);
  while (true) {
    int sig;
    {
      // FIXME : Currently we have not decided what should be the status
      //         for this java thread blocked here. Once we decide about
      //         that we should fix this.
      sig = os::signal_wait();
    }
    if (sig == os::sigexitnum_pd()) {
       // Terminate the signal thread
       return;
    }

    switch (sig) {
      case SIGBREAK: {
#if INCLUDE_SERVICES
        // Check if the signal is a trigger to start the Attach Listener - in that
        // case don‘t print stack traces.
        if (!DisableAttachMechanism) {
          // Attempt to transit state to AL_INITIALIZING.
          AttachListenerState cur_state = AttachListener::transit_state(AL_INITIALIZING, AL_NOT_INITIALIZED);
          if (cur_state == AL_INITIALIZING) {
            // Attach Listener has been started to initialize. Ignore this signal.
            continue;
          } else if (cur_state == AL_NOT_INITIALIZED) {
            // Start to initialize.
            if (AttachListener::is_init_trigger()) {
              // Attach Listener has been initialized.
              // Accept subsequent request.
              continue;
            } else {
              // Attach Listener could not be started.
              // So we need to transit the state to AL_NOT_INITIALIZED.
              AttachListener::set_state(AL_NOT_INITIALIZED);
            }
          } else if (AttachListener::check_socket_file()) {
            // Attach Listener has been started, but unix domain socket file
            // does not exist. So restart Attach Listener.
            continue;
          }
        }
#endif
        // Print stack traces
        // Any SIGBREAK operations added here should make sure to flush
        // the output stream (e.g. tty->flush()) after output.  See 4803766.
        // Each module also prints an extra carriage return after its output.
        VM_PrintThreads op(tty, PrintConcurrentLocks, false /* no extended info */, true /* print JNI handle info */);
        VMThread::execute(&op);
        VM_FindDeadlocks op1(tty);
        VMThread::execute(&op1);
        Universe::print_heap_at_SIGBREAK();
        if (PrintClassHistogram) {
          VM_GC_HeapInspection op1(tty, true /* force full GC before heap inspection */);
          VMThread::execute(&op1);
        }
        if (JvmtiExport::should_post_data_dump()) {
          JvmtiExport::post_data_dump();
        }
        break;
      }
      default: {
        // Dispatch the signal to java
        HandleMark hm(THREAD);
        Klass* klass = SystemDictionary::resolve_or_null(vmSymbols::jdk_internal_misc_Signal(), THREAD);
        if (klass != nullptr) {
          JavaValue result(T_VOID);
          JavaCallArguments args;
          args.push_int(sig);
          JavaCalls::call_static(
            &result,
            klass,
            vmSymbols::dispatch_name(),
            vmSymbols::int_void_signature(),
            &args,
            THREAD
          );
        }
        if (HAS_PENDING_EXCEPTION) {
          // tty is initialized early so we don’t expect it to be null, but
          // if it is we can‘t risk doing an initialization that might
          // trigger additional out-of-memory conditions
          if (tty != nullptr) {
            char klass_name[256];
            char tmp_sig_name[16];
            const char* sig_name = ”UNKNOWN“;
            InstanceKlass::cast(PENDING_EXCEPTION->klass())->
              name()->as_klass_external_name(klass_name, 256);
            if (os::exception_name(sig, tmp_sig_name, 16) != nullptr)
              sig_name = tmp_sig_name;
            warning(”Exception %s occurred dispatching signal %s to handler“
                    ”- the VM may need to be forcibly terminated“,
                    klass_name, sig_name );
          }
          CLEAR_PENDING_EXCEPTION;
        }
      }
    }
  }
}


这里 SIGBREAK 实际是 SIGQUIT信号

// SIGBREAK is sent by the keyboard to query the VM state
#ifndef SIGBREAK
#define SIGBREAK SIGQUIT
#endif



// Starts the Attach Listener thread
void AttachListener::init() {
    EXCEPTION_MARK;

    const char* name = ”Attach Listener“;
    Handle thread_oop = JavaThread::create_system_thread_object(name, THREAD);
    if (has_init_error(THREAD)) {
        set_state(AL_NOT_INITIALIZED);
        return;
    }

    JavaThread* thread = new JavaThread(&attach_listener_thread_entry);
    JavaThread::vm_exit_on_osthread_failure(thread);

    JavaThread::start_internal_daemon(THREAD, thread, thread_oop, NoPriority);
}



AttachListener::pd_init()初始化逻辑根据实际的操作系统决定。在linux上，最终的初始化工作是由LinuxAttachListener::init()完成



// Starts the target JavaThread as a daemon of the given priority, and
// bound to the given java.lang.Thread instance.
// The Threads_lock is held for the duration.
void JavaThread::start_internal_daemon(JavaThread* current, JavaThread* target,
                                       Handle thread_oop, ThreadPriority prio) {

  assert(target->osthread() != nullptr, ”target thread is not properly initialized“);

  MutexLocker mu(current, Threads_lock);

  // Initialize the fields of the thread_oop first.
  if (prio != NoPriority) {
    java_lang_Thread::set_priority(thread_oop(), prio);
    // Note: we don’t call os::set_priority here. Possibly we should,
    // else all threads should call it themselves when they first run.
  }

  java_lang_Thread::set_daemon(thread_oop());

  // Now bind the thread_oop to the target JavaThread.
  target->set_threadOopHandles(thread_oop());

  Threads::add(target); // target is now visible for safepoint/handshake
  // Publish the JavaThread* in java.lang.Thread after the JavaThread* is
  // on a ThreadsList. We don‘t want to wait for the release when the
  // Theads_lock is dropped when the ’mu‘ destructor is run since the
  // JavaThread* is already visible to JVM/TI via the ThreadsList.
  java_lang_Thread::release_set_thread(thread_oop(), target); // isAlive == true now
  Thread::start(target);
}









## NonJavaThread


```cpp
class NonJavaThread: public Thread {
  friend class VMStructs;

  NonJavaThread* volatile _next;

  class List;
  static List _the_list;

  void add_to_the_list();
  void remove_from_the_list();

 protected:
  virtual void pre_run();
  virtual void post_run();

 public:
  NonJavaThread();
  ~NonJavaThread();

  class Iterator;
};
```


```cpp
// A base class for non-JavaThread subclasses with multiple
// uniquely named instances. NamedThreads also provide a common
// location to store GC information needed by GC threads
// and the VMThread.
class NamedThread: public NonJavaThread {
  friend class VMStructs;
  enum {
    max_name_len = 64
  };
 private:
  char* _name;
  // log Thread being processed by oops_do
  Thread* _processed_thread;
  uint _gc_id; // The current GC id when a thread takes part in GC

 public:
  NamedThread();
  ~NamedThread();
  // May only be called once per thread.
  void set_name(const char* format, ...)  ATTRIBUTE_PRINTF(2, 3);
  virtual bool is_Named_thread() const { return true; }
  virtual const char* name() const { return _name == nullptr ? "Unknown Thread" : _name; }
  virtual const char* type_name() const { return "NamedThread"; }
  Thread *processed_thread() { return _processed_thread; }
  void set_processed_thread(Thread *thread) { _processed_thread = thread; }
  virtual void print_on(outputStream* st) const;

  void set_gc_id(uint gc_id) { _gc_id = gc_id; }
  uint gc_id() { return _gc_id; }
};
```




## VMThread

A single VMThread is used by other threads to offload heavy vm operations like scavenge, garbage_collect etc.

```cpp
class VMThread: public NamedThread {
 private:
  volatile bool _is_running;

  static ThreadPriority _current_priority;

  static bool _should_terminate;
  static bool _terminated;
  static Monitor * _terminate_lock;
  static PerfCounter* _perf_accumulated_vm_operation_time;

  static VMOperationTimeoutTask* _timeout_task;

  static bool handshake_alot();
  static void setup_periodic_safepoint_if_needed();

  void evaluate_operation(VM_Operation* op);
  void inner_execute(VM_Operation* op);
  void wait_for_operation();

  // Constructor
  VMThread();

  // No destruction allowed
  ~VMThread() {
    guarantee(false, "VMThread deletion must fix the race with VM termination");
  }

  // The ever running loop for the VMThread
  void loop();

 public:
  bool is_running() const { return Atomic::load(&_is_running); }

  // Tester
  bool is_VM_thread() const                      { return true; }

  // Called to stop the VM thread
  static void wait_for_vm_thread_exit();
  static bool should_terminate()                  { return _should_terminate; }
  static bool is_terminated()                     { return _terminated == true; }

  // Execution of vm operation
  static void execute(VM_Operation* op);

  // Returns the current vm operation if any.
  static VM_Operation* vm_operation()             {
    assert(Thread::current()->is_VM_thread(), "Must be");
    return _cur_vm_operation;
  }

  static VM_Operation::VMOp_Type vm_op_type()     {
    VM_Operation* op = vm_operation();
    assert(op != nullptr, "sanity");
    return op->type();
  }

  // Returns the single instance of VMThread.
  static VMThread* vm_thread()                    { return _vm_thread; }

  void verify();

  // Performance measurement
  static PerfCounter* perf_accumulated_vm_operation_time() {
    return _perf_accumulated_vm_operation_time;
  }

  // Entry for starting vm thread
  virtual void run();

  // Creations/Destructions
  static void create();
  static void destroy();

  static void wait_until_executed(VM_Operation* op);

  // Printing
  const char* type_name() const { return "VMThread"; }

 private:
  // VM_Operation support
  static VM_Operation*     _cur_vm_operation;   // Current VM operation
  static VM_Operation*     _next_vm_operation;  // Next VM operation

  bool set_next_operation(VM_Operation *op);    // Set the _next_vm_operation if possible.

  // Pointer to single-instance of VM thread
  static VMThread*     _vm_thread;
};
```


Created one VMThread when [create_vm](/docs/CS/Java/JDK/JVM/start.md?id=create_vm) and wait for VMOperations.

```cpp
jint Threads::create_vm(JavaVMInitArgs* args, bool* canTryAgain) {
    // Create the VMThread
    { 
        TraceTime timer("Start VMThread", TRACETIME_LOG(Info, startuptime));

        VMThread::create();
        VMThread* vmthread = VMThread::vm_thread();

        if (!os::create_thread(vmthread, os::vm_thread)) {
            vm_exit_during_initialization("Cannot create VM thread. "
                "Out of system resources.");
        }

        // Wait for the VM thread to become ready, and VMThread::run to initialize
        // Monitors can have spurious returns, must always check another state flag
        {
            MonitorLocker ml(Notify_lock);
            os::start_thread(vmthread);
            while (!vmthread->is_running()) {
                ml.wait();
            }
        }
    }
}
```


```cpp
jint Threads::create_vm(JavaVMInitArgs* args, bool* canTryAgain) {
    // Create the VMThread
    { 
        TraceTime timer("Start VMThread", TRACETIME_LOG(Info, startuptime));

        VMThread::create();
        VMThread* vmthread = VMThread::vm_thread();

        if (!os::create_thread(vmthread, os::vm_thread)) {
            vm_exit_during_initialization("Cannot create VM thread. "
                "Out of system resources.");
        }

        // Wait for the VM thread to become ready, and VMThread::run to initialize
        // Monitors can have spurious returns, must always check another state flag
        {
            MonitorLocker ml(Notify_lock);
            os::start_thread(vmthread);
            while (!vmthread->is_running()) {
                ml.wait();
            }
        }
    }
}
```






JavaThread会通过执行VMThread::execute()函数把相关操作放到队列中，然后由VMThread在run()函数中轮询队列并获取任务


### VMThread::run

```cpp

void VMThread::run() {
  // Notify_lock wait checks on is_running() to rewait in case of spurious wakeup, it should wait on the last value set prior to the notify
  Atomic::store(&_is_running, true);

  {
    MutexLocker ml(Notify_lock);
    Notify_lock->notify();
  }
```

Notify_lock is destroyed by [Threads::create_vm()](/docs/CS/Java/JDK/JVM/start.md?id=create_vm).

```cpp
  int prio = (VMThreadPriority == -1)
    ? os::java_to_os_priority[NearMaxPriority]
    : VMThreadPriority;
  // Note that I cannot call os::set_priority because it expects Java
  // priorities and I am *explicitly* using OS priorities so that it's
  // possible to set the VM thread priority higher than any Java thread.
  os::set_native_priority( this, prio );
```

Wait for VM_Operations until termination

```
  this->loop();
```

Note the intention to exit before safepointing.

This has the effect of waiting for any large tty outputs to finish.

```cpp
  if (xtty != NULL) {
    ttyLocker ttyl;
    xtty->begin_elem("destroy_vm");
    xtty->stamp();
    xtty->end_elem();
    assert(should_terminate(), "termination flag must be set");
  }

```

let VM thread exit at [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md?id=begin)

```cpp
  _cur_vm_operation = &halt_op;
  SafepointSynchronize::begin();

  if (VerifyBeforeExit) {
    HandleMark hm(VMThread::vm_thread());
    // Among other things, this ensures that Eden top is correct.
    Universe::heap()->prepare_for_verify();
    // Silent verification so as not to pollute normal output,
    // unless we really asked for it.
    Universe::verify();
  }

  CompileBroker::set_should_block();

  // wait for threads (compiler threads or daemon threads) in the
  // _thread_in_native state to block.
  VM_Exit::wait_for_threads_in_native_to_block();

  // The ObjectMonitor subsystem uses perf counters so do this before
  // we signal that the VM thread is gone. We don't want to run afoul
  // of perfMemory_exit() in exit_globals().
  ObjectSynchronizer::do_final_audit_and_print_stats();

  // signal other threads that VM process is gone
  {
    // Note: we must have the _no_safepoint_check_flag. Mutex::lock() allows
    // VM thread to enter any lock at Safepoint as long as its _owner is NULL.
    // If that happens after _terminate_lock->wait() has unset _owner
    // but before it actually drops the lock and waits, the notification below
    // may get lost and we will have a hang. To avoid this, we need to use
    // Mutex::lock_without_safepoint_check().
    MonitorLocker ml(_terminate_lock, Mutex::_no_safepoint_check_flag);
    _terminated = true;
    ml.notify();
  }

  // We are now racing with the VM termination being carried out in
  // another thread, so we don't "delete this". Numerous threads don't
  // get deleted when the VM terminates

}
```

#### loop

```cpp
void VMThread::loop() {
  assert(_cur_vm_operation == NULL, "no current one should be executing");

  SafepointSynchronize::init(_vm_thread);

  // Need to set a calling thread for ops not passed
  // via the normal way.
  cleanup_op.set_calling_thread(_vm_thread);
  safepointALot_op.set_calling_thread(_vm_thread);

  while (true) {
    if (should_terminate()) break;
    wait_for_operation();
    if (should_terminate()) break;
    assert(_next_vm_operation != NULL, "Must have one");
```

call inner_execute

```cpp
    inner_execute(_next_vm_operation);
  }
}
```

### inner_execute

```cpp

void VMThread::inner_execute(VM_Operation* op) {
  assert(Thread::current()->is_VM_thread(), "Must be the VM thread");

  VM_Operation* prev_vm_operation = NULL;
  if (_cur_vm_operation != NULL) {
    // Check that the VM operation allows nested VM operation.
    // This is normally not the case, e.g., the compiler
    // does not allow nested scavenges or compiles.
    if (!_cur_vm_operation->allow_nested_vm_operations()) {
      fatal("Unexpected nested VM operation %s requested by operation %s",
            op->name(), _cur_vm_operation->name());
    }
    op->set_calling_thread(_cur_vm_operation->calling_thread());
    prev_vm_operation = _cur_vm_operation;
  }

  _cur_vm_operation = op;

  HandleMark hm(VMThread::vm_thread());
  EventMarkVMOperation em("Executing %sVM operation: %s", prev_vm_operation != NULL ? "nested " : "", op->name());

```

if is_at_safepoint, **evaluate_operation** between [SafepointSynchronize::begin()](/docs/CS/Java/JDK/JVM/Safepoint.md?id=begin)
and [SafepointSynchronize::end()](/docs/CS/Java/JDK/JVM/Safepoint.md?id=end)

```cpp
  log_debug(vmthread)("Evaluating %s %s VM operation: %s",
                       prev_vm_operation != NULL ? "nested" : "",
                      _cur_vm_operation->evaluate_at_safepoint() ? "safepoint" : "non-safepoint",
                      _cur_vm_operation->name());

  bool end_safepoint = false;
  bool has_timeout_task = (_timeout_task != nullptr);
  if (_cur_vm_operation->evaluate_at_safepoint() &&
      !SafepointSynchronize::is_at_safepoint()) {
    SafepointSynchronize::begin();
    if (has_timeout_task) {
      _timeout_task->arm(_cur_vm_operation->name());
    }
    end_safepoint = true;
  }

  evaluate_operation(_cur_vm_operation);

  if (end_safepoint) {
    if (has_timeout_task) {
      _timeout_task->disarm();
    }
    SafepointSynchronize::end();
  }

  _cur_vm_operation = prev_vm_operation;
}
```

#### evaluate_operation

```cpp
void VMThread::evaluate_operation(VM_Operation* op) {
  ResourceMark rm;

  {
    PerfTraceTime vm_op_timer(perf_accumulated_vm_operation_time());
    HOTSPOT_VMOPS_BEGIN(
                     (char *) op->name(), strlen(op->name()),
                     op->evaluate_at_safepoint() ? 0 : 1);

    EventExecuteVMOperation event;
    op->evaluate();
    if (event.should_commit()) {
      post_vm_operation_event(&event, op);
    }

    HOTSPOT_VMOPS_END(
                     (char *) op->name(), strlen(op->name()),
                     op->evaluate_at_safepoint() ? 0 : 1);
  }

}```

## CompilerThread

### compilation_init_phase1
Initialize the Compilation object
```cpp
void CompileBroker::compilation_init_phase1(JavaThread* THREAD) {
  // No need to initialize compilation system if we do not use it.
  if (!UseCompiler) {
    return;
  }
  // Set the interface to the current compiler(s).
  _c1_count = CompilationPolicy::c1_count();
  _c2_count = CompilationPolicy::c2_count();

#if INCLUDE_JVMCI
  if (EnableJVMCI) {
```

This is creating a JVMCICompiler singleton.

```cpp
    JVMCICompiler* jvmci = new JVMCICompiler();

    if (UseJVMCICompiler) {
      _compilers[1] = jvmci;
      if (FLAG_IS_DEFAULT(JVMCIThreads)) {
        if (BootstrapJVMCI) {
          // JVMCI will bootstrap so give it more threads
          _c2_count = MIN2(32, os::active_processor_count());
        }
      } else {
        _c2_count = JVMCIThreads;
      }
      if (FLAG_IS_DEFAULT(JVMCIHostThreads)) {
      } else {
#ifdef COMPILER1
        _c1_count = JVMCIHostThreads;
#endif // COMPILER1
      }
    }
  }
#endif // INCLUDE_JVMCI

#ifdef COMPILER1
  if (_c1_count > 0) {
    _compilers[0] = new Compiler();
  }
#endif // COMPILER1

#ifdef COMPILER2
  if (true JVMCI_ONLY( && !UseJVMCICompiler)) {
    if (_c2_count > 0) {
      _compilers[1] = new C2Compiler();
      // Register c2 first as c2 CompilerPhaseType idToPhase mapping is explicit.
      // idToPhase mapping for c2 is in opto/phasetype.hpp
      JFR_ONLY(register_jfr_phasetype_serializer(compiler_c2);)
    }
  }
#endif // COMPILER2

#if INCLUDE_JVMCI
   // Register after c2 registration.
   // JVMCI CompilerPhaseType idToPhase mapping is dynamic.
   if (EnableJVMCI) {
     JFR_ONLY(register_jfr_phasetype_serializer(compiler_jvmci);)
   }
#endif // INCLUDE_JVMCI

  // Start the compiler thread(s) and the sweeper thread
  init_compiler_sweeper_threads();
  // totalTime performance counter is always created as it is required
  // by the implementation of java.lang.management.CompilationMXBean.
  {
    // Ensure OOM leads to vm_exit_during_initialization.
    EXCEPTION_MARK;
    _perf_total_compilation =
                 PerfDataManager::create_counter(JAVA_CI, "totalTime",
                                                 PerfData::U_Ticks, CHECK);
  }

  if (UsePerfData) {

    EXCEPTION_MARK;

    // create the jvmstat performance counters
    _perf_osr_compilation =
                 PerfDataManager::create_counter(SUN_CI, "osrTime",
                                                 PerfData::U_Ticks, CHECK);

    _perf_standard_compilation =
                 PerfDataManager::create_counter(SUN_CI, "standardTime",
                                                 PerfData::U_Ticks, CHECK);

    _perf_total_bailout_count =
                 PerfDataManager::create_counter(SUN_CI, "totalBailouts",
                                                 PerfData::U_Events, CHECK);

    _perf_total_invalidated_count =
                 PerfDataManager::create_counter(SUN_CI, "totalInvalidates",
                                                 PerfData::U_Events, CHECK);

    _perf_total_compile_count =
                 PerfDataManager::create_counter(SUN_CI, "totalCompiles",
                                                 PerfData::U_Events, CHECK);
    _perf_total_osr_compile_count =
                 PerfDataManager::create_counter(SUN_CI, "osrCompiles",
                                                 PerfData::U_Events, CHECK);

    _perf_total_standard_compile_count =
                 PerfDataManager::create_counter(SUN_CI, "standardCompiles",
                                                 PerfData::U_Events, CHECK);

    _perf_sum_osr_bytes_compiled =
                 PerfDataManager::create_counter(SUN_CI, "osrBytes",
                                                 PerfData::U_Bytes, CHECK);

    _perf_sum_standard_bytes_compiled =
                 PerfDataManager::create_counter(SUN_CI, "standardBytes",
                                                 PerfData::U_Bytes, CHECK);

    _perf_sum_nmethod_size =
                 PerfDataManager::create_counter(SUN_CI, "nmethodSize",
                                                 PerfData::U_Bytes, CHECK);

    _perf_sum_nmethod_code_size =
                 PerfDataManager::create_counter(SUN_CI, "nmethodCodeSize",
                                                 PerfData::U_Bytes, CHECK);

    _perf_last_method =
                 PerfDataManager::create_string_variable(SUN_CI, "lastMethod",
                                       CompilerCounters::cmname_buffer_length,
                                       "", CHECK);

    _perf_last_failed_method =
            PerfDataManager::create_string_variable(SUN_CI, "lastFailedMethod",
                                       CompilerCounters::cmname_buffer_length,
                                       "", CHECK);

    _perf_last_invalidated_method =
        PerfDataManager::create_string_variable(SUN_CI, "lastInvalidatedMethod",
                                     CompilerCounters::cmname_buffer_length,
                                     "", CHECK);

    _perf_last_compile_type =
             PerfDataManager::create_variable(SUN_CI, "lastType",
                                              PerfData::U_None,
                                              (jlong)CompileBroker::no_compile,
                                              CHECK);

    _perf_last_compile_size =
             PerfDataManager::create_variable(SUN_CI, "lastSize",
                                              PerfData::U_Bytes,
                                              (jlong)CompileBroker::no_compile,
                                              CHECK);


    _perf_last_failed_type =
             PerfDataManager::create_variable(SUN_CI, "lastFailedType",
                                              PerfData::U_None,
                                              (jlong)CompileBroker::no_compile,
                                              CHECK);

    _perf_last_invalidated_type =
         PerfDataManager::create_variable(SUN_CI, "lastInvalidatedType",
                                          PerfData::U_None,
                                          (jlong)CompileBroker::no_compile,
                                          CHECK);
  }
}
```

## ServiceThread

### ServiceThread::initialize

## MonitorDeflationThread

### MonitorDeflationThread::initialize

## CompilerThread

The main loop run by a CompilerThread.

`CompileBroker::compiler_thread_loop()` -> invoke_compiler_on_method -> compile_method([c1](/docs/CS/Java/JDK/JVM/JIT.md?id=c1) or [c2](/docs/CS/Java/JDK/JVM/JIT.md?id=c2))

CompileBroker::compilation_init_phase1()

`-XX:+UseDynamicNumberOfCompilerThreads`

`-XX:+TraceCompilerThreads`

`-XX:+MethodFlushing` create CodeCacheSweeperThread clear CodeCache

## WatchedThread

## Summary

一些影响线程创建的因素，包括
- JVM：Xmx，Xss，MaxPermSize，MaxDirectMemorySize，ReservedCodeCacheSize 等
- Kernel：max_user_processes，max_map_count，max_threads，pid_max 等









## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)

## References

1. [JVM 内部运行线程介绍](https://ifeve.com/jvm-thread/)
