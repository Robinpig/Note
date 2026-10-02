## Introduction

一个文件系统的一次逻辑修改，往往要动多处磁盘结构：在目录里加一项要改目录块、改 inode 位图、改 inode 表、改块位图、改组描述符、改超级块。这些写入不是原子的——断电可能停在中间任何一步，留下"位图说块已分配但没人指向它"或"目录项指向一个还被别人占用的 inode"这类结构性损坏。**日志（journaling）** 的作用不是阻止崩溃，而是让崩溃后的修复变成一次确定性的重放：先把这次修改的**元数据**按事务写到一个专门的环形区域（日志），落盘后再写回真实位置；崩溃后只需扫描日志，把已提交事务重放一遍即可。

JBD2（journaling block device, v2）是 Linux 的通用日志层，源自 ext3、现被 ext4 与 ocfs2 使用。它是**块设备层**的日志：只认块号与 `buffer_head`，不理解 inode 或目录语义，因此与具体文件系统解耦；文件系统负责声明"我要改哪些块"，JBD2 负责原子提交与恢复。本文讲 JBD2 自身的机制——[ext4.md](/docs/CS/OS/Linux/fs/ext4.md) 从文件系统视角讲的挂载模式与特性，这里不再重复。

## 一致性不是免费的：三种 data 模式

日志只保证**元数据**的结构一致。用户数据是否进日志是可配的，三种模式的差别全在数据块与元数据日志的相对顺序：

| 模式 | 数据是否进日志 | 提交前对数据的要求 | 崩溃后可能看到 |
| --- | --- | --- | --- |
| `data=journal` | 是（数据写两遍） | 与元数据同事务 | 最一致，代价最高 |
| `data=ordered`（默认） | 否 | **必须先于**元数据提交落盘 | 不会读到垃圾；只有未 fsync 的近期数据会丢 |
| `data=writeback` | 否 | 无顺序要求 | 可能读到**旧**块内容（属于别人的数据） |

`data=ordered` 的默认地位来自一个权衡：它避免了 writeback 模式的**安全性**问题（元数据先落盘、指向尚未写入的新块，于是文件里出现上一次使用该块的残留内容——这是真实的越权泄露风险），又不必像 journal 模式那样把每个数据块写两遍。它的实现靠 commit 阶段的一个强制 flush，见后文 "阶段二 T_FLUSH"。

## 磁盘布局

### 日志超级块

日志区第一个块是 `journal_superblock_s`（`include/linux/jbd2.h`），全部字段**大端**：

```c
typedef struct journal_superblock_s
{
	journal_header_t s_header;
	/* Static information describing the journal */
	__be32	s_blocksize;		/* journal device blocksize */
	__be32	s_maxlen;		/* total blocks in journal file */
	__be32	s_first;		/* first block of log information */
	/* Dynamic information describing the current state of the log */
	__be32	s_sequence;		/* first commit ID expected in log */
	__be32	s_start;		/* blocknr of start of log */
	__be32	s_errno;
	/* Remaining fields are only valid in a version-2 superblock */
	__be32	s_feature_compat;
	__be32	s_feature_incompat;
	__be32	s_feature_ro_compat;
	__u8	s_uuid[16];
	__be32	s_nr_users;		/* Nr of filesystems sharing log */
	__be32	s_dynsuper;		/* Blocknr of dynamic superblock copy*/
	__be32	s_max_transaction;	/* Limit of journal blocks per trans.*/
	__be32	s_max_trans_data;	/* Limit of data blocks per trans. */
	__u8	s_checksum_type;
	__u8	s_padding2[3];
	__be32	s_num_fc_blks;		/* Number of fast commit blocks */
	__be32	s_head;			/* blocknr of head of log, only uptodate
					 * while the filesystem is clean */
	__u32	s_padding[40];
	__be32	s_checksum;		/* crc32c(superblock) */
	__u8	s_users[16*48];		/* ids of all fs'es sharing the log */
} journal_superblock_t;
```

`s_start` 是整个恢复逻辑的开关：**它为零当且仅当日志是干净卸载的**。挂载时看到 `s_start == 0` 就直接跳过恢复，这也是 `jbd2_journal_recover()` 里的第一条快路径判断。

### 五种描述符块

日志区里只有五类块，开头都带 `journal_header_t`，靠 `h_blocktype` 区分：

