## Introduction

Goroutine是Golang支持高并发的重要保障。Golang可以创建成千上万个Goroutine来处理任务，将这些Goroutine分配、负载、调度到处理器上采用的是G-M-P模型
Goroutine = Golang + Coroutine。Goroutine是golang实现的协程，是用户级线程。Goroutine具有以下特点：

- 相比线程，其启动的代价很小，以很小栈空间启动（2Kb左右）
- 能够动态地伸缩栈的大小，最大可以支持到Gb级别
- 工作在用户态，切换成很小
- 与线程关系是n:m，即可以在n个系统线程上多工调度m个Goroutine

## GMP



在GMP模型中，

- G代表的是Go语言中的协程（Goroutine），
- M代表的是执行运算单元, Go会将其与操作系统的线程绑定
- P代表的是Go逻辑处理器（Processor），Go语言为了方便协程调度与缓存，抽象出了逻辑处理器。

Go 语言针对 GMP 模型 分别定义了对应的数据结构


<!-- tabs:start -->


##### **g**

g结构体用于代表一个goroutine，该结构体保存了goroutine的所有信息，包括栈，gobuf结构体和其它的一些状态信息

```go
 
type g struct {
	stack       stack  
	sched     gobuf
	...
		
}
```



##### **m**

m结构体用来代表工作线程，它保存了m自身使用的栈信息，当前正在运行的goroutine以及与m绑定的p等信息

调度程序被封装成协程 g0

```go
type m struct {
   g0      *g     // goroutine with scheduling stack
   mstartfn        func()
   curg            *g       // current running goroutine
   p               puintptr // attached p for executing go code (nil if not executing go code)
   nextp           puintptr
   id              int64
   ...
}
```



##### **p**

p结构体用于保存工作线程执行go代码时所必需的资源，比如goroutine的运行队列，内存分配用到的缓存等等。

```go
type p struct {
	id          int32
	status      uint32 // one of pidle/prunning/...
	m           muintptr   // back-link to associated m (nil if idle)

	// Queue of runnable goroutines. Accessed without lock.
	runqhead uint32
	runqtail uint32
	runq     [256]guintptr
  ...
}
```

<!-- tabs:end -->


- G 的数量： 理论上没有数量上限限制的。查看当前G的数量可以使用runtime. NumGoroutine()
- M 的数量: go 语言本身的限制：go 程序启动时，会设置 M 的最大数量，默认 10000. 但是内核很难支持这么多的线程数，所以这个限制可以忽略。 runtime/debug 中的 SetMaxThreads 函数，设置 M 的最大数量 一个 M 阻塞了，会创建新的 M。M 与 P 的数量没有绝对关系，一个 M 阻塞，P 就会去创建或者切换另一个 M，所以，即使 P 的默认数量是 1，也有可能会创建很多个 M 出来。
- P 的数量：默认情况下P的数量等于CPU逻辑核的数量 可以使用runtime.GOMAXPROCS来修改 每个P都有一个本地goroutine队列

> 一般来讲，程序运行时就将GOMAXPROCS大小设置为CPU核数，可让Go程序充分利用CPU。 在某些IO密集型的应用里，这个值可能并不意味着性能最好 
> 理论上当某个Goroutine进入系统调用时，会有一个新的M被启用或创建，继续占满CPU。 但由于Go调度器检测到M被阻塞是有一定延迟的，
> 也即旧的M被阻塞和新的M得到运行之间是有一定间隔的，所以在IO密集型应用中不妨把GOMAXPROCS设置的大一些，或许会有好的效果。

最早的Go(1.0以下)运行时模型是GM模型

1. 用一个全局的mutex保护着一个全局的runq（就绪队列），所有goroutine的创建、结束，以及 调度等操作都要先获得锁，造成对锁的争用异常严重
2. G的每次执行都会被分发到随机的M上，造成在不同M之间频繁切换，破坏了程序的局部性， 主要原因也是因为只有一个全局的runq。例如在一个chan上互相唤醒的两个goroutine就会面临这种 问题。还有一点就是新创建的G会被创建它的M放入全局runq中，但是会被另一个M调度执行，也会造成不必要的开销
3. 每个M都会关联一个内存分配缓存mcache，造成了大量的内存开销，进一步使数据的局部性变差。实际上只有执行Go代码的M才真地需要mcache，那些阻塞在系统调用中的M根本不需要， 而实际执行Go代码的M可能仅占M总数的1%。
4. 在存在系统调用的情况下，工作线程经常被阻塞和解除阻塞，从而增加了很多开销

