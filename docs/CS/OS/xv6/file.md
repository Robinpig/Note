## Introduction

xv6 的文件系统把"文件、目录、设备、管道"统一抽象成**文件描述符（fd）**——一个小整数，代表一个内核管理的对象。进程通过打开文件/目录/设备、建管道、或复制已有 fd 来获取它；按惯例 0/1/2 是标准输入/输出/错误，`sh` 正是靠这个约定实现重定向与管道。fd 的语义（open/read/write/close 等）在 [Syscall](/docs/CS/OS/xv6/Syscall.md) 里有分发说明。

本笔记从"进程视角"的 fd 表，一路下钻到"磁盘视角"的 inode 与块分配，最后串起 buffer cache 与日志（[device](/docs/CS/OS/xv6/device.md) 讲底层 MMIO/virtio，`bio.c`/`log.c` 是中间层）。

## 文件描述符表

每个进程在自己的 PCB 里持有一张私有 fd 表：

```c
// proc.h（节选）
struct proc {
  // ...
  struct file *ofile[NOFILE];   // 进程打开的文件表
  struct inode *cwd;            // 当前工作目录
  // ...
};
```

下标就是 fd 号（0 起），值指向内核全局的 `file` 结构。`dup` 复制一项、`fork` 让子进程共享同一张表（并各把 `file.ref` 加 1）、`close` 把 `file.ref` 减 1，归零才真正释放。

## file 结构

`file` 是"已打开对象"的内核表示，区分三种类型（普通 inode、管道、未使用）：

```c
// file.h
struct file {
  enum { FD_NONE, FD_PIPE, FD_INODE } type;
  int ref;              // 引用计数
  char readable;
  char writable;
  struct pipe *pipe;    // 若是管道
  struct inode *ip;     // 若是文件/设备
  uint off;             // 读写偏移
};
```

`fileread/filewrite/fileclose` 是这层的统一入口：按 `type` 分发到 `piperead/pipewrite` 或 `readi/writei`（inode I/O）；`off` 在每次读写后推进。

## inode：磁盘与内存两份

### 磁盘 inode（dinode）

文件元信息与数据块索引存在磁盘的 `dinode` 里，每个文件/目录一个：

```c
// fs.h
#define NDIRECT 12
#define NINDIRECT (BSIZE / sizeof(uint))
#define MAXFILE (NDIRECT + NINDIRECT)

struct dinode {
  short type;           // 0=空闲, 1=目录, 2=文件, 3=设备
  short major;
  short minor;
  short nlink;          // 硬链接数
  uint size;            // 字节数
  uint addrs[NDIRECT+1]; // 12 个直接块 + 1 个间接块
};
```

`type` 决定它是什么：`T_DIR`/`T_FILE`/`T_DEVICE`。数据块用 **12 个直接地址 + 1 个一级间接地址**（间接块里再存 `BSIZE/4` 个块号）寻址，故单个文件最大 `MAXFILE` 个块（xv6 块大小 1024 B，约 140 KB 上限）。

### 内存 inode

内核只把需要用到的 inode 缓存在内存：

```c
// fs.h
struct inode {
  uint dev;             // 设备号
  uint inum;            // inode 号
  int ref;              // 内存引用计数
  struct sleeplock lock;
  int flags;
  short type;
  short major;
  short minor;
  short nlink;
  uint size;
  uint addrs[NDIRECT+1];
};
```

`iget(dev, inum)` 取一个内存 inode（可能从磁盘读、可能命中缓存）、`iput` 减引用；`ilock/iunlock` 保证对某个 inode 的修改互斥。注意：内存 inode 与 fd 表是两层独立的引用计数（`ref` vs `file.ref`）。

## 目录与路径查找

目录本质是一个**特殊类型的文件**，内容是一串定长目录项：

```c
// fs.h
#define DIRSIZ 14
struct dirent {
  ushort inum;          // 指向的 inode 号
  char name[DIRSIZ];     // 文件名
};
```

`namei(path)` 把路径解析成内存 inode，内部走 `namex` 逐段查找：从根或当前目录出发，每段用 `dirlookup` 在目录文件里按 `name` 匹配 `dirent.inum`，再 `iget` 下一层，直到最后一段（创建文件时允许末段不存在）。

```
namei("/a/b/c")
  → iget(ROOT) → dirlookup("a") → iget(a)
  → dirlookup("b") → iget(b)
  → dirlookup("c") → iget(c)   // 返回 c 的 inode
```

`link`/`unlink`/`mkdir` 就是在这个目录项层做增删，并维护 `dinode.nlink` 与 `ip->nlink`。

## 管道（pipe）

`pipe()` 创建一对 fd，内核用 `struct pipe` 做无界 FIFO 缓冲：

```c
// pipe.c
#define PIPESIZE 512
struct pipe {
  struct spinlock lock;
  char data[PIPESIZE];
  uint nread;     // 下一个读位置
  uint nwrite;    // 下一个写位置
  int readopen;
  int writeopen;
};
```

`piperead` 在 `data` 环形缓冲上取字节并推进 `nread`，空了就睡眠等写者；`pipewrite` 推进 `nwrite`，满了就睡眠等读者。管道与文件的区别：它没有 inode、不落盘、靠 `lock + 睡眠/唤醒` 同步——这正是 [proc](/docs/CS/OS/xv6/proc.md) 里 sleep/wakeup 机制的典型用例。

## 分层与崩溃一致性

文件系统是分层的，越往下越接近硬件：

```
用户 open/read/write/close         ← [Syscall](/docs/CS/OS/xv6/Syscall.md)
        ↓
file*（fd 表 / 偏移 / 类型分发）
        ↓
inode（readi/writei/目录项）       ← 本页
        ↓
buffer cache（bio.c，块缓存）       ← [device](/docs/CS/OS/xv6/device.md)
        ↓
日志（log.c，把多步写打包成原子事务）
        ↓
virtio-blk / IDE 磁盘驱动           ← [device](/docs/CS/OS/xv6/device.md)
```

xv6 用一个**简单的预写日志（write-ahead log）**保证崩溃一致性：`log_write` 先把要改的块抄进日志区，`commit` 时一次性把日志回放到文件系统、再写提交标志。这样哪怕写到一半断电，重启时要么整组生效、要么被丢弃，不会出现"目录项写了但数据块没写"的半吊子状态。

## x86 与 RISC-V 差异

文件系统层在两份移植里是**同一份 C 代码**（`fs.c`/`file.c`/`bio.c`/`log.c`/`pipe.c`），差异只在最底层的块设备驱动：x86 用 IDE（`ide.c`/`memide.c`），RISC-V 用 virtio-blk（`virtio_disk.c`），两者都由 `bio.c` 通过 [device](/docs/CS/OS/xv6/device.md) 的抽象接口访问。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 系统调用](/docs/CS/OS/xv6/Syscall.md)
- [xv6 进程](/docs/CS/OS/xv6/proc.md)
- [xv6 设备管理](/docs/CS/OS/xv6/device.md)
- [xv6 内存管理](/docs/CS/OS/xv6/memory.md)
- [Linux 文件系统](/docs/CS/OS/Linux/fs/fs.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [xv6 中文文档](https://th0ar.gitbooks.io/xv6-chinese/content/)
