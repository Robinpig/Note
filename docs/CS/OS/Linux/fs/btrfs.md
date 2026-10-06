## Introduction

btrfs 是 Linux 上最重要的 CoW（写时复制）文件系统。它不是" ext4 的改进版"，而是围绕**三棵树 + 一套映射**重新设计的：把"哪些逻辑块在用"（extent tree）、"逻辑到物理怎么转"（chunk tree）、"文件树"（fs tree）分开，再用 CoW 保证一致性。

它的三个招牌能力都源于这个设计：

- **快照（snapshot）** —— 块级共享，改动时只复制变化的块。子卷快照几乎是零成本。
- **多盘聚合（multi-device）** —— 多个设备组成一个文件系统，按 chunk 分配到各设备，支持 RAID。
- **校验和（checksum）** —— 每个 extent 都有独立校验和，不依赖下层设备是否可靠。

版本基线 **v7.2**。⚠️ **v7.2 的结构定义已大改**：核心结构定义搬到 **uapi 头**（`include/uapi/linux/btrfs_tree.h`，1357 行），`fs/btrfs/` 下的私有头改用**下划线命名**（`block-group.h` / `delayed-ref.h` / `extent-io-tree.h`）。旧的 `btrfs_tree.h` 私有头**已不存在**。

## 魔数与根

```c
#define BTRFS_MAGIC 0x4D5F53665248425FULL
```

定义在 `include/uapi/linux/btrfs_tree.h:14`。

> ⚠️ **旧资料里的 `BTRFS_SUPER_MAGIC` 及其四个变体（`_METADUP` / `_METADUP_V0` / `_CSUM_TREE`）在 v7.2 全部不存在** —— v7.2 只有单一 `BTRFS_MAGIC`。这些变体是历史遗留，用于识别旧格式磁盘，现在只读旧盘的代码才需要。

## 五棵树

btrfs 的核心是**所有元数据存在树里**。每棵树是一个 B+ 树，根由超级块指向。树用 objectid 区分：

| objectid | 常量 | 作用 |
| :-- | :-- | :-- |
| 1 | `BTRFS_EXTENT_TREE_OBJECTID` | **哪些 extent 在用 + 引用计数** |
| 2 | （同上，值 2） | |
| 3 | `BTRFS_CHUNK_TREE_OBJECTID` | **逻辑 → 物理的映射**（块设备映射表） |
| 4 | `BTRFS_DEV_TREE_OBJECTID` | 每个设备一棵（哪些区域在用） |
| 5 | `BTRFS_FS_TREE_OBJECTID` | **文件树**（每个 subvolume 一棵） |
| 6 | `BTRFS_ROOT_TREE_DIR_OBJECTID` | root tree 里的目录 |
| 7 | `BTRFS_CSUM_TREE_OBJECTID` | **所有 data extent 的校验和** |
| 8 | `BTRFS_QUOTA_TREE_OBJECTID` | quota 配置与统计 |
| 9 | `BTRFS_UUID_TREE_OBJECTID` | `BTRFS_UUID_KEY*` 类型的条目 |
| 10 | `BTRFS_FREE_SPACE_TREE_OBJECTID` | 空闲空间跟踪 |
| 11 | `BTRFS_BLOCK_GROUP_TREE_OBJECTID` | **extent tree v2** 的块组条目 |
| 12 | `BTRFS_RAID_STRIPE_TREE_OBJECTID` | 块组内的 RAID 条带跟踪 |
| 13 | `BTRFS_REMAP_TREE_OBJECTID` | **relocate 之后的地址重映射** |

> ⚠️ **命名全变了**：旧资料里的 `BTRFS_EXTENT_TREE_KEY` / `BTRFS_CHUNK_TREE_KEY` / `BTRFS_ROOT_TREE_KEY` / `BTRFS_DEV_TREE_KEY` / `BTRFS_UUID_ITEM_KEY` **都不存在**，v7.2 一律是 `*_OBJECTID`。`BTRFS_UUID_ITEM_KEY` 也不存在（对应的是 `BTRFS_UUID_TREE_OBJECTID` 这棵树里的 key 类型）。

负 objectid 用于**内部/元数据用途**：

