## Introduction

Java provides a built-in locking mechanism for enforcing atomicity: the **synchronized block**.
A synchronized block has two parts: a reference to an object that will serve as the lock, and a block of code to be guarded by that lock.
A synchronized method is a shorthand for a synchronized block that spans an entire method body, and whose lock is the object on which the method is being invoked
(Static synchronized methods use the Class object for the lock).

Every Java object can implicitly act as a lock for purposes of synchronization; these built-in locks are called intrinsic locks or monitor locks.
The lock is automatically acquired by the executing thread before entering a synchronized block and automatically released when control exits the synchronized block,
whether by the normal control path or by throwing an exception out of the block.
The only way to acquire an intrinsic lock is to enter a synchronized block or method guarded by that lock.

Intrinsic locks in Java act as mutexes (or mutual exclusion locks), which means that at most one thread may own the lock.
When thread A attempts to acquire a lock held by thread B, A must wait, or block, until B releases it.
If B never releases the lock, A waits forever.

The Java monitor pattern is inspired by Hoare's work on monitors (Hoare, 1974), though there are significant differences between this pattern and a true monitor. 


The bytecode instructions for entering and exiting a synchronized block are even called `monitorenter` and `monitorexit`, and Java's built‐in (intrinsic) locks are sometimes called monitor locks or monitors.
> [!NOTE]
> 
> [monitorenter](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=monitorenter) & [exit](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=monitorexit) are symmetric routines; which is reflected in the assembly code structure as well.


use javap -c   *.class

```
//synchronized with block finally add monitorexit
monitorenter monitorexit

//synchronized with method
ACC_SYNCHRONIZED
```



### MarkWord
[MarkWord](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=MarkWord) in [Oop](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=oop) header.


## Process

