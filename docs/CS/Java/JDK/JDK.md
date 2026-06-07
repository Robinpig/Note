## Introduction

> [!NOTE]
> Java is a blue collar language. It’s not PhD thesis material but a language for a job.
>
> -- by James Gosling

每种编程语言都操作内存中的元素。
有时程序员必须时刻注意这种操作。
你是直接操作元素，还是使用需要特殊语法的间接表示（例如 [C](/docs/CS/C/C.md) 或 [C++](/docs/CS/C++/C++.md) 中的指针）？

Java 通过[将所有内容视为对象](/docs/CS/Java/JDK/Basic/Object.md)并使用统一的语法来简化这个问题。
虽然你将所有内容都视为对象，但你操作的标识符实际上是对对象的"引用"。

在一本书中我读到"说 Java 支持按引用传递是完全错误的"，因为根据该作者的观点，Java 对象标识符实际上是"对象引用"。
而所有东西实际上都是按值传递的。 <br>
**所以你不是按引用传递，而是"按值传递对象引用"。**

JDK版本

- [毕昇JDK](https://www.openeuler.org/zh/other/projects/bishengjdk/)
- OpenJDK
- 
例如，国内厂商阿里巴巴的Dragonwell支持JWarmup，可以让代码在灰度环境预热编译后供生产环境直接使用；腾讯的Kona 8将高版本的JFR和CDS移植到JDK 8上；龙芯JDK支持包含JIT的MIPS架构，而非Zero的解释器版本；国外厂商Amazon、Azul、Google、Microsoft、Red Hat、Twitter等都有维护自用或者开源的JDK分支

OpenJDK包含很多子项目，它们大都是为了实现某一较大的特性而立项，关注它们可以了解Java社区的最新动向和研究方向。一些重要和有趣的子项目如下所示。
1）Amber：探索与孵化一些小面向生产力提升的Java语言特性。Amber项目的贡献包括模式匹配、Switch表达式、文本块、局部变量类型推导等语言特性。
2）Coin：决定哪些小的语言改变会添加进JDK7。常用的钻石形式的泛型类型推导语法以及try-with-resource语句都来自Coin项目。
3）Graal：Graal最初是基于JVMCI的编译器，后面进一步发展出Graal VM，旨在开发一个通用虚拟机平台，允许JavaScript、Python、Ruby、R、JVM等语言运行在同一个虚拟机上而不需要修改应用自身的代码
4）Jigsaw：Jigsaw孵化了Java 9的模块系统。
5）Kulla：实现一个交互式REPL工具，即JEP 222的JShell工具。
6）Loom：探索与孵化JVM特性及API，并基于此构建易用、高吞吐量的轻量级并发与编程模型。目前Loom的研究方向包括协程、Continuation、尾递归消除。
7）Panama：沟通JVM和机器代码，研究方向有Vector API和新一代JNI。
8）Shenandoah：拥有极低暂停时间的垃圾回收器。相较并发标记的CMS和G1，Shenandoah增加了并发压缩功能。
9）Sumatra：让Java程序享受GPU、APU等异构芯片带来的好处。目前关注于让GPU在HotSpot VM代码生成、运行时支持和垃圾回收上发挥作用。
10）Tsan：为Java提供Thread Sanitizer检查工具，可以检查Java和JNI代码中潜在的数据竞争。
11）Valhalla：探索与孵化JVM及Java的语言特性，主要贡献有备受瞩目的值类型（Value Type）、嵌套权限访问控制（Nest-based Access Control），以及对基本类型作为模板参数的泛型支持。
12）ZGC：低延时、高伸缩的垃圾回收器。它的目标是使暂停时间不超过10ms，且不会随着堆变大或者存活对象变多而变长，同时可以接收（包括但不限于）小至几百兆，大至数十T的堆。ZGC的关键字包括并发、Region、压缩、支持NUMA、使用着色指针、使用读屏障

JEP（Java Enhancement Proposal）即Java改进提案。所谓提案是指社区在某方面的努力，比如在需要一次较大的代码变更，或者某项工作的目标、进展、结果值得广泛讨论时，就可以起草书面的、正式的JEP到OpenJDK社区。每个JEP都有一个编号，为了方便讨论，通常使用JEP ID代替某个改进提案。
JEP之于Java就像PEP之于Python、RFC之于Rust，它代表了Java社区最新的工作动向和未来的研究方向。在较大的Java/JVM特性实现前通常都有JEP，它是Java社区成员和领导者多轮讨论的结果。JEP描述了该工作的动机、目标、详细细节、风险和影响等，通过阅读JEP（如果有的话），可以更好地了解Java/JVM某个特性。下面摘录了一些较新的JEP，注意，处于"草案"和"候选"状态的JEP不能保证最终会被加入JDK发行版。

另一个常常与JEP一起出现的是JSR（Java Specification Request，Java规范提案）。有时人们想开发一些实验性特性，例如探索新奇的点子、实现特性的原型，或者增强当前特性，在这些情况下都可以提出JEP，让社区也参与实现或者讨论。这些JEP中的少数可能会随着技术的发展愈发成熟，此时，JSR可以将这些成熟的技术提案进一步规范化，产生新的语言规范，或者修改当前语言规范，将它们加入Java语言标准中。

## Build

参考 https://github.com/Robinpig/jdk

## Basics

[Basics of Java](/docs/CS/Java/JDK/Basic/Basic.md)

## Collection

Java 中的 [Collection](/docs/CS/Java/JDK/Collection/Collection.md) 是一个框架，提供了存储和操作对象组的架构。

## Concurrency

[Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md) 是同时执行多个线程的过程。

## JVM

[JVM (Java Virtual Machine)](/docs/CS/Java/JDK/JVM/JVM.md) 是一个抽象机器。它是一个规范，提供了 Java 字节码可以执行的运行时环境。

## Security

if you want to high security, please enable

-Djava.security.manager

SecurityManger

[JEP 332: Transport Layer Security (TLS) 1.3](https://openjdk.org/jeps/332)

keytool

jarsigner

### Zip Bomb Attack

zip bomb 攻击的核心思想是利用 zip 压缩器及其技术的特性来创建易于传输的小型 zip 文件。
然而，这些文件需要大量的计算资源（时间、处理、内存或磁盘）来解压。

zip bomb 最常见的目标是在相对 CPU 密集的过程中快速消耗可用的计算机内存。
通过这种方式，攻击者期望成为 zip bomb 受害者的计算机在某个时刻崩溃。

然而，攻击者可能设计 zip bomb 以利用受害者计算机上安装的其他软件的特性。
例如，有些 zip bomb 的目标是在不消耗所有计算机内存的情况下使文件系统崩溃。

## Projects

Project 是为产生特定工件而进行的协作努力，可以是一段代码、文档或其他材料。
一个 Project 必须由一个或多个 Group 赞助。
一个 Project 可以有网页内容、一个或多个文件仓库，以及一个或多个邮件列表。

- [Project Valhalla](/docs/CS/Java/JDK/Valhalla.md) 计划用值对象和用户定义的原始类型来增强 Java 对象模型，将面向对象编程的抽象与简单原始类型的性能特性结合起来。
  这些特性将伴随着 Java 泛型的变更，以通过通用 API 保持性能提升。
- [Project Loom](/docs/CS/Java/JDK/Loom.md) 的使命是让编写、调试、性能分析和维护满足当今需求的并发应用程序变得更加容易。
- Amber
- Coin
- Graal
- jigsaw
- Kulla
- Panama
- Shenandoah
- Sumatra
- Tsan
- ZGC
- Lilliput

## Performance

事实是，性能分析是硬性经验主义和软性人类心理学的奇怪混合体。
重要的是，可观察指标的绝对数值以及最终用户和利益相关者对它们的感受。

- JVM 没有神奇的"加速"开关
- 没有让 Java 运行得更快的"技巧和窍门"
- 没有对你隐藏的秘密算法

### Performance Metrics

一组常见的性能指标包括：

- Throughput
- Latency
- Capacity
- Utilization
- Efficiency
- Scalability
- Degradation

#### Capacity

Capacity 通常以在给定的延迟或吞吐量值下可用的处理量来衡量。

#### Efficiency

将系统的吞吐量除以利用的资源可以得到系统整体效率的度量。
在处理大型系统时，也可以使用某种形式的成本会计来衡量效率。

#### Scalability

系统可扩展性的圣杯是吞吐量随资源的变化精确同步。

#### Degradation

如果我们增加系统的负载，无论是通过增加请求（或客户端）数量还是增加请求到达的速度，我们可能会看到观察到的延迟和/或吞吐量的变化。
如果系统未充分利用，那么在可观察指标变化之前应该有一些余量；但如果资源已完全利用，那么我们会期望看到吞吐量停止增长或延迟增加。
这些变化通常称为系统在额外负载下的性能下降。

在罕见的情况下，额外的负载可能导致反直觉的结果。
例如，如果负载的变化导致系统的某部分切换到更资源密集但更高性能的模式（如 JIT），
那么整体效果可能是减少延迟，即使接收的请求更多了。

`performance elbow`

## Tuning

Java的编译和启动时长都较长 开发和部署效率低

Maven改造 大多数编译慢的情况都是生成依赖树阶段 依赖多而复杂 就更易去仓库下载依赖

- 优化依赖分析算法 边生成依赖树边进行版本仲裁
- 增量缓存依赖树 修改pom文件的情况远小于修改自己代码的情况
- maven程序编译成机器码运行

### Upgrade

Upgrade causes:

- performance improvement, such as JVM(GC)
- Framework supported, like Spring

Upgrade concern:

- dependencies, such as xml, 

8 to 11

Maven, Compile 

jdwp host/ip from 0.0.0.0 to localhost and not support to debug remotely

## Summary

Java 相对于其它现代语言主要的优势还是生态庞大

和其它语言相比缺点
- 启动耗时较长 启动加载类 
- 其次是占用内存大 JVM固定占用内存
- 还有面向对象过于严格 在编写简单程序比较麻烦 相较于Go 可以返回多个响应
- 语法繁琐 相较于Python

## Links

## References

1. [The Java Language Environment: Contents A White Paper](https://www.oracle.com/java/technologies/language-environment.html)
2. [Java Performance Tuning](http://www.javaperformancetuning.com/)
3. [The Java Tutorial](https://docs.oracle.com/javase/tutorial/)
