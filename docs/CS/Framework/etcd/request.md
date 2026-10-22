## Introduction

[etcd](/docs/CS/Framework/etcd/etcd.md) 的**请求处理路径**深潜：客户端请求如何经 gRPC 拦截器进入 `KVServer`，quota 模块如何做请求限流（`ErrTooManyRequests` / `ErrRequestTooLarge` / 7s 超时），以及 `get` / `put` 一次读写请求在 etcd server 侧从「进入」到「提交 Raft 提案」的全链路。启动链见 [boot](/docs/CS/Framework/etcd/boot.md)；提案之后的 Raft 复制、Ready 消费与 apply 见 [raft](/docs/CS/Framework/etcd/raft.md)；线性读（ReadIndex）机制见 [read](/docs/CS/Framework/etcd/read.md)。

> [!NOTE]
> 版本基线同 [etcd](/docs/CS/Framework/etcd/etcd.md)：**3.7.2**（raft 已外置 `go.etcd.io/raft/v3` v3.7.0）。

## server

etcd 在 `server/etcdserver/api/v3rpc` 中把实现 `KV` 各方法的对象注册到 gRPC Server，并挂上一系列拦截器。下面是 `KV` service 的 protobuf 定义，`Range` 即负责读取的 RPC：

```protobuf
service KV {
  // Range gets the keys in the range from the key-value store.
  rpc Range(RangeRequest) returns (RangeResponse) {
      option (google.api.http) = {
        post: "/v3/kv/range"
        body: "*"
    };
  }
  // Put / DeleteRange / Txn / Compact ...
}
```

**gRPC 拦截器（interceptor）**提供在请求前后插入 hook 的能力，etcd 基于它实现了若干关键特性：

| 拦截器 / 能力 | 作用 |
|---|---|
| debug 日志 | 记录请求细节，便于排查 |
| metrics 统计 | 暴露请求计数、延时分布到 Prometheus |
| Learner 节点限制 | 限制对 Learner 节点的写/读请求接口与参数 |
| Leader 前置检查 | 执行操作前要求集群**必须有 Leader**，无 Leader 直接拒绝 |
| 慢查询日志 | 请求延时超过阈值时打印**含来源 IP** 的慢查询日志（3.5 引入） |

server 收到 client 的 `Range` RPC 后，按 `ServiceName + RPC Method` 路由到对应 handler；handler 先把上述拦截器串成执行链，在拦截器逻辑里再调用 `KVServer` 模块的 `Range` 接口取数。

**KVServer 方法 ↔ EtcdServer 实现映射**（client 侧接口即 server 侧 `EtcdServer` 的实现入口）：

| KVClient 方法 | 对应 RPC | EtcdServer 实现 |
|---|---|---|
| `Range` | `KV/Range` | `EtcdServer.Range` |
| `Put` | `KV/Put` | `EtcdServer.Put` |
| `DeleteRange` | `KV/DeleteRange` | `EtcdServer.DeleteRange` |
| `Txn` | `KV/Txn` | `EtcdServer.Txn` |
| `Compact` | `KV/Compact` | `EtcdServer.Compact` |

## quota

写入请求在提交 Raft 之前，会先过 quota 限流，避免 expensive request 把集群打雪崩。etcd 用两个常量界定后端 db 的配额范围：

```go
const (
    // DefaultQuotaBytes is the number of bytes the backend Size may
    // consume before exceeding the space quota.
    DefaultQuotaBytes = int64(2 * 1024 * 1024 * 1024) // 2GB
    // MaxQuotaBytes is the maximum number of bytes suggested for a backend
    // quota. A larger quota may lead to degraded performance.
    MaxQuotaBytes = int64(8 * 1024 * 1024 * 1024) // 8GB
)
```

**为什么不建议 db 超过 8G**：etcd 不支持数据分片，所有 key-value 落在 boltdb 单个 bucket；db 过大时启动期重建 `treeIndex`、事务提交时 freelist 的 `O(N)` 遍历、以及查询触发的主缺页中断都会显著放大延时与内存压力，进而让任意 expensive read 引发 OOM / 丢包。更细的配额与性能调优（含 `--quota-backend-bytes`、compact、freelist 类型）见 [tuning](/docs/CS/Framework/etcd/tuning.md)。

限流的核心判定在 `EtcdServer.processInternalRaftRequestOnce`：先比 committed / applied 间隙，再查包大小，最后才 `Propose`：

```go
func (s *EtcdServer) processInternalRaftRequestOnce(ctx context.Context, r pb.InternalRaftRequest) (*applyResult, error) {
    ai := s.getAppliedIndex()
    ci := s.getCommittedIndex()
    if ci > ai+maxGapBetweenApplyAndCommitIndex {
        return nil, ErrTooManyRequests          // ① 已提交但还未 apply 的日志过多
    }
    // check authinfo if it is not InternalAuthenticateRequest
    // max-request-bytes '1572864' 1.5M
    if len(data) > int(s.Cfg.MaxRequestBytes) {
        return nil, ErrRequestTooLarge          // ② 包大小超 --max-request-bytes（默认 1.5M）
    }
    // ...
    err = s.r.Propose(cctx, data)
    select {
    case x := <-ch:
        return x.(*applyResult), nil
    case <-cctx.Done():
        proposalsFailed.Inc()
        s.w.Trigger(id, nil) // GC wait
        return nil, s.parseProposeCtxErr(cctx.Err(), start)  // ③ 等待 apply 结果超时（默认 7s）
    case <-s.done:
        return nil, ErrStopped
    }
}
```

