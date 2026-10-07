## Introduction

KVM（Kernel-based Virtual Machine）不是一个独立的虚拟机软件，而是**内核里的一个模块**：它把 Linux 内核本身变成一个 hypervisor。加载 `kvm.ko` + `kvm-intel.ko`（或 `kvm-amd.ko`）之后，内核多出一个字符设备 `/dev/kvm`，用户态程序打开它、发 ioctl，就能创建虚拟机。

这个设计带来一个常被误读的分类问题。按 [虚拟机](/docs/CS/OS/VM.md) 的 Type-1 / Type-2 划分，KVM 看上去像 Type-2——它"跑在操作系统上"。但真正跑 guest 代码时，vCPU 是直接在物理 CPU 上以 guest 模式执行的，host 内核退到一边，只负责处理退出事件；从"谁在裸机上执行指令"这个角度看，它和 Type-1 没有区别。所以准确的说法是：**KVM 是用 Type-2 的组织形式，达成 Type-1 的执行效率**——借 host 内核现成的调度器、内存管理、设备驱动，省掉一整套独立的 VMM。

理解 KVM 的第一个关键是**它只做三件事，剩下的全交给用户态**：

| 职责 | 归属 | 原因 |
|---|---|---|
| CPU 虚拟化（VMX/SVM 进入退出、VMCS 管理） | KVM 内核 | 需要最高特权级，且退出处理在内核做最快 |
| 内存虚拟化（EPT/NPT 二维页表、影子页表） | KVM 内核 | 缺页是热路径，放内核避免每次退出到用户态 |
| 中断虚拟化（LAPIC / IOAPIC / PIC 建模） | KVM 内核 | 中断注入同样热，且能直接用 posted interrupt |
| **设备模拟**（磁盘、网卡、显卡、BIOS/ACPI） | 用户态（[QEMU](/docs/CS/OS/qemu.md)） | 设备模型复杂多变，放内核会让内核膨胀且不稳定 |
| 固件、启动、迁移、快照 | 用户态 | 纯策略问题，内核不该管 |

这个切分是刻意的：把机制放内核、策略放用户态。KVM 因此只有几万行，而 QEMU 有上百万行。

第二个关键是**所有控制面都是 fd + ioctl**，没有自定义系统调用。本节后面会看到，一个虚拟机被拆成三个 fd，且第三个 fd 的数据交互不走 read/write，而是 mmap 共享页——这个取舍直接决定了 KVM 的性能特征。

## Three fd Models

KVM 把虚拟机的一切都表达成文件描述符，形成一条三层链：

```
open("/dev/kvm")          →  kvm fd     系统级：查询能力、创建 VM
  └─ KVM_CREATE_VM        →  vm fd      VM 级：建内存、建 vCPU、建中断芯片
       └─ KVM_CREATE_VCPU →  vcpu fd    vCPU 级：KVM_RUN、读写寄存器
```

### ① /dev/kvm: A misc Device

KVM 复用了 [miscdevice](/docs/CS/OS/Linux/dev/char.md?id=shortcut-miscdevice) 机制，主设备号固定 10、次设备号 `KVM_MINOR`：

```c
static struct file_operations kvm_chardev_ops = {
	.unlocked_ioctl = kvm_dev_ioctl,
	.llseek		= noop_llseek,
	KVM_COMPAT(kvm_dev_ioctl),
};

static struct miscdevice kvm_dev = {
	KVM_MINOR,
	"kvm",
	&kvm_chardev_ops,
};
```

注意 fops 里**没有 open/read/write**——系统级 fd 上只有三个 ioctl 有意义：`KVM_GET_API_VERSION`（恒为 12）、`KVM_CREATE_VM`、`KVM_CHECK_EXTENSION`，以及 `KVM_GET_VCPU_MMAP_SIZE`。其余交给 `kvm_arch_dev_ioctl()`。

`KVM_GET_VCPU_MMAP_SIZE` 的返回值直接体现了 vCPU fd 的共享页布局：

```c
	case KVM_GET_VCPU_MMAP_SIZE:
		if (arg)
			goto out;
		r = PAGE_SIZE;     /* struct kvm_run */
#ifdef CONFIG_X86
		r += PAGE_SIZE;    /* pio data page */
#endif
#ifdef CONFIG_KVM_MMIO
		r += PAGE_SIZE;    /* coalesced mmio ring page */
#endif
		break;
```

即：第 0 页是 `struct kvm_run`（**每次退出的原因与数据都写在这里**），x86 上第 1 页是 PIO 数据页，第 2 页是合并 MMIO 环形缓冲；若启用了脏页环，后面还跟着若干页。

### ② VM fd and vCPU fd: Anonymous inode

后两个 fd 都不是真实文件，而是用 `anon_inode_getfd()` 造出来的匿名 inode：

```c
static int create_vcpu_fd(struct kvm_vcpu *vcpu)
{
	char name[8 + 1 + ITOA_MAX_LEN + 1];

	snprintf(name, sizeof(name), "kvm-vcpu:%d", vcpu->vcpu_id);
	return anon_inode_getfd(name, &kvm_vcpu_fops, vcpu, O_RDWR | O_CLOEXEC);
}
```

vCPU fd 的 fops 里同样**没有 read/write**：

```c
static struct file_operations kvm_vcpu_fops = {
	.release        = kvm_vcpu_release,
	.unlocked_ioctl = kvm_vcpu_ioctl,
	.mmap           = kvm_vcpu_mmap,
	.llseek		= noop_llseek,
	KVM_COMPAT(kvm_vcpu_compat_ioctl),
};
```

这不是遗漏，而是核心设计：**vCPU 与用户态之间绝不用 read/write 拷贝数据**。高频的退出信息通过 `mmap(vcpu_fd, 0)` 得到的共享页传递，ioctl 只承担"启动/停止/配置"这类低频控制。缺页处理函数把不同的页偏移映射到不同内核页：

