## Introduction

JVM 的关闭分**有序（orderly）**与**突然（abrupt）**两类。有序关闭的触发条件是：最后一个 non-daemon 线程结束、有人调用 `System.exit`、或其他平台相关手段（例如收到 `SIGINT`、按下 `Ctrl-C`），这是标准且推荐的方式。但 JVM 也可以被突然终止：调用 `Runtime.halt`，或者由操作系统直接杀掉 JVM 进程（例如 `SIGKILL`）。

本篇只讲**退出侧**的 HotSpot 实现。启动侧的对称页见 [start.md](/docs/CS/Java/JDK/JVM/start.md)（`## MainClass` 之后就是退出）；JNI `DestroyJavaVM` 的**程序员可见语义**（返回值、幂等性、多线程注意事项）属于 [JNI.md](/docs/CS/Java/JDK/Basic/JNI.md)，此处不重复，只讲 VM 内部发生了什么。

## Version Baseline

> [!NOTE]
>
> 本篇最容易写错的四处版本变化，全部按 jdk-27-ga 源码复核：
>
> 1. **`JVM_OnExit` 已经不是代码，只是注释化石**。`runtime/threads.cpp:908-909` 的 shutdown sequence 注释里仍写着「VM level shutdown hooks 通过 `JVM_OnExit()` 注册，目前唯一用户是 `File.deleteOnExit()`」，但全 `share/` 树 grep `JVM_OnExit` **只有这一处注释命中，没有任何实现或注册表**。旧版正文照抄这句话就是过时的。JDK 27 里 VM 级唯一保留的 exit 钩子是 `Arguments::exit_hook()`（`runtime/arguments.cpp:2385-2386`，来自 JNI Invocation API 的 `exit` 选项字符串），消费点在 `runtime/vmOperations.cpp:572-579`。
> 2. **shutdown sequence 注释里已经没有 StatSampler 与 CMS**。现注释（`runtime/threads.cpp:901-926`）只列 `stop watcher thread` / `post thread end and vm death events to JVMTI` / `stop signal thread`，旧资料里的「stop StatSampler、CMS threads」在本树已无对应物。
> 3. **`Threads::destroy_vm()` 现在返回 `void`**（`runtime/threads.hpp:76`），不再是 `bool`；并且等待条件从「non-daemon 线程数 > 1」改成 **daemon-aware** 的 `> expected`（`runtime/threads.cpp:937-943`）。
> 4. **`before_exit()` 多了一个 `halt` 形参**（`runtime/java.hpp:35`，`extern void before_exit(JavaThread* thread, bool halt = false)`），它只影响 LSan 检查模式与 `Jfr::on_vm_shutdown(false, halt)`，不改变关闭流程本身。

详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Orderly and Abrupt Shutdown

| 类别 | 触发 | VM 侧入口 | Java shutdown hooks | 清理动作 |
| :--- | :--- | :--- | :--- | :--- |
| orderly | `main()` 返回后 launcher 调 `DestroyJavaVM` | `Threads::destroy_vm()` | **跑** | 全套，见 destroy_vm 一节 |
| orderly | 最后一个 non-daemon 线程结束 | 同上，靠 `destroy_vm` 里的等待循环放行 | **跑** | 全套 |
| orderly | `System.exit(n)` | `JVM_Halt` → `vm_exit(n)` → `VM_Exit` op | **先跑**（`System.exit` 在 Java 层先走 `Shutdown.exit`） | 全套，但跳过 `destroy_vm` 的线程等待 |
| abrupt | `Runtime.halt(n)` | `JVM_Halt` → `vm_exit(n)` | **不跑**（Java 层直接 halt，不进 `Shutdown.shutdown()`） | 只有 VM 级 `before_exit(halt=true)` + `VM_Exit` |
| abrupt | 崩溃 / `FatalError` | `VMError::report_and_die()` → `os::abort()` → `os::die()` | **不跑** | 只出 `hs_err` 与 core，不走 `before_exit` |
| abrupt | `SIGKILL` | 无 | **不跑** | **无任何 JVM 代码执行** |