| objectid | 常量 | 用途 |
| :-- | :-- | :-- |
| -4 | `BTRFS_BALANCE_OBJECTID` | balance 参数 |
| -5 | `BTRFS_ORPHAN_OBJECTID` | **跟踪被 unlink/truncate 的文件** |
| -6 | `BTRFS_TREE_LOG_OBJECTID` | **写前日志（tree log）** |
| -7 | `BTRFS_TREE_LOG_FIXUP_OBJECTID` | tree log 修正 |
| -8 | `BTRFS_TREE_RELOC_OBJECTID` | 空间平衡 |
| -9 | `BTRFS_DATA_RELOC_TREE_OBJECTID` | 预留 |
| -10 | `BTRFS_EXTENT_CSUM_OBJECTID` | **extent 校验和（共享 tree log 加速 fsync）** |
| -11 | `BTRFS_FREE_SPACE_OBJECTID` | 空闲空间缓存 |

`BTRFS_TREE_LOG_OBJECTID` 与 `BTRFS_EXTENT_CSUM_OBJECTID` 的注释值得注意：

```c
/*
 * extent checksums all have this objectid
 * this allows them to share the logging tree
 * for fsyncs
 */
#define BTRFS_EXTENT_CSUM_OBJECTID -10ULL
```

**校验和条目共享 tree log** —— 所以 `fsync` 一个文件时，其数据块的校验和也在同一个 log 里被 fsync，这是 btrfs 的 `data-sum` 机制。

分界常量：

```c
#define BTRFS_FIRST_FREE_OBJECTID 256ULL
#define BTRFS_LAST_FREE_OBJECTID -256ULL
#define BTRFS_FIRST_CHUNK_TREE_OBJECTID 256ULL
```

**256 是分界线**：用户空间 objectid 从 256 起分配，内核保留 < 256。

## key：树的坐标

```c
struct btrfs_disk_key {
	__le64 objectid;
	__u8 type;
	__u8 offset;
} __attribute__ ((__packed__));

struct btrfs_key {
	u64 objectid;
	u32 type;
	u64 offset;
};
```

三段式坐标：**哪个文件（objectid）× 什么类型（type）× 文件内偏移（offset）**。树内按 `(objectid, type, offset)` 排序，所以一次树搜索就是三元组比较。

主要 key 类型（数值来自 `uapi/linux/btrfs_tree.h`）：

| 常量 | 值 | 内容 |
| :-- | :-- | :-- |
| `BTRFS_INODE_ITEM_KEY` | 1 | **inode 的元数据**（mode/uid/times/flags） |
| `BTRFS_INODE_REF_KEY` | 12 | **硬链接计数** |
| `BTRFS_INODE_EXTREF_KEY` | 13 | 扩展硬链接引用 |
| `BTRFS_XATTR_ITEM_KEY` | 24 | 扩展属性 |
| `BTRFS_VERITY_DESC_ITEM_KEY` | 36 | fs verity 描述符 |
| `BTRFS_VERITY_MERKLE_ITEM_KEY` | 37 | fs verity merkle 树 |
| `BTRFS_ORPHAN_ITEM_KEY` | 48 | **孤儿条目**（已 unlink 但未提交） |
| `BTRFS_DIR_ITEM_KEY` | 84 | 目录项（文件名 → inode） |
| `BTRFS_DIR_INDEX_KEY` | 96 | 目录项的哈希排序索引 |
| `BTRFS_EXTENT_DATA_KEY` | 108 | **数据 extent**（文件内容在此指向） |
| `BTRFS_EXTENT_CSUM_KEY` | 128 | 整个 extent 的校验和 |
| `BTRFS_ROOT_ITEM_KEY` | 132 | **树根条目**（指向各棵树的根） |

`BTRFS_EXTENT_DATA_KEY` 是理解 btrfs 的关键：**文件内容不进 fs tree，而是存在 data extent 里，fs tree 只存一个指针**。这正是 CoW 快照能零成本的原因 —— 快照只是多一棵 fs tree，data extent 共享。

`BTRFS_INODE_REF_KEY`（硬链接计数）放在 inode 项旁的**固定 offset** 上，而不是散在各处 —— 删一个硬链接只需改一个计数器，效率极高。

