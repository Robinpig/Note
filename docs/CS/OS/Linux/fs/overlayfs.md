## Introduction

Overlayfs 是一个**联合挂载（union mount）**文件系统：它自己不存数据，而是把多个已有目录按优先级叠成一棵树，对外呈现为一个目录。上层可见、下层被遮挡；读时自上而下找第一个命中，写时落到最上层。

它的价值在于把"只读的基底"和"可写的增量"解耦。容器镜像正是这个模型：镜像由若干只读层叠成 `lowerdir`，容器运行时的修改写进唯一的 `upperdir`，容器看到的是二者合并后的 `merged`。删除一个容器只需删掉 `upperdir`——镜像层一个字节都没动。这也是为什么 `docker build` 能复用层、为什么多个容器能共享同一份镜像。

本文讲 overlayfs 自身的机制。VFS 层如何挂载与查找路径见 [文件管理机制](/docs/CS/OS/Linux/fs/README.md) 与 [VFS 详解](/docs/CS/OS/Linux/fs/fs.md)，底层文件系统的磁盘格式见 [ext4](/docs/CS/OS/Linux/fs/ext4.md)——overlayfs 不关心 lower/upper 各自是什么文件系统，只要它们支持它需要的那几个原语。

## Three-Directory Model

一次典型挂载有四个路径：

```shell
mount -t overlay overlay \
  -o lowerdir=/lower1:/lower2:/lower3,upperdir=/upper,workdir=/work \
  /merged
```

| 路径 | 角色 | 能否为空 |
| --- | --- | --- |
| `lowerdir` | 只读层，可多层，用 `:` 分隔，**从左到右优先级递减** | 可以（纯 upper 挂载） |
| `upperdir` | 唯一的可写层，所有修改落在这里 | 可以（只读挂载） |
| `workdir` | 与 upper 同文件系统的**临时工作区**，对用户不可见 | 必须（有 upper 时） |
| `merged` | 挂载点，对外呈现的合并视图 | — |

`workdir` 是最容易让人困惑的一个。它不是给用户用的，而是给 overlayfs 做**原子操作**用的：copy-up 时先在 workdir 里建好临时文件、填完数据和元数据，再 `rename()` 到 upper 的真实位置——rename 在同文件系统内是原子的，于是"文件出现在 upper"这件事要么完整发生、要么完全不发生。这要求 workdir 与 upperdir **必须在同一个文件系统上**，否则 rename 会退化成跨设备复制。

层数上限由 `OVL_MAX_STACK` 给出：

```c
#define OVL_MAX_STACK 500
```

（`fs/overlayfs/params.h`，超过则 `pr_err("too many lower directories, limit is %d")`。）

## Data Structures

### ovl_fs and Layers

超级块私有数据 `ovl_fs` 持有全部层：

```c
struct ovl_fs {
	unsigned int numlayer;
	/* Number of unique fs among layers including upper fs */
	unsigned int numfs;
	/* Number of data-only lower layers */
	unsigned int numdatalayer;
	struct ovl_layer *layers;
	struct ovl_sb *fs;
	/* workbasedir is the path at workdir= mount option */
	struct dentry *workbasedir;
	/* workdir is the 'work' or 'index' directory under workbasedir */
	struct dentry *workdir;
	/* -1: disabled, 0: same fs, 1..32: number of unused ino bits */
	int xino_mode;
	/* For allocation of non-persistent inode numbers */
	atomic_long_t last_ino;
	/* Shared whiteout cache */
	struct dentry *whiteout;
	struct ovl_config config;
	/* ... */
};
```

注意 `numlayer` 把 upper 也算进去了——**upper 是 `layers[0]`**，索引即优先级：

```c
static inline struct vfsmount *ovl_upper_mnt(struct ovl_fs *ofs)
{
	return ofs->layers[0].mnt;
}
```

每层用 `ovl_layer` 描述，其中 `idx` 是层号、`fsid` 是按底层超级块分配的编号（upper 恒为 0），后者用于合成 inode 号：

```c
struct ovl_layer {
	/* ovl_free_fs() relies on @mnt being the first member! */
	struct vfsmount *mnt;
	/* Trap in ovl inode cache */
	struct inode *trap;
	struct ovl_sb *fs;
	/* Index of this layer in fs root (upper idx == 0) */
	int idx;
	/* One fsid per unique underlying sb (upper fsid == 0) */
	int fsid;
	/* xwhiteouts were found on this layer */
	bool has_xwhiteouts;
};
```

