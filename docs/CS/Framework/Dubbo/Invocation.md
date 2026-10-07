## Introduction

Dubbo 的一次调用，表面看就是「代理对象方法进、结果出」，背后却叠了四层语义：调用模式（同步 / 异步 / 单向）、上下文传递（attachment）、泛化调用、以及线程切换。这几层里散落着大量「看起来像但其实是另一回事」的说法，先破除三个最常见的：

- **`sent=true` 不是「不等待响应返回」。** 它是 remoting 层 `send(message, boolean sent)` 的参数，语义是**发送时是否阻塞等待写入完成**；真正「不等响应就返回」的是单向调用，由 `return=false` 推导而来，源码里**没有 `oneway` 这个配置 key**。
- **`AsyncRpcResult` 上不存在 `getCompletableFuture()` 方法。** 它只有 `getResponseFuture(): CompletableFuture<AppResponse>`。`getCompletableFuture()` 出现在 `RpcContext` / `RpcServiceContext` / `FutureContext` 上。
- **Provider 用 `RpcContext.getServerAttachment().setAttachment()` 写的值不会回传给客户端。** 想回传必须写 `getServerContext()`——这就是 Dubbo 3 把 `RpcContext` 拆成四类语义化 Context 之后最容易踩的坑。

本文基于 Apache Dubbo **3.3.6** 官方源码，所有默认值标注文件与行号。

## Invocation Modes: async / return / sent / timeout

四个参数常量分散在三个模块，这是第一个容易找错的地方：

| 参数 | 字符串值 | 常量位置 |
| :--- | :--- | :--- |
| `async` | `"async"` | `dubbo-rpc-api` 的 `org.apache.dubbo.rpc.Constants:71` |
| `return` | `"return"` | 同上 `:73` |
| `sent` | `"sent"` | `dubbo-remoting-api` 的 `org.apache.dubbo.remoting.Constants:132` |
| `timeout` | `"timeout"` | `dubbo-common` 的 `CommonConstants:145` |
| `oneway` | —— | **不存在** |

