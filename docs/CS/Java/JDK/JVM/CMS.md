## Introduction



Before CMS, Serial, Parallel all STW.

CMS（Concurrent Mark Sweep)收集器是⼀种以获取最短回收停顿时间为⽬标的收集器。

CMS for Old GC, and Young GC still a pause by other collector.

- Init Mark STW
- Concurrent Mark
- Finish Mark STW
- Concurrent Sweep - Does not solve fragmentation





初始标记
并发标记

重新标记：
因为并发标记的过程中可能有引用关系的变化，所以该阶段需要Stop The World。以`GC ROOT`，`Writter Barrier`中记录的对象为根节点，重新遍历。
这里为什么还需要再遍历`GC ROOT`？因为`Writter Barrier`是作用在堆上的，无法感知到`GC ROOT`上引用关系的变更。

并发清除



其中，初始标记、重新标记这两个步骤仍然需要“stop the world”。初始标记仅仅只是标记⼀下GC roots
能够关联到的对象，速度很快。并发标记是进⾏GC roots Tracing过程。重新标记，修正并发标记期间⽤
户程序就⾏运⾏⽽导致标记产⽣变动的那⼀部分对象。
三个缺点：



也是由于在垃圾收集阶段⽤户线程还需要
运⾏，那也就还需要预留有⾜够的内存空间给⽤户线程使⽤，因此CMS收集器不能像其他收集器那样
等到⽼年代⼏乎完全被填满了再进⾏收集，需要预留⼀部分空间提供并发收集时的程序运作使⽤。在
JDK1.5的默认设置下，CMS收集器当⽼年代使⽤了68%的空间后就会被激活，这是⼀个偏保守的设
置，如果在应⽤中⽼年代增⻓不是太快，可以适当调⾼参数-XX：CMSInitiatingOccupancyFraction
的值来提⾼触发百分⽐，以便降低内存回收次数从⽽获取更好的性能，在JDK 1.6中，CMS收集器的启
动阈值已经提升⾄92%。要是CMS运⾏期间预留的内存⽆法满⾜程序需要，就会出现⼀
次“Concurrent Mode Failure”失败，这时虚拟机将启动后备预案：临时启⽤Serial Old收集器来重新
进⾏⽼年代的垃圾收集，这样停顿时间就很⻓了







1.浮动垃圾，在并发标记的过程中（及之后阶段），可能存在原来被引用的对象变成无人引用了，而在这次gc是发现不会清理这些对象的。

2.cpu敏感，因为用户程序是和GC线程同时运行的，所以会导致GC的过程中程序运行变慢，gc运行时间增长，吞吐量降低。默认回收线程是（CPU数量+3）/4，也就是cpu不足4个时，会有一半的cpu资源给GC线程。

3.空间碎片，标记清除算法都有的问题。当碎片过多时，为大对象分配内存空间就会很麻烦，有时候就是老年代空间有大量空间剩余，但没有连续的大空间来分配当前对象，不得不提前触发full gc。CMS提供一个参数（-XX:+UseCMSCompactAtFullCollection），在Full Gc发生时开启内存合并整理。这个过程是STW的。同时还可以通过参数（-XX:CMSFullGCsBeforeCom-paction）来这只执行多少次不压缩的Full GC后，来一次压缩的。

4.需要更大的内存空间，因为是同时运行的GC和用户程序，所以不能像其他老年代收集器一样，等老年代满了再触发GC，而是要预留一定的空间。CMS可以配置当老年代使用率到达某个阈值时（ -XX:CMSInitiatingOccupancyFraction=80 ），开始CMS GC。

在old GC运行的过程中，可能有大量对象从年轻代晋升，而出现老年代存放不下的问题（因为这个时候垃圾还没被回收掉），该问题叫Concurrent Model Failure,这时候会启用Serial Old收集器，重新回收整个老年代。Concurrent Model Failure一般伴随着ParNew promotion failed（晋升担保失败）,解决这个问题的办法就是可以让CMS在进行一定次数的Full GC（标记清除）的时候进行一次标记整理算法，或者降低触发cms gc的阈值
