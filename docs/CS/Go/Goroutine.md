## Introduction

Go进程中的众多协程其实依托于线程，借助操作系统将线程调度到CPU执行，从而最终执行协程。

上下文切换只是PC SP DX的修改 创建最初的m0 创建最初的g0

## GMP



在GMP模型中，

- G代表的是Go语言中的协程（Goroutine），

- M代表的是执行运算单元, Go会将其与操作系统的线程绑定

- P代表的是Go逻辑处理器（Processor），Go语言为了方便协程调度与缓存，抽象出了逻辑处理器。

  默认情况下P的数量等于CPU逻辑核的数量 可以使用runtime.GOMAXPROCS来修改 每个P都有一个本地goroutine队列

> 一般来讲，程序运行时就将GOMAXPROCS大小设置为CPU核数，可让Go程序充分利用CPU。 在某些IO密集型的应用里，这个值可能并不意味着性能最好。 理论上当某个Goroutine进入系统调用时，会有一个新的M被启用或创建，继续占满CPU。 但由于Go调度器检测到M被阻塞是有一定延迟的，也即旧的M被阻塞和新的M得到运行之间是有一定间隔的，所以在IO密集型应用中不妨把GOMAXPROCS设置的大一些，或许会有好的效果。

最早的Go(1.0以下)运行时模型是GM模型
1. 用一个全局的mutex保护着一个全局的runq（就绪队列），所有goroutine的创建、结束，以及 调度等操作都要先获得锁，造成对锁的争用异常严重
2. G的每次执行都会被分发到随机的M上，造成在不同M之间频繁切换，破坏了程序的局部性， 主要原因也是因为只有一个全局的runq。例如在一个chan上互相唤醒的两个goroutine就会面临这种 问题。还有一点就是新创建的G会被创建它的M放入全局runq中，但是会被另一个M调度执行，也 会造成不必要的开销
3. 每个M都会关联一个内存分配缓存mcache，造成了大量的内存开销，进一步使数据的局部性 变差。实际上只有执行Go代码的M才真地需要mcache，那些阻塞在系统调用中的M根本不需要， 而实际执行Go代码的M可能仅占M总数的1%。
4. 在存在系统调用的情况下，工作线程经常被阻塞和解除阻塞，从而增加了很多开销

在任一时刻，一个P可能在其本地包含多个G，同时，一个P在任一时刻只能绑定一个M。
  图14-9中没有涵盖的信息是：一个G并不是固定绑定同一个P的，有很多情况（例如P在运行时被销毁）会导致一个P中的G转移到其他的P中。
  同样的，一个P只能对应一个M，但是具体对应的是哪一个M也是不固定的。一个M可能在某些时候转移到其他的P中执行



实际上一共有三种 g：
1. 执行用户代码的 g； 使用 go 关键字启动的 goroutine，也是我们接触最多的一类 g
2. 执行调度器代码的 g，也即是 g0； g0 在底层和其他 g 是一样的数据结构，但是性质上有很大的区别，首先 g0 的栈大小是固定的，比如在 Linux 或者其他 Unix-like 的系统上一般是固定 8MB，不能动态伸缩，而普通的 g 初始栈大小是 2KB，可按需扩展 每个线程被创建出来之时都需要操作系统为之分配一个初始固定的线程栈，就是前面说的 8MB 大小的栈，g0 栈就代表了这个线程栈，因此每一个 m 都需要绑定一个 g0 来执行调度器代码，然后跳转到执行用户代码的地方。
3. 执行 runtime.main 初始化工作的 main goroutine；


启动一个新的 goroutine 是通过 go 关键字来完成的，而 go compiler 会在编译期间利用 cmd/compile/internal/gc.state.stmt 和 cmd/compile/internal/gc.state.call 这两个函数将 go 关键字翻译成 runtime.newproc 函数调用，而 runtime.newproc 接收了函数指针和其大小之后，会获取 goroutine 和调用处的程序计数器，接着再调用 runtime.newproc1


运行Go程序时 通过一个Go的runtime函数完成初始化工作(包括schedule和GC) 最开始会创建m0和g0 为main生成一个goroutine由m0执行



m0全局变量 与m0绑定的g0也是全局变量






每个线程都有一个特殊goroutine g0用于调度

