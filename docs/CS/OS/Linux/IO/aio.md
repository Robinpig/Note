## Introduction

Linux Native AIO（常以用户态库 **libaio** 暴露）是内核自 2.5 时代就提供的**文件**异步 I/O 接口：应用通过 `io_setup` 建一个上下文，用 `io_submit` 提交一批读/写请求，再用 `io_getevents` 收割完成。它的设计初衷与 Windows IOCP 类似——让阶段①（数据准备）和阶段②（数据拷贝）都由内核完成、完成后再通知，从而把"真异步"带上 Linux。

但现实是：Native AIO 在 Linux 上**长期不温不火**，并最终被 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)（5.1+）取代。本笔记对照内核 **v7.2.7** 源码（`fs/aio.c`）梳理它到底能做什么、为什么连"异步"都名不副实，并解释 **JDK 为何从未采用它**——这与 Java 侧 [AsynchronousFileChannel 是线程池模拟](/docs/CS/Java/JDK/IO/AsyncFileChannel.md) 的结论恰好咬合。

## Interface: Four System Calls

libaio 的五个系统调用在 `fs/aio.c` 中都有 `SYSCALL_DEFINE`（其余 `io_cancel`/`io_pgetevents` 为变体）：

```c
// fs/aio.c
SYSCALL_DEFINE2(io_setup, unsigned, nr_events, aio_context_t __user *, ctxp)        // 1435
SYSCALL_DEFINE1(io_destroy, aio_context_t, ctx)                                    // 1504
SYSCALL_DEFINE3(io_submit, aio_context_t, ctx_id, long, nr,
                struct iocb __user * __user *, iocbpp)                             // 2135
SYSCALL_DEFINE5(io_getevents, aio_context_t, ctx_id,
                long, min_nr, long, nr,
                struct io_event __user *, events,
                struct timespec __user *, timeout)                                // 2304
```

- **`io_setup`**：创建 `kioctx`，并在用户态 **mmap 一张完成环**（`io_event` 数组），应用此后读完成不必每次陷入内核；
- **`io_submit`**：把 `nr` 个 `struct iocb` 逐个提交（`io_submit_one` 串行循环，见下）；
- **`io_getevents`**：从完成环收割 `io_event`，可阻塞等待 `min_nr` 个完成；
- **`io_destroy`**：拆除上下文。

注意 `io_submit` 的循环体直接 `io_submit_one(ctx, user_iocb, false)`（2170 行），**没有任何批处理或 SQ/CQ 魔法**——每个 iocb 都要从用户态 `get_user` 拷进来、逐个提交；这与 io_uring 一次填一堆 SQE 再统一 `enter` 有代际差距。

## Core Structures

```c
// fs/aio.c
struct kioctx {
    struct percpu_ref   users;
    /* ... */
    unsigned            nr_events;      /* ring buffer size, in io_event */
    unsigned long       mmap_base;      /* user-mapped completion ring */
    unsigned long       mmap_size;
    struct folio        **ring_folios;  /* pages backing the ring */
    struct file         *aio_ring_file;
    /* ... */
};
```

`kioctx` 的 `mmap_base`/`ring_folios`/`aio_ring_file` 就是 libaio 用户态那张完成环——`io_getevents` 读的就是它，这点与 io_uring 的 CQ 共享环思路相同，但 aio 的**提交侧没有共享环**（每次 `io_submit` 都要系统调用 + 拷贝 iocb）。

```c
// fs/aio.c
struct aio_kiocb {                       /* one per submitted iocb */
    union {
        struct file        *ki_filp;
        struct kiocb       rw;
    };
    /* ... */
    struct io_event        ki_res;       /* completion goes here */
    /* ... */
};
```

每个提交项在内核对应一个 `aio_kiocb`；完成时把结果写进 `ki_res`（一个 `io_event`），再由 `aio_complete` 推进完成环的 tail。

## Submission Path

`io_submit` → `io_submit_one` → `aio_run_iocb`（按操作类型分派）→ 文件读写走 `aio_read`/`aio_write`：

```c
// fs/aio.c
static int aio_read(struct kiocb *req, const struct iocb *iocb, bool vectored, bool compat)
{
    /* ... */
    file = req->ki_filp;
    if (unlikely(!(file->f_mode & FMODE_READ)))
        return -EBADF;
    if (unlikely(!file->f_op->read_iter))     /* ← socket has no read_iter */
        return -EINVAL;                       /*    → AIO rejects sockets */
    /* ... */
    ret = rw_verify_area(READ, file, &req->ki_pos, iov_iter_count(&iter));
    if (!ret)
        aio_rw_done(req, file->f_op->read_iter(req, &iter));
    /* ... */
}
```

真正决定"异步与否"的是 `aio_rw_done` 对返回值的处理：

```c
// fs/aio.c
static inline void aio_rw_done(struct kiocb *req, ssize_t ret)
{
    switch (ret) {
    case -EIOCBQUEUED:          /* 底层真正异步：请求被队列化，稍后回调 ki_complete */
        break;
    case -ERESTARTSYS:          /* 其它（含同步完成 / 错误）：直接同步完成 */
    /* ... */
    default:
        req->ki_complete(req, ret);
    }
}
```

- 底层 `read_iter` 若**异步**下发（典型是 O_DIRECT 走块层），返回 `-EIOCBQUEUED`，`aio_rw_done` 不立即完成，等 I/O 真完成时在软中断 / workqueue 里经 `aio_complete_rw`（1544，`req->ki_complete = aio_complete_rw`，1568）回调填环——这才是真异步；
- 其它情况（**含同步完成**）直接 `ki_complete` 把结果写进完成环，`io_submit` 返回时 I/O 其实已经做完。

