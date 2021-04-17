#  SafePoint

Main thread will print the num util sub thread ends, not after 1000ms we expected.

```java
public static AtomicInteger num = new AtomicInteger(0);

public static void main(String[] args) throws Throwable {
    Runnable runnable = () -> {
        for (int i = 0; i < 1000000000; i++) {
            num.getAndAdd(1);
        }
    };

    Thread t1 = new Thread(runnable);
    Thread t2 = new Thread(runnable);
    t1.start();
    t2.start();

    System.out.println("before sleep");
    Thread.sleep(1000);
    System.out.println("after sleep");

    System.out.println(num);
}
```



## PrintStatistics

```
-XX:+PrintSafepointStatistics  -XX:PrintSafepointStatisticsCount=1
```

> Task :MainTest.main()
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 1.016: no vm operation                  [      11          2              2    ]      [ 29399     0 29399     0     0    ]  0   
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 30.416: EnableBiasedLocking              [      11          0              0    ]      [     0     0     0     0     0    ]  0   
> num = 2000000000
>     vmop                    [threads: total initially_running wait_to_block]    [time: spin block sync cleanup vmop] page_trap_count
> 30.416: no vm operation                  [       8          1              1    ]      [     0     0     0     0     0    ]  0 >  
> Polling page always armed
> EnableBiasedLocking                1
>     0 VM operations coalesced during safepoint
> Maximum sync time  29399 ms
> Maximum vm operation time (except for Exit VM operation)      0 ms





## Fix



```
 -XX:+UnlockDiagnosticVMOptions  -XX:GuaranteedSafepointInterval=2000 
```
 *-XX:GuaranteedSafepointInterval=2000* option set safepoint after thread sleep ends.

```
-XX:+UseCountedLoopSafepoints
```

`-XX:+UseCountedLoopSafepoints` option turns off the optimization that eliminates safepoint polling.

Other methods

- Use JDK10 and later
- Use long to limit a countedLoop





## Reference

1. [真是绝了！这段被JVM动了手脚的代码！](https://mp.weixin.qq.com/s/KDUccdLALWdjNBrFjVR74Q)
2. [StackOverFlow](https://stackoverflow.com/questions/67068057/the-main-thread-exceeds-the-set-sleep-time)

