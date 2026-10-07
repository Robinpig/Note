## Introduction

Dubbo 协议（`dubbo://`）的报文格式是理解整个 RPC 框架的解剖标本：一个固定 16 字节的二进制头，加上变长 body，请求与响应共用同一套头结构。很多面试题和博客会渲染一个细节——「序列化类型标识在请求包和响应包里的位置不一样」，用来体现协议设计的精妙。**这个说法是错的**：3.3.6 源码里请求与响应的序列化 id 都放在 `header[2]` 的低 5 位，位置完全相同；真正的差异是 `header[3]`——响应包用它放 status，请求包不使用。

另外两个需要先立正的认知：

- **协议层（Codec）与 RPC 层（Protocol）是两套体系。** `ExchangeCodec`/`DubboCodec` 负责 16 字节头与 body 的编解码，属于 `dubbo-remoting` 体系；`DubboProtocol` 负责 Invoker 的 export/refer，属于 `dubbo-rpc` 体系。谈论「Dubbo 协议」时必须先分清说的是哪一层。
- **3.3.6 的 `dubbo-rpc/` 下只有 4 个模块**，网上「Dubbo 支持 hessian/rmi/webservice/thrift 协议」的资料描述的都是旧版本——这些协议实现已整体迁到 `org.apache.dubbo.extensions`，主仓库里不是「标了废弃」，而是**整个模块都不存在**。

本文所有结论来自 Apache Dubbo **3.3.6** 官方源码（`apache/dubbo` 仓库 tag `dubbo-3.3.6`），默认值一律标注文件与行号，网上流传但与源码不符的说法会在文中显式标出。

## Dubbo Protocol Message Format

### 16-Byte Header Layout

头部长度是常量 16，magic number 是 `0xdabb`：

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/codec/ExchangeCodec.java:60-69
protected static final int HEADER_LENGTH = 16;           // :60 头固定 16 字节
protected static final short MAGIC = (short) 0xdabb;     // :62 魔数
protected static final byte MAGIC_HIGH = Bytes.bytes2high(MAGIC);  // :63 0xda
protected static final byte MAGIC_LOW = Bytes.bytes2low(MAGIC);    // :64 0xbb
protected static final byte FLAG_REQUEST = (byte) 0x80;  // :66 请求/响应标志位
protected static final byte FLAG_TWOWAY = (byte) 0x40;   // :67 twoway 标志位
protected static final byte FLAG_EVENT = (byte) 0x20;    // :68 事件标志位
protected static final int SERIALIZATION_MASK = 0x1f;    // :69 序列化 id 掩码，占低 5 位
```

完整头部布局：

| 字节偏移 | 长度 | 内容 |
| :--- | :--- | :--- |
| `[0..1]` | 2 字节 | magic `0xdabb`（高字节 `0xda`，低字节 `0xbb`） |
| `[2]` | 1 字节 | flag：bit7=请求/响应，bit6=twoway，bit5=event，低 5 位=序列化 id |
| `[3]` | 1 字节 | status，仅响应有效（请求包不使用） |
| `[4..11]` | 8 字节 | request id（long），异步请求-响应配对的依据 |
| `[12..15]` | 4 字节 | body 长度（int） |

请求编码的核心三行：

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/codec/ExchangeCodec.java:257-308（encodeRequest 摘录）
byte[] header = new byte[HEADER_LENGTH];
Bytes.short2bytes(MAGIC, header);                                 // [0..1] 魔数
header[2] = (byte) (FLAG_REQUEST | serialization.getContentTypeId());  // :262/:265 请求标志 + 序列化 id（低 5 位）
if (req.isTwoWay()) header[2] |= FLAG_TWOWAY;                     // :267 twoway 按位或
if (req.isEvent()) header[2] |= FLAG_EVENT;                       // :269 event 按位或
Bytes.long2bytes(req.getId(), header, 4);                         // [4..11] request id
Bytes.int2bytes(body.length, header, 12);                         // [12..15] body 长度
```

