# gRPC Java Status Codes and Metadata

## Introduction

gRPC 把"成败"从 HTTP 状态码里剥离出来：HTTP 状态恒为 200，真正的成败放在 trailer 的 `grpc-status`——线协议层为何如此规定见 [Architecture](/docs/CS/Framework/gRPC/Architecture.md)。本页沿 grpc-java 1.75.0 源码看三件事：17 个状态码的枚举定义、trailer 里 ASCII 状态码的解析、以及 metadata 的二进制头（`-bin`）处理。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。以下片段均取自该 tag。

三个反直觉点：

- **状态码用 fallthrough 解析**：`Status.fromCodeValueSlow` 用 `switch` 的 fallthrough 处理 1~2 位 ASCII 十进制码，最多两位（0~16），其它一律 `UNKNOWN`。
- **trailer 里 OK 也必须有**：即使调用成功，`grpc-status = 0` 也必须出现在 Trailers 中；立即失败走 Trailers-Only（唯一 HEADERS 帧）。
- **二进制头 Base64 去填充**：`Metadata.BASE64_ENCODING_OMIT_PADDING = base64().omitPadding()`，发送无填充形式，key 名强制小写化。

## The 17 Status Codes

`Status.Code` 枚举把 0~16 写死，注释强调"新增码不能与历史值冲突"：

```java
// api/src/main/java/io/grpc/Status.java
public enum Code {
  OK(0),
  CANCELLED(1),
  UNKNOWN(2),
  INVALID_ARGUMENT(3),
  DEADLINE_EXCEEDED(4),
  NOT_FOUND(5),
  ALREADY_EXISTS(6),
  // ... PERMISSION_DENIED(7) ~ ABORTED(10) ...
  RESOURCE_EXHAUSTED(8),
  // ...
  INTERNAL(13),
  UNAVAILABLE(14),
  DATA_LOSS(15),
  UNAUTHENTICATED(16);
  // ...
}
```

| Code | 名称 | 含义 | 典型处理 |
| ---: | :--- | :--- | :--- |
| 0 | OK | 成功 | — |
| 1 | CANCELLED | 调用被取消 | 通常不重试 |
| 2 | UNKNOWN | 兜底 | — |
| 3 | INVALID_ARGUMENT | 参数不合法 | 不重试 |
| 4 | DEADLINE_EXCEEDED | 超时 | 视幂等性 |
| 5 | NOT_FOUND | 资源不存在 | 不重试 |
| 6 | ALREADY_EXISTS | 已存在 | 视语义 |
| 7 | PERMISSION_DENIED | 无权限 | 不重试 |
| 8 | RESOURCE_EXHAUSTED | 配额/限流 | 退避后重试 |
| 9 | FAILED_PRECONDITION | 前置条件不满足 | 不重试 |
| 10 | ABORTED | 并发冲突 | 可重试 |
| 11 | OUT_OF_RANGE | 越界 | 不重试 |
| 12 | UNIMPLEMENTED | 方法未实现 | 不重试 |
| 13 | INTERNAL | 内部错误 | 不重试 |
| 14 | UNAVAILABLE | 服务不可用 | 可重试 |
| 15 | DATA_LOSS | 数据损坏 | 不重试 |
| 16 | UNAUTHENTICATED | 未认证 | 刷新凭据后重试 |

`UNAVAILABLE` 与 `RESOURCE_EXHAUSTED` 常被重试策略区别对待——前者一般可安全重试，后者取决于业务语义。

## Parsing the Trailer Code

trailer 里的 `grpc-status` 是十进制 ASCII 字符串。Java 用 `fromCodeValue(byte[])` 解析，慢路径用 switch fallthrough 处理两位数字：

```java
// api/src/main/java/io/grpc/Status.java
private static Status fromCodeValue(byte[] asciiCodeValue) {
  if (asciiCodeValue.length == 1 && asciiCodeValue[0] == '0') {
    return Status.OK;
  }
  return fromCodeValueSlow(asciiCodeValue);
}

@SuppressWarnings("fallthrough")
private static Status fromCodeValueSlow(byte[] asciiCodeValue) {
  int index = 0;
  int codeValue = 0;
  switch (asciiCodeValue.length) {
    case 2:
      if (asciiCodeValue[index] < '0' || asciiCodeValue[index] > '9') {
        break;
      }
      codeValue += (asciiCodeValue[index++] - '0') * 10;
      // fall through
    case 1:
      if (asciiCodeValue[index] < '0' || asciiCodeValue[index] > '9') {
        break;
      }
      codeValue += asciiCodeValue[index] - '0';
      if (codeValue < STATUS_LIST.size()) {
        return STATUS_LIST.get(codeValue);
      }
      break;
    default:
      break;
  }
  return UNKNOWN.withDescription("Unknown code " + new String(asciiCodeValue, US_ASCII));
}
```

