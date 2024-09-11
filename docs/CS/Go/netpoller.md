





Go netpoller 通过在底层对 epoll/kqueue/iocp 的封装，从而实现了使用同步编程模式达到异步执行的效果。总结来说，所有的网络操作都以网络描述符 netFD 为中心实现。
netFD 与底层 PollDesc 结构绑定，当在一个 netFD 上读写遇到 EAGAIN 错误时，
就将当前 goroutine 存储到这个 netFD 对应的 PollDesc 中，同时调用 gopark 把当前 goroutine 给 park 住，
直到这个 netFD 上再次发生读写事件，才将此 goroutine 给 ready 激活重新运行。
显然，在底层通知 goroutine 再次发生读写等事件的方式就是 epoll/kqueue/iocp 等事件驱动机制



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

调用 net.Listen 之后，底层会通过 Linux 的系统调用 socket 方法创建一个 fd 分配给 listener，并用以来初始化 listener 的 netFD ，
接着调用 netFD 的 listenStream 方法完成对 socket 的 bind&listen 操作以及对 netFD 的初始化（主要是对 netFD 里的 pollDesc 的初始化），
调用链是 runtime.runtime_pollServerInit --> runtime.poll_runtime_pollServerInit --> runtime.netpollGenericInit，主要做的事情是：
1. 调用 epollcreate1 创建一个 epoll 实例 epfd，作为整个 runtime 的唯一 event-loop 使用；
2. 调用 runtime.nonblockingPipe 创建一个用于和 epoll 实例通信的管道，这里为什么不用更新且更轻量的 eventfd 呢？我个人猜测是为了兼容更多以及更老的系统版本；
3. 将 netpollBreakRd 通知信号量封装成 epollevent 事件结构体注册进 epoll 实例