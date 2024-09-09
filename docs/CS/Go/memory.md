## Introduction



Go语言采用现代内存分配TCMalloc算法的思想来进行内存分配，将对象分为微小对象、小对象、大对象，使用三级管理结构mcache、mcentral、mheap用于管理、缓存加速span对象的访问和分配，使用精准的位图管理已分配的和未分配的对象及对象的大小。
 



## Links

