## Introduction

FUSE（Filesystem in Userspace）让**文件系统实现跑在用户态**。内核只提供一个"转发请求"的通道：应用发起 `read`/`write`/ syscall，内核把它打包成消息送到 `/dev/fuse`，用户态守护进程处理完回一个响应。

它的价值在于：**文件系统不必编译进内核**。用 Python/Go/Rust 写一个文件系统只需几百行代码，崩溃了也只是用户态进程挂掉而非内核 panic。这是 Docker 存储、SSHFS、ntfs-3g、borg/restic 备份、浏览器沙箱等场景的基础设施。

代价是**每次 I/O 都要往返用户态**（两次上下文切换 + 两次拷贝），所以 FUSE 的性能关键在**批量化**（`FUSE_MAX_PAGES`）与**页缓存**。

版本基线 **v7.2**。⚠️ **v7.2 的代码组织与 API 已大改**，见文末的"v7.2 变化清单"——旧教程里的许多函数名已不存在。

## Request and Response

### Message Header

```c
struct fuse_in_header {
	u32	len;
	u32	opcode;
	u64	unique;
	u64	nodeid;
	u32	uid;
	u32	gid;
	u32	pid;
	u32	padding;
};

struct fuse_out_header {
	u32	len;
	int32	error;
	u64	unique;
};
```

`unique` 是请求的唯一标识，响应必须原样带回 —— 内核靠它匹配。这是**异步**设计的基石：用户态可以先处理请求 A 再回 A，不必按顺序。

### INIT: Capability Negotiation in the Handshake

内核与用户态在挂载时交换能力位。**这是最重要的协商点** —— 用户态声明自己支持什么，内核据此调整行为。

`include/uapi/linux/fuse.h` 的能力位表（v7.2 已去掉 `CAP_` 中缀）：

```c
#define FUSE_ASYNC_READ		(1 << 0)
#define FUSE_POSIX_LOCKS		(1 << 1)
#define FUSE_FILE_OPS		(1 << 2)
#define FUSE_ATOMIC_O_TRUNC		(1 << 3)
#define FUSE_EXPORT_SUPPORT		(1 << 4)
#define FUSE_BIG_WRITES		(1 << 5)
#define FUSE_DONT_MASK		(1 << 6)
#define FUSE_SPLICE_WRITE		(1 << 7)
#define FUSE_SPLICE_MOVE		(1 << 8)
#define FUSE_SPLICE_READ		(1 << 9)
#define FUSE_FLOCK_LOCKS		(1 << 10)
#define FUSE_HAS_IOCTL_DIR		(1 << 11)
#define FUSE_AUTO_INVAL_DATA		(1 << 12)
#define FUSE_DO_READDIRPLUS		(1 << 13)
#define FUSE_READDIRPLUS_AUTO		(1 << 14)
#define FUSE_ASYNC_DIO		(1 << 15)
#define FUSE_WRITEBACK_CACHE		(1 << 16)
#define FUSE_NO_OPEN_SUPPORT		(1 << 17)
#define FUSE_HANDLE_KILLPRIV		(1 << 19)
#define FUSE_POSIX_ACL		(1 << 20)
#define FUSE_ABORT_ERROR		(1 << 21)
#define FUSE_MAX_PAGES		(1 << 22)
#define FUSE_CACHE_SYMLINKS		(1 << 23)
#define FUSE_MAP_ALIGNMENT		(1 << 26)
#define FUSE_SUBMOUNTS		(1 << 27)
#define FUSE_HANDLE_KILLPRIV_V2		(1 << 28)
#define FUSE_SETXATTR_EXT		(1 << 29)
#define FUSE_INIT_EXT		(1 << 30)
#define FUSE_INIT_RESERVED		(1 << 31)     /* 占位，后面全在 64 位空间 */
#define FUSE_SECURITY_CTX		(1ULL << 32)
#define FUSE_HAS_INODE_DAX		(1ULL << 33)
#define FUSE_CREATE_SUPP_GROUP		(1ULL << 34)
#define FUSE_HAS_EXPIRE_ONLY		(1ULL << 35)
#define FUSE_PASSTHROUGH		(1ULL << 37)
#define FUSE_NO_EXPORT_SUPPORT		(1ULL << 38)
#define FUSE_HAS_RESEND		(1ULL << 39)
#define FUSE_DIRECT_IO_RELAX		FUSE_DIRECT_IO_ALLOW_MMAP
#define FUSE_ALLOW_IDMAP		(1ULL << 40)
#define FUSE_OVER_IO_URING		(1ULL << 41)
#define FUSE_REQUEST_TIMEOUT		(1ULL << 42)
```

