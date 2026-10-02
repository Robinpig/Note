## Introduction

unbuffered I/O

open read write lseek close

Most file I/O on a UNIX system can be performed using only five functions: open, read, write, lseek, and close.
These functions are often referred to as unbuffered I/O.

Historically, a buffer_head was used to map a single block within a page, and of course as the unit of I/O through the filesystem and block layers.
Nowadays the basic I/O unit is the bio, and buffer_heads are used for extracting block mappings (via a get_block_t call), for tracking state within a page (via a page_mapping) and for wrapping bio submission for backward compatibility reasons (e.g. submit_bh).

```c
struct buffer_head {
	unsigned long b_state;		/* buffer state bitmap (see above) */
	struct buffer_head *b_this_page;/* circular list of page's buffers */
	struct page *b_page;		/* the page this bh is mapped to */

	sector_t b_blocknr;		/* start block number */
	size_t b_size;			/* size of mapping */
	char *b_data;			/* pointer to data within the page */

	struct block_device *b_bdev;
	bh_end_io_t *b_end_io;		/* I/O completion */
 	void *b_private;		/* reserved for b_end_io */
	struct list_head b_assoc_buffers; /* associated with another mapping */
	struct address_space *b_assoc_map;	/* mapping this buffer is
						   associated with */
	atomic_t b_count;		/* users using this buffer_head */
	spinlock_t b_uptodate_lock;	/* Used by the first bh in a page, to
					 * serialise IO completion of other
					 * buffers in the page */
};
```

main unit of I/O for the block layer and lower layers (ie drivers and stacking drivers)

```c
struct bio {
	struct bio		*bi_next;	/* request queue link */
	struct block_device	*bi_bdev;
	unsigned int		bi_opf;		/* bottom bits req flags,
						 * top bits REQ_OP. Use
						 * accessors.
						 */
	unsigned short		bi_flags;	/* BIO_* below */
	unsigned short		bi_ioprio;
	unsigned short		bi_write_hint;
	blk_status_t		bi_status;
	atomic_t		__bi_remaining;

	struct bvec_iter	bi_iter;

	bio_end_io_t		*bi_end_io;

	void			*bi_private;
#ifdef CONFIG_BLK_CGROUP
	/*
	 * Represents the association of the css and request_queue for the bio.
	 * If a bio goes direct to device, it will not have a blkg as it will
	 * not have a request_queue associated with it.  The reference is put
	 * on release of the bio.
	 */
	struct blkcg_gq		*bi_blkg;
	struct bio_issue	bi_issue;
#ifdef CONFIG_BLK_CGROUP_IOCOST
	u64			bi_iocost_cost;
#endif
#endif

#ifdef CONFIG_BLK_INLINE_ENCRYPTION
	struct bio_crypt_ctx	*bi_crypt_context;
#endif

	union {
#if defined(CONFIG_BLK_DEV_INTEGRITY)
		struct bio_integrity_payload *bi_integrity; /* data integrity */
#endif
	};

	unsigned short		bi_vcnt;	/* how many bio_vec's */

	/*
	 * Everything starting with bi_max_vecs will be preserved by bio_reset()
	 */

	unsigned short		bi_max_vecs;	/* max bvl_vecs we can hold */

	atomic_t		__bi_cnt;	/* pin count */

	struct bio_vec		*bi_io_vec;	/* the actual vec list */

	struct bio_set		*bi_pool;

	/*
	 * We can inline a number of vecs at the end of the bio, to avoid
	 * double allocations for a small number of bio_vecs. This member
	 * MUST obviously be kept at the very end of the bio.
	 */
	struct bio_vec		bi_inline_vecs[];
};
```

## DirectIO

__generic_file_write_iter - write data to a file
@iocb:	IO state structure (file, offset, etc.)
@from:	iov_iter with data to write

This function does all the work needed for actually writing data to a file.
It does all basic checks, removes SUID from the file, updates modification times and calls proper subroutines depending on whether we do direct IO or a standard buffered write.

It expects i_mutex to be grabbed unless we work on a block device or similar object which does not need locking at all.

This function does *not* take care of syncing data in case of O_SYNC write.
A caller has to handle it. This is mainly due to the fact that we want to avoid syncing under i_mutex.

Return:

* number of bytes written, even for truncated writes
* negative error code if no data has been written at all

