## Introduction







## Mutex
不可重入
```go
type Locker interface {
    Lock()
    Unlock()
}
```

```go
type Mutex struct {
    state int32
    sema  uint32
}
```
The zero value for a Mutex is an unlocked mutex.
不需要初始化mutex

08年初版只实现公平锁
11年支持非公平锁
15年2月 增加spin逻辑
16年1.9版本增加饥饿模式 限制不公平时间 修复唤醒goroutine在最末尾的问题
18年 分离慢速和快速逻辑 方便inline提高性能

1.14版本 在Unlocking a highly contented Mutex下directly yields 给下一个waiting mutex的goroutine
> [记一次 Consul 故障分析与优化](https://www.infoq.cn/article/qV02j2EZMjboW8cKcOpg)
> [sync: Mutex performance collapses with high concurrency](https://github.com/golang/go/issues/33747)

```go
const (
    mutexLocked = 1 << iota // mutex is locked
    mutexWoken
    mutexStarving
    mutexWaiterShift = iota

    // Mutex fairness.
    //
    // Mutex can be in 2 modes of operations: normal and starvation.
    // In normal mode waiters are queued in FIFO order, but a woken up waiter
    // does not own the mutex and competes with new arriving goroutines over
    // the ownership. New arriving goroutines have an advantage -- they are
    // already running on CPU and there can be lots of them, so a woken up
    // waiter has good chances of losing. In such case it is queued at front
    // of the wait queue. If a waiter fails to acquire the mutex for more than 1ms,
    // it switches mutex to the starvation mode.
    //
    // In starvation mode ownership of the mutex is directly handed off from
    // the unlocking goroutine to the waiter at the front of the queue.
    // New arriving goroutines don't try to acquire the mutex even if it appears
    // to be unlocked, and don't try to spin. Instead they queue themselves at
    // the tail of the wait queue.
    //
    // If a waiter receives ownership of the mutex and sees that either
    // (1) it is the last waiter in the queue, or (2) it waited for less than 1 ms,
    // it switches mutex back to normal operation mode.
    //
    // Normal mode has considerably better performance as a goroutine can acquire
    // a mutex several times in a row even if there are blocked waiters.
    // Starvation mode is important to prevent pathological cases of tail latency.
    starvationThresholdNs = 1e6
)
```
lock
```go
func (m *Mutex) Lock() {
    // Fast path: grab unlocked mutex.
    if atomic.CompareAndSwapInt32(&m.state, 0, mutexLocked) {
        if race.Enabled {
            race.Acquire(unsafe.Pointer(m))
        }
        return
    }
    // Slow path (outlined so that the fast path can be inlined)
    m.lockSlow()
}


func (m *Mutex) lockSlow() {
	var waitStartTime int64
	starving := false
	awoke := false
	iter := 0
	old := m.state
	for {
		// Don't spin in starvation mode, ownership is handed off to waiters
		// so we won't be able to acquire the mutex anyway.
		if old&(mutexLocked|mutexStarving) == mutexLocked && runtime_canSpin(iter) {
			// Active spinning makes sense.
			// Try to set mutexWoken flag to inform Unlock
			// to not wake other blocked goroutines.
			if !awoke && old&mutexWoken == 0 && old>>mutexWaiterShift != 0 &&
				atomic.CompareAndSwapInt32(&m.state, old, old|mutexWoken) {
				awoke = true
			}
			runtime_doSpin()
			iter++
			old = m.state
			continue
		}
		new := old
		// Don't try to acquire starving mutex, new arriving goroutines must queue.
		if old&mutexStarving == 0 {
			new |= mutexLocked
		}
		if old&(mutexLocked|mutexStarving) != 0 {
			new += 1 << mutexWaiterShift
		}
		// The current goroutine switches mutex to starvation mode.
		// But if the mutex is currently unlocked, don't do the switch.
		// Unlock expects that starving mutex has waiters, which will not
		// be true in this case.
		if starving && old&mutexLocked != 0 {
			new |= mutexStarving
		}
		if awoke {
			// The goroutine has been woken from sleep,
			// so we need to reset the flag in either case.
			if new&mutexWoken == 0 {
				throw("sync: inconsistent mutex state")
			}
			new &^= mutexWoken
		}
		if atomic.CompareAndSwapInt32(&m.state, old, new) {
			if old&(mutexLocked|mutexStarving) == 0 {
				break // locked the mutex with CAS
			}
			// If we were already waiting before, queue at the front of the queue.
			queueLifo := waitStartTime != 0
			if waitStartTime == 0 {
				waitStartTime = runtime_nanotime()
			}
			runtime_SemacquireMutex(&m.sema, queueLifo, 1)
			starving = starving || runtime_nanotime()-waitStartTime > starvationThresholdNs
			old = m.state
			if old&mutexStarving != 0 {
				// If this goroutine was woken and mutex is in starvation mode,
				// ownership was handed off to us but mutex is in somewhat
				// inconsistent state: mutexLocked is not set and we are still
				// accounted as waiter. Fix that.
				if old&(mutexLocked|mutexWoken) != 0 || old>>mutexWaiterShift == 0 {
					throw("sync: inconsistent mutex state")
				}
				delta := int32(mutexLocked - 1<<mutexWaiterShift)
				if !starving || old>>mutexWaiterShift == 1 {
					// Exit starvation mode.
					// Critical to do it here and consider wait time.
					// Starvation mode is so inefficient, that two goroutines
					// can go lock-step infinitely once they switch mutex
					// to starvation mode.
					delta -= mutexStarving
				}
				atomic.AddInt32(&m.state, delta)
				break
			}
			awoke = true
			iter = 0
		} else {
			old = m.state
		}
	}

	if race.Enabled {
		race.Acquire(unsafe.Pointer(m))
	}
}
```
unlock
```go
func (m *Mutex) Unlock() {
    if race.Enabled {
        _ = m.state
        race.Release(unsafe.Pointer(m))
    }

    // Fast path: drop lock bit.
    new := atomic.AddInt32(&m.state, -mutexLocked)
    if new != 0 {
        // Outlined slow path to allow inlining the fast path.
        // To hide unlockSlow during tracing we skip one extra frame when tracing GoUnblock.
        m.unlockSlow(new)
    }
}

func (m *Mutex) unlockSlow(new int32) {
    if (new+mutexLocked)&mutexLocked == 0 {
        fatal("sync: unlock of unlocked mutex")
    }
    if new&mutexStarving == 0 {
        old := new
        for {
            // If there are no waiters or a goroutine has already
            // been woken or grabbed the lock, no need to wake anyone.
            // In starvation mode ownership is directly handed off from unlocking
            // goroutine to the next waiter. We are not part of this chain,
            // since we did not observe mutexStarving when we unlocked the mutex above.
            // So get off the way.
            if old>>mutexWaiterShift == 0 || old&(mutexLocked|mutexWoken|mutexStarving) != 0 {
                return
            }
            // Grab the right to wake someone.
            new = (old - 1<<mutexWaiterShift) | mutexWoken
            if atomic.CompareAndSwapInt32(&m.state, old, new) {
                runtime_Semrelease(&m.sema, false, 1)
                return
            }
            old = m.state
        }
    } else {
        // Starving mode: handoff mutex ownership to the next waiter, and yield
        // our time slice so that the next waiter can start to run immediately.
        // Note: mutexLocked is not set, the waiter will set it after wakeup.
        // But mutex is still considered locked if mutexStarving is set,
        // so new coming goroutines won't acquire it.
        runtime_Semrelease(&m.sema, true, 1)
    }
}
```



















### tryLock

1.18后加入


```go
func (m *Mutex) TryLock() bool {
    old := m.state
    if old&(mutexLocked|mutexStarving) != 0 {
        return false
    }

    // There may be a goroutine waiting for the mutex, but we are
    // running now and can try to grab the mutex before that
    // goroutine wakes up.
    if !atomic.CompareAndSwapInt32(&m.state, old, old|mutexLocked) {
        return false
    }

    if race.Enabled {
        race.Acquire(unsafe.Pointer(m))
    }
    return true
}
```


## RWLock


```go
func (rw *RWMutex) Lock() {
    if race.Enabled {
        _ = rw.w.state
        race.Disable()
    }
    // First, resolve competition with other writers.
    rw.w.Lock()
    // Announce to readers there is a pending writer.
    r := rw.readerCount.Add(-rwmutexMaxReaders) + rwmutexMaxReaders
    // Wait for active readers.
    if r != 0 && rw.readerWait.Add(r) != 0 {
        runtime_SemacquireRWMutex(&rw.writerSem, false, 0)
    }
    if race.Enabled {
        race.Enable()
        race.Acquire(unsafe.Pointer(&rw.readerSem))
        race.Acquire(unsafe.Pointer(&rw.writerSem))
    }
}
```



```go
func (rw *RWMutex) Unlock() {
	if race.Enabled {
		_ = rw.w.state
		race.Release(unsafe.Pointer(&rw.readerSem))
		race.Disable()
	}

	// Announce to readers there is no active writer.
	r := rw.readerCount.Add(rwmutexMaxReaders)
	if r >= rwmutexMaxReaders {
		race.Enable()
		fatal("sync: Unlock of unlocked RWMutex")
	}
	// Unblock blocked readers, if any.
	for i := 0; i < int(r); i++ {
		runtime_Semrelease(&rw.readerSem, false, 0)
	}
	// Allow other writers to proceed.
	rw.w.Unlock()
	if race.Enabled {
		race.Enable()
	}
}
```
写锁释放后 读锁先唤醒

```go
func (rw *RWMutex) TryLock() bool {
    if race.Enabled {
        _ = rw.w.state
        race.Disable()
    }
    if !rw.w.TryLock() {
        if race.Enabled {
            race.Enable()
        }
        return false
    }
    if !rw.readerCount.CompareAndSwap(0, -rwmutexMaxReaders) {
        rw.w.Unlock()
        if race.Enabled {
            race.Enable()
        }
        return false
    }
    if race.Enabled {
        race.Enable()
        race.Acquire(unsafe.Pointer(&rw.readerSem))
        race.Acquire(unsafe.Pointer(&rw.writerSem))
    }
    return true
}

func (m *Mutex) TryLock() bool {
	old := m.state
	if old&(mutexLocked|mutexStarving) != 0 {
		return false
	}

	// There may be a goroutine waiting for the mutex, but we are
	// running now and can try to grab the mutex before that
	// goroutine wakes up.
	if !atomic.CompareAndSwapInt32(&m.state, old, old|mutexLocked) {
		return false
	}

	if race.Enabled {
		race.Acquire(unsafe.Pointer(m))
	}
	return true
}
```



## WaitGroup

类似Linux的barrier,POSIX的barrier, C++的std::barrier, Java的[CycleBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)和[CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)

```go
type WaitGroup struct {
    noCopy noCopy

    state atomic.Uint64 // high 32 bits are counter, low 32 bits are waiter count.
    sema  uint32
}
```
Add

Add adds delta, which may be negative, to the [WaitGroup] counter.
If the counter becomes zero, all goroutines blocked on [WaitGroup.Wait] are released.
If the counter goes negative, Add panics.

Note that calls with a positive delta that occur when the counter is zero must happen before a Wait.
Calls with a negative delta, or calls with a positive delta that start when the counter is greater than zero, may happen at any time.
Typically this means the calls to Add should execute before the statement creating the goroutine or other event to be waited for.
If a WaitGroup is reused to wait for several independent sets of events, new Add calls must happen after all previous Wait calls have returned.

```go
func (wg *WaitGroup) Add(delta int) {
    if race.Enabled {
        if delta < 0 {
            // Synchronize decrements with Wait.
            race.ReleaseMerge(unsafe.Pointer(wg))
        }
        race.Disable()
        defer race.Enable()
    }
    state := wg.state.Add(uint64(delta) << 32)
    v := int32(state >> 32)
    w := uint32(state)
    if race.Enabled && delta > 0 && v == int32(delta) {
        // The first increment must be synchronized with Wait.
        // Need to model this as a read, because there can be
        // several concurrent wg.counter transitions from 0.
        race.Read(unsafe.Pointer(&wg.sema))
    }
    if v < 0 {
        panic("sync: negative WaitGroup counter")
    }
    if w != 0 && delta > 0 && v == int32(delta) {
        panic("sync: WaitGroup misuse: Add called concurrently with Wait")
    }
    if v > 0 || w == 0 {
        return
    }
    // This goroutine has set counter to 0 when waiters > 0.
    // Now there can't be concurrent mutations of state:
    // - Adds must not happen concurrently with Wait,
    // - Wait does not increment waiters if it sees counter == 0.
    // Still do a cheap sanity check to detect WaitGroup misuse.
    if wg.state.Load() != state {
        panic("sync: WaitGroup misuse: Add called concurrently with Wait")
    }
    // Reset waiters count to 0.
    wg.state.Store(0)
    for ; w != 0; w-- {
        runtime_Semrelease(&wg.sema, false, 0)
    }
}
```

wait

Wait blocks until the [WaitGroup] counter is zero.
```go

func (wg *WaitGroup) Wait() {
	if race.Enabled {
		race.Disable()
	}
	for {
		state := wg.state.Load()
		v := int32(state >> 32)
		w := uint32(state)
		if v == 0 {
			// Counter is 0, no need to wait.
			if race.Enabled {
				race.Enable()
				race.Acquire(unsafe.Pointer(wg))
			}
			return
		}
		// Increment waiters count.
		if wg.state.CompareAndSwap(state, state+1) {
			if race.Enabled && w == 0 {
				// Wait must be synchronized with the first Add.
				// Need to model this is as a write to race with the read in Add.
				// As a consequence, can do the write only for the first waiter,
				// otherwise concurrent Waits will race with each other.
				race.Write(unsafe.Pointer(&wg.sema))
			}
			runtime_Semacquire(&wg.sema)
			if wg.state.Load() != 0 {
				panic("sync: WaitGroup is reused before previous Wait has returned")
			}
			if race.Enabled {
				race.Enable()
				race.Acquire(unsafe.Pointer(wg))
			}
			return
		}
	}
}
```

WaitGroup计数器值必须>=0, 否则将在更改时抛出panic


## Cond
非常类似Java里的notify/wait 需要配合Lock使用

```go
c.L.Lock()
for !condition() {
    c.Wait()
}
... make use of condition ...
c.L.Unlock()
```


```go
type Cond struct {
	noCopy noCopy

	// L is held while observing or changing the condition
	L Locker

	notify  notifyList
	checker copyChecker
}
```



Wait atomically unlocks c.L and suspends execution of the calling goroutine. After later resuming execution,
Wait locks c.L before returning. Unlike in other systems,
Wait cannot return unless awoken by [Cond.Broadcast] or [Cond.Signal].

Because c.L is not locked while Wait is waiting, the caller typically cannot assume that the condition is true when Wait returns. 
Instead, the caller should Wait in a loop:


```go
func (c *Cond) Wait() {
	c.checker.check()
	t := runtime_notifyListAdd(&c.notify)
	c.L.Unlock()
	runtime_notifyListWait(&c.notify, t)
	c.L.Lock()
}
```
Signal wakes one goroutine waiting on c, if there is any.

It is allowed but not required for the caller to hold c.L
during the call.

Signal() does not affect goroutine scheduling priority; if other goroutines
are attempting to lock c.L, they may be awoken before a "waiting" goroutine.
```go
func (c *Cond) Signal() {
	c.checker.check()
	runtime_notifyListNotifyOne(&c.notify)
}
```

## Links


