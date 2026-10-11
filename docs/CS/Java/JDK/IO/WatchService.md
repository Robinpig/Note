# WatchService on Linux (inotify)

## Introduction

`java.nio.file.WatchService` 提供"注册目录、异步收到增删改事件"的能力，是 `java.io` 时代完全缺失的语义。它最常见的用途是配置热加载、目录同步、构建工具监听源码变更。

在 Linux 上，`WatchService` 的实现就是 **inotify**（`fs/notify/inotify/`）。JDK 25 的 `LinuxFileSystem.newWatchService()` 直接 `new LinuxWatchService(this)`，源码注释直白地写着"assume 2.6.13 or newer"——正是 inotify 进入主线内核的版本。本文基于 JDK 25（`jdk-25+36`）源码逐行核实这条链路，并对比无原生支持平台上的轮询回退实现。

## LinuxWatchService: inotify-backed

`LinuxWatchService extends AbstractWatchService`。构造时建立 inotify 实例，并搭好一套"后台线程 + 唤醒管道"的事件循环：

```java
// linux/classes/sun/nio/fs/LinuxWatchService.java
LinuxWatchService(UnixFileSystem fs) throws IOException {
    int ifd = -1;
    try {
        ifd = inotifyInit();                 // native → inotify_init(2)
    } catch (UnixException x) {
        String msg = (x.errno() == EMFILE) ?
            "User limit of inotify instances reached or too many open files"
            : x.errorString();
        throw new IOException(msg);
    }
    int sp[] = new int[2];
    configureBlocking(ifd, false);           // fcntl(O_NONBLOCK)
    socketpair(sp);                          // 用于关闭/请求时的唤醒
    configureBlocking(sp[0], false);
    this.poller = new Poller(fs, this, ifd, sp);
    this.poller.start();                     // 启动后台线程
}
```

三个要点：

1. **inotify 实例 fd 设为非阻塞**（`configureBlocking` → `fcntl(O_NONBLOCK)`），便于与唤醒 socket 一起 `poll`。
2. **`socketpair` 是唤醒机制**：当调用 `close()` 或发起 register/cancel 请求时，向 `sp[1]` 写一个字节，正在 `poll` 的 Poller 被唤醒去处理请求——这与上一轮 [Selector and epoll](/docs/CS/Java/JDK/IO/Selector_Epoll.md) 中 `EventFD` 唤醒 `epoll_wait` 是同一个思路，只不过 WatchService 这里用的是 `socketpair` + `poll`，不依赖 `epoll`。
3. 所有实际工作都在 **`Poller` 后台线程**里完成。

### The Poller Loop

```java
// Poller.run() 核心循环（节选）
for (;;) {
    int nReady = poll(ifd, socketpair[0]);           // 等 inotify 或唤醒

    int bytesRead = read(ifd, address, BUFFER_SIZE); // BUFFER_SIZE = 8192
    //                           ↑ Unsafe.allocateMemory 堆外缓冲

    int offset = 0;
    while (offset < bytesRead) {
        long event = address + offset;
        int wd   = unsafe.getInt(event + OFFSETOF_WD);     // 监控描述符
        int mask = unsafe.getInt(event + OFFSETOF_MASK);   // 事件掩码
        int len  = unsafe.getInt(event + OFFSETOF_LEN);    // 文件名长度
        // 文件名从 OFFSETOF_NAME 起，去掉尾部对齐用的 NUL
        ...
        processEvent(wd, mask, name);
        offset += (SIZEOF_INOTIFY_EVENT + len);
    }
    ...
}
```

- 事件缓冲区是 **`Unsafe.allocateMemory(8192)` 堆外内存**，避免每次 `read` 都新建 `byte[]`；`inotify_event` 的结构体布局（`wd`/`mask`/`len`/`name` 的偏移）由 `eventSize()` / `eventOffsets()` 两个 native 在运行时按当前平台 ABI 计算，再用 `Unsafe.getInt` / `Unsafe.getByte` 直接解码。
- `read(ifd, ..., 8192)` 一次性把内核 inotify 队列里已有的事件**批量**取回——这正是 inotify 相比"每事件一次系统调用"高效的地方。

### Mask → WatchEvent.Kind Mapping

`Poller.maskToEventKind` 把内核 `IN_*` 掩码翻译成 `StandardWatchEventKinds`：

| Java `WatchEvent.Kind` | 内核 `IN_*` 来源 |
|---|---|
| `ENTRY_CREATE` | `IN_CREATE` \| `IN_MOVED_TO` |
| `ENTRY_DELETE` | `IN_DELETE` \| `IN_MOVED_FROM` |
| `ENTRY_MODIFY` | `IN_MODIFY` \| `IN_ATTRIB` |

注意一个**事件合并**事实：`IN_MODIFY`（文件内容被写）和 `IN_ATTRIB`（元数据如权限/时间戳变化）都映射到同一个 `ENTRY_MODIFY`。所以一个文件被连续多次写入，不会在 `WatchKey.pollEvents()` 里产生等量的 `ENTRY_MODIFY`——它们被合并成"发生了修改"这一事实，调用方拿不到精确的写入次数。

溢出情况：`IN_Q_OVERFLOW` 会让 `processEvent` 向**所有**已注册的 key 广播一个 `OVERFLOW` 事件（提示"细粒度事件已丢失，请重新全量扫描目录"），而不是针对某个具体文件。

