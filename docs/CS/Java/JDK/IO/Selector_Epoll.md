## Introduction

本页把 JDK NIO 的 [Selector](/docs/CS/Java/JDK/IO/NIO.md?id=selectors) 与 Linux 内核的 [epoll](/docs/CS/OS/Linux/IO/epoll.md) 在源码层面对接起来：一条 `Selector.open()` → `epoll_create1` → `epoll_ctl` → `epoll_wait` 的完整链路。所有结论均按 **JDK 25（`jdk-25+36`）** 源码核实，覆盖 `sun.nio.ch.EPoll` / `EPollSelectorImpl` / `EPoll.c` / `EPollPort` / `LinuxAsynchronousChannelProvider` / `IOStatus`。

内核侧的 `epoll` 机制、红黑树与就绪链表见 [epoll](/docs/CS/OS/Linux/IO/epoll.md)；本页只看 **JDK 如何封装并调用它**。

## SelectorProvider Resolution

`SelectorProvider.provider()` 是静态单例，按 OS 在类加载期选定实现，而非运行时探测：

```java
// sun.nio.ch.DefaultSelectorProvider (Linux)
public static SelectorProvider create() {
    String osname = AccessController
        .doPrivileged(new GetPropertyAction("os.name"));
    if (osname.equals("SunOS"))
        return createProvider("sun.nio.ch.DevPollSelectorProvider");
    if (osname.equals("Linux"))
        return createProvider("sun.nio.ch.EPollSelectorProvider");
    return new sun.nio.ch.PollSelectorProvider();
}
```

`EPollSelectorProvider` 极薄，只负责造 `Selector`：

```java
public class EPollSelectorProvider extends SelectorProviderImpl {
    public AbstractSelector openSelector() throws IOException {
        return new EPollSelectorImpl(this);
    }
}
```

> 结论：**Linux 上的默认 Selector 实现写死为 `EPollSelectorImpl`，由 epoll 支撑**；macOS/BSD 对应 `KQueueSelectorProvider`（kqueue），Solaris 用 `/dev/poll`（`DevPollSelectorProvider`）。这与 [Uring](/docs/CS/Java/JDK/IO/Uring.md?id=jdk-mainline-integration-status) 中"主线 JDK 仍基于 epoll、未内置 io_uring"的判断一致——选择引擎是编译期按平台决定的，不存在读取 `os.name` 之外的探测分支。

## EPoll: The Native Wrapper (JDK 25 Refactoring)

**版本陷阱**：大量旧文章/教程引用 `sun.nio.ch.EPollArrayWrapper`。在 JDK 25 中该类已被**重命名**为 `EPoll`（同时新增 `EPollPoller`、`EPollPort`）。凡是出现 `EPollArrayWrapper` 的资料，描述的都是 JDK 8–17 时代的代码布局，不能当作当前事实。

`EPoll` 是一个无实例的工具类，持有 3 个 native 方法与事件结构体的偏移量：

```java
class EPoll {
    // opcodes
    static final int EPOLL_CTL_ADD  = 1;
    static final int EPOLL_CTL_DEL  = 2;
    static final int EPOLL_CTL_MOD  = 3;

    // events
    static final int EPOLLIN   = 0x1;
    static final int EPOLLOUT  = 0x4;
    static final int EPOLLONESHOT = (1 << 30);

    private static final int SIZEOF_EPOLLEVENT = eventSize();   // sizeof(struct epoll_event)
    private static final int OFFSETOF_EVENTS   = eventsOffset();
    private static final int OFFSETOF_FD       = dataOffset();

    static native int create() throws IOException;
    static native int ctl(int epfd, int opcode, int fd, int events);
    static native int wait(int epfd, long pollAddress, int numfds, int timeout);

    // 事件数组在堆外分配（不走 Java 堆，避免 GC 移动地址）
    static long allocatePollArray(int count) {
        return unsafe.allocateMemory(count * SIZEOF_EPOLLEVENT);
    }
    static int getDescriptor(long eventAddress) {     // event->data.fd
        return unsafe.getInt(eventAddress + OFFSETOF_FD);
    }
    static int getEvents(long eventAddress) {         // event->events
        return unsafe.getInt(eventAddress + OFFSETOF_EVENTS);
    }
}
```

