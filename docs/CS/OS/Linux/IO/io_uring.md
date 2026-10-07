## Introduction

io_uring 是 Linux 5.1（2019，Jens Axboe）引入的**异步 I/O 接口**：应用与内核通过**共享的两个环形队列**——submission queue（SQ）提交请求、completion queue（CQ）收割结果——来协作，使一次 I/O 可以做到提交与完成都不阻塞、甚至完全不触发系统调用。

要理解它解决的痛点，先看两条老路的局限：

- **epoll 只是"就绪通知"，不是异步**。它告诉应用"数据已在内核缓冲区就绪"，但阶段②（数据从内核拷到用户空间）仍要应用自己调 `read` 完成。海量连接下，每个请求至少是 `epoll_wait` + `read`/`write` 多次系统调用，上下文切换成本随连接数增长。
- **Linux Native AIO（libaio / `io_submit`）长期残废**。它只在 **O_DIRECT** 下才真正异步，对 buffered I/O、网络 socket 大多仍会阻塞在提交路径，接口设计陈旧、错误处理反直觉。

io_uring 把"提交一批操作"与"收割一批结果"都做成内存中共享环上的读写，并把网络、文件、甚至 `accept`/`openat`/`send`/`futex` 等非传统 I/O 操作都纳入同一套异步框架，让阶段①、阶段②都可由内核完成、完成后再通知，是 Linux 上最接近 Windows IOCP 的真异步接口。本笔记对照内核 **v6.12** 源码梳理：共享环设计 → UAPI 数据结构 → 三种工作模式 → 四个系统调用 → 一个请求的完整生命周期 → 固定资源与高级特性 → io-wq 回退与安全限制。

## Shared Ring Design

### SQ and CQ: Single Producer Single Consumer

SQ 和 CQ 都是**单生产者 / 单消费者**（SPSC）的环形队列，但读写方向相反：

| 环 | 生产者（写 tail） | 消费者（写 head） |
| --- | --- | --- |
| SQ 提交环 | 应用填入待执行操作 | 内核取走执行 |
| CQ 完成环 | 内核填入完成结果 | 应用收割 |

内核维护 SQ 的 head 和 CQ 的 tail；应用维护 SQ 的 tail 和 CQ 的 head。双方通过 head/tail 两个索引判断环中有多少条目，索引与 `ring_mask`（= 环大小 − 1）按位与得到下标，因此**环大小必须是 2 的幂**。

关键在于：这些环和 SQE/CQE 数组都被 mmap 进了用户空间，**应用提交请求、收割完成只是在写/读自己进程地址空间里的内存，不必每步都陷入内核**——可以批量填充多个 SQE 后只在必要时通知内核一次。

### Memory Barrier

共享内存的两端必须用配对的内存屏障保证可见性。应用侧的规则：

- 写入 SQ tail 之前，需要 `smp_wmb()`（保证先写好 SQE 内容、再推进 tail），与内核读 tail 的 `smp_load_acquire` 配对；用 `smp_store_release` 写 tail 即可。
- 读取 CQ tail 之后、读 CQE 之前，需要 `smp_rmb()`，与内核写 tail 前的 `smp_wmb()` 配对；更新 CQ head 之前需要 `smp_mb()`，用 `smp_store_release` 存 head。
- 使用 SQPOLL 时，应用更新 SQ tail **之后**再检查 `IORING_SQ_NEED_WAKEUP` 标志，中间需要一次完整的 `smp_mb()`。

内核对任何发生在与应用共享数据上的读写都使用 `READ_ONCE()` / `WRITE_ONCE()`，既保证顺序，也确保一旦从（可能被应用篡改的）共享内存加载了值，该值在内核里保持稳定。

## UAPI Data Structures

### SQE: Submission Entry

`struct io_uring_sqe` 是应用描述"要做什么"的定长结构，**固定 64 字节**（内核用 `BUILD_BUG_ON(sizeof(struct io_uring_sqe) != 64)` 强校验）。定义见 `include/uapi/linux/io_uring.h`：