响应编码：

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/codec/ExchangeCodec.java:310-368（encodeResponse 摘录）
byte[] header = new byte[HEADER_LENGTH];
Bytes.short2bytes(MAGIC, header);                     // [0..1] 魔数
header[2] = serialization.getContentTypeId();         // :319 注意：响应没有 FLAG_REQUEST，序列化 id 同样在低 5 位
header[3] = status;                                   // :324-325 status，如 OK=20 / TIMEOUT=27 / SERVER_ERROR=80
Bytes.long2bytes(res.getId(), header, 4);             // [4..11] 与请求相同的 request id
Bytes.int2bytes(body.length, header, 12);             // [12..15] body 长度
```

> [!WARNING]
> 「响应包里序列化 id 的位置与请求不同」不成立。请求与响应的序列化 id 都在 `header[2] & 0x1f`；两包的真正差异是：请求 `header[2]` 额外置了 `FLAG_REQUEST`（0x80）位，且响应多用了 `header[3]` 存放 status（请求时 `header[3]` 不使用）。

解码侧先校验魔数与 `HEADER_LENGTH`，再从 `header[2]` 取 flag 与序列化 id、从 `header[3]` 取 status、从 `[4..11]` 取 request id，由 id 在 `DefaultFuture` 中找回对应的请求 future——这就是 Dubbo 在单条 TCP 连接上多路复用的全部基础。

### Protocol Version

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/Version.java:46
public static final String DEFAULT_DUBBO_PROTOCOL_VERSION = "2.0.2";
```

`DUBBO_VERSION` 默认 `"2.0.2"`，写在 body 里随请求携带。这个「2.0.2」是 Dubbo 协议自身的格式版本号，与 Dubbo 框架版本（3.3.6）无关——从 2.x 到 3.x，协议格式没有大改，这也是 `dubbo://` 长期保持兼容的原因。

### DubboCodec: Bridge from Exchange Layer to RPC Layer

```java
// dubbo-rpc/dubbo-rpc-dubbo/.../codec/DubboCodec.java:61-63
public class DubboCodec extends ExchangeCodec {       // :61 ExchangeCodec 的子类
    public static final String NAME = "dubbo";        // :63 协议名
}
```

`DubboCodec` 继承 `ExchangeCodec`（`DubboCodec.java:61`），复用 16 字节头的编解码，只覆写 body 的序列化/反序列化。网络层挂载的编解码器是 `DubboCountCodec`（负责拆包粘包并把解码计数带出来），它内部委托给 `DubboCodec`。

### Object Order of Request body

body 按 `DubboCodec` 中 `encodeRequestData` 的写入顺序固定为六个元素：

1. 服务接口全限定名（`path`）；
2. 服务版本与分组拼接的版本串（可能为空串）；
3. 方法名（`method`）；
4. 参数类型描述串（3.x 为方法描述符格式，如 `(Ljava/lang/String;)V`）；
5. 参数值数组（`arguments`）；
6. 附件表（`attachments`，可能为空）。

响应 body 的形态由 status 决定：`OK` 时先写结果值，有附件时在结果后追加 attachments；异常 status 时直接写异常对象。**顺序是硬编码的**——解码按同样下标读回，跳读任何一个字段都会导致后续字节流错位，这是抓包分析 Dubbo 协议时最常犯的错误。泛化调用也不改变这一结构：`path`/`method`/描述串照常写真实值，差异在第 5 项参数值以 Map 形态（带 `generic` 附件标注）承载——泛化是「参数表示法」的变化，不是「报文格式」的变化。

### Values of status Field

`header[3]` 的 status 由 `ChannelStatus`（`dubbo-remoting-api`）定义，常见取值：

