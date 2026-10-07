## Introduction

Unix 最响亮的设计哲学是 **"一切皆文件"**：磁盘上的普通文件是文件，目录是文件，键盘、硬盘、网卡经设备节点也表现为文件，甚至 `/proc` 里的内核状态、管道、套接字都是文件。应用程序不必为"读磁盘"和"读键盘"学两套接口——统一是 `open / read / write / close`。

但承诺"一切皆文件"是要还的：一台机器上可能同时有 ext4 磁盘、FAT 的 U 盘、NFS 网络盘、proc 内核伪文件系统，它们在磁盘上存放数据的方式完全不同，凭什么能用同一套系统调用？Linux 的答案是在系统调用与具体实现之间加一层 **VFS（Virtual File System，虚拟文件系统）**。VFS 定义一套统一的对象与契约，让所有文件系统照着实现，内核其余部分只跟 VFS 打交道。本页是 `fs/` 目录的链路总图，沿因果顺序展开：先讲 VFS 的**四大对象**，再看文件系统如何**注册**与**挂载**成一棵树，应用如何沿这棵树**查找路径**、**打开**文件，以及读写如何经 **PageCache** 落到块设备。

## VFS Four Major Objects

要让五花八门的文件系统"看起来一样"，VFS 把"一个文件系统、一个文件、一个名字、一个打开实例"抽象成四个核心结构。它们在 6.12 `include/linux/fs.h`、`dcache.h` 中定义，字段与回调全部对照源码。

**super_block——一个已挂载的文件系统实例**。它描述整个文件系统：块大小、最大文件尺寸、根目录、魔数、底层块设备，以及把操作交还给具体文件系统的 `super_operations`：

```c
struct super_block {
	struct list_head	s_list;		/* Keep this first */
	dev_t			s_dev;		/* search index; _not_ kdev_t */
	unsigned char		s_blocksize_bits;
	unsigned long		s_blocksize;
	loff_t			s_maxbytes;	/* Max file size */
	struct file_system_type	*s_type;
	const struct super_operations	*s_op;
    ...
	unsigned long		s_magic;
	struct dentry		*s_root;
    ...
	struct block_device	*s_bdev;
	struct backing_dev_info *s_bdi;
    ...
	void			*s_fs_info;	/* Filesystem private info */
    ...
};
```

`s_root` 指向该文件系统根目录的 dentry，`s_fs_info` 留给具体文件系统挂自己的私有信息，`s_bdev` 表明它建立在哪个块设备上。

**inode——一个文件本身**。inode（index node）唯一标识文件系统内的一个对象，保存的是与"文件名"无关的元数据：大小、权限、属主、时间戳、块映射、以及文件自己的操作集。注意**文件名不存在 inode 里**：

```c
struct inode {
	umode_t			i_mode;
	kuid_t			i_uid;
	kgid_t			i_gid;
	unsigned int		i_flags;
    ...
	const struct inode_operations	*i_op;
	struct super_block	*i_sb;
	struct address_space	*i_mapping;
    ...
	unsigned long		i_ino;
	union {
		const unsigned int i_nlink;
		unsigned int __i_nlink;
	};
	dev_t			i_rdev;
	loff_t			i_size;
	time64_t		i_atime_sec;
	time64_t		i_mtime_sec;
	time64_t		i_ctime_sec;
    ...
	blkcnt_t		i_blocks;
    ...
};
```

`i_op`（`inode_operations`）提供 `lookup`、`create`、`unlink`、`mkdir`、`rename`、`link`、`symlink` 等"对这个对象能做什么"的回调；`i_mapping` 指向它的 address_space，是文件内容接入 PageCache 的入口；普通文件、目录、符号链接靠 `i_mode` 的类型位区分。

**dentry——一个名字与路径的组成单元**。inode 不管名字，名字由 dentry（directory entry）承担：`/home/robin/a.txt` 被拆成 `/`、`home`、`robin`、`a.txt` 四个 dentry，串成一条父子链。它是路径查找的缓存单元：

```c
struct dentry {
	unsigned int d_flags;
	seqcount_spinlock_t d_seq;
	struct hlist_bl_node d_hash;
	struct dentry *d_parent;	/* parent directory */
	struct qstr d_name;
	struct inode *d_inode;		/* Where the name belongs to - NULL is
					 * negative */
	unsigned char d_iname[DNAME_INLINE_LEN];	/* small names */
    ...
	struct super_block *d_sb;	/* The root of the dentry tree */
	void *d_fsdata;
	struct lockref d_lockref;
    ...
	struct hlist_head d_children;	/* our children */
    ...
};
```