```c
typedef struct journal_header_s
{
	__be32		h_magic;
	__be32		h_blocktype;
	__be32		h_sequence;
} journal_header_t;

#define JBD2_DESCRIPTOR_BLOCK	1
#define JBD2_COMMIT_BLOCK	2
#define JBD2_SUPERBLOCK_V1	3
#define JBD2_SUPERBLOCK_V2	4
#define JBD2_REVOKE_BLOCK	5
```

一次事务在日志里的排布是：**描述符块**（后面跟一串 tag，每个 tag 指向一个元数据块在日志中的位置）+ 若干**元数据块** + **revoke 块**（可选）+ **commit 块**。恢复时就是按这个顺序读。

tag 有两种形态，取决于是否启用 64 位块号：

```c
typedef struct journal_block_tag_s
{
	__be32		t_blocknr;	/* The on-disk block number */
	__be16		t_checksum;	/* truncated crc32c(uuid+seq+block) */
	__be16		t_flags;	/* See below */
	__be32		t_blocknr_high; /* most-significant high 32bits. */
} journal_block_tag_t;

/* Definitions for the journal tag flags word: */
#define JBD2_FLAG_ESCAPE		1	/* on-disk block is escaped */
#define JBD2_FLAG_SAME_UUID	2	/* block has same uuid as previous */
#define JBD2_FLAG_DELETED	4	/* block deleted by this transaction */
#define JBD2_FLAG_LAST_TAG	8	/* last tag in this descriptor block */
```

源码注释特意提醒：**不要直接用 `sizeof(journal_block_tag_t)` 做指针运算**，而要用 `journal_tag_bytes(journal)`——`t_blocknr_high` 只在 `INCOMPAT_64BIT` 时才有意义，v1 与 v3 的长度也不同。

`JBD2_FLAG_ESCAPE` 对应一个容易忽略的坑：如果某个元数据块的**前四个字节恰好等于 JBD2_MAGIC_NUMBER（`0xc03b3998`）**，恢复扫描会把它误认成描述符块头。`jbd2_journal_write_metadata_buffer()` 检测到这个就把首 4 字节清零再写（`jbd2_data_do_escape()`），并在 tag 上打 ESCAPE 标记，读回时还原。

### commit 块与校验和的演进

```c
struct commit_header {
	__be32		h_magic;
	__be32          h_blocktype;
	__be32          h_sequence;
	unsigned char   h_chksum_type;
	unsigned char   h_chksum_size;
	unsigned char 	h_padding[2];
	__be32 		h_chksum[JBD2_CHECKSUM_BYTES];
	__be64		h_commit_sec;
	__be32		h_commit_nsec;
};
```

校验和有三代，互斥：`CHECKSUM`（v1，整块算一个和放在 commit 块）、`CSUM_V2`（每个元数据块自带 crc32c，commit 块存 `crc32c(uuid+commit_block)`）、`CSUM_V3`（tag 用 32 位完整校验和）。内核能识别的范围由 `JBD2_KNOWN_INCOMPAT_FEATURES` 列出，未知的不兼容位会拒绝挂载。

### 日志是环形缓冲区

日志区大小固定（ext4 默认按文件系统大小算，上限 102400 块），写满就绕回开头复用。三个指针维护它：`j_head`（下一个可写的块）、`j_tail`（最老的、还不能覆盖的块）、`j_free`。**`j_tail` 只能由 checkpoint 推进**——这就是 checkpoint 存在的全部理由：把已提交事务的元数据真正写回原位，然后宣布"这些日志块可以覆盖了"。

## 内存数据结构

### journal_t：三态事务与环形指针

```c
struct journal_s
{
	unsigned long		j_flags;
	/**
	 * @j_running_transaction:
	 * Transactions: The current running transaction...
	 */
	transaction_t		*j_running_transaction;
	/**
	 * @j_committing_transaction: the transaction we are pushing to disk
	 */
	transaction_t		*j_committing_transaction;
	/**
	 * @j_checkpoint_transactions:
	 * ... and a linked circular list of all transactions waiting for
	 * checkpointing. [j_list_lock]
	 */
	transaction_t		*j_checkpoint_transactions;
	/**
	 * @j_head: Journal head: identifies the first unused block in the journal.
	 */
	unsigned long		j_head;
	/**
	 * @j_tail: Journal tail: identifies the oldest still-used block in the journal.
	 */
	unsigned long		j_tail;
	/**
	 * @j_free: Journal free: how many free blocks are there in the journal?
	 */
	unsigned long		j_free;
	/* ... */
};
```

