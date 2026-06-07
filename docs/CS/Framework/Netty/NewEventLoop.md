## EventLoop

一旦 Channel 注册后，由它处理所有 I/O 操作。一个 EventLoop 实例通常处理多个 Channel，但这可能取决于实现细节和内部机制。

```java
public interface EventLoop extends OrderedEventExecutor, EventLoopGroup {

    /**
     * 返回一个仅供内部使用的对象，提供不安全操作。
     */
    Unsafe unsafe();

    /**
     * 不应从用户代码调用的不安全操作。这些方法仅用于实现实际的传输，
     * 并且必须从 EventLoop 自身调用。
     */
    interface Unsafe {
        /**
         * 将 Channel 注册到 EventLoop。
         */
        void register(Channel channel) throws Exception;

        /**
         * 将 Channel 从 EventLoop 注销。
         */
        void deregister(Channel channel) throws Exception;
    }
}
```



### IoHandler

处理 EventLoop 的 IO 分发。除 wakeup(boolean) 外的所有操作都必须在 EventLoop 线程上执行，且不应由用户直接调用。

```java
public interface IoHandler extends EventLoop.Unsafe {
    /**
     * 运行此 IoHandler 处理的 IO。
     * IoExecutionContext 用于确保不会执行过长时间而阻塞 EventLoop 上调度的其他任务。
     * 这通过考虑 IoExecutionContext#delayNanos(long) 或 IoExecutionContext#deadlineNanos() 来实现。
     *
     * @return 已处理 IO 的 Channel 数量。
     */
    int run(IoExecutionContext context);

    // 唤醒 IoHandler，如果有任何阻塞操作，应解除阻塞并尽快返回。
    void wakeup(boolean inEventLoop);

    // 准备销毁此 IoHandler。此方法将在 destroy() 之前调用，并可能被多次调用。
    void prepareToDestroy();

    /**
     * 销毁 IoHandler 并释放其所有资源。
     */
    void destroy();
}
```



## NioHandler

调用 [processSelectedKeys](/docs/CS/Framework/Netty/EventLoop.md?id=processSelectedKey)

```java
// NioHandler
@Override
public int run(IoExecutionContext runner) {
    int handled = 0;
    try {
        try {
            switch (selectStrategy.calculateStrategy(selectNowSupplier, !runner.canBlock())) {
                case SelectStrategy.CONTINUE:
                    return 0;

                case SelectStrategy.BUSY_WAIT:
                    // fall-through to SELECT since the busy-wait is not supported with NIO

                case SelectStrategy.SELECT:
                    select(runner, wakenUp.getAndSet(false));

                    // 'wakenUp.compareAndSet(false, true)' is always evaluated
                    // before calling 'selector.wakeup()' to reduce the wake-up
                    // overhead. (Selector.wakeup() is an expensive operation.)
                    //
                    // However, there is a race condition in this approach.
                    // The race condition is triggered when 'wakenUp' is set to
                    // true too early.
                    //
                    // 'wakenUp' is set to true too early if:
                    // 1) Selector is waken up between 'wakenUp.set(false)' and
                    //    'selector.select(...)'. (BAD)
                    // 2) Selector is waken up between 'selector.select(...)' and
                    //    'if (wakenUp.get()) { ... }'. (OK)
                    //
                    // In the first case, 'wakenUp' is set to true and the
                    // following 'selector.select(...)' will wake up immediately.
                    // Until 'wakenUp' is set to false again in the next round,
                    // 'wakenUp.compareAndSet(false, true)' will fail, and therefore
                    // any attempt to wake up the Selector will fail, too, causing
                    // the following 'selector.select(...)' call to block
                    // unnecessarily.
                    //
                    // To fix this problem, we wake up the selector again if wakenUp
                    // is true immediately after selector.select(...).
                    // It is inefficient in that it wakes up the selector for both
                    // the first case (BAD - wake-up required) and the second case
                    // (OK - no wake-up required).

                    if (wakenUp.get()) {
                        selector.wakeup();
                    }
                    // fall through
                default:
            }
        } catch (IOException e) {
            // If we receive an IOException here its because the Selector is messed up. Let's rebuild
            // the selector and retry. https://github.com/netty/netty/issues/8566
            rebuildSelector();
            handleLoopException(e);
            return 0;
        }

        cancelledKeys = 0;
        needsToSelectAgain = false;
        handled = processSelectedKeys();
    } catch (Throwable t) {
        handleLoopException(t);
    }
    return handled;
}
```


## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
