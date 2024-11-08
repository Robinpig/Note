## Introduction


在Linux上直接查看Page Cache的方式有很多，包括/proc/meminfo、free 、/proc/vmstat命令等，它们的内容其实是一致的
> [free](https://gitlab.com/procps-ng/procps/-/blob/master/src/free.c) 是读取了/proc/meminfo

这些内容都是page cache
```
Buffers + Cached + SwapCached = Active(file) + Inactive(file) + Shmem + SwapCached
```

在Page Cache中，Active(file)+Inactive(file)是File-backed page（与文件对应的内存页），是你最需要关注的部分。因为你平时用的mmap()内存映射方式和buffered I/O来消耗的内存就属于这部分，最重要的是，这部分在真实的生产环境上也最容易产生问题
SwapCached是在打开了Swap分区后，把Inactive(anon)+Active(anon)这两项里的匿名页给交换到磁盘（swap out），然后再读入到内存（swap in）后分配的内存。由于读入到内存后原来的Swap File还在，所以SwapCached也可以认为是File-backed page，即属于Page Cache。这样做的目的也是为了减少I/O
SwapCached只在Swap分区打开的情况下才会有，而我建议你在生产环境中关闭Swap分区，因为Swap过程产生的I/O会很容易引起性能抖动。

> Shmem是指匿名共享映射这种方式分配的内存（free命令中shared这一项），比如tmpfs（临时文件系统），这部分在真实的生产环境中产生的问题比较少

Page Cache的产生有两种不同的方式：
- Buffered I/O（标准I/O）标准I/O是写的(write(2))用户缓冲区(Userpace Page对应的内存)，然后再将用户缓冲区里的数据拷贝到内核缓冲区(Pagecache Page对应的内存)；如果是读的(read(2))话则是先从内核缓冲区拷贝到用户缓冲区，再从用户缓冲区读数据，也就是buffer和文件内容不存在任何映射关系
- Memory-Mapped I/O（存储映射I/O）。对于存储映射I/O而言，则是直接将Pagecache Page给映射到用户地址空间，用户直接读写Pagecache Page中内容

显然，存储映射I/O要比标准I/O效率高一些，毕竟少了“用户空间到内核空间互相拷贝”的过程

查看dirty page统计
```shell
cat /proc/vmstat | egrep "dirty|writeback"
```


当内存水位低于watermark low时，就会唤醒kswapd进行后台回收，然后kswapd会一直回收到watermark high。
那么，我们可以增大min_free_kbytes这个配置选项来及早地触发后台回收
vm.min_free_kbytes = 4194304
对于大于等于128G的系统而言，将min_free_kbytes设置为4G比较合理，这是我们在处理很多这种问题时总结出来的一个经验值，既不造成较多的内存浪费，又能避免掉绝大多数的直接内存回收。
该值的设置和总的物理内存并没有一个严格对应的关系，我们在前面也说过，如果配置不当会引起一些副作用，所以在调整该值之前，我的建议是：你可以渐进式地增大该值，比如先调整为1G，观察sar -B中pgscand是否还有不为0的情况；如果存在不为0的情况，继续增加到2G，再次观察是否还有不为0的情况来决定是否增大，以此类推。
这样做也有一些缺陷：提高了内存水位后，应用程序可以直接使用的内存量就会减少，这在一定程度上浪费了内存。所以在调整这一项之前，你需要先思考一下，应用程序更加关注什么，如果关注延迟那就适当地增大该值，如果关注内存的使用量那就适当地调小该值。

通过调整内存水位，在一定程度上保障了应用的内存申请，但是同时也带来了一定的内存浪费，因为系统始终要保障有这么多的free内存，这就压缩了Page Cache的空间。调整的效果你可以通过/proc/zoneinfo来观察：

```shell
egrep "min|low|high" /proc/zoneinfo
```


## Links

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)