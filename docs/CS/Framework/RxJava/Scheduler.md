




```java
package io.reactivex.schedulers;

public final class Schedulers {
    @NonNull
    static final Scheduler SINGLE = RxJavaPlugins.initSingleScheduler(new Schedulers.SingleTask());
    @NonNull
    static final Scheduler COMPUTATION = RxJavaPlugins.initComputationScheduler(new Schedulers.ComputationTask());
    @NonNull
    static final Scheduler IO = RxJavaPlugins.initIoScheduler(new Schedulers.IOTask());
    @NonNull
    static final Scheduler TRAMPOLINE = TrampolineScheduler.instance();
    @NonNull
    static final Scheduler NEW_THREAD = RxJavaPlugins.initNewThreadScheduler(new Schedulers.NewThreadTask());


    static {
        SINGLE = RxJavaPlugins.initSingleScheduler(new SingleTask());

        COMPUTATION = RxJavaPlugins.initComputationScheduler(new ComputationTask());

        IO = RxJavaPlugins.initIoScheduler(new IOTask());

        TRAMPOLINE = TrampolineScheduler.instance();

        NEW_THREAD = RxJavaPlugins.initNewThreadScheduler(new NewThreadTask());
    }
}
```