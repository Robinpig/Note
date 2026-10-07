## Version Baseline

本页与 `JDK/` 下各子页的**默认值、命令行选项与 API 状态**以 **JDK 27** 为准；生产落地按 LTS 基线 **JDK 25** 对齐。

- **最新版本**：JDK 27，2026-09-15 GA，**非 LTS**（常规版本每半年一发，3 月 / 9 月）。
- **当前 LTS**：JDK 25，2025-09 GA（Oracle Premier Support 至 2030-09，Extended Support 至 2033-09）；**下一个 LTS 是 JDK 29（2027-09）**。
- **JDK 27 有两处直接改变默认行为的变化，写死默认值前必看**：
  - **JEP 523 Make G1 the Default Garbage Collector in All Environments**：G1 成为**所有环境**的默认 GC。JDK 9 起 G1 只对 server 环境默认，受限环境（单 CPU，或物理内存 < 1792 MB）会回落 Serial；27 起不再回落，命令行显式指定的收集器仍优先生效。
  - **JEP 534 Compact Object Headers by Default**：**紧凑对象头**在 64 位架构下把对象头由 96 bit 压到 64 bit，27 起**默认启用**。该特性经 JEP 450（JDK 24 引入）、JEP 519（JDK 25 转为正式产品特性）逐步转正，JDK 25 时代需显式 `-XX:+UseCompactObjectHeaders`，27 起无需该选项，必要时可用 `-XX:-UseCompactObjectHeaders` 关闭。
- 读到「G1 是默认（限 server 环境）」「compact object headers 需显式开启」等表述时，均为 JDK 25 及更早口径。

> [!NOTE]
> 版本基线随发版滚动更新；核对单个 API / 选项时以对应 release 的官方文档与 JEP 状态为准，不以本页叙述为准。

## Introduction

> [!NOTE]
> Java is a blue collar language. It’s not PhD thesis material but a language for a job.
>
> -- by James Gosling

Every programming language manipulates elements in memory.
Sometimes the programmer must be constantly aware of that manipulation.
Do you manipulate the element directly, or use an indirect representation that requires special syntax (for example, pointers in [C](/docs/CS/C/C.md) or [C++](/docs/CS/C++/C++.md))?

Java simplifies the issue by [considering everything an object](/docs/CS/Java/JDK/Basic/Object.md), using a single consistent syntax.
Although you treat everything as an object, the identifier you manipulate is actually a “reference” to an object.

In one book I read that it was “completely wrong to say that Java supports pass by reference,” because Java object identifiers(according to that author) are actually “object references.”
And everything is actually pass by value. <br>
**So you’re not passing by reference, you’re “passing an object reference by value.”**

## Knowledge Map

JDK 笔记按「语言基础 → 标准库 → 虚拟机 → I/O」四层展开，另有一组横切主题与生态库。**各分区的入口页同时承担该目录的完整导航**，本页只给分区入口与代表性页面。

**语言与类型基础** —— 入口 [Basics of Java](/docs/CS/Java/JDK/Basic/Basic.md)。覆盖值与引用语义、[Object](/docs/CS/Java/JDK/Basic/Object.md) 对象模型、[String](/docs/CS/Java/JDK/Basic/String.md)、[PrimitiveType](/docs/CS/Java/JDK/Basic/PrimitiveType.md)、[enum](/docs/CS/Java/JDK/Basic/enum.md)、[Generics](/docs/CS/Java/JDK/Basic/Generics.md)、[Lambda](/docs/CS/Java/JDK/Basic/Lambda.md)、[Annotation](/docs/CS/Java/JDK/Basic/Annotation.md)、[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) 与 [Ref](/docs/CS/Java/JDK/Basic/Ref.md)、[Throwable](/docs/CS/Java/JDK/Basic/Throwable.md)、[serialize](/docs/CS/Java/JDK/Basic/serialize.md)、[SPI](/docs/CS/Java/JDK/Basic/SPI.md)、[module](/docs/CS/Java/JDK/Basic/module.md)、[unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)、[JNI](/docs/CS/Java/JDK/Basic/JNI.md)、[JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)、[JNDI](/docs/CS/Java/JDK/Basic/JNDI.md)、[Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)、[Intrinsics](/docs/CS/Java/JDK/Basic/Intrinsics.md)、[JDK 命令行工具](/docs/CS/Java/JDK/Basic/Tools.md)。