> ⚠️ **命名全变了**：旧资料里的 `FUSE_CAP_ASYNC_READ` / `FUSE_CAP_POSIX_LOCKS` / `FUSE_CAP_BIG_WRITES` 等（带 `CAP_` 中缀）在 v7.2 **全部不存在**。**语义也翻转了** —— 旧的 `fc->want` 表达"内核期望什么"，现在改为"服务端单向声明自己支持什么"。

**`FUSE_INIT_RESERVED` 占掉 bit 31** 是个 notable 的历史包袱：早期能力位设计没预留扩展空间，只能占一个位当"以后别用这儿的标志"。

几个值得单独理解的能力位：

| 能力 | 作用 | 权衡 |
| :-- | :-- | :-- |
| `FUSE_ASYNC_READ` | 读请求可乱序返回 | 并行度↑，用户态需自己排序 |
| `FUSE_BIG_WRITES` | 一次写超过 4 KiB | **必须开**，否则写性能灾难 |
| `FUSE_MAX_PAGES` | 一次请求可带多个页 | 减少往返，**性能关键** |
| `FUSE_WRITEBACK_CACHE` | 内核用 writeback 而非 write-through | **写性能↑↑，崩溃时丢数据** |
| `FUSE_ATOMIC_O_TRUNC` | 支持 O_TRUNC 原子性 | 避免"截断可见但数据未写"窗口 |
| `FUSE_AUTO_INVAL_DATA` | 自动失效页缓存 | 正确性vs性能 |
| `FUSE_SPLICE_READ/WRITE/MOVE` | splice 支持 | 与零拷贝配合 |
| `FUSE_FLOCK_LOCKS` | 独立处理 flock | 避免与 POSIX 锁冲突 |
| `FUSE_NO_OPEN_SUPPORT` | **open 时不请求用户态** | 减少往返（配合 `kernel_cache`） |
| `FUSE_OVER_IO_URING` | 走 io_uring 后端 | v7.x 新增，减少中断 |
| `FUSE_REQUEST_TIMEOUT` | 内核侧请求超时 | 防止用户态永久挂起 |

`FUSE_DIRECT_IO_RELAX` 是个别名：

```c
#define FUSE_DIRECT_IO_RELAX		FUSE_DIRECT_IO_ALLOW_MMAP
```

**它就是允许 mmap** —— 旧版 `FOPEN_DIRECT_IO` 打开的文件不能共享 mmap，这个能力位放宽了该限制（uapi 注释里 "allow shared mmap in FOPEN_DIRECT_IO mode"）。

### FOPEN: The Switch Returned on open

```c
#define FOPEN_DIRECT_IO		(1 << 0)   /* bypass page cache for this open file */
#define FOPEN_KEEP_CACHE		(1 << 1)   /* don't invalidate the data cache on open */
```

`FOPEN_DIRECT_IO` **让这个 fd 绕过页缓存**。注意 v7.2 里 **`fc->direct_io` 字段已不存在** —— DIRECT_IO 现在完全由 `fuse_file` 的 `open_flags` 承载，即**每个 fd 独立决定**（同一文件可以一个 fd 直写、一个 fd 走缓存）。

## nodeid and inode Lifecycle

FUSE 里 inode 由**两套标识**：

