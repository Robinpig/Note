## Introduction



为方便管理物理内存 xv6的内核态页表具备所有可用物理内存的直接映射 可以直接访问物理内存



操作系统通过页表来向每个进程提供私有的地址空间和内存。页表决定了内存地址的含义，哪些物理内存可以访问。xv6使用页表分隔不同进程的地址空间，并把它们多路复用到单一的物理内存。xv6还使用页表实现了一些技巧：把同一块内存映射到多个地址空间(a trampoline page)，使用未映射的页来保护内核和用户的栈





当xv6在进程间切换的时候，进程的页表也会跟着切换


xv6 对于物理内存的组织管理使用的是空闲链表法




## x86



```c
# kalloc.c 
struct run {
  struct run *next;
};

struct {
  struct spinlock lock;
  int use_lock;
  struct run *freelist;
} kmem;

```


Allocate one 4096-byte page of physical memory. Returns a pointer that the kernel can use. Returns 0 if the memory cannot be allocated.

```
char*
kalloc(void)
{
  struct run *r;

  if(kmem.use_lock)
    acquire(&kmem.lock);
  r = kmem.freelist;
  if(r)
    kmem.freelist = r->next;
  if(kmem.use_lock)
    release(&kmem.lock);
  return (char*)r;
}


```

Free the page of physical memory pointed at by v, which normally should have been returned by a call to kalloc().  (The exception is when initializing the allocator; see kinit above.)


```c

void
kfree(char *v)
{
  struct run *r;

  if((uint)v % PGSIZE || v < end || V2P(v) >= PHYSTOP)
    panic(“kfree”);

  // Fill with junk to catch dangling refs.
  memset(v, 1, PGSIZE);

  if(kmem.use_lock)
    acquire(&kmem.lock);
  r = (struct run*)v;
  r->next = kmem.freelist;
  kmem.freelist = r;
  if(kmem.use_lock)
    release(&kmem.lock);
}
```


这个函数就是连续调用 kfree 来回收多个页


```c

void
freerange(void *vstart, void *vend)
{
  char *p;
  p = (char*)PGROUNDUP((uint)vstart);
  for(; p + PGSIZE <= (char*)vend; p += PGSIZE)
    kfree(p);
}

```

还有两个函数 kinit1，kinit2 是freerange函数的封装
它俩是在 main.c 的 main 函数中被调用，调用的参数也已经注释在后边。调用这两个函数就是初始化内存，将内存一页一页的回收，使用头插法链在一起组成一个空闲链表，是为初始化
这里使用初始化内存的时候 kmem.use_lock = 0 表示不使用锁，这里应是为了加快初始化内存的速度



```c

// Initialization happens in two phases.
// 1. main() calls kinit1() while still using entrypgdir to place just
// the pages mapped by entrypgdir on free list.
// 2. main() calls kinit2() with the rest of the physical pages
// after installing a full page table that maps them on all cores.
void
kinit1(void *vstart, void *vend)
{
  initlock(&kmem.lock, “kmem”);
  kmem.use_lock = 0;
  freerange(vstart, vend);
}

void
kinit2(void *vstart, void *vend)
{
  freerange(vstart, vend);
  kmem.use_lock = 1;
}

```






// There is one page table per process, plus one that’s used when
// a CPU is not running any process (kpgdir). The kernel uses the
// current process’s page table during system calls and interrupts;
// page protection bits prevent user code from using the kernel’s
// mappings.
//
// setupkvm() and exec() set up every page table like this:
//
//   0..KERNBASE: user memory (text+data+stack+heap), mapped to
//                phys memory allocated by the kernel
//   KERNBASE..KERNBASE+EXTMEM: mapped to 0..EXTMEM (for I/O space)
//   KERNBASE+EXTMEM..data: mapped to EXTMEM..V2P(data)
//                for the kernel’s instructions and r/o data
//   data..KERNBASE+PHYSTOP: mapped to V2P(data)..PHYSTOP,
//                                  rw data + free physical memory
//   0xfe000000..0: mapped direct (devices such as ioapic)
//
// The kernel allocates physical memory for its heap and for user memory
// between V2P(end) and the end of physical memory (PHYSTOP)
// (directly addressable from end..P2V(PHYSTOP)).

// This table defines the kernel’s mappings, which are present in
// every process’s page table.

```c
static struct kmap {
  void *virt;
  uint phys_start;
  uint phys_end;
  int perm;
} kmap[] = {
 { (void*)KERNBASE, 0,             EXTMEM,    PTE_W}, // I/O space
 { (void*)KERNLINK, V2P(KERNLINK), V2P(data), 0},     // kern text+rodata
 { (void*)data,     V2P(data),     PHYSTOP,   PTE_W}, // kern data+memory
 { (void*)DEVSPACE, DEVSPACE,      0,         PTE_W}, // more devices
};

```
内核部分的虚拟地址空间和物理地址空间就是一一对应的，只是相差了 0x80000000





