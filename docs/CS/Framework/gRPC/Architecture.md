## Introduction

gRPC 的"薄"体现在它几乎没有自定义传输协议——它把一次 RPC 完整地映射到 HTTP/2 的帧序列上。理解 gRPC，本质上就是理解三件事：请求/响应如何拆成 HTTP/2 帧、消息体如何定界、状态与元数据如何通过头部传递。

官方规范 `gRFC: gRPC over HTTP/2` 给出了完整 ABNF，本章按该规范展开。

## Request and Response Framing

一次调用的帧序列由规范定义：

```text
Request  → Request-Headers *Length-Prefixed-Message EOS
Response → (Response-Headers *Length-Prefixed-Message Trailers) / Trailers-Only
```

请求头通过 HEADERS + CONTINUATION 帧传递，其构成是：

```text
Request-Headers  → Call-Definition *Custom-Metadata
Call-Definition  → Method Scheme Path [Authority] TE [Timeout] Content-Type
                   [Message-Type] [Message-Encoding] [Message-Accept-Encoding] [User-Agent]
```

几个必须注意的点：

- **Method 恒为 POST**。RPC 的方法名不落在 HTTP 动词上，而是编码进 `:path`，格式为 `/{Service-Name}/{method}`。HTTP/1.1 那套"用动词表达语义"的直觉在这里完全不适用。
- **TE 必须为 `trailers`**。这是用来探测链路上是否存在不兼容代理的——HTTP/1.1 没有 trailer 概念，不兼容的中间设备会直接拒绝。
- **Content-Type 以 `application/grpc` 开头**，可选 `+proto`、`+json` 或自定义后缀。服务端若发现不是 `application/grpc` 前缀，应返回 HTTP 415，避免把 gRPC 的错误响应（HTTP 状态恒为 200）误判为成功。
- **`:status` 恒为 200**。真正的成败在 trailer 的 `grpc-status` 里，这也是 gRPC 与 REST 最容易混淆的一点。

一个 unary 调用的完整帧序列（取自官方规范）：

```text
HEADERS (flags = END_HEADERS)
:method = POST
:scheme = http
:path = /google.pubsub.v2.PublisherService/CreateTopic
:authority = pubsub.googleapis.com
grpc-timeout = 1S
content-type = application/grpc+proto
grpc-encoding = gzip
authorization = Bearer y235.wef315yfh138vh31hv93hv8h3v

DATA (flags = END_STREAM)
<Length-Prefixed Message>
```

```text
HEADERS (flags = END_HEADERS)
:status = 200
grpc-encoding = gzip
content-type = application/grpc+proto

DATA
<Length-Prefixed Message>

HEADERS (flags = END_STREAM, END_HEADERS)
grpc-status = 0 # OK
trace-proto-bin = jher831yy13JHy3hc
```

响应有两条合法路径：正常路径是 Response-Headers + 若干消息 + Trailers；**Trailers-Only** 用于立即出错的场景，直接把状态放在第一个也是唯一一个 HEADERS 帧里，省掉一次往返。注意即使状态码是 OK，也必须在 Trailers 中发送。

## Length-Prefixed Message

消息体通过重复的 Length-Prefixed-Message 序列承载，落在 DATA 帧上：

```text
Length-Prefixed-Message → Compressed-Flag Message-Length Message
Compressed-Flag         → 0 / 1     ; 1 字节无符号整数
Message-Length          →           ; 4 字节无符号整数（大端）
Message                 → *{binary octet}
```

即每条消息前有一个 5 字节前缀：**1 字节压缩标志 + 4 字节大端长度**。

关键约束：

- 压缩标志为 1 表示消息按 `grpc-encoding` 声明的算法压缩；**压缩上下文不跨消息边界保持**，每条消息都要新建上下文。若未发送 `grpc-encoding`，压缩标志必须为 0。
- 一条 DATA 帧可以承载多条消息的片段，一条消息也可能横跨多条 DATA 帧——**帧边界与消息边界无关**，接收方必须按长度前缀重新组帧。这是实现 codec 时最容易踩的坑。
- 请求的 EOS 由最后一个 DATA 帧的 END_STREAM 标志表示；若流需关闭但无数据可发，必须发送一个带该标志的空 DATA 帧。

## Metadata

Custom-Metadata 是应用自定义的键值对，分两类：

| 类型 | 标识 | 编码 |
| :--- | :--- | :--- |
| ASCII-Header | 普通名称 | 可打印 ASCII（`%x20-%x7E`） |
| Binary-Header | 名称以 `-bin` 结尾 | Base64（RFC 4648 §4） |

头部名称字符集受限：`0-9 a-z _ - .`。以 `grpc-` 开头但未列入规范的名称为保留名，应用不应占用。

