# synchronized

## 字节码分析

 通过字节码我们可以发现 ，修饰在方法层面的同步关键字，会多一个 ACC_SYNCHRONIZED的flag；修饰在代码块层面的同步块会多一个 monitorenter和 monitorexit关键字。无论采用哪一种方式，本质上都是对一个对象的监视器(monitor)进行获取，而这个获取的过程是排他的，也就是同一个时刻只能有一个线程获得同步块对象的监视器。



![sychronized](https://notfound9.github.io/interviewGuide/static/sychronize.png)



```
//synchronized with block
monitorenter monitorexit

//synchronized with method
ACC_SYNCHRONIZED
```



interpreterRuntime.cpp

```cpp
// Synchronization
//
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

偏向锁可以通过 -XX:+UseBiasedLocking开启或者关闭

如果支持偏向锁,则执行 ObjectSynchronizer::fast_enter的逻辑
如果不支持偏向锁,则执行 ObjectSynchronizer::slow_enter逻辑，绕过偏向锁，直接进入轻量级锁

basicLock.hpp

```cpp
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

class BasicObjectLock {
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



 synchronizer.cpp文件 

### objectMonitor
 在hotspot虚拟机中，采用ObjectMonitor类来实现monitor ， 每个对象中都会内置一个ObjectMonitor对象 

在 ObjectMonitor.hpp中，可以看到ObjectMonitor的定义
```cpp
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



### Biased Lock

在大多数的情况下，锁不仅不存在多线程的竞争，而且总是由同一个线程获得。因此为了让线程获得锁的代价更低引入了偏向锁的概念。偏向锁的意思是如果一个线程获得了一个偏向锁，如果在接下来的一段时间中没有其他线程来竞争锁，那么持有偏向锁的线程再次进入或者退出同一个同步代码块，不需要再次进行抢占锁和释放锁的操作。


ObjectSynchronizer::fast_enter的实现在 synchronizer.cpp文件中，代码如下

```cpp
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
   1. *`if(!SafepointSynchronize::is_at_safepoint())`, invoke `BiasedLocking::revoke_and_rebias()` success, return*
2. *Others, `ObjectSynchronizer::slow_enter()`*



#### revoke and rebias

偏向锁的获取过程非常简单，当一个线程访问同步块获取锁时，会在对象头和栈帧中的锁记录里存储偏向锁的线程ID，表示哪个线程获得了偏向锁，结合前面分析的Mark Word来分析一下偏向锁的获取逻辑

1. 首先获取目标对象的Mark Word，根据锁的标识为和epoch去判断当前是否处于可偏向的状态
2. 如果为可偏向状态，则通过CAS操作将自己的线程ID写入到MarkWord，如果CAS操作成功，则表示当前线程成功获取到偏向锁，继续执行同步代码块
3. 如果是已偏向状态，先检测MarkWord中存储的threadID和当前访问的线程的threadID是否相等，如果相等，表示当前线程已经获得了偏向锁，则不需要再获得锁直接执行同步代码；如果不相等，则证明当前锁偏向于其他线程，需要撤销偏向锁。

> CAS:表示自旋锁，由于线程的阻塞和唤醒需要CPU从用户态转为核心态，频繁的阻塞和唤醒对CPU来说性能开销很大。同时，很多对象锁的锁定状态指会持续很短的时间，因此引入了自旋锁，所谓自旋就是一个无意义的死循环，在循环体内不断的重行竞争锁。当然，自旋的次数会有限制，超出指定的限制会升级到阻塞锁。

BiasedLocking::revoke_and_rebias 是用来获取当前偏向锁的状态(可能是偏向锁撤销后重新偏向)。

in biasedLocking.cpp

1. Get markOop
2.  if (mark->is_biased_anonymously() && !attempt_rebias) 

```cpp
BiasedLocking::Condition BiasedLocking::revoke_and_rebias(Handle obj, bool attempt_rebias, TRAPS) {
  assert(!SafepointSynchronize::is_at_safepoint(), "must not be called while at safepoint");

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



```cpp
BiasedLocking::Condition BiasedLocking::revoke_and_rebias(Handle obj, bool attempt_rebias, TRAPS) {
  assert(!SafepointSynchronize::is_at_safepoint(), "must not be called while at safepoint");
  markOop mark = obj->mark(); //获取锁对象的对象头
  //判断mark是否为可偏向状态，即mark的偏向锁标志位为1，锁标志位为 01，线程id为null
  if (mark->is_biased_anonymously() && !attempt_rebias) {
    //这个分支是进行对象的hashCode计算时会进入，在一个非全局安全点进行偏向锁撤销
    markOop biased_value       = mark;
    //创建一个非偏向的markword
    markOop unbiased_prototype = markOopDesc::prototype()->set_age(mark->age());
    //Atomic:cmpxchg_ptr是CAS操作，通过cas重新设置偏向锁状态
    markOop res_mark = (markOop) Atomic::cmpxchg_ptr(unbiased_prototype, obj->mark_addr(), mark);
    if (res_mark == biased_value) {//如果CAS成功，返回偏向锁撤销状态
      return BIAS_REVOKED;
    }
  } else if (mark->has_bias_pattern()) {//如果锁对象为可偏向状态（biased_lock:1, lock:01，不管线程id是否为空）,尝试重新偏向
    Klass* k = obj->klass(); 
    markOop prototype_header = k->prototype_header();
    //如果已经有线程对锁对象进行了全局锁定，则取消偏向锁操作
    if (!prototype_header->has_bias_pattern()) {
      markOop biased_value       = mark;
      //CAS 更新对象头markword为非偏向锁
      markOop res_mark = (markOop) Atomic::cmpxchg_ptr(prototype_header, obj->mark_addr(), mark);
      assert(!(*(obj->mark_addr()))->has_bias_pattern(), "even if we raced, should still be revoked");
      return BIAS_REVOKED; //返回偏向锁撤销状态
    } else if (prototype_header->bias_epoch() != mark->bias_epoch()) {
      //如果偏向锁过期，则进入当前分支
      if (attempt_rebias) {//如果允许尝试获取偏向锁
        assert(THREAD->is_Java_thread(), "");
        markOop biased_value       = mark;
        markOop rebiased_prototype = markOopDesc::encode((JavaThread*) THREAD, mark->age(), prototype_header->bias_epoch());
        //通过CAS 操作， 将本线程的 ThreadID 、时间错、分代年龄尝试写入对象头中
        markOop res_mark = (markOop) Atomic::cmpxchg_ptr(rebiased_prototype, obj->mark_addr(), mark);
        if (res_mark == biased_value) { //CAS成功，则返回撤销和重新偏向状态
          return BIAS_REVOKED_AND_REBIASED;
        }
      } else {//不尝试获取偏向锁，则取消偏向锁
        //通过CAS操作更新分代年龄
        markOop biased_value       = mark;
        markOop unbiased_prototype = markOopDesc::prototype()->set_age(mark->age());
        markOop res_mark = (markOop) Atomic::cmpxchg_ptr(unbiased_prototype, obj->mark_addr(), mark);
        if (res_mark == biased_value) { //如果CAS操作成功，返回偏向锁撤销状态
          return BIAS_REVOKED;
        }
      }
    }
  }
  ...//省略
}
```

#### revoke bias

In  biasedLocking.cpp

***BiasedLocking::revoke_at_safepoint must only be called while at safepoint.***

update_heuristics:

 Heuristics to attempt to throttle the number of revocations.
 Stages:

 1. Revoke the biases of all objects in the heap of this type,    but allow rebiasing of those objects if unlocked.
  2. Revoke the biases of all objects in the heap of this type   and don't allow rebiasing of these objects. Disable  allocation of objects of that type with the bias bit set.

```cpp
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

### 轻量级锁

前面我们知道，当存在超过一个线程在竞争同一个同步代码块时，会发生偏向锁的撤销。偏向锁撤销以后对象会可能会处于两种状态

1. 一种是不可偏向的无锁状态，简单来说就是已经获得偏向锁的线程已经退出了同步代码块，那么这个时候会撤销偏向锁，并升级为轻量级锁
2. 一种是不可偏向的已锁状态，简单来说就是已经获得偏向锁的线程正在执行同步代码块，那么这个时候会升级到轻量级锁并且被原持有锁的线程获得锁

#### 轻量级锁加锁

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
>

轻量级锁加锁前：
    ![Light-weight Locking ： Before](https://segmentfault.com/img/remote/1460000007006604?w=839&h=499)
    
轻量级锁加锁后：
    ![Ligth-weight Locking ： After](https://segmentfault.com/img/remote/1460000007006605?w=839&h=499)


#### 轻量锁解锁

1. 尝试CAS操作将锁记录中的Displaced Mark Word替换回到对象头中
2. 如果成功，表示没有竞争发生
3. 如果失败，表示当前锁存在竞争，锁会膨胀成重量级锁

> 一旦锁升级成重量级锁，就不会再恢复到轻量级锁状态。当锁处于重量级锁状态，其他线程尝试获取锁时，都会被阻塞，也就是 BLOCKED状态。当持有锁的线程释放锁之后会唤醒这些现场，被唤醒之后的线程会进行新一轮的竞争

轻量级锁的释放是通过 monitorexit调用

```
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

这段代码中主要是通过 ObjectSynchronizer::slow_exit来执行

```
void ObjectSynchronizer::slow_exit(oop object, BasicLock* lock, TRAPS) {
  fast_exit (object, lock, THREAD) ;
}
```

ObjectSynchronizer::fast_exit的代码如下

```
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

### 锁膨胀的过程分析

重量级锁是通过对象内部的监视器(monitor)来实现，而monitor的本质是依赖操作系统底层的MutexLock实现的。我们先来看锁的膨胀过程，从前面的分析中已经知道了所膨胀的过程是通过 ObjectSynchronizer::inflate方法实现的，代码如下

```
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

锁膨胀的过程稍微有点复杂，整个锁膨胀的过程是通过自旋来完成的，具体的实现逻辑简答总结以下几点

1. mark->has_monitor() 判断如果当前锁对象为重量级锁，也就是lock:10，则执行(2),否则执行(3)
2. 通过 mark->monitor获得重量级锁的对象监视器ObjectMonitor并返回，锁膨胀过程结束
3. 如果当前锁处于 INFLATING,说明有其他线程在执行锁膨胀，那么当前线程通过自旋等待其他线程锁膨胀完成
4. 如果当前是轻量级锁状态 mark->has_locker(),则进行锁膨胀。首先，通过omAlloc方法获得一个可用的ObjectMonitor，并设置初始数据；然后通过CAS将对象头设置为`markOopDesc:INFLATING，表示当前锁正在膨胀，如果CAS失败，继续自旋
5. 如果是无锁状态，逻辑类似第4步骤

> 锁膨胀的过程实际上是获得一个ObjectMonitor对象监视器，而真正抢占锁的逻辑，在 ObjectMonitor::enter方法里面

### 重量级锁

重量级锁依赖对象内部的monitor锁来实现，而monitor又依赖操作系统的MutexLock（互斥锁）

大家如果对MutexLock有兴趣，可以抽时间去了解，假设Mutex变量的值为1，表示互斥锁空闲，这个时候某个线程调用lock可以获得锁，而Mutex的值为0表示互斥锁已经被其他线程获得，其他线程调用lock只能挂起等待

> 为什么重量级锁的开销比较大呢？

原因是当系统检查到是重量级锁之后，会把等待想要获取锁的线程阻塞，被阻塞的线程不会消耗CPU，但是阻塞或者唤醒一个线程，都需要通过操作系统来实现，也就是相当于从用户态转化到内核态，而转化状态是需要消耗时间的

#### 重量级锁的竞争逻辑

重量级锁的竞争，在 ObjectMonitor::enter方法中，代码文件在 objectMonitor.cpp重量级锁的代码就不一一分析了，简单说一下下面这段代码主要做的几件事

1. 通过CAS将monitor的 _owner字段设置为当前线程，如果设置成功，则直接返回

2. 如果之前的 _owner指向的是当前的线程，说明是重入，执行 _recursions++增加重入次数

3. 如果当前线程获取监视器锁成功，将 _recursions设置为1， _owner设置为当前线程

4. 如果获取锁失败，则等待锁释放

   ```cpp
   void ATTR ObjectMonitor::enter(TRAPS) {
     // The following code is ordered to check the most common cases first
     // and to reduce RTS->RTO cache line upgrades on SPARC and IA32 processors.
     Thread * const Self = THREAD ;
     void * cur ;
   
     cur = Atomic::cmpxchg_ptr (Self, &_owner, NULL) ;
     if (cur == NULL) {//CAS成功
        // Either ASSERT _recursions == 0 or explicitly set _recursions = 0.
        assert (_recursions == 0   , "invariant") ;
        assert (_owner      == Self, "invariant") ;
        // CONSIDER: set or assert OwnerIsThread == 1
        return ;
     }
   
     if (cur == Self) {
        // TODO-FIXME: check for integer overflow!  BUGID 6557169.
        _recursions ++ ;
        return ;
     }
   
     if (Self->is_lock_owned ((address)cur)) {
       assert (_recursions == 0, "internal state error");
       _recursions = 1 ;
       // Commute owner from a thread-specific on-stack BasicLockObject address to
       // a full-fledged "Thread *".
       _owner = Self ;
       OwnerIsThread = 1 ;
       return ;
     }
   
     // We've encountered genuine contention.
     assert (Self->_Stalled == 0, "invariant") ;
     Self->_Stalled = intptr_t(this) ;
   
     // Try one round of spinning *before* enqueueing Self
     // and before going through the awkward and expensive state
     // transitions.  The following spin is strictly optional ...
     // Note that if we acquire the monitor from an initial spin
     // we forgo posting JVMTI events and firing DTRACE probes.
     if (Knob_SpinEarly && TrySpin (Self) > 0) {
        assert (_owner == Self      , "invariant") ;
        assert (_recursions == 0    , "invariant") ;
        assert (((oop)(object()))->mark() == markOopDesc::encode(this), "invariant") ;
        Self->_Stalled = 0 ;
        return ;
     }
   
     assert (_owner != Self          , "invariant") ;
     assert (_succ  != Self          , "invariant") ;
     assert (Self->is_Java_thread()  , "invariant") ;
     JavaThread * jt = (JavaThread *) Self ;
     assert (!SafepointSynchronize::is_at_safepoint(), "invariant") ;
     assert (jt->thread_state() != _thread_blocked   , "invariant") ;
     assert (this->object() != NULL  , "invariant") ;
     assert (_count >= 0, "invariant") ;
   
     // Prevent deflation at STW-time.  See deflate_idle_monitors() and is_busy().
     // Ensure the object-monitor relationship remains stable while there's contention.
     Atomic::inc_ptr(&_count);
   
     EventJavaMonitorEnter event;
   
     { // Change java thread status to indicate blocked on monitor enter.
       JavaThreadBlockedOnMonitorEnterState jtbmes(jt, this);
   
       DTRACE_MONITOR_PROBE(contended__enter, this, object(), jt);
       if (JvmtiExport::should_post_monitor_contended_enter()) {
         JvmtiExport::post_monitor_contended_enter(jt, this);
       }
   
       OSThreadContendState osts(Self->osthread());
       ThreadBlockInVM tbivm(jt);
   
       Self->set_current_pending_monitor(this);
   
       // TODO-FIXME: change the following for(;;) loop to straight-line code.
       for (;;) {
         jt->set_suspend_equivalent();
         // cleared by handle_special_suspend_equivalent_condition()
         // or java_suspend_self()
   
         EnterI (THREAD) ;
   
         if (!ExitSuspendEquivalent(jt)) break ;
   
         //
         // We have acquired the contended monitor, but while we were
         // waiting another thread suspended us. We don't want to enter
         // the monitor while suspended because that would surprise the
         // thread that suspended us.
         //
             _recursions = 0 ;
         _succ = NULL ;
         exit (false, Self) ;
   
         jt->java_suspend_self();
       }
       Self->set_current_pending_monitor(NULL);
     }
   ...//此处省略无数行代码
   ```

如果获取锁失败，则需要通过自旋的方式等待锁释放，自旋执行的方法是 ObjectMonitor::EnterI，主要做的几件事如下

1. 将当前线程封装成ObjectWaiter对象node，状态设置成TS_CXQ
2. 通过自旋操作将node节点push到_cxq队列
3. node节点添加到_cxq队列之后，继续通过自旋尝试获取锁，如果在指定的阈值范围内没有获得锁，则通过park将当前线程挂起，等待被唤醒

```cpp
void ATTR ObjectMonitor::EnterI (TRAPS) {
    Thread * Self = THREAD ;
    ...//省略很多代码
    ObjectWaiter node(Self) ;
    Self->_ParkEvent->reset() ;
    node._prev   = (ObjectWaiter *) 0xBAD ;
    node.TState  = ObjectWaiter::TS_CXQ ;

    // Push "Self" onto the front of the _cxq.
    // Once on cxq/EntryList, Self stays on-queue until it acquires the lock.
    // Note that spinning tends to reduce the rate at which threads
    // enqueue and dequeue on EntryList|cxq.
    ObjectWaiter * nxt ;
    for (;;) { //自旋，讲node添加到_cxq队列
        node._next = nxt = _cxq ;
        if (Atomic::cmpxchg_ptr (&node, &_cxq, nxt) == nxt) break ;

        // Interference - the CAS failed because _cxq changed.  Just retry.
        // As an optional optimization we retry the lock.
        if (TryLock (Self) > 0) {
            assert (_succ != Self         , "invariant") ;
            assert (_owner == Self        , "invariant") ;
            assert (_Responsible != Self  , "invariant") ;
            return ;
        }
    }
    ...//省略很多代码
    //node节点添加到_cxq队列之后，继续通过自旋尝试获取锁，如果在指定的阈值范围内没有获得锁，则通过park将当前线程挂起，等待被唤醒
    for (;;) {
        if (TryLock (Self) > 0) break ;
        assert (_owner != Self, "invariant") ;

        if ((SyncFlags & 2) && _Responsible == NULL) {
           Atomic::cmpxchg_ptr (Self, &_Responsible, NULL) ;
        }

        // park self //通过park挂起当前线程
        if (_Responsible == Self || (SyncFlags & 1)) {
            TEVENT (Inflated enter - park TIMED) ;
            Self->_ParkEvent->park ((jlong) RecheckInterval) ;
            // Increase the RecheckInterval, but clamp the value.
            RecheckInterval *= 8 ;
            if (RecheckInterval > 1000) RecheckInterval = 1000 ;
        } else {
            TEVENT (Inflated enter - park UNTIMED) ;
            Self->_ParkEvent->park() ;//当前线程挂起
        }

        if (TryLock(Self) > 0) break ; //当线程被唤醒时，会从这里继续执行


        TEVENT (Inflated enter - Futile wakeup) ;
        if (ObjectMonitor::_sync_FutileWakeups != NULL) {
           ObjectMonitor::_sync_FutileWakeups->inc() ;
        }
        ++ nWakeups ;

        if ((Knob_SpinAfterFutile & 1) && TrySpin (Self) > 0) break ;

        if ((Knob_ResetEvent & 1) && Self->_ParkEvent->fired()) {
           Self->_ParkEvent->reset() ;
           OrderAccess::fence() ;
        }
        if (_succ == Self) _succ = NULL ;

        // Invariant: after clearing _succ a thread *must* retry _owner before parking.
        OrderAccess::fence() ;
    }
    ...//省略很多代码
}
```

TryLock(self)的代码是在 ObjectMonitor::TryLock定义的，代码的实现如下

> 代码的实现原理很简单，通过自旋，CAS设置monitor的_owner字段为当前线程，如果成功，表示获取到了锁，如果失败，则继续被挂起

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

#### 重量级锁的释放

重量级锁的释放是通过 ObjectMonitor::exit来实现的，释放以后会通知被阻塞的线程去竞争锁

1. 判断当前锁对象中的owner没有指向当前线程，如果owner指向的BasicLock在当前线程栈上,那么将_owner指向当前线程
2. 如果当前锁对象中的_owner指向当前线程，则判断当前线程重入锁的次数，如果不为0，继续执行ObjectMonitor::exit()，直到重入锁次数为0为止
3. 释放当前锁，并根据QMode的模式判断，是否将_cxq中挂起的线程唤醒。还是其他操作

```
void ATTR ObjectMonitor::exit(bool not_suspended, TRAPS) {
   Thread * Self = THREAD ;
   if (THREAD != _owner) {//如果当前锁对象中的_owner没有指向当前线程
     //如果_owner指向的BasicLock在当前线程栈上,那么将_owner指向当前线程
     if (THREAD->is_lock_owned((address) _owner)) {
       // Transmute _owner from a BasicLock pointer to a Thread address.
       // We don't need to hold _mutex for this transition.
       // Non-null to Non-null is safe as long as all readers can
       // tolerate either flavor.
       assert (_recursions == 0, "invariant") ;
       _owner = THREAD ;
       _recursions = 0 ;
       OwnerIsThread = 1 ;
     } else {
       // NOTE: we need to handle unbalanced monitor enter/exit
       // in native code by throwing an exception.
       // TODO: Throw an IllegalMonitorStateException ?
       TEVENT (Exit - Throw IMSX) ;
       assert(false, "Non-balanced monitor enter/exit!");
       if (false) {
          THROW(vmSymbols::java_lang_IllegalMonitorStateException());
       }
       return;
     }
   }
   //如果当前，线程重入锁的次数，不为0，那么就重新走ObjectMonitor::exit，直到重入锁次数为0为止
   if (_recursions != 0) {
     _recursions--;        // this is simple recursive enter
     TEVENT (Inflated exit - recursive) ;
     return ;
   }
  ...//此处省略很多代码
  for (;;) {
    if (Knob_ExitPolicy == 0) {
      OrderAccess::release_store(&_owner, (void*)NULL);   //释放锁
      OrderAccess::storeload();                        // See if we need to wake a successor
      if ((intptr_t(_EntryList)|intptr_t(_cxq)) == 0 || _succ != NULL) {
        TEVENT(Inflated exit - simple egress);
        return;
      }
      TEVENT(Inflated exit - complex egress);
      //省略部分代码...
    }
    //省略部分代码...
    ObjectWaiter * w = NULL;
    int QMode = Knob_QMode;
    //根据QMode的模式判断，
    //如果QMode == 2则直接从_cxq挂起的线程中唤醒    
    if (QMode == 2 && _cxq != NULL) {
      w = _cxq;
      ExitEpilog(Self, w);
      return;
    }
     //省略部分代码... 省略的代码为根据QMode的不同，不同的唤醒机制
  }
}
```

根据不同的策略(由QMode指定)，从cxq或EntryList中获取头节点，通过ObjectMonitor::ExitEpilog方法唤醒该节点封装的线程，唤醒操作最终由unpark完成

```
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