```c
struct io_uring_sqe {
	__u8	opcode;		/* type of operation for this sqe */
	__u8	flags;		/* IOSQE_ flags */
	__u16	ioprio;		/* ioprio for the request */
	__s32	fd;		/* file descriptor to do IO on */
	union {
		__u64	off;	/* offset into file */
		__u64	addr2;
		struct {
			__u32	cmd_op;
			__u32	__pad1;
		};
	};
	union {
		__u64	addr;	/* pointer to buffer or iovecs */
		__u64	splice_off_in;
	};
	__u32		len;	/* buffer size or number of iovecs */
	union {
		__kernel_rwf_t	rw_flags;
		__u32		fsync_flags;
		__u16		poll_events;
		__u32		poll32_events;
		__u32		sync_range_flags;
		__u32		msg_flags;
		__u32		timeout_flags;
		__u32		accept_flags;
		__u32		cancel_flags;
		__u32		open_flags;
		__u32		statx_flags;
		__u32		fadvise_advice;
		__u32		splice_flags;
		__u32		msg_ring_flags;
		__u32		uring_cmd_flags;
		__u32		futex_flags;
		/* ... 更多操作的 flags ... */
	};
	__u64	user_data;	/* data to be passed back at completion time */
	union {
		__u16	buf_index;	/* index into fixed buffers */
		__u16	buf_group;	/* for grouped buffer selection */
	} __attribute__((packed));
	__u16	personality;
	union {
		__s32	splice_fd_in;
		__u32	file_index;
		__u32	optlen;
	};
	union {
		struct {
			__u64	addr3;
			__u64	__pad2[1];
		};
		__u64	optval;
		/*
		 * If the ring is initialized with IORING_SETUP_SQE128, then
		 * this field is used for 80 bytes of arbitrary command data
		 */
		__u8	cmd[0];
	};
};
```

大量 union 是因为不同操作复用同一批字段：`read`/`write` 用 `addr`(缓冲地址)+`len`+`off`；`readv`/`writev` 用 `addr` 指向 iovec、`len` 为 iovec 个数；`splice` 用 `splice_off_in`+`splice_fd_in`；`uring_cmd` 把末尾当命令数据。这样无论何种操作都能塞进同一条 64 字节表项。

### CQE: Completion Entry

```c
struct io_uring_cqe {
	__u64	user_data;	/* sqe->user_data value passed back */
	__s32	res;		/* result code for this event */
	__u32	flags;

	/*
	 * If the ring is initialized with IORING_SETUP_CQE32, then this field
	 * contains 16-bytes of padding, doubling the size of the CQE.
	 */
	__u64 big_cqe[];
};
```

`user_data` 原样回填提交时的值，应用靠它把完成项关联回自己的请求（不必是指针，也可放请求 id）；`res` 是结果——成功时是字节数等，失败时是负的 errno；`flags` 携带 `IORING_CQE_F_*` 信息，如 multishot 是否还有后续、是否使用了 provided buffer。

### Shared Page io_rings

SQ 与 CQ 的 head/tail、mask、计数等元数据放在同一个 mmap 页 `struct io_rings`（定义在 `include/linux/io_uring_types.h`），`cqes[]` 柔性数组紧随其后：

```c
struct io_rings {
	/*
	 * Head and tail offsets into the ring; the offsets need to be
	 * masked to get valid indices.
	 *
	 * The kernel controls head of the sq ring and the tail of the cq ring,
	 * and the application controls tail of the sq ring and the head of the
	 * cq ring.
	 */
	struct io_uring		sq, cq;
	u32			sq_ring_mask, cq_ring_mask;
	u32			sq_ring_entries, cq_ring_entries;
	u32			sq_dropped;
	atomic_t		sq_flags;
	u32			cq_flags;
	u32			cq_overflow;
	struct io_uring_cqe	cqes[] ____cacheline_aligned_in_smp;
};
```

应用通过 `io_uring_setup` 返回的 `sq_off` / `cq_off`（各字段在共享页内的偏移）定位 head/tail/mask 等，因此同一份结构可以在内核与不同版本的 liburing 之间稳定演进。三个 mmap 偏移量是固定的魔数：`IORING_OFF_SQ_RING = 0`、`IORING_OFF_CQ_RING = 0x8000000`、`IORING_OFF_SQES = 0x10000000`，分别映射 SQ/CQ 元数据页和 SQE 数组。

### opcode: One Interface for All Operations

v6.12 已支持 60 多种 opcode，远不止读写。常见分类：

