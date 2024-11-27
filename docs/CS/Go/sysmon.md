


运行时通过系统监控来触发线程的抢占、网络的轮询和垃圾回收，保证 Go 语言运行时的可用性。系统监控能够很好地解决尾延迟的问题，减少调度器调度 Goroutine 的饥饿问题并保证计时器在尽可能准确的时间触发

在新创建的线程中，我们会执行存储在 runtime.m 结构体中的 runtime.sysmon 函数启动系统监控：

```go
//go:nowritebarrierrec
func sysmon() {
    lock(&sched.lock)
    sched.nmsys++
    checkdead()
    unlock(&sched.lock)

    lasttrace := int64(0)
    idle := 0 // how many cycles in succession we had not wokeup somebody
    delay := uint32(0)

    for {
        if idle == 0 { // start with 20us sleep...
            delay = 20
        } else if idle > 50 { // start doubling the sleep after 1ms...
            delay *= 2
        }
        if delay > 10*1000 { // up to 10ms
            delay = 10 * 1000
        }
        usleep(delay)

        // sysmon should not enter deep sleep if schedtrace is enabled so that
        // it can print that information at the right time.
        //
        // It should also not enter deep sleep if there are any active P's so
        // that it can retake P's from syscalls, preempt long running G's, and
        // poll the network if all P's are busy for long stretches.
        //
        // It should wakeup from deep sleep if any P's become active either due
        // to exiting a syscall or waking up due to a timer expiring so that it
        // can resume performing those duties. If it wakes from a syscall it
        // resets idle and delay as a bet that since it had retaken a P from a
        // syscall before, it may need to do it again shortly after the
        // application starts work again. It does not reset idle when waking
        // from a timer to avoid adding system load to applications that spend
        // most of their time sleeping.
        now := nanotime()
        if debug.schedtrace <= 0 && (sched.gcwaiting.Load() || sched.npidle.Load() == gomaxprocs) {
            lock(&sched.lock)
            if sched.gcwaiting.Load() || sched.npidle.Load() == gomaxprocs {
                syscallWake := false
                next := timeSleepUntil()
                if next > now {
                    sched.sysmonwait.Store(true)
                    unlock(&sched.lock)
                    // Make wake-up period small enough
                    // for the sampling to be correct.
                    sleep := forcegcperiod / 2
                    if next-now < sleep {
                        sleep = next - now
                    }
                    shouldRelax := sleep >= osRelaxMinNS
                    if shouldRelax {
                        osRelax(true)
                    }
                    syscallWake = notetsleep(&sched.sysmonnote, sleep)
                    if shouldRelax {
                        osRelax(false)
                    }
                    lock(&sched.lock)
                    sched.sysmonwait.Store(false)
                    noteclear(&sched.sysmonnote)
                }
                if syscallWake {
                    idle = 0
                    delay = 20
                }
            }
            unlock(&sched.lock)
        }

        lock(&sched.sysmonlock)
        // Update now in case we blocked on sysmonnote or spent a long time
        // blocked on schedlock or sysmonlock above.
        now = nanotime()

        // trigger libc interceptors if needed
        if *cgo_yield != nil {
            asmcgocall(*cgo_yield, nil)
        }
        // poll network if not polled for more than 10ms
        lastpoll := sched.lastpoll.Load()
        if netpollinited() && lastpoll != 0 && lastpoll+10*1000*1000 < now {
            sched.lastpoll.CompareAndSwap(lastpoll, now)
            list, delta := netpoll(0) // non-blocking - returns list of goroutines
            if !list.empty() {
                // Need to decrement number of idle locked M's
                // (pretending that one more is running) before injectglist.
                // Otherwise it can lead to the following situation:
                // injectglist grabs all P's but before it starts M's to run the P's,
                // another M returns from syscall, finishes running its G,
                // observes that there is no work to do and no other running M's
                // and reports deadlock.
                incidlelocked(-1)
                injectglist(&list)
                incidlelocked(1)
                netpollAdjustWaiters(delta)
            }
        }
        if GOOS == "netbsd" && needSysmonWorkaround {
            // netpoll is responsible for waiting for timer
            // expiration, so we typically don't have to worry
            // about starting an M to service timers. (Note that
            // sleep for timeSleepUntil above simply ensures sysmon
            // starts running again when that timer expiration may
            // cause Go code to run again).
            //
            // However, netbsd has a kernel bug that sometimes
            // misses netpollBreak wake-ups, which can lead to
            // unbounded delays servicing timers. If we detect this
            // overrun, then startm to get something to handle the
            // timer.
            //
            // See issue 42515 and
            // https://gnats.netbsd.org/cgi-bin/query-pr-single.pl?number=50094.
            if next := timeSleepUntil(); next < now {
                startm(nil, false, false)
            }
        }
        if scavenger.sysmonWake.Load() != 0 {
            // Kick the scavenger awake if someone requested it.
            scavenger.wake()
        }
        // retake P's blocked in syscalls
        // and preempt long running G's
        if retake(now) != 0 {
            idle = 0
        } else {
            idle++
        }
        // check if we need to force a GC
        if t := (gcTrigger{kind: gcTriggerTime, now: now}); t.test() && forcegc.idle.Load() {
            lock(&forcegc.lock)
            forcegc.idle.Store(false)
            var list gList
            list.push(forcegc.g)
            injectglist(&list)
            unlock(&forcegc.lock)
        }
        if debug.schedtrace > 0 && lasttrace+int64(debug.schedtrace)*1000000 <= now {
            lasttrace = now
            schedtrace(debug.scheddetail > 0)
        }
        unlock(&sched.sysmonlock)
    }
}
```
运行时刚刚调用上述函数时，会先通过 runtime.checkdead 检查是否存在死锁，然后进入核心的监控循环；系统监控在每次循环开始时都会通过 usleep 挂起当前线程，该函数的参数是微秒，运行时会遵循以下的规则决定休眠时间：
- 初始的休眠时间是 20μs；
- 最长的休眠时间是 10ms；
- 当系统监控在 50 个循环中都没有唤醒 Goroutine 时，休眠时间在每个循环都会倍增；