关键区分：**`halt` 走的是和 `exit` 完全相同的 VM 侧路径**，差别全在 Java 层是否先执行 `java.lang.Shutdown.shutdown()`。VM 自己并不知道你是 `exit` 还是 `halt`，只有 `before_exit(thread, /*halt=*/true)` 这个参数留下了痕迹。

## Two VM Side Entry Points

两条路径的权威描述在 `runtime/threads.cpp:894-899` 的函数头注释里：`destroy_vm()` normally called from `jni_DestroyJavaVM()` when the program falls off the end of `main()`；另一条是 `vm_exit()`，用于 `System.exit()` 要返回值或 VM 内部严重错误。注释最后一句点出两条路径的公共部分：**they share `Shutdown.shutdown()` at Java level and `before_exit()` and `VM_Exit` op at VM level**。

### jni_DestroyJavaVM

`prims/jni.cpp:3740-3778`。有序关闭的正门，函数名是 `jni_DestroyJavaVM_inner`（外层 `jni_DestroyJavaVM` 只加了 Windows SEH 保护），它做三件事：

```c++
  res = vm->AttachCurrentThread((void **)&env, (void *)&destroyargs);
  if (res != JNI_OK) {
    return res;
  }
  JavaThread* thread = JavaThread::current();
  // Make sure we are actually in a newly attached thread, with no
  // existing Java frame.
  if (thread->has_last_Java_frame()) {
    return JNI_ERR;
  }
  ThreadStateTransition::transition_from_native(thread, _thread_in_vm);
  Threads::destroy_vm();
  // Don't bother restoring thread state, VM is gone.
  vm_created = NOT_CREATED;
```

`has_last_Java_frame()` 检查意味着：**还有 Java 栈帧的线程调 `DestroyJavaVM` 会直接返回 `JNI_ERR`**，VM 不会开始关闭。这是 VM 侧对「不许在 Java 代码里拆自己脚手架」的强制。

`Threads::destroy_vm()` 在本树只有两个调用点：`prims/jni.cpp:3774` 与 `ci/ciReplay.cpp:1329`（`-XX:replay-compiler-replay=...` 的编译器重放跑完后收尾）。

### vm_exit

`runtime/java.cpp:522-563`。`System.exit` / `Runtime.halt` 的落点，也用于 VM 内部严重错误：

```c++
void vm_exit(int code) {
  Thread* thread =
      ThreadLocalStorage::is_initialized() ? Thread::current_or_null() : nullptr;
  if (thread == nullptr) {
    // very early initialization failure -- just exit
    vm_direct_exit(code);
  }
  ...
  if (VMThread::vm_thread() != nullptr) {
    // Fire off a VM_Exit operation to bring VM to a safepoint and exit
    VM_Exit op(code);
    // 4945125 The vm thread comes to a safepoint during exit. ...
    // Grab the Heap_lock to prevent this.
    MutexLocker ml(Heap_lock);
    VMThread::execute(&op);
    // should never reach here; but in case something wrong with VM Thread.
    vm_direct_exit(code);
  } else {
    // VM thread is gone, just exit
    vm_direct_exit(code);
  }
  ShouldNotReachHere();
}
```

三个 `vm_direct_exit(code)` 兜底对应三种"来不及优雅关闭"的情形：极早期初始化失败（连 TLS 都没建好）、VMThread 已经死了、以及 `VMThread::execute` 意外返回。**`vm_exit` 这条路径上没有任何地方等待 non-daemon 线程归零**——它是"立刻带走整个 VM"的语义。

`runtime/java.cpp:570-574` 的 `vm_direct_exit(code)` 是真正的最短路径：`notify_vm_shutdown()`（dtrace probe）→ `os::wait_for_keypress_at_exit()` → `os::exit(code)`。而 `os::exit` 就是 libc `exit`（`os/posix/os_posix.cpp:985-987`，被包进 `permit_forbidden_function` 才能调用）——它会跑 C 层 `atexit` 处理器，但**不会**给 Java shutdown hook 任何机会。

### Java Side Chain