实现上要注意：除重名值外**头部顺序不保证保留**；重名值可能被以 `,` 连接，二进制头部必须在 Base64 解码前按 `,` 切分。规范要求实现对填充与未填充的 Base64 都能接受，但应发送未填充形式。

头部大小限制默认建议为 8 KiB，计算方式对齐 HTTP/2 的 `SETTINGS_MAX_HEADER_LIST_SIZE`：每个字段取未压缩的名称与值长度之和再加 32，二进制值按 Base64 后的长度计。

## Status Codes

gRPC 定义了 17 个状态码（0~16），通过 trailer 的 `grpc-status` 传递，取值是十进制 ASCII 字符串、无前导零：

| Code | 名称 | 含义 |
| ---: | :--- | :--- |
| 0 | `OK` | 成功 |
| 1 | `CANCELLED` | 调用被取消，通常是客户端主动取消 |
| 2 | `UNKNOWN` | 未知错误，兜底值 |
| 3 | `INVALID_ARGUMENT` | 参数不合法 |
| 4 | `DEADLINE_EXCEEDED` | 超时 |
| 5 | `NOT_FOUND` | 资源不存在 |
| 6 | `ALREADY_EXISTS` | 资源已存在 |
| 7 | `PERMISSION_DENIED` | 无权限 |
| 8 | `RESOURCE_EXHAUSTED` | 资源耗尽（配额、限流） |
| 9 | `FAILED_PRECONDITION` | 系统状态不满足前置条件 |
| 10 | `ABORTED` | 并发冲突导致中止 |
| 11 | `OUT_OF_RANGE` | 超出合法范围 |
| 12 | `UNIMPLEMENTED` | 方法未实现 |
| 13 | `INTERNAL` | 内部错误 |
| 14 | `UNAVAILABLE` | 服务不可用，通常可重试 |
| 15 | `DATA_LOSS` | 数据丢失或损坏 |
| 16 | `UNAUTHENTICATED` | 未认证 |

其中 `UNAVAILABLE` 与 `RESOURCE_EXHAUSTED` 常被重试策略区别对待——前者一般可安全重试，后者取决于业务语义。`grpc-message` 承载 Unicode 错误描述，物理上是 UTF-8 再做百分号编码；`grpc-status-details-bin` 仅在状态非 OK 时允许出现，携带 Base64 编码的 `google.rpc.Status`，其中的状态码不得与 `grpc-status` 冲突，消费方必须校验。

规范还要求实现能容忍"坏部署"：响应里出现非 200 的 HTTP 状态、非 gRPC content-type、或缺少 `grpc-status`，都必须合成一个状态传给应用层，而不是让调用挂住或崩溃。

## Channel and Transport

客户端的核心抽象是 channel，它是一组到同一目标的 subchannel 之上的虚拟连接：

- **Channel**：面向应用，持有 name resolver 与 LB policy。RPC 发起时由 LB 挑一个 subchannel。
- **Subchannel**：面向单后端实例，负责连接建立、重连退避、健康检查。
- **Transport**：HTTP/2 帧读写、流控窗口与 keepalive。

分层带来的实际效果是：连接故障被收敛在 subchannel 内部，应用层看到的是"这次调用失败"而不是"连接断了"。这也是 gRPC 相对裸 RPC 在工程上最大的收益。

codec（序列化层）在接口上是可插拔的：默认走 [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)，也可以替换为 JSON 或自定义实现——只要实现消息的编组/解组接口。跨语言互操作的前提是双方使用相同的 codec 与 `content-type` 后缀。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 框架总览与版本基线
- [gRPC Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 帧之上如何承载流与流控
- [gRPC Ecosystem](/docs/CS/Framework/gRPC/Ecosystem.md) — 拦截器、服务发现与可观测性
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md) — 默认 codec 与 IDL
- [HTTP](/docs/CS/CN/HTTP/HTTP.md) — HTTP/2 的帧、流与头部压缩基础
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md) — 自带完整软件栈的另一条路线

## References

1. [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
2. [gRFC: gRPC Status Codes](https://github.com/grpc/grpc/blob/master/doc/statuscodes.md)
3. [RFC 7540 - Hypertext Transfer Protocol Version 2 (HTTP/2)](https://datatracker.ietf.org/doc/rfc7540/)
4. [RFC 4648 - The Base16, Base32, and Base64 Data Encodings](https://datatracker.ietf.org/doc/rfc4648/)
5. [RFC 3986 - Uniform Resource Identifier (URI): Generic Syntax](https://datatracker.ietf.org/doc/rfc3986/)
6. [google.rpc.Status](https://github.com/googleapis/googleapis/blob/master/google/rpc/status.proto)
7. [gRFC A6: gRPC Retry Design](https://github.com/grpc/grpc/blob/master/doc/connection-backoff.md)
