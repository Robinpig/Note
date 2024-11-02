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



## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)