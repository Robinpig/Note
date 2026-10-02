## Introduction

ext4（fourth extended filesystem）是 Linux 上使用最广泛的**磁盘文件系统**之一，ext3 的后继者，由 Ted Ts'o 等人开发，自 Linux 2.6.19（2006）起逐步合入、2.6.28 稳定。它在 ext2/ext3 的整体设计（块组 + inode 位图）上向后兼容演进，重点解决了 ext3 的三个痛点：**大文件/大分区寻址、碎片与分配效率、崩溃恢复性能**。

需要区分两个层面：[fs.md](/docs/CS/OS/Linux/fs/fs.md) 讲的是与具体磁盘格式无关的 **VFS 抽象层**（inode、dentry、file、vfsmount、lookup），ext4 则是 VFS 之下的一个具体 `super_operations`/`inode_operations`/`address_space_operations` 实现，负责把逻辑 inode/目录映射到磁盘块，并通过日志保证元数据一致性。

读 ext4 源码前还要建立一个关键意识：**磁盘上的结构与内存里的结构是两套**。磁盘结构（`ext4_super_block`、`ext4_inode`、`ext4_group_desc`）字段全部是 little-endian（`__le32` 等），只在读写块设备时出现；内存结构（`ext4_sb_info`、`ext4_inode_info`）才是内核运行时操作的对象。两套结构经专用助手互转：

```c
static inline struct ext4_sb_info *EXT4_SB(struct super_block *sb);

static inline struct ext4_inode_info *EXT4_I(struct inode *inode)
{
	return container_of(inode, struct ext4_inode_info, vfs_inode);
}
```

## Disk Layout

ext4 把块设备划分为**块组（block group）**，每组自带描述信息，以局部化相关数据、减少寻道：

```
Boot block | Group 0            | Group 1            | ... | Group n
           | Superblock(copy)   |                    |
           | GDT (group desc)   |                    |
           | block bitmap       | block bitmap       |
           | inode bitmap       | inode bitmap       |
           | inode table        | inode table        |
           | data blocks        | data blocks        |
```

**Superblock** 的磁盘形态是 `struct ext4_super_block`（`fs/ext4/ext4.h`），字段带字节偏移注释，全部 little-endian：

```c
struct ext4_super_block {
/*00*/	__le32	s_inodes_count;		/* Inodes count */
	__le32	s_blocks_count_lo;	/* Blocks count */
	__le32	s_r_blocks_count_lo;	/* Reserved blocks count */
	__le32	s_free_blocks_count_lo;	/* Free blocks count */
/*10*/	__le32	s_free_inodes_count;	/* Free inodes count */
	__le32	s_first_data_block;	/* First Data Block */
	__le32	s_log_block_size;	/* Block size */
	__le32	s_log_cluster_size;	/* Allocation cluster size */
/*20*/	__le32	s_blocks_per_group;	/* # Blocks per group */
	__le32	s_clusters_per_group;	/* # Clusters per group */
	__le32	s_inodes_per_group;	/* # Inodes per group */
	__le32	s_mtime;		/* Mount time */
/*30*/	__le32	s_wtime;		/* Write time */
	__le16	s_mnt_count;		/* Mount count */
	__le16	s_max_mnt_count;	/* Maximal mount count */
	__le16	s_magic;		/* Magic signature */
	__le16	s_state;		/* File system state */
	__le16	s_errors;		/* Behaviour when detecting errors */
	__le16	s_minor_rev_level;
    ...
	__le32	s_feature_compat;	/* compatible feature set */
/*60*/	__le32	s_feature_incompat;	/* incompatible feature set */
	__le32	s_feature_ro_compat;	/* readonly-compatible feature set */
    ...
	__le16  s_inode_size;		/* size of inode structure */
    ...
};
```

块大小不是直接存储、而是由 `s_log_block_size` 经 `1024 << s_log_block_size` 得到；`s_magic` 的固定值是 `0xEF53`（与 ext2/ext3 相同，因此可向后兼容挂载）。三套特性位（`s_feature_compat` / `s_feature_incompat` / `s_feature_ro_compat`）决定内核能否挂载——incompat 里出现内核不认识的位会直接拒绝挂载。

**GDT（Group Descriptor Table）** 每一项是 `struct ext4_group_desc`，同时保留 lo/hi 两半以兼容旧格式并支持 64bit：

