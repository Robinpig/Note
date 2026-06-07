## Introduction

使用线程的主要原因之一是提高性能。使用线程可以通过让应用程序更容易地利用可用处理能力来提高资源利用率，并且可以通过让应用程序在现有任务仍在运行时立即开始处理新任务来提高响应性。

## Create

线程由 `Thread` 类表示。用户创建线程的唯一方法是**创建此类的对象**；
每个线程都与这样一个对象关联。
当在相应的 `Thread` 对象上调用 `start()` 方法时，线程将启动。

```java
// Allocates a new Thread object.
public Thread() {
    init(null, null, "Thread-" + nextThreadNum(), 0);
}

// Allocates a new Thread object with Runnable taarget.
public Thread(Runnable target) {
    init(null, target, "Thread-" + nextThreadNum(), 0);
}
```

### init

线程分为两种类型：普通线程和守护线程。

普通线程和守护线程仅在退出时的行为有所不同。
当线程退出时，JVM 对正在运行的线程进行清查，如果剩下的唯一线程是守护线程，则启动有序关闭。
当 JVM 停止时，任何剩余的守护线程都被遗弃——finally 块不执行，栈不展开——JVM 只是退出。

守护线程并不能很好地替代正确管理应用程序中的服务生命周期。

### 线程状态

线程可以有六种状态：
- NEW：尚未启动的线程
- RUNNABLE：在 JVM 中执行的线程
- BLOCKED：等待监视器锁而被阻塞的线程
- WAITING：无限期等待另一个线程执行特定操作的线程
- TIMED_WAITING：等待另一个线程执行操作达到指定等待时间的线程
- TERMINATED：已退出的线程

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
