## Introduction

任何一次 RPC 调用，最终都要回答一个问题：一个 Java 对象如何变成字节流，又如何变回来？序列化选错了，轻则性能糟糕，重则直接被打出反序列化漏洞。Dubbo 在这一层做了一件大多数框架没做的事——它不绑死某一种序列化，而是把序列化做成 SPI 扩展，并且在 3.x 里给整个机制套上了一层**运行时安全检查**（类白名单/黑名单校验），这正是 CVE-2020-1948（Hessian2 反序列化 RCE）之后补上的防线。

围绕 Dubbo 序列化有三个广为流传、但与 3.3.6 源码不符的直觉，开篇先破：

- **「Dubbo 内置支持 kryo / fst / protostuff / gson / jackson 等一堆序列化」——不成立。** 主仓库 `dubbo-serialization/` 下只有 3 个子模块，真正注册的 `Serialization` 扩展只有 `hessian2`、`fastjson2` 两个实现加一个异常包装器；其余实现全部外置在独立的 `dubbo-spi-extensions` 仓库，主仓库只留了 ID 常量。
- **「序列化安全检查默认是 WARN 级别」——不成立。** `SerializeCheckStatus` 的默认值就是 `STRICT`，且默认放行清单不是宽泛的包前缀，而是一份逐条类名的 allowlist 文件。
- **「配置项叫 `serialize.check.status` 或 `serialize.checker`」——不成立。** 真实配置 key 是 `dubbo.application.serialize-check-status`，这些网传 key 在源码里根本不存在。

本文所有结论来自 Apache Dubbo **3.3.6** 官方源码（`apache/dubbo` 仓库 tag `dubbo-3.3.6`），默认值一律标注文件与行号，网上流传但与源码不符的说法会在文中显式标出。

## Serialization SPI and Extension List

### Actual Module Structure of the Main Repo

`dubbo-serialization/` 目录下**只有 3 个子模块**：

- `dubbo-serialization-api`：SPI 接口 + 常量 + 异常包装器 + 默认序列化选择器；
- `dubbo-serialization-fastjson2`：`FastJson2Serialization`；
- `dubbo-serialization-hessian2`：`Hessian2Serialization`（默认实现）。

对应地，`Serialization` 接口的 SPI 扩展文件里真实注册的只有 3 条：

```properties
# dubbo-serialization/dubbo-serialization-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.serialize.Serialization
wrapper=org.apache.dubbo.common.serialize.DefaultSerializationExceptionWrapper
hessian2=org.apache.dubbo.common.serialize.hessian2.Hessian2Serialization

# dubbo-serialization/dubbo-serialization-fastjson2/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.serialize.Serialization
fastjson2=org.apache.dubbo.common.serialize.fastjson2.FastJson2Serialization
```

> [!WARNING]
> 「Dubbo 内置 kryo / fst / protostuff / avro / gson / jackson / nativejava / msgpack / fury / protobuf 序列化」这句话在 3.3.6 主仓库语境下**不成立**。这些实现类不在 `apache/dubbo` 主仓库，而在独立的 `dubbo-spi-extensions` 仓库（`org.apache.dubbo.extensions`）。主仓库里它们只以「ID 常量」的形式存在，用于协议头里标识序列化类型。

### ID Constant Table: Only Numbers Left in the Main Repo

`dubbo-serialization-api/.../serialize/Constants.java:19-40` 定义了全部序列化 ID，这是主仓库对「缺失实现」留下的唯一痕迹：

```java
// dubbo-serialization/dubbo-serialization-api/.../common/serialize/Constants.java:19-40
byte HESSIAN2_SERIALIZATION_ID = 2;
byte JAVA_SERIALIZATION_ID = 3;
byte COMPACTED_JAVA_SERIALIZATION_ID = 4;
byte FASTJSON_SERIALIZATION_ID = 6;
byte NATIVE_JAVA_SERIALIZATION_ID = 7;
byte KRYO_SERIALIZATION_ID = 8;
byte FST_SERIALIZATION_ID = 9;
byte NATIVE_HESSIAN_SERIALIZATION_ID = 10;
byte AVRO_SERIALIZATION_ID = 11;
byte PROTOSTUFF_SERIALIZATION_ID = 12;
byte GSON_SERIALIZATION_ID = 16;
byte JACKSON_SERIALIZATION_ID = 18;
byte PROTOBUF_JSON_SERIALIZATION_ID = 21;
byte PROTOBUF_SERIALIZATION_ID = 22;
byte FASTJSON2_SERIALIZATION_ID = 23;
byte KRYO2_SERIALIZATION_ID = 25;
byte MSGPACK_SERIALIZATION_ID = 27;
byte FURY_SERIALIZATION_ID = 28;
byte CUSTOM_MESSAGEPACK_SERIALIZATION_ID = 31;
```

这张表的实践含义：协议头 flag 字段的低 5 位（见 [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)）就是从这里取值。哪怕你通过 `dubbo-spi-extensions` 引入了 `kryo`，协议头里写的也是数字 `8`——ID 空间由主仓库统一管理，实现可以外置。

