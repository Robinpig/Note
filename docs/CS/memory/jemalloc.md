## Introduction

[jemalloc](http://jemalloc.net/) 是一个通用的 malloc(3) 实现，强调避免碎片化和可扩展的并发支持。
jemalloc 于 2005 年首次作为 FreeBSD libc 分配器使用，此后被众多依赖其可预测行为的应用程序采用。
2010 年，jemalloc 的开发工作扩展到包括开发者支持功能，如堆分析以及广泛的监控/调优钩子。
现代 jemalloc 版本继续被整合回 FreeBSD，因此通用性仍然至关重要。
持续的开发努力趋向于使 jemalloc 成为广泛苛刻应用中最好的分配器之一，
并消除/减轻对现实世界应用有实际影响的弱点。

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
