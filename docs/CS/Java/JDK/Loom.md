## Introduction

[Project Loom](https://cr.openjdk.java.net/~rpressler/loom/Loom-Proposal.html) 旨在探索、孵化并提供 Java VM 特性及基于这些特性构建的 API，以支持在 Java 平台上实现易用、高吞吐量的轻量级并发和新编程模型。
这是通过添加以下结构来实现的：

- Virtual threads
- Delimited continuations
- Tail-call elimination

Project Loom 将引入 fibers 作为由 Java 虚拟机管理的轻量级、高效的线程，让开发者使用相同的简单抽象，但具有更好的性能和更低的开销。
一个 fiber 由两个组件组成——一个 continuation 和一个 scheduler。
由于 Java 已经以 `ForkJoinPool` 的形式拥有一个优秀的调度器，fibers 将通过向 JVM 添加 continuation 来实现。

## What Threads Are

目前，Java 平台提供的线程构造是 [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md) 类，它由内核线程实现；它依赖操作系统来实现 continuation 和 scheduler。

## Continuations

向 Java 平台添加 continuation 的动机是为了实现 fibers，但 continuation 还有其他一些有趣的用途，因此这个项目的次要目标是提供 continuation 作为公共 API。

## Fibers

Fibers 就是我们所说的 Java 计划的用户模式线程。

永远不要忘记虚拟线程不是更快的线程。虚拟线程不会神奇地每秒执行比平台线程更多的指令。
虚拟线程真正擅长的是等待。
因为虚拟线程不需要或阻塞 OS 线程，潜在的数百万个虚拟线程可以耐心等待文件系统、数据库或 Web 服务的请求完成。
通过最大化外部资源的利用率，虚拟线程提供的是更大的规模，而不是更快的速度。换句话说，它们提高了吞吐量。
除了硬指标之外，虚拟线程还可以提高代码质量。

## Schedulers

如上所述，像 `ForkJoinPools` 这样的工作窃取调度器特别适合调度那些经常阻塞并通过 IO 或与其他线程进行通信的线程。
然而，fibers 将具有可插拔的调度器，用户将能够编写自己的调度器（scheduler 的 SPI 可以像 `Executor` 那样简单）。
基于先前的经验，预计异步模式下的 `ForkJoinPool` 可以作为大多数用途的优秀默认 fiber 调度器，
但我们可能也想探索一种或两种更简单的设计，例如固定调度器，它总是将给定的 fiber 调度到特定的内核线程（假定该线程固定在一个处理器上）。

## Demo

```java

public class ThreadDemo {

    public static void main(String[] args) throws InterruptedException {
        Thread thread = Thread.ofVirtual().start(() -> System.out.println("Hello"));
        thread.join();
    }
}
```

- [JEP 353: Reimplement the Legacy Socket API](https://openjdk.org/jeps/353)
- [JEP 373: Reimplement the Legacy DatagramSocket API](https://openjdk.org/jeps/373)
- [JEP 425: Virtual Threads (Preview)](https://openjdk.org/jeps/425)
## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. [Project Loom: Fibers and Continuations for the Java Virtual Machine](https://cr.openjdk.java.net/~rpressler/loom/Loom-Proposal.html)
2. [Project Loom on GitHub](https://github.com/openjdk/loom)
2. [State of Loom](http://cr.openjdk.java.net/~rpressler/loom/loom/sol1_part1.html)
3. [Going inside Java's Project Loom and virtual threads](https://blogs.oracle.com/javamagazine/post/going-inside-javas-project-loom-and-virtual-threads)
