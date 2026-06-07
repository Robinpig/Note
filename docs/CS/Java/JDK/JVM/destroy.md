## Overview

JVM 可以以有序或突然的方式关闭。
当最后一个"正常"（非守护）线程终止、有人调用 `System.exit` 或通过其他平台特定方式（如发送 `SIGINT` 或按 `Ctrl-C`）时，会启动有序关闭。

虽然这是 JVM 关闭的标准和首选方式，
但也可以通过调用 `Runtime.halt` 或通过操作系统杀死 JVM 进程（如发送 `SIGKILL`）来突然关闭。

## destroy_vm

- `Threads::destroy_vm()` 通常在程序从 [main()](/docs/CS/Java/JDK/JVM/start.md?id=main) 返回时从 `jni_DestroyJavaVM()` 调用。
- 另一个 VM 退出路径是通过 vm_exit()，当程序调用 `System.exit()` 返回值或 VM 中出现严重错误时。

这两个关闭路径并不完全相同，但它们在 Java 级别共享 Shutdown.shutdown()，在 VM 级别共享 before_exit() 和 VM_Exit 操作。

```
Shutdown sequence:
+ Shutdown native memory tracking if it is on
+ Wait until we are the last non-daemon thread to execute
  <-- every thing is still working at this moment -->
+ Call java.lang.Shutdown.shutdown(), which will invoke Java level shutdown hooks
+ Call before_exit(), prepare for VM exit
  > run VM level shutdown hooks (they are registered through JVM_OnExit(), currently the only user of this mechanism is File.deleteOnExit())
  > stop StatSampler, watcher thread, CMS threads, post thread end and vm death events to JVMTI, stop signal thread
+ Call JavaThread::exit(), it will:
  > release JNI handle blocks, remove stack guard pages
  > remove this thread from Threads list
  <-- no more Java code from this thread after this point -->
+ Stop VM thread, it will bring the remaining VM to a safepoint and stop the compiler threads at safepoint
  <-- do not use anything that could get blocked by Safepoint -->
+ Disable tracing at JNI/JVM barriers
+ Set _vm_exited flag for threads that are still running native code
+ Call exit_globals()
  > deletes tty
  > deletes PerfMemory resources
+ Delete this thread
+ Return to caller
```

1. Wait until we are the last non-daemon thread to execute

```cpp
// thread.cpp


bool Threads::destroy_vm() {
  JavaThread* thread = JavaThread::current();

#ifdef ASSERT
  _vm_complete = false;
#endif
  // Wait until we are the last non-daemon thread to execute
  { MutexLocker nu(Threads_lock);
    while (Threads::number_of_non_daemon_threads() > 1)
      // This wait should make safepoint checks, wait without a timeout,
      // and wait as a suspend-equivalent condition.
      Threads_lock->wait(!Mutex::_no_safepoint_check_flag, 0,
                         Mutex::_as_suspend_equivalent_flag);
  }

  EventShutdown e;
  if (e.should_commit()) {
    e.set_reason("No remaining non-daemon Java threads");
    e.commit();
  }

  // Hang forever on exit if we are reporting an error.
  if (ShowMessageBoxOnError && VMError::is_error_reported()) {
    os::infinite_sleep();
  }
  os::wait_for_keypress_at_exit();

  // run Java level shutdown hooks
  thread->invoke_shutdown_hooks();

  before_exit(thread);

  thread->exit(true);

  // Stop VM thread.
  {
    // 4945125 The vm thread comes to a safepoint during exit.
    // GC vm_operations can get caught at the safepoint, and the
    // heap is unparseable if they are caught. Grab the Heap_lock
    // to prevent this. The GC vm_operations will not be able to
    // queue until after the vm thread is dead. After this point,
    // we'll never emerge out of the safepoint before the VM exits.

    MutexLockerEx ml(Heap_lock, Mutex::_no_safepoint_check_flag);

    VMThread::wait_for_vm_thread_exit();
    assert(SafepointSynchronize::is_at_safepoint(), "VM thread should exit at Safepoint");
    VMThread::destroy();
  }

  // Now, all Java threads are gone except daemon threads. Daemon threads
  // running Java code or in VM are stopped by the Safepoint. However,
  // daemon threads executing native code are still running.  But they
  // will be stopped at native=>Java/VM barriers. Note that we can't
  // simply kill or suspend them, as it is inherently deadlock-prone.

  VM_Exit::set_vm_exited();

  // Clean up ideal graph printers after the VMThread has started
  // the final safepoint which will block all the Compiler threads.
  // Note that this Thread has already logically exited so the
  // clean_up() function's use of a JavaThreadIteratorWithHandle
  // would be a problem except set_vm_exited() has remembered the
  // shutdown thread which is granted a policy exception.
#if defined(COMPILER2) && !defined(PRODUCT)
  IdealGraphPrinter::clean_up();
#endif

  notify_vm_shutdown();

  // exit_globals() will delete tty
  exit_globals();

  // We are after VM_Exit::set_vm_exited() so we can't call
  // thread->smr_delete() or we will block on the Threads_lock.
  // Deleting the shutdown thread here is safe because another
  // JavaThread cannot have an active ThreadsListHandle for
  // this JavaThread.
  delete thread;

#if INCLUDE_JVMCI
  if (JVMCICounterSize > 0) {
    FREE_C_HEAP_ARRAY(jlong, JavaThread::_jvmci_old_thread_counters);
  }
#endif

  LogConfiguration::finalize();

  return true;
}
```

最后一个运行中的线程调用 `java.lang.Shutdown.shutdown()`

## Shutdown Hooks

*在有序关闭中，JVM 首先启动所有已注册的 shutdown hooks。* Shutdown hooks 是通过 `Runtime.addShutdownHook` 注册的未启动线程。JVM 不保证 shutdown hooks 启动的顺序。如果在关闭时任何应用程序线程（守护或非守护）仍在运行，它们将与关闭过程同时继续运行。当所有 shutdown hooks 完成后，如果 runFinalizersOnExit 为 true，JVM 可能会选择运行 finalizers，然后停止。JVM 不会尝试停止或中断关闭时仍在运行的任何应用程序线程；当 JVM 最终停止时，它们会被突然终止。如果 shutdown hooks 或 finalizers 没有完成，那么有序关闭过程会"挂起"，并且必须突然关闭 JVM。

*在突然关闭中，除了停止 JVM 之外，JVM 不需要执行任何操作；shutdown hooks 不会运行。*

**Shutdown hooks 应该是线程安全的**：它们必须在访问共享数据时使用同步，并应小心避免死锁，就像任何其他并发代码一样。此外，它们不应假设应用程序的状态（例如其他服务是否已关闭或所有正常线程是否已完成）或 JVM 关闭的原因，因此必须非常防御性地编码。最后，它们应尽可能快地退出，因为它们的存会延迟 JVM 终止，而此时用户可能正期望 JVM 快速终止。

Shutdown hooks 可用于服务或应用程序清理，例如删除临时文件或清理操作系统不会自动清理的资源。

由于所有 shutdown hooks 同时运行，关闭日志文件可能会给想要使用日志记录器的其他 shutdown hooks 带来麻烦。为避免此问题，shutdown hooks 不应依赖可能被应用程序或其他 shutdown hooks 关闭的服务。实现此目的的一种方法是为所有服务使用单个 shutdown hook，而不是为每个服务使用一个，并让它调用一系列关闭操作。例如 [DubboShutdownHook](/docs/CS/Framework/Dubbo/Start.md?id=shutdown-hooks)

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Start JVM](/docs/CS/Java/JDK/JVM/start.md)
