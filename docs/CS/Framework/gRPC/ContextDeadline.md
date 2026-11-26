# gRPC Java Context, Deadline and Cancellation

## Introduction

超时与取消是 RPC 语义里最容易出错的部分。gRPC Java 用两个类承载它们：`Context` 是跨线程传播的"调用上下文"（携带值、deadline、取消监听），`Deadline` 是一个绝对时刻。一次调用的最终 deadline 由三方共同决定，最终编码成请求头的 `grpc-timeout`；取消则沿 Context 监听器传播到 transport 的 RST_STREAM。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。以下片段均取自该 tag。

两个反直觉点：

- **超时编码是"贪心精度"**：`cutoff = 100000000`（1e8 ns，即 100ms），2 秒被编码成 `2000000u` 而不是 `2S`——源码注释明确写了这个例子。
- **服务端只有 deadline 到期才主动 cancel stream**：客户端主动取消时 RST_STREAM 已关闭 stream；只有本地 deadline 先到时，`ServerStreamCancellationListener` 才会 `stream.cancel(status)`。

## Deadline: An Absolute Instant

`Deadline` 内部只存一个绝对时刻 `deadlineNanos = baseInstant + offset`，`expired` 用懒计算（`isExpired()` 首次检查时置位）：

```java
// api/src/context/java/io/grpc/Deadline.java
private Deadline(Ticker ticker, long baseInstant, long offset,
    boolean baseInstantAlreadyExpired) {
  this.ticker = ticker;
  // Clamp to range [MIN_OFFSET, MAX_OFFSET]
  offset = Math.min(MAX_OFFSET, Math.max(MIN_OFFSET, offset));
  deadlineNanos = baseInstant + offset;
  expired = baseInstantAlreadyExpired && offset <= 0;
}

@Override
public boolean isExpired() {
  if (!expired) {
    if (deadlineNanos - ticker.nanoTime() <= 0) {
      expired = true;
    } else {
      return false;
    }
  }
  return true;
}
```

两个源码细节：`offset` 被钳制在 `[MIN_OFFSET, MAX_OFFSET]`（约 ±292 年，避免 `baseInstant + offset` 长溢出）；`minimum(other)` 要求两者用同一个 `Ticker`（`checkTicker`），否则比较无意义。

## Three-Way Deadline Merge

客户端最终 deadline 是三方取最早者：

1. **CallOptions deadline**：用户通过 `CallOptions.withDeadline()` 设置。
2. **Context deadline**：调用线程的 `Context.current().getDeadline()`。
3. **Service config timeout**：resolver 下发的 method config 里的 `timeout`。

前两者的合并发生在 `ClientCallImpl`：

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
@Nullable
private Deadline effectiveDeadline() {
  // Call options and context are immutable, so we don't need to cache the deadline.
  return min(callOptions.getDeadline(), context.getDeadline());
}
```

service config 的 timeout 更早介入——在 `applyMethodConfig()` 里，若 computed timeout 比现有 deadline 更早，就 swap 进 callOptions：

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
private void applyMethodConfig() {
  MethodInfo info = callOptions.getOption(MethodInfo.KEY);
  if (info == null) {
    return;
  }
  if (info.timeoutNanos != null) {
    Deadline newDeadline = Deadline.after(info.timeoutNanos, TimeUnit.NANOSECONDS);
    Deadline existingDeadline = callOptions.getDeadline();
    // If the new deadline is sooner than the existing deadline, swap them.
    if (existingDeadline == null || newDeadline.compareTo(existingDeadline) < 0) {
      callOptions = callOptions.withDeadline(newDeadline);
    }
  }
  // ... waitForReady ...
}
```

`compareTo < 0` 即"newDeadline 更早"——service config 只能**收紧**超时，不能放宽。

## Timeout Marshalling: Greedy Precision

`TimeoutMarshaller` 把纳秒编码成"最多 8 位数字 + 单位"的线格式。它的单位选择不是按语义（秒用 S），而是按 `cutoff = 1e8` 分级选**能放下最多 8 位**的最小单位：

```java
// core/src/main/java/io/grpc/internal/GrpcUtil.java
@Override
public String toAsciiString(Long timeoutNanosObject) {
  long cutoff = 100000000;
  long timeoutNanos = Math.max(1, timeoutNanosObject);
  TimeUnit unit = TimeUnit.NANOSECONDS;
  if (timeoutNanos < cutoff) {
    return timeoutNanos + "n";
  } else if (timeoutNanos < cutoff * 1000L) {
    return unit.toMicros(timeoutNanos) + "u";
  } else if (timeoutNanos < cutoff * 1000L * 1000L) {
    return unit.toMillis(timeoutNanos) + "m";
  } else if (timeoutNanos < cutoff * 1000L * 1000L * 1000L) {
    return unit.toSeconds(timeoutNanos) + "S";
  } else if (timeoutNanos < cutoff * 1000L * 1000L * 1000L * 60L) {
    return unit.toMinutes(timeoutNanos) + "M";
  } else {
    return unit.toHours(timeoutNanos) + "H";
  }
}
```