dentry 还区分**正 / 负**两种状态：`d_inode` 非空为正（名字对应真实文件），`d_inode` 为空是负 dentry（查过、确定不存在，用来缓存"没有此文件"）。dentry 被组织进 dcache 哈希表并按 LRU 回收，是路径查找能在内存里高速命中的关键。

**file——一个进程打开文件的实例**。前三者是内核长期对象，file 则对应"某进程某次 open 的结果"，持有读写位置、打开标志、文件操作表：

```c
struct file {
	atomic_long_t			f_count;
	fmode_t				f_mode;
	const struct file_operations	*f_op;
	struct address_space		*f_mapping;
	void				*private_data;
	struct inode			*f_inode;
	unsigned int			f_flags;
	const struct cred		*f_cred;
	struct path			f_path;
    ...
	loff_t				f_pos;
    ...
	struct file_ra_state		f_ra;
    ...
};
```

同一个磁盘文件被两个进程打开会有**两个独立 file**（各自的 `f_pos`），但它们的 `f_inode` 指向同一个 inode、`f_mapping` 指向同一棵 PageCache。这正解释了"读写偏移量各进程独立、文件数据全局共享"。

四者关系一句话：**super_block 含根 dentry，dentry 通过 `d_inode` 关联 inode，inode 经 `i_mapping` 接 PageCache，file 是 dentry + inode 被打开后的运行时实例**。

## Registering a File System

挂载之前，文件系统得先让内核"知道有我这一号"。每种文件系统定义一个 `file_system_type`（`include/linux/fs.h`），经 `register_filesystem` 挂进全局链表：

```c
struct file_system_type {
	const char *name;
	int fs_flags;
    ...
	int (*init_fs_context)(struct fs_context *);
	const struct fs_parameter_spec *parameters;
	struct dentry *(*mount) (struct file_system_type *, int,
		       const char *, void *);
	void (*kill_sb) (struct super_block *);
	struct module *owner;
	struct file_system_type * next;
	struct hlist_head fs_supers;
    ...
};
```

`name` 就是 `mount -t ext4` 里的类型名；`fs_supers` 收集该类型下所有已存在的超级块；`init_fs_context` / `mount` 负责在挂载时建立 super_block。文件系统可以内建进内核，也可像 [LKM](/docs/CS/OS/Linux/module/LKM.md) 那样作为模块按需加载。VFS 各对象的字段细节与初始化路径在 [fs](/docs/CS/OS/Linux/fs/fs.md) 中有完整源码摘录。

## Mount: Assembling a Global Directory Tree

内核里有许多独立文件系统，用户却希望它们呈现为**一棵**从 `/` 开始的目录树——`mount`（挂载）就是把某文件系统的根"接"到现有树的某个目录（挂载点）上的动作。现代挂载经 **fs_context** 完成，它把"挂载参数 + 超级块 + 根 dentry"打包，取代了老式的一次性参数传递：

```c
struct fs_context {
	const struct fs_context_operations *ops;
	struct file_system_type	*fs_type;
	void			*fs_private;
	struct dentry		*root;		/* The root and superblock */
    ...
	const char		*source;	/* The source name (eg. dev path) */
	void			*s_fs_info;
	unsigned int		sb_flags;
    ...
};
```

挂载主干是：建立 fs_context → 解析参数（源设备、挂载选项）→ 文件系统的 `get_tree` 回调读设备、建立或复用 super_block 并得到根 dentry → 生成一个 **vfsmount**（记录"这个文件系统从树的哪里挂上去"）挂入全局挂载命名空间。对基于块设备的文件系统，通用助手 `mount_bdev` 会打开块设备、回调文件系统的 `fill_super`；伪文件系统则走 `mount_nodev` / `mount_single`。挂载树、命名空间与 task_struct 里的根/工作目录（`fs_struct`）详见 [fs 的 mount 章](/docs/CS/OS/Linux/fs/fs.md?id=mount)。

> 进程的 `fs_struct` 记住它自己的根目录与当前工作目录（cwd），因此同一份挂载树在不同挂载命名空间里可以有不同视图——这正是容器文件隔离的基础，见 [namespace](/docs/CS/OS/Linux/namespace.md)。

## Path Lookup: Turning a String into a dentry

