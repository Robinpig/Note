## Introduction

[CompletableFuture](/docs/CS/Java/JDK/Concurrency/CompletableFuture.md) 同时实现 [Future](/docs/CS/Java/JDK/Concurrency/Future.md) 与 `CompletionStage`：它既能像 FutureTask 那样承载一个异步结果，又支持**显式完成**（`complete` / `completeExceptionally`）与**依赖编排**（一串 `thenApply` 式的回调）。JDK 8（JEP 155: Concurrency Updates）引入，JDK 9（JEP 266: More Concurrency Updates）补上超时与子类扩展，是今天 Java 异步组合的事实标准。

与 FutureTask 的根本差异在于：**CompletableFuture 不控制产生结果的那个计算**。它不知道谁会在什么时候、用哪个线程完成自己，所以「取消」只是异常完成的一种形式：

```java
// 源码规格：cancel 与 completeExceptionally(new CancellationException()) 等价
// mayInterruptIfRunning 在本实现中没有任何作用——中断不参与处理控制
```

异常出口也因此分裂成两套：`get()` / `get(timeout, unit)` 抛受检的 `ExecutionException`（包着 `CompletionException` 的 cause），而 `join()` / `getNow(valueIfAbsent)` 直接抛未检查的 `CompletionException`。写组合链时用后者更顺滑。

> [!NOTE]
>
> 本文事实以 **JDK 25（jdk-25+36）** 源码核实，`@since` 标注均来自源码 javadoc。

## Creating and Completing

| 入口 | 说明 |
| --- | --- |
| `new CompletableFuture<>()` | 未完成，等待别人完成 |
| `completedFuture(v)` / `failedFuture(ex)` | 已是终态的静态工厂（JDK 8 / `failedFuture` JDK 9） |
| `supplyAsync(supplier[, executor])` / `runAsync(runnable[, executor])` | 异步执行后自动完成 |
| `complete(v)` / `completeExceptionally(ex)` | 竞争式完成——**多方调用只有一方成功**（源码：CAS `result` 字段） |
| `obtrudeValue(v)` / `obtrudeException(ex)` | 强制覆写已完成的 future，仅限错误恢复场景 |
| `completeAsync(supplier[, executor])` | JDK 9，从异步任务里供应完成值 |

`newIncompleteFuture()` 是「虚拟构造器」：所有 CompletionStage 方法返回的新 future 都经它创建，子类覆盖它即可让整条链变成自己的子类型；覆盖 `defaultExecutor()` 可替换默认执行器。`minimalCompletionStage()` 只暴露 CompletionStage 接口（客户端无法直接完成），`copy()` 是「防御性拷贝」——同样结果、独立完成权。

## CompletionStage Operations

单输入操作族（另有 `*Async` 变体）：

| 方法 | 正常完成 | 异常完成 |
| --- | --- | --- |
| `thenApply(fn)` | `fn(result)` 的结果完成下游 | **跳过**，异常沿链传播 |
| `thenAccept(action)` / `thenRun(action)` | 消费结果 / 只执行动作 | 跳过 |
| `thenCompose(fn)` | `fn` 返回的 stage 拍平到下游（flatMap） | 跳过 |
| `whenComplete(action)` | 执行动作，**结果原样透传** | 也执行（`ex` 非空），异常仍透传 |
| `handle(fn)` | `fn(result, null)` 完成下游 | `fn(null, ex)` 完成下游——**可恢复** |
| `exceptionally(fn)` | 结果透传 | `fn(ex)` 的结果完成下游 |

双输入与多路：`thenCombine`（两侧都正常才合并）、`thenAcceptBoth` / `runAfterBoth`（等待双方）、`applyToEither` / `acceptEither` / `runAfterEither`（任一先完成就用谁的结果）、静态 `allOf`（全部完成，任一异常则整体异常）与 `anyOf`（任一完成，结果透传；空参数返回**未完成**的 future）。

版本演进（源码 `@since` 可查）：

- **JDK 12**：`exceptionallyAsync` / `exceptionallyCompose` / `exceptionallyComposeAsync`——异常恢复也能异步化；
- **JDK 19**：`resultNow()` / `exceptionNow()` / `state()`——非阻塞读取，`state()` 返回 `RUNNING / SUCCESS / FAILED / CANCELLED`（`Future.State`），与阻塞的 `isDone()` 分工；
- **JDK 9**：`orTimeout` / `completeOnTimeout` / `delayedExecutor`（见下）。

`getNumberOfDependents()` 与 `toString()` 仅供监控，规格明确说**不要**用于同步控制。

## Execution Semantics

这是 CompletableFuture 最容易写错的部分，规格（译意）：

> 为**非 async** 方法的依赖完成所提供的动作，可能由完成当前 CompletableFuture 的那个线程执行，**也可能由任何其它调用了完成方法的线程执行**。

也就是说 `thenApply(fn)` 里的 `fn` **不保证**在哪个线程跑：可能是当初完成源 future 的那个线程，也可能是随后任一调用了完成方法的线程。只有 `*Async` 变体才有明确的执行器：

- 不传 executor 的 `*Async` → `ForkJoinPool.commonPool()`（并行度 `< 2` 时退化为「每个任务新建一个 Thread」，JDK 8 规格原文）；
- 所有异步任务实现标记接口 `AsynchronousCompletionTask`，便于监控与调试；
- 子类覆盖 `defaultExecutor()` 可改默认执行器。