```c
static vm_fault_t kvm_vcpu_fault(struct vm_fault *vmf)
{
	struct kvm_vcpu *vcpu = vmf->vma->vm_file->private_data;
	struct page *page;

	if (vmf->pgoff == 0)
		page = virt_to_page(vcpu->run);
#ifdef CONFIG_X86
	else if (vmf->pgoff == KVM_PIO_PAGE_OFFSET)
		page = virt_to_page(vcpu->arch.pio_data);
#endif
#ifdef CONFIG_KVM_MMIO
	else if (vmf->pgoff == KVM_COALESCED_MMIO_PAGE_OFFSET)
		page = virt_to_page(vcpu->kvm->coalesced_mmio_ring);
#endif
	else if (kvm_page_in_dirty_ring(vcpu->kvm, vmf->pgoff))
		page = kvm_dirty_ring_get_page(
		    &vcpu->dirty_ring,
		    vmf->pgoff - KVM_DIRTY_LOG_PAGE_OFFSET);
	else
		return kvm_arch_vcpu_fault(vcpu, vmf);
	get_page(page);
	vmf->page = page;
	return 0;
}
```

一个真实的取舍摆在这里：共享页**可被用户态任意时刻改写**，内核读它就可能踩 TOCTOU。UAPI 头文件里为此专门定义了一个宏，让内核编译时把字段名改掉，逼每个使用者显式确认：

```c
 * struct kvm_run can be modified by userspace at any time, so KVM must be
 * careful to avoid TOCTOU bugs. In order to protect KVM, HINT_UNSAFE_IN_KVM()
 * renames fields in struct kvm_run from <symbol> to <symbol>__unsafe when
 * compiled into the kernel, ensuring that any use within KVM is obvious and
 * gets extra scrutiny.
 */
#ifdef __KERNEL__
#define HINT_UNSAFE_IN_KVM(_symbol) _symbol##__unsafe
#else
#define HINT_UNSAFE_IN_KVM(_symbol) _symbol
#endif
```

所以内核代码里出现的是 `vcpu->run->immediate_exit__unsafe`——那个 `__unsafe` 后缀不是变量名的一部分，而是编译器层面的提醒。

### ③ struct kvm_run: Exit Information

```c
/* for KVM_RUN, returned by mmap(vcpu_fd, offset=0) */
struct kvm_run {
	/* in */
	__u8 request_interrupt_window;
	__u8 HINT_UNSAFE_IN_KVM(immediate_exit);
	__u8 padding1[6];

	/* out */
	__u32 exit_reason;
	__u8 ready_for_interrupt_injection;
	__u8 if_flag;
	__u16 flags;
	...
```

`exit_reason` 是唯一的退出分类，共 40 种（`KVM_EXIT_IO` 端口 I/O、`KVM_EXIT_MMIO` 内存映射 I/O、`KVM_EXIT_HLT`、`KVM_EXIT_IRQ_WINDOW_OPEN`、`KVM_EXIT_DIRTY_RING_FULL`……）。不同 reason 对应 union 里不同的结构体，例如 MMIO 退出：

```c
		/* KVM_EXIT_MMIO */
		struct {
			__u64 phys_addr;
			__u8  data[8];
			__u32 len;
			__u8  is_write;
		} mmio;
	union {
		...
		/* Fix the size of the union. */
		char padding[256];
	};
```

union 尾部那个 `padding[256]` 是为了固定大小——结构体大小是 ABI 的一部分，不能随内核演进变动。

## Data Structures

### struct kvm: A Virtual Machine

```c
struct kvm {
	spinlock_t mmu_lock;          /* 或 rwlock_t，取决于架构 */

	struct mutex slots_lock;      /* 保护 memslot 集合的变更 */
	struct mutex slots_arch_lock;
	struct mm_struct *mm;         /* 绑定到的用户态进程地址空间 */
	unsigned long nr_memslot_pages;
	/* The two memslot sets - active and inactive (per address space) */
	struct kvm_memslots __memslots[KVM_MAX_NR_ADDRESS_SPACES][2];
	/* The current active memslot set for each address space */
	struct kvm_memslots __rcu *memslots[KVM_MAX_NR_ADDRESS_SPACES];
	struct xarray vcpu_array;
	...
	struct kvm_io_bus __rcu *buses[KVM_NR_BUSES];
	struct list_head ioeventfds;
	...
	struct mmu_notifier mmu_notifier;
};
```

几个要点：

- **`mm` 字段把虚拟机绑死到一个用户态进程**。vCPU 运行前内核要切到这个地址空间，因为 guest 的物理内存就是 QEMU 进程的普通匿名内存。ioctl 入口那句 `if (vcpu->kvm->mm != current->mm ...) return -EIO` 就是在守这个约束。
- **双 memslot 集（active / inactive）** 配合 SRCU，使得"修改内存布局"和"正在跑的 vCPU 查询 memslot"可以并发：改的时候写 inactive 那份，改完原子换指针，旧的那份靠 SRCU 宽限期之后再释放。
- **`buses[]`** 是 I/O 总线数组，把 PIO 与 MMIO 注册的设备按总线号分桶——这是设备模拟的挂接点。
- **`mmu_notifier`**：host 侧换页/回收内存时要通知 KVM 拆掉对应的 EPT 映射，否则 guest 会访问到已回收的物理页。

### struct kvm_vcpu: A Virtual CPU

```c
struct kvm_vcpu {
	struct kvm *kvm;
	int cpu;
	int vcpu_id; /* id given by userspace at creation */
	int vcpu_idx; /* index into kvm->vcpu_array */
	int ____srcu_idx; /* Don't use this directly.  You've been warned. */
	int mode;
	u64 requests;
	unsigned long guest_debug;

	struct mutex mutex;
	struct kvm_run *run;
	...
	unsigned int halt_poll_ns;
	...
	struct kvm_vcpu_arch arch;
	struct kvm_vcpu_stat stat;
	struct kvm_dirty_ring dirty_ring;
	struct kvm_memory_slot *last_used_slot;
	u64 last_used_slot_gen;
};
```

两个字段决定了 vCPU 的行为模型：

**`mode`** 描述"这个 vCPU 线程现在在哪一层"，共四态：

