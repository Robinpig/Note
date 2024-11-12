## Introduction

The physical memory in a computer system is a limited resource and even for systems that support memory hotplug there is a hard limit on the amount of memory that can be installed. The physical memory is not necessarily contiguous; it might be accessible as a set of distinct address ranges. Besides, different CPU architectures, and even different implementations of the same architecture have different views of how these address ranges are defined.
All this makes dealing directly with physical memory quite complex and to avoid this complexity a concept of virtual memory was developed.
The virtual memory abstracts the details of physical memory from the application software, allows to keep only needed information in the physical memory (demand paging) and provides a mechanism for the protection and controlled sharing of data between processes.
With virtual memory, each and every memory access uses a virtual address. When the CPU decodes an instruction that reads (or writes) from (or to) the system memory, it translates the virtual address encoded in that instruction to a physical address that the memory controller can understand.
The physical system memory is divided into page frames, or pages. The size of each page is architecture specific. Some architectures allow selection of the page size from several supported values; this selection is performed at the kernel build time by setting an appropriate kernel configuration option.
Each physical memory page can be mapped as one or more virtual pages. These mappings are described by page tables that allow translation from a virtual address used by programs to the physical memory address. The page tables are organized hierarchically.
The tables at the lowest level of the hierarchy contain physical addresses of actual pages used by the software. The tables at higher levels contain physical addresses of the pages belonging to the lower levels. The pointer to the top level page table resides in a register. When the CPU performs the address translation, it uses this register to access the top level page table. The high bits of the virtual address are used to index an entry in the top level page table. That entry is then used to access the next level in the hierarchy with the next bits of the virtual address as the index to that level page table. The lowest bits in the virtual address define the offset inside the actual page.



The address translation requires several memory accesses and memory accesses are slow relatively to CPU speed. To avoid spending precious processor cycles on the address translation, CPUs maintain a cache of such translations called Translation Lookaside Buffer (or TLB). Usually TLB is pretty scarce resource and applications with large memory working set will experience performance hit because of TLB misses.
Many modern CPU architectures allow mapping of the memory pages directly by the higher levels in the page table. For instance, on x86, it is possible to map 2M and even 1G pages using entries in the second and the third level page tables. In Linux such pages are called huge. Usage of huge pages significantly reduces pressure on TLB, improves TLB hit-rate and thus improves overall system performance.
There are two mechanisms in Linux that enable mapping of the physical memory with the huge pages. The first one is HugeTLB filesystem, or hugetlbfs. It is a pseudo filesystem that uses RAM as its backing store. For the files created in this filesystem the data resides in the memory and mapped using huge pages. The hugetlbfs is described at HugeTLB Pages.
Another, more recent, mechanism that enables use of the huge pages is called Transparent HugePages, or THP. Unlike the hugetlbfs that requires users and/or system administrators to configure what parts of the system memory should and can be mapped by the huge pages, THP manages such mappings transparently to the user and hence the name. See Transparent Hugepage Support for more details about THP.


Zone

Often hardware poses restrictions on how different physical memory ranges can be accessed. In some cases, devices cannot perform DMA to all the addressable memory. In other cases, the size of the physical memory exceeds the maximal addressable size of virtual memory and special actions are required to access portions of the memory. Linux groups memory pages into zones according to their possible usage. For example, ZONE_DMA will contain memory that can be used by devices for DMA, ZONE_HIGHMEM will contain memory that is not permanently mapped into kernel’s address space and ZONE_NORMAL will contain normally addressed pages.
The actual layout of the memory zones is hardware dependent as not all architectures define all zones, and requirements for DMA are different for different platforms.


