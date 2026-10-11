## Introduction

`inotify` 是 Linux 2.6.13 引入的文件系统事件通知子系统，让用户态以 `read(2)` 从 fd 拉取"某目录/文件发生了什么"的结构化事件。它是 `WatchService` 在 Linux 上的**真实后端**——JDK 25 的 `LinuxWatchService` 正是 `inotify_init1` + `inotify_add_watch` + 一个 `Poller` 线程 `read` 事件队列（见 [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)）。

内核侧 inotify 本身不是一个独立子系统，而是 **fsnotify 框架**的一个"后端"：`inotify_user.c` 顶部注释明确写着 "inotify was largely rewritten to make use of the fsnotify infrastructure"（inotify_user.c:13）。理解 inotify 必须同时看两层：
- **用户态接口层** `fs/notify/inotify/inotify_user.c`：syscall、watch 生命周期、事件队列与交付。
- **事件注入层** `fs/notify/inotify/inotify_fsnotify.c`：把 VFS 各处的 fsnotify 钩子翻译成 inotify 事件并入队（含合并逻辑）。

## Syscall Surface

四个系统调用都在 `inotify_user.c`：

| 系统调用 | 位置 | 作用 |
|---|---|---|
| `inotify_init1(flags)` | inotify_user.c:707 | 建一个 `fsnotify_group` + 返回匿名 fd；`IN_CLOEXEC`/`IN_NONBLOCK` 在此设 |
| `inotify_init` | inotify_user.c:712 | `inotify_init1(0)` 的薄包装 |
| `inotify_add_watch(fd, path, mask)` | inotify_user.c:717 | 在目标 inode 上挂一个 `inotify_inode_mark`，返回 wd |
| `inotify_rm_watch(fd, wd)` | inotify_user.c:774 | 摘掉 mark，触发 `IN_IGNORED` |

`inotify_new_group`(641) 调 `fsnotify_alloc_group(&inotify_fsnotify_ops, ...)`(646) 拿到 group；每个 watch 由 `inotify_new_watch`(577) 分配一个 `inotify_inode_mark` 内核对象（`kmem_cache_alloc(inotify_inode_mark_cachep)` 606），再 `fsnotify_add_inode_mark_locked`(607) 把它挂到目标 inode 的 `fsnotify_mark_connector` 上。

```c
// fs/notify/inotify/inotify_user.c
SYSCALL_DEFINE3(inotify_add_watch, int, fd, const char __user *, pathname,
                u32, arg)
{
    struct fsnotify_group *group;
    struct inode *inode;
    struct path path;
    // ... 解析 pathname 得到 inode ...
    ret = inotify_new_watch(group, inode, inotify_arg_to_flags(arg));
    // 返回 wd（idr 分配的整型句柄）
}
```

## fsnotify Framework

inotify 的"事件来自哪里"完全依赖 VFS 在关键路径上埋的 fsnotify 钩子（如 `fsnotify_create` / `fsnotify_unlink` / `fsnotify_modify`，散落在 `fs/namei.c`、`fs/open.c`、`mm/filemap.c` 等处）。当 VFS 完成一个会触发通知的操作时，它回调当前已挂在 inode 上的所有 mark 的 `handle_event`。

inotify 后端注册的回调在 `inotify_fsnotify.c`：

- `inotify_handle_event(...)`：把 fsnotify 事件（`FS_MODIFY` / `FS_ATTRIB` / `FS_CREATE` / `FS_DELETE` / `FS_MOVE` …）翻译成 inotify 的 `IN_*` 语义，构造 `inotify_event_info`，再 `fsnotify_add_event(group, fsn_event, inotify_merge)`(126)。
- inotify 事件 mask 与 fsnotify mask 是 1:1 对齐的，源码用 `BUILD_BUG_ON` 强约束：`BUILD_BUG_ON(IN_MODIFY != FS_MODIFY)`(inotify_user.c:820)、`BUILD_BUG_ON(IN_Q_OVERFLOW != FS_Q_OVERFLOW)`(832)——任何偏移都会编译失败。

`inotify_inode_mark` 是关键数据结构（inotify_user.c:41），它内嵌 `struct fsnotify_mark fsn_mark`，把"用户视角的 wd"与"内核视角的 inode 关注点"绑在一起；`wd` 由 group 私有的 `idr` 分配，是用户态识别事件的唯一 key。

## Event Queue and Delivery