```c
struct ext4_group_desc
{
	__le32	bg_block_bitmap_lo;	/* Blocks bitmap block */
	__le32	bg_inode_bitmap_lo;	/* Inodes bitmap block */
	__le32	bg_inode_table_lo;	/* Inodes table block */
	__le16	bg_free_blocks_count_lo;/* Free blocks count */
	__le16	bg_free_inodes_count_lo;/* Free inodes count */
	__le16	bg_used_dirs_count_lo;	/* Directories count */
	__le16	bg_flags;		/* EXT4_BG_flags (INODE_UNINIT, etc) */
	__le32  bg_exclude_bitmap_lo;   /* Exclude bitmap for snapshots */
	__le16  bg_block_bitmap_csum_lo;
	__le16  bg_inode_bitmap_csum_lo;
	__le16  bg_itable_unused_lo;	/* Unused inodes count */
	__le16  bg_checksum;		/* crc16(sb_uuid+group+desc) */
	__le32	bg_block_bitmap_hi;
	__le32	bg_inode_bitmap_hi;
	__le32	bg_inode_table_hi;
    ...
};
```

- **block / inode bitmap**：各占一个块，标记组内数据块/inode 的占用情况。
- **inode table**：连续存放定长磁盘 inode，结构为 `struct ext4_inode`（`fs/ext4/ext4.h`），默认 256B、大小由超级块 `s_inode_size` 决定：

```c
struct ext4_inode {
	__le16	i_mode;		/* File mode */
	__le16	i_uid;		/* Low 16 bits of Owner Uid */
	__le32	i_size_lo;	/* Size in bytes */
	__le32	i_atime;	/* Access time */
	__le32	i_ctime;	/* Inode Change time */
	__le32	i_mtime;	/* Modification time */
	__le32	i_dtime;	/* Deletion Time */
	__le16	i_gid;		/* Low 16 bits of Group Id */
	__le16	i_links_count;	/* Links count */
	__le32	i_blocks_lo;	/* Blocks count */
	__le32	i_flags;	/* File flags */
    ...
	__le32	i_block[EXT4_N_BLOCKS];/* Pointers to blocks */
	__le32	i_generation;	/* File version (for NFS) */
	__le32	i_file_acl_lo;	/* File ACL */
	__le32	i_size_high;
    ...
	__le16	i_extra_isize;
	__le16	i_checksum_hi;
	__le32  i_ctime_extra;  /* extra Change time      (nsec << 2 | epoch) */
	__le32  i_mtime_extra;  /* extra Modification time(nsec << 2 | epoch) */
	__le32  i_atime_extra;  /* extra Access time      (nsec << 2 | epoch) */
	__le32  i_crtime;       /* File Creation time */
	__le32  i_crtime_extra;
	__le32	i_version_hi;
	__le32	i_projid;	/* Project ID */
};
```

注意 `i_block[15]`（`EXT4_N_BLOCKS`）这个 60 字节字段——它在 ext2/ext3 里是间接块指针，在 ext4 里复用为 extent 树根。后面带 `_extra` 后缀的字段存纳秒与创建时间，只有当 inode 大于基础的 128B（`i_extra_isize`）时才存在，这正是老格式能向后兼容、又能扩展新属性的机制。
- **data blocks**：文件数据与目录项所在块。

灵活块组（flex_bg，`flex_bg` 特性）把多个块组的位图和 inode 表合并到一起，给大文件和日志腾出连续的大块空闲区。

## Extents

ext3 用**间接块映射**（直接/一级/二级/三级间接指针）记录文件逻辑块到物理块的映射，大文件元数据多、随机寻址深。ext4 改用 **extent 树**，磁盘结构定义在 `fs/ext4/ext4_extents.h`。

一个 extent 表示一段**连续的物理块**，真实 on-disk 结构只有 12 字节：

```c
struct ext4_extent {
	__le32	ee_block;	/* first logical block extent covers */
	__le16	ee_len;		/* number of blocks covered by extent */
	__le16	ee_start_hi;	/* high 16 bits of physical block */
	__le32	ee_start_lo;	/* low 32 bits of physical block */
};
```

物理块地址由 `ee_start_hi`（16 位）与 `ee_start_lo`（32 位）拼成 **48 位**，单文件和卷容量远超 ext3。更深的树用索引节点（index）指向下一层：

```c
struct ext4_extent_idx {
	__le32	ei_block;	/* index covers logical blocks from 'block' */
	__le32	ei_leaf_lo;	/* pointer to the physical block of the next *
				 * level. leaf or next index could be there */
	__le16	ei_leaf_hi;	/* high 16 bits of physical block */
	__u16	ei_unused;
};
```