另一个容易漏看的扩展点：多类型序列化（一条连接上协商多种序列化，Triple 用得多）的默认实现也注册在主仓库：

```properties
# dubbo-serialization/dubbo-serialization-api/.../META-INF/dubbo/internal/org.apache.dubbo.common.serialize.MultipleSerialization
default=org.apache.dubbo.common.serialize.DefaultMultipleSerialization
```

### Serialization Interface Contract

所有实现共同遵守的 SPI 接口定义在 `dubbo-serialization-api`：

```java
// dubbo-serialization/dubbo-serialization-api/.../common/serialize/Serialization.java
@SPI
public interface Serialization {
    // 协议头低 5 位写入的 id，即 Constants.java 中那 19 个常量
    byte getContentTypeId();

    // 协商/日志用的名字，如 "hessian2"、"fastjson2"
    String getContentType();

    // 请求头 side：objectOutput 用 buffer 做缓冲（可关），ObjectInput 立即读
    @Adaptive
    ObjectOutput serialize(URL url, OutputStream out) throws IOException;

    @Adaptive
    ObjectInput deserialize(URL url, InputStream is) throws IOException;
}
```

接口只约定「id、名字、读、写」四件事。实现方不需要感知协议头布局——flag 位的组装在 `ExchangeCodec` 里完成，序列化实现只负责对象与流的转换。这也是为什么扩展外置到 `dubbo-spi-extensions` 后无需改动协议层：ID 空间主仓库已预留，实现只需报告自己的 `getContentTypeId()`。

### wrapper Extension: Exception Wrapper

注册清单里的 `wrapper=` 条目值得单独说明。`DefaultSerializationExceptionWrapper` 是一个装饰器，它在反序列化抛出异常时，把底层 IO 异常统一包装成 Dubbo 语义的 `SerializeException`（带 `isSerializationException` 标记），使上层能把「序列化本身出错」与「网络断开」区分开——前者应提示客户端检查类型与安全配置，后者应走重连逻辑。Dubbo SPI 的 wrapper 机制（命名以 `wrapper` 开头自动包裹所有实现）保证了这一层对所有序列化实现透明生效。

## Default Values and Priority

### Default Remote Serialization Is hessian2

```java
// dubbo-serialization/dubbo-serialization-api/.../common/serialize/support/DefaultSerializationSelector.java:25
public static final String DEFAULT_REMOTING_SERIALIZATION_PROPERTY = "hessian2";
```

注意这和 Triple 的行为一致：即使协议换成 Triple，默认序列化依然是 `hessian2`，而不是很多人直觉里的 Protobuf。

### Configuration key and Priority

三个相关配置 key 的定义位置：

| key | 定义位置 | 说明 |
| :--- | :--- | :--- |
| `serialization` | `dubbo-remoting-api/.../remoting/Constants.java:89` | 单一序列化名 |
| `prefer.serialization` | `dubbo-remoting-api/.../remoting/Constants.java:94` | 逗号分隔的偏好列表 |
| `serialize.multiple` | `dubbo-common/.../config/Constants.java:130` | 是否启用多序列化协商，默认 `"default"`（`CommonConstants.DEFAULT_KEY`） |

三者的优先级核心逻辑在 `UrlUtils.serializationId(URL)`，共 18 行，完整引用如下：

```java
// dubbo-remoting/dubbo-remoting-api/.../remoting/utils/UrlUtils.java:92-109
public static byte serializationId(URL url) {
    // prefer.serialization 列表优先：从左到右找到第一个可用的序列化
    String preferred = url.getParameter(Constants.PREFER_SERIALIZATION_KEY);
    if (preferred != null) {
        String[] preferredList = preferred.split(",");
        for (String preferredSerialization : preferredList) {
            Serialization serialization = FrameworkModel.defaultModel()
                .getExtensionLoader(Serialization.class)
                .getExtension(preferredSerialization.trim());
            if (serialization != null) {
                return serialization.getContentTypeId();
            }
        }
    }

    // 其次是 serialization 单值配置
    String serializationName = url.getParameter(Constants.SERIALIZATION_KEY,
        DefaultSerializationSelector.DEFAULT_REMOTING_SERIALIZATION_PROPERTY);
    Serialization serialization = FrameworkModel.defaultModel()
        .getExtensionLoader(Serialization.class)
        .getExtension(serializationName);
    return serialization.getContentTypeId();
}
```

结论：**`prefer.serialization` 列表 > `serialization` 单值 > 默认 `hessian2`**。`prefer.serialization` 的设计意图是客户端与服务端各持有一份偏好列表，协商时取双方都支持的第一个。

## Multi-Serialization Negotiation (MultipleSerialization)

`serialize.multiple` 打开后，Dubbo 不再把「一次部署一种序列化」当成前提，而是允许同一连接上按请求选择序列化。默认实现：