`trap` 字段防的是"层互相嵌套"：如果 upper 目录本身位于某个 lower 层之下，查找会无限递归，所以每层记一个陷阱 inode，遇到就返回 `-ELOOP`。

### ovl_entry: One dentry Maps to One Path Stack

这是 overlayfs 最核心的结构——合并视图里的一个 dentry，在内存里对应**一组**真实路径：

```c
struct ovl_path {
	const struct ovl_layer *layer;
	struct dentry *dentry;
};

struct ovl_entry {
	unsigned int __numlower;
	struct ovl_path __lowerstack[];
};
```

`__lowerstack` 是柔性数组，按优先级存放各 lower 层里找到的 dentry。upper 路径单独存在 inode 里（见下）。所以"合并"在内存里的表示就是：**0 或 1 个 upper 路径 + 0 到 N 个 lower 路径**。

### ovl_inode

```c
struct ovl_inode {
	union {
		struct ovl_dir_cache *cache;	/* directory */
		const char *lowerdata_redirect;	/* regular file */
	};
	const char *redirect;
	u64 version;
	unsigned long flags;
	struct inode vfs_inode;
	struct dentry *__upperdentry;
	struct ovl_entry *oe;

	/* synchronize copy up and more */
	struct mutex lock;
};
```

`__upperdentry` 是 upper 层里的对应项，**它的有无就是"这个文件是否已 copy-up"的判据**。`version` 用于失效目录读缓存，`lock` 串行化同一个 inode 上的 copy-up。

### State Encoding: xattr

overlayfs 需要把"这个文件来自哪个 lower 文件""这个目录是否已合并过"之类的元信息持久化，而它不能改底层文件系统的格式，于是全部塞进 **xattr**，命名空间是 `trusted.overlay.*`（无特权挂载时降级到 `user.overlay.*`）：

```c
#define OVL_XATTR_NAMESPACE "overlay."
#define OVL_XATTR_TRUSTED_PREFIX XATTR_TRUSTED_PREFIX OVL_XATTR_NAMESPACE
#define OVL_XATTR_USER_PREFIX XATTR_USER_PREFIX OVL_XATTR_NAMESPACE

enum ovl_xattr {
	OVL_XATTR_OPAQUE,
	OVL_XATTR_REDIRECT,
	OVL_XATTR_ORIGIN,
	OVL_XATTR_IMPURE,
	OVL_XATTR_NLINK,
	OVL_XATTR_UPPER,
	OVL_XATTR_UUID,
	OVL_XATTR_METACOPY,
	OVL_XATTR_PROTATTR,
	OVL_XATTR_XWHITEOUT,
};
```

几个关键的：

- **`overlay.origin`** —— 存 lower 文件的**文件句柄**（file handle）。文件已 copy-up 到 upper，但我们仍需知道它"原本是谁"，否则 `st_ino` 会在 copy-up 前后变化，很多程序会出问题。
- **`overlay.opaque`** —— 目录标记，值为 `y` 表示"不要与下层合并"，`x` 表示这是个 xwhiteout 目录。
- **`overlay.redirect`** —— 记录 lower 文件被重命名后的新路径。
- **`overlay.metacopy`** —— 标记"只复制了元数据，数据还在 lower"。
- **`overlay.impure`** —— 标记"这个 upper 目录里现在混进了来自 lower 的项"，因为合并过的目录不能再被当成纯 upper 目录处理。

## Lookup: How the Path Stack Is Assembled

核心是 `ovl_lookup()`（`fs/overlayfs/namei.c`）。它先查 upper，再自顶向下遍历各 lower 层，把命中项填进 `ovl_entry`。

### Four Results of Single-Layer Lookup

`ovl_lookup_single()` 对某一层做一次查找，结果分四种：

```c
	path.dentry = this;
	path.mnt = d->layer->mnt;
	if (ovl_path_is_whiteout(ofs, &path)) {
		d->stop = d->opaque = true;
		goto put_and_out;
	}
```

**① 是 whiteout** —— 立即停止向下查找，且标记 opaque。这就是"删除下层文件"在查找侧的体现：上层有个 whiteout 挡着，下层同名文件就当不存在。

```c
	if (!d_can_lookup(this)) {
		if (d->is_dir || !last_element) {
			d->stop = true;
			goto put_and_out;
		}
		err = ovl_check_metacopy_xattr(ofs, &path, NULL);
		...
		d->metacopy = err;
		d->stop = !d->metacopy;
```

**② 是普通文件** —— 若路径还有后续分量（说明上层把它当目录），停止；否则停止向下（普通文件不合并）。

