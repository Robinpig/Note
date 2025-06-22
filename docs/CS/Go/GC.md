## Introduction

Go语言采用了并发三色标记算法进行垃圾回收。三色标记是最简单的垃圾回收算法，其实现也很简单


 为什么不选择压缩GC？
压缩算法的主要优势是减少碎片并且快速分配。Go语言使用了现代内存分配算法TCmalloc，虽然没有压缩算法那样极致，但它已经很好地解决了内存碎片的问题。
 并且，由于需要加锁，压缩算法并不适合在并发程序中使用。另外，在Go语言设计初期，由于时间紧迫，设计团队放弃了考虑更加复杂的压缩算法，转而使用了更简单的三色标记算法。

为什么不选择分代GC？
Go语言并不是没有尝试过分代GC。分代GC的主要假设是大部分变成垃圾的对象都是新创建的
但是由于编译器的优化，Go语言通过内存逃逸的机制将会继续使用的对象转移到了堆中，大部分生命周期很短的对象会在栈中分配，
这和其他使用分代GC的编程语言有显著的不同，减弱了使用分代GC的优势。“同时，分代GC需要额外的写屏障来保护并发垃圾回收时对象的隔代性，会减慢GC的速度。
因此，分代GC是被尝试过并抛弃的方案



gcMarkBits 用于实现内存标记 0-白色 未扫描垃圾内存 1-黑色 已扫描内存

```go
type mspan struct {
	// allocBits and gcmarkBits hold pointers to a span's mark and
	// allocation bits. The pointers are 8 byte aligned.
	// There are three arenas where this data is held.
	// free: Dirty arenas that are no longer accessed
	//       and can be reused.
	// next: Holds information to be used in the next GC cycle.
	// current: Information being used during this GC cycle.
	// previous: Information being used during the last GC cycle.
	// A new GC cycle starts with the call to finishsweep_m.
	// finishsweep_m moves the previous arena to the free arena,
	// the current arena to the previous arena, and
	// the next arena to the current arena.
	// The next arena is populated as the spans request
	// memory to hold gcmarkBits for the next GC cycle as well
	// as allocBits for newly allocated spans.
	//
	// The pointer arithmetic is done "by hand" instead of using
	// arrays to avoid bounds checks along critical performance
	// paths.
	// The sweep will free the old allocBits and set allocBits to the
	// gcmarkBits. The gcmarkBits are replaced with a fresh zeroed
	// out memory.
	allocBits  *gcBits
	gcmarkBits *gcBits
	pinnerBits *gcBits // bitmap for pinned objects; accessed atomically
}
```





Go 语言将垃圾回收整个过程分成三个阶段: 未启动 标记扫描和标记终止

```go
const (
	_GCoff             = iota // GC not running; sweeping in background, write barrier disabled
	_GCmark                   // GC marking roots and workbufs: allocate black, write barrier ENABLED
	_GCmarktermination        // GC mark termination: allocate black, P's help GC, write barrier ENABLED
)
```


#### gcStart

gcStart starts the GC. It transitions from _GCoff to _GCmark (if debug.gcstoptheworld == 0) or performs all of GC (if debug.gcstoptheworld != 0).


This may return without performing this transition in some cases, such as when called on a system stack or with locks held.