一个事务在生命周期里依次经过三个位置：**running**（接受新 handle）→ **committing**（正在写日志）→ **checkpoint**（已提交，元数据待回原位）。同一时刻 running 与 committing 各至多一个，checkpoint 是一个链表。三个指针各自有不同的锁（`j_state_lock` / `j_list_lock`），这是 JBD2 能高并发的根本。

### handle_t：以额度为单位

文件系统的一次逻辑操作持有一个 handle：

```c
struct jbd2_journal_handle
{
	union {
		transaction_t	*h_transaction;
		/* Which journal handle belongs to - used iff h_reserved set */
		journal_t	*h_journal;
	};
	handle_t		*h_rsv_handle;
	int			h_total_credits;
	int			h_revoke_credits;
	int			h_ref;
	int			h_err;
	unsigned int	h_sync:		1;	/* Flag for sync-on-close */
	unsigned int	h_aborted:	1;
	/* ... */
};
```

`h_total_credits` 是**预算**——调用方在 `jbd2_journal_start()` 时必须声明"我最多会弄脏多少块"。这是为了避免日志在提交中途耗尽空间：既然日志是环形且大小已知，就必须事先记账。估少了会被强制重启事务（`jbd2_journal_restart()`），估多了浪费并发度。

### transaction_t：九个状态与五个链表

```c
	enum {
		T_RUNNING,
		T_LOCKED,
		T_SWITCH,
		T_FLUSH,
		T_COMMIT,
		T_COMMIT_DFLUSH,
		T_COMMIT_JFLUSH,
		T_COMMIT_CALLBACK,
		T_FINISHED
	}			t_state;
```

状态迁移严格单向，由 kjournald2 推进，源码注释注明"只有 kjournald2 改它"。这九个状态不是装饰——每个状态都对应"此时允许谁碰哪些链表"，比如 `T_LOCKED` 阶段还在等 `t_updates` 归零，而 `T_SWITCH` 是唯一不允许 reserved handle 加入的窗口。

缓冲区按用途分挂在五个链表上：

| 链表 | 含义 |
| --- | --- |
| `t_reserved_list` | 已声明要改、但还没真正弄脏 |
| `t_buffers` | 本事务拥有的元数据缓冲区（commit 时写日志） |
| `t_forget` | 已被本事务取代的旧缓冲区，commit 后可解除 checkpoint |
| `t_checkpoint_list` | 提交后仍待写回原位的缓冲区 |
| `t_shadow_list` | 正在被日志 IO 影射的缓冲区，与 IO 缓冲区一一对应 |

### journal_head：缓冲区在日志里的归属

每个被日志跟踪的 `buffer_head` 挂一个 `journal_head`，其 `b_jlist` 取五种之一：

```c
#define BJ_Metadata	1	/* Normal journaled metadata */
#define BJ_Forget	2	/* Buffer superseded by this transaction */
#define BJ_Shadow	3	/* Buffer contents being shadowed to the log */
#define BJ_Reserved	4	/* Buffer is reserved for access by journal */
```

`BJ_Shadow` 值得单独提：commit 时元数据块的内容被复制到一块临时 IO 缓冲（`jbd2_journal_write_metadata_buffer()`），原缓冲区进入 Shadow 状态——**此时它还在内存中且内容与日志一致，但不允许再改**，直到日志 IO 完成后被重新归类为 `BJ_Forget`。这就是"元数据写两遍"的第一遍。

## 事务生命周期

### 启动 handle

`start_this_handle()`（`fs/jbd2/transaction.c`）做四件事：检查额度合法性、等 barrier、把额度计入 running 事务、把 handle 挂到当前进程（`current->journal_info`）。

额度校验的边界很明确——**保留额度不超过单次事务上限的一半，且保留 + 申请不超过上限**：

```c
	if (rsv_blocks > jbd2_max_user_trans_buffers(journal) / 2 ||
	    rsv_blocks + blocks > jbd2_max_user_trans_buffers(journal)) {
		printk(KERN_ERR "JBD2: %s wants too many credits "
		       "credits:%d rsv_credits:%d max:%d\n", ...);
		WARN_ON(1);
		return -ENOSPC;
	}
```

barrier 是给 `jbd2_journal_lock_updates()` 之类需要"冻结"日志的操作用的，但有一条例外：

```c
	/*
	 * Wait on the journal's transaction barrier if necessary. Specifically
	 * we allow reserved handles to proceed because otherwise commit could
	 * deadlock on page writeback not being able to complete.
	 */
	if (!handle->h_reserved && journal->j_barrier_count) {
		read_unlock(&journal->j_state_lock);
		wait_event(journal->j_wait_transaction_locked,
				journal->j_barrier_count == 0);
		goto repeat;
	}
```

