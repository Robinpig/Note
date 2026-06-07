## Introduction

一个*内存模型*描述，给定一个程序及其执行轨迹，该执行轨迹是否是程序的合法执行。
Java 编程语言内存模型通过检查执行轨迹中的每次读取并检查该读取观察到的写入是否根据某些规则有效来工作。

内存模型描述了程序的可能行为。
实现可以自由地生成任何它喜欢的代码，只要程序的所有结果执行都产生可由内存模型预测的结果。

这为实现者提供了很大的自由来执行大量的代码转换，包括重新排序操作和删除不必要的同步。

内存模型指定了线程和对象如何交互
- **Atomicity（原子性）**
  通过锁定来获得字段更新的互斥性
- **Visibility（可见性）**
  确保一个线程中做的更改被其他线程看到
- **Ordering（有序性）**
  确保你不会对语句的执行顺序感到惊讶

Java 内存模型（JMM）是一个宽松的内存模型，充当 Java 程序员、编译器编写者和 JVM 实现者之间的契约。

## Cache Coherence

### Memory Consistency Properties

定义了内存操作（如共享变量的读写）上的 happens-before 关系。

#### happens-before

Java 内存模型中的 happens-before 关系确保一个线程执行的内存写入对另一个线程可见。

规则包括：
- 程序顺序规则：线程中的每个动作 happens-before 该线程中后续的每个动作。
- 监视器锁规则：解锁 happens-before 后续的加锁。
- volatile 变量规则：对 volatile 字段的写 happens-before 对该字段的后续读。
- 传递性：如果 A happens-before B，且 B happens-before C，则 A happens-before C。

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
