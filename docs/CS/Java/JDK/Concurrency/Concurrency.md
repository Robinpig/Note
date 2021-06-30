# Concurrency


### Basic

#### Memory Model

monitor

线程各自的本地内存对其它线程是不可见的；多个线程写入主存时可能会存在脏数据；指令重排导致结果不可控。
多线程交互需要解决上述三个问题，这三个问题也是线程并发的核心：

> 1、可见性
> 2、原子性
> 3、有序性

同步是在互斥的基础上增加了等待-通知机制，实现了对互斥资源的有序访问，因此同步本身已经实现了互斥。

> 同步是种复杂的互斥
> 互斥是种特殊的同步



#### CAS

#### valatile

#### synchronized



#### Thread

Thread

ThreadLocal

### atomic



### Collections

1. fail-fast for Collections in `java.util`, such as `HashMap`, `ArrayList`
2. fail-safe for Collections in `java.util.concurrent`, such as `ConcurrentHashMap`, `CopyOnWriteArrayList`

#### Blocking Queue





### locks

![locks](../images/juc-locks.png)



### synchronizer

![img](https://upload-images.jianshu.io/upload_images/19073098-ad30778587f3b754.png?imageMogr2/auto-orient/strip|imageView2/2/w/1200)



### Executor

#### Future

#### ThreadPoolExecutor