`System.exit(n)` → `Runtime.exit(n)` → `java.lang.Shutdown.exit(n)`：**先在 Java 层跑完 shutdown hooks，再调 `Runtime.halt(n)`**，后者经 `JVM_Halt` 落到上面那条 VM 路径（`prims/jvm.cpp:439-442`）。Java 源码不在本树，此处只给方向；VM 侧唯一能看到的是 `prims/jvm.cpp:430-442` 的两个入口：

```c++
JVM_ENTRY_NO_ENV(void, JVM_BeforeHalt())
  EventShutdown event;
  if (event.should_commit()) {
    event.set_reason("Shutdown requested from Java");
    event.commit();
  }
JVM_END
JVM_ENTRY_NO_ENV(void, JVM_Halt(jint code))
  before_exit(thread, true);
  vm_exit(code);
JVM_END
```

`JVM_BeforeHalt` 只打一个 JFR `EventShutdown`（供事件流区分"关是 Java 请求的"），`JVM_Halt` 才是真的开始拆 VM。**注意 `before_exit(thread, /*halt=*/true)`：halt 参数在这条路上恒为 true**，与 `destroy_vm` 里的 `before_exit(thread)`（默认 false）不同。

## destroy_vm

JDK 27 的 `runtime/threads.cpp:928-1023`。函数头注释给出的 shutdown sequence 是本篇的主干（`runtime/threads.cpp:901-926` 原文）：

```text
Shutdown sequence:
  + Shutdown native memory tracking if it is on
  + Wait until we are the last non-daemon thread to execute
    <-- every thing is still working at this moment -->
  + Call java.lang.Shutdown.shutdown(), which will invoke Java level
       shutdown hooks
  + Call before_exit(), prepare for VM exit
     > run VM level shutdown hooks (they are registered through JVM_OnExit(),
       currently the only user of this mechanism is File.deleteOnExit())
     > stop watcher thread,
       post thread end and vm death events to JVMTI,
       stop signal thread
  + Call JavaThread::exit(), it will:
     > release JNI handle blocks, remove stack guard pages
     > remove this thread from Threads list
    <-- no more Java code from this thread after this point -->
  + Stop VM thread, it will bring the remaining VM to a safepoint and stop
    the compiler threads at safepoint
    <-- do not use anything that could get blocked by Safepoint -->
  + Disable tracing at JNI/JVM barriers
  + Set _vm_exited flag for threads that are still running native code
  + Call exit_globals()
     > deletes tty
     > deletes PerfMemory resources
  + Delete this thread
  + Return to caller
```

> [!WARNING]
>
> 上面这段是**上游注释原文**，其中 `JVM_OnExit()` 那一行在 JDK 27 已经是化石（见 Version Baseline 第 1 条）。`runtime/threads.cpp` 里注释提到的机制与实际代码已经不一致，读源码时不要把它当现状。

`runtime/threads.cpp:928-1023` 的骨架（`...` 为省略，其余为源码原文）：

```c++
void Threads::destroy_vm() {
  JavaThread* thread = JavaThread::current();
  ...
  // Wait until we are the last non-daemon thread to execute, or
  // if we are a daemon then wait until the last non-daemon thread has
  // executed.
  bool daemon = java_lang_Thread::is_daemon(thread->threadObj());
  int expected = daemon ? 0 : 1;
  {
    MonitorLocker nu(Threads_lock);
    while (Threads::number_of_non_daemon_threads() > expected)
      // This wait should make safepoint checks, wait without a timeout.
      nu.wait(0);
  }
  ...
  // run Java level shutdown hooks
  thread->invoke_shutdown_hooks();
  before_exit(thread);
  thread->exit(true);
  ...
  ThreadsSMRSupport::wait_until_not_protected(thread);
  // Stop VM thread.
  {
    MutexLocker ml(Heap_lock);
    VMThread::wait_for_vm_thread_exit();
    assert(SafepointSynchronize::is_at_safepoint(), "VM thread should exit at Safepoint");
    VMThread::destroy();
  }
  ...
  VM_Exit::set_vm_exited();
  ...
  notify_vm_shutdown();
  // exit_globals() will delete tty
  exit_globals();
  delete thread;
  LogConfiguration::finalize();
}
```