在任一时刻，一个P可能在其本地包含多个G，同时，一个P在任一时刻只能绑定一个M。
图14-9中没有涵盖的信息是：一个G并不是固定绑定同一个P的，有很多情况（例如P在运行时被销毁）会导致一个P中的G转移到其他的P中。
同样的，一个P只能对应一个M，但是具体对应的是哪一个M也是不固定的。一个M可能在某些时候转移到其他的P中执行



实际上一共有三种 g：

1. 执行用户代码的 g； 使用 go 关键字启动的 goroutine，也是我们接触最多的一类 g
2. 执行调度器代码的 g，也即是 g0； g0 在底层和其他 g 是一样的数据结构，但是性质上有很大的区别，首先 g0 的栈大小是固定的，
3. 比如在 Linux 或者其他 Unix-like 的系统上一般是固定 8MB，不能动态伸缩，而普通的 g 初始栈大小是 2KB，可按需扩展 
4. 每个线程被创建出来之时都需要操作系统为之分配一个初始固定的线程栈，就是前面说的 8MB 大小的栈，g0 栈就代表了这个线程栈，因此每一个 m 都需要绑定一个 g0 来执行调度器代码，然后跳转到执行用户代码的地方。
5. 执行 runtime.main 初始化工作的 main goroutine；

启动一个新的 goroutine 是通过 go 关键字来完成的，而 go compiler 会在编译期间利用 cmd/compile/internal/gc.state.stmt 和 cmd/compile/internal/gc.state.call 
这两个函数将 go 关键字翻译成 runtime.newproc 函数调用，而 runtime.newproc 接收了函数指针和其大小之后，会获取 goroutine 和调用处的程序计数器，接着再调用 runtime.newproc1





## start

首先来看Go程序的启动过程

程序入口函数在 `runtime/rt0_linux_amd64.s` 文件 最终会执行 `CALL runtime·mstart(SB)` 指令 调度 main goroutine 执行 runtime.main 函数

```cpp

#include "textflag.h"

TEXT _rt0_amd64_linux(SB),NOSPLIT,$-8
	JMP	_rt0_amd64(SB)
```

go/src/runtime/asm_amd64.s

_rt0_amd64 is common startup code for most amd64 systems when using internal linking.
This is the entry point for the program from the kernel for an ordinary -buildmode=exe program. 
The stack holds the number of arguments and the C-style argv.

```cpp
TEXT _rt0_amd64(SB),NOSPLIT,$-8
	MOVQ	0(SP), DI	// argc
	LEAQ	8(SP), SI	// argv
	JMP	runtime·rt0_go(SB)
```


M0 是启动程序后的编号为 0 的主线程，这个 M 对应的实例会在全局变量 runtime.m0 中，不需要在 heap 上分配，M0 负责执行初始化操作和启动第一个 G， 在之后 M0 就和其他的 M 一样了
上面生命周期流程说明：

runtime 创建最初的线程 m0 和 goroutine g0，并把两者进行关联（g0.m = m0)
调度器初始化：设置M最大数量，P个数，栈和内存出事，以及创建 GOMAXPROCS个P
示例代码中的 main 函数是 main.main，runtime 中也有 1 个 main 函数 ——runtime.main，代码经过编译后，runtime.main 会调用 main.main，程序启动时会为 runtime.main 创建 goroutine，称它为 main goroutine 吧，然后把 main goroutine 加入到 P 的本地队列。
启动 m0，m0 已经绑定了 P，会从 P 的本地队列获取 G，获取到 main goroutine。
G 拥有栈，M 根据 G 中的栈信息和调度信息设置运行环境
M 运行 G
G 退出，再次回到 M 获取可运行的 G，这样重复下去，直到 main.main 退出，runtime.main 执行 Defer 和 Panic 处理，或调用 runtime.exit 退出程序。



比较重要的操作

- 创建第一个协程 g0
- 调度器初始化
- 创建一个新的协程用于执行 runtime.main 函数 等待调度器调度
- 启动 M 用于调度