```java
// implRegister：把 Java 事件翻译成 inotify mask
int mask = 0;
for (WatchEvent.Kind<?> event : events) {
    if (event == StandardWatchEventKinds.ENTRY_CREATE)
        mask |= IN_CREATE | IN_MOVED_TO;
    else if (event == StandardWatchEventKinds.ENTRY_DELETE)
        mask |= IN_DELETE | IN_MOVED_FROM;
    else if (event == StandardWatchEventKinds.ENTRY_MODIFY)
        mask |= IN_MODIFY | IN_ATTRIB;
}
// 检查目标是目录，否则抛 NotDirectoryException
UnixFileAttributes attrs = UnixFileAttributes.get(dir, true);
if (!attrs.isDirectory()) return new NotDirectoryException(...);

int wd = inotifyAddWatch(ifd, buffer.address(), mask); // inotify_add_watch(2)
```

`inotifyAddWatch` 对应内核 `inotify_add_watch(2)`；若达到 `max_user_watches` 上限，内核返回 `ENOSPC`，JDK 转成友好的 `"User limit of inotify watches reached"` 异常。

## PollingWatchService: the Fallback

`share/classes/sun/nio/fs/PollingWatchService.java` 是**给没有原生文件变更通知能力的平台用的回退**（Linux 不走这条路径）。它完全是用户态轮询：

```java
// share/classes/sun/nio/fs/PollingWatchService.java
private static final int POLLING_INTERVAL = 2;   // 秒

PollingWatchService() {
    scheduledExecutor = Executors.newSingleThreadScheduledExecutor(
        r -> { Thread t = InnocuousThread.newThread("FileSystemWatcher", r);
               t.setDaemon(true); return t; });
}
```

机制：

- 一个**守护线程** `FileSystemWatcher`，每 `POLLING_INTERVAL = 2` 秒对注册目录执行一次 `Files.newDirectoryStream`，把当前条目与缓存（`文件名 → {lastModifiedTime, tickCount}`）比对：
  - 缓存里没有的条目 → `ENTRY_CREATE`
  - `lastModifiedTime` 变了 → `ENTRY_MODIFY`
  - 本轮缓存里有、目录里没了 → `ENTRY_DELETE`
- 延迟最高 2 秒，且每次轮询都要**完整遍历目录 + 逐个 stat**，在大目录下代价显著。
- 因为只比对 `lastModifiedTime`，所以"内容没变但被 touch"也会被当成修改，精度远不如 inotify。

对比之下，Linux 的 `LinuxWatchService` 由内核在事件发生的瞬间主动推送，几乎零轮询开销、亚毫秒延迟、且能区分 create/modify/delete 的来源动作（`IN_MOVED_FROM`/`IN_MOVED_TO`）。

## inotify Limits and Pitfalls

Java 层之上的几个坑都来自 inotify 本身的限制（对应内核 `fs/notify/inotify/`）：

- **`max_user_watches` 上限**：监控大量目录（如 node_modules）时极易触顶，表现为 `ENOSPC` → "User limit of inotify watches reached"。需调 `fs.inotify.max_user_watches`。
- **队列溢出**：内核事件队列有界，生产者（文件系统）快于消费者（`read`）时会丢事件并以 `IN_Q_OVERFLOW` 通知——JDK 已转成 `OVERFLOW`，调用方必须据此做全量重扫。
- **不递归**：`inotify_add_watch` 只监控"这一个目录"，子目录不会自动被监控。要递归监听需自行对每个子目录 `register`（这也是很多 Java 文件监听库要做的事）。
- **短生命周期文件**：文件被创建又迅速删除时，两个事件可能合并，调用方看到的只是一次 `ENTRY_CREATE` 后直接 `IN_IGNORED`（watch 自动失效）。

## Mapping to Kernel fs/notify

`LinuxWatchService` 的每一步都对应 `fs/notify/inotify/` 的内核实现：

- `inotifyInit()` → `inotify_init(2)`（`fs/notify/inotify/inotify_user.c`，创建 `inotify_instance` 与一个匿名 fd）
- `inotifyAddWatch()` → `inotify_add_watch(2)`（把 watch 挂到目标 inode 的通知链上）
- `read(ifd, ...)` → 从 instance 的事件队列里取 `inotify_event`（用户态用 `inotify_event{wd,mask,len,name}` 解码）
- `inotifyRmWatch()` → `inotify_rm_watch(2)`（卸载 watch，`IN_IGNORED` 事件回填）
- 内核产生 `IN_*` 的时机：`fsnotify` 钩子嵌在 `vfs_{unlink,rename,write,setattr,...}` 等路径里，文件操作触发时回调 inotify 组

这正是 VFS 层（[NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md) 里 `open`/`stat` 的目标）与通知子系统交汇的地方。

## Links

- [NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md)
- [IO](/docs/CS/Java/JDK/IO/IO.md)
- [NIO](/docs/CS/Java/JDK/IO/NIO.md)
- [Selector and epoll](/docs/CS/Java/JDK/IO/Selector_Epoll.md)
- [Linux inotify](/docs/CS/OS/Linux/IO/inotify.md)

## References

- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/LinuxWatchService.java`
- JDK 25 source: `src/java.base/share/classes/sun/nio/fs/PollingWatchService.java`
- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/LinuxFileSystem.java` (`newWatchService`)
- Linux man-pages: `inotify(7)`, `inotify_init(2)`, `inotify_add_watch(2)`, `inotify_rm_watch(2)`