```go
// mgc.go
func gcStart(trigger gcTrigger) {
	// Since this is called from malloc and malloc is called in
	// the guts of a number of libraries that might be holding
	// locks, don't attempt to start GC in non-preemptible or
	// potentially unstable situations.
	mp := acquirem()
	if gp := getg(); gp == mp.g0 || mp.locks > 1 || mp.preemptoff != "" {
		releasem(mp)
		return
	}
	releasem(mp)
	mp = nil

	if gp := getg(); gp.syncGroup != nil {
		// Disassociate the G from its synctest bubble while allocating.
		// This is less elegant than incrementing the group's active count,
		// but avoids any contamination between GC and synctest.
		sg := gp.syncGroup
		gp.syncGroup = nil
		defer func() {
			gp.syncGroup = sg
		}()
	}

	// Pick up the remaining unswept/not being swept spans concurrently
	//
	// This shouldn't happen if we're being invoked in background
	// mode since proportional sweep should have just finished
	// sweeping everything, but rounding errors, etc, may leave a
	// few spans unswept. In forced mode, this is necessary since
	// GC can be forced at any point in the sweeping cycle.
	//
	// We check the transition condition continuously here in case
	// this G gets delayed in to the next GC cycle.
	for trigger.test() && sweepone() != ^uintptr(0) {
	}

	// Perform GC initialization and the sweep termination
	// transition.
	semacquire(&work.startSema)
	// Re-check transition condition under transition lock.
	if !trigger.test() {
		semrelease(&work.startSema)
		return
	}

	// In gcstoptheworld debug mode, upgrade the mode accordingly.
	// We do this after re-checking the transition condition so
	// that multiple goroutines that detect the heap trigger don't
	// start multiple STW GCs.
	mode := gcBackgroundMode
	if debug.gcstoptheworld == 1 {
		mode = gcForceMode
	} else if debug.gcstoptheworld == 2 {
		mode = gcForceBlockMode
	}

	// Ok, we're doing it! Stop everybody else
	semacquire(&gcsema)
	semacquire(&worldsema)

	// For stats, check if this GC was forced by the user.
	// Update it under gcsema to avoid gctrace getting wrong values.
	work.userForced = trigger.kind == gcTriggerCycle

	trace := traceAcquire()
	if trace.ok() {
		trace.GCStart()
		traceRelease(trace)
	}

	// Check that all Ps have finished deferred mcache flushes.
	for _, p := range allp {
		if fg := p.mcache.flushGen.Load(); fg != mheap_.sweepgen {
			println("runtime: p", p.id, "flushGen", fg, "!= sweepgen", mheap_.sweepgen)
			throw("p mcache not flushed")
		}
	}

	gcBgMarkStartWorkers()

	systemstack(gcResetMarkState)

	work.stwprocs, work.maxprocs = gomaxprocs, gomaxprocs
	if work.stwprocs > ncpu {
		// This is used to compute CPU time of the STW phases,
		// so it can't be more than ncpu, even if GOMAXPROCS is.
		work.stwprocs = ncpu
	}
	work.heap0 = gcController.heapLive.Load()
	work.pauseNS = 0
	work.mode = mode

	now := nanotime()
	work.tSweepTerm = now
	var stw worldStop
	systemstack(func() {
		stw = stopTheWorldWithSema(stwGCSweepTerm)
	})

	// Accumulate fine-grained stopping time.
	work.cpuStats.accumulateGCPauseTime(stw.stoppingCPUTime, 1)

	// Finish sweep before we start concurrent scan.
	systemstack(func() {
		finishsweep_m()
	})

	// clearpools before we start the GC. If we wait the memory will not be
	// reclaimed until the next GC cycle.
	clearpools()

	work.cycles.Add(1)

	// Assists and workers can start the moment we start
	// the world.
	gcController.startCycle(now, int(gomaxprocs), trigger)

	// Notify the CPU limiter that assists may begin.
	gcCPULimiter.startGCTransition(true, now)

	// In STW mode, disable scheduling of user Gs. This may also
	// disable scheduling of this goroutine, so it may block as
	// soon as we start the world again.
	if mode != gcBackgroundMode {
		schedEnableUser(false)
	}

	// Enter concurrent mark phase and enable
	// write barriers.
	//
	// Because the world is stopped, all Ps will
	// observe that write barriers are enabled by
	// the time we start the world and begin
	// scanning.
	//
	// Write barriers must be enabled before assists are
	// enabled because they must be enabled before
	// any non-leaf heap objects are marked. Since
	// allocations are blocked until assists can
	// happen, we want to enable assists as early as
	// possible.
	setGCPhase(_GCmark)

	gcBgMarkPrepare() // Must happen before assists are enabled.
	gcMarkRootPrepare()

	// Mark all active tinyalloc blocks. Since we're
	// allocating from these, they need to be black like
	// other allocations. The alternative is to blacken
	// the tiny block on every allocation from it, which
	// would slow down the tiny allocator.
	gcMarkTinyAllocs()

	// At this point all Ps have enabled the write
	// barrier, thus maintaining the no white to
	// black invariant. Enable mutator assists to
	// put back-pressure on fast allocating
	// mutators.
	atomic.Store(&gcBlackenEnabled, 1)

	// In STW mode, we could block the instant systemstack
	// returns, so make sure we're not preemptible.
	mp = acquirem()

	// Update the CPU stats pause time.
	//
	// Use maxprocs instead of stwprocs here because the total time
	// computed in the CPU stats is based on maxprocs, and we want them
	// to be comparable.
	work.cpuStats.accumulateGCPauseTime(nanotime()-stw.finishedStopping, work.maxprocs)

	// Concurrent mark.
	systemstack(func() {
		now = startTheWorldWithSema(0, stw)
		work.pauseNS += now - stw.startedStopping
		work.tMark = now

		// Release the CPU limiter.
		gcCPULimiter.finishGCTransition(now)
	})

	// Release the world sema before Gosched() in STW mode
	// because we will need to reacquire it later but before
	// this goroutine becomes runnable again, and we could
	// self-deadlock otherwise.
	semrelease(&worldsema)
	releasem(mp)

	// Make sure we block instead of returning to user code
	// in STW mode.
	if mode != gcBackgroundMode {
		Gosched()
	}

	semrelease(&work.startSema)
}
```