`fromCodeValue(int)` 走快路径：越界（<0 或 ≥17）也返回 `UNKNOWN` 并带描述，而不是抛异常——规范要求实现"容忍坏部署"。

```java
// api/src/main/java/io/grpc/Status.java
public static Status fromCodeValue(int codeValue) {
  if (codeValue < 0 || codeValue >= STATUS_LIST.size()) {
    return UNKNOWN.withDescription("Unknown code " + codeValue);
  } else {
    return STATUS_LIST.get(codeValue);
  }
}
```

## grpc-status-details-bin

非 OK 状态可携带 `google.rpc.Status`（Base64）作为详情。`grpc-message` 是 Unicode 错误描述，物理上是 UTF-8 再做百分号编码；解码遇到非法序列时不得报错，最坏保留原始百分号形式。规范要求 `grpc-status-details-bin` 里的状态码不得与 `grpc-status` 冲突，消费方必须校验。

## Metadata: ASCII vs Binary Headers

`Metadata` 把头分两类：普通 ASCII 头与 `-bin` 结尾的二进制头。源码常量：

```java
// api/src/main/java/io/grpc/Metadata.java
public static final String BINARY_HEADER_SUFFIX = "-bin";
static final BaseEncoding BASE64_ENCODING_OMIT_PADDING = BaseEncoding.base64().omitPadding();
```

key 名在构造时**小写化**并校验字符集（tchar），pseudo header（`:method` 等）允许首字符是 `:`：

```java
// api/src/main/java/io/grpc/Metadata.java
private static String validateName(String n, boolean pseudo) {
  checkNotNull(n, "name");
  checkArgument(!n.isEmpty(), "token must have at least 1 tchar");
  if (n.equals("connection")) {
    logger.log(Level.WARNING, "Metadata key is 'Connection', which should not be used. ...");
  }
  for (int i = 0; i < n.length(); i++) {
    char tChar = n.charAt(i);
    if (pseudo && tChar == ':' && i == 0) {
      continue;
    }
    checkArgument(VALID_T_CHARS.get(tChar), "Invalid character '%s' in key name '%s'", tChar, n);
  }
  return n;
}

private Key(String name, boolean pseudo, Object marshaller) {
  this.originalName = checkNotNull(name, "name");
  this.name = validateName(this.originalName.toLowerCase(Locale.ROOT), pseudo);
  this.nameBytes = this.name.getBytes(US_ASCII);
  this.marshaller = marshaller;
}
```

序列化时二进制值用去填充的 Base64：

```java
// api/src/main/java/io/grpc/Metadata.java
sb.append(BASE64_ENCODING_OMIT_PADDING.encode(valueAsBytes(i)));
```

> [!NOTE]
> 除重名值外，头部顺序不保证保留；重名值可能被以 `,` 连接，二进制头必须在 Base64 解码前按 `,` 切分。发送用无填充 Base64，但实现对填充与未填充都要能接受。

## Status in the Call Chain

客户端收到 trailer 后，`ClientStreamListenerImpl.closed(Status status, Metadata trailers)` 把状态交给应用 listener；服务端则由 `ServerCallImpl.closeInternal` 调 `stream.close(status, trailers)`，transport 把 status code 写进 `grpc-status`、描述写进 `grpc-message`（见 [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md)）。

| 来源 | 状态码 | 触发点 |
| :--- | :--- | :--- |
| 客户端 deadline 到期 | DEADLINE_EXCEEDED(4) | `CancellationHandler.run()` |
| 客户端主动 cancel | CANCELLED(1) | `ClientCallImpl.cancelInternal()` |
| 服务端超时 | DEADLINE_EXCEEDED(4) | `ServerStreamCancellationListener` |
| 服务端业务异常 | UNKNOWN(2) / INTERNAL(13) | handler 抛异常 / close |
| unary 返回 OK 但无消息 | INTERNAL(13) | `ServerCallImpl.closeInternal` 校验 |

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与纠偏
- [Framing](/docs/CS/Framework/gRPC/Framing.md) — 状态如何随 trailer 帧传输
- [ClientCallChain](/docs/CS/Framework/gRPC/ClientCallChain.md) — 客户端如何解析状态
- [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md) — 服务端如何写状态
- [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md) — CANCELLED / DEADLINE_EXCEEDED 的产生
- [Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 流上的错误与 trailer 传递

## References

- [grpc-java v1.75.0 Status.java](https://github.com/grpc/grpc-java/blob/v1.75.0/api/src/main/java/io/grpc/Status.java)
- [grpc-java v1.75.0 Metadata.java](https://github.com/grpc/grpc-java/blob/v1.75.0/api/src/main/java/io/grpc/Metadata.java)
- [gRFC: Status Codes](https://github.com/grpc/grpc/blob/master/doc/statuscodes.md)
- [google.rpc.Status](https://github.com/googleapis/googleapis/blob/master/google/rpc/status.proto)