```java
// dubbo-serialization/dubbo-serialization-api/.../common/serialize/DefaultMultipleSerialization.java
// SPI 注册：default=org.apache.dubbo.common.serialize.DefaultMultipleSerialization
public class DefaultMultipleSerialization implements MultipleSerialization {
    // 按 URL 上协商好的序列化名，取对应 Serialization 实现写对象
    @Override
    public void serialize(URL url, String serializeType, OutputStream os, Object[] data) {
        Serialization serialization = FrameworkModel.defaultModel()
            .getExtensionLoader(Serialization.class)
            .getExtension(serializeType);
        // ... 逐对象写出，并在流头记录序列化类型
    }
}
```

Triple 是这个机制的主要消费者：`serialize.multiple=default` 语义为「使用框架默认协商策略」，客户端取自己的 `prefer.serialization` 首选、与对端注册的序列化能力求交集。注意协商使用的名字（`getContentType()`）与 SPI 名可能不同——Hessian2 在协商字符串里就表现为 `hessian4`（见上一节）。

## Hessian2 Implementation Details

### hessian4 Naming Trap

`Hessian2Serialization` 写入 content type 的名字是 **`x-application/hessian2`**（`dubbo-serialization/.../hessian2/Hessian2Serialization.java:63-65`），与 SPI 扩展名 `hessian2` 一致。

`hessian4` 这个名字出现在**另一个地方**——Triple 的 wrapper 路径。`ReflectionPackableMethod` 在把序列化类型写进 wrapper 头之前会做一次换算：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/ReflectionPackableMethod.java:424-428
private String convertHessianToWrapper(String serializeType) {
    if (TripleConstants.HESSIAN2.equals(serializeType)) {
        return TripleConstants.HESSIAN4;    // "hessian4"
    }
    return serializeType;
}
```

`TripleConstants.HESSIAN4 = "hessian4"` 与 `HESSIAN2 = "hessian2"` 并列定义在 `dubbo-rpc/dubbo-rpc-triple/.../tri/TripleConstants.java:27,29`。所以：**Dubbo 协议头里写的是序列化 id `2`，Triple 的 wrapper 头里写的是字符串 `hessian4`，而 `Serialization.getContentType()` 返回 `x-application/hessian2`** —— 三个名字指同一个实现，排查时看到任何一个都要先确认自己在看哪一层。

底层库也不是 `com.caucho:hessian` 而是 Dubbo 自己维护的 **`org.apache.dubbo:hessian-lite`**（`dubbo-serialization/dubbo-serialization-hessian2/pom.xml:39-42`，版本 `4.0.4` 见 `dubbo-dependencies-bom/pom.xml:171`），包名是 `com.alibaba.com.caucho.hessian.io`——`Hessian2Serialization` 静态块里校验的正是 `com.alibaba.com.caucho.hessian.io.Hessian2Output`。

### allowNonSerializable and Class Factory Bypass

Hessian2 的对象输出工厂由 `Hessian2FactoryManager` 管理，按 **ClassLoader 维度**缓存 `SerializerFactory`（`dubbo-serialization/.../hessian2/Hessian2FactoryManager.java:45`）：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2FactoryManager.java:85-92
private SerializerFactory createDefaultSerializerFactory(ClassLoader classLoader) {
    Hessian2SerializerFactory hessian2SerializerFactory =
            new Hessian2SerializerFactory(classLoader, defaultSerializeClassChecker);
    hessian2SerializerFactory.setAllowNonSerializable(Boolean.parseBoolean(
            SystemPropertyConfigUtils.getSystemProperty(DUBBO_HESSIAN_ALLOW_NON_SERIALIZABLE, "false")));
    hessian2SerializerFactory.getClassFactory().allow("org.apache.dubbo.*");
    return hessian2SerializerFactory;
}
```

两处关键点：

- **类工厂层面放行 `org.apache.dubbo.*`**（`:90`）——这是框架自身类型（`URL`、`RpcInvocation` 等）能正常传输的保障，**与安全检查配置无关，无条件生效**。白名单模式分支（`createWhiteListSerializerFactory`，`:94-121`）在最后也补了同一行（`:119`），所以无论走哪条路径这个放行都存在。
- **`allowNonSerializable` 读的是 JVM 系统属性，不是 URL 参数**。常量 `DUBBO_HESSIAN_ALLOW_NON_SERIALIZABLE = "dubbo.hessian.allowNonSerializable"` 定义在 `dubbo-common/.../constants/CommonConstants.java:784`（`DubboProperty` 接口内），读取走 `SystemPropertyConfigUtils.getSystemProperty(key, "false")`——**必须是 `-Ddubbo.hessian.allowNonSerializable=true` 启动参数或系统属性**，写成 URL 上的 `dubbo.hessian.allowNonSerializable=true` **不生效**。

> [!WARNING]
> **不存在 `getNonSerializableObjectFactory()` 这个方法。** 全仓库（`grep -rn "getNonSerializableObjectFactory" --include=*.java .`）搜不到任何定义或调用——它既不在 Hessian 官方库里，也不在 Dubbo 的 `Hessian2SerializerFactory` / `Hessian2FactoryManager` 里。「非序列化对象工厂」这个概念在 Hessian 4.x 里由 `SerializerFactory#isAllowNonSerializable()` 这个开关表达（见下），不是通过一个独立工厂对象放行的。