| 值 | 含义 |
| :--- | :--- |
| 20 (`OK`) | 正常响应 |
| 25 (`CLIENT_TIMEOUT`) / 27 (`SERVER_TIMEOUT`) | 客户端/服务端超时 |
| 31 (`BAD_REQUEST`) / 35 (`BAD_RESPONSE`) | 请求/响应不合法 |
| 50 (`SERVICE_NOT_FOUND`) | 服务不存在 |
| 60 (`SERVICE_ERROR`) | 服务层异常 |
| 70 (`SERVER_ERROR`) | 服务端内部错误 |
| 80 (`SERVER_TIMEOUT`) 系列之外的 `CLIENT_ERROR=90` | 客户端错误 |

解码侧对 status 的判断很直接：非 `OK` 时响应 body 携带的是异常对象而非调用结果，`DefaultFuture.completeExceptionally` 走异常路径。服务端处理请求时若来不及构造业务结果，`DubboProtocol` 也会主动构造带异常 status 的 `Response` 回写。

### Half-Packet and Sticky-Packet: Practice of NEED_MORE_INPUT

Dubbo 协议的 TCP 流没有分隔符，拆包完全依赖解码器的状态判断。`Codec2.decode` 返回 `DecodeResult.NEED_MORE_INPUT` 时，`AbstractCodec` 侧会把 buffer 的 readerIndex 回退并暂停读取，等待下一批网络数据；magic 校验失败则用 `SKIP_SOME_INPUT` 跳过脏字节重新对齐。理解这一点才能解释 Dubbo 的两个经典现象：半包请求不会产生半执行的调用（解码不完整就不分发），以及流中出现非 `0xdabb` 开头的脏数据时连接靠跳帧自愈而不是直接断开。

## Codec2 System and Current Registration Status

### Codec and Codec2 Are Two Independent Interfaces

一个常见的想当然是「`Codec2` 继承自老的 `Codec`」——不成立。二者是**平行的两个 `@SPI` 接口**：

```java
// dubbo-remoting/dubbo-remoting-api/.../remoting/codec/Codec2.java:26-38
@SPI
public interface Codec2 {                       // :26-27 独立 @SPI，不继承任何接口
    void encode(Channel channel, ChannelBuffer buffer, Object message) throws IOException;
    Object decode(Channel channel, ChannelBuffer buffer) throws IOException;
    enum DecodeResult {                          // :33-37
        NEED_MORE_INPUT,                         // 数据不足，暂停读等待下次
        SKIP_SOME_INPUT                          // 跳过部分脏数据
    }
}

// dubbo-remoting/dubbo-remoting-api/.../remoting/codec/Codec.java:32
@Deprecated                                     // 老 Codec 已废弃
public interface Codec { ... }
```

`Codec` 是遗留接口，已标 `@Deprecated`；现行体系全部基于 `Codec2`。

### Debunk Interface Methods

**`Codec2` 接口不存在 `encodeRequestData` / `decodeBody` 这两个方法**。这两个名字属于实现类的 `protected` 方法，而非 SPI 接口契约：

- `decodeBody`：`ExchangeCodec.java:152` 的 `protected` 方法，子类 `DubboCodec` 覆写以解析 RPC body；
- `encodeRequestData`：`ExchangeCodec.java:522-530` 的 `protected` 方法，同样由 `DubboCodec` 覆写。

SPI 接口只声明 `encode` / `decode` 两个方法加一个 `DecodeResult` 枚举。把 protected 实现方法当成接口方法写进文档，会导致对「自定义编解码器需要实现什么」产生错误预期——自定义 Codec 实现的是 `Codec2.encode/decode`，拆包状态机（粘包/半包处理）也要自己在 `decode` 里用 `NEED_MORE_INPUT` 表达。

### Codec2 Extension Registration Overview

```properties
# dubbo-remoting/dubbo-remoting-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.Codec2
transport=org.apache.dubbo.remoting.transport.TransportCodec
telnet=org.apache.dubbo.remoting.telnet.TelnetCodec
exchange=org.apache.dubbo.remoting.exchange.codec.ExchangeCodec
default=org.apache.dubbo.remoting.api.pu.DefaultCodec

# dubbo-rpc/dubbo-rpc-dubbo/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.Codec2
dubbo=org.apache.dubbo.rpc.protocol.dubbo.DubboCountCodec
```