```go
type m struct {
   g0      *g     // goroutine with scheduling stack
   ...
}
```

协程g0运行在操作系统线程栈上，其作用主要是执行协程调度的一系列运行时代码，而一般的协程无差别地用于执行用户代码。很显然，执行用户代码的任何协程都不适合进行全局调度

在用户协程退出或者被抢占时，意味着需要重新执行协程调度，这时需要从用户协程g切换到协程g0，协程g与协程g0的对应关系如图15-2所示。要注意的是，每个线程的内部都在完成这样的切换与调度循环


协程经历g→g0→g的过程，完成了一次调度循环。
和线程类似，协程切换的过程叫作协程的上下文切换。当某一个协程g执行上下文切换时需要保存当前协程的执行现场，才能够在后续切换回g协程时正常执行。
协程的执行现场存储在g.gobuf结构体中，g.gobuf结构体主要保存CPU中几个重要的寄存器值，分别是rsp、rip、rbp。
rsp寄存器始终指向函数调用栈栈顶，rip寄存器指向程序要执行的下一条指令的地址，rbp存储了函数栈帧的起始位置
 ```go
 
type g struct {
	// Stack parameters.
	// stack describes the actual stack memory: [stack.lo, stack.hi).
	// stackguard0 is the stack pointer compared in the Go stack growth prologue.
	// It is stack.lo+StackGuard normally, but can be StackPreempt to trigger a preemption.
	// stackguard1 is the stack pointer compared in the //go:systemstack stack growth prologue.
	// It is stack.lo+StackGuard on g0 and gsignal stacks.
	// It is ~0 on other goroutine stacks, to trigger a call to morestackc (and crash).
	stack       stack  
	sched     gobuf
	...
		
}
 ```

调度循环指从调度协程g0开始，找到接下来将要运行的协程g、再从协程g切换到协程g0开始新一轮调度的过程。它和上下文切换类似，但是上下文切换关注的是具体切换的状态，而调度循环关注的是调度的流程。
图15-4所示为调度循环的整个流程。从协程g0调度到协程g，经历了从schedule函数到execute函数再到gogo函数的过程。
其中，schedule函数处理具体的调度策略，选择下一个要执行的协程；execute函数执行一些具体的状态转移、协程g与结构体m之间的绑定等操作；gogo函数是与操作系统有关的函数，用于完成栈的切换及CPU寄存器的恢复。

执行完毕后，切换到协程g执行。当协程g主动让渡、被抢占或退出后，又会切换到协程g0进入第二轮调度。在从协程g切换回协程g0时，mcall函数用于保存当前协程的执行现场，并切换到协程g0继续执行，mcall函数仍



work steal

goroutine创建时优先加入本地队列 可被其它P/M窃取

## main

The main goroutine


