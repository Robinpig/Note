
select() allows a program to monitor multiple file descriptors, waiting until one or more of the file descriptors become "ready" for some class of I/O operation (e.g., input possible). A file descriptor is considered ready if it is possible to perform a corresponding I/O operation (e.g., read(2), or a sufficiently small write(2)) without blocking.

poll() performs a similar task to select(2): it waits for one of a set of file descriptors to become ready to perform I/O.

## select

```c
SYSCALL_DEFINE5(select, int, n, fd_set __user *, inp, fd_set __user *, outp,
    fd_set __user *, exp, struct timeval __user *, tvp)
{
    return kern_select(n, inp, outp, exp, tvp);
}
```

- `maxfd`：代表要监控的最大文件描述符`fd+1`
- `writefds`：监控可写的文件描述符`fd`集合
- `readfds`：监控可读的文件描述符`fd`集合
- `exceptfds`：监控异常事件的文件描述符`fd`集合
- `timeout`：超时时长

`select`将监听的文件描述符分为三组，每一组监听不同的I/O操作。`readfds/writefds/exceptfds`分别表示可写、可读、异常事件的文件描述符集合，这三个参数可以用`NULL`来表示对应的事件不需要监听。对fd_set的操作可以利用如下几个函数完成


```
void FD_CLR(int fd, fd_set *set);
int  FD_ISSET(int fd, fd_set *set);
void FD_SET(int fd, fd_set *set);
void FD_ZERO(fd_set *set);
```

`select`的调用会阻塞到有文件描述符可以进行IO操作或被信号打断或者超时才会返回。`timeout`参数用来指定超时时间，含义如下：

- `NULL`: 表示不设置超时，调用会一直阻塞直到文件描述符上的事件触发
- `0`: 表示不等待，立即返回，用于检测文件描述符状态
- 正整数: 表示指定时间内没有事件触发，则超时返回

`select`调用返回时，每个文件描述符集合均会被过滤，只保留得到事件响应的文件描述符。在下一次调用`select`时，描述符集合均需要重新设

`select`系统调用的进程/线程，会维护一个`struct poll_wqueues`结构，其中两个关键字段：

1. `pll_table`：该结构体中的函数指针`_qproc`指向`__pollwait`函数；
2. `struct poll_table_entry[]`：存放不同设备的`poll_table_entry`，这些条目的增加是在驱动调用`poll_wait->__pollwait()`时进行初始化并完成添加的；
```
struct poll_wqueues {
    poll_table pt;
    struct poll_table_page *table;
    struct task_struct *polling_task;
    int triggered;
    int error;
    int inline_index;
    struct poll_table_entry inline_entries[N_INLINE_POLL_ENTRIES];
};
```


```c
int core_sys_select(int n, fd_set __user *inp, fd_set __user *outp,
               fd_set __user *exp, struct timespec64 *end_time)
{
    fd_set_bits fds;

    //...

    if ((ret = get_fd_set(n, inp, fds.in)) ||
        (ret = get_fd_set(n, outp, fds.out)) ||
        (ret = get_fd_set(n, exp, fds.ex)))
        goto out;
    zero_fd_set(n, fds.res_in);
    zero_fd_set(n, fds.res_out);
    zero_fd_set(n, fds.res_ex);

    ret = do_select(n, &fds, end_time);

    if (set_fd_set(n, inp, fds.res_in) ||
        set_fd_set(n, outp, fds.res_out) ||
        set_fd_set(n, exp, fds.res_ex))
        ret = -EFAULT;
    //...
}
```

#### do_select
`select`系统调用，最终的核心逻辑是在`do_select`函数中处理的，参考`fs/select.c`文件；

- `do_select`函数中，有几个关键的操作：

1. 初始化`poll_wqueues`结构，包括几个关键函数指针的初始化，用于驱动中进行回调处理；
2. 循环遍历监测的文件描述符，并且调用`f_op->poll()`函数，如果有监测条件满足，则会跳出循环；
3. 在监测的文件描述符都不满足条件时，`poll_schedule_timeout`让当前进程进行睡眠，超时唤醒，或者被所属的等待队列唤醒；

- `do_select`函数的循环退出条件有三个：

1. 检测的文件描述符满足条件；
2. 超时；
3. 有信号要处理；

- 在设备驱动程序中实现的`poll()`函数，会在`do_select()`中被调用，而驱动中的`poll()`函数，需要调用`poll_wait()`函数，`poll_wait`函数本身很简单，就是去回调函数`p->_qproc()`，这个回调函数正是`poll_initwait()`函数中初始化的`__pollwait()`

- 驱动中的`poll_wait`函数回调`__pollwait`，这个函数完成的工作是向`struct poll_wqueue`结构中添加一条`poll_table_entry`；
- `poll_table_entry`中包含了等待队列的相关数据结构；
- 对等待队列的相关数据结构进行初始化，包括设置等待队列唤醒时的回调函数指针，设置成`pollwake`；
- 将任务添加到驱动程序中的等待队列中，最终驱动可以通过`wake_up_interruptile`等接口来唤醒处理；

