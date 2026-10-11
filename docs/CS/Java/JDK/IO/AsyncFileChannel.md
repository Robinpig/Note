# AsynchronousFileChannel

## Introduction

很多人以为 JDK 7 引入的 `AsynchronousFileChannel`（NIO.2 异步文件通道）在 Linux 上底层是内核 AIO（`io_submit` / `io_getevents` / `libaio`）。JDK 25 (`jdk-25+36`) 源码证实：**并非如此**。Linux 上的 `AsynchronousFileChannel` 是标准的**线程池模拟**——把阻塞的 `read` / `write` / `lock` 包成 `Runnable` 提交到 `ExecutorService`，与真正的 Linux 内核 AIO 无关。这与 socket 侧 AIO（`EPollPort`，epoll + 线程池，见 [Selector (epoll)](/docs/CS/Java/JDK/IO/Selector_Epoll.md)）完全一致：Java NIO.2 在 Linux 整体没有用到内核 AIO，无论文件还是网络。

## Provider Chain

`AsynchronousFileChannel.open(Path)` 的调用链与直觉不同——它**不走** `AsynchronousChannelProvider`（NIO 异步通道的 provider 体系），而是走 NIO.2 的 `FileSystemProvider`：

```java
// AsynchronousFileChannel.java:244-252 (JDK 25, jdk-25+36)
public static AsynchronousFileChannel open(Path file,
                                           Set<? extends OpenOption> options,
                                           ExecutorService executor,
                                           FileAttribute<?>... attrs)
    throws IOException
{
    FileSystemProvider provider = file.getFileSystem().provider();
    return provider.newAsynchronousFileChannel(file, options, executor, attrs);
}
```

公开 API 的 Javadoc 自己承认这是线程池（afc.java:270-273）：

> The resulting channel is associated with **default thread pool** to which **tasks are submitted** to handle I/O events and dispatch to completion handlers...

`FileSystemProvider.newAsynchronousFileChannel` 的默认实现（JDK 标准）返回 `SimpleAsynchronousFileChannelImpl.open(...)`。这一原则在 `LinuxFileSystemProvider` / `UnixFileSystemProvider` 中**没有被 override 为内核 AIO 版本**——证据是 JDK 25 的 `src/java.base/linux/classes/sun/nio/ch/` 目录**只有** `DefaultAsynchronousChannelProvider` 和 `LinuxAsynchronousChannelProvider`（后者仅服务 socket / server-socket / group），**没有**任何文件通道的 Linux 专属实现。

## Thread Pool Mechanics

`SimpleAsynchronousFileChannelImpl`（位于 `share/classes/sun/nio/ch/`，跨平台通用，**非 Linux 专属**）就是模拟异步的核心。其类注释直白：

```java
// SimpleAsynchronousFileChannelImpl.java:37-42 (JDK 25)
/**
 * ...
 * systems that don't support asynchronous file I/O.
 */
public class SimpleAsynchronousFileChannelImpl
    extends AsynchronousFileChannelImpl
{
```

默认线程池（lazy init）：

```java
// SimpleAsynchronousFileChannelImpl.java:44-48
// lazy initialization of default thread pool for file I/O
private static class DefaultExecutorHolder {
    static final ExecutorService defaultExecutor =
        ThreadPool.createDefault().executor();
}
```

`open` 工厂：未指定 group / pool 时使用默认线程池：

```java
// SimpleAsynchronousFileChannelImpl.java:70-80
public static AsynchronousFileChannel open(FileDescriptor fdo,
                                           String path,
                                           boolean reading,
                                           boolean writing,
                                           ThreadPool pool)
{
    // Executor is either default or based on pool parameters
    ExecutorService executor = (pool == null) ?
        DefaultExecutorHolder.defaultExecutor : pool.executor();
    return new SimpleAsynchronousFileChannelImpl(fdo, path, reading, writing, executor);
}
```

异步读 / 写 / 锁的本质——构造 `Runnable` 把**阻塞的 native 调用**（`nd.read` / `nd.write` / `nd.lock`）放进任务，再 `executor.execute(task)`：

```java
// SimpleAsynchronousFileChannelImpl.java:212-249 (lock 为例，read/write 同构)
Runnable task = new Runnable() {
    public void run() {
        // ...
        int n;
        try {
            begin();
            do {
                n = nd.lock(fdObj, true, position, len, shared);
            } while ((n == FileDispatcher.INTERRUPTED) && isOpen());
            // ...
        } finally { /* end() */ }
        // 完成回调 dispatch
    }
};
// ...
executor.execute(task);   // <-- 线程池模拟异步，非内核 AIO
```

全文**没有任何** `io_submit` / `aio_read` / `libaio` 的 native 调用——只有普通的阻塞 `read(2)` / `write(2)` / `fcntl` 在池线程上执行。

## Socket AIO vs File AIO

把三类异步通道在 Linux 上的实现并列，更能看清 Java 的选择：

