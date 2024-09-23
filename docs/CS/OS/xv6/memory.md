## Introduction



为方便管理物理内存 xv6的内核态页表具备所有可用物理内存的直接映射 可以直接访问物理内存





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