- **内核分配的 `nodeid`**（u64）—— 内核侧唯一标识，inode 结构体索引；
- **用户态返回的 inode 号**（st_ino）—— 同一 inode 内的文件唯一标识。

关系是"多对一"：同一 nodeid 可以有多个用户态 inode 号（硬链接）。反过来，**用户态 inode 号唯一但 nodeid 可共享**。

### nlookup Count

```c
struct fuse_inode {
	...
	u64 nodeid;
	/** @nlookup: Number of lookups on this inode */
	u64 nlookup;
	...
};
```

**`nlookup` 是 FUSE 最反直觉的机制**：每次内核查路径（lookup）就 +1，内核**每释放一次 dentry 就 -1**。归零时内核发 `FORGET` 告诉用户态"这个 inode 没人用了，你可以释放"。

用户态收到 `FORGET` 后**必须释放**对应 inode 的所有资源。**漏掉 `FORGET` → 内存泄漏；过早释放 → dangling inode**。这是写 FUSE 文件系统最容易出错的地方。

内核实现在 inode 有效性：

```c
static inline u64 fuse_inode_to_nodeid(struct inode *inode) { return get_fuse_inode(inode)->nodeid; }
```

`nlookup > 0` 是它"有效"的判据。

## File Operation Path

```
应用 read(fd)
  → VFS 查页缓存
    命中 → 直接返回
    未命中 → fuse_file_read_iter()
      → 组装 fuse_read_in
      → 送 /dev/fuse
      → 阻塞在 wait queue
用户态读到消息 → 打开真实文件 → read → 回 fuse_read_out
  → 内核唤醒等待者
  → copy_to_user / 页缓存填充
```

关键点：**内核在等待期间可以挂起进程**（异步 I/O），所以 FUSE 支持真正的 AIO。这条路径的实现分散在 `file.c`（读写）、`dir.c`（目录）、`control.c`（控制）、`xattr.c`、`ioctl.c`、`readdir.c`、`poll.c`、`notify.c`。

## Page Cache and writeback

**这是 FUSE 性能与正确性的核心权衡。**

| 模式 | 行为 | 优点 | 缺点 |
| :-- | :-- | :-- | :-- |
| 直写（默认） | 每次写同步送用户态 | 崩溃不丢数据 | 每个 4 KiB 一次往返，慢 |
| **writeback cache** | 写先进页缓存，异步刷回 | **吞吐高** | **进程/机器崩溃丢未刷数据** |

`FUSE_WRITEBACK_CACHE` 开启后，内核把 FUSE 文件当本地文件一样缓存并延迟写回。**注意 fsync 语义**：开启后 fsync 仍要等用户态确认，所以"崩溃丢数据"的窗口是"未 fsync 的部分"。

`FUSE_MAX_PAGES` 决定了单次请求的最大页数，**是减少往返次数最直接的开关**。用户态没开这个位时，每次写只传 4 KiB —— 顺序写 1 GB 就是 26 万次往返，性能不可接受。

## Mount Options

> ⚠️ **v7.2 用标准 `fs_parameter` API**（`fsparam_*`），**旧的 `FUSE_OPT` 宏已彻底移除**，`fs/fuse/options.c` **文件也不存在**（逻辑并入 `inode.c`）。`fuse_mount_opts` 结构改名为 **`struct fuse_fs_context`**。

选项表在 `fs/fuse/inode.c:777-786`：

```c
	fsparam_string	("source",		OPT_SOURCE),
	fsparam_fd	("fd",			OPT_FD),
	fsparam_u32oct	("rootmode",		OPT_ROOTMODE),
	fsparam_uid	("user_id",		OPT_USER_ID),
	fsparam_gid	("group_id",		OPT_GROUP_ID),
	fsparam_flag	("default_permissions",	OPT_DEFAULT_PERMISSIONS),
	fsparam_flag	("allow_other",		OPT_ALLOW_OTHER),
	fsparam_u32	("max_read",		OPT_MAX_READ),
	fsparam_u32	("blksize",		OPT_BLKSIZE),
	fsparam_string	("subtype",		OPT_SUBTYPE),
```