```c
static int do_select(int n, fd_set_bits *fds, struct timespec64 *end_time)
{

    //...
    for (;;) {
        unsigned long *rinp, *routp, *rexp, *inp, *outp, *exp;

        inp = fds->in; outp = fds->out; exp = fds->ex;
        rinp = fds->res_in; routp = fds->res_out; rexp = fds->res_ex;

        for (i = 0; i < n; ++rinp, ++routp, ++rexp) {
            unsigned long in, out, ex, all_bits, bit = 1, j;
            unsigned long res_in = 0, res_out = 0, res_ex = 0;

            in = *inp++; out = *outp++; ex = *exp++;
            all_bits = in | out | ex;
            if (all_bits == 0) {
                i += BITS_PER_LONG;
                continue;
            }

            for (j = 0; j < BITS_PER_LONG; ++j, ++i, bit <<= 1) {
                struct fd f;
                f = fdget(i);
                if (f.file) {
                    //...
                }
            }
        }

        if (!poll_schedule_timeout(&table, TASK_INTERRUPTIBLE,
                       to, slack))
            timed_out = 1;
    }
    //...
}
```


## poll

`poll`函数与`select`不同，不需要为三种事件分别设置文件描述符集，而是构造了`pollfd`结构的数组，每个数组元素指定一个描述符`fd`以及对该描述符感兴趣的条件(events)。`poll`调用返回时，每个描述符`fd`上产生的事件均被保存在`revents`成员内。  
和`select`类似，`timeout`参数用来指定超时时间(ms)
```c
SYSCALL_DEFINE3(poll, struct pollfd __user *, ufds, unsigned int, nfds,
        int, timeout_msecs)
{
    struct timespec64 end_time, *to = NULL;
    int ret;

    if (timeout_msecs >= 0) {
        to = &end_time;
        poll_select_set_timeout(to, timeout_msecs / MSEC_PER_SEC,
            NSEC_PER_MSEC * (timeout_msecs % MSEC_PER_SEC));
    }

    ret = do_sys_poll(ufds, nfds, to);

    //...
}
```

首先，会调用`poll_select_set_timeout`函数将超时时间转换为`timespec64`结构变量，注意超时时间将会以当前时间(monotonic clock)为基础，转换为未来的一个超时时间点（绝对时间）

`do_sys_poll`函数首先将`pollfd`结构体数组从用户空间拷贝至内核空间，同时用名为`poll_list`的链表存储（一部分存储在栈空间上，一部分存储在堆空间），
```c
static int do_sys_poll(struct pollfd __user *ufds, unsigned int nfds,
        struct timespec64 *end_time)
{
    //...
    len = min_t(unsigned int, nfds, N_STACK_PPS);
    for (;;) {
        //...
        if (copy_from_user(walk->entries, ufds + nfds-todo,
                    sizeof(struct pollfd) * walk->len))
            goto out_fds;

        todo -= walk->len;
        if (!todo)
            break;
        //...
    }

    poll_initwait(&table);
    fdcount = do_poll(head, &table, end_time);
    poll_freewait(&table);

    for (walk = head; walk; walk = walk->next) {
        struct pollfd *fds = walk->entries;
        int j;

        for (j = 0; j < walk->len; j++, ufds++)
            if (__put_user(fds[j].revents, &ufds->revents))
                goto out_fds;
      }
    //...
}
```

#### do_poll
同样与 `select` 实现中的 `do_select` 类似，`do_poll` 函数的主要逻辑是监听多个 `fd` ，只要这些 `fd` 中有一个 `fd` 有事件发生，进程就会从休眠中被唤醒。并依次遍历所有的 `fd` 来判断到底是哪个 `fd` 有事件发生。 所以 `poll` 与 `select` 一样的效率低
```c
static int do_poll(struct poll_list *list, struct poll_wqueues *wait,
           struct timespec64 *end_time)
{
    //...
    for (;;) {
        struct poll_list *walk;

        for (walk = list; walk != NULL; walk = walk->next) {
            struct pollfd * pfd, * pfd_end;

            pfd = walk->entries;
            pfd_end = pfd + walk->len;
            for (; pfd != pfd_end; pfd++) {
                /*
                 * Fish for events. If we found one, record it
                 * and kill poll_table->_qproc, so we don't
                 * needlessly register any other waiters after
                 * this. They'll get immediately deregistered
                 * when we break out and return.
                 */
                if (do_pollfd(pfd, pt, &can_busy_loop,
                          busy_flag)) {

                    //...
                }
            }
        }
        //...
        if (!poll_schedule_timeout(wait, TASK_INTERRUPTIBLE, to, slack))
            timed_out = 1;
    }
    return count;
}
```

`poll_initwait(&table)`对`poll_wqueues`结构体变量`table`进行初始化：





## epoll


[epoll](/docs/CS/OS/Linux/IO/epoll.md) 的实现原理看起来很复杂，其实很简单，注意两个回调函数的使用：数据到达 socket 的等待队列时，通过**回调函数 ep_poll_callback** 找到 eventpoll 对象中红黑树的 epitem 节点，并将其加入就绪列队 rdllist，然后通过**回调函数 default_wake_function** 唤醒用户进程 ，并将 rdllist 传递给用户进程，让用户进程准确读取就绪的 socket 的数据。这种回调机制能够定向准确的通知程序要处理的事件，而不需要每次都循环遍历检查数据是否到达以及数据该由哪个进程处理

