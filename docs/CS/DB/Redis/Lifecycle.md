

- [start](/docs/CS/DB/Redis/start.md?id=main)
- [exec](/docs/CS/DB/Redis/start.md?id=do)


serverCron是干嘛的
redis内部有定期执行的函数servercron，它默认每隔100ms执行一次，它的作用主要是以下：

「更新服务器时间缓存」：redis有不少功能需要获取当前时间，每次获取时间的话要进行一次系统调用，对于一些对时间实时性要求不是很高的场景，redis通过缓存来减少系统调用的次数。实时性要求不高的主要有：打印日志、更新服务器的LRU时钟、决定是否执行持久化任务、计算服务器上线时间。对于设置设置过期时间、添加慢查询日志还是会系统调用获取实时时间的。
「更新LRU时钟」：redis中有个lruclock属性用于保存服务器的lru时钟，每个对象也有一个lru时钟，通过服务器的lru减去对象的lru，可以得出对象的空转时间，serverCron默认会以每10s一次更新一次lruclock，所以这也是一个模糊值。
「更新每秒执行的次数」：这是一个估算值，每次执行的时候，会根据上一次抽样时间和服务器的当前时间，以及上一次抽样的已执行命令数量和服务器当前的已执行命令数量，计算出两次调用之间，服务器平均每毫秒处理了多少个命令请求，然后将这个平均值乘以1000，这就得到了服务器在一秒钟内能处理多少个命令请求的估计值。
INFO stats
...
instantaneous_ops_per_sec:1
「更新内存峰值」：每次执行的时候会查看当前内存使用量，然后和上一次的峰值对比，判断是否需要更新峰值。
INFO stats
...
used_memory_peak:2026832
used_memory_peak_human:1.93M
「处理SIGTERM信号」：收到SIGTERM信号的时候，redis会打个标识，然后等待serverCron到来的时候，根据标识状态处理一些在shutdown之前的工作，比如持久化。
「处理客户端资源」：如果客户端和服务之间很长时间没通信了，那么就会释放这个客户端。如果输入缓冲区的大小超过了一定长度，那么就会释放当前客户端的输入缓冲区，然后重建一个默认大小的输入缓冲区，防止输入缓冲区占用较大的内存。同时也会关闭输出缓冲区超过限制的客户端。
「延迟执行aof重写」：在服务器执行BGSAVE的时候，如果BGREWRITEAOF也到来了，那么BGREWRITEAOF会被延迟到BGSAVE执行完毕之后，这时会记个标记aof_rewrite_scheduled，每次serverCron执行的时候会检查当前是否有BGSAVE或BGREWRITEAOF在执行，如果没有且aof_rewrite_scheduled已标记，那么就会执行BGREWRITEAOF。
「持久化」：serverCron每次执行的时候，会判断当前是否在进行持久化，如果没有的话，会判断aof重写是否被延迟，延迟的话，执行aof重写，没有的话，会检查rdb条件是否满足，满足的话执行rdb持久化，否则判断aof重写条件是否满足，满足的话执行aof重写。在开启aof的时候，会根据设置看需不需要把aof缓冲区的数据写入到aof文件中。
「记录执行次数」：serverCron每次执行的时候，都会记录下执行的次数。

如何解决redis脑裂问题
Image
「什么是脑裂问题」：在redis集群中，如果存在两个master节点就是脑裂问题，这时候客户端连着哪个master，就往哪个master上写数据，导致数据不一致。
「脑裂问题是如何产生的」：一般可能是由于master所处的网络发生了问题，导致master和其余的slave无法正常通信，但是master和客户端的通信是ok的，这时哨兵会从剩下的slave中选举一个master，当原master网络恢复后，就会被降级成slave。
「脑裂产生的影响」：在原master失联的期间，和它通信的client会把变更记录在原master中，当原master网络恢复并成为新master的slave的时候，它会清空自己的数据，同步新master的数据。那么在网络失联的期间，往原master写入数据都是丢失的。
「如何解决」：主要通过两个配置参数来解决：

min-slaves-to-write 1
min-slaves-max-lag 10
「min-slaves-to-write」：这个配置项设置了主库能进行数据同步的最少从库数量；
「min-slaves-max-lag」：这个配置项设置了主从库间进行数据复制时，从库给主库发送 ACK 消息的最大延迟（以秒为单位）。
如果两个配置都不满足的话，那么master就拒绝客户端的请求，通过以上配置可以将丢失的数据控制在10s内。

