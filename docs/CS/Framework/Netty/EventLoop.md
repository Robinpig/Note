## Introduction

EventLoopGroup 是 Netty Reactor 线程模型的实现：一个 group 管多个 EventLoop（线程），每个 EventLoop 管多个 Channel（注册到它的 fd）。4.2 的核心重构是把 IO 多路复用循环从 EventLoop 抽出来，交给 `IoHandler` 接口——EventLoop 只负责跑任务队列 + 调 `ioHandler.run(context)`，不再知道底层是 select 还是 epollWait。

本文以 **Netty 4.2.19.Final** 源码为准。

## 家族对比

| 4.1（已 Deprecated） | 4.2（当前） | 差异 |
| :--- | :--- | :--- |
| `NioEventLoopGroup` | `MultiThreadIoEventLoopGroup(new NioIoHandlerFactory(...))` | 构造时传入 IoHandlerFactory，实现细节（NIO / epoll / kqueue / io_uring）后移 |
| `NioEventLoop` | `SingleThreadIoEventLoop`（继承 `SingleThreadEventLoop`） | 主循环从 `run0()` 里的 select 循环变成 `run()` 里的 `ioHandler.run(context)` |
| — | `IoHandler` / `IoHandlerFactory` | 新增抽象层——见 [Transport IoHandler 抽象](/docs/CS/Framework/Netty/Transport.md?id=iohandler-abstraction) |
| `EventExecutorGroup`（只有 next()） | `IoEventLoopGroup extends EventLoopGroup` | 新增 `register(IoHandle)` 让 EventLoop 能注册 IoHandle |

AIO transport（`io.netty.channel.aio`）4.1 就彻底移除了。OIO（`io.netty.channel.socket.oio`）整体 `@Deprecated`，推荐换 NIO / epoll / kqueue。4.2 里原来那几个 `NioEventLoopGroup` / `EpollEventLoopGroup` / `KQueueEventLoopGroup` 也全部 `@Deprecated`，迁移方式就是上面那行 MultiThreadIoEventLoopGroup + 对应的 IoHandlerFactory。

## SingleThreadIoEventLoop.run() —— 4.2 主循环

```java
protected void run() {
    assert inEventLoop();
    ioHandler.initialize();                     // ① IoHandler 启动（openSelector / epoll_create1 / io_uring_setup）
    do {
        final int ioRatio = this.ioRatio;
        long quantum;
        activeIoTimeNanos = -1;                // ② reset，runIo() 里 reportActiveIoTime
        runIo();                               // ③ ioHandler.run(context) —— select/epollWait/keventWait
        if (ioRatio == 100 || activeIoTimeNanos == -1) {
            quantum = maxTaskProcessingQuantumNs;  // 默认 1000ms，系统属性可配
        } else {
            // ④ ioRatio 不是 100 → 任务预算按 IO 时间比例分配
            quantum = Math.min(maxTaskProcessingQuantumNs,
                    activeIoTimeNanos * (100 - ioRatio) / ioRatio);
            if (quantum == 0) quantum = maxTaskProcessingQuantumNs;
        }
        if (isShuttingDown()) {
            ioHandler.prepareToDestroy();
        }
        runAllTasks(quantum);                  // ⑤ 任务队列消费（上限 quantum 时间）
    } while (!confirmShutdown() && !canSuspend()); // ⑥ shutdown 确认 or 可挂起
}
```

**与 4.1 的差异**：
- 4.1 的 `NioEventLoop.run0()` 里自己写 select 循环、自己处理 IO / 任务切换、自己处理 busy-wait。4.2 把 IO 循环完全委托给 `ioHandler.run(context)`，SingleThreadIoEventLoop 只做 **IO 时间计量 → 任务预算分配**
- `ioRatio`（默认 100）控制 IO vs 任务的时间分配比例，4.2 把它从 NioEventLoop 挪到 SingleThreadIoEventLoop，成为通用调度器
- `runIo()` 返回值（handled 就绪数）在 4.2 里不参与循环决策（4.1 里 `select` 就绪数决定下一轮 select timeout），只有 `runAllTasks(quantum)` 的 quantum 决策用到了 activeIoTimeNanos
- `confirmShutdown()` 和 `canSuspend()` 是 4.2 新增。`canSuspend` 额外检查 `numRegistrations.get() == 0`——没有注册任何 fd 的 EventLoop 才允许挂起（底层 selector / epoll 空等没意义）

### ioRatio 与 taskQuantum 的实际语义