`BTRFS_ORPHAN_ITEM_KEY` 的作用在注释里：

```c
/* orphan objectid for tracking unlinked/truncated files */
#define BTRFS_ORPHAN_OBJECTID -5ULL
```

**unlink 只是减引用计数，不立即释放；条目挪到 orphan 树，等事务提交后才真正删** —— 这样崩溃后能恢复，代价是需要处理"提交时发现还有引用"的情况。

## 树深度

```c
#define BTRFS_MAX_LEVEL 8
```

> ⚠️ 单数 `BTRFS_MAX_LEVEL`，值 **8**。旧资料里的 `BTRFS_MAX_LEVELS`（复数）不存在。

注释解释了层次安排：

```c
 * level 0 is always the leaf, and nodes[1...BTRFS_MAX_LEVEL] will point
```

**level 0 是叶子，1..8 是内部节点**。8 层足够支撑极大的文件（索引 4 字节 × 每项，能索引 TB 级）。

`struct btrfs_path` 用数组保存沿途节点：

```c
	struct extent_buffer *nodes[BTRFS_MAX_LEVEL];
	int slots[BTRFS_MAX_LEVEL];
	u8 locks[BTRFS_MAX_LEVEL];
	...
	struct rb_root blocks[BTRFS_MAX_LEVEL];
```

**用数组而非链表** —— 树搜索是热点，数组索引比链表快，且 `locks[]` 让同一路径上的锁有序获取（按 level 顺序）。

## 时间戳：btrfs_timespec

```c
struct btrfs_timespec {
	__le64 tv_sec;
	__le32 tv_nsec;
} __attribute__ ((__packed__));
```

> ⚠️ **旧结构名 `btrfs_timeval` 在 v7.2 不存在**，且字段是 `tv_sec` / `tv_nsec`（不是 `sec` / `nsec`）。

为什么不用内核的 `timespec64`：**纳秒字段是 32 位**（最多约 2.1 秒），秒是 64 位。on-disk 格式省空间，所以定义了自己的类型。四个时间戳（atime/ctime/mtime/otime）都用这个类型。

## 树映射链

从 inode 到磁盘块要走四步：

```
inode → 文件偏移
      → BTRFS_EXTENT_DATA_KEY（fs tree）→ data extent 的引用
      → block group（extent tree）        → 块组内的偏移
      → chunk（chunk tree）               → 哪个设备的哪个物理块
```

对应函数：

- `btrfs_map_blocks()` —— 入口
- `btrfs_lookup_block_group()` —— 查块组
- `btrfs_get_extent()` —— 查 extent

chunk tree 的作用在注释里说得很准：

```c
/*
 * chunk tree stores translations from logical -> physical block numbering
 * the super block points to the chunk tree
 */
#define BTRFS_CHUNK_TREE_OBJECTID 3ULL
```

**chunk tree 就是一张"逻辑块号 → (设备, 物理块号)"的翻译表**。btrfs 把磁盘空间切成固定大小的 chunk（默认 256 MiB），每个 chunk 整体分配给某个设备的某个块组。多 RAID 情况下 chunk 跨设备由条带组成。

## 写时复制

CoW 的核心规则：**任何要修改的块先复制一份，改动写在新块上，原块留给旧快照**。

这带来两条路径的差异：

| | 数据块 | 元数据块 |
| :-- | :-- | :-- |
| 引用者 | 可能有多个文件引用 | 树内共享（节点分裂时） |
| 引用计数 | `refs`（inode ref + data ref） | `refs` + `shared` |
| 全被引用时 | 只能 CoW | 只能 CoW |
| 空间足够时 | 原地写 | **原地写** |

**元数据块空间足够时是原地写的**（不需要 CoW）—— 这是 btrfs 性能的关键。数据块则必须 CoW（否则会改到别人的数据）。

`BTRFS_EXTENT_CSUM_OBJECTID` 的存在让校验和也是 CoW 的一部分。

## 事务

所有修改都在事务里，提交时要么全成功要么全失败。v7.2 的 API：