Many multi-processor machines are NUMA - Non-Uniform Memory Access - systems. In such systems the memory is arranged into banks that have different access latency depending on the “distance” from the processor. Each bank is referred to as a node and for each node Linux constructs an independent memory management subsystem. A node has its own set of zones, lists of free and used pages and various statistics counters. You can find more details about NUMA in What is NUMA?` and in NUMA Memory Policy.

Page cache
The physical memory is volatile and the common case for getting data into the memory is to read it from files. Whenever a file is read, the data is put into the page cache to avoid expensive disk access on the subsequent reads. Similarly, when one writes to a file, the data is placed in the page cache and eventually gets into the backing storage device. The written pages are marked as dirty and when Linux decides to reuse them for other purposes, it makes sure to synchronize the file contents on the device with the updated data.
Anonymous Memory
The anonymous memory or anonymous mappings represent memory that is not backed by a filesystem. Such mappings are implicitly created for program’s stack and heap or by explicit calls to mmap(2) system call. Usually, the anonymous mappings only define virtual memory areas that the program is allowed to access. The read accesses will result in creation of a page table entry that references a special physical page filled with zeroes. When the program performs a write, a regular physical page will be allocated to hold the written data. The page will be marked dirty and if the kernel decides to repurpose it, the dirty page will be swapped out.
Reclaim
Throughout the system lifetime, a physical page can be used for storing different types of data. It can be kernel internal data structures, DMA’able buffers for device drivers use, data read from a filesystem, memory allocated by user space processes etc.
Depending on the page usage it is treated differently by the Linux memory management. The pages that can be freed at any time, either because they cache the data available elsewhere, for instance, on a hard disk, or because they can be swapped out, again, to the hard disk, are called reclaimable. The most notable categories of the reclaimable pages are page cache and anonymous memory.
In most cases, the pages holding internal kernel data and used as DMA buffers cannot be repurposed, and they remain pinned until freed by their user. Such pages are called unreclaimable. However, in certain circumstances, even pages occupied with kernel data structures can be reclaimed. For instance, in-memory caches of filesystem metadata can be re-read from the storage device and therefore it is possible to discard them from the main memory when system is under memory pressure.
The process of freeing the reclaimable physical memory pages and repurposing them is called (surprise!) reclaim. Linux can reclaim pages either asynchronously or synchronously, depending on the state of the system. When the system is not loaded, most of the memory is free and allocation requests will be satisfied immediately from the free pages supply. As the load increases, the amount of the free pages goes down and when it reaches a certain threshold (low watermark), an allocation request will awaken the kswapd daemon. It will asynchronously scan memory pages and either just free them if the data they contain is available elsewhere, or evict to the backing storage device (remember those dirty pages?). As memory usage increases even more and reaches another threshold - min watermark - an allocation will trigger direct reclaim. In this case allocation is stalled until enough memory pages are reclaimed to satisfy the request.
Compaction
As the system runs, tasks allocate and free the memory and it becomes fragmented. Although with virtual memory it is possible to present scattered physical pages as virtually contiguous range, sometimes it is necessary to allocate large physically contiguous memory areas. Such need may arise, for instance, when a device driver requires a large buffer for DMA, or when THP allocates a huge page. Memory compaction addresses the fragmentation issue. This mechanism moves occupied pages from the lower part of a memory zone to free pages in the upper part of the zone. When a compaction scan is finished free pages are grouped together at the beginning of the zone and allocations of large physically contiguous areas become possible.
Like reclaim, the compaction may happen asynchronously in the kcompactd daemon or synchronously as a result of a memory allocation request.
OOM killer
It is possible that on a loaded machine memory will be exhausted and the kernel will be unable to reclaim enough memory to continue to operate. In order to save the rest of the system, it invokes the OOM killer.
The OOM killer selects a task to sacrifice for the sake of the overall system health. The selected task is killed in a hope that after it exits enough memory will be freed to continue normal operation.
在大多数操作系统中，数值比较小的地址通常被认为不是一个合法的地址，这块小地址是不允许访问的保留区

保留区的上边就是代码段和数据段，它们是从程序的二进制文件中直接加载进内存中的，BSS 段中的数据也存在于二进制文件中，因为内核知道这些数据是没有初值的，所以在二进制文件中只会记录 BSS 段的大小，在加载进内存时会生成一段 0 填充的内存空间。
紧挨着 BSS 段的上边就是我们经常使用到的堆空间

内核中使用 start_brk 标识堆的起始位置，brk 标识堆当前的结束位置。当堆申请新的内存空间时，只需要将 brk 指针增加对应的大小，回收地址时减少对应的大小即可。比如当我们通过 malloc 向内核申请很小的一块内存时（128K 之内），就是通过改变 brk 位置实现的

栈空间这里会保存函数运行过程所需要的局部变量以及函数参数等函数调用信息。栈空间中的地址增长方向是从高地址向低地址增长。每次进程申请新的栈地址时，其地址值是在减少的
在内核中使用 start_stack 标识栈的起始位置，RSP 寄存器中保存栈顶指针 stack pointer，RBP 寄存器中保存的是栈基地址。
在栈空间的下边也有一段待分配区域用于扩展栈空间，在栈空间的上边就是内核空间了，进程虽然可以看到这段内核空间地址，但是就是不能访问



虚拟内存空间布局都可以通过 cat /proc/pid/maps 或者 pmap pid 来查看某个进程的实际虚拟内存布局

目前的 64 位系统下只使用了 48 位来描述虚拟内存空间，寻址范围为  2^48 ，所能表达的虚拟内存空间为 256TB。
其中低 128 T 表示用户态虚拟内存空间，虚拟内存地址范围为：0x0000 0000 0000 0000  - 0x0000 7FFF FFFF F000 。
高 128 T 表示内核态虚拟内存空间，虚拟内存地址范围为：0xFFFF 8000 0000 0000  - 0xFFFF FFFF FFFF FFFF
在 64 位机器上的指针寻址范围为 2^64，但是在实际使用中我们只使用了其中的低 48 位来表示虚拟内存地址，那么这多出的高 16 位就形成了这个地址空洞(canonical address)



## mm_struct

在 copy_process 函数中创建 task_struct 结构，并拷贝父进程的相关资源到新进程的 task_struct 结构里，其中就包括拷贝父进程的虚拟内存空间 mm_struct 结构。这里可以看出子进程在新创建出来之后它的虚拟内存空间是和父进程的虚拟内存空间一模一样的，直接拷贝过来

copy_mm  函数首先会将父进程的虚拟内存空间 current->mm 赋值给指针 oldmm。然后通过 dup_mm 函数将父进程的虚拟内存空间以及相关页表拷贝到子进程的 mm_struct 结构中。最后将拷贝出来的 mm_struct 赋值给子进程的 task_struct 结构。
通过 fork() 函数创建出的子进程，它的虚拟内存空间以及相关页表相当于父进程虚拟内存空间的一份拷贝，直接从父进程中拷贝到子进程中

而当我们通过 vfork 或者 clone 系统调用创建出的子进程，首先会设置 CLONE_VM 标识，这样来到 copy_mm 函数中就会进入  if (clone_flags & CLONE_VM)  条件中，在这个分支中会将父进程的虚拟内存空间以及相关页表直接赋值给子进程。这样一来父进程和子进程的虚拟内存空间就变成共享的了。也就是说父子进程之间使用的虚拟内存空间是一样的，并不是一份拷贝。
子进程共享了父进程的虚拟内存空间，这样子进程就变成了我们熟悉的线程，是否共享地址空间几乎是进程和线程之间的本质区别。Linux 内核并不区别对待它们，线程对于内核来说仅仅是一个共享特定资源的进程而已

内核线程和用户态线程的区别就是内核线程没有相关的内存描述符 mm_struct ，内核线程对应的 task_struct 结构中的 mm 域指向 Null，所以内核线程之间调度是不涉及地址空间切换的
当一个内核线程被调度时，它会发现自己的虚拟地址空间为 Null，虽然它不会访问用户态的内存，但是它会访问内核内存，聪明的内核会将调度之前的上一个用户态进程的虚拟内存空间 mm_struct 直接赋值给内核线程，因为内核线程不会访问用户空间的内存，它仅仅只会访问内核空间的内存，所以直接复用上一个用户态进程的虚拟地址空间就可以避免为内核线程分配 mm_struct 和相关页表的开销，以及避免内核线程之间调度时地址空间的切换开销。
父进程与子进程的区别，进程与线程的区别，以及内核线程与用户态线程的区别其实都是围绕着这个 mm_struct 展开的


进程的内存描述符 mm_struct 结构体中的 task_size 变量，task_size 定义了用户态地址空间与内核态地址空间之间的分界线。

```c
struct mm_struct {
    unsigned long task_size; /* size of task vm space */
}
```





```c