```cpp
TEXT runtime·rt0_go(SB),NOSPLIT|NOFRAME|TOPFRAME,$0
	// copy arguments forward on an even stack
	MOVQ	DI, AX		// argc
	MOVQ	SI, BX		// argv
	SUBQ	$(5*8), SP		// 3args 2auto
	ANDQ	$~15, SP
	MOVQ	AX, 24(SP)
	MOVQ	BX, 32(SP)

	// create istack out of the given (operating system) stack.
	// _cgo_init may update stackguard.
	MOVQ	$runtime·g0(SB), DI
	LEAQ	(-64*1024)(SP), BX
	MOVQ	BX, g_stackguard0(DI)
	MOVQ	BX, g_stackguard1(DI)
	MOVQ	BX, (g_stack+stack_lo)(DI)
	MOVQ	SP, (g_stack+stack_hi)(DI)

	// find out information about the processor we're on
	MOVL	$0, AX
	CPUID
	CMPL	AX, $0
	JE	nocpuinfo

	CMPL	BX, $0x756E6547  // "Genu"
	JNE	notintel
	CMPL	DX, $0x49656E69  // "ineI"
	JNE	notintel
	CMPL	CX, $0x6C65746E  // "ntel"
	JNE	notintel
	MOVB	$1, runtime·isIntel(SB)



    LEAQ	runtime·m0+m_tls(SB), DI
	CALL	runtime·settls(SB)

	// store through it, to make sure it works
	get_tls(BX)
	MOVQ	$0x123, g(BX)
	MOVQ	runtime·m0+m_tls(SB), AX
	CMPQ	AX, $0x123
	JEQ 2(PC)
	CALL	runtime·abort(SB)
ok:
	// set the per-goroutine and per-mach "registers"
	get_tls(BX)
	LEAQ	runtime·g0(SB), CX
	MOVQ	CX, g(BX)
	LEAQ	runtime·m0(SB), AX

	// save m->g0 = g0
	MOVQ	CX, m_g0(AX)
	// save m0 to g0->m
	MOVQ	AX, g_m(CX)

	CLD				// convention is D is always left cleared

	// Check GOAMD64 requirements
	// We need to do this after setting up TLS, so that
	// we can report an error if there is a failure. See issue 49586.

    // ...

    
	CALL	runtime·check(SB)

	MOVL	24(SP), AX		// copy argc
	MOVL	AX, 0(SP)
	MOVQ	32(SP), AX		// copy argv
	MOVQ	AX, 8(SP)
	CALL	runtime·args(SB)
	CALL	runtime·osinit(SB)
	CALL	runtime·schedinit(SB)

	// create a new goroutine to start program
	MOVQ	$runtime·mainPC(SB), AX		// entry
	PUSHQ	AX
	CALL	runtime·newproc(SB)
	POPQ	AX

	// start this M
	CALL	runtime·mstart(SB)

	CALL	runtime·abort(SB)	// mstart should never return
	RET
    
    // mainPC is a function value for runtime.main, to be passed to newproc.
    // The reference to runtime.main is made via ABIInternal, since the
    // actual function (not the ABI0 wrapper) is needed by newproc.
    DATA	runtime·mainPC+0(SB)/8,$runtime·main<ABIInternal>(SB)
    GLOBL	runtime·mainPC(SB),RODATA,$8

```



### runtime#main

main goroutine

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
		if GOARCH == "wasm" {
			// On Wasm, pause makes it return to the host.
			// Unlike cgo callbacks where Ms are created on demand,
			// on Wasm we have only one M. So we keep this M (and this
			// G) for callbacks.
			// Using the caller's SP unwinds this frame and backs to
			// goexit. The -16 is: 8 for goexit's (fake) return PC,
			// and pause's epilogue pops 8.
			pause(sys.GetCallerSP() - 16) // should not return
			panic("unreachable")
		}
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






上下文切换只是PC SP DX的修改 创建最初的m0 创建最初的g0

schedt结构体用来保存调度器的状态信息和goroutine的全局运行队列












运行Go程序时 通过一个Go的runtime函数完成初始化工作(包括schedule和GC) 最开始会创建m0和g0 为main生成一个goroutine由m0执行



m0全局变量 与m0绑定的g0也是全局变量






每个线程都有一个特殊goroutine g0用于调度

