## Introduction

任何一次 RPC 调用，最终都要回答一个问题：一个 Java 对象如何变成字节流，又如何变回来？序列化选错了，轻则性能糟糕，重则直接被打出反序列化漏洞。Dubbo 在这一层做了一件大多数框架没做的事——它不绑死某一种序列化，而是把序列化做成 SPI 扩展，并且在 3.x 里给整个机制套上了一层**运行时安全检查**（类白名单/黑名单校验），这正是 CVE-2020-1948（Hessian2 反序列化 RCE）之后补上的防线。

围绕 Dubbo 序列化有三个广为流传、但与 3.3.6 源码不符的直觉，开篇先破：

- **「Dubbo 内置支持 kryo / fst / protostuff / gson / jackson 等一堆序列化」——不成立。** 主仓库 `dubbo-serialization/` 下只有 3 个子模块，真正注册的 `Serialization` 扩展只有 `hessian2`、`fastjson2` 两个实现加一个异常包装器；其余实现全部外置在独立的 `dubbo-spi-extensions` 仓库，主仓库只留了 ID 常量。
- **「序列化安全检查默认是 WARN 级别」——不成立。** `SerializeCheckStatus` 的默认值就是 `STRICT`，且默认放行清单不是宽泛的包前缀，而是一份逐条类名的 allowlist 文件。
- **「配置项叫 `serialize.check.status` 或 `serialize.checker`」——不成立。** 真实配置 key 是 `dubbo.application.serialize-check-status`，这些网传 key 在源码里根本不存在。

本文所有结论来自 Apache Dubbo **3.3.6** 官方源码（`apache/dubbo` 仓库 tag `dubbo-3.3.6`），默认值一律标注文件与行号，网上流传但与源码不符的说法会在文中显式标出。

## 序列化 SPI 与扩展清单

### 主仓库的真实模块结构

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

### ID 常量表：主仓库留下的只有编号

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

### Serialization 接口契约

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

### wrapper 扩展：异常包装器

注册清单里的 `wrapper=` 条目值得单独说明。`DefaultSerializationExceptionWrapper` 是一个装饰器，它在反序列化抛出异常时，把底层 IO 异常统一包装成 Dubbo 语义的 `SerializeException`（带 `isSerializationException` 标记），使上层能把「序列化本身出错」与「网络断开」区分开——前者应提示客户端检查类型与安全配置，后者应走重连逻辑。Dubbo SPI 的 wrapper 机制（命名以 `wrapper` 开头自动包裹所有实现）保证了这一层对所有序列化实现透明生效。

## 默认值与优先级

### 默认远程序列化是 hessian2

```java
// dubbo-serialization/dubbo-serialization-api/.../common/serialize/support/DefaultSerializationSelector.java:25
public static final String DEFAULT_REMOTING_SERIALIZATION_PROPERTY = "hessian2";
```

注意这和 Triple 的行为一致：即使协议换成 Triple，默认序列化依然是 `hessian2`，而不是很多人直觉里的 Protobuf。

### 配置 key 与优先级

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

## 多序列化协商（MultipleSerialization）

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

## Hessian2 实现细节

### hessian4 的命名陷阱

`Hessian2Serialization` 实际写入 content type 的名字是 `hessian4`——虽然 SPI 扩展名叫 `hessian2`，但底层用的是 Hessian 4.x 的库（`com.caucho.hessian4`，Maven 坐标 `com.caucho:hessian`）。对外配置写 `hessian2`，内部协商字符串却是 `hessian4`，排查 Triple 的 `serialize.multiple` 协商日志时会同时看到这两个名字，属于同一实现。

### allowNonSerializable 与类工厂放行

Hessian2 的对象输出工厂由 `Hessian2FactoryManager` 管理，其中有两处关键逻辑：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2FactoryManager.java:88-90
// 类工厂层面放行 org.apache.dubbo.* 整个包
hessian2SerializerFactory.getClassFactory().allow("org.apache.dubbo.*");

// :117-119
// 非序列化类的白名单同样放行 dubbo 包
hessian2SerializerFactory.getNonSerializableObjectFactory().allow("org.apache.dubbo.*");
```

也就是说，无论安全检查配置得多严格，`org.apache.dubbo.*` 在 Hessian2 这一层始终是放行的——这是框架自身类型（`URL`、`RpcInvocation` 等）能正常传输的保障。而控制「是否允许序列化未实现 `Serializable` 接口的类」的开关：

```java
// dubbo-serialization/dubbo-serialization-hessian2/.../hessian2/Hessian2FactoryManager.java（dubbo.hessian.allowNonSerializable 读取处）
// 默认 "false"：非 Serializable 类默认拒绝序列化
boolean allowNonSerializable = Boolean.parseBoolean(
    url.getParameter("dubbo.hessian.allowNonSerializable", "false"));
```

`dubbo.hessian.allowNonSerializable` 默认 `"false"`，与 Hessian 官方 `SerializerFactory#setAllowNonSerializable` 的语义一致。

## 序列化安全（3.x 的核心防线）

### 背景：CVE-2020-1948

2020 年的 CVE-2020-1948 是一条完整的 Hessian2 反序列化 RCE 链：攻击者伪造请求体，借助 Hessian2 的类还原机制触发 gadget 链。之后 Dubbo 逐步落地了 `SerializeSecurityManager` 体系——请求体里出现的每一个反序列化目标类，都要先过安全检查。详见 [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) 中该 CVE 的链接。

### 类名打假

先纠正两个网上流传的类名：