| ioRatio | 行为 |
| :--- | :--- |
| 100（默认） | runAllTasks 永远跑满 `maxTaskProcessingQuantumNs`（默认 1000ms），不管上一轮 IO 花了多久——这是 4.1 以来的默认行为 |
| 50 | 若上一轮 IO 花了 10ms，本轮任务预算 = `min(1000, 10 * 50/50) = 10ms`——给 IO 密集型场景留出更多 IO 时间 |
| 20 | 若上一轮 IO 花了 10ms，本轮任务预算 = `min(1000, 10 * 80/20) = 40ms`——任务密集型 |
| 1 | 几乎只给 1ms 任务预算（除非 activeIoTimeNanos 还是 -1），IO 优先模式 |

### IoHandlerContext —— IO handler 向 EventLoop 要时间参数

```java
private final IoHandlerContext context = new IoHandlerContext() {
    public boolean canBlock() {
        return !hasTasks() && !hasScheduledTasks();  // 无待办才能阻塞 IO 多路复用
    }
    public long delayNanos(long currentTimeNanos) {
        return SingleThreadIoEventLoop.this.delayNanos(currentTimeNanos); // 下一个定时任务剩余时间
    }
    public long deadlineNanos() {
        return SingleThreadIoEventLoop.this.deadlineNanos();
    }
};
```

每个 transport 自己用这三个值算 IO 多路复用的超时：
- **NioIoHandler**：`selectDeadLineNanos = currentTimeNanos + context.delayNanos()`，select 超时设为离下一个定时任务 deadline 的毫秒数
- **EpollIoHandler**：timerFd 直接 arm 到 deadline（`prevDeadlineNanos` 缓存减少 arm 次数）
- **IoUringIoHandler**：`submitAndWaitWithTimeout(sq, false, context.delayNanos())`——把 deadline 换算成 io_uring_enter 的 timeout_ns 参数

**canBlock() 是"是否允许长时间阻塞"**——有任务要执行时 IO handler 应尽量立即返回（selectNow、timeout=0 或 epollWait 的 immediate）。

### registerForIo0 + IoRegistrationWrapper

```java
private void registerForIo0(final IoHandle handle, Promise<IoRegistration> promise) {
    assert inEventLoop();
    final IoRegistration registration;
    try {
        registration = ioHandler.register(handle);
    } catch (Exception e) {
        promise.setFailure(e); return;
    }
    numRegistrations.incrementAndGet();
    promise.setSuccess(new IoRegistrationWrapper(registration));
}
```

`IoRegistrationWrapper` 是一个装饰器，`cancel()` 里额外 `numRegistrations.decrementAndGet()`——让 EventLoop 知道当前还有多少活跃注册，`canSuspend` 用的就是这个计数。

## NioIoHandler.run —— select 循环实锤

```java
public int run(IoHandlerContext context) {
    int handled = 0;
    try {
        switch (selectStrategy.calculateStrategy(selectNowSupplier, !context.canBlock())) {
            case CONTINUE: return 0;         // IO 策略要求跳过（busy-wait 但没任务）
            case SELECT:
                select(context, wakenUp.getAndSet(false)); // 阻塞 select
                // wakeup 竞态修复（4.1 就有但 4.2 保留在 IoHandler）
                if (wakenUp.get()) selector.wakeup();
        }
    } catch (IOException e) {
        rebuildSelector0(); handleLoopException(e); return 0;
    }
    handled = processSelectedKeys();
    if (context.shouldReportActiveIoTime()) {
        context.reportActiveIoTime(System.nanoTime() - activeIoStartTimeNanos);
    }
    return handled;
}
```

**与 4.1 的差异**：4.1 把 select + ready process + IO/timeouts 全塞在一个方法里；4.2 把它拆成独立 IoHandler 的 run，IoHandler 拿 context 从 SingleThreadIoEventLoop 取时间参数，同时把 transport 自己的 IO 准备（openSelector / epoll_create1）也提前到 `initialize()`。

### select 超时与定时任务 deadline

```java
private void select(IoHandlerContext runner, boolean oldWakenUp) throws IOException {
    long currentTimeNanos = System.nanoTime();
    long delayNanos = runner.delayNanos(currentTimeNanos);
    long selectDeadLineNanos = Long.MAX_VALUE;
    if (delayNanos != Long.MAX_VALUE) {
        selectDeadLineNanos = currentTimeNanos + delayNanos;
    }
    for (;;) {
        int timeoutMillis;
        if (delayNanos != Long.MAX_VALUE) {
            timeoutMillis = millisBeforeDeadline(selectDeadLineNanos, System.nanoTime());
        } else if (runner.canBlock()) {
            timeoutMillis = Long.MAX_VALUE; // 可以无限阻塞
        } else {
            timeoutMillis = 0;              // 有任务 → selectNow
        }
        int selectedKeys = selector.select(timeoutMillis);
        if (selectedKeys != 0 || oldWakenUp || wakenUp.get() || !runner.canBlock()) {
            break;
        }
    }
}
```