```c
int btrfs_start_transaction(struct btrfs_fs_info *fs_info);
int btrfs_commit_transaction(struct btrfs_fs_info *fs_info, struct btrfs_trans_handle *trans);
int __btrfs_abort_transaction(struct btrfs_fs_info *fs_info, struct btrfs_trans_handle *trans, bool backup);
```

> ⚠️ **v7.2 全改名**：旧的 `btrfs_trans_start()` / `btrfs_trans_commit()` / `btrfs_trans_abort()` **都不存在**。`abort` 有个 `__btrfs_abort_transaction()`（下划线前缀，内部用）与公开包装的区别，额外参数是 `backup`（是否在 abort 时写一份 tree log 用于恢复）。

**树锁定**（`struct btrfs_tree_lock`）保证并发事务对同一棵树的操作互斥或可并行。`btrfs_start_transaction()` 决定本次事务锁哪些树 —— 读多写少时可以共享锁。

### tree log：单设备快照的基础

`BTRFS_TREE_LOG_OBJECTID` 是 btrfs 的**写前日志**。它让 `fsync` 一个文件时只提交该文件相关的块，而不用提交整个事务。

> ⚠️ **v7.2 重写**：旧的 `btrfs_log_start_commit()` / `btrfs_log_append()` / `btrfs_log_commit()` / `btrfs_log_written()` **全部不存在**，改为单一的 `btrfs_log_inode()`。相关的还有 `tree-mod-log.h`（tree modification log）与 `orphan.h` —— 孤儿处理与 tree log 拆成了独立模块。

## 挂载选项

> ⚠️ **v7.2 用标准 `fs_parameter` API**（`fsparam_flag` / `fsparam_u32` / `fsparam_string` / `fsparam_enum`），**旧的 `FUSE_OPT` 式选项表已不存在**。选项枚举 `Opt_*` 仍在 `fs/btrfs/super.c`（约 45 个，含 `Opt_err` 兜底）。

主要选项（`fs/btrfs/super.c:222-246`）：

| 选项 | 类型 | 说明 |
| :-- | :-- | :-- |
| `commit` | u32 | 提交间隔，**默认 `BTRFS_DEFAULT_COMMIT_INTERVAL`**（30 秒） |
| `compress` | flag / string | 压缩开关 / 算法（同一名两用，见下） |
| `compress-force` | flag / string | **只读不压缩的文件也压** |
| `space_cache` | enum | 空闲空间缓存，**枚举**（v1/v2），不是 flag |
| `ssd` | flag（`_no`） | SSD 模式，**默认随设备 rotating 属性自动** |
| `ssd_spread` | flag | SSD 空间跨块组分散 |
| `thread_pool` | u32 | 工作线程数 |
| `discard` | enum | discard 模式（不是 flag） |
| `datacow` | flag | 禁用 CoW（`nodatacow`） |
| `datasum` | flag | 禁用校验和（`nodatasum`） |
| `defrag` | flag | 碎片整理（`defrag`/`nodefrag`/`nodatacow`） |
| `subvol` / `subvolid` | string / u64 | 挂载哪个子卷 |
| `user_subvol_rm_allowed` | flag | 允许删除用户子卷 |
| `rescan_uuid_tree` | flag | 重扫 uuid 树 |
| `skip_balance` | flag | 挂起时不做 balance |
| `treelog` | flag | 禁用 tree log |
| `recovery` / `rescue` / `usebackuproot` | flag | 恢复模式 |

**`compress` 一个名字两种类型**是这个设计的巧妙处：

```c
	fsparam_flag("compress", Opt_compress),
	fsparam_string("compress", Opt_compress_type),
```

`compress=zlib:7` 走 string 分支设算法与等级；裸 `compress` 走 flag 分支。源码注释解释了互斥逻辑：

```c
	 * context, specifying the "compress" option clears "force-compress"
	 * specifying "compress".
```

### 压缩算法

```c
	ctx->compress_type = BTRFS_COMPRESS_ZLIB;     /* 缺省 zlib */
	ctx->compress_type = BTRFS_COMPRESS_LZO;
	ctx->compress_type = BTRFS_COMPRESS_ZSTD;
	ctx->compress_type = 0;                        /* "no"/"none" → 关闭 */
```