| 类别 | 代表 opcode |
| --- | --- |
| 文件读写 | `READV`/`WRITEV`、`READ`/`WRITE`、`READ_FIXED`/`WRITE_FIXED` |
| 文件操作 | `OPENAT`/`OPENAT2`、`CLOSE`、`FTRUNCATE`、`STATX`、`FADVISE`、`MADVISE` |
| 目录/路径 | `MKDIRAT`、`SYMLINKAT`、`LINKAT`、`RENAMEAT`、`UNLINKAT` |
| 网络 | `SOCKET`、`BIND`、`LISTEN`、`ACCEPT`、`CONNECT`、`SEND`/`RECV`、`SENDMSG`/`RECVMSG`、`SHUTDOWN`、`EPOLL_CTL` |
| 零拷贝 | `SEND_ZC`、`SENDMSG_ZC` |
| 轮询/超时 | `POLL_ADD`/`POLL_REMOVE`、`TIMEOUT`/`TIMEOUT_REMOVE` |
| 同步原语 | `FUTEX_WAIT`/`FUTEX_WAKE`/`FUTEX_WAITV`、`WAITID` |
| 其它 | `NOP`、`URING_CMD`（设备特定命令）、`MSG_RING`（环间通信）、`PROVIDE_BUFFERS`、`SPLICE`/`TEE` |

这意味着一条提交链可以表达"accept → recv → 读文件 → send"这种完整工作流，全部在同一个异步上下文里推进。

## Three Working Modes

`io_uring_setup` 的 flags 决定内核如何收割完成，三种模式性能与适用场景不同：

| 模式 | 关键 flag | 完成如何被发现 | 适用 |
| --- | --- | --- | --- |
| 中断驱动（默认） | 无 | I/O 完成触发中断，内核填 CQE | 通用，文件/网络 buffered I/O |
| 轮询模式 | `IORING_SETUP_IOPOLL` | 应用或内核主动轮询块层完成（无中断） | O_DIRECT、低延迟 NVMe，需要设备支持 |
| 内核轮询线程 | `IORING_SETUP_SQPOLL` | 内核 SQPOLL 线程持续轮询 SQ，连提交都免系统调用 | 极高 IOPS、极致低延迟 |

**IOPOLL** 下没有传统中断，请求完成后需要有人调用 io_poll 去收割块层 completion；`io_uring_enter` 中若同时设了 `SETUP_IOPOLL` 且没有 `SQPOLL`，等待走 `io_iopoll_check` 而非默认的 `io_cqring_wait`。

**SQPOLL** 会创建一个内核线程（任务名 `iou-sqp-*`），持续轮询关联环的 SQ：应用写完 SQE、推进 tail 后，线程会自己取走提交，**正常情况下完全无需 `io_uring_enter`**。线程空闲超过 `sq_thread_idle` 毫秒会睡眠，此时内核在 SQ flags 里置 `IORING_SQ_NEED_WAKEUP`，应用发现后要用带 `IORING_ENTER_SQ_WAKEUP` 的 `io_uring_enter` 唤醒它。`IORING_SETUP_SQ_AFF` 可把该线程绑定到指定 CPU（`sq_thread_cpu`）。

IOPOLL 与 SQPOLL 同时开启时，应用连完成轮询都不用做——`io_sq_thread` 一并承担提交与完成轮询，减少 CPU 消耗与 uring_lock 争用。

## Four System Calls

### io_uring_setup: Create the Ring

```c
SYSCALL_DEFINE2(io_uring_setup, u32, entries,
		struct io_uring_params __user *, params)
{
	return io_uring_setup(entries, params);
}
```

应用传入期望的环大小 `entries` 和 `io_uring_params`，内核返回一个 ring fd，并把实际的 SQ/CQ 大小、特性位、各字段偏移写回 params。内核把 SQ 大小向上取整到 2 的幂；CQ 默认是 SQ 的两倍（因为应用可能临时超出 SQ 深度），设 `IORING_SETUP_CQSIZE` 则用应用指定值。限制为 `IORING_MAX_ENTRIES` / `IORING_MAX_CQ_ENTRIES`，超限且没有 `IORING_SETUP_CLAMP` 则报错。

