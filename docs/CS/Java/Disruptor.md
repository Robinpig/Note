## Introduction

伦敦多资产交易所（LMAX）开发的 Disruptor 是一个开源并发框架，曾荣获 2011 年 Duke's Choice Award 创新编程框架奖。

Disruptor 是一个用于线程间通信（ITC）的框架，即在线程之间共享数据。
LMAX 创建 Disruptor 作为其可靠消息传递架构的一部分，并将其发展成为一种在组件之间传递数据的极快方式。

通过利用机械同情（理解底层硬件的工作原理）、基础计算机科学和领域驱动设计，
Disruptor 已经发展成为一个开发者可以用来承担并发编程大量繁重工作的框架。

目前，包括Apache Storm、Camel、Log4j 2在内的很多知名项目都应用了Disruptor以获取高性能

Java内置的[并发队列](/docs/CS/Java/JDK/Collection/Queue.md?id=BlockingQueue) 底层实现一般分成三种：数组、链表和堆

ArrayBlockingQueue有三个成员变量： - takeIndex：需要被取走的元素下标 - putIndex：可被元素插入的位置的下标 - count：队列中元素的数量

这三个变量很容易放到一个缓存行中，但是之间修改没有太多的关联。所以每次修改，都会使之前缓存的数据失效，从而不能完全达到共享的效果
当生产者线程put一个元素到ArrayBlockingQueue时，putIndex会修改，从而导致消费者线程的缓存中的缓存行无效，需要从主存中重新读取。
这种无法充分使用缓存行特性的现象，称为伪共享

## Architecture

Disruptor通过以下设计来解决队列速度慢的问题：

- 环形数组结构
  为了避免垃圾回收，采用数组而非链表。同时，数组对处理器的缓存机制更加友好。
- 元素位置定位
  数组长度2^n，通过位运算，加快定位的速度。下标采取递增的形式。不用担心index溢出的问题。index是long类型，即使100万QPS的处理速度，也需要30万年才能用完。
- 无锁设计
  每个生产者或者消费者线程，会先申请可以操作的元素在数组中的位置，申请到之后，直接在该位置写入或者读取数据。

## write

## References

1. [LMAX Disruptor](http://lmax-exchange.github.io/disruptor/)
2. [高性能队列——Disruptor](https://tech.meituan.com/2016/11/18/disruptor.html)
