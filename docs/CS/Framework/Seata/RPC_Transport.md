## Introduction

本笔记拆解 Seata 的 **RPC 传输层与通信协议**（apache/seata @ v2.7.0）。一次事务的端到端链路与 TC / RM 内部实现分别见 Transaction Flow、TC Coordinator 两册。所有类名均可在 `core.rpc` / `core.protocol` 包下核对。

## Two Type Axes

源码里有两套「类型」，务必区分：

1. **线级消息种类** `RpcMessage.messageType`（`byte`）：只表示「请求 / 响应 / 单向 / 心跳」，与业务无关。取值 `MSGTYPE_RESQUEST_SYNC=0`、`MSGTYPE_RESPONSE=1`、`MSGTYPE_RESQUEST_ONEWAY=2`、`MSGTYPE_HEARTBEAT_REQUEST=3`、`MSGTYPE_HEARTBEAT_RESPONSE=4`（见 `ProtocolConstants`）。
2. **业务消息类型** `MessageType.getTypeCode()`（`short`）：这才是 TM/RM/TC 之间的「链路契约」，也是 `processorTable` 分派的 key。例如 `TYPE_GLOBAL_BEGIN=1`、`TYPE_BRANCH_REGISTER=11`、`TYPE_BRANCH_COMMIT=3`。

> `RpcMessage` 头里写的是前者（线级种类）；`processorTable` 用后者（业务类型）查处理器。两者都叫 "type"，极易看错。

## Remoting Classes

```dot
digraph rpc {
  rankdir=LR;
  node [shape=box, style=rounded];
  ANR [label="AbstractNettyRemoting\n(futures / processorTable / 超时扫描)"];
  SRV [label="NettyRemotingServer"];
  CLI [label="AbstractNettyRemotingClient"];
  RM [label="RmNettyRemotingClient (RMROLE)"];
  TM [label="TmNettyRemotingClient (TMROLE)"];
  SRV -> ANR;
  CLI -> ANR;
  RM -> CLI;
  TM -> CLI;
}
```

- `AbstractNettyRemoting`：收发、超时、`processorTable` 分派的公共基类。
- `NettyRemotingServer`：服务端；`registerProcessor()` 把所有 server 侧消息类型注册到 `ServerOnRequestProcessor`。
- `AbstractNettyRemotingClient`（**注意：没有 `NettyRemotingClient` 这个具体类**）由两个 final 单例子类特化：`RmNettyRemotingClient`、`TmNettyRemotingClient`。客户端每 10s 触发 `reconnect`。

## Wire Format (V1 equals V2)

帧布局（`ProtocolEncoderV1`，V2 仅覆写 `protocolVersion()`，字节布局完全一致）：

```
 0       2    3        7        9     10    11    12    16
+---------+----+--------+--------+-----+-----+-----+-----+
| magic   |ver |fullLen |headLen |type |code |comp | id  |
| 0xda 0xda| 2  | 4B     | 2B     | 1B  | 1B  | 1B  | 4B  |
+---------+----+--------+--------+-----+-----+-----+-----+
| headMap(可选, 零拷贝)        | body(codec 序列化 -> compressor 压缩; 心跳时为空) |
```

- `magic = 0xda,0xda`；`MAX_FRAME_LENGTH = 8MB`；`V1_HEAD_LENGTH = 16` 基线。
- 默认 `codec = SEATA(1)`（非 protobuf，可按 `SERIALIZE_FOR_RPC` 配置切换），默认 `compressor = NONE(0)`（可按 `COMPRESSOR_FOR_RPC` 配置）。
- **心跳无 body**：编码时 `messageType` 为心跳直接跳过 body 序列化。

## Request / Response Correlation

- 关联 key = `RpcMessage.id`（int，自增）。`sendSync` 时把 `id → MessageFuture(CompletableFuture)` 放进 `futures`，`channel.writeAndFlush` 后 `future.get(timeout)` 阻塞。
- 响应回来由 `ClientOnResponseProcessor` 用 `id` 从 `futures` 取出并 `setResultMessage` 唤醒。
- 超时：独立 timer 每 3s 扫描 `futures`，超时置 `TimeoutException` 并移除。
- 合并/批量：`MergedWarpMessage` 把多条子消息合成一帧，结果用 `MergeResultMessage` / `BatchResultMessage` 拆分回各子 `id`（`childToParentMap` / `mergeMsgMap` 维护父子关系）。

## Processor Dispatch

分派入口恒为 `AbstractNettyRemoting.processMessage`：取 `((MessageTypeAware)body).getTypeCode()` 查 `processorTable`，拿到 `Pair<processor, executor>` 执行。

- **TC 侧**：所有事务类请求统一进 `ServerOnRequestProcessor` → `TransactionMessageHandler.onRequest()` → `request.handle()` → `AbstractTCInboundHandler` 的 8 个 `handle(...)` 模板 → `DefaultCoordinator` 的 `doXxx`。**不是「一个 Handler 类对应一种消息」，而是 DTO 多态 `handle()` 落到协调者的 `doXxx`**。
- `executor == null` 的处理器（注册、心跳、响应）在 Netty IO 线程直接跑；请求类走 `messageExecutor`；branch 结果走独立的 `branchResultMessageExecutor`。

