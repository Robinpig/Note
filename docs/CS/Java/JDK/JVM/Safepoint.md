## Introduction


### Preemptive Suspension

### Voluntary Suspension


Main thread will print the num util sub thread ends, not after 1000ms we expected.

```java
public static AtomicInteger num = new AtomicInteger(0);

public static void main(String[] args) throws Throwable {
    Runnable runnable = () -> {
        for (int i = 0; i < 1000000000; i++) {
            num.getAndAdd(1);
        }
    };

    Thread t1 = new Thread(runnable);
    Thread t2 = new Thread(runnable);
    t1.start();
    t2.start();

    System.out.println("before sleep");
    Thread.sleep(1000);
    System.out.println("after sleep");

    System.out.println(num);
}
```



## PrintStatistics

```shell
-XX:+PrintSafepointStatistics  -XX:PrintSafepointStatisticsCount = 1
logsafepoint=debug # JDK11
```

> Task :MainTest.main()
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 1.016: no vm operation                  [      11          2              2    ]      [ 29399     0 29399     0     0    ]  0   
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 30.416: EnableBiasedLocking              [      11          0              0    ]      [     0     0     0     0     0    ]  0   
> num = 2000000000
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 30.416: no vm operation                  [       8          1              1    ]      [     0     0     0     0     0    ]  0 >  
> Polling page always armed
> EnableBiasedLocking                1
>     0 VM operations coalesced during safepoint
> Maximum sync time  29399 ms
> Maximum vm operation time (except for Exit VM operation)      0 ms


-XX:+SafePointTimeout -XX:SafepointTimeoutDelay=2000



## Fix



```
 -XX:+UnlockDiagnosticVMOptions  -XX:GuaranteedSafepointInterval=2000 
```
 *-XX:GuaranteedSafepointInterval=2000* option set safepoint after thread sleep ends.

```
-XX:+UseCountedLoopSafepoints
```

`-XX:+UseCountedLoopSafepoints` option turns off the optimization that eliminates safepoint polling.

Other methods

- Use JDK10 and later
- Use long to limit a countedLoop



`SafepointMechanism::default_initialize`

*SafePoint actually a page of memory*



### Run

#### VMThread::loop

vm operation see `vmOperations.hpp`

