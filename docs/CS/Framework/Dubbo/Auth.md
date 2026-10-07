## Introduction

RPC 框架之间的能力差距，最终都会落到一个问题上：**你怎么确认屏幕对面的那个进程，不是随便谁都能调你？** Dubbo 为这个问题准备了三块互不相干的地基——凭据签名与校验（`dubbo-auth`）、证书签发与托管（`dubbo-security`）、Spring Security 上下文透传（`dubbo-spring-security`）。它们名字都带 security，职责却完全不搭界，混起来读源码只会越读越乱。

关于它们流传着三个几乎人人中招的直觉：

1. **「Dubbo 有好几种凭据类型可以选」**——错。`Authenticator` SPI 在 3.3.6 里只有 **2 个**实现：`basic` 与 `accesskey`，一个不多。而**默认的那个恰恰是最不安全的**：`DEFAULT_AUTHENTICATOR = "basic"`（`Constants.java:29`），basic 做的事情只是 `Base64(user:pass)`，**Base64 是编码不是加密**，等同于把密码明文写在请求头里。
2. **「`dubbo-security` 是 Dubbo 的认证框架，`BasicAuthenticator` 就在它里面」**——全错。`dubbo-security` 里只有 `cert/` 一个子包，干的是**向 CA 申请证书并托管**的活；`BasicAuthenticator` 在 `dubbo-auth` 里。而 `dubbo-spring-security` 更特殊：它**把客户端传来的 `SecurityContextHolder` 反序列化后直接塞回 Provider 端，本身不做任何校验**——它是上下文透传，不是认证。
3. **「认证失败抛 `UNAUTHORIZED`」**——错。`RpcException` 的常量表里只有 `AUTHORIZATION_EXCEPTION = 13`（`RpcException.java:43`）和 `FORBIDDEN_EXCEPTION = 4`（:34），**整棵源码树里不存在 `UNAUTHORIZED` 这个 RpcException 码**（唯一带这个词的 `HttpStatus.UNAUTHORIZED(401)` 是 HTTP 状态码，不是错误码）。更麻烦的是**同一个 token 机制在两条链路上的 code 都不一样**，按错误码做监控告警会踩空。

本文版本基线：Apache Dubbo **3.3.6**，所有结论均逐文件核对自源码 tag `dubbo-3.3.6`。Filter 链的组装机制见 [Filter](/docs/CS/Framework/Dubbo/Filter.md)，attachment 的透传路径见 [Invocation](/docs/CS/Framework/Dubbo/Invocation.md?id=three-transparent-paths-of-attachment)。

## Authentication Switch and Configuration Items

### Configuration Fields Inlined in Two Config Classes

Dubbo 没有 `AuthenticationConfig`、`AccessKeyConfig`、`CredentialConfig` 这类东西。认证字段**直接内联在已有的配置基类上**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/AbstractInterfaceConfig.java:204
/**
 * Enable service authentication.
 */
private Boolean auth;            // :207

/**
 * Authenticator for authentication
 */
private String authenticator;    // :212

/**
 * Username for basic authenticator
 */
private String username;         // :217

/**
 * Password for basic authenticator
 */
private String password;         // :222
```

`token` 不在这个类里，它在服务配置基类上（`AbstractServiceConfig.java:85-88`，注释 "Whether to use a token for authentication"）。

两者的粒度差异值得注意：`auth` / `authenticator` / `username` / `password` 定义在 `AbstractInterfaceConfig`，意味着**接口级和服务级都能配**；而 `token` 在 `AbstractServiceConfig` 上，**只有服务侧能配**——Consumer 侧没有「把 token 配在自己身上」的地方，token 是 Provider 单方面声明的期望值。这些字段全部通过 URL 参数读取，键就是字段名本身，没有 `dubbo.auth.` 这样的前缀。

### auth Switch Is Disabled by Default

`auth` 的默认值不是 `true` 也不是 `null` 语义上的「未配置」，而是被三个 Filter 各自显式读成 `false`：

```java
// dubbo-plugin/dubbo-auth/src/main/java/org/apache/dubbo/auth/filter/ProviderAuthFilter.java:43
boolean shouldAuth = url.getParameter(Constants.AUTH_KEY, false);
```

这行代码在 `ConsumerSignFilter.java:47` 与 `ProviderAuthHeaderFilter.java:42` 里各出现一次，**三处都是硬编码 `false`**。只配 `authenticator=accesskey` 而不配 `auth=true`，整套签名与验签逻辑一行都不会执行，且没有任何警告。

> [!WARNING]
> 认证是**双边显式开启**的：Consumer 不开 `auth` 就不会签名，Provider 不开 `auth` 就不会验签。两边不同步配置的结果是「看起来配了认证，实际上完全敞开」，且不报错。生产环境排查「为什么没拦住」时，第一件事是确认两侧 URL 上都真的带了 `auth=true`。

## Token Mechanism

### TokenFilter Full Text

`TokenFilter` 在 `dubbo-rpc-api` 里，不在 `dubbo-auth`——这一点和 auth 系的 Filter 完全不同，替换时要注意它属于核心 API 模块：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/TokenFilter.java:38
@Activate(group = CommonConstants.PROVIDER, value = TOKEN_KEY)
public class TokenFilter implements Filter {

    @Override
    public Result invoke(Invoker<?> invoker, Invocation inv) throws RpcException {
        String token = invoker.getUrl().getParameter(TOKEN_KEY);
        if (ConfigUtils.isNotEmpty(token)) {
            Class<?> serviceType = invoker.getInterface();
            String remoteToken = (String) inv.getObjectAttachmentWithoutConvert(TOKEN_KEY);
            if (!token.equals(remoteToken)) {
                throw new RpcException("Invalid token! Forbid invoke remote service " + serviceType + " method "
                        + RpcUtils.getMethodName(inv) + "() from consumer "
                        + RpcContext.getServiceContext().getRemoteHost() + " to provider "
                        + RpcContext.getServiceContext().getLocalHost()
                        + ", consumer incorrect token is " + remoteToken);
            }
        }
        return invoker.invoke(inv);
    }
}
```

token 的键是 `Constants.TOKEN_KEY = "token"`（`dubbo-rpc-api/.../rpc/Constants.java:75`）。逻辑只有五行，下面四点必须逐条钉住。

### Four Must-Know Points

**① token 只在 Provider URL 上配置，没配就整体跳过。** `ConfigUtils.isNotEmpty(token)` 是唯一的开关判断（:44）。Provider 没配 `token`，整个校验块连同 `equals` 比较一起消失——这是**默认不设防**的经典形态，配置漏了不会有任何提示。