`ShowMessageBoxOnError` 且已报 VMError 时，前面还会插一段 `os::infinite_sleep()`（故意挂住等调试器附加）。三个容易看漏的点：

1. **等待循环可以响应安全点**（`nu.wait(0)` 不带 `_no_safepoint_check_flag`），所以这段等待期间 GC 与 VM operation 全部正常工作——这就是注释里那句 `every thing is still working at this moment`。`expected` 的 daemon-aware 逻辑是较新的改动：如果调 `DestroyJavaVM` 的线程自己是 daemon，它连"自己"都不该算进 non-daemon 数目。
2. **`wait_until_not_protected()` 是新增的必经步骤**：本线程已从主线程表摘掉，但可能还挂在别的线程的 secondary list 上；不等这些交互结束就拉终止安全点，会有线程持有指向已死线程的句柄。上游 `4945125` 注释解释了这里为什么要抢 `Heap_lock`：VMThread 退出时会进安全点，若 GC 类 vm_operation 卡在这个安全点上，堆就处于不可解析状态；**过了这一点，在 VM 真正退出前再也走不出安全点**。
3. **`LogConfiguration::finalize()` 在最末**（`runtime/threads.cpp:1022`）：统一日志的配置最后才拆，前面所有 shutdown 步骤都还能写日志，见 [Serviceability.md](/docs/CS/Java/JDK/JVM/Serviceability.md)。

## VM_Exit and Safepoint

两条路径最终都要把整个 VM 冻在安全点上，做这件事的是 `VM_Exit`：声明在 `runtime/vmOperations.hpp:244-265`，实现在 `runtime/vmOperations.cpp`。**注意真实函数名是 `VM_Exit::doit()`，本树不存在 `do_vm_exit` 这种名字。**

`VM_Exit` 没有 `doit_prologue` / `doit_epilogue`，因此按 VM operation 的常规规则**在安全点内执行**。`vm_exit()` 侧负责把 `Heap_lock` 抢先握住（见上文注释 4945125），使 GC 类 vm_operation 在 VMThread 死掉之前无法入队——否则堆会停在"安全点上但再也走不出去"的状态。

`runtime/vmOperations.cpp:534-580`：

```c++
void VM_Exit::doit() {
  CompileBroker::set_should_block();
  // Wait for a short period for threads in native to block. Any thread
  // still executing native code after the wait will be stopped at
  // native==>Java/VM barriers.
  wait_for_threads_in_native_to_block();
  set_vm_exited();
  // The ObjectMonitor subsystem uses perf counters so do this before
  // we call exit_globals() so we don't run afoul of perfMemory_exit().
  ObjectSynchronizer::do_final_audit_and_print_stats();
  exit_globals();
  LogConfiguration::finalize();
  // Check for exit hook
  exit_hook_t exit_hook = Arguments::exit_hook();
  if (exit_hook != nullptr) {
    // exit hook should exit.
    exit_hook(_exit_code);
    // ... but if it didn't, we must do it here
    vm_direct_exit(_exit_code);
  } else {
    vm_direct_exit(_exit_code);
  }
}
```

三个动作值得单独说：