**reserved handle 可以越过 barrier**——因为持有它的往往是内存回收路径上的回写，若被 barrier 挡住而 barrier 又在等回写完成，就死锁了。这是"日志服务于文件系统，文件系统又服务于内存回收"这条依赖链上的一处刻意破环。

最后一步常被忽略但很关键：

```c
	/*
	 * Ensure that no allocations done while the transaction is open are
	 * going to recurse back to the fs layer.
	 */
	handle->saved_alloc_context = memalloc_nofs_save();
```

事务打开期间的所有分配都禁止递归回文件系统——否则一次 GFP 分配触发回写、回写又想启动事务，就自锁了。

### 关闭 handle：同步批处理

`jbd2_journal_stop()` 里有一段不写进教科书但影响很大的优化。同步 handle（fsync 路径）并不立刻提交，而是**先睡一小会儿，等别的线程搭便车进来**：

```c
	/*
	 * Implement synchronous transaction batching.  If the handle
	 * was synchronous, don't force a commit immediately.  Let's
	 * yield and let another thread piggyback onto this
	 * transaction.  ... Speeds up many-threaded, many-dir
	 * operations by 30x or more...
	 *
	 * We try and optimize the sleep time against what the
	 * underlying disk can do, instead of having a static sleep
	 * time. ...
	 */
	pid = current->pid;
	if (handle->h_sync && journal->j_last_sync_writer != pid &&
	    journal->j_max_batch_time) {
		journal->j_last_sync_writer = pid;
		commit_time = journal->j_average_commit_time;
		trans_time = ktime_to_ns(ktime_sub(ktime_get(),
					   transaction->t_start_time));
		commit_time = max_t(u64, commit_time,
				    1000*journal->j_min_batch_time);
		commit_time = min_t(u64, commit_time,
				    1000*journal->j_max_batch_time);
		if (trans_time < commit_time) {
			ktime_t expires = ktime_add_ns(ktime_get(), commit_time);
			set_current_state(TASK_UNINTERRUPTIBLE);
			schedule_hrtimeout(&expires, HRTIMER_MODE_ABS);
		}
	}
```

睡眠时长不是常量，而是拿**本事务已运行时间**和**历史平均提交时间**做差——设备越快（提交越快），睡得越短；慢盘则更愿意积攒批次。同时用 `j_last_sync_writer` 排除"单进程连续 fsync"的情形：没人可等的时候就别等。

提交触发条件只有两个——handle 是同步的，或事务超龄：

```c
	if (handle->h_sync ||
	    time_after_eq(jiffies, transaction->t_expires)) {
		jbd2_log_start_commit(journal, tid);
		/* Special case: JBD2_SYNC synchronous updates require us
		 * to wait for the commit to complete. */
		if (handle->h_sync && !(current->flags & PF_MEMALLOC))
			wait_for_commit = 1;
	}
```

`PF_MEMALLOC` 那一半条件是同一类破环：内存告急时的写者不能在这里等 IO 完成。

## Commit：从 T_LOCKED 到 T_FINISHED

提交由内核线程 **kjournald2**（`kthread_run(kjournald2, ..., "jbd2/%s")`，名字里的 `%s` 是设备名）驱动。它平时睡在 `j_wait_commit` 上，被唤醒的条件是"有人请求提交"或"running 事务超龄"；默认提交间隔 `JBD2_DEFAULT_MAX_COMMIT_AGE` 为 5 秒（`j_commit_interval = HZ * 5`，可用挂载选项 `commit=N` 改）：

```c
	transaction = journal->j_running_transaction;
	if (transaction && time_after_eq(jiffies, transaction->t_expires)) {
		journal->j_commit_request = transaction->t_tid;
		jbd2_debug(1, "woke because of timeout\n");
	}
```

线程主体是一个 `loop`：只要 `j_commit_sequence != j_commit_request` 就调 `jbd2_journal_commit_transaction()`。

### 阶段一：T_LOCKED —— 封锁并等待

```c
	J_ASSERT(commit_transaction->t_state == T_RUNNING);
	commit_transaction->t_state = T_LOCKED;
	// waits for any t_updates to finish
	jbd2_journal_wait_updates(journal);
	commit_transaction->t_state = T_SWITCH;
```