就这五条。**没有 thrift / tri / rest 的注册**——triple 协议不走 `Codec2` 体系，它通过 `WireProtocol`（`dubbo-remoting-api` 的另一个 SPI）接入，详见 [Triple](/docs/CS/Framework/Dubbo/Triple.md)。`DefaultCodec` 是 3.x 新增的抽象基类体系（`pu` 包），为端口复用/多协议探测服务。

### WireProtocol and Codec2 Division of Labor

3.x 引入 `WireProtocol` 后，编解码体系实际是双轨制：

| 维度 | `Codec2` 体系 | `WireProtocol` 体系 |
| :--- | :--- | :--- |
| 抽象层级 | 面向 `Channel` 的逐消息编解码 | 面向 `PuHandler`/探测的协议感知管线 |
| 典型实现 | `ExchangeCodec`、`DubboCountCodec` | Triple、HTTP 系协议 |
| 多协议单端口探测 | 不支持，端口绑定即协议确定 | 支持 magic/首个请求嗅探 |
| 版本走向 | 维护旧协议（dubbo、telnet、transport） | 新协议（tri、rest2、http 系列）的接入方向 |

实践含义：给 Dubbo 3 写新协议应实现 `WireProtocol`，而不是再挂一个 `Codec2` 扩展——`Codec2` 体系在 3.x 中服务于存量协议，不再扩展。

## Exchange Layer and Request-Response Mapping

### ExchangeHandler

传输层只认识字节，把字节变成「可回复的消息」的是 `ExchangeHandler`：

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/ExchangeHandler.java:28,38
public interface ExchangeHandler extends ChannelHandler, TelnetHandler {   // :28
    // 核心方法：收到 twoway 请求后由实现方产出响应对象，框架负责编码回写
    CompletableFuture<Object> reply(ExchangeChannel channel, Object request) throws RemotingException;  // :38
}
```

它同时继承了 `ChannelHandler`（连接事件）与 `TelnetHandler`（telnet 指令），`reply()` 是 twoway 请求的服务端入口。

### HeaderExchangeHandler Dispatch

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/support/HeaderExchangeHandler.java:49
public class HeaderExchangeHandler implements ChannelHandlerDelegate {
    // 收到 Response（客户端侧）：交给 DefaultFuture 完成对应的 future
    // :63-65
    DefaultFuture.received(channel, response);

    // 收到 twoway Request（服务端侧）：调 handler.reply() 并回写
    // :88-110
    CompletableFuture<Object> future = handler.reply(channel, request);
    future.whenComplete((result, t) -> {
        Response res = new Response(request.getId());
        // ... 组装响应并 channel.send(res)
    });
}
```

客户端与服务端的收发路径在这里分叉：客户端收到的是 `Response`，按 request id 唤醒等待中的 future；服务端收到的是 `Request`，进入 `reply()` 业务逻辑后回写响应。

### DefaultFuture: Mapping Table from id to future

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/support/DefaultFuture.java
private static final Map<Long, Channel> CHANNELS = new ConcurrentHashMap<>();     // :58 request id -> channel
private static final Map<Long, DefaultFuture> FUTURES = new ConcurrentHashMap<>(); // :63 request id -> future
```

两张静态表构成了 Dubbo 的请求-响应映射：发请求时以全局自增 id 建 `DefaultFuture` 入表，收到响应按 id 出表并 `complete`。这也是单连接多路复用不会串包的保证——id 全局唯一，表按 id 索引。

## Timeout Mechanism: Time-Wheel Timer, Not a Scanning Thread

### Debunk RemotingInvocationTimeoutScan

网上大量资料描述「`RemotingInvocationTimeoutScan` 线程每 30ms 扫描所有 future 检查超时」——这是 2.x 早期的实现，**3.3.6 中 `RemotingInvocationTimeoutScan` 这个类不存在**，也不存在「每 30ms 全表扫描」的行为。

### 3.3.6 Actual Implementation: HashedWheelTimer + Single Future Single Timeout

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/support/DefaultFuture.java:65-67
private static final HashedWheelTimer TIMEOUT_TIMER = new HashedWheelTimer(
    new NamedThreadFactory("dubbo-future-timeout", true),   // 守护线程
    30, TimeUnit.MILLISECONDS);                             // tick 间隔 30ms

// :107-110 每个 future 创建时挂一个独立 timeout
timeoutCheckTask = new TimeoutCheckTask(id);
timeout = TIMEOUT_TIMER.newTimeout(timeoutCheckTask, future.getTimeout(), TimeUnit.MILLISECONDS);
```