**② token 从 Invocation 的 object attachment 取，不从 `RpcContext` 取。** 读的是 `getObjectAttachmentWithoutConvert`（:46），绕过了类型转换，因此在 Java 侧塞进 attachment 的任何非 String 对象都会在这里触发 `ClassCastException` 而不是认证失败。

这个「不从 `RpcContext` 取」还有个连带效应：`ContextFilter` 的 `UNLOADING_KEYS` 里明确包含了 `TOKEN_KEY`（`ContextFilter.java:82`），invoke 开头会把命中该 TrieTree 的 key 从 attachments 里**剔除**掉再写入 `RpcContext`（:139-149）。所以 `RpcContext.getServerAttachment().getAttachment("token")` 永远是 null，想在业务代码里读 token 只能从 `Invocation` 拿。Consumer 侧传 token 的正规途径是配在 URL 上——`RpcInvocation` 构造时会检查 `url.hasParameter(TOKEN_KEY)` 并自动 `setAttachment`（`RpcInvocation.java:148-150`），不需要业务代码手动塞。

**③ 源码里没有任何 remove 调用。** `TokenFilter` 与它的 HeaderFilter  counterpart 都没有 `removeAttachment` 之类的清理逻辑。token 会随 invocation 对象一路存活到请求结束，异常堆栈或链路追踪里如果 dump 了 attachments，token 会一起被 dump 出来。

**④ 抛的是单参 `RpcException(String)`，不带 code。** 结果就是 code 落到 `UNKNOWN_EXCEPTION = 0`：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/TokenHeaderFilter.java:31
@Activate
public class TokenHeaderFilter implements HeaderFilter {
    @Override
    public RpcInvocation invoke(Invoker<?> invoker, RpcInvocation invocation) throws RpcException {
        String token = invoker.getUrl().getParameter(TOKEN_KEY);
        if (ConfigUtils.isNotEmpty(token)) {
            String remoteToken = (String) invocation.getObjectAttachmentWithoutConvert(TOKEN_KEY);
            if (!token.equals(remoteToken)) {
                throw new RpcException(
                        FORBIDDEN_EXCEPTION,
                        "Forbid invoke remote service " + invoker.getInterface() + " method "
                                + RpcUtils.getMethodName(invocation) + "() from consumer " + ...);
            }
        }
        return invocation;
    }
}
```

> [!WARNING]
> **同一个 token 机制有两条实现，错误码不一致。** 上面的 `TokenHeaderFilter` 是 `rpc.HeaderFilter` SPI 的 `token` 实现（`dubbo-rpc-api` 的 `META-INF/dubbo/internal/org.apache.dubbo.rpc.HeaderFilter`），走 Triple 协议链路，抛 **`FORBIDDEN_EXCEPTION = 4`**；`TokenFilter` 走普通 `rpc.Filter` 链，抛 **`UNKNOWN_EXCEPTION = 0`**。而 auth 机制在 HeaderFilter 链上抛的又是 `AUTHORIZATION_EXCEPTION = 13`（见下文）。**三条链路的认证失败 code 各不相同**，`RpcException.isAuthorization()`（:115）只在 HeaderFilter 链的 auth 失败时为 true。指望用一个错误码统一捕获认证失败是做不到的。

### Granularity Only Down to URL Parameter Level

`TokenFilter` 里没有任何 `getMethodParameter` 调用，也没有方法级判定逻辑。**同一个 Provider 上的所有方法、所有接口共享一个 token**：拿到它就能调该 Provider 上 `token` 覆盖到的所有方法。它防的是「匿名调用」，不是「越权访问」。

## Credential System

### Only Two Kinds of Authenticator

`dubbo-auth` 的 `Authenticator` SPI 注册文件总共两行：

```properties
# dubbo-plugin/dubbo-auth/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.auth.spi.Authenticator
accesskey=org.apache.dubbo.auth.AccessKeyAuthenticator
basic=org.apache.dubbo.auth.BasicAuthenticator
```

接口本身也把默认值写死在注解上（`auth/spi/Authenticator.java:25`）：`@SPI(scope = ExtensionScope.FRAMEWORK, value = "basic")`。两个方法的分工明确：`sign` 只在 Consumer 侧调用（给请求签名），`authenticate` 只在 Provider 侧调用（验签）。`Authenticator` 是 **FRAMEWORK 作用域**（不是 MODULE），实现里可以安全地拿到 `FrameworkModel`。

### basic vs accesskey Comparison

| 维度 | `basic` | `accesskey` |
| :--- | :--- | :--- |
| 实现类 | `BasicAuthenticator` | `AccessKeyAuthenticator` |
| 凭据来源 | Provider URL 上的 `username` / `password` | URL 参数 `.accessKeyId` / `.secretAccessKey`，或自定义 `AccessKeyStorage` |
| 线上传递 | `authorization` attachment：`"Basic " + Base64(user:pass)` | `ak` / `timestamp` / `signature` 三个 attachment |
| 算法 | 无（仅 Base64 编码） | `HmacSHA256` + Base64 |
| 是否防篡改 | **否**，抓包拿到头就能重放 | 是（签名覆盖服务 key + 方法名） |
| 传输保密性 | **无**，Base64 可逆 | 无（AK/SK 本身不下传，但调用元数据是明文） |
| 典型用途 | 内网、低敏感接口、Triple REST 场景 | 敏感接口、需要防重放的场景 |

Basic 的校验逻辑简单到可以完整贴出（`BasicAuthenticator.java:41-52`）：

```java
// dubbo-plugin/dubbo-auth/src/main/java/org/apache/dubbo/auth/BasicAuthenticator.java:41
String auth = username + ":" + password;
String encodedAuth = Base64.getEncoder().encodeToString(auth.getBytes(StandardCharsets.UTF_8));
String authHeaderValue = "Basic " + encodedAuth;

