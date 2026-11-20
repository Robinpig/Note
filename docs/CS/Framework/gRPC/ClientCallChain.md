# gRPC Java Client Call Chain

## Introduction

一次 unary 调用从应用代码到 HTTP/2 帧，中间经过 stub → `ClientCallImpl` → `ClientStream` → transport 四层。本页沿 grpc-java 1.75.0 源码把这条链走一遍，重点看每次调用都会经过的截获点：deadline 计算、压缩器选择、Unary 与 Streaming 的 flush 差异、以及取消为何要延后到 `start()` 之后。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。以下片段均取自该 tag。

三个反直觉点：

- **deadline 已过就不建流**：`start()` 里先算 `remainingNanos`，若 ≤ 0，直接构造 `FailingClientStream`，真实 transport 根本不会被触碰。
- **unary 不主动 flush**：`sendMessage` 对 unary 调用跳过 `stream.flush()`，靠随后的 `halfClose()` 把 `END_STREAM=true` piggy-back 到最后一帧。
- **取消监听延后注册**：`cancellationHandler.setUp()` 放在 `stream.start()` 之后，源码注释明说多数 transport 在 start 前收到 cancel 会崩（Issue #1343）。

## The Four Stages

一次调用分四步，对应 gRPC 通用调用模型：

```dot
digraph ClientCallChain {
  rankdir=LR;
  node [shape=box, style=rounded];

  app [label="应用\nstub.blockingUnaryCall"];
  impl [label="ClientCallImpl\nstart/sendMessage/halfClose"];
  stream [label="ClientStream\n(AbstractClientStream)"];
  transport [label="NettyClientTransport\nwriteHeaders/deliverFrame"];

  app -> impl [label="method.streamRequest"];
  impl -> stream [label="writeMessage / request"];
  stream -> transport [label="framer.deliverFrame"];
}
```

## Stage 1: start() — Deadline & Header Preparation

`start(Listener, Metadata)` 是入口，但它是个薄包装——真正的逻辑在 `startInternal()`。后者先处理两个"短路"分支：Context 已取消时用 `NoopClientStream.INSTANCE`（不建真实流，只回调通知 observer），压缩器找不到时回 `INTERNAL`。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
@Override
public void start(Listener<RespT> observer, Metadata headers) {
  try (TaskCloseable ignore = PerfMark.traceTask("ClientCall.start")) {
    PerfMark.attachTag(tag);
    startInternal(observer, headers);
  }
}