每个 `DefaultFuture` 创建时独立注册一个 `newTimeout(task, future.getTimeout(), MILLISECONDS)`（`:107-110`），超时检查任务 `TimeoutCheckTask` 在 `:311-348`：触发后把 future 从 `FUTURES`/`CHANNELS` 移除，标记 `TIMEOUT` 并唤醒等待线程。30ms 是时间轮的 **tick 精度**（到期检查的分辨率），不是「扫描周期」——时间轮按到期时间哈希到槽位，不存在全表遍历。这是 O(1) 的定时器模型，与「扫描全部 future」的 O(n) 模型是两回事。

### Default Timeout Value

```java
// dubbo-common/src/main/java/org/apache/dubbo/constants/CommonConstants.java:147
int DEFAULT_TIMEOUT = 1000;  // 默认方法调用超时 1000ms
```

即未配置 `timeout` 时，一次调用 1 秒即超时。超时后客户端 future 标记失败，但服务端可能仍在执行——这就是 Dubbo 经典的「超时后 provider 仍在跑」问题，与协议无关，是异步映射模型的固有语义。

## Protocol Family Status and Migration Notes

### dubbo-rpc Module Overview

`dubbo-rpc/` 下**只有 4 个模块**：

- `dubbo-rpc-api`：`Protocol` SPI 接口与公共逻辑，另注册 5 个 wrapper；
- `dubbo-rpc-dubbo`：`DubboProtocol`（`dubbo://`）；
- `dubbo-rpc-injvm`：`InjvmProtocol`（`injvm://`，本地调用）;
- `dubbo-rpc-triple`：`TripleProtocol`（`tri` / `grpc` / `rest2`）。

对应协议扩展注册：

```properties
# dubbo-rpc-api
listener=...ProtocolListenerWrapper        # 监听器包装
serializationwrapper=...ProtocolSerializationWrapper
securitywrapper=...ProtocolSecurityWrapper
invokercount=...InvokerCountCallbackWrapper
mock=...MockProtocol                       # mock 支持

# dubbo-rpc-dubbo
dubbo=org.apache.dubbo.rpc.protocol.dubbo.DubboProtocol

# dubbo-rpc-triple
tri=org.apache.dubbo.rpc.protocol.tri.TripleProtocol
grpc=org.apache.dubbo.rpc.protocol.tri.GrpcProtocol
rest2=org.apache.dubbo.rpc.protocol.tri.RestProtocol

# dubbo-rpc-injvm
injvm=org.apache.dubbo.rpc.protocol.injvm.InjvmProtocol
```

### Debunk: Those "Non-Existent" Protocol Modules

| 网传模块 | 3.3.6 现状 |
| :--- | :--- |
| `dubbo-rpc-grpc` | **不存在**。gRPC 兼容由 `dubbo-rpc-triple` 的 `grpc=` 承担 |
| `dubbo-rpc-rest` | **不存在**。REST 由 `dubbo-rpc-triple` 的 `rest2=` 承担 |
| `dubbo-rpc-hessian` | **不存在** |
| rmi / webservice / http / thrift 独立模块 | **不存在** |

需要特别强调措辞：这些协议在主仓库**整体不存在**，而不是「源码还在、标了 @Deprecated」。它们已迁移到 `org.apache.dubbo.extensions`（`dubbo-spi-extensions` 仓库），需要时按扩展方式引入 artifact（如 `dubbo-rpc-hessian` 的扩展版）。另一个佐证：除 `DubboProtocol.getDubboProtocol()` 这个静态方法外，**3.3.6 没有任何协议实现类标注 `@Deprecated`**——因为根本没有旧实现可标。