1. **停编译器线程**：`doit()` 开头还有 `VerifyBeforeExit`（默认关，开了会在最终安全点前跑一次 `Universe::verify()`）；随后 `CompileBroker::set_should_block()`（`compiler/compileBroker.cpp:1830-1838`）要求调用者**已持有 `Threads_lock` 且已在安全点**（两条 assert 写得很明白），它只置 `_should_block = true`；编译器线程随后在 `maybe_block` 处自锁，不再触碰正在被拆掉的 VM 数据结构。
2. **等在 native 里的线程安静下来**：`VM_Exit::wait_for_threads_in_native_to_block()`（`runtime/vmOperations.cpp:471-532`）必须在最终安全点调用（有 assert）。它按 `_thread_in_native` 状态扫描线程，指数退避从 10 µs 涨到 10 ms：**普通线程的期限是 `UserThreadWaitAttemptsAtExit` 个 10 ms（上限 10 s），编译器线程至少等 10 s**。上游注释给的经验值是 16276 个 JCK 用例里 94% 到这里已无 native 线程在跑，其余 6% 在 250 ms 内安静。原因见源码注释——编译器线程在 native 状态也能直接访问 VM 数据，如果它们正在用的结构被 shutdown 删掉就会崩；普通线程必须先过 native→Java/VM 转换屏障，会在那儿被拦住。
3. **`set_vm_exited()`**（`runtime/vmOperations.cpp:451-469`）：置全局 `_vm_exited = true`，并给所有仍在 native 的线程打上线程级 `JavaThread::_vm_exited` terminated 标记，返回"仍处于 active 的 native 线程数"。这些线程之后一旦想回到 Java/VM，就会在 `SafepointSynchronize::block()` 里被 `thread->block_if_vm_exited()`（`runtime/safepoint.cpp:566-572`）挂住，或走 `JavaThread::block_if_vm_exited()`（`runtime/javaThread.cpp:520-523`）；JNI/JVM 入口也统一调 `VM_Exit::block_if_vm_exited()`（`prims/jni.cpp:3955`、`prims/jvm.cpp:3242-3261`）。**这就是注释里 "Disable tracing at JNI/JVM barriers" 与 "do not use anything that could get blocked by Safepoint" 的具体落点。**

与 [Safepoint.md](/docs/CS/Java/JDK/JVM/Safepoint.md) 的分工：安全点协议本身（`SafepointSynchronize::begin/end`、`_at_safepoint` 状态机、spin-block 策略）在那篇讲；本篇只讲**终止安全点是一次不回头的特殊用法**——`VM_Exit` 之后没有任何线程会再执行字节码。

## Two Sets of Shutdown Hooks

### Java Level Shutdown Hooks

`Threads::destroy_vm()` 调 `JavaThread::invoke_shutdown_hooks()`（`runtime/javaThread.cpp:1941-1969`），实现就是反射式地调一个静态方法：

```c++
// Last thread running calls java.lang.Shutdown.shutdown()
void JavaThread::invoke_shutdown_hooks() {
  HandleMark hm(this);
  // We could get here with a pending exception, if so clear it now.
  if (this->has_pending_exception()) { this->clear_pending_exception(); }
  EXCEPTION_MARK;
  Klass* shutdown_klass =
    SystemDictionary::resolve_or_null(vmSymbols::java_lang_Shutdown(), THREAD);
  if (shutdown_klass != nullptr) {
    JavaValue result(T_VOID);
    JavaCalls::call_static(&result, shutdown_klass, vmSymbols::shutdown_name(),
                           vmSymbols::void_method_signature(), THREAD);
  }
  CLEAR_PENDING_EXCEPTION;
}
```

**`java.lang.Shutdown` 加载失败会静默跳过所有 hook**（源码注释：`just don't call Shutdown.shutdown() at all`，连报错都没有）——这是"hook 莫名没跑"的一个隐蔽成因。

*In an orderly shutdown, the JVM first starts all registered shutdown hooks.* Shutdown hooks are unstarted threads that are registered with `Runtime.addShutdownHook`. The JVM makes no guarantees on the order in which shutdown hooks are started. If any application threads (daemon or non-daemon) are still running at shutdown time, they continue to run concurrently with the shutdown process. When all shutdown hooks have completed, the JVM may choose to run finalizers if `runFinalizersOnExit` is true, and then halts. The JVM makes no attempt to stop or interrupt any application threads that are still running at shutdown time; they are abruptly terminated when the JVM eventually halts. If the shutdown hooks or finalizers don't complete, then the orderly shutdown process "hangs" and the JVM must be shut down abruptly. *In an abrupt shutdown, the JVM is not required to do anything other than halt the JVM; shutdown hooks will not run.*

**Shutdown hooks should be thread-safe**: they must use synchronization when accessing shared data and should be careful to avoid deadlock, just like any other concurrent code. Further, they should not make assumptions about the state of the application (such as whether other services have shut down already or all normal threads have completed) or about why the JVM is shutting down, and must therefore be coded extremely defensively. Finally, they should exit as quickly as possible, since their existence delays JVM termination at a time when the user may be expecting the JVM to terminate quickly.