```c
// Create PTEs for virtual addresses starting at va that refer to
// physical addresses starting at pa. va and size might not
// be page-aligned.
static int
mappages(pde_t *pgdir, void *va, uint size, uint pa, int perm)
{
  char *a, *last;
  pte_t *pte;

  a = (char*)PGROUNDDOWN((uint)va);
  last = (char*)PGROUNDDOWN(((uint)va) + size - 1);
  for(;;){
    if((pte = walkpgdir(pgdir, a, 1)) == 0)
      return -1;
    if(*pte & PTE_P)
      panic(“remap”);
    *pte = pa | perm | PTE_P;
    if(a == last)
      break;
    a += PGSIZE;
    pa += PGSIZE;
  }
  return 0;
}


```





```c

// Set up kernel part of a page table.
pde_t*
setupkvm(void)
{
  pde_t *pgdir;
  struct kmap *k;

  if((pgdir = (pde_t*)kalloc()) == 0)
    return 0;
  memset(pgdir, 0, PGSIZE);
  if (P2V(PHYSTOP) > (void*)DEVSPACE)
    panic(“PHYSTOP too high”);
  for(k = kmap; k < &kmap[NELEM(kmap)]; k++)
    if(mappages(pgdir, k->virt, k->phys_end - k->phys_start,
                (uint)k->phys_start, k->perm) < 0)
      return 0;
  return pgdir;
}

```








## RISC-V

Xv6的物理地址布局在 memlayout.h 中有描述

```c
// Physical memory layout

// qemu -machine virt is set up like this,
// based on qemu's hw/riscv/virt.c:
//
// 00001000 -- boot ROM, provided by qemu
// 02000000 -- CLINT
// 0C000000 -- PLIC
// 10000000 -- uart0 
// 10001000 -- virtio disk 
// 80000000 -- boot ROM jumps here in machine mode
//             -kernel loads the kernel here
// unused RAM after 80000000.

// the kernel uses physical memory thus:
// 80000000 -- entry.S, then kernel text and data
// end -- start of kernel page allocation area
// PHYSTOP -- end RAM used by the kernel
```


```c
void
main()
{
  if(cpuid() == 0){
    consoleinit();
    printfinit();
    printf("\n");
    printf("xv6 kernel is booting\n");
    printf("\n");
    kinit();         // physical page allocator
    kvminit();       // create kernel page table
    kvminithart();   // turn on paging
   	...  
  }
}
```



```c
struct {
  struct spinlock lock;
  struct run *freelist;
} kmem;
```

- 调用 kvminit() 对内核的页表进行初始化，调用 kvmmake() 实现
- 直接映射（物理地址和虚拟地址相同）生成如下的页表（为了使用统一的页表映射策略）
○ UART0：Universal Asynchronous Receiver/Transmitter
○ VIRTIO0：virtio disk
○ PLIC：Platform-Level Interrupt Controller
○ Kernel text（内核代码段）
○ Kernel data（内核数据段）
- 对 TRAMPOLINE 进行虚拟映射
- 映射内核栈，为每一个进程分配一个页的内核栈，在两个内核栈之间分配一个 guard page，用于检测栈溢出
- 接下来就是初始一些数据结构 proc 等
- 以上的建立起虚拟地址和物理地址的映射是通过函数 mappages() 实现的，实现的大致逻辑如下
○ 首先通过 walk() 在已经存在的页表项中检索，如果找到一个有效的页表项，则报错 remap
○ 如果找不到（正常的情况下应该是找不到），此时建立起映射即可，也就是在页表项（第 3 级页表）设置 PPN 的值和物理页的基地址相同，同时设置权限位



```c
void
kvminit(void)
{
  kernel_pagetable = kvmmake();
}


// Make a direct-map page table for the kernel.
pagetable_t
kvmmake(void)
{
  pagetable_t kpgtbl;

  kpgtbl = (pagetable_t) kalloc();
  memset(kpgtbl, 0, PGSIZE);

  // uart registers
  kvmmap(kpgtbl, UART0, UART0, PGSIZE, PTE_R | PTE_W);

  // virtio mmio disk interface
  kvmmap(kpgtbl, VIRTIO0, VIRTIO0, PGSIZE, PTE_R | PTE_W);

  // PLIC
  kvmmap(kpgtbl, PLIC, PLIC, 0x4000000, PTE_R | PTE_W);

  // map kernel text executable and read-only.
  kvmmap(kpgtbl, KERNBASE, KERNBASE, (uint64)etext-KERNBASE, PTE_R | PTE_X);

  // map kernel data and the physical RAM we'll make use of.
  kvmmap(kpgtbl, (uint64)etext, (uint64)etext, PHYSTOP-(uint64)etext, PTE_R | PTE_W);

  // map the trampoline for trap entry/exit to
  // the highest virtual address in the kernel.
  kvmmap(kpgtbl, TRAMPOLINE, (uint64)trampoline, PGSIZE, PTE_R | PTE_X);

  // allocate and map a kernel stack for each process.
  proc_mapstacks(kpgtbl);
  
  return kpgtbl;
}
```

