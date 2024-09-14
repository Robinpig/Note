## EventLoop

Will handle all the I/O operations for a Channel once registered. One EventLoop instance will usually handle more than one Channel but this may depend on implementation details and internals.

```java
public interface EventLoop extends OrderedEventExecutor, EventLoopGroup {

    /**
     * Returns an <em>internal-use-only</em> object that provides unsafe operations.
     */
    Unsafe unsafe();

    /**
     * <em>Unsafe</em> operations that should <em>never</em> be called from user-code. These methods
     * are only provided to implement the actual transport, and must be invoked from the {@link EventLoop} itself.
     */
    interface Unsafe {
        /**
         * Register the {@link Channel} to the {@link EventLoop}.
         */
        void register(Channel channel) throws Exception;

        /**
         * Deregister the {@link Channel} from the {@link EventLoop}.
         */
        void deregister(Channel channel) throws Exception;
    }
}
```



### IoHandler

Handles IO dispatching for an EventLoop All operations except wakeup(boolean) MUST be executed on the EventLoop thread and should never be called from the user-directly.

```java
public interface IoHandler extends EventLoop.Unsafe {
    /**
     * Run the IO handled by this {@link IoHandler}. The {@link IoExecutionContext} should be used
     * to ensure we not execute too long and so block the processing of other task that are
     * scheduled on the {@link EventLoop}. This is done by taking {@link IoExecutionContext#delayNanos(long)} or
     * {@link IoExecutionContext#deadlineNanos()} into account.
     *
     * @return the number of {@link Channel} for which I/O was handled.
     */
    int run(IoExecutionContext context);

    // Wakeup the IoHandler, which means if any operation blocks it should be unblocked and return as soon as possible.
    void wakeup(boolean inEventLoop);

    // Prepare to destroy this IoHandler. This method will be called before destroy() and may be called multiple times.
    void prepareToDestroy();

    /**
     * Destroy the {@link IoHandler} and free all its resources.
     */
    void destroy();
}
```



## NioHandler

call [processSelectedKeys](/docs/CS/Framework/Netty/EventLoop.md?id=processSelectedKey)

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