`allowNonSerializable` 的最终语义由 `Hessian2SerializerFactory.checkSerializable` 决定——**它同时看 Hessian 自己的开关和 Dubbo 的 `checkSerializable` 开关，两者都放行才允许**：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2SerializerFactory.java:92-101
private void checkSerializable(Class<?> cl) {
    // If class is Serializable => ok
    // If class has not implement Serializable
    //      If hessian check serializable => fail
    //      If dubbo class checker check serializable => fail
    //      If both hessian and dubbo class checker allow non-serializable => ok
    if (!Serializable.class.isAssignableFrom(cl)
            && (!isAllowNonSerializable() || defaultSerializeClassChecker.isCheckSerializable())) {
        throw new IllegalStateException(
                "Serialized class " + cl.getName() + " must implement java.io.Serializable");
    }
}
```

因此「Dubbo 侧把 `check-serializable` 关掉」**并不足以**让非 `Serializable` 类通过——Hessian 侧的 `allowNonSerializable` 也必须同时为 true。反过来 `dubbo.hessian.allowNonSerializable=false`（默认）时，无论 Dubbo 侧怎么配，非 `Serializable` 类一律抛 `IllegalStateException`。

### Class Loading Hook loadSerializedClass

安全检查真正的落点在 `Hessian2SerializerFactory` 覆写的 `loadSerializedClass` 上——Hessian 每次还原类名时都会调它：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2SerializerFactory.java:45-48
@Override
public Class<?> loadSerializedClass(String className) throws ClassNotFoundException {
    return defaultSerializeClassChecker.loadClass(getClassLoader(), className);
}
```

也就是说，**Dubbo 把「类名 → Class」的解析权接管了**：还原请求体里出现的类名时，先过 `DefaultSerializeClassChecker.loadClass`（`dubbo-common/.../utils/DefaultSerializeClassChecker.java:108`），命中 blockedlist 或不在 allowlist 就抛异常。`getDefaultSerializer` / `getDefaultDeserializer`（`:51-70`、`:69-87`）在取默认序列化器前还会额外做一次 `defaultSerializeClassChecker.loadClass(...)` 预检。

这就是 CVE-2020-1948 之后的关键防线位置：**不是靠「序列化完之后再看类名」，而是在类被加载的那一刻就拦下**。与之配套的 `Hessian2ScopeModelInitializer`（`dubbo-serialization/.../hessian2/Hessian2ScopeModelInitializer.java`）在 `FrameworkModel` 初始化时注册 `Hessian2FactoryManager` Bean 并挂上 `Hessian2ClassLoaderListener`，保证 ClassLoader 回收时对应的 `SerializerFactory` 一并从 `CL_2_SERIALIZER_FACTORY` 移除（`Hessian2FactoryManager.onRemoveClassLoader`，`:123-125`）——否则会因 ClassLoader 泄漏导致工厂里的类引用无法回收。

## Serialization Security (Core Defense Line of 3.x)

### Background: CVE-2020-1948

2020 年的 CVE-2020-1948 是一条完整的 Hessian2 反序列化 RCE 链：攻击者伪造请求体，借助 Hessian2 的类还原机制触发 gadget 链。之后 Dubbo 逐步落地了 `SerializeSecurityManager` 体系——请求体里出现的每一个反序列化目标类，都要先过安全检查。详见 [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) 中该 CVE 的链接。

### Debunk Class Names

先纠正两个网上流传的类名：

- **不存在 `SerializationSecurityManager` 这个类**。真实执行类校验的是 `org.apache.dubbo.common.utils.DefaultSerializeClassChecker`，安全管理与配置分发给 `SerializeSecurityManager` 和 `SerializeSecurityConfigurator`。
- **不存在 `AllowClassChecker` 这个类**。放行/阻断逻辑在 `DefaultSerializeClassChecker` 内部实现。

### State Machine: The Default Is STRICT

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/utils/AllowClassNotifyListener.java:23
public static final SerializeCheckStatus DEFAULT_STATUS = SerializeCheckStatus.STRICT;
```

`SerializeSecurityManager` 初始化时若未显式配置，就回落到这个默认值（`SerializeSecurityManager.java:42,137-139`）。`SerializeCheckStatus` 共三档：

- `STRICT`：默认。只放行 allowlist 与注册接口自动信任的类型，其余阻断；
- `WARN`：放行但打告警日志；
- `DISABLE`：完全关闭检查。

**「默认是 WARN」的说法不成立**——从引入这套机制起，默认就是 `STRICT`。

### refreshStatus(): Switch Semantics of Two System Properties

`SerializeSecurityConfigurator.refreshStatus()`（`SerializeSecurityConfigurator.java:186-211`）按以下顺序决定最终状态：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/utils/SerializeSecurityConfigurator.java:186-211（逻辑摘录）
// 1. dubbo.security.serialize.openCheckClass，默认 "true"
//    设为 false → 整体 DISABLE，检查彻底关闭
boolean openCheck = Boolean.parseBoolean(
    cfg.getOrDefault(CommonConstants.SERIALIZE_OPEN_CHECK_CLASS_KEY, "true"));

// 2. dubbo.security.serialize.blockAllClassExceptAllow，默认 "false"
//    设为 true → 强制 STRICT（黑名单之外全拦截，即使配置了 serialize-check-status=WARN）
boolean blockAll = Boolean.parseBoolean(
    cfg.getOrDefault(CommonConstants.SERIALIZE_BLOCK_ALL_CLASS_EXCEPT_ALLOW_KEY, "false"));
```

