## Introduction

[Project Loom](https://openjdk.org/projects/loom/) is to intended to explore, incubate and deliver Java VM features and APIs built on top of them for the purpose of supporting easy-to-use, high-throughput lightweight concurrency and new programming models on the Java platform.

It is **not a single feature** but a family of three pillars, each shipping on its own JDK timeline:

| 支柱 | 解决什么 | 关键 JEP | JDK 状态 |
| --- | --- | --- | --- |
| **Virtual Threads**（虚拟线程） | 百万级轻量线程，thread-per-task 风格重获可扩展性 | JEP 444 | **JDK 21 定稿（GA）** |
| **Structured Concurrency**（结构化并发） | 把并发子任务的生命周期绑定到代码块，消除「线程泄漏」与取消传播难题 | JEP 505 | **JDK 25 仍为第五次预览**（`--enable-preview`） |
| **Scoped Values**（作用域值） | 在大量虚拟线程下安全、廉价地传递上下文，取代 `ThreadLocal` | JEP 506 | **JDK 25 定稿（final）** |

> 下文只给项目层总览；三大支柱的**实现机制**分别深入 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)、[StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md)、[ScopedValues](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)。

## JDK Timeline

| 版本 | 关键变化 | 实践含义 |
| --- | --- | --- |
| JDK 19 / 20 | 虚拟线程预览（JEP 425 / 436） | 仅供实验 |
| **JDK 21 (LTS)** | 虚拟线程定稿（JEP 444） | 生产可用；但 `synchronized` 内阻塞会 **pinning** carrier |
| JDK 23 | 虚拟线程 dump 改进（含锁归属信息） | 诊断死锁不再依赖堆转储 |
| **JDK 24** | `synchronized` 不再 pinning（JEP 491） | pinning 主因消除，官方建议**停止**用 `ReentrantLock` 替代 `synchronized` 作为 workaround |
| **JDK 25 (LTS)** | 作用域值定稿（JEP 506）；结构化并发第五次预览（JEP 505） | 首个含 pinning 修复的 LTS，且 `ThreadLocal` 有了稳定替代 |

## Virtual Threads

Currently, the thread construct offered by the Java platform is the [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md) class, which is implemented by a kernel thread; it relies on the OS for the implementation of both the continuation and the scheduler.

Project Loom introduces **fibers** (虚拟线程) as lightweight, efficient threads managed by the JVM, letting developers use the same simple abstraction with better performance and lower footprint. A fiber is made of two components — a **continuation** and a **scheduler**:

- **Continuation（续延）**：一段可挂起/恢复的执行序列，由 JVM 原生支持（不依赖 OS 线程栈）。它是 Loom 的次要目标——作为公共 API 也有价值。
- **Scheduler（调度器）**：默认是 `ForkJoinPool`（异步模式），把虚拟线程 mount 到少量平台线程（carrier）上；原 `ForkJoinPool` 本身就擅长调度频繁阻塞的任务。虚拟线程支持可插拔调度器（SPI 可简至 `Executor`）。

> **Never forget that virtual threads aren't faster threads.** Virtual threads don't magically execute more instructions per second than platform threads do. What virtual threads are really good for is **waiting**. Because they don't block an OS thread, potentially millions of virtual threads can wait patiently for I/O (filesystem, databases, web services). By maximizing utilization of external resources, virtual threads provide larger **scale**, not more speed — i.e. they improve **throughput** and code quality.

## Structured Concurrency & Scoped Values

这两者是虚拟线程之上、面向「可维护并发」的 API 层：

- **Structured Concurrency**：用 `StructuredTaskScope` 把任务拆成若干 subtask，要求它们在代码块结束前全部完成（或出错取消）。核心是 `fork` + `join`，owner 线程负责生命周期。详见 [StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md)。
- **Scoped Values**：在作用域内一次性写入、供其内所有线程（含虚拟线程）只读读取，无哈希表查找、无继承开销，是 `ThreadLocal` 的轻量替代。详见 [ScopedValues](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)。

## Demo

```java
public class ThreadDemo {
    public static void main(String[] args) throws InterruptedException {
        Thread thread = Thread.ofVirtual().start(() -> System.out.println("Hello"));
        thread.join();
    }
}
```

## Status & Caveats (as of JDK 25)

- 虚拟线程与作用域值已 **final**，可直接用于生产；结构化并发截至 JDK 25 仍是 **预览**，每个版本 API 形状都可能调整。
- **pinning 已非主要障碍**：JEP 491（JDK 24）让 `synchronized` 与 `Object.wait()` 不再 pin carrier，绝大多数「换 ReentrantLock」的迁移是多余的。
- 虚拟线程数量可达百万级，**`ThreadLocal` 使用须极度谨慎**（每个 VT 都复制/隔离，内存放大）；优先改用 Scoped Values。

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
- [StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md)
- [ScopedValues](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)
- [frame](/docs/CS/Java/JDK/JVM/frame.md)
- [Stack](/docs/CS/Java/JDK/JVM/Stack.md)

## References

1. [Project Loom](https://openjdk.org/projects/loom/)
2. [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
3. [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491)
4. [JEP 505: Structured Concurrency (Fifth Preview)](https://openjdk.org/jeps/505)
5. [JEP 506: Scoped Values](https://openjdk.org/jeps/506)
6. [JEP 425: Virtual Threads (Preview)](https://openjdk.org/jeps/425)
7. [Going inside Java's Project Loom and virtual threads](https://blogs.oracle.com/javamagazine/post/going-inside-javas-project-loom-and-virtual-threads)
