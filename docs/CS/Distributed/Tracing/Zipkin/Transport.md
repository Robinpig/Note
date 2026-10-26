## Introduction

本篇展开 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的**传输层**：被埋点的库如何把 span 发给 collector，以及跨进程时如何传播 trace 上下文（**B3 格式**）。应用内的发送组件统称 **Reporter**，传输通道则有 HTTP、Kafka、RabbitMQ、Scribe 等。

## Transports

被埋点的应用把 span 发往 Zipkin collector 的主要方式：

| 传输 | 说明 |
| --- | --- |
| **HTTP** | 默认方式，向 `POST /api/v2/spans` 发送（JSON / protobuf） |
| **Kafka** | 经 Kafka topic（默认 `zipkin`）异步削峰，collector 消费 |
| **RabbitMQ** | 经消息队列，适合已有 MQ 基础设施的场景 |
| **Scribe** | Zipkin 早期的日志聚合传输（Facebook Scribe），现较少用 |
| 其它 | ActiveMQ、gRPC 等也有社区实现 |

传输对应用是透明的：业务代码只调用 `reporter.report(span)`，具体走哪条通道由 Reporter 背后的 `Sender` 决定。

## Reporters

`Reporter<S>` 是「把一条 span 调度到传输上」的抽象接口；`NOOP` 与 `CONSOLE` 是其两个内置实现（前者丢弃、后者打印）。

```java
public interface Reporter<S> {
  Reporter<Span> NOOP = new Reporter<Span>() {
    @Override public void report(Span span) {
    }

    @Override public String toString() {
      return "NoopReporter{}";
    }
  };
  Reporter<Span> CONSOLE = new Reporter<Span>() {
    @Override public void report(Span span) {
      System.out.println(span.toString());
    }

    @Override public String toString() {
      return "ConsoleReporter{}";
    }
  };

  /**
   * Schedules the span to be sent onto the transport.
   *
   * @param span Span, should not be <code>null</code>.
   */
  void report(S span);
}
```

### Asynchronous

生产环境几乎总是用 `AsyncReporter`：调用 `report()` 只把 span 入队，真正的编码与发送在独立 flush 线程完成，绝不阻塞业务线程。`BoundedAsyncReporter` 用有界字节队列缓冲，队列满或单条超 `messageMaxBytes` 时**丢弃并计入 dropped metrics**；发送失败时按异常类型递增 `messagesDropped` / `spansDropped`，首次失败后将后续错误降级到 FINE 避免日志风暴。

