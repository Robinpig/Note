## Introduction

ReentrantLock 实现 [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md) 接口，提供与 [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) 相同的互斥和内存可见性保证。
获取 ReentrantLock 与进入 synchronized 块具有相同的内存语义，释放 ReentrantLock 与退出 synchronized 块具有相同的内存语义。
而且，与 synchronized 一样，ReentrantLock 提供可重入的锁定语义。
ReentrantLock 支持 Lock 定义的所有锁获取模式，在处理锁不可用方面比 synchronized 提供更大的灵活性。

**为什么要创建与内置锁如此相似的新锁定机制？**

内置锁在大多数情况下工作正常，但有一些功能限制——无法中断正在等待获取锁的线程，
或者无法尝试获取锁而不愿意永远等待。
内置锁也必须在获取它们的相同代码块中释放；
这简化了编码并与异常处理良好地交互，但使得非块结构的锁定纪律变得不可能。

一种可重入的互斥锁，具有与使用 synchronized 方法和语句访问的隐式监视器锁相同的基本行为和语义，但具有扩展能力。
ReentrantLock 由最后一个成功锁定但尚未解锁的线程拥有。当锁不被其他线程持有时，调用 lock 的线程将返回，
成功获取锁。
如果当前线程已经拥有锁，该方法将立即返回。
这可以通过 isHeldByCurrentThread 和 getHoldCount 方法检查。

此类的构造方法接受一个可选的公平性参数。当设置为 true 时，在争用下，锁倾向于授予等待时间最长的线程。否则，此锁不保证任何特定的访问顺序。使用公平锁的程序在多线程访问时可能显示较低的整体吞吐量（即更慢，通常慢得多），但获得锁的时间方差更小，并保证无饥饿。但注意，锁的公平性并不能保证线程调度的公平性。因此，使用公平锁的多个线程中的一个可能连续多次获得锁，而其他活跃线程没有进展且当前未持有锁。另请注意，无定时的 tryLock() 方法不遵守公平性设置。如果锁可用，即使其他线程在等待，它也会成功。

建议的做法是始终在 lock 调用后立即跟随 try 块，最常见的是在 before/after 构造中，例如：

```java
class X {
    private final ReentrantLock lock = new ReentrantLock();
    // ...

    public void m() {
        lock.lock();  // block until condition holds
        try {
            // ... method body
        } finally {
            lock.unlock();
        }
    }
}
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