```cpp
void VMThread::loop() {
  assert(_cur_vm_operation == NULL, "no current one should be executing");

  while(true) {
    VM_Operation* safepoint_ops = NULL;
    //
    // Wait for VM operation
    //
    // use no_safepoint_check to get lock without attempting to "sneak"
    { MutexLockerEx mu_queue(VMOperationQueue_lock,
                             Mutex::_no_safepoint_check_flag);

      // Look for new operation
      assert(_cur_vm_operation == NULL, "no current one should be executing");
      _cur_vm_operation = _vm_queue->remove_next();

      // Stall time tracking code
      if (PrintVMQWaitTime && _cur_vm_operation != NULL &&
          !_cur_vm_operation->evaluate_concurrently()) {
        long stall = os::javaTimeMillis() - _cur_vm_operation->timestamp();
        if (stall > 0)
          tty->print_cr("%s stall: %ld",  _cur_vm_operation->name(), stall);
      }

      while (!should_terminate() && _cur_vm_operation == NULL) {
        // wait with a timeout to guarantee safepoints at regular intervals
        bool timedout =
          VMOperationQueue_lock->wait(Mutex::_no_safepoint_check_flag,
                                      GuaranteedSafepointInterval);

        // Support for self destruction
        if ((SelfDestructTimer != 0) && !VMError::is_error_reported() &&
            (os::elapsedTime() > (double)SelfDestructTimer * 60.0)) {
          tty->print_cr("VM self-destructed");
          exit(-1);
        }

        if (timedout && VMThread::no_op_safepoint_needed(false)) { 
          MutexUnlockerEx mul(VMOperationQueue_lock,
                              Mutex::_no_safepoint_check_flag);
          // Force a safepoint since we have not had one for at least
          // 'GuaranteedSafepointInterval' milliseconds.  This will run all
          // the clean-up processing that needs to be done regularly at a
          // safepoint
          SafepointSynchronize::begin();
          #ifdef ASSERT
            if (GCALotAtAllSafepoints) InterfaceSupport::check_gc_alot();
          #endif
          SafepointSynchronize::end();
        }
        _cur_vm_operation = _vm_queue->remove_next();

        // If we are at a safepoint we will evaluate all the operations that
        // follow that also require a safepoint
        if (_cur_vm_operation != NULL &&
            _cur_vm_operation->evaluate_at_safepoint()) {
          safepoint_ops = _vm_queue->drain_at_safepoint_priority();
        }
      }

      if (should_terminate()) break;
    } // Release mu_queue_lock

    //
    // Execute VM operation
    //
    { HandleMark hm(VMThread::vm_thread());

      EventMark em("Executing VM operation: %s", vm_operation()->name());
      assert(_cur_vm_operation != NULL, "we should have found an operation to execute");

      // If we are at a safepoint we will evaluate all the operations that
      // follow that also require a safepoint
      if (_cur_vm_operation->evaluate_at_safepoint()) {
        log_debug(vmthread)("Evaluating safepoint VM operation: %s", _cur_vm_operation->name());

        _vm_queue->set_drain_list(safepoint_ops); // ensure ops can be scanned

        SafepointSynchronize::begin();

        if (_timeout_task != NULL) {
          _timeout_task->arm();
        }

        evaluate_operation(_cur_vm_operation);
        // now process all queued safepoint ops, iteratively draining
        // the queue until there are none left
        do {
          _cur_vm_operation = safepoint_ops;
          if (_cur_vm_operation != NULL) {
            do {
              log_debug(vmthread)("Evaluating coalesced safepoint VM operation: %s", _cur_vm_operation->name());
              // evaluate_operation deletes the op object so we have
              // to grab the next op now
              VM_Operation* next = _cur_vm_operation->next();
              _vm_queue->set_drain_list(next);
              evaluate_operation(_cur_vm_operation);
              _cur_vm_operation = next;
              if (log_is_enabled(Debug, safepoint, stats)) {
                SafepointSynchronize::inc_vmop_coalesced_count();
              }
            } while (_cur_vm_operation != NULL);
          }
          // There is a chance that a thread enqueued a safepoint op
          // since we released the op-queue lock and initiated the safepoint.
          // So we drain the queue again if there is anything there, as an
          // optimization to try and reduce the number of safepoints.
          // As the safepoint synchronizes us with JavaThreads we will see
          // any enqueue made by a JavaThread, but the peek will not
          // necessarily detect a concurrent enqueue by a GC thread, but
          // that simply means the op will wait for the next major cycle of the
          // VMThread - just as it would if the GC thread lost the race for
          // the lock.
          if (_vm_queue->peek_at_safepoint_priority()) {
            // must hold lock while draining queue
            MutexLockerEx mu_queue(VMOperationQueue_lock,
                                     Mutex::_no_safepoint_check_flag);
            safepoint_ops = _vm_queue->drain_at_safepoint_priority();
          } else {
            safepoint_ops = NULL;
          }
        } while(safepoint_ops != NULL);

        _vm_queue->set_drain_list(NULL);

        if (_timeout_task != NULL) {
          _timeout_task->disarm();
        }

        // Complete safepoint synchronization
        SafepointSynchronize::end();

      } else {  // not a safepoint operation
        log_debug(vmthread)("Evaluating non-safepoint VM operation: %s", _cur_vm_operation->name());
        if (TraceLongCompiles) {
          elapsedTimer t;
          t.start();
          evaluate_operation(_cur_vm_operation);
          t.stop();
          double secs = t.seconds();
          if (secs * 1e3 > LongCompileThreshold) {
            // XXX - _cur_vm_operation should not be accessed after
            // the completed count has been incremented; the waiting
            // thread may have already freed this memory.
            tty->print_cr("vm %s: %3.7f secs]", _cur_vm_operation->name(), secs);
          }
        } else {
          evaluate_operation(_cur_vm_operation);
        }

        _cur_vm_operation = NULL;
      }
    }

    //
    //  Notify (potential) waiting Java thread(s) - lock without safepoint
    //  check so that sneaking is not possible
    { MutexLockerEx mu(VMOperationRequest_lock,
                       Mutex::_no_safepoint_check_flag);
      VMOperationRequest_lock->notify_all();
    }

    //
    // We want to make sure that we get to a safepoint regularly.
    //
    if (VMThread::no_op_safepoint_needed(true)) {
      HandleMark hm(VMThread::vm_thread());
      SafepointSynchronize::begin();
      SafepointSynchronize::end();
    }
  }
}

bool VMThread::no_op_safepoint_needed(bool check_time) {
  if (SafepointALot) {
    _no_op_reason = "SafepointALot";
    return true;
  }
  if (!SafepointSynchronize::is_cleanup_needed()) {
    return false;
  }
  if (check_time) {
    long interval = SafepointSynchronize::last_non_safepoint_interval();
    bool max_time_exceeded = GuaranteedSafepointInterval != 0 &&
                             (interval > GuaranteedSafepointInterval);
    if (!max_time_exceeded) {
      return false;
    }
  }
  _no_op_reason = "Cleanup";
  return true;
}
```