```go
func main() {
    mp := getg().m

    // Racectx of m0->g0 is used only as the parent of the main goroutine.
    // It must not be used for anything else.
    mp.g0.racectx = 0

    // Max stack size is 1 GB on 64-bit, 250 MB on 32-bit.
    // Using decimal instead of binary GB and MB because
    // they look nicer in the stack overflow failure message.
    if goarch.PtrSize == 8 {
        maxstacksize = 1000000000
    } else {
        maxstacksize = 250000000
    }

    // An upper limit for max stack size. Used to avoid random crashes
    // after calling SetMaxStack and trying to allocate a stack that is too big,
    // since stackalloc works with 32-bit sizes.
    maxstackceiling = 2 * maxstacksize

    // Allow newproc to start new Ms.
    mainStarted = true

    if haveSysmon {
        systemstack(func() {
            newm(sysmon, nil, -1)
        })
    }

    // Lock the main goroutine onto this, the main OS thread,
    // during initialization. Most programs won't care, but a few
    // do require certain calls to be made by the main thread.
    // Those can arrange for main.main to run in the main thread
    // by calling runtime.LockOSThread during initialization
    // to preserve the lock.
    lockOSThread()

    if mp != &m0 {
        throw("runtime.main not on m0")
    }

    // Record when the world started.
    // Must be before doInit for tracing init.
    runtimeInitTime = nanotime()
    if runtimeInitTime == 0 {
        throw("nanotime returning zero")
    }

    if debug.inittrace != 0 {
        inittrace.id = getg().goid
        inittrace.active = true
    }

    doInit(runtime_inittasks) // Must be before defer.

    // Defer unlock so that runtime.Goexit during init does the unlock too.
    needUnlock := true
    defer func() {
        if needUnlock {
            unlockOSThread()
        }
    }()

    gcenable()

    main_init_done = make(chan bool)
    if iscgo {
        if _cgo_pthread_key_created == nil {
            throw("_cgo_pthread_key_created missing")
        }

        if _cgo_thread_start == nil {
            throw("_cgo_thread_start missing")
        }
        if GOOS != "windows" {
            if _cgo_setenv == nil {
                throw("_cgo_setenv missing")
            }
            if _cgo_unsetenv == nil {
                throw("_cgo_unsetenv missing")
            }
        }
        if _cgo_notify_runtime_init_done == nil {
            throw("_cgo_notify_runtime_init_done missing")
        }

        // Set the x_crosscall2_ptr C function pointer variable point to crosscall2.
        if set_crosscall2 == nil {
            throw("set_crosscall2 missing")
        }
        set_crosscall2()

        // Start the template thread in case we enter Go from
        // a C-created thread and need to create a new thread.
        startTemplateThread()
        cgocall(_cgo_notify_runtime_init_done, nil)
    }

    // Run the initializing tasks. Depending on build mode this
    // list can arrive a few different ways, but it will always
    // contain the init tasks computed by the linker for all the
    // packages in the program (excluding those added at runtime
    // by package plugin). Run through the modules in dependency
    // order (the order they are initialized by the dynamic
    // loader, i.e. they are added to the moduledata linked list).
    for m := &firstmoduledata; m != nil; m = m.next {
        doInit(m.inittasks)
    }

    // Disable init tracing after main init done to avoid overhead
    // of collecting statistics in malloc and newproc
    inittrace.active = false

    close(main_init_done)

    needUnlock = false
    unlockOSThread()

    if isarchive || islibrary {
        // A program compiled with -buildmode=c-archive or c-shared
        // has a main, but it is not executed.
        return
    }
    fn := main_main // make an indirect call, as the linker doesn't know the address of the main package when laying down the runtime
    fn()
    if raceenabled {
        runExitHooks(0) // run hooks now, since racefini does not return
        racefini()
    }

    // Make racy client program work: if panicking on
    // another goroutine at the same time as main returns,
    // let the other goroutine finish printing the panic trace.
    // Once it does, it will exit. See issues 3934 and 20018.
    if runningPanicDefers.Load() != 0 {
        // Running deferred functions should not take long.
        for c := 0; c < 1000; c++ {
            if runningPanicDefers.Load() == 0 {
                break
            }
            Gosched()
        }
    }
    if panicking.Load() != 0 {
        gopark(nil, nil, waitReasonPanicWait, traceBlockForever, 1)
    }
    runExitHooks(0)

    exit(0)
    for {
        var x *int32
        *x = 0
    }
}
```
runtime.newm 会创建一个存储待执行函数和处理器的新结构体 runtime.m。运行时执行系统监控不需要处理器，系统监控的 Goroutine 会直接在创建的线程上运行

```go
func newm(fn func(), pp *p, id int64) {
    // allocm adds a new M to allm, but they do not start until created by
    // the OS in newm1 or the template thread.
    //
    // doAllThreadsSyscall requires that every M in allm will eventually
    // start and be signal-able, even with a STW.
    //
    // Disable preemption here until we start the thread to ensure that
    // newm is not preempted between allocm and starting the new thread,
    // ensuring that anything added to allm is guaranteed to eventually
    // start.
    acquirem()

    mp := allocm(pp, fn, id)
    mp.nextp.set(pp)
    mp.sigmask = initSigmask
    if gp := getg(); gp != nil && gp.m != nil && (gp.m.lockedExt != 0 || gp.m.incgo) && GOOS != "plan9" {
        // We're on a locked M or a thread that may have been
        // started by C. The kernel state of this thread may
        // be strange (the user may have locked it for that
        // purpose). We don't want to clone that into another
        // thread. Instead, ask a known-good thread to create
        // the thread for us.
        //
        // This is disabled on Plan 9. See golang.org/issue/22227.
        //
        // TODO: This may be unnecessary on Windows, which
        // doesn't model thread creation off fork.
        lock(&newmHandoff.lock)
        if newmHandoff.haveTemplateThread == 0 {
            throw("on a locked thread with no template thread")
        }
        mp.schedlink = newmHandoff.newm
        newmHandoff.newm.set(mp)
        if newmHandoff.waiting {
            newmHandoff.waiting = false
            notewakeup(&newmHandoff.wake)
        }
        unlock(&newmHandoff.lock)
        // The M has not started yet, but the template thread does not
        // participate in STW, so it will always process queued Ms and
        // it is safe to releasem.
        releasem(getg().m)
        return
    }
    newm1(mp)
    releasem(getg().m)
}
```