源码注释直接给出例子："2 seconds will be represented as `2000000u`"。按 cutoff 推算：2s = 2e9 ns，而 `cutoff*1000 = 1e11`，所以 2e9 落在第二个分支（`< cutoff*1000`），转成微秒 = 2e9/1e3 = 2,000,000，即 `2000000u`。分档依次是 `<1e8`→n、`<1e11`→u、`<1e14`→m、`<1e17`→S、`<6e18`→M、其余→H。选单位的原则是**让数值保持在 8 位以内**，而非按人类习惯选"秒就用 S"。单位字符大小写敏感：`m` 毫秒、`M` 分钟、`n` 纳秒、`u` 微秒、`S` 秒、`H` 小时。解码侧 `parseAsciiString` 用 switch，允许最多 9 字符（8 位数字 + 1 单位）。

> [!WARNING]
> grpc-timeout 是**相对值**在线上传输，deadline 是**绝对值**在内存里维护。每跳（proxy / server）都要用当前时间重新计算自己的 deadline，不是把字符串原样转发——服务端 `createContext` 里 `Deadline.after(timeoutNanos, NANOSECONDS, ticker)` 就是证据（见 [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md)）。

## Cancellation Propagation: Context Listeners

`ClientCallImpl.CancellationHandler` 把 Context 取消或 deadline 到期转成 `stream.cancel(status)`。它只在 `stream.start()` 之后 `setUp()`——源码注释点明"多数 transport 在 start 前收到 cancel 会出问题（Issue #1343）"。

一个关键优化：**若有效 deadline 来自 Context，就不额外调度定时任务**，因为 Context 自己会在到期时触发 listener；只有 deadline 来自 CallOptions（Context 无 deadline）时才 `schedule` 一个任务：

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
private final class CancellationHandler implements Runnable, CancellationListener {
  private final boolean contextIsDeadlineSource;
  private final boolean hasDeadline;
  private final long remainingNanos;
  private volatile ScheduledFuture<?> deadlineCancellationFuture;
  private volatile boolean tearDownCalled;

  CancellationHandler(Deadline deadline, boolean contextIsDeadlineSource) {
    this.contextIsDeadlineSource = contextIsDeadlineSource;
    if (deadline == null) {
      hasDeadline = false;
      remainingNanos = 0;
    } else {
      hasDeadline = true;
      remainingNanos = deadline.timeRemaining(TimeUnit.NANOSECONDS);
    }
  }

  void setUp() {
    if (tearDownCalled) {
      return;
    }
    if (hasDeadline
        // If the context has the effective deadline, we don't need to schedule an extra task.
        && !contextIsDeadlineSource
        // If the channel has been terminated, we don't need to schedule an extra task.
        && deadlineCancellationExecutor != null) {
      deadlineCancellationFuture = deadlineCancellationExecutor.schedule(
          new LogExceptionRunnable(this), remainingNanos, TimeUnit.NANOSECONDS);
    }
    context.addListener(this, directExecutor());
    if (tearDownCalled) {
      // Race detected! Re-run to make sure the future is cancelled and context listener removed
      tearDown();
    }
  }
```

`setUp` 末尾的二次 `tearDownCalled` 检查是竞态防护：`cancel()` 可能与 `setUp()` 并发，若 setUp 期间已被 tearDown，就补做一次清理。`cancelled()` 里还有一层细化——当 deadline 来自 Context 且取消原因是 `TimeoutException` 时，格式化成带 deadline 描述的 `DEADLINE_EXCEEDED`，否则按普通取消处理。

服务端侧只有 deadline 到期才主动 cancel（客户端取消已由 RST_STREAM 完成），见 [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md) 的真实片段。

## Context as a Value Bag

除了 deadline 和取消，`Context` 还是跨线程的值容器（认证主体、trace id 等）。`attach()` / `detach()` 成对使用，源码反复强调"每个 attach 必须有同方法内的 detach"：

```java
// api/src/context/java/io/grpc/Context.java
// Context previous = someContext.attach();
// try {
//   ... work with someContext as current ...
// } finally {
//   someContext.detach(previous);
// }
public Context attach() {
  // ...
}
```

`fork()` 只继承值、不继承取消——`ServerImpl` 用它在所有请求间共享 rootContext 的值，又不让一个请求的取消传染给其他请求。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与纠偏表
- [ClientCallChain](/docs/CS/Framework/gRPC/ClientCallChain.md) — deadline 三方合并的调用入口
- [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md) — 服务端 deadline 重建与 cancellation listener
- [Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 流上的取消与超时
- [RPC](/docs/CS/Distributed/RPC/RPC.md) — 超时、孤儿与重复执行语义的概念源头
- [Status](/docs/CS/Framework/gRPC/Status.md) — CANCELLED / DEADLINE_EXCEEDED 状态码

## References

- [grpc-java v1.75.0 Deadline.java](https://github.com/grpc/grpc-java/blob/v1.75.0/api/src/context/java/io/grpc/Deadline.java)
- [grpc-java v1.75.0 Context.java](https://github.com/grpc/grpc-java/blob/v1.75.0/api/src/context/java/io/grpc/Context.java)
- [grpc-java v1.75.0 GrpcUtil.TimeoutMarshaller](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/GrpcUtil.java)
- [gRFC: gRPC over HTTP/2 - Timeout](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md#requests)