![sychronized](https://notfound9.github.io/interviewGuide/static/sychronize.png)




### monitorenter



In TemplateInterpreter

Synchronization Stack layout:
- expressions    <--- rsp               = expression stack top
- expressions   
- monitor entry  <--- monitor block top = expression stack bot
- monitor entry 
- frame data     <--- monitor block bot
- saved rbp      <--- rbp

```cpp
void TemplateTable::monitorenter() {
  transition(atos, vtos);

  // check for NULL object
  __ null_check(rax);

  const Address monitor_block_top(
        rbp, frame::interpreter_frame_monitor_block_top_offset * wordSize);
  const Address monitor_block_bot(
        rbp, frame::interpreter_frame_initial_sp_offset * wordSize);
  const int entry_size = frame::interpreter_frame_monitor_size() * wordSize;

  Label allocated;

  Register rtop = LP64_ONLY(c_rarg3) NOT_LP64(rcx);
  Register rbot = LP64_ONLY(c_rarg2) NOT_LP64(rbx);
  Register rmon = LP64_ONLY(c_rarg1) NOT_LP64(rdx);

  // initialize entry pointer
  __ xorl(rmon, rmon); // points to free slot or NULL

  // find a free slot in the monitor block (result in rmon)
  {
    Label entry, loop, exit;
    __ movptr(rtop, monitor_block_top); // points to current entry,
                                        // starting with top-most entry
    __ lea(rbot, monitor_block_bot);    // points to word before bottom
                                        // of monitor block
    __ jmpb(entry);

    __ bind(loop);
    // check if current entry is used
    __ cmpptr(Address(rtop, BasicObjectLock::obj_offset_in_bytes()), (int32_t) NULL_WORD);
    // if not used then remember entry in rmon
    __ cmovptr(Assembler::equal, rmon, rtop);   // cmov => cmovptr
    // check if current entry is for same object
    __ cmpptr(rax, Address(rtop, BasicObjectLock::obj_offset_in_bytes()));
    // if same object then stop searching
    __ jccb(Assembler::equal, exit);
    // otherwise advance to next entry
    __ addptr(rtop, entry_size);
    __ bind(entry);
    // check if bottom reached
    __ cmpptr(rtop, rbot);
    // if not at bottom then check this entry
    __ jcc(Assembler::notEqual, loop);
    __ bind(exit);
  }

  __ testptr(rmon, rmon); // check if a slot has been found
  __ jcc(Assembler::notZero, allocated); // if found, continue with that one

  // allocate one if there's no free slot
  {
    Label entry, loop;
    // 1. compute new pointers          // rsp: old expression stack top
    __ movptr(rmon, monitor_block_bot); // rmon: old expression stack bottom
    __ subptr(rsp, entry_size);         // move expression stack top
    __ subptr(rmon, entry_size);        // move expression stack bottom
    __ mov(rtop, rsp);                  // set start value for copy loop
    __ movptr(monitor_block_bot, rmon); // set new monitor block bottom
    __ jmp(entry);
    // 2. move expression stack contents
    __ bind(loop);
    __ movptr(rbot, Address(rtop, entry_size)); // load expression stack
                                                // word from old location
    __ movptr(Address(rtop, 0), rbot);          // and store it at new location
    __ addptr(rtop, wordSize);                  // advance to next word
    __ bind(entry);
    __ cmpptr(rtop, rmon);                      // check if bottom reached
    __ jcc(Assembler::notEqual, loop);          // if not at bottom then
                                                // copy next word
  }

  // call run-time routine
  // rmon: points to monitor entry
  __ bind(allocated);

  // Increment bcp to point to the next bytecode, so exception
  // handling for async. exceptions work correctly.
  // The object has already been poped from the stack, so the
  // expression stack looks correct.
  __ increment(rbcp);

```
store object, call [lock object](/docs/CS/Java/JDK/JVM/interpreter.md?id=lock_object)
```cpp
  __ movptr(Address(rmon, BasicObjectLock::obj_offset_in_bytes()), rax);
  __ lock_object(rmon);

  // check to make sure this monitor doesn't cause stack overflow after locking
  __ save_bcp();  // in case of exception
  __ generate_stack_overflow_check(0);

  // The bcp has already been incremented. Just need to dispatch to
  // next instruction.
  __ dispatch_next(vtos);
}
```

in bytecodeInterpreter
```cpp
// bytecodeInterpreter.cpp
CASE(_monitorenter): {
        oop lockee = STACK_OBJECT(-1);
        // derefing's lockee ought to provoke implicit null check
        CHECK_NULL(lockee);
        // find a free monitor or one already allocated for this object
        // if we find a matching object then we need a new monitor
        // since this is recursive enter
        BasicObjectLock* limit = istate->monitor_base();
        BasicObjectLock* most_recent = (BasicObjectLock*) istate->stack_base();
        BasicObjectLock* entry = NULL;
        while (most_recent != limit ) {
          if (most_recent->obj() == NULL) entry = most_recent;
          else if (most_recent->obj() == lockee) break;
          most_recent++;
        }
        if (entry != NULL) {
          entry->set_obj(lockee);
          int success = false;
          uintptr_t epoch_mask_in_place = (uintptr_t)markOopDesc::epoch_mask_in_place;

          markOop mark = lockee->mark();
          intptr_t hash = (intptr_t) markOopDesc::no_hash;
          // implies UseBiasedLocking
          if (mark->has_bias_pattern()) {
            uintptr_t thread_ident;
            uintptr_t anticipated_bias_locking_value;
            thread_ident = (uintptr_t)istate->thread();
            anticipated_bias_locking_value =
              (((uintptr_t)lockee->klass()->prototype_header() | thread_ident) ^ (uintptr_t)mark) &
              ~((uintptr_t) markOopDesc::age_mask_in_place);

            if  (anticipated_bias_locking_value == 0) {
              // already biased towards this thread, nothing to do
              if (PrintBiasedLockingStatistics) {
                (* BiasedLocking::biased_lock_entry_count_addr())++;
              }
              success = true;
            }
            else if ((anticipated_bias_locking_value & markOopDesc::biased_lock_mask_in_place) != 0) {
              // try revoke bias
              markOop header = lockee->klass()->prototype_header();
              if (hash != markOopDesc::no_hash) {
                header = header->copy_set_hash(hash);
              }
              if (lockee->cas_set_mark(header, mark) == mark) {
                if (PrintBiasedLockingStatistics)
                  (*BiasedLocking::revoked_lock_entry_count_addr())++;
              }
            }
            else if ((anticipated_bias_locking_value & epoch_mask_in_place) !=0) {
              // try rebias
              markOop new_header = (markOop) ( (intptr_t) lockee->klass()->prototype_header() | thread_ident);
              if (hash != markOopDesc::no_hash) {
                new_header = new_header->copy_set_hash(hash);
              }
              if (lockee->cas_set_mark(new_header, mark) == mark) {
                if (PrintBiasedLockingStatistics)
                  (* BiasedLocking::rebiased_lock_entry_count_addr())++;
              }
              else {
                CALL_VM(InterpreterRuntime::monitorenter(THREAD, entry), handle_exception);
              }
              success = true;
            }
            else {
              // try to bias towards thread in case object is anonymously biased
              markOop header = (markOop) ((uintptr_t) mark & ((uintptr_t)markOopDesc::biased_lock_mask_in_place |
                                                              (uintptr_t)markOopDesc::age_mask_in_place |
                                                              epoch_mask_in_place));
              if (hash != markOopDesc::no_hash) {
                header = header->copy_set_hash(hash);
              }
              markOop new_header = (markOop) ((uintptr_t) header | thread_ident);
              // debugging hint
              DEBUG_ONLY(entry->lock()->set_displaced_header((markOop) (uintptr_t) 0xdeaddead);)
              if (lockee->cas_set_mark(new_header, header) == header) {
                if (PrintBiasedLockingStatistics)
                  (* BiasedLocking::anonymously_biased_lock_entry_count_addr())++;
              }
              else {
                CALL_VM(InterpreterRuntime::monitorenter(THREAD, entry), handle_exception);
              }
              success = true;
            }
          }

          // traditional lightweight locking
          if (!success) {
            markOop displaced = lockee->mark()->set_unlocked();
            entry->lock()->set_displaced_header(displaced);
            bool call_vm = UseHeavyMonitors;
            if (call_vm || lockee->cas_set_mark((markOop)entry, displaced) != displaced) {
              // Is it simple recursive case?
              if (!call_vm && THREAD->is_lock_owned((address) displaced->clear_lock_bits())) {
                entry->lock()->set_displaced_header(NULL);
              } else {
                CALL_VM(InterpreterRuntime::monitorenter(THREAD, entry), handle_exception);
              }
            }
          }
          UPDATE_PC_AND_TOS_AND_CONTINUE(1, -1);
        } else {
          istate->set_msg(more_monitors);
          UPDATE_PC_AND_RETURN(0); // Re-execute
        }
      }
```


```cpp
//interpreterRuntime.cpp
//
// Synchronization
// The interpreter's synchronization code is factored out so that it can
// be shared by method invocation and synchronized blocks.
//%note synchronization_3

//%note monitor_1
IRT_ENTRY_NO_ASYNC(void, InterpreterRuntime::monitorenter(JavaThread* thread, BasicObjectLock* elem))
#ifdef ASSERT
  thread->last_frame().interpreter_frame_verify_monitor(elem);
#endif
  if (PrintBiasedLockingStatistics) {
    Atomic::inc(BiasedLocking::slow_path_entry_count_addr());
  }
  Handle h_obj(thread, elem->obj());
  assert(Universe::heap()->is_in_reserved_or_null(h_obj()),
         "must be NULL or an object");
  if (UseBiasedLocking) {
    // Retry fast entry if bias is revoked to avoid unnecessary inflation
    ObjectSynchronizer::fast_enter(h_obj, elem->lock(), true, CHECK);
  } else {
    ObjectSynchronizer::slow_enter(h_obj, elem->lock(), CHECK);
  }
  assert(Universe::heap()->is_in_reserved_or_null(elem->obj()),
         "must be NULL or an object");
#ifdef ASSERT
  thread->last_frame().interpreter_frame_verify_monitor(elem);
#endif
IRT_END
```

1. support Biased Lock, call `ObjectSynchronizer::fast_enter`
2. Or call `ObjectSynchronizer::slow_enter`, use light lock




### monitorexit

```cpp
// bytecodeInterpreter.cpp
CASE(_monitorexit): {
    oop lockee = STACK_OBJECT(-1);
    CHECK_NULL(lockee);
    // derefing's lockee ought to provoke implicit null check
    // find our monitor slot
    BasicObjectLock* limit = istate->monitor_base();
    BasicObjectLock* most_recent = (BasicObjectLock*) istate->stack_base();
    while (most_recent != limit ) {
      if ((most_recent)->obj() == lockee) {
        BasicLock* lock = most_recent->lock();
        markOop header = lock->displaced_header();
        most_recent->set_obj(NULL);
        if (!lockee->mark()->has_bias_pattern()) {
          bool call_vm = UseHeavyMonitors;
          // If it isn't recursive we either must swap old header or call the runtime
          if (header != NULL || call_vm) {
            markOop old_header = markOopDesc::encode(lock);
            if (call_vm || lockee->cas_set_mark(header, old_header) != old_header) {
              // restore object for the slow case
              most_recent->set_obj(lockee);
              CALL_VM(InterpreterRuntime::monitorexit(THREAD, most_recent), handle_exception);
            }
          }
        }
        UPDATE_PC_AND_TOS_AND_CONTINUE(1, -1);
      }
      most_recent++;
    }
    // Need to throw illegal monitor state exception
    CALL_VM(InterpreterRuntime::throw_illegal_monitor_state_exception(THREAD), handle_exception);
    ShouldNotReachHere();
  }
```


```cpp
// interpreterRuntime.cpp
IRT_ENTRY_NO_ASYNC(void, InterpreterRuntime::monitorexit(JavaThread* thread, BasicObjectLock* elem))
#ifdef ASSERT
  thread->last_frame().interpreter_frame_verify_monitor(elem);
#endif
  Handle h_obj(thread, elem->obj());
  assert(Universe::heap()->is_in_reserved_or_null(h_obj()),
         "must be NULL or an object");
  if (elem == NULL || h_obj()->is_unlocked()) {
    THROW(vmSymbols::java_lang_IllegalMonitorStateException());
  }
  ObjectSynchronizer::slow_exit(h_obj(), elem->lock(), thread);
  // Free entry. This must be done here, since a pending exception might be installed on
  // exit. If it is not cleared, the exception handling code will try to unlock the monitor again.
  elem->set_obj(NULL);
#ifdef ASSERT
  thread->last_frame().interpreter_frame_verify_monitor(elem);
#endif
IRT_END
```



### Biased Lock

```shell
-XX:+UseBiasedLocking # in JDK15 default close and in
-XX:BiasedLockingStartupDelay = 0 #default 5
-XX:BiasedLockingBulkRebiasThreshold = 20 # default 20
-XX:BiasedLockingBulkRevokeThreshold = 40 # default 40
-XX:BiasedLockingDecayTime = 25000 # default 25000 ms
```

[JEP 374: Disable and Deprecate Biased Locking](https://openjdk.java.net/jeps/374)

1. 偏向锁和重量级锁只用到了_obj字段，而轻量级锁用到了_displaced_header
2. 释放锁时都需要修改Lock Record 里的_obj字段。



`hashcode()` and `wait()` depend on monitor, so wil never use light lock directly after them completed,

批量重偏向是以class而不是对象为单位的，每个class会维护一个偏向锁的撤销计数器，每当该class的对象发生偏向锁的撤销时，该计数器会加一，当这个值达到默认阈值20时，jvm就会认为这个锁对象不再适合原线程，
因此进行批量重偏向。而距离上次批量重偏向的25秒内，如果撤销计数达到40，就会发生批量撤销，如果超过25秒，那么就会重置在[20, 40)内的计数。

```cpp
//basicLock.hpp
class BasicLock {  
  friend class VMStructs;
  friend class JVMCIVMStructs;
 private:
  volatile markOop _displaced_header;
 public:
  markOop      displaced_header() const               { return _displaced_header; }
  void         set_displaced_header(markOop header)   { _displaced_header = header; }

  void print_on(outputStream* st) const;

  // move a basic lock (used during deoptimization
  void move_to(oop obj, BasicLock* dest);

  static int displaced_header_offset_in_bytes()       { return offset_of(BasicLock, _displaced_header); }
};

// A BasicObjectLock associates a specific Java object with a BasicLock.
// It is currently embedded in an interpreter frame.

// Because some machines have alignment restrictions on the control stack,
// the actual space allocated by the interpreter may include padding words
// after the end of the BasicObjectLock.  Also, in order to guarantee
// alignment of the embedded BasicLock objects on such machines, we
// put the embedded BasicLock at the beginning of the struct.

class BasicObjectLock { // Lock Record
  friend class VMStructs;
 private:
  BasicLock _lock;                                    // the lock, must be double word aligned
  oop       _obj;                                     // object holds the lock;

 public:
  // Manipulation
  oop      obj() const                                { return _obj;  }
  void set_obj(oop obj)                               { _obj = obj; }
  BasicLock* lock()                                   { return &_lock; }

  // Note: Use frame::interpreter_frame_monitor_size() for the size of BasicObjectLocks
  //       in interpreter activation frames since it includes machine-specific padding.
  static int size()                                   { return sizeof(BasicObjectLock)/wordSize; }

  // GC support
  void oops_do(OopClosure* f) { f->do_oop(&_obj); }

  static int obj_offset_in_bytes()                    { return offset_of(BasicObjectLock, _obj);  }
  static int lock_offset_in_bytes()                   { return offset_of(BasicObjectLock, _lock); }
};
```



#### ObjectSynchronizer::fast_enter

**ObjectSynchronizer::fast_enter():**

1. check `if(UseBiasedLocking) `
    1. `if is_at_safepoint())`, invoke `BiasedLocking::revoke_at_safepoint()`
    2. Else invoke `BiasedLocking::revoke_and_rebias()` success, return
2. Others, `ObjectSynchronizer::slow_enter()`

```cpp
//synchronizer.cpp
void ObjectSynchronizer::fast_enter(Handle obj, BasicLock* lock, bool attempt_rebias, TRAPS) {
  if (UseBiasedLocking) { 
    if (!SafepointSynchronize::is_at_safepoint()) {
      BiasedLocking::Condition cond = BiasedLocking::revoke_and_rebias(obj, attempt_rebias, THREAD);
      if (cond == BiasedLocking::BIAS_REVOKED_AND_REBIASED) {
        return;
      }
    } else {
      assert(!attempt_rebias, "can not rebias toward VM thread");
      BiasedLocking::revoke_at_safepoint(obj);	//is_at_safepoint
    }
    assert(!obj->mark()->has_bias_pattern(), "biases should be revoked by now");
  }
  
  slow_enter(obj, lock, THREAD);
}
```



#### revoke and rebias

**must not be called while at safepoint**

use CAS

1. `Get markOop`
2.  `if (mark->is_biased_anonymously() && !attempt_rebias) `

```cpp
//biasedLocking.cpp
BiasedLocking::Condition BiasedLocking::revoke_and_rebias(Handle obj, bool attempt_rebias, TRAPS) {
  // We can revoke the biases of anonymously-biased objects
  // efficiently enough that we should not cause these revocations to
  // update the heuristics because doing so may cause unwanted bulk
  // revocations (which are expensive) to occur.
  markOop mark = obj->mark();
  if (mark->is_biased_anonymously() && !attempt_rebias) {
    // We are probably trying to revoke the bias of this object due to
    // an identity hash code computation. Try to revoke the bias
    // without a safepoint. This is possible if we can successfully
    // compare-and-exchange an unbiased header into the mark word of
    // the object, meaning that no other thread has raced to acquire
    // the bias of the object.
    markOop biased_value       = mark;
    markOop unbiased_prototype = markOopDesc::prototype()->set_age(mark->age());
    markOop res_mark = obj->cas_set_mark(unbiased_prototype, mark);
    if (res_mark == biased_value) {
      return BIAS_REVOKED;
    }
  } else if (mark->has_bias_pattern()) {
    Klass* k = obj->klass();
    markOop prototype_header = k->prototype_header();
    if (!prototype_header->has_bias_pattern()) {
      // This object has a stale bias from before the bulk revocation
      // for this data type occurred. It's pointless to update the
      // heuristics at this point so simply update the header with a
      // CAS. If we fail this race, the object's bias has been revoked
      // by another thread so we simply return and let the caller deal
      // with it.
      markOop biased_value       = mark;
      markOop res_mark = obj->cas_set_mark(prototype_header, mark);
      assert(!obj->mark()->has_bias_pattern(), "even if we raced, should still be revoked");
      return BIAS_REVOKED;
    } else if (prototype_header->bias_epoch() != mark->bias_epoch()) {
      // The epoch of this biasing has expired indicating that the
      // object is effectively unbiased. Depending on whether we need
      // to rebias or revoke the bias of this object we can do it
      // efficiently enough with a CAS that we shouldn't update the
      // heuristics. This is normally done in the assembly code but we
      // can reach this point due to various points in the runtime
      // needing to revoke biases.
      if (attempt_rebias) {
        assert(THREAD->is_Java_thread(), "");
        markOop biased_value       = mark;
        markOop rebiased_prototype = markOopDesc::encode((JavaThread*) THREAD, mark->age(), prototype_header->bias_epoch());
        markOop res_mark = obj->cas_set_mark(rebiased_prototype, mark);
        if (res_mark == biased_value) {
          return BIAS_REVOKED_AND_REBIASED;
        }
      } else {
        markOop biased_value       = mark;
        markOop unbiased_prototype = markOopDesc::prototype()->set_age(mark->age());
        markOop res_mark = obj->cas_set_mark(unbiased_prototype, mark);
        if (res_mark == biased_value) {
          return BIAS_REVOKED;
        }
      }
    }
  }

  HeuristicsResult heuristics = update_heuristics(obj(), attempt_rebias);
  if (heuristics == HR_NOT_BIASED) {
    return NOT_BIASED;
  } else if (heuristics == HR_SINGLE_REVOKE) {
    Klass *k = obj->klass();
    markOop prototype_header = k->prototype_header();
    if (mark->biased_locker() == THREAD &&
        prototype_header->bias_epoch() == mark->bias_epoch()) {
      // A thread is trying to revoke the bias of an object biased
      // toward it, again likely due to an identity hash code
      // computation. We can again avoid a safepoint in this case
      // since we are only going to walk our own stack. There are no
      // races with revocations occurring in other threads because we
      // reach no safepoints in the revocation path.
      // Also check the epoch because even if threads match, another thread
      // can come in with a CAS to steal the bias of an object that has a
      // stale epoch.
      ResourceMark rm;
      log_info(biasedlocking)("Revoking bias by walking my own stack:");
      EventBiasedLockSelfRevocation event;
      BiasedLocking::Condition cond = revoke_bias(obj(), false, false, (JavaThread*) THREAD, NULL);
      ((JavaThread*) THREAD)->set_cached_monitor_info(NULL);
      assert(cond == BIAS_REVOKED, "why not?");
      if (event.should_commit()) {
        post_self_revocation_event(&event, k);
      }
      return cond;
    } else {
      EventBiasedLockRevocation event;
      VM_RevokeBias revoke(&obj, (JavaThread*) THREAD);
      VMThread::execute(&revoke);
      if (event.should_commit() && revoke.status_code() != NOT_BIASED) {
        post_revocation_event(&event, k, &revoke);
      }
      return revoke.status_code();
    }
  }

  assert((heuristics == HR_BULK_REVOKE) ||
         (heuristics == HR_BULK_REBIAS), "?");
  EventBiasedLockClassRevocation event;
  VM_BulkRevokeBias bulk_revoke(&obj, (JavaThread*) THREAD,
                                (heuristics == HR_BULK_REBIAS),
                                attempt_rebias);
  VMThread::execute(&bulk_revoke);
  if (event.should_commit()) {
    post_class_revocation_event(&event, obj->klass(), heuristics != HR_BULK_REBIAS);
  }
  return bulk_revoke.status_code();
}
```



#### revoke bias

BiasedLocking::revoke_at_safepoint must only be called while at safepoint, so don't need CAS.

update_heuristics:

 Heuristics to attempt to throttle the number of revocations.
 Stages:

 1. Revoke the biases of all objects in the heap of this type,    but allow rebiasing of those objects if unlocked.
  2. Revoke the biases of all objects in the heap of this type   and don't allow rebiasing of these objects. Disable  allocation of objects of that type with the bias bit set.

```cpp
//biasedLocking.cpp
void BiasedLocking::revoke_at_safepoint(Handle h_obj) {
  assert(SafepointSynchronize::is_at_safepoint(), "must only be called while at safepoint");
  oop obj = h_obj();
  HeuristicsResult heuristics = update_heuristics(obj, false);//
  if (heuristics == HR_SINGLE_REVOKE) {
    revoke_bias(obj, false, false, NULL, NULL);
  } else if ((heuristics == HR_BULK_REBIAS) ||
             (heuristics == HR_BULK_REVOKE)) {
    bulk_revoke_or_rebias_at_safepoint(obj, (heuristics == HR_BULK_REBIAS), false, NULL);
  }
  clean_up_cached_monitor_info();
}

enum HeuristicsResult {
  HR_NOT_BIASED    = 1,
  HR_SINGLE_REVOKE = 2,
  HR_BULK_REBIAS   = 3,
  HR_BULK_REVOKE   = 4
};
```

1. 首先，暂停拥有偏向锁的线程，然后检查偏向锁的线程是否为存活状态
2. 如果线程已经死了，直接把对象头设置为无锁状态
3. 如果还活着，当达到全局安全点时获得偏向锁的线程会被挂起，接着偏向锁升级为轻量级锁，然后唤醒被阻塞在全局安全点的线程继续往下执行同步代码

    JVM内部为每个类维护了一个偏向锁revoke计数器，对偏向锁撤销进行计数，当这个值达到指定阈值时，JVM会认为这个类的偏向锁有问题，需要重新偏向(rebias),对所有属于这个类的对象进行重偏向的操作成为 批量重偏向(bulk rebias)。
    在做bulk rebias时，会对这个类的epoch的值做递增，这个epoch会存储在对象头中的epoch字段。在判断这个对象是否获得偏向锁的条件是:MarkWord的 biased_lock:1、lock:01、threadid和当前线程id相等、epoch字段和所属类的epoch值相同，如果epoch的值不一样，要么就是撤销偏向锁、要么就是rebias； 如果这个类的revoke计数器的值继续增加到一个阈值，那么jvm会认为这个类不适合偏向锁，就需要进行bulk revoke操作 

### Lightweight Lock

Displaced Mark Word = 25 hashcode + 4 age + 1 biased flag
Mark Word = pointer to Displaced Mark Word

#### ObjectSynchronizer::slow_enter
1. is_neutral, cas set mark
2. has_locker, set_displaced_header
3. [ObjectSynchronizer::inflate](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=inflate) then [ObjectMonitor::enter](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=ObjectMonitorenter)

```cpp
// synchronizer.cpp
void ObjectSynchronizer::slow_enter(Handle obj, BasicLock* lock, TRAPS) {
  markOop mark = obj->mark();
  assert(!mark->has_bias_pattern(), "should not see bias pattern here");

  if (mark->is_neutral()) {
    // Anticipate successful CAS -- the ST of the displaced mark must
    // be visible <= the ST performed by the CAS.
    lock->set_displaced_header(mark);
    if (mark == obj()->cas_set_mark((markOop) lock, mark)) {
      return;
    }
    // Fall through to inflate() ...
  } else if (mark->has_locker() &&
             THREAD->is_lock_owned((address)mark->locker())) {
    assert(lock != mark->locker(), "must not re-lock the same lock");
    assert(lock != (BasicLock*)obj->mark(), "don't relock with same BasicLock");
    lock->set_displaced_header(NULL);
    return;
  }

  // The object header will never be displaced to this lock,
  // so it does not matter what the value is, except that it
  // must be non-zero to avoid looking like a re-entrant lock,
  // and must not look locked either.
  lock->set_displaced_header(markOopDesc::unused_mark());
  ObjectSynchronizer::inflate(THREAD,
                              obj(),
                              inflate_cause_monitor_enter)->enter(THREAD);
}
```



#### Unlock




#### ObjectSynchronizer::slow_exit

We take the slow-path of **possible inflation** and then exit. -- see `ObjectSynchronizer::inflate()`

```cpp
// synchronizer.cpp
void ObjectSynchronizer::slow_exit(oop object, BasicLock* lock, TRAPS) {
  fast_exit (object, lock, THREAD) ;
}


void ObjectSynchronizer::fast_exit(oop object, BasicLock* lock, TRAPS) {
  markOop mark = object->mark();
  // We cannot check for Biased Locking if we are racing an inflation.
  assert(mark == markOopDesc::INFLATING() ||
         !mark->has_bias_pattern(), "should not see bias pattern here");

  markOop dhw = lock->displaced_header();
  if (dhw == NULL) {
    // If the displaced header is NULL, then this exit matches up with
    // a recursive enter. No real work to do here except for diagnostics.
    #ifndef PRODUCT
    if (mark != markOopDesc::INFLATING()) {
      // Only do diagnostics if we are not racing an inflation. Simply
      // exiting a recursive enter of a Java Monitor that is being
      // inflated is safe; see the has_monitor() comment below.
      assert(!mark->is_neutral(), "invariant");
      assert(!mark->has_locker() ||
             THREAD->is_lock_owned((address)mark->locker()), "invariant");
      if (mark->has_monitor()) {
        // The BasicLock's displaced_header is marked as a recursive
        // enter and we have an inflated Java Monitor (ObjectMonitor).
        // This is a special case where the Java Monitor was inflated
        // after this thread entered the stack-lock recursively. When a
        // Java Monitor is inflated, we cannot safely walk the Java
        // Monitor owner's stack and update the BasicLocks because a
        // Java Monitor can be asynchronously inflated by a thread that
        // does not own the Java Monitor.
        ObjectMonitor * m = mark->monitor();
        assert(((oop)(m->object()))->mark() == mark, "invariant");
        assert(m->is_entered(THREAD), "invariant");
      }
    }
    #endif
    return;
  }

  if (mark == (markOop) lock) {
    // If the object is stack-locked by the current thread, try to
    // swing the displaced header from the BasicLock back to the mark.
    assert(dhw->is_neutral(), "invariant");
    if (object->cas_set_mark(dhw, mark) == mark) {
      return;
    }
  }

  // We have to take the slow-path of possible inflation and then exit.
  ObjectSynchronizer::inflate(THREAD,
                              object,
                              inflate_cause_vm_internal)->exit(true, THREAD);
}
```



### Heavyweight Lock

#### ObjectMonitor

The ObjectMonitor class implements the heavyweight version of a JavaMonitor.
The lightweight BasicLock/stack lock version has been inflated into an ObjectMonitor.
This inflation is typically due to contention or use of [Object.wait()](/docs/CS/Java/JDK/Concurrency/Thread.md?id=wait).


Only onDeck, owner and threads not in cxq can get Lock.
Owner move other threads to onDeck from EntryList, and move cxq into EntryList.

WaitSet -> cxq

```cpp

class ObjectMonitor : public CHeapObj<mtInternal> {
  friend class ObjectSynchronizer;
  friend class ObjectWaiter;


  // The sync code expects the header field to be at offset zero (0).
  // Enforced by the assert() in header_addr().
  volatile markWord _header;        // displaced object header word - mark
  WeakHandle _object;               // backward object pointer
  // Separate _header and _owner on different cache lines since both can
  // have busy multi-threaded access. _header and _object are set at initial
  // inflation. The _object does not change, so it is a good choice to share
  // its cache line with _header.
  DEFINE_PAD_MINUS_SIZE(0, OM_CACHE_LINE_SIZE, sizeof(volatile markWord) +
                        sizeof(WeakHandle));
  // Used by async deflation as a marker in the _owner field:
  #define DEFLATER_MARKER reinterpret_cast<void*>(-1)
  void* volatile _owner;            // pointer to owning thread OR BasicLock
  volatile uint64_t _previous_owner_tid;  // thread id of the previous owner of the monitor
  // Separate _owner and _next_om on different cache lines since
  // both can have busy multi-threaded access. _previous_owner_tid is only
  // changed by ObjectMonitor::exit() so it is a good choice to share the
  // cache line with _owner.
  DEFINE_PAD_MINUS_SIZE(1, OM_CACHE_LINE_SIZE, sizeof(void* volatile) +
                        sizeof(volatile uint64_t));
  ObjectMonitor* _next_om;          // Next ObjectMonitor* linkage
  volatile intx _recursions;        // recursion count, 0 for first entry
  ObjectWaiter* volatile _EntryList;  // Threads blocked on entry or reentry.
                                      // The list is actually composed of WaitNodes,
                                      // acting as proxies for Threads.

  ObjectWaiter* volatile _cxq;      // LL of recently-arrived threads blocked on entry.
  JavaThread* volatile _succ;       // Heir presumptive thread - used for futile wakeup throttling
  JavaThread* volatile _Responsible;

  volatile int _Spinner;            // for exit->spinner handoff optimization
  volatile int _SpinDuration;

  int _contentions;                 // Number of active contentions in enter(). It is used by is_busy()
                                    // along with other fields to determine if an ObjectMonitor can be
                                    // deflated. It is also used by the async deflation protocol. See
                                    // ObjectMonitor::deflate_monitor().
 protected:
  ObjectWaiter* volatile _WaitSet;  // LL of threads wait()ing on the monitor
  volatile int  _waiters;           // number of waiting threads
 private:
  volatile int _WaitSetLock;        // protects Wait Queue - simple spinlock
}
```

ObjectMonitor Layout Overview/Highlights/Restrictions:

- The _header field must be at offset 0 because the displaced header
  from markWord is stored there. We do not want markWord.hpp to include
  ObjectMonitor.hpp to avoid exposing ObjectMonitor everywhere. This
  means that ObjectMonitor cannot inherit from any other class nor can
  it use any virtual member functions. This restriction is critical to
  the proper functioning of the VM.
- The _header and _owner fields should be separated by enough space
  to avoid false sharing due to parallel access by different threads.
  This is an advisory recommendation.
- The general layout of the fields in ObjectMonitor is:
    _header
    <lightly_used_fields>
    <optional padding>
    _owner
    <remaining_fields>
- The VM assumes write ordering and machine word alignment with
  respect to the _owner field and the <remaining_fields> that can
  be read in parallel by other threads.
- Generally fields that are accessed closely together in time should
  be placed proximally in space to promote data cache locality. That
  is, temporal locality should condition spatial locality.
- We have to balance avoiding false sharing with excessive invalidation
  from coherence traffic. As such, we try to cluster fields that tend
  to be _written_ at approximately the same time onto the same data
  cache line.
- We also have to balance the natural tension between minimizing
  single threaded capacity misses with excessive multi-threaded
  coherency misses. There is no single optimal layout for both
  single-threaded and multi-threaded environments.

- See TEST_VM(ObjectMonitor, sanity) gtest for how critical restrictions are enforced.
- Adjacent ObjectMonitors should be separated by enough space to avoid
  false sharing. This is handled by the ObjectMonitor allocation code
  in synchronizer.cpp. Also see TEST_VM(SynchronizerTest, sanity) gtest.


Futures notes:
  - Separating _owner from the <remaining_fields> by enough space to avoid false sharing might be profitable. 
    The CAS in monitorenter will invalidate the line underlying _owner. 
    We want to avoid an L1 data cache miss on that same line for monitorexit. 
    Putting these <remaining_fields>:
    _recursions, _EntryList, _cxq, and _succ, all of which may be fetched in the inflated unlock path, on a different cache line would make them immune to CAS-based invalidation from the _owner field.

  - The _recursions field should be of type int, or int32_t but not intptr_t. There's no reason to use a 64-bit type for this field in a 64-bit JVM.



ContentionList LIFO Lock-Free
only Owner thread can get elements from tail
insert into head by CAS

Owner thread move elements from ContentionList to EntryList and set Ready(OnDeck) of a element from EntryList(usually head)

OnDeck thread change to Owner thread when get lock, 
or still in EntryList

if Owner thread block by wait, then to WaitSet and wait for notify/notifyAll/interrupt then to EntryList

spin lock before insert into EntryList



#### inflate

1. in loop
2. Get Mark Word
3. if has_monitor, return
4. If markOopDesc::INFLATING, continue loop until has_monitor
5. if `has_locker`(`Light Lock`), CAS set mark = markOopDesc:INFLATING, _owner = Lock Record
6. Else non-lock, CAS set mark = markOopDesc:INFLATING, _owner = NULL

`ObjectSynchronizer::inflate` just get monitor
lock operation in `ObjectMonitor::enter`


```cpp
// synchronizer.cpp
ObjectMonitor* ObjectSynchronizer::inflate(Thread * Self,
                                                     oop object,
                                                     const InflateCause cause) {

  // Inflate mutates the heap ...
  // Relaxing assertion for bug 6320749.
  assert(Universe::verify_in_progress() ||
         !SafepointSynchronize::is_at_safepoint(), "invariant");

  EventJavaMonitorInflate event;

  for (;;) {
    const markOop mark = object->mark();
    assert(!mark->has_bias_pattern(), "invariant");

    // The mark can be in one of the following states:
    // *  Inflated     - just return
    // *  Stack-locked - coerce it to inflated
    // *  INFLATING    - busy wait for conversion to complete
    // *  Neutral      - aggressively inflate the object.
    // *  BIASED       - Illegal.  We should never see this

    // CASE: inflated
    if (mark->has_monitor()) { // already has monitor
      ObjectMonitor * inf = mark->monitor();
      assert(inf->header()->is_neutral(), "invariant");
      assert(oopDesc::equals((oop) inf->object(), object), "invariant");
      assert(ObjectSynchronizer::verify_objmon_isinpool(inf), "monitor is invalid");
      return inf;
    }

    // CASE: inflation in progress - inflating over a stack-lock.
    // Some other thread is converting from stack-locked to inflated.
    // Only that thread can complete inflation -- other threads must wait.
    // The INFLATING value is transient.
    // Currently, we spin/yield/park and poll the markword, waiting for inflation to finish.
    // We could always eliminate polling by parking the thread on some auxiliary list.
    if (mark == markOopDesc::INFLATING()) {
      ReadStableMark(object);
      continue;
    }

    // CASE: stack-locked
    // Could be stack-locked either by this thread or by some other thread.
    //
    // Note that we allocate the objectmonitor speculatively, _before_ attempting
    // to install INFLATING into the mark word.  We originally installed INFLATING,
    // allocated the objectmonitor, and then finally STed the address of the
    // objectmonitor into the mark.  This was correct, but artificially lengthened
    // the interval in which INFLATED appeared in the mark, thus increasing
    // the odds of inflation contention.
    //
    // We now use per-thread private objectmonitor free lists.
    // These list are reprovisioned from the global free list outside the
    // critical INFLATING...ST interval.  A thread can transfer
    // multiple objectmonitors en-mass from the global free list to its local free list.
    // This reduces coherency traffic and lock contention on the global free list.
    // Using such local free lists, it doesn't matter if the omAlloc() call appears
    // before or after the CAS(INFLATING) operation.
    // See the comments in omAlloc().

    if (mark->has_locker()) {
      ObjectMonitor * m = omAlloc(Self); // allocate monitor
      // Optimistically prepare the objectmonitor - anticipate successful CAS
      // We do this before the CAS in order to minimize the length of time
      // in which INFLATING appears in the mark.
      m->Recycle();
      m->_Responsible  = NULL;
      m->_recursions   = 0;
      m->_SpinDuration = ObjectMonitor::Knob_SpinLimit;   // Consider: maintain by type/class

      markOop cmp = object->cas_set_mark(markOopDesc::INFLATING(), mark);
      if (cmp != mark) {
        omRelease(Self, m, true);
        continue;       // Interference -- just retry
      }

      // We've successfully installed INFLATING (0) into the mark-word.
      // This is the only case where 0 will appear in a mark-word.
      // Only the singular thread that successfully swings the mark-word
      // to 0 can perform (or more precisely, complete) inflation.
      //
      // Why do we CAS a 0 into the mark-word instead of just CASing the
      // mark-word from the stack-locked value directly to the new inflated state?
      // Consider what happens when a thread unlocks a stack-locked object.
      // It attempts to use CAS to swing the displaced header value from the
      // on-stack basiclock back into the object header.  Recall also that the
      // header value (hashcode, etc) can reside in (a) the object header, or
      // (b) a displaced header associated with the stack-lock, or (c) a displaced
      // header in an objectMonitor.  The inflate() routine must copy the header
      // value from the basiclock on the owner's stack to the objectMonitor, all
      // the while preserving the hashCode stability invariants.  If the owner
      // decides to release the lock while the value is 0, the unlock will fail
      // and control will eventually pass from slow_exit() to inflate.  The owner
      // will then spin, waiting for the 0 value to disappear.   Put another way,
      // the 0 causes the owner to stall if the owner happens to try to
      // drop the lock (restoring the header from the basiclock to the object)
      // while inflation is in-progress.  This protocol avoids races that might
      // would otherwise permit hashCode values to change or "flicker" for an object.
      // Critically, while object->mark is 0 mark->displaced_mark_helper() is stable.
      // 0 serves as a "BUSY" inflate-in-progress indicator.


      // fetch the displaced mark from the owner's stack.
      // The owner can't die or unwind past the lock while our INFLATING
      // object is in the mark.  Furthermore the owner can't complete
      // an unlock on the object, either.
      markOop dmw = mark->displaced_mark_helper();
      assert(dmw->is_neutral(), "invariant");

      // Setup monitor fields to proper values -- prepare the monitor
      m->set_header(dmw);

      // Optimization: if the mark->locker stack address is associated
      // with this thread we could simply set m->_owner = Self.
      // Note that a thread can inflate an object
      // that it has stack-locked -- as might happen in wait() -- directly
      // with CAS.  That is, we can avoid the xchg-NULL .... ST idiom.
      m->set_owner(mark->locker());
      m->set_object(object);
      // TODO-FIXME: assert BasicLock->dhw != 0.

      // Must preserve store ordering. The monitor state must
      // be stable at the time of publishing the monitor address.
      guarantee(object->mark() == markOopDesc::INFLATING(), "invariant");
      object->release_set_mark(markOopDesc::encode(m));

      // Hopefully the performance counters are allocated on distinct cache lines
      // to avoid false sharing on MP systems ...
      OM_PERFDATA_OP(Inflations, inc());
      if (log_is_enabled(Debug, monitorinflation)) {
        if (object->is_instance()) {
          ResourceMark rm;
          log_debug(monitorinflation)("Inflating object " INTPTR_FORMAT " , mark " INTPTR_FORMAT " , type %s",
                                      p2i(object), p2i(object->mark()),
                                      object->klass()->external_name());
        }
      }
      if (event.should_commit()) {
        post_monitor_inflate_event(&event, object, cause);
      }
      return m;
    }

    // CASE: neutral
    // TODO-FIXME: for entry we currently inflate and then try to CAS _owner.
    // If we know we're inflating for entry it's better to inflate by swinging a
    // pre-locked objectMonitor pointer into the object header.   A successful
    // CAS inflates the object *and* confers ownership to the inflating thread.
    // In the current implementation we use a 2-step mechanism where we CAS()
    // to inflate and then CAS() again to try to swing _owner from NULL to Self.
    // An inflateTry() method that we could call from fast_enter() and slow_enter()
    // would be useful.

    assert(mark->is_neutral(), "invariant");
    ObjectMonitor * m = omAlloc(Self);
    // prepare m for installation - set monitor to initial state
    m->Recycle();
    m->set_header(mark);
    m->set_owner(NULL);
    m->set_object(object);
    m->_recursions   = 0;
    m->_Responsible  = NULL;
    m->_SpinDuration = ObjectMonitor::Knob_SpinLimit;       // consider: keep metastats by type/class

    if (object->cas_set_mark(markOopDesc::encode(m), mark) != mark) {
      m->set_object(NULL);
      m->set_owner(NULL);
      m->Recycle();
      omRelease(Self, m, true);
      m = NULL;
      continue;
      // interference - the markword changed - just retry.
      // The state-transitions are one-way, so there's no chance of
      // live-lock -- "Inflated" is an absorbing state.
    }

    // Hopefully the performance counters are allocated on distinct
    // cache lines to avoid false sharing on MP systems ...
    OM_PERFDATA_OP(Inflations, inc());
    if (log_is_enabled(Debug, monitorinflation)) {
      if (object->is_instance()) {
        ResourceMark rm;
        log_debug(monitorinflation)("Inflating object " INTPTR_FORMAT " , mark " INTPTR_FORMAT " , type %s",
                                    p2i(object), p2i(object->mark()),
                                    object->klass()->external_name());
      }
    }
    if (event.should_commit()) {
      post_monitor_inflate_event(&event, object, cause);
    }
    return m;
  }
}
```


#### ObjectMonitor::enter

1. CAS set  _owner = cur Thread success, return
2. If recursion,  _recursions++
3. if Self is_lock_owned，set _recursions = 1， _owner = Self
4. Else trySpin -- Adaptive Spinning Support
5. EnterI in loop

```cpp
// objectMonitor.cpp
void ObjectMonitor::enter(TRAPS) {
  // The following code is ordered to check the most common cases first
  // and to reduce RTS->RTO cache line upgrades on SPARC and IA32 processors.
  Thread * const Self = THREAD;

  void * cur = Atomic::cmpxchg(Self, &_owner, (void*)NULL);//cas
  if (cur == NULL) {
    // Either ASSERT _recursions == 0 or explicitly set _recursions = 0.
    assert(_recursions == 0, "invariant");
    assert(_owner == Self, "invariant");
    return;
  }

  if (cur == Self) {//if recursion
    // TODO-FIXME: check for integer overflow!  BUGID 6557169.
    _recursions++;
    return;
  }

  if (Self->is_lock_owned ((address)cur)) {
    assert(_recursions == 0, "internal state error");
    _recursions = 1;
    // Commute owner from a thread-specific on-stack BasicLockObject address to
    // a full-fledged "Thread *".
    _owner = Self;
    return;
  }

  // We've encountered genuine contention.
  assert(Self->_Stalled == 0, "invariant");
  Self->_Stalled = intptr_t(this);

  // Try one round of spinning *before* enqueueing Self
  // and before going through the awkward and expensive state
  // transitions.  The following spin is strictly optional ...
  // Note that if we acquire the monitor from an initial spin
  // we forgo posting JVMTI events and firing DTRACE probes.
  if (TrySpin(Self) > 0) {
    assert(_owner == Self, "invariant");
    assert(_recursions == 0, "invariant");
    assert(((oop)(object()))->mark() == markOopDesc::encode(this), "invariant");
    Self->_Stalled = 0;
    return;
  }

  assert(_owner != Self, "invariant");
  assert(_succ != Self, "invariant");
  assert(Self->is_Java_thread(), "invariant");
  JavaThread * jt = (JavaThread *) Self;
  assert(!SafepointSynchronize::is_at_safepoint(), "invariant");
  assert(jt->thread_state() != _thread_blocked, "invariant");
  assert(this->object() != NULL, "invariant");
  assert(_count >= 0, "invariant");

  // Prevent deflation at STW-time.  See deflate_idle_monitors() and is_busy().
  // Ensure the object-monitor relationship remains stable while there's contention.
  Atomic::inc(&_count);

  JFR_ONLY(JfrConditionalFlushWithStacktrace<EventJavaMonitorEnter> flush(jt);)
  EventJavaMonitorEnter event;
  if (event.should_commit()) {
    event.set_monitorClass(((oop)this->object())->klass());
    event.set_address((uintptr_t)(this->object_addr()));
  }

  { // Change java thread status to indicate blocked on monitor enter.
    JavaThreadBlockedOnMonitorEnterState jtbmes(jt, this);

    Self->set_current_pending_monitor(this);

    DTRACE_MONITOR_PROBE(contended__enter, this, object(), jt);
    if (JvmtiExport::should_post_monitor_contended_enter()) {
      JvmtiExport::post_monitor_contended_enter(jt, this);

      // The current thread does not yet own the monitor and does not
      // yet appear on any queues that would get it made the successor.
      // This means that the JVMTI_EVENT_MONITOR_CONTENDED_ENTER event
      // handler cannot accidentally consume an unpark() meant for the
      // ParkEvent associated with this ObjectMonitor.
    }

    OSThreadContendState osts(Self->osthread());
    ThreadBlockInVM tbivm(jt);

    // TODO-FIXME: change the following for(;;) loop to straight-line code.
    for (;;) {
      jt->set_suspend_equivalent();
      // cleared by handle_special_suspend_equivalent_condition()
      // or java_suspend_self()

      EnterI(THREAD);

      if (!ExitSuspendEquivalent(jt)) break;

      // We have acquired the contended monitor, but while we were
      // waiting another thread suspended us. We don't want to enter
      // the monitor while suspended because that would surprise the
      // thread that suspended us.
      //
      _recursions = 0;
      _succ = NULL;
      exit(false, Self);

      jt->java_suspend_self();
    }
    Self->set_current_pending_monitor(NULL);

    // We cleared the pending monitor info since we've just gotten past
    // the enter-check-for-suspend dance and we now own the monitor free
    // and clear, i.e., it is no longer pending. The ThreadBlockInVM
    // destructor can go to a safepoint at the end of this block. If we
    // do a thread dump during that safepoint, then this thread will show
    // as having "-locked" the monitor, but the OS and java.lang.Thread
    // states will still report that the thread is blocked trying to
    // acquire it.
  }

  Atomic::dec(&_count);
  assert(_count >= 0, "invariant");
  Self->_Stalled = 0;

  // Must either set _recursions = 0 or ASSERT _recursions == 0.
  assert(_recursions == 0, "invariant");
  assert(_owner == Self, "invariant");
  assert(_succ != Self, "invariant");
  assert(((oop)(object()))->mark() == markOopDesc::encode(this), "invariant");

  // The thread -- now the owner -- is back in vm mode.
  // Report the glorious news via TI,DTrace and jvmstat.
  // The probe effect is non-trivial.  All the reportage occurs
  // while we hold the monitor, increasing the length of the critical
  // section.  Amdahl's parallel speedup law comes vividly into play.
  //
  // Another option might be to aggregate the events (thread local or
  // per-monitor aggregation) and defer reporting until a more opportune
  // time -- such as next time some thread encounters contention but has
  // yet to acquire the lock.  While spinning that thread could
  // spinning we could increment JVMStat counters, etc.

  DTRACE_MONITOR_PROBE(contended__entered, this, object(), jt);
  if (JvmtiExport::should_post_monitor_contended_entered()) {
    JvmtiExport::post_monitor_contended_entered(jt, this);

    // The current thread already owns the monitor and is not going to
    // call park() for the remainder of the monitor enter protocol. So
    // it doesn't matter if the JVMTI_EVENT_MONITOR_CONTENDED_ENTERED
    // event handler consumed an unpark() issued by the thread that
    // just exited the monitor.
  }
  if (event.should_commit()) {
    event.set_previousOwner((uintptr_t)_previous_owner_tid);
    event.commit();
  }
  OM_PERFDATA_OP(ContendedLockAttempts, inc());
}
```

#### ObjectMonitor::EnterI

1. tryLock
2. trySpin
3. wrap to node add push "Self" onto **the front of the _cxq(ContentionList)**
4. tryLock and trySpin in a loop with [ParkEvent](/docs/CS/Java/JDK/Concurrency/Parker.md?id=ParkEvent)
   1. if tryLock and trySpin fail, park self
   2. unpark in exit by other Thread
5. Unlink Self from the cxq or EntryList.

```cpp
   void ObjectMonitor::EnterI(TRAPS) {
     Thread * const Self = THREAD;
     assert(Self->is_Java_thread(), "invariant");
     assert(((JavaThread *) Self)->thread_state() == _thread_blocked, "invariant");
   
     // Try the lock - TATAS
     if (TryLock (Self) > 0) {
       assert(_succ != Self, "invariant");
       assert(_owner == Self, "invariant");
       assert(_Responsible != Self, "invariant");
       return;
     }
   
     assert(InitDone, "Unexpectedly not initialized");
   
     // We try one round of spinning *before* enqueueing Self.
     //
     // If the _owner is ready but OFFPROC we could use a YieldTo()
     // operation to donate the remainder of this thread's quantum
     // to the owner.  This has subtle but beneficial affinity
     // effects.
   
     if (TrySpin(Self) > 0) {
       assert(_owner == Self, "invariant");
       assert(_succ != Self, "invariant");
       assert(_Responsible != Self, "invariant");
       return;
     }
   
     // The Spin failed -- Enqueue and park the thread ...
     assert(_succ != Self, "invariant");
     assert(_owner != Self, "invariant");
     assert(_Responsible != Self, "invariant");
   
     // Enqueue "Self" on ObjectMonitor's _cxq.
     //
     // Node acts as a proxy for Self.
     // As an aside, if were to ever rewrite the synchronization code mostly
     // in Java, WaitNodes, ObjectMonitors, and Events would become 1st-class
     // Java objects.  This would avoid awkward lifecycle and liveness issues,
     // as well as eliminate a subset of ABA issues.
     // TODO: eliminate ObjectWaiter and enqueue either Threads or Events.
   
     ObjectWaiter node(Self);
     Self->_ParkEvent->reset();
     node._prev   = (ObjectWaiter *) 0xBAD;
     node.TState  = ObjectWaiter::TS_CXQ;
   
     // Push "Self" onto the front of the _cxq.
     // Once on cxq/EntryList, Self stays on-queue until it acquires the lock.
     // Note that spinning tends to reduce the rate at which threads
     // enqueue and dequeue on EntryList|cxq.
     ObjectWaiter * nxt;
     for (;;) {
       node._next = nxt = _cxq;
       if (Atomic::cmpxchg(&node, &_cxq, nxt) == nxt) break;
   
       // Interference - the CAS failed because _cxq changed.  Just retry.
       // As an optional optimization we retry the lock.
       if (TryLock (Self) > 0) {
         assert(_succ != Self, "invariant");
         assert(_owner == Self, "invariant");
         assert(_Responsible != Self, "invariant");
         return;
       }
     }
```    
Check for cxq|EntryList edge transition to non-null.  This indicates
the onset of contention.  While contention persists exiting threads
will use a ST:MEMBAR:LD 1-1 exit protocol.  When contention abates exit
operations revert to the faster 1-0 mode.  This enter operation may interleave
(race) a concurrent 1-0 exit operation, resulting in stranding, so we
arrange for one of the contending thread to use a timed park() operations
to detect and recover from the race.  (Stranding is form of progress failure
where the monitor is unlocked but all the contending threads remain parked).
That is, at least one of the contended threads will periodically poll _owner.
One of the contending threads will become the designated "Responsible" thread.
The Responsible thread uses a timed park instead of a normal indefinite park
operation -- it periodically wakes and checks for and recovers from potential
strandings admitted by 1-0 exit operations.   We need at most one Responsible
thread per-monitor at any given moment.  Only threads on cxq|EntryList may
be responsible for a monitor.

Currently, one of the contended threads takes on the added role of "Responsible".
A viable alternative would be to use a dedicated "stranding checker" thread
that periodically iterated over all the threads (or active monitors) and unparked
successors where there was risk of stranding.  This would help eliminate the
timer scalability issues we see on some platforms as we'd only have one thread
-- the checker -- parked on a timer.

```cpp   
     if (nxt == NULL && _EntryList == NULL) {
       // Try to assume the role of responsible thread for the monitor.
       // CONSIDER:  ST vs CAS vs { if (Responsible==null) Responsible=Self }
       Atomic::replace_if_null(Self, &_Responsible);
     }
   
     // The lock might have been released while this thread was occupied queueing
     // itself onto _cxq.  To close the race and avoid "stranding" and
     // progress-liveness failure we must resample-retry _owner before parking.
     // Note the Dekker/Lamport duality: ST cxq; MEMBAR; LD Owner.
     // In this case the ST-MEMBAR is accomplished with CAS().
     //
     // TODO: Defer all thread state transitions until park-time.
     // Since state transitions are heavy and inefficient we'd like
     // to defer the state transitions until absolutely necessary,
     // and in doing so avoid some transitions ...
   
     int nWakeups = 0;
     int recheckInterval = 1;
   
     for (;;) {
   
       if (TryLock(Self) > 0) break;
       assert(_owner != Self, "invariant");
   
       // park self
       if (_Responsible == Self) {
         Self->_ParkEvent->park((jlong) recheckInterval);
         // Increase the recheckInterval, but clamp the value.
         recheckInterval *= 8;
         if (recheckInterval > MAX_RECHECK_INTERVAL) {
           recheckInterval = MAX_RECHECK_INTERVAL;
         }
       } else {
         Self->_ParkEvent->park();
       }
   
       if (TryLock(Self) > 0) break;
   
       // The lock is still contested.
       // Keep a tally of the # of futile wakeups.
       // Note that the counter is not protected by a lock or updated by atomics.
       // That is by design - we trade "lossy" counters which are exposed to
       // races during updates for a lower probe effect.
   
       // This PerfData object can be used in parallel with a safepoint.
       // See the work around in PerfDataManager::destroy().
       OM_PERFDATA_OP(FutileWakeups, inc());
       ++nWakeups;
   
       // Assuming this is not a spurious wakeup we'll normally find _succ == Self.
       // We can defer clearing _succ until after the spin completes
       // TrySpin() must tolerate being called with _succ == Self.
       // Try yet another round of adaptive spinning.
       if (TrySpin(Self) > 0) break;
   
       // We can find that we were unpark()ed and redesignated _succ while
       // we were spinning.  That's harmless.  If we iterate and call park(),
       // park() will consume the event and return immediately and we'll
       // just spin again.  This pattern can repeat, leaving _succ to simply
       // spin on a CPU.
   
       if (_succ == Self) _succ = NULL;
   
       // Invariant: after clearing _succ a thread *must* retry _owner before parking.
       OrderAccess::fence();
     }
```
   
Egress :
Self has acquired the lock -- Unlink Self from the cxq or EntryList.
Normally we'll find Self on the EntryList .
From the perspective of the lock owner (this thread), the EntryList is stable and cxq is prepend-only.
The head of cxq is volatile but the interior is stable.
In addition, Self.TState is stable.
```cpp
     assert(_owner == Self, "invariant");
     assert(object() != NULL, "invariant");
     // I'd like to write:
     //   guarantee (((oop)(object()))->mark() == markOopDesc::encode(this), "invariant") ;
     // but as we're at a safepoint that's not safe.
   
     UnlinkAfterAcquire(Self, &node);
     if (_succ == Self) _succ = NULL;
   
     assert(_succ != Self, "invariant");
     if (_Responsible == Self) {
       _Responsible = NULL;
       OrderAccess::fence(); // Dekker pivot-point
     }
```

We may leave threads on cxq|EntryList without a designated"Responsible" thread.  This is benign.  
When this thread subsequently exits the monitor it can "see" such preexisting "old" threads -- threads that arrived on the cxq|EntryList before the fence, above -- by LDing cxq|EntryList.  
Newly arrived threads -- that is, threads that arrive on cxq after the ST:MEMBAR, above -- will set Responsible non-null and elect a new "Responsible" timer thread.

This thread executes:
ST Responsible=null; MEMBAR    (in enter epilogue - here)
LD cxq|EntryList               (in subsequent exit)

Entering threads in the slow/contended path execute:
ST cxq=nonnull; MEMBAR; LD Responsible (in enter prolog)
The (ST cxq; MEMBAR) is accomplished with CAS().

The MEMBAR, above, prevents the LD of cxq|EntryList in the subsequent
exit operation from floating above the ST Responsible=null.

We've acquired ownership with CAS().
CAS is serializing -- it has MEMBAR/FENCE-equivalent semantics.
But since the CAS() this thread may have also stored into _succ,
EntryList, cxq or Responsible.  These meta-data updates must be
visible __before this thread subsequently drops the lock.
Consider what could occur if we didn't enforce this constraint --
STs to monitor meta-data and user-data could reorder with (become
visible after) the ST in exit that drops ownership of the lock.
Some other thread could then acquire the lock, but observe inconsistent
or old monitor meta-data and heap data.  That violates the JMM.
To that end, the 1-0 exit() operation must have at least STST|LDST
"release" barrier semantics.  Specifically, there must be at least a
STST|LDST barrier in exit() before the ST of null into _owner that drops
the lock.   The barrier ensures that changes to monitor meta-data and data
protected by the lock will be visible before we release the lock, and
therefore before some other thread (CPU) has a chance to acquire the lock.
See also: http://gee.cs.oswego.edu/dl/jmm/cookbook.html.

Critically, any prior STs to _succ or EntryList must be visible before
the ST of null into _owner in the *subsequent* (following) corresponding
monitorexit.  Recall too, that in 1-0 mode monitorexit does not necessarily
execute a serializing instruction.
```cpp
     return;
   }
```




#### ObjectMonitor::TrySpin

`Adaptive spin-then-block - rational spinning`

```cpp
// Spinning: Fixed frequency (100%), vary duration
int ObjectMonitor::TrySpin(Thread * Self) {
  // Dumb, brutal spin.  Good for comparative measurements against adaptive spinning.
  int ctr = Knob_FixedSpin;
  if (ctr != 0) {
    while (--ctr >= 0) {
      if (TryLock(Self) > 0) return 1;
      SpinPause();
    }
    return 0;
  }

  for (ctr = Knob_PreSpin + 1; --ctr >= 0;) {
    if (TryLock(Self) > 0) {
      // Increase _SpinDuration ...
      // Note that we don't clamp SpinDuration precisely at SpinLimit.
      // Raising _SpurDuration to the poverty line is key.
      int x = _SpinDuration;
      if (x < Knob_SpinLimit) {
        if (x < Knob_Poverty) x = Knob_Poverty;
        _SpinDuration = x + Knob_BonusB;
      }
      return 1;
    }
    SpinPause();
  }

  // Admission control - verify preconditions for spinning
  //
  // We always spin a little bit, just to prevent _SpinDuration == 0 from
  // becoming an absorbing state.  Put another way, we spin briefly to
  // sample, just in case the system load, parallelism, contention, or lock
  // modality changed.
  //
  // Consider the following alternative:
  // Periodically set _SpinDuration = _SpinLimit and try a long/full
  // spin attempt.  "Periodically" might mean after a tally of
  // the # of failed spin attempts (or iterations) reaches some threshold.
  // This takes us into the realm of 1-out-of-N spinning, where we
  // hold the duration constant but vary the frequency.

  ctr = _SpinDuration;
  if (ctr <= 0) return 0;

  if (NotRunnable(Self, (Thread *) _owner)) {
    return 0;
  }

  // We're good to spin ... spin ingress.
  // CONSIDER: use Prefetch::write() to avoid RTS->RTO upgrades
  // when preparing to LD...CAS _owner, etc and the CAS is likely
  // to succeed.
  if (_succ == NULL) {
    _succ = Self;
  }
  Thread * prv = NULL;

  // There are three ways to exit the following loop:
  // 1.  A successful spin where this thread has acquired the lock.
  // 2.  Spin failure with prejudice
  // 3.  Spin failure without prejudice

  while (--ctr >= 0) {

    // Periodic polling -- Check for pending GC
    // Threads may spin while they're unsafe.
    // We don't want spinning threads to delay the JVM from reaching
    // a stop-the-world safepoint or to steal cycles from GC.
    // If we detect a pending safepoint we abort in order that
    // (a) this thread, if unsafe, doesn't delay the safepoint, and (b)
    // this thread, if safe, doesn't steal cycles from GC.
    // This is in keeping with the "no loitering in runtime" rule.
    // We periodically check to see if there's a safepoint pending.
    if ((ctr & 0xFF) == 0) {
      if (SafepointMechanism::should_block(Self)) {
        goto Abort;           // abrupt spin egress
      }
      SpinPause();
    }

    // Probe _owner with TATAS
    // If this thread observes the monitor transition or flicker
    // from locked to unlocked to locked, then the odds that this
    // thread will acquire the lock in this spin attempt go down
    // considerably.  The same argument applies if the CAS fails
    // or if we observe _owner change from one non-null value to
    // another non-null value.   In such cases we might abort
    // the spin without prejudice or apply a "penalty" to the
    // spin count-down variable "ctr", reducing it by 100, say.

    Thread * ox = (Thread *) _owner;
    if (ox == NULL) {
      ox = (Thread*)Atomic::cmpxchg(Self, &_owner, (void*)NULL);
      if (ox == NULL) {
        // The CAS succeeded -- this thread acquired ownership
        // Take care of some bookkeeping to exit spin state.
        if (_succ == Self) {
          _succ = NULL;
        }

        // Increase _SpinDuration :
        // The spin was successful (profitable) so we tend toward
        // longer spin attempts in the future.
        // CONSIDER: factor "ctr" into the _SpinDuration adjustment.
        // If we acquired the lock early in the spin cycle it
        // makes sense to increase _SpinDuration proportionally.
        // Note that we don't clamp SpinDuration precisely at SpinLimit.
        int x = _SpinDuration;
        if (x < Knob_SpinLimit) {
          if (x < Knob_Poverty) x = Knob_Poverty;
          _SpinDuration = x + Knob_Bonus;
        }
        return 1;
      }

      // The CAS failed ... we can take any of the following actions:
      // * penalize: ctr -= CASPenalty
      // * exit spin with prejudice -- goto Abort;
      // * exit spin without prejudice.
      // * Since CAS is high-latency, retry again immediately.
      prv = ox;
      goto Abort;
    }

    // Did lock ownership change hands ?
    if (ox != prv && prv != NULL) {
      goto Abort;
    }
    prv = ox;

    // Abort the spin if the owner is not executing.
    // The owner must be executing in order to drop the lock.
    // Spinning while the owner is OFFPROC is idiocy.
    // Consider: ctr -= RunnablePenalty ;
    if (NotRunnable(Self, ox)) {
      goto Abort;
    }
    if (_succ == NULL) {
      _succ = Self;
    }
  }

  // Spin failed with prejudice -- reduce _SpinDuration.
  // TODO: Use an AIMD-like policy to adjust _SpinDuration.
  // AIMD is globally stable.
  {
    int x = _SpinDuration;
    if (x > 0) {
      // Consider an AIMD scheme like: x -= (x >> 3) + 100
      // This is globally sample and tends to damp the response.
      x -= Knob_Penalty;
      if (x < 0) x = 0;
      _SpinDuration = x;
    }
  }

 Abort:
  if (_succ == Self) {
    _succ = NULL;
    // Invariant: after setting succ=null a contending thread
    // must recheck-retry _owner before parking.  This usually happens
    // in the normal usage of TrySpin(), but it's safest
    // to make TrySpin() as foolproof as possible.
    OrderAccess::fence();
    if (TryLock(Self) > 0) return 1;
  }
  return 0;
}
```

#### ObjectMonitor::TryLock

```cpp
int ObjectMonitor::TryLock (Thread * Self) {
   for (;;) {
      void * own = _owner ;
      if (own != NULL) return 0 ;
      if (Atomic::cmpxchg_ptr (Self, &_owner, NULL) == NULL) {
         // Either guarantee _recursions == 0 or set _recursions = 0.
         assert (_recursions == 0, "invariant") ;
         assert (_owner == Self, "invariant") ;
         // CONSIDER: set or assert that OwnerIsThread == 1
         return 1 ;
      }
      // The lock had been free momentarily, but we lost the race to the lock.
      // Interference -- the CAS failed.
      // We can either return -1 or retry.
      // Retry doesn't make as much sense because the lock was just acquired.
      if (true) return -1 ;
   }
}
```

#### ObjectMonitor::exit


1. if _owner != Self  & is_lock_owned(Light Lcok), set _owner = Self
2. if _recursions != 0, _recursions-- then return
4. Or else drop the lock and check if we need to wake a successor
5. If other threads are acquiring lock, return
3. 释放当前锁，并根据QMode的模式判断，是否将_cxq中挂起的线程唤醒。还是其他操作


Chose onDeck from EntryList

Drain _cxq into EntryList - bulk transfer. -- by owner

```cpp
void ObjectMonitor::exit(bool not_suspended, TRAPS) {
  Thread * const Self = THREAD;
  if (THREAD != _owner) {
    if (THREAD->is_lock_owned((address) _owner)) {
      // Transmute _owner from a BasicLock pointer to a Thread address.
      // We don't need to hold _mutex for this transition.
      // Non-null to Non-null is safe as long as all readers can
      // tolerate either flavor.
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

  for (;;) {
    // release semantics: prior loads and stores from within the critical section
    // must not float (reorder) past the following store that drops the lock.
    // On SPARC that requires MEMBAR #loadstore|#storestore.
    // But of course in TSO #loadstore|#storestore is not required.
    OrderAccess::release_store(&_owner, (void*)NULL);   // drop the lock
    OrderAccess::storeload();                       
    
    // Check if we need to wake a successor
    if ((intptr_t(_EntryList)|intptr_t(_cxq)) == 0 || _succ != NULL) {
      return;
    }
```
Other threads are blocked trying to acquire the lock.


Normally the exiting thread is responsible for ensuring succession,
but if other successors are ready or other entering threads are spinning
then this thread can simply store NULL into _owner and exit without
waking a successor.  The existence of spinners or ready successors
guarantees proper succession (liveness).  Responsibility passes to the
ready or running successors.  The exiting thread delegates the duty.
More precisely, if a successor already exists this thread is absolved
of the responsibility of waking (unparking) one.

The _succ variable is critical to reducing futile wakeup frequency.
_succ identifies the "heir presumptive" thread that has been made
ready (unparked) but that has not yet run.  We need only one such
successor thread to guarantee progress.
See http://www.usenix.org/events/jvm01/full_papers/dice/dice.pdf
section 3.3 "Futile Wakeup Throttling" for details.

Note that spinners in Enter() also set _succ non-null.
In the current implementation spinners opportunistically set
_succ so that exiting threads might avoid waking a successor.
Another less appealing alternative would be for the exiting thread
to drop the lock and then spin briefly to see if a spinner managed
to acquire the lock.  If so, the exiting thread could exit
immediately without waking a successor, otherwise the exiting
thread would need to dequeue and wake a successor.
(Note that we'd need to make the post-drop spin short, but no
shorter than the worst-case round-trip cache-line migration time.
The dropped lock needs to become visible to the spinner, and then
the acquisition of the lock by the spinner must become visible to
the exiting thread).

It appears that an heir-presumptive (successor) must be made ready.
Only the current lock owner can manipulate the EntryList or
drain _cxq, so we need to reacquire the lock.  If we fail
to reacquire the lock the responsibility for ensuring succession
falls to the new owner.

```cpp
    if (!Atomic::replace_if_null(THREAD, &_owner)) {
      return;
    }

```
I'd like to write: guarantee (w->_thread != Self).
But in practice an exiting thread may find itself on the EntryList.
Let's say thread T1 calls O.wait().  Wait() enqueues T1 on O's waitset and
then calls exit().  Exit release the lock by setting O._owner to NULL.
Let's say T1 then stalls.  T2 acquires O and calls O.notify().  The
notify() operation moves T1 from O's waitset to O's EntryList. T2 then
release the lock "O".  T2 resumes immediately after the ST of null into
_owner, above.  T2 notices that the EntryList is populated, so it
reacquires the lock and then finds itself on the EntryList.
Given all that, we have to tolerate the circumstance where "w" is
associated with Self.


```cpp
    ObjectWaiter * w = NULL;
    w = _EntryList;
    if (w != NULL) {
      assert(w->TState == ObjectWaiter::TS_ENTER, "invariant");
      ExitEpilog(Self, w);
      return;
    }
```
If we find that both _cxq and EntryList are null then just re-run the exit protocol from the top.
```cpp
    w = _cxq;
    if (w == NULL) continue;
```
Drain _cxq into EntryList - bulk transfer.
```cpp
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
```
 In 1-0 mode we need: ST EntryList; MEMBAR #storestore; ST _owner = NULL
 The MEMBAR is satisfied by the release_store() operation in ExitEpilog().

 See if we can abdicate to a spinner instead of waking a thread.
 A primary goal of the implementation is to reduce the context-switch rate.
```cpp
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
2. ST _owner = NULL
3. unpark(wakee)

```cpp
void ObjectMonitor::ExitEpilog(JavaThread* current, ObjectWaiter* Wakee) {
  _succ = Wakee->_thread;
  ParkEvent * Trigger = Wakee->_event;

  // Hygiene -- once we've set _owner = NULL we can't safely dereference Wakee again.
  // The thread associated with Wakee may have grabbed the lock and "Wakee" may be
  // out-of-scope (non-extant).
  Wakee  = NULL;

  // Drop the lock.
  // Uses a fence to separate release_store(owner) from the LD in unpark().
  release_clear_owner(current);
  OrderAccess::fence();

  DTRACE_MONITOR_PROBE(contended__exit, this, object(), current);
  Trigger->unpark();

  // Maintain stats and report events to JVMTI
  OM_PERFDATA_OP(Parks, inc());
}
```

#### deflate_idle_monitors



Deflate the specified ObjectMonitor if not in-use. Returns true if it was deflated and false otherwise.

The async deflation protocol sets owner to DEFLATER_MARKER and makes contentions negative as signals to contending threads that an async deflation is in progress. 
There are a number of checks as part of the protocol to make sure that the calling thread has not lost the race to a contending thread.

The ObjectMonitor has been successfully async deflated when: (contentions < 0)
Contending threads that see that condition know to retry their operation.


## Summary

Using ParkEvent(A wrapper of mutex).


| Lock           | Bias Lock    | Light lock   | Heavy Lock                            |
| -------------- | ------------ | ------------ | ------------------------------------- |
| Race condition | Mark Word    | Mark Word    | ObjectMonitor                         |
| Recursion      | Lock Record nums | Lock Record nums| _recursions in ObjectMonitor(use CAS) |
|                |              |              |                                       |



## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [Java Synchronized 偏向锁/轻量级锁/重量级锁的演变过程](https://www.jianshu.com/p/22b5a0a78a9b)
2. [JEP draft: Concurrent Monitor Deflation](https://openjdk.java.net/jeps/8183909)
3. [Biased Locking in HotSpot](https://blogs.oracle.com/dave/biased-locking-in-hotspot)
4. [Java中的锁机制](https://www.cnblogs.com/charlesblc/p/5994162.html)
5. [死磕Synchronized底层实现--偏向锁](https://github.com/farmerjohngit/myblog/issues/13)
6. [Synchronization - OpenJDKwiki](https://wiki.openjdk.java.net/display/HotSpot/Synchronization)