```c
		/* overlay.opaque=x means xwhiteouts directory */
		val = ovl_get_opaquedir_val(ofs, &path);
		if (last_element && !is_upper && val == 'x') {
			d->xwhiteouts = true;
			ovl_layer_set_xwhiteouts(ofs, d->layer);
		} else if (val == 'y') {
			d->stop = true;
			if (last_element)
				d->opaque = true;
			goto out;
		}
```

**③ 是 opaque 目录** —— 停止向下，不再与更低层合并。

**④ 是普通目录** —— 继续向下一层，把结果入栈。

### Main Loop

```c
	for (i = 0; !d.stop && i < ovl_numlower(poe); i++) {
		struct ovl_path lower = ovl_lowerstack(poe)[i];
		...
		d.layer = lower.layer;
		err = ovl_lookup_layer(lower.dentry, &d, &this, false);
		...
		stack[ctr].dentry = this;
		stack[ctr].layer = lower.layer;
		ctr++;
		...
	}
```

循环条件 `!d.stop` 是 whiteout/opaque 的截断机制，其余情况下逐层收集。注意**目录会一直查到底**（为了后续读目录时能合并），而普通文件通常在第一层命中后就 `stop`。

### redirect Security Implications

lower 层的文件被 rename 后，仅靠路径查找会找不到它，所以 overlayfs 用 `overlay.redirect` xattr 记录新位置。但跟随 redirect 有安全后果，源码注释说得很直白：

```c
		/*
		 * Following redirects can have security consequences: it's like
		 * a symlink into the lower layer without the permission checks.
		 * This is only a problem if the upper layer is untrusted (e.g
		 * comes from an USB drive).  This can allow a non-readable file
		 * or directory to become readable.
		 *
		 * Only following redirects when redirects are enabled disables
		 * this attack vector when not necessary.
		 */
		err = -EPERM;
		if (d.redirect && !ovl_redirect_follow(ofs)) {
			pr_warn_ratelimited("refusing to follow redirect for (%pd2)\n", dentry);
			goto out_put;
		}
```

**redirect 相当于一条不受权限检查的符号链接**。所以默认不为不信任的 upper（如 U 盘）跟随。

## Deletion: whiteout and opaque

删除一个**只存在于 lower 层**的文件，不能真的去改 lower（它是只读的镜像层），于是在 upper 里放一个"墓碑"：

> A whiteout is created as a character device with 0/0 device number or as a zero-size regular file with the xattr "trusted.overlay.whiteout".

两种形态对应两类底层文件系统：能建字符设备的用 **0/0 字符设备**（`vfs_whiteout()`，overlayfs 侧包装为 `ovl_do_whiteout()`）；不能建的（如某些网络/用户态文件系统）退化为**带 `trusted.overlay.whiteout` xattr 的零长普通文件**，即 xwhiteout。

创建流程在 `ovl_whiteout()`：先在 workdir 里建好（必要时 `link` 复用一个共享的 whiteout inode 以省 inode，链接数耗尽时自动禁用该优化），再 `rename()` 到 upper 的目标位置：

```c
	whiteout = ovl_whiteout(ofs);
	err = PTR_ERR(whiteout);
	if (IS_ERR(whiteout))
		return err;

	if (d_is_dir(dentry))
		flags = RENAME_EXCHANGE;

	err = ovl_do_rename(ofs, wdir, whiteout, dir, dentry, flags);
```

删目录用 `RENAME_EXCHANGE`——把 whiteout 换进去，一次原子操作。

**opaque** 解决的是另一种情形：删除一个**目录**后重建同名目录。此时若继续与下层的同名目录合并，旧内容会"复活"。所以新建的 upper 目录会被标上 `overlay.opaque=y`，查找时 `stop = true`，彻底屏蔽下层。

## Copy-on-Write: copy-up

### When Triggered

任何对 lower 文件的**写**操作都会触发 copy-up。判定在 `ovl_open_need_copy_up()`——只读打开不需要，特殊文件（`special_file()`）不需要：

```c
static bool ovl_open_need_copy_up(struct dentry *dentry, int flags)
{
	/* Copy up of disconnected dentry does not set upper alias */
	if (ovl_already_copied_up(dentry, flags))
		return false;

	if (special_file(d_inode(dentry)->i_mode))
		return false;

	if (!ovl_open_flags_need_copy_up(flags))
		return false;

	return true;
}
```

容器场景里最典型的代价来源：镜像里一个 500MB 的文件，容器里只改一个字节，也要整个复制上来。

### Bottom-Up: Copy All Uncopied Ancestors First