group 持有一条**内核侧事件队列**（`notification_list` + `notification_lock`）。`inotify_handle_event` 把事件入队后，用户态通过 `read(ifd, buf, count)` 取走——内核侧由 `copy_event_to_user`(inotify_user.c:199) 把 `inotify_event_info` 拷到用户 buffer，这正是 JDK `LinuxWatchService` 里 `read(ifd, addr, 8192)`（`Unsafe` 堆外 8 KB）所消费的数据布局（`struct inotify_event { wd, mask, cookie, len, name[] }`）。

`inotify_poll`(139) 在队列非空时返回 `EPOLLIN | EPOLLRDNORM`——这正是 JDK 那个后台 `Poller` 线程 `poll(ifd, sp[0])` 等待的可读信号来源。换句话说，**inotify 事件的"异步"完全建立在"fd 可读"上，与 epoll 同构**；若 JDK 用 `Selector` 监听这个 inotify fd，走的也是同一套 epoll 机制（见 [epoll](/docs/CS/OS/Linux/IO/epoll.md)）。

## Event Coalescing

inotify 的"事件合并"语义由 `inotify_merge`(inotify_fsnotify.c:49) 实现：`fsnotify_add_event` 入队前会问 merge 回调——如果队首已有一个**相同 wd + 相同 mask** 且尚未被用户读走的事件，就合并（丢弃新事件，只保留老的），而不是追加。

这就是"连续多次 `write` 触发多个 `IN_MODIFY`，但用户 `read` 只看到一次"的根因，也对应 JDK 侧观察到的现象：`StandardWatchEventKinds.ENTRY_MODIFY` 会被合并报告，高频小写不会一对一地刷爆事件流。注意合并以 **(wd, mask)** 为粒度，不同 mask（如 `IN_MODIFY` vs `IN_ATTRIB`）不会被合到一起。

## Overflow

每个 group 有事件队列上限（`max_queued_events`，默认 16384，由 `fs.inotify.max_queued_events` 调）。队列溢出时内核调用 `inotify_q_overflow`（inotify_user.c:135），它入队一个 `mask = FS_Q_OVERFLOW` 的事件（oevent->mask = FS_Q_OVERFLOW，658），用户读到的就是 `IN_Q_OVERFLOW`。

JDK 侧把这个事件翻译为 `StandardWatchEventKinds.OVERFLOW`——此时应用**不能**假设丢失了哪些具体事件，必须做"全量重扫"（如重新 `walk` 目录）。这也解释了为什么 JDK `WatchService` 的 `Overflow` 需要被特殊对待，而不能当普通条目处理。

## JDK Mapping

inotify 的 `IN_*` 到 JDK `StandardWatchEventKinds` 的映射（由 `LinuxWatchService` 解码，注意**合并语义**）：

| inotify mask（内核） | JDK `WatchEvent.Kind` | 说明 |
|---|---|---|
| `IN_MODIFY` \| `IN_ATTRIB` | `ENTRY_MODIFY` | 二者都映射到"修改"，且会被 coalesce |
| `IN_CREATE` | `ENTRY_CREATE` | 新建文件/子目录 |
| `IN_DELETE` | `ENTRY_DELETE` | 删除文件/子目录 |
| `IN_MOVED_FROM` | `ENTRY_DELETE` | 移出（配合 cookie 可识别同源移动） |
| `IN_MOVED_TO` | `ENTRY_CREATE` | 移入 |
| `IN_IGNORED` | key 失效 | watch 被 rm 或底层 inode 销毁 |
| `IN_Q_OVERFLOW` | `OVERFLOW` | 队列溢出，需全量重扫 |
| `IN_ISDIR` | — | 修饰位，标记事件目标是目录 |

**限制**（写 Java 程序时务必知晓）：`fs.inotify.max_user_watches` 限制单用户可挂 watch 总数（默认通常 8192，容器里常被调小）；watch **不递归**——要监视整棵目录树必须自己对每个子目录 `register`；inotify 只报告"发生了什么"，不保证顺序与完整性（溢出即丢）。

## Links

- [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [File System (VFS)](/docs/CS/OS/Linux/fs/fs.md)
- [aio (libaio)](/docs/CS/OS/Linux/IO/aio.md)

## References

- Linux 7.2.7 source: `fs/notify/inotify/inotify_user.c`
- Linux 7.2.7 source: `fs/notify/inotify/inotify_fsnotify.c`
- Linux man-pages: `inotify(7)`, `inotify_init(2)`, `inotify_add_watch(2)`