实践含义有三条：

1. **别在非 async 回调里假设线程身份**——里面读 [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md) 是不安全的；要传上下文请用 [ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md) 或在 async 变体里显式绑定。
2. **别把阻塞操作丢给 commonPool**——`supplyAsync` 里做阻塞 I/O 会占住公共池的工作线程（并行度 = `availableProcessors() - 1`），拖垮同进程内所有异步任务。阻塞型任务显式传自己的 [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)，或用 [虚拟线程](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)执行器。
3. **组合链的末端仍然可以阻塞等待**：`allOf(...).join()` 是等一批独立任务全部完成的惯用法。

## Exception Propagation

异常沿依赖链**向下游传播**，直到被 `handle` / `exceptionally` / `whenComplete` 接住：

- 回调自身抛异常 → 下游 stage 以该异常异常完成（`whenComplete` 的动作抛异常时，若源本身也异常完成，则保留源异常）；
- 异常被包装为 `CompletionException`（`CancellationException` 是特例，不额外包装）；
- `isCompletedExceptionally()` 判断「以任何异常方式完成」，取消也算。

一个常见陷阱：`thenApply` 里抛出未检查异常后，如果没有任何 terminal 处理（`handle` / `exceptionally`），异常会一路静默传播到被遗忘的末端 future——不 `join()` 就永远看不到。

## Timeouts

JDK 9 起提供三种超时手段：

```java
CompletableFuture.supplyAsync(task)
                 .orTimeout(2, TimeUnit.SECONDS)        // 超时 → TimeoutException 异常完成
                 .completeOnTimeout(fallback, 2, TimeUnit.SECONDS);  // 超时 → 用 fallback 正常完成

// 延迟执行器：把任意 Async 方法变成「delay 之后才触发」
CompletableFuture.supplyAsync(supplier,
        CompletableFuture.delayedExecutor(1, TimeUnit.SECONDS));
```

`orTimeout` / `completeOnTimeout` 返回**自身**（原地完成），`delayedExecutor` 内部走 `DelayScheduler` 的定时 `ScheduledForkJoinTask`。

## Internals

源码 Overview 注释把设计讲得很清楚，骨架只有两个字段：

```java
volatile Object result;       // 结果，或装箱异常的 AltResult（NIL 装箱 null 结果）
volatile Completion stack;    // 依赖动作的 Treiber 栈顶
```

- **完成 = 一次 CAS**：`internalComplete` 用 `RESULT.compareAndSet(this, null, r)` 把 `result` 从 null 改成非 null；多线程竞争完成时只有一方成功，与规格里「只有一方成功」对应。这三个 `VarHandle`（`RESULT` / `STACK` / `NEXT`）本身就是 [VarHandle](/docs/CS/Java/JDK/Concurrency/VarHandle.md) 的典型用法。
- **依赖动作挂栈**：`thenXxx` 创建 `Completion` 对象，用 `tryPushStack` CAS 压入源 future 的 `stack`；压入后再复查一次，覆盖「源在压栈过程中刚好完成」的竞态。
- **完成即触发**：`postComplete` 把栈上每个依赖动作 pop 出来 `tryFire`（NESTED 模式），触发可递归传播；`tryFire(SYNC → ASYNC)` 两次调用的分工是：第一次筛选并包装异常、安排执行，第二次在任务里真正执行。
- **Completion extends ForkJoinTask**：这样异步执行时**零额外空间开销**——它复用 ForkJoinTask 的 tag 方法维护 claim。`get()` / `join()` 的阻塞则靠 `Signaller` Completion 唤醒，机制与 FutureTask、Phaser、SynchronousQueue 的等待节点同族。
- **双输入用树**：`allOf` 把多个源两两配对形成 `CoCompletion` 树（第二个 completion 指向第一个、共享，保证动作至多执行一次）；`anyOf` 用共享数组互相可达，任一完成即对其它源 `cleanStack`。
- **防垃圾累积**：字段尽早置 null，`cleanStack` 把已触发/已取消的 completion 从栈头解链；Completion 的字段不需要 `final` / `volatile`——它们只在安全发布后对其它线程可见。

## Pitfalls Checklist

1. 在 `thenApply`（非 async）里阻塞或读 ThreadLocal——执行线程不可控；
2. `supplyAsync` 无执行器 + 阻塞 I/O——拖垮 commonPool；
3. 依赖链末端不 `join` 也不挂 `exceptionally`——异常静默蒸发；
4. `allOf().join()` 中某个 future 被取消——整体以 `CompletionException` 失败；
5. 用 `obtrude*` 做常规状态更新——规格限定它只用于错误恢复；
6. 以为 `cancel(true)` 能中断正在跑的回调——本实现完全不使用中断来控制处理。

## Links

- [Future](/docs/CS/Java/JDK/Concurrency/Future.md)
- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)
- [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
- [ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [CompletableFuture (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CompletableFuture.html)
2. [JEP 155: Concurrency Updates](https://openjdk.org/jeps/155)
3. [JEP 266: More Concurrency Updates](https://openjdk.org/jeps/266)
4. [Concurrency JSR-166 Interest Site](http://gee.cs.oswego.edu/dl/concurrency-interest/index.html)