// arch/x86/include/asm/page_32_types.h
/*
 * This handles the memory map.
 *
 * A __PAGE_OFFSET of 0xC0000000 means that the kernel has
 * a virtual address space of one gigabyte, which limits the
 * amount of physical memory you can use to about 950MB.
 *
 * If you want more physical memory than this then see the CONFIG_HIGHMEM4G
 * and CONFIG_HIGHMEM64G options in the kernel configuration.
 */
#define __PAGE_OFFSET_BASE	_AC(CONFIG_PAGE_OFFSET, UL)
#define __PAGE_OFFSET		__PAGE_OFFSET_BASE

#ifdef CONFIG_X86_PAE
/*
 * This is beyond the 44 bit limit imposed by the 32bit long pfns,
 * but we need the full mask to make sure inverted PROT_NONE
 * entries have all the host bits set in a guest.
 * The real limit is still 44 bits.
 */
#define __PHYSICAL_MASK_SHIFT	52
#define __VIRTUAL_MASK_SHIFT	32

#else  /* !CONFIG_X86_PAE */
#define __PHYSICAL_MASK_SHIFT	32
#define __VIRTUAL_MASK_SHIFT	32
#endif	/* CONFIG_X86_PAE */

/*
 * User space process size: 3GB (default).
 */
#define IA32_PAGE_OFFSET	__PAGE_OFFSET
#define TASK_SIZE		__PAGE_OFFSET
```





```c
// /arch/x86/Kconfig
config PAGE_OFFSET
	hex
	default 0xB0000000 if VMSPLIT_3G_OPT
	default 0x80000000 if VMSPLIT_2G
	default 0x78000000 if VMSPLIT_2G_OPT
	default 0x40000000 if VMSPLIT_1G
	default 0xC0000000
	depends on X86_32
