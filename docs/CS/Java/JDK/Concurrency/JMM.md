


Java Memory Model



Atomic

Orderable

Shareable

### Orderable

compiler
CPU
Memory


## happen-before

>- 程序顺序规则：一个线程中的每个操作，happens-before于该线程中的任意后续操作。
>- 监视器锁规则：对一个锁的解锁，happens-before于随后对这个锁的加锁。
>- volatile变量规则：对一个volatile域的写，happens-before于任意后续对这个volatile域的读。
>- 传递性：如果A happens-before B，且B happens-before C，那么A happens-before C。
>- start()规则：如果线程A执行操作ThreadB.start()（启动线程B），那么A线程的ThreadB.start()操作happens-before于线程B中的任意操作。
>- join()规则：如果线程A执行操作ThreadB.join()并成功返回，那么线程B中的任意操作happens-before于线程A从ThreadB.join()操作成功返回。
>- 线程中断规则:对线程interrupt方法的调用happens-before于被中断线程的代码检测到中断事件的发生。



snooping



### MESI



Modified（已修改）, Exclusive（独占的）,Shared（共享的），Invalid（无效的）

总线风暴

总线嗅探技术有哪些缺点？

由于MESI缓存一致性协议，需要不断对主线进行内存嗅探，大量的交互会导致总线带宽达到峰值。

### Memory Barries



## Reference

1.[为什么需要内存屏障 - zhihu](https://zhuanlan.zhihu.com/p/55767485)