#### Need a safepoint

```cpp
// safepoint.cpp
bool SafepointSynchronize::is_cleanup_needed() {
  // Need a safepoint if there are many monitors to deflate.
  if (ObjectSynchronizer::is_cleanup_needed()) return true;
```  
Need a safepoint if some inline cache buffers is non-empty
```  
  if (!InlineCacheBuffer::is_empty()) return true;
  return false;
}
```
##### many monitors to deflate
```cpp
// synchronizer.cpp
static bool monitors_used_above_threshold() {
  if (gMonitorPopulation == 0) {
    return false;
  }
  int monitors_used = gMonitorPopulation - gMonitorFreeCount;
  int monitor_usage = (monitors_used * 100LL) / gMonitorPopulation;
  return monitor_usage > MonitorUsedDeflationThreshold;
}

bool ObjectSynchronizer::is_cleanup_needed() {
  if (MonitorUsedDeflationThreshold > 0) {
    return monitors_used_above_threshold();
  }
  return false;
}
```

##### some inline cache buffers is non-empty

check if [StubQueue](/docs/CS/Java/JDK/JVM/interpreter.md?id=StubQueue) is non-empty
```cpp
// icBuffer.cpp
lass InlineCacheBuffer: public AllStatic {
 private:
  // friends
  friend class ICStub;

  static int ic_stub_code_size();

  static StubQueue* _buffer;

  static CompiledICHolder* _pending_released;
  static int _pending_count;

  static StubQueue* buffer()                         { return _buffer;         }

  static ICStub* new_ic_stub();

  // Machine-dependent implementation of ICBuffer
  static void    assemble_ic_buffer_code(address code_begin, void* cached_value, address entry_point);
  static address ic_buffer_entry_point  (address code_begin);
  static void*   ic_buffer_cached_value (address code_begin);
}

bool InlineCacheBuffer::is_empty() {
  return buffer()->number_of_stubs() == 0;
}
```

##### string/symbol table rehash



#### SafepointSynchronize::begin

```cpp
// safepoint.cpp
// Roll all threads forward to a safepoint and suspend them all
void SafepointSynchronize::begin() {
 
    // Make interpreter safepoint aware
    Interpreter::notice_safepoints();

    // Make polling safepoint aware
    guarantee (PageArmed == 0, "invariant") ;
    PageArmed = 1 ;
    os::make_polling_page_unreadable();
 

    // wait until all threads are stopped STW
    while (_waiting_to_block > 0) {
    ..
    }
}
```

#### SafepointSynchronize#end()

