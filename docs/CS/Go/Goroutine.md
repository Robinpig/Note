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



运行Go程序时 通过一个Go的runtime函数完成初始化工作(包括schedule和GC) 最开始会创建m0和g0 为main生成一个goroutine由m0执行







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

## schedule

调度的核心策略位于schedule函数 

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



### 抢占

为了让每个协程都有执行的机会，并且最大化利用CPU资源，Go语言在初始化时会启动一个特殊的线程来执行系统监控任务。
系统监控在一个独立的M上运行，不用绑定逻辑处理器P，系统监控每隔10ms会检测是否有准备就绪的网络协程，并放置到全局队列中。
和抢占调度相关的是，系统监控服务会判断当前协程是否运行时间过长，或者处于系统调用阶段，如果是，则会抢占当前G的执行。其核心逻辑位于runtime.retake函数中



#### Interrput

1.14实现基于信号抢占 向运行的P绑定的M发送SIGURG信号





## Links

