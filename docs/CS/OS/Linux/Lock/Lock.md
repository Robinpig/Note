## Introduction



锁的实现大多位于 lernel/locking 目录下 内核中的资源锁有基于硬件总线的原子操作（spinlock、mutex、rwlock、seqlock、RCU锁、信号量）和对文件内容进行保护的文件锁


rwlock在本质上是spinlock的一种 它在spinlock概念上增加了一个类似信号量的读计数器 读操作首先获得spinlock 然后增加引用计数 最后释放spinlock 写操作需要满足引用计数为0和获取到spinlock 写操作获得rwlock后不会释放spinlock 这样做到独占 但是rwlock容易造成写饥饿

在允许睡眠情况下可以使用 rwsem 在不允许睡眠的高响应要求下 可以使用seqlock

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)