要复制 `/a/b/c`，必须保证 `/a`、`/a/b` 已经在 upper 里存在。`ovl_copy_up_flags()` 用一个循环处理——**自顶向下找到第一个尚未 copy-up 的祖先，然后自底向上逐级复制**：

```c
	while (!err) {
		if (ovl_already_copied_up(dentry, flags))
			break;

		next = dget(dentry);
		/* find the topmost dentry not yet copied up */
		for (; !disconnected;) {
			parent = dget_parent(next);

			if (ovl_dentry_upper(parent))
				break;

			dput(next);
			next = parent;
		}

		err = ovl_copy_up_one(parent, next, flags);

		dput(parent);
		dput(next);
	}
```

外层 `while` 保证一轮之后若目标仍未完成（父目录刚被复制，需要重来）就继续。

### workdir and Atomic Placement

`ovl_copy_up_workdir()` 是真正的复制动作：

```c
	ovl_start_write(c->dentry);
	inode_lock(wdir);
	temp = ovl_create_temp(ofs, c->workdir, &cattr);
	inode_unlock(wdir);
	ovl_end_write(c->dentry);
	ovl_revert_cu_creds(&cc);
	...
	/*
	 * Copy up data first and then xattrs. Writing data after
	 * xattrs will remove security.capability xattr automatically.
	 */
	path.dentry = temp;
	err = ovl_copy_up_data(c, &path);
```

顺序有个讲究：**先写数据、再写 xattr**。反过来的话，写数据会把 `security.capability` 这类 xattr 清掉。

落位用 rename：

```c
	ovl_start_write(c->dentry);
	trap = lock_rename(c->workdir, c->destdir);
	if (trap || temp->d_parent != c->workdir) {
		/* temp or workdir moved underneath us? abort without cleanup */
		dput(temp);
		err = -EIO;
		...
	} else if (err) {
		goto cleanup;
	}

	err = ovl_copy_up_metadata(c, temp);
	...
	err = ovl_do_rename(ofs, wdir, temp, udir, upper, 0);
```

`lock_rename()` 同时锁住 workdir 与目标目录，防止二者被并发移动；`temp->d_parent != c->workdir` 是一次"我手里的临时文件还在原地吗"的复核。

### metacopy: Copy Only Metadata

完整复制大文件很贵，而很多操作（`chmod`、`chown`、`touch`）只改元数据。`metacopy` 特性允许只把 inode 元数据复制上来，数据块继续留在 lower，靠 `overlay.metacopy` xattr 标记，真正写数据时再补复制：

```c
	ctx.metacopy = ovl_need_meta_copy_up(dentry, ctx.stat.mode, flags);
	...
	if (!err && ovl_dentry_needs_data_copy_up_locked(dentry, flags))
		err = ovl_copy_up_meta_inode_data(&ctx);
```

代价是后续每次打开都多一次判断，且数据仍在 lower——**lower 层因此不能被修改或删除**，这正是容器镜像层必须只读的原因之一。

另有一个细节：关闭 metacopy 时，为保证在元数据顺序不严格的文件系统（注释点名 ubifs）上也有原子语义，会对常规文件与目录在最终元数据复制后 fsync：

```c
	ctx.metadata_fsync = !OVL_FS(dentry->d_sb)->config.metacopy &&
			     (S_ISREG(ctx.stat.mode) || S_ISDIR(ctx.stat.mode));
```

## Merged Directory Read

读目录要跨层去重。`ovl_dir_read_merged()` 自顶向下遍历各层，用红黑树保证同名项只保留第一次出现（即最高优先级）的那个：

```c
	for (idx = 0; idx != -1; idx = next) {
		next = ovl_path_next(idx, dentry, &realpath, &layer);
		rdd.is_upper = ovl_dentry_upper(dentry) == realpath.dentry;
		rdd.in_xwhiteouts_dir = layer->has_xwhiteouts &&
					ovl_dentry_has_xwhiteouts(dentry);

		if (next != -1) {
			err = ovl_dir_read(&realpath, &rdd);
			if (err)
				break;
		} else {
			/*
			 * Insert lowest layer entries before upper ones, this
			 * allows offsets to be reasonably constant
			 */
			list_add(&rdd.middle, rdd.list);
			rdd.is_lowest = true;
			err = ovl_dir_read(&realpath, &rdd);
			list_del(&rdd.middle);
		}
	}
```

最后一层用一个"中间锚点"技巧：把最底层的项插到链表中间而非尾部，这样目录项的偏移在多次读之间相对稳定——`getdents` 的 `d_off` 语义需要它。

