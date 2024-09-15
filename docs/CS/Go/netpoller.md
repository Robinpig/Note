## Introduction

网络轮询器不仅用于监控网络 I/O，还能用于监控文件的 I/O，它利用了操作系统提供的 I/O 多路复用模型来提升 I/O 设备的利用率以及程序的性能

网络轮询器并不是由运行时中的某一个线程独立运行的，运行时中的调度和系统调用会通过 runtime.netpoll 与网络轮询器交换消息，获取待执行的 Goroutine 列表，并将待执行的 Goroutine 加入运行队列等待处理。

所有的文件 I/O、网络 I/O 和计时器都是由网络轮询器管理的，它是 Go 语言运行时重要的组成部分



Go netpoller 通过在底层对 epoll/kqueue/iocp 的封装，从而实现了使用同步编程模式达到异步执行的效果。总结来说，所有的网络操作都以网络描述符 netFD 为中心实现。
netFD 与底层 PollDesc 结构绑定，当在一个 netFD 上读写遇到 EAGAIN 错误时，
就将当前 goroutine 存储到这个 netFD 对应的 PollDesc 中，同时调用 gopark 把当前 goroutine 给 park 住，
直到这个 netFD 上再次发生读写事件，才将此 goroutine 给 ready 激活重新运行。
显然，在底层通知 goroutine 再次发生读写等事件的方式就是 epoll/kqueue/iocp 等事件驱动机制


Go 为了实现底层 I/O 多路复用的跨平台，分别基于上述的这些不同平台的系统调用实现了多版本的 netpollers，具体的源码路径位于src/runtime/下
以netpoll_epoll.go为例

epoll、kqueue、solaries 等多路复用模块都要实现以下五个函数，这五个函数构成一个虚拟的接口：
```go
func netpollinit()
func netpollopen(fd uintptr, pd *pollDesc) int32
func netpoll(delta int64) gList
func netpollBreak()
func netpollIsPollDescriptor(fd uintptr) bool
```
上述函数在网络轮询器中分别扮演了不同的作用：

runtime.netpollinit — 初始化网络轮询器，通过 sync.Once 和 netpollInited 变量保证函数只会调用一次；
runtime.netpollopen — 监听文件描述符上的边缘触发事件，创建事件并加入监听；
runtime.netpoll — 轮询网络并返回一组已经准备就绪的 Goroutine，传入的参数会决定它的行为3；
如果参数小于 0，无限期等待文件描述符就绪；
如果参数等于 0，非阻塞地轮询网络；
如果参数大于 0，阻塞特定时间轮询网络；
runtime.netpollBreak — 唤醒网络轮询器，例如：计时器向前修改时间时会通过该函数中断网络轮询器4；
runtime.netpollIsPollDescriptor — 判断文件描述符是否被轮询器使用；






```go
func (pd *pollDesc) init(fd *FD) error {
    serverInit.Do(runtime_pollServerInit)
    ctx, errno := runtime_pollOpen(uintptr(fd.Sysfd))
    if errno != 0 {
        return errnoErr(syscall.Errno(errno))
    }
    pd.runtimeCtx = ctx
    return nil
}
```

操作系统中 I/O 多路复用函数会监控文件描述符的可读或者可写，而 Go 语言网络轮询器会监听 runtime.pollDesc 结构体的状态，该结构会封装操作系统的文件描述符：



