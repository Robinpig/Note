## Introduction

Netty 的 I/O 操作全是异步的：`bind` / `connect` / `write` 立刻返回一个「结果占位符」，真正的完成状态稍后由 EventLoop 线程写入。这个占位符就是 Future，Netty 在它之上做了两件事——补齐 JDK Future 的短板，以及把「读结果」和「写结果」拆成两个接口。

`java.util.concurrent.Future` 只能阻塞在 `get()` 上，既无法区分「完成但失败」与「被取消」，也无法在完成时自动触发回调。Netty 的 `Future` 因此增加 `isSuccess()` / `cause()` 表达三态结果，并用 `addListener` 把等待变成非阻塞注册，避免业务线程 park 在 EventLoop 上（`checkDeadLock()` 甚至会主动拒绝在 loop 内 await）。

可写的另一半交给 `Promise`：只有它提供 `setSuccess` / `setFailure`，因此 transport 内部用它写结果，而暴露给用户的 API 一律声明成只读的 `Future`，用户无法伪造完成状态。`ChannelFuture` / `ChannelPromise` 则是这对接口在 channel 维度的特化，额外携带 `channel()` 上下文。

按下面顺序读：先看 Future Hierarchy 的类型谱系，再看接口层（`Future` → `ChannelFuture`、`Promise` → `ChannelPromise`），最后看实现层（`AbstractFuture` → `DefaultPromise` → `DefaultChannelPromise`）。

## Future Hierarchy

![Future](img/Future.png)



## Future

```java
/**
 * The result of an asynchronous operation.
 */
@SuppressWarnings("ClassNameSameAsAncestorName")
public interface Future<V> extends java.util.concurrent.Future<V> {

    //Returns {@code true} if and only if the I/O operation was completed successfully.
    boolean isSuccess();

    //returns {@code true} if and only if the operation can be cancelled via {@link #cancel(boolean)}.
    boolean isCancellable();

    //Returns the cause of the failed I/O operation if the I/O operation has failed.
    Throwable cause();

    /**
     * Adds the specified listener to this future.  The
     * specified listener is notified when this future is
     * {@linkplain #isDone() done}.  If this future is already
     * completed, the specified listener is notified immediately.
     */
    Future<V> addListener(GenericFutureListener<? extends Future<? super V>> listener);

    /**
     * Adds the specified listeners to this future.  The
     * specified listeners are notified when this future is
     * {@linkplain #isDone() done}.  If this future is already
     * completed, the specified listeners are notified immediately.
     */
    Future<V> addListeners(GenericFutureListener<? extends Future<? super V>>... listeners);

    /**
     * Removes the first occurrence of the specified listener from this future.
     * The specified listener is no longer notified when this
     * future is {@linkplain #isDone() done}.  If the specified
     * listener is not associated with this future, this method
     * does nothing and returns silently.
     */
    Future<V> removeListener(GenericFutureListener<? extends Future<? super V>> listener);

    /**
     * Removes the first occurrence for each of the listeners from this future.
     * The specified listeners are no longer notified when this
     * future is {@linkplain #isDone() done}.  If the specified
     * listeners are not associated with this future, this method
     * does nothing and returns silently.
     */
    Future<V> removeListeners(GenericFutureListener<? extends Future<? super V>>... listeners);

    /**
     * Waits for this future until it is done, and rethrows the cause of the failure if this future
     * failed.
     */
    Future<V> sync() throws InterruptedException;

    //Waits for this future until it is done, and rethrows the cause of the failure if this future failed.
    Future<V> syncUninterruptibly();

    //Waits for this future to be completed.
    Future<V> await() throws InterruptedException;

    /**
     * Waits for this future to be completed without
     * interruption.  This method catches an {@link InterruptedException} and
     * discards it silently.
     */
    Future<V> awaitUninterruptibly();

    //Waits for this future to be completed within the specified time limit.
    boolean await(long timeout, TimeUnit unit) throws InterruptedException;

    //Waits for this future to be completed within the specified time limit.
    boolean await(long timeoutMillis) throws InterruptedException;

    /**
     * Waits for this future to be completed within the
     * specified time limit without interruption.  This method catches an
     * {@link InterruptedException} and discards it silently.
     *
     * @return {@code true} if and only if the future was completed within
     *         the specified time limit
     */
    boolean awaitUninterruptibly(long timeout, TimeUnit unit);

    /**
     * Waits for this future to be completed within the
     * specified time limit without interruption.  This method catches an
     * {@link InterruptedException} and discards it silently.
     *
     * @return {@code true} if and only if the future was completed within
     *         the specified time limit
     */
    boolean awaitUninterruptibly(long timeoutMillis);

    /**
     * Return the result without blocking. If the future is not done yet this will return {@code null}.
     *
     * As it is possible that a {@code null} value is used to mark the future as successful you also need to check
     * if the future is really done with {@link #isDone()} and not rely on the returned {@code null} value.
     */
    V getNow();

    /**
     * {@inheritDoc}
     *
     * If the cancellation was successful it will fail the future with a {@link CancellationException}.
     */
    @Override
    boolean cancel(boolean mayInterruptIfRunning);
}
```



## ChannelFuture