native 实现（`EPoll.c`）精确映射到三个系统调用，并发包 `epoll_event` 结构体：

```c
JNIEXPORT jint JNICALL Java_sun_nio_ch_EPoll_create(JNIEnv *env, jclass clazz) {
    int epfd = epoll_create1(EPOLL_CLOEXEC);          // 现代接口，非老 epoll_create
    if (epfd < 0) JNU_ThrowIOExceptionWithLastError(env, "epoll_create1 failed");
    return epfd;
}

JNIEXPORT jint JNICALL Java_sun_nio_ch_EPoll_ctl(JNIEnv *env, jclass clazz,
                          jint epfd, jint opcode, jint fd, jint events) {
    struct epoll_event event;
    event.events = events;
    event.data.fd = fd;                               // 把 fd 塞进 data 联合
    int res = epoll_ctl(epfd, (int)opcode, (int)fd, &event);
    return (res == 0) ? 0 : errno;
}

JNIEXPORT jint JNICALL Java_sun_nio_ch_EPoll_wait(JNIEnv *env, jclass clazz,
                           jint epfd, jlong address, jint numfds, jint timeout) {
    struct epoll_event *events = jlong_to_ptr(address);
    int res = epoll_wait(epfd, events, numfds, timeout);
    if (res < 0) {
        if (errno == EINTR) return IOS_INTERRUPTED;  // 映射成 IOStatus.INTERRUPTED
        JNU_ThrowIOExceptionWithLastError(env, "epoll_wait failed");
        return IOS_THROWN;
    }
    return res;
}
```

`eventSize()` / `eventsOffset()` / `dataOffset()` 分别返回 `sizeof(struct epoll_event)`、`offsetof(epoll_event, events)`、`offsetof(epoll_event, data)`。C 侧结构体为：

```c
typedef union epoll_data { void *ptr; int fd; uint32_t u32; uint64_t u64; } epoll_data_t;
struct epoll_event { uint32_t events; epoll_data_t data; };
```

在 x86-64 glibc 上 `sizeof(struct epoll_event) == 16`（4 字节 `events` + 4 字节对齐填充 + 8 字节 `data` 联合），故 `data.fd` 位于偏移 **8**。Java 端 `OFFSETOF_FD=8` 后，用 `Unsafe.getInt(eventAddress + 8)` 直接读出就绪 fd——这就是"零拷贝"地从内核返回的事件里取回 fd 的方式。

## EPollSelectorImpl: From select() to epoll_wait

`EPollSelectorImpl` 持有：epoll fd（`epfd`）、堆外事件数组（`pollArrayAddress`）、一个 `EventFD`（用于 `wakeup()` 中断）、以及 `fd → SelectionKeyImpl` 的 `HashMap`。

构造时创建 epoll 实例并把 eventfd 注册进去（注意是 **eventfd 而非老式 pipe**）：

```java
EPollSelectorImpl(SelectorProvider sp) throws IOException {
    this.epfd = EPoll.create();
    this.pollArrayAddress = EPoll.allocatePollArray(NUM_EPOLLEVENTS);
    this.eventfd = new EventFD();
    IOUtil.configureBlocking(IOUtil.newFD(eventfd.efd()), false);   // 非阻塞
    EPoll.ctl(epfd, EPOLL_CTL_ADD, eventfd.efd(), EPOLLIN);          // eventfd 进 epoll
}
```

### doSelect 主流程

```java
protected int doSelect(Consumer<SelectionKey> action, long timeout) throws IOException {
    int to = (int) Math.min(timeout, Integer.MAX_VALUE);
    processUpdateQueue();        // 把待生效的 interest-op 变更刷进 epoll_ctl
    processDeregisterQueue();
    int numEntries;
    if (Thread.currentThread().isVirtual()) {
        numEntries = (timedPoll) ? timedPoll(...) : untimedPoll(blocking);  // 虚线程走 Poller
    } else {
        try {
            begin(blocking);
            do {
                numEntries = EPoll.wait(epfd, pollArrayAddress, NUM_EPOLLEVENTS, to);
                if (numEntries == IOStatus.INTERRUPTED && timedPoll) {
                    to -= /* 按已用时调整超时 */;                            // 被信号打断要重算剩余时间
                }
            } while (numEntries == IOStatus.INTERRUPTED);
        } finally { end(blocking); }
    }
    processDeregisterQueue();
    return processEvents(numEntries, action);
}
```

