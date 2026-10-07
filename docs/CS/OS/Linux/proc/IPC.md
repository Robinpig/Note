## Introduction

进程间通信（IPC）的核心问题是：**进程的地址空间彼此隔离，如何交换数据、传递事件、共享资源**。内核提供了一整套机制，代价与适用场景各不相同。

理论视角（竞态、临界区、信号量、管程等抽象）见 [InterProcess Communication](/docs/CS/OS/process.md?id=interprocess-communication)；同步原语（锁、futex）见 [Lock](/docs/CS/OS/Linux/Lock/README.md)。

## Mechanism Overview

| 机制 | 通信方向 | 是否跨主机 | 数据边界 | 是否内核参与每次传输 | 典型用途 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| [pipe 匿名管道](#pipe) | 单向（半双工） | 否 | 字节流 | 是（拷贝两次） | 父子进程、shell 管道 |
| FIFO（命名管道） | 单向 | 否 | 字节流 | 是 | 无亲缘关系进程，路径可寻址 |
| 消息队列（POSIX/SysV） | 双向 | 否 | 有边界（消息） | 是 | 结构化消息、内核缓冲 |
| 共享内存（mmap/shm） | 双向 | 否 | 裸内存 | 否（仅建立映射时） | **最高吞吐**，需自建同步 |
| 信号量（SysV/POSIX） | 事件/计数 | 否 | 无数据 | 是 | 共享内存的配套互斥与计数 |
| socket（AF_UNIX） | 双向 | **是**（跨主机） | 字节流/数据报 | 是 | 通用、可跨网络、可传 fd |
| 信号 | 单向事件 | 否 | 无数据（可带少量信息） | 是 | 通知、控制（见 [signal](/docs/CS/OS/Linux/proc/signal.md)） |

选择顺序通常是：**同机高吞吐 → 共享内存 + 信号量/futex；通用与跨机 → socket；简单父子 → pipe**。

## pipe

首先是 pipe（管道），它是一个单向(unidirectional)、半双工(half-duplex)的通信方式，一个写端和一个读端，写端写入、读端读出。虽然有些系统中没有单向的限制，但为了可移植性，请视它为单向。

要点：

- 内核用一个环形缓冲区（pipe buffer）实现，写满则写者阻塞，读空则读者阻塞——缓冲、同步、唤醒都由内核完成，因此使用极简单；
- 数据要**经过两次拷贝**（用户 → 内核缓冲区 → 用户），吞吐不如共享内存；
- 匿名管道只能通过 `fork` 继承 fd 的方式共享，因此限于有亲缘关系的进程；需要无亲缘进程使用则创建 FIFO（`mkfifo`）；
- 任一端关闭后的行为有明确约定：读端全关 → 写者收到 `SIGPIPE`；写端全关 → 读者读到 EOF（这正是 shell 管道 `cmd1 | cmd2` 的协作基础）。

## Shared Memory

`mmap(MAP_SHARED)` 或 `shm_open` + `mmap` 让多个进程映射同一物理页：**建立映射之后就完全不需要内核参与**，是 IPC 中吞吐最高的方式。代价是：

- 没有天然的同步——必须自己配一把锁，跨进程锁用 POSIX 信号量（`sem_wait`/`sem_post`）或基于共享内存的 [futex](/docs/CS/OS/Linux/Lock/futex.md)；
- 需要自己处理"谁是最后一个使用者"的回收问题（`shm_unlink` 后已映射者仍可用）。

## Semaphores and Message Queues

- **信号量**：跨进程的计数/事件原语，`sem_wait`/`sem_post` 无竞争时同样可以先在用户态尝试（POSIX 实现基于 futex），与内核内 [semaphore](/docs/CS/OS/Linux/Lock/semaphore.md) 同源；
- **消息队列**：内核维护的有界消息链表，`msgsnd`/`msgrcv` 保留消息边界，适合"少量结构化消息 + 内核缓冲"的场景；如今多被 socket 与 MQ 中间件取代。

## socket and Cross-Machine

AF_UNIX 域套接字在**同一台机器上**提供了 socket 语义（双向、可变类型）且支持**传递文件描述符**（`SCM_RIGHTS`）与凭据（`SCM_CREDENTIALS`）：这也是 systemd、D-Bus、容器运行时传递 fd 的标准做法。跨主机通信只能靠网络 socket，见 [socket](/docs/CS/OS/Linux/net/socket.md)。

## Relationship with Kernel Internal Mechanisms

- **同步**：共享内存方案必须自建锁，可用 POSIX 信号量或 process-shared mutex，详见[跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md)；内核侧对照见 [Lock](/docs/CS/OS/Linux/Lock/README.md)；
- **等待与唤醒**：pipe/消息队列的阻塞都基于[等待队列](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wait)，多读者/多写者时会出现惊群问题；
- **观察**：`ipcs`/`ipcs -m` 查看 SysV IPC 对象，`/proc/<pid>/fd` 与 `/proc/sysvipc/` 可辅助排查泄漏（见 [procfs](/docs/CS/OS/Linux/fs/proc.md)）。

## Links

- [processes](/docs/CS/OS/Linux/proc/process.md)
- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
- [InterProcess Communication（理论）](/docs/CS/OS/process.md?id=interprocess-communication)
- [Lock（内核同步）](/docs/CS/OS/Linux/Lock/README.md)
- [跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md) — 共享内存配什么锁、崩溃了怎么办
- [futex](/docs/CS/OS/Linux/Lock/futex.md)
- [signal](/docs/CS/OS/Linux/proc/signal.md)
- [socket](/docs/CS/OS/Linux/net/socket.md)
