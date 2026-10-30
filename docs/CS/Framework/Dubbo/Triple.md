## Introduction

Dubbo 3 最根本的变化，是把默认通信协议从 Dubbo 协议（TCP 私有二进制）换成了 Triple。Triple 构建在 HTTP/2 之上，协议层与 [gRPC](/docs/CS/Framework/gRPC/gRPC.md) 完全兼容，同时保留了 Dubbo 的服务发现与治理能力。它的设计目标很明确：让 Dubbo 服务的流量能被网关、代理、Service Mesh 这类通用组件识别，并让「Java 接口优先」与「Protobuf IDL 优先」两种开发方式共存。

围绕 Triple 有三个极易踩错的直觉，开篇先逐条破除：

- **协议名不是 `triple`，而是 `tri`。** SPI 里注册的名字是 `tri`、`grpc`、`rest2` 三个，全仓库不存在 `triple=` 的注册项。3.3.6 的 `Protocol` 接口甚至已经删掉了 `getName()`，协议名只由 SPI 扩展名决定，所以「协议名」就是「扩展名」。
- **Triple 的默认序列化不是 Protobuf，而是 `hessian2`。** 只有当参数或返回值本身就是 Protobuf 生成类时，才走 Protobuf 直通打包（`PbArrayPacker` / `PbUnpack`）；普通 Java POJO、泛化调用仍走包装器（wrapper），默认 `hessian2`——在 wrapper 内部会被转换成 `hessian4` 这个名字。
- **3.3 的 Triple 运行时已经不再依赖 grpc-java。** 它改用自研的 `dubbo-remoting-http12` 加 Netty 原生 HTTP/2 编解码器；`io.grpc` 只留下 health / reflection 的生成桩与若干字符串常量。

本文所有结论来自 Apache Dubbo **3.3.6** 官方源码（`apache/dubbo` 仓库 tag `dubbo-3.3.6`），默认值一律标注文件与行号，网上流传但与源码不符的说法会在文中显式标出。

## Protocol Registration and Naming

`dubbo-rpc/dubbo-rpc-triple` 的协议扩展文件注册了三个名字：

```properties
# dubbo-rpc/dubbo-rpc-triple/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol
tri=org.apache.dubbo.rpc.protocol.tri.TripleProtocol
grpc=org.apache.dubbo.rpc.protocol.tri.GrpcProtocol
rest2=org.apache.dubbo.rpc.protocol.tri.RestProtocol
```