Shutdown hooks can be used for service or application cleanup, such as deleting temporary files or cleaning up resources that are not automatically cleaned up by the OS. Because shutdown hooks all run concurrently, closing the log file could cause trouble for other shutdown hooks who want to use the logger. To avoid this problem, shutdown hooks should not rely on services that can be shut down by the application or other shutdown hooks. One way to accomplish this is to use a single shutdown hook for all services, rather than one for each service, and have it call a series of shutdown actions. For example [DubboShutdownHook](/docs/CS/Framework/Dubbo/Start.md?id=shutdown-hook)。

### VM Level before_exit

`before_exit(JavaThread* thread, bool halt)`（`runtime/java.cpp:375-520`）跑的是**VM 内部自身的收尾**，不是给用户挂回调的地方。它的三段式状态机值得注意：

```c++
void before_exit(JavaThread* thread, bool halt) {
  #define BEFORE_EXIT_NOT_RUN 0
  #define BEFORE_EXIT_RUNNING 1
  #define BEFORE_EXIT_DONE    2
  static jint volatile _before_exit_status = BEFORE_EXIT_NOT_RUN;
  ...
  { MonitorLocker ml(BeforeExit_lock);
    switch (_before_exit_status) { ... }   // NOT_RUN → RUNNING → DONE
  }
```

源码注释写明 `before_exit() can be executed only once`：后进来的线程（例如某个 hook 又调了 `System.exit`）会等到第一个线程做完再直接返回。用 `Monitor` 而不是 `Mutex` 全程保护，是因为 `JvmtiExport::post_thread_end_event` / `post_vm_death_event` 会跑 native 代码。

JDK 27 里 `before_exit()` 的实际内容（按代码顺序，`runtime/java.cpp:415-515`）：

| 顺序 | 动作 |
| :--- | :--- |
| 1 | LSan 泄漏检查：`halt` 或已报 VMError 时走 recoverable 检查（`:415-427`） |
| 2 | CDS：`DynamicArchive::dump_at_exit(thread)`（必须还能跑 Java 代码）→ `ClassListWriter::write_resolved_constants()` 与静态归档 dump（`:429-444`） |
| 3 | `ShowMessageBoxOnError` 且已报错 → `os::infinite_sleep()`；JFR `EventThreadEnd` + `Jfr::on_vm_shutdown(false, halt)`（`:446-457`） |
| 4 | `WatcherThread::stop()`、`NativeHeapTrimmer::cleanup()`（`:459-463`） |
| 5 | JVMTI `post_thread_end` → `post_vm_death` → `JvmtiAgentList::unload_agents()`（`:465-472`） |
| 6 | `Universe::before_exit()` 停并发 GC 线程（`:477`，`memory/universe.cpp:1374`）；Linux 下 `DumpPerfMapAtExit` / `PrintMemoryMapAtExit`（`:483-490`） |
| 7 | `os::terminate_signal_thread()`（不等它真死）→ `print_statistics()` → 置 `BEFORE_EXIT_DONE`（`:492-507`） |

第 5 步之后源码里有一句硬边界注释：**`No user code can be executed in the current thread after this point.`** 第 6 步的 `Universe::before_exit()` 是"注释里 VM level shutdown hooks"在 JDK 27 的**实际替身**——它做的是停 GC 线程，而不是跑用户注册表。

也就是说：**"通过 `JVM_OnExit()` 注册、唯一用户是 `File.deleteOnExit()`" 这句话在 JDK 27 的 HotSpot 里已经不成立**——机制本身没了，`deleteOnExit` 的语义改由 Java 层 `java.lang.Shutdown` 的 hook 承担（Java 侧源码不在本树，未逐行核实）。VM 级还留着的"注册钩子"只有 `Arguments::exit_hook()`，来源是 JNI Invocation API 的选项字符串 `exit`（`runtime/arguments.cpp:2383-2388`，与 `vfprintf` / `abort` 两个 hook 并列）——这是嵌入 JVM 的宿主程序接管退出行为的手段，与 Java 用户无关。

## halt abort and crash