```go
type m struct {
   g0      *g     // goroutine with scheduling stack
   mstartfn        func()
   curg            *g       // current running goroutine
   p               puintptr // attached p for executing go code (nil if not executing go code)
   nextp           puintptr
   id              int64
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




```asm
// asm_amd64.s
TEXT runtime·rt0_go(SB),NOSPLIT|NOFRAME|TOPFRAME,$0
	// copy arguments forward on an even stack
	MOVQ	DI, AX		// argc
	MOVQ	SI, BX		// argv
	SUBQ	$(5*8), SP		// 3args 2auto
	ANDQ	$~15, SP
	MOVQ	AX, 24(SP)
	MOVQ	BX, 32(SP)

	// create istack out of the given (operating system) stack.
	// _cgo_init may update stackguard.
	MOVQ	$runtime·g0(SB), DI
	LEAQ	(-64*1024)(SP), BX
	MOVQ	BX, g_stackguard0(DI)
	MOVQ	BX, g_stackguard1(DI)
	MOVQ	BX, (g_stack+stack_lo)(DI)
	MOVQ	SP, (g_stack+stack_hi)(DI)

	// find out information about the processor we're on
	MOVL	$0, AX
	CPUID
	CMPL	AX, $0
	JE	nocpuinfo

	CMPL	BX, $0x756E6547  // "Genu"
	JNE	notintel
	CMPL	DX, $0x49656E69  // "ineI"
	JNE	notintel
	CMPL	CX, $0x6C65746E  // "ntel"
	JNE	notintel
	MOVB	$1, runtime·isIntel(SB)

	// update stackguard after _cgo_init
	MOVQ	$runtime·g0(SB), CX
	MOVQ	(g_stack+stack_lo)(CX), AX
	ADDQ	$const_stackGuard, AX
	MOVQ	AX, g_stackguard0(CX)
	MOVQ	AX, g_stackguard1(CX)


	LEAQ	runtime·m0+m_tls(SB), DI
	CALL	runtime·settls(SB)

	// store through it, to make sure it works
	get_tls(BX)
	MOVQ	$0x123, g(BX)
	MOVQ	runtime·m0+m_tls(SB), AX
	CMPQ	AX, $0x123
	JEQ 2(PC)
	CALL	runtime·abort(SB)
ok:
	// set the per-goroutine and per-mach "registers"
	get_tls(BX)
	LEAQ	runtime·g0(SB), CX
	MOVQ	CX, g(BX)
	LEAQ	runtime·m0(SB), AX

	// save m->g0 = g0
	MOVQ	CX, m_g0(AX)
	// save m0 to g0->m
	MOVQ	AX, g_m(CX)

	CLD				// convention is D is always left cleared

	// Check GOAMD64 requirements
	// We need to do this after setting up TLS, so that
	// we can report an error if there is a failure. See issue 49586.

	CALL	runtime·check(SB)

	MOVL	24(SP), AX		// copy argc
	MOVL	AX, 0(SP)
	MOVQ	32(SP), AX		// copy argv
	MOVQ	AX, 8(SP)
	CALL	runtime·args(SB)
	CALL	runtime·osinit(SB)
	CALL	runtime·schedinit(SB)

	// create a new goroutine to start program
	MOVQ	$runtime·mainPC(SB), AX		// entry
	PUSHQ	AX
	CALL	runtime·newproc(SB)
	POPQ	AX

	// start this M
	CALL	runtime·mstart(SB)

	CALL	runtime·abort(SB)	// mstart should never return
	RET
	
// mainPC is a function value for runtime.main, to be passed to newproc.
// The reference to runtime.main is made via ABIInternal, since the
// actual function (not the ABI0 wrapper) is needed by newproc.
DATA	runtime·mainPC+0(SB)/8,$runtime·main<ABIInternal>(SB)
GLOBL	runtime·mainPC(SB),RODATA,$8
```







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

调度的核心策略位于 `runtime.schedule` 函数
Go scheduler 的调度 goroutine 过程中所调用的核心函数链如下：

```
runtime.schedule --> runtime.execute --> runtime.gogo --> goroutine code --> runtime.goexit --> runtime.goexit1 
  --> runtime.mcall --> runtime.goexit0 --> runtime.schedule
