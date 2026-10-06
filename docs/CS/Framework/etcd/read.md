## Introduction

[raft.md](/docs/CS/Framework/etcd/raft.md) 讲了 Raft 层的 **ReadIndex** 算法：leader 记下当前 commit index、向 follower 广播心跳、收到多数派响应后，等状态机 apply 到该 index 再返回，从而避免网络分区下的 stale read。本文讲 etcd **服务端**如何把这套算法接到 `Range` 请求上——也就是 raft.md 那套机制在 `etcdserver` 里的"胶水"层（源码 `server/etcdserver/v3_server.go` 与 `raft.go`，v3.5.34）。

etcd.md 的 `get` 段其实把"读"和"写/apply"混在一段里讲了（标题是 get，内容却描述的是 propose→readyc→applyc 的写路径）；本文专讲**读路径**，并区分 linearizable 与 serializable 两种读。

## 两种读：Serializable vs Linearizable

etcd 的 `RangeRequest` 有个布尔字段 `Serializable`。它直接决定走不走 ReadIndex：

```go
// server/etcdserver/v3_server.go:98  Range
func (s *EtcdServer) Range(ctx context.Context, r *pb.RangeRequest) (*pb.RangeResponse, error) {
    // ...
    if !r.Serializable {
        err = s.linearizableReadNotify(ctx)   // 默认（Serializable=false）走这里
        // ...
    }
    // 无论哪种，最终都读 MVCC 当前状态机
    get := func() { resp, err = s.applyV3Base.Range(ctx, nil, r) }
    // ...
}
```

- **Linearizable（默认，`Serializable=false`）**：先调 `linearizableReadNotify` 与集群"对一遍账"，保证读到**最新已提交**的数据（线性一致）。代价是一次 ReadIndex 往返（leader 心跳 + 等 apply）。
- **Serializable（`Serializable=true`）**：**跳过** `linearizableReadNotify`，直接读本地 MVCC 状态机。延迟低、不加重 leader 负担，但可能读到稍旧的数据（stale）——因为本地状态机可能还没 apply 到最新 commit index。

只读事务 `Txn` 同理：若 `isTxnReadonly(r)` 且 `!isTxnSerializable(r)`，也会先 `linearizableReadNotify`（v3_server.go:162）。

> [!NOTE]
> serializable 读不是"错误数据"，而是"可能落后一个 apply 延迟"。监控读取、最终一致即可的业务、或扛大量读压力时常用它；要求强一致（如读刚写下去的配置）必须用默认 linearizable。

## linearizableReadNotify 的流程

`Range` 调用 `linearizableReadNotify(ctx)` 只是往 `readwaitc` 发个信号；真正的 ReadIndex 由**后台常驻 goroutine** `linearizableReadLoop()` 驱动（v3_server.go:911）：

```go
// server/etcdserver/raft.go:911
func (s *EtcdServer) linearizableReadLoop() {
    for {
        leaderChangedNotifier := s.LeaderChangedNotify()
        select {
        case <-leaderChangedNotifier:
            continue
        case <-s.readwaitc:          // 被 Range 的 linearizableReadNotify 唤醒
        case <-s.stopping:
            return
        }
        nextnr := newNotifier()
        s.readMu.Lock()
        nr := s.readNotifier
        s.readNotifier = nextnr
        s.readMu.Unlock()

        confirmedIndex, err := s.requestCurrentIndex(leaderChangedNotifier)
        // ...
        appliedIndex := s.getAppliedIndex()
        if appliedIndex < confirmedIndex {
            select {
            case <-s.applyWait.Wait(confirmedIndex):   // 等状态机 apply 到该 index
            case <-s.stopping:
                return
            }
        }
        nr.notify(nil)               // 唤醒所有在此期间排队的读
    }
}
```

`requestCurrentIndex`（raft.go:967）内部：

1. 生成 8 字节 `requestID`，调 `s.sendReadIndex(requestID)` 向 Raft 发一条 ReadIndex 请求；
2. 等 `s.r.readStateC` 拿到 `ReadState{Index}`（这就是 raft.md 里讲的：leader 广播心跳、多数派响应后产生的 read index），用 `requestID` 匹配响应、忽略过期的；
3. 返回 `confirmedIndex`（= 本次读要保证 apply 到的 index）。

拿到 `confirmedIndex` 后，循环**阻塞等待 `appliedIndex >= confirmedIndex`**（`s.applyWait.Wait(confirmedIndex)`），即本地状态机已把日志 apply 到该 index，然后 `nr.notify(nil)` 一次性唤醒本轮所有排队的读。

> [!NOTE]
> 这个"一个 loop 唤醒一批读"的设计很关键：同一时刻多个线性读请求会被合并——它们共享同一个 ReadIndex 往返，只在 `appliedIndex` 追上后一起被放行。这把"每次读都走一次 Raft 心跳"的代价摊薄了。raft.md 只描述单条 ReadIndex 的四步，本文补的是 etcd 服务端的**批量聚合**实现。

## Leader 变更与重试

等待 `readStateC` 期间若 leader 发生变更，`requestCurrentIndex` 会返回 `ErrLeaderChanged`（一个**可重试**错误），`linearizableReadLoop` 据此 `continue` 重新发起 ReadIndex。`Range` 上层把这个错误交给客户端重试逻辑（见 [client](/docs/CS/Framework/etcd/client.md) 的 `isSafeRetry`：读是 immutable RPC，仅在 `Unavailable` 等少数码上重试）。

requestID 用 8 字节、从 `reqIDGen` 递增生成，配合 `readStateC` 响应的 `RequestCtx` 做匹配；若某次请求超时，响应回来时会被 `slowReadIndex` 计数并忽略，继续等当前请求。

## 与 raft.md 的衔接

| 层 | 文件 | 讲什么 |
| :--- | :--- | :--- |
| Raft 算法 | [raft.md](/docs/CS/Framework/etcd/raft.md) `## ReadIndex` | ReadIndex 四步、心跳确认、stale read 成因、`ReadState` / `readOnly` 结构 |
| 服务端胶水 | 本文 | `Range` 如何触发、`linearizableReadLoop` 如何聚合多读、`appliedIndex` 如何通过 `applyWait` 等待、leader 变更如何转成可重试错误 |

一句话：raft.md 告诉你"leader 怎么确认自己还是 leader 且数据最新"，本文告诉你"etcd 的 `Range` 怎么利用这个确认、把一批并发读批量放行"。

## Links

- [etcd（get/put 消息处理与启动流程）](/docs/CS/Framework/etcd/etcd.md)
- [raft（ReadIndex 算法与 readOnly 结构）](/docs/CS/Framework/etcd/raft.md)
- [client（读请求的重试语义 isSafeRetry）](/docs/CS/Framework/etcd/client.md)
- [MVCC（状态机 apply 与 revision）](/docs/CS/Framework/etcd/MVCC.md)
- [watch（与读共享的 MVCC 视图）](/docs/CS/Framework/etcd/watch.md)

## References

1. [etcd source - server/etcdserver/v3_server.go（Range / linearizableReadNotify）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/etcdserver/v3_server.go)
2. [etcd source - server/etcdserver/raft.go（linearizableReadLoop / requestCurrentIndex）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/etcdserver/raft.go)
