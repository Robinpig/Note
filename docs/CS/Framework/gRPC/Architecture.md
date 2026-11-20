# gRPC over HTTP/2: The Wire Protocol

## Introduction

gRPC 的"薄"体现在它几乎没有自定义传输协议——它把一次 RPC 完整地映射到 HTTP/2 帧序列上。理解 gRPC 的线协议，本质上就是理解三件事：请求/响应如何拆成 HEADERS / DATA / Trailers、消息体如何定界、状态与元数据如何通过头部传递。本文以 gRFC 规范为准，并用 grpc-java 1.75.0 的源码片段佐证实现如何落地。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）；线协议以 [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md) 为准。实现细节见 [Framing](/docs/CS/Framework/gRPC/Framing.md)。

两个反直觉点：

- **HTTP 状态码恒为 200**：成败在 trailer 的 `grpc-status`，用 REST 的"看 HTTP 状态码"直觉判断会全部误判为成功。
- **`:method` 恒为 POST**：RPC 方法名编码进 `:path`（`/Service/Method`），HTTP 动词不携带语义。

## Request and Response Framing

规范定义的帧序列：

```text
Request  → Request-Headers *Length-Prefixed-Message EOS
Response → (Response-Headers *Length-Prefixed-Message Trailers) / Trailers-Only
```

请求头构成：

```text
Request-Headers  → Call-Definition *Custom-Metadata
Call-Definition  → Method Scheme Path [Authority] TE [Timeout] Content-Type
                   [Message-Type] [Message-Encoding] [Message-Accept-Encoding] [User-Agent]
```

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

响应有两条合法路径：正常路径是 Response-Headers + 若干消息 + Trailers；**Trailers-Only** 用于立即出错，把状态放在第一个也是唯一一个 HEADERS 帧里，省掉一次往返。**即使状态码是 OK，也必须在 Trailers 中发送。**

## Mandatory Headers

| Header | 约束 | 作用 |
| :--- | :--- | :--- |
| `:method` | 恒为 `POST` | RPC 动词语义不在这里 |
| `:path` | `/{Service}/{Method}` | 方法名编码点 |
| `TE` | 必须为 `trailers` | 探测不兼容 HTTP/1 代理 |
| `content-type` | 以 `application/grpc` 开头 | 可选 `+proto` / `+json` 后缀；非此前缀应返回 HTTP 415 |
| `:status` | 恒为 200 | 成败看 `grpc-status` |
| `grpc-timeout` | 可选 | 相对值编码，见 [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md) |

Java 实现里 `GrpcUtil` 定义了 `TE_HEADER`、`TIMEOUT_KEY` 等 key；`Metadata.Key` 在构造时小写化并校验 tchar 字符集（见 [Status](/docs/CS/Framework/gRPC/Status.md)）。

## Length-Prefixed Message

消息体是重复的 5 字节前缀 + 载荷，落在 DATA 帧：

```text
Length-Prefixed-Message → Compressed-Flag Message-Length Message
Compressed-Flag         → 0 / 1     ; 1 字节无符号整数
Message-Length          →           ; 4 字节无符号整数（大端）
```

Java 侧由 `MessageFramer` / `MessageDeframer` 实现，帧头常量与位掩码校验、组帧状态机见 [Framing](/docs/CS/Framework/gRPC/Framing.md)。关键约束：压缩上下文不跨消息边界；帧边界与消息边界无关，接收方必须按长度前缀重新组帧。

## Metadata Rules

Custom-Metadata 两类：ASCII 头（普通名）与二进制头（以 `-bin` 结尾，Base64 编码）。头部名字符集 `0-9 a-z _ - .`；以 `grpc-` 开头但未列入规范的名称为保留名。除重名值外顺序不保证保留；二进制头按 `,` 切分后 Base64 解码。头部大小默认建议 8 KiB（Java `DEFAULT_MAX_HEADER_LIST_SIZE = 8192`，对齐 `SETTINGS_MAX_HEADER_LIST_SIZE`）。

## Status Codes in Trailers

17 个状态码（0~16）通过 `grpc-status` 传递，十进制 ASCII、无前导零；`grpc-message` 是百分号编码的 UTF-8；`grpc-status-details-bin` 仅非 OK 时允许，携带 Base64 的 `google.rpc.Status`。完整码表与 Java 枚举/解析源码见 [Status](/docs/CS/Framework/gRPC/Status.md)。

规范要求实现"容忍坏部署"：非 200 HTTP 状态、非 gRPC content-type、缺失 `grpc-status` 都必须合成一个状态上抛，不能让调用挂死。Java `Status.fromCodeValue` 越界返回 `UNKNOWN` 而非抛异常，正是这条的落地。

## Cross-Language Caveats

同一份线协议，各语言实现的**默认值**差异很大，排查跨语言问题时必须按实现核对：

| 维度 | grpc-java 1.75.0 | grpc-go 1.84.x |
| :--- | :--- | :--- |
| 默认 header 上限 | 8192（8 KiB） | 16 MiB（8 KiB 是"计划值"） |
| 初始流控窗口 | 1 MiB + BDP 自动调优 | 64 KiB 默认 + BDP ping |
| keepalive 客户端 | 默认关闭 | 默认关闭 |
| keepalive 服务端 | 2h | 2h |

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与版本基线
- [Framing](/docs/CS/Framework/gRPC/Framing.md) — 5 字节头与组帧状态机
- [Status](/docs/CS/Framework/gRPC/Status.md) — 状态码枚举与 trailer 解析
- [Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 帧之上如何承载流
- [HTTP](/docs/CS/CN/HTTP/HTTP.md) — HTTP/2 帧、流与头部压缩基础
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md) — 自带完整协议栈的另一条路线

## References

- [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
- [gRFC: gRPC Status Codes](https://github.com/grpc/grpc/blob/master/doc/statuscodes.md)
- [RFC 7540 - HTTP/2](https://datatracker.ietf.org/doc/rfc7540/)
- [RFC 4648 - Base64](https://datatracker.ietf.org/doc/rfc4648/)
- [google.rpc.Status](https://github.com/googleapis/googleapis/blob/master/google/rpc/status.proto)