```



```c
/*
 * Set __PAGE_OFFSET to the most negative possible address +
 * PGDIR_SIZE*17 (pgd slot 273).
 *
 * The gap is to allow a space for LDT remap for PTI (1 pgd slot) and space for
 * a hypervisor (16 slots). Choosing 16 slots for a hypervisor is arbitrary,
 * but it's what Xen requires.
 */
#define __PAGE_OFFSET_BASE_L5	_AC(0xff11000000000000, UL)
#define __PAGE_OFFSET_BASE_L4	_AC(0xffff888000000000, UL)

#ifdef CONFIG_DYNAMIC_MEMORY_LAYOUT
#define __PAGE_OFFSET           page_offset_base
#else
#define __PAGE_OFFSET           __PAGE_OFFSET_BASE_L4
#endif /* CONFIG_DYNAMIC_MEMORY_LAYOUT */

#define __START_KERNEL_map	_AC(0xffffffff80000000, UL)

/* See Documentation/arch/x86/x86_64/mm.rst for a description of the memory map. */

#define __PHYSICAL_MASK_SHIFT	52

#ifdef CONFIG_X86_5LEVEL
#define __VIRTUAL_MASK_SHIFT	(pgtable_l5_enabled() ? 56 : 47)
/* See task_size_max() in <asm/page_64.h> */
#else
#define __VIRTUAL_MASK_SHIFT	47
#define task_size_max()		((_AC(1,UL) << __VIRTUAL_MASK_SHIFT) - PAGE_SIZE)
#endif

#define TASK_SIZE_MAX		task_size_max()
#define DEFAULT_MAP_WINDOW	((1UL << 47) - PAGE_SIZE)

/* This decides where the kernel will search for a free chunk of vm
 * space during mmap's.
 */
#define IA32_PAGE_OFFSET	((current->personality & ADDR_LIMIT_3GB) ? \
					0xc0000000 : 0xFFFFe000)

#define TASK_SIZE_LOW		(test_thread_flag(TIF_ADDR32) ? \
					IA32_PAGE_OFFSET : DEFAULT_MAP_WINDOW)
#define TASK_SIZE		(test_thread_flag(TIF_ADDR32) ? \
					IA32_PAGE_OFFSET : TASK_SIZE_MAX)
```



```c
/* PAGE_SHIFT determines the page size */
#define PAGE_SHIFT		CONFIG_PAGE_SHIFT
#define PAGE_SIZE		(_AC(1,UL) << PAGE_SHIFT)
#define PAGE_MASK		(~(PAGE_SIZE-1))
```
64 位虚拟内存空间的布局是和物理内存页 page 的大小有关的，物理内存页 page 默认大小 PAGE_SIZE 为 4K


```c
// arch/Kconfig
config PAGE_SHIFT
	int
	default	12 if PAGE_SIZE_4KB
	default	13 if PAGE_SIZE_8KB
	default	14 if PAGE_SIZE_16KB
	default	15 if PAGE_SIZE_32KB
	default	16 if PAGE_SIZE_64KB
	default	18 if PAGE_SIZE_256KB
```

```c