```c
ssize_t __generic_file_write_iter(struct kiocb *iocb, struct iov_iter *from)
{
	struct file *file = iocb->ki_filp;
	struct address_space *mapping = file->f_mapping;
	struct inode 	*inode = mapping->host;
	ssize_t		written = 0;
	ssize_t		err;
	ssize_t		status;

	/* We can write back this queue in page reclaim */
	current->backing_dev_info = inode_to_bdi(inode);
	err = file_remove_privs(file);
	if (err)
		goto out;

	err = file_update_time(file);
	if (err)
		goto out;

	if (iocb->ki_flags & IOCB_DIRECT) {
		loff_t pos, endbyte;

		written = generic_file_direct_write(iocb, from);
		/*
		 * If the write stopped short of completing, fall back to
		 * buffered writes.  Some filesystems do this for writes to
		 * holes, for example.  For DAX files, a buffered write will
		 * not succeed (even if it did, DAX does not handle dirty
		 * page-cache pages correctly).
		 */
		if (written < 0 || !iov_iter_count(from) || IS_DAX(inode))
			goto out;

		status = generic_perform_write(file, from, pos = iocb->ki_pos);
		/*
		 * If generic_perform_write() returned a synchronous error
		 * then we want to return the number of bytes which were
		 * direct-written, or the error code if that was zero.  Note
		 * that this differs from normal direct-io semantics, which
		 * will return -EFOO even if some bytes were written.
		 */
		if (unlikely(status < 0)) {
			err = status;
			goto out;
		}
		/*
		 * We need to ensure that the page cache pages are written to
		 * disk and invalidated to preserve the expected O_DIRECT
		 * semantics.
		 */
		endbyte = pos + status - 1;
		err = filemap_write_and_wait_range(mapping, pos, endbyte);
		if (err == 0) {
			iocb->ki_pos = endbyte + 1;
			written += status;
			invalidate_mapping_pages(mapping,
						 pos >> PAGE_SHIFT,
						 endbyte >> PAGE_SHIFT);
		} else {
			/*
			 * We don't know how much we wrote, so just return
			 * the number of bytes which were direct-written
			 */
		}
	} else {
		written = generic_perform_write(file, from, iocb->ki_pos);
		if (likely(written > 0))
			iocb->ki_pos += written;
	}
out:
	current->backing_dev_info = NULL;
	return written ? written : err;
}
```

```c
// mm/filemap.c
ssize_t
generic_file_direct_write(struct kiocb *iocb, struct iov_iter *from)
{
	struct file	*file = iocb->ki_filp;
	struct address_space *mapping = file->f_mapping;
	struct inode	*inode = mapping->host;
	loff_t		pos = iocb->ki_pos;
	ssize_t		written;
	size_t		write_len;
	pgoff_t		end;

	write_len = iov_iter_count(from);
	end = (pos + write_len - 1) >> PAGE_SHIFT;

	if (iocb->ki_flags & IOCB_NOWAIT) {
		/* If there are pages to writeback, return */
		if (filemap_range_has_page(file->f_mapping, pos,
					   pos + write_len - 1))
			return -EAGAIN;
	} else {
		written = filemap_write_and_wait_range(mapping, pos,
							pos + write_len - 1);
		if (written)
			goto out;
	}

	/*
	 * After a write we want buffered reads to be sure to go to disk to get
	 * the new data.  We invalidate clean cached page from the region we're
	 * about to write.  We do this *before* the write so that we can return
	 * without clobbering -EIOCBQUEUED from ->direct_IO().
	 */
	written = invalidate_inode_pages2_range(mapping,
					pos >> PAGE_SHIFT, end);
	/*
	 * If a page can not be invalidated, return 0 to fall back
	 * to buffered write.
	 */
	if (written) {
		if (written == -EBUSY)
			return 0;
		goto out;
	}

	written = mapping->a_ops->direct_IO(iocb, from);

	/*
	 * Finally, try again to invalidate clean pages which might have been
	 * cached by non-direct readahead, or faulted in by get_user_pages()
	 * if the source of the write was an mmap'ed region of the file
	 * we're writing.  Either one is a pretty crazy thing to do,
	 * so we don't support it 100%.  If this invalidation
	 * fails, tough, the write still worked...
	 *
	 * Most of the time we do not need this since dio_complete() will do
	 * the invalidation for us. However there are some file systems that
	 * do not end up with dio_complete() being called, so let's not break
	 * them by removing it completely.
	 *
	 * Noticeable example is a blkdev_direct_IO().
	 *
	 * Skip invalidation for async writes or if mapping has no pages.
	 */
	if (written > 0 && mapping->nrpages &&
	    invalidate_inode_pages2_range(mapping, pos >> PAGE_SHIFT, end))
		dio_warn_stale_pagecache(file);

	if (written > 0) {
		pos += written;
		write_len -= written;
		if (pos > i_size_read(inode) && !S_ISBLK(inode->i_mode)) {
			i_size_write(inode, pos);
			mark_inode_dirty(inode);
		}
		iocb->ki_pos = pos;
	}
	if (written != -EIOCBQUEUED)
		iov_iter_revert(from, write_len - iov_iter_count(from));
out:
	return written;
}
```