核心创建逻辑在 `io_uring_create`：分配 `io_ring_ctx` → `io_allocate_scq_urings` 建立共享环 → 若需要则 `io_sq_offload_create` 起 SQPOLL 线程 → 回填 `sq_off`/`cq_off` 偏移和 `features` → 最后 `io_uring_install_fd` 安装 fd（放到最后，避免有人在初始化完成前就 close 它）。

### io_uring_enter: Submit and Wait

```c
SYSCALL_DEFINE6(io_uring_enter, unsigned int, fd, u32, to_submit,
		u32, min_complete, u32, flags, const void __user *, argp,
		size_t, argsz)
```

这是提交与等待的入口，一次调用可同时完成两件事：

- `to_submit`：提交 SQ 中指定数量的待处理项（非 SQPOLL 模式下走 `io_submit_sqes`）；
- `min_complete` + `IORING_ENTER_GETEVENTS`：阻塞等待至少这么多个完成，可带超时与要屏蔽的信号集（`argp`）。

SQPOLL 模式下提交与完成都由 SQ 线程负责，此调用只是按需唤醒线程（`IORING_ENTER_SQ_WAKEUP`）或等待 SQ 被消费（`IORING_ENTER_SQ_WAIT`）。

### io_uring_register: Register Fixed Resources

```c
SYSCALL_DEFINE4(io_uring_register, unsigned int, fd, unsigned int, opcode,
		void __user *, arg, unsigned int, nr_args)
```

用于注册长期复用的资源（文件、缓冲、凭证等），是热路径性能优化的关键，详见后文「固定资源」。

### io_uring: Reaping CQ without a System Call

应用收割 CQ 完全是读共享内存：比较 CQ head/tail、取出 CQE、处理后推进 head。只有当需要阻塞等待新完成、或 CQ 环溢出需要内核补刷时才进入内核。

## Lifecycle of a Request

下面跟踪一条普通 `READ` SQE 从提交到完成在内核里走过的路径（v6.12）。

### Allocating the Request Object io_kiocb

每个 SQE 在内核对应一个 `struct io_kiocb`（io_uring 的内核 I/O 控制块）。它从专用 slab 缓存 `req_cachep`（`KMEM_CACHE(io_kiocb, ...)`）分配，并有 per-context 的请求缓存做批量补充，避免每个请求都走 slab 分配器。`io_kiocb` 是连接一切的枢纽，关键字段：

```c
struct io_kiocb {
	union {
		struct file		*file;
		struct io_cmd_data	cmd;
	};

	u8				opcode;
	u8				iopoll_completed;
	u16				buf_index;
	unsigned			nr_tw;
	io_req_flags_t			flags;	/* REQ_F_* flags */

	struct io_cqe			cqe;
	struct io_ring_ctx		*ctx;
	struct task_struct		*task;

	union {
		struct io_mapped_ubuf	*imu;	/* registered buffer */
		struct io_buffer	*kbuf;	/* selected provided buffer */
		struct io_buffer_list	*buf_list;
	};
	union {
		struct io_wq_work_node	comp_list;
		__poll_t		apoll_events;
	};

	struct io_rsrc_node		*rsrc_node;
	atomic_t			refs;
	struct io_task_work		io_task_work;
	struct hlist_node		hash_node;
	struct async_poll		*apoll;
	void				*async_data;
	atomic_t			poll_refs;
	struct io_kiocb			*link;
	const struct cred		*creds;
	struct io_wq_work		work;

	struct {
		u64			extra1;
		u64			extra2;
	} big_cqe;
};
```

提交主循环 `io_submit_sqes` 每次先 `io_alloc_req` 取一个 `io_kiocb`，再 `io_get_sqe` 取出应用填的 SQE（经 SQ index array 一层间接，`IORING_SETUP_NO_SQARRAY` 可去掉），交给 `io_submit_sqe`。

### Initializing io_init_req

`io_submit_sqe` 先调 `io_init_req`，把 SQE 的内容搬进 `io_kiocb` 并做校验：