其中 `GrpcProtocol` 与 `RestProtocol` 都是 `TripleProtocol` 的空子类，只是换了个协议名：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/GrpcProtocol.java:21
public class GrpcProtocol extends TripleProtocol {
    public GrpcProtocol(FrameworkModel frameworkModel) {
        super(frameworkModel);
    }
}
```

于是有两条结论：

- **`tri` 是 Triple 的正式协议名**，`CommonConstants.TRIPLE = "tri"`（`dubbo-common/.../constants/CommonConstants.java:30`）。配置里写 `dubbo.protocol.name=tri`，不要写 `triple`。
- **`grpc` 与 `rest2` 不是独立实现**，而是同一套 Triple 引擎换个名字暴露出来，用于让 `name=grpc` 这种既有配置能直接落到 Triple 上。

> [!WARNING]
> 旧写法里 `Protocol` 接口上的 `getName()` 方法在 3.3.6 已不存在（`dubbo-rpc/dubbo-rpc-api/.../rpc/Protocol.java:58-66` 只有 `getDefaultPort()` / `export` / `refer` / `destroy` / `getServers`）。任何「通过 `protocol.getName()` 判断协议类型」的经验在 3.3 上都不成立，判断协议类型应当读 `URL` 的 `protocol` 参数。

## Compatibility Boundary with gRPC

Triple 在传输层用 HTTP/2，与 gRPC 共用同一套帧格式，因此可以被标准的 gRPC 客户端或 Envoy 之类的代理直接识别；Dubbo 另外提供了 health 与 reflection 服务桩，让 `grpc_health_probe`、`grpcurl` 这类工具能探测 Triple 服务。

但兼容是「协议层」的，不是「实现层」的。3.3.6 的 Triple 已经**不依赖 grpc-java 运行时**：

```xml
<!-- dubbo-rpc/dubbo-rpc-triple/pom.xml:39-66 -->
<artifactId>dubbo-remoting-http12</artifactId>
<artifactId>dubbo-remoting-http3</artifactId>      <!-- optional -->
<artifactId>dubbo-remoting-websocket</artifactId>  <!-- optional -->
<artifactId>dubbo-remoting-netty4</artifactId>     <!-- optional -->
<artifactId>dubbo-native</artifactId>
```

pom 里没有任何 `grpc-netty` / `grpc-stub` / `grpc-core`；`TripleHttp2Protocol` 直接使用 `io.netty.handler.codec.http2.*`。`io.grpc` 仅剩三类残留：`TripleProtocol.java:45` 的 import、`service/HealthStatusManager.java` 与 `service/ReflectionV1AlphaService.java` 的生成桩、以及 `ReflectionPackableMethod.java:52` 的字符串常量 `GRPC_STREAM_CLASS = "io.grpc.stub.StreamObserver"`。`grpc-stub` 只出现在 `dubbo-compiler` 与 `dubbo-security` 的编译期依赖里。

```properties
# dubbo-rpc/dubbo-rpc-triple/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.api.WireProtocol
tri=org.apache.dubbo.rpc.protocol.tri.TripleHttp2Protocol
grpc=org.apache.dubbo.rpc.protocol.tri.GrpcHttp2Protocol
```

Triple 走的是 `WireProtocol` 扩展体系（而不是老协议的 `Codec2`），这也是它与 Dubbo 协议在 remoting 层的本质差异。

## Four Invocation Modes

Triple 支持 gRPC 定义的全部四种 RPC 模式，枚举定义在 `dubbo-common`：

```java
// dubbo-common/.../rpc/model/MethodDescriptor.java:58-63
enum RpcType {
    UNARY,
    CLIENT_STREAM,
    SERVER_STREAM,
    BI_STREAM
}
```

| 模式 | RpcType | 语义 |
| :--- | :--- | :--- |
| 一元 | `UNARY` | 一问一答，与 Dubbo 协议同步调用等价 |
| 服务端流 | `SERVER_STREAM` | 一次请求，服务端返回多条消息 |
| 客户端流 | `CLIENT_STREAM` | 客户端发送多条消息，服务端返回一次 |
| 双向流 | `BI_STREAM` | 双方各自持续发送 |

分发逻辑在 `TripleInvoker` 里按 `RpcType` 分流：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleInvoker.java:176-189
switch (methodDescriptor.getRpcType()) {
    case UNARY:          result = invokeUnary(...);            break;
    case SERVER_STREAM:  result = invokeServerStream(...);     break;
    case CLIENT_STREAM:
    case BI_STREAM:      result = invokeBiOrClientStream(...); break;
    default: throw new IllegalStateException("Can not reach here");
}
```

客户端侧的核心类是 `TripleClientCall`、`ClientCall`、`AbstractTripleClientStream`、`UnaryClientCallListener`；服务端侧是 `AbstractServerTransportListener`、`AbstractServerCallListener`、`GrpcStreamServerChannelObserver`、`ServerStreamObserver`。注意**不存在名为 `StreamCallListener` 的类**，流式监听是通过 `ClientCall.Listener` 与各个 `*ChannelObserver` 实现的。

## Serialization: First Check Whether It Is a Protobuf Type

Triple 的序列化选择分两条路径，判断发生在 `ReflectionPackableMethod`：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/ReflectionPackableMethod.java:127-132
public static boolean needWrap(MethodDescriptor methodDescriptor, Class<?>[] parameterClasses, Class<?> returnClass) {
    String methodName = methodDescriptor.getMethodName();
    // generic call must be wrapped
    if (CommonConstants.$INVOKE.equals(methodName) || CommonConstants.$INVOKE_ASYNC.equals(methodName)) {
        return true;
    }
    ...
}
```

```java
// ReflectionPackableMethod.java:88-108（节选）
if (!needWrapper) {
    requestPack = new PbArrayPacker(singleArgument);
    responsePack = PB_PACK;
    requestUnpack = new PbUnpack<>(actualRequestTypes[0]);
    responseUnpack = new PbUnpack<>(actualResponseType);
} else {
    final MultipleSerialization serialization = url.getOrDefaultFrameworkModel()
            .getExtensionLoader(MultipleSerialization.class)
            .getExtension(url.getParameter(Constants.MULTI_SERIALIZATION_KEY, CommonConstants.DEFAULT_KEY));
    ...
}
```

- **不需要包装**（参数/返回值就是 Protobuf 生成类）→ 走 `PbArrayPacker` / `PB_PACK` / `PbUnpack`，即 Protobuf 直通打包，没有通用序列化介入。
- **需要包装**（Java POJO、泛化调用、echo）→ 走 `MultipleSerialization`（`serialize.multiple`，默认扩展名 `default` → `DefaultMultipleSerialization`）。

包装路径下的默认序列化名来自 `UrlUtils`：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/ReflectionPackableMethod.java:112-116
public static ReflectionPackableMethod init(MethodDescriptor methodDescriptor, URL url) {
    String serializeName = UrlUtils.serializationOrDefault(url);
    Collection<String> allSerialize = UrlUtils.allSerializations(url);
    return new ReflectionPackableMethod(methodDescriptor, url, serializeName, allSerialize);
}
```

