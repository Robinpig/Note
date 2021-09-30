# GC
Garbage Collection 

## When an instance is dead？ 
#### 引用计数算法：

   为对象添加一个引用计数器，当对象增加一个引用时计数器加 1，
        引用失效时计数器减 1。引用计数为 0 的对象可被回收，
        但存在循环引用而无法回收问题，已不再适用。



#### 可达性分析算法：

  以 GC Roots 为起始点进行搜索，可达的对象都是存活的，不可达的对象可被回收。
  Java 虚拟机使用该算法来判断对象是否可被回收，GC Roots 一般包含以下内容：



**GC Roots:**

  - 虚拟机栈中局部变量表中引用的对象
  - 本地方法栈中 JNI 中引用的对象 包括global handles和local handles
  - 方法区中类静态属性引用的对象
  - 方法区中的常量引用的对象
  - 所有当前被加载的Java类
  - JVM内部数据结构的一些引用，比如`sun.jvm.hotspot.memory.Universe`类
  - 用于同步的监控对象，比如调用了对象的`wait()`方法



### Recycle

Copying

Mark-Sweep

Mark-Compact

分代

interceptor and JIT use Write Barrier to maintain Card Table

Premature Promotion

Promotion Failure

[Reference](/docs/CS/Java/JDK/Basic/Ref.md)


gcCause.cpp




### Young GC 问题

####  YGC耗时异常 

- toot对象扫描+标记时间过长                
- 存活对象copy耗时较大                
- 等待各线程到达安全点时间较长                
- GC日志对GC时间的影响                
- 操作系统活动影响（内存swap等）                

### Full GC 问题

 FGC频次异常 

- 老年代空间不足                
- 内存碎片化                
- 永久代/元空间 空间不足                
- 对象预估和担保                
- 堆大小动态调整          



![img](https://user-gold-cdn.xitu.io/2020/6/30/1730111bfa01fba7?imageView2/0/w/1280/h/960/format/webp/ignore-error/1)







![GC Collector](../images/GC-collector.png)



## Collector

### epsilon

### serial


### parallel

- GCTimeRatio                               = 99
- MaxGCPauseMillis                          = 18446744073709551615


- UseParallelGC                            := true
- UseParallelOldGC                          = true
- UseAdaptiveGCBoundary                     = false

### Concurrent
The mostly concurrent collector trades processor resources (which would otherwise be available to the application) for shorter major collection pause times. The most visible overhead is the use of one or more processors during the concurrent parts of the collection. On an N processor system, the concurrent part of the collection will use K/N of the available processors, where 1<=K<=ceiling{N/4}. (Note that the precise choice of and bounds on K are subject to change.) In addition to the use of processors during concurrent phases, additional overhead is incurred to enable concurrency. Thus while garbage collection pauses are typically much shorter with the concurrent collector, application throughput also tends to be slightly lower than with the other collectors.

On a machine with more than one processing core, processors are available for application threads during the concurrent part of the collection, so the concurrent garbage collector thread does not "pause" the application. This usually results in shorter pauses, but again fewer processor resources are available to the application and some slowdown should be expected, especially if the application uses all of the processing cores maximally. As N increases, the reduction in processor resources due to concurrent garbage collection becomes smaller, and the benefit from concurrent collection increases. The section Concurrent Mode Failure in Concurrent Mark Sweep (CMS) Collector discusses potential limits to such scaling.

Because at least one processor is used for garbage collection during the concurrent phases, the concurrent collectors do not normally provide any benefit on a uniprocessor (single-core) machine. However, there is a separate mode available for CMS (not G1) that can achieve low pauses on systems with only one or two processors; see Incremental Mode in Concurrent Mark Sweep (CMS) Collector for details. This feature is being deprecated in Java SE 8 and may be removed in a later major release.

### cms

### g1

### shenandoah

### z

### 










## References
1. [Unnecessary GCLocker-initiated young GCs](https://bugs.openjdk.java.net/browse/JDK-8048556)
2. [Exploiting the Weak Generational Hypothesis for Write Reduction and Object Recycling](https://openscholarship.wustl.edu/eng_etds/169/)
3. [Java Platform, Standard Edition HotSpot Virtual Machine Garbage Collection Tuning Guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/toc.html)