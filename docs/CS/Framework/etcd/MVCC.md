## Introduction

etcd的使用场景是一种“读多写少”的场景，etcd里  的一个key，其实并不会发生频繁的变更，但是一旦发生变更，etcd就  需要通知监控这个key的所有客户端

etcd v2 是一个内存数据库，整个数据库拥有一个`Stop-the-World`的大锁，通过锁机制来解决并发带来的数据竞争。

但是存在**并发性能问题**：

- 1）锁的粒度不好控制，每次都会锁整个数据库
- 2）写锁和读锁相互阻塞。
- 3）前面的事务会阻塞后面的事务，对并发性能影响很大。

同时在高并发环境下还存在另一个严重的问题：

- **watch 机制可靠性问题**：etcd 中的 watch 机制会依赖旧数据，v2 版本基于滑动窗口实现的 watch 机制，只能保留最近的 1000 条历史事件版本，当 etcd server 写请求较多、网络波动时等场景，很容易出现事件丢失问题，进而又触发 client 数据全量拉取，产生大量 expensive request，甚至导致 etcd 雪崩。



etcd v2并未实时地将数据写入磁盘，持久化是靠快照来实现的，具体实现就是  将整个内存中的数据复制一份出来，然后序列化成JSON，写入磁盘  中，成为一个快照







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





```go
type ResponseHeader struct {
	// cluster_id is the ID of the cluster which sent the response.
	ClusterId uint64 `protobuf:"varint,1,opt,name=cluster_id,json=clusterId,proto3" json:"cluster_id,omitempty"`
	// member_id is the ID of the member which sent the response.
	MemberId uint64 `protobuf:"varint,2,opt,name=member_id,json=memberId,proto3" json:"member_id,omitempty"`
	// revision is the key-value store revision when the request was applied.
	// For watch progress responses, the header.revision indicates progress. All future events
	// recieved in this stream are guaranteed to have a higher revision number than the
	// header.revision number.
	Revision int64 `protobuf:"varint,3,opt,name=revision,proto3" json:"revision,omitempty"`
	// raft_term is the raft term when the request was applied.
	RaftTerm             uint64   `protobuf:"varint,4,opt,name=raft_term,json=raftTerm,proto3" json:"raft_term,omitempty"`
	XXX_NoUnkeyedLiteral struct{} `json:"-"`
	XXX_unrecognized     []byte   `json:"-"`
	XXX_sizecache        int32    `json:"-"`
}
```

ResponseHeader.Revision代表该请求成功执行之后etcd的revision



键值对数据结构的定义具体如下

```go

type KeyValue struct {
	// key is the key in bytes. An empty key is not allowed.
	Key []byte `protobuf:"bytes,1,opt,name=key,proto3" json:"key,omitempty"`
	// create_revision is the revision of last creation on this key.
	CreateRevision int64 `protobuf:"varint,2,opt,name=create_revision,json=createRevision,proto3" json:"create_revision,omitempty"`
	// mod_revision is the revision of last modification on this key.
	ModRevision int64 `protobuf:"varint,3,opt,name=mod_revision,json=modRevision,proto3" json:"mod_revision,omitempty"`
	// version is the version of the key. A deletion resets
	// the version to zero and any modification of the key
	// increases its version.
	Version int64 `protobuf:"varint,4,opt,name=version,proto3" json:"version,omitempty"`
	// value is the value held by the key, in bytes.
	Value []byte `protobuf:"bytes,5,opt,name=value,proto3" json:"value,omitempty"`
	// lease is the ID of the lease that attached to key.
	// When the attached lease expires, the key will be deleted.
	// If lease is 0, then no lease is attached to the key.
	Lease                int64    `protobuf:"varint,6,opt,name=lease,proto3" json:"lease,omitempty"`
	XXX_NoUnkeyedLiteral struct{} `json:"-"`
	XXX_unrecognized     []byte   `json:"-"`
	XXX_sizecache        int32    `json:"-"`
}
```

KeyValue.CreateRevision代表etcd的某个key最后一次创建时etcd的  revison，KeyValue.ModRevision则代表etcd的某个key最后一次更新  时etcd的revison。verison特指etcd键空间某个key从创建开始被修改  的次数，即KeyValue.Version



etcd将物理数据存储为一棵持久B+树中的键值对。为了高效，每  个revision的存储状态都只包含相对于之前revision的增量。一个  revision可能对应于树中的多个key



B+树中键值对的key即revision，revision是一个2元组（main，  sub），其中main是该revision的主版本号，sub是同一revision的副版本  号，其用于区分同一个revision的不同key。B+树中键值对的value包含  了相对于之前revision的修改，即相对于之前revision的一个增量。  

B+树按key的字典字节序进行排序。这样，etcd v3对revision增量的  范围查询（range query，即从某个revision到另一个revision）会很快  ——因为我们已经记录了从一个特定revision到其他revision的修改量。  etcd v3的压缩操作会删除过时的键值对

etcd v3还在内存中维护了一个基于B树的二级索引来加快对key的  范围查询。该B树索引的key是向用户暴露的etcd v3存储的key，而该B  树索引的value则是一个指向上文讨论的持久化B+树的增量的指针。  etcd v3的压缩操作会删除指向B树索引的无效指针



etcd v2的每个key只保留一个value，所以数据库并不大，可以直  接放在内存中。但是etcd v3实现了MVCC以后，每个key的value都需要  保存多个历史版本，这就极大地增加了存储的数据量，因此内存中就  会存储不下这么多数据。对此，一个自然的解决方案就是将数据存储  在磁盘里。etcd v3当前使用BoltDB将数据存储在磁盘中





## put

一个 put 命令流程如下图所示：

1. 首先它需要从 treeIndex 模块中查询 key 的 keyIndex 索引信息
2. 其次 etcd 会根据当前的全局版本号（空集群启动时默认为 1）自增，生成 put hello 操作对应的版本号 revision{2,0}，这就是 boltdb 的 key









## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

1. [etcd教程(六)---etcd多版本并发控制 - (lixueduan.com)](https://www.lixueduan.com/posts/etcd/06-why-mvcc/)