| 选项 | 类型 | 说明 |
| :-- | :-- | :-- |
| `fd` | fd | 用已打开的 fd 而非重新打开 source |
| `user_id` / `group_id` | uid/gid | **挂载为指定用户**（容器场景常用） |
| `rootmode` | 八进制 | 根目录权限 |
| `allow_other` | flag | **允许其他用户访问该挂载** |
| `default_permissions` | flag | 内核做权限检查 |
| `max_read` | u32 | 单次读的最大字节 |
| `blksize` | u32 | 块大小 |
| `subtype` | string | 子类型名（`s3fs`/`sshfs` 等） |
| `source` | string | 源（低层挂载用） |

`allow_other` 值得注意：**默认挂载只有挂载者可访问**。要给别人用必须开这个，且 `/etc/fuse.conf` 里要有 `user_allow_other`（`user_allow_other` 是 libfuse 层的检查）。

`user_id` / `group_id` 有**额外校验**（v7.2 新增的 idmapping 支持）：uid/gid 必须在挂载的 idmapping 中可表示，否则挂载失败。这是为了配合 user namespace 做的正确性检查。

## CUSE: Character Device in Userspace

CUSE（Character device in Userspace）把 FUSE 的机制用于**字符设备**而非文件系统 —— 用户态收到的是 ioctl/read/write 请求，返回的是"数据"而不是"缓冲区"。

```c
obj-$(CONFIG_CUSE) += cuse.o
```

适合虚拟串口、虚拟网卡、加密转换层等场景。

> ⚠️ **v7.2 的 CUSE 已重写**：`CUSE_IOC_*` ioctl、`cuse_lowlevel_setup()`、`cuse_send_ioctl()` 等旧 API **全部不存在**。`virtiofs`（`CONFIG_VIRTIO_FS`）是另一条更现代的路径 —— 通过 virtio 传输而不是 FUSE 协议。

## v7.2 Change List

写 FUSE 代码前必读。以下是 v7.2 相对旧资料的差异：

| 旧（不存在） | v7.2 | 备注 |
| :-- | :-- | :-- |
| `fs/fuse/fuse.h` | `fuse_i.h` / `dev.h` | 头文件拆分 |
| `fs/fuse/options.c` | 并入 `inode.c` | 文件消失 |
| `FUSE_OPT()` | `fsparam_*()` | 标准 fs_context API |
| `fuse_mount_opts` | `struct fuse_fs_context` | 类型改名 |
| `FUSE_CAP_*` | `FUSE_*` | 去 `CAP_` 中缀，语义翻转（服务端声明） |
| `fc->want` | （无） | 字段删除 |
| `struct fuse_iov_iter` | （无） | 类型删除 |
| `fc->direct_io` | `ff->open_flags` | 改为 per-fd |
| `struct fuse_file` 的 `write_buf`/`read_buf`/`page_cache` | （无） | 字段精简 |
| `fuse_request_queue()` / `fuse_send_reply*()` / `fuse_reply_*()` | 预分配 buffer + 置 `FR_SENT` | reply 机制重写 |
| `fuse_interrupt*()` / `fuse_reverse_inodes()` / `fuse_iget_dirty()` | （无） | 函数删除 |
| `fuse_file_put(ff)` | `fuse_file_put(ff, bool sync)` | **签名变了** |
| `FUSE_MIN_READ_BUFFER` = 128 KiB | **8192** | 值不同 |
| `cuse_lowlevel_setup()` / `CUSE_IOC_*` / `cuse_send_*` | 重写 | CUSE API 变 |
| `fuse_entry_out` 的 `inlookup` 位 | （无） | 字段删除 |
| uapi 的 `fuse_llseek_*` / `fuse_fiemap_*` / `fuse_statfs_in` / `fuse_read_buf_*` / `fuse_write_buf_*` | （无） | 协议结构删除 |