无论是 inode 内嵌的根、还是索引块/叶块，开头都有一个 extent header：

```c
struct ext4_extent_header {
	__le16	eh_magic;	/* probably will support different formats */
	__le16	eh_entries;	/* number of valid entries */
	__le16	eh_max;		/* capacity of store in entries */
	__le16	eh_depth;	/* has tree real underlying blocks? */
	__le32	eh_generation;	/* generation of the tree */
};

#define EXT4_EXT_MAGIC		cpu_to_le16(0xf30a)
#define EXT4_MAX_EXTENT_DEPTH 5
```

综合起来的结构是一棵 B+ 树：

- inode 的 `i_block[15]` 放 extent 树根（header + 若干 extent/index），`eh_depth=0` 表示全是叶、`eh_magic` 必须是 `0xf30a`；
- 小文件的所有 extent 直接内联在 inode 里，**无需额外读任何索引块**；
- 装不下时把 extent 下沉到独立的叶块，inode 根改放 index（`eh_depth` 增加，最大深度 5），靠 `ei_block` 在逻辑块区间上做范围查找。

连续分配时一个 extent 可覆盖上万块（`ee_len` 的高位还用来标记 uninitialized extent 支持预分配），把 ext3"每块一个映射指针"降为"每段一个映射"。

## Block Allocation

为降低碎片、提高连续性，ext4 引入多块分配器（mballoc）与延迟分配：

- **多块分配（mballoc）**：一次分配调用可分配任意数量连续块，而不是像 ext3 每次一块；分配器借助 per-CPU prefetch 空间与 buddy 风格的空闲区间结构选择最佳区段。
- **延迟分配（delalloc，delayed allocation）**：写页时先只在内存标记脏、保留逻辑块（`buffer_delay`），把物理块分配推迟到回写（writeback）前。这样分配器能一次看到一个文件的全部脏页，分配出更连续的区段；但也放大了"写时已返回、掉盘才分配"窗口内的崩溃/ENOSPC 语义差异。
- **持久预分配**：`fallocate(2)` 通过标记 uninitialized extent 预留连续空间而不写零，对应 `posix_fallocate`。
- **stripe-aware 分配**：感知 RAID 条带宽度，避免 read-modify-write。

## Journal (jbd2)

ext4 复用并扩展 ext3 的日志层 **JBD2**（journaling block device, v2）：提交前先把元数据变更写入日志，崩溃后通过 **replay** 重做日志中已提交事务，保证元数据结构一致（但不保证未 fsync 的用户数据本身不丢）。三种挂载模式：

| 模式 | 记录内容 | 一致性 | 性能 |
| --- | --- | --- | --- |
| `data=journal` | 元数据 + 数据都先进日志 | 最强 | 最慢（数据写两遍） |
| `data=ordered`（默认） | 只记元数据，但保证相关数据块在元数据提交前落盘 | 避免元数据指向垃圾数据 | 中等 |
| `data=writeback` | 只记元数据，数据顺序不保证 | 崩溃后可能读到旧块内容 | 最快 |

事务以 handle 为单位，关键阶段是 write→commit：先把描述符与元数据写入日志并 flush，再写 commit 块；只有看到完整 commit 块的事务才会在恢复时 replay。现代特性：

- **Fast Commit**（5.10，`fast_commit`）：轻量的"增量重做"日志，记录 append、长度更新等操作的重做信息，减少 fsync 时完整事务的开销；
- **journal checksum / async commit / async discard**：日志校验、并行提交，以及配合 SSD TRIM 的异步丢弃，降低尾延迟。

这里只讲 ext4 侧的模式与特性；日志层自身的机制——`journal_t` 的三态事务与环形指针、handle 的额度记账、commit 的六个阶段与状态迁移、checkpoint 如何回收日志空间、崩溃恢复的 SCAN/REVOKE/REPLAY 三趟扫描，以及 revoke 为什么要阻止重放旧记录——单独成篇见 [jbd2](/docs/CS/OS/Linux/fs/jbd2.md)。

## Directories

目录在 ext4 里也是一种文件（inode 的类型位为目录），其数据块里存放的是变长的目录项。磁盘结构 `ext4_dir_entry_2`（`fs/ext4/ext4.h`）：