```c
	OUTSIDE_GUEST_MODE,
	IN_GUEST_MODE,
	EXITING_GUEST_MODE,
	READING_SHADOW_PAGE_TABLES,
```

状态切换要用 cmpxchg，不是简单赋值：

```c
	return cmpxchg(&vcpu->mode, IN_GUEST_MODE, EXITING_GUEST_MODE);
```

原因值得琢磨：其他 CPU 想让某个 vCPU 退出 guest（比如要 flush TLB），它不能强行把对方拽出来，只能改 mode 并 IPI；正在跑 guest 的那个线程自己在退出时再检查这个标记。而 `EXITING_GUEST_MODE` 这个中间态就是为了区分"我已响应，正在退出"和"我还没看到请求"，避免重复发 IPI。

**`requests`** 是一个位图，表示"下次进入 guest 前必须先处理的事"：`KVM_REQ_TLB_FLUSH`、`KVM_REQ_MMU_SYNC`、`KVM_REQ_CLOCK_UPDATE`、`KVM_REQ_NMI`、`KVM_REQ_TRIPLE_FAULT`……请求方只需 `kvm_make_request()` 置位 + 必要时 kick，真正处理集中在进入 guest 前的一个地方。这是典型的"请求—延迟执行"模式，和 [workqueue](/docs/CS/OS/Linux/workqueue.md) 里 pending 队列的思路同源：把并发写变成串行处理，简化加锁。

### struct kvm_memory_slot: The Registration Unit of Guest Memory

guest 的物理内存不是 KVM 分配的，而是 **QEMU 先 mmap 一大块 userspace 内存，再告诉内核"这段对应 guest 物理地址 X"**。这个对应关系就叫 memslot：

```c
struct kvm_memory_slot {
	struct hlist_node id_node[2];
	struct interval_tree_node hva_node[2];
	struct rb_node gfn_node[2];
	gfn_t base_gfn;
	unsigned long npages;
	unsigned long *dirty_bitmap;
	struct kvm_arch_memory_slot arch;
	unsigned long userspace_addr;
	u32 flags;
	short id;
	u16 as_id;
};
```

注意那三棵树各有 **2 份**（`[2]`）—— 又是 active/inactive 双缓冲。三棵树服务于三种查询：

| 树 | 索引 | 用于 |
|---|---|---|
| `id_node` 哈希 | slot id | 按 id 精确查找（增删、脏页日志） |
| `hva_node` 区间树 | host 虚拟地址区间 | mmu notifier 收到 host 地址时要反查是哪个 slot |
| `gfn_node` 红黑树 | guest 页框号 | guest 访问某 GPA 时查它属于哪个 slot（热路径） |

```c
struct kvm_memslots {
	u64 generation;
	atomic_long_t last_used_slot;
	struct rb_root_cached hva_tree;
	struct rb_root gfn_tree;
	DECLARE_HASHTABLE(id_hash, 7);
	int node_idx;
};
```

id 哈希表的桶数是 `1 << 7`，注释解释了为什么是 7：

```c
	 * 7-bit bucket count matches the size of the old id to index array for
	 * 512 slots, while giving good performance with this slot count.
	 * Higher bucket counts bring only small performance improvements but
	 * always result in higher memory usage (even for lower slot counts).
```

slot 数量上限是 `KVM_MEM_SLOTS_NUM = SHRT_MAX`（32767）。

## ioctl's Three-layer Grouping

ioctl 编号按作用对象分了三段，看编号就能判断属于哪层：

| 段 | 编号范围 | 作用对象 | 代表 ioctl |
|---|---|---|---|
| 系统级 | `0x00`–`0x0a` | `/dev/kvm` fd | `KVM_GET_API_VERSION`、`KVM_CREATE_VM`、`KVM_CHECK_EXTENSION` |
| VM 级 | `0x40`–`0x7f` | VM fd | `KVM_CREATE_VCPU`、`KVM_SET_USER_MEMORY_REGION`、`KVM_CREATE_IRQCHIP`、`KVM_IRQFD`、`KVM_IOEVENTFD`、`KVM_SET_GSI_ROUTING` |
| vCPU 级 | `0x80`– | vCPU fd | `KVM_RUN`、`KVM_GET_REGS`/`KVM_SET_REGS`、`KVM_GET_SREGS`、`KVM_SET_CPUID2`、`KVM_GET_MSRS` |

VM 级里最要紧的是 `KVM_SET_USER_MEMORY_REGION`，它就是前面 memslot 的注册接口；`KVM_CREATE_IRQCHIP` 决定中断芯片由内核建模还是留给 QEMU——这个选择会改变很多退出路径的走向。

## vCPU Run Loop

一切收敛到一个 ioctl：`KVM_RUN`。QEMU 的每个 vCPU 有一个宿主线程，线程主体就是一个循环：反复发 `KVM_RUN`，按返回的 `exit_reason` 处理，再发下一次。内核侧入口很简单：

```c
static long kvm_vcpu_ioctl(struct file *filp,
			   unsigned int ioctl, unsigned long arg)
{
	struct kvm_vcpu *vcpu = filp->private_data;
	...
	if (vcpu->kvm->mm != current->mm || vcpu->kvm->vm_dead)
		return -EIO;

	if (unlikely(_IOC_TYPE(ioctl) != KVMIO))
		return -EINVAL;
	...
	case KVM_RUN: {
		struct pid *oldpid;
		r = -EINVAL;
		if (arg)
			goto out;
		oldpid = rcu_access_pointer(vcpu->pid);
		if (unlikely(oldpid != task_pid(current))) {
			/* The thread running this VCPU changed. */
			...
		}
		vcpu->wants_to_run = !READ_ONCE(vcpu->run->immediate_exit__unsafe);
		r = kvm_arch_vcpu_ioctl_run(vcpu);
		vcpu->wants_to_run = false;

		trace_kvm_userspace_exit(vcpu->run->exit_reason, r);
		break;
	}
```

x86 上 `kvm_arch_vcpu_ioctl_run()` 落到两层循环。

### Outer Layer: vcpu_run — Decide Whether to Return to User Space

