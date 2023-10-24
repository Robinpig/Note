## Introduction

[Zipkin](https://zipkin.io/) is a distributed tracing system.
It helps gather timing data needed to troubleshoot latency problems in service architectures.
Features include both the collection and lookup of this data.



### Architecture

Tracers live in your applications and record timing and metadata about operations that took place. 
They often instrument libraries, so that their use is transparent to users. 
The trace data collected is called a Span.

Instrumentation is written to be safe in production and have little overhead. 
For this reason, they only propagate IDs in-band, to tell the receiver there’s a trace in progress.
Trace instrumentation report spans asynchronously to prevent delays or failures relating to the tracing system from delaying or breaking user code.

Here’s a diagram describing this flow from Zipkin homepage:



<div style="text-align: center;">

![Fig.1. Architecture](https://zipkin.io/public/img/architecture-1.png)

</div>

<p style="text-align: center;">
Fig.1. Architecture
</p>




## Transport

Spans sent by the instrumented library must be transported from the services being traced to Zipkin collectors.
There are three primary transports: HTTP, Kafka and Scribe.

### Reporter

The component in an instrumented app that sends data to Zipkin is called a Reporter.
Reporters send trace data via one of several transports to Zipkin collectors, which persist trace data to storage.

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
        metrics.updateQueuedBytes(pending.sizeInBytes);

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

## Collector
Once the trace data arrives at the Zipkin collector daemon, it is validated, stored, and indexed for lookups by the Zipkin collector.


## Storage

Zipkin was initially built to store data on Cassandra since Cassandra is scalable, has a flexible schema, and is heavily used within Twitter.
However, we made this component pluggable. In addition to Cassandra, we natively support ElasticSearch and MySQL. 
Other back-ends might be offered as third party extensions.

## Query Service

Once the data is stored and indexed, we need a way to extract it. The query daemon provides a simple JSON API for finding and retrieving traces.
The primary consumer of this API is the Web UI.


## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md?id=sleuth)