##### 


stopTheWorldWithSema is the core implementation of stopTheWorld.
The caller is responsible for acquiring worldsema and disabling preemption first and then should stopTheWorldWithSema on the system stack:

```
//
//	semacquire(&worldsema, 0)
//	m.preemptoff = "reason"
//	var stw worldStop
//	systemstack(func() {
//		stw = stopTheWorldWithSema(reason)
//	})
//
// When finished, the caller must either call startTheWorld or undo
// these three operations separately:
//
//	m.preemptoff = ""
//	systemstack(func() {
//		now = startTheWorldWithSema(stw)
//	})
//	semrelease(&worldsema)
```
#### stopTheWorldWithSema
It is allowed to acquire worldsema once and then execute multiple startTheWorldWithSema/stopTheWorldWithSema pairs.
Other P's are able to execute between successive calls to startTheWorldWithSema and stopTheWorldWithSema.
Holding worldsema causes any other goroutines invoking stopTheWorld to block.

Returns the STW context. When starting the world, this context must be passed to startTheWorldWithSema.

```go
func stopTheWorldWithSema(reason stwReason) worldStop {
	trace := traceAcquire()
	if trace.ok() {
		trace.STWStart(reason)
		traceRelease(trace)
	}
	gp := getg()

	// If we hold a lock, then we won't be able to stop another M
	// that is blocked trying to acquire the lock.
	if gp.m.locks > 0 {
		throw("stopTheWorld: holding locks")
	}

	lock(&sched.lock)
	start := nanotime() // exclude time waiting for sched.lock from start and total time metrics.
	sched.stopwait = gomaxprocs
	sched.gcwaiting.Store(true)
	preemptall()
	// stop current P
	gp.m.p.ptr().status = _Pgcstop // Pgcstop is only diagnostic.
	gp.m.p.ptr().gcStopTime = start
	sched.stopwait--
	// try to retake all P's in Psyscall status
	trace = traceAcquire()
	for _, pp := range allp {
		s := pp.status
		if s == _Psyscall && atomic.Cas(&pp.status, s, _Pgcstop) {
			if trace.ok() {
				trace.ProcSteal(pp, false)
			}
			pp.syscalltick++
			pp.gcStopTime = nanotime()
			sched.stopwait--
		}
	}
	if trace.ok() {
		traceRelease(trace)
	}

	// stop idle P's
	now := nanotime()
	for {
		pp, _ := pidleget(now)
		if pp == nil {
			break
		}
		pp.status = _Pgcstop
		pp.gcStopTime = nanotime()
		sched.stopwait--
	}
	wait := sched.stopwait > 0
	unlock(&sched.lock)

	// wait for remaining P's to stop voluntarily
	if wait {
		for {
			// wait for 100us, then try to re-preempt in case of any races
			if notetsleep(&sched.stopnote, 100*1000) {
				noteclear(&sched.stopnote)
				break
			}
			preemptall()
		}
	}

	finish := nanotime()
	startTime := finish - start
	if reason.isGC() {
		sched.stwStoppingTimeGC.record(startTime)
	} else {
		sched.stwStoppingTimeOther.record(startTime)
	}

	// Double-check we actually stopped everything, and all the invariants hold.
	// Also accumulate all the time spent by each P in _Pgcstop up to the point
	// where everything was stopped. This will be accumulated into the total pause
	// CPU time by the caller.
	stoppingCPUTime := int64(0)
	bad := ""
	if sched.stopwait != 0 {
		bad = "stopTheWorld: not stopped (stopwait != 0)"
	} else {
		for _, pp := range allp {
			if pp.status != _Pgcstop {
				bad = "stopTheWorld: not stopped (status != _Pgcstop)"
			}
			if pp.gcStopTime == 0 && bad == "" {
				bad = "stopTheWorld: broken CPU time accounting"
			}
			stoppingCPUTime += finish - pp.gcStopTime
			pp.gcStopTime = 0
		}
	}
	if freezing.Load() {
		// Some other thread is panicking. This can cause the
		// sanity checks above to fail if the panic happens in
		// the signal handler on a stopped thread. Either way,
		// we should halt this thread.
		lock(&deadlock)
		lock(&deadlock)
	}
	if bad != "" {
		throw(bad)
	}

	worldStopped()

	return worldStop{
		reason:           reason,
		startedStopping:  start,
		finishedStopping: finish,
		stoppingCPUTime:  stoppingCPUTime,
	}
}
```