## The O_DIRECT Restriction

**buffered I/O 在 `io_submit` 路径上就阻塞了，"异步"退化成同步。** 根因在 `aio_read` 调的 `file->f_op->read_iter`：

- 普通文件的 `read_iter`（如 `generic_file_read_iter`）遇到 **page cache miss** 时，会**就地阻塞等待磁盘 I/O 完成**（内部 `wait_on_page_locked` / 等块层），然后返回已读字节数（正值）；
- 这个阻塞发生在 `io_submit` 的内核栈里——**提交线程被卡住**，直到磁盘数据就绪；
- 返回正值后落到 `aio_rw_done` 的 `default` 分支，`ki_complete` 同步填完成环。

于是 buffered AIO 的"提交"与"完成"几乎同时发生，与 `read()` 阻塞调用没有本质区别。只有 **O_DIRECT**（绕过 page cache，直接下发异步块 I/O）才能让底层返回 `-EIOCBQUEUED`、走真正的异步完成路径。这是 Native AIO "只支持 Direct I/O 才真正异步" 的内核真相——和 [io_uring 笔记](/docs/CS/OS/Linux/IO/io_uring.md?id=introduction) 对其的批评完全吻合。

## No Network Support

`aio_read`/`aio_write` 都要求 `file->f_op->read_iter` / `write_iter`（1648/1676 行），而 **socket 的 `file_operations` 没有这两个方法**（网络用 `read`/`sendmsg`/`recvmsg` 等）。因此向 socket 提交 AIO 请求会直接 `return -EINVAL`。

换句话说，Native AIO 是一个**纯文件接口**——既不能异步网络 I/O，也无法把 `accept`/`connect`/`recv` 纳入同一异步框架。相比之下，io_uring 用同一套 SQ/CQ 把文件、网络甚至 `futex`/`openat` 全部异步化（见 [io_uring 的 opcode 表](/docs/CS/OS/Linux/IO/io_uring.md?id=opcode-one-interface-for-all-operations)）。这是两者代际差距的核心之一。

## Why JDK Never Adopted libaio

Java 的 [AsynchronousFileChannel 在 Linux 上不是内核 AIO，而是纯线程池模拟](/docs/CS/Java/JDK/IO/AsyncFileChannel.md)——`SimpleAsynchronousFileChannelImpl` 把阻塞读/写包成 `Runnable` 提交到 `ExecutorService`。JDK 选择这条路线而非 libaio，恰恰因为内核 AIO 的先天残疾：

1. **只支持文件、不支持网络**：而 Java NIO.2 的 `AsynchronousChannel` 体系要同时覆盖文件与 socket，libaio 满足不了；
2. **buffered I/O 在提交路径阻塞**：用 libaio 跑 buffered 文件 I/O 并不能释放调用线程，反而比线程池更难预测；
3. **接口陈旧、错误处理反直觉**：`io_event` 间接返回、cancel 语义脆弱、与 `epoll` 不能自然配合（两个独立的等待机制）。

与其在 libaio 的坑上再包一层，JDK 直接用通用线程池对外呈现一致的异步语义——代价是"异步"由用户态线程承担，而非内核。

## io_uring Supersedes It

[io_uring](/docs/CS/OS/Linux/IO/io_uring.md) 从三个维度解决了 Native AIO 的痛点：

| 维度 | Native AIO (libaio) | io_uring |
| --- | --- | --- |
| 提交开销 | 每次 `io_submit` 系统调用 + 拷贝 iocb | 填共享 SQ、必要时一次 `enter`（甚至 SQPOLL 免 syscall） |
| buffered I/O | 提交路径阻塞，退化同步 | 内联完成 / poll / io-wq 三条路径，buffered 也可真异步 |
| 网络 I/O | 不支持（`-EINVAL`） | `ACCEPT`/`CONNECT`/`SEND`/`RECV` 等全套 opcode |
| 框架统一性 | 纯文件，与 epoll 割裂 | 文件 / 网络 / 同步原语统一异步框架 |

也正因如此，JDK 社区"计划用 io_uring 做异步文件 I/O"的动机成立（见 [Uring 笔记](/docs/CS/Java/JDK/IO/Uring.md?id=jdk-mainline-integration-status)），只是截至 JDK 25 仍未进入主线。Native AIO 如今基本只剩数据库等"自带 O_DIRECT + 自己管理 buffer"的少数场景在用。

## Links

- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md) — 取代 Native AIO 的真异步框架
- [epoll](/docs/CS/OS/Linux/IO/epoll.md) — 同步就绪通知（JDK Selector 的底层）
- [IO 总览（五种模型）](/docs/CS/OS/Linux/IO/IO.md)
- [AsynchronousFileChannel 是线程池模拟（JDK 侧）](/docs/CS/Java/JDK/IO/AsyncFileChannel.md)
- [JDK 与 io_uring 的集成状态（JDK 侧）](/docs/CS/Java/JDK/IO/Uring.md)

## References

1. [fs/aio.c — Linux v7.2.7 source tree (local: /Users/robin/Tools/linux-7.2.7)](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/aio.c)
2. [Design Notes on Asynchronous I/O (aio) for Linux](http://lse.sourceforge.net/io/aionotes.txt)
3. [Efficient IO with io_uring — Jens Axboe](https://kernel.dk/io_uring.pdf)
