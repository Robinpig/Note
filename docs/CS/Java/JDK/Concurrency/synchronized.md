## Introduction

Java 提供了一种用于强制执行原子性的内置锁定机制：**synchronized 块**。
synchronized 块有两个部分：一个用作锁的对象引用，以及一个由该锁保护的代码块。
synchronized 方法是 synchronized 块的简写，跨越整个方法体，其锁是调用该方法的对象
（静态 synchronized 方法使用 Class 对象作为锁）。

每个 Java 对象都可以隐式地充当同步的锁；这些内置锁称为 intrinsic locks 或 monitor locks。
锁由执行线程在进入 synchronized 块之前自动获取，并在控制退出 synchronized 块时自动释放，
无论是通过正常控制路径还是通过抛出异常退出块。
获取内置锁的唯一方法是进入由该锁保护的 synchronized 块或方法。

Java 中的内置锁充当 mutexes（互斥锁），这意味着最多一个线程可以拥有该锁。
当线程 A 尝试获取由线程 B 持有的锁时，A 必须等待或阻塞，直到 B 释放它。
如果 B 从不释放锁，则 A 永远等待。

Java 监视器模式受到 Hoare 关于 monitor 的工作的启发（Hoare, 1974），尽管此模式与真正的 monitor 之间存在显著差异。

进入和退出 synchronized 块的字节码指令甚至被称为 `monitorenter` 和 `monitorexit`，Java 的内置锁有时被称为 monitor locks 或 monitors。

> [!NOTE]
> 
> [monitorenter](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=monitorenter) & [exit](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=monitorexit) are symmetric routines; which is reflected in the assembly code structure as well.

use javap -c   *.class

```
//synchronized with block finally add monitorexit
monitorenter monitorexit
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