```go
type pollDesc struct {
    _     sys.NotInHeap
    link  *pollDesc      // in pollcache, protected by pollcache.lock
    fd    uintptr        // constant for pollDesc usage lifetime
    fdseq atomic.Uintptr // protects against stale pollDesc

    // atomicInfo holds bits from closing, rd, and wd,
    // which are only ever written while holding the lock,
    // summarized for use by netpollcheckerr,
    // which cannot acquire the lock.
    // After writing these fields under lock in a way that
    // might change the summary, code must call publishInfo
    // before releasing the lock.
    // Code that changes fields and then calls netpollunblock
    // (while still holding the lock) must call publishInfo
    // before calling netpollunblock, because publishInfo is what
    // stops netpollblock from blocking anew
    // (by changing the result of netpollcheckerr).
    // atomicInfo also holds the eventErr bit,
    // recording whether a poll event on the fd got an error;
    // atomicInfo is the only source of truth for that bit.
    atomicInfo atomic.Uint32 // atomic pollInfo

    // rg, wg are accessed atomically and hold g pointers.
    // (Using atomic.Uintptr here is similar to using guintptr elsewhere.)
    rg atomic.Uintptr // pdReady, pdWait, G waiting for read or pdNil
    wg atomic.Uintptr // pdReady, pdWait, G waiting for write or pdNil

    lock    mutex // protects the following fields
    closing bool
    rrun    bool      // whether rt is running
    wrun    bool      // whether wt is running
    user    uint32    // user settable cookie
    rseq    uintptr   // protects from stale read timers
    rt      timer     // read deadline timer
    rd      int64     // read deadline (a nanotime in the future, -1 when expired)
    wseq    uintptr   // protects from stale write timers
    wt      timer     // write deadline timer
    wd      int64     // write deadline (a nanotime in the future, -1 when expired)
    self    *pollDesc // storage for indirect interface. See (*pollDesc).makeArg.
}
```

该结构体中包含用于监控可读和可写状态的变量，我们按照功能将它们分成以下四组：

rseq 和 wseq — 表示文件描述符被重用或者计时器被重置5；
rg 和 wg — 表示二进制的信号量，可能为 pdReady、pdWait、等待文件描述符可读或者可写的 Goroutine 以及 nil；
rd 和 wd — 等待文件描述符可读或者可写的截止日期；
rt 和 wt — 用于等待文件描述符的计时器；
除了上述八个变量之外，该结构体中还保存了用于保护数据的互斥锁、文件描述符。runtime.pollDesc 结构体会使用 link 字段串联成一个链表存储在 runtime.pollCache 中：
```go
type pollCache struct {
    lock  mutex
    first *pollDesc
}
```
runtime.pollCache 是运行时包中的全局变量，该结构体中包含一个用于保护轮询数据的互斥锁和链表头：

运行时会在第一次调用 runtime.pollCache.alloc 方法时初始化总大小约为 4KB 的 runtime.pollDesc 结构体，runtime.persistentalloc 会保证这些数据结构初始化在不会触发垃圾回收的内存中，让这些数据结构只能被内部的 epoll 和 kqueue 模块引用：
```go
func (c *pollCache) alloc() *pollDesc {
    lock(&c.lock)
    if c.first == nil {
        const pdSize = unsafe.Sizeof(pollDesc{})
        n := pollBlockSize / pdSize
        if n == 0 {
            n = 1
        }
        mem := persistentalloc(n*pdSize, 0, &memstats.other_sys)
        for i := uintptr(0); i < n; i++ {
            pd := (*pollDesc)(add(mem, i*pdSize))
            pd.link = c.first
            c.first = pd
        }
    }
    pd := c.first
    c.first = pd.link
    unlock(&c.lock)
    return pd
}
```

每次调用该结构体都会返回链表头还没有被使用的 runtime.pollDesc，这种批量初始化的做法能够增加网络轮询器的吞吐量。Go 语言运行时会调用 runtime.pollCache.free 方法释放已经用完的 runtime.pollDesc 结构，它会直接将结构体插入链表的最前面：
```go
func (c *pollCache) free(pd *pollDesc) {
    lock(&c.lock)
    pd.link = c.first
    c.first = pd
    unlock(&c.lock)
}
```

上述方法没有重置 runtime.pollDesc 结构体中的字段，该结构体被重复利用时才会由 runtime.poll_runtime_pollOpen 函数重置


网络轮询器实际上就是对 I/O 多路复用技术的封装，本节将通过以下的三个过程分析网络轮询器的实现原理：

- 网络轮询器的初始化；
- 如何向网络轮询器中加入待监控的任务；
- 如何从网络轮询器中获取触发的事件；

上述三个过程包含了网络轮询器相关的方方面面，能够让我们对其实现有完整的理解。需要注意的是，我们在分析实现时会遵循以下两个规则：

因为不同 I/O 多路复用模块的实现大同小异，本节会使用 Linux 操作系统上的 epoll 实现；
因为处理读事件和写事件的逻辑类似，本节会省略写事件相关的代码；
### 初始化

