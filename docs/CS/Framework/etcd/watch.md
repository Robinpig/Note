## Introduction

在etcd v2 Watch机制实现中，使用的是HTTP/1.x协议，实现简单、兼容性好，每个watcher对应一个TCP连接。client通过HTTP/1.1协议长连接定时轮询server，获取最新的数据变化事件。
然而当你的watcher成千上万的时，即使集群空负载，大量轮询也会产生一定的QPS，server端会消耗大量的socket、内存等资源，导致etcd的扩展性、稳定性无法满足Kubernetes等业务场景诉求

在etcd v3中，为了解决etcd v2的以上缺陷，使用的是基于HTTP/2的gRPC协议，双向流的Watch API设计，实现了连接多路复用
etcd基于多路复用等机制，实现了一个client/TCP连接支持多gRPC Stream， 一个gRPC Stream又支持多个watcher 同时事件通知模式也从client轮询优化成server流式推送，极大降低了server端socket、内存等资源
在clientv3库中，Watch特性被抽象成Watch、Close、RequestProgress三个简单API提供给开发者使用，屏蔽了client与gRPC WatchServer交互的复杂细节，实现了一个client支持多个gRPC Stream，一个gRPC Stream支持多个watcher，显著降低了你的开发复杂度
同时当watch连接的节点故障，clientv3库支持自动重连到健康节点，并使用之前已接收的最大版本号创建新的watcher，避免旧事件回放等

etcd经历了从滑动窗口到MVCC机制的演变，滑动窗口是仅保存有限的最近历史版本到内存中，而MVCC机制则将历史版本保存在磁盘中，避免了历史版本的丢失，极大的提升了Watch机制的可靠性。
etcd v2滑动窗口是如何实现的？它有什么缺点呢？
它使用的是如下一个简单的环形数组来存储历史事件版本，当key被修改后，相关事件就会被添加到数组中来。若超过eventQueue的容量，则淘汰最旧的事件。在etcd v2中，eventQueue的容量是固定的1000，因此它最多只会保存1000条事件记录，不会占用大量etcd内存导致etcd OOM
```go
type EventHistory struct {
    Queue      eventQueue
    StartIndex uint64
    LastIndex  uint64
    rwl        sync.RWMutex
}
```


它的缺陷显而易见的，固定的事件窗口只能保存有限的历史事件版本，是不可靠的。当写请求较多的时候、client与server网络出现波动等异常时，很容易导致事件丢失，client不得不触发大量的expensive查询操作，以获取最新的数据及版本号，才能持续监听数据。
特别是对于重度依赖Watch机制的Kubernetes来说，显然是无法接受的。因为这会导致控制器等组件频繁的发起expensive List Pod等资源操作，导致APIServer/etcd出现高负载、OOM等，对稳定性造成极大的伤害

watch请求流程

当你通过etcdctl或API发起一个watch key请求的时候，etcd的gRPCWatchServer收到watch请求后，会创建一个serverWatchStream, 它负责接收client的gRPC Stream的create/cancel watcher请求(recvLoop goroutine)，并将从MVCC模块接收的Watch事件转发给client(sendLoop goroutine)。
当serverWatchStream收到create watcher请求后，serverWatchStream会调用MVCC模块的WatchStream子模块分配一个watcher id，并将watcher注册到MVCC的WatchableKV模块。
在etcd启动的时候，WatchableKV模块会运行syncWatchersLoop和syncVictimsLoop goroutine，分别负责不同场景下的事件推送，它们也是Watch特性可靠性的核心之一。
从架构图中你可以看到Watch特性的核心实现是WatchableKV模块


```go
type WatchableKV interface {
    KV
    Watchable
}
```

```shell
etcdctl watch hello -w=json –rev=1
```

Watch特性的核心实现模块是watchableStore etcd根据不同场景将watcher分类，实现了轻重分离、低耦合。我首先给你介绍下synced watcher、unsynced watcher它们各自的含义。
synced watcher，顾名思义，表示此类watcher监听的数据都已经同步完毕，在等待新的变更。
如果你创建的watcher未指定版本号(默认0)、或指定的版本号大于etcd sever当前最新的版本号(currentRev)，那么它就会保存到synced watcherGroup中。watcherGroup负责管理多个watcher，能够根据key快速找到监听该key的一个或多个watcher。
unsynced watcher，表示此类watcher监听的数据还未同步完成，落后于当前最新数据变更，正在努力追赶。
如果你创建的watcher指定版本号小于etcd server当前最新版本号，那么它就会保存到unsynced watcherGroup中。比如我们的这个案例中watch带指定版本号1监听时，版本号1和etcd server当前版本之间的数据并未同步给你，因此它就属于此类。

```go
type watchableStore struct {
    *store

    // mu protects watcher groups and batches. It should never be locked
    // before locking store.mu to avoid deadlock.
    mu sync.RWMutex

    // victims are watcher batches that were blocked on the watch channel
    victims []watcherBatch
    victimc chan struct{}

    // contains all unsynced watchers that needs to sync with events that have happened
    unsynced watcherGroup

    // contains all synced watchers that are in sync with the progress of the store.
    // The key of the map is the key that the watcher watches on.
    synced watcherGroup

    stopc chan struct{}
    wg    sync.WaitGroup
}
```


