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
protected static final byte MAGIC_HIGH = Bytes.short2bytes(MAGIC)[0];  // :63 0xda
protected static final byte MAGIC_LOW = Bytes.short2bytes(MAGIC)[1];    // :64 0xbb
protected static final byte FLAG_REQUEST = (byte) 0x80;  // :66 请求/响应标志位
protected static final byte FLAG_TWOWAY = (byte) 0x40;   // :67 twoway 标志位
protected static final byte FLAG_EVENT = (byte) 0x20;    // :68 事件标志位
protected static final int SERIALIZATION_MASK = 0x1f;    // :69 序列化 id 掩码，占低 5 位
```

> [!NOTE]
> `MAGIC_HIGH` / `MAGIC_LOW` 的写法是 `Bytes.short2bytes(MAGIC)[0]` / `[1]`（`ExchangeCodec.java:63-64`）——`Bytes` 类里**没有** `bytes2high` / `bytes2low` 方法，只有 `short2bytes`（`dubbo-common/.../io/Bytes.java:71-93`）。这里取数组下标而非移位，是因为 `0xdabb` 的高字节恰好是 `0xda`、低字节是 `0xbb`，与 `Bytes.short2bytes` 的写出顺序（大端）一致。

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
// dubbo-remoting/dubbo-remoting-api/.../exchange/codec/ExchangeCodec.java:257-277（encodeRequest 摘录）
byte[] header = new byte[HEADER_LENGTH];
Bytes.short2bytes(MAGIC, header);                                 // :262 魔数写入 [0..1]
header[2] = (byte) (FLAG_REQUEST | serialization.getContentTypeId());  // :265 请求标志 + 序列化 id（低 5 位）
if (req.isTwoWay()) header[2] |= FLAG_TWOWAY;                     // :268 twoway 按位或
if (req.isEvent()) header[2] |= FLAG_EVENT;                       // :271 event 按位或
Bytes.long2bytes(req.getId(), header, 4);                         // :275 request id
Bytes.int2bytes(body.length, header, 12);                         // body 长度
```

响应编码：

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/codec/ExchangeCodec.java:310-327（encodeResponse 摘录）
byte[] header = new byte[HEADER_LENGTH];
Bytes.short2bytes(MAGIC, header);                     // :317 魔数写入 [0..1]
header[2] = serialization.getContentTypeId();         // :319 注意：响应没有 FLAG_REQUEST，序列化 id 同样在低 5 位
if (res.isHeartbeat()) header[2] |= FLAG_EVENT;       // :320-322 心跳响应置 event 位
header[3] = status;                                   // :324-325 status，如 OK=20 / SERVICE_ERROR=70 / SERVER_ERROR=80
Bytes.long2bytes(res.getId(), header, 4);             // :327 与请求相同的 request id
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

`header[3]` 的 status 由 `org.apache.dubbo.remoting.exchange.Response` 的常量定义（`dubbo-remoting-api`），**不是**由 `ChannelStatus` 枚举定义——3.3.6 的 `dubbo-remoting` 下**不存在 `ChannelStatus` 这个类**，全仓库搜不到。真实取值：

| 值 | 常量（`Response.java`） | 含义 |
| :--- | :--- | :--- |
| 20 | `OK`（`:26`） | 正常响应 |
| 30 | `CLIENT_TIMEOUT`（`:36`） | 客户端超时 |
| 31 | `SERVER_TIMEOUT`（`:41`） | 服务端超时 |
| 40 | `BAD_REQUEST`（`:51`） | 请求不合法（如反序列化失败） |
| 60 | `SERVICE_NOT_FOUND`（`:61`） | 服务不存在 |
| 70 | `SERVICE_ERROR`（`:66`） | 服务层业务异常 |
| 80 | `SERVER_ERROR`（`:71`） | 服务端内部错误 |
| 90 | `CLIENT_ERROR`（`:76`） | 客户端错误 |

> [!WARNING]
> 网上流传的「25 = CLIENT_TIMEOUT / 27 = SERVER_TIMEOUT / 31 = BAD_REQUEST / 35 = BAD_RESPONSE / 50 = SERVICE_NOT_FOUND / 60 = SERVICE_ERROR / 70 = SERVER_ERROR」这组取值**全部对不上源码**。3.3.6 的 `Response` 只有上表这 8 个常量，**没有 `BAD_RESPONSE` 这个常量**（响应不合法复用 `BAD_REQUEST = 40`），也没有 `50` 与 `35` 这两个值。另外 `Response` 的默认状态是 `OK`（`Response.java:87`，`private byte mStatus = OK;`）。

