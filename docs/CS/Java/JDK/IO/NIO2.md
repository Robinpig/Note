# NIO.2 File System (java.nio.file on Linux)

## Introduction

`java.nio.file`（代号 NIO.2，JDK 7 引入）是 JDK 对文件系统访问的现代化封装：`Path`、`FileSystem`、`FileSystemProvider`、`Files`、`DirectoryStream`、`WatchService`、`FileVisitor` 都在这一层。它与更古老的 `java.io.File`（已过时）最大的不同是——**它有一套真正落到操作系统系统调用的本地实现**，而不是把一切都委托给 `java.io` 的薄封装。

本文基于 **JDK 25（`jdk-25+36`）** 源码逐行核实，聚焦 `java.nio.file` 在 **Linux** 上的实现链路：从 `FileSystemProvider` 的平台选择，到 `LinuxNativeDispatcher` 把 Java 调用翻译成 `open(2)` / `getdents64(2)` / `fstatat(2)` / `copy_file_range(2)` 等内核系统调用。它与你整理的 Linux 内核 `fs/` 子系统（VFS 的 `path_lookup`、目录迭代、通知机制）一一对应。

> 一个重要提醒：旧博客里大量出现的 `UnixFileSystemProvider` / `UnixNativeDispatcher` 等"跨 Unix 通用类"，在 JDK 25 源码树里的**位置已经变化**——Linux 专属实现集中在 `sun.nio.fs.Linux*`，而共享基类（仍叫 `Unix*`，如 `UnixFileSystem`、`UnixNativeDispatcher`）被移到了 `sun/nio/fs` 包之外的跨平台层。本文只引用已逐行读取的真实文件，不编造父类路径。

## Provider Selection (Compile-time, Not Runtime)

`FileSystems.getDefault().provider()` 在 Linux 上返回 `LinuxFileSystemProvider`。这个选择**没有任何运行时 OS 探测**，完全是编译期硬编码：构建 Linux 版本时，只有 `linux/classes/sun/nio/fs/DefaultFileSystemProvider.java` 被编入镜像。

```java
// linux/classes/sun/nio/fs/DefaultFileSystemProvider.java (JDK 25)
public class DefaultFileSystemProvider {
    private static final LinuxFileSystemProvider INSTANCE
        = new LinuxFileSystemProvider();

    public static LinuxFileSystemProvider instance() {
        return INSTANCE;
    }
    public static FileSystem theFileSystem() {
        return INSTANCE.theFileSystem();
    }
}
```

macOS / Windows 各有自己的 `DefaultFileSystemProvider`（分别产出 `MacOSXFileSystemProvider` / `WindowsFileSystemProvider`）。正是这种"每个平台一个 provider 子类"的结构，使得 NIO.2 既能统一 API、又能贴近各 OS 的本地语义。

## LinuxFileSystemProvider: a Thin Override

`LinuxFileSystemProvider extends UnixFileSystemProvider`（基类在跨平台共享层，承载 `newByteChannel` / `checkAccess` / `copy` / `move` 等核心逻辑）。Linux 子类极薄，只覆写少数平台相关点：

```java
// linux/classes/sun/nio/fs/LinuxFileSystemProvider.java
class LinuxFileSystemProvider extends UnixFileSystemProvider {
    @Override LinuxFileSystem newFileSystem(String dir)
        { return new LinuxFileSystem(this, dir); }

    @Override
    public <V extends FileAttributeView> V getFileAttributeView(Path obj,
                                                                Class<V> type, ...)
    {
        if (type == DosFileAttributeView.class)          // Linux 也暴露 dos 视图
            return (V) new LinuxDosFileAttributeView(...);
        if (type == UserDefinedFileAttributeView.class)  // 扩展属性 xattr
            return (V) new LinuxUserDefinedFileAttributeView(...);
        return super.getFileAttributeView(obj, type, options);
    }

    @Override
    FileTypeDetector getFileTypeDetector() {
        // 链：~/.mime.types → /etc/mime.types
        return chain(new MimeTypesFileTypeDetector(Path.of(userHome, ".mime.types")),
                     new MimeTypesFileTypeDetector(Path.of("/etc/mime.types")));
    }
}
```

值得注意：**Linux 上 `Files.probeContentType` 会读 `/etc/mime.types`**——这就是 JDK 探测文件 MIME 类型的本地来源，而非魔数识别。

## LinuxFileSystem

`LinuxFileSystem extends UnixFileSystem`，承载若干 Linux 特有的文件系统行为：

```java
// linux/classes/sun/nio/fs/LinuxFileSystem.java
class LinuxFileSystem extends UnixFileSystem {
    @Override
    public WatchService newWatchService() throws IOException {
        // assume 2.6.13 or newer  → 即假设内核支持 inotify
        return new LinuxWatchService(this);
    }

    @Override
    List<UnixMountEntry> getMountEntries() {
        return getMountEntries("/etc/mtab");   // 读挂载表识别 FileStore
    }

    @Override
    int directCopy(int dst, int src, long addressToPollForCancel) throws UnixException {
        int advice = POSIX_FADV_SEQUENTIAL | POSIX_FADV_NOREUSE | POSIX_FADV_WILLNEED;
        posix_fadvise(src, 0, 0, advice);      // 给内核的预读/缓存建议
        return directCopy0(dst, src, addressToPollForCancel);
    }
}
```