if (!Objects.equals(authHeaderValue, invocation.getAttachment(Constants.AUTHORIZATION_HEADER))
        && !Objects.equals(authHeaderValue, invocation.getAttachment(Constants.AUTHORIZATION_HEADER_LOWER))) {
    throw new RpcAuthenticationException("Failed to authenticate, maybe consumer side did not enable the auth");
}
```

两个细节：写入端用的是小写 key `authorization`（`AUTHORIZATION_HEADER_LOWER`，`Constants.java:51`），读取端却**大小写两个都试**（:49-50），这是为兼容 HTTP 头的大小写不敏感；比较用的是 `Objects.equals` 的字符串比较，**不是常量时间比较**——时序侧信道理论上可区分前缀，但它要求攻击者精确测量单次请求的响应延迟，远程场景下极难利用，生产上更值得担心的还是「basic 根本不提供保密性」这件事。

> [!WARNING]
> **default 是 basic 这件事本身就是个坑。** 官方文档给 basic 的定位是「Triple REST 场景的 HTTP Basic 认证」，但它是 SPI 的**全局默认值**。任何只写了 `auth=true` 而忘了写 `authenticator=...` 的配置，拿到的都是 Base64 明文口令的传输——**在链路上等同于明文 HTTP Basic**。生产上凡是开启 `auth` 的接口，都应该显式写明 `authenticator`，并优先选 `accesskey`，或者干脆用 TLS 通道保护（见后文）。

### How AK/SK Signatures Are Computed

签名串由四段拼成，格式常量是 `"%s#%s#%s#%s"`（`Constants.java:45`）：

```java
// dubbo-plugin/dubbo-auth/src/main/java/org/apache/dubbo/auth/AccessKeyAuthenticator.java:93
String getSignature(URL url, Invocation invocation, String secretKey, String time) {
    String requestString = String.format(
            Constants.SIGNATURE_STRING_FORMAT,
            url.getColonSeparatedKey(),   // 服务唯一标识：group/interface:version
            RpcUtils.getMethodName(invocation),
            secretKey,                    // 注意：secretKey 本身参与拼接
            time);
    return SignatureUtils.sign(requestString, secretKey);
}
```

`SignatureUtils.sign` 用 `HmacSHA256` 计算原始摘要，再做 Base64（`auth/utils/SignatureUtils.java:33`、:63、:81）。四个拼接项里 `secretKey` 既是被签的明文内容又是 HMAC 的密钥——这是标准做法，意味着**只有持有 secretKey 的一方才能算出正确签名**。

`SignatureUtils` 还有一个重载 `sign(Object[] parameters, String metadata, String key)`（:39-58），它会校验参数可序列化、用 `ObjectOutputStream` 拼出字节流再签名，对应配置项 `param.sign`（`PARAMETER_SIGNATURE_ENABLE_KEY`，`Constants.java:47`），用于把**方法参数也纳入签名**防止调用方篡改。默认关闭。

验签流程（`AccessKeyAuthenticator.authenticate`，:52-73）是：读四个 attachment → 任一为空抛 `RpcAuthenticationException` → 取 `AccessKeyPair` → 用**同一个 secretKey** 重算签名 → `equals` 比较。注意这里**没有时间戳窗口校验**——`timestamp` 参与签名但从不被拿来做过期判断，所以**录下来的合法请求可以无限期重放**。

### The Leading Dot in `.accessKeyId` Is Deliberate Design

默认的密钥存储实现简单到近乎直白——直接读 URL 参数塞进 `AccessKeyPair`（`DefaultAccessKeyStorage.java:28-36`）。但两个参数的键是 `.accessKeyId` 和 `.secretAccessKey`，**前面各有一个点**。源码注释把原因写得很直白（`Constants.java:34-37`）：

```java
// the key starting  with "." shouldn't be output
String ACCESS_KEY_ID_KEY = ".accessKeyId";
// the key starting  with "." shouldn't be output
String SECRET_ACCESS_KEY_KEY = ".secretAccessKey";
```

Dubbo 在把 Config 转成 URL、以及把 URL 输出到注册中心/运维命令/监控指标时，会**跳过所有以 `.` 开头的参数**。这个设计让密钥**只参与本进程的认证计算，不出现在任何会被外送或打印的地方**。这是整套 AK/SK 机制里最值得学的一处工程细节。

代价是默认实现**完全依赖 URL 参数**——secretKey 此刻就躺在进程的 URL 对象里。想接外部密钥管理（Vault、KMS、配置中心加密项），必须实现 `AccessKeyStorage` SPI 并通过 `accessKey.storage` 指定扩展名，默认扩展名是 `urlstorage`（`AccessKeyAuthenticator.java:76-78`）。

`AccessKeyPair` 这个 POJO 只有六个字段：`accessKey` / `secretKey` / `consumerSide` / `providerSide` / `creator` / `options`。注意**它没有「凭据类型」字段**——想按应用维度限制某把 AK 能调哪些服务，实现方得自己往 `consumerSide` / `providerSide` 里塞并自行校验，框架不读这两个字段。

## Division of Labor Among Three Filters and the Dual Chain

### Overview Table

`dubbo-auth` 一共注册了四个 SPI 文件，其中三个 Filter 分属两条不同的链：

| 类 | SPI 扩展名 | `@Activate` | order | 失败行为 |
| :--- | :--- | :--- | :--- | :--- |
| `ConsumerSignFilter` | `consumersign` | `group = CONSUMER`, `value = "auth"` | **-10000** | 只签名，不抛异常 |
| `ProviderAuthFilter` | `providerauth` | `group = PROVIDER`, `value = "auth"` | **-10000** | `AsyncRpcResult.newDefaultAsyncResult(e, invocation)`——**转成 Result，不抛 RpcException** |
| `ProviderAuthHeaderFilter` | `auth` | **无 group**（不限）, `value = "auth"` | **-20000** | `throw new RpcException(AUTHORIZATION_EXCEPTION, "No Auth.")` |

三者的 `@Activate` 全部带 `value = Constants.AUTH_KEY`，也就是说**`auth=true` 是它们共同的前置开关**。`ConsumerSignFilter` 最短，只做签名：

```java
// dubbo-plugin/dubbo-auth/src/main/java/org/apache/dubbo/auth/filter/ConsumerSignFilter.java:45
boolean shouldAuth = url.getParameter(Constants.AUTH_KEY, false);
if (shouldAuth) {
    Authenticator authenticator = frameworkModel
            .getExtensionLoader(Authenticator.class)
            .getExtension(url.getParameter(Constants.AUTHENTICATOR_KEY, Constants.DEFAULT_AUTHENTICATOR));
    authenticator.sign(invocation, url);
}
return invoker.invoke(invocation);
```

### Why There Are Two on the Provider Side

这是整套机制里最反直觉的设计：**同一份 auth 校验逻辑在 Provider 侧存在两份实现，走两条链路，谁先跑谁做校验。**

原因是协议差异。`ProviderAuthHeaderFilter` 实现的是 `rpc.HeaderFilter` 接口，而这个接口全树**只有一个调用点**——Triple 协议的 HTTP/2 传输监听器：

```java
// dubbo-rpc/dubbo-rpc-triple/src/main/java/org/apache/dubbo/rpc/protocol/tri/h12/AbstractServerTransportListener.java:285
for (HeaderFilter headerFilter : headerFilters) {
    headerFilter.invoke(invoker, inv);
}
```

Dubbo 协议、gRPC 协议走的是常规 `rpc.Filter` 链，`HeaderFilter` 根本不会被调用。所以：走 Triple / gRPC 的请求由 `ProviderAuthHeaderFilter` 在**构建 RpcInvocation 的那一刻**（还没进业务线程池）校验；走 Dubbo 协议的请求由 `ProviderAuthFilter` 在 Filter 链里校验。两条路径都得有人管，于是就配了两个。

### Deduplication Mechanism: auth.success

`ProviderAuthHeaderFilter` 的 `@Activate` **没有 group 约束**，意味着它在 consumer 侧也会被激活（只是 Consumer 侧 URL 一般没有 `auth=true` 所以直接跳过）。一旦两侧都带了 `auth=true`，`ProviderAuthFilter` 就会在 HeaderFilter 之后**再校验一遍**。去重靠的是 Invocation attributes 上的一个标记：

```java
// dubbo-plugin/dubbo-auth/src/main/java/org/apache/dubbo/auth/filter/ProviderAuthHeaderFilter.java:47
try {
    authenticator.authenticate(invocation, url);
} catch (Exception e) {
    throw new RpcException(AUTHORIZATION_EXCEPTION, "No Auth.");
}
invocation.getAttributes().put(Constants.AUTH_SUCCESS, Boolean.TRUE);   // :52
```

对应的检查在 `ProviderAuthFilter.java:45`：

```java
if (Boolean.TRUE.equals(invocation.getAttributes().get(Constants.AUTH_SUCCESS))) {
    return invoker.invoke(invocation);
}
```

`AUTH_SUCCESS = "auth.success"`（`Constants.java:49`）。注意它是 **`Boolean.TRUE.equals` 的显式比较**而不是 `instanceof`——HeaderFilter 写入的就是 `Boolean.TRUE`，读的时候也只认这个类型。标记走 `invocation.getAttributes()`（内部属性），不占 attachment 空间也不跨网络传输，意味着它是**单次调用内有效**的：Provider 集群里换一个实例处理同一请求时不会残留。

### Failure Semantics Are Completely Different

两个 Provider Filter 对同一类失败的处理方式截然不同，这是排查时最需要先确认的事：

- `ProviderAuthHeaderFilter` **抛异常**：`RpcException(AUTHORIZATION_EXCEPTION, "No Auth.")`。注意 message 是**固定的 `"No Auth."`**（:50），真实的失败原因（AK 错了、签名不匹配、accessKey 读不到）**全被吞掉了**——`catch (Exception e)` 直接丢弃异常对象，连日志都没有。HeaderFilter 在建 invocation 阶段执行，此时还没有请求上下文，源码选择了最保守的失败方式。
- `ProviderAuthFilter` **转成 Result**：`AsyncRpcResult.newDefaultAsyncResult(e, invocation)`（:54），把原始异常（`RpcAuthenticationException` 或其子类）包成失败结果返回，**不抛 RpcException**。好处是异常信息能原样透给 Consumer，代价是**这条链路上 RpcException 的 code 不是 13**——如果监控按 code 分类，Filter 链和 HeaderFilter 链的认证失败会被统计到两个桶里。

两个异常类都是**受检异常**（这在 dubbo-auth 里少见，与框架里清一色的 RuntimeException 风格不同）：`RpcAuthenticationException extends Exception`（`exception/RpcAuthenticationException.java:19`）、`AccessKeyNotFoundException extends Exception`（:24）。而 `AccessKeyAuthenticator` 里 `getAccessKeyPair` 的 catch 块（:87-89）会把 `AccessKeyNotFoundException` 包成 `RuntimeException` 再抛，所以「Provider 侧没配 `.accessKeyId`」最终落到调用方的是一个无 message 的 RuntimeException。

## Responsibility Boundaries of Three security Modules

| 模块 | 真实职责 | 关键类 | 与 `dubbo-auth` 的关系 |
| :--- | :--- | :--- | :--- |
| `dubbo-auth` | 凭据签名与校验 | `AccessKeyAuthenticator`、`BasicAuthenticator`、三个 Filter | —— |
| `dubbo-security` | **证书签发 / 托管（CA）**，做双向 TLS 的证书分发 | `cert/DubboCertManager`、`DubboCertProvider`、`CertDeployerListener` | **无任何共享 SPI** |
| `dubbo-spring-security` | **传播 Spring SecurityContext**（上下文透传，不是认证） | `ContextHolderAuthenticationPrepareFilter`(Consumer)、`ContextHolderAuthenticationResolverFilter`(Provider) | 独立 `ClusterFilter` / `Filter` 扩展名 |
| `dubbo-spring6-security` | Spring 6 变体，**只为 OAuth2 补 Jackson Mixin** | `oauth2/*Mixin`、`OAuth2SecurityModule` | 依赖并复用 `dubbo-spring-security` |

**三者不共享任何 SPI 扩展点。** `dubbo-security` 的三个注册文件分别是 `CertProvider`、`ApplicationDeployListener`、`ScopeModelInitializer`，与 `Authenticator` / `AccessKeyStorage` / `Filter` / `HeaderFilter` 完全没有交集。所以「`BasicAuthenticator` 在 dubbo-security 里」这个说法是彻底错的——它在 `dubbo-plugin/dubbo-auth`，包名 `org.apache.dubbo.auth`。

## Certificate System

`dubbo-security` 只有一个子包 `cert/`，七个类，管的是「向 CA 要一张证书并定期续期」：

```properties
# dubbo-plugin/dubbo-security/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.ssl.CertProvider
dubbo=org.apache.dubbo.security.cert.DubboCertProvider
# .../META-INF/dubbo/internal/org.apache.dubbo.common.deploy.ApplicationDeployListener
cert=org.apache.dubbo.security.cert.CertDeployerListener
# .../META-INF/dubbo/internal/org.apache.dubbo.rpc.model.ScopeModelInitializer
cert=org.apache.dubbo.security.cert.CertScopeModelInitializer
```

`CertProvider` 这个 SPI 有**两个**实现在争：上面 `dubbo-security` 提供的 `dubbo=`，以及 `dubbo-common` 自带的 `ssl-config=`（见下文 TLS 章节）。选择逻辑是 `isSupport(URL)`——`DubboCertProvider.isSupport` 的判据是「`dubboCertManager != null && dubboCertManager.isConnected()`」，即**能否连上 CA**。

连接的触发点在 `CertDeployerListener.onStarting`（:38-50），条件是 `caAddress` 非空：

```java
// dubbo-plugin/dubbo-security/src/main/java/org/apache/dubbo/security/cert/CertDeployerListener.java:38
public void onStarting(ApplicationModel scopeModel) {
    scopeModel.getApplicationConfigManager().getSsl().ifPresent(sslConfig -> {
        if (Objects.nonNull(sslConfig.getCaAddress()) && dubboCertManager != null) {
            CertConfig certConfig = new CertConfig(
                    sslConfig.getCaAddress(), sslConfig.getEnvType(),
                    sslConfig.getCaCertPath(), sslConfig.getOidcTokenPath());
            dubboCertManager.connect(certConfig);
        }
    });
}
```

**`caAddress` 是唯一「配了就会去连外部 CA」的开关。** 停止时在 `onStopping` 里 `dubboCertManager.disConnect()`。

证书刷新间隔是**写死 30 秒**（`security/cert/Constants.java:20` 的 `DEFAULT_REFRESH_INTERVAL = 30_000`）。`CertConfig` 的四参构造器直接取这个默认值，五参构造器可以覆盖——**但 `CertDeployerListener` 用的是四参版本，所以 30s 在标准链路上不可改**，想调整只能自己实现 `CertProvider`。

`SslConfig` 里与 CA 相关的四个字段值得单独记住，因为它们**行为与其他字段不同**：`caAddress` / `envType` / `caCertPath` / `oidcTokenPath`（:125-140）**都没有 `@Parameter` 注解**，而八个证书路径字段全部带 `@Parameter(key = ...)`（:148-211）。缺少 `@Parameter` 意味着**这四个字段不会被同步进 URL**——URL 会进注册中心、进监控、进日志，CA 地址和 OIDC Token 恰恰是最不该出现在那里的东西。这和 `.accessKeyId` 用前导点是同一种思路。

## TLS and mTLS

### The Class Name Is SslContexts, Not SslContextFactory

TLS 的代码分在两个包里：SPI 与配置在 `org.apache.dubbo.common.ssl`，Netty 构建在 `org.apache.dubbo.remoting.transport.netty4.ssl`。核心类叫 **`SslContexts`**（复数），不存在 `SslContextFactory` 这个类。服务端 context 的构建：

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/ssl/SslContexts.java:68
if (serverTrustCertStream != null) {
    sslClientContextBuilder.trustManager(serverTrustCertStream);
    if (providerConnectionConfig.getAuthPolicy() == AuthPolicy.CLIENT_AUTH) {
        sslClientContextBuilder.clientAuth(ClientAuth.REQUIRE);
    } else {
        sslClientContextBuilder.clientAuth(ClientAuth.OPTIONAL);
    }
}
```

**`clientAuth` 完全由 `AuthPolicy` 决定**，而 `AuthPolicy` 只有三个值（`common/ssl/AuthPolicy.java:19-23`）：`NONE` / `SERVER_AUTH` / `CLIENT_AUTH`。TLS provider 的选择是「优先 OpenSSL，回退 JDK」（:144-156），两者都不可用时抛 `IllegalStateException`。Server 端的 ALPN 固定协商 `HTTP_2` + `HTTP_1_1`（:87-92），cipher 套件用 `Http2SecurityUtil.CIPHERS`（:86）——这两个值对 Dubbo 协议也是同一套，因为它们服务于 Triple/gRPC 的 HTTP/2 承载。

### mTLS Is Supported, but AuthPolicy Is Hardcoded

**Dubbo 3.3.6 明确支持 mTLS**，没有任何「不支持」的限制。问题出在唯一一个基于本地文件配置证书的 `CertProvider` 上：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/ssl/impl/SSLConfigCertProvider.java:33
@Activate(order = Integer.MAX_VALUE - 10000)
public class SSLConfigCertProvider implements CertProvider {
    // :46-62 getProviderConnectionConfig(URL) 的实际逻辑
    return localAddress.getOrDefaultApplicationModel()
            .getApplicationConfigManager().getSsl()
            .filter(sslConfig -> Objects.nonNull(sslConfig.getServerKeyCertChainPath()))   // :51
            .filter(sslConfig -> Objects.nonNull(sslConfig.getServerPrivateKeyPath()))     // :52
            .map(sslConfig -> new ProviderCert(
                    IOUtils.toByteArray(sslConfig.getServerKeyCertChainPathStream()),
                    IOUtils.toByteArray(sslConfig.getServerPrivateKeyPathStream()),
                    sslConfig.getServerTrustCertCollectionPath() != null
                            ? IOUtils.toByteArray(sslConfig.getServerTrustCertCollectionPathStream())
                            : null,
                    sslConfig.getServerKeyPassword(),
                    AuthPolicy.CLIENT_AUTH));                                              // :62
    // IOException 时打 warn 日志并 return null（:63-70），无异常上抛
}
```

两个反直觉的事实：

1. **`AuthPolicy.CLIENT_AUTH` 是硬编码的**（:62，**没有开关**）。只要证书文件加载成功就一律 `CLIENT_AUTH`；只有 `serverTrustCertStream == null` 时，`SslContexts.java:73` 才降级成 `ClientAuth.OPTIONAL`。所以「配了 trust 证书就是强制双向认证」成立，但也意味着**不能通过配置把这个 `CertProvider` 降级回单向 TLS**——只能不配 trust 证书。
2. **只配 trust 证书、不配 `serverKeyCertChainPath`，会静默不启用 TLS**。`.filter(sslConfig -> Objects.nonNull(sslConfig.getServerKeyCertChainPath()))`（:51）在 `map` 之前，返回 `null` 而**不抛任何异常**。直觉是「配了双向认证的 trust 路径就已启用 mTLS」，实际结果是整个 `CertProvider` 被跳过、连接退回明文，日志里什么都没有。

> [!WARNING]
> 这个静默失效是 TLS 部分最值得单独记住的坑：**TLS 的启用条件是「`serverKeyCertChainPath` + `serverPrivateKeyPath` 两个都非 null」，而不是「你配了证书相关的任意一项」**。`SslConfig` 的八个路径字段之间**没有互斥校验、没有启动期断言、没有告警日志**。而 `@Activate(order = Integer.MAX_VALUE - 10000)` 是全树最低优先级，意味着别的 `CertProvider`（比如 `dubbo-security` 的 `dubbo=`）有机会先被选中，两者都支持时最终用哪个取决于扩展加载顺序。

Dubbo 侧配 TLS 还需要协议层显式打开 `sslEnabled`（`ProtocolConfig.setSslEnabled(true)`），官方 TLS 文档有完整示例；`SslConfig` 的八个路径常量定义在 :36-50（`server-key-cert-chain-path` 等），字段在 :55-140。

## Spring Security Context Propagation and Security Boundary

### Propagation Chain

`dubbo-spring-security` 干的事分两侧，SPI 注册在 `ClusterFilter` 与 `Filter` 两个文件里：

```properties
# dubbo-plugin/dubbo-spring-security/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.filter.ClusterFilter
authenticationPrepare=org.apache.dubbo.spring.security.filter.ContextHolderAuthenticationPrepareFilter
contextHolderParametersSelectedTransfer=org.apache.dubbo.spring.security.filter.ContextHolderParametersSelectedTransferFilter
# .../META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter
authenticationResolver=org.apache.dubbo.spring.security.filter.ContextHolderAuthenticationResolverFilter
authenticationExceptionTranslator=org.apache.dubbo.spring.security.filter.AuthenticationExceptionTranslatorFilter
```

Consumer 侧（`ClusterFilter`，在负载均衡**之前**执行，所以只会被调用一次，与实例数无关）把 `SecurityContextHolder` 里的 `Authentication` 序列化后塞进 attachment（`ContextHolderAuthenticationPrepareFilter.java:71-83`），键是 `security_authentication_context`（`SecurityNames`），用的是 `setObjectAttachment`——**所以在 Provider 侧读它必须用 `getObjectAttachment` 系列，用 `getAttachment` 拿不到**。Provider 侧（`Filter`，`order = -10000`）反序列化后塞回 `SecurityContextHolder`（`ContextHolderAuthenticationResolverFilter.java:67-74`）：

```java
Authentication authentication = mapper.deserialize(authenticationJSON, Authentication.class);
if (authentication == null) {
    return;
}
SecurityContextHolder.getContext().setAuthentication(authentication);
```

两个 Filter 的 `@Activate` 都带 `onClass` 类探测（Consumer 侧 :43-52、Provider 侧 :40-51），要求这五个类**同时存在**才激活：`SecurityContextHolder`、`CoreJackson2Module`、`ObjectMapper`、`JavaTimeModule`、`SimpleModule`（类名以字符串常量形式定义在 `SecurityNames`）。

> [!NOTE]
> **`onClass` 探测失败时 Filter 静默不激活，没有任何日志。** 这类「类在就不生效」的开关是排查「为什么 SecurityContext 没传过去」时的第一检查点。

### Security Boundary: It Trusts the Client and Does No Validation

> [!WARNING]
> `dubbo-spring-security` 的方向是「**Consumer 说我是谁，Provider 就信我是谁**」。Consumer 侧无条件把本地 `SecurityContextHolder` 的 `Authentication` 序列化发出去，Provider 侧反序列化后**直接 `setAuthentication`，中间没有任何签名、没有任何校验、没有任何比对**。这意味着：
>
> - 任何能连到 Provider 端口的客户端，**都可以自己构造一段 JSON 声称自己是任意用户/任意角色**，Provider 侧的业务代码会看到伪造的身份。
> - 它**必须**与真正的认证机制（`auth=true` + AK/SK，或 mTLS）配合使用——传输层必须先确认对端身份，上下文透传才有意义。单独使用等于**把授权决策交给了客户端**。
> - 正确用法是「让已有的 Spring Security 认证结果跨进程可用」，认证本身仍应由网关 / `dubbo-auth` / mTLS 承担。

### Exception Translation and spring6 Variant

Provider 侧的 `AuthenticationExceptionTranslatorFilter`（`order = Integer.MAX_VALUE`，排最后）把 Spring Security 异常翻译成 Dubbo 错误码：`onResponse` 里若结果异常是 `AuthenticationException` 或 `AccessDeniedException`，就包一个 `RpcException` 并 `setCode(AUTHORIZATION_EXCEPTION)`。这是**第三条**能产生 code 13 的路径。它的 `onError` 是空实现，说明翻译只覆盖「正常返回但结果里带异常」这一种情况。

`dubbo-spring6-security` 单独成模块的唯一原因是**反序列化兼容性**：Spring Security 6 的 OAuth2 类型（`RegisteredClient`、`OAuth2AuthorizationGrantType`、`ClientSettings` 等）无法用 5.x 的 `ObjectMapper` 正确还原，需要 Mixin 补齐。它的 `pom.xml` 清晰地展示了这个意图——引入 spring 6 全家桶（:37-40）的同时**排除** `dubbo-spring-security` 自带的 `spring-security-core`，再引入 security 6（:88-100）：

```xml
<!-- dubbo-plugin/dubbo-spring6-security/pom.xml:88 -->
<dependency>
  <groupId>org.apache.dubbo</groupId>
  <artifactId>dubbo-spring-security</artifactId>
  <exclusions>
    <exclusion>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
    </exclusion>
  </exclusions>
</dependency>
```

其 SPI 只有一个扩展点：`org.apache.dubbo.spring.security.jackson.ObjectMapperCodecCustomer` → `oauth2Customer=OAuth2ObjectMapperCodecCustomer`，把那一堆 `*Mixin` 注册进 `ObjectMapper`。

## Ecosystem Quick Reference

与安全无关但常被一并打听的插件，清单级结论：

| 模块 | 关键类 / SPI 扩展名 |
| :--- | :--- |
| `dubbo-filter-cache` | `Filter` → `cache=CacheFilter`；`CacheFactory` → `threadlocal` / `lru` / `jcache` / `expiring` / `lfu` 共 5 个 |
| `dubbo-filter-validation` | `Filter` → `validation=ValidationFilter`；`Validation` → `jvalidation` / `jvalidationNew` / `jvalidation-javax` / `jvalidation-jakarta` |
| `dubbo-reactive` | 入口 `reactive/calls/ReactorClientCalls`、`ReactorServerCalls` + `AbstractTripleReactorPublisher/Subscriber`。**无 `ReactiveInvoker` 类** |
| `dubbo-mutiny` | 入口 `mutiny/calls/MutinyClientCalls`、`MutinyServerCalls`。**无 `MutinyInvoker` 类** |
| `dubbo-native` | GraalVM AOT：`aot/api/*Describer`、`aot/generate/AotProcessor`、`NativeClassSourceWriter`、`ReflectConfigWriter` / `ProxyConfigWriter` / `ResourceConfigWriter` |
| `dubbo-compatible` | `com.alibaba.dubbo.*` 旧包名桥接层；README:5「From 2.7.x, Dubbo has renamed package to org.apache.dubbo」；README:26 自陈「we will remove this module some day」；**无生产 SPI**（仅 test 资源） |
| `dubbo-configcenter-nacos` | `DynamicConfigurationFactory` → `nacos=NacosDynamicConfigurationFactory` |
| `dubbo-configcenter-apollo` | → `apollo=ApolloDynamicConfigurationFactory` |
| `dubbo-configcenter-file` | → `file=FileSystemDynamicConfigurationFactory` |
| `dubbo-configcenter-zookeeper` | → `zookeeper=ZookeeperDynamicConfigurationFactory` |

配置中心的启动链路与优先级规则见 [config](/docs/CS/Framework/Dubbo/config.md?id=startup-chain-of-the-configuration-center)。

## Default Value Summary Table

| 项目 | 默认值 | 源码位置 |
| :--- | :--- | :--- |
| `Authenticator` 扩展名 | `basic` | `auth/Constants.java:29` + `auth/spi/Authenticator.java:25` |
| `Authenticator` 实现总数 | 2 个（`basic` / `accesskey`） | `META-INF/dubbo/internal/org.apache.dubbo.auth.spi.Authenticator` |
| basic 编码方式 | `Base64(user:pass)`，无加密 | `BasicAuthenticator.java:32-38` |
| `AccessKeyStorage` 扩展名 | `urlstorage` | `auth/Constants.java:31` |
| AK/SK URL 键 | `.accessKeyId` / `.secretAccessKey`（**带前导点**） | `auth/Constants.java:35`、:37 |
| 签名字符串格式 | `"%s#%s#%s#%s"` | `auth/Constants.java:45` |
| 签名算法 | `HmacSHA256` + Base64 | `auth/utils/SignatureUtils.java:33`、:63、:81 |
| 参数签名开关 | `param.sign`，默认不启用 | `auth/Constants.java:47` |
| 时间戳有效期校验 | **无**（`timestamp` 只参与签名） | `AccessKeyAuthenticator.java:52-73` |
| `auth` 开关 | `false`（三处硬编码） | `ProviderAuthFilter.java:43` 等 |
| 去重标记 | `auth.success`（`Boolean.TRUE`，Invocation attributes） | `auth/Constants.java:49` |
| `ConsumerSignFilter` order | -10000 | `ConsumerSignFilter.java:36` |
| `ProviderAuthFilter` order | -10000 | `ProviderAuthFilter.java:32` |
| `ProviderAuthHeaderFilter` order | -20000，**无 group 约束** | `ProviderAuthHeaderFilter.java:31` |
| `TokenFilter` 异常 code | `UNKNOWN_EXCEPTION = 0`（单参构造） | `TokenFilter.java:48` |
| `TokenHeaderFilter` 异常 code | `FORBIDDEN_EXCEPTION = 4` | `TokenHeaderFilter.java:41` |
| auth HeaderFilter 异常 code | `AUTHORIZATION_EXCEPTION = 13` | `ProviderAuthHeaderFilter.java:50` |
| auth Filter 链失败方式 | 转成 `Result`，不抛 `RpcException` | `ProviderAuthFilter.java:54` |
| auth HeaderFilter 失败 message | 固定 `"No Auth."`（真实原因被吞） | `ProviderAuthHeaderFilter.java:50` |
| token 键 | `"token"` | `rpc/Constants.java:75` |
| token 读取位置 | Invocation object attachment，**不从 `RpcContext` 取** | `TokenFilter.java:46` |
| token 粒度 | URL 参数级（接口/方法级统一） | `TokenFilter.java` 无方法参数判定 |
| `AuthPolicy` 取值 | `NONE` / `SERVER_AUTH` / `CLIENT_AUTH`（3 个） | `common/ssl/AuthPolicy.java:19-23` |
| `SSLConfigCertProvider` 的 AuthPolicy | **硬编码 `CLIENT_AUTH`**，无开关 | `ssl/impl/SSLConfigCertProvider.java:62` |
| `SSLConfigCertProvider` order | `Integer.MAX_VALUE - 10000`（最低优先级） | `SSLConfigCertProvider.java:33` |
| TLS 启用条件 | `serverKeyCertChainPath` 与 `serverPrivateKeyPath` **都非 null** | `SSLConfigCertProvider.java:51-52` |
| trust 为 null 时的 clientAuth | `OPTIONAL` | `SslContexts.java:73` |
| Server ALPN | `HTTP_2` + `HTTP_1_1` | `SslContexts.java:87-92` |
| TLS provider 选择 | 优先 OpenSSL，回退 JDK | `SslContexts.java:144-156` |
| 证书刷新间隔 | 30000 ms（标准链路不可改） | `security/cert/Constants.java:20` |
| CA 连接触发条件 | `caAddress` 非空 | `CertDeployerListener.java:40` |
| `SslConfig` 中不同步到 URL 的字段 | `caAddress` / `envType` / `caCertPath` / `oidcTokenPath` | `SslConfig.java:125-140`（无 `@Parameter`） |
| `ContextHolderAuthenticationPrepareFilter` | `group = CONSUMER`, `order = -10000`，**类探测才激活** | `ContextHolderAuthenticationPrepareFilter.java:43-52` |
| `AuthenticationExceptionTranslatorFilter` order | `Integer.MAX_VALUE` | `AuthenticationExceptionTranslatorFilter.java:39` |
| SecurityContext attachment 键 | `security_authentication_context`（**object attachment**） | `spring/security/utils/SecurityNames` |

## Pitfall List

1. **凭据只有 2 种，不是 3 种**：SPI 里只有 `basic` 与 `accesskey`，`Authenticator.java:25` 的 `@SPI(value = "basic")` 是唯一的默认值来源。
2. **默认的 basic 不是加密**：`Base64(user:pass)` 可逆，等同明文传输；且**读取端用的是非常量时间比较**。生产上开 `auth` 必须显式写 `authenticator`。
3. **`dubbo-security` 是证书 CA，不是认证框架**：里面只有 `cert/` 一个子包；`BasicAuthenticator` 在 `dubbo-auth`。三者与 `dubbo-auth` **不共享任何 SPI**。
4. **`dubbo-spring-security` 信任客户端上下文**：Provider 侧反序列化后直接 `setAuthentication`，零校验。单独使用等于把授权决策交给客户端。
5. **没有 `UNAUTHORIZED` 这个 RpcException 码**：只有 `AUTHORIZATION_EXCEPTION = 13` 与 `FORBIDDEN_EXCEPTION = 4`；`HttpStatus.UNAUTHORIZED(401)` 是 HTTP 状态码，不是错误码。
6. **认证失败的 code 有四个来源**：`TokenFilter` → 0、`TokenHeaderFilter` → 4、`ProviderAuthHeaderFilter` / `AuthenticationExceptionTranslatorFilter` → 13，而 `ProviderAuthFilter` 干脆不抛 `RpcException`。按单一 code 做统一告警必然漏。
7. **`auth` 默认 `false` 且三处硬编码**：只配 `authenticator` 不配 `auth=true`，整套逻辑一行不跑，无任何警告。
8. **认证是双边开关**：Consumer 不开不签名、Provider 不开不验签，两边不同步就是「配了等于没配」。
9. **Provider 侧两个 Filter 不是重复代码**：`HeaderFilter` 链只被 Triple 的 `AbstractServerTransportListener.java:285-286` 调用，Dubbo 协议走 `rpc.Filter` 链，两条路径都要有人校验。
10. **去重靠 `auth.success` 这个 attributes 标记**：`ProviderAuthHeaderFilter.java:52` 写、`ProviderAuthFilter.java:45` 读；只认 `Boolean.TRUE`，且仅在同一次调用内有效。
11. **HeaderFilter 的失败原因被吞掉**：`catch (Exception e)` 丢弃异常，只抛固定 message `"No Auth."`，排查时拿不到任何线索。
12. **token 不配就完全不设防**：`ConfigUtils.isNotEmpty(token)` 是唯一开关（`TokenFilter.java:44`），漏配无提示。
13. **token 不从 `RpcContext` 取**：`ContextFilter` 的 `UNLOADING_KEYS` 含 `TOKEN_KEY`（:82），会把 token 从 attachments 剔除，业务代码从 `RpcContext` 读永远是 null。
14. **token 不会被消费方清除**：`TokenFilter` / `TokenHeaderFilter` 里都没有 remove 调用，dump invocation 时 token 会一起泄露。
15. **AK/SK 没有时间窗**：`timestamp` 只参与签名、从不用于判断过期，录制的合法请求可无限期重放。
16. **`.accessKeyId` 的前导点是安全设计不是笔误**：以 `.` 开头的参数不输出到 URL，密钥因此不会进注册中心/监控/日志；代价是默认实现只能从 URL 取密钥，接外部密钥管理必须自定义 `AccessKeyStorage`。
17. **TLS 静默不启用**：只配 `serverTrustCertCollectionPath` 而没配 `serverKeyCertChainPath` 时，`SSLConfigCertProvider.java:51-52` 的两个 `filter` 直接返回 `null`，不抛异常、不打日志，连接退回明文。
18. **mTLS 的 `AuthPolicy.CLIENT_AUTH` 是硬编码的**（`SSLConfigCertProvider.java:62`）：一旦证书加载成功就是强制双向认证，没有降级开关。
19. **`SSLConfigCertProvider` 优先级最低**（`order = Integer.MAX_VALUE - 10000`）：与 `dubbo-security` 的 `dubbo=` 同时可用时，最终选中哪个取决于扩展加载顺序。
20. **`caAddress` 等四个字段不写进 URL**：`caAddress` / `envType` / `caCertPath` / `oidcTokenPath` 无 `@Parameter`，且只有 `caAddress` 非空才会触发 `dubboCertManager.connect()`。
21. **证书刷新 30s 写死**：`CertDeployerListener` 用的是 `CertConfig` 四参构造器，走 `DEFAULT_REFRESH_INTERVAL = 30_000`，要改必须自己实现 `CertProvider`。
22. **TLS 类名是 `SslContexts` 不是 `SslContextFactory`**：包也分两处——SPI/配置在 `org.apache.dubbo.common.ssl`，Netty 构建在 `org.apache.dubbo.remoting.transport.netty4.ssl`。
23. **spring-security 的 Filter 是类探测激活**：`onClass` 要求 5 个类同时存在（`SecurityNames` 里全是字符串常量），探测失败静默不激活且无日志。
24. **SecurityContext 走 object attachment**：键是 `security_authentication_context`，必须用 `getObjectAttachment` 读；用 `getAttachment` 拿不到。
25. **`AuthenticationExceptionTranslatorFilter` 只覆盖一种情况**：`onError` 是空实现，只在「正常返回但结果带异常」时翻译 code。
26. **不存在 `AuthenticationConfig` / `AccessKeyConfig` / `CredentialConfig`**：认证字段内联在 `AbstractInterfaceConfig`（:207/212/217/222）与 `AbstractServiceConfig`（:88）；也不存在 `dubbo.registry.client` 这个配置常量。
27. **`token` 只有服务侧能配**：它在 `AbstractServiceConfig` 上，Consumer 侧没有配置位；`auth` 系列在 `AbstractInterfaceConfig` 上，接口级服务级都能配。
28. **`dubbo-compatible` 迟早会被删**：README 自陈「we will remove this module some day」，且**无生产 SPI**（只有 test 资源），新代码不要基于 `com.alibaba.dubbo.*` 写扩展。
29. **没有 `ReactiveInvoker` / `MutinyInvoker` 这两个类**：响应式入口是 `calls/*ClientCalls` / `*ServerCalls` 系列，按这两个名字搜源码会一无所获。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [Invocation](/docs/CS/Framework/Dubbo/Invocation.md)
- [Triple](/docs/CS/Framework/Dubbo/Triple.md)
- [config](/docs/CS/Framework/Dubbo/config.md)
- [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)

## References

1. [Apache Dubbo 3.3.6 源码（tag dubbo-3.3.6）](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
2. [Dubbo 服务鉴权官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/tasks/security/auth/)
3. [Dubbo TLS 支持官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mmanual/java-sdk/tasks/security/tls/)
4. [dubbo-plugin/dubbo-auth 源码](https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-plugin/dubbo-auth)
5. [dubbo-plugin/dubbo-security 源码](https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-plugin/dubbo-security)
6. [Triple REST Manual（含 Basic 认证配置示例）](https://cn.dubbo.apache.org/en/docs3-v2/java-sdk/reference-manual/protocol/tripe-rest-manual/)