- **不存在 `SerializationSecurityManager` 这个类**。真实执行类校验的是 `org.apache.dubbo.common.utils.DefaultSerializeClassChecker`，安全管理与配置分发给 `SerializeSecurityManager` 和 `SerializeSecurityConfigurator`。
- **不存在 `AllowClassChecker` 这个类**。放行/阻断逻辑在 `DefaultSerializeClassChecker` 内部实现。

### 状态机：默认就是 STRICT

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/utils/AllowClassNotifyListener.java:23
public static final SerializeCheckStatus DEFAULT_STATUS = SerializeCheckStatus.STRICT;
```

`SerializeSecurityManager` 初始化时若未显式配置，就回落到这个默认值（`SerializeSecurityManager.java:42,137-139`）。`SerializeCheckStatus` 共三档：

- `STRICT`：默认。只放行 allowlist 与注册接口自动信任的类型，其余阻断；
- `WARN`：放行但打告警日志；
- `DISABLE`：完全关闭检查。

**「默认是 WARN」的说法不成立**——从引入这套机制起，默认就是 `STRICT`。

### refreshStatus()：两个系统属性的开关语义

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

### allowlist 与 blockedlist：逐条类名，不是包前缀

默认放行清单不是 `java.util.*` 这类宽泛前缀，而是一份**逐条类名**的文件：

- `dubbo-common/src/main/resources/security/serialize.allowlist`：含 `java.lang.String`、`java.util.HashMap`、`org.apache.dubbo.common.URL`、`org.apache.dubbo.rpc.RpcException` 等具体类，一条一行；
- `dubbo-common/src/main/resources/security/serialize.blockedlist`：含 `com.alibaba.fastjson.annotation`、`com.caucho.`、`java.rmi`、`javax.naming.` 等高风险包/类，一条一行。

两个文件的路径常量定义在 `CommonConstants.java:449,451`（`SERIALIZE_ALLOW_LIST_PATH` / `SERIALIZE_BLOCK_LIST_PATH`）。blockedlist 里的条目**在任何状态下都会被阻断**，即使开了 `openCheckClass=false` 之外的宽松配置，`com.caucho.`、`javax.naming.` 这些经典 gadget 来源也进不来。

### 自动信任：被导出接口的类型自动放行

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

### 配置项真名清单

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

## 跨语言序列化选择

`fastjson2` 之所以是主仓库唯二的注册实现之一，定位很清晰：它是纯 JSON 语义的序列化，任何语言都能消费，适合泛化调用、HTTP 网关侧的场景。而 Protobuf 类型的「跨语言」走的是另一条路——如果方法签名本身是 Protobuf 生成类，Triple 直接做 PB 直通打包（见 [Triple](/docs/CS/Framework/Dubbo/Triple.md)），根本不经过 `Serialization` SPI 的通用对象序列化路径。

想用 kryo / fury / protostuff 等高性能序列化时的正确姿势：

1. 引入 `org.apache.dubbo.extensions:dubbo-serialization-kryo` 等对应 artifact（来自 `dubbo-spi-extensions` 仓库）；
2. 该 artifact 会通过 SPI 自动注册 `Serialization` 扩展；
3. 配置 `serialization=kryo` 或加入 `prefer.serialization` 列表。

协议头里的 ID（如 kryo=8、fury=28）不需要也无法自定义——ID 空间由主仓库 `Constants.java` 统一编号，客户端与服务端必须引入一致版本的扩展实现，否则会出现「ID 认识、实现没有」的解码失败。

## 默认值汇总表

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
| `dubbo.hessian.allowNonSerializable` | `"false"` | Hessian2FactoryManager |
| Hessian2 固定放行 | `org.apache.dubbo.*` | `Hessian2FactoryManager.java:88-90,117-119` |

## 陷阱清单

| 直觉/网传说法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「内置 kryo/fst/protostuff/gson 等序列化」 | 实现在 `dubbo-spi-extensions` 仓库，主仓库只有 ID 常量（`Constants.java:19-40`） | 直接配置 `serialization=kryo` 报找不到扩展 |
| 「安全检查默认 WARN」 | 默认 `STRICT`（`AllowClassNotifyListener.java:23`） | 新增 DTO 未被自动信任时线上直接反序列化失败 |
| 配置 `serialize.check.status` / `serialize.checker` / `serialize.allowlist` | 这些 key 不存在 | 配置静默失效，策略以为生效实则没有 |
| 类名 `SerializationSecurityManager` / `AllowClassChecker` | 真名 `DefaultSerializeClassChecker` / `SerializeSecurityManager` / `SerializeSecurityConfigurator` | 搜代码、写排查文档时找错类 |
| 「allowlist 是 `java.*`、`javax.*` 这类包前缀」 | 是逐条类名文件 `security/serialize.allowlist` | 以为某些类默认放行，实际被 STRICT 拦截 |
| 「检查器无法定制放行业务类」 | `autoTrustSerializeClass` 自动信任接口签名类型，`allowedClassList` 可显式补充 | 不必要的 `DISABLE` 降级，留下安全口子 |
| SPI 名 `hessian2` 即 Hessian 2.x 协议 | 实现基于 Hessian 4.x，内部协商名为 `hessian4` | 协商日志看到 `hessian4` 误以为配置错了 |
| 「`org.apache.dubbo.*` 也会被 STRICT 拦截」 | Hessian2 层固定放行（`Hessian2FactoryManager.java:88-90`） | 误判为安全配置问题 |

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