而 `UrlUtils.serializationOrDefault()` 的兜底值定义在 `DefaultSerializationSelector`：

```java
// dubbo-serialization/dubbo-serialization-api/.../support/DefaultSerializationSelector.java:25
private static final String DEFAULT_REMOTING_SERIALIZATION_PROPERTY = "hessian2";
```

**所以 Triple 在非 Protobuf 场景下的默认序列化与 Dubbo 协议完全一致，都是 `hessian2`。** 唯一的区别是名字：wrapper 内部把 `hessian2` 转换成了 `hessian4`（`ReflectionPackableMethod.java:424-428` 的 `convertHessianToWrapper`），这是 Dubbo 自研 hessian 实现的标识，不是另一种序列化算法。

### Priority of Serialization

`prefer.serialization` 优先于 `serialization`，两者都配了才生效：

```java
// dubbo-remoting/dubbo-remoting-api/.../utils/UrlUtils.java:92-109（节选）
public static Byte serializationId(URL url) {
    Byte serializationId;
    List<String> preferSerials = preferSerialization(url);   // prefer.serialization
    for (String preferSerial : preferSerials) {
        if ((serializationId = CodecSupport.getIDByName(preferSerial)) != null) return serializationId;
    }
    if ((serializationId = CodecSupport.getIDByName(url.getParameter(SERIALIZATION_KEY))) != null) return serializationId;
    return CodecSupport.getIDByName(DefaultSerializationSelector.getDefaultRemotingSerialization());
}
```

`prefer.serialization` 可以写一列候选（逗号分隔），框架按顺序找到第一个可用实现；这在「Provider 与 Consumer 支持不同序列化实现」时是唯一的柔性协商手段。注意 `@DubboService` 上有 `serialization()` 与 `preferSerialization()` 两个属性，而 **`@DubboReference` 上没有这两个属性**——消费侧的序列化必须靠 URL 参数或注解外的配置传递。

## Port and Single-Port Multi-Protocol

Triple 与 Dubbo 协议默认端口不同，且 `ProtocolConfig` 本身没有默认端口常量，端口由各 `Protocol.getDefaultPort()` 提供，`ServiceConfig` 在未配置时采用：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleProtocol.java:96-99
@Override
public int getDefaultPort() {
    return 50051;
}
```

```java
// dubbo-rpc/dubbo-rpc-dubbo/.../DubboProtocol.java:99
public static final int DEFAULT_PORT = 20880;
```

| 协议 | 默认端口 | 来源 |
| :--- | :--- | :--- |
| `tri` | **50051** | `TripleProtocol.java:96-99` |
| `dubbo` | **20880** | `DubboProtocol.java:99` |

Triple 自身导出时总是经过 `PortUnificationExchanger.bind()`：

```java
// TripleProtocol.java:177-179
if (bindPort) {
    PortUnificationExchanger.bind(url, new DefaultPuHandler());
}
```

所谓「单端口多协议」就是让 Dubbo 协议也复用这个端口——**默认并不开启**，需要在服务 URL 上带 `ext.protocol`，此时 `ServiceConfig` 会补上 `ispuserver=true`：

```java
// dubbo-config/dubbo-config-api/.../config/ServiceConfig.java:874-881（节选）
String extProtocol = url.getParameter(EXT_PROTOCOL, "");
...
if (StringUtils.isNotBlank(extProtocol)) {
    url = URLBuilder.from(url).addParameter(IS_PU_SERVER_KEY, Boolean.TRUE.toString()).build();
}
```

```java
// dubbo-remoting/dubbo-remoting-api/.../exchange/support/header/HeaderExchanger.java:49-56
boolean isPuServerKey = url.getParameter(IS_PU_SERVER_KEY, false);
if (isPuServerKey) {
    server = new HeaderExchangeServer(PortUnificationExchanger.bind(url, ...));
} else {
    server = new HeaderExchangeServer(Transporters.bind(url, ...));
}
```

常量位置：`EXT_PROTOCOL = "ext.protocol"`（`CommonConstants.java:630`）、`IS_PU_SERVER_KEY = "ispuserver"`（`remoting/Constants.java:102`），`ProtocolConfig.extProtocol` 的注释就是 "Extra protocol for this service, using Port Unification Server"。

## Two Development Modes

### Java Interface First (No IDL)

直接写 Java 接口 + Dubbo 注解，序列化回落 hessian2。这是从 Dubbo 2.x 迁移过来的团队最省事的路径：

```java
@DubboService   // 暴露服务
public class DemoServiceImpl implements DemoService { ... }

