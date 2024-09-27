## Introduction



为方便管理物理内存 xv6的内核态页表具备所有可用物理内存的直接映射 可以直接访问物理内存



操作系统通过页表来向每个进程提供私有的地址空间和内存。页表决定了内存地址的含义，哪些物理内存可以访问。xv6使用页表分隔不同进程的地址空间，并把它们多路复用到单一的物理内存。xv6还使用页表实现了一些技巧：把同一块内存映射到多个地址空间(a trampoline page)，使用未映射的页来保护内核和用户的栈





当xv6在进程间切换的时候，进程的页表也会跟着切换

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