##### gcBgMarkStartWorkers

```go

// gcBgMarkStartWorkers prepares background mark worker goroutines. These
// goroutines will not run until the mark phase, but they must be started while
// the work is not stopped and from a regular G stack. The caller must hold
// worldsema.
func gcBgMarkStartWorkers() {
	// Background marking is performed by per-P G's. Ensure that each P has
	// a background GC G.
	//
	// Worker Gs don't exit if gomaxprocs is reduced. If it is raised
	// again, we can reuse the old workers; no need to create new workers.
	if gcBgMarkWorkerCount >= gomaxprocs {
		return
	}

	// Increment mp.locks when allocating. We are called within gcStart,
	// and thus must not trigger another gcStart via an allocation. gcStart
	// bails when allocating with locks held, so simulate that for these
	// allocations.
	//
	// TODO(prattmic): cleanup gcStart to use a more explicit "in gcStart"
	// check for bailing.
	mp := acquirem()
	ready := make(chan struct{}, 1)
	releasem(mp)

	for gcBgMarkWorkerCount < gomaxprocs {
		mp := acquirem() // See above, we allocate a closure here.
		go gcBgMarkWorker(ready)
		releasem(mp)

		// N.B. we intentionally wait on each goroutine individually
		// rather than starting all in a batch and then waiting once
		// afterwards. By running one goroutine at a time, we can take
		// advantage of runnext to bounce back and forth between
		// workers and this goroutine. In an overloaded application,
		// this can reduce GC start latency by prioritizing these
		// goroutines rather than waiting on the end of the run queue.
		<-ready
		// The worker is now guaranteed to be added to the pool before
		// its P's next findRunnableGCWorker.

		gcBgMarkWorkerCount++
	}
}
```


#### sweep

