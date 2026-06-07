## Introduction

一种同步辅助工具，允许**一个或多个线程**等待，直到其他线程中执行的**一组操作**完成。
CountDownLatch 是一个非常简单但非常通用的工具，用于阻塞直到给定数量的信号、事件或条件成立。

CountDownLatch 以给定的计数初始化。await 方法阻塞，直到当前计数由于 countDown 方法的调用而达到零，之后所有等待线程被释放，并且任何后续的 await 调用立即返回。这是一次性现象——计数不能重置。如果你需要可以重置计数的版本，请考虑使用 **CyclicBarrier**。
CountDownLatch 是一个多功能的同步工具，可用于多种目的。初始化计数为 1 的 CountDownLatch 充当简单的开关或门：所有调用 await 的线程在门处等待，直到一个线程调用 countDown 打开门。初始化计数为 N 的 CountDownLatch 可用于使一个线程等待，直到 N 个线程完成了某个动作，或某个动作已完成了 N 次。
CountDownLatch 的一个有用特性是它不要求调用 countDown 的线程等待计数达到零才继续，它只是阻止任何线程通过 await，直到所有线程都可以通过。

**内存一致性效应**：*在计数达到零之前，一个线程中调用 countDown() 之前的操作 happens-before 另一个线程中对应的 await() 成功返回之后的操作。*

Sync

```java
    /**
     * Synchronization control For CountDownLatch.
     * Uses AQS state to represent count.
     */
    private static final class Sync extends AbstractQueuedSynchronizer {
        private static final long serialVersionUID = 4982264981922014374L;

        Sync(int count) {
            setState(count);
        }

        int getCount() {
            return getState();
        }

        protected int tryAcquireShared(int acquires) {
            return (getState() == 0) ? 1 : -1;
        }

        protected boolean tryReleaseShared(int releases) {
            // Decrement count; signal when transition to zero
            for (;;) {
                int c = getState();
                if (c == 0)
                    return false;
                int nextc = c - 1;
                if (compareAndSetState(c, nextc))
                    return nextc == 0;
            }
        }
    }
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