即：`openCheckClass=false` 一票否决（DISABLE），`blockAllClassExceptAllow=true` 一票抬升（STRICT），`serialize-check-status` 只在这两个开关允许的范围内生效。

### allowlist and blockedlist: Per-Class Names, Not Package Prefixes

默认放行清单不是 `java.util.*` 这类宽泛前缀，而是一份**逐条类名**的文件：

- `dubbo-common/src/main/resources/security/serialize.allowlist`：含 `java.lang.String`、`java.util.HashMap`、`org.apache.dubbo.common.URL`、`org.apache.dubbo.rpc.RpcException` 等具体类，一条一行；
- `dubbo-common/src/main/resources/security/serialize.blockedlist`：含 `com.alibaba.fastjson.annotation`、`com.caucho.`、`java.rmi`、`javax.naming.` 等高风险包/类，一条一行。

两个文件的路径常量定义在 `CommonConstants.java:449,451`（`SERIALIZE_ALLOW_LIST_PATH` / `SERIALIZE_BLOCK_LIST_PATH`）。blockedlist 里的条目**在任何状态下都会被阻断**，即使开了 `openCheckClass=false` 之外的宽松配置，`com.caucho.`、`javax.naming.` 这些经典 gadget 来源也进不来。

### Automatic Trust: Exported Interface Types Are Automatically Allowed

严格模式之所以可用，是因为框架会**自动信任业务自己声明的类型**。`SerializeSecurityConfigurator.registerInterface()`（`:213-253`）在服务导出/引用时，把该接口的方法签名里出现的参数、返回值、异常类型全部注册进 allowlist。两个配套开关：

```java
// dubbo-common/.../utils/SerializeSecurityConfigurator.java:84-91
// dubbo.application.auto-trust-serialize-class，默认 true：自动信任接口签名中的类型
private boolean autoTrustSerializeClass = true;
// trust-serialize-class-level：自动信任时向下扫描的类/包层级，默认 Integer.MAX_VALUE（不设限）
private int trustSerializeClassLevel = Integer.MAX_VALUE;
// check-serializable：是否要求类实现 Serializable，默认 true
private boolean checkSerializable = true;
```

### Actual Configuration Item Name List

这一节是打假重灾区。**真实存在的配置项**只有以下这些：

| 配置项 | 定义位置 | 默认值 |
| :--- | :--- | :--- |
| `dubbo.application.serialize-check-status` | `CommonConstants.java:453`（`SERIALIZE_CHECK_STATUS_KEY`） | `STRICT` |
| `dubbo.application.auto-trust-serialize-class` | `ApplicationConfig.java:281`（`autoTrustSerializeClass`） | `true` |
| `dubbo.application.trust-serialize-class-level` | `ApplicationConfig.java:286`（`trustSerializeClassLevel`） | `Integer.MAX_VALUE` |
| `dubbo.application.check-serializable` | `ApplicationConfig.java:291`（`checkSerializable`） | `true` |
| `dubbo.security.serialize.openCheckClass` | `CommonConstants.java:750-753` | `"true"` |
| `dubbo.security.serialize.blockAllClassExceptAllow` | `CommonConstants.java:750-753` | `"false"` |
| `dubbo.security.serialize.allowedClassList` | `CommonConstants.java:750-753` | 无 |
| `dubbo.security.serialize.blockedClassList` | `CommonConstants.java:750-753` | 无 |
| `dubbo.application.hessian2.whitelist` | `CommonConstants.java:784-790` | 无 |
| `dubbo.application.hessian2.allow` | `CommonConstants.java:784-790` | 无 |
| `dubbo.application.hessian2.deny` | `CommonConstants.java:784-790` | 无 |

> [!WARNING]
> 网上流传的 `serialize.check.status`、`serialize.checker`、`serialize.allowlist` 作为配置 key 在 3.3.6 源码中**均不存在**。用这些 key 配置不会有任何效果，也不会报错——排查时如果发现安全策略「配了不生效」，先检查 key 名是不是写错了。

## Cross-Language Serialization Selection

`fastjson2` 之所以是主仓库唯二的注册实现之一，定位很清晰：它是纯 JSON 语义的序列化，任何语言都能消费，适合泛化调用、HTTP 网关侧的场景。而 Protobuf 类型的「跨语言」走的是另一条路——如果方法签名本身是 Protobuf 生成类，Triple 直接做 PB 直通打包（见 [Triple](/docs/CS/Framework/Dubbo/Triple.md)），根本不经过 `Serialization` SPI 的通用对象序列化路径。

想用 kryo / fury / protostuff 等高性能序列化时的正确姿势：

1. 引入 `org.apache.dubbo.extensions:dubbo-serialization-kryo` 等对应 artifact（来自 `dubbo-spi-extensions` 仓库）；
2. 该 artifact 会通过 SPI 自动注册 `Serialization` 扩展；
3. 配置 `serialization=kryo` 或加入 `prefer.serialization` 列表。

