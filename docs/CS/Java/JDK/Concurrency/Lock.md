## Introduction

Lock 接口定义了许多抽象锁定操作。
与内置锁定不同，Lock 提供了无条件、轮询、定时和可中断的锁获取方式，
并且所有锁定和解锁操作都是显式的。
Lock 实现必须提供与内置锁相同的内存可见性语义，
但它们的锁定语义、调度算法、顺序保证和性能特性可能有所不同。

## Lock

Lock 实现提供了比使用 [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) 方法和语句可以获得的更广泛的锁定操作。
它们允许更灵活的结构化，可能具有相当不同的属性，并且可能支持多个关联的 Condition 对象。

锁是控制多个线程对共享资源访问的工具。
通常，锁提供对共享资源的独占访问：一次只有一个线程可以获取锁，并且对共享资源的所有访问都需要先获取锁。
然而，某些锁可能允许对共享资源的并发访问，例如 ReadWriteLock 的读锁。

使用 synchronized 方法或语句提供对每个对象关联的隐式监视器锁的访问，但强制所有锁获取和释放以块结构方式发生：
当获取多个锁时，必须以相反的顺序释放，并且所有锁必须在获取它们的相同词法作用域内释放。

虽然 synchronized 方法和语句的范围机制使得使用监视器锁编程更容易，
并且有助于避免许多涉及锁的常见编程错误，但有时你需要以更灵活的方式使用锁。
例如，某些并发访问数据结构的遍历算法需要使用"hand-over-hand"或"链式锁定"：
你获取节点 A 的锁，然后是节点 B，然后释放 A 并获取 C，然后释放 B 并获取 D，依此类推。
Lock 接口的实现通过允许在不同作用域中获取和释放锁，以及允许以任何顺序获取和释放多个锁，来支持使用这些技术。

```java
public interface Lock {
    void lock();
    void lockInterruptibly() throws InterruptedException;
    boolean tryLock();
    boolean tryLock(long time, TimeUnit unit) throws InterruptedException;
    void unlock();
    Condition newCondition();
}
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
