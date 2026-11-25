## Introduction

> [!NOTE]
> 本篇以 **etcd v3.7.2** 为源码基线。`watchableStore` 的 channel 容量、批量同步和 victim 重试常量均以该版本为准；跨层的事件发布边界见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)。

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


```go
// server/storage/mvcc/watchable_store.go:542-572（节选）
type watcher struct {
    key []byte
    end []byte

    // victim is set when ch is blocked and undergoing victim processing
    victim bool

    // compacted is set when the watcher is removed because of compaction
    compacted bool
    // restore is true when a synced watcher is moved to unsynced after restore.
    restore bool

    startRev int64
    // minRev is the minimum revision update the watcher will accept
    minRev int64
    id     WatchID

    fcs []FilterFunc
    // The channel might be shared with other watchers in the same stream.
    ch chan<- WatchResponse
}
```

当watcher实例监听的key发生了变化 则使用一个Event实例进行表示

```go
type Event struct {
    // type is the kind of event. If type is a PUT, it indicates
    // new data has been stored to the key. If type is a DELETE,
    // it indicates the key was deleted.
    Type Event_EventType `protobuf:"varint,1,opt,name=type,proto3,enum=mvccpb.Event_EventType" json:"type,omitempty"`
    // kv holds the KeyValue for the event.
    // A PUT event contains current kv pair.
    // A PUT event with kv.Version=1 indicates the creation of a key.
    // A DELETE/EXPIRE event contains the deleted key with
    // its modification revision set to the revision of deletion.
    Kv *KeyValue `protobuf:"bytes,2,opt,name=kv,proto3" json:"kv,omitempty"`
    // prev_kv holds the key-value pair before the event happens.
    PrevKv               *KeyValue `protobuf:"bytes,3,opt,name=prev_kv,json=prevKv,proto3" json:"prev_kv,omitempty"`
    XXX_NoUnkeyedLiteral struct{}  `json:"-"`
    XXX_unrecognized     []byte    `json:"-"`
    XXX_sizecache        int32     `json:"-"`
}
```

eventBatch.add添加Event实例
```go
func (eb *eventBatch) add(ev mvccpb.Event) {
    if eb.revs > watchBatchMaxRevs {
        // maxed out batch size
        return
    }

    if len(eb.evs) == 0 {
        // base case
        eb.revs = 1
        eb.evs = append(eb.evs, ev)
        return
    }

    // revision accounting
    ebRev := eb.evs[len(eb.evs)-1].Kv.ModRevision
    evRev := ev.Kv.ModRevision
    if evRev > ebRev {
        eb.revs++
        if eb.revs > watchBatchMaxRevs {
            eb.moreRev = evRev
            return
        }
    }

    eb.evs = append(eb.evs, ev)
}
```

WatchResponse表示一次响应


```go
type WatchResponse struct {
    Header *ResponseHeader `protobuf:"bytes,1,opt,name=header,proto3" json:"header,omitempty"`
    // watch_id is the ID of the watcher that corresponds to the response.
    WatchId int64 `protobuf:"varint,2,opt,name=watch_id,json=watchId,proto3" json:"watch_id,omitempty"`
    // created is set to true if the response is for a create watch request.
    // The client should record the watch_id and expect to receive events for
    // the created watcher from the same stream.
    // All events sent to the created watcher will attach with the same watch_id.
    Created bool `protobuf:"varint,3,opt,name=created,proto3" json:"created,omitempty"`
    // canceled is set to true if the response is for a cancel watch request.
    // No further events will be sent to the canceled watcher.
    Canceled bool `protobuf:"varint,4,opt,name=canceled,proto3" json:"canceled,omitempty"`
    // compact_revision is set to the minimum index if a watcher tries to watch
    // at a compacted index.
    //
    // This happens when creating a watcher at a compacted revision or the watcher cannot
    // catch up with the progress of the key-value store.
    //
    // The client should treat the watcher as canceled and should not try to create any
    // watcher with the same start_revision again.
    CompactRevision int64 `protobuf:"varint,5,opt,name=compact_revision,json=compactRevision,proto3" json:"compact_revision,omitempty"`
    // cancel_reason indicates the reason for canceling the watcher.
    CancelReason string `protobuf:"bytes,6,opt,name=cancel_reason,json=cancelReason,proto3" json:"cancel_reason,omitempty"`
    // framgment is true if large watch response was split over multiple responses.
    Fragment             bool            `protobuf:"varint,7,opt,name=fragment,proto3" json:"fragment,omitempty"`
    Events               []*mvccpb.Event `protobuf:"bytes,11,rep,name=events,proto3" json:"events,omitempty"`
    XXX_NoUnkeyedLiteral struct{}        `json:"-"`
    XXX_unrecognized     []byte          `json:"-"`
    XXX_sizecache        int32           `json:"-"`
}
```


