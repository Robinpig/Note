## Introduction

Dubbo 3 最根本的变化，是把默认通信协议从 Dubbo 协议（TCP 私有二进制）换成了 Triple。Triple 构建在 HTTP/2 之上，协议层与 [gRPC](/docs/CS/Framework/gRPC/gRPC.md) 完全兼容，同时保留了 Dubbo 的服务发现与治理能力。它的设计目标很明确：让 Dubbo 服务的流量能被网关、代理、Service Mesh 这类通用组件识别，并让「Java 接口优先」与「Protobuf IDL 优先」两种开发方式共存。

围绕 Triple 有三个极易踩错的直觉，开篇先逐条破除：

- **协议名不是 `triple`，而是 `tri`。** SPI 里注册的名字是 `tri`、`grpc`、`rest2` 三个，全仓库不存在 `triple=` 的注册项。3.3.6 的 `Protocol` 接口甚至已经删掉了 `getName()`，协议名只由 SPI 扩展名决定，所以「协议名」就是「扩展名」。
- **Triple 的默认序列化不是 Protobuf，而是 `hessian2`。** 只有当参数或返回值本身就是 Protobuf 生成类时，才走 Protobuf 直通打包（`PbArrayPacker` / `PbUnpack`）；普通 Java POJO、泛化调用仍走包装器（wrapper），默认 `hessian2`——在 wrapper 内部会被转换成 `hessian4` 这个名字。
- **3.3 的 Triple 运行时已经不再依赖 grpc-java。** 它改用自研的 `dubbo-remoting-http12` 加 Netty 原生 HTTP/2 编解码器；`io.grpc` 只留下 health / reflection 的生成桩与若干字符串常量。

本文所有结论来自 Apache Dubbo **3.3.6** 官方源码（`apache/dubbo` 仓库 tag `dubbo-3.3.6`），默认值一律标注文件与行号，网上流传但与源码不符的说法会在文中显式标出。

## 协议注册与命名

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

## 与 gRPC 的兼容边界

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

## 四种调用模式

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

## 序列化：先看是不是 Protobuf 类型

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

### 序列化的优先级

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

## 端口与单端口多协议

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

## 两种开发模式

### Java 接口优先（无 IDL）

直接写 Java 接口 + Dubbo 注解，序列化回落 hessian2。这是从 Dubbo 2.x 迁移过来的团队最省事的路径：

```java
@DubboService   // 暴露服务
public class DemoServiceImpl implements DemoService { ... }

@DubboReference // 引用服务
private DemoService demoService;
```

### IDL 优先（Protobuf）

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

## REST 能力

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

## 陷阱清单

| 直觉写法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| `dubbo.protocol.name=triple` | 协议名是 `tri`，无 `triple` 扩展 | 启动时报找不到扩展 |
| 「Triple 默认 Protobuf 序列化」 | 默认 `hessian2`，仅 Protobuf 类型走 PB 直通 | 误判跨语言互操作能力 |
| 「Triple 依赖 grpc-java」 | 3.3 已切自研 Netty HTTP/2 实现 | 依赖冲突排查时找错方向 |
| 「`getName()` 判断协议类型」 | 3.3.6 `Protocol` 已无该方法 | 编译不过 |
| 「单端口多协议默认开启」 | 需 `ext.protocol` + `ispuserver=true` | 端口复用不生效 |
| 「`@DubboService(protobuf=true)`」 | 注解无 `protobuf` 属性 | 编译不过 |

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
