





Go netpoller 通过在底层对 epoll/kqueue/iocp 的封装，从而实现了使用同步编程模式达到异步执行的效果。总结来说，所有的网络操作都以网络描述符 netFD 为中心实现。
netFD 与底层 PollDesc 结构绑定，当在一个 netFD 上读写遇到 EAGAIN 错误时，
就将当前 goroutine 存储到这个 netFD 对应的 PollDesc 中，同时调用 gopark 把当前 goroutine 给 park 住，
直到这个 netFD 上再次发生读写事件，才将此 goroutine 给 ready 激活重新运行。
显然，在底层通知 goroutine 再次发生读写等事件的方式就是 epoll/kqueue/iocp 等事件驱动机制


Go 为了实现底层 I/O 多路复用的跨平台，分别基于上述的这些不同平台的系统调用实现了多版本的 netpollers，具体的源码路径位于src/runtime/下
以netpoll_epoll.go为例

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




TCP

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