private void startInternal(Listener<RespT> observer, Metadata headers) {
  checkState(stream == null, "Already started");
  checkState(!cancelCalled, "call was cancelled");
  checkNotNull(observer, "observer");
  checkNotNull(headers, "headers");

  if (context.isCancelled()) {
    // Context is already cancelled so no need to create a real stream, just notify the observer
    // of cancellation via callback on the executor
    stream = NoopClientStream.INSTANCE;
    final Listener<RespT> finalObserver = observer;
    class ClosedByContext extends ContextRunnable { /* closes observer with statusFromCancelled */ }
    callExecutor.execute(new ClosedByContext());
    return;
  }
  applyMethodConfig();
```

Context 已取消的短路之后，`applyMethodConfig()` 合并 service config 的超时（见 [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md)），再查压缩器、准备 headers，才进入建流逻辑。压缩器找不到时同样用 `NoopClientStream` 短路，回 `INTERNAL: Unable to find compressor by name %s`。

过了短路分支，才算有效 deadline、建流。deadline 已超时时构造 `FailingClientStream`（不是返回 null）：

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
Deadline effectiveDeadline = effectiveDeadline();
boolean contextIsDeadlineSource = effectiveDeadline != null
    && effectiveDeadline.equals(context.getDeadline());
cancellationHandler = new CancellationHandler(effectiveDeadline, contextIsDeadlineSource);
boolean deadlineExceeded = effectiveDeadline != null && cancellationHandler.remainingNanos <= 0;
if (!deadlineExceeded) {
  stream = clientStreamProvider.newStream(method, callOptions, headers, context);
} else {
  // ... assemble description with name resolution delay ...
  stream = new FailingClientStream(DEADLINE_EXCEEDED.withDescription(description), tracers);
}
```

`effectiveDeadline()` 取 CallOptions 与 Context 的 deadline 的最小值；相等时说明 deadline 来自 Context——这个布尔值会决定超时日志里显示 `Context` 还是 `CallOptions`，也决定是否需要额外调度取消任务（Context 自己会调度）。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
@Nullable
private Deadline effectiveDeadline() {
  // Call options and context are immutable, so we don't need to cache the deadline.
  return min(callOptions.getDeadline(), context.getDeadline());
}

private static Deadline min(@Nullable Deadline deadline0, @Nullable Deadline deadline1) {
  if (deadline0 == null) return deadline1;
  if (deadline1 == null) return deadline0;
  return deadline0.minimum(deadline1);
}
```

建流后逐一把配置灌进 stream：authority、max inbound/outbound size、deadline、compressor、decompressor registry，最后 `stream.start()` 并注册取消传播。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
if (effectiveDeadline != null) {
  stream.setDeadline(effectiveDeadline);
}
stream.setCompressor(compressor);
stream.setDecompressorRegistry(decompressorRegistry);
channelCallsTracer.reportCallStarted();
stream.start(new ClientStreamListenerImpl(observer));

// Delay any sources of cancellation after start(), because most of the transports are broken if
// they receive cancel before start. Issue #1343 has more details
cancellationHandler.setUp();
```

## Stage 2: request() — Flow Control Gate

`request(n)` 是响应侧的流控闸门——它告诉 transport"我还想收 n 条消息"。不加 `request(1)` 是手写 `ClientCall` 时最常见的 bug：服务端发了消息，客户端却永远不投递给 listener。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
@Override
public void request(int numMessages) {
  try (TaskCloseable ignore = PerfMark.traceTask("ClientCall.request")) {
    PerfMark.attachTag(tag);
    checkState(stream != null, "Not started");
    checkArgument(numMessages >= 0, "Number requested must be non-negative");
    stream.request(numMessages);
  }
}
```

阻塞 stub 会自动 `request(1)`，所以业务代码通常无感；只有直接操作 `ClientCall` 时才需要手动管理（详见 [FlowControl](/docs/CS/Framework/gRPC/FlowControl.md)）。

## Stage 3: sendMessage() — Retrable vs Plain

`sendMessage` 判断 stream 是否为 `RetriableStream`（配置了重试策略时），据此走不同分支。序列化由 `method.streamRequest(message)` 完成——这就是 stub 生成代码里注册的 marshaller。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
private void sendMessageInternal(ReqT message) {
  checkState(stream != null, "Not started");
  checkState(!cancelCalled, "call was cancelled");
  checkState(!halfCloseCalled, "call was half-closed");
  try {
    if (stream instanceof RetriableStream) {
      @SuppressWarnings("unchecked")
      RetriableStream<ReqT> retriableStream = (RetriableStream<ReqT>) stream;
      retriableStream.sendMessage(message);
    } else {
      stream.writeMessage(method.streamRequest(message));
    }
  } catch (RuntimeException e) {
    stream.cancel(Status.CANCELLED.withCause(e).withDescription("Failed to stream message"));
    return;
  }
  // For unary requests, we don't flush since we know that halfClose should be coming soon.
  // This allows us to piggy-back the END_STREAM=true on the last message frame without opening the
  // possibility of broken applications forgetting to call halfClose without noticing.
  if (!unaryRequest) {
    stream.flush();
  }
}
```

序列化失败（RuntimeException）不会抛给应用，而是转成 `CANCELLED` 取消调用——这是"为什么业务 marshaller 抛异常，调用方看到的是 CANCELLED 而不是异常"的原因。

## Stage 4: halfClose() and cancel()

`halfClose()` 关闭请求的半边（告诉服务端"我发完了"）；`cancel()` 则整个取消调用。`cancelInternal` 的源码强调：即使在 `start()` 之前被调用（比如 `request()` 里出错），也要安全处理——`stream` 可能为 null，但 `cancellationHandler` 必须 tearDown。

```java
// core/src/main/java/io/grpc/internal/ClientCallImpl.java
private void cancelInternal(@Nullable String message, @Nullable Throwable cause) {
  if (message == null && cause == null) {
    cause = new CancellationException("Cancelled without a message or cause");
    log.log(Level.WARNING, "Cancelling without a message or cause is suboptimal", cause);
  }
  if (cancelCalled) {
    return;
  }
  cancelCalled = true;
  try {
    if (stream != null) {
      Status status = Status.CANCELLED;
      status = message != null ? status.withDescription(message)
          : status.withDescription("Call cancelled without message");
      if (cause != null) {
        status = status.withCause(cause);
      }
      stream.cancel(status);
    }
  } finally {
    // start() might not have been called
    if (cancellationHandler != null) {
      cancellationHandler.tearDown();
    }
  }
}
```

`cancelCalled` 是幂等标志——重复 cancel 只有第一次生效。取消最终沿 HTTP/2 的 `RST_STREAM` 传到服务端，服务端 handler 从 Context 观察到——这是"孤儿 RPC"问题的现代解答：框架提供取消通道，但业务代码仍要主动检查 `Context.isCancelled()`（见 [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md)）。

## Interceptors in the Chain

客户端拦截器包在 `ClientCall` 外面：`ClientInterceptors.intercept(channel, interceptors)` 生成一个 `InterceptorChannel`，每次 `newCall` 时用 `InterceptCall` 逐层包裹。最外层先执行 `start`，最接近网络的那层最后执行——与服务端 interceptor 的包裹方向相反（服务端在 `wrapMethod` 里 for 循环逐层 `interceptCallHandlerCreate`，见 [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md)）。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与纠偏
- [Framing](/docs/CS/Framework/gRPC/Framing.md) — writeMessage 之后如何变成 5 字节头帧
- [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md) — 服务端如何接收与回传
- [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md) — deadline 三方取最小与取消传播
- [FlowControl](/docs/CS/Framework/gRPC/FlowControl.md) — request(n) 背后的背压
- [Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 四种模式下的调用链差异

## References

- [grpc-java v1.75.0 ClientCallImpl.java](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/ClientCallImpl.java)
- [gRPC Java Core Concepts](https://grpc.io/docs/what-is-grpc/core-concepts/)
- [gRPC Issue #1343: cancel before start](https://github.com/grpc/grpc-java/issues/1343)