当程序趋于稳定之后，系统监控的触发时间就会稳定在 10ms。它除了会检查死锁之外，还会在循环中完成以下的工作：
- 运行计时器 — 获取下一个需要被触发的计时器；
- 轮询网络 — 获取需要处理的到期文件描述符；
- 抢占处理器 — 抢占运行时间较长的或者处于系统调用的 Goroutine；
- 垃圾回收 — 在满足条件时触发垃圾收集回收内存；

检查死锁
系统监控通过 runtime.checkdead 检查运行时是否发生了死锁，我们可以将检查死锁的过程分成以下三个步骤：
1. 检查是否存在正在运行的线程；
2. 检查是否存在正在运行的 Goroutine；
3. 检查处理器上是否存在计时器；

```go
func sysmon() {
    // ...
    lock(&sched.lock)
    sched.nmsys++
    checkdead()
    unlock(&sched.lock)
    // ...
}

func checkdead() {
    assertLockHeld(&sched.lock)

    // For -buildmode=c-shared or -buildmode=c-archive it's OK if
    // there are no running goroutines. The calling program is
    // assumed to be running.
    if islibrary || isarchive {
        return
    }

    // If we are dying because of a signal caught on an already idle thread,
    // freezetheworld will cause all running threads to block.
    // And runtime will essentially enter into deadlock state,
    // except that there is a thread that will call exit soon.
    if panicking.Load() > 0 {
        return
    }

    // If we are not running under cgo, but we have an extra M then account
    // for it. (It is possible to have an extra M on Windows without cgo to
    // accommodate callbacks created by syscall.NewCallback. See issue #6751
    // for details.)
    var run0 int32
    if !iscgo && cgoHasExtraM && extraMLength.Load() > 0 {
        run0 = 1
    }

    run := mcount() - sched.nmidle - sched.nmidlelocked - sched.nmsys
    if run > run0 {
        return
    }
    if run < 0 {
        print("runtime: checkdead: nmidle=", sched.nmidle, " nmidlelocked=", sched.nmidlelocked, " mcount=", mcount(), " nmsys=", sched.nmsys, "\n")
        unlock(&sched.lock)
        throw("checkdead: inconsistent counts")
    }

    grunning := 0
    forEachG(func(gp *g) {
        if isSystemGoroutine(gp, false) {
            return
        }
        s := readgstatus(gp)
        switch s &^ _Gscan {
            case _Gwaiting,
            _Gpreempted:
            grunning++
            case _Grunnable,
            _Grunning,
            _Gsyscall:
            print("runtime: checkdead: find g ", gp.goid, " in status ", s, "\n")
            unlock(&sched.lock)
            throw("checkdead: runnable g")
        }
    })
    if grunning == 0 { // possible if main goroutine calls runtime·Goexit()
        unlock(&sched.lock) // unlock so that GODEBUG=scheddetail=1 doesn't hang
        fatal("no goroutines (main called runtime.Goexit) - deadlock!")
    }

    // Maybe jump time forward for playground.
    if faketime != 0 {
        if when := timeSleepUntil(); when < maxWhen {
            faketime = when

            // Start an M to steal the timer.
            pp, _ := pidleget(faketime)
            if pp == nil {
                // There should always be a free P since
                // nothing is running.
                unlock(&sched.lock)
                throw("checkdead: no p for timer")
            }
            mp := mget()
            if mp == nil {
                // There should always be a free M since
                // nothing is running.
                unlock(&sched.lock)
                throw("checkdead: no m for timer")
            }
            // M must be spinning to steal. We set this to be
            // explicit, but since this is the only M it would
            // become spinning on its own anyways.
            sched.nmspinning.Add(1)
            mp.spinning = true
            mp.nextp.set(pp)
            notewakeup(&mp.park)
            return
        }
    }

    // There are no goroutines running, so we can look at the P's.
    for _, pp := range allp {
        if len(pp.timers.heap) > 0 {
            return
        }
    }

    unlock(&sched.lock) // unlock so that GODEBUG=scheddetail=1 doesn't hang
    fatal("all goroutines are asleep - deadlock!")
} 
```