**集合框架** —— 入口 [Collection](/docs/CS/Java/JDK/Collection/Collection.md)，下辖 [List](/docs/CS/Java/JDK/Collection/List.md)、[Set](/docs/CS/Java/JDK/Collection/Set.md)、[Queue](/docs/CS/Java/JDK/Collection/Queue.md)、[Map](/docs/CS/Java/JDK/Collection/Map.md)、[WeakHashMap](/docs/CS/Java/JDK/Collection/WeakHashMap.md)。

**并发** —— 入口 [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)，围绕线程与内存模型（[Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)、[JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)、[volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)、[synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)）、锁与同步器（[AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)、[ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md)、[StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md)、[Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md)、[CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)、[Phaser](/docs/CS/Java/JDK/Concurrency/Phaser.md)）、执行框架（[ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)、[ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)、[Future](/docs/CS/Java/JDK/Concurrency/Future.md)）与 Loom 时代原语（[VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)、[ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)、[ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)）展开。

**虚拟机** —— 入口 [JVM](/docs/CS/Java/JDK/JVM/JVM.md)，覆盖类加载（[ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)、[ClassFile](/docs/CS/Java/JDK/JVM/ClassFile.md)、[Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)、[Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)）、运行时数据区（[Runtime_Data_Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)、[Stack](/docs/CS/Java/JDK/JVM/Stack.md)、[frame](/docs/CS/Java/JDK/JVM/frame.md)、[TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)）、执行引擎（[interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)、[c1](/docs/CS/Java/JDK/JVM/c1.md)、[JIT](/docs/CS/Java/JDK/JVM/JIT.md)、[CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)）以及 [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)、[Javac](/docs/CS/Java/JDK/JVM/Javac.md)、[JavaCall](/docs/CS/Java/JDK/JVM/JavaCall.md)、[Graal](/docs/CS/Java/JDK/JVM/Graal.md)、[JMH](/docs/CS/Java/JDK/JVM/JMH.md)、启动与[销毁](/docs/CS/Java/JDK/JVM/destroy.md)。

**垃圾回收** —— 入口 [GC](/docs/CS/Java/JDK/JVM/GC/GC.md)，逐收集器展开：[Serial](/docs/CS/Java/JDK/JVM/GC/Serial.md)、[Parallel](/docs/CS/Java/JDK/JVM/GC/Parallel.md)、[CMS](/docs/CS/Java/JDK/JVM/GC/CMS.md)、[G1](/docs/CS/Java/JDK/JVM/GC/G1.md)、[Shenandoah](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)、[ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC.md)、[Epsilon](/docs/CS/Java/JDK/JVM/GC/Epsilon.md)，以及写屏障相关的 [CardTable](/docs/CS/Java/JDK/JVM/GC/CardTable.md)。

**I/O** —— 入口 [IO](/docs/CS/Java/JDK/IO/IO.md)，下辖 [NIO](/docs/CS/Java/JDK/IO/NIO.md)、[Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)、[io_uring](/docs/CS/Java/JDK/IO/Uring.md)。

**横切主题与 OpenJDK 项目** —— [新版本特性](/docs/CS/Java/JDK/New.md)、[升级](/docs/CS/Java/JDK/Upgrade.md)、[定时任务总览](/docs/CS/Java/JDK/sche.md)、[Project Loom](/docs/CS/Java/JDK/Loom.md)、[Project Valhalla](/docs/CS/Java/JDK/Valhalla.md)、[Servlet](/docs/CS/Java/JDK/Servlet.md)、[ASM 字节码框架](/docs/CS/Java/JDK/ASM.md)、[Java Agent](/docs/CS/Java/JDK/Agent.md) 及其[示例](/docs/CS/Java/JDK/Extension/AgentDemoExample.md)。