协议头里的 ID（如 kryo=8、fury=28）不需要也无法自定义——ID 空间由主仓库 `Constants.java` 统一编号，客户端与服务端必须引入一致版本的扩展实现，否则会出现「ID 认识、实现没有」的解码失败。

## Default Value Summary Table

| 项目 | 值 | 源码位置 |
| :--- | :--- | :--- |
| 默认远程序列化 | `hessian2` | `DefaultSerializationSelector.java:25` |
| 主仓库 `Serialization` 注册实现 | `hessian2`、`fastjson2` + `wrapper` | 各模块 SPI 文件 |
| `MultipleSerialization` 默认扩展 | `DefaultMultipleSerialization` | SPI 文件 `default=` 条目 |
| 优先级顺序 | `prefer.serialization` > `serialization` > 默认 | `UrlUtils.java:92-109` |
| `serialize.multiple` | `"default"` | `dubbo-common/.../config/Constants.java:130` |
| 默认检查状态 | `STRICT` | `AllowClassNotifyListener.java:23` |
| `openCheckClass` | `"true"` | `SerializeSecurityConfigurator.java:186-211` |
| `blockAllClassExceptAllow` | `"false"` | 同上 |
| `autoTrustSerializeClass` | `true` | `SerializeSecurityConfigurator.java:84-86` |
| `trustSerializeClassLevel` | `Integer.MAX_VALUE` | `SerializeSecurityConfigurator.java:87-89` |
| `checkSerializable` | `true` | `SerializeSecurityConfigurator.java:90-91` |
| `dubbo.hessian.allowNonSerializable` | `"false"`，**系统属性**（非 URL 参数） | `Hessian2FactoryManager.java:88-89`、`CommonConstants.java:784` |
| Hessian2 固定放行 | `org.apache.dubbo.*` | `Hessian2FactoryManager.java:90,119` |
| Hessian2 content type | `"x-application/hessian2"` | `Hessian2Serialization.java:63-65` |
| Triple wrapper 换算名 | `hessian2` → `hessian4` | `ReflectionPackableMethod.java:424-428` |
| Hessian2 底层依赖 | `org.apache.dubbo:hessian-lite:4.0.4` | `dubbo-serialization-hessian2/pom.xml:39-42` |

## Serialization Interface getContentTypeId and content type

`Serialization` 接口（`dubbo-serialization-api/.../common/serialize/Serialization.java`）只约定四类能力，`@SPI(scope = ExtensionScope.FRAMEWORK)`：

```java
// dubbo-serialization-api/.../common/serialize/Serialization.java:36-76
@SPI(scope = ExtensionScope.FRAMEWORK)
public interface Serialization {
    byte getContentTypeId();     // :46 写入协议头 flag 低 5 位
    String getContentType();     // :53 协商/日志用的名字，如 "x-application/hessian2"
    @Adaptive ObjectOutput serialize(URL url, OutputStream output);
    @Adaptive ObjectInput deserialize(URL url, InputStream input);
}
```

两个关键约束（接口 javadoc 明确写）：

- `getContentTypeId()` 的返回值**必须 ≤ `ExchangeCodec.SERIALIZATION_MASK`（31）**，因为 Dubbo 私有协议头只用 5 个 bit 记录序列化 id（见 [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)）。主仓库 `Constants.java` 的 ID 表最大到 `FURY_SERIALIZATION_ID = 28`，全部在 31 以内——外置扩展若要自定义 id 也不能越界。
- `getContentTypeId()`（数字）与 `getContentType()`（字符串）是两套命名空间：协议头只认数字 id，而 `serialize.multiple` 协商、日志、Triple 的 `hessian4`/`hessian2` 换算走的是字符串名。**不存在 `getSerializationId()` 这个方法**，网上若见到这个名字是误记。

## FastJson2 autotype and blacklist

`FastJson2Serialization` 是主仓库唯二注册实现之一，它的反序列化安全不是自己实现的，而是复用全局的 `SerializeSecurityManager`，并借 fastjson2 的 `ContextAutoTypeBeforeHandler` 在「autotype」那一刻做拦截：

```java
// dubbo-serialization/.../fastjson2/FastJson2Serialization.java:57-64
public byte getContentTypeId() { return FASTJSON2_SERIALIZATION_ID; }   // 23
public String getContentType() { return "text/jsonb"; }
// serialize/deserialize 都会取出 fastjson2SecurityManager Bean 传给 ObjectOutput/Input
Fastjson2SecurityManager fastjson2SecurityManager = ...getBean(Fastjson2SecurityManager.class);
```