`AsyncRpcResult` 与 `RpcInvocation` 之外，判断逻辑集中在 `RpcUtils`：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/support/RpcUtils.java:172-188
public static boolean isAsync(URL url, Invocation inv) {
    boolean isAsync;
    if (inv instanceof RpcInvocation) {
        RpcInvocation rpcInvocation = (RpcInvocation) inv;
        if (rpcInvocation.getInvokeMode() != null) {
            return rpcInvocation.getInvokeMode() == InvokeMode.ASYNC;
        }
    }
    if (Boolean.TRUE.toString().equals(inv.getAttachment(ASYNC_KEY))) {
        isAsync = true;
    } else {
        isAsync = url.getMethodParameter(getMethodName(inv), ASYNC_KEY, false);
    }
    return isAsync;
}
```

异步判定是**三级优先**：`RpcInvocation.invokeMode`（显式设置）> invocation attachment 的 `async` > URL 的 method 级 `async` 参数（默认 `false`）。

单向判定则完全由 `return` 推导：

```java
// RpcUtils.java:232-240
public static boolean isOneway(URL url, Invocation inv) {
    boolean isOneway;
    if (Boolean.FALSE.toString().equals(inv.getAttachment(RETURN_KEY))) {
        isOneway = true;
    } else {
        isOneway = !url.getMethodParameter(getMethodName(inv), RETURN_KEY, true);
    }
    return isOneway;
}
```

注意 URL 参数的默认值是 `true`，即**默认不是 oneway**。想单向调用只有一条路：把 `return` 设为 `false`。

在 Dubbo 协议的调用器里，oneway 的判定**先于** async：

```java
// dubbo-rpc/dubbo-rpc-dubbo/.../protocol/dubbo/DubboInvoker.java:105,128-145（节选）
boolean isOneway = RpcUtils.isOneway(getUrl(), invocation);
...
if (isOneway) {
    boolean isSent = getUrl().getMethodParameter(methodName, Constants.SENT_KEY, false);
    request.setTwoWay(false);
    currentClient.send(request, isSent);
    return AsyncRpcResult.newDefaultAsyncResult(invocation);
} else {
    request.setTwoWay(true);
    ...
}
```

也就是说，`return=false` 时请求干脆不带 twoway 标志、发出即返回一个默认结果，根本不会进入 async 分支。**oneway 优先于 async。**

### The Actual Semantics of `sent`

`sent` 传给了 `currentClient.send(request, isSent)`，最终在 Netty 通道上体现为「是否阻塞等这次写入完成」：

```java
// dubbo-remoting/dubbo-remoting-netty4/.../transport/netty4/NettyChannel.java:224-228
if (sent) {
    // wait timeout ms
    timeout = getUrl().getPositiveParameter(TIMEOUT_KEY, DEFAULT_TIMEOUT);
    success = future.await(timeout);
}
```

`sent=false` 意味着「fire and forget 地写出去，不确认是否写成功」，`sent=true` 会阻塞至多一个 `timeout`。它与「等不等业务响应」完全无关。

> [!WARNING]
> 这里还有一个默认值不一致的细节：运行时读取的默认值是 `false`（`DubboInvoker.java:129` 的 `getMethodParameter(..., SENT_KEY, false)`），但配置层 `MethodConfig.java:322-334` 在构造时会把 `sent` 补成 `true`。两者作用于不同阶段，排查「为什么发了但没报错」时要注意以运行时读取为准。

## Async Return Value

Dubbo 3 推荐的异步写法是**方法签名直接返回 `CompletableFuture`**，框架据此识别：

```java
// RpcUtils.java:190-198
public static boolean isReturnTypeFuture(Invocation inv) {
    Class<?> clazz;
    if (inv instanceof RpcInvocation) { clazz = ((RpcInvocation) inv).getReturnType(); }
    else { clazz = getReturnType(inv); }
    return (clazz != null && CompletableFuture.class.isAssignableFrom(clazz)) || isGenericAsync(inv);
}
```

拿结果的 API 有三个层次：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/AsyncRpcResult.java:161
public CompletableFuture<AppResponse> getResponseFuture() {
    return responseFuture;
}
```

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/RpcContext.java:315-328（节选）
public <T> CompletableFuture<T> getCompletableFuture() {
    return SERVICE_CONTEXT.get().getCompletableFuture();
}
public <T> Future<T> getFuture() {
    return SERVICE_CONTEXT.get().getFuture();
}
```

| 用法 | 位置 | 状态 |
| :--- | :--- | :--- |
| `Result.getResponseFuture()` | `AsyncRpcResult:161` | 推荐，`FutureContext` 的 javadoc 明确 2.7.3 起优先用它 |
| `RpcContext.getServiceContext().getCompletableFuture()` | `RpcContext:315` | 3.x 正式入口 |
| `RpcContext.getContext().getFuture()` | `RpcContext:160,325` | `getContext()` 已 `@Deprecated`，整体不推荐 |

`FutureContext` 的注释把历史交代得很清楚：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/FutureContext.java:108-117（节选）
 * Start from 2.7.3, you don't have to get Future from RpcContext, we recommend using Result directly:
 *      Result result = invoker.invoke(invocation);
 *      result.getResponseFuture().whenComplete(new FinishSpanCallback(span));
```

> [!NOTE]
> `RpcContext.getFuture()` 方法**自身并没有** `@Deprecated` 标注，被废弃的是它的宿主 `getContext()`。网上「`getFuture()` 已废弃」的说法不准确，准确的表述是「`getContext()` 已废弃，因此整条 `RpcContext.getContext().xxx` 链路都不推荐」。

## Four Categories of Context

Dubbo 3 把原来的 `RpcContext` 单例拆成了四类语义化 Context，源码注释就是最好的说明：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/RpcContext.java:37-46
 * There are four kinds of RpcContext, which are ServerContext, ClientAttachment, ServerAttachment and ServiceContext.
 * ClientAttachment is using to pass attachments to next hop as a consumer. ( A --> B , in A side)
 * ServerAttachment is using to fetch attachments from previous hop as a provider. ( A --> B , in B side)
 * ServerContext is using to return some attachments back to client as a provider. ( A <-- B , in B side)
