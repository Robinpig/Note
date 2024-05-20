## Introduction


## Async


This appender buffers events in a BlockingQueue. 
AsyncAppenderBase.Worker thread created by this appender takes events from the head of the queue, 
and dispatches them to the single appender attached to this appender.


[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ArrayBlockingQueue)


```java
public class AsyncAppenderBase<E> extends UnsynchronizedAppenderBase<E> implements AppenderAttachable<E> {
    public static final int DEFAULT_QUEUE_SIZE = 256;

    @Override
    public void start() {
        // ...
        blockingQueue = new ArrayBlockingQueue<E>(queueSize);
        if (discardingThreshold == UNDEFINED)
            discardingThreshold = queueSize / 5;
        
        worker.setDaemon(true);
        worker.setName("AsyncAppender-Worker-" + getName());
        super.start();
        worker.start();
    }
}
```


Discard TRACE, DEBUG and INFO logs when remainingCapacity < discardingThreshold(default `queueSize / 5`)

```java
public class AsyncAppenderBase<E> extends UnsynchronizedAppenderBase<E> implements AppenderAttachable<E> {
    @Override
    protected void append(E eventObject) {
        if (isQueueBelowDiscardingThreshold() && isDiscardable(eventObject)) {
            return;
        }
        preprocess(eventObject);
        put(eventObject);
    }


    private boolean isQueueBelowDiscardingThreshold() {
        return (blockingQueue.remainingCapacity() < discardingThreshold);
    }

    protected boolean isDiscardable(ILoggingEvent event) {
        Level level = event.getLevel();
        return level.toInt() <= Level.INFO_INT;
    }

}
```

Default block if queue is full
```java
private void put(E eventObject) {
    if (neverBlock) {
        // discard if queue is full
        blockingQueue.offer(eventObject);
    } else {
        // cach interrupt and blocking put until enqueue successfully in while loop
        putUninterruptibly(eventObject); 
    }
}

private void putUninterruptibly(E eventObject) {
    boolean interrupted = false;
    try {
        while (true) {
            try {
                blockingQueue.put(eventObject);
                break;
            } catch (InterruptedException e) {
                interrupted = true;
            }
        }
    } finally {
        if (interrupted) {
            Thread.currentThread().interrupt();
        }
    }
}
```

### consume
```java
class Worker extends Thread {

    public void run() {
        AsyncAppenderBase<E> parent = AsyncAppenderBase.this;
        AppenderAttachableImpl<E> aai = parent.aai;

        // loop while the parent is started
        while (parent.isStarted()) {
            try {
                E e = parent.blockingQueue.take();
                aai.appendLoopOnAppenders(e);
            } catch (InterruptedException ie) {
                break;
            }
        }

        addInfo("Worker thread will flush remaining events before exiting. ");

        for (E e : parent.blockingQueue) {
            aai.appendLoopOnAppenders(e);
            parent.blockingQueue.remove(e);
        }

        aai.detachAndStopAllAppenders();
    }
}
```

## Links

- [Log](/docs/CS/log/Log.md)
- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)



## References
1. [logback manual](http://logback.qos.ch/manual/introduction.html)