```c
static int vcpu_run(struct kvm_vcpu *vcpu)
{
	int r;

	vcpu->run->exit_reason = KVM_EXIT_UNKNOWN;

	for (;;) {
		vcpu->arch.at_instruction_boundary = false;
		if (kvm_vcpu_running(vcpu)) {
			r = vcpu_enter_guest(vcpu);
		} else {
			r = vcpu_block(vcpu);
		}

		if (r <= 0)
			break;
		...
		if (dm_request_for_irq_injection(vcpu) &&
			kvm_vcpu_ready_for_interrupt_injection(vcpu)) {
			r = 0;
			vcpu->run->exit_reason = KVM_EXIT_IRQ_WINDOW_OPEN;
			++vcpu->stat.request_irq_exits;
			break;
		}
		...
	}

	return r;
}
```

约定是 `r <= 0` 才返回用户态，`r > 0` 表示"内核自己处理完了，继续跑 guest"。所以**绝大多数退出根本不会回到 QEMU**——只有内核处理不了（设备 I/O、需要用户态决策）才退出。这个判断是 KVM 性能的源头。

`KVM_EXIT_IRQ_WINDOW_OPEN` 是个精巧的设计：当有待注入中断但 guest 当前关中断（IF=0）时，内核不是干等，而是退出告诉 QEMU"我先出来了，等 guest 开中断的那一刻再叫我"——QEMU 下一轮 `KVM_RUN` 时内核才注入。

### Inner Layer: vcpu_enter_guest — Handle All Requests Before Entering

进入 guest 之前有一段很长的"请求兑现"清单：

```c
static int vcpu_enter_guest(struct kvm_vcpu *vcpu)
{
	int r;
	bool req_int_win =
		dm_request_for_irq_injection(vcpu) &&
		kvm_cpu_accept_dm_intr(vcpu);
	fastpath_t exit_fastpath;

	bool req_immediate_exit = false;

	if (kvm_request_pending(vcpu)) {
		if (kvm_check_request(KVM_REQ_VM_DEAD, vcpu)) {
			r = -EIO;
			goto out;
		}

		if (kvm_dirty_ring_check_request(vcpu)) {
			r = 0;
			goto out;
		}
		...
		if (kvm_check_request(KVM_REQ_MMU_SYNC, vcpu))
			kvm_mmu_sync_roots(vcpu);
		if (kvm_check_request(KVM_REQ_LOAD_MMU_PGD, vcpu))
			kvm_mmu_load_pgd(vcpu);

		/*
		 * Note, the order matters here, as flushing "all" TLB entries
		 * also flushes the "current" TLB entries, i.e. servicing the
		 * flush "all" will clear any request to flush "current".
		 */
		if (kvm_check_request(KVM_REQ_TLB_FLUSH, vcpu))
			kvm_vcpu_flush_tlb_all(vcpu);
		...
```

顺序不是随意的——注释专门指出 flush all 会顺带清掉 flush current 的请求，所以必须先处理 all。这类顺序约束在 KVM 里很多，也是它难改的原因。

随后是中断/事件注入，以及真正进入前的一串准备：禁抢占、关中断、置 `IN_GUEST_MODE`：

```c
	preempt_disable();

	kvm_x86_call(prepare_switch_to_guest)(vcpu);

	/*
	 * Disable IRQs before setting IN_GUEST_MODE.  Posted interrupt
	 * IPI are then delayed after guest entry, which ensures that they
	 * result in virtual interrupt delivery.
	 */
	local_irq_disable();

	/* Store vcpu->apicv_active before vcpu->mode.  */
	smp_store_release(&vcpu->mode, IN_GUEST_MODE);

	kvm_vcpu_srcu_read_unlock(vcpu);

	/*
	 * 1) We should set ->mode before checking ->requests.  Please see
	 * the comment in kvm_vcpu_exiting_guest_mode().
	 *
	 * 2) For APICv, we should set ->mode before checking PID.ON. This
	 * pairs with the memory barrier implicit in pi_test_and_set_on
	 * (see vmx_deliver_posted_interrupt).
	 *
	 * 3) This also orders the write to mode from any reads to the page
	 * tables done while the VCPU is running.  Please see the comment
	 * in kvm_flush_remote_tlbs.
	 */
	smp_mb__after_srcu_read_unlock();
```

注意 `kvm_vcpu_srcu_read_unlock()`：**进入 guest 前要主动释放 SRCU 读锁**。因为 guest 可能跑一整个时间片，持有 SRCU 读锁会阻塞别人的宽限期。这也意味着 guest 期间不能访问任何 SRCU 保护的数据——KVM 把 guest 模式当作一种"扩展静默态"，类似用户态执行：

```c
static __always_inline void guest_context_enter_irqoff(void)
{
	/*
	 * KVM does not hold any references to rcu protected data when it
	 * switches CPU into a guest mode. In fact switching to a guest mode
	 * is very similar to exiting to userspace from rcu point of view. In
	 * addition CPU may stay in a guest mode for quite a long time (up to
	 * one time slice). Lets treat guest mode as quiescent state, just like
	 * we do with user-mode execution.
	 */
	if (!context_tracking_guest_enter()) {
		instrumentation_begin();
		rcu_virt_note_context_switch();
		instrumentation_end();
	}
}
```

### The Real Entry: A Loop

```c
	for (;;) {
		exit_fastpath = kvm_x86_call(vcpu_run)(vcpu,
						       req_immediate_exit);
		if (likely(exit_fastpath != EXIT_FASTPATH_REENTER_GUEST))
			break;

		if (kvm_lapic_enabled(vcpu))
			kvm_x86_call(sync_pir_to_irr)(vcpu);

		if (unlikely(kvm_vcpu_exit_request(vcpu))) {
			exit_fastpath = EXIT_FASTPATH_EXIT_HANDLED;
			break;
		}

		/* Note, VM-Exits that go down the "slow" path are accounted below. */
		++vcpu->stat.exits;
	}
```

