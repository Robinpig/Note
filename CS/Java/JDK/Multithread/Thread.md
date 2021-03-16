# Thread



## Create



| Method             |                               |
| ------------------ | ----------------------------- |
| extends Thread     |                               |
| implement Runnable | could extends another Class   |
| implement Callable | override call() return Future |



## Status

在Java中，线程共有六种状态：

| 状态         | 说明                                                         |
| ------------ | ------------------------------------------------------------ |
| NEW          | 初始状态：线程被创建，但还没有调用start()方法                |
| RUNNABLE     | 运行状态：Java线程将操作系统中的就绪和运行两种状态笼统的称作“运行” |
| BLOCKED      | 阻塞状态：表示线程阻塞于锁                                   |
| WAITING      | 等待状态：表示线程进入等待状态，进入该状态表示当前线程需要等待其他线程做出一些特定动作（通知或中断） |
| TIME_WAITING | 超时等待状态：该状态不同于 WAITIND，它是可以在指定的时间自行返回的 |
| TERMINATED   | 终止状态：表示当前线程已经执行完毕                           |

线程在自身的生命周期中， 并不是固定地处于某个状态，而是随着代码的执行在不同的状态之间进行切换，Java线程状态变化如图示：



<img src="https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/2b137582468744efb04b4523599fe8a0~tplv-k3u1fbpfcp-zoom-1.image" alt="Thread Status" style="zoom:100%;" />





## Method

### Sleep

#### yield 跟 sleep 

1. yield 跟 sleep 都能暂停当前线程，都不会释放锁资源，sleep 可以指定具体休眠的时间，而 yield 则依赖 CPU 的时间片划分。
2. sleep方法给其他线程运行机会时不考虑线程的优先级，因此会给低优先级的线程以运行的机会。yield方法只会给相同优先级或更高优先级的线程以运行的机会。
3. 调用 sleep 方法使线程进入等待状态，等待休眠时间达到，而调用我们的 yield方法，线程会进入就绪状态，也就是sleep需要等待设置的时间后才会进行就绪状态，而yield会立即进入就绪状态。
4. sleep方法声明会抛出 InterruptedException，而 yield 方法没有声明任何异常
5. yield 不能被中断，而 sleep 则可以接受中断。
6. sleep方法比yield方法具有更好的移植性(跟操作系统CPU调度相关)

#### wait 跟 sleep 

1. wait来自Object，sleep 来自 Thread
2. wait 释放锁，sleep 不释放
3. wait 必须在同步代码块中，sleep 可以任意使用
4. wait 不需要捕获异常，sleep 需捕获异常





## Lock

### Dead Lock



产生死锁必须满足四个条件：

1. 互斥条件：该资源任意⼀个时刻只由⼀个线程占⽤。
2. 请求与保持条件：⼀个进程因请求资源⽽阻塞时，对已获得的资源保持不放。
3. 不剥夺条件:线程已获得的资源在末使⽤完之前不能被其他线程强⾏剥夺，只有⾃⼰使⽤完毕后才释放资源。
4. 循环等待条件:若⼲进程之间形成⼀种头尾相接的循环等待资源关系。






### Live Lock



## JMM