xv6 通过 3 级页表实现页级管理
- 虚拟地址中首先保存着 4 个偏移量 L2、L1、L0、Offset
- 通过 satp 寄存器读取到第一级页表的基地址，通过 L2 找到 PPN1
- PPN1 中记录的第二级页表的基地址，通过 L1 找到 PPN2
- PPN2 记录着第三级页表的基地址，通过 L2 找到 PPN
- PPN 和 页内偏移量 Offset 组合形成最终的物理地址
- 具体是通过函数 walkaddr() 实现的，其中三级页表的翻译是通过 walk() 实现的


```c
// Look up a virtual address, return the physical address,
// or 0 if not mapped.
// Can only be used to look up user pages.
uint64
walkaddr(pagetable_t pagetable, uint64 va)
{
  pte_t *pte;
  uint64 pa;

  if(va >= MAXVA)
    return 0;

  pte = walk(pagetable, va, 0);
  if(pte == 0)
    return 0;
  if((*pte & PTE_V) == 0)
    return 0;
  if((*pte & PTE_U) == 0)
    return 0;
  pa = PTE2PA(*pte);
  return pa;
}
```


```c
// Return the address of the PTE in page table pagetable
// that corresponds to virtual address va.  If alloc!=0,
// create any required page-table pages.
//
// The risc-v Sv39 scheme has three levels of page-table
// pages. A page-table page contains 512 64-bit PTEs.
// A 64-bit virtual address is split into five fields:
//   39..63 -- must be zero.
//   30..38 -- 9 bits of level-2 index.
//   21..29 -- 9 bits of level-1 index.
//   12..20 -- 9 bits of level-0 index.
//    0..11 -- 12 bits of byte offset within the page.
pte_t *
walk(pagetable_t pagetable, uint64 va, int alloc)
{
  if(va >= MAXVA)
    panic("walk");

  for(int level = 2; level > 0; level--) {
    pte_t *pte = &pagetable[PX(level, va)];
    if(*pte & PTE_V) {
      pagetable = (pagetable_t)PTE2PA(*pte);
    } else {
      if(!alloc || (pagetable = (pde_t*)kalloc()) == 0)
        return 0;
      memset(pagetable, 0, PGSIZE);
      *pte = PA2PTE(pagetable) | PTE_V;
    }
  }
  return &pagetable[PX(0, va)];
}
```

- 发生中断时，将 CPU 上进程的第一级页表的及地址存入 stap 寄存器，同时清空 TLB
- 也就是说，将当前页表替换为触发中断的进程的页表，紧接着之后的查找都是在新的页表上执行，具体的翻译步骤就是通过上面的 3 级页表翻译
- 其中每一级页表都有 512 个页表项，支持内存大小可达 \(2^{39}\)
- 清空 TLB 的操作是由如下命令执行的

```c
// flush the TLB.
static inline void
sfence_vma()
{
  // the zero, zero means flush all TLB entries.
  asm volatile("sfence.vma zero, zero");
}
```

- xv6-riscv 的设计和其他的设计不太一样，xv6 的设计中内核态拥有自己的一个页表，这就是说对于 xv6 来说，用户态和内核态的虚拟地址空间都可以达到 0 - MAXVA，这样的设计的好处似乎还挺多
○ 首先我们可以看到，可以分配的空间变大了
○ 在内核态分配空间的时候不需要考虑和用户态是否有交集了
■ 当然直接将内核态和用户态分离开也能马上实现没有交集的效果
○ 当然也存在一些问题，比在在陷入内核、退出内核的时候都需要对 TLB 进行一个清空的操作，这样增大了 TLB miss 的概率，导致效率有所下降
- 用户空间的虚拟地址范围如下



内核态的 CPU 栈与内核栈
- 一开始系统启动的时候为每一个 CPU 都分配了一个栈，这个栈是为了每个 CPU 的前期初始化操作以及调度程序准备的
- 我们可以认为在内核态下，其实是存在两个线程的，一个线程是调度线程，一个线程是由用户态的 trap 进入的
- 因此这两个线程也是需要有自己的栈的
- 所以这样的设计是没有问题的，而且在一定程度上讲确实得这么设计




## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)