## Introduction





文本处理的一些命令

cat | grep



cut -d ',' -f 1

cut -cN-



sort | uniq | wc -l 




bat

```shell
wget  https://github.com/sharkdp/bat/releases/download/v0.24.0/bat_0.24.0_amd64.deb
dpkg -i bat_0.24.0_amd64.deb
```




https://wiki.linuxfoundation.org/start

https://www.infoq.cn/u/peihongchen/publish

https://mp.weixin.qq.com/mp/appmsgalbum?__biz=Mzg2MzU3Mjc3Ng==&action=getalbum&album_id=2559805446807928833&scene=173&from_msgid=&from_itemidx=&count=3&nolastread=1&scene=21#wechat_redirect





https://www.dingmos.com/
https://blogs.oracle.com/linux/category/lnx-linux-kernel-development


https://www.bookstack.cn/read/linux-insides-zh/README.md
https://lyq.blogd.club/2022/08/03/LKD-conclusion-1/
https://elixir.bootlin.com/linux/v6.10.10/source/fs/select.c

https://xie.infoq.cn/article/b063087bd7d6b157613986e71
https://abcdxyzk.github.io/blog/cats/kernel/

http://www.wowotech.net/process_management/448.html
https://www.cnblogs.com/LoyenWang
https://www.bookstack.cn/books/understand_linux_process
https://ixx.life/notes/cross-compile-linux-on-macos/

https://asahilinux.org/fedora/#device-support

https://flyflypeng.tech/%E5%88%A9%E5%99%A8/2022/04/23/vscode%E5%86%85%E6%A0%B8%E6%BA%90%E7%A0%81%E9%98%85%E8%AF%BB%E7%8E%AF%E5%A2%83%E9%85%8D%E7%BD%AE.html






任务的睡眠与唤醒是内核调度器重要的组成部分，下面先简单介绍一下唤醒的流程。

现有任务A想要唤醒睡眠中的任务B。任务A正运行在CPU1上，任务B将会运行在CPU2上（这里1和2可以是同一个CPU）。无论用户态中是什么行为，最终在内核态都会走到try_to_wake_up()这个主入口。它主要干两件事情：
1. 寻找合适的CPU2来让任务B运行
2. 执行唤醒操作

调度器设计了一套复杂的数据结构去维护所有任务，其中最主要的数据是每个CPU的运行队列（即runqueue，下文缩写rq）。该队列记录了对应CPU上的就绪任务的情况。因此，常规的第二件事展开来说就是：
1.
获取CPU2的rq锁
2.
将任务B加入CPU2的rq
3.
如果任务B可以立即运行（满足抢占条件），则通知CPU2重新调度
这种方式是在CPU1上去拿CPU2的锁并操作CPU2的数据，要注意第二步并不只是单纯的入队操作，还伴有许多统计数据的维护操作。从性能和缓存的角度来看，似乎有那么点微妙。

既然有常规的方式，那当然还有特殊的方式，这种方式也就是本文的主角wakelist（CPU1和CPU2不相同时）：
1.
将任务B加入CPU2的特殊链表(wakelist)上
2.
通知CPU2
3.
自己收工，剩下的事（指常规方式的那些事）都丢给CPU2做

乍一看，通常情况下，似乎wakelist这种方式更好啊，让CPU2自己拿自己的锁，处理自己的数据，似乎对性能和缓存更友好。这样CPU1还可以提前结束工作，继续去处理后面的事。不过，这里的第二步是无条件通知的，如果是整个机器都比较繁忙的场景，CPU2正在运行其他任务，频繁被打断就不太好了。在引入wakelist唤醒方式之后，很快遇到了性能问题。内核大佬分析认为这是因为第二步的无条件通知产生的IPI太多了，因此用这个补丁将wakelist限制为只有CPU1和CPU2不共享llc时才使用，从而减少IPI的数量，同时保持数据不要在llc级别的缓存之间反复横跳。