> [!TIP]
> 判断「某协议在当前 Dubbo 3 里是否可用」的最快方法：看 `dubbo-rpc/` 的模块列表与各模块 `META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol` 文件。主仓库内可用协议就是 `dubbo`、`tri`、`grpc`、`rest2`、`injvm` 五个名字，其余一律需要引入 extensions 依赖。

## Default Value Summary Table

| 项目 | 值 | 源码位置 |
| :--- | :--- | :--- |
| 头部长度 | 16 字节 | `ExchangeCodec.java:60` |
| 魔数 | `0xdabb` | `ExchangeCodec.java:62` |
| flag 位 | 请求 `0x80`、twoway `0x40`、event `0x20`、序列化掩码 `0x1f` | `ExchangeCodec.java:66-69` |
| 序列化 id 位置 | `header[2]` 低 5 位（请求与响应相同） | `ExchangeCodec.java:262/319` |
| status 位置 | `header[3]`，仅响应有效 | `ExchangeCodec.java:324-325` |
| 协议格式版本 | `"2.0.2"` | `Version.java:46` |
| `Codec2` 注册 | transport/telnet/exchange/default + dubbo | 各模块 SPI 文件 |
| 时间轮 tick | 30ms | `DefaultFuture.java:65-67` |
| 默认调用超时 | 1000ms | `CommonConstants.java:147` |
| `dubbo-rpc` 模块 | api / dubbo / injvm / triple 共 4 个 | 目录结构 |
| 可用协议名 | `dubbo`、`tri`、`grpc`、`rest2`、`injvm` | 各模块 SPI 文件 |

## Pitfall List

| 直觉/网传说法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「序列化 id 在请求/响应包位置不同」 | 都在 `header[2] & 0x1f`；差异在 `header[3]` status | 对协议的理解从根上错位 |
| 「`Codec2` 继承 `Codec`」 | 平行的两个 SPI，`Codec` 已 `@Deprecated` | 误读遗留代码结构 |
| 「接口有 `encodeRequestData` / `decodeBody`」 | 是 `ExchangeCodec` 的 protected 方法，非接口契约 | 自定义 Codec 时实现错方法 |
| 「Codec2 注册了 thrift/tri/rest」 | 只有 transport/telnet/exchange/default/dubbo 五条；triple 走 `WireProtocol` | 在 Codec2 体系里找不到 triple 实现 |
| 「`RemotingInvocationTimeoutScan` 每 30ms 扫描」 | 类已不存在；现为 `HashedWheelTimer` + 每 future 独立 timeout | 误判超时精度与性能模型 |
| 「时间轮 30ms = 每 30ms 扫全表」 | 30ms 是 tick 精度，O(1) 定时非 O(n) 扫描 | 错误的容量规划结论 |
| 「Dubbo 内置 hessian/rmi/webservice/thrift 协议」 | `dubbo-rpc/` 仅 4 个模块，旧协议已迁 `dubbo-spi-extensions` | 配置协议名后启动报找不到扩展 |
| 「有 `dubbo-rpc-grpc` / `dubbo-rpc-rest` 模块」 | 不存在，由 triple 的 `grpc=`/`rest2=` 承担 | 依赖引错，排查方向错误 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Triple](/docs/CS/Framework/Dubbo/Triple.md)
- [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)
- [remoting](/docs/CS/Framework/Dubbo/remoting.md)
- [Transporter](/docs/CS/Framework/Dubbo/Transporter.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

1. [Apache Dubbo 3.3.6 源码（tag dubbo-3.3.6）](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
2. [Dubbo 协议官方文档](https://cn.dubbo.apache.org/zh-cn/docs3-v2/java-sdk/reference-manual/protocol/dubbo/)
3. [dubbo-rpc-dubbo 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-rpc/dubbo-rpc-dubbo)
