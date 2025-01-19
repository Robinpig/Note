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
JEP之于Java就像PEP之于Python、RFC之于Rust，它代表了Java社区最新的工作动向和未来的研究方向。在较大的Java/JVM特性实现前通常都有JEP，它是Java社区成员和领导者多轮讨论的结果。JEP描述了该工作的动机、目标、详细细节、风险和影响等，通过阅读JEP（如果有的话），可以更好地了解Java/JVM某个特性。下面摘录了一些较新的JEP，注意，处于“草案”和“候选”状态的JEP不能保证最终会被加入JDK发行版。

另一个常常与JEP一起出现的是JSR（Java Specification Request，Java规范提案）。有时人们想开发一些实验性特性，例如探索新奇的点子、实现特性的原型，或者增强当前特性，在这些情况下都可以提出JEP，让社区也参与实现或者讨论。这些JEP中的少数可能会随着技术的发展愈发成熟，此时，JSR可以将这些成熟的技术提案进一步规范化，产生新的语言规范，或者修改当前语言规范，将它们加入Java语言标准中。


## Build

参考 https://github.com/Robinpig/jdk

## Basics

[Basics of Java](/docs/CS/Java/JDK/Basic/Basic.md)

## Collection

The [Collection](/docs/CS/Java/JDK/Collection/Collection.md) in Java is a framework that provides an architecture to store and manipulate the group of objects.

## Concurrency

[Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)  is a process of executing multiple threads simultaneously.

## JVM

[JVM (Java Virtual Machine)](/docs/CS/Java/JDK/JVM/JVM.md) is an abstract machine. It is a specification that provides runtime environment in which java bytecode can be executed.


## Security

if you want to high security, please enable

-Djava.security.manager


SecurityManger


[JEP 332: Transport Layer Security (TLS) 1.3](https://openjdk.org/jeps/332)



keytool

jarsigner



### Zip Bomb Attack

The central idea of zip bomb attacks is to exploit the characteristics of the zip compressor and its techniques to create small and easy-to-transport zip files. However, these files require many computational resources (time, processing, memory, or disk) to uncompress.

The most common objective of a zip bomb is rapidly consuming the available computer memory in a relatively CPU-intensive process. In such a way, the attacker expects that the computer victim of a zip bomb crashes at some point.

However, attackers may design zip bombs to exploit other characteristics of software installed on the victim’s computer. For example, some zip bombs aim to crash file systems without consuming all the computer’s memory.




## Projects

A Project is a collaborative effort to produce a specific artifact, which may be a body of code, or documentation, or some other material.
A Project must be sponsored by one or more Groups.
A Project may have web content, one or more file repositories, and one or more mailing lists.

- [Project Valhalla](/docs/CS/Java/JDK/Valhalla.md) plans to augment the Java object model with value objects and user-defined primitives, combining the abstractions of object-oriented programming with the performance characteristics of simple primitives.
  These features will be complemented with changes to Java’s generics to preserve performance gains through generic APIs.
- [Project Loom](/docs/CS/Java/JDK/Loom.md)'s mission is to make it easier to write, debug, profile and maintain concurrent applications meeting today's requirements.
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



## Links




## References

1. [The Java Language Environment: Contents A White Paper](https://www.oracle.com/java/technologies/language-environment.html)
2. [Java Performance Tuning](http://www.javaperformancetuning.com/)
3. [The Java Tutorial](https://docs.oracle.com/javase/tutorial/)