```java
static final class BoundedAsyncReporter<S> extends AsyncReporter<S> {
    static final Logger logger = Logger.getLogger(BoundedAsyncReporter.class.getName());
    final AtomicBoolean started, closed;
    final BytesEncoder<S> encoder;
    final ByteBoundedQueue<S> pending;
    final Sender sender;
    final int messageMaxBytes;
    final long messageTimeoutNanos, closeTimeoutNanos;
    final CountDownLatch close;
    final ReporterMetrics metrics;
    final ThreadFactory threadFactory;

    void startFlusherThread() {
        BufferNextMessage<S> consumer =
                BufferNextMessage.create(encoder.encoding(), messageMaxBytes, messageTimeoutNanos);
        Thread flushThread = threadFactory.newThread(new Flusher<>(this, consumer));
        flushThread.setName("AsyncReporter{" + sender + "}");
        flushThread.setDaemon(true);
        flushThread.start();
    }

    @Override
    public void report(S next) {
        if (next == null) throw new NullPointerException("span == null");
        // Lazy start so that reporters never used don't spawn threads
        if (started.compareAndSet(false, true)) startFlusherThread();
        metrics.incrementSpans(1);
        int nextSizeInBytes = encoder.sizeInBytes(next);
        int messageSizeOfNextSpan = sender.messageSizeInBytes(nextSizeInBytes);
        metrics.incrementSpanBytes(nextSizeInBytes);
        if (closed.get() ||
                // don't enqueue something larger than we can drain
                messageSizeOfNextSpan > messageMaxBytes ||
                !pending.offer(next, nextSizeInBytes)) {
            metrics.incrementSpansDropped(1);
        }
    }

    @Override
    public final void flush() {
        if (closed.get()) throw new ClosedSenderException();
        flush(BufferNextMessage.create(encoder.encoding(), messageMaxBytes, 0));
    }


    void flush(BufferNextMessage<S> bundler) {
        pending.drainTo(bundler, bundler.remainingNanos());

        // record after flushing reduces the amount of gauge events vs on doing this on report
        metrics.updateQueuedSpans(pending.count);
        metrics.updateQueuedBytes(pending.sizeInBytes());

        // loop around if we are running, and the bundle isn't full
        // if we are closed, try to send what's pending
        if (!bundler.isReady() && !closed.get()) return;

        // Signal that we are about to send a message of a known size in bytes
        metrics.incrementMessages();
        metrics.incrementMessageBytes(bundler.sizeInBytes());

        // Create the next message. Since we are outside the lock shared with writers, we can encode
        ArrayList<byte[]> nextMessage = new ArrayList<>(bundler.count());
        bundler.drain(new SpanWithSizeConsumer<S>() {
            @Override public boolean offer(S next, int nextSizeInBytes) {
                nextMessage.add(encoder.encode(next)); // speculatively add to the pending message
                if (sender.messageSizeInBytes(nextMessage) > messageMaxBytes) {
                    // if we overran the message size, remove the encoded message.
                    nextMessage.remove(nextMessage.size() - 1);
                    return false;
                }
                return true;
            }
        });

        try {
            sender.sendSpans(nextMessage).execute();
        } catch (Throwable t) {
            // In failure case, we increment messages and spans dropped.
            int count = nextMessage.size();
            Call.propagateIfFatal(t);
            metrics.incrementMessagesDropped(t);
            metrics.incrementSpansDropped(count);

            Level logLevel = FINE;

            if (shouldWarnException) {
                logger.log(WARNING, "Spans were dropped due to exceptions. "
                        + "All subsequent errors will be logged at FINE level.");
                logLevel = WARNING;
                shouldWarnException = false;
            }

            if (logger.isLoggable(logLevel)) {
                logger.log(logLevel,
                        format("Dropped %s spans due to %s(%s)", count, t.getClass().getSimpleName(),
                                t.getMessage() == null ? "" : t.getMessage()), t);
            }

            // Raise in case the sender was closed out-of-band.
            if (t instanceof ClosedSenderException) throw (ClosedSenderException) t;

            // Old senders in other artifacts may be using this less precise way of indicating they've been closed
            // out-of-band.
            if (t instanceof IllegalStateException && t.getMessage().equals("closed"))
                throw (IllegalStateException) t;
        }
    }
}
```

### Sleuth

Spring 生态历史上用 **Spring Cloud Sleuth** 作为 Zipkin 客户端，它在内部用 `CompositeReporter` 串起若干 `SpanAdjuster` 与真正的 `spanReporter`：先依次应用调整器（例如补充 `span.kind`、规范化 tag），再交给底层 reporter。Sleuth 现已 EOL，由 **Micrometer Tracing** 取代（参见 [Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md)）。

```java
	private static final class CompositeReporter implements Reporter<zipkin2.Span> {

		private static final Log log = LogFactory.getLog(CompositeReporter.class);

		private final List<SpanAdjuster> spanAdjusters;

		private final Reporter<zipkin2.Span> spanReporter;

		private CompositeReporter(List<SpanAdjuster> spanAdjusters,
				List<Reporter<Span>> spanReporters) {
			this.spanAdjusters = spanAdjusters;
			this.spanReporter = spanReporters.size() == 1 ? spanReporters.get(0)
					: new ListReporter(spanReporters);
		}

		@Override
		public void report(Span span) {
			Span spanToAdjust = span;
			for (SpanAdjuster spanAdjuster : this.spanAdjusters) {
				spanToAdjust = spanAdjuster.adjust(spanToAdjust);
			}
			this.spanReporter.report(spanToAdjust);
		}

		private static final class ListReporter implements Reporter<zipkin2.Span> {

			private final List<Reporter<Span>> spanReporters;

			private ListReporter(List<Reporter<Span>> spanReporters) {
				this.spanReporters = spanReporters;
			}

			@Override
			public void report(Span span) {
				for (Reporter<zipkin2.Span> spanReporter : this.spanReporters) {
					try {
						spanReporter.report(span);
					}
					catch (Exception ex) {
						log.warn("Exception occurred while trying to report the span " + span, ex);
					}
				}
			}
		}

	}
```