```go
/go:systemstack
func gcSweep(mode gcMode) bool {
	assertWorldStopped()

	if gcphase != _GCoff {
		throw("gcSweep being done but phase is not GCoff")
	}

	lock(&mheap_.lock)
	mheap_.sweepgen += 2
	sweep.active.reset()
	mheap_.pagesSwept.Store(0)
	mheap_.sweepArenas = mheap_.allArenas
	mheap_.reclaimIndex.Store(0)
	mheap_.reclaimCredit.Store(0)
	unlock(&mheap_.lock)

	sweep.centralIndex.clear()

	if !concurrentSweep || mode == gcForceBlockMode {
		// Special case synchronous sweep.
		// Record that no proportional sweeping has to happen.
		lock(&mheap_.lock)
		mheap_.sweepPagesPerByte = 0
		unlock(&mheap_.lock)
		// Flush all mcaches.
		for _, pp := range allp {
			pp.mcache.prepareForSweep()
		}
		// Sweep all spans eagerly.
		for sweepone() != ^uintptr(0) {
		}
		// Free workbufs eagerly.
		prepareFreeWorkbufs()
		for freeSomeWbufs(false) {
		}
		// All "free" events for this mark/sweep cycle have
		// now happened, so we can make this profile cycle
		// available immediately.
		mProf_NextCycle()
		mProf_Flush()
		return true
	}

	// Background sweep.
	lock(&sweep.lock)
	if sweep.parked {
		sweep.parked = false
		ready(sweep.g, 0, true)
	}
	unlock(&sweep.lock)
	return false
}
```



GC时机

- 定时
- 手动
- 申请内存时



申请内存的触发方式依赖于 GOGC 这同时也需要更大的内存

由于现在服务多在容器中部署 且应用流量是会变化 所以GOGC的配置也需要动态变化

Uber 使用半自动化调优方式 通过Go的终结器采集内存性能指标 动态调整GOGC 减少GC


内存分配的基本单元是 mspan 查找空闲内存是从比特位 allocBits 中查找满足条件的连续0比特位 除此之外还有一个比特位 gcmarkBits 实现内存标记(0白色 1黑色)

如何表示灰色对象? Go 语言维护了一个灰色对象集合 灰色对象的 gcmarkBits 已经设置为1


`runtime.greyobject` 是实现了对象标为 grey 的逻辑


```go
//go:nowritebarrierrec
func greyobject(obj, base, off uintptr, span *mspan, gcw *gcWork, objIndex uintptr) {
	// obj should be start of allocation, and so must be at least pointer-aligned.
	if obj&(goarch.PtrSize-1) != 0 {
		throw("greyobject: obj not pointer-aligned")
	}
	mbits := span.markBitsForIndex(objIndex)

	if useCheckmark {
		if setCheckmark(obj, base, off, mbits) {
			// Already marked.
			return
		}
	} else {
		if debug.gccheckmark > 0 && span.isFree(objIndex) {
			print("runtime: marking free object ", hex(obj), " found at *(", hex(base), "+", hex(off), ")\n")
			gcDumpObject("base", base, off)
			gcDumpObject("obj", obj, ^uintptr(0))
			getg().m.traceback = 2
			throw("marking free object")
		}

		// If marked we have nothing to do.
		if mbits.isMarked() {
			return
		}
		mbits.setMarked()

		// Mark span.
		arena, pageIdx, pageMask := pageIndexOf(span.base())
		if arena.pageMarks[pageIdx]&pageMask == 0 {
			atomic.Or8(&arena.pageMarks[pageIdx], pageMask)
		}

		// If this is a noscan object, fast-track it to black
		// instead of greying it.
		if span.spanclass.noscan() {
			gcw.bytesMarked += uint64(span.elemsize)
			return
		}
	}

	// We're adding obj to P's local workbuf, so it's likely
	// this object will be processed soon by the same P.
	// Even if the workbuf gets flushed, there will likely still be
	// some benefit on platforms with inclusive shared caches.
	sys.Prefetch(obj)
	// Queue the obj for scanning.
	if !gcw.putFast(obj) {
		gcw.put(obj)
	}
}
```