**生态库**（同级 `CS/Java/` 目录）—— 连接池 [ConnectionPool](/docs/CS/Java/ConnectionPool/ConnectionPool.md)（[HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)、[Druid](/docs/CS/Java/ConnectionPool/Druid.md)、[DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)）；工具 [Tools](/docs/CS/Java/Tools/Tools.md)（[Arthas](/docs/CS/Java/Tools/Arthas.md)、[JFR](/docs/CS/Java/Tools/JFR.md)、[Lombok](/docs/CS/Java/Tools/Lombok.md)）；序列化与缓存 [Jackson](/docs/CS/Java/Jackson.md)、[Gson](/docs/CS/Java/Gson.md)、[Codec](/docs/CS/Java/Codec.md)、[JCache](/docs/CS/Java/JCache.md)、[Ehcache](/docs/CS/Java/Ehcache.md)、[Guava_Cache](/docs/CS/Java/Guava_Cache.md)；并发框架 [Disruptor](/docs/CS/Java/Disruptor.md)；HTTP 客户端 [Retrofit](/docs/CS/Java/Retrofit.md)；AOP [AspectJ](/docs/CS/Java/AspectJ.md)；测试 [JUnit](/docs/CS/Java/JUnit.md)；日志 [Log4j](/docs/CS/Java/Log4j.md)；运行时 [Quarkus](/docs/CS/Java/Quarkus.md)；[OOP](/docs/CS/Java/OOP.md)。

## Distributions, OpenJDK Projects and JEP

除 Oracle / OpenJDK 官方构建外，国内外厂商与组织维护着各自的 JDK 分支：