**默认算法是 zlib**（`Opt_compress_type` 的解析入口在 `btrfs_parse_param()`，缺省赋 `BTRFS_COMPRESS_ZLIB`）。接受 `zlib` / `lzo` / `zstd` 三个算法名，都可带 `:level` 后缀；`no` / `none` 显式关闭。

压缩分块大小：

```c
#define BTRFS_COMPRESSION_CHUNK_SIZE	(SZ_512K)
```

**512 KiB** —— 一个叶子的数据量。

⚠️ 注意 `force-compress` 与 `compress` 在读回时区分：

```c
		if (info->force_compress)
			seq_printf(seq, ",compress-force=%s", compress_type);
		else
			seq_printf(seq, ",compress=%s", compress_type);
		if (info->compress_level && info->compress_type != BTRFS_COMPRESS_LZO)
```

**LZO 不支持压缩等级**（LZO 压缩格式本身不带等级参数）—— 读 `/proc/mounts` 或 mountinfo 时会看到 LZO 没有 level 后缀。

## ioctl 接口

`include/uapi/linux/btrfs.h` 的完整 ioctl 清单（按序号）：

| 号 | 宏 | 作用 |
| :-- | :-- | :-- |
| 1 | `SNAP_CREATE` | 建快照（dev → 文件） |
| 2 | `DEFRAG` | 整理文件 |
| 3 | `RESIZE` | 改文件系统大小 |
| 4 | `SCAN_DEV` | 扫描设备 |
| 5 | `FORGET_DEV` | 遗忘设备 |
| 6 / 7 | `TRANS_START` / `TRANS_END` | 事务控制（老接口） |
| 8 | `SYNC` | 同步 |
| 9 | `CLONE` | 创建子卷 |
| 10 / 11 | `ADD_DEV` / `RM_DEV` | 增删设备 |
| 12 | **`BALANCE`** | balance（旧接口） |
| 13 | `CLONE_RANGE` | **克隆文件区间（reflink）** |
| 14 | `SUBVOL_CREATE` | 建子卷 |
| 15 | `SNAP_DESTROY` | 删快照 |
| 16 | `DEFRAG_RANGE` | 整理区间 |
| 17 | `TREE_SEARCH` / `TREE_SEARCH_V2` | **树搜索（读元数据）** |
| 18 | `INO_LOOKUP` | inode 号 → 路径 |
| 19 | `DEFAULT_SUBVOL` | 默认子卷 |
| 20 | **`SPACE_INFO`** | 空间统计（`btrfs fi df`） |
| 22 / 24 | `WAIT_SYNC` / `START_SYNC` | 同步 |
| 23 / 14 | `SNAP_CREATE_V2` / `SUBVOL_CREATE_V2` | 新版子卷创建 |
| 25 / 26 | `SUBVOL_GETFLAGS` / `SUBVOL_SETFLAGS` | **子卷属性（只读/压缩标志）** |
| 27-29 | **`SCRUB` / `SCRUB_CANCEL` / `SCRUB_PROGRESS`** | **校验和检查** |
| 30 | `DEV_INFO` | 设备信息 |
| 31 | `FS_INFO` | 文件系统信息 |
| 32-34 | **`BALANCE_V2` / `BALANCE_CTL` / `BALANCE_PROGRESS`** | **balance 新接口** |
| 35 | `INO_PATHS` | inode → 多条路径（硬链接） |
| 36 | `LOGICAL_INO` | **逻辑 inode → 物理 inode**（virtual 特性） |
| 37 / 38 | `SET_RECEIVED_SUBVOL` / `SEND` | 子卷收发 |
| 39 | `DEVICES_READY` | 设备就绪查询 |
| 40-46 | `QUOTA_CTL` / `QGROUP_*` / `QUOTA_RESCAN*` | **quota 管理** |
| — | `GET_FSLABEL` / `SET_FSLABEL` | 卷标（复用 `FS_IOC_*`） |
| 52 | `GET_DEV_STATS` | 设备统计 |

