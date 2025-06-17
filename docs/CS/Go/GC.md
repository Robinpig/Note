## Introduction

Go语言采用了并发三色标记算法进行垃圾回收。三色标记是最简单的垃圾回收算法，其实现也很简单


 为什么不选择压缩GC？
压缩算法的主要优势是减少碎片并且快速分配。Go语言使用了现代内存分配算法TCmalloc，虽然没有压缩算法那样极致，但它已经很好地解决了内存碎片的问题。
 并且，由于需要加锁，压缩算法并不适合在并发程序中使用。另外，在Go语言设计初期，由于时间紧迫，设计团队放弃了考虑更加复杂的压缩算法，转而使用了更简单的三色标记算法。

为什么不选择分代GC？
Go语言并不是没有尝试过分代GC。分代GC的主要假设是大部分变成垃圾的对象都是新创建的
但是由于编译器的优化，Go语言通过内存逃逸的机制将会继续使用的对象转移到了堆中，大部分生命周期很短的对象会在栈中分配，
这和其他使用分代GC的编程语言有显著的不同，减弱了使用分代GC的优势。“同时，分代GC需要额外的写屏障来保护并发垃圾回收时对象的隔代性，会减慢GC的速度。
因此，分代GC是被尝试过并抛弃的方案[2]。



gcMarkBits 用于实现内存标记 0-白色 1-黑色

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





gcStart starts the GC. It transitions from _GCoff to _GCmark (if debug.gcstoptheworld == 0) or performs all of GC (if debug.gcstoptheworld != 0).


This may return without performing this transition in some cases, such as when called on a system stack or with locks held.


```go
// mgc.go
func gcStart(trigger gcTrigger) {
    // ...
}
```

func (c *gcControllerState) startCycle(markStartTime int64, procs int, trigger gcTrigger) {


sweep

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







## Links

- [Garbage Collection](/docs/CS/memory/GC.md)
- [Java GC](/docs/CS/Java/JDK/JVM/GC/GC.md)