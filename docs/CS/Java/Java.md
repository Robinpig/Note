## Introduction

Java 是一门**跑在 JVM 上的静态强类型语言**：源码编译成字节码，由 JVM 解释 + JIT 执行，靠 GC 管理内存。它的核心竞争力不在语法，而在**跨平台运行时 + 成熟可观测性 + 企业级生态厚度**——Spring、Netty、Kafka、Flink、Hadoop 都构建其上。逐门语言的适用场景与横向对比，见本站的《编程语言横向对比》。

本页是 `docs/CS/Java/` 的**语言入口与目录地图**。下方的「本目录包含」给出该目录下所有主题分区的入口；JDK 与 JVM 的内部机制（类加载、内存模型、GC、JIT…）由 [JDK/JDK.md](/docs/CS/Java/JDK/JDK.md) 这一核心枢纽展开，本页不再重复。

> 版本基线：本库 Java 相关笔记的默认值与 API 状态以 **JDK 27** 为准、生产按 LTS **JDK 25** 对齐，详见 [JDK/JDK.md 的版本基线](/docs/CS/Java/JDK/JDK.md)。

## This Directory Contains

Java 目录按「语言基础 → 标准库 → 虚拟机 → I/O → 生态」组织，主要分区如下：

- **JDK 与 JVM（核心枢纽）**：[JDK/JDK.md](/docs/CS/Java/JDK/JDK.md) 为总入口，下辖 **语言基础**（[Basic](/docs/CS/Java/JDK/Basic/Basic.md)：Object / String / 泛型 / Lambda / 反射 / 序列化…）、**集合框架**（[Collection](/docs/CS/Java/JDK/Collection/Collection.md)）、**并发**（[Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)：JMM / 锁 / 线程池 / Loom 虚拟线程）、**虚拟机**（[JVM](/docs/CS/Java/JDK/JVM/JVM.md)：类加载 / 运行时数据区 / JIT / GC）、**垃圾回收**（[GC](/docs/CS/Java/JDK/JVM/GC/GC.md)：G1 / ZGC / Shenandoah…）。版本演进见 [New](/docs/CS/Java/JDK/New.md)、[Valhalla](/docs/CS/Java/JDK/Valhalla.md)、[Loom](/docs/CS/Java/JDK/Loom.md)、[Upgrade](/docs/CS/Java/JDK/Upgrade.md)。
- **面向对象基础**：[OOP.md](/docs/CS/Java/OOP.md) —— 封装 / 继承 / 多态与 Java 的对象模型。
- **连接池**：[ConnectionPool/](/docs/CS/Java/ConnectionPool/ConnectionPool.md) —— DBCP / Druid / HiKariCP 对比。
- **工具与诊断**：[Tools/](/docs/CS/Java/Tools/Tools.md) —— 含 JFR 等运行时诊断。
- **生态与框架**：[AspectJ](/docs/CS/Java/AspectJ.md)（AOP）、[Codec](/docs/CS/Java/Codec.md)、[Disruptor](/docs/CS/Java/Disruptor.md)（高性能环形队列）、[Ehcache](/docs/CS/Java/Ehcache.md) / [Guava_Cache](/docs/CS/Java/Guava_Cache.md) / [JCache](/docs/CS/Java/JCache.md)（缓存）、[Gson](/docs/CS/Java/Gson.md) / [Jackson](/docs/CS/Java/Jackson.md)（JSON）、[Log4j](/docs/CS/Java/Log4j.md)（日志）、[JUnit](/docs/CS/Java/JUnit.md)（测试）、[Quarkus](/docs/CS/Java/Quarkus.md)（云原生框架）、[Retrofit](/docs/CS/Java/Retrofit.md)（HTTP 客户端）。

## Links

- [编程语言横向对比](/docs/CS/Languages.md)

## References

- [Java SE Documentation](https://docs.oracle.com/en/java/)
- [JEP Index](https://openjdk.org/jeps/)
