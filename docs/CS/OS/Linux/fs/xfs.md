## Introduction

**XFS** 是 1993 年由 SGI 为 IRIX 设计、2001 年并入 Linux 的 64 位日志型文件系统。它的设计目标与 ext4 不同：ext4 是从 ext2/ext3 演进来的"通用盘"，XFS 从第一天起就面向**大容量、大文件、高并发**——单文件 EB 级、文件系统 EB 级、分配路径天然可并行。

它靠三条主线支撑这个目标：

1. **分配组（allocation group, AG）**：整盘切成若干自包含的 AG，每个 AG 有自己的空闲空间树与 inode 树，不同 AG 的分配可以并行进行，锁竞争被摊薄到 AG 粒度；
2. **一切皆 B+ 树**：文件 extent、空闲空间、inode 索引、反向映射、引用计数、目录与扩展属性，全部是 B+ 树，共用一套通用游标与遍历代码，只在叶子记录类型上分化；
3. **逻辑日志（delayed logging）**：日志里记的不是"被改动的磁盘块"，而是"发生了什么修改"（log item），配合 CIL 合并与 AIL 跟踪，让元数据更新的日志写入量大幅下降。

本文按磁盘布局 → 内存结构 → 树家族 → 日志与事务 → 目录 → 分配 → 完整性 → 新特性的顺序展开，源码对照 Linux v7.2.7（`fs/xfs/`，353 个文件）。与 ext4 的逐项对照放在最后，阅读时可以跳到 [ext4 / XFS 对照](#ext4-与-xfs-的对照)先建立坐标。

## Disk Layout

XFS 的盘面由三部分组成：**日志**（可以在本盘的某个 AG 内，也可以是独立的外部设备）、**若干分配组**、可选的 **realtime 子卷**（独立设备，给需要稳定带宽的场景用）。

每个 AG 的开头是四个"死位置"的元数据扇区，然后是数据区：

| 位置 | 宏 | 内容 |
| --- | --- | --- |
| AG 第 0 扇区 | — | 超级块副本（每个 AG 都有一份，主本在 AG 0） |
| AG 第 1 扇区 | `XFS_AGF_DADDR` | **AGF**：空闲空间管理 |
| AG 第 2 扇区 | `XFS_AGI_DADDR` | **AGI**：inode 管理 |
| AG 第 3 扇区 | `XFS_AGFL_DADDR` | **AGFL**：空闲链表（AGFL：AG free list） |

AGF 里挂着本 AG 的三棵 B+ 树根，以及空闲块总数与最大连续长度：

```c
typedef struct xfs_agf {
	/*
	 * Common allocation group header information
	 */
	__be32		agf_magicnum;	/* magic number == XFS_AGF_MAGIC */
	__be32		agf_versionnum;	/* header version == XFS_AGF_VERSION */
	__be32		agf_seqno;	/* sequence # starting from 0 */
	__be32		agf_length;	/* size in blocks of a.g. */
	/*
	 * Freespace and rmap information
	 */
	__be32		agf_bno_root;	/* bnobt root block */
	__be32		agf_cnt_root;	/* cntbt root block */
	__be32		agf_rmap_root;	/* rmapbt root block */

	__be32		agf_bno_level;	/* bnobt btree levels */
	__be32		agf_cnt_level;	/* cntbt btree levels */
	__be32		agf_rmap_level;	/* rmapbt btree levels */

	__be32		agf_flfirst;	/* first freelist block's index */
	__be32		agf_fllast;	/* last freelist block's index */
	__be32		agf_flcount;	/* count of blocks in freelist */
	__be32		agf_freeblks;	/* total free blocks */

	__be32		agf_longest;	/* longest free space */
	__be32		agf_btreeblks;	/* # of blocks held in AGF btrees */
	uuid_t		agf_uuid;	/* uuid of filesystem */

	__be32		agf_rmap_blocks;	/* rmapbt blocks used */
	__be32		agf_refcount_blocks;	/* refcountbt blocks used */

	__be32		agf_refcount_root;	/* refcount tree root block */
	__be32		agf_refcount_level;	/* refcount btree levels */
	...
	/* unlogged fields, written during buffer writeback. */
	__be64		agf_lsn;	/* last write sequence */
	__be32		agf_crc;	/* crc of agf sector */
```

注意末尾那句注释——`agf_lsn` 与 `agf_crc` 属于**不记日志的字段**，在 buffer 写回时才填。这是 XFS v5 的自我描述元数据（self-describing metadata）设计的一部分：LSN 用于判断日志里的内容是否比盘上的新，CRC 用于校验，两者都不能进日志（否则自己校验自己）。

AGI 管 inode，除了 inobt 根之外还有一个**空 inode 树 finobt** 的根，以及 unlinked 链表：

```c
typedef struct xfs_agi {
	__be32		agi_magicnum;	/* magic number == XFS_AGI_MAGIC */
	__be32		agi_versionnum;	/* header version == XFS_AGI_VERSION */
	__be32		agi_seqno;	/* sequence # starting from 0 */
	__be32		agi_length;	/* size in blocks of a.g. */
	/*
	 * Inode information
	 * Inodes are mapped by interpreting the inode number, so no
	 * mapping data is needed here.
	 */
	__be32		agi_count;	/* count of allocated inodes */
	__be32		agi_root;	/* root of inode btree */
	__be32		agi_level;	/* levels in inode btree */
	__be32		agi_freecount;	/* number of free inodes */

	__be32		agi_newino;	/* new inode just allocated */
	__be32		agi_dirino;	/* last directory inode chunk */
	/*
	 * Hash table of inodes which have been unlinked but are
	 * still being referenced.
	 */
	__be32		agi_unlinked[XFS_AGI_UNLINKED_BUCKETS];
	...
	__be32		agi_free_root; /* root of the free inode btree */
	__be32		agi_free_level;/* levels in free inode btree */

	__be32		agi_iblocks;	/* inobt blocks used */
	__be32		agi_fblocks;	/* finobt blocks used */
} xfs_agi_t;
```

那句 "Inodes are mapped by interpreting the inode number, so no mapping data is needed here" 是 XFS 与 ext4 的一处根本差异：**inode 号本身编码了位置**（`agno` + AG 内块号 + 块内偏移），所以不存在 ext4 那种"块组里固定位置的 inode 表"。定位 inode 不需要查表，只要按位拆分 inode 号：

```
ino = (agno << (sb_agblklog + sb_inopblog)) | (agbno << sb_inopblog) | offset
```

代价是 inode 不能任意放——它必须落在某个 inode chunk（默认 64 个 inode 一组）里；inobt 记录的是"哪些 chunk 里有空闲 inode"，而不是 inode 本身的位置。

`agi_unlinked[64]` 是 XFS 处理"文件被 unlink 但仍被打开"的方式：这类 inode 挂进 AGI 的 64 个哈希桶之一，崩溃恢复时 `xlog_recover_process_iunlinks()` 扫这些桶把残留 inode 真正删掉。ext4 用 orphan 链表做同一件事。

超级块里与布局相关的关键字段（v7.2.7）：

| 字段 | 含义 |
| --- | --- |
| `sb_agblocks` / `sb_agcount` | 每个 AG 的块数（最后一个 AG 可能短）与 AG 数量 |
| `sb_blocklog` / `sb_inodelog` / `sb_inopblog` | 块大小、inode 大小、每块 inode 数的 log2，用于上面的位拆分 |
| `sb_logstart` / `sb_logblocks` | 内部日志的起始块与长度；外部日志时 `sb_logstart` 为 0 |
| `sb_rootino` | 根目录 inode 号 |
| `sb_features_compat` / `ro_compat` / `incompat` / `log_incompat` | 四级特性位 |
| `sb_metadirino` | 元数据目录树的根（v7 新增，见后文 metadir） |
| `sb_rgcount` / `sb_rgextents` | realtime group 数量与每个 rt group 的 extent 数（zoned 支持引入） |

## AG in Memory: xfs_perag

每个 AG 在内存里有对应的 `struct xfs_perag`，缓存 AGF/AGI 的易变摘要，避免每次都读盘：

```c
struct xfs_perag {
	struct xfs_group	pag_group;
	unsigned long		pag_opstate;
	uint8_t		pagf_bno_level;	/* # of levels in bno btree */
	uint8_t		pagf_cnt_level;	/* # of levels in cnt btree */
	uint8_t		pagf_rmap_level;/* # of levels in rmap btree */
	uint32_t	pagf_flcount;	/* count of blocks in freelist */
	xfs_extlen_t	pagf_freeblks;	/* total free blocks */
	xfs_extlen_t	pagf_longest;	/* longest free space */
	uint32_t	pagf_btreeblks;	/* # of blocks held in AGF btrees */
	xfs_agino_t	pagi_freecount;	/* number of free inodes */
	xfs_agino_t	pagi_count;	/* number of allocated inodes */

	/*
	 * Inode allocation search lookup optimisation.
	 * If the pagino matches, the search for new inodes
	 * doesn't need to search the near ones again straight away
	 */
	xfs_agino_t	pagl_pagino;
	xfs_agino_t	pagl_leftrec;
	xfs_agino_t	pagl_rightrec;

	uint8_t		pagf_refcount_level; /* recount btree height */

	/* Blocks reserved for all kinds of metadata. */
	struct xfs_ag_resv	pag_meta_resv;
	/* Blocks reserved for the reverse mapping btree. */
	struct xfs_ag_resv	pag_rmapbt_resv;
	...
	spinlock_t	pag_ici_lock;	/* incore inode cache lock */
	struct radix_tree_root pag_ici_root;	/* incore inode cache root */
	int		pag_ici_reclaimable;	/* reclaimable inodes */
	...
	/* background prealloc block trimming */
	struct delayed_work	pag_blockgc_work;
};
```

几个值得注意的点：

- `pagf_freeblks` / `pagf_longest` 是分配的**快速判据**——要分配 N 个连续块时先扫 perag 看有没有 AG 的 `longest >= N`，不必真的走 B+ 树；
- `pag_ici_root` 是**按 AG 划分的 inode cache**（基数树），配合 `pag_ici_reclaimable` 做inode 回收，同样把全局锁拆成 per-AG 锁；
- `pag_meta_resv` / `pag_rmapbt_resv` 是 **per-AG 预留池**：rmapbt 与 refcountbt 自己也要占块，若不预留会出现"想记录一个分配却没有空间记录"的死锁；
- `pag_blockgc_work` 负责**回收投机预分配**（speculative preallocation）的块——XFS 写文件时会多预分配一段，文件关闭或空间紧张时由这个后台工作收回。

v7.2.7 里 `xfs_perag` 的第一个成员变成了 `struct xfs_group pag_group`：内核把 AG 与 realtime group 抽象成统一的 `xfs_group`（`XG_TYPE_AG` / `XG_TYPE_RTG`），引用计数与遍历（grab/rele/next_range）都用同一套 `xfs_group_*()` 实现，perag 只是它的容器（`to_perag()` / `pag_group()` 互相转换）。这是为 rt group 与 zoned 设备做准备的重构。

对应的通用抽象在 [fs.md](/docs/CS/OS/Linux/fs/fs.md) 讲的 VFS 四对象之下，是 XFS 自己的一层；`struct xfs_mount` 持有全局状态（superblock 副本、`m_ail`、`m_log`、各 btree 的 maxlevels、`m_features`）。

## Inode

磁盘上的 inode 是一块可变大小的区域（默认 512 字节，mkfs 可选 256–2048），由 **core + data fork + attr fork** 三段组成，attr fork 的起点由 `di_forkoff << 3` 决定：

```c
/*
 * On-disk inode structure.
 *
 * This is just the header or "dinode core", the inode is expanded to fill a
 * variable size the leftover area split into a data and an attribute fork.
 * The format of the data and attribute fork depends on the format of the
 * inode as indicated by di_format and di_aformat. ...
 */
struct xfs_dinode {
	__be16		di_magic;	/* inode magic # = XFS_DINODE_MAGIC */
	__be16		di_mode;	/* mode and type of file */
	__u8		di_version;	/* inode version */
	__u8		di_format;	/* format of di_c data */
	__be16		di_metatype;	/* XFS_METAFILE_*; was di_onlink */
	...
	__be64		di_size;	/* number of bytes in file */
	__be64		di_nblocks;	/* # of direct & btree blocks used */
	...
	__u8		di_forkoff;	/* attr fork offs, <<3 for 64b align */
	__s8		di_aformat;	/* format of attr fork's data */
	...
	/* start of the extended dinode, writable fields */
	__le32		di_crc;		/* CRC of the inode */
	__be64		di_changecount;	/* number of attribute changes */
	__be64		di_lsn;		/* flush sequence */
	__be64		di_flags2;	/* more random flags */
	...
	/* fields only written to during inode creation */
	xfs_timestamp_t	di_crtime;	/* time created */
	__be64		di_ino;		/* inode number */
	uuid_t		di_uuid;	/* UUID of the filesystem */
};
```

fork 有五种格式：

```c
enum xfs_dinode_fmt {
	XFS_DINODE_FMT_DEV,		/* xfs_dev_t */
	XFS_DINODE_FMT_LOCAL,		/* bulk data */
	XFS_DINODE_FMT_EXTENTS,		/* struct xfs_bmbt_rec */
	XFS_DINODE_FMT_BTREE,		/* struct xfs_bmdr_block */
	XFS_DINODE_FMT_UUID,		/* added long ago, but never used */
	XFS_DINODE_FMT_META_BTREE,	/* metadata btree */
};
```

映射成日常语义：小目录、短符号链接、小扩展属性用 **LOCAL**（内容直接嵌在 inode 里）；普通文件用 **EXTENTS**（fork 里是 extent 记录数组）；extent 多到 inode 装不下就升级为 **BTREE**（fork 里是 bmbt 的根块）；`XFS_DINODE_FMT_META_BTREE` 是 v7 给 metadir 新增的形态（fork 里放的是元数据 B+ 树的根，用于 rt rmapbt 之类的元数据文件）。

内存里的 `xfs_inode` 把 fork 统一成三份，并额外保存 reflink 需要的 CoW fork：

```c
typedef struct xfs_inode {
	...
	/* Extent information. */
	struct xfs_ifork	*i_cowfp;	/* copy on write extents */
	struct xfs_ifork	i_df;		/* data fork */
	struct xfs_ifork	i_af;		/* attribute fork */

	/* Transaction and locking information. */
	struct xfs_inode_log_item *i_itemp;	/* logging information */
	struct rw_semaphore	i_lock;		/* inode lock */
	atomic_t		i_pincount;	/* inode pin count */
	struct llist_node	i_gclist;	/* deferred inactivation list */
	...
	uint64_t		i_delayed_blks;	/* count of delay alloc blks */
	xfs_fsize_t		i_disk_size;	/* number of bytes in file */
	...
	enum xfs_metafile_type	i_metatype;	/* XFS_METAFILE_* */
	...
	struct inode		i_vnode;	/* embedded VFS inode */
} xfs_inode_t;
```

`struct xfs_ifork` 本身：

```c
struct xfs_ifork {
	int64_t			if_bytes;	/* bytes in if_data */
	struct xfs_btree_block	*if_broot;	/* file's incore btree root */
	unsigned int		if_seq;		/* fork mod counter */
	int			if_height;	/* height of the extent tree */
	void			*if_data;	/* extent tree root or inline data */
	xfs_extnum_t		if_nextents;	/* # of extents in this fork */
	short			if_broot_bytes;	/* bytes allocated for root */
	int8_t			if_format;	/* format of this fork */
	uint8_t			if_needextents;	/* extents have not been read */
};
```

**关键设计**：不管磁盘上是 EXTENTS 数组还是 bmbt，内存里 fork 的 extent 集合都被统一放进 `if_data` 指向的一棵 **in-core B+ 树**（`libxfs/xfs_iext_tree.c`）。它是一棵 16 叉的 mini B+ 树：节点 256 字节，inner 节点 16 个 key + 16 个指针，leaf 节点 15 条记录 + 前后指针：

```c
enum {
	NODE_SIZE	= 256,
	KEYS_PER_NODE	= NODE_SIZE / (sizeof(uint64_t) + sizeof(void *)),
	RECS_PER_LEAF	= (NODE_SIZE - (2 * sizeof(struct xfs_iext_leaf *))) /
				sizeof(struct xfs_iext_rec),
};

/*
 * In-core extent btree block layout:
 *
 * There are two types of blocks in the btree: leaf and inner (non-leaf) blocks.
 *
 * The leaf blocks are made up by %KEYS_PER_NODE extent records, which each
 * contain the startoffset, blockcount, startblock and unwritten extent flag.
 * See above for the exact format, followed by pointers to the previous and next
 * leaf blocks (if there are any).
 * ...
 */
```

节点大小 256 字节是刻意的——正好一个 cacheline 簇，且 extent 记录在内存里被压成 16 字节（两个 u64 手工位打包）：

```
 * In-core extent record layout:
 *
 * +-------+----------------------------+
 * | 00:53 | all 54 bits of startoff    |
 * | 54:63 | low 10 bits of startblock  |
 * +-------+----------------------------+
 * | 00:20 | all 21 bits of length      |
 * |    21 | unwritten extent bit       |
 * | 22:63 | high 42 bits of startblock |
 * +-------+----------------------------+
```

配合 `struct xfs_iext_cursor`（缓存最近访问的 leaf + pos），顺序遍历一个文件的 extent 几乎退化为数组扫描——这正是 XFS 在大文件顺序读写上表现好的原因之一。

## Everything Is a B+ Tree

XFS 里没有"位图 + 表"这种东西，所有索引结构都是 B+ 树：

| 树 | 全称 | 键 → 值 | 根在哪 | 用途 |
| --- | --- | --- | --- | --- |
| bmbt | bmap btree | 文件逻辑块 → 物理块 + 长度 | inode data fork（BTREE 格式） | 文件 extent 映射 |
| bnobt | free space by block | 起始块号 → 长度 | AGF `agf_bno_root` | 按位置找空闲空间（近邻分配、合并） |
| cntbt | free space by count | 长度 → 起始块号（多重） | AGF `agf_cnt_root` | 按大小找空闲空间 |
| inobt | inode btree | AG 内 inode 号 → chunk 空闲掩码 | AGI `agi_root` | 定位 inode chunk 与空闲 inode |
| finobt | free inode btree | AG 内 inode 号 | AGI `agi_free_root` | 只索引"有空闲 inode"的 chunk |
| rmapbt | reverse mapping | 物理块 → (owner, offset, flags) | AGF `agf_rmap_root` | 反向映射，支撑 reflink / scrub / trim |
| refcbt | refcount | 物理块 → 引用计数 | AGF `agf_refcount_root` | reflink 共享块的引用计数 |
| dabt | directory/attr btree | 名字哈希 → 块地址 | inode fork | 大目录与大属性 |

注意 **bnobt 与 cntbt 记录的是同一份空闲空间的两份索引**：一个按位置排序（便于"在 X 附近找块"和"与相邻空闲区合并"），一个按长度排序（便于"找一段 ≥ N 的空间"）。这是 XFS 分配质量高的关键，代价是每次空闲空间变动要更新两棵树。

磁盘上的 B+ 树块头分 **short / long** 两种格式：

```c
/* short form block header */
struct xfs_btree_block_shdr {
	__be32		bb_leftsib;
	__be32		bb_rightsib;

	__be64		bb_blkno;
	__be64		bb_lsn;
	uuid_t		bb_uuid;
	__be32		bb_owner;
	__le32		bb_crc;
};

/* long form block header */
struct xfs_btree_block_lhdr {
	__be64		bb_leftsib;
	__be64		bb_rightsib;

	__be64		bb_blkno;
	__be64		bb_lsn;
	uuid_t		bb_uuid;
	__be64		bb_owner;
	__le32		bb_crc;
	__be32		bb_pad; /* padding for alignment */
};

struct xfs_btree_block {
	__be32		bb_magic;	/* magic number for block type */
	__be16		bb_level;	/* 0 is a leaf */
	__be16		bb_numrecs;	/* current # of data records */
	union {
		struct xfs_btree_block_shdr s;
		struct xfs_btree_block_lhdr l;
	} bb_u;				/* rest */
};
```

short 用于**指针是 32 位**的树（AG 内的 bnobt/cntbt/inobt/finobt/rmapbt/refcbt，块号是 32 位 AG 相对块号）；long 用于**指针是 64 位**的树（bmbt 的 fsblock、realtime 的 rtrmapbt）。源码里明确警告"永远不要用 `sizeof(xfs_btree_block)`"，要用 `XFS_BTREE_SBLOCK_LEN` / `XFS_BTREE_LBLOCK_LEN`。

所有树共用一套游标与遍历算法，差异通过 `struct xfs_btree_ops` 这张"vtable"注入：

```c
	/* cursor operations */
	struct xfs_btree_cur *(*dup_cursor)(struct xfs_btree_cur *);
	void	(*update_cursor)(struct xfs_btree_cur *src,
				 struct xfs_btree_cur *dst);

	/* update btree root pointer */
	void	(*set_root)(struct xfs_btree_cur *cur,
			    const union xfs_btree_ptr *nptr, int level_change);

	/* block allocation / freeing */
	int	(*alloc_block)(struct xfs_btree_cur *cur, ...);
	int	(*free_block)(struct xfs_btree_cur *cur, struct xfs_buf *bp);

	/* records in block/level */
	int	(*get_minrecs)(struct xfs_btree_cur *cur, int level);
	int	(*get_maxrecs)(struct xfs_btree_cur *cur, int level);

	/* init values of btree structures */
	void	(*init_key_from_rec)(union xfs_btree_key *key,
				     const union xfs_btree_rec *rec);
	...
	/* Compare key value and cursor value -- positive if key > cur, ... */
	int	(*cmp_key_with_cur)(struct xfs_btree_cur *cur,
				    const union xfs_btree_key *key);
	...
	const struct xfs_buf_ops	*buf_ops;
```

`buf_ops` 是每种树的 **verifier**——读写块时校验 magic、uuid、owner、CRC 与记录有序性。这既是完整性保护，也让 [scrub](#数据完整性crc-与在线修复) 与在线修复有了统一的检查入口。

## Extent Mapping and Delayed Allocation

磁盘上的 bmbt 记录是两个 64 位字的位打包：

```c
/*
 * Bmap btree record and extent descriptor.
 *  l0:63 is an extent flag (value 1 indicates non-normal).
 *  l0:9-62 are startoff.
 *  l0:0-8 and l1:21-63 are startblock.
 *  l1:0-20 are blockcount.
 */
#define BMBT_EXNTFLAG_BITLEN	1
#define BMBT_STARTOFF_BITLEN	54
#define BMBT_STARTBLOCK_BITLEN	52
#define BMBT_BLOCKCOUNT_BITLEN	21
```

由此推出两个硬限制：**单个 extent 最长 2²¹−1 个块**（4 KiB 块即 8 GiB，`XFS_MAX_BMBT_EXTLEN`），以及物理块号 52 位。文件偏移只能到 54 位——这也是 XFS 单文件大小上限的来源。

延迟分配（delayed allocation）是 XFS 写路径的核心。写入时先在内存 fork 里插一条**没有真实物理块**的 extent，用非法的 startblock 值编码"这是延迟分配，另外预留了 indlen 个间接块"：

```c
/*
 * Values and macros for delayed-allocation startblock fields.
 */
#define STARTBLOCKVALBITS	17
#define STARTBLOCKMASKBITS	(15 + 20)
#define STARTBLOCKMASK		\
	(((((xfs_fsblock_t)1) << STARTBLOCKMASKBITS) - 1) << STARTBLOCKVALBITS)

static inline int isnullstartblock(xfs_fsblock_t x)
{
	return ((x) & STARTBLOCKMASK) == STARTBLOCKMASK;
}
```

预留动作在 `xfs_bmapi_reserve_delalloc()` 里完成——从全局空闲块计数里扣掉数据块 + 最坏情况的间接块（`xfs_bmap_worst_indlen()`），再插一条 `br_startblock = nullstartblock(indlen)` 的记录：

```c
	indlen = (xfs_extlen_t)xfs_bmap_worst_indlen(ip, alen);
	ASSERT(indlen > 0);

	fdblocks = indlen;
	if (XFS_IS_REALTIME_INODE(ip)) {
		...
	} else {
		fdblocks += alen;
	}

	error = xfs_dec_fdblocks(mp, fdblocks, false);
	if (error)
		goto out_unreserve_frextents;

	ip->i_delayed_blks += alen;
	xfs_mod_delalloc(ip, alen, indlen);

	got->br_startoff = aoff;
	got->br_startblock = nullstartblock(indlen);
	got->br_blockcount = alen;
	got->br_state = XFS_EXT_NORM;

	xfs_bmap_add_extent_hole_delay(ip, whichfork, icur, got);
```

真正分配发生在**页写回时**（`xfs_bmapi_convert_delalloc()`）：此时内核已经知道要写多少个连续页，可以一次拿到一段连续物理块。这就是 XFS 常说的"延迟分配改善文件布局"的机制——分配决策推迟到信息最完整的时刻，而不是在 `write()` 刚到达、还不知道后续写多少的时候。

副作用有两个：一是 `i_delayed_blks` 让 `stat` 看到的块数与最终落盘的不同；二是空间不足时，延迟分配的"过度预留"（speculative preallocation）要先由 `pag_blockgc_work` 收回。

## Log: Logical Log, CIL and AIL

这是 XFS 与 ext4 差别最大的一块。ext4 用 [jbd2](/docs/CS/OS/Linux/fs/jbd2.md) 做**物理日志**：记录"哪些元数据块被改了"（整块或块内范围），恢复时把块内容重新写回原位，并用 revoke 表防止重放已被取消的旧块。XFS 做的是**逻辑日志**：日志项描述"发生了什么修改"，恢复时按项的类型重新执行。

差异落到四个机制上：

### log item

```c
struct xfs_log_item {
	struct list_head		li_ail;		/* AIL pointers */
	struct list_head		li_trans;	/* transaction list */
	xfs_lsn_t			li_lsn;		/* last on-disk lsn */
	struct xlog			*li_log;
	struct xfs_ail			*li_ailp;	/* ptr to AIL */
	uint				li_type;	/* item type */
	unsigned long			li_flags;	/* misc flags */
	struct xfs_buf			*li_buf;	/* real buffer pointer */
	struct list_head		li_bio_list;	/* buffer item list */
	const struct xfs_item_ops	*li_ops;	/* function list */

	/* delayed logging */
	struct list_head		li_cil;		/* CIL pointers */
	struct xfs_log_vec		*li_lv;		/* active log vector */
	struct xfs_log_vec		*li_lv_shadow;	/* standby vector */
	xfs_csn_t			li_seq;		/* CIL commit seq */
	uint32_t			li_order_id;	/* CIL commit order */
};

struct xfs_item_ops {
	unsigned flags;
	void (*iop_size)(struct xfs_log_item *, int *, int *);
	void (*iop_format)(struct xfs_log_item *lip,
			struct xlog_format_buf *lfb);
	void (*iop_pin)(struct xfs_log_item *);
	void (*iop_unpin)(struct xfs_log_item *, int remove);
	uint64_t (*iop_sort)(struct xfs_log_item *lip);
	int (*iop_precommit)(struct xfs_trans *tp, struct xfs_log_item *lip);
	void (*iop_committing)(struct xfs_log_item *lip, xfs_csn_t seq);
	xfs_lsn_t (*iop_committed)(struct xfs_log_item *, xfs_lsn_t);
	uint (*iop_push)(struct xfs_log_item *, struct list_head *);
	void (*iop_release)(struct xfs_log_item *);
	bool (*iop_match)(struct xfs_log_item *item, uint64_t id);
	struct xfs_log_item *(*iop_intent)(struct xfs_log_item *intent_done);
};
```

一个 item 同时挂在三个链表上：`li_trans`（当前事务的项）、`li_cil`（已提交但还没写进日志缓冲区的项）、`li_ail`（已写进日志但对应元数据还没落盘的项）。`li_lv` / `li_lv_shadow` 是延迟日志的双缓冲——格式化新内容时写进 shadow，push 时交换。

`iop_pin` / `iop_unpin` 是 XFS 保证顺序的机制：**元数据 buffer 在日志写入完成前被 pin 住，不许回写**。否则可能出现"盘上的元数据已经是新的，但日志里还没有对应的记录"，崩溃后无法恢复。ext4 靠 jbd2 的 commit/checkpoint 顺序保证同一件事。

`XFS_ITEM_INTENT` / `XFS_ITEM_INTENT_DONE` 两类项是 XFS 特有的：**一个逻辑操作可能要修改多个 AG 的多个结构，无法放进一个事务**。做法是先把"意图"（intent，比如 EFI = extent free intent）记进日志，执行完后再记一条"完成"（intent done，EFD），恢复时若发现只有 intent 没有 done，就重做；若两者都有就跳过。

### Transactions

```c
static int
xfs_trans_reserve(
	struct xfs_trans	*tp,
	struct xfs_trans_res	*resp,
	uint			blocks,
	uint			rtextents)
{
	...
	/*
	 * Attempt to reserve the needed disk blocks by decrementing the number
	 * needed from the number available.  This will fail if the count would
	 * go below zero.
	 */
	if (blocks > 0) {
		error = xfs_dec_fdblocks(mp, blocks, rsvd);
		if (error != 0)
			return -ENOSPC;
		tp->t_blk_res += blocks;
	}

	/*
	 * Reserve the log space needed for this transaction.
	 */
	if (resp->tr_logflags & XFS_TRANS_PERM_LOG_RES)
		tp->t_flags |= XFS_TRANS_PERM_LOG_RES;
	error = xfs_log_reserve(mp, resp->tr_logres, resp->tr_logcount,
			&tp->t_ticket, (tp->t_flags & XFS_TRANS_PERM_LOG_RES));
	...
```

注意 XFS 的**预留是三重**的：日志空间（ticket）、数据块、realtime extent。而且日志空间的预留量是**静态预估**的（`struct xfs_trans_res` 在 `xfs_trans_resv.c` 里按操作类型预先算好最坏值），这是"XFS 事务不会因日志满而半途失败"的前提——预留足了就一定能提交完。

提交路径很短——**提交就是把 item 交给 CIL**：

```c
	xlog_cil_commit(log, tp, &commit_seq, regrant);

	xfs_trans_free(tp);

	/*
	 * If the transaction needs to be synchronous, then force the
	 * log out now and wait for it.
	 */
	if (sync) {
		error = xfs_log_force_seq(mp, commit_seq, XFS_LOG_SYNC, NULL);
		XFS_STATS_INC(mp, xs_trans_sync);
	} else {
		XFS_STATS_INC(mp, xs_trans_async);
	}
```

只有 `XFS_TRANS_SYNC` 的事务（如 `fsync`、创建文件）才真的等日志落盘。

### CIL: The Core of Delayed Logging

CIL（Committed Item List）把"每个事务一次日志写"变成"一批事务合并成一次 checkpoint"。同一个元数据在 CIL 里被改十次，最终只写一次最新内容：

```c
		/* compare to existing item size */
		if (lv && shadow->lv_alloc_size <= lv->lv_alloc_size) {
			/* same or smaller, optimise common overwrite case */

			/*
			 * set the item up as though it is a new insertion so
			 * that the space reservation accounting is correct.
			 */
			*diff_len -= lv->lv_bytes;
			...
			/* reset the lv buffer information for new formatting */
			lv->lv_buf_used = 0;
			lv->lv_bytes = 0;
			lv->lv_buf = (char *)lv +
					xlog_cil_iovec_space(lv->lv_niovecs);
		} else {
			/* switch to shadow buffer! */
			lv = shadow;
			lv->lv_item = lip;
		}

		lfb.lv = lv;
		lip->li_ops->iop_format(lip, &lfb);
		xfs_cil_prepare_item(log, lip, lv, diff_len);
```

这就是 **re-logging**：重新格式化覆盖旧内容，而不是追加一条新记录。这个优化对 XFS 至关重要——典型负载（频繁 bump 同一个 inode 的 mtime、反复增删同一个目录项）在物理日志下会产生大量冗余记录，在这里被压缩成一份。

push 由工作队列异步执行，触发条件是 CIL 大小超过阈值、日志空间紧张、或显式 `xfs_log_force`。它还要保证 **checkpoint 之间的顺序**：

```c
	/*
	 * Switch the contexts so we can drop the context lock and move out
	 * of a shared context. We can't just go straight to the commit record,
	 * though - we need to synchronise with previous and future commits so
	 * that the commit records are correctly ordered in the log to ensure
	 * that we process items during log IO completion in the correct order.
	 *
	 * For example, if we get an EFI in one checkpoint and the EFD in the
	 * next (e.g. due to log forces), we do not want the checkpoint with
	 * the EFD to be committed before the checkpoint with the EFI.  Hence
	 * we must strictly order the commit records of the checkpoints so
	 * that: a) the checkpoint callbacks are attached to the iclogs in the
	 * correct order; and b) the checkpoints are replayed in correct order
	 * in log recovery.
	 */
```

同一个 checkpoint 内部还有**项排序**（`li_order_id`）——reflink 场景下一次事务会记录 4 条有依赖关系的 intent（unmap → drop refcount → inc refcount → remap），顺序不能乱：

```c
/*
 * CIL item reordering compare function. We want to order in ascending ID order,
 * but we want to leave items with the same ID in the order they were added to
 * the list. This is important for operations like reflink where we log 4 order
 * dependent intents in a single transaction when we overwrite an existing
 * shared extent with a new shared extent. i.e. BUI(unmap), CUI(drop),
 * CUI (inc), BUI(remap)...
 */
```

### AIL and the Log Tail

日志写完后，item 从 CIL 移入 **AIL（Active Item List）**。AIL 回答的问题是"**哪些元数据已经记进日志、但还没写到最终位置**"——最老的那个 item 的 LSN 就是**日志尾部（tail LSN）**，它之前的日志空间可以回收。元数据块真正回写后，对应 item 出 AIL，尾部前进。

所以 XFS 里"日志空间不够"的常见原因是：AIL 里有钉住的老 item（比如某个 AG 的元数据一直没能写回），尾部推不动。这与 jbd2 的 checkpoint 机制目标相同，但粒度是 item 而不是整个事务/块。

### Recovery

```c
	/*
	 * First do a pass to find all of the cancelled buf log items.
	 * Store them in the buf_cancel_table for use in the second pass.
	 */
	error = xlog_alloc_buf_cancel_table(log);
	if (error)
		return error;

	error = xlog_do_recovery_pass(log, head_blk, tail_blk,
				      XLOG_RECOVER_PASS1, NULL);
	if (error != 0)
		goto out_cancel;

	/*
	 * Then do a second pass to actually recover the items in the log.
	 * When it is complete free the table of buf cancel items.
	 */
	error = xlog_do_recovery_pass(log, head_blk, tail_blk,
				      XLOG_RECOVER_PASS2, NULL);
```

两趟扫描：**PASS1** 只收集"哪些 buffer 项的修改后来被取消了"（对应 jbd2 的 revoke 表），**PASS2** 才真正回放。之后还有两步：`xlog_recover_process_intents()` 处理没配对的 intent，`xlog_recover_process_iunlinks()` 清理 unlinked inode。

## Directory and Extended Attributes: da btree

目录有四种形态，随条目数增长依次升级：

```
 *  - shortform - embedded into the inode
 *  - single block - data with embedded leaf at the end
 *  - multiple data blocks, single leaf+freeindex block
 *  - data blocks, node and leaf blocks (btree), freeindex blocks
```

对应的 magic：

```c
#define	XFS_DIR2_BLOCK_MAGIC	0x58443242	/* XD2B: single block dirs */
#define	XFS_DIR2_DATA_MAGIC	0x58443244	/* XD2D: multiblock dirs */
#define	XFS_DIR2_FREE_MAGIC	0x58443246	/* XD2F: free index blocks */
```

- **shortform**：小目录的条目直接嵌在 inode 的 LOCAL fork 里，一次读 inode 就拿到全部内容；
- **block**：单个目录块，数据区放条目、块尾内嵌 leaf（哈希索引），省一次 I/O；
- **leaf + freeindex**：多个数据块 + 一个 leaf 块，freeindex 跟踪每个数据块的空闲空间以便分配新条目；
- **node/btree**：目录大到 leaf 放不下，升级为 B+ 树。

目录与扩展属性**共用同一套 da btree 代码**（`XFS_DA_NODE_MAGIC`），区别只在叶子里的条目格式。这也是为什么 XFS 的 xattr 能做到与目录同量级的大小——它们本来就是同一棵树，只是叶子解释方式不同。

v3（CRC 版）换了 magic 以便运行时原地识别，并给目录项加了文件类型字段：

```c
#define	XFS_DIR3_BLOCK_MAGIC	0x58444233	/* XDB3: single block dirs */
#define	XFS_DIR3_DATA_MAGIC	0x58444433	/* XDD3: multiblock dirs */
#define	XFS_DIR3_FREE_MAGIC	0x58444633	/* XDF3: free index blocks */
...
#define XFS_DIR3_FT_UNKNOWN		0
#define XFS_DIR3_FT_REG_FILE		1
#define XFS_DIR3_FT_DIR			2
...
```

有了 FT 字段，`readdir` 不用为每个条目 `stat` 一次——这是 `ls -lR` 在大目录上快的原因之一。源码里那句"Where it is possible, the code decides what to do based on the magic numbers in the blocks rather than feature bits in the superblock"说明格式判断是靠块内 magic 而非超级块特性位，便于工具离线解析。

## Free Space and Allocation Strategy

分配一个 extent 时，XFS 的决策链是：

1. **选 AG**：按 locality（文件所在目录/已有 extent 附近的 AG）优先，否则选空闲最多的；filestream 特性（`-o filestreams`）会把大文件流分散到不同 AG，避免一个 AG 被单个大文件吃满；
2. **选 extent**：优先在目标偏移附近找（`bnobt` 近邻查找），找不到再用 `cntbt` 找足够长的；
3. **投机预分配**：按文件大小与访问模式多分配一段（`i_delayed_blks`），减少后续分配的次数与碎片；空间紧张时由 `pag_blockgc_work` 收回；
4. **extent size hint**（`di_extsize`）：给实时/数据库类负载的对齐提示，让分配按固定粒度对齐。

刚释放的 extent 不会立即复用：

```
刚释放的块 → extent busy 树（按 AG 组织的红黑树）→ 等到相关日志写回 → 才可重新分配
```

原因是：如果块被立刻分配给了别处，而旧的所有者元数据还没落盘，崩溃后恢复会把旧内容"复活"，造成交叉损坏。ext4 用块位图的日志顺序保证同一件事。

## Data Integrity: CRC and Online Repair

v5 格式（2013 年引入，现在是 mkfs 默认）给每个元数据块加了自我描述头：`magic + uuid + 自身块号 + owner + LSN + CRC`。这带来三个能力：

- **认领**：读到一块能立刻判断它是不是本文件系统的、是不是该位置的、owner 对不对——`xfs_repair` 因此能区分"这是我的块放错了"和"这是别人的块"；
- **新鲜度**：LSN 让恢复时判断"盘上这块是否已经包含了日志里的修改"，避免重复回放；
- **即时检测**：verifier 在每次读写时校验，出错立即报错而不是静默损坏。

更进一步的是**在线检查与修复**：`xfs_scrub`（用户态）驱动内核的 `fs/xfs/scrub/` 做一致性检查（`scrub/btree.c`、`scrub/rmap.c`、`scrub/dir.c` …），并在 `CONFIG_XFS_ONLINE_REPAIR` 下调用对应的 `*_repair.c` 重建结构。这在 ext4 侧没有对等物（ext4 只能 offline `e2fsck`）。

健康状态用位掩码记录在 `xfs_mount.m_fs_sick` / `m_rt_sick` 与每个 inode 的 `i_sick` 上，v7 还加了 `xfs_healthmon.c` 把状态变化以事件形式上报给用户态。

## reflink and Reverse Mapping

**reflink**（`cp --reflink`）让两个文件共享同一批物理块，写入时再 CoW。它依赖两棵树：

- **refcbt**：记录每个共享物理块的引用计数；
- **rmapbt**：记录每个物理块属于谁（owner inode + 逻辑偏移 + 属性）。

为什么一定要 rmapbt？因为要 CoW 一个共享块，必须知道"还有谁在用这块"以及"这块在各自的逻辑偏移上是什么"——只有正向的 extent 映射回答不了这个问题。rmapbt 顺带还支撑：

- 在线修复（能反查出某块的所有引用，重建结构）；
- `fstrim` 与 thin provisioning（知道哪些块真的没被引用来判断能否 discard）；
- 文件块级别的碎片整理。

写入共享块时，新内容先写进 **CoW fork**（`i_cowfp`），写完成后再原子地替换 data fork 中的映射（通过 BUI/BUD intent 项保证原子性）。这一整套依赖前面说的 intent 机制，是 XFS 日志里最复杂的一类操作。

## Realtime Subvolume, zoned, and Metadata Directory (v7 New Developments)

XFS 有一个可选的 **realtime 子卷**：独立设备，空间按 **rt extent**（通常是块大小的整数倍）分配，由 rtbitmap / rtsummary 两个元数据文件管理。它给需要稳定带宽的场景（视频采集、数据库）用——分配粒度大、布局可预测。

v7.2.7 在这个方向上加了两个大东西：

### realtime group and zoned Devices

`sb_rgcount` / `sb_rgextents` / `sb_rgblklog` 把 realtime 子卷也切成 **rt group**，与 AG 并列为 `struct xfs_group`（`XG_TYPE_RTG`）。在此基础上支持 **zoned 块设备**（SMR HDD、NVMe ZNS）：

```c
#define XFS_FEAT_ZONED		(1ULL << 29)	/* zoned RT device */
```

`xfs_zone_alloc.c`（2023–2025，Christoph Hellwig）实现了 zone 分配器：把 rt group 当作 zone，按"已用块数"分桶（`xfs_zone_bucket()`）选择 open zone，写满后回收，并配 `xfs_zone_gc.c` 做垃圾回收——本质上是一个 log-structured 分配器跑在 realtime 子卷上。这是 XFS 近年最大的结构性变化之一。

### metadata directory（metadir）

```c
#define XFS_FEAT_METADIR	(1ULL << 28)	/* metadata directory tree */
```

传统 XFS 的元数据（rt bitmap、rt summary、quota 文件）是"藏在超级块指针后面"的特殊 inode，没法被 scrub、没法配额、也没法用普通工具查看。metadir 把它们变成**元数据目录树里的普通文件**（`sb_metadirino` 指向根目录），每个文件的角色由 `di_metatype` 标记：

```c
enum xfs_metafile_type {
	XFS_METAFILE_UNKNOWN,		/* unknown */
	XFS_METAFILE_DIR,		/* metadir directory */
	XFS_METAFILE_USRQUOTA,		/* user quota */
	XFS_METAFILE_GRPQUOTA,		/* group quota */
	XFS_METAFILE_PRJQUOTA,		/* project quota */
	XFS_METAFILE_RTBITMAP,		/* rt bitmap */
	XFS_METAFILE_RTSUMMARY,		/* rt summary */
	XFS_METAFILE_RTRMAP,		/* rt rmap */
	XFS_METAFILE_RTREFCOUNT,	/* rt refcount */
	XFS_METAFILE_MAX
};
```

对应的 fork 格式是新增的 `XFS_DINODE_FMT_META_BTREE`。

## Feature Bits

特性分四级，决定"老内核能否挂载"：

| 级别 | 含义 | 举例 |
| --- | --- | --- |
| `sb_features_compat` | 老内核可读写 | — |
| `sb_features_ro_compat` | 老内核可只读挂载 | `rmapbt`、`reflink`、`finobt`、`inobtcount`、`bigtime`、`nrext64` |
| `sb_features_incompat` | 老内核拒绝挂载 | `metadir`、`zoned`、`parent`（parent pointers）、`ftype` |
| `sb_features_log_incompat` | 只在日志里有不兼容记录时置位，清日志后可降级 | 某些 intent 项 |

内核侧对应 `m_features` 位图（`XFS_FEAT_*`，`xfs_mount.h`），常用 `xfs_has_reflink(mp)` 之类的谓词判断。新增特性往往同时需要 log_incompat 位，这样"用过新特性但日志已清空"的文件系统仍能降级挂载。

## ext4 vs XFS Comparison

| 维度 | ext4 | XFS |
| --- | --- | --- |
| 出身 | ext2/ext3 演进，面向通用 | SGI IRIX，面向大容量高并发 |
| 空间管理单元 | 块组（固定 inode 表 + 位图） | 分配组（自包含 B+ 树，inode 位置由 inode 号算出） |
| 空闲空间索引 | 块位图 + 伙伴（mballocator 在内存做） | bnobt / cntbt 两棵持久化 B+ 树 |
| inode 分配 | 块组内固定 inode 表 + 位图 | inobt + finobt，sparse chunk |
| 大目录 | HTree（哈希 B 树） | da btree（目录与 xattr 共用） |
| 分配策略 | 延迟分配 + 多块预分配 + 组内聚集 | 延迟分配 + 投机预分配 + per-AG 并行 + filestream |
| 日志 | jbd2，物理日志，checkpoint 推进 | 逻辑日志，log item + CIL 合并 + AIL 推进 |
| 日志内容粒度 | 元数据块（整块/范围）+ revoke 表 | 操作项（buf/inode/dquot/intent…），可 re-logging 覆盖 |
| 元数据校验 | 部分（metadata_csum 覆盖有限） | v5 全量 self-describing + CRC |
| 在线修复 | 无（只能 offline e2fsck） | `xfs_scrub` + 内核 online repair |
| reflink | 支持（较晚，上限较少） | 支持，且依赖 rmapbt/refcbt 体系 |
| 缩小 | 支持（resize2fs 离线） | **不支持**，只能 grow |
| 典型场景 | 通用、小盘、boot 分区、需要缩容 | 大容量、大文件、高并发、数据库与虚拟化存储 |

一句话总结取舍：**ext4 是"够用且能缩"的通用盘，XFS 是"大而快但不能缩"的专业盘**。选择时最硬的约束是"要不要缩容"——要就只能选 ext4（或 Btrfs）。

## Usage and Operations

- `mkfs.xfs`：创建时可指定 AG 数量/大小（`agcount=` / `agsize=`）、inode 大小、是否启用 reflink/rmap（`-m reflink=1 -m rmapbt=1`）、CRC（默认开）、外部日志（`logdev=`）；
- `xfs_growfs`：在线扩容（**只能增不能减**）；
- `xfs_repair`：离线修复，通常需要先 replay 日志；严重时可能需要 `-L` 强制清日志（会丢最近的修改）；
- `xfs_scrub`：在线一致性检查（需要内核开启 scrub 支持）；
- `xfs_fsr`：在线碎片整理；
- `xfs_quota`：配额管理，project quota 常用于给容器目录设限；
- `xfsdump` / `xfsrestore`：备份，支持并行流。

XFS 的元数据更新频繁且都经过日志，因此**日志设备放 SSD 或独立盘**是常见的优化；`logbufs=` / `logbsize=` 调大日志缓冲对元数据密集负载有效。

## Links

- [文件管理链路总图](/docs/CS/OS/Linux/fs/README.md) — XFS 在 VFS 之下的位置
- [fs.md](/docs/CS/OS/Linux/fs/fs.md) — 四大对象与挂载、路径查找
- [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md) — 容器镜像分层，通常跑在 XFS / ext4 之上
- [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) — 缓冲写的落盘时机决定延迟分配的最终布局
- [mempool](/docs/CS/OS/Linux/mm/mempool.md) — XFS 在元数据路径上用预留池避免回收死锁

## References

1. [XFS Filesystem Documentation — The Linux Kernel documentation](https://docs.kernel.org/filesystems/xfs/index.html)
2. [XFS Logging Design（delayed logging 与 re-logging）](https://docs.kernel.org/filesystems/xfs/xfs-delayed-logging-design.html)
3. [XFS Self Describing Metadata](https://docs.kernel.org/filesystems/xfs/xfs-self-describing-metadata.html)
4. [XFS Online Fsck Design（scrub 与在线修复）](https://docs.kernel.org/filesystems/xfs/xfs-online-fsck-design.html)
5. [xfs(5) — Linux manual page](https://man7.org/linux/man-pages/man5/xfs.5.html)