`jbd2_journal_wait_updates()` 等 `t_updates` 归零，即所有已打开的 handle 都关闭。进入 `T_SWITCH` 后，本事务不再接受新 handle（reserved 的除外，见前文）。此后清理 `t_reserved_list` 里没用上的缓冲区，并在提交前先尝试清一遍 checkpoint 链表——**"在提交之前做，因为它可能释放内存"**，而提交过程本身要分配大量临时缓冲。

### 阶段二：T_FLUSH —— 数据先落盘

```c
	commit_transaction->t_state = T_FLUSH;
	journal->j_committing_transaction = commit_transaction;
	journal->j_running_transaction = NULL;
	commit_transaction->t_log_start = journal->j_head;
	wake_up_all(&journal->j_wait_transaction_locked);
	write_unlock(&journal->j_state_lock);

	/*
	 * Now start flushing things to disk, in the order they appear
	 * on the transaction lists.  Data blocks go first.
	 */
	err = journal_submit_data_buffers(journal, commit_transaction);
```

把 `j_running_transaction` 置空、唤醒 barrier 等待者，然后 **`journal_submit_data_buffers()` 先下发数据块**——这一行就是 `data=ordered` 语义的物理实现：数据先于元数据日志落盘，保证元数据绝不会指向尚未写入的数据块。

### 阶段三：T_COMMIT —— 写描述符与元数据

随后是主循环：为每个元数据块分配日志块号、复制到临时 IO 缓冲、在描述符块里写 tag，攒够一批就 `submit_bh()`：

```c
		if (!descriptor) {
			descriptor = jbd2_journal_get_descriptor_buffer(
						commit_transaction,
						JBD2_DESCRIPTOR_BLOCK);
			tagp = &descriptor->b_data[sizeof(journal_header_t)];
			space_left = descriptor->b_size - sizeof(journal_header_t);
			first_tag = 1;
			set_buffer_jwrite(descriptor);
			set_buffer_dirty(descriptor);
			wbuf[bufs++] = descriptor;
			jbd2_file_log_bh(&log_bufs, descriptor);
		}
		...
		escape = jbd2_journal_write_metadata_buffer(commit_transaction,
						jh, &wbuf[bufs], blocknr);
		...
		tag_flag = 0;
		if (escape)
			tag_flag |= JBD2_FLAG_ESCAPE;
		if (!first_tag)
			tag_flag |= JBD2_FLAG_SAME_UUID;
		write_tag_block(journal, tag, jh2bh(jh)->b_blocknr);
		tag->t_flags = cpu_to_be16(tag_flag);
```

收尾时给最后一个 tag 打 `JBD2_FLAG_LAST_TAG`，然后整批下发：

```c
		if (bufs == journal->j_wbufsize ||
		    commit_transaction->t_buffers == NULL ||
		    space_left < tag_bytes + 16 + csum_size) {
			tag->t_flags |= cpu_to_be16(JBD2_FLAG_LAST_TAG);
start_journal_io:
			if (descriptor)
				jbd2_descriptor_block_csum_set(journal, descriptor);
			for (i = 0; i < bufs; i++) {
				struct buffer_head *bh = wbuf[i];
				if (jbd2_has_feature_checksum(journal))
					crc32_sum = jbd2_checksum_data(crc32_sum, bh);
				lock_buffer(bh);
				clear_buffer_dirty(bh);
				set_buffer_uptodate(bh);
				bh->b_end_io = journal_end_buffer_io_sync;
				submit_bh(REQ_OP_WRITE | JBD2_JOURNAL_REQ_FLAGS, bh);
			}
			cond_resched();
			descriptor = NULL;
			bufs = 0;
		}
```

注意描述符块与它描述的元数据块是**同一批下发**的，而不是"先写描述符确认再写数据"——顺序由后文的 flush 保证。

### 阶段四、五：等 IO 与写 commit 记录

```c
	jbd2_debug(3, "JBD2: commit phase 3\n");
	while (!list_empty(&io_bufs)) {
		...
		wait_on_buffer(bh);
		...
		/* The metadata is now released for reuse, but we need
                   to remember it against this transaction so that when
                   we finally commit, we can do any checkpointing
                   required. */
		jbd2_journal_file_buffer(jh, commit_transaction, BJ_Forget);
		__brelse(bh);
	}
	jbd2_debug(3, "JBD2: commit phase 4\n");
	/* Here we wait for the revoke record and descriptor record buffers */
	while (!list_empty(&log_bufs)) { ... }
```