因为文件 I/O、网络 I/O 以及计时器都依赖网络轮询器，所以 Go 语言会通过以下两条不同路径初始化网络轮询器：

internal/poll.pollDesc.init — 通过 net.netFD.init 和 os.newFile 初始化网络 I/O 和文件 I/O 的轮询信息时；
runtime.doaddtimer — 向处理器中增加新的计时器时；
网络轮询器的初始化会使用 runtime.poll_runtime_pollServerInit 和 runtime.netpollGenericInit 两个函数：
```go
func poll_runtime_pollServerInit() {
    netpollGenericInit()
}
func netpollGenericInit() {
    if atomic.Load(&netpollInited) == 0 {
        lock(&netpollInitLock)
        if netpollInited == 0 {
            netpollinit()
            atomic.Store(&netpollInited, 1)
        }
        unlock(&netpollInitLock)
    }
}
```

runtime.netpollGenericInit 会调用平台上特定实现的 runtime.netpollinit 函数，即 Linux 上的 epoll，它主要做了以下几件事情：

是调用 epollcreate1 创建一个新的 epoll 文件描述符，这个文件描述符会在整个程序的生命周期中使用；
通过 runtime.nonblockingPipe 创建一个用于通信的管道；
使用 epollctl 将用于读取数据的文件描述符打包成 epollevent 事件加入监听；
```go
var (
    epfd int32 = -1
    netpollBreakRd, netpollBreakWr uintptr
)
func netpollinit() {
    epfd = epollcreate1(_EPOLL_CLOEXEC)
    r, w, _ := nonblockingPipe()
    ev := epollevent{
        events: _EPOLLIN,
    }
    *(**uintptr)(unsafe.Pointer(&ev.data)) = &netpollBreakRd
    epollctl(epfd, _EPOLL_CTL_ADD, r, &ev)
    netpollBreakRd = uintptr(r)
    netpollBreakWr = uintptr(w)
}
```

初始化的管道为我们提供了中断多路复用等待文件描述符中事件的方法，runtime.netpollBreak 函数会向管道中写入数据唤醒 epoll：
```go
func netpollBreak() {
    for {
        var b byte
        n := write(netpollBreakWr, unsafe.Pointer(&b), 1)
        if n == 1 {
            break
        }
        if n == -_EINTR {
            continue
        }
        if n == -_EAGAIN {
            return
        }
    }
}
```

因为目前的计时器由网络轮询器管理和触发，它能够让网络轮询器立刻返回并让运行时检查是否有需要触发的计时器。

轮询事件

调用 internal/poll.pollDesc.init 初始化文件描述符时不止会初始化网络轮询器，还会通过 runtime.poll_runtime_pollOpen 函数重置轮询信息 runtime.pollDesc 并调用 runtime.netpollopen 初始化轮询事件：
```go
func poll_runtime_pollOpen(fd uintptr) (*pollDesc, int) {
    pd := pollcache.alloc()
    lock(&pd.lock)
    if pd.wg != 0 && pd.wg != pdReady {
        throw(”runtime: blocked write on free polldesc“)
    }
    ...
    pd.fd = fd
    pd.closing = false
    pd.everr = false
    ...
    pd.wseq++
    pd.wg = 0
    pd.wd = 0
    unlock(&pd.lock)
    var errno int32
    errno = netpollopen(fd, pd)
    return pd, int(errno)
}
```

runtime.netpollopen 的实现非常简单，它会调用 epollctl 向全局的轮询文件描述符 epfd 中加入新的轮询事件监听文件描述符的可读和可写状态：
```go
func netpollopen(fd uintptr, pd *pollDesc) int32 {
    var ev epollevent
    ev.events = _EPOLLIN | _EPOLLOUT | _EPOLLRDHUP | _EPOLLET
    *(**pollDesc)(unsafe.Pointer(&ev.data)) = pd
    return -epollctl(epfd, _EPOLL_CTL_ADD, int32(fd), &ev)
}
```

从全局的 epfd 中删除待监听的文件描述符可以使用 runtime.netpollclose 函数，因为该函数的实现与 runtime.netpollopen 比较相似，所以这里就不展开分析了。