```c
static int io_init_req(struct io_ring_ctx *ctx, struct io_kiocb *req,
		       const struct io_uring_sqe *sqe)
{
	const struct io_issue_def *def;
	unsigned int sqe_flags;
	u8 opcode;

	/* req is partially pre-initialised, see io_preinit_req() */
	req->opcode = opcode = READ_ONCE(sqe->opcode);
	/* same numerical values with corresponding REQ_F_*, safe to copy */
	sqe_flags = READ_ONCE(sqe->flags);
	req->flags = (__force io_req_flags_t) sqe_flags;
	req->cqe.user_data = READ_ONCE(sqe->user_data);
	req->file = NULL;
	req->rsrc_node = NULL;
	req->task = current;

	if (unlikely(opcode >= IORING_OP_LAST)) {
		req->opcode = 0;
		return io_init_fail_req(req, -EINVAL);
	}
	def = &io_issue_defs[opcode];
	/* ...校验 flags、调用 def->prep 做操作特定准备... */
```

每个 opcode 在 `io_issue_defs[opcode]`（`struct io_issue_def`）里登记了自己的 `prep`（准备/校验）、`issue`（实际下发）函数和能力位，是一套典型的 opcode 分发表。注意这里读 SQE 都用 `READ_ONCE`——因为 SQE 在用户映射内存里，可能被应用随时改动。

### Dispatching io_queue_sqe → io_issue_sqe

普通请求经 `io_queue_sqe`，它先以内联、非阻塞方式尝试一次：

```c
static inline void io_queue_sqe(struct io_kiocb *req)
{
	int ret;

	ret = io_issue_sqe(req, IO_URING_F_NONBLOCK|IO_URING_F_COMPLETE_DEFER);

	/*
	 * We async punt it if the file wasn't marked NOWAIT, or if the file
	 * doesn't support non-blocking read/write attempts
	 */
	if (unlikely(ret))
		io_queue_async(req, ret);
}
```

`IO_URING_F_NONBLOCK` 要求"绝不能阻塞"，`IO_URING_F_COMPLETE_DEFER` 表示"完成先攒着、批量提交结束再统一刷 CQ"。`io_issue_sqe` 调对应操作的 `issue` 函数（如读文件走 `io_read`、网络走相应 handler）。这一步有三种结果，决定请求走向。

### Three Exit Paths

1. **内联完成（inline completion）**：操作当场就能完成（如数据已在 PageCache、或一个非阻塞的纯计算操作），结果直接写入 `req->cqe`，请求随后进入批量完成列表，等这一批提交结束统一刷进 CQ 环——整条路径不睡眠、不额外调度。

2. **挂起等待（poll / arm poll）**：暂时不能完成（如 socket 无数据、文件需块 I/O）。`io_issue_sqe` 返回 `-EAGAIN`，`io_queue_async` 调 `io_arm_poll_handler` 注册一个轮询/等待项，数据就绪时由内核回调（如协议栈 `sock_def_readable` 触发）把请求重新排队执行，类似 epoll 的等待机制但由 io_uring 自管。

3. **异步线程回退（io-wq）**：操作不支持非阻塞、必须在阻塞上下文中完成时（典型是 buffered I/O 遇到需要等待的情况），`io_queue_async` 走 `io_queue_iowq`，把请求丢给 **io-wq** 线程池阻塞执行，应用线程完全不被阻塞。

### Completing and Filling Back CQE

执行完成后，结果写进 `req->cqe.res`/`flags`。绝大多数路径用**延迟完成**（`IO_URING_F_COMPLETE_DEFER`），在批量提交结束的 `io_submit_state_end` → `io_submit_flush_completions` 里一次性把攒下的完成项填进 CQ 环，摊薄开销。真正填 CQE 的是 `io_fill_cqe_req`：

```c
static __always_inline bool io_fill_cqe_req(struct io_ring_ctx *ctx,
					    struct io_kiocb *req)
{
	struct io_uring_cqe *cqe;

	if (unlikely(!io_get_cqe(ctx, &cqe)))
		return false;

	memcpy(cqe, &req->cqe, sizeof(*cqe));
	if (ctx->flags & IORING_SETUP_CQE32) {
		memcpy(cqe->big_cqe, &req->big_cqe, sizeof(*cqe));
		memset(&req->big_cqe, 0, sizeof(req->big_cqe));
	}
	return true;
}
```

若 CQ 环已满（应用没及时收割），`io_get_cqe` 失败，完成项进入 `cq_overflow_list` 并累加 `cq_overflow` 计数，等应用腾出空间后由内核补刷。io-wq 线程里的完成走 `io_req_complete_post`，单独加锁填 CQE。完成回填后释放对 `io_kiocb` 的引用，最后一个引用把对象还回请求缓存。