`EXIT_FASTPATH_REENTER_GUEST` 表示"这次退出内核已完全消化，不必回到外层循环，直接再进 guest"。像 HLT（有 in-kernel LAPIC 时）、PAUSE、某些 EPT 违规都走这条路，省掉了重新检查请求的开销。

三个 fastpath 取值的含义：

| 返回值 | 含义 |
|---|---|
| `EXIT_FASTPATH_REENTER_GUEST` | 内核已处理完，立刻重进 guest，不回外层 |
| `EXIT_FASTPATH_EXIT_HANDLED` | 内核已处理完，但需回外层重新判断（如 vCPU 变成不可运行） |
| `EXIT_FASTPATH_EXIT_USERSPACE` | 处理不了，退出到 QEMU |

以 HLT 为例，这个三分支很直观：

```c
fastpath_t handle_fastpath_hlt(struct kvm_vcpu *vcpu)
{
	int ret;

	kvm_vcpu_srcu_read_lock(vcpu);
	ret = kvm_emulate_halt(vcpu);
	kvm_vcpu_srcu_read_unlock(vcpu);

	if (!ret)
		return EXIT_FASTPATH_EXIT_USERSPACE;

	if (kvm_vcpu_running(vcpu))
		return EXIT_FASTPATH_REENTER_GUEST;

	return EXIT_FASTPATH_EXIT_HANDLED;
}
```

而"HLT 之后到底退不退出"取决于 LAPIC 在哪建模：

```c
static int __kvm_emulate_halt(struct kvm_vcpu *vcpu, int state, int reason)
{
	/*
	 * The vCPU has halted, e.g. executed HLT.  Update the run state if the
	 * local APIC is in-kernel, the run loop will detect the non-runnable
	 * state and halt the vCPU.  Exit to userspace if the local APIC is
	 * managed by userspace, in which case userspace is responsible for
	 * handling wake events.
	 */
	++vcpu->stat.halt_exits;
	if (lapic_in_kernel(vcpu)) {
		if (kvm_vcpu_has_events(vcpu))
			vcpu->arch.pv.pv_unhalted = false;
		else
			vcpu->arch.mp_state = state;
		return 1;
	} else {
		vcpu->run->exit_reason = reason;
		return 0;
	}
}
```

**这就是 `KVM_CREATE_IRQCHIP` 的价值**：中断芯片在内核里时，guest 执行 HLT 只是一次 fastpath 重入；在用户态时，每次 HLT 都要退出到 QEMU——而 idle 的 guest 每秒会 HLT 成千上万次。

## VM-Exit Dispatch

硬件退出原因到处理函数的映射是一张静态数组，用退出码直接索引：

```c
static int (*kvm_vmx_exit_handlers[])(struct kvm_vcpu *vcpu) = {
	[EXIT_REASON_EXCEPTION_NMI]           = handle_exception_nmi,
	[EXIT_REASON_EXTERNAL_INTERRUPT]      = handle_external_interrupt,
	[EXIT_REASON_TRIPLE_FAULT]            = handle_triple_fault,
	[EXIT_REASON_IO_INSTRUCTION]          = handle_io,
	[EXIT_REASON_CR_ACCESS]               = handle_cr,
	[EXIT_REASON_CPUID]                   = kvm_emulate_cpuid,
	[EXIT_REASON_MSR_READ]                = kvm_emulate_rdmsr,
	[EXIT_REASON_MSR_WRITE]               = kvm_emulate_wrmsr,
	[EXIT_REASON_INTERRUPT_WINDOW]        = handle_interrupt_window,
	[EXIT_REASON_HLT]                     = kvm_emulate_halt,
	[EXIT_REASON_INVLPG]		      = handle_invlpg,
	[EXIT_REASON_VMCALL]                  = kvm_emulate_hypercall,
	[EXIT_REASON_APIC_ACCESS]             = handle_apic_access,
	[EXIT_REASON_APIC_WRITE]              = handle_apic_write,
	[EXIT_REASON_EPT_VIOLATION]	      = handle_ept_violation,
	[EXIT_REASON_EPT_MISCONFIG]           = handle_ept_misconfig,
	[EXIT_REASON_PAUSE_INSTRUCTION]       = handle_pause,
	[EXIT_REASON_PREEMPTION_TIMER]	      = handle_preemption_timer,
	[EXIT_REASON_BUS_LOCK]                = handle_bus_lock_vmexit,
	[EXIT_REASON_NOTIFY]		      = handle_notify,
};

static const int kvm_vmx_max_exit_handlers =
	ARRAY_SIZE(kvm_vmx_exit_handlers);
```

数组形式（而非 switch）的好处是分派为一次间接跳转，且新增退出码只是加一行。这张表也是理解"哪些操作会退出"的最好索引：CPUID、RDMSR/WRMSR、CR 访问、I/O 指令、HLT、PAUSE、EPT 违规、APIC 访问……

## CPU Virtualization: VMX Dual Modes

Intel VT-x 引入了 root / non-root 两种运行模式，host 在 root、guest 在 non-root，两者都有完整的 ring0–ring3。切换由 VMCS（Virtual Machine Control Structure）这块内存控制，KVM 里每个 vCPU 一个 VMCS，用 `vmcs_writel()` 写字段。

进入 guest 前要做的收尾工作都在 `vmx_vcpu_run()` 里：

```c
fastpath_t vmx_vcpu_run(struct kvm_vcpu *vcpu, bool force_immediate_exit)
{
	struct vcpu_vmx *vmx = to_vmx(vcpu);
	unsigned long cr3, cr4;

	/*
	 * Don't enter VMX if guest state is invalid, let the exit handler
	 * start emulation until we arrive back to a valid state.  Synthesize a
	 * consistency check VM-Exit due to invalid guest state and bail.
	 */
	if (unlikely(vmx->emulation_required)) {
		vmx->fail = 0;

		vmx->exit_reason.full = EXIT_REASON_INVALID_STATE;
		vmx->exit_reason.failed_vmentry = 1;
		...
		return EXIT_FASTPATH_NONE;
	}
```

