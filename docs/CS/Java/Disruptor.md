## Introduction

The London Multi-Asset Exchange (LMAX) Disruptor is an open source concurrency framework that recently won the 2011 Duke’s Choice Award for Innovative Programming Framework.

The Disruptor is a framework for interthread communication (ITC), that is, the sharing of data among threads.
LMAX created the Disruptor as part of its reliable messaging architecture and developed it into an extremely fast way of handing off data between different components.

Using mechanical sympathy (an understanding of how the underlying hardware works), fundamental computer science, and domain-driven design, 
the Disruptor has evolved into a framework that developers can use to do much of the heavy lifting for concurrent programming.

目前，包括Apache Storm、Camel、Log4j 2在内的很多知名项目都应用了Disruptor以获取高性能

Java内置的[并发队列](/docs/CS/Java/JDK/Collection/Queue.md?id=BlockingQueue) 底层实现一般分成三种：数组、链表和堆
例如 ArrayBlockingQueue有三个成员变量： - takeIndex：需要被取走的元素下标 - putIndex：可被元素插入的位置的下标 - count：队列中元素的数量

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


 



预分配内存（消除 GC 压力）：
在 Disruptor 初始化时，会提前创建好所有的 Event（事件）对象并填充到数组中。
运行时，生产者和消费者只是修改这些预分配对象的属性，而不是创建新对象或回收旧对象，从而彻底消除了垃圾回收（GC）带来的停顿。


消费者在消费时，不是每次只处理一个事件，而是获取当前可用的最大序列号，一次性批量处理多个事件，减少了方法调用和边界检查的开销


## Architecture

Disruptor 的架构非常清晰，主要由以下几个核心组件构成：
RingBuffer（环形缓冲区）：
核心数据结构，本质上是一个数组，用于存储 Event。
Event（事件）：
数据的载体，由用户定义。
Sequencer（序列器）：
Disruptor 的大脑。负责分配序列号，协调生产者和消费者之间的并发控制。分为单生产者（SingleProducerSequencer）和多生产者（MultiProducerSequencer）两种实现。
Sequence（序列号）：
用于标识 RingBuffer 中某个位置。每个生产者、消费者都有自己独立的 Sequence，用于记录当前处理到的进度。
SequenceBarrier（序列屏障）：
消费者用来等待生产者或其他消费者进度的屏障。它包含了等待策略（WaitStrategy）和依赖关系。
WaitStrategy（等待策略）：
当消费者追上生产者（或消费者追上消费者）时，如何等待。Disruptor 提供了多种策略：
BlockingWaitStrategy：使用 Lock 和 Condition，CPU 消耗最低，但延迟最高。
SleepingWaitStrategy：先自旋，再 yield()，最后 sleep()，平衡了延迟和 CPU 消耗。
YieldingWaitStrategy：先自旋，再 Thread.yield()，适合低延迟场景。
BusySpinWaitStrategy：疯狂自旋，延迟最低，但 CPU 消耗最大（需绑定 CPU 核心）。
EventProcessor / EventHandler：
EventProcessor 是消费者线程，负责循环拉取事件。
EventHandler 是用户实现的具体业务逻辑接口，由 EventProcessor 调用。



## 工作流程


1. 生产者发布事件
生产者向 Sequencer 请求下一个可用的 Sequence（调用 next()）。
Sequencer 通过 CAS 分配 Sequence，并检查该 Sequence 是否已经覆盖了最慢的消费者（如果 RingBuffer 满了，则根据等待策略阻塞或自旋）。
生产者拿到 Sequence 后，通过 ringBuffer.get(sequence) 获取预分配的 Event 对象。
生产者填充 Event 的数据。
生产者调用 publish(sequence) 发布事件。这一步会更新生产者的 Sequence，并唤醒正在等待的消费者。
2. 消费者处理事件
消费者（EventProcessor）通过 SequenceBarrier 等待可用的 Sequence。
当生产者发布事件后，消费者获取到当前可用的最大 Sequence。
消费者根据自己当前的 Sequence 和可用的最大 Sequence，批量从 RingBuffer 中读取 Event。
调用用户实现的 EventHandler 处理 Event。
处理完成后，消费者更新自己的 Sequence，并通知下游消费者（如果有依赖关系）或唤醒生产者。







## Summary


底层优化细节（面试常考）

1. 消除伪共享（False Sharing）
问题：在多核 CPU 中，缓存是以“缓存行”（Cache Line，通常 64 字节）为单位加载的。如果两个被频繁修改的变量（如生产者的 Sequence 和消费者的 Sequence）在内存中挨得很近，它们可能会落入同一个缓存行。一个 CPU 核心修改了其中一个变量，会导致另一个 CPU 核心的缓存行失效，这就是伪共享，会严重降低性能。
Disruptor 的解决：在 Sequence 类的实现中，通过缓存行填充（Cache Line Padding），在 value 变量前后填充了大量的 long 类型变量（p1, p2, p3...），强制将 value 隔离到独立的缓存行中，彻底消除伪共享。
2. 内存屏障（Memory Barrier）
在多线程环境下，CPU 和编译器可能会对指令进行重排序。Disruptor 在关键操作（如发布事件、更新 Sequence）时，使用了 volatile 关键字和底层的内存屏障指令（如 LoadLoad, StoreStore），确保：
生产者填充 Event 数据的操作，必须在更新 Sequence 之前完成（防止消费者读到未填充完的脏数据）。
消费者读取 Event 数据的操作，必须在读取 Sequence 之后进行。




优点：
极高的吞吐量：无锁设计、CAS、批量处理。
极低的延迟：避免了线程上下文切换和锁竞争。
对 GC 友好：预分配内存，运行时无对象创建和销毁。
缺点/注意事项：
内存占用大：因为预分配了所有 Event 对象，如果 RingBuffer 设置得很大，或者 Event 对象本身很大，会占用大量内存。
不适合长生命周期数据：Disruptor 适合处理瞬时、突发的高并发事件流。如果数据需要长期存储或处理时间极长，会导致 RingBuffer 迅速被填满，阻塞生产者。

适用场景：
金融交易系统（如 LMAX 本身的应用）。
高性能日志收集与处理（如 Log4j2 的 AsyncLogger 底层就是基于 Disruptor）。
复杂事件处理（CEP）、实时流计算。
系统内部模块间的高性能异步解耦。


## References

1. [LMAX Disruptor](http://lmax-exchange.github.io/disruptor/)
2. [高性能队列——Disruptor](https://tech.meituan.com/2016/11/18/disruptor.html)