### 事件循环

本节将继续介绍网络轮询器的核心逻辑，也就是事件循环。我们将从以下的两个部分介绍事件循环的实现原理：

Goroutine 让出线程并等待读写事件；
多路复用等待读写事件的发生并返回；
上述过程连接了操作系统中的 I/O 多路复用机制和 Go 语言的运行时，在两个不同体系之间构建了桥梁，我们将分别介绍上述的两个过程。

等待事件

当我们在文件描述符上执行读写操作时，如果文件描述符不可读或者不可写，当前 Goroutine 就会执行 runtime.poll_runtime_pollWait 检查 runtime.pollDesc 的状态并调用 runtime.netpollblock 等待文件描述符的可读或者可写：
```go
func poll_runtime_pollWait(pd *pollDesc, mode int) int {
    ...
    for !netpollblock(pd, int32(mode), false) {
        ...
    }
    return 0
}
func netpollblock(pd *pollDesc, mode int32, waitio bool) bool {
    gpp := &pd.rg
    if mode == ’w‘ {
        gpp = &pd.wg
    }
    ...
    if waitio || netpollcheckerr(pd, mode) == 0 {
        gopark(netpollblockcommit, unsafe.Pointer(gpp), waitReasonIOWait, traceEvGoBlockNet, 5)
    }
    ...
}
```

runtime.netpollblock 是 Goroutine 等待 I/O 事件的关键函数，它会使用运行时提供的 runtime.gopark 让出当前线程，将 Goroutine 转换到休眠状态并等待运行时的唤醒。

### 轮询等待

Go 语言的运行时会在调度或者系统监控中调用 runtime.netpoll 轮询网络，该函数的执行过程可以分成以下几个部分：

根据传入的 delay 计算 epoll 系统调用需要等待的时间；
调用 epollwait 等待可读或者可写事件的发生；
在循环中依次处理 epollevent 事件；
因为传入 delay 的单位是纳秒，下面这段代码会将纳秒转换成毫秒：
```go
func netpoll(delay int64) gList {
    var waitms int32
    if delay < 0 {
        waitms = -1
    } else if delay == 0 {
        waitms = 0
    } else if delay < 1e6 {
        waitms = 1
    } else if delay < 1e15 {
        waitms = int32(delay / 1e6)
    } else {
        waitms = 1e9
    }
```
    
计算了需要等待的时间之后，runtime.netpoll 会执行 epollwait 等待文件描述符转换成可读或者可写，如果该函数返回了负值，就可能返回空的 Goroutine 列表或者重新调用 epollwait 陷入等待：
```go
    var events [128]epollevent
retry:
    n := epollwait(epfd, &events[0], int32(len(events)), waitms)
    if n < 0 {
        if waitms > 0 {
            return gList{}
        }
        goto retry
    }
```

当 epollwait 函数返回的值大于 0 时，就意味着被监控的文件描述符出现了待处理的事件，我们在如下所示的循环中就会依次处理这些事件：
```go
    var toRun gList
    for i := int32(0); i < n; i++ {
        ev := &events[i]
        if *(**uintptr)(unsafe.Pointer(&ev.data)) == &netpollBreakRd {
            ...
            continue
        }
        var mode int32
        if ev.events&(_EPOLLIN|_EPOLLRDHUP|_EPOLLHUP|_EPOLLERR) != 0 {
            mode += ’r‘
        }
        ...
        if mode != 0 {
            pd := *(**pollDesc)(unsafe.Pointer(&ev.data))
            pd.everr = false
            netpollready(&toRun, pd, mode)
        }
    }
    return toRun
}
```

处理的事件总共包含两种，一种是调用 runtime.netpollBreak 函数触发的事件，该函数的作用是中断网络轮询器；另一种是其他文件描述符的正常读写事件，对于这些事件，我们会交给 runtime.netpollready 处理：
```go
func netpollready(toRun *gList, pd *pollDesc, mode int32) {
    var rg, wg *g
    ...
    if mode == ’w‘ || mode == ’r‘+’w‘ {
        wg = netpollunblock(pd, ’w‘, true)
    }
    ...
    if wg != nil {
        toRun.push(wg)
    }
}
```