new

```go
func newm1(mp *m) {
    if iscgo {
        var ts cgothreadstart
        if _cgo_thread_start == nil {
            throw("_cgo_thread_start missing")
        }
        ts.g.set(mp.g0)
        ts.tls = (*uint64)(unsafe.Pointer(&mp.tls[0]))
        ts.fn = unsafe.Pointer(abi.FuncPCABI0(mstart))
        if msanenabled {
            msanwrite(unsafe.Pointer(&ts), unsafe.Sizeof(ts))
        }
        if asanenabled {
            asanwrite(unsafe.Pointer(&ts), unsafe.Sizeof(ts))
        }
        execLock.rlock() // Prevent process clone.
        asmcgocall(_cgo_thread_start, unsafe.Pointer(&ts))
        execLock.runlock()
        return
    }
    execLock.rlock() // Prevent process clone.
    newosproc(mp)
    execLock.runlock()
}
```
runtime.newm1 会调用特定平台的 runtime.newsproc 通过系统调用 clone 创建一个新的线程并在新的线程中执行 runtime.mstart：

```go
//go:nowritebarrierrec
func newosproc(mp *m) {
    stk := unsafe.Pointer(mp.g0.stack.hi)
    if false {
        print("newosproc stk=", stk, " m=", mp, " g=", mp.g0, " id=", mp.id, " ostk=", &mp, "\n")
    }

    // Initialize an attribute object.
    var attr pthreadattr
    var err int32
    err = pthread_attr_init(&attr)
    if err != 0 {
        writeErrStr(failthreadcreate)
        exit(1)
    }

    // Find out OS stack size for our own stack guard.
    var stacksize uintptr
    if pthread_attr_getstacksize(&attr, &stacksize) != 0 {
        writeErrStr(failthreadcreate)
        exit(1)
    }
    mp.g0.stack.hi = stacksize // for mstart

    // Tell the pthread library we won't join with this thread.
    if pthread_attr_setdetachstate(&attr, _PTHREAD_CREATE_DETACHED) != 0 {
        writeErrStr(failthreadcreate)
        exit(1)
    }

    // Finally, create the thread. It starts at mstart_stub, which does some low-level
    // setup and then calls mstart.
    var oset sigset
    sigprocmask(_SIG_SETMASK, &sigset_all, &oset)
    err = retryOnEAGAIN(func() int32 {
        return pthread_create(&attr, abi.FuncPCABI0(mstart_stub), unsafe.Pointer(mp))
    })
    sigprocmask(_SIG_SETMASK, &oset, nil)
    if err != 0 {
        writeErrStr(failthreadcreate)
        exit(1)
    }
}
```

## schedule

调度的核心策略位于schedule函数
Go scheduler 的调度 goroutine 过程中所调用的核心函数链如下：

```
runtime.schedule --> runtime.execute --> runtime.gogo --> goroutine code --> runtime.goexit --> runtime.goexit1 
  --> runtime.mcall --> runtime.goexit0 --> runtime.schedule
```
Go scheduler 会不断循环调用 runtime.schedule() 去调度 goroutines，而每个 goroutine 执行完成并退出之后，会再次调用 runtime.schedule()，使得调度器回到调度循环去执行其他的 goroutine，不断循环，永不停歇。
当我们使用 go 关键字启动一个新 goroutine 时，最终会调用 runtime.newproc --> runtime.newproc1，来得到 g，runtime.newproc1 会先从 P 的 gfree 缓存链表中查找可用的 g，若缓存未生效，则会新创建 g 给当前的业务函数，最后这个 g 会被传给 runtime.gogo 去真正执行