**新增的能力位**：`FUSE_SUBMOUNTS`（子挂载）、`FUSE_PASSTHROUGH`（透传模式）、`FUSE_OVER_IO_URING`（io_uring 后端）、`FUSE_REQUEST_TIMEOUT`、`FUSE_ALLOW_IDMAP`、`FUSE_HAS_RESEND`。

`CONFIG_FUSE_PASSTHROUGH` 让 `struct fuse_file` 多出两个字段：

```c
#ifdef CONFIG_FUSE_PASSTHROUGH
	/** @passthrough: Reference to backing file in passthrough mode */
	struct file *passthrough;
	/** @cred: passthrough file credentials */
	const struct cred *cred;
#endif
```

**透传模式下 FUSE 直接持有真实文件的 `struct file`** —— 读操作不经用户态往返，接近本地性能。这解释了为什么 passthrough 值得为它加整个 `backing.c` 模块。

另外还有 `CONFIG_FUSE_DAX`（`dax.o`）与 `CONFIG_FUSE_IO_URING`（`dev_uring.o`）两个可选特性。

## Interfaces with Other Subsystems

- **VFS**：FUSE 实现了 file_operations 与 address_space_operations，所有路径都经它，见 [fs/fs.md](/docs/CS/OS/Linux/fs/fs.md)。
- **页缓存**：`FUSE_DIRECT_IO` / writeback 模式直接决定页缓存行为，与 [mm/PageCache.md](/docs/CS/OS/Linux/mm/PageCache.md) 相关。
- **零拷贝**：`FUSE_SPLICE_*` 让 `splice`/`sendfile` 能穿透 FUSE，见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)。
- **io_uring**：`FUSE_OVER_IO_URING` 走 io_uring 后端，见 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。
- **设备模型**：`/dev/fuse` 是字符设备，`/sys/fs/fuse/connections/` 暴露连接信息，见 [dev/char.md](/docs/CS/OS/Linux/dev/char.md)。
- **user namespace**：`FUSE_ALLOW_IDMAP` 与 `user_id=`/`group_id=` 的 idmapping 校验，见 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **容器**：Docker 的存储驱动、FUSE-overlayfs 都基于 FUSE。

## Troubleshooting Quick Reference

```shell
# 连接信息
ls /sys/fs/fuse/connections/                    # 每个挂载一个
cat /sys/fs/fuse/connections/<id>/waiting        # 是否有等待中的请求
ls -l /dev/fuse

# 挂载参数与能力
mount | grep fuse
cat /sys/fs/fuse/connections/<id>/max_background
cat /sys/fs/fuse/connections/<id>/max_readahead
cat /sys/fs/fuse/connections/<id>/waiting

# 内核侧 trace（最有效的排查手段）
mount -t debugfs none /sys/kernel/debug
echo 1 > /sys/kernel/debug/tracing/events/fuse/fuse_request/enable
cat /sys/kernel/debug/tracing/trace_pipe

# abort：让内核放弃所有等待中的请求（用户态挂死时的救急）
echo 1 > /sys/fs/fuse/connections/<id>/abort

# 性能：看是否有大量往返
perf stat -e 'syscalls:sys_enter_read' -a sleep 10
# fuse 统计在 /sys/fs/fuse/connections/<id>/ 下

# 用户态调试：libfuse 的 -d 与 strace
fusermount3 -d -o allow_other,debug /mnt/point 2>&1 | head -50
```

## Links

- [fs 知识地图](/docs/CS/OS/Linux/fs/README.md)
- [fs/fs（VFS 机制）](/docs/CS/OS/Linux/fs/fs.md)
- [mm/PageCache](/docs/CS/OS/Linux/mm/PageCache.md)
- [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [dev/char（字符设备）](/docs/CS/OS/Linux/dev/char.md)

## References

1. [Linux Kernel Documentation — FUSE](https://docs.kernel.org/filesystems/fuse.html)
2. [libfuse documentation](https://libfuse.readthedocs.io/en/latest/)
3. [include/uapi/linux/fuse.h](https://elixir.bootlin.com/linux/latest/source/include/uapi/linux/fuse.h)