| 通道类型 | Linux 实现类 | 底层机制 | 是否内核 AIO |
|----------|--------------|----------|--------------|
| `AsynchronousSocketChannel` | `UnixAsynchronousSocketChannelImpl` + `EPollPort` | epoll 多路复用 + 线程池 | 否（epoll 模拟） |
| `AsynchronousServerSocketChannel` | `UnixAsynchronousServerSocketChannelImpl` + `EPollPort` | epoll 多路复用 + 线程池 | 否 |
| `AsynchronousFileChannel` | `SimpleAsynchronousFileChannelImpl` | 纯线程池（`ExecutorService`） | 否 |

socket 侧至少还借助 epoll 做事件分发；文件侧连 epoll 都没用，就是裸线程池。这与 [Selector (epoll)](/docs/CS/Java/JDK/IO/Selector_Epoll.md) 篇的结论（JDK `Selector` 在 Linux 是 epoll、AIO 由 epoll 模拟）相互印证。

## Why Not Kernel AIO

Linux 内核 AIO 由 `libaio` 用户态库封装 `io_setup` / `io_submit` / `io_getevents` 实现，但历史上局限明显，也是 JDK 一直回避它的原因：

- **真正异步的范围窄**：只有 `O_DIRECT`（绕过页缓存）下的块设备 I/O 才保证不阻塞；buffered I/O、管道、socket、多数文件系统上内核会「假异步」或直接返回 `-EAGAIN`，甚至退化为阻塞。
- **API 难用且与 NIO 模型冲突**：固定大小的请求环、要求 `O_DIRECT` 对齐、不支持 `fork` 后安全继承，与 Java 以 `ByteBuffer` / `Future` / `CompletionHandler` 为中心的抽象格格不入。
- **可移植性**：JDK 坚持 `SimpleAsynchronousFileChannelImpl` 这种跨平台通用实现，使同一份代码在 Windows（IOCP）、Solaris（`aio_*`）、Linux（线程池）上都能跑——内核 AIO 是 Linux-only 且行为不一致。

现代真正通用的内核异步接口是 `io_uring`（5.1+），但 JDK 主线截至 25 仍未内置（见 [io_uring](/docs/CS/Java/JDK/IO/Uring.md)）——需 `JUring`（FFM API）或 Netty incubator transport 等第三方接入。

## Kernel AIO vs Thread Pool

事实对照（澄清常见误解）：

| 维度 | 内核 AIO (`libaio`) | JDK `AsynchronousFileChannel` (线程池) |
|------|---------------------|----------------------------------------|
| 提交方式 | `io_submit` 系统调用，请求入内核队列 | `ExecutorService.execute(Runnable)` |
| 真正非阻塞 | 仅 `O_DIRECT` 部分场景 | 否——池线程自己阻塞在 `read(2)` / `write(2)` |
| 并发来源 | 内核态 I/O 调度 | 线程池 worker 线程 |
| JDK 是否使用 | **否** | 是（标准实现） |
| 第三方接入 | Netty `io_uring` / JNI `aio` 封装 | 标准 `java.nio` |

## Performance Implications

- **不要指望 AIO 比 NIO 更快**：在 Linux 上 `AsynchronousFileChannel` 只是把阻塞 I/O 挪到线程池，并没有减少系统调用或上下文切换，反而多了任务调度开销。高并发网络场景仍应直接用 Netty 而非原生 AIO。
- **线程池调优**：通过 `AsynchronousFileChannel.open(path, options, executor, attrs)` 显式传入 `ExecutorService`，或经由 `AsynchronousChannelGroup`（注意：file channel 的 group 仅影响 executor 分配，不改变「线程池模拟」本质）控制并发度。
- **大块文件 I/O**：若目标是减少拷贝 / 阻塞，更应关注 [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md) 与零拷贝（`transferTo` → `copy_file_range` / `sendfile`，见 [NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md)），而非切换到 AIO。

## Links

- [NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md)
- [Selector (epoll)](/docs/CS/Java/JDK/IO/Selector_Epoll.md)
- [io_uring](/docs/CS/Java/JDK/IO/Uring.md)
- [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)
- [Linux 内核 AIO（libaio）](/docs/CS/OS/Linux/IO/aio.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. JDK 25 source `java/nio/channels/AsynchronousFileChannel.java` (jdk-25+36, line 244-252, 270-273)
2. JDK 25 source `sun/nio/ch/SimpleAsynchronousFileChannelImpl.java` (jdk-25+36, line 37-48, 70-80, 212-249)
3. JDK 25 source `sun/nio/ch/LinuxAsynchronousChannelProvider.java` (jdk-25+36, 仅 socket/server-socket/group，无 file channel)
4. JDK 25 source `sun/nio/ch/DefaultAsynchronousChannelProvider.java` (jdk-25+36, 工厂类)
5. Linux kernel AIO (`libaio`): `io_setup` / `io_submit` / `io_getevents` man pages
6. `io_uring` (Linux 5.1+): Jens Axboe, <https://github.com/axboe/liburing>