> ⚠️ **`BTRFS_IOC_DEDUPE` 不存在** —— 去重没有独立 ioctl，靠 `CLONE_RANGE`（reflink）实现。而 **`BTRFS_IOC_INCOMPAT_RESIZE` / `_SUBVOL_GET_LIST` / `_SET_SUBVOL_ROOTREF` / `_SEND_RECEIVE_SUBVOL` / `_IBCNEG` 都不存在**。balance 走 `BALANCE_V2` + `BALANCE_CTL` + `BALANCE_PROGRESS` 三件套（旧 `BALANCE` 保留但已过时）。

`BTRFS_IOC_LOGICAL_INO` 对应 btrfs 的 **virtual inode** 特性 —— 逻辑 inode 号与物理 inode 分离，所以 `BTRFS_LOOKUP` 之类操作不暴露物理位置（子卷复制 / 重定位后 inode 号会变，但对用户保持稳定）。

## sysfs 接口

```
/sys/fs/btrfs/<devid>/
├── devices/                # 多设备时列出各设备
├── global_ro/              # 只读属性
│   ├── free_space          # 空闲空间（字节）
│   ├── total_bytes
│   ├── used_bytes
│   ├── default_subvolumeid
│   ├── fsid
│   ├── label
│   ├── csum_type
│   ├── metadata_profile
│   └── ...
├── global_rw/              # 可写属性
│   ├── free_space
│   ├── reserve_metadata_level
│   ├── space_cache_commit_interval
│   ├── balance_start / balance_pause / balance_cancel / balance_progress
│   ├── defrag_start / defrag_pause / defrag_cancel / defrag_progress
│   └── ...
└── properties/             # 每挂载点的属性
    ├── ro
    └── rw
```

`global_ro/global_rw` 对应 uapi 里的 `BTRFS_IOC_SPACE_INFO` / `BTRFS_IOC_FS_INFO` / `BTRFS_IOC_GET_FSLABEL` 等；balance 与 defrag 的 start/pause/cancel/progress 四件套对应 `BTRFS_IOC_BALANCE_CTL`。

排查文件系统健康用：

```shell
# 空间统计
btrfs fi df /mnt/btrfs          # 或 df
btrfs fi show /mnt/btrfs        # 设备详情（含 devid）
btrfs fi usage /mnt/btrfs       # 每条路径的分配

# 设备详情
btrfs device show /mnt/btrfs
btrfs device stats /mnt/btrfs   # 错误计数（write_io_errs / read_io_errs / flush_io_errs）

# 子卷
btrfs subvolume list /mnt/btrfs
btrfs subvolume get-default /mnt/btrfs
btrfs subvolume show /mnt/btrfs/subvol

# 校验和检查（read-only 只读数据，safe 模式）
btrfs scrub start -Bd /mnt/btrfs
btrfs scrub status /mnt/btrfs

# balance 状态
cat /sys/fs/btrfs/<devid>/global_rw/balance_progress
cat /sys/fs/btrfs/<devid>/global_rw/space_cache_commit_interval
```

## 与其它子系统的接缝

- **块层**：chunk 是块层的分配单位（默认 256 MiB），多设备映射依赖 device mapper 或原生多路径，见 [dev/char.md](/docs/CS/OS/Linux/dev/char.md) 的块设备部分与 [dev/block.md](/docs/CS/OS/Linux/dev/block.md)。
- **VFS**：CoW 语义对 `stat` / `fallocate` / `copy_file_range` 有特殊语义（reflink），见 [fs/fs.md](/docs/CS/OS/Linux/fs/fs.md)。
- **jbd2**：ext4 的日志设计与之对照，见 [jbd2](/docs/CS/OS/Linux/fs/jbd2.md)。
- **XFS**：另一种 CoW 设计（元数据日志 vs CoW），见 [xfs.md](/docs/CS/OS/Linux/fs/xfs.md)。
- **overlayfs**：容器镜像的存储层常用 btrfs 子卷，见 [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md)。
- **dev/bus**：`fs verity`（`verity.o`）复用块层校验机制，见 [dev/bus.md](/docs/CS/OS/Linux/dev/bus.md)。

## References

1. [Linux Kernel Documentation — btrfs](https://docs.kernel.org/filesystems/btrfs.html)
2. [btrfs wiki](https://btrfs.readthedocs.io/en/latest/)
3. [btrfs-progs man pages](https://btrfs.readthedocs.io/en/latest/man/index.html)