1. runtime.mcount 根据下一个待创建的线程 id 和释放的线程数得到系统中存在的线程数；
2. nmidle 是处于空闲状态的线程数量；
3. nmidlelocked 是处于锁定状态的线程数量；
4. nmsys 是处于系统调用的线程数量；


利用上述几个线程相关数据，我们可以得到正在运行的线程数，如果线程数量大于 0，说明当前程序不存在死锁；如果线程数小于 0，说明当前程序的状态不一致；如果线程数等于 0，我们需要进一步检查程序的运行状态：
1. 当存在 Goroutine 处于 _Grunnable、_Grunning 和 _Gsyscall 状态时，意味着程序发生了死锁；
2. 当所有的 Goroutine 都处于 _Gidle、_Gdead 和 _Gcopystack 状态时，意味着主程序调用了 runtime.goexit；
   当运行时存在等待的 Goroutine 并且不存在正在运行的 Goroutine 时，我们会检查处理器中存在的计时器1
   如果处理器中存在等待的计时器，那么所有的 Goroutine 陷入休眠状态是合理的，不过如果不存在等待的计时器，运行时就会直接报错并退出程序


运行计时器
在系统监控的循环中，我们通过 runtime.nanotime 和 runtime.timeSleepUntil 获取当前时间和计时器下一次需要唤醒的时间；当前调度器需要执行垃圾回收或者所有处理器都处于闲置状态时，如果没有需要触发的计时器，那么系统监控可以暂时陷入休眠：

```go
func sysmon() {
    // ...
    for {
        // ...
        // sysmon should not enter deep sleep if schedtrace is enabled so that
        // it can print that information at the right time.
        //
        // It should also not enter deep sleep if there are any active P's so
        // that it can retake P's from syscalls, preempt long running G's, and
        // poll the network if all P's are busy for long stretches.
        //
        // It should wakeup from deep sleep if any P's become active either due
        // to exiting a syscall or waking up due to a timer expiring so that it
        // can resume performing those duties. If it wakes from a syscall it
        // resets idle and delay as a bet that since it had retaken a P from a
        // syscall before, it may need to do it again shortly after the
        // application starts work again. It does not reset idle when waking
        // from a timer to avoid adding system load to applications that spend
        // most of their time sleeping.
        now := nanotime()
        if debug.schedtrace <= 0 && (sched.gcwaiting.Load() || sched.npidle.Load() == gomaxprocs) {
            lock(&sched.lock)
            if sched.gcwaiting.Load() || sched.npidle.Load() == gomaxprocs {
                syscallWake := false
                next := timeSleepUntil()
                if next > now {
                    sched.sysmonwait.Store(true)
                    unlock(&sched.lock)
                    // Make wake-up period small enough
                    // for the sampling to be correct.
                    sleep := forcegcperiod / 2
                    if next-now < sleep {
                        sleep = next - now
                    }
                    shouldRelax := sleep >= osRelaxMinNS
                    if shouldRelax {
                        osRelax(true)
                    }
                    syscallWake = notetsleep(&sched.sysmonnote, sleep)
                    if shouldRelax {
                        osRelax(false)
                    }
                    lock(&sched.lock)
                    sched.sysmonwait.Store(false)
                    noteclear(&sched.sysmonnote)
                }
                if syscallWake {
                    idle = 0
                    delay = 20
                }
            }
            unlock(&sched.lock)
        }
        // ...
    }
}
```