@DubboReference // 引用服务
private DemoService demoService;
```

### IDL First (Protobuf)

写 `.proto`，由 `dubbo-maven-plugin` 生成 Triple 桩：

```java
// dubbo-maven-plugin/.../protoc/DubboProtocCompilerMojo.java:77-103（节选）
@Mojo(name = "compile", defaultPhase = LifecyclePhase.GENERATE_SOURCES, ...)
public class DubboProtocCompilerMojo extends AbstractMojo {
    @Parameter(property = "protoSourceDir", defaultValue = "${basedir}/src/main/proto")
    private File protoSourceDir;
    ...
    @Parameter(required = true, property = "dubboGenerateType", defaultValue = "tri")
    private String dubboGenerateType;
}
```

goal 名为 `compile`，`dubboGenerateType` 默认 `tri`，可选的 `tri_reactor` 走响应式生成器：

```java
// dubbo-maven-plugin/.../protoc/enums/DubboGenerateTypeEnum.java
Tri("tri", "org.apache.dubbo.gen.tri.Dubbo3TripleGenerator"),
Tri_reactor("tri_reactor", "org.apache.dubbo.gen.tri.reactive.ReactorDubbo3TripleGenerator"),
```

`dubbo-plugin/dubbo-compiler` 里还有 `MutinyDubbo3TripleGenerator`，对应响应式/协程式风格。用它可以替代社区通用的 `protobuf-maven-plugin`。

> [!NOTE]
> 检索 `config/annotation/` 全目录，`@DubboService` 与 `@DubboReference` 上**没有** `protobuf` 这个属性；注解里出现的只有 `protocol()`（协议名）。「通过 `@DubboService(protobuf = true)` 开启 Protobuf 模式」是不存在的写法。

## REST Capabilities

`tri` 协议自身内置 REST 支持，由一个静态开关控制：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleProtocol.java:70,132-135
public static boolean REST_ENABLED = true;
...
if (REST_ENABLED) {
    mappingRegistry.register(invoker);
}
```

REST 的 `produces` / `consumes` 由 `RequestMapping` 的两个条件类实现：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/rest/mapping/RequestMapping.java:48-49,398-399
private final ConsumesCondition consumesCondition;
private final ProducesCondition producesCondition;
...
private String[] consumes;
private String[] produces;
```

因此 `tri` 与 `rest2` 的关系是「同一引擎的两种协议名」，REST 风格的服务既能按 `tri` 导出（HTTP/2 + RESTful 语义），也能按 `rest2` 导出。注意**不存在 `TripleRestProtocol` 这个类**，REST 能力不在独立类里。

## TripleProtocol Class Hierarchy

`TripleProtocol` 是 Triple 引擎的**具体**实现类（不是抽象类），继承 RPC 层基类：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleProtocol.java:59-99
public class TripleProtocol extends AbstractProtocol {
    public static boolean REST_ENABLED = true;     // :70 由 H2_SETTINGS_REST_ENABLED 控制
    @Override public int getDefaultPort() { return 50051; }
}
```

`GrpcProtocol` 与 `RestProtocol` 只是换名的空子类（`GrpcProtocol.java:21` 已给出），所以 `tri` / `grpc` / `rest2` 三个 SPI 名共享同一套 `TripleProtocol` 逻辑，差异只体现在入口层：同一个 `serviceKey` 在 `export()` 时既注册到 gRPC 的 `PathResolver`，也（当 `REST_ENABLED`）注册到 `RequestMappingRegistry`（`TripleProtocol.java:102-151`）。

