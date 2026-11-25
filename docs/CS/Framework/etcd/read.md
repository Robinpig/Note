## Introduction

[raft.md](/docs/CS/Framework/etcd/raft.md) 讲了 Raft 层的 **ReadIndex** 算法：leader 记下当前 commit index、向 follower 广播心跳、收到多数派响应后，等状态机 apply 到该 index 再返回，从而避免网络分区下的 stale read。本文讲 etcd **服务端**如何把这套算法接到 `Range` / 只读 `Txn` 上，即 v3.7.2 中 `etcdserver/read` 包的胶水层。

写路径的 Propose、apply 与 revision 边界见 [Core_Mechanisms](/docs/CS/Framework/etcd/Core_Mechanisms.md)，`Range` 的完整入口见 [request](/docs/CS/Framework/etcd/request.md)。本文只聚焦读路径，并区分 linearizable 与 serializable 两种读。

## Two Reads: Serializable vs Linearizable

etcd 的 `RangeRequest` 有个布尔字段 `Serializable`。它直接决定走不走 ReadIndex：

```go
// server/etcdserver/v3_server.go:106-155（节选）
func (s *EtcdServer) Range(ctx context.Context, r *pb.RangeRequest) (*pb.RangeResponse, error) {
    if !r.Serializable {
        err = s.read.LinearizableReadNotify(ctx) // 默认（Serializable=false）走这里
        if err != nil {
            return nil, err
        }
    }
    get := func() { resp, _, err = txn.Range(ctx, s.Logger(), s.KV(), r, true) }
    // 鉴权后执行 get，最终读本地 MVCC
}
```

- **Linearizable（默认，`Serializable=false`）**：先调 `LinearizableReadNotify` 与集群"对一下账"，保证读到 ReadIndex 确认 index 之前已提交的数据（线性一致）。代价是一次 ReadIndex 往返，并可能等待本地 apply。
- **Serializable（`Serializable=true`）**：跳过 `LinearizableReadNotify`，直接读本地 MVCC 状态机。延迟低、不加重 leader 负担，但可能读到稍旧的数据（stale）——因为本地状态机可能还没 apply 到最新 commit index。

只读事务 `Txn` 同理：若 `txn.IsTxnReadonly(r)` 且 `!txn.IsTxnSerializable(r)`，也会先调用 `s.read.LinearizableReadNotify(ctx)`（`v3_server.go:325-372`）。

> [!NOTE]
> serializable 读不是"错误数据"，而是"可能落后一个 apply 延迟"。监控读取、最终一致即可的业务、或扛大量读压力时常用它；要求强一致（如读刚写下去的配置）必须用默认 linearizable。

## Linearizable Read Flow

`Range` 调用 `s.read.LinearizableReadNotify(ctx)` 只是记录当前 notifier，并尽可能向 `waitC` 发信号；真正的 ReadIndex 由后台 `LinearizableReadLoop` 驱动。3.7.2 的实现位于 `server/etcdserver/read/read.go`：

```go
// read/read.go:74-146（节选）
func (r *Read) LinearizableReadNotify(ctx context.Context) error {
    r.mux.RLock()
    nc := r.notifier
    r.mux.RUnlock()

    select {
    case r.waitC <- struct{}{}:
    default:
    }

    select {
    case <-nc.c:
        return nc.err
    case <-ctx.Done():
        return ctx.Err()
    case <-r.server.Done():
        return errors.ErrStopped
    }
}
```

`LinearizableReadLoop` 每轮替换 notifier，让在该轮注册的多个读共享一次 ReadIndex：

```go
confirmedIndex, err := r.requestCurrentIndex(leaderChangedNotifier)
if err != nil {
    nr.notify(err)
    continue
}

appliedIndex := r.server.AppliedIndex()
if appliedIndex < confirmedIndex {
    select {
    case <-r.server.ApplyWait(confirmedIndex):
    case <-r.server.Stopping():
        return
    }
}
nr.notify(nil)
```

`requestCurrentIndex` 内部：

1. 生成 8 字节 `requestID`，通过 `raft.ReadIndex` 发送；
2. 用 `map[uint64]struct{}` 保存本轮所有已发送 ID；
3. 收到 `ReadState` 后匹配 `RequestCtx`，忽略过期响应；
4. first commit in current term 或 retry timer 到期时重发；
5. 返回 `confirmedIndex`，循环再等待本地 applied index 追上。

> [!NOTE]
> 一个 loop 唤醒一批读，把多次并发线性读的 ReadIndex 往返合并。但“同批”不是由客户端显式传入的批次，而是 notifier 切换与后台循环时序自然形成的聚合。

## Leader Change and Retry

等待 ReadState 期间若 leader 变更，`requestCurrentIndex` 返回 `ErrLeaderChanged`；`LinearizableReadLoop` 通过 notifier 把错误交给本轮读，随后继续等待下一批请求。客户端可按自身重试策略重新发起读。

3.7.2 还增加了 first-commit-in-term 重发与周期 retry：前者避免新 term 尚未提交日志时 ReadIndex 卡住，后者处理响应丢失或本地节点排队。旧请求的迟到响应会因 request ID 不在当前 map 中被忽略并计入 `slowReadIndex`，不会错误放行当前读。

## Connection with raft.md

| 层 | 文件 | 讲什么 |
| :--- | :--- | :--- |
| Raft 算法 | [raft.md](/docs/CS/Framework/etcd/raft.md) `## ReadIndex` | ReadIndex 四步、心跳确认、stale read 成因、`ReadState` / `readOnly` 结构 |
| 服务端胶水 | 本文 / `etcdserver/read/read.go` | `Range` 如何触发、loop 如何聚合多读、如何等待 `ApplyWait`、leader 变更与重试如何返回 |

一句话：raft.md 解释"leader 如何确认自己仍是 leader 且读 index 足够新"，本文解释"etcd 如何把该确认接到 `Range` / 只读 Txn，并批量放行并发读"。

## Links

- [client（读请求的重试语义）](/docs/CS/Framework/etcd/client.md)
- [MVCC（状态机视图与 revision）](/docs/CS/Framework/etcd/MVCC.md)
- [watch（与读共享的 MVCC 状态）](/docs/CS/Framework/etcd/watch.md)

## References

1. [etcd v3.7.2 source - EtcdServer.Range](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/v3_server.go)
2. [etcd v3.7.2 source - linearizable read loop](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/read/read.go)