```java
/**
*                                      +---------------------------+
*                                      | Completed successfully    |
*                                      +---------------------------+
*                                 +---->      isDone() = true      |
* +--------------------------+    |    |   isSuccess() = true      |
* |        Uncompleted       |    |    +===========================+
* +--------------------------+    |    | Completed with failure    |
* |      isDone() = false    |    |    +---------------------------+
* |   isSuccess() = false    |----+---->      isDone() = true      |
* | isCancelled() = false    |    |    |       cause() = non-null  |
* |       cause() = null     |    |    +===========================+
* +--------------------------+    |    | Completed by cancellation |
*                                 |    +---------------------------+
*                                 +---->      isDone() = true      |
*                                      | isCancelled() = true      |
*                                      +---------------------------+
*/
```



## Promise

**Special Future which is writable.**

```java
public interface Promise<V> extends Future<V> {

    //Marks this future as a success and notifies all listeners.
    Promise<V> setSuccess(V result);

    //Marks this future as a success and notifies all listeners.
    boolean trySuccess(V result);

    //Marks this future as a failure and notifies all listeners.
    Promise<V> setFailure(Throwable cause);

    //Marks this future as a failure and notifies all listeners.
    boolean tryFailure(Throwable cause);

    //Make this future impossible to cancel.
    boolean setUncancellable();

    @Override
    Promise<V> addListener(GenericFutureListener<? extends Future<? super V>> listener);

    @Override
    Promise<V> addListeners(GenericFutureListener<? extends Future<? super V>>... listeners);

    @Override
    Promise<V> removeListener(GenericFutureListener<? extends Future<? super V>> listener);

    @Override
    Promise<V> removeListeners(GenericFutureListener<? extends Future<? super V>>... listeners);

    @Override
    Promise<V> await() throws InterruptedException;

    @Override
    Promise<V> awaitUninterruptibly();

    @Override
    Promise<V> sync() throws InterruptedException;

    @Override
    Promise<V> syncUninterruptibly();
}
```



## ChannelPromise

**Special ChannelFuture which is writable.**

Use in [Bootstrap-bind-register](/docs/CS/Framework/Netty/Bootstrap.md?id=register)

```java
public interface ChannelPromise extends ChannelFuture, Promise<Void> {
    ChannelPromise setSuccess();

    boolean trySuccess();

    //Returns a new ChannelPromise if isVoid() returns true otherwise itself.
    ChannelPromise unvoid();
  
  	...
}
```



## AbstractFuture

AbstractFuture provide two  get methods

```java
public abstract class AbstractFuture<V> implements Future<V> {

    @Override
    public V get() throws InterruptedException, ExecutionException {
        await();

        Throwable cause = cause();
        if (cause == null) {
            return getNow();
        }
        if (cause instanceof CancellationException) {
            throw (CancellationException) cause;
        }
        throw new ExecutionException(cause);
    }

    @Override
    public V get(long timeout, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
        if (await(timeout, unit)) {
            Throwable cause = cause();
            if (cause == null) {
                return getNow();
            }
            if (cause instanceof CancellationException) {
                throw (CancellationException) cause;
            }
            throw new ExecutionException(cause);
        }
        throw new TimeoutException();
    }
}
```

## DefaultPromise



DefaultPromise#await()

```java
@Override
public Promise<V> await() throws InterruptedException {
    if (isDone()) {
        return this;
    }

    if (Thread.interrupted()) {
        throw new InterruptedException(toString());
    }

    checkDeadLock();

    synchronized (this) {
        while (!isDone()) {
            incWaiters();
            try {
                wait();
            } finally {
                decWaiters();
            }
        }
    }
    return this;
}
```



```java
protected void checkDeadLock() {
    EventExecutor e = executor();
    if (e != null && e.inEventLoop()) {
        throw new BlockingOperationException(toString());
    }
}
```



DefaultPromise#addListener

```java
@Override
public Promise<V> addListener(GenericFutureListener<? extends Future<? super V>> listener) {
    checkNotNull(listener, "listener");

    synchronized (this) {
        addListener0(listener);
    }

    if (isDone()) {
        notifyListeners();
    }

    return this;
}

private void addListener0(GenericFutureListener<? extends Future<? super V>> listener) {
    if (listeners == null) {
        listeners = listener;
    } else if (listeners instanceof DefaultFutureListeners) {
        ((DefaultFutureListeners) listeners).add(listener);
    } else {
        listeners = new DefaultFutureListeners((GenericFutureListener<?>) listeners, listener);
    }
}

private void notifyListeners() {
    EventExecutor executor = executor();
    if (executor.inEventLoop()) {
        final InternalThreadLocalMap threadLocals = InternalThreadLocalMap.get();
        final int stackDepth = threadLocals.futureListenerStackDepth();
        if (stackDepth < MAX_LISTENER_STACK_DEPTH) {
            threadLocals.setFutureListenerStackDepth(stackDepth + 1);
            try {
                notifyListenersNow();
            } finally {
                threadLocals.setFutureListenerStackDepth(stackDepth);
            }
            return;
        }
    }

    safeExecute(executor, new Runnable() {
        @Override
        public void run() {
            notifyListenersNow();
        }
    });
}
```



## DefaultChannelPromise

The default ChannelPromise implementation. It is recommended to use `Channel.newPromise()` to create a new ChannelPromise rather than calling the constructor explicitly.

```java
public class DefaultChannelPromise extends DefaultPromise<Void> implements ChannelPromise, FlushCheckpoint {

    private final Channel channel;
    private long checkpoint;
 ... 
}
```


## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Channel](/docs/CS/Framework/Netty/Channel.md)
- [Bootstrap](/docs/CS/Framework/Netty/Bootstrap.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)

## References
1. [method io.netty.util.concurrent.DefaultPromise#cancel/isDone violates contract?](https://github.com/netty/netty/issues/7712)