### task_work: Finishing Up Using the Submitter's Context

有些完成工作（如把数据 fixup、收割 multishot）必须在**提交该请求的那个用户进程上下文**里、且需要 `mm` 时才能做。内核不能在硬中断或别的 CPU 上随意强行打断，于是用 **task_work** 机制：`io_req_task_work_add` 把一个回调挂到提交任务的 `task->task_works` 链表，等该任务下次要进入/返回内核（返回用户态前）时执行。

应用侧每次进入 `io_uring_enter` 也会先 `io_run_task_work()` 主动跑掉攒下的 task_work，`io_handle_tw_list` 逐个取出、在持有 `uring_lock` 的情况下调用对应回调（如 `io_poll_task_func`、`io_req_rw_complete`）。为减少无谓的 IPI（核间中断），还有两个优化 flag：

- `IORING_SETUP_COOP_TASKRUN`：协作式运行——等任务反正要切换时再做 task_work，而不是强制用 IPI 打断正在用户态运行的任务；
- `IORING_SETUP_DEFER_TASKRUN`：把 task_work 推迟到真正需要事件（如 `io_uring_enter` 等 GETEVENTS）时才跑。

## Fixed Resources and Advanced Features

### Fixed Files (Fixed File Table)

正常 I/O 每个请求要用 `fget`/`fput` 引用 fd，底层有原子操作与锁。`io_uring_register`（`IORING_REGISTER_FILES` / `..._FILES2`）可预先把一组文件注册进 `ctx->file_table`，之后 SQE 设 `IOSQE_FIXED_FILE`、用 `file_index` 下标引用，走 `io_file_get_fixed`，**每次 I/O 省去 fget/fput 的原子开销**。可用 `FILES_UPDATE`/`FILES_UPDATE2` 增量更新，`IORING_REGISTER_FILE_ALLOC_RANGE` 注册一个可自动分配的槽位区间。

### Registered Buffers (Fixed Buffer)

`IORING_REGISTER_BUFFERS` 预注册一组用户缓冲，内核把它们 [pin 在内存](/docs/CS/OS/Linux/mm/gup.md?id=the-cost-of-longterm)（`io_mapped_ubuf`），之后 `READ_FIXED`/`WRITE_FIXED` 或带 `buf_index` 的操作直接用，免去每次 I/O 的 `pin_user_pages`/解 pin 开销，并支持块层的固定缓冲快速路径。

### Provided Buffers (On-demand Buffer Group)

对于"事先不知道数据多大"的读（典型是服务器 recv），可以用 `PROVIDE_BUFFERS` 或注册 **buffer ring**（`IORING_REGISTER_PBUF_RING`）提供一个缓冲组。SQE 设 `IOSQE_BUFFER_SELECT` + `buf_group`，请求就绪时内核自动从组里挑一个缓冲、把缓冲 ID 放进 CQE 的高 16 位（`IORING_CQE_F_BUFFER`）返回，应用无需提前为每个连接挂起一个缓冲。基于共享环的 PBUF ring 连缓冲的提交/回收都可在用户态完成；`IOU_PBUF_RING_INC` 支持增量消费大缓冲。

### Chained Operations and Multishot

- **`IOSQE_IO_LINK` / `IOSQE_IO_HARDLINK`**：把多个 SQE 串成一条链，前一个成功才执行下一个，可表达"open→read→close""recv→处理→send"工作流；配 `LINK_TIMEOUT` 可给整链加超时。
- **multishot**：`POLL_ADD`、`ACCEPT`、`RECV` 等支持 multishot 标志，一条 SQE 在事件反复到来时**持续产生多个 CQE**，每次 CQE 带 `IORING_CQE_F_MORE` 表示"还有后续"，省去反复重新注册。
- **`IOSQE_CQE_SKIP_SUCCESS`**：请求成功时不产生 CQE（失败仍产生），适合纯串联、只关心异常的中间步骤。

### Zero-copy and Buffer-select Network Send