```java
// dubbo-serialization/.../fastjson2/Fastjson2SecurityManager.java:103-170
public static class Handler extends ContextAutoTypeBeforeHandler {   // 继承 fastjson2 的 autotype 前置处理器
    public Class<?> apply(String typeName, Class<?> expectClass, long features) {
        Class<?> tryLoad = super.apply(typeName, expectClass, features); // 1. fastjson2 自带 acceptNames 白名单
        if (tryLoad != null) return tryLoad;
        if (status == STRICT) {                                      // 2. STRICT 下不在白名单直接抛 IllegalArgumentException
            throw new IllegalArgumentException("[Serialization Security] ... not in allow list ...");
        }
        Class<?> localClass = loadClassDirectly(typeName);           // 3. WARN 下尝试加载
        ...
    }
    public boolean checkIfDisAllow(String typeName) {                // 4. 黑名单按前缀匹配
        return disAllowedList.stream().anyMatch(typeName::startsWith);
    }
}
```

也就是说，fastjson2 的 autotype 与普通 Hessian2 走**同一套** `security/serialize.allowlist` + `security/serialize.blockedlist`（见 [Serialization Security](/docs/CS/Framework/Dubbo/Serialization.md)），`Fastjson2SecurityManager` 实现了 `AllowClassNotifyListener`（`:38`），当 `SerializeSecurityManager` 的配置变化时通过 `notifyPrefix`（`:66-75`）/ `notifyCheckStatus`（`:78-86`）重建 `Handler`。`disAllowedList` 用「前缀匹配」（`startsWith`，`:168-170`）拦截经典 gadget 来源，与 Hessian2 侧 `com.caucho.*`、`javax.naming.*` 等 blockedlist 条目目标一致。

`checkIfDisAllow` 的调用点在类加载之前（`:179`）：类名命中 `disAllowedList` 前缀时直接返回 `null`（加载不到），**不抛异常**——所以 blockedlist 是「静默拒绝」，而「不在 allowlist 且处于 STRICT 模式」是「显式抛 `IllegalArgumentException`」，两者的失败表现不同，排障时看到的现象不一样。

## Why hessian2 is the default

默认远程序列化是 `hessian2` 并非偶然，几个事实叠加：

- 它是**主仓库唯一与 Triple、Dubbo 两套协议都内置兼容**的实现（Dubbo 协议头 id = 2；Triple 的 wrapper 路径也默认回落 hessian2）。
- 其余高性能实现（kryo / fst / protostuff / fury …）在 3.3.6 已整体外置到 `dubbo-spi-extensions`，主仓库只剩 ID 常量；而 `fastjson2` 虽在主仓库，语义是纯 JSON，不适合做默认二进制 RPC 体。
- 生效开关是 `DefaultSerializationSelector.DEFAULT_REMOTING_SERIALIZATION_PROPERTY = "hessian2"`（`dubbo-serialization-api/.../support/DefaultSerializationSelector.java:25`），`UrlUtils.serializationId` 在未显式配置时回落到这里。
- `Hessian2Serialization` 在静态块就校验 `com.alibaba.com.caucho.hessian.io.Hessian2Output` 是否在 classpath，缺失直接 `IllegalStateException("The hessian2 is not in classpath.")`，所以它对运行环境的依赖是硬绑定的。

> [!TIP]
> 默认值本身还可被**系统属性 / 环境变量**覆盖：`DefaultSerializationSelector` 除了硬编码的 `"hessian2"` 兜底，还会先读系统属性 `dubbo.default.remoting.serialization`，再读同名环境变量（`DefaultSerializationSelector.java:28-40`，常量 `DUBBO_DEFAULT_REMOTING_SERIALIZATION_PROPERTY`）。注意这与 URL 上的 `serialization` 参数是**两条独立路径**——前者是 JVM 级别的默认，后者是每次调用的协议协商。

代价是 hessian2 体积与性能不如 fury/kryo；需要更高吞吐时按「扩展外置实现 + `serialization=` / `prefer.serialization=`」方式切换即可（见 [Cross-Language Serialization Selection](/docs/CS/Framework/Dubbo/Serialization.md)）。

## Hessian2 Whitelist Mode and ClassLoader Scoping