调度时机


主动让渡

协程可以选择主动让渡自己的执行权利，这主要是通过用户在代码中执行runtime.Gosched函数实现的。
在大多数情况下，用户并不需要执行此函数，因为Go语言编译器会在调用函数之前插入检查代码，判断该协程是否需要被抢占。



被动
被动调度指协程在休眠、channel通道堵塞、网络I/O堵塞、执行垃圾回收而暂停时，被动让渡自己执行权利的过程。
被动调度具有重要的意义，可以保证最大化利用CPU的资源。根据被动调度的原因不同，调度器可能执行一些特殊的操作。
由于被动调度仍然是协程发起的操作，因此其调度的时机相对明确。
和主动调度类似的是，被动调度需要先从当前协程切换到协程g0，更新协程的状态并解绑与M的关系，重新调度。
和主动调度不同的是，被动调度不会将G放入全局运行队列，因为当前G的状态不是_Grunnable而是_Gwaiting，所以，被动调度需要一个额外的唤醒机制

当通道中暂时没有数据时，会调用gopark函数完成被动调度，gopark函数是被动调度的核心逻辑
gopark函数最后会调用park_m，该函数会解除G和M之间的关系，根据执行被动调度的原因不同，执行不同的waitunlockf函数，并开始新一轮调度

如果当前协程需要被唤醒，那么会先将协程的状态从_Gwaiting转换为_Grunnable，并添加到当前P的局部运行队列中


```go
func gopark(unlockf func(*g, unsafe.Pointer) bool, lock unsafe.Pointer, reason waitReason, traceReason traceBlockReason, traceskip int) {
    if reason != waitReasonSleep {
        checkTimeouts() // timeouts may expire while two goroutines keep the scheduler busy
    }
    mp := acquirem()
    gp := mp.curg
    status := readgstatus(gp)
    if status != _Grunning && status != _Gscanrunning {
        throw("gopark: bad g status")
    }
    mp.waitlock = lock
    mp.waitunlockf = unlockf
    gp.waitreason = reason
    mp.waitTraceBlockReason = traceReason
    mp.waitTraceSkip = traceskip
    releasem(mp)
    // can't do anything that might move the G between Ms here.
    mcall(park_m)
}

```


runtime.mcall 主要的工作就是是从当前 goroutine 切换回 g0 的系统堆栈，然后调用 fn(g)，而此时 runtime.mcall 调用执行的是 runtime.park_m，这个方法里会利用 CAS 把当前运行的 goroutine -- gp 的状态 从 _Grunning 切换到 _Gwaiting，表明该 goroutine 已进入到等待唤醒状态，此时封存和休眠 G 的操作就完成了，只需等待就绪之后被重新唤醒执行即可。最后调用 runtime.schedule() 再次进入调度循环，去执行下一个 goroutine，充分利用 CPU

```go

func park_m(gp *g) {
	mp := getg().m

	trace := traceAcquire()

	if trace.ok() {
		// Trace the event before the transition. It may take a
		// stack trace, but we won't own the stack after the
		// transition anymore.
		trace.GoPark(mp.waitTraceBlockReason, mp.waitTraceSkip)
	}
	// N.B. Not using casGToWaiting here because the waitreason is
	// set by park_m's caller.
	casgstatus(gp, _Grunning, _Gwaiting)
	if trace.ok() {
		traceRelease(trace)
	}

	dropg()

	if fn := mp.waitunlockf; fn != nil {
		ok := fn(gp, mp.waitlock)
		mp.waitunlockf = nil
		mp.waitlock = nil
		if !ok {
			trace := traceAcquire()
			casgstatus(gp, _Gwaiting, _Grunnable)
			if trace.ok() {
				trace.GoUnpark(gp, 2)
				traceRelease(trace)
			}
			execute(gp, true) // Schedule it back, never returns.
		}
	}
	schedule()
}
```
schedule