runtime.netpollunblock 会在读写事件发生时，将 runtime.pollDesc 中的读或者写信号量转换成 pdReady 并返回其中存储的 Goroutine；如果返回的 Goroutine 不会为空，那么该 Goroutine 就会被加入 toRun 列表，运行时会将列表中的全部 Goroutine 加入运行队列并等待调度器的调度。

### 截止日期

网络轮询器和计时器的关系非常紧密，这不仅仅是因为网络轮询器负责计时器的唤醒，还因为文件和网络 I/O 的截止日期也由网络轮询器负责处理。截止日期在 I/O 操作中，尤其是网络调用中很关键，网络请求存在很高的不确定因素，我们需要设置一个截止日期保证程序的正常运行，这时就需要用到网络轮询器中的 runtime.poll_runtime_pollSetDeadline 函数：
```go
func poll_runtime_pollSetDeadline(pd *pollDesc, d int64, mode int) {
    rd0, wd0 := pd.rd, pd.wd
    if d > 0 {
        d += nanotime()
    }
    pd.rd = d
    ...
    if pd.rt.f == nil {
        if pd.rd > 0 {
            pd.rt.f = netpollReadDeadline
            pd.rt.arg = pd
            pd.rt.seq = pd.rseq
            resettimer(&pd.rt, pd.rd)
        }
    } else if pd.rd != rd0 {
        pd.rseq++
        if pd.rd > 0 {
            modtimer(&pd.rt, pd.rd, 0, rtf, pd, pd.rseq)
        } else {
            deltimer(&pd.rt)
            pd.rt.f = nil
        }
    }
```

该函数会先使用截止日期计算出过期的时间点，然后根据 runtime.pollDesc 的状态做出以下不同的处理：

如果结构体中的计时器没有设置执行的函数时，该函数会设置计时器到期后执行的函数、传入的参数并调用 runtime.resettimer 重置计时器；
如果结构体的读截止日期已经被改变，我们会根据新的截止日期做出不同的处理：
如果新的截止日期大于 0，调用 runtime.modtimer 修改计时器；
如果新的截止日期小于 0，调用 runtime.deltimer 删除计时器；
在 runtime.poll_runtime_pollSetDeadline 函数的最后，会重新检查轮询信息中存储的截止日期：
```go
    var rg *g
    if pd.rd < 0 {
        if pd.rd < 0 {
            rg = netpollunblock(pd, ’r‘, false)
        }
        ...
    }
    if rg != nil {
        netpollgoready(rg, 3)
    }
    ...
}
```

如果截止日期小于 0，上述代码会调用 runtime.netpollgoready 直接唤醒对应的 Goroutine。

在 runtime.poll_runtime_pollSetDeadline 函数中直接调用 runtime.netpollgoready 是相对比较特殊的情况。在正常情况下，运行时都会在计时器到期时调用 runtime.netpollDeadline、runtime.netpollReadDeadline 和 runtime.netpollWriteDeadline 三个函数：



上述三个函数都会通过 runtime.netpolldeadlineimpl 调用 runtime.netpollgoready 直接唤醒相应的 Goroutine:
```go
func netpolldeadlineimpl(pd *pollDesc, seq uintptr, read, write bool) {
    currentSeq := pd.rseq
    if !read {
        currentSeq = pd.wseq
    }
    if seq != currentSeq {
        return
    }
    var rg *g
    if read {
        pd.rd = -1
        atomic.StorepNoWB(unsafe.Pointer(&pd.rt.f), nil)
        rg = netpollunblock(pd, ’r‘, false)
    }
    ...
    if rg != nil {
        netpollgoready(rg, 0)
    }
    ...
}
```

Goroutine 在被唤醒之后就会意识到当前的 I/O 操作已经超时，可以根据需要选择重试请求或者中止调用










## TCP

