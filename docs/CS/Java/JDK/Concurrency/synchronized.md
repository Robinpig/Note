

## Introduction

use javap -c

```
//synchronized with block
monitorenter monitorexit

//synchronized with method
ACC_SYNCHRONIZED
```







## Process

![sychronized](https://notfound9.github.io/interviewGuide/static/sychronize.png)



### Oop

```cpp
//oop.hpp
class oopDesc {
  friend class VMStructs;
  friend class JVMCIVMStructs;
 private:
  volatile markOop _mark;
  union _metadata {
    Klass*      _klass;
    narrowKlass _compressed_klass;
  } _metadata;

 public:
  inline markOop  mark()          const;
  inline markOop  mark_raw()      const;
  inline markOop* mark_addr_raw() const;

  inline void set_mark(volatile markOop m);
  inline void set_mark_raw(volatile markOop m);
  static inline void set_mark_raw(HeapWord* mem, markOop m);

  inline void release_set_mark(markOop m);
  inline markOop cas_set_mark(markOop new_mark, markOop old_mark);
  inline markOop cas_set_mark_raw(markOop new_mark, markOop old_mark, atomic_memory_order order = memory_order_conservative);

  // Used only to re-initialize the mark word (e.g., of promoted
  // objects during a GC) -- requires a valid klass pointer
  inline void init_mark();
  inline void init_mark_raw();

  inline Klass* klass() const;
  inline Klass* klass_or_null() const volatile;
  inline Klass* klass_or_null_acquire() const volatile;
  static inline Klass** klass_addr(HeapWord* mem);
  static inline narrowKlass* compressed_klass_addr(HeapWord* mem);
  inline Klass** klass_addr();
  inline narrowKlass* compressed_klass_addr();
...
}
```



```cpp
//markOop.hpp
class markOopDesc: public oopDesc
  ObjectMonitor* monitor() const {
    assert(has_monitor(), "check");
    // Use xor instead of &~ to provide one extra tag-bit check.
    return (ObjectMonitor*) (value() ^ monitor_value);//monitor_value = 2
  }
...
}
```



### InterpreterRuntime::monitorenter

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

biasLock unlock 后其它线程都升级为轻量级锁，解锁后为不可偏向无锁状态

如果支持偏向锁,则执行 `ObjectSynchronizer::fast_enter`
如果不支持偏向锁,则执行 `ObjectSynchronizer::slow_enter`，直接进入轻量级锁



```shell
-XX:+UseBiasedLocking # in JDK15 default close
-XX:BiasedLockingStartupDelay=0 #default 5
```



存在矛盾
匿名偏向状态下，如果调用系统的hashCode()方法，会使对象回到无锁态，并在markword中写入hashCode。并且在这个状态下，如果有线程尝试获取锁，会直接从无锁升级到轻量级锁，不会再升级为偏向锁
wait()方法调用过程中依赖于重量级锁中与对象关联的monitor，在调用wait()方法后monitor会把线程变为WAITING状态，所以才会强制升级为重量级锁。除此之外，调用hashCode方法时也会使偏向锁直接升级为重量级锁

BiasedLockingBulkRebiasThreshold：偏向锁批量重偏向阈值，默认为20次
BiasedLockingBulkRevokeThreshold：偏向锁批量撤销阈值，默认为40次
BiasedLockingDecayTime：重置计数的延迟时间，默认值为25000毫秒（即25秒）
批量重偏向是以class而不是对象为单位的，每个class会维护一个偏向锁的撤销计数器，每当该class的对象发生偏向锁的撤销时，该计数器会加一，当这个值达到默认阈值20时，jvm就会认为这个锁对象不再适合原线程，因此进行批量重偏向。而距离上次批量重偏向的25秒内，如果撤销计数达到40，就会发生批量撤销，如果超过25秒，那么就会重置在[20, 40)内的计数。

### Biased Lock

[JEP 374: Disable and Deprecate Biased Locking](https://openjdk.java.net/jeps/374)

1. 偏向锁和重量级锁只用到了_obj字段，而轻量级锁用到了_displaced_header
2. 释放锁时都需要修改Lock Record 里的_obj字段。

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

默认开启
```shell
-XX:+UseCompressedOops
```
由于使用了8字节对齐后每个对象的地址偏移量后3位必定为0，所以在存储的时候可以将后3位0抹除（转化为bit是抹除了最后24位）
在此基础上再去掉最高位，就完成了指针从8字节到4字节的压缩。而在实际使用时，在压缩后的指针后加3位0，就能够实现向真实地址的映射。
指针的32位中的每一个bit，都可以代表8个字节，这样就相当于使原有的内存地址得到了8倍的扩容。所以在8字节对齐的情况下，32位最大能表示2^32*8=32GB内存
由于能够表示的最大内存是32GB，所以如果配置的最大的堆内存超过这个数值时，那么指针压缩将会失效。
-XX:ObjectAlignmentInBytes=16 对应64g

实例数据排序规则
根据对齐规则会压缩调整
```shell
-XX:+CompactFields
```
父类先
大字段先
基本类型先，可调整
```shell
-XX:FieldsAllocationStyle=0 # POJO first, primitive second, default =1
```


超过15 报错
```
-XX:MaxTenuringThreshold=15
```
在大多数的情况下，锁不仅不存在多线程的竞争，而且总是由同一个线程获得。因此为了让线程获得锁的代价更低引入了偏向锁的概念。偏向锁的意思是如果一个线程获得了一个偏向锁，如果在接下来的一段时间中没有其他线程来竞争锁，那么持有偏向锁的线程再次进入或者退出同一个同步代码块，不需要再次进行抢占锁和释放锁的操作。

#### ObjectSynchronizer::fast_enter

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

**ObjectSynchronizer::fast_enter():** 

1. *check `if(UseBiasedLocking) `*
   1. *`if is_at_safepoint())`, invoke `BiasedLocking::revoke_at_safepoint()`*
   2. *Else invoke `BiasedLocking::revoke_and_rebias()` success, return*
2. *Others, `ObjectSynchronizer::slow_enter()`*



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

***BiasedLocking::revoke_at_safepoint must only be called while at safepoint.***, so don't need CAS

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
    在做bulk rebias时，会对这个类的epoch的值做递增，这个epoch会存储在对象头中的epoch字段。在判断这个对象是否获得偏向锁的条件是:markword的 biased_lock:1、lock:01、threadid和当前线程id相等、epoch字段和所属类的epoch值相同，如果epoch的值不一样，要么就是撤销偏向锁、要么就是rebias； 如果这个类的revoke计数器的值继续增加到一个阈值，那么jvm会认为这个类不适合偏向锁，就需要进行bulk revoke操作 

### Light Lock

前面我们知道，当存在超过一个线程在竞争同一个同步代码块时，会发生偏向锁的撤销。偏向锁撤销以后对象会可能会处于两种状态

1. 一种是不可偏向的无锁状态，简单来说就是已经获得偏向锁的线程已经退出了同步代码块，那么这个时候会撤销偏向锁，并升级为轻量级锁
2. 一种是不可偏向的已锁状态，简单来说就是已经获得偏向锁的线程正在执行同步代码块，那么这个时候会升级到轻量级锁并且被原持有锁的线程获得锁

#### ObjectSynchronizer::slow_enter

轻量级锁的获取，是调用 ::slow_enter方法，该方法同样位于 synchronizer.cpp文件中

```cpp
void ObjectSynchronizer::slow_enter(Handle obj, BasicLock* lock, TRAPS) {
  markOop mark = obj->mark();
  assert(!mark->has_bias_pattern(), "should not see bias pattern here");

  if (mark->is_neutral()) { //如果当前是无锁状态, markword的biase_lock:0，lock:01
    //直接把mark保存到BasicLock对象的_displaced_header字段
    lock->set_displaced_header(mark);
    //通过CAS将mark word更新为指向BasicLock对象的指针，更新成功表示获得了轻量级锁
    if (mark == (markOop) Atomic::cmpxchg_ptr(lock, obj()->mark_addr(), mark)) {
      TEVENT (slow_enter: release stacklock) ;
      return ;
    }
    // Fall through to inflate() ... 
  }
  //如果markword处于加锁状态、且markword中的ptr指针指向当前线程的栈帧，表示为重入操作，不需要争抢锁 
  else if (mark->has_locker() && THREAD->is_lock_owned((address)mark->locker())) {
    assert(lock != mark->locker(), "must not re-lock the same lock");
    assert(lock != (BasicLock*)obj->mark(), "don't relock with same BasicLock");
    lock->set_displaced_header(NULL);
    return;
  }

#if 0
  // The following optimization isn't particularly useful.
  if (mark->has_monitor() && mark->monitor()->is_entered(THREAD)) {
    lock->set_displaced_header (NULL) ;
    return ;
  }
#endif
  //代码执行到这里，说明有多个线程竞争轻量级锁，轻量级锁通过`inflate`进行膨胀升级为重量级锁
  lock->set_displaced_header(markOopDesc::unused_mark());
  ObjectSynchronizer::inflate(THREAD, obj())->enter(THREAD);
}
```

轻量级锁的获取逻辑简单再整理一下

1. mark->is_neutral()方法, is_neutral这个方法是在 markOop.hpp中定义，如果 biased_lock:0且lock:01表示无锁状态
2. 如果mark处于无锁状态，则进入步骤(3)，否则执行步骤(5)
3. 把mark保存到BasicLock对象的displacedheader字段
4. 通过CAS尝试将markword更新为指向BasicLock对象的指针，如果更新成功，表示竞争到锁，则执行同步代码，否则执行步骤(5)
5. 如果当前mark处于加锁状态，且mark中的ptr指针指向当前线程的栈帧，则执行同步代码，否则说明有多个线程竞争轻量级锁，轻量级锁需要膨胀升级为重量级锁



> 1. JVM会先在当前线程的栈帧中创建用于存储锁记录的空间(LockRecord)
>
> 2. 将对象头中的Mark Word复制到锁记录中，称为Displaced Mark Word.
>
> 3. 线程尝试使用CAS将对象头中的Mark Word替换为指向锁记录的指针 ——stack pointer 
>
> 4. 如果替换成功，表示当前线程获得轻量级锁，如果失败，表示存在其他线程竞争锁，那么当前线程会尝试使用CAS来获取锁，当自旋超过指定次数(可以自定义)时仍然无法获得锁，此时锁会膨胀升级为重量级锁

轻量级锁加锁前：
    ![Light-weight Locking ： Before](https://segmentfault.com/img/remote/1460000007006604?w=839&h=499)
    
轻量级锁加锁后：
    ![Ligth-weight Locking ： After](https://segmentfault.com/img/remote/1460000007006605?w=839&h=499)

#### Unlock

轻量级锁的释放是通过 monitorexit调用

1. 尝试CAS操作将锁记录中的Displaced Mark Word替换回到对象头中
2. 如果成功，表示没有竞争发生
3. 如果失败，表示当前锁存在竞争，锁会膨胀成重量级锁

> 一旦锁升级成重量级锁，就不会再恢复到轻量级锁状态。当锁处于重量级锁状态，其他线程尝试获取锁时，都会被阻塞，也就是 BLOCKED状态。当持有锁的线程释放锁之后会唤醒这些现场，被唤醒之后的线程会进行新一轮的竞争

```cpp
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



#### ObjectSynchronizer::slow_exit

```cpp
void ObjectSynchronizer::slow_exit(oop object, BasicLock* lock, TRAPS) {
  fast_exit (object, lock, THREAD) ;
}

void ObjectSynchronizer::fast_exit(oop object, BasicLock* lock, TRAPS) {
  assert(!object->mark()->has_bias_pattern(), "should not see bias pattern here");
  // if displaced header is null, the previous enter is recursive enter, no-op
  markOop dhw = lock->displaced_header(); //获取锁对象中的对象头
  markOop mark ;
  if (dhw == NULL) { 
     // Recursive stack-lock.
     // Diagnostics -- Could be: stack-locked, inflating, inflated.
     mark = object->mark() ;
     assert (!mark->is_neutral(), "invariant") ;
     if (mark->has_locker() && mark != markOopDesc::INFLATING()) {
        assert(THREAD->is_lock_owned((address)mark->locker()), "invariant") ;
     }
     if (mark->has_monitor()) {
        ObjectMonitor * m = mark->monitor() ;
        assert(((oop)(m->object()))->mark() == mark, "invariant") ;
        assert(m->is_entered(THREAD), "invariant") ;
     }
     return ;
  }

  mark = object->mark() ; //获取线程栈帧中锁记录(LockRecord)中的markword

  // If the object is stack-locked by the current thread, try to
  // swing the displaced header from the box back to the mark.
  if (mark == (markOop) lock) {
     assert (dhw->is_neutral(), "invariant") ;
     //通过CAS尝试将Displaced Mark Word替换回对象头，如果成功，表示锁释放成功。
     if ((markOop) Atomic::cmpxchg_ptr (dhw, object->mark_addr(), mark) == mark) {
        TEVENT (fast_exit: release stacklock) ;
        return;
     }
  }
  //锁膨胀，调用重量级锁的释放锁方法
  ObjectSynchronizer::inflate(THREAD, object)->exit (true, THREAD) ;
}
```

轻量级锁的释放也比较简单，就是将当前线程栈帧中锁记录空间中的Mark Word替换到锁对象的对象头中，如果成功表示锁释放成功。否则，锁膨胀成重量级锁，实现重量级锁的释放锁逻辑



### Height Lock


同时竞争重量锁释放后为无锁不可偏向

#### ObjectSynchronizer::inflate

1. in loop
2. Get Mark Word
3. if has_monitor, return
4. If markOopDesc::INFLATING, continue loop until has_monitor
5. if `has_locker`(`Light Lock`), CAS set mark = markOopDesc:INFLATING, _owner = Lock Record
6. Else non-lock, CAS set mark = markOopDesc:INFLATING, _owner = NULL

锁膨胀的过程实际上是获得一个ObjectMonitor对象监视器，而真正抢占锁的逻辑，在 ObjectMonitor::enter方法里面

```cpp
ObjectMonitor * ATTR ObjectSynchronizer::inflate (Thread * Self, oop object) {
  // Inflate mutates the heap ...
  // Relaxing assertion for bug 6320749.
  assert (Universe::verify_in_progress() ||
          !SafepointSynchronize::is_at_safepoint(), "invariant") ;

  for (;;) { //通过无意义的循环实现自旋操作
      const markOop mark = object->mark() ;
      assert (!mark->has_bias_pattern(), "invariant") ;

      if (mark->has_monitor()) {//has_monitor是markOop.hpp中的方法，如果为true表示当前锁已经是重量级锁了
          ObjectMonitor * inf = mark->monitor() ;//获得重量级锁的对象监视器直接返回
          assert (inf->header()->is_neutral(), "invariant");
          assert (inf->object() == object, "invariant") ;
          assert (ObjectSynchronizer::verify_objmon_isinpool(inf), "monitor is invalid");
          return inf ;
      }

      if (mark == markOopDesc::INFLATING()) {//膨胀等待，表示存在线程正在膨胀，通过continue进行下一轮的膨胀
         TEVENT (Inflate: spin while INFLATING) ;
         ReadStableMark(object) ;
         continue ;
      }

      if (mark->has_locker()) {//表示当前锁为轻量级锁，以下是轻量级锁的膨胀逻辑
          ObjectMonitor * m = omAlloc (Self) ;//获取一个可用的ObjectMonitor
          // Optimistically prepare the objectmonitor - anticipate successful CAS
          // We do this before the CAS in order to minimize the length of time
          // in which INFLATING appears in the mark.
          m->Recycle();
          m->_Responsible  = NULL ;
          m->OwnerIsThread = 0 ;
          m->_recursions   = 0 ;
          m->_SpinDuration = ObjectMonitor::Knob_SpinLimit ;   // Consider: maintain by type/class
          /**将object->mark_addr()和mark比较，如果这两个值相等，则将object->mark_addr()
          改成markOopDesc::INFLATING()，相等返回是mark，不相等返回的是object->mark_addr()**/
                     markOop cmp = (markOop) Atomic::cmpxchg_ptr (markOopDesc::INFLATING(), object->mark_addr(), mark) ;
          if (cmp != mark) {//CAS失败
             omRelease (Self, m, true) ;//释放监视器
             continue ;       // 重试
          }

          markOop dmw = mark->displaced_mark_helper() ;
          assert (dmw->is_neutral(), "invariant") ;

          //CAS成功以后，设置ObjectMonitor相关属性
          m->set_header(dmw) ;


          m->set_owner(mark->locker());
          m->set_object(object);
          // TODO-FIXME: assert BasicLock->dhw != 0.


          guarantee (object->mark() == markOopDesc::INFLATING(), "invariant") ;
          object->release_set_mark(markOopDesc::encode(m));


          if (ObjectMonitor::_sync_Inflations != NULL) ObjectMonitor::_sync_Inflations->inc() ;
          TEVENT(Inflate: overwrite stacklock) ;
          if (TraceMonitorInflation) {
            if (object->is_instance()) {
              ResourceMark rm;
              tty->print_cr("Inflating object " INTPTR_FORMAT " , mark " INTPTR_FORMAT " , type %s",
                (void *) object, (intptr_t) object->mark(),
                object->klass()->external_name());
            }
          }
          return m ; //返回ObjectMonitor
      }
      //如果是无锁状态
      assert (mark->is_neutral(), "invariant");
      ObjectMonitor * m = omAlloc (Self) ; ////获取一个可用的ObjectMonitor
      //设置ObjectMonitor相关属性
      m->Recycle();
      m->set_header(mark);
      m->set_owner(NULL);
      m->set_object(object);
      m->OwnerIsThread = 1 ;
      m->_recursions   = 0 ;
      m->_Responsible  = NULL ;
      m->_SpinDuration = ObjectMonitor::Knob_SpinLimit ;       // consider: keep metastats by type/class
      /**将object->mark_addr()和mark比较，如果这两个值相等，则将object->mark_addr()
          改成markOopDesc::encode(m)，相等返回是mark，不相等返回的是object->mark_addr()**/
      if (Atomic::cmpxchg_ptr (markOopDesc::encode(m), object->mark_addr(), mark) != mark) {
          //CAS失败，说明出现了锁竞争，则释放监视器重行竞争锁
          m->set_object (NULL) ;
          m->set_owner  (NULL) ;
          m->OwnerIsThread = 0 ;
          m->Recycle() ;
          omRelease (Self, m, true) ;
          m = NULL ;
          continue ;
          // interference - the markword changed - just retry.
          // The state-transitions are one-way, so there's no chance of
          // live-lock -- "Inflated" is an absorbing state.
      }

      if (ObjectMonitor::_sync_Inflations != NULL) ObjectMonitor::_sync_Inflations->inc() ;
      TEVENT(Inflate: overwrite neutral) ;
      if (TraceMonitorInflation) {
        if (object->is_instance()) {
          ResourceMark rm;
          tty->print_cr("Inflating object " INTPTR_FORMAT " , mark " INTPTR_FORMAT " , type %s",
            (void *) object, (intptr_t) object->mark(),
            object->klass()->external_name());
        }
      }
      return m ; //返回ObjectMonitor对象
  }
}
```




#### objectMonitor

 在hotspot虚拟机中，采用ObjectMonitor类来实现monitor ， 每个对象中都会内置一个ObjectMonitor对象 

在 ObjectMonitor.hpp中，可以看到ObjectMonitor的定义

```cpp
// objectMonitor.hpp
ObjectMonitor() {
    _header       = NULL; //markOop对象头
    _count        = 0;    
    _waiters      = 0,   //等待线程数
    _recursions   = 0;   //重入次数
    _object       = NULL;  
    _owner        = NULL;  //获得ObjectMonitor对象的线程
    _WaitSet      = NULL;  //处于wait状态的线程，会被加入到waitSet
    _WaitSetLock  = 0 ; 
    _Responsible  = NULL ;
    _succ         = NULL ;
    _cxq          = NULL ;
    FreeNext      = NULL ;
    _EntryList    = NULL ; //处于等待锁BLOCKED状态的线程
    _SpinFreq     = 0 ;   
    _SpinClock    = 0 ;
    OwnerIsThread = 0 ; 
    _previous_owner_tid = 0; //监视器前一个拥有线程的ID
}
```



#### ObjectMonitor::enter

简单说一下`ObjectMonitor::enter`主要做的几件事

1. CAS set  _owner = cur Thread success, return
2. if recursion,  _recursions++
3. If _owner = Lock Record(Light Lock)，set _recursions = 1， _owner = Self
4. Else **TrySpin** -- Adaptive Spinning Support
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

加锁过程是不断地尝试加锁，实在不行了才放入队列里，而且还是插入队列头的位置，最后才挂起自己

1. tryLock
2. trySpin
3. wrap to node add push "Self" onto the front of the _cxq
4. tryLock and trySpin in a loop with ParkEvent
   1. if tryLock and trySpin fail, park
   2. unpark in exit by other Thread

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
   
     // Check for cxq|EntryList edge transition to non-null.  This indicates
     // the onset of contention.  While contention persists exiting threads
     // will use a ST:MEMBAR:LD 1-1 exit protocol.  When contention abates exit
     // operations revert to the faster 1-0 mode.  This enter operation may interleave
     // (race) a concurrent 1-0 exit operation, resulting in stranding, so we
     // arrange for one of the contending thread to use a timed park() operations
     // to detect and recover from the race.  (Stranding is form of progress failure
     // where the monitor is unlocked but all the contending threads remain parked).
     // That is, at least one of the contended threads will periodically poll _owner.
     // One of the contending threads will become the designated "Responsible" thread.
     // The Responsible thread uses a timed park instead of a normal indefinite park
     // operation -- it periodically wakes and checks for and recovers from potential
     // strandings admitted by 1-0 exit operations.   We need at most one Responsible
     // thread per-monitor at any given moment.  Only threads on cxq|EntryList may
     // be responsible for a monitor.
     //
     // Currently, one of the contended threads takes on the added role of "Responsible".
     // A viable alternative would be to use a dedicated "stranding checker" thread
     // that periodically iterated over all the threads (or active monitors) and unparked
     // successors where there was risk of stranding.  This would help eliminate the
     // timer scalability issues we see on some platforms as we'd only have one thread
     // -- the checker -- parked on a timer.
   
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
   
     // Egress :
     // Self has acquired the lock -- Unlink Self from the cxq or EntryList.
     // Normally we'll find Self on the EntryList .
     // From the perspective of the lock owner (this thread), the
     // EntryList is stable and cxq is prepend-only.
     // The head of cxq is volatile but the interior is stable.
     // In addition, Self.TState is stable.
   
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
   
       // We may leave threads on cxq|EntryList without a designated
       // "Responsible" thread.  This is benign.  When this thread subsequently
       // exits the monitor it can "see" such preexisting "old" threads --
       // threads that arrived on the cxq|EntryList before the fence, above --
       // by LDing cxq|EntryList.  Newly arrived threads -- that is, threads
       // that arrive on cxq after the ST:MEMBAR, above -- will set Responsible
       // non-null and elect a new "Responsible" timer thread.
       //
       // This thread executes:
       //    ST Responsible=null; MEMBAR    (in enter epilogue - here)
       //    LD cxq|EntryList               (in subsequent exit)
       //
       // Entering threads in the slow/contended path execute:
       //    ST cxq=nonnull; MEMBAR; LD Responsible (in enter prolog)
       //    The (ST cxq; MEMBAR) is accomplished with CAS().
       //
       // The MEMBAR, above, prevents the LD of cxq|EntryList in the subsequent
       // exit operation from floating above the ST Responsible=null.
     }
   
     // We've acquired ownership with CAS().
     // CAS is serializing -- it has MEMBAR/FENCE-equivalent semantics.
     // But since the CAS() this thread may have also stored into _succ,
     // EntryList, cxq or Responsible.  These meta-data updates must be
     // visible __before this thread subsequently drops the lock.
     // Consider what could occur if we didn't enforce this constraint --
     // STs to monitor meta-data and user-data could reorder with (become
     // visible after) the ST in exit that drops ownership of the lock.
     // Some other thread could then acquire the lock, but observe inconsistent
     // or old monitor meta-data and heap data.  That violates the JMM.
     // To that end, the 1-0 exit() operation must have at least STST|LDST
     // "release" barrier semantics.  Specifically, there must be at least a
     // STST|LDST barrier in exit() before the ST of null into _owner that drops
     // the lock.   The barrier ensures that changes to monitor meta-data and data
     // protected by the lock will be visible before we release the lock, and
     // therefore before some other thread (CPU) has a chance to acquire the lock.
     // See also: http://gee.cs.oswego.edu/dl/jmm/cookbook.html.
     //
     // Critically, any prior STs to _succ or EntryList must be visible before
     // the ST of null into _owner in the *subsequent* (following) corresponding
     // monitorexit.  Recall too, that in 1-0 mode monitorexit does not necessarily
     // execute a serializing instruction.
   
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

ObjectMonitor::TryLock

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

#### Unlock

`ObjectMonitor::exit`，释放以后会通知被阻塞的线程去竞争锁

1. if _owner != Self  & is_lock_owned(Light Lcok),那么将_owner指向当前线程
2. 如果当前锁对象中的_owner指向当前线程，则判断当前线程重入锁的次数，如果不为0，继续执行ObjectMonitor::exit()，直到重入锁次数为0为止
3. 释放当前锁，并根据QMode的模式判断，是否将_cxq中挂起的线程唤醒。还是其他操作



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

根据不同的策略(由QMode指定)，从cxq或EntryList中获取头节点，通过ObjectMonitor::ExitEpilog方法唤醒该节点封装的线程，唤醒操作最终由unpark完成

```cpp
void ObjectMonitor::ExitEpilog (Thread * Self, ObjectWaiter * Wakee) {
{
   assert (_owner == Self, "invariant") ;

   // Exit protocol:
   // 1. ST _succ = wakee
   // 2. membar #loadstore|#storestore;
   // 2. ST _owner = NULL
   // 3. unpark(wakee)

   _succ = Knob_SuccEnabled ? Wakee->_thread : NULL ;
   ParkEvent * Trigger = Wakee->_event ;

   // Hygiene -- once we've set _owner = NULL we can't safely dereference Wakee again.
   // The thread associated with Wakee may have grabbed the lock and "Wakee" may be
   // out-of-scope (non-extant).
   Wakee  = NULL ;

   // Drop the lock
   OrderAccess::release_store_ptr (&_owner, NULL) ;
   OrderAccess::fence() ;                               // ST _owner vs LD in unpark()

   if (SafepointSynchronize::do_call_back()) {
      TEVENT (unpark before SAFEPOINT) ;
   }

   DTRACE_MONITOR_PROBE(contended__exit, this, object(), Self);
   Trigger->unpark() ; //unpark唤醒线程

   // Maintain stats and report events to JVMTI
   if (ObjectMonitor::_sync_Parks != NULL) {
      ObjectMonitor::_sync_Parks->inc() ;
   }
}
```





## Summary

| Lock           | Bias Lock    | Light lock   | Heavy Lock                            |
| -------------- | ------------ | ------------ | ------------------------------------- |
| Race condition | Mark Word    | Mark Word    | ObjectMonitor                         |
| Recursion      | Lock Record nums | Lock Record nums| _recursions in ObjectMonitor(use CAS) |
|                |              |              |                                       |
|                |              |              |                                       |



## Reference



1. [](https://www.jianshu.com/p/22b5a0a78a9b)