| 判定 | 返回错误 | 触发条件 | 默认值 / 出处 |
|---|---|---|---|
| ① apply lag | `ErrTooManyRequests`（"etcdserver: too many requests"） | `committed - applied > maxGapBetweenApplyAndCommitIndex`（5000） | 间隙阈值 5000 |
| ② 包过大 | `ErrRequestTooLarge`（"etcdserver: request is too large"） | `len(data) > MaxRequestBytes` | `--max-request-bytes` 默认 1.5M（1572864） |
| ③ 提案超时 | `ErrTimeout`（"etcdserver: request timed out"） | 等待 apply 通知超过 ctx 超时（5s 磁盘 IO + 2×1s 竞选超时 ≈ 7s） | 默认 7s |

> 限流只挡在「写路径」入口；读路径（含线性读）不受 quota 约束，其一致性由 [read](/docs/CS/Framework/etcd/read.md) 的 ReadIndex 机制保证。

## Message Processing

### 消息入口

一个 etcd 节点运行后，有 3 个通道接收外界消息（以 kv 增删改查为例）：

1. **client 的 HTTP 调用**：经注册到 http 模块的 `keysHandler.ServeHTTP` 解析后，调用 `EtcdServer.Do()` 处理。
2. **client 的 gRPC 调用**：启动时把 `quotaKVServer`（组合增强了 `kvServer`）注册到 gRPC server；消息解析完后调用 `kvServer` 的 `Range`/`Put`/`DeleteRange`/`Txn`/`Compact`，最终落到 `EtcdServer` 的实现。
3. **节点间 gRPC 消息**：每个 `EtcdServer` 含 `Transport`，其 `peers` map 封装了到其它节点的 `streamReader`/`streamWriter`；`streamReader` 的 `recvc`/`propc` 队列收到消息后由 peer 交给 `raftNode.Process` 处理。

clientv3 库基于 gRPC 封装了 KVServer / Cluster / Auth / Lease / Watch 等 API，并自带负载均衡与健康探测。其负载均衡算法为 **Round-robin**（每个请求轮询选 endpoint 建长连接）。

> 1. client 版本 ≤ 3.3 时，配多个 endpoint 只会 **Pinned endpoint**（选一个 IP 建一条连接），heavy usage 下可能 server 负载不均。
> 2. client 3.4 之前的负载均衡有严重 Bug：首节点异常可能让 client 访问异常（K8s 场景导致 APIServer 不可用），已在 Kubernetes 1.16 后修复。

### get

```shell
etcdctl get hello --endpoints http://127.0.0.1:2379
```

`get` 对应 `KVClient.Range`：client 经 gRPC 调用 `/etcdserverpb.KV/Range`，server 路由到 handler，先过拦截器链，再进 `KVServer.Range` 取数。

```go
func (c *kVClient) Range(ctx context.Context, in *RangeRequest, opts ...grpc.CallOption) (*RangeResponse, error) {
    out := new(RangeResponse)
    err := c.cc.Invoke(ctx, "/etcdserverpb.KV/Range", in, out, opts...)
    if err != nil {
        return nil, err
    }
    return out, nil
}
```

读请求若要求**线性一致性**，server 需先经 ReadIndex 向 Leader 确认 committed index、等本地 applied index 追上后才读状态机——这套机制与脑裂防护见 [read](/docs/CS/Framework/etcd/read.md)；若只需串行/历史版本读，则可绕过 Raft 直接读 MVCC 快照。

### put

```shell
etcdctl put hello world --endpoints http://127.0.0.1:2379
```

写流程相比读额外经过 **Quota + WAL + Apply** 三模块：

1. client 经负载均衡选节点，发起 gRPC 调用；
2. 请求过 gRPC 拦截器（Leader 检查、慢查询等），再经 **quota** 限流（见上节三判定）；
3. 进入 `KVServer`，向 `Node` 提交 `Propose`，生成全局 revision 并封装成 Raft 日志条目；
4. 后续由 Raft 复制到多数派、持久化 WAL、提交后进入 **apply** 管线异步按序执行——Raft 事件循环、`Ready` 五步消费、`applyAll` 与 FIFOScheduler 见 [raft](/docs/CS/Framework/etcd/raft.md)。

> 写路径上许多步骤是异步/并发的（如 WAL 落盘与向副本发 AppendEntries 并行），序号并非严格时间序。

## Links

- [net（gRPC 传输与 Peer）](/docs/CS/Framework/etcd/net.md)
- [troubleshooting（NOSPACE / slow apply）](/docs/CS/Framework/etcd/troubleshooting.md)