`Hessian2FactoryManager` 有两条建工厂的路径，由系统属性 `dubbo.application.hessian2.whitelist` 是否非空决定（`dubbo-serialization/.../hessian2/Hessian2FactoryManager.java:77-83`）：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2FactoryManager.java:85-92
private SerializerFactory createDefaultSerializerFactory(ClassLoader classLoader) {
    Hessian2SerializerFactory hessian2SerializerFactory =
            new Hessian2SerializerFactory(classLoader, defaultSerializeClassChecker);
    hessian2SerializerFactory.setAllowNonSerializable(Boolean.parseBoolean(
            SystemPropertyConfigUtils.getSystemProperty(DUBBO_HESSIAN_ALLOW_NON_SERIALIZABLE, "false")));
    hessian2SerializerFactory.getClassFactory().allow("org.apache.dubbo.*");
    return hessian2SerializerFactory;
}
```

白名单模式（`createWhiteListSerializerFactory`，`:94-121`）有两条互斥分支：

| `dubbo.application.hessian2.whitelist` | 行为 |
| :--- | :--- |
| `"true"` | `getClassFactory().setWhitelist(true)`，按 `dubbo.application.hessian2.allow`（`;` 分隔的 pattern）逐条 `allow()`，并 `serializeSecurityManager.addToAlwaysAllowed(pattern)` + `setCheckStatus(STRICT)` |
| 其它非空值 | `setWhitelist(false)`，按 `dubbo.application.hessian2.deny` 逐条 `deny()` + `serializeSecurityManager.addToDisAllowed(pattern)` |

三个系统属性的常量定义在 `dubbo-common/.../constants/CommonConstants.java:786,788,790`（`DUBBO_HESSIAN_WHITELIST` / `DUBBO_HESSIAN_ALLOW` / `DUBBO_HESSIAN_DENY`），同样是**系统属性**而非 URL 参数。

> [!NOTE]
> 白名单模式有个容易被忽略的副作用：走 `"true"` 分支时会**强制把全局检查状态抬到 `STRICT`**（`:106`）。也就是说，只要设了 `dubbo.application.hessian2.whitelist=true`，即便别处把 `serialize-check-status` 配成 `WARN`，这一层也会把它拉回 `STRICT`。

工厂的**ClassLoader 维度隔离**是另一处关键设计：`Hessian2FactoryManager` 用 `ConcurrentHashMap<ClassLoader, SerializerFactory> CL_2_SERIALIZER_FACTORY`（`:40`）为每个 ClassLoader 建一份工厂，并额外维护一个 `stickySerializerFactory` 缓存「最近用过的那份」（`:43`、`:58-61`），避免每次序列化都做 map 查找。系统 ClassLoader（`classLoader == null`）走单独的 `SYSTEM_SERIALIZER_FACTORY` 单例（`:62-72`）。

## Pitfall List

| 直觉/网传说法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「内置 kryo/fst/protostuff/gson 等序列化」 | 实现在 `dubbo-spi-extensions` 仓库，主仓库只有 ID 常量（`Constants.java:19-40`） | 直接配置 `serialization=kryo` 报找不到扩展 |
| 「安全检查默认 WARN」 | 默认 `STRICT`（`AllowClassNotifyListener.java:23`） | 新增 DTO 未被自动信任时线上直接反序列化失败 |
| 配置 `serialize.check.status` / `serialize.checker` / `serialize.allowlist` | 这些 key 不存在 | 配置静默失效，策略以为生效实则没有 |
| 类名 `SerializationSecurityManager` / `AllowClassChecker` | 真名 `DefaultSerializeClassChecker` / `SerializeSecurityManager` / `SerializeSecurityConfigurator` | 搜代码、写排查文档时找错类 |
| 「allowlist 是 `java.*`、`javax.*` 这类包前缀」 | 是逐条类名文件 `security/serialize.allowlist` | 以为某些类默认放行，实际被 STRICT 拦截 |
| 「检查器无法定制放行业务类」 | `autoTrustSerializeClass` 自动信任接口签名类型，`allowedClassList` 可显式补充 | 不必要的 `DISABLE` 降级，留下安全口子 |
| SPI 名 `hessian2` 即 Hessian 2.x 协议 | 实现基于 `org.apache.dubbo:hessian-lite:4.0.4`，content type 是 `x-application/hessian2`；`hessian4` 只是 Triple wrapper 层的换算名 | 协商日志看到 `hessian4` 误以为配置错了 |
| 「`org.apache.dubbo.*` 也会被 STRICT 拦截」 | Hessian2 层固定放行（`Hessian2FactoryManager.java:90,119`） | 误判为安全配置问题 |
| 「`getContentType()` 返回 `hessian4`」 | 返回 `x-application/hessian2`；`hessian4` 来自 `ReflectionPackableMethod.convertHessianToWrapper` | 混淆协议层与 Triple wrapper 层 |
| 「有 `getNonSerializableObjectFactory()` 方法」 | 全仓库不存在该方法，非 Serializable 的判定在 `Hessian2SerializerFactory.checkSerializable` | 照抄代码编译不过 |
| 「`dubbo.hessian.allowNonSerializable` 是 URL 参数」 | 是 **JVM 系统属性**，读自 `SystemPropertyConfigUtils`；写成 URL 参数不生效 | 以为配了其实没配，序列化仍被拒 |
| 「关掉 `check-serializable` 就能传非 Serializable 类」 | `checkSerializable` 需与 hessian 侧 `allowNonSerializable` **同时**放行 | 单改一边仍抛 `IllegalStateException` |
| 类名 `FastJson2SecurityManager` | 真实类名 `Fastjson2SecurityManager`（小写 j） | 搜类名搜不到 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Triple](/docs/CS/Framework/Dubbo/Triple.md)
- [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)
- [SPI](/docs/CS/Framework/Dubbo/SPI.md)
- [config](/docs/CS/Framework/Dubbo/config.md)

## References

1. [Apache Dubbo 3.3.6 源码（tag dubbo-3.3.6）](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
2. [CVE-2020-1948 官方公告](https://apache.org/security/CVE-2020-1948)
3. [Dubbo 序列化安全官方文档](https://cn.dubbo.apache.org/zh-cn/blog/2023/01/16/%e5%ba%8f%e5%88%97%e5%8c%96%e5%ae%89%e5%85%a8/)
4. [dubbo-spi-extensions 仓库](https://github.com/apache/dubbo-spi-extensions)
