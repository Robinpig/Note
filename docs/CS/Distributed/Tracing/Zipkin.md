## Introduction

[Zipkin](https://zipkin.io/) 是一个分布式追踪系统。
它帮助收集用于排查服务架构中延迟问题所需的时序数据。
功能包括数据的收集和查找。

### Architecture

Tracer 存在于应用程序中，记录所发生操作的时序和元数据。
它们通常对库进行埋点，以便对用户透明使用。
收集到的追踪数据称为 Span。

埋点被编写为在生产环境中安全且开销很小。
因此，它们仅带内传播 ID，以告知接收方有追踪正在进行。
追踪埋点异步报告 span，以防止与追踪系统相关的延迟或故障延迟或破坏用户代码。

以下是来自 Zipkin 主页的描述此流程的示意图：

<div style="text-align: center;">

![Fig.1. Architecture](https://zipkin.io/public/img/architecture-1.png)

</div>

<p style="text-align: center;">
Fig.1. 架构
</p>

## Transport

被埋点库发送的 span 必须从被追踪的服务传输到 Zipkin collector。
有三种主要的传输方式：HTTP、Kafka 和 Scribe。

### Reporter

被埋点应用中向 Zipkin 发送数据的组件称为 Reporter。
Reporter 通过多种传输方式之一将追踪数据发送到 Zipkin collector，collector 将追踪数据持久化到存储中。

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

#### Async

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
        if (started.compareAndSet(false, true)) startFlusherThread();
        metrics.incrementSpans(1);
        int nextSizeInBytes = encoder.sizeInBytes(next);
        int messageSizeOfNextSpan = sender.messageSizeInBytes(nextSizeInBytes);
        metrics.incrementSpanBytes(nextSizeInBytes);
        if (closed.get() ||
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
        metrics.updateQueuedSpans(pending.count);
        metrics.updateQueuedBytes(pending.sizeInBytes);
        if (!bundler.isReady() && !closed.get()) return;
        metrics.incrementMessages();
        metrics.incrementMessageBytes(bundler.sizeInBytes());
        ArrayList<byte[]> nextMessage = new ArrayList<>(bundler.count());
        bundler.drain(new SpanWithSizeConsumer<S>() {
            @Override public boolean offer(S next, int nextSizeInBytes) {
                nextMessage.add(encoder.encode(next));
                if (sender.messageSizeInBytes(nextMessage) > messageMaxBytes) {
                    nextMessage.remove(nextMessage.size() - 1);
                    return false;
                }
                return true;
            }
        });
        try {
            sender.sendSpans(nextMessage).execute();
        } catch (Throwable t) {
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
            if (t instanceof ClosedSenderException) throw (ClosedSenderException) t;
            if (t instanceof IllegalStateException && t.getMessage().equals("closed"))
                throw (IllegalStateException) t;
        }
    }
}
```

## Collector

一旦追踪数据到达 Zipkin collector 守护进程，它就会被验证、存储和索引，以供 Zipkin collector 查询。

## Storage

Zipkin 最初构建时使用 Cassandra 存储数据，因为 Cassandra 可扩展、具有灵活的模式，并且在 Twitter 内部被广泛使用。
然而，我们使这个组件可插拔。除了 Cassandra，我们还原生支持 ElasticSearch 和 MySQL。
其他后端可能作为第三方扩展提供。

## Query Service

数据被存储和索引后，我们需要一种提取数据的方式。Query daemon 提供简单的 JSON API，用于查找和检索追踪。
该 API 的主要消费者是 Web UI。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=sleuth)
