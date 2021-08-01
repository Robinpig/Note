# Kernel





## 内存管理

任务调度

数据结构

双向链表

/include/linux/list.h

红黑树

代码位于/lib/rbtree.c，内核I/O调度算法和内存管理都使用到红黑树。

radix树

代码位于/lib/radix-tree.c，radix树是一种以空间换时间的数据结构，适合稀疏的数据，在内核文件页缓存中采用。

## 进程管理

##### fork()

fork()调用成功，子进程是对父进程的复制，父进程返回值为子进程PID，子进程返回0，子进程可通过getppid()获得父进程PID，而父进程无法通过函数获取子进程PID；
进程创建失败，fork()返回-1。

### 进程通信

#### 管道

##### 匿名管道

进程间单向通信

创建管道：

pipe()函数创建匿名管道，需要有输入和输出端，成功返回0，固定读写写位置，不允许文件定位。

##### FIFO

命名管道，半双工模式，不同进程通过FIFO交换数据进行读写自动先入先出，mknod()函数或mkfifo()函数创建。

##### 消息队列

##### 共享存储

##### 信号量

## 设备管理

### PCI总线

## 文件系统

### VFS

Linux通过***VFS***(Virtual File System)管理文件系统，它为所有文件系统提供统一接口，其本身只存在于内存中，将文件系统抽象到内存。

其定义几个结构：

- **super_block** 超级块

对应具体文件系统的超级块，为其抽象结构

- **dentry** 目录项

每个文件都有**至少一个**目录项，目录项是一个特殊文件，维护树状结构。

内核使用hash表缓存dentry，加快查找

- **inode** 索引节点

inode保存文件大小、创建时间、文件的块大小等参数，以及对文件的读写函数、文件的读写缓存等信息。一个文件只有**一个**inode，其本身也是个文件。

内核提供hash链表数组inode_hashtable，所有inode结构都要链接到数组中某个hash链表，

- 文件

**硬盘中不存在文件结构。**

文件对象用于描述进程和文件交互关系，进程打开文件即动态创建一个文件对象，不同进程中文件对象不同。每个进程指向一个文件描述符表，里面维护打开的文件描述符。

挂载

## Spurious wakeup

A spurious wakeup happens when a thread wakes up from waiting on a condition variable that's been signaled, only to discover that the condition it was waiting for isn't satisfied. It's called spurious because the thread has seemingly been awakened for no reason. But spurious wakeups don't happen for no reason: 

*they usually happen because, in between the time when the condition variable was signaled and when the waiting thread finally ran, another thread ran and changed the condition.* There was a race condition between the threads, with the typical result that sometimes, the thread waking up on the condition variable runs first, winning the race, and sometimes it runs second, losing the race.

On many systems, especially multiprocessor systems, the problem of spurious wakeups is exacerbated because if there are several threads waiting on the condition variable when it's signaled, the system may decide to wake them all up, treating every signal( ) to wake one thread as a broadcast( ) to wake all of them, thus breaking any possibly expected 1:1 relationship between signals and wakeups. If there are ten threads waiting, only one will win and the other nine will experience spurious wakeups.

To allow for implementation flexibility in dealing with error conditions and races inside the operating system, condition variables may also be allowed to return from a wait even if not signaled, though it is not clear how many implementations actually do that. In the Solaris implementation of condition variables, a spurious wakeup may occur without the condition being signaled if the process is signaled; the wait system call aborts and returns EINTR. The Linux pthread implementation of condition variables guarantees it will not do that.

Because spurious wakeups can happen whenever there's a race and possibly even in the absence of a race or a signal, when a thread wakes on a condition variable, it should always check that the condition it sought is satisfied. If it's not, it should go back to sleeping on the condition variable, waiting for another opportunity.