解码侧对 status 的判断很直接：非 `OK` 时响应 body 携带的是异常对象而非调用结果，`DefaultFuture.completeExceptionally` 走异常路径。服务端处理请求时若来不及构造业务结果，`DubboProtocol` 也会主动构造带异常 status 的 `Response` 回写。具体路径见 `HeaderExchangeHandler.handleRequest`（`exchange/support/header/HeaderExchangeHandler.java:90-118`）：业务 `reply()` 的 future 正常完成则 `res.setStatus(Response.OK)`，抛异常则 `res.setStatus(Response.SERVICE_ERROR)`；而请求本身解码失败时（`req.isBroken()`）直接回 `Response.BAD_REQUEST`（`:96-108`）。

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

## Protocol Interface export and refer

`org.apache.dubbo.rpc.Protocol` 是框架与具体协议实现之间的 SPI 边界，两个核心方法都是 `@Adaptive`，由 adaptive 扩展按 URL 的 `protocol` 参数分发：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/Protocol.java:58-117
@SPI(value = "dubbo", scope = ExtensionScope.FRAMEWORK)
public interface Protocol {
    int getDefaultPort();                                    // :66 未配端口时由实现提供（dubbo=20880, tri=50051）
    @Adaptive <T> Exporter<T> export(Invoker<T> invoker);    // :82 服务端暴露
    @Adaptive <T> Invoker<T> refer(Class<T> type, URL url);  // :100 消费端引用
    void destroy();                                          // 销毁全部 export/refer
    default List<ProtocolServer> getServers() { return Collections.emptyList(); } // :115 3.3 新增
}
```

接口 javadoc 的约定：`export()` 收到的 `Invoker` 由框架实现（协议不应关心其实现），`refer()` 返回的 `Invoker` 由协议自己实现（调用其 `invoke()` 时协议负责真正发请求）。`export()` 必须幂等（同一 URL 暴露多次无副作用），这正与下面 server 按 address 复用的设计直接相关。3.3.6 的 `Protocol` 已删除旧版 `getName()`，协议名完全由 SPI 扩展名决定（见 [Triple](/docs/CS/Framework/Dubbo/Triple.md)）。

## SPI Wrapper Mechanism ProtocolFilterWrapper and ProtocolListenerWrapper

`Protocol` 的真实实现（`DubboProtocol`、`TripleProtocol`）不会被调用方直接拿到。ExtensionLoader 创建扩展实例后会自动用所有 **Wrapper 类**（实现 `Protocol` 且存在单参数 `Protocol` 构造器的类）层层包裹。3.3.6 的 wrapper 分散在**三个** SPI 文件里：

```properties
# dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol
listener=org.apache.dubbo.rpc.protocol.ProtocolListenerWrapper
serializationwrapper=org.apache.dubbo.rpc.protocol.ProtocolSerializationWrapper
securitywrapper=org.apache.dubbo.rpc.protocol.ProtocolSecurityWrapper
invokercount=org.apache.dubbo.rpc.protocol.InvokerCountWrapper
mock=org.apache.dubbo.rpc.support.MockProtocol          # ← 不是 wrapper，是正常扩展点

# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol
filter=org.apache.dubbo.rpc.cluster.filter.ProtocolFilterWrapper