```
Go scheduler 会不断循环调用 runtime.schedule() 去调度 goroutines，而每个 goroutine 执行完成并退出之后，会再次调用 runtime.schedule()，使得调度器回到调度循环去执行其他的 goroutine，不断循环，永不停歇。
当我们使用 go 关键字启动一个新 goroutine 时，最终会调用 runtime.newproc --> runtime.newproc1，来得到 g，runtime.newproc1 会先从 P 的 gfree 缓存链表中查找可用的 g，
若缓存未生效，则会新创建 g 给当前的业务函数，最后这个 g 会被传给 runtime.gogo 去真正执行



### 调度时机


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


runtime.mcall 主要的工作就是是从当前 goroutine 切换回 g0 的系统堆栈，然后调用 fn(g)，而此时 runtime.mcall 调用执行的是 runtime.park_m，
这个方法里会利用 CAS 把当前运行的 goroutine -- gp 的状态 从 _Grunning 切换到 _Gwaiting，表明该 goroutine 已进入到等待唤醒状态，此时封存和休眠 G 的操作就完成了，只需等待就绪之后被重新唤醒执行即可
最后调用 runtime.schedule() 再次进入调度循环，去执行下一个 goroutine，充分利用 CPU

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

### execute

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

### gogo

runtime.gogo 函数切换协程上下文 此时需要操作寄存器 所以函数是由汇编实现


```asm

// func gogo(buf *gobuf)
// restore state from Gobuf; longjmp
TEXT runtime·gogo(SB), NOSPLIT, $0-8
	MOVQ	buf+0(FP), BX		// gobuf
	MOVQ	gobuf_g(BX), DX
	MOVQ	0(DX), CX		// make sure g != nil
	JMP	gogo<>(SB)

TEXT gogo<>(SB), NOSPLIT, $0
	get_tls(CX)
	MOVQ	DX, g(CX)
	MOVQ	DX, R14		// set the g register
	MOVQ	gobuf_sp(BX), SP	// restore SP
	MOVQ	gobuf_ret(BX), AX
	MOVQ	gobuf_ctxt(BX), DX
	MOVQ	gobuf_bp(BX), BP
	MOVQ	$0, gobuf_sp(BX)	// clear to help garbage collector
	MOVQ	$0, gobuf_ret(BX)
	MOVQ	$0, gobuf_ctxt(BX)
	MOVQ	$0, gobuf_bp(BX)
	MOVQ	gobuf_pc(BX), BX
	JMP	BX