要点：

- **`NUM_EPOLLEVENTS = Math.min(IOUtil.fdLimit(), 1024)`**：单次 `epoll_wait` 最多收割 1024 个事件（受进程 fd 上限约束）。
- **兴趣事件变更是延迟应用的**：`setEventOps` 只把 key 塞进 `updateKeys` 队列，`processUpdateQueue()` 在下次 `select` 时才真正调用 `EPoll.ctl`。新增（`registeredEvents==0`→`EPOLL_CTL_ADD`）、修改（`EPOLL_CTL_MOD`）、移除（`EPOLL_CTL_DEL`）三态由 `translateInterestOps()` 与已注册事件比对决定。
- **`EPOLL_CTL_DEL` 时 events 传 0**；`EPOLL_CTL_ADD/MOD` 时 events 由各 key 的 Java 兴趣位翻译而来（`SelectionKey.OP_READ=1`/`OP_WRITE=4` 恰与 `EPOLLIN=0x1`/`EPOLLOUT=0x4` 数值一致，connect/accept 再映射到对应的 EPOLLOUT/EPOLLIN 语义）。

### 事件解码

```java
private int processEvents(int numEntries, Consumer<SelectionKey> action) {
    for (int i = 0; i < numEntries; i++) {
        long event = EPoll.getEvent(pollArrayAddress, i);
        int fd = EPoll.getDescriptor(event);                  // 无需线性扫描：data.fd 直取
        if (fd == eventfd.efd()) {
            interrupted = true;                               // wakeup 信号
        } else {
            SelectionKeyImpl ski = fdToKey.get(fd);
            if (ski != null) {
                int rOps = EPoll.getEvents(event);            // 就绪的事件位
                processReadyEvents(rOps, ski, action);
            }
        }
    }
    if (interrupted) clearInterrupt();                        // 排空 eventfd
    return numKeysUpdated;
}
```

因为注册时把 `fd` 写进了 `epoll_event.data.fd`，收割时**直接用 `getDescriptor` 取出 fd，再用 `fdToKey` 这个 `HashMap` O(1) 反查 `SelectionKeyImpl`**，避免了在就绪数组里反复匹配 channel。

### wakeup 与中断

`wakeup()` 不再写 pipe，而是对 `EventFD` 做一次 `eventfd.set()`；阻塞在 `epoll_wait` 的线程因 eventfd 可读而返回，`processEvents` 检测到 eventfd 描述符即 `clearInterrupt()` 排空它。这条路径同样服务于 `Selector.close()` 与线程中断。

## Virtual Threads and the Poller

Loom 之后，`select()` 在虚拟线程上不能把 carrier 平台线程钉死在 `epoll_wait` 上。`EPollSelectorImpl` 对虚拟线程走 `untimedPoll` / `timedPoll`，其核心是：

```java
while (numEntries == 0 && !Thread.currentThread().isInterrupted()) {
    Poller.pollSelector(epfd, remainingNanos);   // 让出 carrier，由 Poller 代为等待
    numEntries = EPoll.wait(epfd, pollArrayAddress, NUM_EPOLLEVENTS, 0);
}
```

`Poller.pollSelector` 背后是 `EPollPoller`——一个**独立的 epoll 实例**，对目标 `epfd` 以 `EPOLLONESHOT` 方式注册，配合 `EPollPort` 的辅助线程在事件到来时唤醒被 park 的虚拟线程。其注册/收割代码与 Selector 同源：

```java
class EPollPoller extends Poller {
    EPollPoller(boolean subPoller, boolean read) throws IOException {
        this.epfd = EPoll.create();
        this.event = (read) ? EPOLLIN : EPOLLOUT;
        this.maxEvents = (subPoller) ? 64 : 512;
        this.address = EPoll.allocatePollArray(maxEvents);
    }
    void implRegister(int fdVal) throws IOException {
        int err = EPoll.ctl(epfd, EPOLL_CTL_MOD, fdVal, (event | EPOLLONESHOT));
        if (err == ENOENT) err = EPoll.ctl(epfd, EPOLL_CTL_ADD, fdVal, (event | EPOLLONESHOT));
        if (err != 0) throw new IOException("epoll_ctl failed: " + err);
    }
    int poll(int timeout) throws IOException {
        int n = EPoll.wait(epfd, address, maxEvents, timeout);
        while (i < n) { polled(EPoll.getDescriptor(EPoll.getEvent(address, i))); i++; }
        return n;
    }
}
```

