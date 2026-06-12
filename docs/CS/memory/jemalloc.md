## Introduction

[jemalloc](http://jemalloc.net/) is a general purpose malloc(3) implementation that emphasizes fragmentation avoidance and scalable concurrency support.
jemalloc first came into use as the FreeBSD libc allocator in 2005, and since then it has found its way into numerous applications that rely on its predictable behavior. 
In 2010 jemalloc development efforts broadened to include developer support features such as heap profiling and extensive monitoring/tuning hooks. 
Modern jemalloc releases continue to be integrated back into FreeBSD, and therefore versatility remains critical. 
Ongoing development efforts trend toward making jemalloc among the best allocators for a broad range of demanding applications, 
and eliminating/mitigating weaknesses that have practical repercussions for real world applications.


jemalloc对哪些进行优化
- false sharing

```c
#include <jemalloc/jemalloc.h>

void *malloc(	size_t size);
void free(	void *ptr);
```


jemalloc基于申请内存的大小把内存分配分为small, large,huge三种类型



## Links

- [Memory](/docs/CS/memory/memory.md)





## References

1. [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)