`SEND_ZC` / `SENDMSG_ZC` 走内核零拷贝发送（与 `MSG_ZEROCOPY` 同源），完成后用带 `IORING_CQE_F_NOTIF` 的通知 CQE 告知内核何时可释放承载页；`IORING_SEND_ZC_REPORT_USAGE` 可让内核报告是否真的零拷贝、还是退回了拷贝。

### Inter-ring Communication MSG_RING

`IORING_OP_MSG_RING` 允许一个环向另一个环直接投递数据（`IORING_MSG_DATA`）甚至传递一个已注册的 fd（`IORING_MSG_SEND_FD`），可用于在同一进程多个环或线程的工作者之间做无锁的工作交接，而不必经额外 IPC。

### URING_CMD and SQE128/CQE32

`IORING_OP_URING_CMD` 让设备驱动注册自己的命令（如 NVMe passthrough、某些网卡/存储命令），配合 `IORING_SETUP_SQE128`（SQE 扩到 128 字节承载 80 字节命令数据）和 `IORING_SETUP_CQE32`（CQE 扩到 32 字节、多 16 字节回传）传递大块命令与结果。

## io-wq: Asynchronous Fallback Thread Pool

当请求无法非阻塞完成、又不能让提交线程阻塞时，io_uring 用 **io-wq**（内核 worker pool，`io_uring/io-wq.c`）在线程上下文阻塞执行。它的 worker 分两类：

- `IO_WQ_BOUND`：受 CPU 亲和性约束、可在需要时阻塞（类似 bound workqueue），用于会阻塞在文件系统/块层的操作；
- `IO_WQ_UNBOUND`：不绑核，用于不受阻塞位置约束的后台工作。

每个 io_ring_ctx 默认有自己的 io-wq，也可通过 `IORING_SETUP_ATTACH_WQ`（传 `wq_fd`）让多个环共享一个线程池；可用 `IORING_REGISTER_IOWQ_MAX_WORKERS` 限制 worker 数、`IORING_REGISTER_IOWQ_AFF` 设置 worker 的 CPU 亲和性。io-wq 使 io_uring 即使面对只支持阻塞语义的旧文件系统也能对外呈现统一的异步接口——内联完成、poll、io-wq 三条路径对应用透明。

## Security and Limitations

io_uring 把大量内核操作暴露到共享内存接口，历史上多次成为本地提权漏洞的来源，因此内核加了多层限制：

- **环禁用态**：`IORING_SETUP_R_DISABLED` 让环创建后暂不可提交，注册完资源和限制策略后再用 `IORING_REGISTER_ENABLE_RINGS` 启用。
- **restriction（限制策略）**：`IORING_REGISTER_RESTRICTIONS` 可限定该环允许哪些 SQE opcode、哪些 SQE flags、哪些 register 操作，常用于把环交给可信度较低的组件（如沙箱、seccomp 用户）。
- **特权与记账**：注册固定缓冲（pin 内存）需要相应的 locked-memory 额度，`io_uring_create` 中对非 `CAP_IPC_LOCK` 用户做记账；很多发行版（如部分容器默认 seccomp）会封禁 io_uring 系统调用。
- 实际部署在容器/多租户环境中时，应通过 seccomp 或 sysctl 控制 io_uring 的可用性，不应默认对不可信工作负载开放。

## Links

- [IO 总览（五种模型）](/docs/CS/OS/Linux/IO/IO.md)
- [multiplexing（select/poll/epoll）](/docs/CS/OS/Linux/IO/multiplexing.md)
- [epoll 详解](/docs/CS/OS/Linux/IO/epoll.md)
- [DPDK（内核旁路）](/docs/CS/OS/Linux/IO/DPDK.md)
- [零拷贝 ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)
- [Nginx Event](/docs/CS/CN/nginx/event.md)

## References

1. [Efficient IO with io_uring — Jens Axboe](https://kernel.dk/io_uring.pdf)
2. [What's new with io_uring — Jens Axboe](https://kernel.dk/io_uring-whatsnew.pdf)
3. [io_uring documentation — kernel.org](https://www.kernel.org/doc/html/latest/io_uring/index.html)
4. [io_uring(7) — Linux manual page](https://man7.org/linux/man-pages/man7/io_uring.7.html)
5. [An Introduction to the io_uring Asynchronous I/O Framework — Oracle Linux](https://blogs.oracle.com/site/linux/post/an-introduction-to-the-io-uring-asynchronous-io-framework)