休眠的时间会依据强制 GC 的周期 forcegcperiod 和计时器下次触发的时间确定，runtime.notesleep 会使用信号量同步系统监控即将进入休眠的状态。当系统监控被唤醒之后，我们会重新计算当前时间和下一个计时器需要触发的时间、调用 runtime.noteclear 通知系统监控被唤醒并重置休眠的间隔。
如果在这之后，我们发现下一个计时器需要触发的时间小于当前时间，这也就说明所有的线程可能正在忙于运行 Goroutine，系统监控会启动新的线程来触发计时器，避免计时器的到期时间有较大的偏差

轮询网络
如果上一次轮询网络已经过去了 10ms，那么系统监控还会在循环中轮询网络，检查是否有待执行的文件描述符

```go
func sysmon() {
    // ...
    for {
        // ...
        // poll network if not polled for more than 10ms
        lastpoll := sched.lastpoll.Load()
        if netpollinited() && lastpoll != 0 && lastpoll+10*1000*1000 < now {
            sched.lastpoll.CompareAndSwap(lastpoll, now)
            list, delta := netpoll(0) // non-blocking - returns list of goroutines
            if !list.empty() {
                // Need to decrement number of idle locked M's
                // (pretending that one more is running) before injectglist.
                // Otherwise it can lead to the following situation:
                // injectglist grabs all P's but before it starts M's to run the P's,
                // another M returns from syscall, finishes running its G,
                // observes that there is no work to do and no other running M's
                // and reports deadlock.
                incidlelocked(-1)
                injectglist(&list)
                incidlelocked(1)
                netpollAdjustWaiters(delta)
            }
        }
        // ...
    }
}
```
上述函数会非阻塞地调用 runtime.netpoll 检查待执行的文件描述符并通过 runtime.injectglist 将所有处于就绪状态的 Goroutine 加入全局运行队列中：


```go
func injectglist(glist *gList) {
    if glist.empty() {
        return
    }
    trace := traceAcquire()
    if trace.ok() {
        for gp := glist.head.ptr(); gp != nil; gp = gp.schedlink.ptr() {
            trace.GoUnpark(gp, 0)
        }
        traceRelease(trace)
    }

    // Mark all the goroutines as runnable before we put them
    // on the run queues.
    head := glist.head.ptr()
    var tail *g
    qsize := 0
    for gp := head; gp != nil; gp = gp.schedlink.ptr() {
        tail = gp
        qsize++
        casgstatus(gp, _Gwaiting, _Grunnable)
    }

    // Turn the gList into a gQueue.
    var q gQueue
    q.head.set(head)
    q.tail.set(tail)
    *glist = gList{}

    startIdle := func(n int) {
        for i := 0; i < n; i++ {
            mp := acquirem() // See comment in startm.
            lock(&sched.lock)

            pp, _ := pidlegetSpinning(0)
            if pp == nil {
                unlock(&sched.lock)
                releasem(mp)
                break
            }

            startm(pp, false, true)
            unlock(&sched.lock)
            releasem(mp)
        }
    }

    pp := getg().m.p.ptr()
    if pp == nil {
        lock(&sched.lock)
        globrunqputbatch(&q, int32(qsize))
        unlock(&sched.lock)
        startIdle(qsize)
        return
    }

    npidle := int(sched.npidle.Load())
    var (
        globq gQueue
        n     int
    )
    for n = 0; n < npidle && !q.empty(); n++ {
        g := q.pop()
        globq.pushBack(g)
    }
    if n > 0 {
        lock(&sched.lock)
        globrunqputbatch(&globq, int32(n))
        unlock(&sched.lock)
        startIdle(n)
        qsize -= n
    }

    if !q.empty() {
        runqputbatch(pp, &q, qsize)
    }

    // Some P's might have become idle after we loaded `sched.npidle`
    // but before any goroutines were added to the queue, which could
    // lead to idle P's when there is work available in the global queue.
    // That could potentially last until other goroutines become ready
    // to run. That said, we need to find a way to hedge
    //
    // Calling wakep() here is the best bet, it will do nothing in the
    // common case (no racing on `sched.npidle`), while it could wake one
    // more P to execute G's, which might end up with >1 P's: the first one
    // wakes another P and so forth until there is no more work, but this
    // ought to be an extremely rare case.
    //
    // Also see "Worker thread parking/unparking" comment at the top of the file for details.
    wakep()
}
```

该函数会将所有 Goroutine 的状态从 _Gwaiting 切换至 _Grunnable 并加入全局运行队列等待运行，如果当前程序中存在空闲的处理器，就会通过 runtime.startm 函数启动线程来执行这些任务