结果缓存在 `ovl_inode` 的 `cache` 里，靠 `version` 字段判断是否需要重建。

## inode Number and st_dev: xino

一个 overlay 文件在不同时刻可能对应不同底层 inode（copy-up 前后更是如此）。若直接暴露底层 inode 号，`st_ino` 会变、且跨层可能撞号。xino 的做法是**用 inode 号的高位编码 fsid**：

```c
	if (samefs) {
		/*
		 * When all layers are on the same fs, all real inode
		 * number are unique, so we use the overlay st_dev,
		 * which is friendly to du -x.
		 */
		stat->dev = dentry->d_sb->s_dev;
		return;
	} else if (xinobits) {
		/*
		 * All inode numbers of underlying fs should not be using the
		 * high xinobits, so we use high xinobits to partition the
		 * overlay st_ino address space. The high bits holds the fsid
		 * (upper fsid is 0). The lowest xinobit is reserved for mapping
		 * the non-persistent inode numbers range in case of overflow.
		 * This way all overlay inode numbers are unique and use the
		 * overlay st_dev.
		 */
		if (likely(!(stat->ino >> xinoshift))) {
			stat->ino |= ((u64)fsid) << (xinoshift + 1);
```

三种情形：**所有层在同一文件系统** —— 直接用 overlay 自己的 `st_dev`，底层 inode 号天然唯一（这对 `du -x` 友好）；**启用 xino** —— 高位塞 fsid；**都不行** —— 退化为非持久的动态编号（`last_ino`），此时 `st_ino` 不保证跨挂载稳定。

这也解释了 overlayfs 的一个经典限制：底层 inode 号若真的用到了高位，会溢出到 fsid 区域，此时该文件退回非 xino 行为。

## Mount Options Quick Reference

按"你要解决什么问题"归类：

| 类别 | 选项 | 说明 |
| --- | --- | --- |
| 层 | `lowerdir=` `upperdir=` `workdir=` | 用 `:` 分隔多个 lower，优先级从左到右递减 |
| inode 稳定 | `xino=off\|auto\|on` | 用高位 fsid 合成唯一 inode 号 |
| 复制策略 | `metacopy=off\|on` | 只复制元数据，延迟数据复制 |
| 一致性 | `index=off\|on` | 为 copy-up 建立索引，保证硬链接与 `st_ino` 稳定 |
| 重命名 | `redirect_dir=off\|follow\|nofollow\|on` | 是否允许 lower 目录重命名与跟随 redirect |
| 权限 | `userxattr` | 无特权挂载时改用 `user.overlay.*` |
| 校验 | `verity=off\|on\|require` | fsverity 摘要校验 |

## Boundaries with Adjacent Subsystems

- **容器与镜像**：容器运行时的 snapshotter 直接把镜像各层设为 `lowerdir`、容器可写层设为 `upperdir`。镜像层必须只读，否则 metacopy 与共享会失效。见 [containerd](/docs/CS/Container/k8s/containerd.md) 与 [Docker](/docs/CS/Container/Docker/Docker.md)。
- **mount namespace**：容器看到的 `merged` 是在独立 [namespace](/docs/CS/OS/Linux/namespace.md) 里挂载的，主机上同一份 upper/lower 可以有完全不同的挂载视图。
- **VFS**：overlayfs 实现的是标准 `super_operations`/`inode_operations`/`dir_operations`，VFS 不感知"合并"这件事——合并完全发生在 overlayfs 的 `ovl_lookup()` 与目录读回调里。
- **PageCache**：合并视图里的文件最终仍由底层文件系统的 `address_space` 提供页缓存，overlayfs 只做 dentry/inode 层的映射；copy-up 后读写切换到 upper 的 inode，缓存随之切换。
- **底层文件系统**：需要支持 xattr（`trusted.overlay.*`）、文件句柄（`exportfs`，用于 origin/index）与 `rename`；不支持其中某些能力时会相应降级（如 xwhiteout、xino=off）。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)

## References

- [Linux 6.12 源码：fs/overlayfs/ovl_entry.h](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/overlayfs/ovl_entry.h?h=v6.12)
- [Linux 6.12 源码：fs/overlayfs/copy_up.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/overlayfs/copy_up.c?h=v6.12)
- [Linux 6.12 源码：fs/overlayfs/namei.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/overlayfs/namei.c?h=v6.12)
- [内核文档：Documentation/filesystems/overlayfs.rst](https://www.kernel.org/doc/html/latest/filesystems/overlayfs.html)