Wake up all threads, so they are ready to resume execution after the safepoint operation has been carried out
```cpp
//safepoint.cpp
void SafepointSynchronize::end() {
  assert(Threads_lock->owned_by_self(), "must hold Threads_lock");
  assert((_safepoint_counter & 0x1) == 1, "must be odd");
  EventSafepointEnd event;
  _safepoint_counter ++;
  // memory fence isn't required here since an odd _safepoint_counter
  // value can do no harm and a fence is issued below anyway.

  DEBUG_ONLY(Thread* myThread = Thread::current();)
  assert(myThread->is_VM_thread(), "Only VM thread can execute a safepoint");

  if (log_is_enabled(Debug, safepoint, stats)) {
    end_statistics(os::javaTimeNanos());
  }

  {
    JavaThreadIteratorWithHandle jtiwh;
#ifdef ASSERT
    // A pending_exception cannot be installed during a safepoint.  The threads
    // may install an async exception after they come back from a safepoint into
    // pending_exception after they unblock.  But that should happen later.
    for (; JavaThread *cur = jtiwh.next(); ) {
      assert (!(cur->has_pending_exception() &&
                cur->safepoint_state()->is_at_poll_safepoint()),
              "safepoint installed a pending exception");
    }
#endif // ASSERT

    if (PageArmed) {
      assert(SafepointMechanism::uses_global_page_poll(), "sanity");
      // Make polling safepoint aware
      os::make_polling_page_readable();
      PageArmed = 0 ;
    }

    if (SafepointMechanism::uses_global_page_poll()) {
      // Remove safepoint check from interpreter
      Interpreter::ignore_safepoints();
    }

    {
      MutexLocker mu(Safepoint_lock);

      assert(_state == _synchronized, "must be synchronized before ending safepoint synchronization");

      if (SafepointMechanism::uses_thread_local_poll()) {
        _state = _not_synchronized;
        OrderAccess::storestore(); // global state -> local state
        jtiwh.rewind();
        for (; JavaThread *current = jtiwh.next(); ) {
          ThreadSafepointState* cur_state = current->safepoint_state();
          cur_state->restart(); // TSS _running
          SafepointMechanism::disarm_local_poll(current);
        }
        log_info(safepoint)("Leaving safepoint region");
      } else {
        // Set to not synchronized, so the threads will not go into the signal_thread_blocked method
        // when they get restarted.
        _state = _not_synchronized;
        OrderAccess::fence();

        log_info(safepoint)("Leaving safepoint region");

        // Start suspended threads
        jtiwh.rewind();
        for (; JavaThread *current = jtiwh.next(); ) {
          ThreadSafepointState* cur_state = current->safepoint_state();
          assert(cur_state->type() != ThreadSafepointState::_running, "Thread not suspended at safepoint");
          cur_state->restart();
          assert(cur_state->is_running(), "safepoint state has not been reset");
        }
      }

      RuntimeService::record_safepoint_end();

      // Release threads lock, so threads can be created/destroyed again.
      // It will also release all threads blocked in signal_thread_blocked.
      Threads_lock->unlock();
    }
  } // ThreadsListHandle destroyed here.

  Universe::heap()->safepoint_synchronize_end();
  // record this time so VMThread can keep track how much time has elapsed
  // since last safepoint.
  _end_of_last_safepoint = os::javaTimeMillis();
  if (event.should_commit()) {
    post_safepoint_end_event(&event);
  }
}
```



## Thread

### in vm

operation must be done than goto safepoint



### in native

Default be in safepoint



### in java-interpreter

Dispatch table

1. normal table
2. Safest table

swtich dispatch table



### in Java-JIT



Polling page



Thread local handkerchief 



 



## References

1. [真是绝了！这段被JVM动了手脚的代码！](https://mp.weixin.qq.com/s/KDUccdLALWdjNBrFjVR74Q)
2. [StackOverFlow](https://stackoverflow.com/questions/67068057/the-main-thread-exceeds-the-set-sleep-time)