关键点：
- `oldWakenUp = wakenUp.getAndSet(false)`——在进入 select 前先置 false，select 返回后若又变 true 说明 wakeup 竞态了，要再唤醒一次
- `canBlock()` 返回 false 时 timeoutMillis = 0 → selectNow（无阻塞返回）
- 定时任务 deadline 驱动 select timeout——到点 select 自动返回，EventLoop 轮完 IO 后就去跑任务队列

### openSelector —— SelectedSelectionKeySet 反射注入

4.1/4.2 都有的 **SelectedSelectionKeySet** 技巧：通过反射把 JDK Selector 内部的 `selectedKeys` 和 `publicSelectedKeys` 字段换成 Netty 自己的实现，省掉每次迭代 `Iterator<SelectionKey>` 的开销：

```java
private SelectorTuple openSelector() {
    Selector unwrappedSelector = provider.openSelector();
    final Class<?> selectorImplClass = (Class<?>) maybeSelectorImplClass;
    if (selectorImplClass != null) {
        Field selectedKeysField = selectorImplClass.getDeclaredField("selectedKeys");
        Field publicSelectedKeysField = selectorImplClass.getDeclaredField("publicSelectedKeys");
        // sun.nio.ch.SelectorImpl —— JDK HotSpot 实现的标准路径
        long selectedKeysFieldOffset = PlatformDependent.objectFieldOffset(selectedKeysField);
        if (selectedKeysFieldOffset != -1 && publicSelectedKeysFieldOffset != -1) {
            // 用 UNSAFE 把 Netty 的 SelectedSelectionKeySet 替换掉两个字段
            ...
            selectedKeys = new SelectedSelectionKeySet();
        }
    }
}
```

`SelectedSelectionKeySet` 底层用 `SelectionKey[]` 数组 + 计数器（`Set` 接口实现），热路径上迭代 `for (int i = 0; i < size; i++)` 比 Iterator 快得多。

### selector 重建（JDK select 空轮询）

```java
// JDK NIO selector 的经典 bug：某些 Linux 内核版本下 selector.select() 返回 0 但没有任何就绪事件
if (selectedKeys == 0 && ++selectNowCount >= SELECTOR_AUTO_REBUILD_THRESHOLD) { // 默认 512
    rebuildSelector0();
}
```

4.1 就有、4.2 保留。阈值 `-Dio.netty.selectorAutoRebuildThreshold=512`。

## MultiThreadIoEventLoopGroup

```java
public class MultiThreadIoEventLoopGroup extends MultithreadEventLoopGroup implements IoEventLoopGroup {
    @Override
    protected EventLoop newChild(Executor executor, Object... args) {
        IoHandlerFactory handlerFactory = (IoHandlerFactory) args[0];
        return newChild(executor, handlerFactory, argsCopy); // 默认 SingleThreadIoEventLoop
    }
    protected IoEventLoop newChild(Executor executor, IoHandlerFactory ioHandlerFactory, Object... args) {
        return new SingleThreadIoEventLoop(this, executor, ioHandlerFactory);
    }
    public void setIoRatio(int ioRatio) { ... }
}
```

构造器签名统一成 `(nThreads, IoHandlerFactory)` 或 `(nThreads, Executor, IoHandlerFactory)`——把"具体用哪个 IO handler"从 EventLoopGroup 子类（NioEventLoopGroup / EpollEventLoopGroup）挪到 IoHandlerFactory 参数。

也支持 `EventExecutorChooserFactory` 注入（默认 `DefaultEventExecutorChooserFactory.INSTANCE`，thread-local round-robin）和 `AutoScalingEventExecutorChooserFactory`（利用率感知动态扩缩线程）。

## Links

- [Transport 与 IoHandler 抽象](/docs/CS/Framework/Netty/Transport.md)
- [Channel 与注册路径](/docs/CS/Framework/Netty/Channel.md)
- [Bootstrap 启动流程](/docs/CS/Framework/Netty/Bootstrap.md)
- [ChannelPipeline 与 Handler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [Future and Promise](/docs/CS/Framework/Netty/Future.md)
- [Netty.md 整体](/docs/CS/Framework/Netty/Netty.md)

## References

1. [Netty 4.2 SingleThreadIoEventLoop source](https://github.com/netty/netty/blob/4.2/transport/src/main/java/io/netty/channel/SingleThreadIoEventLoop.java)
2. [Netty 4.2 NioIoHandler source](https://github.com/netty/netty/blob/4.2/transport/src/main/java/io/netty/channel/nio/NioIoHandler.java)
3. [Netty #8566 — rebuildSelector IOException on select loop](https://github.com/netty/netty/issues/8566)
4. [Netty #597 — empty selectedKeys optimization](https://github.com/netty/netty/issues/597)
5. [OpenJDK JDK-8180450 — Duplex handler instanceof scalability](https://bugs.openjdk.org/browse/JDK-8180450)