一个细节：如果 guest 状态非法（比如 QEMU 刚 reset 完还没设好寄存器），硬件的 VMENTRY 会失败。KVM 的做法是**不真的去试**，而是伪造一次"一致性检查失败"的退出，交给模拟代码慢慢把状态修好——避免昂贵的失败进入。

进入前要把 CPU 状态同步进 VMCS：

```c
	if (kvm_register_is_dirty(vcpu, VCPU_REGS_RSP))
		vmcs_writel(GUEST_RSP, vcpu->arch.regs[VCPU_REGS_RSP]);
	if (kvm_register_is_dirty(vcpu, VCPU_REGS_RIP))
		vmcs_writel(GUEST_RIP, vcpu->arch.regs[VCPU_REGS_RIP]);
	vcpu->arch.regs_dirty = 0;

	/*
	 * Refresh vmcs.HOST_CR3 if necessary.  This must be done immediately
	 * prior to VM-Enter, as the kernel may load a new ASID (PCID) any time
	 * it switches back to the current->mm, which can occur in KVM context
	 * when switching to a temporary mm to patch kernel code, e.g. if KVM
	 * toggles a static key while handling a VM-Exit.
	 */
	cr3 = __get_current_cr3_fast();
	if (unlikely(cr3 != vmx->loaded_vmcs->host_state.cr3)) {
		vmcs_writel(HOST_CR3, cr3);
		vmx->loaded_vmcs->host_state.cr3 = cr3;
	}
```

`HOST_CR3` 必须在**紧邻 VM-Enter 之前**刷新——注释解释了原因：处理 VM-Exit 期间内核可能切换临时 mm（比如 patch 静态键），那时 CR3 会变，而 VMCS 里记的 host CR3 就会过期。用陈旧 CR3 返回 host 会立刻崩。

真正的切换指令在一个特殊段里：

```c
	/* The actual VMENTER/EXIT is in the .noinstr.text section. */
	vmx_vcpu_enter_exit(vcpu, __vmx_vcpu_run_flags(vmx));
```

`.noinstr.text` 表示这段代码**不允许被插桩**（tracepoint、kprobes、sanitizer 全部绕开）。因为在 VMENTER 与 VMEXIT 之间，CPU 跑的是 guest，任何插桩代码都可能踩到 guest 的状态或引入不可控延迟。

退出后还有一个容易忽略的动作：

```c
	if (is_guest_mode(vcpu)) {
		/*
		 * Track VMLAUNCH/VMRESUME that have made past guest state
		 * checking.
		 */
		if (vmx->nested.nested_run_pending &&
		    !vmx->exit_reason.failed_vmentry)
			++vcpu->stat.nested_run;

		vmx->nested.nested_run_pending = 0;
	}
```

`is_guest_mode()` 为真说明是**嵌套虚拟化**——guest 自己也是个 hypervisor，它里面还有一层 guest。KVM 支持 L1 管理 L2，代价是 VMCS 要做影子同步（`nested` 那一大坨状态机）。

## Memory Virtualization

### Three-level Address Translation

guest 的一次内存访问要过两级翻译，因此有四类地址：

```
GVA (guest 虚拟地址)
  ↓  guest 页表（CR3 指向，由 guest OS 维护，KVM 不信任）
GPA (guest 物理地址)
  ↓  memslot: GPA → HVA（纯算术：userspace_addr + (gpa - base_gfn << PAGE_SHIFT)）
HVA (host 虚拟地址，QEMU 进程地址空间)
  ↓  host 页表 / get_user_pages
HPA (host 物理地址)
```

第二步在内核里就是这个函数：

```c
kvm_pfn_t __gfn_to_pfn_memslot(const struct kvm_memory_slot *slot, gfn_t gfn,
			       bool atomic, bool interruptible, bool *async,
			       bool write_fault, bool *writable, hva_t *hva)
{
	unsigned long addr = __gfn_to_hva_many(slot, gfn, NULL, write_fault);

	if (hva)
		*hva = addr;

	if (kvm_is_error_hva(addr)) {
		if (writable)
			*writable = false;

		return addr == KVM_HVA_ERR_RO_BAD ? KVM_PFN_ERR_RO_FAULT :
						    KVM_PFN_NOSLOT;
	}

	/* Do not map writable pfn in the readonly memslot. */
	if (writable && memslot_is_readonly(slot)) {
		*writable = false;
		writable = NULL;
	}

	return hva_to_pfn(addr, atomic, interruptible, async, write_fault,
			  writable);
}
```

要点：GPA→HVA 是**纯算术、绝不失败**（除非 GPA 不在任何 slot 里，返回 `KVM_PFN_NOSLOT`）；真正的开销在 HVA→PFN，它走的是 host 的页表与 `get_user_pages()`——也就是说 **guest 的内存就是 QEMU 进程的普通匿名页**，会被 host 的 [虚拟内存管理](/docs/CS/OS/Linux/mm/vm.md) 换出、回收、透明大页合并。KVM 不额外持有内存。

这里的 `get_user_pages()` 用的是**普通引用**（配 `put_page()`），而不是 pin（配 `unpin_user_page()`）——所以 guest 内存才换得出去、迁得动。这个选择正是"KVM 不额外持有内存"的实现依据：如果改成 [长期 pin](/docs/CS/OS/Linux/mm/gup.md?id=the-cost-of-longterm)，guest 的每一页都会被钉死在非 movable zone 里，host 的内存热插拔、CMA、乃至回收都会连带失效。

反过来说，host 换出页面时必须通知 KVM 拆 EPT 映射，这就是 `struct kvm.mmu_notifier` 的作用：它是 host 内存管理向虚拟化层开的回调口。

### Two Modes: Shadow Page Table vs Two-dimensional Page Table

**影子页表（shadow paging）**：硬件只有一套页表，KVM 就维护一份"GVA→HPA"的影子页表给硬件用，guest 自己那份 GVA→GPA 的页表被 KVM 藏起来（把 guest CR3 换成影子页表的物理地址）。guest 每次改页表都要退出，KVM 同步影子页表。代价极高，但因为硬件不要求，是老 CPU 上的唯一选择。

