## Overview
The JVM can shut down in either an orderly or abrupt manner. An orderly shutdown is initiated when the last "normal"(non‐daemon) thread terminates, someone calls `System.exit`, or by other platform‐specific means (such as sending a `SIGINT` or hitting `Ctrl-C`). While this is the standard and preferred way for the JVM to shut down, it can also be shut down abruptly by calling `Runtime.halt` or by killing the JVM process through the operating system (such as sending a `SIGKILL`).



## destroy_vm

- `Threads::destroy_vm()` is normally called from `jni_DestroyJavaVM()` when the program falls off the end of main().
- Another VM exit path is through vm_exit() when the program calls `System.exit()` to return a value or when there is a serious error in VM.
  
The two shutdown paths are not exactly the same, but they share Shutdown.shutdown() at Java level and before_exit() and VM_Exit op at VM level.
```
Shutdown sequence:
+ Shutdown native memory tracking if it is on
+ Wait until we are the last non-daemon thread to execute
  <-- every thing is still working at this moment -->
+ Call java.lang.Shutdown.shutdown(), which will invoke Java level
  shutdown hooks
+ Call before_exit(), prepare for VM exit
  > run VM level shutdown hooks (they are registered through JVM_OnExit(),
  currently the only user of this mechanism is File.deleteOnExit())
  > stop StatSampler, watcher thread, CMS threads,
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
Last thread running calls `java.lang.Shutdown.shutdown()`

## Shutdown Hooks
*In an orderly shutdown, the JVM first starts all registered shutdown hooks.* Shutdown hooks are unstarted threads that are registered with `Runtime.addShutdownHook`. The JVM makes no guarantees on the order in which shutdown hooks are started. If any application threads (daemon or nondaemon) are still running at shutdown time, they continue to run concurrently with the shutdown process. When all shutdown hooks have completed, the JVM may choose to run finalizers if runFinalizersOnExit is true, and then halts. The JVM makes no attempt to stop or interrupt any application threads that are still running at shutdown time; they are abruptly terminated when the JVM eventually halts. If the shutdown hooks or finalizers don't complete, then the orderly shutdown process "hangs" and the JVM must be shut down abruptly. 

*In an abrupt shutdown, the JVM is not required to do anything other than halt the JVM; shutdown hooks will not run.*

**Shutdown hooks should be thread‐safe**: they must use synchronization when accessing shared data and should be careful to avoid deadlock, just like any other concurrent code. Further, they should not make assumptions about the state of the application (such as whether other services have shut down already or all normal threads have completed)or about why the JVM is shutting down, and must therefore be coded extremely defensively. Finally, they should exit as quickly as possible, since their existence delays JVM termination at a time when the user may be expecting the JVM to terminate quickly.

Shutdown hooks can be used for service or application cleanup, such as deleting temporary files or cleaning up resources that are not automatically cleaned up by the OS. 

Because shutdown hooks all run concurrently, closing the log file could cause trouble for other shutdown hooks who want to use the logger. To avoid this problem, shutdown hooks should not rely on services that can be shut down by the application or other shutdown hooks. One way to accomplish this is to use a single shutdown hook for all services, rather than one for each service, and have it call a series of shutdown actions. For example [DubboShutdownHook](/docs/CS/Java/Dubbo/Start.md?id=shutdown-hooks)