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

## BIO

Blocking system calls

Read/write



## NIO



select/poll/epoll



only support network sockets and pipes



Databases  **`O_DIRECT`**

Direct IO, don't use os page cache

Zero-Copy IO







## AIO
Native IO
[Design Notes on Asynchronous I/O (aio) for Linux](http://lse.sourceforge.net/io/aionotes.txt)

libaio

- ony support Direct IO





Io_uring


bypass IO