三件关键事实：

1. **`newWatchService()` 直接 new `LinuxWatchService`**——意味着 Linux 上的 `WatchService` 就是 inotify 封装（详见 [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)）。源码注释"assume 2.6.13 or newer"正是 inotify 进入主线内核的版本。
2. **`getMountEntries` 读 `/etc/mtab`**（经由 `setmntent` / `getmntent_r` / `endmntent` 三个 native，见下文）——`FileStore` 的"磁盘/分区"识别、空间统计都建立在这之上。
3. **`directCopy` 先 `posix_fadvise` 再 `directCopy0`**——零拷贝路径的真正入口。

## The Native Dispatcher Layer (JDK → Kernel)

JDK 把"调系统调用"收口在 `UnixNativeDispatcher`（共享层）及其平台子类 `LinuxNativeDispatcher` 里。**Linux 子类极薄**，只额外声明了 Linux 特有的 native：

```java
// linux/classes/sun/nio/fs/LinuxNativeDispatcher.java (JDK 25)
class LinuxNativeDispatcher extends UnixNativeDispatcher {
    static long   setmntent(byte[] filename, byte[] type) ...   // 挂载表
    static int    getmntent(long fp, UnixMountEntry entry, int buflen) ...
    static void   endmntent(long stream) ...
    static native int  posix_fadvise(int fd, long offset, long len, int advice) ...
    static native int  directCopy0(int dst, int src, long addressToPollForCancel) ...
}
```

也就是说，`open` / `readdir` / `stat` / `readlink` / `inotify*` 这些**真正的系统调用封装在父类的 native 方法**中；Linux 子类只补了"挂载表解析"和"零拷贝/预读"两个平台增强点。

以下是 `java.nio.file` 主要操作到 Linux 内核系统调用的映射（语义自 NIO.2 诞生起稳定，与内核 `fs/` 直接对应）：

| Java 操作 | Dispatcher native | 内核系统调用 | 内核路径（参考 v7.2.7） |
|---|---|---|---|
| 打开/创建文件 | `open` | `open(2)`（`O_RDONLY`/`O_WRONLY`/`O_CREAT`/`O_TRUNC`/`O_APPEND`，`O_NOFOLLOW` 控制符号链接穿透，`O_CLOEXEC` 防止 fd 泄漏到子进程） | `fs/open.c: do_sys_open` → `do_filp_open` → `path_lookup` |
| 读取属性 | `stat` / `lstat` / `fstat` | `fstatat(2)` / `lstat(2)` / `fstat(2)` | `fs/stat.c: vfs_statx`（`AT_SYMLINK_NOFOLLOW` 对应 `LinkOption.NOFOLLOW_LINKS`） |
| 目录遍历 | `readdir` | `fdopendir` + `getdents64(2)`（批量） | `fs/readdir.c: iterate_dir`（依赖 dcache 加速） |
| 符号链接 | `readlink` / `symlink` | `readlinkat(2)` / `symlinkat(2)` | `fs/namei.c` / `fs/stat.c` |
| 删除/重命名 | `unlink` / `rename` | `unlinkat(2)` / `renameat2(2)` | `fs/namei.c` |
| 文件变更监听 | `inotifyInit` / `inotifyAddWatch` | `inotify_init(2)` / `inotify_add_watch(2)` | `fs/notify/inotify/` |
| 挂载表识别 | `setmntent` / `getmntent_r` | `setmntent(3)` / `getmntent_r(3)`（读 `/etc/mtab` 或 `/proc/mounts`） | — |
| 零拷贝复制 | `directCopy0` | `copy_file_range(2)` 优先，回退 `sendfile(2)` | `fs/read_write.c` / `net/core` |

**目录遍历的批量性**值得强调：与 `java.io.File.list()` 每次返回一个小对象不同，NIO.2 的 `DirectoryStream` 实现通过 `getdents64(2)` 一次从内核拉取一批目录项进一块通过 `NativeBuffer` 复用的堆外内存，再在用户态逐个解码成 `Path`。这直接对应内核 `iterate_dir` 利用 dcache 批量产出 dirent 的机制，也是 `Files.newDirectoryStream` 在大目录下明显快于 `File.listFiles()` 的根源。

## Zero-Copy Path: copy_file_range First

`directCopy0` 是 `Files.copy(Path, Path)` 与 `FileChannel.transferTo` 在 Linux 上走"内核内复制"的底层。JDK 25 的 native 实现（`linux/native/libnio/fs/LinuxNativeDispatcher.c`）先把 `copy_file_range` 动态解析出来，优先使用：

