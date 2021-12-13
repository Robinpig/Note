
## Introduction


Schedulers provides various Scheduler flavors usable by publishOn or subscribeOn :

- parallel(): Optimized for fast Runnable non-blocking executions
- single: Optimized for low-latency Runnable one-off executions
- elastic(): Optimized for longer executions, an alternative for blocking tasks where the number of active tasks (and threads) can grow indefinitely
- boundedElastic(): Optimized for longer executions, an alternative for blocking tasks where the number of active tasks (and threads) is capped
- immediate: to immediately run submitted Runnable instead of scheduling them (somewhat of a no-op or "null object" Scheduler)
- fromExecutorService(ExecutorService) to create new instances around java.util.concurrent.Executors

Factories prefixed with new (eg. newBoundedElastic(int, int, String) return a new instance of their flavor of Scheduler, while other factories like boundedElastic() return a shared instance - which is the one used by operators requiring that flavor as their default Scheduler. All instances are returned in a started state.


Scheduler that dynamically creates a bounded number of ExecutorService-based Workers, reusing them once the Workers have been shut down. 
The underlying daemon threads can be evicted if idle for more than 60 seconds.
```java
package reactor.core.scheduler;

public abstract class Schedulers {
    public static Scheduler boundedElastic() {
        return cache(CACHED_BOUNDED_ELASTIC, BOUNDED_ELASTIC, BOUNDED_ELASTIC_SUPPLIER);
    }
}
```