```

Linux provides a variety of APIs for memory allocation. You can allocate small chunks using kmalloc or kmem_cache_alloc families, large virtually contiguous areas using vmalloc and its derivatives, or you can directly request pages from the page allocator with alloc_pages. It is also possible to use more specialized allocators, for instance cma_alloc or zs_malloc.

每个 vm_area_struct 结构对应于虚拟内存空间中的唯一虚拟内存区域 VMA，vm_start 指向了这块虚拟内存区域的起始地址（最低地址），vm_start 本身包含在这块虚拟内存区域内。vm_end 指向了这块虚拟内存区域的结束地址（最高地址），而 vm_end 本身包含在这块虚拟内存区域之外，所以 vm_area_struct 结构描述的是 [vm_start，vm_end) 这样一段左闭右开的虚拟内存区域

vm_page_prot 和 vm_flags 都是用来标记 vm_area_struct 结构表示的这块虚拟内存区域的访问权限和行为规范。




我们可以通过 posix_fadvise，madvise 系统调用来暗示内核是否对相关内存区域进行顺序读取或者随机读取

三个属性 anon_vma，vm_file，vm_pgoff 分别和虚拟内存映射相关，虚拟内存区域可以映射到物理内存上，也可以映射到文件中，映射到物理内存上我们称之为匿名映射，映射到文件中我们称之为文件映射。

当我们调用 malloc 申请内存时，如果申请的是小块内存（低于 128K）则会使用 do_brk() 系统调用通过调整堆中的 brk 指针大小来增加或者回收堆内存。
如果申请的是比较大块的内存（超过 128K）时，则会调用 mmap 在上图虚拟内存空间中的文件映射与匿名映射区创建出一块 VMA 内存区域（这里是匿名映射）。这块匿名映射区域就用 struct anon_vma 结构表示。
当调用 mmap 进行文件映射时，vm_file 属性就用来关联被映射的文件。这样一来虚拟内存区域就与映射文件关联了起来。vm_pgoff 则表示映射进虚拟内存中的文件内容，在文件中的偏移。
当然在匿名映射中，vm_area_struct 结构中的 vm_file 就为 null，vm_pgoff 也就没有了意义。
vm_private_data 则用于存储 VMA 中的私有数据。具体的存储内容和内存映射的类型有关，我们暂不展开论述

struct vm_area_struct 结构中还有一个 vm_ops 用来指向针对虚拟内存区域 VMA 的相关操作的函数指针。

在内核中其实是通过一个 struct vm_area_struct 结构的双向链表将虚拟内存空间中的这些虚拟内存区域 VMA 串联起来的。
vm_area_struct 结构中的 vm_next ，vm_prev 指针分别指向 VMA 节点所在双向链表中的后继节点和前驱节点，内核中的这个 VMA 双向链表是有顺序的，所有 VMA 节点按照低地址到高地址的增长方向排序。
双向链表中的最后一个 VMA 节点的 vm_next 指针指向 NULL，双向链表的头指针存储在内存描述符 struct mm_struct 结构中的 mmap 中，正是这个 mmap 串联起了整个虚拟内存空间中的虚拟内存区域。


```c
// include/linux/mm_types.h
struct mm_struct {
    struct vm_area_struct *mmap;  /* list of VMAs */
}
```

在每个虚拟内存区域 VMA 中又通过 struct vm_area_struct 中的 vm_mm 指针指向了所属的虚拟内存空间 mm_struct

cat /proc/pid/maps 或者 pmap pid 查看进程的虚拟内存空间布局以及其中包含的所有内存区域。这两个命令背后的实现原理就是通过遍历内核中的这个 vm_area_struct 双向链表获取的。

内核中关于这些虚拟内存区域的操作除了遍历之外还有许多需要根据特定虚拟内存地址在虚拟内存空间中查找特定的虚拟内存区域。
尤其在进程虚拟内存空间中包含的内存区域 VMA 比较多的情况下，使用红黑树查找特定虚拟内存区域的时间复杂度是 O( logN ) ，可以显著减少查找所需的时间。
所以在内核中，同样的内存区域 vm_area_struct 会有两种组织形式，一种是双向链表用于高效的遍历，另一种就是红黑树用于高效的查找。
每个 VMA 区域都是红黑树中的一个节点，通过 struct vm_area_struct 结构中的 vm_rb 将自己连接到红黑树中。
而红黑树中的根节点存储在内存描述符 struct mm_struct 中的 mm_rb 中：


```c
struct mm_struct {
     struct rb_root mm_rb;
}
```



每个进程对应一个 task 结构，它指向一个 mm 结构，这就是该进程的内存管理器。（对于线程来说，每个线程也都有一个 task 结构，但是它们都指向同一个 mm，所以同一进程中的多个线程的地址空间是共享的。）
mm->pgd 指向容纳页表的内存，每个进程有自已的 mm，每个 mm 有自己的页表。于是，进程调度时，页表被切换（一般会有一个 CPU 寄存器来保存页表的地址，比如 X86 下的 CR3，页表切换就是改变该寄存器的值）。所以，各个进程的地址空间互不影响（因为页表都不一样了，当然无法访问到别人的地址空间上。但是共享内存除外，这是故意让不同的页表能够访问到相同的物理地址上）。
用户程序对内存的操作（分配、回收、映射、等）都是对 mm 的操作，具体来说是对 mm 上的 vma（虚拟内存空间） 的操作。这些 vma 代表着进程空间的各个区域，比如堆、栈、代码区、数据区、各种映射区 等

假设用户分配了内存，然后访问这块内存。由于页表里面并没有记录相关的映射，CPU 产生一次缺页异常。内核捕捉异常，检查产生异常的地址是不是存在于一个合法的 vma 中，如果不是，则给进程一个”段错误”，让其崩溃；如果是，则分配一个物理页，并为之建立映射


malloc是libc的库函数，用户程序一般通过它（或类似函数）来分配内存空间。
libc对内存的分配有两种途径：一是调整堆的大小，二是mmap 一个新的虚拟内存区域（堆也是一个 vma）
在内核中，堆是一个一端固定、一端可伸缩的 vma（图：左中）。可伸缩的一端通过系统调用 brk 来调整。libc 管理着堆的空间，用户调用 malloc 分配内存时，libc 尽量从现有的堆中去分配。如果堆空间不够，则通过 brk 增大堆空间。
当用户将已分配的空间 free 时，libc 可能会通过 brk 减小堆空间。但是堆空间增大容易减小却难，考虑这样一种情况，用户空间连续分配了 10 块内存，前 9 块已经 free。这时，未 free 的第 10 块哪怕只有 1 字节大，libc 也不能够去减小堆的大小。因为堆只有一端可伸缩，并且中间不能掏空。而第 10 块内存就死死地占据着堆可伸缩的那一端，堆的大小没法减小，相关资源也没法归还内核。
当用户 malloc 一块很大的内存时，libc 会通过 mmap 系统调用映射一个新的 vma。因为对于堆的大小调整和空间管理还是比较麻烦的，重新建一个 vma 会更方便

与堆一样，栈也是一个 vma（图：左中），这个 vma 是一端固定、一端可伸（注意，不能缩）的。这个 vma 比较特殊，没有类似 brk 的系统调用让这个 vma 伸展，它是自动伸展的。
当用户访问的虚拟地址越过这个 vma 时，内核会在处理缺页异常的时候将自动将这个 vma 增大。内核会检查当时的栈寄存器（如：ESP），访问的虚拟地址不能超过 ESP 加 n（n 为 CPU 压栈指令一次性压栈的最大字节数）。也就是说，内核是以 ESP 为基准来检查访问是否越界。
但是，ESP的值是可以由用户态程序自由读写的，用户程序如果调整ESP，将栈划得很大很大怎么办呢？ 内核中有一套关于进程限制的配置，其中就有栈大小的配置，栈只能这么大，再大就出错。

对于一个进程来说，栈一般是可以被伸展得比较大（如：8MB）。然而对于线程呢？
首先线程的栈是怎么回事？前面说过，线程的 mm 是共享其父进程的。虽然栈是 mm 中的一个 vma，但是线程不能与其父进程共用这个 vma（两个运行实体显然不用共用一个栈）。于是，在线程创建时，线程库通过 mmap 新建了一个 vma，以此作为线程的栈（大于一般为：2M）。
可见，线程的栈在某种意义上并不是真正栈，它是一个固定的区域，并且容量很有限。


### vm_area_struct


This struct describes a virtual memory area. There is one of these per VM-area/task.
A VM area is any part of the process virtual memory space that has a special rule for the page-fault handlers (ie a shared library, the executable area etc).

```c
struct vm_area_struct {
	/* The first cache line has the info for VMA tree walking. */