```

### 抢占

为了让每个协程都有执行的机会，并且最大化利用CPU资源，Go语言在初始化时会启动一个特殊的线程来执行系统监控任务。
系统监控在一个独立的M上运行，不用绑定逻辑处理器P，系统监控每隔10ms会检测是否有准备就绪的网络协程，并放置到全局队列中。
和抢占调度相关的是，系统监控服务会判断当前协程是否运行时间过长，或者处于系统调用阶段，如果是，则会抢占当前G的执行。其核心逻辑位于runtime.retake函数中



#### Interrput

1.14实现基于信号抢占 向运行的P绑定的M发送SIGURG信号



### findRunnable

schedule -> findRunnable

Finds a runnable goroutine to execute.
Tries to steal from other P's, get g from local or global queue, poll network. 
tryWakeP indicates that the returned goroutine is not normal (GC worker, trace reader) so the caller should try to wake a P.

```go
func findRunnable() (gp *g, inheritTime, tryWakeP bool) {
    mp := getg().m

    // The conditions here and in handoffp must agree: if
    // findrunnable would return a G to run, handoffp must start
    // an M.

top:
    pp := mp.p.ptr()
    if sched.gcwaiting.Load() {
        gcstopm()
        goto top
    }
    if pp.runSafePointFn != 0 {
        runSafePointFn()
    }

    // now and pollUntil are saved for work stealing later,
    // which may steal timers. It's important that between now
    // and then, nothing blocks, so these numbers remain mostly
    // relevant.
    now, pollUntil, _ := pp.timers.check(0)

    // Try to schedule the trace reader.
    if traceEnabled() || traceShuttingDown() {
        gp := traceReader()
        if gp != nil {
            trace := traceAcquire()
            casgstatus(gp, _Gwaiting, _Grunnable)
            if trace.ok() {
                trace.GoUnpark(gp, 0)
                traceRelease(trace)
            }
            return gp, false, true
        }
    }

    // Try to schedule a GC worker.
    if gcBlackenEnabled != 0 {
        gp, tnow := gcController.findRunnableGCWorker(pp, now)
        if gp != nil {
            return gp, false, true
        }
        now = tnow
    }

    // Check the global runnable queue once in a while to ensure fairness.
    // Otherwise two goroutines can completely occupy the local runqueue
    // by constantly respawning each other.
    if pp.schedtick%61 == 0 && sched.runqsize > 0 {
        lock(&sched.lock)
        gp := globrunqget(pp, 1)
        unlock(&sched.lock)
        if gp != nil {
            return gp, false, false
        }
    }

    // Wake up the finalizer G.
    if fingStatus.Load()&(fingWait|fingWake) == fingWait|fingWake {
        if gp := wakefing(); gp != nil {
            ready(gp, 0, true)
        }
    }
    if *cgo_yield != nil {
        asmcgocall(*cgo_yield, nil)
    }

    // local runq
    if gp, inheritTime := runqget(pp); gp != nil {
        return gp, inheritTime, false
    }

    // global runq
    if sched.runqsize != 0 {
        lock(&sched.lock)
        gp := globrunqget(pp, 0)
        unlock(&sched.lock)
        if gp != nil {
            return gp, false, false
        }
    }

    // Poll network.
    // This netpoll is only an optimization before we resort to stealing.
    // We can safely skip it if there are no waiters or a thread is blocked
    // in netpoll already. If there is any kind of logical race with that
    // blocked thread (e.g. it has already returned from netpoll, but does
    // not set lastpoll yet), this thread will do blocking netpoll below
    // anyway.
    if netpollinited() && netpollAnyWaiters() && sched.lastpoll.Load() != 0 {
        if list, delta := netpoll(0); !list.empty() { // non-blocking
            gp := list.pop()
            injectglist(&list)
            netpollAdjustWaiters(delta)
            trace := traceAcquire()
            casgstatus(gp, _Gwaiting, _Grunnable)
            if trace.ok() {
                trace.GoUnpark(gp, 0)
                traceRelease(trace)
            }
            return gp, false, false
        }
    }

    // Spinning Ms: steal work from other Ps.
    //
    // Limit the number of spinning Ms to half the number of busy Ps.
    // This is necessary to prevent excessive CPU consumption when
    // GOMAXPROCS>>1 but the program parallelism is low.
    if mp.spinning || 2*sched.nmspinning.Load() < gomaxprocs-sched.npidle.Load() {
        if !mp.spinning {
            mp.becomeSpinning()
        }

        gp, inheritTime, tnow, w, newWork := stealWork(now)
        if gp != nil {
            // Successfully stole.
            return gp, inheritTime, false
        }
        if newWork {
            // There may be new timer or GC work; restart to
            // discover.
            goto top
        }

        now = tnow
        if w != 0 && (pollUntil == 0 || w < pollUntil) {
            // Earlier timer to wait for.
            pollUntil = w
        }
    }

    // We have nothing to do.
    //
    // If we're in the GC mark phase, can safely scan and blacken objects,
    // and have work to do, run idle-time marking rather than give up the P.
    if gcBlackenEnabled != 0 && gcMarkWorkAvailable(pp) && gcController.addIdleMarkWorker() {
        node := (*gcBgMarkWorkerNode)(gcBgMarkWorkerPool.pop())
        if node != nil {
            pp.gcMarkWorkerMode = gcMarkWorkerIdleMode
            gp := node.gp.ptr()

            trace := traceAcquire()
            casgstatus(gp, _Gwaiting, _Grunnable)
            if trace.ok() {
                trace.GoUnpark(gp, 0)
                traceRelease(trace)
            }
            return gp, false, false
        }
        gcController.removeIdleMarkWorker()
    }

    // wasm only:
    // If a callback returned and no other goroutine is awake,
    // then wake event handler goroutine which pauses execution
    // until a callback was triggered.
    gp, otherReady := beforeIdle(now, pollUntil)
    if gp != nil {
        trace := traceAcquire()
        casgstatus(gp, _Gwaiting, _Grunnable)
        if trace.ok() {
            trace.GoUnpark(gp, 0)
            traceRelease(trace)
        }
        return gp, false, false
    }
    if otherReady {
        goto top
    }

    // Before we drop our P, make a snapshot of the allp slice,
    // which can change underfoot once we no longer block
    // safe-points. We don't need to snapshot the contents because
    // everything up to cap(allp) is immutable.
    allpSnapshot := allp
    // Also snapshot masks. Value changes are OK, but we can't allow
    // len to change out from under us.
    idlepMaskSnapshot := idlepMask
    timerpMaskSnapshot := timerpMask

    // return P and block
    lock(&sched.lock)
    if sched.gcwaiting.Load() || pp.runSafePointFn != 0 {
        unlock(&sched.lock)
        goto top
    }
    if sched.runqsize != 0 {
        gp := globrunqget(pp, 0)
        unlock(&sched.lock)
        return gp, false, false
    }
    if !mp.spinning && sched.needspinning.Load() == 1 {
        // See "Delicate dance" comment below.
        mp.becomeSpinning()
        unlock(&sched.lock)
        goto top
    }
    if releasep() != pp {
        throw("findrunnable: wrong p")
    }
    now = pidleput(pp, now)
    unlock(&sched.lock)

    // Delicate dance: thread transitions from spinning to non-spinning
    // state, potentially concurrently with submission of new work. We must
    // drop nmspinning first and then check all sources again (with
    // #StoreLoad memory barrier in between). If we do it the other way
    // around, another thread can submit work after we've checked all
    // sources but before we drop nmspinning; as a result nobody will
    // unpark a thread to run the work.
    //
    // This applies to the following sources of work:
    //
    // * Goroutines added to the global or a per-P run queue.
    // * New/modified-earlier timers on a per-P timer heap.
    // * Idle-priority GC work (barring golang.org/issue/19112).
    //
    // If we discover new work below, we need to restore m.spinning as a
    // signal for resetspinning to unpark a new worker thread (because
    // there can be more than one starving goroutine).
    //
    // However, if after discovering new work we also observe no idle Ps
    // (either here or in resetspinning), we have a problem. We may be
    // racing with a non-spinning M in the block above, having found no
    // work and preparing to release its P and park. Allowing that P to go
    // idle will result in loss of work conservation (idle P while there is
    // runnable work). This could result in complete deadlock in the
    // unlikely event that we discover new work (from netpoll) right as we
    // are racing with _all_ other Ps going idle.
    //
    // We use sched.needspinning to synchronize with non-spinning Ms going
    // idle. If needspinning is set when they are about to drop their P,
    // they abort the drop and instead become a new spinning M on our
    // behalf. If we are not racing and the system is truly fully loaded
    // then no spinning threads are required, and the next thread to
    // naturally become spinning will clear the flag.
    //
    // Also see "Worker thread parking/unparking" comment at the top of the
    // file.
    wasSpinning := mp.spinning
    if mp.spinning {
        mp.spinning = false
        if sched.nmspinning.Add(-1) < 0 {
            throw("findrunnable: negative nmspinning")
        }

        // Note the for correctness, only the last M transitioning from
        // spinning to non-spinning must perform these rechecks to
        // ensure no missed work. However, the runtime has some cases
        // of transient increments of nmspinning that are decremented
        // without going through this path, so we must be conservative
        // and perform the check on all spinning Ms.
        //
        // See https://go.dev/issue/43997.

        // Check global and P runqueues again.

        lock(&sched.lock)
        if sched.runqsize != 0 {
            pp, _ := pidlegetSpinning(0)
            if pp != nil {
                gp := globrunqget(pp, 0)
                if gp == nil {
                    throw("global runq empty with non-zero runqsize")
                }
                unlock(&sched.lock)
                acquirep(pp)
                mp.becomeSpinning()
                return gp, false, false
            }
        }
        unlock(&sched.lock)

        pp := checkRunqsNoP(allpSnapshot, idlepMaskSnapshot)
        if pp != nil {
            acquirep(pp)
            mp.becomeSpinning()
            goto top
        }

        // Check for idle-priority GC work again.
        pp, gp := checkIdleGCNoP()
        if pp != nil {
            acquirep(pp)
            mp.becomeSpinning()

            // Run the idle worker.
            pp.gcMarkWorkerMode = gcMarkWorkerIdleMode
            trace := traceAcquire()
            casgstatus(gp, _Gwaiting, _Grunnable)
            if trace.ok() {
                trace.GoUnpark(gp, 0)
                traceRelease(trace)
            }
            return gp, false, false
        }

        // Finally, check for timer creation or expiry concurrently with
        // transitioning from spinning to non-spinning.
        //
        // Note that we cannot use checkTimers here because it calls
        // adjusttimers which may need to allocate memory, and that isn't
        // allowed when we don't have an active P.
        pollUntil = checkTimersNoP(allpSnapshot, timerpMaskSnapshot, pollUntil)
    }

    // Poll network until next timer.
    if netpollinited() && (netpollAnyWaiters() || pollUntil != 0) && sched.lastpoll.Swap(0) != 0 {
        sched.pollUntil.Store(pollUntil)
        if mp.p != 0 {
            throw("findrunnable: netpoll with p")
        }
        if mp.spinning {
            throw("findrunnable: netpoll with spinning")
        }
        delay := int64(-1)
        if pollUntil != 0 {
            if now == 0 {
                now = nanotime()
            }
            delay = pollUntil - now
            if delay < 0 {
                delay = 0
            }
        }
        if faketime != 0 {
            // When using fake time, just poll.
            delay = 0
        }
        list, delta := netpoll(delay) // block until new work is available
        // Refresh now again, after potentially blocking.
        now = nanotime()
        sched.pollUntil.Store(0)
        sched.lastpoll.Store(now)
        if faketime != 0 && list.empty() {
            // Using fake time and nothing is ready; stop M.
            // When all M's stop, checkdead will call timejump.
            stopm()
            goto top
        }
        lock(&sched.lock)
        pp, _ := pidleget(now)
        unlock(&sched.lock)
        if pp == nil {
            injectglist(&list)
            netpollAdjustWaiters(delta)
        } else {
            acquirep(pp)
            if !list.empty() {
                gp := list.pop()
                injectglist(&list)
                netpollAdjustWaiters(delta)
                trace := traceAcquire()
                casgstatus(gp, _Gwaiting, _Grunnable)
                if trace.ok() {
                    trace.GoUnpark(gp, 0)
                    traceRelease(trace)
                }
                return gp, false, false
            }
            if wasSpinning {
                mp.becomeSpinning()
            }
            goto top
        }
    } else if pollUntil != 0 && netpollinited() {
        pollerPollUntil := sched.pollUntil.Load()
        if pollerPollUntil == 0 || pollerPollUntil > pollUntil {
            netpollBreak()
        }
    }
    stopm()
    goto top
}
```


```go
// stealWork attempts to steal a runnable goroutine or timer from any P.
//
// If newWork is true, new work may have been readied.
//
// If now is not 0 it is the current time. stealWork returns the passed time or
// the current time if now was passed as 0.
func stealWork(now int64) (gp *g, inheritTime bool, rnow, pollUntil int64, newWork bool) {
    pp := getg().m.p.ptr()

    ranTimer := false

    const stealTries = 4
    for i := 0; i < stealTries; i++ {
        stealTimersOrRunNextG := i == stealTries-1

        for enum := stealOrder.start(cheaprand()); !enum.done(); enum.next() {
            if sched.gcwaiting.Load() {
                // GC work may be available.
                return nil, false, now, pollUntil, true
            }
            p2 := allp[enum.position()]
            if pp == p2 {
                continue
            }

            // Steal timers from p2. This call to checkTimers is the only place
            // where we might hold a lock on a different P's timers. We do this
            // once on the last pass before checking runnext because stealing
            // from the other P's runnext should be the last resort, so if there
            // are timers to steal do that first.
            //
            // We only check timers on one of the stealing iterations because
            // the time stored in now doesn't change in this loop and checking
            // the timers for each P more than once with the same value of now
            // is probably a waste of time.
            //
            // timerpMask tells us whether the P may have timers at all. If it
            // can't, no need to check at all.
            if stealTimersOrRunNextG && timerpMask.read(enum.position()) {
                tnow, w, ran := p2.timers.check(now)
                now = tnow
                if w != 0 && (pollUntil == 0 || w < pollUntil) {
                    pollUntil = w
                }
                if ran {
                    // Running the timers may have
                    // made an arbitrary number of G's
                    // ready and added them to this P's
                    // local run queue. That invalidates
                    // the assumption of runqsteal
                    // that it always has room to add
                    // stolen G's. So check now if there
                    // is a local G to run.
                    if gp, inheritTime := runqget(pp); gp != nil {
                        return gp, inheritTime, now, pollUntil, ranTimer
                    }
                    ranTimer = true
                }
            }

            // Don't bother to attempt to steal if p2 is idle.
            if !idlepMask.read(enum.position()) {
                if gp := runqsteal(pp, p2, stealTimersOrRunNextG); gp != nil {
                    return gp, false, now, pollUntil, ranTimer
                }
            }
        }
    }

    // No goroutines found to steal. Regardless, running a timer may have
    // made some goroutine ready that we missed. Indicate the next timer to
    // wait for.
    return nil, false, now, pollUntil, ranTimer
}
```

## Links

- [Concurrency](/docs/CS/Go/Concurrency/Concurrency.md)

## References
1. [Golang 程序启动流程分析](https://blog.tianfeiyu.com/2021/07/01/golang_bootstrap/#more)
2. [Understanding Real-World Concurrency Bugs in Go](https://songlh.github.io/paper/go-study.pdf)