#### scanobject


scanobject scans the object starting at b, adding pointers to gcw. b must point to the beginning of a heap object or an oblet.
scanobject consults the GC bitmap for the pointer mask and the spans for the size of the object.

> scan 只会扫描堆内存 Go 专门设置了一个字段 `mspan.state` 判断当前内存是堆内存还是栈内存

```go
//go:nowritebarrier
func scanobject(b uintptr, gcw *gcWork) {
	// Prefetch object before we scan it.
	//
	// This will overlap fetching the beginning of the object with initial
	// setup before we start scanning the object.
	sys.Prefetch(b)

	// Find the bits for b and the size of the object at b.
	//
	// b is either the beginning of an object, in which case this
	// is the size of the object to scan, or it points to an
	// oblet, in which case we compute the size to scan below.
	s := spanOfUnchecked(b)
	n := s.elemsize
	if n == 0 {
		throw("scanobject n == 0")
	}
	if s.spanclass.noscan() {
		// Correctness-wise this is ok, but it's inefficient
		// if noscan objects reach here.
		throw("scanobject of a noscan object")
	}

	var tp typePointers
	if n > maxObletBytes {
		// Large object. Break into oblets for better
		// parallelism and lower latency.
		if b == s.base() {
			// Enqueue the other oblets to scan later.
			// Some oblets may be in b's scalar tail, but
			// these will be marked as "no more pointers",
			// so we'll drop out immediately when we go to
			// scan those.
			for oblet := b + maxObletBytes; oblet < s.base()+s.elemsize; oblet += maxObletBytes {
				if !gcw.putFast(oblet) {
					gcw.put(oblet)
				}
			}
		}

		// Compute the size of the oblet. Since this object
		// must be a large object, s.base() is the beginning
		// of the object.
		n = s.base() + s.elemsize - b
		n = min(n, maxObletBytes)
		tp = s.typePointersOfUnchecked(s.base())
		tp = tp.fastForward(b-tp.addr, b+n)
	} else {
		tp = s.typePointersOfUnchecked(b)
	}

	var scanSize uintptr
	for {
		var addr uintptr
		if tp, addr = tp.nextFast(); addr == 0 {
			if tp, addr = tp.next(b + n); addr == 0 {
				break
			}
		}

		// Keep track of farthest pointer we found, so we can
		// update heapScanWork. TODO: is there a better metric,
		// now that we can skip scalar portions pretty efficiently?
		scanSize = addr - b + goarch.PtrSize

		// Work here is duplicated in scanblock and above.
		// If you make changes here, make changes there too.
		obj := *(*uintptr)(unsafe.Pointer(addr))

		// At this point we have extracted the next potential pointer.
		// Quickly filter out nil and pointers back to the current object.
		if obj != 0 && obj-b >= n {
			// Test if obj points into the Go heap and, if so,
			// mark the object.
			//
			// Note that it's possible for findObject to
			// fail if obj points to a just-allocated heap
			// object because of a race with growing the
			// heap. In this case, we know the object was
			// just allocated and hence will be marked by
			// allocation itself.
			if obj, span, objIndex := findObject(obj, b, addr-b); obj != 0 {
				greyobject(obj, b, addr-b, span, gcw, objIndex)
			}
		}
	}
	gcw.bytesMarked += uint64(n)
	gcw.heapScanWork += int64(scanSize)
}
```

### write barrier


协程并发执行导致黑色对象指向白色对象 且没有任何灰色对象指向该白色对象


写屏障将需要标记为灰色的对象加入到缓存队列 当灰度对象集合为空时 或者标记扫描过程结束时 垃圾回收会将缓存队列的所有对象重新加入灰色对象集合 重新开始扫描





## Links

- [Garbage Collection](/docs/CS/memory/GC.md)
- [Java GC](/docs/CS/Java/JDK/JVM/GC/GC.md)