`EPOLLONESHOT` 意味着每次事件触发后必须重新 `EPOLL_CTL_MOD` 才能再次被通知——这是 epoll 边沿触发语义下避免惊群/重复派发的标准做法（详见 [epoll](/docs/CS/OS/Linux/IO/epoll.md)）。

## AIO on Linux Is epoll, Not Kernel AIO

[IO](/docs/CS/Java/JDK/IO/IO.md) 中"Linux 的 AIO 由 epoll 模拟、实践中并不比 NIO 更快"这句话，在源码里有确定证据。`AsynchronousSocketChannel` 在 Linux 上经 `DefaultAsynchronousChannelProvider` → `LinuxAsynchronousChannelProvider`，其 channel group 就是 `EPollPort`：

```java
public class LinuxAsynchronousChannelProvider extends AsynchronousChannelProvider {
    public AsynchronousChannelGroup openAsynchronousChannelGroup(int nThreads, ThreadFactory f) {
        return new EPollPort(this, ThreadPool.create(nThreads, f)).start();
    }
    public AsynchronousSocketChannel openAsynchronousSocketChannel(AsynchronousChannelGroup group) {
        return new UnixAsynchronousSocketChannelImpl(toPort(group));   // toPort 要求 group 是 EPollPort
    }
}
```

`EPollPort` 的注释开宗明义——*"AsynchronousChannelGroup implementation based on the Linux epoll facility"*。它自己 `EPoll.create()` 一个 epoll 实例，`start()` 后跑一个任务线程循环：

```java
n = EPoll.wait(epfd, address, MAX_EPOLL_EVENTS, -1);   // 阻塞等待，timeout=-1
...
int fd = EPoll.getDescriptor(eventAddress);
int events = EPoll.getEvents(eventAddress);
// 把完成事件投入 BlockingQueue，由 channel 的回调/CompletionHandler 线程消费
```

每个注册都用 `(events | EPOLLONESHOT)`，事件触发后通过 `EPOLL_CTL_MOD` 重新武装。因此：

> **结论（订正常见误解）**：JDK 的 `AsynchronousChannel` 在 Linux 上**完全不依赖内核 AIO（`io_submit` / `io_getevents`）**，而是 `epoll + 线程池（或 `ForkJoinPool` 托管阻塞线程）` 的封装。与 NIO 共用同一套 epoll 核心，只是多了"事件 → 队列 → 回调"的派发层，所以没有数量级上的性能优势——这也是 Netty 等框架普遍绕过原生 AIO 的原因。真正想要内核级异步文件 I/O，仍要等 [io_uring](/docs/CS/Java/JDK/IO/Uring.md)（经 JUring / Netty incubator 接入）。

## Links

- [NIO](/docs/CS/Java/JDK/IO/NIO.md) — Selector/Channel 标准模型
- [epoll (Linux kernel)](/docs/CS/OS/Linux/IO/epoll.md) — 内核侧 epoll 数据结构与 ET/LT
- [io_uring](/docs/CS/Java/JDK/IO/Uring.md) — JDK 主线未集成，Java 侧经 JUring/Netty 接入
- [IO](/docs/CS/Java/JDK/IO/IO.md) — 五种 I/O 模型与 AIO 行
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) — 虚拟线程下 select 不钉死 carrier

## References

1. OpenJDK `jdk-25+36` source: `src/java.base/linux/classes/sun/nio/ch/EPoll.java`
2. OpenJDK `jdk-25+36` source: `src/java.base/linux/classes/sun/nio/ch/EPollSelectorImpl.java`
3. OpenJDK `jdk-25+36` source: `src/java.base/linux/native/libnio/ch/EPoll.c`
4. OpenJDK `jdk-25+36` source: `src/java.base/linux/classes/sun/nio/ch/EPollPort.java`
5. OpenJDK `jdk-25+36` source: `src/java.base/linux/classes/sun/nio/ch/LinuxAsynchronousChannelProvider.java`
6. OpenJDK `jdk-25+36` source: `src/java.base/share/classes/sun/nio/ch/IOStatus.java`