> [!TIP]
> 「差异只体现在入口层」这句话在**协议名层面**成立，但要说清它到底差在哪：`tri` / `grpc` / `rest2` 三个名字**不改变 `TripleProtocol` 的任何一行逻辑**（三者继承链上没有任何字段或方法被覆写），真正的差异在 `RequestHandlerMapping` 这一层——服务端收到请求后由 `DefaultRequestRouter` 遍历所有 `RequestHandlerMapping` 扩展，先返回非 null handler 的那个接管请求，并把 `mapping.getType()`（`"grpc"` 或 `"rest"`）写进 `TripleConstants.HANDLER_TYPE_KEY`。详见 [tri vs grpc vs rest2 Handler Routing](#tri-vs-grpc-vs-rest2-handler-routing)。

`export()` 与 `refer()` 都走 `PortUnificationExchanger`：

```java
// TripleProtocol.java:161-195
private void bindServerPort(URL url) {
    ...
    if (bindPort) PortUnificationExchanger.bind(url, new DefaultPuHandler());  // :178 服务端绑定
}
public <T> Invoker<T> refer(Class<T> type, URL url) {
    optimizeSerialization(url);
    AbstractConnectionClient connectionClient =
        Http3Exchanger.isEnabled(url) ? Http3Exchanger.connect(url)
                                      : PortUnificationExchanger.connect(url, new DefaultPuHandler()); // :188-190
    return new TripleInvoker<>(type, url, acceptEncodings, connectionClient, invokers, streamExecutor);
}
```

注意 `protocolBindingRefer` 在 `TripleProtocol` 里直接 `return null`（`TripleProtocol.java:206-209`）—— Triple 不走 `AbstractProtocol.protocolBindingRefer` 的默认模板，而是自己重写 `refer()` 完成建连。

## TripleInvoker Connection and Invocation

消费端 `TripleInvoker` 不负责建连，它复用 `TripleProtocol.refer()` 已经建好的 `AbstractConnectionClient`：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleInvoker.java:89-122
public class TripleInvoker<T> extends AbstractInvoker<T> {
    private final AbstractConnectionClient connectionClient;   // 来自 PortUnificationExchanger.connect
    private final TripleWriteQueue writeQueue = new TripleWriteQueue(256);
    ...
}
```

`doInvoke` 的发送流程：

```java
// TripleInvoker.java:141-189
protected Result doInvoke(final Invocation invocation) {
    if (!connectionClient.isConnected()) {        // :143 未连上直接返回 UNAVAILABLE
        ... return new AsyncRpcResult(future, invocation);
    }
    ConsumerModel consumerModel = ...;            // 取 ServiceDescriptor / MethodDescriptor
    ExecutorService callbackExecutor =
        isSync(methodDescriptor, invocation) ? new ThreadlessExecutor() : streamExecutor;  // sync unary 用 ThreadlessExecutor
    ClientCall call = new TripleClientCall(
        connectionClient, callbackExecutor, getUrl().getOrDefaultFrameworkModel(), writeQueue);  // :171
    switch (methodDescriptor.getRpcType()) {       // :176 按 RpcType 分流
        case UNARY:          result = invokeUnary(...);           break;
        case SERVER_STREAM:  result = invokeServerStream(...);    break;
        case CLIENT_STREAM:
        case BI_STREAM:      result = invokeBiOrClientStream(...); break;
    }
    return result;
}
```

要点：真正在 HTTP/2 上开流、写首部帧与 body 的是 `TripleClientCall` 借由 `connectionClient`（底层 `dubbo-remoting-http12` 的 Netty HTTP/2 编解码）。源码里**没有名为 `HttpClient` 的类**——所谓「建连」就是 `PortUnificationExchanger.connect` 返回的 `AbstractConnectionClient`，tri/grpc/rest2 三种协议名共用它。同步一元调用为了不额外占线程，用 `ThreadlessExecutor` 把结果挂回调用线程；流式调用则交给 `streamExecutor`。

## gRPC Interop Boundary service method naming content type trailer

Triple 与标准 gRPC 互通靠一组成对的 HTTP/2 头，全部由 `TripleHeaderEnum` 定义（注意前缀是 `grpc-`，与 gRPC 规范一致）：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleHeaderEnum.java:32-44
HTTP_STATUS_KEY("http-status"),
STATUS_KEY("grpc-status"),                  // gRPC 状态码
MESSAGE_KEY("grpc-message"),               // 错误描述
STATUS_DETAIL_KEY("grpc-status-details-bin"), // 结构化错误详情（protobuf 二进制）
TIMEOUT("grpc-timeout"),                   // 调用超时（gRPC 时间格式，如 "1S"）
GRPC_ENCODING("grpc-encoding"),            // 消息压缩
GRPC_ACCEPT_ENCODING("grpc-accept-encoding"),
CONSUMER_APP_NAME_KEY("tri-consumer-appname"),
SERVICE_VERSION("tri-service-version"),
SERVICE_GROUP("tri-service-group"),
SERVICE_TIMEOUT("tri-service-timeout"),
TRI_HEADER_CONVERT("tri-header-convert"),  // 大小写头名转换开关
TRI_EXCEPTION_CODE("tri-exception-code");
```

互通边界的关键点：

- **service / method 命名**：gRPC 路径形如 `/package.Service/Method`，Triple 通过 `PathResolver` 把 `serviceKey` 映射到该 HTTP/2 `:path`；方法经 `MethodDescriptor.RpcType` 识别为 `UNARY/SERVER_STREAM/CLIENT_STREAM/BI_STREAM` 四种之一（见 Four Invocation Modes）。
- **content-type**：有两个媒体类型常量，都在 `dubbo-remoting/dubbo-remoting-http12/.../message/MediaType.java`——`APPLICATION_GRPC = "application/grpc"`（`:47`）与 `APPLICATION_GRPC_PROTO = "application/grpc+proto"`（`:49`）。**Triple 默认发的是后者**（`TripleInvoker.java:319` 用 `APPLICATION_GRPC_PROTO.getName()` 构造 `MethodDescriptor`），而 gRPC 兼容路径（`GrpcCompositeCodec`）用的是 `APPLICATION_GRPC`（`tri/h12/grpc/GrpcCompositeCodec.java:131`）。服务端判断「是不是 gRPC 请求」用**前缀匹配**：`contentType.startsWith(MediaType.APPLICATION_GRPC.getName())`（`GrpcUtils.java:91`）——所以 `application/grpc+proto` 也能被识别成 gRPC。
- **trailer**：最终状态与错误通过 HTTP/2 **trailer** 头回传，`grpc-status` / `grpc-status-details-bin` 放在 trailer 而非 header，与 gRPC 规范一致；流结束时据此判定成功或失败（`TriRpcStatus` 映射 gRPC code）。客户端的解析入口是 `AbstractTripleClientStream.statusFromTrailers`（`tri/stream/AbstractTripleClientStream.java:330-352`）：先取 trailer 里的 `grpc-status`，没有则取 `grpc-message` 拼描述；**连 `grpc-status` 都没有**时，若已收到 header 则报 `"missing GRPC status in response"`，否则退化用 HTTP 状态码经 `TriRpcStatus.httpStatusToGrpcCode` 转换。
- **attachment 过滤**：`excludeAttachmentsSet`（`TripleHeaderEnum.java:48`）显式排除 pseudo-header 与内部头（group、interface、path、remote.application、application、serialization 等），避免它们被当作业务 attachment 透传。

这意味着 Dubbo 的 `RpcContext` attachment 与 gRPC 的 metadata 并非一一对应：只有非内部的、非伪头的 key 才会以 gRPC metadata 形式出现在 `tri-*` / 自定义头里。

## TriplePathResolver Path Mapping

`PathResolver` 是 Triple 服务端把「HTTP/2 `:path`」映射回「哪个 Invoker」的核心，3.3.6 的实现是 `TriplePathResolver`（SPI 注册名 `tri`）：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TriplePathResolver.java:37-52
public void register(Invoker<?> invoker) {
    URL url = invoker.getUrl();
    String serviceKey = url.getServiceKey();
    String serviceInterface = url.getServiceModel().getServiceModel().getInterfaceName();

    register0(serviceKey, serviceInterface, invoker, url);

    // Path pattern: '{interfaceName}' or '{contextPath}/{interfaceName}'
    String path = url.getPath();
    int index = path.lastIndexOf('/');
    if (index == -1) {
        return;
    }
    String fallbackPath = path.substring(0, index + 1) + serviceInterface;
    register0(URL.buildKey(path, url.getGroup(), url.getVersion()), fallbackPath, invoker, url);
}
```

设计要点：

- **双路径注册**：主路径是 `serviceKey`（含 group/version），回退路径是 `{contextPath}/{interfaceName}`。`TripleProtocol.RESOLVE_FALLBACK_TO_DEFAULT`（默认 `true`，`TripleProtocol.java:68`）控制是否也注册回退路径。
- **路径冲突直接抛异常**：`register0` 里若主路径已被占用且**不是**回退路径，直接抛 `IllegalStateException`（`TriplePathResolver.java:65-69`）——两个服务用同一个 `:path` 是启动期错误，不是运行期错误。
- **查找时逐级降级**：`resolve(path, group, version)` 先按 `URL.buildKey(path, group, version)` 精确找；找不到则按 `(path, group, DEFAULT_VERSION)` 找；再找不到则按**裸 path** 找（`TriplePathResolver.java:116-124`）。三级降级让「客户端按 gRPC 标准路径 `/package.Service/Method` 调用」能命中「服务端按 Dubbo 风格 `group/interface:version` 暴露」的服务。
- **`nativeStubs` 单独一张表**：`addNativeStub` / `hasNativeStub` 标记那些由 Dubbo 自身生成桩代码的服务（`:127-135`）。

## tri vs grpc vs rest2 Handler Routing

三个协议名的实际差异落在 `RequestHandlerMapping` 这个 SPI 上，只有两个实现：

```properties
# dubbo-rpc/dubbo-rpc-triple/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.protocol.tri.route.RequestHandlerMapping
grpc=org.apache.dubbo.rpc.protocol.tri.h12.grpc.GrpcRequestHandlerMapping
rest=org.apache.dubbo.rpc.protocol.tri.rest.mapping.RestRequestHandlerMapping
```

服务端收到请求后由 `DefaultRequestRouter` 依次询问，谁先返回非 null handler 谁接管：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/route/DefaultRequestRouter.java:44-60
for (int i = 0, size = requestHandlerMappings.size(); i < size; i++) {
    RequestHandlerMapping mapping = requestHandlerMappings.get(i);
    RequestHandler handler = mapping.getRequestHandler(url, request, response);
    if (handler == null) {
        continue;
    }
    handler.setAttribute(TripleConstants.HANDLER_TYPE_KEY, mapping.getType());
    handler.setAttribute(TripleConstants.HTTP_REQUEST_KEY, request);
    handler.setAttribute(TripleConstants.HTTP_RESPONSE_KEY, response);
    return handler;
}
return null;
```

`mapping.getType()` 返回的正是 `TripleConstants.TRIPLE_HANDLER_TYPE_GRPC`（`"grpc"`）或 `TRIPLE_HANDLER_TYPE_REST`（`"rest"`）（`GrpcRequestHandlerMapping.java:84`、`RestRequestHandlerMapping.java:150`），下游据此分流：

- `HttpContextFilter`（`tri/h12/HttpContextFilter.java:37`）读 `HANDLER_TYPE_KEY` 决定要不要把 HTTP 上下文写进 `RpcContext`；
- `RestFilterAdapter` / `RestHeaderFilterAdapter`（`tri/rest/filter/`）只在 handler type 为 `"rest"` 时才介入。

> [!NOTE]
> 所以「`grpc=` 与 `tri=` 有区别吗」这个问题的准确答案是：**协议实现层没有区别，请求分发层有区别**。`tri` 协议名导出的服务，`grpc` 的 `RequestHandlerMapping` 与 `rest` 的 `RequestHandlerMapping` 都会尝试处理同一个请求——先命中谁取决于 HTTP 请求的实际形态（路径、方法、content-type），而不是取决于 SPI 名字。`tri` 之所以能同时服务 gRPC 客户端和 REST 客户端，靠的就是这个「两个 mapping 并存、谁先匹配谁接管」的机制。

## TripleConstants Reference

`TripleConstants`（`dubbo-rpc/dubbo-rpc-triple/.../tri/TripleConstants.java`）是 Triple 层的常量集中地，几个关键项：

| 常量 | 值 | 用途 |
| :--- | :--- | :--- |
| `DEFAULT_VERSION` | `"1.0.0"` | `TriplePathResolver.resolve` 降级查找时的默认版本 |
| `HESSIAN2` / `HESSIAN4` | `"hessian2"` / `"hessian4"` | wrapper 层的序列化名换算（见 [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)） |
| `HANDLER_TYPE_KEY` | `"tri.handler.type"` | 请求 attribute，值为 `"grpc"` 或 `"rest"` |
| `HTTP_REQUEST_KEY` / `HTTP_RESPONSE_KEY` | `"tri.http.request"` / `"tri.http.response"` | 原始 HTTP 消息的 attribute |
| `REMOTE_ADDRESS_KEY` | `"tri.remote.address"` | 对端地址 |
| `HTTPS_SCHEME` / `HTTP_SCHEME` | `"https"` / `"http"` | Netty `AsciiString` 形式的 scheme 常量 |
| `HEADER_BIN_SUFFIX` | `"-bin"` | 二进制 metadata 后缀 |

## Triple Static Switches and H2 Settings Keys

`TripleProtocol` 有一组 `public static boolean` 开关，在**构造器里**从环境/全局配置一次性读入（`TripleProtocol.java:66-71` 定义，`:73-95` 赋值）：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleProtocol.java:82-91
Configuration conf = ConfigurationUtils.getEnvConfiguration(ApplicationModel.defaultModel());
CONVERT_NO_LOWER_HEADER = conf.getBoolean(H2_SETTINGS_SUPPORT_NO_LOWER_HEADER_KEY, true);
IGNORE_1_0_0_VERSION = conf.getBoolean(H2_SETTINGS_IGNORE_1_0_0_VERSION, false);
RESOLVE_FALLBACK_TO_DEFAULT = conf.getBoolean(H2_SETTINGS_RESOLVE_FALLBACK_TO_DEFAULT_KEY, true);

// init global settings
Configuration globalConf = ConfigurationUtils.getGlobalConfiguration(frameworkModel.defaultApplication());
VERBOSE_ENABLED = globalConf.getBoolean(H2_SETTINGS_VERBOSE_ENABLED, false);
REST_ENABLED = globalConf.getBoolean(H2_SETTINGS_REST_ENABLED, true);
OPENAPI_ENABLED = globalConf.getBoolean(H2_SETTINGS_OPENAPI_ENABLED, false);
```

对应的配置 key 定义在 `dubbo-rpc/dubbo-rpc-api/.../rpc/Constants.java`：

| 常量 | key | 默认值 | 作用域 |
| :--- | :--- | :--- | :--- |
| `H2_SETTINGS_SUPPORT_NO_LOWER_HEADER_KEY` | `dubbo.rpc.tri.support-no-lower-header` | `true` | 环境变量 |
| `H2_SETTINGS_IGNORE_1_0_0_KEY` | `dubbo.rpc.tri.ignore-1.0.0-version` | `false` | 环境变量 |
| `H2_SETTINGS_RESOLVE_FALLBACK_TO_DEFAULT_KEY` | `dubbo.rpc.tri.resolve-fallback-to-default` | `true` | 环境变量 |
| `H2_SETTINGS_VERBOSE_ENABLED` | `dubbo.protocol.triple.verbose` | `false` | 全局配置 |
| `H2_SETTINGS_REST_ENABLED` | `dubbo.protocol.triple.rest.enabled` | `true` | 全局配置 |
| `H2_SETTINGS_OPENAPI_ENABLED` | `dubbo.protocol.triple.rest.openapi.enabled` | `false` | 全局配置 |

> [!NOTE]
> 注意「**环境变量**」与「**全局配置**」两类作用域不同：前三项走 `ConfigurationUtils.getEnvConfiguration(...)`（读环境变量），后三项走 `getGlobalConfiguration(...)`（读 `dubbo.properties` 等全局配置源）。另外 `REST_ENABLED` / `OPENAPI_ENABLED` 等是 `public static` 字段——它们在**类初始化时**就被赋值，因此同一 JVM 内后续修改配置源不会即时生效（除非重新加载类）。

## Pitfall List

| 直觉写法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| `dubbo.protocol.name=triple` | 协议名是 `tri`，无 `triple` 扩展 | 启动时报找不到扩展 |
| 「Triple 默认 Protobuf 序列化」 | 默认 `hessian2`，仅 Protobuf 类型走 PB 直通 | 误判跨语言互操作能力 |
| 「Triple 依赖 grpc-java」 | 3.3 已切自研 Netty HTTP/2 实现 | 依赖冲突排查时找错方向 |
| 「`getName()` 判断协议类型」 | 3.3.6 `Protocol` 已无该方法 | 编译不过 |
| 「单端口多协议默认开启」 | 需 `ext.protocol` + `ispuserver=true` | 端口复用不生效 |
| 「`@DubboService(protobuf=true)`」 | 注解无 `protobuf` 属性 | 编译不过 |
| 「`tri` / `grpc` / `rest2` 是三套实现」 | 三个都是 `TripleProtocol` 子类且**无任何覆写**，差异在 `RequestHandlerMapping` 层 | 误以为要按名字切换实现 |
| 「content-type 是 `application/grpc`」 | Triple 默认发 `application/grpc+proto`；gRPC 兼容路径用 `application/grpc`，服务端按**前缀**判定 | 网关按精确匹配分流时匹配不上 |
| 「`grpc-status` 在 header 里」 | 放在 HTTP/2 **trailer**；缺失时降级用 HTTP 状态码转换 | 按 header 解析永远拿不到状态 |
| 「`tri` 协议名导出就只服务 gRPC」 | grpc 与 rest 两个 `RequestHandlerMapping` 并存，谁先匹配谁接管 | 误判 REST 客户端的可用性 |
| 「`REST_ENABLED` 可以运行期动态改」 | 它是 `public static` 字段，在 `TripleProtocol` 构造器里一次性赋值 | 改配置不生效，需重启 |
| 「`dubbo.rpc.tri.*` 和 `dubbo.protocol.triple.*` 是一类配置」 | 前三者是**环境变量**、后三者是**全局配置**，读取 API 都不同 | 配置写错位置不生效 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)
- [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)
- [Invocation](/docs/CS/Framework/Dubbo/Invocation.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)
- [Auth](/docs/CS/Framework/Dubbo/Auth.md)

## References

1. [Apache Dubbo 3 官方文档](https://cn.dubbo.apache.org/zh-cn/overview/what/)
2. [dubbo-rpc-triple 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-rpc/dubbo-rpc-triple)