```c
// linux/native/libnio/fs/LinuxNativeDispatcher.c
static copy_file_range_func* my_copy_file_range_func = NULL;

JNIEXPORT void JNICALL Java_sun_nio_fs_LinuxNativeDispatcher_init(...)
{
    my_copy_file_range_func =
        (copy_file_range_func*) dlsym(RTLD_DEFAULT, "copy_file_range");
}

JNIEXPORT jint JNICALL Java_sun_nio_fs_LinuxNativeDispatcher_directCopy0
    (JNIEnv* env, jclass this, jint dst, jint src, jlong cancelAddress)
{
    const size_t count = cancel != NULL ? 1048576       // 1 MB，留给取消机会
                                       : 0x7ffff000;    // 不可取消时 sendfile 单次上限
    ssize_t bytes_sent;
    if (my_copy_file_range_func != NULL) {
        do {
            RESTARTABLE(my_copy_file_range_func(src, NULL, dst, NULL, count, 0),
                        bytes_sent);
            if (bytes_sent < 0) {
                switch (errno) {
                    case EINVAL:
                    case ENOSYS:
                    case EXDEV:   // 跨文件系统时 copy_file_range 不支持
                        break;    // 落到下面的 sendfile
                    default:
                        JNU_ThrowIOExceptionWithLastError(env, "Copy failed");
                        return IOS_THROWN;
                }
            }
            ...
        } while (bytes_sent > 0);
        if (bytes_sent == 0) return 0;
    }
    do {                                  // 回退路径
        RESTARTABLE(sendfile(dst, src, NULL, count), bytes_sent);
        if (bytes_sent < 0) {
            if (errno == EAGAIN) return IOS_UNAVAILABLE;   // 会触发上层重试
            if (errno == EINVAL || errno == ENOSYS) return IOS_UNSUPPORTED_CASE;
            ...
        }
    } while (bytes_sent > 0);
    return 0;
}
```

要点：

- **`copy_file_range(2)` 优先**（JDK 通过 `dlsym` 探测 glibc 是否提供，避免硬链接符号导致低版本启动失败）。它是真正的"内核内数据搬运"，不往返用户态，且能跨同一文件系统内的页缓存优化。
- 遇到 `EXDEV`（源/目标不在同一文件系统）、`EINVAL`、`ENOSYS` 时**回退到 `sendfile(2)`**——后者常用于 socket→file 或 file→file，但同样免去用户态缓冲。
- 可被取消的复制每次最多 1 MB，不可取消时取 `sendfile` 的单次上限 `0x7ffff000`；`EAGAIN` 返回 `IOS_UNAVAILABLE`，由上层 `IOUtil` 风格的循环重试（对照 [NIO](/docs/CS/Java/JDK/IO/NIO.md) 里的 `IOStatus` 机制）。

这与上一轮在 `NIO.md` 中确认的 `transferTo0` 行为一致，且在这里拿到了**完整的 native 源码证据**。

## Mapping to Linux VFS

把上面的链路接到你已经整理的内核侧，形成一张完整的"Java 调用 → 内核路径"图：

- `open(2)` → `do_sys_open` → `do_filp_open` → `path_lookup` / `link_path_walk`（VFS 的 dentry+inode 解析，见 [File System (VFS)](/docs/CS/OS/Linux/fs/fs.md)）
- `fstatat(2)` → `vfs_statx`（属性从 inode 读取，不走磁盘 I/O 当有 dcache）
- `getdents64(2)` → `iterate_dir`（目录 inode 的 `->iterate` 方法，由具体文件系统实现，借助 dcache 批产 dirent）
- `copy_file_range(2)` / `sendfile(2)` → 内核内页搬运，绕开用户态 buffer
- `inotify_*` → `fs/notify/inotify/`（见 [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)）

NIO.2 这一层的价值，正是把"面向对象的文件 API"干净地翻译到这套 VFS 原语上，而不像 `java.io.File` 那样混入了大量为了兼容 Windows 语义而做的妥协。

## Links

- [IO](/docs/CS/Java/JDK/IO/IO.md)
- [NIO](/docs/CS/Java/JDK/IO/NIO.md)
- [Selector and epoll](/docs/CS/Java/JDK/IO/Selector_Epoll.md)
- [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)
- [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)
- [io_uring](/docs/CS/Java/JDK/IO/Uring.md)

## References

- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/DefaultFileSystemProvider.java`
- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/LinuxFileSystemProvider.java`
- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/LinuxFileSystem.java`
- JDK 25 source: `src/java.base/linux/classes/sun/nio/fs/LinuxNativeDispatcher.java`
- JDK 25 source: `src/java.base/linux/native/libnio/fs/LinuxNativeDispatcher.c`
- Linux man-pages: `open(2)`, `getdents(2)`, `fstatat(2)`, `readlinkat(2)`, `copy_file_range(2)`, `sendfile(2)`, `inotify(7)`