- [毕昇 JDK](https://www.openeuler.org/zh/other/projects/bishengjdk/)
- OpenJDK
- 阿里巴巴 Dragonwell 支持 JWarmup，可让代码在灰度环境预热编译后供生产环境直接使用；腾讯 Kona 8 将高版本的 JFR 与 CDS 移植到 JDK 8；龙芯 JDK 支持包含 JIT 的 MIPS 架构，而非 Zero 的解释器版本；Amazon、Azul、Google、Microsoft、Red Hat、Twitter 等也都有自用或开源的 JDK 分支。

OpenJDK 下辖多个子项目，多是为某一较大特性而立项，关注它们可以了解 Java 社区的最新动向和研究方向：

1. **Amber**：探索与孵化面向生产力提升的语言特性，贡献包括模式匹配、Switch 表达式、文本块、局部变量类型推导。
2. **Coin**：决定哪些小的语言改动进入 JDK 7，钻石泛型类型推导与 try-with-resources 都来自 Coin。
3. **Graal**：最初是基于 JVMCI 的编译器，后发展为 Graal VM，目标是让 JavaScript、Python、Ruby、R、JVM 等语言无需改码即可运行在同一虚拟机上。
4. **Jigsaw**：孵化了 Java 9 的模块系统。
5. **Kulla**：实现交互式 REPL 工具，即 JEP 222 的 JShell。
6. **Loom**：探索与孵化 JVM 特性及 API，构建轻量级并发与编程模型，研究方向包括虚拟线程、Continuation、尾递归消除。
7. **Panama**：沟通 JVM 与机器代码，方向有 Vector API 与新一代 JNI。
8. **Shenandoah**：极低暂停时间的垃圾回收器，相较并发标记的 CMS / G1 增加了并发压缩。
9. **Sumatra**：让 Java 程序享受 GPU、APU 等异构芯片的好处。
10. **Tsan**：为 Java 提供 Thread Sanitizer 检查，可发现 Java 与 JNI 代码中潜在的数据竞争。
11. **Valhalla**：探索值类型（Value Type）、嵌套权限访问控制（Nest-based Access Control），以及对基本类型作为泛型参数的支持。
12. **ZGC**：低延时、高伸缩的垃圾回收器，目标暂停时间不超过 10ms 且不随堆变大而变长，关键词包括并发、Region、压缩、NUMA、着色指针、读屏障。
13. **Lilliput**：缩小对象头（已产出 JEP 450 / 519 / 534 系列）。

**JEP（Java Enhancement Proposal）** 即 Java 改进提案：社区在某方面需要较大代码变更，或某项工作的目标、进展、结果值得广泛讨论时，可起草正式 JEP 提交 OpenJDK 社区。每个 JEP 有唯一编号，方便讨论时代指某个提案。JEP 之于 Java 如同 PEP 之于 Python、RFC 之于 Rust。较大的 Java / JVM 特性实现前通常都有 JEP；处于「草案」和「候选」状态的 JEP **不能保证最终进入 JDK 发行版**。

**JSR（Java Specification Request）** 常与 JEP 一起出现：想开发实验性特性（探索新奇点子、实现原型、增强当前特性）时可先提 JEP，其中少数随技术成熟会被 JSR 进一步规范化，形成新的语言规范或修改当前语言规范。

## Build

参考 https://github.com/Robinpig/jdk

## Security

如需更高安全等级，可启用 SecurityManager：

```bash
-Djava.security.manager
```

相关命令行工具：`keytool`（密钥与证书库管理）、`jarsigner`（JAR 签名）。

- [JEP 332: Transport Layer Security (TLS) 1.3](https://openjdk.org/jeps/332)
- JDK 27 起 TLS 1.3 支持后量子混合密钥交换，见 [JEP 527: Post-Quantum Hybrid Key Exchange for TLS 1.3](https://openjdk.org/jeps/527)。

### Zip Bomb Attack

The central idea of zip bomb attacks is to exploit the characteristics of the zip compressor and its techniques to create small and easy-to-transport zip files. However, these files require many computational resources (time, processing, memory, or disk) to uncompress.

The most common objective of a zip bomb is rapidly consuming the available computer memory in a relatively CPU-intensive process. In such a way, the attacker expects that the computer victim of a zip bomb crashes at some point.

However, attackers may design zip bombs to exploit other characteristics of software installed on the victim’s computer. For example, some zip bombs aim to crash file systems without consuming all the computer’s memory.

## Performance

The truth is that performance analysis is a weird blend of hard empiricism and squishy human psychology.
What matters is, at one and the same time, the absolute numbers of observable metrics and how the end users and stakeholders feel about them.

- No magic “go faster” switches for the JVM
- No “tips and tricks” to make Java run faster
- No secret algorithms that have been hidden from you

### Performance Metrics

One common basic set of performance metrics is:

- Throughput
- Latency
- Capacity
- Utilization
- Efficiency
- Scalability
- Degradation

#### Capacity

Capacity is usually quoted as the processing available at a given value of latency or throughput.

#### Efficiency

Dividing the throughput of a system by the utilized resources gives a measure of the overall efficiency of the system.
It is also possible, when one is dealing with larger systems, to use a form of cost accounting to measure efficiency.

#### Scalability

The holy grail of system scalability is to have throughput change exactly in step with resources.

#### Degradation

If we increase the load on a system, either by increasing the number of requests (or clients) or by increasing the speed requests arrive at, then we may see a change in the observed latency and/or throughput.
If the system is underutilized, then there should be some slack before observables change, but if resources are fully utilized then we would expect to see throughput stop increasing, or latency increase.
These changes are usually called the degradation of the system under additional load.

In rare cases, additional load can cause counterintuitive results.
For example, if the change in load causes some part of the system to switch to a more resource-intensive but higher-performance mode(such as JIT),
then the overall effect can be to reduce latency, even though more requests are being received.

`performance elbow`

## Tuning

Java 的编译和启动时长都较长，开发和部署效率低。

Maven 改造：大多数编译慢的情况都发生在生成依赖树阶段，依赖多而复杂就更易去仓库下载依赖。

- 优化依赖分析算法，边生成依赖树边进行版本仲裁
- 增量缓存依赖树，修改 pom 文件的情况远小于修改自己代码的情况
- 将 Maven 程序编译成机器码运行

升级的动因与顾虑见 [Upgrade](/docs/CS/Java/JDK/Upgrade.md)：动因多为性能提升（如 JVM / GC）与框架支持（如 Spring）；顾虑主要来自依赖（如 XML 相关）。另需注意 JDWP 的 host 从 `0.0.0.0` 收紧为 `localhost` 后不再支持远程调试。

## Summary

Java 相对于其它现代语言主要的优势还是生态庞大。和其它语言相比的缺点：

- 启动耗时较长，需加载大量类
- 占用内存大，JVM 固定占用内存
- 面向对象过于严格，编写简单程序较麻烦，不像 Go 可以返回多个响应
- 语法繁琐，相较 Python

## Links

- [OOP](/docs/CS/Java/OOP.md)
- [编程语言横向对比](/docs/CS/Languages.md)

## References

1. [The Java Language Environment: Contents A White Paper](https://www.oracle.com/java/technologies/language-environment.html)
2. [Java Performance Tuning](http://www.javaperformancetuning.com/)
3. [The Java Tutorial](https://docs.oracle.com/javase/tutorial/)
4. [Oracle Java SE Support Roadmap](https://www.oracle.com/java/technologies/java-se-support-roadmap.html)