挂载给出了一棵静态的树，但应用给 VFS 的是 `/home/robin/a.txt` 这样的**字符串**。把字符串解析成最终 dentry 的工作叫**路径查找（path lookup / namei）**，实现于 `fs/namei.c`。主干是逐分量行走：

1. `path_init` 确定起点：绝对路径从进程根、相对路径从 cwd 开始；
2. `link_path_walk` 用 `/` 切分路径，对每个分量调 `walk_component`；
3. 每个分量先走**快路径 `lookup_fast`**：在 dcache 里按哈希找 dentry，命中且有效就直接用，无锁、极快；
4. dcache 未命中走**慢路径 `lookup_slow`**：调用父目录 inode 的 `i_op->lookup`，让具体文件系统（如 ext4）去自己的目录结构里查，结果回填进 dcache；
5. 遇到符号链接则解析目标、可能切换挂载点继续行走，直到最后一个分量。

这套"先查内存缓存、未命中才下探到文件系统"的两级结构，与 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) "先查缓存、未命中才读盘"是同一种思想。它也解释了为什么内核要保留负 dentry：一次 `open` 一个不存在的文件，慢路径查过一次后，短时间内重复查找能直接在缓存里返回"不存在"。

## Opening a File: open and fd

路径查到 dentry、确认其 inode 后，`open` 做的是建立**运行时实例**：分配一个 `struct file`，挂上 inode 的 `file_operations`、初始化读写偏移与打开标志、做权限与各种 flag（O_CREAT / O_TRUNC / O_APPEND）检查。随后内核在进程的 **`files_struct`**（打开文件表）里分配一个整数下标——这就是返回给用户态的 **文件描述符 fd**。

之后所有 `read(fd)` / `write(fd)` 都经 fd 在 `files_struct` 里查出 file，再调 `file->f_op`。fd 0/1/2 默认是标准输入/输出/错误，fork 后子进程继承同一张打开文件表（可共享 file 与偏移），这些进程侧结构在 [fs 的 files_struct 章](/docs/CS/OS/Linux/fs/fs.md?id=files_struct) 与 [进程管理链路](/docs/CS/OS/Linux/proc/README.md) 中展开。

## Read/Write: From file to PageCache to Block Device

拿到 file 后，数据如何流动？现代内核里普通文件读写几乎都先经过 **PageCache**，而不是直接读盘：

- **read**：先在 inode 的 address_space（`i_mapping`）里按偏移查页；命中直接拷给用户；未命中触发缺页式的读，向块层提交 bio 从盘读入并挂 readahead 预读；
- **write**：默认缓冲写，数据先写进 PageCache 标记为脏，立即返回；脏页由回写线程在稍后经文件系统的 `writepages` 转成 bio 批量下发；要同步语义可用 O_SYNC / `fsync` 等待落盘；
- **O_DIRECT** 绕过 PageCache，bio 直接引用用户页，要求对齐块设备的队列限制。

file 把"用哪种读写实现"交给 `file_operations`（`include/linux/fs.h`），现代接口主要是 `read_iter` / `write_iter`：

```c
struct file_operations {
	struct module *owner;
	ssize_t (*read) (struct file *, char __user *, size_t, loff_t *);
	ssize_t (*write) (struct file *, const char __user *, size_t, loff_t *);
	ssize_t (*read_iter) (struct kiocb *, struct iov_iter *);
	ssize_t (*write_iter) (struct kiocb *, struct iov_iter *);
    ...
	int (*iterate_shared) (struct file *, struct dir_context *);
	__poll_t (*poll) (struct file *, struct poll_table_struct *);
	int (*mmap) (struct file *, struct vm_area_struct *);
	int (*open) (struct inode *, struct file *);
	int (*fsync) (struct file *, loff_t, loff_t, int datasync);
    ...
};
```

bio 一旦提交，就离开 VFS 进入通用块层：合并、I/O 调度、blk-mq 派发到驱动——这条下行链路见 [块设备驱动](/docs/CS/OS/Linux/dev/block.md) 与 [IO](/docs/CS/OS/Linux/IO/IO.md)。内存紧张时 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 还会反向要求文件系统先回写脏页才能回收缓存，VFS 与内存子系统由此紧密咬合。

## Several Fates of a File System

`fs/` 目录下的笔记按"数据真正存在哪"分成几类：