## 五种 IO 模型

一次读操作可以拆成两个阶段：**①数据准备**（数据从网卡/磁盘到达内核缓冲区——Socket 接收队列或 page cache）与**②数据拷贝**（内核空间 → 用户空间缓冲区）。阻塞/非阻塞与同步/异步这两组容易混淆的概念，分别对应两个阶段的行为：

- **阻塞 vs 非阻塞**：看**阶段①**。数据未就绪时，阻塞 IO 让线程睡眠（内核机制见 [Socket 阻塞读与唤醒](/docs/CS/OS/Linux/proc/thundering_herd.md?id=socket-阻塞读与唤醒)）；非阻塞 IO 立即返回 `EWOULDBLOCK`，由用户轮询；
- **同步 vs 异步**：看**阶段②**。同步 IO 的数据拷贝由用户线程在内核态完成（epoll 就绪后仍要自己 `read`）；异步 IO 两阶段全部由内核完成后通知用户（Windows IOCP、Linux io_uring）。

| 模型 | 阶段① | 阶段② | 典型实现 |
| :-- | :-- | :-- | :-- |
| 阻塞 IO (BIO) | 阻塞等待 | 阻塞拷贝 | 传统 socket read |
| 非阻塞 IO | 轮询返回 `EWOULDBLOCK` | 阻塞拷贝 | `O_NONBLOCK` |
| IO 多路复用 | select/poll/epoll 批量等待 | 阻塞拷贝 | [multiplexing](/docs/CS/OS/Linux/IO/multiplexing.md) |
| 信号驱动 | SIGIO 通知就绪 | 阻塞拷贝 | `sigaction`；TCP 不适用（信号不携带信息、易溢出），UDP 可用 |
| 异步 IO | 内核完成 | 内核完成并通知 | Windows IOCP、Linux [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)（5.1+） |

上层线程模型（Reactor/Proactor）与 Netty 的落地见 [Reactor 线程模型](/docs/CS/Framework/Netty/EventLoop.md?id=reactor-线程模型)。

## BIO

阻塞系统调用：`read`/`write` 数据未就绪时线程睡眠。并发模型是**一连接一线程**，连接数受线程成本限制，适合 C10K 以下的内部系统。

## NIO（非阻塞）

`O_NONBLOCK` 下读操作无数据立即返回 `EWOULDBLOCK`，写操作"能写多少写多少"（返回已写字节数）。可以用少量线程轮询大量连接，但轮询本身是密集的系统调用 + 上下文切换，连接多时开销反而剧增——真正解决 C10K 的是把"等待"也批量化：

## 多路复用

select/poll/epoll 用一个系统调用同时等待大量 fd，机制与演进详见 [multiplexing](/docs/CS/OS/Linux/IO/multiplexing.md) 与 [epoll](/docs/CS/OS/Linux/IO/epoll.md)。核心差异一句话：select 是固定 1024 的位图 + 每次全量拷贝 fd 集合 + O(n) 遍历；epoll 用红黑树管理 fd（免全量拷贝）、就绪链表 `rdllist`（免遍历）、就绪回调 `ep_poll_callback`（免内核轮询）。

不经过 page cache 的读写是 Direct IO（数据库等自带缓存的场景），见上文 [DirectIO](#directio) 与 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)。

## AIO

Native AIO（libaio）只支持 Direct IO，一直不温不火；io_uring（5.1+，Jens Axboe）用共享环形缓冲区提交/收割 IO，把真异步带上了 Linux，见 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。

参考：[Design Notes on Asynchronous I/O (aio) for Linux](http://lse.sourceforge.net/io/aionotes.txt)

## Links

- [multiplexing](/docs/CS/OS/Linux/IO/multiplexing.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [thundering herd（Socket 阻塞读）](/docs/CS/OS/Linux/proc/thundering_herd.md)
- [Netty EventLoop（Reactor 线程模型）](/docs/CS/Framework/Netty/EventLoop.md)
- [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)
- [DPDK](/docs/CS/OS/Linux/IO/DPDK.md)