从以上介绍中，我们可以将可靠的事件推送机制拆分成最新事件推送、异常场景重试、历史事件推送机制三个子问题来进行分析。


执行put hello修改操作时，如上图所示，请求经过KVServer、Raft模块后Apply到状态机时，在MVCC的put事务中，它会将本次修改的后的mvccpb.KeyValue保存到一个changes数组中。
在put事务结束时，如下面的精简代码所示，它会将KeyValue转换成Event事件，然后回调watchableStore.notify函数（流程5）。notify会匹配出监听过此key并处于synced watcherGroup中的watcher，同时事件中的版本号要大于等于watcher监听的最小版本号，才能将事件发送到此watcher的事件channel中。
serverWatchStream的sendLoop goroutine监听到channel消息后，读出消息立即推送给client（流程6和7），至此，完成一个最新修改事件推送


```go
func (tw *watchableStoreTxnWrite) End() {
    changes := tw.Changes()
    if len(changes) == 0 {
        tw.TxnWrite.End()
        return
    }

    rev := tw.Rev() + 1
    evs := make([]mvccpb.Event, len(changes))
    for i, change := range changes {
        evs[i].Kv = &changes[i]
        if change.CreateRevision == 0 {
            evs[i].Type = mvccpb.DELETE
            evs[i].Kv.ModRevision = rev
        } else {
            evs[i].Type = mvccpb.PUT
        }
    }

    // end write txn under watchable store lock so the updates are visible
    // when asynchronous event posting checks the current store revision
    tw.s.mu.Lock()
    tw.s.notify(rev, evs)
    tw.TxnWrite.End()
    tw.s.mu.Unlock()
}
```

接收Watch事件channel的buffer容量默认1024 若出现channel buffer满了，etcd为了保证Watch事件的高可靠性，并不会丢弃它，而是将此watcher从synced watcherGroup中删除，然后将此watcher和事件列表保存到一个名为受害者victim的watcherBatch结构中，通过异步机制重试保证事件的可靠性

notify操作它是在修改事务结束时同步调用的，必须是轻量级、高性能、无阻塞的，否则会严重影响集群写性能。
那么若因网络波动、CPU高负载等异常导致watcher处于victim集合中后，etcd是如何处理这种slow watcher呢？
在介绍Watch机制整体架构时，我们知道WatchableKV模块会启动两个异步goroutine，其中一个是syncVictimsLoop，正是它负责slower watcher的堆积的事件推送。
它的基本工作原理是，遍历victim watcherBatch数据结构，尝试将堆积的事件再次推送到watcher的接收channel中。若推送失败，则再次加入到victim watcherBatch数据结构中等待下次重试。
若推送成功，watcher监听的最小版本号(minRev)小于等于server当前版本号(currentRev)，说明可能还有历史事件未推送，需加入到unsynced watcherGroup中，由下面介绍的历史事件推送机制，推送minRev到currentRev之间的事件。
若watcher的最小版本号大于server当前版本号，则加入到synced watcher集合中，进入上面介绍的最新事件通知机制


历史事件

WatchableKV模块的另一个goroutine，syncWatchersLoop，正是负责unsynced watcherGroup中的watcher历史事件推送。
在历史事件推送机制中，如果你监听老的版本号已经被etcd压缩了，client该如何处理？
要了解这个问题，我们就得搞清楚syncWatchersLoop如何工作，它的核心支撑是boltdb中存储了key-value的历史版本。
syncWatchersLoop，它会遍历处于unsynced watcherGroup中的每个watcher，为了优化性能，它会选择一批unsynced watcher批量同步，找出这一批unsynced watcher中监听的最小版本号。
因boltdb的key是按版本号存储的，因此可通过指定查询的key范围的最小版本号作为开始区间，当前server最大版本号作为结束区间，遍历boltdb获得所有历史数据。
然后将KeyValue结构转换成事件，匹配出监听过事件中key的watcher后，将事件发送给对应的watcher事件接收channel即可。发送完成后，watcher从unsynced watcherGroup中移除、添加到synced watcherGroup中
若watcher监听的版本号已经小于当前etcd server压缩的版本号，历史变更数据就可能已丢失，因此etcd server会返回ErrCompacted错误给client。client收到此错误后，需重新获取数据最新版本号后，再次Watch。你在业务开发过程中，使用Watch API最常见的一个错误之一就是未处理此错误

事件快速匹配
etcd使用map记录了监听单个key的watcher 同时Watch特性不仅仅可以监听单key，它还可以指定监听key范围、key前缀，因此etcd还使用了如下的区间树
当收到创建watcher请求的时候，它会把watcher监听的key范围插入到上面的区间树中，区间的值保存了监听同样key范围的watcher集合/watcherSet。
当产生一个事件时，etcd首先需要从map查找是否有watcher监听了单key，其次它还需要从区间树找出与此key相交的所有区间，然后从区间的值获取监听的watcher集合







## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)





      
      
      
      




 