**二维页表（TDP / EPT / NPT）**：硬件支持两层翻译，KVM 只需维护 GPA→HPA 那层（EPT），guest 自己的 GVA→GPA 页表由硬件自动 walked。guest 切页表（写 CR3）不再需要退出。现代 x86 上都走这条路，模块参数默认开：

```c
bool __read_mostly enable_ept = 1;
module_param_named(ept, enable_ept, bool, 0444);
```

把这两层翻译对照回 Linux 自己：guest 的 GVA→GPA 与 EPT 的 GPA→HPA 是**两级串联**，而 host 侧页表本身的构造与维护方式（多级布局、表项位布局、页表页生命周期、TLB 失效）是另一套机制，见 [页表](/docs/CS/OS/Linux/mm/pagetable.md)。值得一提的两者是**同源抽象**：都靠一张函数指针表把架构差异挡在核心逻辑之外——KVM 用 `struct kvm_mmu`，host 内存管理用 `pagetable_*_ctor` 族与 `__pte_offset_map` 系列，思路是同一个。

KVM 用一个函数指针表把两种模式统一起来：

```c
struct kvm_mmu {
	unsigned long (*get_guest_pgd)(struct kvm_vcpu *vcpu);
	u64 (*get_pdptr)(struct kvm_vcpu *vcpu, int index);
	int (*page_fault)(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault);
	void (*inject_page_fault)(struct kvm_vcpu *vcpu,
				  struct x86_exception *fault);
	gpa_t (*gva_to_gpa)(struct kvm_vcpu *vcpu, struct kvm_mmu *mmu,
			    gpa_t gva_or_gpa, u64 access,
			    struct x86_exception *exception);
	int (*sync_spte)(struct kvm_vcpu *vcpu,
			 struct kvm_mmu_page *sp, int i);
	struct kvm_mmu_root_info root;
	union kvm_cpu_role cpu_role;
	union kvm_mmu_page_role root_role;
	...
	/*
	 * check zero bits on shadow page table entries, these
	 * bits include not only hardware reserved bits but also the
	 * bits spte never used.
	 */
	struct rsvd_bits_validate shadow_zero_check;

	struct rsvd_bits_validate guest_rsvd_check;
};
```

两种模式体现在 `root_role` 的一个位上：

```c
union kvm_mmu_page_role {
	u32 word;
	struct {
		unsigned level:4;
		unsigned has_4_byte_gpte:1;
		unsigned quadrant:2;
		unsigned direct:1;
		unsigned access:3;
		unsigned invalid:1;
		...
		unsigned passthrough:1;
		unsigned :5;
		unsigned smm:8;
	};
};
```

`direct:1` —— 置位表示"直接映射"（TDP，页表里就是 GPA→HPA），清零表示影子页表。影子页表的 role 位多得多是为了**缓存复用**：guest 的 CR0/CR4/EFER/SMEP/SMAP 任一改变，已有的影子页就作废；所以 role 把这些条件编码进一个 u32，作为哈希键判断能否复用。TDP 模式下这些条件大部分不影响 GPA→HPA，role 自然简单得多——这也是 EPT 快的根本原因之一。

### Handling EPT Violations

两层翻译下，缺页由硬件在 EPT 那层报出：

```c
static int handle_ept_violation(struct kvm_vcpu *vcpu)
{
	unsigned long exit_qualification;
	gpa_t gpa;
	u64 error_code;

	exit_qualification = vmx_get_exit_qual(vcpu);
	...
	gpa = vmcs_read64(GUEST_PHYSICAL_ADDRESS);
	trace_kvm_page_fault(vcpu, gpa, exit_qualification);

	/* Is it a read fault? */
	error_code = (exit_qualification & EPT_VIOLATION_ACC_READ)
		     ? PFERR_USER_MASK : 0;
	/* Is it a write fault? */
	error_code |= (exit_qualification & EPT_VIOLATION_ACC_WRITE)
		      ? PFERR_WRITE_MASK : 0;
	/* Is it a fetch fault? */
	error_code |= (exit_qualification & EPT_VIOLATION_ACC_INSTR)
		      ? PFERR_FETCH_MASK : 0;
	/* ept page table entry is present? */
	error_code |= (exit_qualification & EPT_VIOLATION_RWX_MASK)
		      ? PFERR_PRESENT_MASK : 0;
```

值得对比的是：原生缺页的地址在 CR2，而 EPT 违规的 GPA 在 **VMCS 的 `GUEST_PHYSICAL_ADDRESS` 字段**里。硬件之所以把地址存在 VMCS 而不是 CR2，正因为此时有两层地址——CR2 里是 GVA，VMCS 里才是 GPA。随后 KVM 按"是 EPT 没映射，还是 guest 页表本身不允许"分流：前者自己填 EPT 项即可（不退出），后者要**向 guest 注入一个缺页异常**（让 guest OS 自己处理，和真机一样）。

## Interrupt Virtualization

中断芯片（PIC / IOAPIC / LAPIC）可以建在内核（`KVM_CREATE_IRQCHIP`），也可以留给 QEMU。在内核时，注入路径完全在内核完成，QEMU 不参与。

`irqfd` 则把"外部事件 → guest 中断"整条链搬进内核：QEMU 拿一个 eventfd 注册成 irqfd，之后**任何进程或内核子系统**写这个 eventfd，内核就直接注入中断，全程不唤醒 QEMU：

```c
	irqfd_inject(struct work_struct *work)
	{
		struct kvm_kernel_irqfd *irqfd =
			container_of(work, struct kvm_kernel_irqfd, inject);
		struct kvm *kvm = irqfd->kvm;

		if (!irqfd->resampler) {
			kvm_set_irq(kvm, KVM_USERSPACE_IRQ_SOURCE_ID, irqfd->gsi, 1,
					false);
			kvm_set_irq(kvm, KVM_USERSPACE_IRQ_SOURCE_ID, irqfd->gsi, 0,
					false);
		} else
			kvm_set_irq(kvm, KVM_IRQFD_RESAMPLE_IRQ_SOURCE_ID,
				    irqfd->gsi, 1, false);
	}
```