```go
// One round of scheduler: find a runnable goroutine and execute it.
// Never returns.
func schedule() {
    mp := getg().m

    if mp.locks != 0 {
        throw("schedule: holding locks")
    }

    if mp.lockedg != 0 {
        stoplockedm()
        execute(mp.lockedg.ptr(), false) // Never returns.
    }

    // We should not schedule away from a g that is executing a cgo call,
    // since the cgo call is using the m's g0 stack.
    if mp.incgo {
        throw("schedule: in cgo")
    }

top:
    pp := mp.p.ptr()
    pp.preempt = false

    // Safety check: if we are spinning, the run queue should be empty.
    // Check this before calling checkTimers, as that might call
    // goready to put a ready goroutine on the local run queue.
    if mp.spinning && (pp.runnext != 0 || pp.runqhead != pp.runqtail) {
        throw("schedule: spinning with local work")
    }

    gp, inheritTime, tryWakeP := findRunnable() // blocks until work is available

    if debug.dontfreezetheworld > 0 && freezing.Load() {
        // See comment in freezetheworld. We don't want to perturb
        // scheduler state, so we didn't gcstopm in findRunnable, but
        // also don't want to allow new goroutines to run.
        //
        // Deadlock here rather than in the findRunnable loop so if
        // findRunnable is stuck in a loop we don't perturb that
        // either.
        lock(&deadlock)
        lock(&deadlock)
    }

    // This thread is going to run a goroutine and is not spinning anymore,
    // so if it was marked as spinning we need to reset it now and potentially
    // start a new spinning M.
    if mp.spinning {
        resetspinning()
    }

    if sched.disable.user && !schedEnabled(gp) {
        // Scheduling of this goroutine is disabled. Put it on
        // the list of pending runnable goroutines for when we
        // re-enable user scheduling and look again.
        lock(&sched.lock)
        if schedEnabled(gp) {
            // Something re-enabled scheduling while we
            // were acquiring the lock.
            unlock(&sched.lock)
        } else {
            sched.disable.runnable.pushBack(gp)
            sched.disable.n++
            unlock(&sched.lock)
            goto top
        }
    }

    // If about to schedule a not-normal goroutine (a GCworker or tracereader),
    // wake a P if there is one.
    if tryWakeP {
        wakep()
    }
    if gp.lockedm != 0 {
        // Hands off own p to the locked m,
        // then blocks waiting for a new p.
        startlockedm(gp)
        goto top
    }

    execute(gp, inheritTime)
}
```

Schedules gp to run on the current M.
If inheritTime is true, gp inherits the remaining time in the current time slice. Otherwise, it starts a new time slice.
Never returns.

Write barriers are allowed because this is called immediately after acquiring a P in several places.
```go
//go:yeswritebarrierrec
func execute(gp *g, inheritTime bool) {
    mp := getg().m

    if goroutineProfile.active {
        // Make sure that gp has had its stack written out to the goroutine
        // profile, exactly as it was when the goroutine profiler first stopped
        // the world.
        tryRecordGoroutineProfile(gp, osyield)
    }

    // Assign gp.m before entering _Grunning so running Gs have an
    // M.
    mp.curg = gp
    gp.m = mp
    casgstatus(gp, _Grunnable, _Grunning)
    gp.waitsince = 0
    gp.preempt = false
    gp.stackguard0 = gp.stack.lo + stackGuard
    if !inheritTime {
        mp.p.ptr().schedtick++
    }

    // Check whether the profiler needs to be turned on or off.
    hz := sched.profilehz
    if mp.profilehz != hz {
        setThreadCPUProfiler(hz)
    }

    trace := traceAcquire()
    if trace.ok() {
        // GoSysExit has to happen when we have a P, but before GoStart.
        // So we emit it here.
        if !goexperiment.ExecTracer2 && gp.syscallsp != 0 {
            trace.GoSysExit(true)
        }
        trace.GoStart()
        traceRelease(trace)
    }

    gogo(&gp.sched)
}
```

### 抢占

为了让每个协程都有执行的机会，并且最大化利用CPU资源，Go语言在初始化时会启动一个特殊的线程来执行系统监控任务。
系统监控在一个独立的M上运行，不用绑定逻辑处理器P，系统监控每隔10ms会检测是否有准备就绪的网络协程，并放置到全局队列中。
和抢占调度相关的是，系统监控服务会判断当前协程是否运行时间过长，或者处于系统调用阶段，如果是，则会抢占当前G的执行。其核心逻辑位于runtime.retake函数中



#### Interrput

1.14实现基于信号抢占 向运行的P绑定的M发送SIGURG信号





## Links

