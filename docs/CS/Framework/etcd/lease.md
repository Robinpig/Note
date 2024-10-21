## Introduction

Lease顾名思义，client和etcd server之间存在一个约定，内容是etcd server保证在约定的有效期内（TTL），不会删除你关联到此Lease上的key-value。

etcd在启动的时候，创建Lessor模块的时候，它会启动两个常驻goroutine，如上图所示，一个是RevokeExpiredLease任务，定时检查是否有过期Lease，发起撤销过期的Lease操作。一个是CheckpointScheduledLease，定时触发更新Lease的剩余到期时间的操作。
Lessor模块提供了Grant、Revoke、LeaseTimeToLive、LeaseKeepAlive API给client使用，各接口作用如下:
● Grant表示创建一个TTL为你指定秒数的Lease，Lessor会将Lease信息持久化存储在boltdb中；
● Revoke表示撤销Lease并删除其关联的数据；
● LeaseTimeToLive表示获取一个Lease的有效期、剩余时间；
● LeaseKeepAlive表示为Lease续期。

# 创建一个TTL为600秒的lease，etcd server返回LeaseID 
$ etcdctl lease grant 600
 # 查看lease的TTL、剩余时间 
$ etcdctl lease timetolive 326975935f48f814

当Lease server收到client的创建一个有效期600秒的Lease请求后，会通过Raft模块完成日志同步，随后Apply模块通过Lessor模块的Grant接口执行日志条目内容。
首先Lessor的Grant接口会把Lease保存到内存的ItemMap数据结构中，然后它需要持久化Lease，将Lease数据保存到boltdb的Lease bucket中，返回一个唯一的LeaseID给client。
通过这样一个流程，就基本完成了Lease的创建

KV模块的API接口提供了一个"–lease"参数，你可以通过如下命令，将key node关联到对应的LeaseID上。然后你查询的时候增加-w参数输出格式为json，就可查看到key关联的LeaseID
过put等命令新增一个指定了"–lease"的key时，MVCC模块它会通过Lessor模块的Attach方法，将key关联到Lease的key内存集合ItemSet中。
renew
为了防止Lease被淘汰，你需要定期发送LeaseKeepAlive请求给etcd server续期Lease，本质是更新Lease的到期时间

expire

淘汰过期Lease的工作由Lessor模块的一个异步goroutine负责。如下面架构图虚线框所示，它会定时从最小堆中取出已过期的Lease，执行删除Lease和其关联的key列表数据的RevokeExpiredLease任务

目前etcd是基于最小堆来管理Lease，实现快速淘汰过期的Lease。
etcd早期的时候，淘汰Lease非常暴力。etcd会直接遍历所有Lease，逐个检查Lease是否过期，过期则从Lease关联的key集合中，取出key列表，删除它们，时间复杂度是O(N)。
然而这种方案随着Lease数增大，毫无疑问它的性能会变得越来越差。我们能否按过期时间排序呢？这样每次只需轮询、检查排在前面的Lease过期时间，一旦轮询到未过期的Lease， 则可结束本轮检查。
刚刚说的就是etcd Lease高效淘汰方案最小堆的实现方法。每次新增Lease、续期的时候，它会插入、更新一个对象到最小堆中，对象含有LeaseID和其到期时间unixnano，对象之间按到期时间升序排序。
etcd Lessor主循环每隔500ms执行一次撤销Lease检查（RevokeExpiredLease），每次轮询堆顶的元素，若已过期则加入到待淘汰列表，直到堆顶的Lease过期时间大于当前，则结束本轮轮询。
相比早期O(N)的遍历时间复杂度，使用堆后，插入、更新、删除，它的时间复杂度是O(Log N)，查询堆顶对象是否过期时间复杂度仅为O(1)，性能大大提升，可支撑大规模场景下Lease的高效淘汰

检查Lease是否过期、维护最小堆、针对过期的Lease发起revoke操作，都是Leader节点负责的，它类似于Lease的仲裁者，通过以上清晰的权责划分，降低了Lease特性的实现复杂度。
那么当Leader因重启、crash、磁盘IO等异常不可用时，Follower节点就会发起Leader选举，新Leader要完成以上职责，必须重建Lease过期最小堆等管理数据结构

当你的集群发生Leader切换后，新的Leader基于Lease map信息，按Lease过期时间构建一个最小堆时，etcd早期版本为了优化性能，并未持久化存储Lease剩余TTL信息，因此重建的时候就会自动给所有Lease自动续期了。
然而若较频繁出现Leader切换，切换时间小于Lease的TTL，这会导致Lease永远无法删除，大量key堆积，db大小超过配额等异常
为了解决这个问题，etcd引入了检查点机制，也就是CheckPointScheduledLeases任务
一方面，etcd启动的时候，Leader节点后台会运行此异步任务，定期批量地将Lease剩余的TTL基于Raft Log同步给Follower节点，Follower节点收到CheckPoint请求后，更新内存数据结构LeaseMap的剩余TTL信息。
另一方面，当Leader节点收到KeepAlive请求的时候，它也会通过checkpoint机制把此Lease的剩余TTL重置，并同步给Follower节点，尽量确保续期后集群各个节点的Lease 剩余TTL一致性



## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References
 

