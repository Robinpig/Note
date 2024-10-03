## Introduction



etcd v2 是一个内存数据库，整个数据库拥有一个`Stop-the-World`的大锁，通过锁机制来解决并发带来的数据竞争。

但是存在**并发性能问题**：

- 1）锁的粒度不好控制，每次都会锁整个数据库
- 2）写锁和读锁相互阻塞。
- 3）前面的事务会阻塞后面的事务，对并发性能影响很大。

同时在高并发环境下还存在另一个严重的问题：

- **watch 机制可靠性问题**：etcd 中的 watch 机制会依赖旧数据，v2 版本基于滑动窗口实现的 watch 机制，只能保留最近的 1000 条历史事件版本，当 etcd server 写请求较多、网络波动时等场景，很容易出现事件丢失问题，进而又触发 client 数据全量拉取，产生大量 expensive request，甚至导致 etcd 雪崩。



etcd v3 为什么要选择 MVCC

多版本并发控制 (Multiversion concurrency control) 模块是为了解决etcd v2 不支持保存 key 的历史版本、不支持多 key 事务等问题而产生的
它核心由内存树形索引模块 (treeIndex) 和嵌入式的 KV 持久化存储库 boltdb 组成。



etcd本质上是内存数据库，所有的数据都是加载到了内存中，当然，它跟redis一样，数据都是持久化了的，只是在启动的时候，将文件数据重新全部加载到内存中



重建内存索引btree的时候，遍历boltdb，从版本号0到最大版本号不断遍历，从value里面解析出对应的key、revision等信息，重建btree



当etcd收到一个请求Get Key时，请求被层层传递到了mvcc层后，它首先需要从内存索引btree中查找key对应的版本号，随后从boltdb里面根据版本号查出对应的value, 然后返回给client



当你执行 put 命令后，请求经过 gRPC KV Server、Raft 模块流转，对应的日志条目被提交后，Apply 模块开始执行此日志内容



**MVCC 模块**将请求请划分成两个类别，分别是读事务（ReadTxn）和写事务（WriteTxn）。读事务负责处理 range 请求，写事务负责 put/delete 操作。读写事务基于 treeIndex、Backend/boltdb 提供的能力，实现对 key-value 的增删改查功能。

**treeIndex 模块**基于内存版 B-tree 实现了 key 索引管理，它保存了用户 key 与版本号（revision）的映射关系等信息。

**Backend 模块**负责 etcd 的 key-value 持久化存储，主要由 ReadTx、BatchTx、Buffer 组成，ReadTx 定义了抽象的读事务接口，BatchTx 在 ReadTx 之上定义了抽象的写事务接口，Buffer 是数据缓存区



**treeIndex 模块正是为了解决这个问题**，支持保存 key 的历史版本，提供稳定的 Watch 机制和事务隔离等能力。

etcd 在每次修改 key 时会生成一个全局递增的版本号（revision）。

- 然后通过数据结构 B-tree 保存用户 key 与版本号之间的关系；
- 再以版本号作为 boltdb key，以用户的 key-value 等信息作为 boltdb value，保存到 boltdb





## put

一个 put 命令流程如下图所示：

1. 首先它需要从 treeIndex 模块中查询 key 的 keyIndex 索引信息
2. 其次 etcd 会根据当前的全局版本号（空集群启动时默认为 1）自增，生成 put hello 操作对应的版本号 revision{2,0}，这就是 boltdb 的 key









## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

1. [etcd教程(六)---etcd多版本并发控制 - (lixueduan.com)](https://www.lixueduan.com/posts/etcd/06-why-mvcc/)