抢占处理器
系统调用会在循环中调用 runtime.retake 函数抢占处于运行或者系统调用中的处理器，该函数会遍历运行时的全局处理器，每个处理器都存储了一个 runtime.sysmontick 结构体：

```go
type sysmontick struct {
schedtick   uint32
syscalltick uint32
schedwhen   int64
syscallwhen int64
}
```


该结构体中的四个字段分别存储了处理器的调度次数、处理器上次调度时间、系统调用的次数以及系统调用的时间。runtime.retake 中的循环包含了两种不同的抢占逻辑：


```go
func retake(now int64) uint32 {
    n := 0
    // Prevent allp slice changes. This lock will be completely
    // uncontended unless we're already stopping the world.
    lock(&allpLock)
    // We can't use a range loop over allp because we may
    // temporarily drop the allpLock. Hence, we need to re-fetch
    // allp each time around the loop.
    for i := 0; i < len(allp); i++ {
        pp := allp[i]
        if pp == nil {
            // This can happen if procresize has grown
            // allp but not yet created new Ps.
            continue
        }
        pd := &pp.sysmontick
        s := pp.status
        sysretake := false
        if s == _Prunning || s == _Psyscall {
            // Preempt G if it's running on the same schedtick for
            // too long. This could be from a single long-running
            // goroutine or a sequence of goroutines run via
            // runnext, which share a single schedtick time slice.
            t := int64(pp.schedtick)
            if int64(pd.schedtick) != t {
                pd.schedtick = uint32(t)
                pd.schedwhen = now
            } else if pd.schedwhen+forcePreemptNS <= now {
                preemptone(pp)
                // In case of syscall, preemptone() doesn't
                // work, because there is no M wired to P.
                sysretake = true
            }
        }
        if s == _Psyscall {
            // Retake P from syscall if it's there for more than 1 sysmon tick (at least 20us).
            t := int64(pp.syscalltick)
            if !sysretake && int64(pd.syscalltick) != t {
                pd.syscalltick = uint32(t)
                pd.syscallwhen = now
                continue
            }
            // On the one hand we don't want to retake Ps if there is no other work to do,
            // but on the other hand we want to retake them eventually
            // because they can prevent the sysmon thread from deep sleep.
            if runqempty(pp) && sched.nmspinning.Load()+sched.npidle.Load() > 0 && pd.syscallwhen+10*1000*1000 > now {
                continue
            }
            // Drop allpLock so we can take sched.lock.
            unlock(&allpLock)
            // Need to decrement number of idle locked M's
            // (pretending that one more is running) before the CAS.
            // Otherwise the M from which we retake can exit the syscall,
            // increment nmidle and report deadlock.
            incidlelocked(-1)
            trace := traceAcquire()
            if atomic.Cas(&pp.status, s, _Pidle) {
                if trace.ok() {
                    trace.ProcSteal(pp, false)
                    traceRelease(trace)
                }
                n++
                pp.syscalltick++
                handoffp(pp)
            } else if trace.ok() {
                traceRelease(trace)
            }
            incidlelocked(1)
            lock(&allpLock)
        }
    }
    unlock(&allpLock)
    return uint32(n)
}
```


1. 当处理器处于 _Prunning 或者 _Psyscall 状态时，如果上一次触发调度的时间已经过去了 10ms，我们就会通过 runtime.preemptone 抢占当前处理器；
2. 当处理器处于 _Psyscall 状态时，在满足以下两种情况下会调用 runtime.handoffp 让出处理器的使用权：
   a. 当处理器的运行队列不为空或者不存在空闲处理器时2；
   b. 当系统调用时间超过了 10ms 时3；
   系统监控通过在循环中抢占处理器来避免同一个 Goroutine 占用线程太长时间造成饥饿问题

垃圾回收
在最后，系统监控还会决定是否需要触发强制垃圾回收，runtime.sysmon 会构建 runtime.gcTrigger 结构体并调用 runtime.gcTrigger.test 函数判断是否需要触发垃圾回收：



```go
func sysmon() {
    // ...
    for {
        // ...
        if t := (gcTrigger{kind: gcTriggerTime, now: now}); t.test() && forcegc.idle.Load() {
            lock(&forcegc.lock)
            forcegc.idle.Store(false)
            var list gList
            list.push(forcegc.g)
            injectglist(&list)
            unlock(&forcegc.lock)
        }
        // ...
    }
}
```

如果需要触发垃圾回收，我们会将用于垃圾回收的 Goroutine 加入全局队列，让调度器选择合适的处理器去执行









