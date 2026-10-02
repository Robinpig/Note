## Introduction

[Lock/](/docs/CS/OS/Linux/Lock/README.md) 里的原语解决的是**同一进程内**（线程/内核上下文）的同步；当共享数据在**多个进程**之间——共享内存（[shmget/mmap](/docs/CS/OS/Linux/proc/IPC.md)）、父子进程映射的匿名内存——就需要进程间同步原语。它们大多构建在 futex 或文件系统之上，但比线程间同步多出两个独有问题：

- **另一端可能崩溃**：持锁的进程死了，锁由谁释放？（robust futex / 文件锁的自动回收就是为此设计）；
- **对方不是你的线程**：没有共享的地址空间，锁字必须放在双方都能看到的内存（共享内存/文件映射）或有内核中介（文件锁、命名信号量）。

## POSIX 信号量

两种形态，实现都是"futex 字 + 计数"（无竞争时纯用户态，见 [futex](/docs/CS/OS/Linux/Lock/futex.md)）：

```c
/* 命名信号量：由内核命名对象中介，落盘在 /dev/shm（tmpfs） */
sem_t *s = sem_open("/mysem", O_CREAT, 0666, 1);   /* 初值 1 = 二元信号量 */
sem_wait(s); sem_post(s);
sem_unlink("/mysem");                              /* 删除名字（引用仍在则对象存活） */

/* 无名信号量：pshared=1 时放在共享内存里，供多个进程使用 */
sem_t shared_sem;
sem_init(&shared_sem, 1, 1);       /* pshared=0 则退化为线程间用 */
sem_destroy(&shared_sem);
```

- `sem_wait`/`sem_trywait`/`sem_timedwait`/`sem_post`；`post` 可在信号处理函数中调用；
- 命名信号量依附 `/dev/shm`，**不会随进程退出消失**——忘记 `sem_unlink` 就是资源泄漏，`ls /dev/shm` 可查；
- 无名信号量的生命周期完全由使用者管理，配合 `mmap(MAP_SHARED)` 是共享内存互斥的最简方案。

## System V 信号量

比 POSIX 早三十年的老接口（XSI），至今仍被老代码和数据库使用：

```c
int id = semget(key, 1, IPC_CREAT | 0666);
semctl(id, 0, SETVAL, 1);                    /* 设置初值 */
struct sembuf op = { .sem_num = 0, .sem_op = -1, .sem_flg = SEM_UNDO };
semop(id, &op, 1);                           /* P 操作 */
```

- 一次管理一个**信号量集合**，`semop` 可原子地对集合内多个量操作（POSIX 信号量做不到）；
- `SEM_UNDO`：进程退出时内核自动回滚它的全部操作——**崩溃友好**，是它相对 POSIX 命名信号量的优点；
- 遗留问题：信号量对象本身仍需显式 `IPC_RMID`；`ipcs -s` 查看，全局数量受 `semmns` 等内核参数限制。

## 文件锁

把"锁"挂在文件上，由内核中介，天然跨无亲缘关系的进程：

```c
/* flock：整文件锁，挂在 open file description 上 */
int fd = open("/var/run/my.lock", O_RDWR | O_CREAT, 0666);
flock(fd, LOCK_EX);           /* 排斥锁；LOCK_SH 共享；LOCK_NB 非阻塞 */

/* fcntl 记录锁（推荐 OFD 锁） */
struct flock fl = { .l_type = F_WRLCK, .l_whence = SEEK_SET, .l_start = 0, .l_len = 0 };
fcntl(fd, F_OFD_SETLK, &fl);  /* Linux 3.15+：锁挂在 open file description */
```

三套语义的区别很关键：

- **`flock`**：整文件、挂在 fd（更准确地说是 open file description）上，`fork` 后父子共享同一把锁；语义简单，守护进程单实例检查的标准做法；
- **`F_SETLK`（传统 POSIX 记录锁）**：挂在**进程**上——同一进程的新锁会**替换**旧锁、关闭该文件**任意一个** fd 会释放该进程在此文件上的**全部**锁，这两个坑是无数 bug 的来源；
- **`F_OFD_SETLK`（OFD 锁）**：修复了上述语义，锁挂在 open file description 上，行为符合直觉，新代码一律用它。

文件锁最大的优势是**崩溃安全**：进程终止时内核自动释放其全部文件锁（`/proc/locks` 可见），无需 robust 机制。此外 `F_SETLEASE`（租约锁）还能在文件被他人打开时收到信号通知。

## 进程共享的 pthread 原语

pthread 的 mutex/cond/rwsem 也能跨进程：放进共享内存，并置 process-shared 属性——底层就是**共享 futex**（内核用 inode+offset 而非匿名地址做键）：

```c
pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED);
pthread_mutex_init(mutex_in_shm, &attr);
```

单独这样用仍有崩溃风险：持锁进程死亡，锁字永远停在"已锁"。补上 **robust mutex**：

```c
pthread_mutexattr_setrobust(&attr, PTHREAD_MUTEX_ROBUST);
```

持锁进程死亡时，内核通过 robust list 把 futex 字标记为 `FUTEX_OWNER_DIED`，下一个加锁者得到 `EOWNERDEAD`，调用 `pthread_mutex_consistent()` 声明数据已恢复一致后继续使用。这是共享内存互斥的**崩溃安全**标准方案（数据库、浏览器多进程架构都在用）。

需要优先级反转保护时，再加 `PTHREAD_PRIO_INHERIT`（落到 `FUTEX_LOCK_PI`，内核侧由 rt_mutex 承接，见 [mutex](/docs/CS/OS/Linux/Lock/mutex.md?id=rt_mutex-与优先级继承)）。

## 选择

| 场景 | 推荐 |
| :-- | :-- |
| 共享内存上的短临界区 | process-shared + robust mutex |
| 简单计数/单资源（可容忍无 robust） | POSIX 信号量（named 或 pshared） |
| 持锁方可能崩溃、必须自动释放 | **文件锁**（flock / F_OFD_SETLK） |
| 原子操作多个资源 | System V 信号量集合 |
| 需要优先级继承 | PI mutex（`PTHREAD_PRIO_INHERIT`） |

各机制的载体对比与 IPC 全景（pipe/消息队列/共享内存/socket）见 [IPC 总览](/docs/CS/OS/Linux/proc/IPC.md)；理论视角见 [Semaphores](/docs/CS/OS/process.md?id=semaphores)。

## 观测与调试

- `ipcs -s`（System V 信号量）、`ls -la /dev/shm`（命名 POSIX 信号量与共享内存）；
- `/proc/locks`：当前全部文件锁（类型、持有进程、范围）；
- `strace -e futex,semget,semop,flock,fcntl`：跨进程同步调用全部现形；`FUTEX_WAIT` 长时间不返回即锁竞争/死锁现场。

## Links

- [futex](/docs/CS/OS/Linux/Lock/futex.md) — 所有用户态进程间同步的内核基石
- [Linux Lock](/docs/CS/OS/Linux/Lock/README.md)
- [IPC 总览](/docs/CS/OS/Linux/proc/IPC.md)
- [pthread](/docs/CS/OS/Linux/proc/pthread.md)
- [Semaphores（理论）](/docs/CS/OS/process.md?id=semaphores)
