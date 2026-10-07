## Introduction

[Zipkin](https://zipkin.io/) 是一个分布式追踪系统。
它帮助收集排查服务架构中延迟问题所需的时序数据。
其功能包括对这些数据的收集与查询。

### Architecture

Tracer 运行在你的应用中，记录下所发生操作的时间与元数据。
它们通常会对各类库做 instrumentation（埋点），因此对用户是透明的。
收集到的追踪数据称为一个 Span。

Instrumentation 被设计为可在生产环境安全使用，且开销极小。
出于这个原因，它们只在带内传播 ID，以告知接收方当前有一条 trace 正在进行。
Trace instrumentation 异步上报 span，以免追踪系统自身的延迟或故障拖慢、打断用户代码。

下面这张来自 Zipkin 官网的图描述了这一流程：



<div style="text-align: center;">

![Fig.1. Architecture](https://zipkin.io/public/img/architecture-1.png)

</div>

<p style="text-align: center;">
Fig.1. Architecture
</p>



## Transport

被埋点的库发出的 span 必须被传输，从被追踪的服务送达 Zipkin collectors。
主要有三种传输方式：HTTP、Kafka 与 Scribe。

### Reporters

被埋点的应用中，负责把数据发送给 Zipkin 的组件称为 Reporter。
Reporter 通过若干种传输方式之一，将追踪数据发送给 Zipkin collectors，由后者把追踪数据持久化到存储中。

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

#### Sleuth
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
#### Asynchronous
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

## Collectors
当追踪数据抵达 Zipkin collector 守护进程后，它会对其进行校验、存储并建立索引，以便被 Zipkin collector 查询。


## Storage

Zipkin 最初构建在 Cassandra 之上，因为 Cassandra 具备良好的可扩展性、灵活的 schema，并且在 Twitter 内部被大量使用。
不过我们让这一组件变得可插拔。除 Cassandra 外，我们还原生支持 ElasticSearch 与 MySQL。
其它后端可能以第三方扩展的形式提供。

## Query Service

数据被存储并建立索引后，我们需要一种方式把它取出来。Query 守护进程提供了一个简单的 JSON API，用于查找与检索 traces。
该 API 的主要消费者是 Web UI。


## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