	unsigned long vm_start;		/* Our start address within vm_mm. */
	unsigned long vm_end;		/* The first byte after our end address
					   within vm_mm. */

	/* linked list of VM areas per task, sorted by address */
	struct vm_area_struct *vm_next, *vm_prev;

	struct rb_node vm_rb;

	/*
	 * Largest free memory gap in bytes to the left of this VMA.
	 * Either between this VMA and vma->vm_prev, or between one of the
	 * VMAs below us in the VMA rbtree and its ->vm_prev. This helps
	 * get_unmapped_area find a free area of the right size.
	 */
	unsigned long rb_subtree_gap;

	/* Second cache line starts here. */

	struct mm_struct *vm_mm;	/* The address space we belong to. */

	/*
	 * Access permissions of this VMA.
	 * See vmf_insert_mixed_prot() for discussion.
	 */
	pgprot_t vm_page_prot;
	unsigned long vm_flags;		/* Flags, see mm.h. */

	/*
	 * For areas with an address space and backing store,
	 * linkage into the address_space->i_mmap interval tree.
	 *
	 * For private anonymous mappings, a pointer to a null terminated string
	 * containing the name given to the vma, or NULL if unnamed.
	 */

	union {
		struct {
			struct rb_node rb;
			unsigned long rb_subtree_last;
		} shared;
		/*
		 * Serialized by mmap_sem. Never use directly because it is
		 * valid only when vm_file is NULL. Use anon_vma_name instead.
		 */
		struct anon_vma_name *anon_name;
	};