历史演进
通知方式：IPI与idle polling
在后续介绍发展过程之前，需要先补充一些背景知识。在内核唤醒流程中，CPU1想要通知CPU2，一般是通过IPI(Inter-Processor Interrupt)进行的。但是有一个例外情况是，如果CPU2处于idle的状态，但它又没有彻底idle而是处于polling中（例如启动命令设置了idle=poll，或是halt-polling中的polling阶段，还有intel的mwait等），他就会监控一块特定的内存区域(thread flag中的TIF_NEED_RESCHED)，如果该flag被设置了，则退出idle状态并根据自己的特殊链表开始工作。这样就避免了发送IPI。
wakelist方式也采用idle polling
在上文我们说到wakelist方式很快因为性能问题被阉割了（只允许跨llc使用），原因是其中第二步的无条件通知会无脑直接发送IPI。因此，这个补丁对wakelist的通知方式做出了优化，当CPU2处于idle polling状态时，可避免IPI的发送。
注：idle polling这个机制更早之前就存在了，不过早期只应用在常规唤醒的第三步：如果任务B可以立即运行（满足抢占条件），则通知CPU2重新调度。这里如果CPU2是idle的，就会通过idle polling机制通知。而wakelist方式一开始并没有使用idle polling，是后来加上的。
扩展wakelist使用场景
这个补丁+这个补丁合起来对一个比较极端的繁忙场景做了个优化：如果任务B刚刚睡下去，还在睡眠操作的一半呢，任务A就想把他叫起来了。那原本任务A所在的CPU1需要等到任务B所在的CPU2把睡眠操作执行完，才能执行唤醒操作，这显然会浪费等待的时间。所以CPU1就可以通过wakelist的方式通知CPU2，自己收工干别的去了。在这个场景下，wakelist的使用条件被放宽到了“任务B正在CPU2上准备睡下去，并且CPU2上没有别的任务”，而不考虑llc了。
我们的进一步优化
通过上面的历史演进，我们可以发现，当wakelist开始支持idle polling的那一刻起，其实条件就可以被放得很宽了。并不需要什么“任务B正准备睡下去”之类的条件，只需要“CPU2处于idle状态”这一条就可以了。条件放宽后，有频繁唤醒的场景的业务都可能获得性能提升。我们测试的一些调度唤醒的benchmark能有约10%左右的收益，更具体的信息可以看补丁内容。
以下分析可以说明这项改动没有副作用：
如果CPU2处于busy，那还是走原来的老路，跟我们的优化无关；
如果CPU2处于idle且polling：
优化前：检查任务B能否立即运行在CPU2上（满足抢占条件），发现它可以（任务必定优先于idle），走idle polling方式通知，不产生IPI
优化后：直接走wakelist方式，因为CPU2正在idle polling，也不产生IPI
如果CPU2处于彻底的idle：
优化前：检查任务B能否立即运行在CPU2上（满足抢占条件），发现它可以（任务必定优先于idle），给CPU2发送IPI
优化后：直接走wakelist方式，给CPU2发送IPI
发送IPI的状况并没有变化，因此没有引入副作用。
本优化已进入上游Linux6.0主线，并backport至5.15、5.18、5.19的stable内核中。龙蜥5.10内核也有等价的自研实现。
有收益的场景
该优化主要适用于唤醒十分频繁，且整体负载不太大的业务场景。例如，我们分析的目标电商业务每秒在16个cpu上总共唤醒约10万次，平均每个cpu每160us就发生一次唤醒。这种场景下测试出来的响应时间缩短了约7%。
另外，因为本优化设定的条件是CPU2需要处于idle，所以一直占着CPU的压力很大的业务就不会有收益了，毕竟每次唤醒都需要至少找到一个空闲着的CPU。
https://www.kernel.org/doc/html/v4.18/dev-tools/kgdb.html

https://docs.kernel.org/dev-tools/kgdb.html#







## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)