元数据 IO 完成后，对应缓冲区从 `BJ_Shadow` 转成 `BJ_Forget`——**日志里现在有了一份完整副本，可以解除对原缓冲区的写保护**。revoke 与描述符块在阶段四等待。

阶段五才是整个提交的关键动作——写 commit 块：

```c
	jbd2_debug(3, "JBD2: commit phase 5\n");
	commit_transaction->t_state = T_COMMIT_JFLUSH;
	if (!jbd2_has_feature_async_commit(journal)) {
		err = journal_submit_commit_record(journal, commit_transaction,
						&cbh, crc32_sum);
	}
	if (cbh)
		err = journal_wait_on_commit_record(journal, cbh);
	if (jbd2_has_feature_async_commit(journal) &&
	    journal->j_flags & JBD2_BARRIER) {
		blkdev_issue_flush(journal->j_dev);
	}
```

**一个事务是否"已提交"，完全取决于这个 commit 块是否完整落盘**（配合 flush 保证前面的描述符与元数据先到）。恢复时看不到合法 commit 块的事务会被整体丢弃，即使它的元数据块已经躺在日志里。

### async commit：把等待挪到后面

启用 `JBD2_FEATURE_INCOMPAT_ASYNC_COMMIT` 后，commit 块的提交位置从阶段五提前到阶段三**之前**：

```c
	/* Done it all: now write the commit record asynchronously. */
	if (jbd2_has_feature_async_commit(journal)) {
		err = journal_submit_commit_record(journal, commit_transaction,
						 &cbh, crc32_sum);
		if (err)
			jbd2_journal_abort(journal, err);
	}
```

也就是说，先发 commit 块，再等元数据 IO。这是拿"多一次 flush"换"少一次串行等待"——正确性靠 `blkdev_issue_flush()` 在 commit 块之前确立顺序，代价是慢盘上未必划算。

### 阶段六：移交 checkpoint

```c
	jbd2_debug(3, "JBD2: commit phase 6\n");
	spin_lock(&journal->j_list_lock);
	while (commit_transaction->t_forget) {
		...
		cp_transaction = jh->b_cp_transaction;
		if (cp_transaction) {
			__jbd2_journal_remove_checkpoint(jh);
		}
		/* Only re-checkpoint the buffer_head if it is marked dirty. ... */
```

`BJ_Forget` 的缓冲区在此重新判定：仍脏的进新事务的 checkpoint 链表，已不脏的直接释放。事务随后进入 `T_FINISHED` 并被摘除。

## Checkpoint：回收日志空间

提交完成**不等于**元数据回到原位——它现在有**两份**：日志里一份（用于恢复），文件系统原位一份（旧的，待更新）。checkpoint 就是把第二份写对，然后回收第一份占用的日志空间。

`jbd2_log_do_checkpoint()` 先尝试直接推进 tail，再逐事务处理：

```c
	result = jbd2_cleanup_journal_tail(journal);
	if (result <= 0)
		return result;
	...
	while (transaction->t_checkpoint_list) {
		jh = transaction->t_checkpoint_list;
		bh = jh2bh(jh);
		if (jh->b_transaction != NULL) {
			/* buffer is still part of a running transaction */
			...
			jbd2_log_start_commit(journal, tid);
			jbd2_log_wait_commit(journal, tid);
			goto restart;
		}
		if (!trylock_buffer(bh)) { ... wait_on_buffer(bh); goto retry; }
		else if (!buffer_dirty(bh)) {
			if (__jbd2_journal_remove_checkpoint(jh) ||
			    !transaction->t_checkpoint_list)
				goto out;
		} else { ...queue for writeback... }
	}
```

三种情形：缓冲区**还属于某个未提交事务**——先强制提交它（这解释了为什么 checkpoint 会反过来驱动 commit）；**不脏**——直接摘链；**脏**——排队回写。日志空间不足时 commit 路径也会同步调用它，这也是满日志场景下延迟抖动的来源之一。

checkpoint 由两部分触发：日志空间压力，以及 `jbd2_journal_shrink_checkpoint_list()` 注册的 **shrinker**——内存回收会顺带帮你回收日志空间（`journal->j_shrinker`）。

## Recovery：崩溃后的三趟扫描

`jbd2_journal_recover()` 先检查快路径，然后跑三趟：