## Watch Request Flow

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

Watch特性的核心实现模块是watchableStore watchableStore结构体完成了注册watcher实例、管理watcher实例，以及发送触发watcher之后的响应等核心功能
etcd根据不同场景将watcher分类，实现了轻重分离、低耦合。我首先给你介绍下synced watcher、unsynced watcher它们各自的含义。
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

接收 Watch 事件的 channel 由 `NewWatchStream` 创建，v3.7.2 默认 buffer 容量为 **128**（`chanBufLen`），不是旧笔记中的 1024。若 channel 已满，etcd 不会丢弃待发送事件，而是把 watcher 从 synced/unsynced 分组中移出，将 watcher 与事件批次保存为 victim，交给异步机制重试。

`notify` 在修改事务结束时同步调用，必须轻量、高性能且不阻塞，否则会严重影响集群写性能。
若网络波动、CPU 高负载等异常使 watcher 进入 victim 集合，WatchableKV 启动的两个异步 goroutine 中，`syncVictimsLoop` 负责推送慢 watcher 积压的事件。
其基本工作方式是遍历 victim 中的 watcher batch，尝试再次发送已计算好的响应；仍失败就保留在 victim 中等待下一轮。`syncVictimsLoop` 在没有 victim 时等待通知，有 victim 时使用 **10ms** timer 重试。

重试成功后，如果 `minRev <= currentRev`，说明可能仍有历史事件未推送，watcher 转入 unsynced；否则说明已追上当前 revision，转回 synced。若批次还有 `moreRev`，先更新 `minRev` 再做上述判断。

## Historical Replay

WatchableKV 模块的另一个 goroutine `syncWatchersLoop` 负责 unsynced watcher 的历史事件推送。v3.7.2 的默认周期为 **100ms**，每批最多选择 **512** 个 watcher（`maxWatchersPerSync`）。

它选出这批 watcher 的最小 `minRev`，固定当前 `curRev`，然后按 backend revision key 范围 `[minRev, curRev+1)` 扫描历史记录，将命中的用户 key 转换为 Event 后发送。扫描结束后，若还有更多事件则继续留在 unsynced，否则转入 synced。用户前缀过滤发生在把 revision 记录转换为 Event 之后，不是直接按用户 key 扫描 bbolt。

如果 `minRev < compactMainRev`，历史已不可读，server 发送带 `CompactRevision` 的取消响应；client 应重新拉取最新数据，再以新的 revision 创建 watch。channel 满时不会删除 watcher，下一轮会重试发送该压缩响应。创建 watch 时若传入负的 `StartRevision`，gRPC 层直接返回 `Created + Canceled`，原因放在 `CancelReason`；正常历史追赶遇到的压缩则设置 `CompactRevision` 与 `Canceled`。

backend 恢复时，`watchableStore.Restore` 把 synced watcher 移到 unsynced 并设置 `restore` 标记，使追赶逻辑可以处理恢复前记下的未来 revision，避免误 panic。

## Fast Event Matching
etcd 使用 map 记录监听单个 key 的 watcher。Watch 也支持 key 范围与前缀，因此 etcd 还用区间树保存监听区间；区间的 value 是共享该区间的 watcher 集合。事件产生时，先查单 key map，再查与事件 key 相交的所有区间，从这些区间取出 watcher 集合。

## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [Core_Mechanisms（Apply → MVCC → Watch 的发布边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [compact（历史水位与 CompactRevision）](/docs/CS/Framework/etcd/compact.md)
- [troubleshooting（revision 已被压缩导致 watch 失效）](/docs/CS/Framework/etcd/troubleshooting.md)

## References

- [etcd v3.7.2 - watchable store](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store.go)
- [etcd v3.7.2 - watcher group](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watcher_group.go)
- [etcd v3.7.2 - watch transaction publication](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store_txn.go)
- [etcd v3.7.2 - gRPC watch server](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/v3rpc/watch.go)
