## Introduction


## Async


This appender buffers events in a BlockingQueue. 
AsyncAppenderBase.Worker thread created by this appender takes events from the head of the queue, 
and dispatches them to the single appender attached to this appender.


[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ArrayBlockingQueue)


```java
public class AsyncAppenderBase<E> extends UnsynchronizedAppenderBase<E> implements AppenderAttachable<E> {

    @Override
    public void start() {
        // ...
        
        blockingQueue = new ArrayBlockingQueue<E>(queueSize);

        if (discardingThreshold == UNDEFINED)
            discardingThreshold = queueSize / 5;
        
        worker.setDaemon(true);
        worker.setName("AsyncAppender-Worker-" + getName());
        
        // make sure this instance is marked as "started" before staring the worker Thread
        super.start();
        worker.start();
    }
}
```

### produce

Discard logs when:
1. remainingCapacity < discardingThreshold(default `queueSize / 5`)
2. and events of level TRACE, DEBUG and INFO

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

put
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





## References
1. [logback manual](http://logback.qos.ch/manual/introduction.html)