```c
	/*
	 * The journal superblock's s_start field (the current log head)
	 * is always zero if, and only if, the journal was cleanly
	 * unmounted.
	 */
	if (!sb->s_start) {
		journal->j_transaction_sequence = be32_to_cpu(sb->s_sequence) + 1;
		journal->j_head = be32_to_cpu(sb->s_head);
		return 0;
	}
	err = do_one_pass(journal, &info, PASS_SCAN);
	if (!err)
		err = do_one_pass(journal, &info, PASS_REVOKE);
	if (!err)
		err = do_one_pass(journal, &info, PASS_REPLAY);
```

| 趟 | 目的 |
| --- | --- |
| `PASS_SCAN` | 从头扫到尾，确定日志里最后一批**完整**事务的范围，并校验校验和 |
| `PASS_REVOKE` | 收集所有 revoke 记录，建立"哪些块不许重放"的表 |
| `PASS_REPLAY` | 在 revoke 表的约束下，把范围内事务的元数据块写回原位 |

为什么要先扫再放？因为**只有扫完整条日志才知道最后一个合法 commit 块在哪**——看到 commit 块才能确认其前面的描述符与元数据是完整的。边扫边放会在遇到半截事务时做出错误决定。

收尾时把事务序号推进到已恢复范围之后，使日志里残留的旧 commit 记录失效，然后 flush 整个文件系统设备：

```c
	/* Restart the log at the next transaction ID, thus invalidating
	 * any existing commit records in the log. */
	journal->j_transaction_sequence = ++info.end_transaction;
	journal->j_head = info.head_block;
	jbd2_journal_clear_revoke(journal);
	err2 = sync_blockdev(journal->j_fs_dev);
	if (journal->j_flags & JBD2_BARRIER) {
		err2 = blkdev_issue_flush(journal->j_fs_dev);
	}
```

`noload` 挂载选项走的是另一条路：`jbd2_journal_skip_recovery()` 只跑 `PASS_SCAN`（为了告诉用户丢了多少事务并初始化序号），然后丢弃全部日志内容。

## Revoke：阻止重放旧记录

revoke 解决的问题很具体：块 B 在事务 100 里被写进日志，随后被释放并重新分配给文件 Y，接着 X 又改了 B。如果崩溃恢复把事务 100 的记录重放到 B 上，就会用 X 的旧内容覆盖 Y 的数据。所以**释放块时必须记一条 revoke**，恢复时据此跳过旧记录。

源码注释（`fs/jbd2/revoke.c` 文件头）列出了四种交互，处理方式各不相同：

| 情形 | 处理 |
| --- | --- |
| 先 revoke、再 journal 同一块 | **取消** revoke——新日志优先 |
| 先 journal、再 revoke | revoke 优先，不取消（revoke 记录写在更后面） |
| 先 revoke、再作为**数据**写 | revoke **不取消**——仍要防旧日志覆盖 |
| 块被释放且无后续引用 | 完全失效缓冲区，解除 checkpoint |

实现上用两张哈希表轮换：

```c
 * We keep two hash tables of revoke records. One hashtable belongs to the
 * running transaction (is pointed to by journal->j_revoke), the other one
 * belongs to the committing transaction. Accesses to the second hash table
 * happen only from the kjournald and no other thread touches this table.  Also
 * journal_switch_revoke_table() ... is called only from kjournald. Therefore
 * we need no locks when accessing the hashtable belonging to the committing
 * transaction.
```

提交事务的那张表**只有 kjournald2 碰**，因此完全无锁；running 事务那张表由持有 handle 的各方通过 `j_revoke_lock` 保护。切换发生在 `commit` 阶段一（`jbd2_journal_switch_revoke_table()`）。

缓冲区上的 revoke 状态是**三态**而非布尔：

```c
 * RevokeValid clear:	no cached revoke status, need to look it up
 * RevokeValid set, Revoked clear:
 *			buffer has not been revoked, and cancel_revoke need do nothing.
 * RevokeValid set, Revoked set:
 *			buffer has been revoked.
```

多出来的"有效位"是为了区分"还没查过"和"查过、确定没被 revoke"，避免每次都做哈希查找。

## 屏障与持久性语义

日志的正确性依赖**顺序**：描述符 + 元数据必须先于 commit 块到达盘上。这个顺序由 `JBD2_BARRIER` 标志下的 `blkdev_issue_flush()` 建立，而非靠下发顺序（块层会重排）。所以 **`barrier=0`（或 `nobarrier`）会破坏日志的崩溃语义**，在有写缓存且掉电不保的设备上等于放弃保护。

另外一处与设备相关的分支：