```

| API | 返回类型 | 语义 | 读写 | 方向 |
| :--- | :--- | :--- | :--- | :--- |
| `getServiceContext()` | `RpcServiceContext` | 环境参数（remoteAddress、url、method、future） | 读写 | 贯穿调用 |
| `getClientAttachment()` | `RpcContextAttachment` | 消费者**写给下游**的 attachment | 可写 | A → B（A 侧写） |
| `getServerAttachment()` | `RpcContextAttachment` | Provider **读上游**传进来的 attachment | 主要读 | A → B（B 侧读） |
| `getServerContext()` | `RpcServerContextAttachment` | Provider **回传**给 client 的 attachment | 可写 | A ← B（B 侧写） |
| `getClientResponseContext()` | `RpcContextAttachment` | 消费者读取 Provider 回传 | 读 | A ← B（A 侧读） |

底层存储全部是 Dubbo 自研的 `InternalThreadLocal`（仿 Netty `FastThreadLocal`）：

```java
// dubbo-common/.../common/threadlocal/InternalThreadLocal.java:34
public class InternalThreadLocal<V> extends ThreadLocal<V> {
```

关键在于 **`getServerContext()` 的 `setAttachment` 被重写了**，它并不写进当前的 ThreadLocal，而是转发到 ServerResponseContext：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/RpcServerContextAttachment.java:36-39
@Override
public RpcContextAttachment setObjectAttachment(String key, Object value) {
    RpcContext.getServerResponseContext().setObjectAttachment(key, value);
    return this;
}
```

```java
// RpcServerContextAttachment.java:71-87（节选）
@Override
public Object getObjectAttachment(String key) {
    Object fromServerResponse = RpcContext.getServerResponseContext().getObjectAttachment(key);
    if (fromServerResponse == null) {
        fromServerResponse = RpcContext.getClientResponseContext().getObjectAttachment(key);
    }
    return fromServerResponse;
}
```

而 `getServerAttachment()` 的写入就只是普通 ThreadLocal 赋值，出了 Provider 的线程就没了：

```java
// dubbo-rpc/dubbo-rpc-api/.../rpc/RpcContextAttachment.java:104-122（节选）
@Override
public RpcContextAttachment setObjectAttachment(String key, Object value) {
    if (value == null) { attachments.remove(key); } else { attachments.put(key, value); }
    return this;
}
```

**结论：Provider 想回传数据给 Consumer，必须用 `RpcContext.getServerContext().setAttachment(...)`；用 `getServerAttachment()` 写只会留在本机。**

## Three Transparent Paths of attachment

### Consumer -> Provider

`ConsumerContextFilter` 负责把消费者写的 attachment 打包进 invocation：

```java
// dubbo-cluster/.../filter/support/ConsumerContextFilter.java:63-95（节选）
public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
    RpcContext.getServiceContext().setInvoker(invoker).setInvocation(invocation);
    RpcContext context = RpcContext.getClientAttachment();
    context.setAttachment(REMOTE_APPLICATION_KEY, invoker.getUrl().getApplication());
    ...
    Map<String, Object> contextAttachments =
            RpcContext.getClientAttachment().getObjectAttachments();
    if (CollectionUtils.isNotEmptyMap(contextAttachments)) {
        ((RpcInvocation) invocation).addObjectAttachments(contextAttachments);
    }
```

Provider 侧由 `ContextFilter` 把它读进 `getServerAttachment()`：

```java
// dubbo-rpc/dubbo-rpc-api/.../filter/ContextFilter.java:138-181（节选）
Map<String, Object> attachments = invocation.getObjectAttachments();
...
RpcContext context = RpcContext.getServerAttachment();
...
if (CollectionUtils.isNotEmptyMap(attachments)) {
    if (context.getObjectAttachments().size() > 0) {
        context.getObjectAttachments().putAll(attachments);
    } else {
        context.setObjectAttachments(attachments);
    }
}
```

### Provider -> Consumer (Callback)

只有写进 Response 的那两类 attachment 会随响应回去：

```java
// ContextFilter.java:200-217（节选）
public void onResponse(Result appResponse, Invoker<?> invoker, Invocation invocation) {
    ...
    appResponse.addObjectAttachments(
            RpcContext.getClientResponseContext().getObjectAttachments());
    appResponse.addObjectAttachments(
            RpcContext.getServerResponseContext().getObjectAttachments());
    removeContext();
}
```

消费侧再把它读回来：

```java
// ConsumerContextFilter.java:122-128
public void onResponse(Result appResponse, Invoker<?> invoker, Invocation invocation) {
    Map<String, Object> map = appResponse.getObjectAttachments();
    RpcContext.getClientResponseContext().setObjectAttachments(map);
    removeContext(invocation);
}
```

### Automatic Transparent Passing of Implicit Parameters (A -> B -> C)

当 Provider B 又要作为消费者调用下游 C 时，B 收到的上游 attachment 会自动带进新请求——这就是「隐式参数透传」的源码依据，**实现点在 `ConsumerContextFilter` 而不是 `AbstractClusterInvoker`**：

```java
// ConsumerContextFilter.java:82-84（节选）
} else {
    ((RpcInvocation) invocation)
            .addObjectAttachments(RpcContext.getServerAttachment().getObjectAttachments());
}
```

> [!WARNING]
> `AbstractClusterInvoker.java:348-351` 里确实有一段与 "binding attachments into invocation" 相关的代码，但它**已被注释掉**，不是现行透传路径。任何引用该处解释透传行为的说法都已过时。

## Generic Invocation

泛化调用让消费方在没有服务接口 API 包的情况下发起调用，入口是 `GenericService`：

```java
// dubbo-common/.../rpc/service/GenericService.java:26-48（节选）
public interface GenericService {
    Object $invoke(String method, String[] parameterTypes, Object[] args) throws GenericException;

    default CompletableFuture<Object> $invokeAsync(String method, String[] parameterTypes, Object[] args)
            throws GenericException { ... }
}
```

相关常量：

```java
// dubbo-common/.../constants/CommonConstants.java:246,264,266,268
String GENERIC_KEY = "generic";
String $INVOKE = "$invoke";
String $INVOKE_ASYNC = "$invokeAsync";
String GENERIC_PARAMETER_DESC = "Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/Object;";
```

两个 Filter 分别守两端，注册在 `dubbo-rpc-api` 的 Filter 扩展文件里：

```properties
# dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter
echo=org.apache.dubbo.rpc.filter.EchoFilter
generic=org.apache.dubbo.rpc.filter.GenericFilter
genericimpl=org.apache.dubbo.rpc.filter.GenericImplFilter
token=org.apache.dubbo.rpc.filter.TokenFilter
```

```java
// GenericFilter.java:74（提供方，无 condition 恒激活）
@Activate(group = CommonConstants.PROVIDER, order = -20000)
public class GenericFilter implements Filter, Filter.Listener, ScopeModelAware {

// GenericImplFilter.java:57（消费方，仅 generic 参数存在时激活）
@Activate(group = CommonConstants.CONSUMER, value = GENERIC_KEY, order = 20000)
public class GenericImplFilter implements Filter, Filter.Listener {
```

`generic` 的取值决定泛化序列化方式（`CommonConstants.java:370-380`）：

| 取值 | 含义 |
| :--- | :--- |
| `true` | 默认泛化（Map/Pojo 互转） |
| `nativejava` | Java 原生序列化透传 |
| `gson` | Gson 反序列化成 Map |
| `bean` | 反序列化成 Bean |
| `protobuf-json` | Protobuf JSON 格式 |

**Triple 协议下泛化同样支持**：`TripleInvoker` 对 `$invoke` 有专门分支，泛化请求会被强制走 wrapper 打包：

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/TripleInvoker.java:157-167（节选）
if (methodDescriptor == null) {
    if (RpcUtils.isGenericCall(
            ((RpcInvocation) invocation).getParameterTypesDesc(), invocation.getMethodName())) {
        // Only reach when server generic
        methodDescriptor = ServiceDescriptorInternalCache.genericService()
                .getMethod(invocation.getMethodName(), invocation.getParameterTypes());
    } else if (RpcUtils.isEcho(...)) { ... }
}
```

```java
// dubbo-rpc/dubbo-rpc-triple/.../tri/ReflectionPackableMethod.java:127-132
public static boolean needWrap(MethodDescriptor methodDescriptor, Class<?>[] parameterClasses, Class<?> returnClass) {
    String methodName = methodDescriptor.getMethodName();
    // generic call must be wrapped
    if (CommonConstants.$INVOKE.equals(methodName) || CommonConstants.$INVOKE_ASYNC.equals(methodName)) {
        return true;
    }
```

> [!NOTE]
> 「Triple 不支持泛化调用」的说法在 3.3.6 源码里找不到依据。`TripleInvoker`、`ReflectionPackableMethod` 都对 `$invoke` 有显式支持分支。

## Pitfall List

| 直觉写法 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「`sent=true` 是不等响应」 | `sent` 控制发送是否阻塞等待写入 | 调优方向完全错 |
| 「用 `oneway=true` 配置单向调用」 | 无 `oneway` key，须 `return=false` | 配置不生效 |
| 「`asyncRpcResult.getCompletableFuture()`」 | 只有 `getResponseFuture()` | 编译不过 |
| 「`getServerAttachment().setAttachment()` 能回传」 | 只写本机 ThreadLocal，回传须 `getServerContext()` | 数据静默丢失 |
| 「透传逻辑在 `AbstractClusterInvoker`」 | 该处代码已注释，实际在 `ConsumerContextFilter` | 排查找错文件 |
| 「`RpcContext.getFuture()` 已废弃」 | 废弃的是 `getContext()`，方法本身无 `@Deprecated` | 误改代码 |
| 「Triple 不支持泛化」 | `TripleInvoker` 有 `$invoke` 专门分支 | 误判能力边界 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [Triple](/docs/CS/Framework/Dubbo/Triple.md)
- [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)

## References

1. [Dubbo 异步调用官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/advanced-features-and-usage/service/async-call/)
2. [Dubbo 泛化调用官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/advanced-features-and-usage/service/generic-reference/)
3. [dubbo-rpc-api 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-rpc/dubbo-rpc-api)