- **磁盘文件系统**：数据持久化在块设备上。[Minix](/docs/CS/OS/Linux/fs/Minix.md) 结构最简单、是内核教学常用的文件系统；[ext4](/docs/CS/OS/Linux/fs/ext4.md) 是多数 Linux 发行版的默认磁盘文件系统；[XFS](/docs/CS/OS/Linux/fs/xfs.md) 面向大容量与大并发，用分配组并行、一切皆 B+ 树、逻辑日志三条主线支撑；[btrfs](/docs/CS/OS/Linux/fs/btrfs.md) 走另一条路——把 extent tree（哪些块在用）、chunk tree（逻辑到物理的映射）、fs tree（文件）分成三棵 B+ 树，靠写时复制换来**块级零成本快照**、多盘聚合与独立校验和，容器镜像分层常用它的子卷；
- **内核伪文件系统**：数据不在磁盘、而是内核临时生成、用来**导出内核状态**。[proc](/docs/CS/OS/Linux/fs/proc.md) 呈现进程与内核信息；[sysfs](/docs/CS/OS/Linux/fs/sysfs.md) 按设备模型把系统拓扑与属性导出到 `/sys`，与设备驱动一一对应。
- **联合文件系统**：自身不存数据，把多个目录叠成一棵树。[overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md) 用"只读 lower 层 + 唯一可写 upper 层"实现写时复制，是容器镜像分层的基础。
- **用户态文件系统**：实现跑在用户态，内核只做请求转发。[FUSE](/docs/CS/OS/Linux/fs/FUSE.md) 把每次 syscall 打包成消息送到 `/dev/fuse`，用能力位协商（批量大小、是否走 writeback 缓存）换取吞吐——SSHFS、s3fs、浏览器沙箱、容器存储驱动都建立在它之上；代价是每次 I/O 都有两次上下文切换与两次拷贝。

## File Management and Its Interaction with Other Subsystems

- **块设备**：磁盘文件系统建立在 [block](/docs/CS/OS/Linux/dev/block.md) 之上，super_block 持有 `s_bdev`，回写以 bio 为单位下发。
- **内存**：文件内容缓存于 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)，脏页回写与 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 联动。FUSE 的性能与正确性同样取决于页缓存模式（`FOPEN_DIRECT_IO` vs writeback）。
- **日志**：磁盘文件系统把崩溃一致性交给日志。[jbd2](/docs/CS/OS/Linux/fs/jbd2.md) 走**物理日志**：元数据按事务写进环形日志区，再经 checkpoint 写回原位并回收日志空间；它只认 `buffer_head` 与块号、不理解 inode 语义，因此与文件系统解耦，并自带 shrinker 参与内存回收。[XFS](/docs/CS/OS/Linux/fs/xfs.md) 不用 jbd2，走**逻辑日志**：记的是操作项而非磁盘块，由 CIL 合并后成批写入、AIL 跟踪"已记日志但未落盘"的元数据并据此推进日志尾部。[btrfs](/docs/CS/OS/Linux/fs/btrfs.md) 两条路都不走——它用 `BTRFS_TREE_LOG_OBJECTID` 这棵写前日志树，让 `fsync` 只提交该文件相关的块。
- **进程**：fd 表是 `files_struct`、cwd/根是 `fs_struct`，随 fork 继承，见 [进程链路](/docs/CS/OS/Linux/proc/README.md)。
- **设备模型**：设备节点是 VFS 与 [设备驱动](/docs/CS/OS/Linux/dev/README.md) 的接缝，sysfs 直接反映 device 拓扑。
- **内核协同全景**：一次文件读写如何串起进程调度、内存、块 I/O 与中断，见 [内核协同链路](/docs/CS/OS/Linux/Architecture.md)。

## Links

- [VFS 详解 fs](/docs/CS/OS/Linux/fs/fs.md)
- [ext4](/docs/CS/OS/Linux/fs/ext4.md)
- [btrfs](/docs/CS/OS/Linux/fs/btrfs.md)
- [Minix](/docs/CS/OS/Linux/fs/Minix.md)
- [FUSE](/docs/CS/OS/Linux/fs/FUSE.md)
- [proc](/docs/CS/OS/Linux/fs/proc.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)

## References

1. [Overview of the Linux Virtual File System — kernel.org](https://www.kernel.org/doc/html/latest/filesystems/vfs.html)
2. [Filesystems — kernel.org documentation](https://www.kernel.org/doc/html/latest/filesystems/index.html)