## MessageType Contracts (TM/RM/TC)

| 方向 | 类型 | 值 | DTO |
| :--- | :--- | :--- | :--- |
| TM/RM to TC | `TYPE_GLOBAL_BEGIN` | 1 | `GlobalBeginRequest` |
| TM/RM to TC | `TYPE_GLOBAL_COMMIT` | 7 | `GlobalCommitRequest` |
| TM/RM to TC | `TYPE_GLOBAL_ROLLBACK` | 9 | `GlobalRollbackRequest` |
| TM/RM to TC | `TYPE_GLOBAL_STATUS` | 15 | `GlobalStatusRequest` |
| TM/RM to TC | `TYPE_GLOBAL_REPORT` | 17 | `GlobalReportRequest` |
| RM to TC | `TYPE_BRANCH_REGISTER` | 11 | `BranchRegisterRequest` |
| RM to TC | `TYPE_BRANCH_STATUS_REPORT` | 13 | `BranchReportRequest` |
| TM/RM to TC | `TYPE_GLOBAL_LOCK_QUERY` | 21 | `GlobalLockQueryRequest` |
| TM to TC | `TYPE_REG_CLT` | 101 | `RegisterTMRequest` |
| RM to TC | `TYPE_REG_RM` | 103 | `RegisterRMRequest` |
| RM to TC | `TYPE_UNREG_RM` | 105 | `UnregisterRMRequest` |
| TM/RM to TC | `TYPE_SEATA_MERGE` | 59 | `MergedWarpMessage` |
| TM/RM to TC | `TYPE_HEARTBEAT_MSG` | 120 | `HeartbeatMessage.PING` |
| TC to TM/RM | `TYPE_GLOBAL_BEGIN_RESULT` | 2 | `GlobalBeginResponse` |
| TC to TM/RM | `TYPE_GLOBAL_COMMIT_RESULT` | 8 | `GlobalCommitResponse` |
| TC to TM/RM | `TYPE_GLOBAL_ROLLBACK_RESULT` | 10 | `GlobalRollbackResponse` |
| TC to TM/RM | `TYPE_GLOBAL_STATUS_RESULT` | 16 | `GlobalStatusResponse` |
| TC to TM/RM | `TYPE_GLOBAL_REPORT_RESULT` | 18 | `GlobalReportResponse` |
| TC to RM | `TYPE_BRANCH_REGISTER_RESULT` | 12 | `BranchRegisterResponse` |
| TC to RM | `TYPE_BRANCH_STATUS_REPORT_RESULT` | 14 | `BranchReportResponse` |
| TC to RM | `TYPE_GLOBAL_LOCK_QUERY_RESULT` | 22 | `GlobalLockQueryResponse` |
| TC to RM | `TYPE_BRANCH_COMMIT` | 3 | `BranchCommitRequest` |
| TC to RM | `TYPE_BRANCH_ROLLBACK` | 5 | `BranchRollbackRequest` |
| TC to RM | `TYPE_RM_DELETE_UNDOLOG` | 111 | `UndoLogDeleteRequest` |
| RM to TC | `TYPE_BRANCH_COMMIT_RESULT` | 4 | `BranchCommitResponse` |
| RM to TC | `TYPE_BRANCH_ROLLBACK_RESULT` | 6 | `BranchRollbackResponse` |
| TC to TM/RM | `TYPE_BATCH_RESULT_MSG` | 121 | `BatchResultMessage` |
| TC to TM/RM | `TYPE_SEATA_MERGE_RESULT` | 60 | `MergeResultMessage` |
| TC to TM/RM | `VERSION_NOT_SUPPORT` | -1 | `VersionNotSupportMessage` |

## Design Gotchas

- **V2 线格式 == V1**：`ProtocolEncoderV2` 只覆写 `protocolVersion()`，没有任何其它差异；真正按版本分流的是 `MultiProtocolDecoder` 首帧嗅探。客户端恒发 V2，服务端按首帧版本装配对应 decoder/encoder（首帧驱动，非握手）。
- **codec/compressor 不是「按消息选」，而是按请求/连接**：请求用全局 `CONFIGURED_CODEC/COMPRESSOR`；响应**原样回抄请求的 codec/compressor**。
- **合并拆帧有版本门槛**：server 仅当对端 ≥ 2.3.0 才把 `MergedWarpMessage` 拆成独立 `RpcMessage` 逐条分派；批量响应 `BatchResultMessage` 仅在 server 开启且对端 ≥ 1.5.0 时产生，否则回 `MergeResultMessage`。
- **连接管理**：服务端 `ChannelManager` 用 `resourceId→appId→ip→port` 多级索引 RM 通道；客户端 `NettyClientChannelManager` 负责连接池与重连；reader-idle 时服务端直接关通道，客户端 writer-idle 主动发 `PING`。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