	/*
	 * A file's MAP_PRIVATE vma can be in both i_mmap tree and anon_vma
	 * list, after a COW of one of the file pages.	A MAP_SHARED vma
	 * can only be in the i_mmap tree.  An anonymous MAP_PRIVATE, stack
	 * or brk vma (with NULL file) can only be in an anon_vma list.
	 */
	struct list_head anon_vma_chain; /* Serialized by mmap_lock &
					  * page_table_lock */
	struct anon_vma *anon_vma;	/* Serialized by page_table_lock */

	/* Function pointers to deal with this struct. */
	const struct vm_operations_struct *vm_ops;

	/* Information about our backing store: */
	unsigned long vm_pgoff;		/* Offset (within vm_file) in PAGE_SIZE
					   units */
	struct file * vm_file;		/* File we map to (can be NULL). */
	void * vm_private_data;		/* was vm_pte (shared mem) */

#ifdef CONFIG_SWAP
	atomic_long_t swap_readahead_info;
#endif
#ifndef CONFIG_MMU
	struct vm_region *vm_region;	/* NOMMU mapping region */
#endif
#ifdef CONFIG_NUMA
	struct mempolicy *vm_policy;	/* NUMA policy for the VMA */
#endif
	struct vm_userfaultfd_ctx vm_userfaultfd_ctx;
} __randomize_layout;
```


根据 vm_file->f_inode 我们可以关联到映射文件的 struct inode，近而关联到映射文件在磁盘中的磁盘块 i_block，这个就是 mmap 内存文件映射最本质的东西

```c
struct vm_area_struct {
	/* Information about our backing store: */
	unsigned long vm_pgoff;		/* Offset (within vm_file) in PAGE_SIZE
					   units */
	struct file * vm_file;		/* File we map to (can be NULL). */
}	
```




## vmalloc

伙伴管理算法初衷是解决外部碎片问题，而slab算法则是用于解决内部碎片问题，但是内存使用的得不合理终究会产生碎片。碎片问题产生后，申请大块连续内存将可能持续失败，但是实际上内存的空闲空间却是足够的。这时候就引入了不连续页面管理算法，即我们常用的vmalloc申请分配的内存空间，它主要是用于将不连续的页面，通过内存映射到连续的虚拟地址空间中，提供给申请者使用，由此实现内存的高利用

vmalloc() 函数则会在虚拟内存空间给出一块连续的内存区，但这片连续的虚拟内存在物理内存中并不一定连续。由于 vmalloc() 没有保证申请到的是连续的物理内存，因此对申请的内存大小没有限制


```c
void __init vmalloc_init(void)
{
    struct vmap_area *va;
    struct vm_struct *tmp;
    int i;

    /*
     * Create the cache for vmap_area objects.
     */
    vmap_area_cachep = KMEM_CACHE(vmap_area, SLAB_PANIC);

    for_each_possible_cpu(i) {
        struct vmap_block_queue *vbq;
        struct vfree_deferred *p;

        vbq = &per_cpu(vmap_block_queue, i);
        spin_lock_init(&vbq->lock);
        INIT_LIST_HEAD(&vbq->free);
        p = &per_cpu(vfree_deferred, i);
        init_llist_head(&p->list);
        INIT_WORK(&p->wq, free_work);
    }

    /* Import existing vmlist entries. */
    for (tmp = vmlist; tmp; tmp = tmp->next) {
        va = kmem_cache_zalloc(vmap_area_cachep, GFP_NOWAIT);
        if (WARN_ON_ONCE(!va))
            continue;

        va->va_start = (unsigned long)tmp->addr;
        va->va_end = va->va_start + tmp->size;
        va->vm = tmp;
        insert_vmap_area(va, &vmap_area_root, &vmap_area_list);
    }

    /*
     * Now we can initialize a free vmap space.
     */
    vmap_init_free_space();
    vmap_initialized = true;
}
```

Allocate enough pages to cover @size from the page level allocator with @gfp_mask flags.  Map them into contiguous kernel virtual space, using a pagetable protection of @prot

```c
void *__vmalloc(unsigned long size, gfp_t gfp_mask)
{
    return __vmalloc_node(size, 1, gfp_mask, NUMA_NO_NODE,
                __builtin_return_address(0));
}
EXPORT_SYMBOL(__vmalloc);