注意那个 `1` 后紧跟 `0`：电平中断要先拉高再拉低，构成一个完整的脉冲。带 resampler 的 irqfd 用于边沿触发设备（如直通设备），需要等 guest 侧 EOI 才能再次断言，所以由 `irqfd_resampler_ack()` 回调驱动。

irqfd 的典型用途是**设备直通（VFIO）**：物理设备的中断直接进 guest，不经过 QEMU。

## Device I/O and ioeventfd

guest 访问设备（端口 I/O 或 MMIO）会退出，内核查 `kvm->buses[]` 找注册的设备：命中内核设备就在内核处理；否则以 `KVM_EXIT_IO` / `KVM_EXIT_MMIO` 退出给 QEMU 模拟。

问题在于 virtio 网卡/磁盘这类设备，guest 每发一个包就要"写寄存器通知后端"，若每次都退出到 QEMU，开销巨大。**ioeventfd** 把这个通知也搬进内核：QEMU 把"某个 MMIO 地址 + 某个值"注册成 ioeventfd，之后 guest 写这个地址时，内核直接 signal 对应的 eventfd，不退出：

```c
ioeventfd_in_range(struct _ioeventfd *p, gpa_t addr, int len, const void *val)
{
	u64 _val;

	if (addr != p->addr)
		/* address must be precise for a hit */
		return false;

	if (!p->length)
		/* length = 0 means only look at the address, so always a hit */
		return true;

	if (len != p->length)
		/* address-range must be precise for a hit */
		return false;

	if (p->wildcard)
		/* all else equal, wildcard is always a hit */
		return true;

	/* otherwise, we have to actually compare the data */
	...
	return _val == p->datamatch;
}

/* MMIO/PIO writes trigger an event if the addr/val match */
static int
ioeventfd_write(struct kvm_vcpu *vcpu, struct kvm_io_device *this, gpa_t addr,
		int len, const void *val)
{
	struct _ioeventfd *p = to_ioeventfd(this);

	if (!ioeventfd_in_range(p, addr, len, val))
		return -EOPNOTSUPP;

	eventfd_signal(p->eventfd);
	return 0;
}
```

匹配规则很讲究：地址必须精确相等；`length = 0` 表示只看地址不看长度；`wildcard` 表示不比较数据；否则还要比对写入的值。这套规则是为了精确匹配 virtio 的"kick"寄存器语义而不误伤相邻的 MMIO 区域。

ioeventfd 的另一半是 **vhost**：数据面本身也搬进内核。`/dev/vhost-net` 是另一套 ioctl 接口（魔数 `VHOST_VIRTIO = 0xAF`），QEMU 通过 `VHOST_SET_MEM_TABLE`（把 guest 内存布局交给 vhost）、`VHOST_SET_VRING_KICK`(0x20)、`VHOST_SET_VRING_CALL`(0x21) 把 virtio 环形队列交给内核线程处理。kick fd 通常就是 ioeventfd，call fd 就是 irqfd——两头都接上之后，一次网络收发可以**完全不退出 guest、不唤醒 QEMU**。

这与 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md) 的思路同构：把高频数据面从"用户态轮询 + 系统调用"改成"内核态共享环 + eventfd 通知"。

## Scheduling and Preemption

一个 vCPU 就是一个普通的 host 线程（QEMU 的线程），因此受 [调度器](/docs/CS/OS/Linux/proc/sche.md) 完全管辖：会被抢占、会睡眠、会被 cgroup 限流。这是借用 host 内核的直接好处，也是 KVM 与 Xen 架构上的根本差异。

代价是：guest 里的"空闲"与 host 的"抢占"会互相污染。KVM 为此配了几样东西：

- **`preempt_notifier`**（`struct kvm_vcpu` 第一个字段之一）：vCPU 线程被抢占出去时收到回调，KVM 借机把"我被抢占了"告知 guest（PV 特性），避免 guest 里的自旋锁持有者被换出导致其他 vCPU 空转。
- **`kvm_vcpu_preempted_in_kernel()`** 与 `kvm_arch_dy_runnable()`：配合 `directed yield`，让同一 VM 的 vCPU 之间互相礼让，而不是盲目自旋。
- **`halt_poll_ns`**（在 `struct kvm_vcpu` 里）：guest 执行 HLT 后不立刻睡，先轮询一会儿看会不会马上有中断。这是用一点 CPU 换掉一次睡眠/唤醒的延迟，与 [NAPI](/docs/CS/OS/Linux/net/NAPI.md) 收包时"先轮询再开中断"的权衡如出一辙。
- **steal time**：告诉 guest "你的时间被 host 拿走了多少"，让 guest 内的调度与计费不至于错乱。

## Observation and Limitations

- `/dev/kvm` 是唯一的入口，权限由文件权限控制，容器里要跑虚拟机必须给它。
- `KVM_CHECK_EXTENSION` 是能力协商接口——QEMU 启动时会挨个查询，不要假设能力存在。
- 每个 VM / vCPU 在 debugfs 下有统计目录；`struct kvm_vcpu_stat`、`struct kvm_vm_stat` 记录退出次数等计数器，`vcpu->stat.exits` 是最直接的"退出有多频繁"指标。
- 嵌套虚拟化、脏页环（`KVM_EXIT_DIRTY_RING_FULL` 表示 QEMU 没及时收割）、guest_memfd（保密计算）都是较新的能力，依赖 `KVM_CHECK_EXTENSION`。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [内核架构分层](/docs/CS/OS/Linux/Architecture.md)
- [容器与虚拟化的边界](/docs/CS/Container/Container.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)

## References

- [Linux KVM API documentation](https://www.kernel.org/doc/Documentation/virt/kvm/api.rst)
- [KVM implementation details](https://www.kernel.org/doc/Documentation/virt/kvm/index.rst)
- [Linux Insides: KVM](https://0xax.gitbooks.io/linux-insides/content/Theory/linux-theory-2.html)
- [QEMU documentation](https://www.qemu.org/docs/master/)