```c
	/*
	 * If the journal is not located on the file system device,
	 * then we must flush the file system device before we issue
	 * the commit record
	 */
	if (commit_transaction->t_need_data_flush &&
	    (journal->j_fs_dev != journal->j_dev) &&
	    (journal->j_flags & JBD2_BARRIER))
		blkdev_issue_flush(journal->j_fs_dev);
```

外部日志（external journal，`j_fs_dev != j_dev`）要额外 flush 一次文件系统设备，因为两个设备各有独立的写缓存，跨设备的顺序没有隐式保证。

## 观测与调优

每个日志设备在 `/proc/fs/jbd2/<dev>/info` 暴露统计，`jbd2_seq_info_show()` 输出的字段及含义：

| 输出行 | 含义 | 用途 |
| --- | --- | --- |
| `N transactions (M requested)` | 已提交事务数 / 其中被显式请求的 | M/N 高说明多为 fsync 驱动 |
| `average: N ms waiting for transaction` | handle 等 running 事务的平均时间 | 高说明事务被占满 |
| `N ms request delay` | 从请求提交到真正开始提交 | 高说明 kjournald2 来不及 |
| `N ms running transaction` | 事务累积 handle 的时长 | 与 `commit=` 比较 |
| `N ms transaction was being locked` | 等 `t_updates` 归零 | 高说明有长事务 |
| `N ms flushing data (in ordered mode)` | `data=ordered` 的数据 flush | 数据块落盘开销 |
| `N ms logging transaction` | 写日志本身 | 日志设备性能 |
| `N us average transaction commit time` | 平均提交耗时 | 被同步批处理用作睡眠基准 |
| `N handles per transaction` | 每事务 handle 数 | 低说明批处理没生效 |
| `N blocks / N logged blocks per transaction` | 事务规模 | 用于估算日志大小是否够 |

调优选项主要是三个：`commit=N`（提交间隔，默认 5 秒）、`journal_async_commit`（异步提交）、日志大小（创建时指定）。三者都是在"崩溃后丢多少"与"平时有多快"之间取舍——提交间隔越长，崩溃时丢的越多。

## 与相邻子系统的边界

- **PageCache 与 buffer_head**：JBD2 操作的是 `buffer_head` 而非 page，`data=ordered` 的 flush 对象是文件数据页，两者通过 `t_inode_list` 关联（ext4 用它跟踪需要特殊处理的 inode）。见 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)。
- **块层**：日志写入最终经 `submit_bh()` 下发到 [块设备栈](/docs/CS/OS/Linux/dev/block.md)；日志设备通常是文件系统内的一个隐藏 inode（ext4 默认 inode 8），因此日志本身也是一次普通的文件块写入，只是绕过了文件系统自己的分配路径（`j_bmap` 回调）。
- **延迟分配**：ext4 的 delalloc 把物理块分配推迟到回写，这意味着事务里"弄脏的块号"直到很晚才确定，日志额度估算必须按最坏情况预留。
- **fsync 语义**：`fsync` 要等到"数据落盘 + 元数据事务 commit 完成"，即 `jbd2_journal_stop()` 里的 `wait_for_commit` 分支；这也是为什么 fsync 的开销与日志设备性能直接相关。
- **快速提交**：`JBD2_FEATURE_INCOMPAT_FAST_COMMIT`（ext4 的 `fast_commit`）是另一条并行的轻量日志，只记少量重做信息，用于降低 fsync 延迟；它走的是 `j_fc_*` 系列回调，与本文的完整事务路径并存——commit 阶段一开始就在 `j_fc_wait` 上等它收尾。
- **VFS 视角**：日志发生在文件系统内部，[VFS](/docs/CS/OS/Linux/fs/fs.md) 层完全不知道它的存在。

## Links

- [Linux 文件系统链路总览](/docs/CS/OS/Linux/fs/README.md)
- [XFS](/docs/CS/OS/Linux/fs/xfs.md) — 另一种日志思路：逻辑日志 + CIL 合并 + AIL 推进尾部
- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)

## References

- [Linux 6.12 源码：include/linux/jbd2.h](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/include/linux/jbd2.h?h=v6.12)
- [Linux 6.12 源码：fs/jbd2/commit.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/jbd2/commit.c?h=v6.12)
- [Linux 6.12 源码：fs/jbd2/revoke.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/fs/jbd2/revoke.c?h=v6.12)
- [ext4 磁盘布局与日志文档（kernel.org）](https://www.kernel.org/doc/html/latest/filesystems/ext4/journal.html)