void *__vmalloc_node(unsigned long size, unsigned long align,
			    gfp_t gfp_mask, int node, const void *caller)
{
	return __vmalloc_node_range(size, align, VMALLOC_START, VMALLOC_END,
				gfp_mask, PAGE_KERNEL, 0, node, caller);
}

void *__vmalloc_node_range(unsigned long size, unsigned long align,
			unsigned long start, unsigned long end, gfp_t gfp_mask,
			pgprot_t prot, unsigned long vm_flags, int node,
			const void *caller)
{
	struct vm_struct *area;
	void *addr;
	unsigned long real_size = size;

	size = PAGE_ALIGN(size);
	if (!size || (size >> PAGE_SHIFT) > totalram_pages())
		goto fail;

	area = __get_vm_area_node(real_size, align, VM_ALLOC | VM_UNINITIALIZED |
				vm_flags, start, end, node, gfp_mask, caller);
	if (!area)
		goto fail;

	addr = __vmalloc_area_node(area, gfp_mask, prot, node);
	if (!addr)
		return NULL;

	/*
	 * In this function, newly allocated vm_struct has VM_UNINITIALIZED
	 * flag. It means that vm_struct is not fully initialized.
	 * Now, it is fully initialized, so remove this flag here.
	 */
	clear_vm_uninitialized_flag(area);

	kmemleak_vmalloc(area, size, gfp_mask);

	return addr;

fail:
	warn_alloc(gfp_mask, NULL,
			  "vmalloc: allocation failure: %lu bytes", real_size);
	return NULL;
}
```

> vmalloc() 和 vfree() 可以睡眠，因此不能从中断上下文调用


kmalloc()、kzalloc()、vmalloc() 的共同特点是： + 用于申请内核空间的内存； + 内存以字节为单位进行分配； + 所分配的内存虚拟地址上连续；
kmalloc()、kzalloc()、vmalloc() 的区别是： + kzalloc 是强制清零的 kmalloc 操作；（以下描述不区分 kmalloc 和 kzalloc） + kmalloc 分配的内存大小有限制（128KB），而 vmalloc 没有限制； + kmalloc 可以保证分配的内存物理地址是连续的，但是 vmalloc 不能保证； + kmalloc 分配内存的过程可以是原子过程（使用 GFP_ATOMIC），而 vmalloc 分配内存时则可能产生阻塞； + kmalloc 分配内存的开销小，因此 kmalloc 比 vmalloc 要快；
一般情况下，内存只有在要被 DMA 访问的时候才需要物理上连续，但为了性能上的考虑，内核中一般使用 kmalloc()，而只有在需要获得大块内存时才使用 vmalloc()。例如，当模块被动态加载到内核当中时，就把模块装载到由 vmalloc() 分配的内存上



```c
/*
 * Returns a start address of the newly allocated area, if success.
 * Otherwise a vend is returned that indicates failure.
 */
static __always_inline unsigned long
__alloc_vmap_area(unsigned long size, unsigned long align,
    unsigned long vstart, unsigned long vend)
{
    unsigned long nva_start_addr;
    struct vmap_area *va;
    enum fit_type type;
    int ret;

    va = find_vmap_lowest_match(size, align, vstart);
    if (unlikely(!va))
        return vend;

    if (va->va_start > vstart)
        nva_start_addr = ALIGN(va->va_start, align);
    else
        nva_start_addr = ALIGN(vstart, align);

    /* Check the "vend" restriction. */
    if (nva_start_addr + size > vend)
        return vend;

    /* Classify what we have found. */
    type = classify_va_fit_type(va, nva_start_addr, size);
    if (WARN_ON_ONCE(type == NOTHING_FIT))
        return vend;

    /* Update the free vmap_area. */
    ret = adjust_va_to_fit_type(va, nva_start_addr, size, type);
    if (ret)
        return vend;

#if DEBUG_AUGMENT_LOWEST_MATCH_CHECK
    find_vmap_lowest_match_check(size);
#endif

    return nva_start_addr;
}
```













## Links

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)