```c
struct ext4_dir_entry_2 {
	__le32	inode;			/* Inode number */
	__le16	rec_len;		/* Directory entry length */
	__u8	name_len;		/* Name length */
	__u8	file_type;		/* See file type macros EXT4_FT_* below */
	char	name[EXT4_NAME_LEN];	/* File name */
};
```

几个设计要点：

- `rec_len` 记录**整条记录的长度**而不是固定值——目录项按名字变长排列，删除一项时把它的 `rec_len` 并进前一项，因此目录只增长、不立即缩小；
- `file_type` 直接存类型（普通/目录/符号链接），查找时不必先读目标 inode 就能判断类型；
- 小目录项存在目录文件的数据块里，大目录启用 `dir_index` 后改用 **HTree**（哈希 B 树）：用文件名的哈希值把目录项分散到一棵带索引的树，解决大目录线性扫描的问题。

## Key Features

- `extents`：extent 块映射；`huge_file` / 48-bit 寻址；`64bit`：大卷支持。
- `dir_index`：目录用 HTree（哈希 B 树）索引，解决大目录线性查找。
- `uninit_bg` / `flex_bg`：未初始化块组、灵活块组，加速 e2fsck 并改善大文件连续性。
- `metadata_csum` / `gdt_csum`：元数据校验和，配合 e2fsck 快速发现损坏。
- `encrypt`（fscrypt）：目录级内容加密；`verity`：只读文件完整性校验。
- `bigalloc`：更大 cluster；`inline_data`：小文件数据直接放进 inode。
- 持久预分配、纳秒时间戳（`extra_isize` 支持创建/保存时间）、`noload` 无日志挂载等。

## Write Path

一次缓冲写的大致路径（体现 VFS 与 ext4 的分工）：

1. `write(2)` 经 VFS `vfs_write` 进入 ext4 的 `ext4_file_write_iter`；
2. 经 generic 层写 page cache，delalloc 只标记脏、保留逻辑映射，暂不分配物理块；
3. 回写由 writeback 内核线程触发：`ext4_writepages` → mballoc 一次性分配连续物理块 → 生成 extent 并纳入 JBD2 事务；
4. JBD2 在 commit 时按 ordered 模式先 flush 数据块、再写元数据日志并提交；
5. checkpoint 后日志空间回收，元数据最终写回其在文件系统中的固定位置。

与块设备交互、bio 合并/调度以及 `fsync` 强制落盘语义关联到 [IO 栈](/docs/CS/OS/Linux/IO/IO.md)；高性能异步提交另见 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。

## ext4 vs ext3 / XFS / Btrfs

与 [XFS](/docs/CS/OS/Linux/fs/xfs.md) 的更细对照见该笔记末尾：两者最本质的差别在日志——ext4 用 jbd2 记物理块，XFS 记逻辑操作项并靠 CIL 合并、AIL 推进日志尾部。

| 维度 | ext3 | ext4 | XFS | Btrfs |
| --- | --- | --- | --- | --- |
| 块映射 | 间接块 | extent 树（48-bit） | extent + B+ 树 | B 树 + 引用计数 |
| 分配 | 逐块 | mballoc + delayed alloc | 成熟 delayed/extent | CoW 分配 |
| 校验 | 无 | 元数据 checksum | 元数据 | 元数据 + 数据 CRC |
| 快照 | 无 | 无 | 无（外部） | 原生写时快照/子卷 |
| 伸缩 | 固定 | 可扩不可缩 | 在线扩容 | 在线扩缩 |
| 定位 | 老旧稳定 | 通用、稳定、生态最广 | 大文件/高吞吐 | 数据完整性与高级特性 |

## Links

- [fs (VFS)](/docs/CS/OS/Linux/fs/fs.md)
- [proc](/docs/CS/OS/Linux/fs/proc.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)
- [Minix](/docs/CS/OS/Linux/fs/Minix.md)
- [IO Stack](/docs/CS/OS/Linux/IO/IO.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)

## References

1. [Kernel Documentation: ext4 General Information](https://docs.kernel.org/filesystems/ext4/overview.html)
2. [Kernel Documentation: ext4 Disk Layout](https://docs.kernel.org/filesystems/ext4/globals.html)
3. [ext4 — Linux Kernel wiki](https://ext4.wiki.kernel.org/)
4. [Design and Implementation of the Fourth Extended File System (Mathur et al., OLS 2007)](https://www.kernel.org/doc/ols/2007/ols2007v2-pages-21-34.pdf)