# dubbo-plugin/dubbo-qos/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol
qos=org.apache.dubbo.qos.protocol.QosProtocolWrapper      # ← 仅当 dubbo-qos 模块在 classpath
```

同一个 SPI 文件里既有 wrapper 也有正常扩展点——**判据不是文件、也不是名字，而是构造器签名**（见本节末尾的说明）。

包裹顺序由 `org.apache.dubbo.common.extension.support.WrapperComparator` 决定，机制在 `ExtensionLoader.createExtension` 里：

```java
// dubbo-common/.../common/extension/ExtensionLoader.java:789-800
List<Class<?>> wrapperClassesList = new ArrayList<>();
if (cachedWrapperClasses != null) {
    wrapperClassesList.addAll(cachedWrapperClasses);
    wrapperClassesList.sort(WrapperComparator.COMPARATOR);   // :792 按 order 升序
    Collections.reverse(wrapperClassesList);                    // :793 翻转为降序
}
if (CollectionUtils.isNotEmpty(wrapperClassesList)) {
    for (Class<?> wrapperClass : wrapperClassesList) {
        ...
        instance = (T) wrapperClass.getConstructor(type).newInstance(instance);   // :800 依次包裹
```

`WrapperComparator.parseOrder`（`dubbo-common/.../extension/support/WrapperComparator.java:70-86`）先读 `@Activate(order=...)`，其次读 `@Wrapper(order=...)`，都没有则 order 为 0。

包裹方向的推导（**这一步容易搞反**）：`sort` 是**升序**（`WrapperComparator.compare` 返回 `n1 > n2 ? 1 : -1`），`reverse` 后数组变成**按 order 降序**，而 `for` 循环**按数组顺序依次包裹**（每次 `new` 出新 wrapper 把上一个包进去）。因此**数组里第一个被包的成为最内层、最后一个成为最外层**——也就是 **order 值越小越靠外**。

参与 `Protocol` 包裹的 wrapper 及其真实 order（3.3.6 源码逐一核实）：

| wrapper 类 | order | 层级 | 职责 |
| :--- | :--- | :--- | :--- |
| `InvokerCountWrapper` | `Integer.MIN_VALUE + 1000` | **最外层** | `refer` 时套 `ReferenceCountInvokerWrapper` |
| `ProtocolSerializationWrapper` | 0（`@Activate` 未写 order） | 次外层 | 把服务 URL 注册进 `PermittedSerializationKeeper` |
| `ProtocolFilterWrapper` | 100 | 中层 | 构造 Filter 链 |
| `ProtocolSecurityWrapper` | 200 | 内层 | 导出/引用时把接口签名类型注册进安全 allowlist |
| `ProtocolListenerWrapper` | 200 | 内层 | 套 `ListenerExporterWrapper` / `ListenerInvokerWrapper` |
| `QosProtocolWrapper` | 200 | 内层 | QoS 协议入口（`dubbo-plugin/dubbo-qos`，仅当该模块在 classpath） |

```java
// dubbo-cluster/.../cluster/filter/ProtocolFilterWrapper.java:35
@Activate(order = 100)               // 中层：负责构建 Filter 链
public class ProtocolFilterWrapper implements Protocol { ... }

// dubbo-rpc/.../rpc/protocol/ProtocolListenerWrapper.java:46
@Activate(order = 200)               // 内层：包裹 Exporter/Invoker 监听器
public class ProtocolListenerWrapper implements Protocol { ... }

// dubbo-rpc/.../rpc/protocol/InvokerCountWrapper.java:27
@Activate(order = Integer.MIN_VALUE + 1000)   // 最外层
public class InvokerCountWrapper implements Protocol { ... }
```

> [!NOTE]
> **order 相同的 wrapper 之间没有语义顺序。** `ProtocolSecurityWrapper` / `ProtocolListenerWrapper` / `QosProtocolWrapper` 三者 order 都是 200，而 `cachedWrapperClasses` 是 `ConcurrentHashSet`（`ExtensionLoader.java:1400`），其迭代顺序不是按 order 排的；`Collections.sort` 是稳定排序但 `reverse` 会把同 order 元素的相对次序也一并倒转。因此这三者的嵌套先后**取决于 Class 的哈希分布**，不要依赖它。

消费端的最终 Invoker 由外到内是：`ReferenceCountInvokerWrapper` → Filter 链 → `ListenerInvokerWrapper` → 真实 Invoker。服务端侧 Filter 链作用在 **Invoker** 上（`ProtocolFilterWrapper.export` 先 `buildInvokerChain` 再交给内层 `protocol.export`），`ListenerExporterWrapper` 作用在 **Exporter** 上。

> [!WARNING]
> 「Wrapper 类」的判定**不靠命名约定，靠构造器签名**：`ExtensionLoader.isWrapperClass`（`:1409-1420`）检查该类是否存在唯一一个「参数类型 == 被扩展的接口类型」的构造器。`loadClass` 在 `:1286-1289` 先判 `isWrapperClass(clazz)`，命中就 `cacheWrapperClass(clazz)` 而**不注册成可按名获取的扩展**——所以 SPI 文件里的 `listener=` / `filter=` 这些名字**取不到**（`getExtension("listener")` 会失败），它们只用于让类被加载进 wrapper 缓存。反之 `mock=` / `injvm=` / `dubbo=` 对应的类没有单参 `Protocol` 构造器，是正常扩展点，仍可按名获取。3.3.6 里**没有**「SPI 扩展名以 `wrapper` 开头就自动包裹」这种规则。

各 wrapper 都用同一道守卫把注册中心地址排除在外：`if (UrlUtils.isRegistry(url)) return protocol.xxx(url);` —— 当 URL 是注册中心地址（`registry://`）时直接透传，只对本协议地址（`dubbo://`、`tri://` 等）套链。`ProtocolListenerWrapper.export` 还有一处特例：`protocol` 为 `injvm` 时额外追加 `InjvmExporterListener`（`ProtocolListenerWrapper.java:68-73`）。

## buildInvokerChain Filter Group and Order

`ProtocolFilterWrapper` 不再自己排序 Filter，而是委托给 3.3 新增的 `FilterChainBuilder` SPI：

```java
// dubbo-cluster/.../cluster/filter/ProtocolFilterWrapper.java:52-73
public <T> Exporter<T> export(Invoker<T> invoker) {
    if (UrlUtils.isRegistry(invoker.getUrl())) return protocol.export(invoker);
    FilterChainBuilder builder = getFilterChainBuilder(invoker.getUrl());
    return protocol.export(builder.buildInvokerChain(invoker, SERVICE_FILTER_KEY, CommonConstants.PROVIDER));
}
public <T> Invoker<T> refer(Class<T> type, URL url) {
    if (UrlUtils.isRegistry(url)) return protocol.refer(type, url);
    FilterChainBuilder builder = getFilterChainBuilder(url);
    return builder.buildInvokerChain(protocol.refer(type, url), REFERENCE_FILTER_KEY, CommonConstants.CONSUMER);
}
```

`DefaultFilterChainBuilder.buildInvokerChain` 决定 Filter 集合的核心只有一行：

```java
// dubbo-cluster/.../cluster/filter/DefaultFilterChainBuilder.java:44-65
List<Filter> filters = ScopeModelUtil.getExtensionLoader(Filter.class, moduleModels.get(0))
        .getActivateExtension(url, key, group);   // key=service.filter / reference.filter, group=provider / consumer
```

`getActivateExtension(url, key, group)` 的过滤与排序规则：

- **group 过滤**：只保留 `@Activate(group = PROVIDER)`（如 `TimeoutFilter`，`dubbo-rpc/.../filter/TimeoutFilter.java:38`）或 `group = CONSUMER`（如 `ActiveLimitFilter`，`@Activate(group = CONSUMER, value = ACTIVES_KEY)`）的 Filter，group 不匹配的直接排除。判定在 `ExtensionLoader.isMatchGroup`（`:461-469`）：传入的 group 为空则**全部匹配**；Filter 声明了 group 则用 `Set.contains` 精确匹配；**Filter 一个 group 都没声明（`@Activate` 的 `group()` 默认为 `{}`）时反而一律不匹配**——所以不写 group 的 Filter 只能在 `group == null` 的场景（如 `getActivateExtension(url, key)`）被激活。
- **order 排序**：同一 group 内按 `@Activate(order = ...)` 升序串成责任链，越小越靠前（越靠近真实 Invoker）。比较器是 `ActivateComparator`（`dubbo-common/.../extension/support/ActivateComparator.java`），`before`/`after` 优先于 `order`，order 相同时按类名 `getSimpleName()` 字典序兜底（详见 [Filter](/docs/CS/Framework/Dubbo/Filter.md)）。
- **key 显式指定**：URL 上的 `service.filter` / `reference.filter` 可强制包含/排除（`-` 前缀表示排除）某些 Filter；两者 key 的常量是 `CommonConstants.SERVICE_FILTER_KEY = "service.filter"`（`:359`）与 `REFERENCE_FILTER_KEY = "reference.filter"`（`:336`）。

链上每个节点是 `FilterChainNode`（或 `CopyOfFilterChainNode`），`filter.invoke(nextNode, invocation)` 依次向下传递，结果经 `whenCompleteWithContext` 回调 `ListenableFilter.Listener`。装配时链是从后往前串的（`DefaultFilterChainBuilder.java:67-74`）：`for (int i = filters.size() - 1; i >= 0; i--)` 逆序遍历 filter 列表，每轮把 `last` 作为 `next` 包进新的 `CopyOfFilterChainNode`，最终最外层再包一层 `CallbackRegistrationInvoker` 用于注册监听回调——**这解释了为什么 order 小的 Filter 在链的外层**（它在逆序循环的最后才被包上）。

`DefaultFilterChainBuilder` 还处理了**多 ModuleModel 场景**（`:49-65`）：`moduleModels.size() > 1` 时分别从各 ModuleModel 取 filter 列表，再经 `sortingAndDeduplication(filters, directors)` 合并去重，此时排序依据是各 ModuleModel 自己的 `ExtensionDirector`；只有单个 ModuleModel 时才直接用 `ScopeModelUtil.getExtensionLoader(Filter.class, moduleModels.get(0))`。

## Consumer Timeout and Provider TimeoutFilter

消费端超时由 `DefaultFuture` 的 `TimeoutCheckTask` 触发（见上文 Time-Wheel Timer 一节），与服务端是否完成无关。服务端侧另有 `TimeoutFilter`（`@Activate(group = PROVIDER)`），职责与消费端不同：

```java
// dubbo-rpc/.../filter/TimeoutFilter.java:38
@Activate(group = CommonConstants.PROVIDER)
public class TimeoutFilter implements Filter { ... }
```

`TimeoutFilter` 在 `reply` 完成后比对「服务端实际处理耗时」与 URL 的 `timeout`，若超时仅打 `warn` 日志（业务仍正常返回），**不会中断或回滚调用**——它只是可观测/告警探针，不是超时的执行者。真正的「调用超时」语义完全落在 `DefaultFuture` 的异步映射模型上：消费端 future 标记失败后服务端可能仍在跑。排查「超时但 provider 还在执行」应看消费端 `timeout` 与 `DefaultFuture`，而非 `TimeoutFilter`。

## DubboProtocol Server Cache and Request Dispatch

`DubboProtocol extends AbstractProtocol`，持有两处来自父类的缓存：`Map<String, ProtocolServer> serverMap`（按 `url.getAddress()` 复用 Server）与 `Map<String, Exporter<?>> exporterMap`（按 `serviceKey` 复用 Exporter，定义于 `AbstractProtocol.java:60,65`）。

服务端暴露时 `openServer` 做了地址级复用：

```java
// dubbo-rpc/.../protocol/dubbo/DubboProtocol.java:367-389
private void openServer(URL url) {
    String key = url.getAddress();                 // host:port
    if (url.getParameter(IS_SERVER_KEY, true)) {
        ProtocolServer server = serverMap.get(key);
        if (server == null) {
            synchronized (this) {
                if (serverMap.get(key) == null) {
                    serverMap.put(key, createServer(url));   // 同一 address 只建一个 ExchangeServer
                    return;
                }
            }
        }
        server.reset(url);                          // 已存在则 reset（配合 override 动态配置）
    }
}

// :397-432 createServer 关键两行
url = url.addParameter(CODEC_KEY, DubboCodec.NAME); // 绑定 DubboCodec
ExchangeServer server = Exchangers.bind(url, requestHandler);
```

即：不论多少个 `dubbo://` 服务暴露在同一 `host:port`，`serverMap` 只保留**一个** `ExchangeServer`，每个服务仅新增一条 `exporterMap` 记录——这是「单端口跑多个 Dubbo 服务」的实现基础。

请求到达后的分发由构造时创建的 `ExchangeHandlerAdapter requestHandler` 完成，它实现了 `ExchangeHandler.reply`：

```java
// dubbo-rpc/.../protocol/dubbo/DubboProtocol.java:111-169
private final ExchangeHandler requestHandler = new ExchangeHandlerAdapter(frameworkModel) {
    public CompletableFuture<Object> reply(ExchangeChannel channel, Object message) {
        Invocation inv = (Invocation) message;
        Invoker<?> invoker = inv.getInvoker() == null ? getInvoker(channel, inv) : inv.getInvoker();
        ...
        Result result = invoker.invoke(inv);       // 进入 Filter 链 → 业务实现
        return result.thenApply(Function.identity());
    }
};

// :287-324 getInvoker
String serviceKey = serviceKey(port, path, version, group);  // port 取自 channel 本地地址；path/version/group 取自 attachment
DubboExporter<?> exporter = (DubboExporter<?>) exporterMap.get(serviceKey);
return exporter.getInvoker();
```

`port` 取自 `channel.getLocalAddress().getPort()`，`path/version/group` 取自 `Invocation` attachment，拼出 `serviceKey` 后在 `exporterMap` 取到 `Invoker`——这正是 16 字节头里 request id 之外的、定位「这次请求属于哪个服务」的服务端依据。`requestHandler` 被传给 `Exchangers.bind`，最终由 `HeaderExchangeHandler`（`dubbo-remoting-api`）按消息类型分派：twoway `Request` 进 `reply()` 回写响应，非 `Invocation` 消息（如事件）走父类逻辑。客户端建连在 `initClient` 里 `Exchangers.connect(url, requestHandler)`，且 `lazy-connect` 时换成 `LazyConnectExchangeClient`。

`getInvoker` 里还有两处易被忽略的分支（`:287-324`）：`isStubServiceInvoke` 为真时把 `port` 强制置 0（本地 stub 服务不对外暴露端口）；`isClientSide(channel)` 为真时（即消费端回调服务端场景）给 `path` 追加 `CALLBACK_SERVICE_KEY` 后缀，用同一个 `exporterMap` 承载双向调用。找不到 exporter 时抛 `RemotingException`，错误信息里带上 `exporterMap.keySet()` 便于排查 group / version 不匹配。

## Lazy Decoding DecodeableRpcInvocation

Dubbo 协议的一个关键设计决策是**反序列化不在 I/O 线程里做**。服务端收到请求包时，`DubboCodec.decodeBody` 只把 body 的字节流包成 `DecodeableRpcInvocation` 对象，**不立即反序列化**：

```java
// dubbo-rpc/.../protocol/dubbo/DubboCodec.java:186-211
DecodeableRpcInvocation inv;
if (isDecodeDataInIoThread(channel)) {
    if (customByteAccessor != null) {
        inv = customByteAccessor.getRpcInvocation(channel, req, new UnsafeByteArrayInputStream(readMessageData(is)), proto);
    } else {
        inv = new DecodeableRpcInvocation(frameworkModel, channel, req,
                new UnsafeByteArrayInputStream(readMessageData(is)), proto);
    }
    inv.decode();                       // :200 仅在 I/O 线程解码模式下才立即解码
} else {
    // ... 只构造，不解码
}
data = inv;
```

真正的解码时机由 `DecodeHandler` 决定——它在消息进入业务线程池**之后**才触发：

```java
// dubbo-remoting/.../remoting/transport/DecodeHandler.java:39-52
public void received(Channel channel, Object message) throws RemotingException {
    if (message instanceof Decodeable) {
        decode(message);               // :41 触发 Decodeable.decode()
    }
    if (message instanceof Request) {
        decode(((Request) message).getData());
    }
    if (message instanceof Response) {
        decode(((Response) message).getResult());
    }
    handler.received(channel, message);
}
```

`DecodeableRpcInvocation.decode()`（`:103-118`）带幂等保护（`hasDecoded` 标志），且解码失败**不抛异常**，而是把错误塞进 Request：

```java
// dubbo-rpc/.../protocol/dubbo/DecodeableRpcInvocation.java:103-118
public void decode() throws Exception {
    if (!hasDecoded && channel != null && inputStream != null) {
        try {
            decode(channel, inputStream);
        } catch (Throwable e) {
            log.warn(PROTOCOL_FAILED_DECODE, "", "", "Decode rpc invocation failed: " + e.getMessage(), e);
            request.setBroken(true);
            request.setData(e);
        } finally {
            hasDecoded = true;
        }
    }
}
```

`setBroken(true)` 的后果在服务端可见：`HeaderExchangeHandler.handleRequest` 检测到 `req.isBroken()` 就直接回一个 `Response.BAD_REQUEST` 的响应，附带解码失败原因，**不会**进入 Filter 链与业务逻辑。

> [!TIP]
> 这套「延迟解码」机制同时是**安全防线**：反序列化（及其触发的类白名单校验）发生在业务线程、且只对真正要处理的请求执行，攻击者用畸形 body 撑爆 I/O 线程的构造被限制在解码路径内。此外 `DecodeableRpcInvocation` 用的是 `UnsafeByteArrayInputStream`（零拷贝）包裹 body 字节，避免在 I/O 线程里多一次数组拷贝。

## DubboInvoker and DubboExporter

服务端导出时 `DubboProtocol.export` 造的是 `DubboExporter`，它继承 `AbstractExporter`：

```java
// dubbo-rpc/.../protocol/dubbo/DubboProtocol.java:336-364（export 摘录）
String key = serviceKey(url);
DubboExporter<T> exporter = new DubboExporter<>(invoker, key, exporterMap);
...
openServer(url);
optimizeSerialization(url);
return exporter;
```

注意 `exporterMap.put(key, this)` 是在 **`DubboExporter` 的构造器里**做的（`DubboExporter.java:36-38`），不是 `export` 方法里——所以 `DubboExporter` 一被构造就已经在 `exporterMap` 中注册了。`DubboExporter` 的另一职责是 `afterUnExport()` 时把自己摘掉：

```java
// dubbo-rpc/.../protocol/dubbo/DubboExporter.java:41-43
@Override
public void afterUnExport() {
    exporterMap.remove(key, this);
}
```

`remove(key, this)` 用的是「key + value 同时匹配」的语义（`ConcurrentHashMap.remove(Object, Object)`），避免误删同 key 的新 Exporter。

消费端引用时 `DubboProtocol.refer` 造的是 `DubboInvoker`，真正的发请求在 `doInvoke`：

```java
// dubbo-rpc/.../protocol/dubbo/DubboInvoker.java:90-145（doInvoke 摘录）
List<? extends ExchangeClient> exchangeClients = clientsProvider.getClients();
if (exchangeClients.size() == 1) {
    currentClient = exchangeClients.get(0);
} else {
    currentClient = exchangeClients.get(index.getAndIncrement() % exchangeClients.size());  // 轮询
}
int timeout = RpcUtils.calculateTimeout(getUrl(), invocation, methodName, DEFAULT_TIMEOUT);
if (timeout <= 0) {                       // 超时时间已耗尽，直接终止
    return AsyncRpcResult.newDefaultAsyncResult(
            new RpcException(RpcException.TIMEOUT_TERMINATE, "No time left for making the following call: ..."), invocation);
}
invocation.setAttachment(TIMEOUT_KEY, String.valueOf(timeout));
Request request = new Request();
request.setData(inv);
request.setVersion(Version.getProtocolVersion());
if (isOneway) {
    boolean isSent = getUrl().getMethodParameter(methodName, Constants.SENT_KEY, false);
    request.setTwoWay(false);
    currentClient.send(request, isSent);
    return AsyncRpcResult.newDefaultAsyncResult(invocation);
} else {
    request.setTwoWay(true);
    ExecutorService executor = getCallbackExecutor(getUrl(), inv);
    CompletableFuture<AppResponse> appResponseFuture =
            currentClient.request(request, timeout, executor).thenApply(AppResponse.class::cast);
    ...
}
```

三点值得注意：

- **`sent` 语义**：单向调用走 `currentClient.send(request, isSent)`，`isSent` 由方法级参数 `sent` 决定（`getMethodParameter(methodName, Constants.SENT_KEY, false)`），默认 `false`——**「发送阻塞等写入完成」而非「不等响应」**，与 Dubbo.md 的已证伪清单一致。
- **`timeout <= 0` 的提前终止**：剩余超时时间已经耗尽时直接抛 `RpcException.TIMEOUT_TERMINATE`，**不会**真的发包。这是消费端超时的一处「事前拦截」，与 `DefaultFuture` 的「事后超时」互补。
- **轮询选连接**：多连接场景下用 `index.getAndIncrement() % exchangeClients.size()` 轮询，即 `connections` 参数配 N 条连接时每次调用换一条。

## Client Connection Sharing and Reference Count

消费端连接的复用由 `DubboProtocol.getClients` 决定，核心是 `connections` 与 `shareconnections` 两个参数：

```java
// dubbo-rpc/.../protocol/dubbo/DubboProtocol.java:452-472
private ClientsProvider getClients(URL url) {
    int connections = url.getParameter(CONNECTIONS_KEY, 0);
    if (connections == 0) {
        // 未配置 connections 时走共享连接；shareconnections 默认 "1"
        String shareConnectionsStr = StringUtils.isBlank(url.getParameter(SHARE_CONNECTIONS_KEY, (String) null))
                ? ConfigurationUtils.getProperty(url.getOrDefaultApplicationModel(), SHARE_CONNECTIONS_KEY, DEFAULT_SHARE_CONNECTIONS)
                : url.getParameter(SHARE_CONNECTIONS_KEY, (String) null);
        connections = Integer.parseInt(shareConnectionsStr);
        return getSharedClient(url, connections);
    }
    List<ExchangeClient> clients =
            IntStream.range(0, connections).mapToObj((i) -> initClient(url)).collect(Collectors.toList());
    return new ExclusiveClientsProvider(clients);
}
```

- `connections` 未配置（0）→ **共享连接**：`getSharedClient`（`:481-494`）以 `url.getAddress()` 为 key 在 `referenceClientMap` 里 `compute`，复用已有的 `SharedClientsProvider` 并对其引用计数 `increaseCount()`。
- `connections` 显式配置 → **独占连接**：每个 Invoker 自建 N 条 `ExchangeClient`（`ExclusiveClientsProvider`），不共享。
- `shareconnections` 默认值是 `"1"`（`dubbo-rpc/.../protocol/dubbo/Constants.java:27`），key 是 `"shareconnections"`（`:21`，**全小写、无连字符**）。

共享连接的引用计数由 `SharedClientsProvider` 管理（`increaseCount()` / `close(int)`），最后一个使用者关闭后通过 `scheduleRemoveSharedClient`（`:496-502`）异步把自己从 `referenceClientMap` 移除。客户端连接的构造在 `initClient`（`:541-585`），会补上 `CODEC_KEY=DubboCodec.NAME` 与默认 `HEARTBEAT_KEY`，`lazy-connect` 为真时返回 `LazyConnectExchangeClient`（延迟到首次调用才真正建连）。

## Default Value Summary Table

| 项目 | 值 | 源码位置 |
| :--- | :--- | :--- |
| 头部长度 | 16 字节 | `ExchangeCodec.java:60` |
| 魔数 | `0xdabb` | `ExchangeCodec.java:62` |
| flag 位 | 请求 `0x80`、twoway `0x40`、event `0x20`、序列化掩码 `0x1f` | `ExchangeCodec.java:66-69` |
| 序列化 id 位置 | `header[2]` 低 5 位（请求与响应相同） | `ExchangeCodec.java:265/319` |
| status 位置 | `header[3]`，仅响应有效 | `ExchangeCodec.java:324-325` |
| status 取值 | `OK=20`、`CLIENT_TIMEOUT=30`、`SERVER_TIMEOUT=31`、`BAD_REQUEST=40`、`SERVICE_NOT_FOUND=60`、`SERVICE_ERROR=70`、`SERVER_ERROR=80`、`CLIENT_ERROR=90` | `Response.java:26-76` |
| 协议格式版本 | `"2.0.2"` | `Version.java:46` |
| `Codec2` 注册 | transport/telnet/exchange/default + dubbo | 各模块 SPI 文件 |
| 时间轮 tick | 30ms | `DefaultFuture.java:65-67` |
| 默认调用超时 | 1000ms | `CommonConstants.java:147` |
| `dubbo-rpc` 模块 | api / dubbo / injvm / triple 共 4 个 | 目录结构 |
| 可用协议名 | `dubbo`、`tri`、`grpc`、`rest2`、`injvm` | 各模块 SPI 文件 |
| Wrapper 层级 | order 越小越靠外；`InvokerCountWrapper`(`MIN_VALUE+1000`) 最外，`ProtocolFilterWrapper`(100) 居中 | `ExtensionLoader.java:789-800` |
| 共享连接默认条数 | `shareconnections=1` | `dubbo-rpc-dubbo/.../Constants.java:21,27` |

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
| 「status 值 25/27/31/35/50…」 | `Response` 只有 20/30/31/40/60/70/80/90 八个常量，无 `BAD_RESPONSE` | 抓包按错误数值解析响应状态 |
| 「status 由 `ChannelStatus` 枚举定义」 | 3.3.6 无此类，状态是 `Response` 里的 `byte` 常量 | 搜类名搜不到，误判无处定义 |
| 「`getNonSerializableObjectFactory()`」 | 该方法全仓库不存在（见 [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)） | 照抄代码编译不过 |
| 「反序列化在 I/O 线程完成」 | `DecodeableRpcInvocation` 延迟到 `DecodeHandler` 才解码 | 误判线程模型与安全边界 |
| 「wrapper 按 SPI 名 `listener=`/`filter=` 获取」 | wrapper 类不进扩展表，只能按构造器签名识别 | `getExtension("listener")` 抛异常 |

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