三条终止路径的强度依次递增，共同点是**都不跑 Java shutdown hooks**。

| 路径 | 最终调用 | 走 `before_exit` | 走 `VM_Exit` 安全点 | 产出 |
| :--- | :--- | :--- | :--- | :--- |
| `Runtime.halt` | `vm_direct_exit` → `os::exit` | 是（`halt=true`） | 是（`VMThread::execute`） | 干净退出，返回码可控 |
| VM 致命错误 | `VMError::report_and_die` → `os::abort` → `os::die` | **否** | 否 | `hs_err_pid*.log` + core |
| `SIGKILL` | 无 | 否 | 否 | 什么都没有 |

`Runtime.halt(n)`：Java 层不调 `Shutdown.shutdown()`，因此 hook 一个不跑；VM 侧仍按 `JVM_Halt` 走 `before_exit(thread, true)` + `vm_exit(n)`，所以 JVMTI vm-death、JFR 落盘、GC 线程停止、`exit_globals` 全都正常做完。**halt 是"跳过用户 hook"，不是"跳过 VM 清理"。**

`FatalError` / 崩溃：`utilities/vmError.cpp` 的 `report_and_die` 序列结束时（`:1974-1988`）：

```c++
  // os::abort() will call abort hooks, try it first.
  static bool skip_os_abort = false;
  if (!skip_os_abort) {
    skip_os_abort = true;
    bool dump_core = should_report_bug(_id);
    os::abort(dump_core && CreateCoredumpOnCrash, _siginfo, _context);
    // if os::abort() doesn't abort, try os::die();
  }
  os::die();
```

要点：**本树 `vmError.cpp` 里既没有 `before_exit` 也没有 `vm_exit` 的调用点**（grep 只命中 `:1184` 读 `VM_Exit::vm_exited()` 来打印 `(shutting down)`）。崩溃路径靠 `os::abort`（内部含 abort hooks、可选 core dump，受 `CreateCoredumpOnCrash` 控制）与兜底的 `os::die` 结束进程，`OnError` 只能靠 `os::fork_and_exec` 执行外部命令（`:1962-1967`）。这解释了崩溃现场的两个常见困惑：**hook 不跑，所以资源没释放；但 `hs_err` 的 "(not fully initialized)" / "(shutting down)" 尾注能告诉你崩在生命周期的哪一段**（判据就是 `Universe::is_fully_initialized()` 与 `VM_Exit::vm_exited()`）。

`SIGKILL`：JVM **没有任何机会执行任何一行代码**——没有 hook、没有 finalizer、没有 `hs_err`、JFR 环形缓冲未落盘部分直接丢，连 `deleteOnExit` 的临时文件都不会被清；只有 OS 回收地址空间与 fd。所有"必须完成"的收尾都不能挂在退出路径上，这一点和 [Ref.md](/docs/CS/Java/JDK/Basic/Ref.md) 里 finalizer 不可靠的结论同源。

> [!TIP]
>
> 还有一个"VM 自己决定退出"的产品外路径：`ExitOnFullCodeCache`（`compiler/compileBroker.cpp:2169-2175`，`#ifndef PRODUCT`）在 CodeCache 打满时直接 `before_exit` → `exit_globals` → `vm_direct_exit(1)`。生产构建里不存在这个开关，别在诊断"进程莫名退出"时找它。

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)
- [Thread](/docs/CS/Java/JDK/JVM/Thread.md)
- [Handles](/docs/CS/Java/JDK/JVM/Handles.md)
- [JNI](/docs/CS/Java/JDK/Basic/JNI.md)
- [Serviceability](/docs/CS/Java/JDK/JVM/Serviceability.md)

## References

- [Java Native Interface Specification](https://docs.oracle.com/en/java/javase/27/docs/specs/jni/functions.html)
- [Runtime (Java SE 27 API)](https://docs.oracle.com/en/java/javase/27/docs/api/java.base/java/lang/Runtime.html)
- [Java Virtual Machine Tool Interface](https://docs.oracle.com/en/java/javase/27/docs/specs/jvmti.html)
- [JDK 27 Release Notes](https://openjdk.org/projects/jdk/27/)