```go
type TCPListener struct {
    fd *netFD
    lc ListenConfig
}

func (l *TCPListener) Accept() (Conn, error) {
	if !l.ok() {
		return nil, syscall.EINVAL
	}
	c, err := l.accept()
	if err != nil {
		return nil, &OpError{Op: "accept", Net: l.fd.net, Source: nil, Addr: l.fd.laddr, Err: err}
	}
	return c, nil
}


func (ln *TCPListener) accept() (*TCPConn, error) {
	fd, err := ln.fd.accept()
	if err != nil {
		return nil, err
	}
	return newTCPConn(fd, ln.lc.KeepAlive, nil), nil
}

type TCPConn struct {
	conn
}

type conn struct {
	fd *netFD
}
```

net.Listen
调用 net.Listen 之后，底层会通过 Linux 的系统调用 socket 方法创建一个 fd 分配给 listener，并用以来初始化 listener 的 netFD ，接着调用 netFD 的 listenStream 方法完成对 socket 的 bind&listen 操作以及对 netFD 的初始化（主要是对 netFD 里的 pollDesc 的初始化），调用链是 runtime.runtime_pollServerInit --> runtime.poll_runtime_pollServerInit --> runtime.netpollGenericInit，主要做的事情是：
1. 调用 epollcreate1 创建一个 epoll 实例 epfd，作为整个 runtime 的唯一 event-loop 使用；
2. 调用 runtime.nonblockingPipe 创建一个用于和 epoll 实例通信的管道，这里为什么不用更新且更轻量的 eventfd 呢？我个人猜测是为了兼容更多以及更老的系统版本；
3. 将 netpollBreakRd 通知信号量封装成 epollevent 事件结构体注册进 epoll 实例。



Go runtime 在程序启动的时候会创建一个独立的 M 作为监控线程，叫 sysmon ，这个线程为系统级的 daemon 线程，无需 P 即可运行， sysmon 每 20us~10ms 运行一次。sysmon 中以轮询的方式执行以下操作（如上面的代码所示）：
1. 以非阻塞的方式调用 runtime.netpoll ，从中找出能从网络 I/O 中唤醒的 g 列表，并通过调用 injectglist 把 g 列表放入全局调度队列或者当前 P 本地调度队列等待被执行，调度触发时，有可能从这个全局 runnable 调度队列获取 g。然后再循环调用 startm ，直到所有 P 都不处于 _Pidle 状态。
2. 调用 retake ，抢占长时间处于 _Psyscall 状态的 P



netpoll 为什么一定要使用非阻塞 I/O 了吧？就是为了避免让操作网络 I/O 的 goroutine 陷入到系统调用从而进入内核态，因为一旦进入内核态，整个程序的控制权就会发生转移(到内核)，不再属于用户进程了，那么也就无法借助于 Go 强大的 runtime scheduler 来调度业务程序的并发了；而有了 netpoll 之后，借助于非阻塞 I/O ，G 就再也不会因为系统调用的读写而 (长时间) 陷入内核态，当 G 被阻塞在某个 network I/O 操作上时，实际上它不是因为陷入内核态被阻塞住了，而是被 Go runtime 调用 gopark 给 park 住了，此时 G 会被放置到某个 wait queue 中，而 M 会尝试运行下一个 _Grunnable 的 G，如果此时没有 _Grunnable 的 G 供 M 运行，那么 M 将解绑 P，并进入 sleep 状态。当 I/O available，在 epoll 的 eventpoll.rdr 中等待的 G 会被放到 eventpoll.rdllist 链表里并通过 netpoll 中的 epoll_wait 系统调用返回放置到全局调度队列或者 P 的本地调度队列，标记为 _Grunnable ，等待 P 绑定 M 恢复执行



goroutine-per-connection 这种模式虽然简单高效，但是在某些极端的场景下也会暴露出问题：goroutine 虽然非常轻量，它的自定义栈内存初始值仅为 2KB，后面按需扩容；海量连接的业务场景下， goroutine-per-connection ，此时 goroutine 数量以及消耗的资源就会呈线性趋势暴涨，虽然 Go scheduler 内部做了 g 的缓存链表，可以一定程度上缓解高频创建销毁 goroutine 的压力，但是对于瞬时性暴涨的长连接场景就无能为力了，大量的 goroutines 会被不断创建出来，从而对 Go runtime scheduler 造成极大的调度压力和侵占系统资源，然后资源被侵占又反过来影响 Go scheduler 的调度，进而导致性能下降