## Instrumentation Libraries

| 语言 | 库 | 说明 |
| --- | --- | --- |
| Java | **Brave** | Zipkin 官方 Java instrumentation，提供 tracer、handler 拦截器与 B3 传播 |
| Go | zipkin-go | 官方 Go 库，含 `model`、`reporter` 与 B3 传播 |
| .NET | zipkin4net | 官方 .NET reporter |
| C++ | zipkin-cpp-opentracing | OpenTracing 桥接 |
| 多语言 | OpenTelemetry | 经 OTel Collector 的 **zipkin exporter** 对接 Zipkin（见下方） |

## B3 Propagation

跨进程传递 trace 上下文的格式叫 **B3**（名字来自 Zipkin 原名 *BigBrotherBird*）。它有两种形式：

### Multi-header（多 header，兼容性最广）

```
X-B3-TraceId: 463ac35c9f6413ad48485a3953bb6124   # 128 或 64 位 lower-hex（必填）
X-B3-SpanId:  0020000000000001                   # 64 位 lower-hex（必填）
X-B3-ParentSpanId: 0010000000000000              # 64 位 lower-hex（root span 缺省）
X-B3-Sampled: 1                                  # "1"/"0"，可缺省
X-B3-Flags: 1                                    # "1" 表示 debug，可缺省
```

### Single-header（单 header）

把所有字段用 `-` 拼进一个 `b3` 头：`{traceId}-{spanId}-{sampled|flags}-{parentSpanId}`。

```
b3: 463ac35c9f6413ad48485a3953bb6124-0020000000000001-1-0010000000000000
```

`Sampled` 取值 `1`（采样）/ `0`（不采样）/ `d`（debug）；只有 traceId 与 spanId 是必填的，下游也可只传播一个采样决策（如 `b3: 0` / `b3: 1`）。消息消费端（永远工作在 child span）可用不含 parentId 的紧凑写法以省字节。

**采样决策在系统边缘做出，下游必须遵从上游**：若入站请求没有 `Sampled` 信息，本服务再自行决定并把决策继续向下游传播。`debug` 标志会强制采样并尽量保证送达 collector 层。

## Relationship to OpenTelemetry

[OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 默认用 **W3C Trace Context**（`traceparent` / `tracestate`）传播，而 Zipkin 生态用 B3。迁移或混部时，在 OTel 侧启用 **B3 propagator**（多 / 单 header）即可让 OTel 服务与既有 Zipkin 服务参与同一条 trace；OTel Collector 的 **zipkin exporter** 则负责把 OTLP span 转成 Zipkin v2 格式写入。

## Links

- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 枢纽页
- [Zipkin Architecture](/docs/CS/Distributed/Tracing/Zipkin/Architecture.md) — 异步上报与带内传播原则
- [Zipkin Data Model](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md) — 被传播的 traceId/spanId/parentId 语义
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — B3 propagator 与 zipkin exporter
- [Spring Cloud Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md) — 历史 Java 客户端（已 EOL）

## References

1. [Instrumenting a library](https://zipkin.io/pages/instrumenting) — 埋点、B3 头与采样规则
2. [B3 Propagation](https://github.com/openzipkin/b3-propagation) — B3 规范
3. [Brave](https://github.com/openzipkin/brave) — Java instrumentation 库
4. [zipkin-go](https://github.com/openzipkin/zipkin-go) — 官方 Go 库
